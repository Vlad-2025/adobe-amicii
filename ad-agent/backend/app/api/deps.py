from __future__ import annotations

from fastapi import HTTPException

from app import registry
from app.state import STATE, Runtime


def rt(ch: str) -> Runtime:
    try:
        return STATE.get(ch)
    except KeyError:
        try:
            info = registry.channel(ch)
        except KeyError:
            raise HTTPException(404, f"unknown channel {ch}")
        raise HTTPException(409, f"channel {ch} has no data feed yet (status: {info['status']})")


def company_cfg(r: Runtime) -> dict:
    return registry.company(r.company_id)["config"]
