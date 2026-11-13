"""Extraction tests against synthetic fixtures — no real corpus, no API key.

Covers the three failure modes the real corpus is known to embed:
  - normal readable docx with headings (like CL-01)
  - parsed-but-empty docx (like PV-06)
  - a doc_id whose file cannot be uniquely resolved (open/parse failure)
plus an xlsx sheet-based document (like EX-05).
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import docx
import openpyxl

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.extraction import extract_document
from src.models import ReadStatus


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

        # A normal readable docx with two headings (simulating CL-01-style structure)
        doc = docx.Document()
        doc.add_heading("Section 5 Statement on Remediation Activity", level=1)
        doc.add_paragraph("The programme has made substantial progress. Certain workstreams remain in delivery.")
        doc.add_heading("Item 6 Financial Crime Remediation Programme", level=1)
        doc.add_paragraph("All twelve high-priority findings have been remediated and closed.")
        doc.save(self.tmpdir / "CL-01 Annual Report Extract FY2025.docx")

        # An empty docx (simulating PV-06): one blank paragraph only
        empty_doc = docx.Document()
        empty_doc.add_paragraph("")
        empty_doc.save(self.tmpdir / "PV-06 Lessons Learned.docx")

        # An xlsx with one sheet (simulating EX-05)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Peer Benchmarking"
        ws.append(["Metric", "Meridian FY2025", "Peer median"])
        ws.append(["Cost-income ratio", 71.2, 66.4])
        wb.save(self.tmpdir / "EX-05 Peer Benchmarking Extract.xlsx")

        # Note: no file at all for CL-02 -> simulates open/parse failure (unresolvable glob)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_readable_docx_has_outline_and_text(self):
        result = extract_document("CL-01", str(self.tmpdir))
        self.assertEqual(result.status, ReadStatus.OK)
        refs = [o.ref for o in result.outline]
        self.assertIn("Section 5 Statement on Remediation Activity", refs)
        self.assertIn("Item 6 Financial Crime Remediation Programme", refs)
        self.assertIn("substantial progress", result.full_text)

    def test_empty_docx_is_flagged_empty_not_failed(self):
        result = extract_document("PV-06", str(self.tmpdir))
        self.assertEqual(result.status, ReadStatus.EMPTY)
        self.assertEqual(result.outline, [])
        self.assertIsNone(result.error)  # distinct from a processing failure

    def test_missing_file_is_flagged_failed_to_process(self):
        result = extract_document("CL-02", str(self.tmpdir))
        self.assertEqual(result.status, ReadStatus.FAILED_TO_PROCESS)
        self.assertIsNotNone(result.error)

    def test_xlsx_sheet_becomes_outline_ref(self):
        result = extract_document("EX-05", str(self.tmpdir))
        self.assertEqual(result.status, ReadStatus.OK)
        self.assertEqual([o.ref for o in result.outline], ["Peer Benchmarking"])
        self.assertIn("Cost-income ratio", result.full_text)


if __name__ == "__main__":
    unittest.main()
