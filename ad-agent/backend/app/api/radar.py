from __future__ import annotations

import asyncio
import json

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import db
from app.analytics import fatigue, segments
from app.analytics.radar import overview as overview_fn
from app.llm.agents import narrate
from app.state import STATE

router = APIRouter(prefix="/api")


@router.get("/overview")
def overview():
    rows = STATE.radar()
    return overview_fn(STATE.ctx, rows) | {"playing": STATE.playing}


@router.get("/ads")
def ads():
    return STATE.radar()


def _ad_or_404(ad_id: str) -> dict:
    try:
        return STATE.ctx.ad(ad_id)
    except StopIteration:
        raise HTTPException(404, f"unknown ad {ad_id}")


@router.get("/ads/{ad_id}")
def ad_detail(ad_id: str):
    ad = _ad_or_404(ad_id)
    ctx = STATE.ctx
    ad_d = ctx.ad_daily()
    me = ad_d[ad_d.ad_id == ad_id].set_index("day").sort_index()
    health = next((r for r in STATE.radar() if r["ad_id"] == ad_id), None)
    # anomaly markers: days whose CTR / CVR / CPM sits > 2.5 robust sigma from the preceding 14 days
    markers = []
    for m, sign in (("ctr", -1), ("cvr", -1), ("cpm", 1)):
        s = me[m]
        for d in s.index:
            b = s[(s.index < d) & (s.index >= d - 14)].to_numpy()
            if len(b) < 7:
                continue
            med = np.median(b)
            mad = max(np.median(np.abs(b - med)) * 1.4826, 0.05 * abs(med), 1e-9)
            z = (s[d] - med) / mad
            if z * sign >= 2.5:
                markers.append({"day": int(d), "metric": m, "z": round(float(z), 2)})
    series = [{"day": int(d), "ctr": float(r.ctr), "cvr": float(r.cvr), "cpm": float(r.cpm), "cpa": float(r.cpa), "roas": float(r.roas),
               "frequency": float(r.frequency), "spend": float(r.spend), "impressions": float(r.impressions), "clicks": float(r.clicks),
               "conversions": float(r.conversions), "annoyed_share": float(r.annoyed_share)} for d, r in me.iterrows()]
    forecast = None
    if health and health.get("days_to_fatigue") is not None:
        forecast = {"days_to_fatigue": health["days_to_fatigue"], "low": health["dtf_low"], "high": health["dtf_high"],
                    "fatigue_day": STATE.day + health["days_to_fatigue"], "fatigue_day_low": STATE.day + health["dtf_low"],
                    "fatigue_day_high": STATE.day + health["dtf_high"], "threshold_ctr": float(me["ctr"].rolling(3, min_periods=1).mean().max() * 0.7)}
    comm = segments.ad_by_community(ctx, ad_id)
    for c in comm:
        c["name"] = STATE.names.get(c["community_id"], f"C{c['community_id']}")
    return {"ad": ad, "health": health, "series": series, "markers": markers, "forecast": forecast, "communities": comm,
            "model": {"kind": "fatigue predictor", "trained": fatigue.MODEL_PATH.exists()}}


@router.post("/ads/{ad_id}/diagnose")
def diagnose(ad_id: str):
    _ad_or_404(ad_id)
    d = STATE.diagnosis(ad_id)
    db.x("INSERT INTO diagnoses(ad_id,day,scores,evidence,narrative,true_label,predicted) VALUES (?,?,?,?,?,?,?)",
         (ad_id, d["day"], json.dumps(d["probabilities"]), json.dumps(d["evidence"]), None, None, d["top"]))
    return d


@router.get("/ads/{ad_id}/diagnose/narrative")
async def narrative(ad_id: str):
    ad = _ad_or_404(ad_id)
    d = STATE.diagnosis(ad_id)
    data, src = await asyncio.to_thread(narrate, d, ad)

    async def gen():
        yield f"event: meta\ndata: {json.dumps({'source': src})}\n\n"
        text = f"{data['headline']}\n\n{data['explanation']}\n\nNext step: {data['recommended_action']}"
        words = text.split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i + 3]) + (" " if i + 3 < len(words) else "")
            yield f"event: chunk\ndata: {json.dumps({'text': chunk})}\n\n"
            await asyncio.sleep(0.04 if src != "cache" else 0.02)
        yield f"event: done\ndata: {json.dumps(data | {'source': src})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/heatmap")
def heatmap():
    rows = segments.heatmap(STATE.ctx)
    for r in rows:
        r["name"] = STATE.names.get(r["community_id"], f"C{r['community_id']}")
    return rows

