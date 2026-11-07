# Ad Fatigue Agent (IT Fest hackathon)

A tool for a marketing manager or sales exec. You create a **company profile** (brand kit and
conversion economics) and connect its **channels**:
- **Ad accounts:** Instagram/Facebook via Meta, TikTok, X, LinkedIn.
- **Audience sources:** the Bluesky public graph, or social listening.

For each ad channel the agent spots ads that are dying before they die, diagnoses why, and
proposes and tests a fix. Analytics appear whenever a channel's connector reports data. It runs on
a laptop for €0.

**Data foundation → AI decisioning → real-time execution.**

## What's in the demo

Four **fictional** companies with 7 ad channels and 20 planted problems:

| Company | What it sells | Channels | Audience |
| --- | --- | --- | --- |
| Volt | Canned cold brew (D2C) | Instagram, TikTok | Bluesky communities (Instagram), TikTok segments |
| Kinetra | Running shoes (e-commerce) | Facebook + Instagram (Meta) | Meta interest × age segments |
| Tallyhawk | Invoicing SaaS (trial signups) | LinkedIn, X | Job function / seniority segments, X interest segments |
| Mosslight Games | Indie game (Steam wishlists) | X, TikTok | Bluesky communities (X), TikTok segments |

Every channel uses a **simulated feed**: a fake ad platform reporting what the real API would.
You can create your own company in the UI and connect a channel:
- **Simulated feed:** pick audience segments; it builds a demo feed with 30 days of history in seconds.
- **Live API:** the channel shows which credentials and approvals that platform needs. The live
  connectors are stubs with real field mappings.

## Real life vs this demo

| Here (simulated) | In production |
| --- | --- |
| Daily stats per ad and segment | Meta Marketing API Insights, TikTok Reporting API, X Ads API stats, LinkedIn adAnalytics: all aggregated per campaign / ad set / ad, with demographic or targeting breakdowns. Never per person. |
| Purchases / signups / wishlists | The pixel / Conversions API of each platform, or the shop / CRM |
| Audience communities | Bluesky public graph (open). Closed platforms give follower demographics to the account owner only, never follower lists, so communities come from open networks or paid social-listening tools. |
| Ad-platform segments | Your ad sets' targeting definitions (interests, job functions, ages) |
| Budget changes, new creatives | The same ads APIs with write permission (e.g. ads_management on Meta), after human approval |
| Reporting delay | Per platform: same day for Meta, about 1 day for TikTok, X and LinkedIn |

Bluesky has no native ads (as of mid-2026), so it's used as an audience source, not an ad channel.


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
   `config/starter_packs.yaml` (~20-40 min for 3,500 accounts at 5 requests/s; resumable), then
   `python run.py build-world` and `python run.py train`. The two Bluesky-backed channels
   (Volt Instagram, Mosslight X) then use real communities. Commit `data/bluesky/` so the demo
   never needs the network. Without a snapshot they use a synthetic graph with the same schema.
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
| 0:00 | Companies | 4 companies, 7 ad channels, total € at risk, failing ads, a health bar per channel |
| 0:15 | Volt → Instagram → Audiences | "Digital twins of real Bluesky communities": graph, persona cards, heatmap |
| 0:35 | Radar → A1 → Diagnose | Fatigue 99%, other causes ruled out, evidence with values, narrative streams in |
| 1:00 | Tallyhawk → LinkedIn → Audiences | Same agent, B2B: segments are job functions, no follower graph (LinkedIn doesn't give one) |
| 1:15 | Creative Studio | Memory items, 3 one-change variants, resonance, brand guard |
| 1:40 | Experiments → Budget | Thompson sampling picks a winner in ~4 days; apply it; approve a budget move (Discord) |
| 2:00 | Company profile → Connect a channel | What each platform's API really gives you; connect a simulated feed live |
| 2:20 | Sim control | A judge picks "Break something"; evaluation shows 20/20 planted problems diagnosed |
| 2:45 | LLM switch | Cloud ↔ local, € 0 inference |

## How it works

- **Registry** (`backend/app/registry.py`): companies and channels. Seed companies live in
  `data/seed/companies/*.json` (brand kit, economics, memory, channels with campaigns, ads and
  planted scenarios). Companies created in the UI live in the database.
- **World build per channel** (`backend/app/world`):
  - Audience: Bluesky snapshot or synthetic segments.
  - MiniLM embeddings (fastembed, ONNX, no PyTorch).
  - An interest vector per twin.
  - Communities: Leiden on the follow graph for Bluesky audiences; one per targeting segment
    for ad platforms.
  - c-TF-IDF keywords, active hours, and an LLM persona per community.
- **Simulator** (`backend/app/sim`): numpy. CPM auction, delivery weighted by affinity ×
  activity, click logit with a frequency penalty, conversions × landing-page health. **Fatigue
  carries over between similar creatives** (cos²), so cosmetic rewrites inherit fatigue and new
  angles don't. Each channel has its own economics (CPM, base CTR, conversion value), reporting
  delay and `twin_scale` (real people per twin). All channels share one clock.
- **Analytics** (`backend/app/analytics`) reads only `daily_stats`, the same shape a real ad
  platform reports. `sources/meta_stub.py` and `google_stub.py` carry the real field mappings.
  - Radar: pooled-rate z-tests (CTR, CVR) and robust z (CPM, ROAS) against a healthy baseline
    that ends 7 days before today.
  - Fatigue predictor: LightGBM with p10/p90 quantiles, trained on 500 simulator runs.
  - Root cause: 8 evidence functions → hand-tuned scores → softmax. It gets 20/20 planted
    problems right on the demo seed and 97/100 across 5 random seeds, over 7 channels and
    4 businesses.
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
backend/app/   main.py (FastAPI + SSE + shared clock), state.py (a runtime per channel), registry.py,
               api/ (companies, per-channel /api/ch/{channel}/...), sim/, analytics/, llm/,
               sources/ (platforms.py = what each real API gives, Meta/Google stubs), integrations/, world/
scripts/       bluesky_snapshot.py, smoke.py, warm_cache.py
config/        starter_packs.yaml
data/seed/     companies/*.json, comments.json, (llm_cache.json)
frontend/      Vite + React 18 + TypeScript + Adobe React Spectrum + Recharts
run.py         task runner (replaces make)
```

## Memory on an 8 GB laptop

The demo runs as one process: FastAPI serves the built frontend, so there is no Node dev server.
With all 7 channels running, the backend peaks around 0.6 GB. If you also run Ollama, it adds ~1.5-2 GB with `qwen3:1.7b`
(2k context). Close the IDE before presenting.

## Honest framing for judges

The companies are fictional. Bluesky audiences are real once you run the snapshot. The ad
platforms are simulated, because no live ad account can be connected in 12 hours. Every
simulated feed only reports what the real API would report. The fatigue model is trained on simulation and
would be retrained per brand on real data. Every diagnosis is graded against a known planted
truth.
