"""Brand guard: done by code, never by the LLM."""
from __future__ import annotations

import json
import re

from app.config import SEED

_BRAND = None


def brand() -> dict:
    global _BRAND
    if _BRAND is None:
        _BRAND = json.loads((SEED / "brand.json").read_text(encoding="utf-8"))
    return _BRAND


def check(v: dict) -> list[dict]:
    b = brand()
    fails = []
    lim = b["limits"]
    for field, key in (("hook", "headline"), ("body", "body"), ("cta", "cta")):
        n = len(v.get(field) or "")
        if n > lim[key]:
            fails.append({"rule": f"{field} length", "detail": f"{n} > {lim[key]} characters"})
    text = " ".join(str(v.get(k) or "") for k in ("hook", "body", "cta", "offer")).lower()
    for p in b["banned_phrases"]:
        if p.lower() in text:
            fails.append({"rule": "banned phrase", "detail": p})
    for pat in b["health_claim_patterns"]:
        if re.search(pat, text):
            fails.append({"rule": "health claim", "detail": pat})
    for c in b["competitors"]:
        if re.search(r"\b" + re.escape(c.lower()) + r"\b", text):
            fails.append({"rule": "competitor name", "detail": c})
    return fails
