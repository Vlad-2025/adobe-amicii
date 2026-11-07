from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db
from app.analytics import experiments as exp_mod
from app.analytics import segments
from app.api.deps import company_cfg, rt
from app.llm.agents import generate_variants, retrieve_memory, write_learning
from app.state import STATE

router = APIRouter(prefix="/api/ch/{ch}")


class VariantReq(BaseModel):
    community_id: int | None = None


def _persona(ch: str, cid: int, names: dict) -> tuple[dict, list[str], str | None]:
    r = db.q("SELECT persona, keywords, dominant_pack FROM communities WHERE channel_id=? AND community_id=?", (ch, cid))[0]
    return (json.loads(r["persona"]) if r["persona"] else {"name": names.get(cid)}), json.loads(r["keywords"]), r["dominant_pack"]


@router.post("/creatives/{ad_id}/variants")
async def variants(ch: str, ad_id: str, req: VariantReq | None = None):
    r = rt(ch)
    try:
        ad = r.ctx.ad(ad_id)
    except StopIteration:
        raise HTTPException(404, ad_id)
    diag = r.diagnosis(ad_id)
    targets = ad["targets"]
    cid = req.community_id if req and req.community_id is not None else None
    if cid is None:
        ratios = {int(k): v for k, v in diag["raw"]["segment_ratios"].items()}
        cid = min(ratios, key=ratios.get) if ratios else targets[0]
    persona, keywords, pack = _persona(ch, cid, r.names)
    memory = retrieve_memory(r.company_id, f"{persona.get('name')} {persona.get('one_liner', '')} {diag['top']}", pack)
    vs, src = await asyncio.to_thread(generate_variants, ad, diag, persona, keywords, memory, company_cfg(r), r.platform)
    out = []
    n0 = db.q("SELECT COUNT(*) AS n FROM creatives WHERE channel_id=? AND parent_ad_id=?", (ch, ad_id))[0]["n"]
    for i, v in enumerate(vs):
        vid = f"{ad_id}-v{n0 + i + 1}"
        res = segments.resonance(ch, v["emb"], targets)
        db.x("INSERT INTO creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (ch, vid, ad["ad_set_id"], v["hook"], v["body"], v["cta"], v.get("offer") or "none", ad["tone"], ad.get("angle"),
              db.blob(v["emb"]), ad_id, "draft", v["changed_dimension"], v["hypothesis"]))
        out.append({"ad_id": vid, **{k: v[k] for k in ("changed_dimension", "hook", "body", "cta", "offer", "hypothesis", "expected_effect", "similarity_to_original", "guard")},
                    "resonance": {r.names.get(c, str(c)): s for c, s in res.items()}})
    orig_emb = r.sim.ads[r.sim.idx[ad_id]].emb
    return {"source": src, "original": {k: ad.get(k) for k in ("ad_id", "hook", "body", "cta", "offer", "tone", "angle")},
            "original_resonance": {r.names.get(c, str(c)): s for c, s in segments.resonance(ch, orig_emb, targets).items()},
            "target_community": {"community_id": cid, "name": r.names.get(cid), "persona": persona},
            "diagnosis": diag["top"], "memory_used": memory, "variants": out}


class ExpReq(BaseModel):
    source_ad_id: str
    variant_ids: list[str]


def _creative(ch: str, ad_id: str) -> dict:
    x = db.q("SELECT * FROM creatives WHERE channel_id=? AND ad_id=?", (ch, ad_id))
    if not x:
        raise HTTPException(404, ad_id)
    x = x[0]
    x["emb"] = db.unblob(x.pop("embedding"))
    return x


@router.post("/experiments")
def create_experiment(ch: str, req: ExpReq):
    r = rt(ch)
    src = r.ctx.ad(req.source_ad_id)
    camp = r.sim.campaigns[src["campaign_id"]]
    for v in req.variant_ids:
        if _creative(ch, v)["parent_ad_id"] != req.source_ad_id:
            raise HTTPException(400, f"{v} is not a variant of {req.source_ad_id}")
    d = r.ctx.ad_daily()
    last = d[(d.ad_id == req.source_ad_id) & (d.day > r.day - 7)]
    metric = exp_mod.choose_metric(camp["objective"], r.diagnosis(req.source_ad_id)["top"])
    base_rate = float((last.clicks.sum() if metric == "ctr" else last.conversions.sum()) / max(last.impressions.sum(), 1))
    set_ads = [a["ad_id"] for a in r.ctx.ads() if a["ad_set_id"] == src["ad_set_id"]]
    daily_imp = float(d[(d.ad_id.isin(set_ads)) & (d.day > r.day - 7)].groupby("day").impressions.sum().mean() or 0)
    if not daily_imp == daily_imp or daily_imp <= 0:
        daily_imp = 1000.0
    plan = exp_mod.plan(max(base_rate, 1e-4), metric, 1 + len(req.variant_ids), daily_imp)
    arms = [{"ad_id": req.source_ad_id, "changed_dimension": None, "hook": src.get("hook")}] + [
        {"ad_id": v, "changed_dimension": _creative(ch, v)["changed_dimension"], "hook": _creative(ch, v)["hook"]} for v in req.variant_ids]
    eid = db.x("INSERT INTO experiments(channel_id,source_ad_id,arms,plan,sample_size,allocation_history,winner,status) VALUES (?,?,?,?,?,?,?,?)",
               (ch, req.source_ad_id, json.dumps(arms), json.dumps(plan), plan["sample_size_per_arm"], "[]", None, "planned"))
    return {"id": eid, "arms": arms, "plan": plan, "objective": camp["objective"]}


