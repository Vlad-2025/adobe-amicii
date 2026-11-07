"""World build: snapshot (or synthetic fallback) -> embeddings -> digital twins -> communities -> SQLite.

Run with `python run.py build-world`. Takes ~10-60 s on a laptop CPU depending on the embedder."""
from __future__ import annotations

import json
import logging
import time

import numpy as np
import pandas as pd

from app import db
from app.config import BLUESKY, DATA, SEED, SEED_RANDOM
from app.world import communities as comm
from app.world.embed import creative_text, get_embedder

log = logging.getLogger(__name__)
WORLD_NPZ = DATA / "world.npz"
TONES = ["witty", "energetic", "chill", "informative"]
MAX_POSTS_PER_USER = 20


def load_snapshot() -> dict:
    files = {k: BLUESKY / f"{k}.parquet" for k in ("accounts", "follows", "interactions", "posts")}
    if all(f.exists() for f in files.values()):
        d = {k: pd.read_parquet(f) for k, f in files.items()}
        meta_f = BLUESKY / "snapshot_meta.json"
        d["meta"] = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {"source": "bluesky"}
        d["meta"].setdefault("source", "bluesky")
        return d
    from app.world.synthetic import generate

    log.warning("No Bluesky snapshot in %s; using the synthetic graph", BLUESKY)
    return generate(SEED_RANDOM)


