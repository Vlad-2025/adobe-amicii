"""Read-only view of ad metadata the analytics layer needs (targets, campaigns, audiences)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.metrics import ad_daily
from app.sim.simulator import Simulator
from app.sources.base import AdsSource


@dataclass
class Ctx:
    channel_id: str
    source: AdsSource
    sim: Simulator  # used for metadata only (ad sets, campaigns, embeddings); never for truth

    def ads(self) -> list[dict]:
        out = []
        for a in self.sim.ads:
            s = self.sim.ad_sets[a.ad_set_id]
            out.append({"ad_id": a.ad_id, "ad_set_id": a.ad_set_id, "campaign_id": a.campaign_id, "status": a.status,
                        "targets": list(s["target_communities"]), **a.fields, "tone": a.tone, "offer": a.offer})
        return out

    def ad(self, ad_id: str) -> dict:
        return next(a for a in self.ads() if a["ad_id"] == ad_id)

    def community_sizes(self) -> np.ndarray:
        return np.bincount(self.sim.labels, minlength=self.sim.K)

    def audience(self, ad_id: str) -> float:
        """Real people targeted by the ad (twins x people per twin)."""
        a = self.ad(ad_id)
        return float(self.community_sizes()[a["targets"]].sum()) * self.sim.scale

    def max_sim_prior(self, ad_id: str) -> float:
        i = self.sim.idx[ad_id]
        a = self.sim.ads[i]
        others = [j for j, b in enumerate(self.sim.ads) if j != i and set(self.sim.ad_sets[b.ad_set_id]["target_communities"]) & set(self.sim.ad_sets[a.ad_set_id]["target_communities"])]
        if not others:
            return 0.0
        return float(max(self.sim.W[i, j] ** 0.5 for j in others))

    def daily(self, start: int = 0, end: int | None = None) -> pd.DataFrame:
        end = self.source.current_day() if end is None else end
        return self.source.get_daily_stats(start, end, "community")

    def ad_daily(self, end: int | None = None) -> pd.DataFrame:
        return ad_daily(self.daily(0, end))
