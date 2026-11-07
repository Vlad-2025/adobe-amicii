"""Fetch real news context per country from the GDELT DOC 2.0 API (free, no key) for each company's markets.

Writes data/signals/<company_id>.json = {"fetched": iso, "query": ..., "countries": {"DE": "headline (domain, yyyy-mm-dd)", ...}}.
The opportunity map shows these lines in the country hover. Demand numbers stay simulated: the headlines are context only.

GDELT asks for at most 1 request per 5 seconds, so this sleeps between calls (a company with 11 markets takes ~1 minute).
Usage: python run.py fetch-news [company_id ...]
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import geo  # noqa: E402

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def headline(query: str, fips: str) -> str | None:
    params = {"query": f"({query}) sourcecountry:{fips}", "mode": "ArtList", "maxrecords": "3",
              "timespan": "7d", "sort": "HybridRel", "format": "json"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "ad-fatigue-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        arts = json.loads(body).get("articles", [])
    except json.JSONDecodeError:  # GDELT answers plain text for bad queries / rate limits
        print("   gdelt:", body[:120].strip())
        return None
    if not arts:
        return None
    a = arts[0]
    date = (a.get("seendate") or "")[:8]
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else ""
    return f"{a.get('title', '').strip()[:140]} ({a.get('domain', '')}, {date})"


def main(ids: list[str]) -> None:
    files = sorted((ROOT / "data" / "seed" / "companies").glob("*.json"))
    out_dir = ROOT / "data" / "signals"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        cfg = json.loads(f.read_text(encoding="utf-8"))
        cid = cfg["company_id"]
        if ids and cid not in ids:
            continue
        query = cfg.get("news_query") or cfg.get("brand", {}).get("product") or cfg["name"]
        print(f"{cid}: {query}")
        res = {}
        for code in cfg.get("markets", []):
            fips = geo.COUNTRIES.get(code, {}).get("fips")
            if not fips:
                continue
            try:
                h = headline(query, fips)
            except Exception as e:  # network down, blocked, rate-limited: keep going
                print(f"   {code}: {e}")
                h = None
            if h:
                res[code] = h
                print(f"   {code}: {h}")
            time.sleep(5.5)
        if not res:
            print("   nothing fetched, keeping any existing file")
            continue
        (out_dir / f"{cid}.json").write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                        "query": query, "countries": res}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"   -> data/signals/{cid}.json ({len(res)} countries)")


if __name__ == "__main__":
    main(sys.argv[1:])
