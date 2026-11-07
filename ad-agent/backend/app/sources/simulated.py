from __future__ import annotations

import pandas as pd

from app.sim.simulator import Simulator
from app.sources.base import DAILY_STATS_COLUMNS, AdsSource


class SimulatedSource(AdsSource):
    """Reads only what a real platform would report: no truth columns leave this class."""

    def __init__(self, sim: Simulator):
        self.sim = sim
        self._cache_len = -1
        self._df = pd.DataFrame(columns=DAILY_STATS_COLUMNS)

    def _all(self) -> pd.DataFrame:
        if len(self.sim.rows) != self._cache_len:
            self._df = self.sim.stats()[DAILY_STATS_COLUMNS]
            self._cache_len = len(self.sim.rows)
        return self._df

    def get_daily_stats(self, start: int, end: int, breakdown: str = "community") -> pd.DataFrame:
        df = self._all()
        df = df[(df["day"] >= start) & (df["day"] <= end)]
        if breakdown == "ad":
            df = df.drop(columns="community_id").groupby(["day", "ad_id"], as_index=False).sum()
        return df

    def get_market_index(self, start: int, end: int) -> dict[int, float]:
        return {d: v for d, v in self.sim.market.items() if start <= d <= end}

    def current_day(self) -> int:
        return self.sim.day - 1
