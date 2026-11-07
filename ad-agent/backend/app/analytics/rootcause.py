"""Probabilistic root cause: evidence functions -> hypothesis scores -> softmax.
Weights are hand-set and tuned until every planted scenario is diagnosed correctly."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.context import Ctx
from app.analytics.metrics import rate_z, robust_z, window, with_rates

HYPOTHESES = ["creative_fatigue", "segment_saturation", "auction_pressure", "landing_page", "seasonality", "tracking", "no_issue"]
LABELS = {
    "creative_fatigue": "Creative fatigue", "segment_saturation": "Segment saturation", "auction_pressure": "Auction cost pressure",
    "landing_page": "Landing page / funnel", "seasonality": "Seasonality (market-wide)", "tracking": "Tracking broke", "no_issue": "No real problem",
}
ACTIONS = {
    "creative_fatigue": "refresh_creative", "segment_saturation": "split_by_segment", "auction_pressure": "rebalance_budget",
    "landing_page": "fix_landing_page", "seasonality": "do_nothing", "tracking": "check_tracking", "no_issue": "do_nothing",
}


GAP = 7


def _z(series: pd.Series, day: int) -> float:
    r, b = window(series, day, gap=GAP)
    return robust_z(r, b)


def evidence(ctx: Ctx, ad_id: str, day: int) -> dict:
    allc = ctx.daily(0, day)
    ad_d = with_rates(allc.drop(columns="community_id").groupby(["ad_id", "day"], as_index=False).sum())
    me = ad_d[ad_d.ad_id == ad_id].set_index("day").sort_index()
    meta = ctx.ad(ad_id)
    ev: dict = {}
    ev["z_ctr"] = rate_z(me, "clicks", "impressions", day, gap=GAP)
    ev["z_cvr"] = rate_z(me, "conversions", "clicks", day, gap=GAP)
    ev["z_cpm"] = _z(me["cpm"], day)
    ev["z_roas"] = _z(me["roas"], day)

    # breadth: how many other ads dropped at the same time
    drops_all, drops_camp, n_all, n_camp = 0, 0, 0, 0
    for a in ctx.ads():
        if a["ad_id"] == ad_id:
            continue
        o = ad_d[ad_d.ad_id == a["ad_id"]].set_index("day").sort_index()
        if len(o) < 8:
            continue
        zc, zv = rate_z(o, "clicks", "impressions", day, gap=GAP), rate_z(o, "conversions", "clicks", day, gap=GAP)
        dropped = (zc < -1.5) or (zv < -1.5)
        n_all += 1
        drops_all += dropped
        if a["campaign_id"] == meta["campaign_id"]:
            n_camp += 1
            drops_camp += dropped
    ev["breadth_all"] = drops_all / max(n_all, 1)
    ev["breadth_campaign"] = drops_camp / n_camp if n_camp else 0.0

    # frequency link: CTR falling while frequency rising
    last = me[me.index > day - 14]
    if len(last) >= 6 and last["ctr"].std() > 0 and last["frequency"].std() > 0:
        ev["freq_corr"] = float(np.corrcoef(last["ctr"], last["frequency"])[0, 1])
    else:
        ev["freq_corr"] = 0.0
    ev["frequency"] = float(me["frequency"].iloc[-1]) if len(me) else 0.0
    ctr3 = me["ctr"].rolling(3, min_periods=3).mean()
    ev["ctr_vs_peak"] = float(ctr3.iloc[-1] / ctr3.max()) if ctr3.notna().any() and ctr3.max() > 0 else 1.0
    r, b = window(me["frequency"], day, gap=GAP)
    ev["freq_change"] = float(np.mean(r) - np.mean(b)) if len(r) and len(b) else 0.0

    # segment split: CTR change per community
    mine = allc[allc.ad_id == ad_id]
    ratios = {}
    for c, g in mine.groupby("community_id"):
        g = with_rates(g.set_index("day").sort_index())
        rr, bb = window(g["ctr"], day, gap=GAP)
        if len(rr) and len(bb) and np.mean(bb) > 0 and g["impressions"].tail(3).sum() > 300:
            ratios[int(c)] = float(np.mean(rr) / np.mean(bb))
    ev["segment_ratios"] = ratios
    if len(ratios) >= 2:
        vals = np.array(list(ratios.values()))
        ev["segment_spread"] = float(vals.max() - vals.min())
        ev["segment_min"] = float(vals.min())
        ev["segment_max"] = float(vals.max())
    else:
        ev["segment_spread"], ev["segment_min"], ev["segment_max"] = 0.0, 1.0, 1.0

    # comment sentiment
    r, b = window(me["annoyed_share"], day, recent=5, base=14, gap=GAP)
    ev["annoyed_now"] = float(np.mean(r)) if len(r) else 0.0
    ev["annoyed_change"] = float(np.mean(r) - np.mean(b)) if len(r) and len(b) else 0.0

    # external signal (Trends-style market index)
    mk = ctx.source.get_market_index(day - 30, day)
    s = pd.Series(mk).sort_index()
    r, b = window(s, day, gap=GAP)
    ev["market_change"] = float(np.mean(r) / np.mean(b) - 1) if len(r) and len(b) else 0.0

    # conversions to zero with normal clicks
    rc = me[me.index > day - 2]
    bc = me[(me.index <= day - 2) & (me.index > day - 16)]
    ev["conv_zero"] = bool(len(rc) and rc["conversions"].sum() == 0 and bc["conversions"].mean() > 2 and ev["z_ctr"] > -2.5)
    return ev


def score(ev: dict) -> dict[str, float]:
    d_ctr = np.clip(-ev["z_ctr"], 0, 8) / 2
    d_cvr = np.clip(-ev["z_cvr"], 0, 8) / 2
    up_cpm = np.clip(ev["z_cpm"], 0, 8) / 2
    fcorr = np.clip(-ev["freq_corr"], 0, 1)
    seg = float(np.clip((ev["segment_spread"] - 0.2) / 0.2, 0, 1)) * float(ev["segment_max"] > 0.85 and ev["segment_min"] < 0.8)
    mkt = np.clip(-ev["market_change"] / 0.1, 0, 3)
    broad = float(np.clip((ev["breadth_all"] - 0.4) / 0.5, 0, 1))
    camp = ev["breadth_campaign"]
    camp_hi = float(np.clip((camp - 0.5) * 2, 0, 1))
    peak_drop = float(np.clip((0.8 - ev["ctr_vs_peak"]) / 0.3, 0, 1.5))
    s = {
        "creative_fatigue": 0.7 * d_ctr + 1.8 * peak_drop + 1.2 * fcorr + 4 * max(ev["annoyed_change"], 0)
                            - 3.0 * broad - 2.5 * seg - 1.5 * mkt - 0.4 * d_cvr - 0.4 * up_cpm - 1.2 * camp_hi,
        "segment_saturation": 0.6 * d_ctr + 3.2 * seg + 0.6 * fcorr - 2.0 * broad - 1.5 * mkt,
        "auction_pressure": 1.4 * up_cpm + 0.6 * camp - 0.5 * d_ctr - 0.5 * d_cvr - 1.0 * mkt,
        "landing_page": 1.5 * d_cvr + 1.2 * camp_hi - 0.3 * d_ctr - 2.0 * broad - 1.0 * mkt - 0.4 * up_cpm,
        "seasonality": 2.5 * broad + 1.6 * mkt + 0.2 * d_ctr + 0.2 * d_cvr - 0.8 * seg,
        "tracking": 8.0 * float(ev["conv_zero"]),
        "no_issue": 1.6 - 0.8 * max(d_ctr, d_cvr, up_cpm),
    }
    return {k: float(v) for k, v in s.items()}


def softmax(s: dict[str, float], temp: float = 0.7) -> dict[str, float]:
    v = np.array([s[h] for h in HYPOTHESES]) / temp
    p = np.exp(v - v.max())
    p /= p.sum()
    return {h: float(x) for h, x in zip(HYPOTHESES, p)}


def evidence_items(ev: dict, community_names: dict[int, str] | None = None) -> list[dict]:
    """Human-readable evidence rows with values, strongest first (code writes these, not the LLM)."""
    names = community_names or {}
    items = [
        {"key": "ctr", "label": "CTR, last 3 days vs healthy baseline", "value": f"{ev['z_ctr']:+.1f} σ", "strength": abs(ev["z_ctr"]), "points_to": "creative_fatigue" if ev["z_ctr"] < 0 else None},
        {"key": "cvr", "label": "Conversion rate, last 3 days vs baseline", "value": f"{ev['z_cvr']:+.1f} σ", "strength": abs(ev["z_cvr"]), "points_to": "landing_page" if ev["z_cvr"] < 0 else None},
        {"key": "cpm", "label": "CPM, last 3 days vs baseline", "value": f"{ev['z_cpm']:+.1f} σ", "strength": abs(ev["z_cpm"]), "points_to": "auction_pressure" if ev["z_cpm"] > 0 else None},
        {"key": "freq", "label": "CTR-frequency correlation (14 d)", "value": f"{ev['freq_corr']:+.2f} (freq {ev['frequency']:.1f})", "strength": 3 * max(-ev["freq_corr"], 0), "points_to": "creative_fatigue"},
        {"key": "breadth", "label": "Other ads dropping at the same time", "value": f"{ev['breadth_all']:.0%} of all, {ev['breadth_campaign']:.0%} of campaign", "strength": 4 * ev["breadth_all"] + 2 * ev["breadth_campaign"], "points_to": "seasonality" if ev["breadth_all"] > 0.5 else "landing_page"},
        {"key": "segments", "label": "CTR change by community", "value": ", ".join(f"{names.get(c, f'C{c}')}: {r - 1:+.0%}" for c, r in sorted(ev["segment_ratios"].items(), key=lambda x: x[1])) or "n/a", "strength": 5 * ev["segment_spread"], "points_to": "segment_saturation"},
        {"key": "comments", "label": "Annoyed comments share", "value": f"{ev['annoyed_now']:.0%} ({ev['annoyed_change']:+.0%})", "strength": 20 * max(ev["annoyed_change"], 0), "points_to": "creative_fatigue"},
        {"key": "market", "label": "Market demand index (Trends-style)", "value": f"{ev['market_change']:+.0%}", "strength": 20 * max(-ev["market_change"], 0), "points_to": "seasonality"},
    ]
    if ev["conv_zero"]:
        items.append({"key": "conv_zero", "label": "Conversions dropped to zero, clicks normal", "value": "0 conversions in 2 days", "strength": 10, "points_to": "tracking"})
    return sorted(items, key=lambda x: -x["strength"])


def diagnose(ctx: Ctx, ad_id: str, day: int | None = None, community_names: dict[int, str] | None = None) -> dict:
    day = ctx.source.current_day() if day is None else day
    ev = evidence(ctx, ad_id, day)
    probs = softmax(score(ev))
    top = max(probs, key=probs.get)
    return {
        "ad_id": ad_id, "day": day, "probabilities": probs, "top": top, "top_label": LABELS[top],
        "recommended_action": ACTIONS[top], "evidence": evidence_items(ev, community_names),
        "raw": {k: v for k, v in ev.items() if k != "segment_ratios"} | {"segment_ratios": {str(k): v for k, v in ev["segment_ratios"].items()}},
    }
