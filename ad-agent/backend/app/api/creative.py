from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db
from app.analytics import experiments as exp_mod
from app.analytics import segments
from app.llm.agents import generate_variants, retrieve_memory, write_learning
from app.state import STATE

router = APIRouter(prefix="/api")


class VariantReq(BaseModel):
    community_id: int | None = None


def _persona(cid: int) -> tuple[dict, list[str], str | None]:
    r = db.q("SELECT persona, keywords, dominant_pack FROM communities WHERE community_id=?", (cid,))[0]
    return (json.loads(r["persona"]) if r["persona"] else {"name": STATE.names.get(cid)}), json.loads(r["keywords"]), r["dominant_pack"]


@router.post("/creatives/{ad_id}/variants")
async def variants(ad_id: str, req: VariantReq | None = None):
    try:
        ad = STATE.ctx.ad(ad_id)
    except StopIteration:
        raise HTTPException(404, ad_id)
    diag = STATE.diagnosis(ad_id)
    targets = ad["targets"]
    cid = req.community_id if req and req.community_id is not None else None
    if cid is None:  # the community where the ad is weakest
        ratios = {int(k): v for k, v in diag["raw"]["segment_ratios"].items()}
        cid = min(ratios, key=ratios.get) if ratios else targets[0]
    persona, keywords, pack = _persona(cid)
    memory = retrieve_memory(f"{persona.get('name')} {persona.get('one_liner', '')} {diag['top']}", pack)
    vs, src = await asyncio.to_thread(generate_variants, ad, diag, persona, keywords, memory)
    out = []
    n0 = db.q("SELECT COUNT(*) AS n FROM creatives WHERE parent_ad_id=?", (ad_id,))[0]["n"]
    for i, v in enumerate(vs):
        vid = f"{ad_id}-v{n0 + i + 1}"
        res = segments.resonance(v["emb"], targets)
        db.x("INSERT INTO creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (vid, ad["ad_set_id"], v["hook"], v["body"], v["cta"], v.get("offer") or "none", ad["tone"], ad.get("angle"),
              db.blob(v["emb"]), ad_id, "draft", v["changed_dimension"], v["hypothesis"]))
        out.append({"ad_id": vid, **{k: v[k] for k in ("changed_dimension", "hook", "body", "cta", "offer", "hypothesis", "expected_effect", "similarity_to_original", "guard")},
                    "resonance": {STATE.names.get(c, str(c)): s for c, s in res.items()}})
    orig_emb = STATE.sim.ads[STATE.sim.idx[ad_id]].emb
    return {"source": src, "original": {k: ad.get(k) for k in ("ad_id", "hook", "body", "cta", "offer", "tone", "angle")},
            "original_resonance": {STATE.names.get(c, str(c)): s for c, s in segments.resonance(orig_emb, targets).items()},
            "target_community": {"community_id": cid, "name": STATE.names.get(cid), "persona": persona},
            "diagnosis": diag["top"], "memory_used": memory, "variants": out}


class ExpReq(BaseModel):
    source_ad_id: str
    variant_ids: list[str]


def _creative(ad_id: str) -> dict:
    r = db.q("SELECT * FROM creatives WHERE ad_id=?", (ad_id,))
    if not r:
        raise HTTPException(404, ad_id)
    r = r[0]
    r["emb"] = db.unblob(r.pop("embedding"))
    return r


@router.post("/experiments")
def create_experiment(req: ExpReq):
    ctx = STATE.ctx
    src = ctx.ad(req.source_ad_id)
    camp = STATE.sim.campaigns[src["campaign_id"]]
    for v in req.variant_ids:
        c = _creative(v)
        if c["parent_ad_id"] != req.source_ad_id:
            raise HTTPException(400, f"{v} is not a variant of {req.source_ad_id}")
    d = ctx.ad_daily()
    last = d[(d.ad_id == req.source_ad_id) & (d.day > STATE.day - 7)]
    objective = camp["objective"]
    metric = exp_mod.choose_metric(objective, STATE.diagnosis(req.source_ad_id)["top"])
    base_rate = float((last.clicks.sum() if metric == "ctr" else last.conversions.sum()) / max(last.impressions.sum(), 1))
    set_ads = [a["ad_id"] for a in ctx.ads() if a["ad_set_id"] == src["ad_set_id"]]
    daily_imp = float(d[(d.ad_id.isin(set_ads)) & (d.day > STATE.day - 7)].groupby("day").impressions.sum().mean() or 0)
    if not daily_imp == daily_imp or daily_imp <= 0:  # NaN or no delivery yet
        daily_imp = 1000.0
    plan = exp_mod.plan(max(base_rate, 1e-4), metric, 1 + len(req.variant_ids), daily_imp)
    arms = [{"ad_id": req.source_ad_id, "changed_dimension": None, "hook": src.get("hook")}] + [
        {"ad_id": v, "changed_dimension": _creative(v)["changed_dimension"], "hook": _creative(v)["hook"]} for v in req.variant_ids]
    eid = db.x("INSERT INTO experiments(source_ad_id,arms,plan,sample_size,allocation_history,winner,status) VALUES (?,?,?,?,?,?,?)",
               (req.source_ad_id, json.dumps(arms), json.dumps(plan), plan["sample_size_per_arm"], "[]", None, "planned"))
    return {"id": eid, "arms": arms, "plan": plan, "objective": objective}


