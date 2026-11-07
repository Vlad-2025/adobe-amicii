"""World build, per ads channel:
audience (Bluesky snapshot / synthetic segments) -> embeddings -> digital twins -> communities -> SQLite.

Bluesky-backed channels: real accounts from the snapshot (filtered to the channel's packs), communities
found with Leiden on the real follow graph. Segment-backed channels (Meta, TikTok, LinkedIn, X): the
platform only reports aggregates per targeting segment, so each segment is one community and its
twins are synthetic, with synthetic posts standing in for social-listening samples."""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import pandas as pd

from app import db, registry
from app.config import BLUESKY, DATA, SEED_RANDOM
from app.world import communities as comm
from app.world.embed import creative_text, get_embedder

log = logging.getLogger(__name__)
WORLDS = DATA / "worlds"
MAX_POSTS_PER_USER = 20
RESONANCE_SAMPLE = 800  # post embeddings kept per community for the resonance score


def world_path(ch: str):
    return WORLDS / f"{ch}.npz"


_snapshot_cache: dict | None = None


def _bluesky_snapshot() -> dict | None:
    global _snapshot_cache
    files = {k: BLUESKY / f"{k}.parquet" for k in ("accounts", "follows", "interactions", "posts")}
    if not all(f.exists() for f in files.values()):
        return None
    if _snapshot_cache is None:
        _snapshot_cache = {k: pd.read_parquet(f) for k, f in files.items()}
    return _snapshot_cache


def load_audience(ch: str, cfg: dict) -> dict:
    aud = cfg["audience"]
    packs = aud["packs"]
    if aud["type"] == "bluesky":
        snap = _bluesky_snapshot()
        if snap is not None:
            acc = snap["accounts"][snap["accounts"]["source_pack"].isin(list(packs))].reset_index(drop=True)
            if len(acc) >= 100:
                ids = set(acc["user_id"])
                return {"accounts": acc,
                        "follows": snap["follows"][snap["follows"]["src"].isin(ids) & snap["follows"]["dst"].isin(ids)],
                        "interactions": snap["interactions"][snap["interactions"]["src"].isin(ids) & snap["interactions"]["dst"].isin(ids)],
                        "posts": snap["posts"][snap["posts"]["user_id"].isin(ids)], "meta": {"source": "bluesky"}}
        log.warning("%s: no Bluesky snapshot for packs %s; using the synthetic graph", ch, list(packs))
    from app.world.synthetic import generate

    salt = aud.get("source", ch)
    d = generate(packs, seed=SEED_RANDOM, salt=salt)
    d["meta"]["source"] = "synthetic" if aud["type"] == "bluesky" else "synthetic-segments"
    return d


def _embed_dedup(emb, texts: list[str]) -> np.ndarray:
    uniq, inv = np.unique(np.asarray(texts, dtype=object), return_inverse=True)
    vecs = emb.embed([str(t) for t in uniq])
    return vecs[inv]


