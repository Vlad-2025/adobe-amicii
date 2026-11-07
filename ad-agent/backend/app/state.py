"""Process-wide state: one runtime per connected ads channel (simulator, analytics context, caches),
a shared clock that advances every simulated channel together, and the SSE listeners."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import pandas as pd

from app import config, db, registry
from app.analytics import radar as radar_mod
from app.analytics import rootcause, segments
from app.analytics.context import Ctx
from app.llm.agents import community_names
from app.sim import scenarios
from app.sim.simulator import Simulator
from app.sim.world import new_simulator
from app.sources.base import DAILY_STATS_COLUMNS
from app.sources.simulated import SimulatedSource
from app.world.build import world_path

log = logging.getLogger(__name__)


def world_ready(ch: str) -> bool:
    """Built = world file on disk AND its rows in the database (either can be deleted independently)."""
    return world_path(ch).exists() and bool(db.q("SELECT 1 FROM campaigns WHERE channel_id=? LIMIT 1", (ch,)))


class Runtime:
    """Everything live for one ads channel."""

    def __init__(self, ch: str) -> None:
        self.ch = ch
        info = registry.channel(ch)
        self.company_id = info["company_id"]
        self.platform = info["platform"]
        self.lag = int(info["config"].get("report_lag_days", 0))
        self.sim: Simulator | None = None
        self.ctx: Ctx | None = None
        self._radar: tuple[int, list[dict]] | None = None
        self._diag: dict[tuple[str, int], dict] = {}
        self.flagged: set[str] = set()
        self.names: dict[int, str] = {}
        self.persisted_rows = 0
        self.persisted_geo = 0

    def reset(self, days: int) -> None:
        db.reset_runtime_tables(self.ch)
        sim = new_simulator(self.ch)
        scenarios.apply_history(self.ch, sim)
        sim.run(days)
        self.sim = sim
        self.ctx = Ctx(self.ch, SimulatedSource(sim, self.lag), sim)
        self._radar, self._diag = None, {}
        self.persisted_rows = 0
        self.persisted_geo = 0
        self.names = community_names(self.ch)
        segments.clear_cache(self.ch)
        self.persist()
        self.flagged = {r["ad_id"] for r in self.radar() if r["status"] in ("failing", "at_risk")}

    @property
    def day(self) -> int:
        """Last day with data from the platform (world day minus reporting lag)."""
        return self.ctx.source.current_day()

    def invalidate(self) -> None:
        self._radar = None
        self._diag = {}

    def persist(self) -> None:
        geo = self.sim.country_rows[self.persisted_geo:]
        if geo:
            with db.tx() as c:
                c.executemany("INSERT INTO country_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                              [(self.ch, g["day"], g["ad_id"], g["campaign_id"], g["country"], g["impressions"], g["clicks"], g["spend"],
                                g["conversions"], g["revenue"]) for g in geo])
            self.persisted_geo = len(self.sim.country_rows)
        rows = self.sim.rows[self.persisted_rows:]
        if not rows:
            return
        df = pd.DataFrame(rows)
        cols = [c for c in DAILY_STATS_COLUMNS if c not in ("reach7", "impressions7")]
        with db.tx() as c:
            c.executemany(f"INSERT INTO daily_stats(channel_id,{','.join(cols)}) VALUES (?,{','.join('?' * len(cols))})",
                          [(self.ch, *r) for r in df[cols].itertuples(index=False, name=None)])
            ev = []
            for r in rows:
                for t, col in (("impression", "impressions"), ("click", "clicks"), ("purchase", "conversions"), ("comment", "comments_total")):
                    ev.append((self.ch, r["day"], r["ad_id"], r["community_id"], t, int(r[col]), r["revenue"] if t == "purchase" else 0.0))
            c.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?)", ev)
            first = rows[0]["day"]
            c.executemany("INSERT INTO truth_user_state VALUES (?,?,?,?,?)",
                          [(self.ch, t["day"], t["ad_id"], t["mean_exposures"], t["mean_fatigue"]) for t in self.sim.truth_rows if t["day"] >= first])
        self.persisted_rows = len(self.sim.rows)

    def radar(self) -> list[dict]:
        if self._radar is None or self._radar[0] != self.day:
            self._radar = (self.day, radar_mod.radar(self.ctx))
        return self._radar[1]

    def diagnosis(self, ad_id: str, day: int | None = None) -> dict:
        day = self.day if day is None else min(day, self.day)
        k = (ad_id, day)
        if k not in self._diag:
            self._diag[k] = rootcause.diagnose(self.ctx, ad_id, day, self.names)
        return self._diag[k]

    def step(self) -> list[dict]:
        rows = self.sim.step()
        self.persist()
        alerts = []
        for r in self.radar():
            if r["status"] in ("failing", "at_risk") and r["ad_id"] not in self.flagged:
                self.flagged.add(r["ad_id"])
                alerts.append({"channel_id": self.ch, "ad_id": r["ad_id"], "status": r["status"], "eur_at_risk": r["eur_at_risk"]})
            elif r["status"] in ("healthy", "watch"):
                self.flagged.discard(r["ad_id"])
        return alerts


class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.rt: dict[str, Runtime] = {}
        self.world_day = config.HISTORY_DAYS - 1
        self.playing = False
        self.tick_seconds = config.TICK_SECONDS
        self.listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def get(self, ch: str) -> Runtime:
        rt = self.rt.get(ch)
        if rt is None:
            raise KeyError(ch)
        return rt

    def live_channels(self) -> list[str]:
        return [c["channel_id"] for c in registry.channels(kind="ads") if c["mode"] == "simulated" and world_ready(c["channel_id"])]

    def reset(self) -> None:
        with self.lock:
            t0 = time.time()
            self.playing = False
            self.world_day = config.HISTORY_DAYS - 1
            self.rt = {}
            for ch in self.live_channels():
                rt = Runtime(ch)
                rt.reset(config.HISTORY_DAYS)
                self.rt[ch] = rt
            log.info("Reset %d channels with %d days of history in %.1fs", len(self.rt), config.HISTORY_DAYS, time.time() - t0)

    def add_channel(self, ch: str) -> None:
        """Start a newly built channel and catch it up to the shared clock."""
        with self.lock:
            rt = Runtime(ch)
            rt.reset(self.world_day + 1)
            self.rt[ch] = rt

    def tick(self) -> dict:
        with self.lock:
            alerts = []
            for rt in self.rt.values():
                alerts += rt.step()
            self.world_day += 1
            evt = {"day": self.world_day}
        self.broadcast("tick", evt)
        for a in alerts:
            self.broadcast("alert", a)
        return evt

    async def clock(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            if not self.playing:
                continue
            t = time.time()
            await asyncio.to_thread(self.tick)
            await asyncio.sleep(max(0.0, self.tick_seconds - (time.time() - t)))

    def broadcast(self, event: str, data: dict) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, default=float)}\n\n"
        if self.loop is None:
            return
        for q in list(self.listeners):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)


STATE = AppState()
