from __future__ import annotations

import json

import numpy as np
from fastapi import APIRouter

from app import db, registry
from app.api.deps import rt

router = APIRouter(prefix="/api/ch/{ch}")
MAX_NODES = 1200
MAX_EDGES = 5000


@router.get("/communities")
def communities(ch: str):
    r = rt(ch)
    info = registry.channel(ch)
    aud = info["config"]["audience"]
    comms = []
    for x in db.q("SELECT * FROM communities WHERE channel_id=? ORDER BY community_id", (ch,)):
        comms.append({
            "community_id": x["community_id"], "size": x["size"], "keywords": json.loads(x["keywords"]),
            "persona": json.loads(x["persona"]) if x["persona"] else None, "central_posts": json.loads(x["central_posts"]),
            "hours": json.loads(x["hours"]), "dominant_pack": x["dominant_pack"], "pack_share": json.loads(x["pack_share"]),
            "name": r.names.get(x["community_id"]), "segment_definition": x["label"],
        })
    graph = None
    if aud["type"] == "bluesky":  # only an open network gives you a follow graph
        acc = db.q("SELECT user_id, community_id, activity FROM accounts WHERE channel_id=?", (ch,))
        rng = np.random.default_rng(0)
        idx = rng.choice(len(acc), min(MAX_NODES, len(acc)), replace=False)
        keep = {acc[i]["user_id"]: i for i in idx}
        nodes = [{"id": str(i), "c": acc[i]["community_id"], "a": round(acc[i]["activity"], 2)} for i in idx]
        edges = [{"source": str(keep[e["src"]]), "target": str(keep[e["dst"]])}
                 for e in db.q("SELECT src, dst FROM follows WHERE channel_id=?", (ch,)) if e["src"] in keep and e["dst"] in keep]
        if len(edges) > MAX_EDGES:
            sel = rng.choice(len(edges), MAX_EDGES, replace=False)
            edges = [edges[i] for i in sel]
        graph = {"nodes": nodes, "links": edges}
    source = None
    if aud["type"] == "bluesky" and aud.get("source"):
        try:
            source = registry.channel(aud["source"])
            source = {"channel_id": source["channel_id"], "platform": source["platform"], "handle": source["handle"]}
        except KeyError:
            pass
    return {"communities": comms, "graph": graph, "audience_type": aud["type"], "audience_source": source,
            "meta": db.kv_get(f"world_meta:{ch}", {})}
