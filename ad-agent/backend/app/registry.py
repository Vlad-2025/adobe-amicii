"""Companies and their connected channels.

A company has a brand profile and any number of channels:
  - ads channels (Instagram/Facebook via Meta, TikTok, X, LinkedIn, ...): campaigns, ad sets, ads, daily reports
  - audience sources (Bluesky public graph, social listening): communities and what they talk about
Seed companies live in data/seed/companies/*.json; companies created in the UI live only in the DB."""
from __future__ import annotations

import json
import re
import time

from app import db
from app.config import SEED

COMPANY_DIR = SEED / "companies"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "co"


def seed_companies(force: bool = False) -> list[str]:
    """Load data/seed/companies/*.json into the registry (seed companies are overwritten on rebuild)."""
    ids = []
    for f in sorted(COMPANY_DIR.glob("*.json")):
        c = json.loads(f.read_text(encoding="utf-8"))
        cid = c["company_id"]
        ids.append(cid)
        exists = db.q("SELECT 1 FROM companies WHERE company_id=?", (cid,))
        if exists and not force:
            continue
        cfg = {k: v for k, v in c.items() if k not in ("channels", "audience_sources")}
        db.x("INSERT OR REPLACE INTO companies VALUES (?,?,?,?,?,?)", (cid, c["name"], c["industry"], json.dumps(cfg, ensure_ascii=False), _now(), 1))
        for s in c.get("audience_sources", []):
            db.x("INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (s["source_id"], cid, s["platform"], "audience", f"{s['platform'].title()} audience", s["handle"], s.get("mode", "simulated"),
                  "connected", json.dumps(s, ensure_ascii=False), _now()))
        for ch in c["channels"]:
            db.x("INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (ch["channel_id"], cid, ch["platform"], "ads", ch["name"], ch["handle"], ch.get("mode", "simulated"),
                  "connected" if ch.get("mode", "simulated") == "simulated" else "awaiting_credentials", json.dumps(ch, ensure_ascii=False), _now()))
    return ids


def companies() -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM companies ORDER BY seeded DESC, created_at, name"):
        r["config"] = json.loads(r["config"])
        r["channels"] = channels(r["company_id"])
        out.append(r)
    return out


def company(cid: str) -> dict:
    r = db.q("SELECT * FROM companies WHERE company_id=?", (cid,))
    if not r:
        raise KeyError(cid)
    r = r[0]
    r["config"] = json.loads(r["config"])
    return r


def channels(cid: str | None = None, kind: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM channels WHERE 1=1", []
    if cid:
        sql += " AND company_id=?"
        args.append(cid)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    out = []
    for r in db.q(sql + " ORDER BY kind DESC, created_at, channel_id", tuple(args)):
        r["config"] = json.loads(r["config"])
        out.append(r)
    return out


def channel(ch: str) -> dict:
    r = db.q("SELECT * FROM channels WHERE channel_id=?", (ch,))
    if not r:
        raise KeyError(ch)
    r = r[0]
    r["config"] = json.loads(r["config"])
    return r


def set_channel_status(ch: str, status: str) -> None:
    db.x("UPDATE channels SET status=? WHERE channel_id=?", (status, ch))


def brand_of(ch: str) -> dict:
    return company(channel(ch)["company_id"])["config"]["brand"]


def economics_of(ch: str) -> dict:
    return company(channel(ch)["company_id"])["config"]["economics"]


# ---------------- creation from the UI ----------------
def create_company(name: str, industry: str, description: str, tone: str, banned: list[str], competitors: list[str],
                   avg_order_value: float, conversion_name: str, base_cvr: float) -> str:
    cid = slug(name)
    n = 2
    while db.q("SELECT 1 FROM companies WHERE company_id=?", (cid,)):
        cid = f"{slug(name)}-{n}"
        n += 1
    cfg = {
        "company_id": cid, "name": name, "industry": industry, "fictional": False, "description": description,
        "brand": {"name": name, "product": industry, "price_eur": avg_order_value, "target_age": "18-65", "tone": tone or "clear and friendly",
                  "banned_phrases": banned, "health_claim_patterns": [], "competitors": competitors, "limits": {"headline": 60, "body": 150, "cta": 20}},
        "economics": {"order_values": [avg_order_value], "order_probs": [1.0], "base_cvr": base_cvr, "price_factor": 0.3, "price_factor_offer": 0.2,
                      "conversion_name": conversion_name or "purchase"},
        "memory": [], "variant_bank": {},
    }
    db.x("INSERT INTO companies VALUES (?,?,?,?,?,?)", (cid, name, industry, json.dumps(cfg, ensure_ascii=False), _now(), 0))
    return cid


def new_channel_id(cid: str, platform: str) -> str:
    base = f"{cid}-{platform}"[:30]
    ch, n = base, 2
    while db.q("SELECT 1 FROM channels WHERE channel_id=?", (ch,)):
        ch = f"{base}-{n}"
        n += 1
    return ch


def insert_channel(ch_cfg: dict, cid: str, kind: str, mode: str, status: str) -> None:
    db.x("INSERT OR REPLACE INTO channels VALUES (?,?,?,?,?,?,?,?,?,?)",
         (ch_cfg["channel_id"], cid, ch_cfg["platform"], kind, ch_cfg["name"], ch_cfg["handle"], mode, status, json.dumps(ch_cfg, ensure_ascii=False), _now()))
