"""
routes.py — Admin and status API routes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config.kill_switch import is_live
from config.settings import settings

router = APIRouter(prefix="/api", tags=["admin"])

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_STATE_DIR = _PROJECT_ROOT / "data" / "processed" / "states"


@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "kill_switch": not is_live(),
        "staff_sink_email": settings.staff_sink_email,
    })


@router.get("/states")
async def list_states() -> JSONResponse:
    """List all prospect conversation states."""
    states: list[dict] = []
    for f in sorted(_STATE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            states.append({
                "prospect_id": data.get("prospect_id"),
                "company_name": data.get("company_name"),
                "stage": data.get("stage"),
                "segment": data.get("segment"),
                "email_touches": data.get("email_touches"),
                "escalated": data.get("escalated"),
                "updated_at": data.get("updated_at"),
            })
        except Exception:
            continue
    return JSONResponse({"count": len(states), "states": states})


@router.get("/states/{prospect_id}")
async def get_state(prospect_id: str) -> JSONResponse:
    path = _STATE_DIR / f"{prospect_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="State not found")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@router.get("/score_log")
async def get_score_log() -> JSONResponse:
    score_path = _PROJECT_ROOT / "eval" / "score_log.json"
    if not score_path.exists():
        return JSONResponse([])
    return JSONResponse(json.loads(score_path.read_text(encoding="utf-8")))
