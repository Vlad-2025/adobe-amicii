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


_post_cache: dict[str, dict[int, np.ndarray]] = {}
_baseline: dict[str, tuple[float, float]] = {}


def community_post_embeddings(ch: str) -> dict[int, np.ndarray]:
    """A sample of post embeddings per community (saved with the world build)."""
    if ch not in _post_cache:
        from app.world.build import load_world

        w = load_world(ch)
        emb, lab = w["sample_emb"], w["sample_lab"]
        _post_cache[ch] = {int(c): emb[lab == c] for c in np.unique(lab)}
    return _post_cache[ch]


def _resonance_baseline(ch: str) -> tuple[float, float]:
    """Mean and spread of raw resonance over this channel's seed creatives x communities, so scores compare across variants."""
    if ch not in _baseline:
        posts = community_post_embeddings(ch)
        embs = [db.unblob(r["embedding"]) for r in db.q("SELECT embedding FROM creatives WHERE channel_id=? AND parent_ad_id IS NULL", (ch,))]
        vals = [float((m @ e).mean()) for e in embs for m in posts.values() if len(m)]
        _baseline[ch] = (float(np.mean(vals)), float(np.std(vals) + 1e-6))
    return _baseline[ch]


def resonance(ch: str, creative_emb: np.ndarray, communities: list[int] | None = None) -> dict[int, float]:
    """Mean cosine between the creative and the community's posts, as a 0-100 score
    (50 = an average seed creative in an average community, +15 per standard deviation)."""
    posts = community_post_embeddings(ch)
    mu, sd = _resonance_baseline(ch)
    out = {}
    for c, m in posts.items():
        if communities is not None and c not in communities or not len(m):
            continue
        z = (float((m @ creative_emb).mean()) - mu) / sd
        out[int(c)] = round(float(np.clip(50 + 15 * z, 0, 100)), 1)
    return out


def clear_cache(ch: str | None = None) -> None:
    for d in (_post_cache, _baseline):
        if ch is None:
            d.clear()
        else:
            d.pop(ch, None)
