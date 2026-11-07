"""Builds a Simulator from the world build + config tables."""
from __future__ import annotations

import json

from app import db
from app.config import SEED_RANDOM
from app.sim.simulator import Simulator
from app.world.build import load_world


def config_tables() -> tuple[dict, dict, list[dict]]:
    campaigns = {r["campaign_id"]: r for r in db.q("SELECT * FROM campaigns")}
    ad_sets = {}
    for r in db.q("SELECT * FROM ad_sets"):
        r["target_communities"] = json.loads(r["target_communities"])
        ad_sets[r["ad_set_id"]] = r
    ads = []
    for r in db.q("SELECT * FROM creatives WHERE parent_ad_id IS NULL ORDER BY rowid"):
        r["emb"] = db.unblob(r.pop("embedding"))
        ads.append(r)
    return campaigns, ad_sets, ads


def new_simulator(seed: int = SEED_RANDOM) -> Simulator:
    world = load_world()
    campaigns, ad_sets, ads = config_tables()
    return Simulator(world, ad_sets, campaigns, ads, seed=seed)