def build_channel(ch: str, profile_with_llm: bool = True) -> dict:
    t0 = time.time()
    rng = np.random.default_rng(SEED_RANDOM)
    chrow = registry.channel(ch)
    cfg = chrow["config"]
    aud_type = cfg["audience"]["type"]
    snap = load_audience(ch, cfg)
    accounts = snap["accounts"].reset_index(drop=True)
    posts = snap["posts"].copy()
    posts = posts[posts["user_id"].isin(set(accounts["user_id"]))]
    posts = posts.sort_values("ts").groupby("user_id", group_keys=False).tail(MAX_POSTS_PER_USER).reset_index(drop=True)
    accounts = accounts[accounts["user_id"].isin(set(posts["user_id"]))].reset_index(drop=True)
    if "source_pack" not in accounts:
        accounts["source_pack"] = "unknown"

    emb = get_embedder()
    post_emb = _embed_dedup(emb, posts["text"].astype(str).tolist())
    uidx = {u: i for i, u in enumerate(accounts["user_id"])}
    pu = posts["user_id"].map(uidx).to_numpy()
    n = len(accounts)
    interest = np.zeros((n, post_emb.shape[1]), np.float32)
    np.add.at(interest, pu, post_emb)
    interest /= np.linalg.norm(interest, axis=1, keepdims=True) + 1e-8
    counts = np.bincount(pu, minlength=n).astype(float)
    activity = 0.2 + 0.8 * (counts - counts.min()) / max(counts.max() - counts.min(), 1)
    hours = pd.to_datetime(posts["ts"], utc=True).dt.hour.to_numpy()
    hour_hist = np.zeros((n, 24), np.float32)
    np.add.at(hour_hist, (pu, hours), 1)
    hour_hist /= np.maximum(hour_hist.sum(1, keepdims=True), 1)

    if aud_type == "segments":  # the platform defines the segments: one community per targeting segment
        order = list(accounts["source_pack"].value_counts().index)
        labels = accounts["source_pack"].map({p: i for i, p in enumerate(order)}).to_numpy()
        method, nmi = "platform segments", None
    else:
        labels, method, nmi = comm.detect(accounts, snap["follows"], snap["interactions"], interest, SEED_RANDOM)
    k = int(labels.max()) + 1
    desc = comm.describe(accounts, posts, labels, post_emb, interest)
    seg_labels = cfg["audience"].get("labels", {})

    comm_price = rng.uniform(0.3, 0.75, k)
    price = np.clip(comm_price[labels] + rng.normal(0, 0.1, n), 0.2, 0.9)
    tone_pref = rng.normal(0, 1, (k, 4))
    prime = hour_hist[:, 7:24].sum(1)

    # resonance sample: up to RESONANCE_SAMPLE post embeddings per community
    plab = labels[pu]
    sample_idx = []
    for c in range(k):
        idx = np.flatnonzero(plab == c)
        if len(idx) > RESONANCE_SAMPLE:
            idx = rng.choice(idx, RESONANCE_SAMPLE, replace=False)
        sample_idx.append(idx)
    sample_idx = np.concatenate(sample_idx)

    db.delete_world(ch)
    with db.tx() as c:
        c.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)",
                      [(ch, accounts["user_id"][i], accounts["source_pack"][i], None, float(activity[i]),
                        json.dumps(hour_hist[i].round(3).tolist()), float(price[i]), int(labels[i])) for i in range(n)])
        c.executemany("INSERT INTO follows VALUES (?,?,?,?)", [(ch, *r) for r in snap["follows"][["src", "dst", "weight"]].itertuples(index=False, name=None)])
        c.executemany("INSERT INTO interactions VALUES (?,?,?,?)", [(ch, *r) for r in snap["interactions"][["src", "dst", "weight"]].itertuples(index=False, name=None)])
        c.executemany("INSERT INTO posts VALUES (?,?,?,?,?)", [(ch, posts["user_id"][i], posts["text"][i], str(posts["ts"][i]), None) for i in range(len(posts))])
        for d in desc:
            label = seg_labels.get(d["dominant_pack"]) if aud_type == "segments" else None
            c.execute("INSERT INTO communities VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (ch, d["community_id"], d["size"], json.dumps(d["keywords"]), None, json.dumps(d["central_posts"]),
                       json.dumps(d["hours"]), d["dominant_pack"], json.dumps(d["pack_share"]), nmi, label))
    _seed_config(ch, cfg, desc, emb)

    WORLDS.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(world_path(ch), interest=interest, activity=activity.astype(np.float32), hour_hist=hour_hist,
                        price=price.astype(np.float32), labels=labels.astype(np.int32), tone_pref=tone_pref.astype(np.float32),
                        prime=prime.astype(np.float32), centroids=np.stack([d["centroid"] for d in desc]),
                        sample_emb=post_emb[sample_idx].astype(np.float32), sample_lab=plab[sample_idx].astype(np.int32))
    meta = {"source": snap["meta"].get("source"), "audience_type": aud_type, "embedder": emb.kind, "community_method": method,
            "nmi_vs_seed": nmi, "accounts": n, "posts": int(len(posts)), "communities": k, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    db.kv_set(f"world_meta:{ch}", meta)
    if profile_with_llm:
        from app.llm.agents import profile_all_communities

        profile_all_communities(ch)
    log.info("%s built in %.1fs: %d accounts, %d communities (%s)", ch, time.time() - t0, n, k, method)
    return meta


def _seed_config(ch: str, cfg: dict, desc: list[dict], emb) -> None:
    cents = np.stack([d["centroid"] for d in desc])
    with db.tx() as c:
        for cp in cfg["campaigns"]:
            c.execute("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)", (ch, cp["campaign_id"], cp["name"], cp["objective"], cp["max_cpa"], cp["min_roas"], cp["total_budget"]))
        present = {d["dominant_pack"] for d in desc}
        for a in cfg["ad_sets"]:
            targets = [d["community_id"] for d in desc if d["dominant_pack"] in a["target_packs"]]
            for p in [p for p in a["target_packs"] if p not in present]:  # real data: closest community to the pack name
                v = emb.embed([p.replace("_", " ")])[0]
                targets.append(int(np.argmax(cents @ v)))
            c.execute("INSERT INTO ad_sets VALUES (?,?,?,?,?,?)", (ch, a["ad_set_id"], a["campaign_id"], a["name"], a["daily_budget"], json.dumps(sorted(set(targets)))))
        vecs = emb.embed([creative_text(cr) for cr in cfg["creatives"]])
        for cr, v in zip(cfg["creatives"], vecs):
            c.execute("INSERT INTO creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (ch, cr["ad_id"], cr["ad_set_id"], cr["hook"], cr["body"], cr["cta"], cr["offer"], cr["tone"], cr["angle"], db.blob(v), None, "active", None, None))


def seed_memory(cid: str) -> None:
    co = registry.company(cid)
    mem = co["config"].get("memory", [])
    db.x("DELETE FROM memory WHERE company_id=?", (cid,))
    if not mem:
        return
    vecs = get_embedder().embed([m["insight"] for m in mem])
    for m, v in zip(mem, vecs):
        db.x("INSERT INTO memory(company_id,brand,insight,evidence,applies_to,winner,embedding,created_day,channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
             (cid, co["name"], m["insight"], m["evidence"], json.dumps(m["applies_to"]), int(m["winner"]), db.blob(v), m["created_day"], None))


def build_all(profile_with_llm: bool = True) -> list[dict]:
    from app.world.embed import get_embedder as ge

    registry.seed_companies(force=True)
    ge(fresh=True)  # choose the best available embedder once for the whole build and pin it
    out = []
    for co in registry.companies():
        seed_memory(co["company_id"])
        for ch in co["channels"]:
            if ch["kind"] == "ads" and ch["mode"] == "simulated":
                out.append({"channel": ch["channel_id"], **build_channel(ch["channel_id"], profile_with_llm)})
    return out


def load_world(ch: str) -> dict:
    p = world_path(ch)
    if not p.exists():
        raise FileNotFoundError(f"World for {ch} not built. Run: python run.py build-world")
    z = np.load(p)
    return {k: z[k] for k in z.files}
