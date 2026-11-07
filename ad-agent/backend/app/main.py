"""FastAPI app: owns the simulator clock and the database; serves the built frontend in demo mode."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.api import audience, budget, creative, radar, system
from app.state import STATE
from app.world.build import WORLD_NPZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    if not WORLD_NPZ.exists() or not db.q("SELECT 1 FROM communities LIMIT 1"):
        from app.world.build import build

        log.info("No world yet: building it now (first start only)")
        await asyncio.to_thread(build)
    await asyncio.to_thread(STATE.reset)
    STATE.loop = asyncio.get_running_loop()
    task = asyncio.create_task(STATE.clock())
    yield
    task.cancel()


app = FastAPI(title="Ad Fatigue Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
for r in (radar.router, audience.router, creative.router, budget.router, system.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True, "day": STATE.day}


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