@router.get("/experiments")
def list_experiments():
    out = []
    for r in db.q("SELECT * FROM experiments ORDER BY id DESC"):
        r["arms"] = json.loads(r["arms"])
        r["plan"] = json.loads(r["plan"])
        r["allocation_history"] = json.loads(r["allocation_history"] or "[]")
        out.append(r)
    return out


@router.post("/experiments/{eid}/run")
async def run_experiment(eid: int):
    r = db.q("SELECT * FROM experiments WHERE id=?", (eid,))
    if not r:
        raise HTTPException(404)
    r = r[0]
    arms = json.loads(r["arms"])
    plan = json.loads(r["plan"])
    src = STATE.ctx.ad(r["source_ad_id"])
    variants = []
    for a in arms[1:]:
        c = _creative(a["ad_id"])
        variants.append({"ad_id": c["ad_id"], "emb": c["emb"], "tone": c["tone"], "offer": c["offer"], "hook": c["hook"], "body": c["body"], "cta": c["cta"], "angle": c["angle"]})
    with STATE.lock:
        gen = exp_mod.run(STATE.sim, r["source_ad_id"], variants, plan["metric"], seed=1000 + eid)
        days = list(gen)
    db.x("UPDATE experiments SET status='running' WHERE id=?", (eid,))

    async def stream():
        history = []
        for d in days:
            history.append(d)
            yield f"event: day\ndata: {json.dumps(d)}\n\n"
            await asyncio.sleep(0.45)
        last = days[-1]
        winner = last["winner"]
        db.x("UPDATE experiments SET allocation_history=?, winner=?, status='done' WHERE id=?", (json.dumps(history), winner, eid))
        # learning writer
        cid = src["targets"][0]
        ratios = {int(k): v for k, v in STATE.diagnosis(r["source_ad_id"])["raw"]["segment_ratios"].items()}
        if ratios:
            cid = min(ratios, key=ratios.get)
        pack = db.q("SELECT dominant_pack FROM communities WHERE community_id=?", (cid,))[0]["dominant_pack"]
        arm_rows = []
        for i, a in enumerate(arms):
            arm_rows.append({"ad_id": a["ad_id"], "changed_dimension": a["changed_dimension"] or "original", "hook": a["hook"],
                             "impressions": int(last["impressions"][i]), "clicks": int(last["clicks"][i]), "conversions": int(last["conversions"][i]),
                             "rate": float(last["rate"][i]), "p_best": float(last["p_best"][i])})
        summary = {"metric": plan["metric"], "arms": arm_rows, "winner_arm": next(a for a in arm_rows if a["ad_id"] == winner),
                   "community": STATE.names.get(cid), "days": last["day"]}
        learning, src_l = await asyncio.to_thread(write_learning, summary, STATE.names.get(cid, str(cid)), pack, STATE.day)
        db.x("UPDATE experiments SET learning_id=? WHERE id=?", (learning["id"], eid))
        yield f"event: done\ndata: {json.dumps({'winner': winner, 'summary': summary, 'learning': learning, 'learning_source': src_l})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/experiments/{eid}/apply")
def apply_winner(eid: int):
    r = db.q("SELECT * FROM experiments WHERE id=?", (eid,))
    if not r or not r[0]["winner"]:
        raise HTTPException(400, "experiment has no winner yet")
    r = r[0]
    w = r["winner"]
    with STATE.lock:
        if w != r["source_ad_id"]:
            c = _creative(w)
            if w not in STATE.sim.idx:
                STATE.sim.add_ad({**c, "status": "active"})
            else:
                STATE.sim.set_status(w, "active")
            STATE.sim.set_status(r["source_ad_id"], "paused")
            db.x("UPDATE creatives SET status='active' WHERE ad_id=?", (w,))
            db.x("UPDATE creatives SET status='paused' WHERE ad_id=?", (r["source_ad_id"],))
        STATE._radar = None
    db.x("UPDATE experiments SET status='applied' WHERE id=?", (eid,))
    STATE.broadcast("action", {"type": "creative_applied", "winner": w, "replaced": r["source_ad_id"]})
    return {"applied": w, "paused": r["source_ad_id"] if w != r["source_ad_id"] else None}

