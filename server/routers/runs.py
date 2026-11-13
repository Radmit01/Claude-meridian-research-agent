"""/api/runs — start, list, inspect, stream (SSE), cancel."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..schemas import RunRequest
from ..services.pack_service import fixed_questions
from ..services.run_manager import STAGES, manager, slugify

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs():
    return {"runs": manager.list(), "stages": STAGES, "active": manager.active.snapshot() if manager.active else None}


@router.post("")
def start_run(req: RunRequest):
    question = req.question.strip()
    fixed = {q["question"]: q["output_name"] for q in fixed_questions()}
    output_name = fixed.get(question) or f"Custom_{time.strftime('%Y%m%d_%H%M%S')}_{slugify(question)}.md"
    try:
        run = manager.start(question, output_name)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return run.snapshot()


@router.get("/{run_id}")
def get_run(run_id: str):
    run = manager.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {**run.snapshot(include_events=True), "stages": STAGES}


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str):
    if not manager.cancel(run_id):
        raise HTTPException(409, "Run is not cancellable")
    return {"ok": True}


@router.get("/{run_id}/stream")
async def stream_run(run_id: str, since: int = 0):
    run = manager.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    async def gen():
        idx = max(0, since)
        last_beat = 0.0
        while True:
            events = run.events
            while idx < len(events):
                yield f"event: log\ndata: {json.dumps(events[idx])}\n\n"
                idx += 1
            now = time.time()
            if now - last_beat > 1.0:
                yield f"event: state\ndata: {json.dumps(run.snapshot())}\n\n"
                last_beat = now
            if run.status not in ("queued", "running") and idx >= len(run.events):
                yield f"event: state\ndata: {json.dumps(run.snapshot())}\n\n"
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
