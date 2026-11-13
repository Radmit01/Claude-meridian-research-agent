"""Paths and limits shared by every backend module."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(ROOT, "Corpus")
OUTPUT_DIR = os.path.join(ROOT, "output")
FRONTEND_DIR = os.path.join(ROOT, "frontend")

# Run history (one JSON per dashboard run, with its full log).
HISTORY_DIR = os.path.join(OUTPUT_DIR, "runs")

# Hidden (dot-prefixed) so manifest globs like "CL-01*" and the corpus file
# count never pick them up.
BACKUP_DIR = os.path.join(CORPUS_DIR, ".backup")
CUSTOM_MANIFEST_PATH = os.path.join(CORPUS_DIR, ".custom_manifest.json")
SYNC_STATE_PATH = os.path.join(OUTPUT_DIR, ".corpus_sync.json")

ALLOWED_DOC_EXTENSIONS = {".docx": "docx", ".pdf": "pdf", ".xlsx": "xlsx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PACK_BYTES = 5 * 1024 * 1024

FIXED_QUESTION_SCRIPTS = [
    ("run_q1", "Q1", "Regulatory exposure"),
    ("run_q2", "Q2", "Prior relationship"),
    ("run_q3", "Q3", "Full pre-engagement pack"),
]
