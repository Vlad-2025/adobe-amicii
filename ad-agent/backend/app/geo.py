"""Countries: names (as in the world-atlas map), GDELT FIPS codes, and relative ad prices.

cpm: typical relative cost of 1,000 impressions (rough industry ratios; normalized per campaign
in the simulator so a campaign's average economics stay calibrated)."""
from __future__ import annotations

COUNTRIES: dict[str, dict] = {
    "DE": {"name": "Germany", "fips": "GM", "cpm": 1.10},
    "FR": {"name": "France", "fips": "FR", "cpm": 1.00},
    "ES": {"name": "Spain", "fips": "SP", "cpm": 0.80},
    "IT": {"name": "Italy", "fips": "IT", "cpm": 0.85},
    "NL": {"name": "Netherlands", "fips": "NL", "cpm": 1.05},
    "BE": {"name": "Belgium", "fips": "BE", "cpm": 1.00},
    "AT": {"name": "Austria", "fips": "AU", "cpm": 1.00},
    "CH": {"name": "Switzerland", "fips": "SZ", "cpm": 1.30},
    "PL": {"name": "Poland", "fips": "PL", "cpm": 0.60},
    "CZ": {"name": "Czechia", "fips": "EZ", "cpm": 0.65},
    "PT": {"name": "Portugal", "fips": "PO", "cpm": 0.70},
    "GR": {"name": "Greece", "fips": "GR", "cpm": 0.60},
    "RO": {"name": "Romania", "fips": "RO", "cpm": 0.50},
    "SE": {"name": "Sweden", "fips": "SW", "cpm": 1.00},
    "DK": {"name": "Denmark", "fips": "DA", "cpm": 1.05},
    "NO": {"name": "Norway", "fips": "NO", "cpm": 1.15},
    "FI": {"name": "Finland", "fips": "FI", "cpm": 0.95},
    "IE": {"name": "Ireland", "fips": "EI", "cpm": 1.05},
    "GB": {"name": "United Kingdom", "fips": "UK", "cpm": 1.20},
    "US": {"name": "United States of America", "fips": "US", "cpm": 1.30},
    "CA": {"name": "Canada", "fips": "CA", "cpm": 1.15},
}


def name(code: str) -> str:
    return COUNTRIES.get(code, {}).get("name", code)
