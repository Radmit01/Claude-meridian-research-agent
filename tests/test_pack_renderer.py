"""Pack rendering / gap propagation tests — pure code, no API key."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import (
    Citation,
    Conflict,
    ConflictPosition,
    CoverageGap,
    Finding,
    GapReason,
    ReadStatus,
    ResearchPack,
    ResolutionBasis,
    SourceRecord,
)
from src.pack_renderer import NO_CONFLICT_SENTENCE, render, validate_structure


def _minimal_pack(**overrides) -> ResearchPack:
    defaults = dict(
        question="Test question",
        findings_by_section={"Topic A": [Finding(topic="t", claim="A claim.", citation=Citation("CL-01", "Section 1"))]},
        conflicts=[],
        gaps=[],
        sources_consulted=[SourceRecord(doc_id="CL-01", status=ReadStatus.OK)],
    )
    defaults.update(overrides)
    return ResearchPack(**defaults)


class PackRendererTests(unittest.TestCase):
    def test_no_conflict_sentence_present_when_no_conflicts(self):
        md = render(_minimal_pack(conflicts=[]))
        self.assertIn(NO_CONFLICT_SENTENCE, md)

    def test_conflict_section_omits_no_conflict_sentence_when_conflict_exists(self):
        conflict = Conflict(
            subject="Is remediation complete?",
            position_a=ConflictPosition(Citation("CL-05", "Item 6 Financial Crime Remediation Programme"), "Reported complete."),
            position_b=ConflictPosition(Citation("EX-07", "Remediation Status Questioned"), "Four findings remain open."),
            resolution_basis=ResolutionBasis.UNRESOLVED,
            resolution_note="Management assertion vs. independent validation; not reconcilable from the corpus alone.",
        )
        md = render(_minimal_pack(conflicts=[conflict]))
        self.assertNotIn(NO_CONFLICT_SENTENCE, md)
        self.assertIn("Is remediation complete?", md)
        self.assertIn("[CL-05, Item 6 Financial Crime Remediation Programme]", md)
        self.assertIn("[EX-07, Remediation Status Questioned]", md)

    def test_gap_reasons_distinguish_failed_vs_empty_vs_withheld(self):
        gaps = [
            CoverageGap("X", GapReason.FAILED_TO_PROCESS, "CL-02", "low confidence"),
            CoverageGap("Y", GapReason.PROCESSED_EMPTY, "PV-06", "lessons-learned reconstructed from other docs"),
            CoverageGap("Z", GapReason.CONTENT_WITHHELD, "CL-06", "annex not available"),
        ]
        md = render(_minimal_pack(gaps=gaps))
        self.assertIn(GapReason.FAILED_TO_PROCESS.value, md)
        self.assertIn(GapReason.PROCESSED_EMPTY.value, md)
        self.assertIn(GapReason.CONTENT_WITHHELD.value, md)

    def test_sources_consulted_includes_failed_and_empty_statuses(self):
        sources = [
            SourceRecord("CL-01", ReadStatus.OK),
            SourceRecord("CL-02", ReadStatus.FAILED_TO_PROCESS, "could not resolve file"),
            SourceRecord("PV-06", ReadStatus.EMPTY),
        ]
        md = render(_minimal_pack(sources_consulted=sources))
        self.assertIn("| CL-02 | failed to process | could not resolve file |", md)
        self.assertIn("| PV-06 | processed — no extractable content |", md)

    def test_validate_structure_flags_duplicate_source_entries(self):
        sources = [SourceRecord("CL-01", ReadStatus.OK), SourceRecord("CL-01", ReadStatus.OK)]
        problems = validate_structure(_minimal_pack(sources_consulted=sources))
        self.assertTrue(any("duplicate" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
