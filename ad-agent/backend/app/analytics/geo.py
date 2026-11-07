"""Opportunity map: per campaign, which countries to keep, expand into, or retreat from.

Inputs (all computed, no LLM):
  - country breakdown of the campaign's results (ROAS, CPA, CTR, last 7 days vs the 7 before)
  - category demand index per country (Trends-style; real deployment: Google Trends / GDELT news volume)
  - optional real news context per country from data/signals/<company>.json (scripts/fetch_news_signals.py)
Rules:
  retreat = active AND (ROAS below the campaign minimum while demand is falling OR ROAS < 60% of the minimum)
  expand  = not active, a market the company sells in, AND demand up >= 20% vs its baseline
"""
from __future__ import annotations

import json

import numpy as np

from app import geo
from app.analytics.context import Ctx
from app.config import DATA

EXPAND_DEMAND = 0.20
RETREAT_DEMAND = -0.15


def _demand_change(demand: dict[int, dict[str, float]], code: str, day: int) -> float | None:
    """Last 3 days vs the first two weeks of a 4-week window (so a shift that started 2 weeks ago still shows)."""
    recent = [v[code] for d, v in demand.items() if day - 3 < d <= day and code in v]
    base = [v[code] for d, v in demand.items() if day - 29 <= d <= day - 15 and code in v]
    if len(recent) < 2 or len(base) < 5:
        return None
    return float(np.mean(recent) / np.mean(base) - 1)


def _news(company_id: str) -> dict:
    f = DATA / "signals" / f"{company_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def campaign_maps(ctx: Ctx, company_id: str, markets: list[str], geo_events: list[dict]) -> list[dict]:
    day = ctx.source.current_day()
    cs = ctx.source.get_country_stats(day - 13, day)
    demand = ctx.source.get_country_demand(day - 29, day)
    news = _news(company_id).get("countries", {})
    notes = {}  # simulated event notes, only shown for simulated feeds (labelled as simulated)
    for e in geo_events:
        if e["start_day"] <= day and (e.get("end_day") is None or e["end_day"] >= day):
            notes[e["country"]] = e.get("note")
    out = []
    for cid, camp in ctx.sim.campaigns.items():
        active = {c: v for c, v in ctx.sim.countries_of(cid).items() if v > 0}
        rows = cs[cs.campaign_id == cid]
        last = rows[rows.day > day - 7]
        prev = rows[(rows.day <= day - 7) & (rows.day > day - 14)]
        min_roas = float(camp.get("min_roas") or 1.0)
        # Geography only explains a gap between countries. If every country is weak the cause is the campaign
        # itself (fatigue, tracking, creative), which the Radar diagnoses, so retreat needs a country that lags the rest.
        by_c = last.groupby("country")[["spend", "revenue"]].sum()
        c_roas = {c: float(r.revenue / r.spend) for c, r in by_c.iterrows() if r.spend > 0 and c in active}
        conv_per_eur = float(last.conversions.sum()) / max(float(last.spend.sum()), 1.0)
        countries = []
        for code in sorted(set(markets) | set(active)):
            d_change = _demand_change(demand, code, day)
            entry = {"code": code, "name": geo.name(code), "active": code in active, "share": round(active.get(code, 0.0), 3),
                     "demand_change": None if d_change is None else round(d_change, 3)}
            if code in active:
                lc, pc = last[last.country == code], prev[prev.country == code]
                sp, rv = float(lc.spend.sum()), float(lc.revenue.sum())
                roas = rv / sp if sp > 0 else None
                prev_roas = float(pc.revenue.sum()) / float(pc.spend.sum()) if float(pc.spend.sum()) > 0 else None
                entry.update({"spend_7d": round(sp, 2), "roas": None if roas is None else round(roas, 2),
                              "roas_prev": None if prev_roas is None else round(prev_roas, 2),
                              "ctr": float(lc.clicks.sum() / max(lc.impressions.sum(), 1)), "conversions_7d": float(lc.conversions.sum())})
                falling = d_change is not None and d_change <= RETREAT_DEMAND
                others = [v for c, v in c_roas.items() if c != code]
                enough = sp * conv_per_eur >= 5  # at least ~5 expected conversions, else the ROAS gap is noise
                lags = roas is not None and enough and bool(others) and roas < 0.75 * float(np.median(others))
                if roas is not None and lags and ((roas < min_roas and falling) or roas < 0.6 * min_roas):
                    entry["status"] = "retreat"
                    why = f"ROAS {roas:.2f} vs campaign minimum {min_roas:.2f}"
                    if falling:
                        why += f"; demand {d_change:+.0%} vs baseline"
                    entry["reason"] = why + f" (other countries {float(np.median(others)):.2f}). Move this country's budget to stronger markets."
                else:
                    entry["status"] = "active"
                    entry["reason"] = f"ROAS {roas:.2f}" if roas is not None else "No spend yet"
            elif code in markets:
                if d_change is not None and d_change >= EXPAND_DEMAND:
                    entry["status"] = "expand"
                    entry["reason"] = f"Category demand {d_change:+.0%} vs baseline and no campaign there yet. Test it with a share of the budget."
                else:
                    entry["status"] = "market"
                    entry["reason"] = "Market you sell in, no campaign running"
            if code in notes:
                entry["signal_note"] = notes[code]
            if code in news:
                entry["news"] = news[code]
            countries.append(entry)
        out.append({"campaign_id": cid, "name": camp.get("name"), "objective": camp.get("objective"), "min_roas": min_roas,
                    "spend_7d": round(float(last.spend.sum()), 2),
                    "roas_7d": round(float(last.revenue.sum()) / float(last.spend.sum()), 2) if float(last.spend.sum()) > 0 else None,
                    "countries": countries,
                    "summary": {s: [c["name"] for c in countries if c.get("status") == s] for s in ("active", "expand", "retreat")}})
    return out
