"""Companies, their brand profiles and connected channels."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import registry
from app.analytics.radar import overview as overview_fn
from app.sources.platforms import AD_PLATFORMS, PLATFORMS
from app.state import STATE
from app.world.synthetic import TOPICS

router = APIRouter(prefix="/api")

PLATFORM_SIM = {  # typical economics per platform for simulated feeds
    "instagram": {"base_cpm": 8.0, "b0": -4.4, "lam": 0.6, "report_lag_days": 0},
    "facebook": {"base_cpm": 8.0, "b0": -4.4, "lam": 0.6, "report_lag_days": 0},
    "tiktok": {"base_cpm": 5.0, "b0": -4.1, "lam": 0.75, "report_lag_days": 1},
    "x": {"base_cpm": 5.0, "b0": -4.6, "lam": 0.6, "report_lag_days": 1},
    "linkedin": {"base_cpm": 28.0, "b0": -4.9, "lam": 0.6, "weekend": 0.6, "report_lag_days": 1},
}


def _channel_summary(ch: dict) -> dict:
    out = {k: ch[k] for k in ("channel_id", "company_id", "platform", "kind", "name", "handle", "mode", "status")}
    out["platform_info"] = {k: PLATFORMS.get(ch["platform"], {}).get(k) for k in ("name", "api", "latency_days")}
    r = STATE.rt.get(ch["channel_id"])
    if r is not None:
        rows = r.radar()
        ov = overview_fn(r.ctx, rows)
        out.update({"live": True, "reported_through": r.day, "report_lag_days": r.lag, "kpi_7d": ov["kpi_7d"], "eur_at_risk": ov["eur_at_risk"],
                    "health_counts": ov["health_counts"], "n_ads": len(rows),
                    "audience_type": ch["config"].get("audience", {}).get("type")})
    else:
        out["live"] = False
    if ch["kind"] == "audience":
        used_by = [c["channel_id"] for c in registry.channels(ch["company_id"], "ads") if c["config"].get("audience", {}).get("source") == ch["channel_id"]]
        out["feeds_channels"] = used_by
    return out


@router.get("/companies")
def list_companies():
    out = []
    for co in registry.companies():
        cfg = co["config"]
        out.append({"company_id": co["company_id"], "name": co["name"], "industry": co["industry"], "fictional": cfg.get("fictional", False),
                    "description": cfg.get("description"), "conversion_name": cfg["economics"].get("conversion_name", "purchase"),
                    "channels": [_channel_summary(c) for c in co["channels"]]})
    return out


@router.get("/companies/{cid}")
def get_company(cid: str):
    try:
        co = registry.company(cid)
    except KeyError:
        raise HTTPException(404, cid)
    return {"company_id": cid, "name": co["name"], "industry": co["industry"], "config": co["config"],
            "channels": [_channel_summary(c) for c in registry.channels(cid)]}


@router.get("/platforms")
def platforms():
    return {"platforms": PLATFORMS, "ad_platforms": AD_PLATFORMS,
            "segments": [{"key": k, "label": k.replace("_", " ").title(), "examples": v["nouns"][:4]} for k, v in TOPICS.items()]}


class NewCompany(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    industry: str = Field(min_length=2, max_length=120)
    description: str = ""
    tone: str = "clear and friendly"
    banned_phrases: list[str] = []
    competitors: list[str] = []
    avg_order_value: float = 50.0
    conversion_name: str = "purchase"
    base_cvr: float = 0.04


@router.post("/companies")
def create_company(c: NewCompany):
    cid = registry.create_company(c.name, c.industry, c.description, c.tone, c.banned_phrases, c.competitors, c.avg_order_value, c.conversion_name, c.base_cvr)
    return get_company(cid)


class NewChannel(BaseModel):
    platform: str
    handle: str = ""
    mode: str = "simulated"           # simulated | live
    segments: list[str] = []          # for simulated feeds: which audience segments the ad sets target
    daily_budget: float = 40.0


def _starter_config(cid: str, ch: str, n: NewChannel) -> dict:
    co = registry.company(cid)["config"]
    b = co["brand"]
    sim = dict(PLATFORM_SIM.get(n.platform, PLATFORM_SIM["instagram"]))
    lag = sim.pop("report_lag_days")
    segs = n.segments[:6]
    camp_id = f"{n.platform[:2]}_always_on"
    ad_sets, creatives = [], []
    for i, s in enumerate(segs):
        label = s.replace("_", " ").title()
        asid = f"{n.platform[:2]}_{s}"[:24]
        ad_sets.append({"ad_set_id": asid, "campaign_id": camp_id, "name": label, "daily_budget": n.daily_budget, "target_packs": [s]})
        creatives.append({"ad_id": f"{n.platform[:1].upper()}{2 * i + 1}", "ad_set_id": asid, "hook": f"{b['name']}, made for {label.lower()}",
                          "body": f"{b['product']}. Built for {label.lower()} who want less hassle.", "cta": "Learn more", "offer": "none", "tone": "informative", "angle": "fit"})
        creatives.append({"ad_id": f"{n.platform[:1].upper()}{2 * i + 2}", "ad_set_id": asid, "hook": f"Why {label.lower()} pick {b['name']}",
                          "body": f"See how {b['name']} fits your week in 30 seconds.", "cta": "Try it", "offer": "none", "tone": "witty", "angle": "social proof"})
    first = creatives[0]["ad_id"]
    return {
        "channel_id": ch, "platform": n.platform, "name": f"{PLATFORMS[n.platform]['name']} Ads", "handle": n.handle or b["name"], "mode": "simulated",
        "report_lag_days": lag, "sim": sim,
        "audience": {"type": "segments", "packs": {s: 380 for s in segs}, "labels": {s: s.replace("_", " ").title() for s in segs}},
        "campaigns": [{"campaign_id": camp_id, "name": "Always-on", "objective": "conversions", "max_cpa": max(5.0, co["economics"]["order_values"][0] * 0.6),
                       "min_roas": 1.0, "total_budget": n.daily_budget * len(segs)}],
        "ad_sets": ad_sets, "creatives": creatives,
        "scenarios": {
            "L1": {"name": "Creative fatigue (live)", "description": f"Push {first}'s budget x5", "label": "creative_fatigue", "target": {"ad": first},
                   "effect": {"type": "budget_multiplier", "value": 5.0}, "history": None, "eval_ad": first, "live_duration": None},
            "L2": {"name": "Seasonal dip (live)", "description": "All activity x0.75 for 4 days", "label": "seasonality", "target": {"all": True},
                   "effect": {"type": "activity", "value": 0.75}, "history": None, "eval_ad": creatives[-1]["ad_id"], "live_duration": 4},
            "L3": {"name": "Tracking broke (live)", "description": "Conversions report 0", "label": "tracking", "target": {"campaign": camp_id},
                   "effect": {"type": "tracking_off", "value": 0}, "history": None, "eval_ad": creatives[-1]["ad_id"], "live_duration": None},
        },
    }


@router.post("/companies/{cid}/channels")
async def add_channel(cid: str, n: NewChannel):
    try:
        registry.company(cid)
    except KeyError:
        raise HTTPException(404, cid)
    if n.platform not in PLATFORMS:
        raise HTTPException(400, f"unknown platform {n.platform}")
    info = PLATFORMS[n.platform]
    ch = registry.new_channel_id(cid, n.platform)
    if info["kind"] == "audience" or n.mode == "live":
        cfg = {"channel_id": ch, "platform": n.platform, "name": f"{info['name']}" + (" Ads" if info["kind"] == "ads" else " audience"),
               "handle": n.handle, "mode": n.mode}
        status = "awaiting_credentials" if n.mode == "live" and n.platform != "bluesky" else "connected"
        registry.insert_channel(cfg, cid, info["kind"], n.mode, status)
        return {"channel_id": ch, "status": status,
                "next_steps": f"{info['auth']}. {info['access']}" if status == "awaiting_credentials" else "Public data: run `python run.py snapshot` to pull communities."}
    unknown = [s for s in n.segments if s not in TOPICS]
    if not n.segments or unknown:
        raise HTTPException(400, f"pick 1-6 audience segments from /api/platforms (unknown: {unknown})")
    cfg = _starter_config(cid, ch, n)
    registry.insert_channel(cfg, cid, "ads", "simulated", "building")

    def build():
        from app.world.build import build_channel

        build_channel(ch, profile_with_llm=True)
        STATE.add_channel(ch)
        registry.set_channel_status(ch, "connected")

    try:
        await asyncio.to_thread(build)
    except Exception as e:
        registry.set_channel_status(ch, "error")
        raise HTTPException(500, f"building the simulated feed failed: {e}")
    STATE.broadcast("action", {"type": "channel_added", "channel_id": ch})
    return {"channel_id": ch, "status": "connected", "config": json.loads(json.dumps(cfg))}
