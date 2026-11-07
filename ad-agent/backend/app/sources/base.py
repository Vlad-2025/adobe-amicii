"""The only door analytics has to ad data. Swapping in a real ad platform = one new class."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

DAILY_STATS_COLUMNS = [
    "day", "ad_id", "community_id", "impressions", "reach", "reach7", "impressions7", "clicks", "spend",
    "conversions", "revenue", "comments_annoyed", "comments_total",
]


class AdsSource(ABC):
    @abstractmethod
    def get_daily_stats(self, start: int, end: int, breakdown: str = "community") -> pd.DataFrame:
        """Rows of DAILY_STATS_COLUMNS for days in [start, end]. breakdown: 'community' | 'ad'."""

    @abstractmethod
    def get_market_index(self, start: int, end: int) -> dict[int, float]:
        """External demand signal per day (Google Trends-style, 1.0 = normal)."""

    def get_country_stats(self, start: int, end: int) -> pd.DataFrame:
        """Per ad x country x day (Meta: breakdowns=country; TikTok/X/LinkedIn: country / location breakdowns)."""
        return pd.DataFrame(columns=["day", "ad_id", "campaign_id", "country", "impressions", "clicks", "spend", "conversions", "revenue"])

    def get_country_demand(self, start: int, end: int) -> dict[int, dict[str, float]]:
        """Category demand index per country per day (Google Trends / news volume), 1.0 = normal."""
        return {}

    @abstractmethod
    def current_day(self) -> int:
        """Last day with complete data."""
