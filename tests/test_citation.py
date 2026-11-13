"""Citation validation tests — pure code, no API key, no real corpus."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.citation import CitationIssueType, validate_citations
from src.models import OutlineEntry


class CitationValidationTests(unittest.TestCase):
    def setUp(self):
        self.outlines = {
            "CL-05": [OutlineEntry(ref="Item 6 Financial Crime Remediation Programme")],
            "EX-07": [OutlineEntry(ref="Remediation Status Questioned")],
        }

    def test_valid_citation_passes(self):
        text = "The programme was reported closed [CL-05, Item 6 Financial Crime Remediation Programme]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(issues, [])

    def test_fuzzy_match_tolerates_minor_wording_difference(self):
        text = "Four findings remain open [EX-07, Remediation Status Questioned]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(issues, [])

    def test_unknown_doc_id_is_flagged(self):
        text = "Some claim [ZZ-99, Nonexistent Section]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, CitationIssueType.UNKNOWN_DOC_ID)

    def test_bare_page_number_is_flagged(self):
        text = "Some claim [CL-05, p. 4]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, CitationIssueType.BARE_PAGE_NUMBER)

    def test_ref_not_found_in_cited_document_is_flagged(self):
        text = "Some claim [CL-05, Completely Unrelated Heading About Something Else]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, CitationIssueType.REF_NOT_FOUND)

    def test_citation_to_doc_never_extracted_in_this_run_is_flagged(self):
        text = "Some claim [PV-09, Prior Scoping Note]."
        issues = validate_citations(text, self.outlines)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, CitationIssueType.NO_OUTLINE_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
