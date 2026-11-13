"""Background run manager for the dashboard.

Each run executes `run_research` (unchanged) on its own worker thread with
its own asyncio event loop. That thread may block on the Entra interactive
login (a synchronous browser flow inside `atlas_env_from_dotenv`), so it must
never run on the web server's event loop.

Progress comes from the pipeline's existing `[n/7] ...` log lines: stdout is
tee'd while a run is active and each line becomes a run event. Only one run
is allowed at a time — the pipeline is subprocess-heavy (see DECISIONS.md
#13) and stdout capture is process-global.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from ..config import CORPUS_DIR, HISTORY_DIR, OUTPUT_DIR

STAGES = [
    {"key": "env", "name": "Gateway auth", "detail": "Atlas env + Entra bearer token"},
    {"key": "triage", "name": "Triage", "detail": "Open and classify all 28 documents"},
    {"key": "retrieval", "name": "Retrieval", "detail": "Select the documents worth deep analysis"},
    {"key": "analysis", "name": "Document analysis", "detail": "Parallel batches extract cited findings"},
    {"key": "conflicts", "name": "Conflict detection", "detail": "Cross-source contradictions + resolution basis"},
    {"key": "synthesis", "name": "Synthesis + recommendations", "detail": "Sections, coverage gaps, focus areas"},
    {"key": "drafting", "name": "Drafting", "detail": "Client-ready prose, citations untouched"},
    {"key": "render", "name": "Render + validate", "detail": "Deterministic markdown, citation checks"},
]

_STAGE_RE = re.compile(r"^\[(\d)/7\]")
_DURATION_RE = re.compile(r"\((\d+(?:\.\d+)?)s\)\s*$")


def slugify(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return (s[:limit].rstrip("_")) or "question"


class Run:
    def __init__(self, question: str, output_name: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.question = question
        self.output_name = output_name
        self.status = "queued"  # queued | running | succeeded | failed | cancelled
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.stage = -1
        self.stage_durations: Dict[int, float] = {}
        self.events: List[Dict[str, Any]] = []
        self.error: Optional[str] = None
        self.summary: Dict[str, Any] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()

    # -- events -------------------------------------------------------------
    def add_event(self, kind: str, text: str) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events), "t": time.time(), "kind": kind, "text": text})

    def ingest_line(self, line: str) -> None:
        line = line.rstrip()
        if not line.strip():
            return
        stripped = line.strip()
        kind = "log"
        if "[retry]" in stripped:
            kind = "retry"
        elif "[warn]" in stripped:
            kind = "warn"
        m = _STAGE_RE.match(stripped)
        if m:
            n = int(m.group(1))
            if n > self.stage:
                self.stage = n
                kind = "stage"
            d = _DURATION_RE.search(stripped)
            if d:
                self.stage_durations[n] = float(d.group(1))
        self.add_event(kind, line)

    def snapshot(self, include_events: bool = False) -> Dict[str, Any]:
        now = time.time()
        end = self.finished_at or now
        data = {
            "id": self.id,
            "question": self.question,
            "output_name": self.output_name,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": (end - self.started_at) if self.started_at else 0,
            "stage": self.stage,
            "stage_durations": {str(k): v for k, v in self.stage_durations.items()},
            "error": self.error,
            "summary": self.summary,
            "event_count": len(self.events),
        }
        if include_events:
            data["events"] = list(self.events)
        return data


class _Tee(io.TextIOBase):
    """Forwards writes to the real stdout and, line by line, to the active run."""

    def __init__(self, original, manager: "RunManager") -> None:
        self._original = original
        self._manager = manager
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:  # type: ignore[override]
        try:
            self._original.write(s)
        except Exception:
            pass
        run = self._manager.active
        if run is None:
            return len(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                run.ingest_line(line)
        return len(s)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass


class RunManager:
    def __init__(self) -> None:
        self.runs: Dict[str, Run] = {}
        self.active: Optional[Run] = None
        self._lock = threading.Lock()
        self._installed = False
        self._load_history()

    # -- history ------------------------------------------------------------
    def _load_history(self) -> None:
        if not os.path.isdir(HISTORY_DIR):
            return
        for name in sorted(os.listdir(HISTORY_DIR)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(HISTORY_DIR, name), encoding="utf-8") as f:
                    data = json.load(f)
                run = Run(data["question"], data.get("output_name", ""))
                run.id = data["id"]
                run.status = data.get("status", "succeeded")
                run.created_at = data.get("created_at", 0)
                run.started_at = data.get("started_at")
                run.finished_at = data.get("finished_at")
                run.stage = data.get("stage", 7)
                run.stage_durations = {int(k): v for k, v in data.get("stage_durations", {}).items()}
                run.error = data.get("error")
                run.summary = data.get("summary", {})
                run.events = data.get("events", [])
                self.runs[run.id] = run
            except Exception:
                continue

    def _persist(self, run: Run) -> None:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(os.path.join(HISTORY_DIR, f"{run.id}.json"), "w", encoding="utf-8") as f:
            json.dump(run.snapshot(include_events=True), f, indent=1)

    # -- lifecycle ----------------------------------------------------------
    def _install_tee(self) -> None:
        if not self._installed:
            sys.stdout = _Tee(sys.stdout, self)  # type: ignore[assignment]
            self._installed = True

    def list(self) -> List[Dict[str, Any]]:
        return [r.snapshot() for r in sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)]

    def get(self, run_id: str) -> Optional[Run]:
        return self.runs.get(run_id)

    def start(self, question: str, output_name: str) -> Run:
        with self._lock:
            if self.active is not None and self.active.status in ("queued", "running"):
                raise RuntimeError("A research run is already in progress. Wait for it to finish or cancel it.")
            run = Run(question, output_name)
            self.runs[run.id] = run
            self.active = run
        self._install_tee()
        threading.Thread(target=self._worker, args=(run,), daemon=True, name=f"run-{run.id}").start()
        return run

    def cancel(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if not run or run.status not in ("queued", "running"):
            return False
        if run._loop and run._task:
            run._loop.call_soon_threadsafe(run._task.cancel)
            run.add_event("warn", "Cancellation requested — stopping after the current subagent call returns.")
            return True
        return False

    def _worker(self, run: Run) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        run._loop = loop
        run.status = "running"
        run.started_at = time.time()
        run.add_event("info", f"Run {run.id} started")
        run.add_event("info", f"Question: {run.question}")
        try:
            from src.coordinator import run_research  # imported lazily: heavy deps

            run._task = loop.create_task(run_research(run.question, CORPUS_DIR))
            result = loop.run_until_complete(run._task)

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            md_path = os.path.join(OUTPUT_DIR, run.output_name)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(result["markdown"])
            pack = result["pack"]
            run.summary = {
                "output_name": run.output_name,
                "citation_issues": [str(i) for i in result["citation_issues"]],
                "structure_issues": [str(i) for i in result["structure_issues"]],
                "sections": len(pack.findings_by_section),
                "conflicts": len(pack.conflicts),
                "gaps": len(pack.gaps),
                "sources": len(pack.sources_consulted),
            }
            try:
                with open(os.path.join(OUTPUT_DIR, run.output_name[:-3] + ".json"), "w", encoding="utf-8") as f:
                    json.dump(asdict(pack), f, indent=1, default=str)
            except Exception:
                pass
            run.stage = 8
            run.status = "succeeded"
            run.add_event("done", f"Pack written to output/{run.output_name}")
        except asyncio.CancelledError:
            run.status = "cancelled"
            run.add_event("warn", "Run cancelled.")
        except BaseException as exc:  # noqa: BLE001 — surface everything to the UI
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            for line in traceback.format_exc().splitlines():
                run.add_event("error", line)
        finally:
            run.finished_at = time.time()
            try:
                sys.stdout.flush()
            except Exception:
                pass
            with self._lock:
                if self.active is run:
                    self.active = None
            try:
                self._persist(run)
            except Exception:
                pass
            loop.close()


manager = RunManager()
