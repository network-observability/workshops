"""Entrypoint for the AutoCon5 webhook receiver."""
from __future__ import annotations

import logging
import os
from logging.config import dictConfig
from urllib.parse import urlparse

import fastapi
import uvicorn

from app import api, config

PREFECT_API_URL = os.getenv("PREFECT_API_URL") or os.getenv("PREFECT_URL", "")
if not PREFECT_API_URL:
    raise RuntimeError("Missing PREFECT_API_URL (or PREFECT_URL).")

_parsed = urlparse(PREFECT_API_URL)
if _parsed.scheme not in ("http", "https") or not _parsed.netloc:
    raise RuntimeError(f"PREFECT_API_URL is not a valid URL: {PREFECT_API_URL}")


dictConfig(config.LogConfig().model_dump())
log = logging.getLogger("webhook")

app = fastapi.FastAPI(title="AutoCon5 Webhook Receiver")
config.load()
app.include_router(api.router)


@app.get("/")
def index() -> dict[str, str]:
    return {"message": "The Webhook service is waiting for your requests!"}


if __name__ == "__main__":
    settings = config.SETTINGS
    log.info("Starting webhook on %s:%s (Prefect at %s)", settings.host, settings.port, PREFECT_API_URL)
    uvicorn.run(app, host=settings.host, port=settings.port)
