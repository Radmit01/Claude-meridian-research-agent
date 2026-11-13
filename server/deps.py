"""Shared route guards."""
from __future__ import annotations

from fastapi import HTTPException

from .services.run_manager import manager


def ensure_no_active_run() -> None:
    """Corpus files must not change underneath a running pipeline."""
    run = manager.active
    if run is not None and run.status in ("queued", "running"):
        raise HTTPException(409, f"Run {run.id} is in progress. Wait for it to finish before changing the corpus.")
