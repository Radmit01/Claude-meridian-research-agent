"""Research packs in output/: list, load (parsed), import and delete."""
from __future__ import annotations

import ast
import glob
import os
import re
import time
from typing import Any, Dict, List, Tuple

from ..config import FIXED_QUESTION_SCRIPTS, MAX_PACK_BYTES, OUTPUT_DIR, ROOT
from .pack_parser import parse_pack


class PackError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _read_constants(path: str) -> Tuple[str, str]:
    """Reads QUESTION / OUTPUT_PATH from run_qN.py without importing it
    (importing would pull in the whole coordinator and SDK)."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("QUESTION", "OUTPUT_PATH") and isinstance(node.value, ast.Constant):
                found[node.targets[0].id] = node.value.value
    return found["QUESTION"], found["OUTPUT_PATH"]


def fixed_questions() -> List[Dict[str, Any]]:
    out = []
    for mod_name, qid, label in FIXED_QUESTION_SCRIPTS:
        try:
            question, path = _read_constants(os.path.join(ROOT, f"{mod_name}.py"))
        except Exception:
            continue
        name = os.path.basename(path)
        full = os.path.join(OUTPUT_DIR, name)
        exists = os.path.exists(full)
        out.append({
            "id": qid,
            "label": label,
            "question": question,
            "output_name": name,
            "has_pack": exists,
            "updated_at": os.path.getmtime(full) if exists else None,
        })
    return out


def fixed_output_names() -> Dict[str, Dict[str, Any]]:
    return {q["output_name"]: q for q in fixed_questions()}


def _safe_path(name: str, must_exist: bool = True) -> str:
    if "/" in name or "\\" in name or name.startswith(".") or not name.endswith(".md"):
        raise PackError("Invalid pack name")
    path = os.path.join(OUTPUT_DIR, name)
    if must_exist and not os.path.isfile(path):
        raise PackError("Pack not found", 404)
    return path


_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def load(name: str) -> Dict[str, Any]:
    path = _safe_path(name)
    mtime = os.path.getmtime(path)
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        data = parse_pack(f.read())
    data["name"] = name
    data["updated_at"] = mtime
    data["is_fixed"] = name in fixed_output_names()
    _cache[name] = (mtime, data)
    return data


def raw(name: str) -> str:
    with open(_safe_path(name), encoding="utf-8") as f:
        return f.read()


def list_all() -> List[Dict[str, Any]]:
    fixed = fixed_output_names()
    packs = []
    for path in glob.glob(os.path.join(OUTPUT_DIR, "*.md")):
        name = os.path.basename(path)
        try:
            p = load(name)
        except Exception:
            continue
        q = fixed.get(name)
        packs.append({
            "name": name,
            "question": p["question"],
            "label": q["label"] if q else ("Imported pack" if name.startswith("Imported_") else "Custom question"),
            "qid": q["id"] if q else None,
            "is_fixed": bool(q),
            "updated_at": p["updated_at"],
            "size": os.path.getsize(path),
            "stats": p["stats"],
        })
    packs.sort(key=lambda p: (p["qid"] or "Z", -p["updated_at"]))
    return packs


def import_pack(data: bytes, filename: str) -> Dict[str, Any]:
    if not data:
        raise PackError("The uploaded file is empty.")
    if len(data) > MAX_PACK_BYTES:
        raise PackError("Pack is larger than 5 MB.", 413)
    if not (filename or "").lower().endswith(".md"):
        raise PackError("Research packs must be .md files.", 415)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackError("Pack must be UTF-8 markdown.", 415)
    parsed = parse_pack(text)
    if not parsed["question"] or not (parsed["sections"] or parsed["sources"]):
        raise PackError(
            "This file isn't a research pack: it needs a '# Research Pack: …' title and the four mandatory sections."
        )
    stem = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(os.path.basename(filename))[0]).strip("_")[:60] or "pack"
    name = f"Imported_{time.strftime('%Y%m%d_%H%M%S')}_{stem}.md"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(_safe_path(name, must_exist=False), "w", encoding="utf-8") as f:
        f.write(text)
    return {"name": name, "pack": load(name)}


def delete(name: str) -> Dict[str, Any]:
    path = _safe_path(name)
    if name in fixed_output_names():
        raise PackError("Fixed-question packs (Q1–Q3) can be re-run but not deleted here.", 403)
    os.remove(path)
    sidecar = path[:-3] + ".json"
    if os.path.exists(sidecar):
        os.remove(sidecar)
    _cache.pop(name, None)
    return {"deleted": name}
