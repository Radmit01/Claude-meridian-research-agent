"""Corpus operations for the dashboard: extraction cache, sync, upload,
restore and delete.

Extraction results are cached per document and keyed by a file fingerprint
(name, size, mtime), so a sync only re-parses files that actually changed.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from src.manifest import MANIFEST

from ..config import (
    ALLOWED_DOC_EXTENSIONS,
    BACKUP_DIR,
    CORPUS_DIR,
    MAX_UPLOAD_BYTES,
    SYNC_STATE_PATH,
)
from . import manifest_service

Fingerprint = Optional[Tuple[str, int, float]]

_lock = threading.RLock()
_cache: Dict[str, Dict[str, Any]] = {}  # doc_id -> {"fp": Fingerprint, "doc": ExtractedDocument|None, "error": str|None}
_pool = ThreadPoolExecutor(max_workers=6)


class CorpusError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def file_matches(doc_id: str) -> List[str]:
    entry = MANIFEST[doc_id]
    return [m for m in glob.glob(os.path.join(CORPUS_DIR, entry.filename_glob)) if os.path.isfile(m)]


def file_for(doc_id: str) -> Optional[str]:
    matches = file_matches(doc_id)
    return matches[0] if len(matches) == 1 else None


def fingerprint(doc_id: str) -> Fingerprint:
    path = file_for(doc_id)
    if not path:
        return None
    st = os.stat(path)
    return (os.path.basename(path), st.st_size, round(st.st_mtime, 3))


def backups_for(doc_id: str) -> List[str]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(
        (os.path.join(BACKUP_DIR, n) for n in os.listdir(BACKUP_DIR) if n.split("__", 1)[-1].startswith(doc_id)),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Extraction cache
# ---------------------------------------------------------------------------

def _extract(doc_id: str) -> Dict[str, Any]:
    fp = fingerprint(doc_id)
    try:
        from src.extraction import extract_document

        doc = extract_document(doc_id, CORPUS_DIR)
        if doc.error and "No module named" in doc.error:
            # Parser missing in this interpreter: the status is unknown, not "failed".
            return {"fp": fp, "doc": None, "error": doc.error, "missing_parser": True}
        return {"fp": fp, "doc": doc, "error": None, "missing_parser": False}
    except Exception as exc:  # noqa: BLE001
        return {"fp": fp, "doc": None, "error": str(exc), "missing_parser": False}


def get_extracted(doc_id: str) -> Dict[str, Any]:
    """Cached extraction; re-parses only if the file changed on disk."""
    with _lock:
        cached = _cache.get(doc_id)
    if cached is not None and cached["fp"] == fingerprint(doc_id):
        return cached
    result = _extract(doc_id)
    with _lock:
        _cache[doc_id] = result
    return result


def invalidate(doc_id: Optional[str] = None) -> None:
    with _lock:
        if doc_id is None:
            _cache.clear()
        else:
            _cache.pop(doc_id, None)


def parsers_error() -> Optional[str]:
    with _lock:
        missing = sorted({r["error"] for r in _cache.values() if r.get("missing_parser")})
    if not missing:
        return None
    return (
        f"Some document parsers are unavailable in this Python environment ({'; '.join(missing)}). "
        "Start the dashboard from the project venv to see extraction status."
    )


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def _status_of(result: Optional[Dict[str, Any]]) -> Optional[str]:
    if not result or result.get("missing_parser"):
        return None
    if result["doc"] is None:
        return "failed to process"
    return result["doc"].status.value


def describe(doc_id: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entry = MANIFEST[doc_id]
    path = file_for(doc_id)
    doc = result["doc"] if result else None
    meta = manifest_service.custom_meta(doc_id) if manifest_service.is_custom(doc_id) else None
    return {
        "doc_id": doc_id,
        "title": entry.title,
        "source_set": entry.source_set.value,
        "set_key": doc_id[:2],
        "format": entry.fmt.value,
        "filename": os.path.basename(path) if path else None,
        "size": os.path.getsize(path) if path else None,
        "modified_at": os.path.getmtime(path) if path else None,
        "file_count": len(file_matches(doc_id)),
        "status": _status_of(result),
        "outline_count": len(doc.outline) if doc else None,
        "chars": len(doc.full_text) if doc else None,
        "error": None if (result or {}).get("missing_parser") else (doc.error if doc else (result or {}).get("error")),
        "is_custom": meta is not None,
        "uploaded_at": meta.get("uploaded_at") if meta else None,
        "has_backup": bool(backups_for(doc_id)),
    }


def list_documents() -> Dict[str, Any]:
    ids = sorted(MANIFEST.keys())
    results = list(_pool.map(get_extracted, ids))
    docs = [describe(i, r) for i, r in zip(ids, results)]
    state = _read_sync_state()
    return {
        "documents": docs,
        "extraction_error": parsers_error(),
        "last_synced_at": state.get("synced_at"),
        "counts": _counts(docs),
    }


def _counts(docs: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {"total": len(docs), "ok": 0, "empty": 0, "failed": 0, "custom": 0, "missing": 0}
    for d in docs:
        s = d["status"] or ""
        if s == "ok":
            c["ok"] += 1
        elif "no extractable" in s:
            c["empty"] += 1
        elif s:
            c["failed"] += 1
        if d["is_custom"]:
            c["custom"] += 1
        if not d["filename"]:
            c["missing"] += 1
    return c


def document_detail(doc_id: str) -> Dict[str, Any]:
    if doc_id not in MANIFEST:
        raise CorpusError("Unknown DOC-ID", 404)
    result = get_extracted(doc_id)
    doc = result["doc"]
    return {
        **describe(doc_id, result),
        "extraction_error": parsers_error(),
        "outline": [{"ref": o.ref, "preview": o.preview} for o in doc.outline] if doc else [],
        "text": doc.full_text[:80_000] if doc else "",
        "backups": [os.path.basename(b) for b in backups_for(doc_id)],
    }


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _read_sync_state() -> Dict[str, Any]:
    try:
        with open(SYNC_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_sync_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SYNC_STATE_PATH), exist_ok=True)
    with open(SYNC_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def sync(force: bool = False) -> Dict[str, Any]:
    """Rescans the corpus folder against the manifest, re-extracts changed
    files (or all, with force=True) and reports what changed since the last sync."""
    started = time.time()
    if force:
        invalidate()
    previous = _read_sync_state().get("fingerprints", {})
    ids = sorted(MANIFEST.keys())
    results = list(_pool.map(get_extracted, ids))

    changes = []
    fingerprints = {}
    for doc_id, result in zip(ids, results):
        fp = fingerprint(doc_id)
        fingerprints[doc_id] = list(fp) if fp else None
        before = previous.get(doc_id, "absent") if previous else "absent"
        if fp is None:
            change = "missing"
        elif before == "absent":
            change = "added" if previous else "indexed"
        elif before is None:
            change = "restored"
        elif list(fp) != before:
            change = "modified"
        else:
            change = "unchanged"
        changes.append({"doc_id": doc_id, "change": change, "status": _status_of(result)})
    for doc_id in previous:
        if doc_id not in MANIFEST:
            changes.append({"doc_id": doc_id, "change": "removed", "status": None})

    # Files in the corpus folder that no manifest entry claims.
    claimed = {os.path.basename(p) for d in ids for p in file_matches(d)}
    untracked = sorted(
        n for n in os.listdir(CORPUS_DIR)
        if not n.startswith(".") and os.path.isfile(os.path.join(CORPUS_DIR, n)) and n not in claimed
    ) if os.path.isdir(CORPUS_DIR) else []

    synced_at = time.time()
    _write_sync_state({"synced_at": synced_at, "fingerprints": fingerprints})
    summary: Dict[str, int] = {}
    for c in changes:
        summary[c["change"]] = summary.get(c["change"], 0) + 1
    docs = [describe(i, r) for i, r in zip(ids, results)]
    return {
        "synced_at": synced_at,
        "duration": round(synced_at - started, 2),
        "changes": [c for c in changes if c["change"] != "unchanged"],
        "summary": summary,
        "untracked_files": untracked,
        "extraction_error": parsers_error(),
        "documents": docs,
        "counts": _counts(docs),
    }


# ---------------------------------------------------------------------------
# Upload / restore / delete
# ---------------------------------------------------------------------------

def _safe_name(name: str) -> str:
    base = os.path.basename(name or "document")
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "document"
    return stem[:80] + ext.lower()


def _backup(path: str, doc_id: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}__{os.path.basename(path)}")
    shutil.move(path, dest)
    return dest


def upload(
    data: bytes,
    filename: str,
    mode: str,
    doc_id: Optional[str] = None,
    title: Optional[str] = None,
    set_key: Optional[str] = None,
) -> Dict[str, Any]:
    if not data:
        raise CorpusError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise CorpusError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", 413)
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_DOC_EXTENSIONS:
        raise CorpusError("Only .docx, .pdf and .xlsx files can be added to the corpus.", 415)
    fmt = ALLOWED_DOC_EXTENSIONS[ext]
    _check_magic(data, fmt)
    now = time.time()
    safe = _safe_name(filename)

    if mode == "replace":
        if not doc_id or doc_id not in MANIFEST:
            raise CorpusError("Pick an existing DOC-ID to replace.", 404)
        entry = MANIFEST[doc_id]
        custom = manifest_service.is_custom(doc_id)
        if not custom and entry.fmt.value != fmt:
            raise CorpusError(
                f"{doc_id} is a .{entry.fmt.value} document in the fixed manifest; upload a .{entry.fmt.value} file to replace it."
            )
        backed_up = [_backup(p, doc_id) for p in file_matches(doc_id)]
        target = os.path.join(CORPUS_DIR, f"{doc_id}_{_strip_id(safe, doc_id)}")
        _write(target, data)
        if custom:
            manifest_service.update_format(doc_id, fmt)
            if title:
                manifest_service.register(doc_id, title.strip(), fmt, filename, now)
        action = "replaced"
    elif mode == "new":
        prefix = (set_key or (doc_id or "")[:2]).upper()
        if prefix not in manifest_service.SET_BY_PREFIX:
            raise CorpusError("Choose a source set: CL (client), EX (external) or PV (Protiviti).")
        if doc_id:
            doc_id = doc_id.strip().upper()
            if not manifest_service.DOC_ID_RE.match(doc_id) or not doc_id.startswith(prefix):
                raise CorpusError(f"DOC-ID must look like {prefix}-11.")
            if doc_id in MANIFEST:
                raise CorpusError(f"{doc_id} already exists. Use replace instead.", 409)
        else:
            doc_id = manifest_service.next_doc_id(prefix)
        if not title or not title.strip():
            title = os.path.splitext(os.path.basename(filename))[0].replace("_", " ")
        stray = glob.glob(os.path.join(CORPUS_DIR, f"{doc_id}*"))
        backed_up = [_backup(p, doc_id) for p in stray if os.path.isfile(p)]
        target = os.path.join(CORPUS_DIR, f"{doc_id}_{_strip_id(safe, doc_id)}")
        _write(target, data)
        manifest_service.register(doc_id, title.strip()[:120], fmt, filename, now)
        action = "added"
    else:
        raise CorpusError("mode must be 'replace' or 'new'.")

    invalidate(doc_id)
    detail = document_detail(doc_id)
    return {
        "action": action,
        "doc_id": doc_id,
        "backups": [os.path.basename(b) for b in backed_up],
        "document": detail,
    }


def _strip_id(name: str, doc_id: str) -> str:
    return re.sub(rf"^{re.escape(doc_id)}[_-]*", "", name) or name


def _write(target: str, data: bytes) -> None:
    tmp = target + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, target)


def _check_magic(data: bytes, fmt: str) -> None:
    if fmt in ("docx", "xlsx") and not data.startswith(b"PK"):
        raise CorpusError(f"This doesn't look like a valid .{fmt} file.", 415)
    if fmt == "pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise CorpusError("This doesn't look like a valid .pdf file.", 415)


def restore(doc_id: str) -> Dict[str, Any]:
    if doc_id not in MANIFEST:
        raise CorpusError("Unknown DOC-ID", 404)
    backups = backups_for(doc_id)
    if not backups:
        raise CorpusError(f"No earlier version of {doc_id} to restore.", 404)
    latest = backups[0]
    for p in file_matches(doc_id):
        os.remove(p)  # the current upload; the original is in .backup
    original_name = os.path.basename(latest).split("__", 1)[-1]
    ext = os.path.splitext(original_name)[1].lower()
    shutil.move(latest, os.path.join(CORPUS_DIR, original_name))
    if manifest_service.is_custom(doc_id) and ext in ALLOWED_DOC_EXTENSIONS:
        manifest_service.update_format(doc_id, ALLOWED_DOC_EXTENSIONS[ext])
    invalidate(doc_id)
    return {"restored": original_name, "document": document_detail(doc_id)}


def delete(doc_id: str) -> Dict[str, Any]:
    if doc_id not in MANIFEST:
        raise CorpusError("Unknown DOC-ID", 404)
    if not manifest_service.is_custom(doc_id):
        raise CorpusError("The original 28 documents can be replaced or restored, not deleted.", 403)
    moved = [os.path.basename(_backup(p, doc_id)) for p in file_matches(doc_id)]
    manifest_service.unregister(doc_id)
    invalidate(doc_id)
    return {"deleted": doc_id, "backups": moved}
