from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import config, db
from app.api.deps import rt
from app.integrations import trends
from app.llm import provider
from app.sim import scenarios
from app.state import STATE

router = APIRouter(prefix="/api")


# ---------------- per channel ----------------
@router.get("/ch/{ch}/memory")
def memory(ch: str):
    r = rt(ch)
    out = []
    for m in db.q("SELECT id, brand, insight, evidence, applies_to, winner, created_day, channel_id FROM memory WHERE company_id=? ORDER BY id DESC", (r.company_id,)):
        m["applies_to"] = json.loads(m["applies_to"])
        m["winner"] = bool(m["winner"])
        out.append(m)
    return out


def _targets_of(r, target: dict) -> set[str]:
    ads = r.ctx.ads()
    if target.get("ad"):
        return {target["ad"]}
    if target.get("campaign"):
        return {a["ad_id"] for a in ads if a["campaign_id"] == target["campaign"]}
    return {a["ad_id"] for a in ads}


def _eval_target(r, t: dict, sc: dict, day: int, all_truth: list[dict]) -> str:
    """The ad to score a scenario on: its own target, avoiding ads hit by another scenario active that day."""
    mine = _targets_of(r, json.loads(t["target"]))
    busy_all: set[str] = set()
    busy_live: set[str] = set()
    for o in all_truth:
        if o is t or json.loads(o["target"]).get("all"):
            continue
        if o["start_day"] <= day and (o["end_day"] is None or o["end_day"] >= day):
            ids = _targets_of(r, json.loads(o["target"]))
            busy_all |= ids
            if o["live"]:
                busy_live |= ids
    active = [a["ad_id"] for a in r.ctx.ads() if a["status"] == "active"]
    prefs = ([sc["eval_ad"]] if sc.get("eval_ad") in mine else []) + sorted(mine)
    for busy in (busy_all, busy_live):
        for a in prefs:
            if a in active and a not in busy:
                return a
    return prefs[0] if prefs else sc["eval_ad"]


def evaluate(ch: str) -> dict:
    """Planted history scenarios are scored at the end of the history (or their eval_day);
    live injections are scored on the latest reported day once 3 days of data exist."""
    r = rt(ch)
    cfg = scenarios.load(ch)
    rows = []
    truth = db.q("SELECT * FROM truth_scenarios WHERE channel_id=? ORDER BY live, start_day", (ch,))
    for t in truth:
        sc = cfg[t["scenario_id"]]
        if t["live"]:
            day = r.day if t["end_day"] is None else min(r.day, t["end_day"])
            if day < t["start_day"] + 2:
                rows.append({"scenario": t["scenario_id"], "name": sc["name"], "ad_id": None, "live": True, "status": "pending",
                             "truth": t["label"], "detail": f"needs 3 days of reported data (injected day {t['start_day']})"})
                continue
        else:
            day = min(sc.get("eval_day", config.HISTORY_DAYS - 1), config.HISTORY_DAYS - 1 - r.lag)
        ad_id = _eval_target(r, t, sc, day, truth)
        d = r.diagnosis(ad_id, day)
        rows.append({"scenario": t["scenario_id"], "name": sc["name"], "ad_id": ad_id, "day": day, "live": bool(t["live"]),
                     "truth": t["label"], "predicted": d["top"], "confidence": round(d["probabilities"][d["top"]], 3),
                     "correct": d["top"] == t["label"], "status": "scored"})
    scored = [x for x in rows if x["status"] == "scored"]
    meta = db.kv_get(f"world_meta:{ch}", {})
    prot = db.q("SELECT COALESCE(SUM(eur_protected),0) AS s, COUNT(*) AS n FROM budget_actions WHERE channel_id=? AND status='approved'", (ch,))[0]
    return {"scenarios": rows, "accuracy": (sum(x["correct"] for x in scored) / len(scored)) if scored else None,
            "n_scored": len(scored), "nmi_vs_seed": meta.get("nmi_vs_seed"), "community_method": meta.get("community_method"),
            "eur_protected": round(prot["s"], 2), "approved_actions": prot["n"], "total_spend": round(float(r.ctx.ad_daily()["spend"].sum()), 2)}


@router.get("/ch/{ch}/eval")
def evaluation(ch: str):
    return evaluate(ch) | {"llm": provider.status()}


@router.get("/eval")
def evaluation_all():
    out = {ch: evaluate(ch) for ch in STATE.rt}
    scored = [s for e in out.values() for s in e["scenarios"] if s["status"] == "scored"]
    return {"channels": out, "accuracy": (sum(s["correct"] for s in scored) / len(scored)) if scored else None, "n_scored": len(scored)}


class Inject(BaseModel):
    scenario: str
    target_ad: str | None = None


@router.get("/ch/{ch}/scenarios")
def list_scenarios(ch: str):
    r = rt(ch)
    return {"scenarios": [{"id": k, "name": v["name"], "description": v["description"], "target": v["target"]} for k, v in scenarios.load(ch).items()],
            "ads": [a["ad_id"] for a in r.ctx.ads() if a["status"] == "active"]}


@router.post("/ch/{ch}/sim/inject")
def inject(ch: str, i: Inject):
    r = rt(ch)
    if i.scenario not in scenarios.load(ch):
        raise HTTPException(400, f"unknown scenario {i.scenario}")
    with STATE.lock:
        out = scenarios.inject(ch, r.sim, i.scenario, i.target_ad)
        r.invalidate()
    STATE.broadcast("action", {"type": "injected", "channel_id": ch, **out})
    return out


@router.get("/ch/{ch}/truth")
def truth(ch: str):
    """Reveal-truth toggle: hidden layer, only for the evaluation panel."""
    r = rt(ch)
    rows = db.q("SELECT day, ad_id, mean_exposures, mean_fatigue FROM truth_user_state WHERE channel_id=? AND day > ? ORDER BY day", (ch, r.sim.day - 15))
    return {"scenarios": db.q("SELECT * FROM truth_scenarios WHERE channel_id=?", (ch,)), "user_state": rows}


# ---------------- global ----------------
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
        STATE.broadcast("tick", {"day": STATE.world_day, "reset": True})
    else:
        raise HTTPException(400, c.action)
    return {"day": STATE.world_day, "playing": STATE.playing, "tick_seconds": STATE.tick_seconds}


@router.get("/sim/state")
def sim_state():
    return {"day": STATE.world_day, "playing": STATE.playing, "tick_seconds": STATE.tick_seconds, "embedder": db.kv_get("embedder"),
            "channels": {ch: {"reported_through": r.day, "lag": r.lag} for ch, r in STATE.rt.items()}}


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
            yield f"event: hello\ndata: {json.dumps({'day': STATE.world_day})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            STATE.listeners.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
