"""Deterministic (non-LLM) citation validation.

Judges mechanically check citation format against the corpus, so this check
must not depend on another model call — it has to be code that either passes
or fails the same way every time.

Two things are checked for every `[DOC-ID, ref]` citation found in drafted
text:
  1. DOC-ID exists in the manifest.
  2. `ref` plausibly corresponds to a heading/section/sheet name that was
     actually extracted from that document (fuzzy match, since a model won't
     reproduce heading text byte-for-byte) — this also rejects citations that
     are just a filename or a bare page number, since those won't match any
     outline entry.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import Enum

from .manifest import MANIFEST
from .models import OutlineEntry

CITATION_RE = re.compile(r"\[\s*([A-Z]{2}-\d{2})\s*,\s*([^\]]+?)\s*\]")

# Below this similarity ratio, a cited ref is considered not to match any
# known outline entry for that document.
MATCH_THRESHOLD = 0.6


class CitationIssueType(str, Enum):
    UNKNOWN_DOC_ID = "unknown DOC-ID — not in corpus manifest"
    REF_NOT_FOUND = "ref does not match any known section/heading/sheet in the cited document"
    NO_OUTLINE_AVAILABLE = "cited document has no outline on record (not yet extracted, or empty/failed)"
    BARE_PAGE_NUMBER = "ref looks like a bare page number, not a section/heading/sheet name"


@dataclass
class CitationIssue:
    raw_citation: str
    doc_id: str
    ref: str
    issue_type: CitationIssueType
    detail: str = ""


_PAGE_ONLY_RE = re.compile(r"^(p\.?|page)\s*\d+$", re.IGNORECASE)


def extract_citations(text: str) -> list[tuple[str, str]]:
    """Returns list of (doc_id, ref) tuples found in `text`."""
    return [(m.group(1), m.group(2).strip()) for m in CITATION_RE.finditer(text)]


def _best_ratio(ref: str, outline: list[OutlineEntry]) -> float:
    if not outline:
        return 0.0
    ref_norm = ref.lower().strip()
    return max(
        difflib.SequenceMatcher(None, ref_norm, entry.ref.lower().strip()).ratio()
        for entry in outline
    )


def validate_citations(
    text: str, outlines: dict[str, list[OutlineEntry]]
) -> list[CitationIssue]:
    """`outlines` maps doc_id -> outline entries extracted for that doc during
    Stage 2 (only documents that were actually analyzed will have an entry).
    """
    issues: list[CitationIssue] = []
    for doc_id, ref in extract_citations(text):
        raw = f"[{doc_id}, {ref}]"

        if doc_id not in MANIFEST:
            issues.append(CitationIssue(raw, doc_id, ref, CitationIssueType.UNKNOWN_DOC_ID))
            continue

        if _PAGE_ONLY_RE.match(ref):
            issues.append(CitationIssue(raw, doc_id, ref, CitationIssueType.BARE_PAGE_NUMBER))
            continue

        outline = outlines.get(doc_id)
        if outline is None:
            issues.append(
                CitationIssue(
                    raw, doc_id, ref, CitationIssueType.NO_OUTLINE_AVAILABLE,
                    detail="document was never extracted in this run, or extraction failed/was empty",
                )
            )
            continue

        ratio = _best_ratio(ref, outline)
        if ratio < MATCH_THRESHOLD:
            issues.append(
                CitationIssue(
                    raw, doc_id, ref, CitationIssueType.REF_NOT_FOUND,
                    detail=f"best match ratio {ratio:.2f} < threshold {MATCH_THRESHOLD}",
                )
            )

    return issues
