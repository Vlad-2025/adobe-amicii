"""Google Ads API connector (stub). GAQL and field mapping are real; not wired.

SELECT ad_group_ad.ad.id, segments.date, metrics.impressions, metrics.clicks,
       metrics.cost_micros, metrics.conversions, metrics.conversions_value
FROM ad_group_ad
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""
from __future__ import annotations

import pandas as pd

from app.sources.base import AdsSource

FIELD_MAP = {
    "ad_group_ad.ad.id": "ad_id",
    "segments.date": "day",
    "metrics.impressions": "impressions",
    "metrics.clicks": "clicks",
    "metrics.cost_micros": "spend",  # / 1e6
    "metrics.conversions": "conversions",
    "metrics.conversions_value": "revenue",
}


class GoogleAdsSource(AdsSource):
    def __init__(self, developer_token: str, customer_id: str):
        self.token = developer_token
        self.customer_id = customer_id

    def get_daily_stats(self, start: int, end: int, breakdown: str = "community") -> pd.DataFrame:
        raise NotImplementedError("Run the GAQL above via GoogleAdsService.SearchStream")

    def get_market_index(self, start: int, end: int) -> dict[int, float]:
        return {}

    def current_day(self) -> int:
        raise NotImplementedError
