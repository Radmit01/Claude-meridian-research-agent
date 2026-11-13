"""Shared route guards."""
from __future__ import annotations

from fastapi import HTTPException

from .config import ALLOW_CORPUS_EDITS
from .services.run_manager import manager


def ensure_no_active_run() -> None:
    """Corpus files must not change underneath a running pipeline."""
    run = manager.active
    if run is not None and run.status in ("queued", "running"):
        raise HTTPException(409, f"Run {run.id} is in progress. Wait for it to finish before changing the corpus.")


def ensure_corpus_edits_allowed() -> None:
    """The hackathon rules require using only the fixed corpus supplied —
    no adding, removing, or replacing its documents. Upload/replace/
    restore/delete are disabled unless ALLOW_CORPUS_EDITS=1 is explicitly
    set; sync/list/download stay available since they're read-only."""
    if not ALLOW_CORPUS_EDITS:
        raise HTTPException(
            403,
            "Corpus edits are disabled: the hackathon rules require using only the "
            "fixed corpus supplied, with no additions, removals, or replacements. "
            "Set ALLOW_CORPUS_EDITS=1 to override for local testing.",
        )
