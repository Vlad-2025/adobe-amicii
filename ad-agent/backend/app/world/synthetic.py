"""Synthetic fallback with the same schema as the Bluesky snapshot.

Used when data/bluesky/*.parquet is missing (no network, crawl failed). Accounts are
grouped by the starter pack they came from; posts are generated from per-pack topic
phrases, with some cross-topic noise so communities overlap like real ones do."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

PACK_SIZES = {
    "coffee": 430,
    "students": 300,
    "gym": 380,
    "remote_work": 420,
    "tech": 230,
    "creators": 450,
    "gaming": 400,
}

TOPICS = {
    "coffee": {
        "nouns": ["pour over", "espresso", "cold brew", "oat milk latte", "single origin beans", "grinder", "V60", "aeropress", "flat white", "roastery", "crema", "barista"],
        "verbs": ["dialed in", "brewed", "tasted", "roasted", "ground", "pulled a shot of"],
    },
    "students": {
        "nouns": ["exam", "thesis", "lecture", "library", "deadline", "group project", "flashcards", "finals week", "dorm", "midterm", "study session", "essay"],
        "verbs": ["survived", "pulled an all-nighter for", "procrastinated on", "finished", "submitted", "crammed for"],
    },
    "gym": {
        "nouns": ["leg day", "deadlift", "squat PR", "pre-workout", "protein shake", "bench press", "cardio", "rest day", "hypertrophy block", "gym bag", "pull-ups", "5k run"],
        "verbs": ["hit", "crushed", "skipped", "added weight to", "finished", "started"],
    },
    "remote_work": {
        "nouns": ["standup", "zoom call", "home office", "async update", "slack thread", "focus block", "coworking space", "laptop stand", "calendar", "afternoon slump", "deep work", "inbox zero"],
        "verbs": ["survived", "blocked out", "rescheduled", "cleared", "muted", "finished"],
    },
    "tech": {
        "nouns": ["pull request", "rust compiler", "kubernetes cluster", "CI pipeline", "side project", "open source repo", "typescript types", "database migration", "code review", "production bug", "LLM agent", "release"],
        "verbs": ["shipped", "debugged", "refactored", "deployed", "merged", "benchmarked"],
    },
    "creators": {
        "nouns": ["video edit", "thumbnail", "podcast episode", "newsletter", "brand deal", "content calendar", "camera setup", "illustration", "livestream", "short-form clip", "portfolio", "photo shoot"],
        "verbs": ["posted", "edited", "launched", "recorded", "planned", "sketched"],
    },
    "gaming": {
        "nouns": ["boss fight", "ranked match", "speedrun", "co-op night", "patch notes", "indie game", "controller", "raid", "save file", "open world", "build guide", "late-night session"],
        "verbs": ["beat", "grinded", "lost", "finally cleared", "streamed", "replayed"],
    },
}


def _hash(s: str) -> str:
    return hashlib.sha256(("synthetic-salt:" + s).encode("utf-8")).hexdigest()[:16]


SHARED_LINES = [
    "just {v} the {n}, {n2} next", "{n} then {n2}, that's the whole day", "hot take: {n} beats {n2}",
    "who else is into {n} right now?", "{v} my {n} and honestly feeling great", "can't stop thinking about {n}",
    "{n} at 2am hits different", "tips for {n}? asking for a friend", "weekend plan: {n} and {n2}",
    "finally {v} the {n}", "{n} > {n2}, fight me", "my {n} era is going strong", "{v} {n} again lol",
    "small win today: {v} the {n}", "spent all evening on {n}",
]


def _post(rng: np.random.Generator, pack: str) -> str:
    t = TOPICS[pack]
    line = SHARED_LINES[rng.integers(len(SHARED_LINES))]
    n, n2 = rng.choice(t["nouns"], 2, replace=False)
    v = t["verbs"][rng.integers(len(t["verbs"]))]
    return line.format(n=n, n2=n2, v=v)


def generate(seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    packs = list(PACK_SIZES)
    rows = []
    for p in packs:
        for i in range(PACK_SIZES[p]):
            rows.append({"user_id": _hash(f"{p}-{i}"), "source_pack": p})
    accounts = pd.DataFrame(rows)
    n = len(accounts)
    pack_of = accounts["source_pack"].to_numpy()
    idx_by_pack = {p: np.flatnonzero(pack_of == p) for p in packs}

    # Secondary interest per account (cross-community overlap)
    affinity = {
        "coffee": ["creators", "remote_work"], "students": ["gaming", "coffee"], "gym": ["students", "creators"],
        "remote_work": ["tech", "coffee"], "tech": ["gaming", "remote_work"], "creators": ["coffee", "gym"],
        "gaming": ["tech", "students"],
    }
    second = np.array([rng.choice(affinity[p]) for p in pack_of])

    # Follows: mostly inside pack, some to the secondary pack, a little random
    src, dst = [], []
    for u in range(n):
        k = int(rng.integers(8, 30))
        own = idx_by_pack[pack_of[u]]
        sec = idx_by_pack[second[u]]
        choices = np.concatenate([
            rng.choice(own, int(k * 0.85)),
            rng.choice(sec, int(k * 0.11)),
            rng.integers(0, n, max(1, int(k * 0.04))),
        ])
        for v in np.unique(choices):
            if v != u:
                src.append(u)
                dst.append(int(v))
    uid = accounts["user_id"].to_numpy()
    follows = pd.DataFrame({"src": uid[src], "dst": uid[dst], "weight": 1.0})

    # Interactions: replies/likes, a subset of follow edges plus noise
    m = len(follows)
    pick = rng.choice(m, int(m * 0.25), replace=False)
    inter = follows.iloc[pick][["src", "dst"]].copy()
    inter["weight"] = rng.integers(1, 4, len(inter)).astype(float)

    # Posts and timestamps; each pack has its own active-hour profile
    peak = {"coffee": 8, "students": 23, "gym": 7, "remote_work": 14, "tech": 22, "creators": 19, "gaming": 22}
    base_ts = pd.Timestamp("2026-10-01T00:00:00Z")
    activity = rng.beta(2, 3, n)
    post_rows = []
    for u in range(n):
        p = pack_of[u]
        cnt = int(5 + activity[u] * 20)
        for _ in range(cnt):
            topic = p if rng.random() < 0.8 else (second[u] if rng.random() < 0.7 else rng.choice(packs))
            hour = int((peak[p] + rng.normal(0, 3)) % 24)
            ts = base_ts + pd.Timedelta(days=int(rng.integers(0, 30)), hours=hour, minutes=int(rng.integers(0, 60)))
            post_rows.append({"user_id": uid[u], "text": _post(rng, topic), "ts": ts})
    posts = pd.DataFrame(post_rows)
    meta = {"source": "synthetic", "seed": seed, "packs": packs, "counts": {"accounts": n, "follows": len(follows), "interactions": len(inter), "posts": len(posts)}}
    return {"accounts": accounts, "follows": follows, "interactions": inter.reset_index(drop=True), "posts": posts, "meta": meta}


if __name__ == "__main__":
    d = generate()
    print(json.dumps(d["meta"], indent=1))
