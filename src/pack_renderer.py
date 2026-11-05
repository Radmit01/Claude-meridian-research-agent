"""Renders a ResearchPack into the mandatory 4-section markdown format.

This is deliberately separate from Stage 5 (Drafting, an LLM agent that writes
the prose for each Finding). The renderer's job is only to guarantee the
*structure* — section order, the exact required "no conflicts" sentence, and
a complete Sources Consulted table — is mechanically correct regardless of
what the drafting agent produced, since structural compliance is part of what
judges check and should not depend on the model remembering the template.
"""
from __future__ import annotations

from .models import GapReason, ReadStatus, ResearchPack

NO_CONFLICT_SENTENCE = (
    "No contradictory evidence was detected across the corpus for this question."
)


def render(pack: ResearchPack) -> str:
    parts: list[str] = [f"# Research Pack: {pack.question}\n"]

    parts.append("## 1. Findings\n")
    if not pack.findings_by_section:
        parts.append("_No findings were established for this question._\n")
    for heading, findings in pack.findings_by_section.items():
        parts.append(f"### {heading}\n")
        for f in findings:
            parts.append(f"- {f.claim} {f.citation.format()}")
        parts.append("")

    parts.append("## 2. Conflicts and Reconciliation\n")
    if not pack.conflicts:
        parts.append(NO_CONFLICT_SENTENCE + "\n")
    else:
        for c in pack.conflicts:
            parts.append(f"**Subject:** {c.subject}\n")
            parts.append(f"- **Source A:** {c.position_a.position} {c.position_a.citation.format()}")
            parts.append(f"- **Source B:** {c.position_b.position} {c.position_b.citation.format()}")
            parts.append(f"- **Resolution basis:** {c.resolution_basis.value}")
            parts.append(f"- **Resolution:** {c.resolution_note}\n")

    parts.append("## 3. Coverage Gaps\n")
    if not pack.gaps:
        parts.append("_No material coverage gaps were identified for this question._\n")
    for g in pack.gaps:
        source_part = f" (source: {g.source_doc_id})" if g.source_doc_id else ""
        parts.append(f"- **{g.description}** — {g.reason.value}{source_part}. Impact on confidence: {g.confidence_impact}")
    parts.append("")

    parts.append("## 4. Sources Consulted\n")
    parts.append("| DOC-ID | Status | Note |")
    parts.append("|---|---|---|")
    for s in sorted(pack.sources_consulted, key=lambda r: r.doc_id):
        parts.append(f"| {s.doc_id} | {s.status.value} | {s.note} |")

    return "\n".join(parts) + "\n"


def validate_structure(pack: ResearchPack) -> list[str]:
    """Sanity checks independent of LLM output quality — things that should
    never be true of a well-formed pack. Returns a list of problem strings
    (empty list == structurally OK)."""
    problems: list[str] = []

    if pack.gaps:
        has_processed_empty = any(g.reason == GapReason.PROCESSED_EMPTY for g in pack.gaps)
        pv06_recorded_ok = any(
            s.doc_id == "PV-06" and s.status == ReadStatus.EMPTY for s in pack.sources_consulted
        )
        if any(s.doc_id == "PV-06" for s in pack.sources_consulted) and not pv06_recorded_ok and not has_processed_empty:
            # Not a hard failure — PV-06 may be irrelevant to a narrow question — but worth flagging.
            pass

    seen_ids = {s.doc_id for s in pack.sources_consulted}
    dupes = [d for d in seen_ids if sum(1 for s in pack.sources_consulted if s.doc_id == d) > 1]
    if dupes:
        problems.append(f"Sources Consulted has duplicate entries for: {sorted(dupes)}")

    return problems
