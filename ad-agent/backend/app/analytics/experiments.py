"""Experiment engine (feature 5): power-calculated plan, Thompson sampling on a forked simulator."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from app.sim.simulator import Simulator


def sample_size_per_arm(p1: float, lift: float = 0.15, alpha: float = 0.05, power: float = 0.8) -> int:
    p1 = max(min(p1, 0.5), 1e-4)
    p2 = p1 * (1 + lift)
    nd = NormalDist()
    za, zb = nd.inv_cdf(1 - alpha / 2), nd.inv_cdf(power)
    pbar = (p1 + p2) / 2
    n = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
    return int(math.ceil(n))


def choose_metric(objective: str, diagnosis: str | None) -> str:
    """Awareness -> CTR. Conversions -> conversions per impression, except for creative problems
    (fatigue, saturation), which show up in CTR first and would need weeks of data on conversions."""
    if objective == "awareness" or diagnosis in ("creative_fatigue", "segment_saturation", None):
        return "ctr"
    return "conversions_per_impression"


def plan(baseline_rate: float, metric: str, n_arms: int, daily_impressions: float, lift: float = 0.15) -> dict:
    n = sample_size_per_arm(baseline_rate, lift)
    per_arm_day = max(daily_impressions / n_arms, 1)
    days = math.ceil(n / per_arm_day)
    text = (f"Testing {n_arms} arms on {metric.replace('_', ' ')}. Baseline {baseline_rate:.2%}; to detect a "
            f"{lift:.0%} lift at α=0.05 with 80% power we need {n:,} impressions per arm, about {days} days at the current "
            f"budget with an even split. Thompson sampling shifts traffic to the leader daily and stops when one arm has ≥95% "
            f"probability of being best (much sooner when the gap is large) or after 14 days.")
    return {"metric": metric, "baseline": baseline_rate, "lift": lift, "sample_size_per_arm": n, "est_days_even_split": days, "text": text}


def p_best(successes: np.ndarray, trials: np.ndarray, rng: np.random.Generator, draws: int = 4000) -> np.ndarray:
    a = 1 + successes[:, None]
    b = 1 + np.maximum(trials - successes, 0)[:, None]
    samples = rng.beta(a, b, size=(len(successes), draws))
    wins = np.bincount(samples.argmax(0), minlength=len(successes))
    return wins / draws


def run(sim: Simulator, source_ad_id: str, variants: list[dict], metric: str, max_days: int = 14, seed: int = 42):
    """Yields one dict per simulated day. `variants` carry ad_id, emb, tone, offer, hook/body/cta."""
    fork = sim.fork(seed)
    src = fork.ads[fork.idx[source_ad_id]]
    arms = [source_ad_id]
    for v in variants:
        fork.add_ad({**v, "ad_set_id": src.ad_set_id, "status": "active", "weight": 1.0})
        arms.append(v["ad_id"])
    # the experiment takes over the ad set: other ads in it pause
    for a in fork.ads:
        if a.ad_set_id == src.ad_set_id and a.ad_id not in arms:
            a.status = "paused"
    for a in arms:
        fork.ads[fork.idx[a]].weight = 1.0 / len(arms)
    rng = np.random.default_rng(seed)
    succ = np.zeros(len(arms))
    trials = np.zeros(len(arms))
    clicks = np.zeros(len(arms))
    conv = np.zeros(len(arms))
    for d in range(max_days):
        rows = fork.step()
        for r in rows:
            if r["ad_id"] in arms:
                i = arms.index(r["ad_id"])
                trials[i] += r["impressions"]
                clicks[i] += r["clicks"]
                conv[i] += r["conversions"]
        succ = clicks if metric == "ctr" else conv
        pb = p_best(succ, trials, rng)
        weights = np.maximum(pb, 0.05)
        weights /= weights.sum()
        for a, w in zip(arms, weights):
            fork.ads[fork.idx[a]].weight = float(w)
        done = (d >= 2 and pb.max() >= 0.95) or d == max_days - 1
        yield {
            "day": d + 1, "arms": arms, "p_best": pb.round(4).tolist(), "allocation": weights.round(4).tolist(),
            "impressions": trials.tolist(), "clicks": clicks.tolist(), "conversions": conv.tolist(),
            "rate": (succ / np.maximum(trials, 1)).round(6).tolist(), "done": bool(done),
            "winner": arms[int(pb.argmax())] if done else None,
        }
        if done:
            break
