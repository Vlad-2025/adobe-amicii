"""Run the scripted demo path once with the real LLM (Gemini or Ollama) so every answer lands in
the cache, then export the cache to data/seed/llm_cache.json. On stage, the same inputs hit the
cache, so the demo works with no network and no local model.

Run on the demo laptop, after the final build-world (cache keys depend on the exact numbers)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

DEMO_PATH = {  # channel -> ads to narrate; the first one also gets variants + an experiment
    "volt-ig": ["A1", "D2", "B1", "C1"],
    "volt-tt": ["T1"],
    "kin-meta": ["K3", "K5", "K2", "K4"],
    "th-li": ["H3", "H2"],
    "th-x": ["X1"],
    "ml-x": ["M1", "M4", "M5"],
    "ml-tt": ["N4", "N2"],
}


def main() -> None:
    from app import config, db, registry
    from app.llm import provider

    if config.LLM_PROVIDER == "cache-only":
        sys.exit("Set LLM_PROVIDER=gemini (with GEMINI_API_KEY) or ollama in .env first")
    from app.llm.agents import profile_all_communities
    from app.main import app

    for ch in registry.channels(kind="ads"):
        if ch["mode"] == "simulated":
            profile_all_communities(ch["channel_id"])
    with TestClient(app) as c:
        c.post("/api/sim/control", json={"action": "reset"})
        for ch, ads in DEMO_PATH.items():
            for ad in ads:
                c.post(f"/api/ch/{ch}/ads/{ad}/diagnose")
                with c.stream("GET", f"/api/ch/{ch}/ads/{ad}/diagnose/narrative") as s:
                    "".join(s.iter_text())
            v = c.post(f"/api/ch/{ch}/creatives/{ads[0]}/variants", json={}).json()
            e = c.post(f"/api/ch/{ch}/experiments", json={"source_ad_id": ads[0], "variant_ids": [x["ad_id"] for x in v["variants"]]}).json()
            with c.stream("POST", f"/api/ch/{ch}/experiments/{e['id']}/run") as s:
                "".join(s.iter_text())
            print(f"{ch}: narrated {ads}, variants via {v['source']}, experiment + learning done")
        c.post("/api/sim/control", json={"action": "reset"})
    n = db.export_llm_cache()
    print(f"Exported {n} cached answers to data/seed/llm_cache.json; stats: {provider.status()['by_provider']}")


if __name__ == "__main__":
    main()
