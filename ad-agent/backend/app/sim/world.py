"""Builds a channel's Simulator from its world build + config tables + company economics."""
from __future__ import annotations

import json

from app import db, registry
from app.config import SEED_RANDOM
from app.sim.simulator import Simulator
from app.world.build import load_world


def config_tables(ch: str) -> tuple[dict, dict, list[dict]]:
    campaigns = {r["campaign_id"]: r for r in db.q("SELECT * FROM campaigns WHERE channel_id=?", (ch,))}
    ad_sets = {}
    for r in db.q("SELECT * FROM ad_sets WHERE channel_id=?", (ch,)):
        r["target_communities"] = json.loads(r["target_communities"])
        ad_sets[r["ad_set_id"]] = r
    ads = []
    for r in db.q("SELECT * FROM creatives WHERE channel_id=? AND parent_ad_id IS NULL ORDER BY rowid", (ch,)):
        r["emb"] = db.unblob(r.pop("embedding"))
        ads.append(r)
    return campaigns, ad_sets, ads


def sim_params(ch: str) -> dict:
    cfg = registry.channel(ch)["config"]
    return {**cfg.get("sim", {}), "economics": registry.economics_of(ch)}


def new_simulator(ch: str, seed: int = SEED_RANDOM) -> Simulator:
    world = load_world(ch)
    campaigns, ad_sets, ads = config_tables(ch)
    return Simulator(world, ad_sets, campaigns, ads, seed=seed, params=sim_params(ch))
