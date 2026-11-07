"""The fake ad network. Pure numpy, no LLM. One call to `step()` = one simulated day.

Users are digital twins of Bluesky accounts (see world/build.py). Each twin stands for
TWIN_SCALE real people: impressions, clicks and conversions are counted at real scale and
spread over twins; a twin's per-person exposure is its impressions / TWIN_SCALE.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.config import TWIN_SCALE

TONES = ["witty", "energetic", "chill", "informative"]

# Click model (design doc, "Daily loop"): logit = b0 + b1*affinity + b2*tone + b3*hour - lam*log(1+f)
B0 = -4.3          # ~1.3% base CTR
B1 = 0.3           # per standard deviation of user-ad affinity
B2 = 0.35          # tone fit
B3 = 0.8           # prime-time fit (centered)
LAM = 0.6          # fatigue penalty
F0 = 4.0           # frequency grace: no penalty until ~4 recent exposures per person
BASE_CPM = 6.0
CPM_SIGMA = 0.08
BASE_CVR = 0.08
FATIGUE_DECAY = 0.95   # exposures fade 5% per day
COMMENT_RATE = 0.0005
PACK_P = np.array([0.3, 0.5, 0.2])
PACK_N = np.array([1, 4, 12])
PRICE = 2.9


def _uniq(k: np.ndarray, scale: int = TWIN_SCALE) -> np.ndarray:
    """Expected unique people reached when k impressions land on a twin standing for `scale` people."""
    return scale * (1 - (1 - 1 / scale) ** k)


@dataclass
class Effect:
    sid: str
    type: str
    value: float
    start: int
    end: int | None
    ad: str | None = None
    campaign: str | None = None
    community: int | None = None
    live: bool = False

    def active(self, day: int) -> bool:
        return day >= self.start and (self.end is None or day <= self.end)


@dataclass
class Ad:
    ad_id: str
    ad_set_id: str
    campaign_id: str
    emb: np.ndarray
    tone: str
    offer: str
    status: str = "active"
    weight: float = 1.0           # share of the ad set budget (experiments re-weight this)
    fields: dict = field(default_factory=dict)


class Simulator:
    def __init__(self, world: dict, ad_sets: dict, campaigns: dict, ads: list[dict], seed: int = 7, params: dict | None = None):
        """params (per channel): base_cpm, b0, lam, weekend, economics{order_values, order_probs, base_cvr, price_factor, price_factor_offer}."""
        p = params or {}
        eco = p.get("economics", {})
        self.scale = int(p.get("twin_scale", TWIN_SCALE))  # real people per twin (bigger audiences = more people per twin)
        self.p_base_cpm = float(p.get("base_cpm", BASE_CPM))
        self.p_b0 = float(p.get("b0", B0))
        self.p_lam = float(p.get("lam", LAM))
        self.p_weekend = float(p.get("weekend", 1.1))
        self.p_cvr = float(eco.get("base_cvr", BASE_CVR))
        self.p_order_values = np.array(eco.get("order_values", PACK_N * PRICE), float)
        self.p_order_probs = np.array(eco.get("order_probs", PACK_P), float)
        self.p_order_probs = self.p_order_probs / self.p_order_probs.sum()
        self.p_price_factor = float(eco.get("price_factor", 0.5))
        self.p_price_factor_offer = float(eco.get("price_factor_offer", 0.35))
        self.rng = np.random.default_rng(seed)
        self.day = 0
        self.interest = world["interest"]
        self.activity = world["activity"]
        self.price = world["price"]
        self.labels = world["labels"]
        self.tone_pref = world["tone_pref"]
        self.prime_c = world["prime"] - float(world["prime"].mean())
        self.U = len(self.labels)
        self.K = int(self.labels.max()) + 1
        self.ad_sets = {k: dict(v) for k, v in ad_sets.items()}      # ad_set_id -> {campaign_id, daily_budget, target_communities}
        self.campaigns = {k: dict(v) for k, v in campaigns.items()}
        self.ads: list[Ad] = []
        self.idx: dict[str, int] = {}
        self.n = np.zeros((self.U, 0), np.float32)          # exposures (decaying)
        self.hist7: list[np.ndarray] = []                   # last 7 days of impressions per user x ad
        self.aff = np.zeros((self.U, 0), np.float32)
        self.W = np.zeros((0, 0), np.float32)
        self.effects: list[Effect] = []
        self._cos_mu = None
        self._cos_sd = None
        for a in ads:
            self.add_ad(a)
        self.rows: list[dict] = []                          # reported daily stats (cleaned layer)
        self.truth_rows: list[dict] = []
        self.market: dict[int, float] = {}

    # ---------- ads ----------
    def add_ad(self, a: dict) -> None:
        s = self.ad_sets[a["ad_set_id"]]
        ad = Ad(a["ad_id"], a["ad_set_id"], s["campaign_id"], np.asarray(a["emb"], np.float32), a.get("tone", "witty"),
                a.get("offer", "none"), a.get("status", "active"), float(a.get("weight", 1.0)), {k: a.get(k) for k in ("hook", "body", "cta", "angle")})
        self.idx[ad.ad_id] = len(self.ads)
        self.ads.append(ad)
        cos = self.interest @ ad.emb
        if self._cos_mu is None:
            self._cos_mu, self._cos_sd = float(cos.mean()), float(cos.std() + 1e-6)
        z = (cos - self._cos_mu) / self._cos_sd
        self.aff = np.concatenate([self.aff, z[:, None].astype(np.float32)], 1)
        self.n = np.concatenate([self.n, np.zeros((self.U, 1), np.float32)], 1)
        self.hist7 = [np.concatenate([h, np.zeros((self.U, 1), np.int32)], 1) for h in self.hist7]
        E = np.stack([x.emb for x in self.ads])
        C = np.clip(E @ E.T, 0, 1) ** 2
        np.fill_diagonal(C, 1.0)
        self.W = C.astype(np.float32)

    def set_status(self, ad_id: str, status: str) -> None:
        self.ads[self.idx[ad_id]].status = status

    # ---------- scenarios ----------
    def add_effect(self, e: Effect) -> None:
        self.effects.append(e)

    def _eff(self, typ: str, day: int, ad: Ad | None = None, campaign: str | None = None) -> list[Effect]:
        out = []
        for e in self.effects:
            if e.type != typ or not e.active(day):
                continue
            if e.ad and ad is not None and e.ad != ad.ad_id:
                continue
            if e.ad and ad is None:
                continue
            if e.campaign and e.campaign != (campaign or (ad.campaign_id if ad else None)):
                continue
            out.append(e)
        return out

    def _mult(self, typ: str, day: int, ad: Ad | None = None, campaign: str | None = None) -> float:
        m = 1.0
        for e in self._eff(typ, day, ad, campaign):
            m *= e.value
        return m

    # ---------- the daily loop ----------
    def step(self) -> list[dict]:
        d = self.day
        rng = self.rng
        weekly = self.p_weekend if d % 7 in (5, 6) else 1.0
        act = self._mult("activity", d)
        season = weekly * act
        self.market[d] = float(np.clip(act * (1 + rng.normal(0, 0.03)), 0.3, 1.5))

        A = len(self.ads)
        f_eff = self.n @ self.W                      # effective fatigue incl. carry-over (U x A)
        imps = np.zeros((self.U, A), np.int32)
        clicks = np.zeros((self.U, A), np.int32)
        conv = np.zeros((self.U, A), np.int32)
        spend = np.zeros(A)
        cpm_a = np.zeros(A)

        # budgets: ad set budget split across its active ads by weight
        by_set: dict[str, list[int]] = {}
        for i, ad in enumerate(self.ads):
            if ad.status == "active":
                by_set.setdefault(ad.ad_set_id, []).append(i)

        for set_id, members in by_set.items():
            s = self.ad_sets[set_id]
            target = np.isin(self.labels, s["target_communities"])
            tw = sum(self.ads[i].weight for i in members) or 1.0
            for i in members:
                ad = self.ads[i]
                budget = s["daily_budget"] * ad.weight / tw * self._mult("budget_multiplier", d, ad)
                comp = self._mult("competition", d, ad)
                cpm = self.p_base_cpm * comp * math.exp(rng.normal(0, CPM_SIGMA)) * (0.92 if act < 1 else 1.0)
                n_imp = int(rng.poisson(budget / cpm * 1000))
                if n_imp == 0 or not target.any():
                    continue
                w = self.activity * np.exp(0.3 * self.aff[:, i]) * target
                for e in self._eff("delivery_skew", d, ad):
                    w = w * np.where(self.labels == e.community, e.value, 1.0)
                w = w.astype(np.float64)
                p = w / w.sum()
                imps[:, i] = rng.multinomial(n_imp, p)
                spend[i] = budget
                cpm_a[i] = cpm

                tone_i = TONES.index(ad.tone) if ad.tone in TONES else 0
                f_mid = f_eff[:, i] + imps[:, i] / (2.0 * self.scale)
                logit = (self.p_b0 + B1 * self.aff[:, i] + B2 * self.tone_pref[self.labels, tone_i] + B3 * self.prime_c
                         - self.p_lam * np.log1p(np.maximum(f_mid - F0, 0)) + math.log(act) + 0.3 * math.log(weekly))
                pc = 1 / (1 + np.exp(-logit))
                clicks[:, i] = rng.binomial(imps[:, i], pc)
                landing = self._mult("landing_health", d, ad)
                price_factor = self.p_price_factor_offer if ad.offer and ad.offer != "none" else self.p_price_factor
                pv = np.clip(self.p_cvr * landing * act * (1 - self.price * price_factor), 0, 1)
                conv[:, i] = rng.binomial(clicks[:, i], pv)

        # update exposure state
        self.n *= FATIGUE_DECAY
        self.n += imps / self.scale
        self.hist7.append(imps)
        if len(self.hist7) > 7:
            self.hist7.pop(0)
        h7 = np.sum(self.hist7, axis=0)

        rows = []
        for i, ad in enumerate(self.ads):
            if imps[:, i].sum() == 0:
                continue
            tracking_off = bool(self._eff("tracking_off", d, ad))
            lab = self.labels
            imp_c = np.bincount(lab, weights=imps[:, i], minlength=self.K)
            reach_c = np.bincount(lab, weights=_uniq(imps[:, i], self.scale), minlength=self.K)
            reach7_c = np.bincount(lab, weights=_uniq(h7[:, i], self.scale), minlength=self.K)
            imp7_c = np.bincount(lab, weights=h7[:, i], minlength=self.K)
            clk_c = np.bincount(lab, weights=clicks[:, i], minlength=self.K)
            cv_c = np.bincount(lab, weights=conv[:, i], minlength=self.K)
            fat_c = np.bincount(lab, weights=f_eff[:, i] * (imps[:, i] > 0), minlength=self.K)
            tot_imp = imps[:, i].sum()
            for c in np.flatnonzero(imp_c):
                real_imp = imp_c[c]
                n_com = rng.binomial(int(real_imp), COMMENT_RATE)
                mean_f = fat_c[c] / max(np.count_nonzero((imps[:, i] > 0) & (lab == c)), 1)
                p_ann = float(np.clip(0.04 + 0.06 * mean_f, 0, 0.9))
                n_ann = rng.binomial(n_com, p_ann)
                n_conv = int(cv_c[c])
                orders = rng.choice(self.p_order_values, size=n_conv, p=self.p_order_probs) if n_conv else np.array([])
                revenue = float(orders.sum())
                rows.append({
                    "day": d, "ad_id": ad.ad_id, "community_id": int(c),
                    "impressions": float(real_imp), "reach": float(reach_c[c]),
                    "reach7": float(reach7_c[c]), "impressions7": float(imp7_c[c]),
                    "clicks": float(clk_c[c]), "spend": float(spend[i] * imp_c[c] / tot_imp),
                    "conversions": 0.0 if tracking_off else float(n_conv),
                    "revenue": 0.0 if tracking_off else revenue,
                    "comments_annoyed": float(n_ann), "comments_total": float(n_com),
                    "true_conversions": float(n_conv),
                })
            exposed = imps[:, i] > 0
            self.truth_rows.append({"day": d, "ad_id": ad.ad_id,
                                    "mean_exposures": float(self.n[exposed, i].mean()) if exposed.any() else 0.0,
                                    "mean_fatigue": float(f_eff[exposed, i].mean()) if exposed.any() else 0.0})
        self.rows.extend(rows)
        self.day += 1
        return rows

    def run(self, days: int) -> None:
        for _ in range(days):
            self.step()

    def stats(self) -> pd.DataFrame:
        cols = ["day", "ad_id", "community_id", "impressions", "reach", "reach7", "impressions7", "clicks", "spend",
                "conversions", "revenue", "comments_annoyed", "comments_total", "true_conversions"]
        return pd.DataFrame(self.rows, columns=cols)

    def fork(self, seed: int | None = None) -> "Simulator":
        f = copy.deepcopy(self)
        f.rng = np.random.default_rng(seed if seed is not None else 1000 + self.day)
        return f

    def ad_info(self) -> list[dict]:
        return [{"ad_id": a.ad_id, "ad_set_id": a.ad_set_id, "campaign_id": a.campaign_id, "status": a.status, "weight": a.weight} for a in self.ads]
