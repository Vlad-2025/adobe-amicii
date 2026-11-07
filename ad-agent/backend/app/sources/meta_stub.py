"""Meta Marketing API connector (stub). Field mapping is real; the HTTP calls are not wired
because developer tokens and app review take days.

GET /v21.0/act_<AD_ACCOUNT_ID>/insights
    ?level=ad&time_increment=1&breakdowns=age,gender (or custom audiences via ad sets)
    &fields=ad_id,impressions,reach,frequency,clicks,spend,actions,action_values
"""
from __future__ import annotations

import pandas as pd

from app.sources.base import AdsSource

FIELD_MAP = {
    "ad_id": "ad_id",
    "date_start": "day",
    "impressions": "impressions",
    "reach": "reach",
    "frequency": None,  # derived: impressions / reach
    "clicks": "clicks",
    "spend": "spend",
    "actions[action_type=purchase]": "conversions",
    "action_values[action_type=purchase]": "revenue",
}


class MetaAdsSource(AdsSource):
    def __init__(self, access_token: str, ad_account_id: str):
        self.token = access_token
        self.account = ad_account_id

    def get_daily_stats(self, start: int, end: int, breakdown: str = "community") -> pd.DataFrame:
        raise NotImplementedError("Wire /insights here; map columns with FIELD_MAP")

    def get_market_index(self, start: int, end: int) -> dict[int, float]:
        return {}

    def current_day(self) -> int:
        raise NotImplementedError
