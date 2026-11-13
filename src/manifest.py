"""Static corpus manifest for the Meridian Financial Group research pack system.

This is intentionally NOT derived from scanning a directory at runtime: the
hard constraint is that every citation must use the exact DOC-ID from the
manifest below, so the manifest is the single source of truth for valid IDs,
independent of whatever filenames the corpus happens to ship with.

`filename_glob` is a best-effort hint for locating the actual file on disk
(exact filenames were not finalized when this was written). The loader in
`extraction.py` resolves a glob against the configured corpus directory and
fails loudly (routes to Sources Consulted as `failed to process`) if no file
or more than one file matches.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceSet(str, Enum):
    CLIENT = "Set A - Client materials"
    EXTERNAL = "Set B - External context"
    PROTIVITI = "Set C - Internal Protiviti material"


class DocFormat(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    XLSX = "xlsx"


@dataclass(frozen=True)
class ManifestEntry:
    doc_id: str
    title: str
    source_set: SourceSet
    fmt: DocFormat
    filename_glob: str


_ENTRIES: list[ManifestEntry] = [
    # Set A - Client materials (all docx)
    ManifestEntry("CL-01", "Annual Report Extract FY2025", SourceSet.CLIENT, DocFormat.DOCX, "CL-01*"),
    ManifestEntry("CL-02", "Annual Report Extract FY2024", SourceSet.CLIENT, DocFormat.DOCX, "CL-02*"),
    ManifestEntry("CL-03", "Org Chart & Leadership Profiles", SourceSet.CLIENT, DocFormat.DOCX, "CL-03*"),
    ManifestEntry("CL-04", "Three-Year Strategy 2026-2028", SourceSet.CLIENT, DocFormat.DOCX, "CL-04*"),
    ManifestEntry("CL-05", "Board Minutes Extract Q3 2025", SourceSet.CLIENT, DocFormat.DOCX, "CL-05*"),
    ManifestEntry("CL-06", "Board Minutes Extract Q4 2025", SourceSet.CLIENT, DocFormat.DOCX, "CL-06*"),
    ManifestEntry("CL-07", "Risk Committee Charter & Governance Structure", SourceSet.CLIENT, DocFormat.DOCX, "CL-07*"),
    ManifestEntry("CL-08", "IT Landscape Overview", SourceSet.CLIENT, DocFormat.DOCX, "CL-08*"),
    ManifestEntry("CL-09", "Internal Audit Plan FY2026", SourceSet.CLIENT, DocFormat.DOCX, "CL-09*"),
    ManifestEntry("CL-10", "Investor Presentation Extract", SourceSet.CLIENT, DocFormat.DOCX, "CL-10*"),
    # Set B - External context (mixed formats)
    ManifestEntry("EX-01", "Regulatory Notice - Supervisory Expectations", SourceSet.EXTERNAL, DocFormat.PDF, "EX-01*"),
    ManifestEntry("EX-02", "Regulator Thematic Review Findings", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-02*"),
    ManifestEntry("EX-03", "Enforcement Action Summary - Peer Firm", SourceSet.EXTERNAL, DocFormat.PDF, "EX-03*"),
    ManifestEntry("EX-04", "Industry Risk Outlook", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-04*"),
    ManifestEntry("EX-05", "Peer Benchmarking Extract", SourceSet.EXTERNAL, DocFormat.XLSX, "EX-05*"),
    ManifestEntry("EX-06", "Press Report - Leadership Change", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-06*"),
    ManifestEntry("EX-07", "Press Report - Service Disruption & Remediation Status", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-07*"),
    ManifestEntry("EX-08", "Analyst Note - Sector Consolidation", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-08*"),
    ManifestEntry("EX-09", "Horizon Scan - Emerging Regulation", SourceSet.EXTERNAL, DocFormat.DOCX, "EX-09*"),
    # Set C - Internal Protiviti material (all docx)
    ManifestEntry("PV-01", "Past Proposal - Internal Audit Co-Source", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-01*"),
    ManifestEntry("PV-02", "Past Proposal - Cyber Security Assessment", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-02*"),
    ManifestEntry("PV-03", "Credential Extracts - Financial Services", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-03*"),
    ManifestEntry("PV-04", "Methodology Extract - Risk-Based Assurance", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-04*"),
    ManifestEntry("PV-05", "Engagement Closeout Summary FY2024", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-05*"),
    ManifestEntry("PV-06", "Lessons Learned - Prior Meridian Engagements", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-06*"),
    ManifestEntry("PV-07", "Service Catalogue Overview", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-07*"),
    ManifestEntry("PV-08", "Point of View - Sequencing Control Investment", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-08*"),
    ManifestEntry("PV-09", "Prior Scoping Note and SOW Extract", SourceSet.PROTIVITI, DocFormat.DOCX, "PV-09*"),
]

MANIFEST: dict[str, ManifestEntry] = {e.doc_id: e for e in _ENTRIES}

assert len(MANIFEST) == 28, f"expected 28 manifest entries, got {len(MANIFEST)}"


def get(doc_id: str) -> ManifestEntry:
    try:
        return MANIFEST[doc_id]
    except KeyError as exc:
        raise KeyError(f"'{doc_id}' is not a valid corpus DOC-ID") from exc


def all_doc_ids() -> list[str]:
    return list(MANIFEST.keys())
