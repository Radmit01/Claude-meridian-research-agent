"""/api/overview and /api/health."""
from __future__ import annotations

import glob
import importlib
import os

from fastapi import APIRouter

from src.manifest import MANIFEST

from ..config import ALLOW_CORPUS_EDITS, CORPUS_DIR, OUTPUT_DIR, ROOT
from ..services import corpus_service, pack_service
from ..services.run_manager import STAGES, manager

router = APIRouter(tags=["system"])

REQUIRED_ENV = [
    "CLIENT_ID", "TENANT_ID", "TOKEN_SCOPE", "MSF_SUBSCRIPTION_KEY",
    "ANTHROPIC_BASE_URL", "AUTHENTICATION_TYPE_VALUE", "ANTHROPIC_MODEL",
]


@router.get("/api/overview")
def overview():
    packs = pack_service.list_all()
    totals = {"findings": 0, "conflicts": 0, "gaps": 0, "recommendations": 0}
    cited = set()
    for p in packs:
        for k in totals:
            totals[k] += p["stats"].get(k, 0)
        try:
            cited.update(pack_service.load(p["name"])["cited_doc_ids"])
        except Exception:
            pass
    sets = {}
    for e in MANIFEST.values():
        sets[e.source_set.value] = sets.get(e.source_set.value, 0) + 1
    sync_state = corpus_service._read_sync_state()
    return {
        "questions": pack_service.fixed_questions(),
        "packs": packs,
        "recent_runs": manager.list()[:6],
        "active_run": manager.active.snapshot() if manager.active else None,
        "corpus": {
            "documents": len(MANIFEST),
            "sets": sets,
            "cited": len(cited),
            "last_synced_at": sync_state.get("synced_at"),
        },
        "totals": totals,
        "stages": STAGES,
    }


@router.get("/api/health")
def health():
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(os.path.join(ROOT, ".env"), override=False)
        dotenv_ok = True
    except Exception:
        dotenv_ok = False
    deps = {}
    for mod in ["claude_agent_sdk", "azure.identity", "docx", "openpyxl", "pypdf", "dotenv"]:
        try:
            importlib.import_module(mod)
            deps[mod] = True
        except Exception:
            deps[mod] = False
    return {
        "env": [{"name": n, "present": bool(os.environ.get(n))} for n in REQUIRED_ENV],
        "env_file": os.path.exists(os.path.join(ROOT, ".env")),
        "dotenv_loaded": dotenv_ok,
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "dependencies": deps,
        "corpus_dir": os.path.relpath(CORPUS_DIR, ROOT),
        "corpus_files": len(glob.glob(os.path.join(CORPUS_DIR, "*.*"))),
        "manifest_documents": len(MANIFEST),
        "output_dir": os.path.relpath(OUTPUT_DIR, ROOT),
        "allow_corpus_edits": ALLOW_CORPUS_EDITS,
    }
