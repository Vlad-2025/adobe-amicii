from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app import db
from app.analytics import budget as budget_mod
from app.api.deps import rt
from app.integrations import discord
from app.state import STATE

router = APIRouter(prefix="/api/ch/{ch}/budget")
link_router = APIRouter(prefix="/api/budget")


def _row(r: dict) -> dict:
    r = dict(r)
    r["detail"] = json.loads(r["detail"]) if r["detail"] else {}
    return r


@router.get("/actions")
def actions(ch: str):
    return [_row(r) for r in db.q("SELECT * FROM budget_actions WHERE channel_id=? ORDER BY id DESC", (ch,))]


@router.post("/propose")
def propose(ch: str):
    r = rt(ch)
    rows = r.radar()
    diags = {x["ad_id"]: r.diagnosis(x["ad_id"]) for x in rows if x["status"] in ("failing", "at_risk")}
    with STATE.lock:
        props = budget_mod.propose(r.ctx, rows, diags, r.names)
    open_sets = {(x["from_ad_set"], x["to_ad_set"]) for x in db.q("SELECT from_ad_set, to_ad_set FROM budget_actions WHERE channel_id=? AND status='proposed'", (ch,))}
    created = []
    for p in props:
        if (p["from_ad_set"], p["to_ad_set"]) in open_sets:
            continue
        detail = {k: p[k] for k in ("cause", "ad_id", "wasted_without", "wasted_with", "eur_protected_sd", "revenue_delta", "days", "runs", "exclude_community") if k in p}
        aid = db.x("INSERT INTO budget_actions(channel_id,day,from_ad_set,to_ad_set,amount,reason,status,eur_protected,detail) VALUES (?,?,?,?,?,?,?,?,?)",
                   (ch, p["day"], p["from_ad_set"], p["to_ad_set"], p["amount"], p["reason"], "proposed", p["eur_protected"], json.dumps(detail)))
        row = _row(db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))[0])
        row["discord_sent"] = discord.post_proposal({**row, "revenue_delta": p["revenue_delta"]})
        created.append(row)
        STATE.broadcast("action", {"type": "proposed", "channel_id": ch, "id": aid})
    return {"created": created, "considered": len(props)}


def decide(aid: int, decision: str) -> dict:
    x = db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))
    if not x:
        raise HTTPException(404)
    x = _row(x[0])
    if x["status"] != "proposed":
        return x
    if decision == "approve":
        r = rt(x["channel_id"])
        change = {"from_ad_set": x["from_ad_set"], "to_ad_set": x["to_ad_set"], "amount": x["amount"], "exclude_community": x["detail"].get("exclude_community")}
        with STATE.lock:
            budget_mod.apply_change(r.sim, change)
            r.invalidate()
        status = "approved"
    elif decision == "reject":
        status = "rejected"
    else:
        raise HTTPException(400, "decision must be approve or reject")
    db.x("UPDATE budget_actions SET status=? WHERE id=?", (status, aid))
    STATE.broadcast("action", {"type": status, "channel_id": x["channel_id"], "id": aid})
    return _row(db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))[0])


@router.post("/actions/{aid}/approve")
def approve(ch: str, aid: int, decision: str = "approve"):
    return decide(aid, decision)


@link_router.get("/actions/{aid}/decide", response_class=HTMLResponse)
def decide_link(aid: int, decision: str):
    """Target of the Discord links (a tap on a phone opens this page)."""
    r = decide(aid, decision)
    color = "#2d9d78" if r["status"] == "approved" else "#e34850"
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font-family:system-ui;background:#1d1d1d;color:#eee;padding:24px">
<h2 style="color:{color}">Proposal #{aid}: {r['status']}</h2><p>{r['reason']}</p>
<p>€ protected (7-day counterfactual): <b>€{r['eur_protected']:.0f}</b></p></body>"""
