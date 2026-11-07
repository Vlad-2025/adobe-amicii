"""Audience Intelligence (feature 3) and the resonance pre-test."""
from __future__ import annotations

import numpy as np

from app import db
from app.analytics.context import Ctx
from app.analytics.metrics import window, with_rates

GAP = 7


def ad_by_community(ctx: Ctx, ad_id: str, day: int | None = None) -> list[dict]:
    day = ctx.source.current_day() if day is None else day
    df = ctx.daily(0, day)
    df = df[df.ad_id == ad_id]
    out = []
    for c, g in df.groupby("community_id"):
        g = with_rates(g.set_index("day").sort_index())
        if g["impressions"].sum() < 500:
            continue
        r, b = window(g["ctr"], day, gap=GAP)
        ratio = float(np.mean(r) / np.mean(b)) if len(r) and len(b) and np.mean(b) > 0 else 1.0
        freq = float(g["frequency"].iloc[-1])
        ctr_all = float(g["clicks"].sum() / g["impressions"].sum())
        if ctr_all < 0.004 and ratio < 1.1:
            status, rec = "never_worked", "exclude"
        elif ratio < 0.7:
            status, rec = "saturated", "replace"
        elif ratio < 0.85 or freq > 3.5:
            status, rec = "saturating", "replace" if ratio < 0.8 else "keep"
        else:
            status, rec = "healthy", "keep"
        out.append({"community_id": int(c), "ctr_now": float(np.mean(r)) if len(r) else 0.0, "ctr_before": float(np.mean(b)) if len(b) else 0.0,
                    "ctr_change": ratio - 1, "frequency": freq, "status": status, "recommendation": rec,
                    "impressions_7d": float(g["impressions"].tail(7).sum())})
    return out


def heatmap(ctx: Ctx, day: int | None = None) -> list[dict]:
    rows = []
    for a in ctx.ads():
        if a["status"] != "active":
            continue
        for r in ad_by_community(ctx, a["ad_id"], day):
            rows.append({"ad_id": a["ad_id"], **r})
    return rows


_post_cache: dict = {}


def community_post_embeddings() -> dict[int, np.ndarray]:
    if not _post_cache:
        rows = db.q("SELECT a.community_id AS c, p.embedding AS e FROM posts p JOIN accounts a ON a.user_id=p.user_id")
        by: dict[int, list] = {}
        for r in rows:
            by.setdefault(r["c"], []).append(np.frombuffer(r["e"], np.float32))
        for c, v in by.items():
            m = np.stack(v)
            idx = np.random.default_rng(0).choice(len(m), min(len(m), 1500), replace=False)
            _post_cache[c] = m[idx]
    return _post_cache


_baseline: dict = {}


def _resonance_baseline() -> tuple[float, float]:
    """Mean and spread of raw resonance over all seed creatives x communities, so scores are comparable across variants."""
    if not _baseline:
        posts = community_post_embeddings()
        embs = [db.unblob(r["embedding"]) for r in db.q("SELECT embedding FROM creatives WHERE parent_ad_id IS NULL")]
        vals = [float((m @ e).mean()) for e in embs for m in posts.values()]
        _baseline["mu"], _baseline["sd"] = float(np.mean(vals)), float(np.std(vals) + 1e-6)
    return _baseline["mu"], _baseline["sd"]


def resonance(creative_emb: np.ndarray, communities: list[int] | None = None) -> dict[int, float]:
    """Mean cosine between the creative and the community's posts, as a 0-100 score
    (50 = an average seed creative in an average community, +15 per standard deviation)."""
    posts = community_post_embeddings()
    mu, sd = _resonance_baseline()
    out = {}
    for c, m in posts.items():
        if communities is not None and c not in communities:
            continue
        z = (float((m @ creative_emb).mean()) - mu) / sd
        out[int(c)] = round(float(np.clip(50 + 15 * z, 0, 100)), 1)
    return out
