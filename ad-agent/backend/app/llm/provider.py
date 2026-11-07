"""One interface: llm.generate(task, inputs, schema) -> dict.

Backends tried in order: cache -> Gemini (free tier) -> Ollama (local) -> caller's template.
Every response is validated with Pydantic; one retry on invalid JSON. A 429 or timeout falls
through to the next backend. The cache key is task + inputs (not the model), so a cache warmed
with Gemini still serves the demo when you switch to cache-only or Ollama."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Callable

import httpx
from pydantic import BaseModel, ValidationError

from app import config, db

log = logging.getLogger(__name__)
_stats = {"calls": 0, "cache_hits": 0, "by_provider": {}}
_SYSTEM_TAIL = "Use only numbers present in the input. Do not invent statistics. Reply with JSON only."


def _key(task: str, inputs: dict) -> str:
    return hashlib.sha256((task + "\n" + json.dumps(inputs, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _cache_get(k: str) -> dict | None:
    r = db.q("SELECT response, provider FROM llm_cache WHERE prompt_hash=?", (k,))
    return json.loads(r[0]["response"]) if r else None


def _cache_put(k: str, task: str, provider: str, resp: dict) -> None:
    db.x("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?)", (k, task, provider, json.dumps(resp, ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S")))


def _strip(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    if "</think>" in t:
        t = t.split("</think>", 1)[1]
    return t.strip()


def _gemini(system: str, user: str, schema: dict, temperature: float) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json", "responseSchema": schema},
    }
    r = httpx.post(url, json=body, headers={"x-goog-api-key": config.GEMINI_API_KEY}, timeout=config.LLM_TIMEOUT_S)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ollama(system: str, user: str, schema: dict, temperature: float) -> str:
    body = {
        "model": config.OLLAMA_MODEL, "stream": False, "think": False, "format": schema,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_ctx": 2048},
    }
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=max(config.LLM_TIMEOUT_S, 60))
    r.raise_for_status()
    return r.json()["message"]["content"]


def backends() -> list[tuple[str, Callable]]:
    p = config.LLM_PROVIDER
    out = []
    if p == "gemini" and config.GEMINI_API_KEY:
        out.append(("gemini", _gemini))
    if p in ("gemini", "ollama"):
        out.append(("ollama", _ollama))
    return out


def generate(task: str, system: str, inputs: dict, schema: dict, model: type[BaseModel], temperature: float,
             fallback: Callable[[], dict], use_cache: bool = True) -> tuple[dict, str]:
    """Returns (validated dict, provider name)."""
    _stats["calls"] += 1
    k = _key(task, inputs)
    if use_cache:
        hit = _cache_get(k)
        if hit is not None:
            try:
                _stats["cache_hits"] += 1
                return model.model_validate(hit).model_dump(), "cache"
            except ValidationError:
                pass
    system = system.strip() + "\n" + _SYSTEM_TAIL
    user = json.dumps(inputs, ensure_ascii=False)
    for name, fn in backends():
        for attempt in range(2):
            try:
                raw = fn(system, user if attempt == 0 else user + "\nYour last reply was not valid JSON for the schema. Reply with JSON only.", schema, temperature)
                data = model.model_validate(json.loads(_strip(raw))).model_dump()
                _cache_put(k, task, name, data)
                _stats["by_provider"][name] = _stats["by_provider"].get(name, 0) + 1
                return data, name
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning("%s returned invalid JSON for %s (attempt %d): %s", name, task, attempt + 1, str(e)[:120])
                continue
            except Exception as e:  # 429, timeout, connection refused, ...
                log.warning("%s failed for %s: %s", name, task, str(e)[:160])
                break
    data = model.model_validate(fallback()).model_dump()
    _stats["by_provider"]["template"] = _stats["by_provider"].get("template", 0) + 1
    return data, "template"


def status() -> dict:
    ollama_ok = False
    try:
        ollama_ok = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=1.5).status_code == 200
    except Exception:
        pass
    n_cache = db.q("SELECT COUNT(*) AS n FROM llm_cache")[0]["n"]
    return {"provider": config.LLM_PROVIDER, "gemini_key": bool(config.GEMINI_API_KEY), "gemini_model": config.GEMINI_MODEL,
            "ollama_model": config.OLLAMA_MODEL, "ollama_reachable": ollama_ok, "cache_entries": n_cache, **_stats}


def set_provider(p: str) -> None:
    if p not in ("gemini", "ollama", "cache-only"):
        raise ValueError(p)
    config.LLM_PROVIDER = p

