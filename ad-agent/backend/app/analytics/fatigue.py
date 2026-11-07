"""Fatigue predictor: days until the 3-day CTR falls below 70% of its peak.

Trained on ~500 offline simulator runs with random audiences, budgets and creatives.
LightGBM (point + 0.1/0.9 quantiles); sklearn GradientBoosting as a fallback.
Honest framing: trained on simulation, to be retrained per brand on real data."""
from __future__ import annotations

import logging
import pickle
import time

import numpy as np
import pandas as pd

from app.analytics.metrics import slope, with_rates
from app.config import MODELS, TWIN_SCALE

log = logging.getLogger(__name__)
MODEL_PATH = MODELS / "fatigue.pkl"
FEATURES = ["days_live", "frequency", "freq_slope", "ctr_slope3", "ctr_slope7", "ctr_vs_peak", "saturation", "audience_k", "max_sim_prior"]
HORIZON = 30


def features_for(ad_rows: pd.DataFrame, day: int, audience: int, max_sim_prior: float) -> dict:
    """ad_rows: per-day rows (with rates) for ONE ad, indexed by day."""
    h = ad_rows[ad_rows.index <= day]
    if h.empty:
        return {k: 0.0 for k in FEATURES}
    ctr3 = h["ctr"].rolling(3, min_periods=1).mean()
    peak = float(ctr3.max()) or 1e-6
    reach7 = float(h["reach7"].iloc[-1])
    return {
        "days_live": float(len(h)),
        "frequency": float(h["frequency"].iloc[-1]),
        "freq_slope": slope(h["frequency"].to_numpy()[-7:]),
        "ctr_slope3": slope(h["ctr"].to_numpy()[-3:]) / peak,
        "ctr_slope7": slope(h["ctr"].to_numpy()[-7:]) / peak,
        "ctr_vs_peak": float(ctr3.iloc[-1]) / peak,
        "saturation": reach7 / max(audience * TWIN_SCALE, 1),
        "audience_k": audience / 1000.0,
        "max_sim_prior": max_sim_prior,
    }


def _target(ctr3: np.ndarray) -> np.ndarray:
    """For each day: days until ctr3 < 0.7 * running peak (capped at HORIZON)."""
    out = np.full(len(ctr3), HORIZON, float)
    peak = np.maximum.accumulate(ctr3)
    for t in range(len(ctr3)):
        for u in range(t + 1, len(ctr3)):
            if ctr3[u] < 0.7 * peak[u]:
                out[t] = u - t
                break
        else:
            out[t] = min(HORIZON, len(ctr3) - t + 10)
    return out


def generate_training(runs: int = 500, days: int = 45, seed: int = 11) -> pd.DataFrame:
    from app.sim.simulator import Simulator
    from app.world.build import load_world

    world = load_world()
    rng = np.random.default_rng(seed)
    labels = world["labels"]
    k = int(labels.max()) + 1
    sizes = np.bincount(labels, minlength=k)
    base_ads = [world["centroids"][i] for i in range(k)]
    rows = []
    t0 = time.time()
    for r in range(runs):
        comms = sorted(rng.choice(k, size=int(rng.integers(1, 3)), replace=False).tolist())
        budget = float(rng.uniform(10, 90))
        emb = base_ads[int(rng.integers(k))] + rng.normal(0, 0.15, base_ads[0].shape)
        emb = (emb / np.linalg.norm(emb)).astype(np.float32)
        prior_sim = float(rng.uniform(0, 0.95))
        ad_sets = {"s": {"campaign_id": "c", "daily_budget": budget, "target_communities": comms}}
        sim = Simulator(world, ad_sets, {"c": {}}, [{"ad_id": "x", "ad_set_id": "s", "emb": emb, "tone": str(rng.choice(["witty", "energetic", "chill", "informative"]))}], seed=int(rng.integers(1e9)))
        if prior_sim > 0.3:  # pre-fatigue with a similar earlier creative
            sim.n[np.isin(labels, comms), 0] += prior_sim * rng.uniform(0, 4)
        sim.run(days)
        df = with_rates(sim.stats().drop(columns="community_id").groupby("day").sum()).sort_index()
        if len(df) < 10:
            continue
        ctr3 = df["ctr"].rolling(3, min_periods=1).mean().to_numpy()
        y = _target(ctr3)
        audience = int(sizes[comms].sum())
        for t in range(3, len(df) - 5):
            f = features_for(df, int(df.index[t]), audience, prior_sim)
            f["y"] = y[t]
            rows.append(f)
    log.info("fatigue training data: %d rows from %d runs in %.1fs", len(rows), runs, time.time() - t0)
    return pd.DataFrame(rows)


def train(runs: int = 500) -> dict:
    df = generate_training(runs)
    X, y = df[FEATURES].to_numpy(), df["y"].to_numpy()
    try:
        import lightgbm as lgb

        params = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=20, verbose=-1)
        models = {
            "p50": lgb.LGBMRegressor(**params).fit(X, y),
            "p10": lgb.LGBMRegressor(objective="quantile", alpha=0.1, **params).fit(X, y),
            "p90": lgb.LGBMRegressor(objective="quantile", alpha=0.9, **params).fit(X, y),
        }
        kind = "lightgbm"
    except Exception as e:  # pragma: no cover
        from sklearn.ensemble import GradientBoostingRegressor

        log.warning("LightGBM unavailable (%s); using sklearn", e)
        models = {
            "p50": GradientBoostingRegressor().fit(X, y),
            "p10": GradientBoostingRegressor(loss="quantile", alpha=0.1).fit(X, y),
            "p90": GradientBoostingRegressor(loss="quantile", alpha=0.9).fit(X, y),
        }
        kind = "sklearn"
    MODELS.mkdir(exist_ok=True)
    pred = models["p50"].predict(X)
    mae = float(np.mean(np.abs(pred - y)))
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"models": models, "kind": kind, "mae": mae, "rows": len(df)}, f)
    return {"kind": kind, "rows": len(df), "mae_days": round(mae, 2)}


_M = None


def _load():
    global _M
    if _M is None:
        if not MODEL_PATH.exists():
            return None
        with open(MODEL_PATH, "rb") as f:
            _M = pickle.load(f)
    return _M


def predict(feats: dict) -> tuple[float, float, float]:
    m = _load()
    x = np.array([[feats[k] for k in FEATURES]])
    if m is None:  # heuristic until trained
        r = feats["ctr_vs_peak"]
        d = max(0.0, (r - 0.7) / max(-feats["ctr_slope7"], 0.005))
        d = min(d, HORIZON)
        return d, max(0, d * 0.6), min(HORIZON, d * 1.5 + 1)
    p50 = float(m["models"]["p50"].predict(x)[0])
    p10 = float(m["models"]["p10"].predict(x)[0])
    p90 = float(m["models"]["p90"].predict(x)[0])
    lo, hi = sorted([p10, p90])
    p50 = float(np.clip(p50, 0, HORIZON))
    return p50, float(np.clip(min(lo, p50), 0, HORIZON)), float(np.clip(max(hi, p50), 0, HORIZON))
