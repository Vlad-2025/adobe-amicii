"""FastAPI app: owns the shared simulator clock and the database; serves the built frontend in demo mode."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, db, registry
from app.api import audience, budget, companies, creative, radar, system
from app.state import STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    registry.seed_companies()
    from app.state import world_ready
    from app.world.build import build_channel, seed_memory
    from app.world.embed import get_embedder

    missing = [c for c in registry.channels(kind="ads") if c["mode"] == "simulated" and not world_ready(c["channel_id"])]
    if missing:
        log.info("Building %d channel world(s) that are missing: %s", len(missing), [c["channel_id"] for c in missing])

        def build_missing():
            if not db.kv_get("embedder"):
                get_embedder(fresh=True)
            for co in {c["company_id"] for c in missing}:
                if not db.q("SELECT 1 FROM memory WHERE company_id=? LIMIT 1", (co,)):
                    seed_memory(co)
            for c in missing:
                build_channel(c["channel_id"])

        await asyncio.to_thread(build_missing)
    await asyncio.to_thread(STATE.reset)
    STATE.loop = asyncio.get_running_loop()
    task = asyncio.create_task(STATE.clock())
    yield
    task.cancel()


app = FastAPI(title="Ad Fatigue Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
for r in (companies.router, radar.router, audience.router, creative.router, budget.router, budget.link_router, system.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "day": STATE.world_day, "channels": list(STATE.rt)}


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
