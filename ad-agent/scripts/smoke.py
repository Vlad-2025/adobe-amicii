"""End-to-end smoke test: world -> 30 days -> radar -> diagnoses vs planted truth -> variants ->
experiment -> learning -> budget proposal -> live injection. Uses whatever LLM_PROVIDER is set
(run.py smoke forces cache-only, so it needs no network). Exit code 1 if anything is wrong."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402


def peak_mb() -> float | None:
    try:
        import resource  # Linux / macOS

        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1024 if sys.platform != "darwin" else r / 1024 / 1024
    except ImportError:
        try:
            import psutil  # Windows, if installed

            return psutil.Process().memory_info().peak_wset / 1024 / 1024
        except Exception:
            return None


def main() -> int:
    t0 = time.time()
    from app.main import app

    problems = []
    with TestClient(app) as c:
        ov = c.get("/api/overview").json()
        print(f"day {ov['day']}, health {ov['health_counts']}, € at risk {ov['eur_at_risk']:.0f}")
        ev = c.get("/api/eval").json()
        for r in ev["scenarios"]:
            print(f"  scenario {r['scenario']}: truth {r['truth']:<20} predicted {r.get('predicted')} ({r.get('confidence')})")
        if ev["accuracy"] is None or ev["accuracy"] < 0.99:
            problems.append(f"planted-scenario accuracy {ev['accuracy']}")

        top = c.post("/api/ads/A1/diagnose").json()["top"]
        v = c.post("/api/creatives/A1/variants", json={}).json()
        print(f"A1 diagnosis {top}; variants via {v['source']}: {[x['changed_dimension'] for x in v['variants']]}")
        if len(v["variants"]) < 2:
            problems.append("fewer than 2 variants")
        exp = c.post("/api/experiments", json={"source_ad_id": "A1", "variant_ids": [x["ad_id"] for x in v["variants"]]}).json()
        with c.stream("POST", f"/api/experiments/{exp['id']}/run") as s:
            body = "".join(s.iter_text())
        if "event: done" not in body:
            problems.append("experiment did not finish")
        else:
            print("experiment finished:", body.split("event: done")[1][:160].replace("\n", " "))
        b = c.post("/api/budget/propose").json()
        print(f"budget proposals: {len(b['created'])} (€ protected: {[a['eur_protected'] for a in b['created']]})")
        c.post("/api/sim/inject", json={"scenario": "A", "target_ad": "C2"})
        for _ in range(6):
            c.post("/api/sim/control", json={"action": "step"})
        live = [r for r in c.get("/api/eval").json()["scenarios"] if r["live"]]
        print(f"live injection A on C2 after 6 days: {live[0].get('predicted')} ({live[0].get('confidence')})")
        c.post("/api/sim/control", json={"action": "reset"})
    mb = peak_mb()
    print(f"done in {time.time() - t0:.1f}s; peak memory {mb:.0f} MB" if mb else f"done in {time.time() - t0:.1f}s")
    if problems:
        print("PROBLEMS:", *problems, sep="\n  ")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
