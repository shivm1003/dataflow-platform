"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from dataflow_platform.api.routes import router as api_router
from dataflow_platform.config import get_settings
from dataflow_platform.dashboard.routes import router as dashboard_router

STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dataflow Platform",
        description="Scraper registry, run reporting, and QA control plane",
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(dashboard_router)
    app.include_router(api_router)
    return app


app = create_app()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    uvicorn.run(
        "dataflow_platform.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    run()
