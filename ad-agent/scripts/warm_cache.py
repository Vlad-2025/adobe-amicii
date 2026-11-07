"""Run the scripted demo path once with the real LLM (Gemini or Ollama) so every answer lands in
the cache, then export the cache to data/seed/llm_cache.json. On stage, the same inputs hit the
cache, so the demo works with no network and no local model.

Run on the demo laptop, after build-world (cache keys depend on the exact numbers, which depend
on the embedder and the snapshot)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402


def main() -> None:
    from app import config, db
    from app.llm import provider

    if config.LLM_PROVIDER == "cache-only":
        sys.exit("Set LLM_PROVIDER=gemini (with GEMINI_API_KEY) or ollama in .env first")
    from app.llm.agents import profile_all_communities
    from app.main import app

    profile_all_communities()
    with TestClient(app) as c:
        c.post("/api/sim/control", json={"action": "reset"})
        for ad in ("A1", "B1", "C1", "D2", "C2", "A3"):
            c.post(f"/api/ads/{ad}/diagnose")
            with c.stream("GET", f"/api/ads/{ad}/diagnose/narrative") as s:
                "".join(s.iter_text())
            print("narrated", ad)
        for ad in ("A1", "D2"):
            v = c.post(f"/api/creatives/{ad}/variants", json={}).json()
            print("variants", ad, v["source"])
            e = c.post("/api/experiments", json={"source_ad_id": ad, "variant_ids": [x["ad_id"] for x in v["variants"]]}).json()
            with c.stream("POST", f"/api/experiments/{e['id']}/run") as s:
                "".join(s.iter_text())
            print("experiment + learning", ad)
        c.post("/api/sim/control", json={"action": "reset"})
    n = db.export_llm_cache()
    print(f"Exported {n} cached answers to data/seed/llm_cache.json; stats: {provider.status()['by_provider']}")


if __name__ == "__main__":
    main()
