"""Process-wide state: the live simulator, its clock, and the SSE listeners. One FastAPI process owns it."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import pandas as pd

from app import config, db
from app.analytics import radar as radar_mod
from app.analytics import rootcause
from app.analytics.context import Ctx
from app.llm.agents import community_names
from app.sim import scenarios
from app.sim.simulator import Simulator
from app.sim.world import new_simulator
from app.sources.base import DAILY_STATS_COLUMNS
from app.sources.simulated import SimulatedSource

log = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sim: Simulator | None = None
        self.ctx: Ctx | None = None
        self.playing = False
        self.tick_seconds = config.TICK_SECONDS
        self.listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._radar: tuple[int, list[dict]] | None = None
        self._diag: dict[tuple[str, int], dict] = {}
        self._flagged: set[str] = set()
        self.names: dict[int, str] = {}
        self.persisted_rows = 0

    # ---------- lifecycle ----------
    def reset(self) -> None:
        with self.lock:
            t0 = time.time()
            db.reset_runtime_tables()
            sim = new_simulator()
            scenarios.apply_history(sim)
            sim.run(config.HISTORY_DAYS)
            self.sim = sim
            self.ctx = Ctx(SimulatedSource(sim), sim)
            self._radar, self._diag = None, {}
            self.persisted_rows = 0
            self.names = community_names()
            self._persist()
            self._flagged = {r["ad_id"] for r in self.radar() if r["status"] in ("failing", "at_risk")}
            self.playing = False
            log.info("Simulator reset: %d days of history in %.1fs", config.HISTORY_DAYS, time.time() - t0)

    def _persist(self) -> None:
        rows = self.sim.rows[self.persisted_rows:]
        if rows:
            df = pd.DataFrame(rows)
            cols = [c for c in DAILY_STATS_COLUMNS if c not in ("reach7", "impressions7")]
            with db.tx() as c:
                c.executemany(f"INSERT INTO daily_stats({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              df[cols].itertuples(index=False, name=None))
                ev = []
                for r in rows:
                    for t, col in (("impression", "impressions"), ("click", "clicks"), ("purchase", "conversions"), ("comment", "comments_total")):
                        ev.append((r["day"], r["ad_id"], r["community_id"], t, int(r[col]), r["revenue"] if t == "purchase" else 0.0))
                c.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", ev)
                truth = [t for t in self.sim.truth_rows if t["day"] >= (rows[0]["day"])]
                c.executemany("INSERT INTO truth_user_state VALUES (?,?,?,?)", [(t["day"], t["ad_id"], t["mean_exposures"], t["mean_fatigue"]) for t in truth])
            self.persisted_rows = len(self.sim.rows)

    # ---------- cached analytics ----------
    @property
    def day(self) -> int:
        return self.sim.day - 1

    def radar(self) -> list[dict]:
        with self.lock:
            if self._radar is None or self._radar[0] != self.day:
                self._radar = (self.day, radar_mod.radar(self.ctx))
            return self._radar[1]

    def diagnosis(self, ad_id: str, day: int | None = None) -> dict:
        day = self.day if day is None else day
        with self.lock:
            k = (ad_id, day)
            if k not in self._diag:
                self._diag[k] = rootcause.diagnose(self.ctx, ad_id, day, self.names)
            return self._diag[k]

    # ---------- clock ----------
    def tick(self) -> dict:
        with self.lock:
            rows = self.sim.step()
            self._persist()
            changed = sorted({r["ad_id"] for r in rows})
            alerts = []
            for r in self.radar():
                if r["status"] in ("failing", "at_risk") and r["ad_id"] not in self._flagged:
                    self._flagged.add(r["ad_id"])
                    alerts.append({"ad_id": r["ad_id"], "status": r["status"], "eur_at_risk": r["eur_at_risk"]})
                elif r["status"] in ("healthy", "watch"):
                    self._flagged.discard(r["ad_id"])
            evt = {"day": self.day, "changed": changed}
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

    # ---------- SSE ----------
    def broadcast(self, event: str, data: dict) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data, default=float)}\n\n"
        if self.loop is None:
            return
        for q in list(self.listeners):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)


STATE = AppState()
