"""Ads Radar (feature 1): anomalies, health status, days to fatigue, € at risk."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics import fatigue
from app.analytics.context import Ctx
from app.analytics.metrics import rate_z, robust_z, window

FLAG_Z = 2.5
BAD_DIRECTION = {"ctr": -1, "cvr": -1, "cpm": +1, "roas": -1, "frequency": +1}
GAP = 7


def ad_health(ctx: Ctx, ad_id: str, ad_d: pd.DataFrame, day: int) -> dict:
    me = ad_d[ad_d.ad_id == ad_id].set_index("day").sort_index()
    me = me[me.index <= day]
    if len(me) < 3:
        return {"ad_id": ad_id, "status": "new", "anomalies": [], "days_to_fatigue": None}
    z = {}
    for m in BAD_DIRECTION:
        if m == "ctr":
            z[m] = rate_z(me, "clicks", "impressions", day, gap=GAP)
        elif m == "cvr":
            z[m] = rate_z(me, "conversions", "clicks", day, gap=GAP)
        else:
            r, b = window(me[m], day, gap=GAP)
            z[m] = robust_z(r, b)
    # pooled-rate tests (CTR, CVR) are calibrated z-scores, so they flag at 2.0; daily robust z for the rest at 2.5
    flags = [{"metric": m, "z": round(z[m], 2)} for m in BAD_DIRECTION
             if m != "frequency" and z[m] * BAD_DIRECTION[m] >= (2.0 if m in ("ctr", "cvr") else FLAG_Z)]
    feats = fatigue.features_for(me, day, ctx.audience(ad_id), ctx.max_sim_prior(ad_id))
    dtf, lo, hi = fatigue.predict(feats)
    if feats["ctr_vs_peak"] < 0.7:
        dtf, lo, hi = 0.0, 0.0, min(hi, 2.0)

    last7 = me[me.index > day - 7]
    spend_day = float(last7["spend"].mean())
    r, b = window(me["roas"], day, gap=GAP)
    roas_now, roas_base = (float(np.mean(r)) if len(r) else 0.0), (float(np.median(b)) if len(b) else 0.0)
    eff_loss_now = max(0.0, 1 - roas_now / roas_base) if roas_base > 0 else 0.0
    eff_loss_fatigue = 0.35 * max(0.0, 7 - dtf) / 7
    eur_at_risk = 7 * spend_day * min(0.9, max(eff_loss_now, eff_loss_fatigue))

    severity = max([abs(f["z"]) for f in flags], default=0.0)
    if (flags and (severity >= 4 or dtf <= 1)) or feats["ctr_vs_peak"] < 0.55:
        status = "failing"
    elif flags or dtf <= 3:
        status = "at_risk"
    elif any(z[m] * BAD_DIRECTION[m] >= 1.5 for m in BAD_DIRECTION if m != "frequency") or dtf <= 7:
        status = "watch"
    else:
        status = "healthy"
    return {
        "ad_id": ad_id, "status": status, "anomalies": flags, "z": {k: round(v, 2) for k, v in z.items()},
        "days_to_fatigue": round(dtf, 1), "dtf_low": round(lo, 1), "dtf_high": round(hi, 1),
        "eur_at_risk": round(eur_at_risk, 2), "severity": round(severity, 2), "spend_day": round(spend_day, 2),
        "ctr_vs_peak": round(feats["ctr_vs_peak"], 3), "frequency": round(feats["frequency"], 2), "saturation": round(feats["saturation"], 3),
    }


def radar(ctx: Ctx, day: int | None = None) -> list[dict]:
    day = ctx.source.current_day() if day is None else day
    ad_d = ctx.ad_daily(day)
    out = []
    for a in ctx.ads():
        if a["status"] not in ("active", "paused"):
            continue
        h = ad_health(ctx, a["ad_id"], ad_d, day)
        me = ad_d[ad_d.ad_id == a["ad_id"]].set_index("day").sort_index()
        last = me[me.index > day - 7]
        h.update({
            "campaign_id": a["campaign_id"], "ad_set_id": a["ad_set_id"], "hook": a.get("hook"), "ad_status": a["status"],
            "ctr": float(last["clicks"].sum() / max(last["impressions"].sum(), 1)),
            "cpa": float(last["spend"].sum() / max(last["conversions"].sum(), 1)),
            "roas": float(last["revenue"].sum() / max(last["spend"].sum(), 0.01)),
            "spend_7d": float(last["spend"].sum()),
            "sparkline": [round(float(v), 5) for v in me["ctr"].tail(21).to_numpy()],
        })
        out.append(h)
    order = {"failing": 0, "at_risk": 1, "watch": 2, "healthy": 3, "new": 4}
    return sorted(out, key=lambda x: (order[x["status"]], -(x.get("eur_at_risk") or 0)))


def overview(ctx: Ctx, rows: list[dict], day: int | None = None) -> dict:
    day = ctx.source.current_day() if day is None else day
    ad_d = ctx.ad_daily(day)
    last = ad_d[ad_d.day > day - 7]
    prev = ad_d[(ad_d.day > day - 14) & (ad_d.day <= day - 7)]

    def k(df):
        sp, rv, cv = df["spend"].sum(), df["revenue"].sum(), df["conversions"].sum()
        return {"spend": float(sp), "revenue": float(rv), "roas": float(rv / max(sp, 0.01)), "cpa": float(sp / max(cv, 1)), "conversions": float(cv)}

    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("healthy", "watch", "at_risk", "failing")}
    return {"day": day, "kpi_7d": k(last), "kpi_prev_7d": k(prev), "eur_at_risk": round(sum(r.get("eur_at_risk") or 0 for r in rows), 2), "health_counts": counts}