@router.get("/experiments")
def list_experiments(ch: str):
    out = []
    for x in db.q("SELECT * FROM experiments WHERE channel_id=? ORDER BY id DESC", (ch,)):
        x["arms"] = json.loads(x["arms"])
        x["plan"] = json.loads(x["plan"])
        x["allocation_history"] = json.loads(x["allocation_history"] or "[]")
        out.append(x)
    return out


@router.post("/experiments/{eid}/run")
async def run_experiment(ch: str, eid: int):
    r = rt(ch)
    e = db.q("SELECT * FROM experiments WHERE channel_id=? AND id=?", (ch, eid))
    if not e:
        raise HTTPException(404)
    e = e[0]
    arms = json.loads(e["arms"])
    plan = json.loads(e["plan"])
    src = r.ctx.ad(e["source_ad_id"])
    variants = []
    for a in arms[1:]:
        c = _creative(ch, a["ad_id"])
        variants.append({k: c[k] for k in ("ad_id", "emb", "tone", "offer", "hook", "body", "cta", "angle")})
    with STATE.lock:
        days = list(exp_mod.run(r.sim, e["source_ad_id"], variants, plan["metric"], seed=1000 + eid))
    db.x("UPDATE experiments SET status='running' WHERE id=?", (eid,))
    cfg = company_cfg(r)

    async def stream():
        for d in days:
            yield f"event: day\ndata: {json.dumps(d)}\n\n"
            await asyncio.sleep(0.45)
        last = days[-1]
        winner = last["winner"]
        db.x("UPDATE experiments SET allocation_history=?, winner=?, status='done' WHERE id=?", (json.dumps(days), winner, eid))
        cid = src["targets"][0]
        ratios = {int(k): v for k, v in r.diagnosis(e["source_ad_id"])["raw"]["segment_ratios"].items()}
        if ratios:
            cid = min(ratios, key=ratios.get)
        pack = db.q("SELECT dominant_pack FROM communities WHERE channel_id=? AND community_id=?", (ch, cid))[0]["dominant_pack"]
        arm_rows = [{"ad_id": a["ad_id"], "changed_dimension": a["changed_dimension"] or "original", "hook": a["hook"],
                     "impressions": int(last["impressions"][i]), "clicks": int(last["clicks"][i]), "conversions": int(last["conversions"][i]),
                     "rate": float(last["rate"][i]), "p_best": float(last["p_best"][i])} for i, a in enumerate(arms)]
        summary = {"metric": plan["metric"], "arms": arm_rows, "winner_arm": next(a for a in arm_rows if a["ad_id"] == winner),
                   "community": r.names.get(cid), "days": last["day"]}
        learning, src_l = await asyncio.to_thread(write_learning, summary, r.names.get(cid, str(cid)), pack, r.day, r.company_id, ch, cfg["brand"])
        db.x("UPDATE experiments SET learning_id=? WHERE id=?", (learning["id"], eid))
        yield f"event: done\ndata: {json.dumps({'winner': winner, 'summary': summary, 'learning': learning, 'learning_source': src_l})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/experiments/{eid}/apply")
def apply_winner(ch: str, eid: int):
    r = rt(ch)
    e = db.q("SELECT * FROM experiments WHERE channel_id=? AND id=?", (ch, eid))
    if not e or not e[0]["winner"]:
        raise HTTPException(400, "experiment has no winner yet")
    e = e[0]
    w = e["winner"]
    with STATE.lock:
        if w != e["source_ad_id"]:
            c = _creative(ch, w)
            if w not in r.sim.idx:
                r.sim.add_ad({**c, "status": "active"})
            else:
                r.sim.set_status(w, "active")
            r.sim.set_status(e["source_ad_id"], "paused")
            db.x("UPDATE creatives SET status='active' WHERE channel_id=? AND ad_id=?", (ch, w))
            db.x("UPDATE creatives SET status='paused' WHERE channel_id=? AND ad_id=?", (ch, e["source_ad_id"]))
        r.invalidate()
    db.x("UPDATE experiments SET status='applied' WHERE id=?", (eid,))
    STATE.broadcast("action", {"type": "creative_applied", "channel_id": ch, "winner": w, "replaced": e["source_ad_id"]})
    return {"applied": w, "paused": e["source_ad_id"] if w != e["source_ad_id"] else None}
