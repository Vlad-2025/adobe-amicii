# Volt · Ad Fatigue Agent (IT Fest hackathon)

An AI marketing agent that models a brand's audience on real Bluesky communities, spots ads that
are dying before they die, diagnoses why, and proposes and tests a fix. It runs on a laptop for €0.

**Data foundation → AI decisioning → real-time execution.** Real audiences go in, failing ads are
detected and diagnosed, tested fixes come out, and every action feeds back into the simulator.

## Quick start (Ubuntu or Windows 10/11, 8 GB RAM is enough)

Prerequisites: **Python 3.11+** and **Node.js 20 LTS**. [`uv`](https://docs.astral.sh/uv/) is
optional; it speeds up setup and installs the right Python for you.

```bash
python run.py setup     # ~3-5 min: venv, packages, world build, model training, UI build
python run.py demo      # open http://127.0.0.1:8000
```

On Windows use `py run.py setup` if `python` is not on PATH. There is no `make` and no Docker, and
the same commands work on both systems.

The first `setup` downloads the MiniLM embedding model (~90 MB) once. Offline, it waits ~40 s for
retries and then falls back to hashed embeddings, which still work. Set `EMBEDDER=hash` in `.env`
to skip the wait. Whichever embedder built the world is pinned, so runtime embeddings always
match it. If you change it, run `python run.py build-world` again.

### Before the event

1. **Real audiences:** `python run.py snapshot` crawls the starter packs in
   `config/starter_packs.yaml` (~15-30 min for 2,500 accounts at 5 requests/s; resumable), then
   `python run.py build-world` and `python run.py train`. Commit `data/bluesky/` so the demo
   never needs the network. Without a snapshot the app uses a synthetic graph with the same
   schema.
2. **LLM:** put a free `GEMINI_API_KEY` from [AI Studio](https://aistudio.google.com) in `.env`,
   and check which Flash / Flash-Lite model the free tier offers today (`GEMINI_MODEL`). For
   private/offline mode: install [Ollama](https://ollama.com), `ollama pull qwen3:1.7b`
   (`qwen3:4b` only on a 16 GB machine), and set `LLM_PROVIDER=ollama`.
3. **Warm the cache:** `python run.py warm-cache` runs the demo path once with the real LLM and
   saves every answer to `data/seed/llm_cache.json`. On stage, those answers are served from the
   cache, so venue Wi-Fi does not matter. Run it on the demo laptop after the final `build-world`.
4. **Check:** `python run.py smoke` runs everything end to end with the LLM in cache-only mode
   and prints peak memory (~0.6 GB for the backend).
5. **Discord (optional):** set `DISCORD_WEBHOOK_URL`. For approve links to work from a phone, set
   `PUBLIC_BASE_URL=http://<laptop LAN IP>:8000`, run `python run.py demo --host 0.0.0.0`, and
   accept the Windows Firewall prompt.
6. Record a backup video of the demo path.

## Demo path (3 minutes)

| Time | Screen | What to show |
| --- | --- | --- |
| 0:00 | Radar | 4 failing ads, € at risk, days-to-fatigue forecast with a confidence band |
| 0:20 | Communities | "Digital twins of real Bluesky communities": the graph, persona cards, heatmap |
| 0:40 | Radar → A1 → Diagnose | Fatigue 99%, other causes ruled out, evidence with values, narrative streams in |
| 1:10 | D2 detail | Saturated in tech, healthy in gaming → keep for one, replace for the other |
| 1:20 | Creative Studio | Memory items, 3 one-change variants, resonance, brand guard |
| 1:45 | Experiments → Budget | Thompson sampling picks a winner in ~4 days; apply it; approve a budget move (Discord) |
| 2:05 | Sim control | A judge picks "Break something" (A on C2 is diagnosed in ~5 days; at 1 s/day that's ~5 s) |
| 2:25 | Sim control → Evaluation | 5/5 planted scenarios correct, NMI, € protected. LLM switch: cloud ↔ local |

## How it works

- **World build** (`backend/app/world`): snapshot → MiniLM embeddings (fastembed, ONNX, no
  PyTorch) → interest vector per account → Leiden communities (Louvain fallback) → c-TF-IDF
  keywords, central posts, active hours → LLM persona per community.
- **Simulator** (`backend/app/sim`): numpy. CPM auction, delivery weighted by affinity ×
  activity, click logit with a frequency penalty, conversions × landing-page health. **Fatigue
  carries over between similar creatives** (cos²), so cosmetic rewrites inherit fatigue and new
  angles don't. Planted scenarios A–F live in `config/scenarios.yaml`.
- **Analytics** (`backend/app/analytics`) reads only `daily_stats`, the same shape a real ad
  platform reports. `sources/meta_stub.py` and `google_stub.py` carry the real field mappings.
  - Radar: pooled-rate z-tests (CTR, CVR) and robust z (CPM, ROAS) against a healthy baseline
    that ends 7 days before today.
  - Fatigue predictor: LightGBM with p10/p90 quantiles, trained on 500 simulator runs.
  - Root cause: 8 evidence functions → hand-tuned scores → softmax. It gets 29/30 planted cases
    right across 6 random seeds, and 5/5 on the demo seed.
  - Experiments: two-proportion power calculation for the plan, then Thompson sampling on a
    forked simulator.
  - Budget Autopilot: the action follows the diagnosed cause. € protected comes from 5 paired
    counterfactual forks, and an action is proposed only if it actually saves money.
- **LLM** (`backend/app/llm`): 4 call sites (profiler, narrator, strategist, learning writer),
  about 5 calls per demo run. Order: cache → Gemini → Ollama → deterministic templates.
  Pydantic validation with one retry. The LLM never produces a number shown as data; the brand
  guard, length limits and dedupe are code.

## Repo layout

```
backend/app/   main.py (FastAPI + SSE + sim clock), state.py, api/, sim/, analytics/, llm/, sources/, integrations/, world/
scripts/       bluesky_snapshot.py, smoke.py, warm_cache.py
config/        scenarios.yaml, starter_packs.yaml
data/seed/     brand, campaigns + creatives, comment bank, memory, variant bank, (llm_cache.json)
frontend/      Vite + React 18 + TypeScript + Adobe React Spectrum + Recharts
run.py         task runner (replaces make)
```

## Memory on an 8 GB laptop

The demo runs as one process: FastAPI serves the built frontend, so there is no Node dev server.
The backend peaks around 0.6 GB. If you also run Ollama, it adds ~1.5-2 GB with `qwen3:1.7b`
(2k context). Close the IDE before presenting.

## Honest framing for judges

Audiences and their interests are real (public Bluesky). The ad platform is simulated, because no
live ad account can be connected in 12 hours. The fatigue model is trained on simulation and
would be retrained per brand on real data. Every diagnosis is graded against a known planted
truth.
