"""Budget Autopilot (feature 6): proposals within campaign guardrails + counterfactual € protected."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.context import Ctx
from app.analytics.metrics import with_rates
from app.sim.simulator import Simulator

HORIZON = 7
SHIFT = 0.4
CAUSE_TEXT = {"creative_fatigue": "creative fatigue", "auction_pressure": "rising auction costs", "landing_page": "a landing-page / funnel drop",
              "segment_saturation": "segment saturation"}


def _set_stats(ctx: Ctx, day: int) -> pd.DataFrame:
    df = ctx.daily(day - 6, day)
    ads = {a["ad_id"]: a for a in ctx.ads()}
    df = df.assign(ad_set_id=df.ad_id.map(lambda a: ads[a]["ad_set_id"]))
    g = df.drop(columns=["ad_id", "community_id"]).groupby("ad_set_id").sum()
    return with_rates(g.reset_index())


def wasted_spend(sim: Simulator, start_day: int) -> float:
    """Spend not justified by conversions at the campaign's max CPA (ad set x day)."""
    df = sim.stats()
    df = df[df.day >= start_day]
    if df.empty:
        return 0.0
    ads = {a.ad_id: a for a in sim.ads}
    df = df.assign(ad_set_id=df.ad_id.map(lambda a: ads[a].ad_set_id))
    g = df.groupby(["ad_set_id", "day"])[["spend", "true_conversions"]].sum().reset_index()
    max_cpa = g.ad_set_id.map(lambda s: sim.campaigns[sim.ad_sets[s]["campaign_id"]]["max_cpa"])
    return float(np.maximum(g.spend - g.true_conversions * max_cpa, 0).sum())


def counterfactual(sim: Simulator, change: dict, days: int = HORIZON, seeds: tuple[int, ...] = (99, 100, 101, 102, 103)) -> dict:
    """Run the next `days` from the current state without and with the change, on paired forks
    (same seed per pair), averaged over several seeds so simulation noise does not decide the answer."""
    start = sim.day
    wb, wa, rb, ra = [], [], [], []

    def rev(s):
        d = s.stats()
        return float(d[d.day >= start].revenue.sum())

    for seed in seeds:
        base = sim.fork(seed)
        base.run(days)
        act = sim.fork(seed)
        apply_change(act, change)
        act.run(days)
        wb.append(wasted_spend(base, start))
        wa.append(wasted_spend(act, start))
        rb.append(rev(base))
        ra.append(rev(act))
    diff = np.array(wb) - np.array(wa)
    return {"wasted_without": round(float(np.mean(wb)), 2), "wasted_with": round(float(np.mean(wa)), 2),
            "eur_protected": round(float(diff.mean()), 2), "eur_protected_sd": round(float(diff.std()), 2),
            "revenue_delta": round(float(np.mean(ra) - np.mean(rb)), 2), "days": days, "runs": len(seeds)}


def apply_change(sim: Simulator, change: dict) -> None:
    if change.get("exclude_community") is not None:
        t = sim.ad_sets[change["from_ad_set"]]["target_communities"]
        sim.ad_sets[change["from_ad_set"]]["target_communities"] = [c for c in t if c != change["exclude_community"]]
        return
    amt = change["amount"]
    sim.ad_sets[change["from_ad_set"]]["daily_budget"] -= amt
    if change.get("to_ad_set"):
        sim.ad_sets[change["to_ad_set"]]["daily_budget"] += amt


def propose(ctx: Ctx, radar_rows: list[dict], diagnoses: dict[str, dict], community_names: dict[int, str] | None = None,
            day: int | None = None) -> list[dict]:
    """One proposal per troubled ad set, chosen by the diagnosed cause:
    fatigue / auction pressure -> move budget to the best sibling ad set (or hold back if none);
    landing page -> hold back budget until fixed; segment saturation -> exclude the saturated community;
    seasonality / tracking / no issue -> no budget action (doing nothing is the right call)."""
    day = ctx.source.current_day() if day is None else day
    names = community_names or {}
    stats = _set_stats(ctx, day).set_index("ad_set_id")
    sim = ctx.sim
    bad: dict[str, dict] = {}
    for r in radar_rows:
        d = diagnoses.get(r["ad_id"])
        if r["status"] in ("failing", "at_risk") and d and d["top"] not in ("seasonality", "tracking", "no_issue"):
            cur = bad.get(r["ad_set_id"])
            if cur is None or (r.get("eur_at_risk") or 0) > cur["risk"]:
                bad[r["ad_set_id"]] = {"risk": r.get("eur_at_risk") or 0, "ad_id": r["ad_id"], "cause": d["top"], "diag": d}
    out = []
    for set_id, info in sorted(bad.items(), key=lambda x: -x[1]["risk"]):
        s = sim.ad_sets[set_id]
        camp = sim.campaigns[s["campaign_id"]]
        cause, risk = info["cause"], info["risk"]
        if cause == "segment_saturation":
            ratios = info["diag"]["raw"]["segment_ratios"]
            if not ratios:
                continue
            c = int(min(ratios, key=ratios.get))
            if c not in s["target_communities"] or len(s["target_communities"]) < 2:
                continue
            change = {"from_ad_set": set_id, "to_ad_set": None, "amount": 0.0, "exclude_community": c}
            reason = (f"{info['ad_id']} is saturated in {names.get(c, f'community {c}')} (CTR {ratios[str(c)] - 1:+.0%}) but still "
                      f"working elsewhere. Exclude that community from {set_id}; keep the ad running for the rest.")
        else:
            amount = round(s["daily_budget"] * SHIFT, 2)
            if amount < 5:
                continue
            siblings = [k for k, v in sim.ad_sets.items() if v["campaign_id"] == s["campaign_id"] and k != set_id and k not in bad and k in stats.index]
            best = min(siblings, key=lambda k: stats.loc[k, "cpa"]) if siblings and cause != "landing_page" else None
            if best is not None and stats.loc[best, "cpa"] <= camp["max_cpa"]:
                change = {"from_ad_set": set_id, "to_ad_set": best, "amount": amount}
                reason = (f"{info['ad_id']} shows {CAUSE_TEXT.get(cause, cause)} (€{risk:.0f} at risk over 7 days). Move €{amount:.0f}/day "
                          f"from {set_id} to {best} (CPA €{stats.loc[best, 'cpa']:.2f}, campaign max €{camp['max_cpa']:.2f}).")
            else:
                change = {"from_ad_set": set_id, "to_ad_set": None, "amount": amount}
                reason = (f"{info['ad_id']} shows {CAUSE_TEXT.get(cause, cause)} and {set_id} has no healthy sibling to take budget. "
                          f"Hold back €{amount:.0f}/day until it is fixed.")
        cf = counterfactual(sim, change)
        if cf["eur_protected"] <= 0:  # the counterfactual says it would not help: do not propose it
            continue
        out.append({**change, "reason": reason, "day": day, "cause": cause, "ad_id": info["ad_id"], **cf})
    return out
