"""Parses a rendered research-pack markdown file (the exact format produced by
`src/pack_renderer.render`) back into structured JSON for the dashboard.

Packs generated before the dashboard existed only exist as markdown, so the
dashboard reads markdown as the common format rather than requiring a JSON
sidecar. The parser is deliberately tolerant: anything it can't classify is
skipped rather than raising, so a hand-edited pack still loads.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

CITATION_RE = re.compile(r"\s*\[([A-Z]{2}-\d{2}),\s*([^\]]+)\]\s*$")
RECOMMENDATIONS_HEADING = "Recommended Engagement Focus Areas"


def _split_citation(text: str) -> Dict[str, Any]:
    m = CITATION_RE.search(text)
    if not m:
        return {"text": text.strip(), "citation": None}
    return {
        "text": text[: m.start()].strip(),
        "citation": {"doc_id": m.group(1), "ref": m.group(2).strip()},
    }


def _parse_gap(line: str) -> Optional[Dict[str, Any]]:
    body = line[2:].strip()
    if not body.startswith("**"):
        return None
    end = body.find("** — ")
    if end == -1:
        return None
    description = body[2:end].strip()
    rest = body[end + len("** — "):]
    impact = ""
    marker = "Impact on confidence:"
    if marker in rest:
        rest, impact = rest.split(marker, 1)
    rest = rest.strip().rstrip(".")
    source = None
    sm = re.search(r"\s*\(source:\s*([A-Z]{2}-\d{2})\)\s*$", rest)
    if sm:
        source = sm.group(1)
        rest = rest[: sm.start()]
    return {
        "description": description,
        "reason": rest.strip(),
        "source_doc_id": source,
        "confidence_impact": impact.strip(),
    }


def parse_pack(markdown: str) -> Dict[str, Any]:
    question = ""
    sections: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    no_conflict_note = None

    part = None
    current_section: Optional[Dict[str, Any]] = None
    current_conflict: Optional[Dict[str, Any]] = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("# Research Pack:"):
            question = line[len("# Research Pack:"):].strip()
            continue
        if line.startswith("## "):
            title = line[3:].lower()
            if "findings" in title:
                part = "findings"
            elif "conflict" in title:
                part = "conflicts"
            elif "gap" in title:
                part = "gaps"
            elif "source" in title:
                part = "sources"
            else:
                part = None
            continue

        if part == "findings":
            if line.startswith("### "):
                current_section = {"heading": line[4:].strip(), "findings": []}
                sections.append(current_section)
            elif line.startswith("- ") and current_section is not None:
                parsed = _split_citation(line[2:])
                current_section["findings"].append({"claim": parsed["text"], "citation": parsed["citation"]})

        elif part == "conflicts":
            if line.startswith("**Subject:**"):
                current_conflict = {
                    "subject": line[len("**Subject:**"):].strip(),
                    "position_a": None,
                    "position_b": None,
                    "resolution_basis": "",
                    "resolution_note": "",
                }
                conflicts.append(current_conflict)
            elif current_conflict is not None and line.startswith("- **Source A:**"):
                p = _split_citation(line[len("- **Source A:**"):])
                current_conflict["position_a"] = {"position": p["text"], "citation": p["citation"]}
            elif current_conflict is not None and line.startswith("- **Source B:**"):
                p = _split_citation(line[len("- **Source B:**"):])
                current_conflict["position_b"] = {"position": p["text"], "citation": p["citation"]}
            elif current_conflict is not None and line.startswith("- **Resolution basis:**"):
                current_conflict["resolution_basis"] = line[len("- **Resolution basis:**"):].strip()
            elif current_conflict is not None and line.startswith("- **Resolution:**"):
                current_conflict["resolution_note"] = line[len("- **Resolution:**"):].strip()
            elif line.strip() and not line.startswith("-") and current_conflict is None:
                no_conflict_note = line.strip()

        elif part == "gaps":
            if line.startswith("- "):
                g = _parse_gap(line)
                if g:
                    gaps.append(g)

        elif part == "sources":
            if line.startswith("|") and not line.startswith("|---") and "DOC-ID" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells and re.match(r"^[A-Z]{2}-\d{2}$", cells[0]):
                    sources.append({
                        "doc_id": cells[0],
                        "status": cells[1] if len(cells) > 1 else "",
                        "note": cells[2] if len(cells) > 2 else "",
                    })

    recommendations = next((s for s in sections if s["heading"] == RECOMMENDATIONS_HEADING), None)
    finding_sections = [s for s in sections if s["heading"] != RECOMMENDATIONS_HEADING]
    cited = sorted({
        f["citation"]["doc_id"]
        for s in sections for f in s["findings"] if f["citation"]
    })

    return {
        "question": question,
        "sections": finding_sections,
        "recommendations": recommendations["findings"] if recommendations else [],
        "conflicts": conflicts,
        "no_conflict_note": no_conflict_note,
        "gaps": gaps,
        "sources": sources,
        "stats": {
            "sections": len(finding_sections),
            "findings": sum(len(s["findings"]) for s in finding_sections),
            "recommendations": len(recommendations["findings"]) if recommendations else 0,
            "conflicts": len(conflicts),
            "gaps": len(gaps),
            "sources": len(sources),
            "cited_documents": len(cited),
        },
        "cited_doc_ids": cited,
    }
