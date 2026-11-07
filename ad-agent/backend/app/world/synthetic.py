"""Synthetic fallback with the same schema as the Bluesky snapshot.

Used for (a) Bluesky audiences when data/bluesky/*.parquet is missing, and (b) ad-platform
segments, where in real life you never see individual people (the platform only reports
aggregates per targeting segment); the synthetic posts stand in for social-listening samples.

Accounts are grouped by pack; posts are generated from per-pack topic words with shared
sentence templates, plus cross-topic noise so groups overlap like real ones do."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

PACK_SIZES = {"coffee": 430, "students": 300, "gym": 380, "remote_work": 420, "tech": 230, "creators": 450, "gaming": 400}

TOPICS = {
    "coffee": {"nouns": ["pour over", "espresso", "cold brew", "oat milk latte", "single origin beans", "grinder", "V60", "aeropress", "flat white", "roastery", "crema", "barista"],
               "verbs": ["dialed in", "brewed", "tasted", "roasted", "ground", "pulled a shot of"]},
    "students": {"nouns": ["exam", "thesis", "lecture", "library", "deadline", "group project", "flashcards", "finals week", "dorm", "midterm", "study session", "essay"],
                 "verbs": ["survived", "pulled an all-nighter for", "procrastinated on", "finished", "submitted", "crammed for"]},
    "gym": {"nouns": ["leg day", "deadlift", "squat PR", "pre-workout", "protein shake", "bench press", "cardio", "rest day", "hypertrophy block", "gym bag", "pull-ups", "5k run"],
            "verbs": ["hit", "crushed", "skipped", "added weight to", "finished", "started"]},
    "remote_work": {"nouns": ["standup", "zoom call", "home office", "async update", "slack thread", "focus block", "coworking space", "laptop stand", "calendar", "afternoon slump", "deep work", "inbox zero"],
                    "verbs": ["survived", "blocked out", "rescheduled", "cleared", "muted", "finished"]},
    "tech": {"nouns": ["pull request", "rust compiler", "kubernetes cluster", "CI pipeline", "side project", "open source repo", "typescript types", "database migration", "code review", "production bug", "LLM agent", "release"],
             "verbs": ["shipped", "debugged", "refactored", "deployed", "merged", "benchmarked"]},
    "creators": {"nouns": ["video edit", "thumbnail", "podcast episode", "newsletter", "brand deal", "content calendar", "camera setup", "illustration", "livestream", "short-form clip", "portfolio", "photo shoot"],
                 "verbs": ["posted", "edited", "launched", "recorded", "planned", "sketched"]},
    "gaming": {"nouns": ["boss fight", "ranked match", "speedrun", "co-op night", "patch notes", "indie game", "controller", "raid", "save file", "open world", "build guide", "late-night session"],
               "verbs": ["beat", "grinded", "lost", "finally cleared", "streamed", "replayed"]},
    "marathoners": {"nouns": ["long run", "tempo session", "marathon block", "taper week", "race bib", "carb load", "negative split", "km 35", "interval workout", "race day", "PB attempt", "recovery run"],
                    "verbs": ["nailed", "survived", "logged", "smashed", "planned", "finished"]},
    "joggers": {"nouns": ["morning 5k", "park run", "evening jog", "couch to 5k plan", "running playlist", "new route", "rest day", "running buddy", "easy 3k", "first 10k", "comfy shoes", "sunset run"],
                "verbs": ["did", "enjoyed", "started", "finished", "tried", "skipped"]},
    "trail": {"nouns": ["trail loop", "muddy descent", "ridge line", "summit push", "headlamp run", "ultra training", "vert gain", "rocky switchbacks", "trail shoes", "forest single track", "hydration vest", "mountain race"],
              "verbs": ["conquered", "slid down", "explored", "climbed", "scouted", "ran"]},
    "parents": {"nouns": ["school run", "nap time", "stroller jog", "kids birthday party", "bedtime routine", "family hike", "lunch boxes", "toddler tantrum", "parent group chat", "weekend football practice", "homework help", "family dinner"],
                "verbs": ["survived", "planned", "squeezed in", "managed", "organized", "finished"]},
    "designers": {"nouns": ["figma file", "client brief", "brand identity", "logo revision", "design system", "moodboard", "portfolio update", "font pairing", "UX audit", "landing page mockup", "freelance rate", "invoice to a client"],
                  "verbs": ["shipped", "presented", "redesigned", "sketched", "finalized", "pitched"]},
    "developers": {"nouns": ["freelance contract", "pull request", "client API", "side project", "production deploy", "code review", "time tracker", "hourly rate", "retainer client", "bug report", "staging server", "late invoice"],
                   "verbs": ["shipped", "debugged", "billed", "refactored", "deployed", "estimated"]},
    "consultants": {"nouns": ["client workshop", "strategy deck", "discovery call", "retainer proposal", "quarterly review", "stakeholder interview", "billable hours", "statement of work", "kickoff meeting", "follow-up email", "slide template", "case study"],
                    "verbs": ["delivered", "pitched", "wrapped up", "scoped", "presented", "closed"]},
    "agency_owners": {"nouns": ["agency retainer", "client churn", "cash flow", "new hire", "pitch deck", "team utilization", "client onboarding", "monthly invoicing", "agency margins", "account manager", "rate card", "overdue payment"],
                      "verbs": ["closed", "lost", "hired", "renegotiated", "chased", "reviewed"]},
    "accountants": {"nouns": ["VAT return", "year-end close", "client receipts", "tax deadline", "bookkeeping software", "expense report", "reconciliation", "payroll run", "small business client", "audit trail", "invoice backlog", "quarterly filing"],
                    "verbs": ["filed", "reconciled", "closed", "reviewed", "prepared", "submitted"]},
    "indie_hackers": {"nouns": ["MRR update", "Product Hunt launch", "side project", "first paying customer", "pricing page", "churn email", "build in public thread", "landing page", "stripe dashboard", "solo founder life", "SaaS idea", "waitlist"],
                      "verbs": ["launched", "shipped", "hit", "rebuilt", "validated", "grew"]},
    "cozy_gamers": {"nouns": ["cozy game", "farming sim", "tea and a game", "rainy day playlist", "village decorating", "fishing minigame", "cottagecore aesthetic", "comfort game", "pixel garden", "gentle puzzle", "wholesome indie", "blanket and controller"],
                    "verbs": ["played", "finished", "decorated", "wishlisted", "relaxed with", "replayed"]},
    "game_dev": {"nouns": ["devlog", "shader", "game jam", "Godot build", "Unity bug", "playtest", "Steam page", "level editor", "particle system", "vertical slice", "publisher pitch", "trailer cut"],
                 "verbs": ["shipped", "debugged", "prototyped", "optimized", "posted", "rewrote"]},
    "pixel_artists": {"nouns": ["pixel art", "sprite sheet", "tileset", "color palette", "animation loop", "Aseprite file", "dithering", "character portrait", "background scene", "art commission", "speedpaint", "pixel tree"],
                      "verbs": ["drew", "animated", "finished", "posted", "repainted", "sketched"]},
}

KNOWN_AFFINITY = {
    "coffee": ["creators", "remote_work"], "students": ["gaming", "coffee"], "gym": ["students", "creators", "marathoners"],
    "remote_work": ["tech", "coffee"], "tech": ["gaming", "remote_work"], "creators": ["coffee", "gym", "gaming"],
    "gaming": ["tech", "students", "cozy_gamers"], "marathoners": ["trail", "gym"], "joggers": ["parents", "gym"],
    "trail": ["marathoners"], "parents": ["joggers"], "designers": ["indie_hackers", "consultants"],
    "developers": ["indie_hackers"], "consultants": ["agency_owners", "accountants"], "agency_owners": ["consultants", "designers"],
    "accountants": ["consultants"], "indie_hackers": ["developers", "designers"], "cozy_gamers": ["gaming", "pixel_artists"],
    "game_dev": ["pixel_artists", "gaming"], "pixel_artists": ["game_dev", "creators"],
}
PEAK_HOUR = {"coffee": 8, "students": 23, "gym": 7, "remote_work": 14, "tech": 22, "creators": 19, "gaming": 22,
             "marathoners": 6, "joggers": 19, "trail": 8, "parents": 21, "designers": 11, "developers": 15, "consultants": 9,
             "agency_owners": 10, "accountants": 10, "indie_hackers": 21, "cozy_gamers": 21, "game_dev": 23, "pixel_artists": 20}

SHARED_LINES = [
    "just {v} the {n}, {n2} next", "{n} then {n2}, that's the whole day", "hot take: {n} beats {n2}",
    "who else is into {n} right now?", "{v} my {n} and honestly feeling great", "can't stop thinking about {n}",
    "{n} at 2am hits different", "tips for {n}? asking for a friend", "weekend plan: {n} and {n2}",
    "finally {v} the {n}", "{n} > {n2}, fight me", "my {n} era is going strong", "{v} {n} again lol",
    "small win today: {v} the {n}", "spent all evening on {n}",
]


def _hash(s: str) -> str:
    return hashlib.sha256(("synthetic-salt:" + s).encode("utf-8")).hexdigest()[:16]


def _post(rng: np.random.Generator, pack: str) -> str:
    t = TOPICS[pack]
    line = SHARED_LINES[rng.integers(len(SHARED_LINES))]
    n, n2 = rng.choice(t["nouns"], 2, replace=False)
    v = t["verbs"][rng.integers(len(t["verbs"]))]
    return line.format(n=n, n2=n2, v=v)


def generate(pack_sizes: dict[str, int] | None = None, seed: int = 7, salt: str = "synthetic") -> dict:
    """pack_sizes: {pack: n_accounts}; every pack needs an entry in TOPICS."""
    pack_sizes = pack_sizes or PACK_SIZES
    rng = np.random.default_rng(seed)
    packs = list(pack_sizes)
    missing = [p for p in packs if p not in TOPICS]
    if missing:
        raise ValueError(f"no synthetic vocabulary for packs {missing}; add them to TOPICS")
    rows = [{"user_id": _hash(f"{salt}-{p}-{i}"), "source_pack": p} for p in packs for i in range(pack_sizes[p])]
    accounts = pd.DataFrame(rows)
    n = len(accounts)
    pack_of = accounts["source_pack"].to_numpy()
    idx_by_pack = {p: np.flatnonzero(pack_of == p) for p in packs}

    # secondary interest: a known affinity if present in this audience, else another pack
    second = []
    for p in pack_of:
        opts = [q for q in KNOWN_AFFINITY.get(p, []) if q in pack_sizes] or [q for q in packs if q != p] or [p]
        second.append(opts[rng.integers(len(opts))])
    second = np.array(second)

    src, dst = [], []
    for u in range(n):
        k = int(rng.integers(8, 30))
        choices = np.concatenate([
            rng.choice(idx_by_pack[pack_of[u]], int(k * 0.85)),
            rng.choice(idx_by_pack[second[u]], int(k * 0.11)),
            rng.integers(0, n, max(1, int(k * 0.04))),
        ])
        for v in np.unique(choices):
            if v != u:
                src.append(u)
                dst.append(int(v))
    uid = accounts["user_id"].to_numpy()
    follows = pd.DataFrame({"src": uid[src], "dst": uid[dst], "weight": 1.0})
    pick = rng.choice(len(follows), int(len(follows) * 0.25), replace=False)
    inter = follows.iloc[pick][["src", "dst"]].copy()
    inter["weight"] = rng.integers(1, 4, len(inter)).astype(float)

    base_ts = pd.Timestamp("2026-10-01T00:00:00Z")
    activity = rng.beta(2, 3, n)
    post_rows = []
    for u in range(n):
        p = pack_of[u]
        for _ in range(int(5 + activity[u] * 20)):
            topic = p if rng.random() < 0.8 else (second[u] if rng.random() < 0.7 else rng.choice(packs))
            hour = int((PEAK_HOUR.get(p, 18) + rng.normal(0, 3)) % 24)
            ts = base_ts + pd.Timedelta(days=int(rng.integers(0, 30)), hours=hour, minutes=int(rng.integers(0, 60)))
            post_rows.append({"user_id": uid[u], "text": _post(rng, topic), "ts": ts})
    posts = pd.DataFrame(post_rows)
    meta = {"source": "synthetic", "seed": seed, "packs": packs, "counts": {"accounts": n, "follows": len(follows), "interactions": len(inter), "posts": len(posts)}}
    return {"accounts": accounts, "follows": follows, "interactions": inter.reset_index(drop=True), "posts": posts, "meta": meta}


if __name__ == "__main__":
    print(json.dumps(generate()["meta"], indent=1))
