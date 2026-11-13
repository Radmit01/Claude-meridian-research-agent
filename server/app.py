"""FastAPI entry point for the research dashboard.

Wraps the existing pipeline without modifying it. Routes live in
`server/routers/`, business logic in `server/services/`. Interactive API docs
are at /api/docs.

Start with:  python run_dashboard.py
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR
from .routers import corpus, packs, runs, system
from .services import manifest_service

manifest_service.load_custom_entries()

app = FastAPI(title="Meridian Research Desk", docs_url="/api/docs", openapi_url="/api/openapi.json")

for r in (system.router, packs.router, corpus.router, runs.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
