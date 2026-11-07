from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db
from app.integrations import trends
from app.llm import provider
from app.sim import scenarios
from app.state import STATE

router = APIRouter(prefix="/api")


@router.get("/memory")
def memory():
    out = []
    for r in db.q("SELECT id, brand, insight, evidence, applies_to, winner, created_day FROM memory ORDER BY id DESC"):
        r["applies_to"] = json.loads(r["applies_to"])
        r["winner"] = bool(r["winner"])
        out.append(r)
    return out


def _targets_of(target: dict) -> set[str]:
    ads = STATE.ctx.ads()
    if target.get("ad"):
        return {target["ad"]}
    if target.get("campaign"):
        return {a["ad_id"] for a in ads if a["campaign_id"] == target["campaign"]}
    return {a["ad_id"] for a in ads}


def _eval_target(t: dict, sc: dict, day: int, all_truth: list[dict]) -> str:
    """The ad to score a scenario on: its own target, avoiding ads hit by another scenario active that day."""
    target = json.loads(t["target"])
    mine = _targets_of(target)
    busy_all: set[str] = set()
    busy_live: set[str] = set()
    for o in all_truth:
        if o is t or json.loads(o["target"]).get("all"):
            continue
        if o["start_day"] <= day and (o["end_day"] is None or o["end_day"] >= day):
            ids = _targets_of(json.loads(o["target"]))
            busy_all |= ids
            if o["live"]:
                busy_live |= ids
    active = [a["ad_id"] for a in STATE.ctx.ads() if a["status"] == "active"]
    prefs = ([sc["eval_ad"]] if sc.get("eval_ad") in mine else []) + sorted(mine)
    for busy in (busy_all, busy_live):
        for a in prefs:
            if a in active and a not in busy:
                return a
    return prefs[0] if prefs else sc["eval_ad"]


@router.get("/eval")
def evaluation():
    """Planted history scenarios are scored at the end of the history (or their eval_day);
    live injections are scored on the current day once 3 days of data exist."""
    from app import config

    cfg = scenarios.load()
    rows = []
    truth = db.q("SELECT * FROM truth_scenarios ORDER BY live, start_day")
    for t in truth:
        sc = cfg[t["scenario_id"]]
        if t["live"]:
            day = STATE.day if t["end_day"] is None else min(STATE.day, t["end_day"])
            if day < t["start_day"] + 2:
                rows.append({"scenario": t["scenario_id"], "name": sc["name"], "ad_id": None, "live": True, "status": "pending",
                             "truth": t["label"], "detail": f"needs 3 days of data (injected day {t['start_day']})"})
                continue
        else:
            day = sc.get("eval_day", config.HISTORY_DAYS - 1)
        ad_id = _eval_target(t, sc, day, truth)
        d = STATE.diagnosis(ad_id, day)
        rows.append({"scenario": t["scenario_id"], "name": sc["name"], "ad_id": ad_id, "day": day, "live": bool(t["live"]),
                     "truth": t["label"], "predicted": d["top"], "confidence": round(d["probabilities"][d["top"]], 3),
                     "correct": d["top"] == t["label"], "status": "scored"})
    scored = [r for r in rows if r["status"] == "scored"]
    meta = db.kv_get("world_meta", {})
    prot = db.q("SELECT COALESCE(SUM(eur_protected),0) AS s, COUNT(*) AS n FROM budget_actions WHERE status='approved'")[0]
    spend = float(STATE.ctx.ad_daily()["spend"].sum())
    return {"scenarios": rows, "accuracy": (sum(r["correct"] for r in scored) / len(scored)) if scored else None,
            "n_scored": len(scored), "nmi_vs_seed": meta.get("nmi_vs_seed"), "community_method": meta.get("community_method"),
            "eur_protected": round(prot["s"], 2), "approved_actions": prot["n"], "total_spend": round(spend, 2),
            "llm": provider.status()}


class SimControl(BaseModel):
    action: str  # play | pause | speed | reset | step
    value: float | None = None


@router.post("/sim/control")
async def sim_control(c: SimControl):
    if c.action == "play":
        STATE.playing = True
    elif c.action == "pause":
        STATE.playing = False
    elif c.action == "speed":
        STATE.tick_seconds = max(0.5, float(c.value or 4))
    elif c.action == "step":
        await asyncio.to_thread(STATE.tick)
    elif c.action == "reset":
        STATE.playing = False
        await asyncio.to_thread(STATE.reset)
        STATE.broadcast("tick", {"day": STATE.day, "changed": [], "reset": True})
    else:
        raise HTTPException(400, c.action)
    return {"day": STATE.day, "playing": STATE.playing, "tick_seconds": STATE.tick_seconds}


@router.get("/sim/state")
def sim_state():
    cfg = scenarios.load()
    return {"day": STATE.day, "playing": STATE.playing, "tick_seconds": STATE.tick_seconds,
            "scenarios": [{"id": k, "name": v["name"], "description": v["description"], "target": v["target"]} for k, v in cfg.items()],
            "ads": [a["ad_id"] for a in STATE.ctx.ads() if a["status"] == "active"], "world": db.kv_get("world_meta", {})}


class Inject(BaseModel):
    scenario: str
    target_ad: str | None = None


@router.post("/sim/inject")
def inject(i: Inject):
    if i.scenario not in scenarios.load():
        raise HTTPException(400, f"unknown scenario {i.scenario}")
    with STATE.lock:
        out = scenarios.inject(STATE.sim, i.scenario, i.target_ad)
    STATE.broadcast("action", {"type": "injected", **out})
    return out


@router.get("/truth")
def truth():
    """Reveal-truth toggle: hidden layer, only for the evaluation panel."""
    rows = db.q("SELECT day, ad_id, mean_exposures, mean_fatigue FROM truth_user_state WHERE day > ? ORDER BY day", (STATE.day - 14,))
    return {"scenarios": db.q("SELECT * FROM truth_scenarios"), "user_state": rows}


class LLMSwitch(BaseModel):
    provider: str


@router.get("/llm")
def llm_status():
    return provider.status()


@router.post("/llm")
def llm_switch(s: LLMSwitch):
    try:
        provider.set_provider(s.provider)
    except ValueError:
        raise HTTPException(400, "provider must be gemini, ollama or cache-only")
    return provider.status()


@router.get("/trends")
def get_trends():
    return trends.cached() or {}


@router.get("/stream")
async def stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    STATE.listeners.add(q)

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'day': STATE.day})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            STATE.listeners.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
