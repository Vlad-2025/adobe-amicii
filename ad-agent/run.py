#!/usr/bin/env python3
"""Cross-platform task runner (Windows has no `make`). Runs with any Python 3.10+, no packages needed.

    python run.py setup        create .venv, install Python + frontend deps, build world, train model, build UI
    python run.py demo         serve the built app on http://127.0.0.1:8000 (one process, no Node)
    python run.py dev          backend with reload + Vite dev server on http://localhost:5173
    python run.py smoke        end-to-end check (cache-only LLM), prints peak memory
    python run.py snapshot     crawl Bluesky starter packs -> data/bluesky/*.parquet
    python run.py build-world  embeddings + communities + personas from the snapshot (or synthetic)
    python run.py train        train the fatigue predictor (~30 s)
    python run.py build        build the frontend into frontend/dist
    python run.py warm-cache   run the demo path once with the real LLM and save every answer
    python run.py fetch-trends refresh cached Google Trends (optional, needs `pip install pytrends`)

Extra args after the command are passed through (e.g. `python run.py demo --host 0.0.0.0`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WIN = os.name == "nt"
PY = VENV / ("Scripts/python.exe" if WIN else "bin/python")
FRONT = ROOT / "frontend"


def env() -> dict:
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"  # Windows defaults to cp1252; Bluesky posts carry emoji
    e["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + e.get("PYTHONPATH", "")
    return e


def sh(cmd: list, cwd: Path = ROOT, check: bool = True) -> int:
    print("»", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env(), check=check).returncode


def need_venv() -> None:
    if not PY.exists():
        sys.exit("No .venv yet. Run: python run.py setup")


def npm() -> str:
    n = shutil.which("npm.cmd" if WIN else "npm") or shutil.which("npm")
    if not n:
        sys.exit("npm not found. Install Node.js 20 LTS from https://nodejs.org and reopen the terminal.")
    return n


def pyrun(code_or_module: str, *args: str, module: bool = False) -> None:
    need_venv()
    sh([PY, "-m", code_or_module, *args] if module else [PY, "-c", code_or_module, *args])


def setup(args: list[str]) -> None:
    uv = shutil.which("uv")
    if not PY.exists():
        if uv:
            sh([uv, "venv", "-p", "3.11", str(VENV)])
        else:
            sh([sys.executable, "-m", "venv", str(VENV)])
    if uv:
        sh([uv, "pip", "install", "-p", str(PY), "-r", "requirements.txt"])
    else:
        sh([PY, "-m", "pip", "install", "--upgrade", "pip"])
        sh([PY, "-m", "pip", "install", "-r", "requirements.txt"])
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("Created .env from .env.example (add GEMINI_API_KEY there if you have one)")
    build_world([])
    train([])
    build([])
    print("\nSetup done. Start the demo with:  python run.py demo")


def build_world(args: list[str]) -> None:
    pyrun("import logging; logging.basicConfig(level=logging.INFO); from app.world.build import build_all; [print(m) for m in build_all()]")


def train(args: list[str]) -> None:
    pyrun("import logging; logging.basicConfig(level=logging.INFO); from app.analytics.fatigue import train; print(train())")


def build(args: list[str]) -> None:
    n = npm()
    if not (FRONT / "node_modules").exists():
        sh([n, "install", "--no-audit", "--no-fund"], cwd=FRONT)
    sh([n, "run", "build"], cwd=FRONT)


def demo(args: list[str]) -> None:
    need_venv()
    if not (FRONT / "dist" / "index.html").exists():
        build([])
    host = "127.0.0.1"
    if "--host" in args:
        host = args[args.index("--host") + 1]
    print(f"\n  Open http://{'127.0.0.1' if host == '0.0.0.0' else host}:8000\n")
    sh([PY, "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", host, "--port", "8000"], check=False)


def dev(args: list[str]) -> None:
    need_venv()
    n = npm()
    if not (FRONT / "node_modules").exists():
        sh([n, "install", "--no-audit", "--no-fund"], cwd=FRONT)
    api = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--reload", "--reload-dir", "backend", "--port", "8000"], cwd=ROOT, env=env())
    try:
        subprocess.run([n, "run", "dev"], cwd=FRONT, env=env())
    finally:
        api.terminate()


def smoke(args: list[str]) -> None:
    need_venv()
    e = env()
    e["LLM_PROVIDER"] = "cache-only"
    print("» smoke test (cache-only LLM)")
    rc = subprocess.run([str(PY), str(ROOT / "scripts" / "smoke.py"), *args], cwd=ROOT, env=e).returncode
    sys.exit(rc)


def snapshot(args: list[str]) -> None:
    need_venv()
    sh([PY, ROOT / "scripts" / "bluesky_snapshot.py", *args])


def warm_cache(args: list[str]) -> None:
    need_venv()
    sh([PY, ROOT / "scripts" / "warm_cache.py", *args])


def fetch_trends(args: list[str]) -> None:
    pyrun("from app.integrations.trends import fetch; import json; print(json.dumps(fetch())[:400])")


COMMANDS = {"setup": setup, "demo": demo, "dev": dev, "smoke": smoke, "snapshot": snapshot, "build-world": build_world,
            "train": train, "build": build, "warm-cache": warm_cache, "fetch-trends": fetch_trends}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    try:
        COMMANDS[sys.argv[1]](sys.argv[2:])
    except subprocess.CalledProcessError as err:
        sys.exit(err.returncode)
    except KeyboardInterrupt:
        pass
