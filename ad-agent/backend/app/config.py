"""Central configuration. Everything comes from .env (python-dotenv), never shell syntax,
so the same file works on Ubuntu and Windows."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
SEED = DATA / "seed"
BLUESKY = DATA / "bluesky"
MODELS = ROOT / "models"
CONFIG = ROOT / "config"
DB_PATH = Path(os.getenv("DB_PATH", str(DATA / "app.db")))
FRONTEND_DIST = ROOT / "frontend" / "dist"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # gemini | ollama | cache-only
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "15"))

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

SEED_RANDOM = int(os.getenv("SEED", "7"))
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "30"))
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "4"))

# Each digital twin stands for this many real people. Spend, impressions, clicks and
# conversions shown in the UI are scaled by it; rates (CTR, CVR) are unaffected.
TWIN_SCALE = int(os.getenv("TWIN_SCALE", "50"))
