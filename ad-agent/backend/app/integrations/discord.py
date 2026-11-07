"""Discord webhook: posts each budget proposal with approve / reject links back to the API.

The links point at PUBLIC_BASE_URL. For a phone to reach them, set it to the laptop's LAN address
(e.g. http://192.168.1.23:8000) and start the server with --host 0.0.0.0, or use a tunnel."""
from __future__ import annotations

import logging

import httpx

from app import config

log = logging.getLogger(__name__)


def post_proposal(action: dict) -> bool:
    if not config.DISCORD_WEBHOOK_URL:
        return False
    base = config.PUBLIC_BASE_URL
    aid = action["id"]
    approve = f"{base}/api/budget/actions/{aid}/decide?decision=approve"
    reject = f"{base}/api/budget/actions/{aid}/decide?decision=reject"
    embed = {
        "title": f"Volt budget proposal #{aid}",
        "description": action["reason"],
        "color": 0xF5A623,
        "fields": [
            {"name": "€ protected (7-day counterfactual)", "value": f"€{action['eur_protected']:.0f}", "inline": True},
            {"name": "Revenue change", "value": f"€{action.get('revenue_delta', 0):+.0f}", "inline": True},
            {"name": "Decide", "value": f"[Approve]({approve}) · [Reject]({reject})", "inline": False},
        ],
    }
    try:
        r = httpx.post(config.DISCORD_WEBHOOK_URL, json={"username": "Ad Fatigue Agent", "embeds": [embed]}, timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("Discord webhook failed: %s", e)
        return False