def build(profile_with_llm: bool = True) -> dict:
    t0 = time.time()
    rng = np.random.default_rng(SEED_RANDOM)
    snap = load_snapshot()
    accounts = snap["accounts"].reset_index(drop=True)
    posts = snap["posts"].copy()
    posts = posts[posts["user_id"].isin(set(accounts["user_id"]))]
    posts = posts.sort_values("ts").groupby("user_id", group_keys=False).tail(MAX_POSTS_PER_USER).reset_index(drop=True)
    # accounts with no posts cannot be modeled
    has_posts = accounts["user_id"].isin(set(posts["user_id"]))
    accounts = accounts[has_posts].reset_index(drop=True)
    if "source_pack" not in accounts:
        accounts["source_pack"] = "unknown"

    emb = get_embedder(fresh=True)
    log.info("Embedding %d posts with %s", len(posts), emb.kind)
    post_emb = emb.embed(posts["text"].astype(str).tolist())

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

    labels, method, nmi = comm.detect(accounts, snap["follows"], snap["interactions"], interest, SEED_RANDOM)
    k = int(labels.max()) + 1
    desc = comm.describe(accounts, posts, labels, post_emb, interest)

    # Price sensitivity: per-community mean, then per-user noise, clipped to [0.2, 0.9]
    comm_price = rng.uniform(0.3, 0.75, k)
    price = np.clip(comm_price[labels] + rng.normal(0, 0.1, n), 0.2, 0.9)
    tone_pref = rng.normal(0, 1, (k, len(TONES)))
    # prime-time fit: how much of the user's activity falls in typical ad delivery hours (7-23)
    prime = hour_hist[:, 7:24].sum(1)

    with db.tx() as c:
        for t in ("accounts", "follows", "interactions", "posts", "communities", "campaigns", "ad_sets", "creatives", "memory"):
            c.execute(f"DELETE FROM {t}")
        c.executemany(
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?)",
            [(accounts["user_id"][i], accounts["source_pack"][i], db.blob(interest[i]), float(activity[i]),
              json.dumps(hour_hist[i].round(3).tolist()), float(price[i]), int(labels[i])) for i in range(n)],
        )
        c.executemany("INSERT INTO follows VALUES (?,?,?)", snap["follows"][["src", "dst", "weight"]].itertuples(index=False, name=None))
        c.executemany("INSERT INTO interactions VALUES (?,?,?)", snap["interactions"][["src", "dst", "weight"]].itertuples(index=False, name=None))
        c.executemany(
            "INSERT INTO posts VALUES (?,?,?,?)",
            [(posts["user_id"][i], posts["text"][i], str(posts["ts"][i]), db.blob(post_emb[i])) for i in range(len(posts))],
        )
        for d in desc:
            c.execute(
                "INSERT INTO communities VALUES (?,?,?,?,?,?,?,?,?)",
                (d["community_id"], d["size"], json.dumps(d["keywords"]), None, json.dumps(d["central_posts"]),
                 json.dumps(d["hours"]), d["dominant_pack"], json.dumps(d["pack_share"]), nmi),
            )

    _seed_config(desc, emb)

    np.savez_compressed(
        WORLD_NPZ,
        interest=interest, activity=activity.astype(np.float32), hour_hist=hour_hist, price=price.astype(np.float32),
        labels=labels.astype(np.int32), tone_pref=tone_pref.astype(np.float32), prime=prime.astype(np.float32),
        centroids=np.stack([d["centroid"] for d in desc]),
    )
    db.kv_set("world_meta", {
        "source": snap["meta"].get("source"), "embedder": emb.kind, "community_method": method, "nmi_vs_seed": nmi,
        "accounts": n, "posts": int(len(posts)), "communities": k, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    if profile_with_llm:
        from app.llm.agents import profile_all_communities

        profile_all_communities()
    log.info("World built in %.1fs: %d accounts, %d communities (%s, NMI %.2f)", time.time() - t0, n, k, method, nmi or 0)
    return db.kv_get("world_meta")


def _seed_config(desc: list[dict], emb) -> None:
    seed = json.loads((SEED / "campaigns.json").read_text(encoding="utf-8"))
    cents = np.stack([d["centroid"] for d in desc])
    pack_names = {
        "coffee": "coffee espresso beans cafe", "students": "students exams studying university", "gym": "gym workout training lifting",
        "remote_work": "remote work meetings home office", "tech": "software code programming developers",
        "creators": "content creators video design", "gaming": "video games gaming streaming",
    }
    with db.tx() as c:
        for cp in seed["campaigns"]:
            c.execute("INSERT INTO campaigns VALUES (?,?,?,?,?,?)", (cp["campaign_id"], cp["name"], cp["objective"], cp["max_cpa"], cp["min_roas"], cp["total_budget"]))
        for a in seed["ad_sets"]:
            targets = [d["community_id"] for d in desc if d["dominant_pack"] in a["target_packs"]]
            missing = [p for p in a["target_packs"] if p not in {d["dominant_pack"] for d in desc}]
            for p in missing:  # real data: pick the community closest to the pack description
                v = emb.embed([pack_names.get(p, p)])[0]
                targets.append(int(np.argmax(cents @ v)))
            targets = sorted(set(targets))
            c.execute("INSERT INTO ad_sets VALUES (?,?,?,?,?)", (a["ad_set_id"], a["campaign_id"], a["name"], a["daily_budget"], json.dumps(targets)))
        texts = [creative_text(cr) for cr in seed["creatives"]]
        vecs = emb.embed(texts)
        for cr, v in zip(seed["creatives"], vecs):
            c.execute(
                "INSERT INTO creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cr["ad_id"], cr["ad_set_id"], cr["hook"], cr["body"], cr["cta"], cr["offer"], cr["tone"], cr["angle"], db.blob(v), None, "active", None, None),
            )
        mem = json.loads((SEED / "memory.json").read_text(encoding="utf-8"))
        mv = emb.embed([m["insight"] for m in mem])
        for m, v in zip(mem, mv):
            c.execute(
                "INSERT INTO memory(brand,insight,evidence,applies_to,winner,embedding,created_day) VALUES (?,?,?,?,?,?,?)",
                ("Volt", m["insight"], m["evidence"], json.dumps(m["applies_to"]), int(m["winner"]), db.blob(v), m["created_day"]),
            )


def load_world() -> dict:
    if not WORLD_NPZ.exists():
        raise FileNotFoundError("World not built. Run: python run.py build-world")
    z = np.load(WORLD_NPZ)
    return {k: z[k] for k in z.files}
