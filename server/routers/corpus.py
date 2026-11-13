"""/api/corpus — list, detail, file download, sync, upload, restore, delete."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..deps import ensure_corpus_edits_allowed, ensure_no_active_run
from ..schemas import SyncRequest
from ..services import corpus_service as svc
from ..services.corpus_service import CorpusError

router = APIRouter(prefix="/api/corpus", tags=["corpus"])


def _run(fn, *args, **kwargs):
    """Corpus work touches the filesystem and parsers: keep it off the event loop."""
    return asyncio.get_running_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


async def _call(fn, *args, **kwargs):
    try:
        return await _run(fn, *args, **kwargs)
    except CorpusError as exc:
        raise HTTPException(exc.status, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("")
async def list_documents():
    return await _call(svc.list_documents)


@router.post("/sync")
async def sync(body: Optional[SyncRequest] = None):
    return await _call(svc.sync, force=bool(body and body.force))


@router.post("/upload", dependencies=[Depends(ensure_corpus_edits_allowed), Depends(ensure_no_active_run)])
async def upload(
    request: Request,
    filename: str = Query(..., description="Original file name, including extension"),
    mode: str = Query("new", pattern="^(new|replace)$"),
    doc_id: Optional[str] = Query(None),
    title: Optional[str] = Query(None, max_length=120),
    set_key: Optional[str] = Query(None, pattern="^(CL|EX|PV)$"),
):
    """Raw-body upload (Content-Type: application/octet-stream). Metadata goes
    in the query string, so no multipart dependency is needed."""
    data = await request.body()
    result = await _call(svc.upload, data, filename, mode, doc_id, title, set_key)
    # Keep the sync baseline current so the next sync doesn't re-report this upload.
    await _call(svc.sync)
    return result


@router.get("/{doc_id}")
async def document(doc_id: str):
    return await _call(svc.document_detail, doc_id)


@router.get("/{doc_id}/file")
async def download(doc_id: str):
    try:
        path = svc.file_for(doc_id)
    except KeyError:
        raise HTTPException(404, "Unknown DOC-ID")
    if not path:
        raise HTTPException(404, "No unique file on disk for this DOC-ID")
    return FileResponse(path, filename=path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])


@router.post("/{doc_id}/restore", dependencies=[Depends(ensure_corpus_edits_allowed), Depends(ensure_no_active_run)])
async def restore(doc_id: str):
    result = await _call(svc.restore, doc_id)
    await _call(svc.sync)
    return result


@router.delete("/{doc_id}", dependencies=[Depends(ensure_corpus_edits_allowed), Depends(ensure_no_active_run)])
async def delete(doc_id: str):
    result = await _call(svc.delete, doc_id)
    await _call(svc.sync)
    return result
