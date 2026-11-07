"""Top voices per community: the accounts a community follows and engages with most.

Rank = followers inside the community + 2 × replies/reposts received from it (the people the
community actually listens to, not just the biggest accounts). Real Bluesky snapshots only name the
public accounts saved in data/bluesky/influencers.parquet; everyone else stays pseudonymous.
The synthetic world gets made-up profiles with .example handles, so no link can hit a real person.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from functools import lru_cache

import pandas as pd

from app import db
from app.config import BLUESKY

FIRST = ["Ana", "Ben", "Chloé", "Dario", "Eli", "Fenna", "Gus", "Hana", "Ilias", "Jo", "Kai", "Lena", "Mats", "Nora", "Oskar",
         "Pia", "Rui", "Sofia", "Tomás", "Uma", "Vera", "Wim", "Yara", "Zoe"]
ROLE = ["Creator, covers", "Writes about", "Posts daily on", "Podcast on", "Newsletter on", "Community lead for", "Reviews"]


@lru_cache(maxsize=1)
def _real_profiles() -> dict[str, dict]:
    f = BLUESKY / "influencers.parquet"
    if not f.exists():
        return {}
    return {r["user_id"]: r for r in pd.read_parquet(f).to_dict("records")}


def _fake_profile(uid: str, keywords: list[str], in_followers: int) -> dict:
    h = int(hashlib.sha1(uid.encode()).hexdigest(), 16)
    name = FIRST[h % len(FIRST)]
    kw = keywords[(h // 7) % max(len(keywords), 1)] if keywords else "topics"
    rest = [k for k in keywords if k != kw] or ["more"]
    kw2 = rest[(h // 11) % len(rest)]
    slug = unicodedata.normalize("NFKD", f"{name}{kw}").encode("ascii", "ignore").decode().lower()
    slug = "".join(ch for ch in slug if ch.isalnum())[:16]
    return {"handle": f"{slug}{h % 90 + 10}.example", "display_name": f"{name} · {kw}",
            "bio": f"{ROLE[(h // 13) % len(ROLE)]} {kw} and {kw2}.", "followers": in_followers * (40 + h % 160),
            "url": None, "synthetic": True}


def top_voices(ch: str, n: int = 10) -> dict[int, list[dict]]:
    acc = pd.DataFrame(db.q("SELECT user_id, community_id FROM accounts WHERE channel_id=?", (ch,)))
    if acc.empty:
        return {}
    comm = dict(zip(acc.user_id, acc.community_id))
    meta = db.kv_get(f"world_meta:{ch}", {})
    real = meta.get("source") == "bluesky"
    profiles = _real_profiles() if real else {}
    keywords = {r["community_id"]: json.loads(r["keywords"]) for r in db.q("SELECT community_id, keywords FROM communities WHERE channel_id=?", (ch,))}

    def inside(table: str) -> pd.Series:
        e = pd.DataFrame(db.q(f"SELECT src, dst, weight FROM {table} WHERE channel_id=?", (ch,)))
        if e.empty:
            return pd.Series(dtype=float)
        e = e[e.src.map(comm) == e.dst.map(comm)]  # only attention from the account's own community
        return e.groupby("dst").weight.sum()

    fol, inter = inside("follows"), inside("interactions")
    acc["in_followers"] = acc.user_id.map(fol).fillna(0).astype(int)
    acc["engagement"] = acc.user_id.map(inter).fillna(0)
    acc["score"] = acc.in_followers + 2 * acc.engagement
    out: dict[int, list[dict]] = {}
    for cid, g in acc.sort_values("score", ascending=False).groupby("community_id", sort=False):
        size = len(g)
        rows = []
        for r in g.itertuples():
            if r.score <= 0:
                break
            if real:
                p = profiles.get(r.user_id)
                if p is None:
                    continue  # pseudonymous account: counted in the graph, never named
                prof = {"handle": p["handle"], "display_name": p["display_name"] or p["handle"], "bio": p["bio"],
                        "followers": int(p["followers"]), "url": f"https://bsky.app/profile/{p['handle']}", "synthetic": False}
            else:
                prof = _fake_profile(r.user_id, keywords.get(int(cid), []), r.in_followers)
            rows.append({**prof, "followed_by_share": round(r.in_followers / size, 3), "in_followers": int(r.in_followers),
                         "engagement": int(r.engagement)})
            if len(rows) >= n:
                break
        out[int(cid)] = rows
    return out
