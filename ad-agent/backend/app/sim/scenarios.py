"""Planted scenarios (config/scenarios.yaml) -> simulator effects + hidden truth rows."""
from __future__ import annotations

import json

import yaml

from app import db
from app.config import CONFIG
from app.sim.simulator import Effect, Simulator


def load() -> dict:
    return yaml.safe_load((CONFIG / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]


def _community_for_pack(pack: str) -> int | None:
    r = db.q("SELECT community_id FROM communities WHERE dominant_pack=? ORDER BY size DESC LIMIT 1", (pack,))
    return r[0]["community_id"] if r else None


def _effect(sid: str, sc: dict, start: int, end: int | None, live: bool, use_live_effect: bool = False) -> Effect:
    eff = sc.get("live_effect") if use_live_effect and sc.get("live_effect") else sc["effect"]
    t = sc["target"]
    return Effect(
        sid=sid, type=eff["type"], value=float(eff["value"]), start=start, end=end,
        ad=t.get("ad"), campaign=t.get("campaign"),
        community=_community_for_pack(t["pack"]) if t.get("pack") else None, live=live,
    )


def apply_history(sim: Simulator) -> None:
    for sid, sc in load().items():
        h = sc.get("history")
        if not h:
            continue
        sim.add_effect(_effect(sid, sc, h["start_day"], h.get("end_day"), live=False))
        db.x("INSERT INTO truth_scenarios VALUES (?,?,?,?,?,?)",
             (sid, json.dumps(sc["target"]), h["start_day"], h.get("end_day"), sc["label"], 0))


def inject(sim: Simulator, sid: str, target_ad: str | None = None) -> dict:
    sc = load()[sid]
    sc = dict(sc)
    if target_ad:  # let the UI point a scenario at a chosen ad / its campaign
        ad = sim.ads[sim.idx[target_ad]]
        t = dict(sc["target"])
        if "ad" in t:
            t["ad"] = target_ad
        if "campaign" in t:
            t["campaign"] = ad.campaign_id
        sc["target"] = t
    start = sim.day
    dur = sc.get("live_duration")
    end = start + dur - 1 if dur else None
    e = _effect(sid, sc, start, end, live=True, use_live_effect=True)
    sim.add_effect(e)
    db.x("INSERT INTO truth_scenarios VALUES (?,?,?,?,?,?)", (sid, json.dumps(sc["target"]), start, end, sc["label"], 1))
    return {"scenario": sid, "name": sc["name"], "start_day": start, "end_day": end, "target": sc["target"]}
