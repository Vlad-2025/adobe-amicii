"""Planted scenarios (per channel, from the channel config) -> simulator effects + hidden truth rows."""
from __future__ import annotations

import json

from app import db, registry
from app.sim.simulator import Effect, Simulator


def load(ch: str) -> dict:
    return registry.channel(ch)["config"].get("scenarios", {})


def _community_for_pack(ch: str, pack: str) -> int | None:
    r = db.q("SELECT community_id FROM communities WHERE channel_id=? AND dominant_pack=? ORDER BY size DESC LIMIT 1", (ch, pack))
    return r[0]["community_id"] if r else None


def _effect(ch: str, sid: str, sc: dict, start: int, end: int | None, live: bool, use_live_effect: bool = False) -> Effect:
    eff = sc.get("live_effect") if use_live_effect and sc.get("live_effect") else sc["effect"]
    t = sc["target"]
    return Effect(sid=sid, type=eff["type"], value=float(eff["value"]), start=start, end=end, ad=t.get("ad"), campaign=t.get("campaign"),
                  community=_community_for_pack(ch, t["pack"]) if t.get("pack") else None, live=live)


def apply_history(ch: str, sim: Simulator) -> None:
    for sid, sc in load(ch).items():
        h = sc.get("history")
        if not h:
            continue
        sim.add_effect(_effect(ch, sid, sc, h["start_day"], h.get("end_day"), live=False))
        db.x("INSERT INTO truth_scenarios VALUES (?,?,?,?,?,?,?)", (ch, sid, json.dumps(sc["target"]), h["start_day"], h.get("end_day"), sc["label"], 0))


def inject(ch: str, sim: Simulator, sid: str, target_ad: str | None = None) -> dict:
    sc = dict(load(ch)[sid])
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
    sim.add_effect(_effect(ch, sid, sc, start, end, live=True, use_live_effect=True))
    db.x("INSERT INTO truth_scenarios VALUES (?,?,?,?,?,?,?)", (ch, sid, json.dumps(sc["target"]), start, end, sc["label"], 1))
    return {"scenario": sid, "name": sc["name"], "start_day": start, "end_day": end, "target": sc["target"]}
