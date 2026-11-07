from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app import db
from app.analytics import budget as budget_mod
from app.integrations import discord
from app.state import STATE

router = APIRouter(prefix="/api/budget")


def _row(r: dict) -> dict:
    r = dict(r)
    r["detail"] = json.loads(r["detail"]) if r["detail"] else {}
    return r


@router.get("/actions")
def actions():
    return [_row(r) for r in db.q("SELECT * FROM budget_actions ORDER BY id DESC")]


@router.post("/propose")
def propose():
    rows = STATE.radar()
    diags = {r["ad_id"]: STATE.diagnosis(r["ad_id"]) for r in rows if r["status"] in ("failing", "at_risk")}
    with STATE.lock:
        props = budget_mod.propose(STATE.ctx, rows, diags, STATE.names)
    open_sets = {(r["from_ad_set"], r["to_ad_set"]) for r in db.q("SELECT from_ad_set, to_ad_set FROM budget_actions WHERE status='proposed'")}
    created = []
    for p in props:
        if (p["from_ad_set"], p["to_ad_set"]) in open_sets:
            continue
        detail = {k: p[k] for k in ("cause", "ad_id", "wasted_without", "wasted_with", "eur_protected_sd", "revenue_delta", "days", "runs", "exclude_community") if k in p}
        aid = db.x("INSERT INTO budget_actions(day,from_ad_set,to_ad_set,amount,reason,status,eur_protected,detail) VALUES (?,?,?,?,?,?,?,?)",
                   (p["day"], p["from_ad_set"], p["to_ad_set"], p["amount"], p["reason"], "proposed", p["eur_protected"], json.dumps(detail)))
        row = _row(db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))[0])
        row["discord_sent"] = discord.post_proposal({**row, "revenue_delta": p["revenue_delta"]})
        created.append(row)
        STATE.broadcast("action", {"type": "proposed", "id": aid})
    return {"created": created, "considered": len(props)}


def _decide(aid: int, decision: str) -> dict:
    r = db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))
    if not r:
        raise HTTPException(404)
    r = _row(r[0])
    if r["status"] != "proposed":
        return r
    if decision == "approve":
        change = {"from_ad_set": r["from_ad_set"], "to_ad_set": r["to_ad_set"], "amount": r["amount"],
                  "exclude_community": r["detail"].get("exclude_community")}
        with STATE.lock:
            budget_mod.apply_change(STATE.sim, change)
            STATE._radar = None
        status = "approved"
    elif decision == "reject":
        status = "rejected"
    else:
        raise HTTPException(400, "decision must be approve or reject")
    db.x("UPDATE budget_actions SET status=? WHERE id=?", (status, aid))
    STATE.broadcast("action", {"type": status, "id": aid})
    return _row(db.q("SELECT * FROM budget_actions WHERE id=?", (aid,))[0])


@router.post("/actions/{aid}/approve")
def approve(aid: int, decision: str = "approve"):
    return _decide(aid, decision)


@router.get("/actions/{aid}/decide", response_class=HTMLResponse)
def decide_link(aid: int, decision: str):
    """Target of the Discord links (a tap on a phone opens this page)."""
    r = _decide(aid, decision)
    color = "#2d9d78" if r["status"] == "approved" else "#e34850"
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font-family:system-ui;background:#1d1d1d;color:#eee;padding:24px">
<h2 style="color:{color}">Proposal #{aid}: {r['status']}</h2><p>{r['reason']}</p>
<p>€ protected (7-day counterfactual): <b>€{r['eur_protected']:.0f}</b></p></body>"""
