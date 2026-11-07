from __future__ import annotations

import asyncio
import json

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import db
from app.analytics import fatigue, segments
from app.analytics.fatigue import pooled_ctr
from app.analytics.radar import overview as overview_fn
from app.api.deps import company_cfg, rt
from app.llm.agents import narrate
from app.state import STATE

router = APIRouter(prefix="/api/ch/{ch}")


@router.get("/overview")
def overview(ch: str):
    r = rt(ch)
    from app import registry

    conv = registry.economics_of(ch).get("conversion_name", "purchase")
    return overview_fn(r.ctx, r.radar()) | {"playing": STATE.playing, "world_day": STATE.world_day, "report_lag_days": r.lag, "conversion_name": conv}


@router.get("/ads")
def ads(ch: str):
    return rt(ch).radar()


def _ad_or_404(r, ad_id: str) -> dict:
    try:
        return r.ctx.ad(ad_id)
    except StopIteration:
        raise HTTPException(404, f"unknown ad {ad_id}")


@router.get("/ads/{ad_id}")
def ad_detail(ch: str, ad_id: str):
    r = rt(ch)
    ad = _ad_or_404(r, ad_id)
    ad_d = r.ctx.ad_daily()
    me = ad_d[ad_d.ad_id == ad_id].set_index("day").sort_index()
    health = next((x for x in r.radar() if x["ad_id"] == ad_id), None)
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
    series = [{"day": int(d), "ctr": float(x.ctr), "cvr": float(x.cvr), "cpm": float(x.cpm), "cpa": float(x.cpa), "roas": float(x.roas),
               "frequency": float(x.frequency), "spend": float(x.spend), "impressions": float(x.impressions), "clicks": float(x.clicks),
               "conversions": float(x.conversions), "annoyed_share": float(x.annoyed_share)} for d, x in me.iterrows()]
    forecast = None
    if health and health.get("days_to_fatigue") is not None and len(me):
        forecast = {"days_to_fatigue": health["days_to_fatigue"], "low": health["dtf_low"], "high": health["dtf_high"],
                    "fatigue_day": r.day + health["days_to_fatigue"], "fatigue_day_low": r.day + health["dtf_low"],
                    "fatigue_day_high": r.day + health["dtf_high"], "threshold_ctr": float(pooled_ctr(me, 7).max() * 0.7)}
    comm = segments.ad_by_community(r.ctx, ad_id)
    for c in comm:
        c["name"] = r.names.get(c["community_id"], f"C{c['community_id']}")
    return {"ad": ad, "health": health, "series": series, "markers": markers, "forecast": forecast, "communities": comm,
            "model": {"kind": "fatigue predictor", "trained": fatigue.MODEL_PATH.exists()}}


@router.post("/ads/{ad_id}/diagnose")
def diagnose(ch: str, ad_id: str):
    r = rt(ch)
    _ad_or_404(r, ad_id)
    d = r.diagnosis(ad_id)
    db.x("INSERT INTO diagnoses(channel_id,ad_id,day,scores,evidence,narrative,true_label,predicted) VALUES (?,?,?,?,?,?,?,?)",
         (ch, ad_id, d["day"], json.dumps(d["probabilities"]), json.dumps(d["evidence"]), None, None, d["top"]))
    return d


@router.get("/ads/{ad_id}/diagnose/narrative")
async def narrative(ch: str, ad_id: str):
    r = rt(ch)
    ad = _ad_or_404(r, ad_id)
    d = r.diagnosis(ad_id)
    data, src = await asyncio.to_thread(narrate, d, ad, company_cfg(r)["brand"])

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


@router.get("/campaigns")
def campaigns(ch: str):
    """Per campaign: KPIs + the country map (active / expand / retreat)."""
    from app import registry
    from app.analytics.geo import campaign_maps

    r = rt(ch)
    co = registry.company(r.company_id)["config"]
    return campaign_maps(r.ctx, r.company_id, co.get("markets", []), co.get("geo_events", []))


@router.get("/heatmap")
def heatmap(ch: str):
    r = rt(ch)
    rows = segments.heatmap(r.ctx)
    for x in rows:
        x["name"] = r.names.get(x["community_id"], f"C{x['community_id']}")
    return rows
