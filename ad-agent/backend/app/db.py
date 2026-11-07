"""SQLite storage, organized in the layers from the design doc:
registry (companies, channels) -> source -> config -> raw -> hidden -> cleaned -> business -> system.
Every per-channel table carries channel_id; memory is per company."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np

from app.config import DB_PATH

SCHEMA_VERSION = 3

SCHEMA = """
-- Registry
CREATE TABLE IF NOT EXISTS companies (company_id TEXT PRIMARY KEY, name TEXT, industry TEXT, config TEXT, created_at TEXT, seeded INTEGER);
CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, company_id TEXT, platform TEXT, kind TEXT, name TEXT, handle TEXT,
  mode TEXT, status TEXT, config TEXT, created_at TEXT);
-- Source (world build)
CREATE TABLE IF NOT EXISTS accounts (channel_id TEXT, user_id TEXT, source_pack TEXT, interest_vec BLOB, activity REAL,
  active_hours TEXT, price_sens REAL, community_id INTEGER);
CREATE TABLE IF NOT EXISTS follows (channel_id TEXT, src TEXT, dst TEXT, weight REAL);
CREATE TABLE IF NOT EXISTS interactions (channel_id TEXT, src TEXT, dst TEXT, weight REAL);
CREATE TABLE IF NOT EXISTS posts (channel_id TEXT, user_id TEXT, text TEXT, ts TEXT, embedding BLOB);
-- Config
CREATE TABLE IF NOT EXISTS campaigns (channel_id TEXT, campaign_id TEXT, name TEXT, objective TEXT, max_cpa REAL, min_roas REAL, total_budget REAL, countries TEXT);
CREATE TABLE IF NOT EXISTS ad_sets (channel_id TEXT, ad_set_id TEXT, campaign_id TEXT, name TEXT, daily_budget REAL, target_communities TEXT);
CREATE TABLE IF NOT EXISTS creatives (channel_id TEXT, ad_id TEXT, ad_set_id TEXT, hook TEXT, body TEXT, cta TEXT, offer TEXT,
  tone TEXT, angle TEXT, embedding BLOB, parent_ad_id TEXT, status TEXT, changed_dimension TEXT, hypothesis TEXT);
-- Raw
CREATE TABLE IF NOT EXISTS events (channel_id TEXT, day INTEGER, ad_id TEXT, community_id INTEGER, type TEXT, n INTEGER, value REAL);
-- Hidden (evaluation panel only)
CREATE TABLE IF NOT EXISTS truth_scenarios (channel_id TEXT, scenario_id TEXT, target TEXT, start_day INTEGER, end_day INTEGER, label TEXT, live INTEGER);
CREATE TABLE IF NOT EXISTS truth_user_state (channel_id TEXT, day INTEGER, ad_id TEXT, mean_exposures REAL, mean_fatigue REAL);
-- Cleaned
CREATE TABLE IF NOT EXISTS country_stats (channel_id TEXT, day INTEGER, ad_id TEXT, campaign_id TEXT, country TEXT, impressions REAL,
  clicks REAL, spend REAL, conversions REAL, revenue REAL);
CREATE TABLE IF NOT EXISTS daily_stats (channel_id TEXT, day INTEGER, ad_id TEXT, community_id INTEGER, impressions REAL, reach REAL,
  clicks REAL, spend REAL, conversions REAL, revenue REAL, comments_annoyed REAL, comments_total REAL);
-- Business
CREATE TABLE IF NOT EXISTS communities (channel_id TEXT, community_id INTEGER, size INTEGER, keywords TEXT, persona TEXT,
  central_posts TEXT, hours TEXT, dominant_pack TEXT, pack_share TEXT, nmi_vs_seed REAL, label TEXT);
CREATE TABLE IF NOT EXISTS diagnoses (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, ad_id TEXT, day INTEGER, scores TEXT,
  evidence TEXT, narrative TEXT, true_label TEXT, predicted TEXT);
CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, source_ad_id TEXT, arms TEXT, plan TEXT,
  sample_size INTEGER, allocation_history TEXT, winner TEXT, status TEXT, learning_id INTEGER);
CREATE TABLE IF NOT EXISTS budget_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, day INTEGER, from_ad_set TEXT,
  to_ad_set TEXT, amount REAL, reason TEXT, status TEXT, eur_protected REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT, brand TEXT, insight TEXT, evidence TEXT,
  applies_to TEXT, winner INTEGER, embedding BLOB, created_day INTEGER, channel_id TEXT);
-- System
CREATE TABLE IF NOT EXISTS llm_cache (prompt_hash TEXT PRIMARY KEY, task TEXT, provider TEXT, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_stats ON daily_stats(channel_id, day);
CREATE INDEX IF NOT EXISTS ix_posts ON posts(channel_id);
CREATE INDEX IF NOT EXISTS ix_accounts ON accounts(channel_id);
CREATE INDEX IF NOT EXISTS ix_follows ON follows(channel_id);
"""

RUNTIME_TABLES = ("events", "truth_scenarios", "truth_user_state", "daily_stats", "country_stats", "diagnoses", "experiments", "budget_actions")
WORLD_TABLES = ("accounts", "follows", "interactions", "posts", "communities", "campaigns", "ad_sets", "creatives")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
        r = c.execute("SELECT value FROM kv WHERE key='schema_version'").fetchone()
        if not r or json.loads(r[0]) != SCHEMA_VERSION:  # older layout: start clean (the LLM cache file re-seeds the cache)
            tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for t in tables:
                c.execute(f"DROP TABLE IF EXISTS {t}")
        c.executescript(SCHEMA)
        c.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('schema_version', ?)", (json.dumps(SCHEMA_VERSION),))
        import_llm_cache(c)
        _conn = c
    return _conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = conn()
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def q(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        return conn().execute(sql, args).lastrowid


def blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def unblob(b: bytes | None) -> np.ndarray | None:
    return None if b is None else np.frombuffer(b, dtype=np.float32)


def kv_get(key: str, default: Any = None) -> Any:
    r = q("SELECT value FROM kv WHERE key=?", (key,))
    return json.loads(r[0]["value"]) if r else default


def kv_set(key: str, value: Any) -> None:
    x("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))


def reset_runtime_tables(channel_id: str) -> None:
    """Clear what the simulator and agents wrote for one channel; keep its world build and the LLM cache."""
    with tx() as c:
        for t in RUNTIME_TABLES:
            c.execute(f"DELETE FROM {t} WHERE channel_id=?", (channel_id,))
        c.execute("DELETE FROM creatives WHERE channel_id=? AND parent_ad_id IS NOT NULL", (channel_id,))
        c.execute("UPDATE creatives SET status='active' WHERE channel_id=?", (channel_id,))
        c.execute("DELETE FROM memory WHERE channel_id=? AND created_day >= 0", (channel_id,))


def delete_world(channel_id: str) -> None:
    with tx() as c:
        for t in WORLD_TABLES + RUNTIME_TABLES:
            c.execute(f"DELETE FROM {t} WHERE channel_id=?", (channel_id,))


def _cache_file():
    from app.config import SEED

    return SEED / "llm_cache.json"


def import_llm_cache(c: sqlite3.Connection) -> None:
    """Seed the LLM cache from data/seed/llm_cache.json (written by `python run.py warm-cache`)."""
    f = _cache_file()
    if not f.exists() or c.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]:
        return
    rows = json.loads(f.read_text(encoding="utf-8"))
    c.executemany("INSERT OR IGNORE INTO llm_cache VALUES (?,?,?,?,?)",
                  [(r["prompt_hash"], r["task"], r["provider"], r["response"], r["created_at"]) for r in rows])


def export_llm_cache() -> int:
    rows = q("SELECT * FROM llm_cache")
    _cache_file().write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(rows)
