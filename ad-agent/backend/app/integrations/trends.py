"""Google Trends for category terms, cached to data/seed/trends.json.

The root-cause scorer reads the simulator's market index (what a Trends feed would report for the
simulated market). Real Trends data is shown in the UI as context only, because the real market
does not know about planted simulator dips. pytrends is unofficial and often rate-limited, hence
the cache. Refresh with: python run.py fetch-trends"""
from __future__ import annotations

import json
import logging

from app.config import SEED

log = logging.getLogger(__name__)
CACHE = SEED / "trends.json"
TERMS = ["cold brew", "iced coffee", "energy drink"]


def fetch(geo: str = "", timeframe: str = "today 3-m") -> dict:
    try:
        from pytrends.request import TrendReq
    except ImportError:
        raise SystemExit("pip install pytrends  (optional dependency)")
    py = TrendReq(hl="en-US", tz=0)
    py.build_payload(TERMS, timeframe=timeframe, geo=geo)
    df = py.interest_over_time()
    out = {"terms": TERMS, "geo": geo or "worldwide", "timeframe": timeframe,
           "series": {t: [{"date": str(i.date()), "value": int(v)} for i, v in df[t].items()] for t in TERMS}}
    CACHE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def cached() -> dict | None:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return None
