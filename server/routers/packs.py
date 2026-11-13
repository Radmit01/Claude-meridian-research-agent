"""/api/packs and /api/questions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..services import pack_service as svc
from ..services.pack_service import PackError

router = APIRouter(tags=["packs"])


def _wrap(fn, *args):
    try:
        return fn(*args)
    except PackError as exc:
        raise HTTPException(exc.status, str(exc))


@router.get("/api/questions")
def questions():
    return {"questions": svc.fixed_questions()}


@router.get("/api/packs")
def list_packs():
    return {"packs": svc.list_all()}


@router.post("/api/packs/upload")
async def import_pack(request: Request, filename: str = Query(...)):
    """Import an existing research pack (.md) as raw body."""
    return _wrap(svc.import_pack, await request.body(), filename)


@router.get("/api/packs/{name}")
def get_pack(name: str):
    return _wrap(svc.load, name)


@router.get("/api/packs/{name}/raw", response_class=PlainTextResponse)
def get_raw(name: str):
    return _wrap(svc.raw, name)


@router.delete("/api/packs/{name}")
def delete_pack(name: str):
    return _wrap(svc.delete, name)
