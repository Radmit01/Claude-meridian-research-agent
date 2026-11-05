"""Shared data model for everything that flows between pipeline stages.

Kept dependency-free (stdlib dataclasses, no pydantic) so this module — and
everything that only touches it — can be exercised in tests without any
third-party package beyond what's needed for document parsing itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Stage 0/2 output: document extraction
# ---------------------------------------------------------------------------

class ReadStatus(str, Enum):
    OK = "ok"
    FAILED_TO_PROCESS = "failed to process"
    EMPTY = "processed — no extractable content"


@dataclass
class OutlineEntry:
    """One addressable unit inside a document that a citation can point at.

    For docx: a heading / numbered item label (e.g. "Item 6 Financial Crime
    Remediation Programme", "Section 5 Statement on Remediation Activity").
    For xlsx: a sheet name.
    For pdf: a heuristically detected section/heading line.
    """
    ref: str
    preview: str = ""  # short snippet of the text under this heading, for humans debugging


@dataclass
class ExtractedDocument:
    doc_id: str
    status: ReadStatus
    outline: list[OutlineEntry] = field(default_factory=list)
    full_text: str = ""
    error: str | None = None  # populated when status == FAILED_TO_PROCESS

    @property
    def is_usable(self) -> bool:
        return self.status == ReadStatus.OK and bool(self.full_text.strip())


# ---------------------------------------------------------------------------
# Stage 2 output: structured claims
# ---------------------------------------------------------------------------

@dataclass
class Citation:
    doc_id: str
    ref: str  # section/heading/sheet name — never a filename or bare page number

    def format(self) -> str:
        return f"[{self.doc_id}, {self.ref}]"


@dataclass
class Finding:
    topic: str  # free-text topic tag used for grouping in Stage 3/4, e.g. "financial crime remediation"
    claim: str
    citation: Citation


# ---------------------------------------------------------------------------
# Stage 3 output: conflicts
# ---------------------------------------------------------------------------

class ResolutionBasis(str, Enum):
    RECENCY = "recency"
    AUTHORITY_INDEPENDENCE = "authority/independence"
    UNRESOLVED = "unresolved"


@dataclass
class ConflictPosition:
    citation: Citation
    position: str


@dataclass
class Conflict:
    subject: str
    position_a: ConflictPosition
    position_b: ConflictPosition
    resolution_basis: ResolutionBasis
    resolution_note: str  # required even when UNRESOLVED — must explain *why* no side can be picked


# ---------------------------------------------------------------------------
# Stage 4 output: coverage gaps
# ---------------------------------------------------------------------------

class GapReason(str, Enum):
    FAILED_TO_PROCESS = "source failed to process"
    PROCESSED_EMPTY = "source processed but contained no extractable content"
    CONTENT_WITHHELD = "relevant content referenced but withheld within an otherwise-readable source"
    NOT_COVERED = "no source in the corpus addresses this sub-topic"


@dataclass
class CoverageGap:
    description: str
    reason: GapReason
    source_doc_id: str | None  # None when reason == NOT_COVERED
    confidence_impact: str


# ---------------------------------------------------------------------------
# Sources Consulted
# ---------------------------------------------------------------------------

@dataclass
class SourceRecord:
    doc_id: str
    status: ReadStatus
    note: str = ""


# ---------------------------------------------------------------------------
# Final pack
# ---------------------------------------------------------------------------

@dataclass
class ResearchPack:
    question: str
    findings_by_section: dict[str, list[Finding]]  # sub-heading -> findings
    conflicts: list[Conflict]
    gaps: list[CoverageGap]
    sources_consulted: list[SourceRecord]
