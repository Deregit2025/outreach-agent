"""
main.py — FastAPI application entry point.

Start with:
    uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from config.kill_switch import assert_safe_mode
from server.middleware import RequestLoggingMiddleware, add_cors
from server.routes import router as api_router
from server.webhooks import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)

app = FastAPI(
    title="Conversion Engine — Tenacious SDR Agent",
    version="0.1.0",
    description=(
        "B2B outreach automation: enriches prospects, generates "
        "grounded outreach, and books discovery calls."
    ),
)

add_cors(app)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(api_router)
app.include_router(webhook_router)


@app.on_event("startup")
async def on_startup() -> None:
    assert_safe_mode()


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "conversion-engine", "docs": "/docs"}
