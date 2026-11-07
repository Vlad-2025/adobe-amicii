"""Snapshot real Bluesky communities via the public AppView (no login needed for these reads).

    python run.py snapshot              # uses config/starter_packs.yaml
    python run.py snapshot --max 1500   # smaller crawl

Writes data/bluesky/{accounts,follows,interactions,posts}.parquet + snapshot_meta.json.
Polite: ~5 requests/second, exponential backoff on 429/5xx, resumable (per-account cache in
data/bluesky/cache/). Privacy: DIDs are hashed with a salt; handles and display names are dropped.
Run it once before the event and commit the output, so the demo never needs the network."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "bluesky"
CACHE = OUT / "cache"
API = "https://public.api.bsky.app/xrpc/"
RPS = 5.0


class Client:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=20, headers={"User-Agent": "ad-fatigue-agent-hackathon/0.1"})
        self.last = 0.0
        self.calls = 0

    def get(self, method: str, **params) -> dict | None:
        for attempt in range(6):
            wait = 1 / RPS - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                r = self.http.get(API + method, params=params)
            except httpx.HTTPError:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            return None  # 400/404: deleted or private account, bad pack
        return None

    def paged(self, method: str, key: str, limit_total: int, **params) -> list:
        out, cursor = [], None
        while len(out) < limit_total:
            p = dict(params, limit=100)
            if cursor:
                p["cursor"] = cursor
            d = self.get(method, **p)
            if not d:
                break
            out.extend(d.get(key, []))
            cursor = d.get("cursor")
            if not cursor:
                break
        return out[:limit_total]


def pack_uri_from_url(c: Client, url: str) -> str | None:
    # https://bsky.app/starter-pack/<handle-or-did>/<rkey>
    parts = url.rstrip("/").split("/")
    actor, rkey = parts[-2], parts[-1]
    if not actor.startswith("did:"):
        prof = c.get("app.bsky.actor.getProfile", actor=actor)
        if not prof:
            return None
        actor = prof["did"]
    return f"at://{actor}/app.bsky.graph.starterpack/{rkey}"


def find_packs(c: Client, spec: dict, n: int) -> list[str]:
    uris = []
    for url in spec.get("urls", []) or []:
        u = pack_uri_from_url(c, url)
        if u:
            uris.append(u)
    for q in spec.get("queries", []) or []:
        if len(uris) >= n:
            break
        d = c.get("app.bsky.graph.searchStarterPacks", q=q, limit=10)
        for sp in (d or {}).get("starterPacks", []):
            if sp["uri"] not in uris:
                uris.append(sp["uri"])
            if len(uris) >= n:
                break
    return uris[:n]


def pack_members(c: Client, uri: str) -> list[str]:
    d = c.get("app.bsky.graph.getStarterPack", starterPack=uri)
    if not d:
        return []
    lst = d["starterPack"].get("list", {}).get("uri")
    if not lst:
        return []
    items = c.paged("app.bsky.graph.getList", "items", 500, list=lst)
    return [i["subject"]["did"] for i in items]


def crawl_account(c: Client, did: str) -> dict:
    f = CACHE / (hashlib.sha1(did.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    follows = [x["did"] for x in c.paged("app.bsky.graph.getFollows", "follows", 300, actor=did)]
    feed = c.get("app.bsky.feed.getAuthorFeed", actor=did, limit=60, filter="posts_with_replies") or {}
    posts, inter = [], []
    for item in feed.get("feed", []):
        post = item.get("post", {})
        rec = post.get("record", {})
        reason = item.get("reason")
        if reason:  # a repost of someone else's post = an interaction
            a = post.get("author", {}).get("did")
            if a and a != did:
                inter.append(a)
            continue
        if post.get("author", {}).get("did") != did:
            continue
        parent = (item.get("reply") or {}).get("parent", {}).get("author", {}).get("did")
        if parent:
            if parent != did:
                inter.append(parent)
            continue
        langs = rec.get("langs") or []
        text = (rec.get("text") or "").strip()
        if text and (not langs or "en" in langs) and len(posts) < 20:
            posts.append({"text": text, "ts": rec.get("createdAt")})
    data = {"follows": follows, "interactions": inter, "posts": posts}
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None, help="max accounts (default from config)")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config" / "starter_packs.yaml").read_text(encoding="utf-8"))
    max_acc = args.max or cfg.get("max_accounts", 2500)
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    salt_f = OUT / ".salt"
    if not salt_f.exists():
        salt_f.write_text(os.getenv("BSKY_SALT") or secrets.token_hex(16), encoding="utf-8")
    salt = salt_f.read_text(encoding="utf-8").strip()
    h = lambda did: hashlib.sha256((salt + did).encode()).hexdigest()[:16]  # noqa: E731

    c = Client()
    per_key = max(1, max_acc // len(cfg["packs"]))
    members: dict[str, str] = {}
    used_packs = {}
    for key, spec in cfg["packs"].items():
        uris = find_packs(c, spec, cfg.get("max_packs_per_key", 3))
        used_packs[key] = uris
        got = 0
        for u in uris:
            for did in pack_members(c, u):
                if did not in members and got < per_key:
                    members[did] = key
                    got += 1
        print(f"{key:12s} {len(uris)} packs, {got} accounts", flush=True)
    if len(members) < 100:
        sys.exit("Too few accounts collected (network blocked?). The app will use the synthetic graph.")

    dids = list(members)
    inside = set(dids)
    acc_rows, f_rows, i_rows, p_rows = [], [], [], []
    t0 = time.time()
    for n, did in enumerate(dids, 1):
        d = crawl_account(c, did)
        uid = h(did)
        acc_rows.append({"user_id": uid, "source_pack": members[did]})
        f_rows += [{"src": uid, "dst": h(x), "weight": 1.0} for x in d["follows"] if x in inside]
        for x in d["interactions"]:
            if x in inside:
                i_rows.append({"src": uid, "dst": h(x), "weight": 1.0})
        p_rows += [{"user_id": uid, "text": p["text"], "ts": p["ts"]} for p in d["posts"]]
        if n % 50 == 0:
            eta = (time.time() - t0) / n * (len(dids) - n)
            print(f"  {n}/{len(dids)} accounts, {c.calls} requests, ~{eta / 60:.0f} min left", flush=True)

    inter = pd.DataFrame(i_rows, columns=["src", "dst", "weight"]).groupby(["src", "dst"], as_index=False)["weight"].sum()
    posts = pd.DataFrame(p_rows, columns=["user_id", "text", "ts"])
    posts["ts"] = pd.to_datetime(posts["ts"], utc=True, errors="coerce", format="ISO8601")
    posts = posts.dropna(subset=["ts"])
    pd.DataFrame(acc_rows).to_parquet(OUT / "accounts.parquet", index=False)
    pd.DataFrame(f_rows, columns=["src", "dst", "weight"]).to_parquet(OUT / "follows.parquet", index=False)
    inter.to_parquet(OUT / "interactions.parquet", index=False)
    posts.to_parquet(OUT / "posts.parquet", index=False)
    meta = {"source": "bluesky", "date": time.strftime("%Y-%m-%d"), "packs": used_packs,
            "counts": {"accounts": len(acc_rows), "follows": len(f_rows), "interactions": len(inter), "posts": len(posts)}, "requests": c.calls}
    (OUT / "snapshot_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta["counts"]))
    print("Done. Now run: python run.py build-world")


if __name__ == "__main__":
    main()
