"""Extends the static 28-document manifest with documents uploaded from the
dashboard.

`src/manifest.py` stays the source of truth for the original corpus and is not
edited. Uploaded documents are recorded in `Corpus/.custom_manifest.json` and
registered into the in-memory `MANIFEST` dict when the server starts, so runs
started from the dashboard (same process) see them. CLI runs (`run_qN.py`)
still see only the original 28.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, List, Optional

from src.manifest import MANIFEST, DocFormat, ManifestEntry, SourceSet

from ..config import CUSTOM_MANIFEST_PATH

ORIGINAL_IDS = frozenset(MANIFEST.keys())
DOC_ID_RE = re.compile(r"^(CL|EX|PV)-\d{2}$")
SET_BY_PREFIX = {"CL": SourceSet.CLIENT, "EX": SourceSet.EXTERNAL, "PV": SourceSet.PROTIVITI}

_lock = threading.Lock()


def _read_registry() -> List[Dict[str, Any]]:
    if not os.path.exists(CUSTOM_MANIFEST_PATH):
        return []
    try:
        with open(CUSTOM_MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_registry(items: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(CUSTOM_MANIFEST_PATH), exist_ok=True)
    tmp = CUSTOM_MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, CUSTOM_MANIFEST_PATH)


def _entry(item: Dict[str, Any]) -> ManifestEntry:
    return ManifestEntry(
        item["doc_id"],
        item["title"],
        SET_BY_PREFIX[item["doc_id"][:2]],
        DocFormat(item["format"]),
        f"{item['doc_id']}*",
    )


def load_custom_entries() -> None:
    """Called once at startup: registers every uploaded document."""
    with _lock:
        for item in _read_registry():
            try:
                if item["doc_id"] not in ORIGINAL_IDS:
                    MANIFEST[item["doc_id"]] = _entry(item)
            except Exception:
                continue


def is_custom(doc_id: str) -> bool:
    return doc_id in MANIFEST and doc_id not in ORIGINAL_IDS


def custom_meta(doc_id: str) -> Optional[Dict[str, Any]]:
    return next((i for i in _read_registry() if i.get("doc_id") == doc_id), None)


def next_doc_id(prefix: str) -> str:
    used = {int(d[3:]) for d in MANIFEST if d.startswith(prefix + "-")}
    n = 1
    while n in used:
        n += 1
    if n > 99:
        raise ValueError(f"No free DOC-ID left in the {prefix} set.")
    return f"{prefix}-{n:02d}"


def register(doc_id: str, title: str, fmt: str, original_filename: str, uploaded_at: float) -> ManifestEntry:
    with _lock:
        items = [i for i in _read_registry() if i.get("doc_id") != doc_id]
        item = {
            "doc_id": doc_id,
            "title": title,
            "format": fmt,
            "original_filename": original_filename,
            "uploaded_at": uploaded_at,
        }
        items.append(item)
        _write_registry(items)
        entry = _entry(item)
        MANIFEST[doc_id] = entry
        return entry


def update_format(doc_id: str, fmt: str) -> None:
    """A custom doc replaced with a file of a different type keeps its ID."""
    with _lock:
        items = _read_registry()
        for i in items:
            if i.get("doc_id") == doc_id:
                i["format"] = fmt
        _write_registry(items)
        meta = next((i for i in items if i.get("doc_id") == doc_id), None)
        if meta:
            MANIFEST[doc_id] = _entry(meta)


def unregister(doc_id: str) -> None:
    if doc_id in ORIGINAL_IDS:
        raise ValueError("Original corpus documents cannot be removed.")
    with _lock:
        _write_registry([i for i in _read_registry() if i.get("doc_id") != doc_id])
        MANIFEST.pop(doc_id, None)
