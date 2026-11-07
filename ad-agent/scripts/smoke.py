"""End-to-end smoke test over every company and channel: planted scenarios -> diagnoses, variants ->
experiment -> learning, budget proposals, a live injection, and creating a new company + channel.
Uses whatever LLM_PROVIDER is set (run.py smoke forces cache-only, so it needs no network)."""
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
        c.post("/api/sim/control", json={"action": "reset"})
        for co in c.get("/api/companies").json():
            for ch in co["channels"]:
                if ch.get("live"):
                    print(f"{co['name']:16s} {ch['channel_id']:10s} {ch['platform']:9s} health {ch['health_counts']}  € at risk {ch['eur_at_risk']:.0f}")
        ev = c.get("/api/eval").json()
        for ch, e in ev["channels"].items():
            for r in e["scenarios"]:
                mark = "ok " if r.get("correct") else "MISS"
                print(f"  {mark} {ch:10s} {r['scenario']:3s} truth {r['truth']:20s} predicted {r.get('predicted')} ({r.get('confidence')})")
        print(f"planted-scenario accuracy: {ev['accuracy']:.0%} of {ev['n_scored']}")
        if ev["accuracy"] is None or ev["accuracy"] < 0.95:
            problems.append(f"planted-scenario accuracy {ev['accuracy']}")

        ch = "volt-ig"
        v = c.post(f"/api/ch/{ch}/creatives/A1/variants", json={}).json()
        print(f"A1 variants via {v['source']}: {[x['changed_dimension'] for x in v['variants']]}")
        if len(v["variants"]) < 2:
            problems.append("fewer than 2 variants")
        exp = c.post(f"/api/ch/{ch}/experiments", json={"source_ad_id": "A1", "variant_ids": [x["ad_id"] for x in v["variants"]]}).json()
        with c.stream("POST", f"/api/ch/{ch}/experiments/{exp['id']}/run") as s:
            body = "".join(s.iter_text())
        if "event: done" not in body:
            problems.append("experiment did not finish")
        b = c.post(f"/api/ch/{ch}/budget/propose").json()
        print(f"budget proposals on {ch}: {len(b['created'])} (€ protected: {[a['eur_protected'] for a in b['created']]})")

        c.post("/api/ch/volt-tt/sim/inject", json={"scenario": "L1", "target_ad": "T4"})
        for _ in range(7):
            c.post("/api/sim/control", json={"action": "step"})
        live = [r for r in c.get("/api/ch/volt-tt/eval").json()["scenarios"] if r["live"]]
        print(f"live fatigue on volt-tt T4 after 7 days: {live[0].get('predicted')} ({live[0].get('confidence')})")
        if live[0].get("predicted") != "creative_fatigue":
            problems.append("live injection not diagnosed")

        co = c.post("/api/companies", json={"name": "Smoke Test Co", "industry": "Test widgets", "avg_order_value": 30}).json()
        r = c.post(f"/api/companies/{co['company_id']}/channels", json={"platform": "tiktok", "segments": ["gaming", "students"]}).json()
        ads = c.get(f"/api/ch/{r['channel_id']}/ads").json()
        print(f"new company channel {r['channel_id']}: {len(ads)} ads live")
        if not ads:
            problems.append("new channel has no ads")
        tv = c.get("/api/ch/volt-ig/voices").json()
        print(f"top voices on volt-ig: {sum(len(x) for x in tv['communities'].values())} profiles in {len(tv['communities'])} communities")
        if not tv["available"] or not any(tv["communities"].values()):
            problems.append("no top voices on volt-ig")
        if "community" not in c.get("/api/ch/volt-ig/voices.csv").text[:20]:
            problems.append("voices csv broken")
        for chan in ("kin-meta", r["channel_id"]):
            maps = c.get(f"/api/ch/{chan}/campaigns").json()
            print(f"campaign maps on {chan}: " + "; ".join(f"{m['name']}: +{m['summary']['expand']} -{m['summary']['retreat']}" for m in maps))
            if not maps or not maps[0]["countries"]:
                problems.append(f"no campaign map on {chan}")
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
