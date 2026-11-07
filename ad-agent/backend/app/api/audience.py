from __future__ import annotations

import json

import numpy as np
from fastapi import APIRouter

from app import db
from app.state import STATE

router = APIRouter(prefix="/api")
MAX_NODES = 1200
MAX_EDGES = 5000


@router.get("/communities")
def communities():
    comms = []
    for r in db.q("SELECT * FROM communities ORDER BY community_id"):
        comms.append({
            "community_id": r["community_id"], "size": r["size"], "keywords": json.loads(r["keywords"]),
            "persona": json.loads(r["persona"]) if r["persona"] else None, "central_posts": json.loads(r["central_posts"]),
            "hours": json.loads(r["hours"]), "dominant_pack": r["dominant_pack"], "pack_share": json.loads(r["pack_share"]),
            "name": STATE.names.get(r["community_id"]),
        })
    acc = db.q("SELECT user_id, community_id, activity FROM accounts")
    rng = np.random.default_rng(0)
    idx = rng.choice(len(acc), min(MAX_NODES, len(acc)), replace=False)
    keep = {acc[i]["user_id"]: i for i in idx}
    nodes = [{"id": str(i), "c": acc[i]["community_id"], "a": round(acc[i]["activity"], 2)} for i in idx]
    edges = []
    for e in db.q("SELECT src, dst FROM follows"):
        if e["src"] in keep and e["dst"] in keep:
            edges.append({"source": str(keep[e["src"]]), "target": str(keep[e["dst"]])})
    if len(edges) > MAX_EDGES:
        sel = rng.choice(len(edges), MAX_EDGES, replace=False)
        edges = [edges[i] for i in sel]
    meta = db.kv_get("world_meta", {})
    return {"communities": comms, "graph": {"nodes": nodes, "links": edges}, "meta": meta}
