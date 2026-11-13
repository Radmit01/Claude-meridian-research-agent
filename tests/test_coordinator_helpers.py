"""Unit tests for coordinator.py's pure, non-SDK helper functions: the
batching helper and the Drafting stage's flatten/stitch logic. These need no
Claude Agent SDK, API key, or live model call — they verify that a
malformed, partial, or missing Drafting response can never corrupt a
citation, drop a finding, or change the pack structure, since citations and
topics never round-trip through the model at all.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

from src.coordinator import (
    _apply_drafted_claims,
    _chunk,
    _compute_batch_size,
    _flatten_findings_for_drafting,
    _repair_json,
)
from src.models import Citation, Finding


class ChunkTests(unittest.TestCase):
    def test_chunk_splits_into_fixed_size_groups(self):
        self.assertEqual(_chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])

    def test_chunk_empty_list(self):
        self.assertEqual(_chunk([], 3), [])

    def test_chunk_works_on_dicts_not_just_strings(self):
        items = [{"id": 0}, {"id": 1}, {"id": 2}]
        self.assertEqual(_chunk(items, 2), [[{"id": 0}, {"id": 1}], [{"id": 2}]])


class DraftingHelpersTests(unittest.TestCase):
    def setUp(self):
        self.findings_by_section = {
            "Section A": [
                Finding(topic="t1", claim="Original claim one.", citation=Citation(doc_id="CL-01", ref="Ref One")),
                Finding(topic="t2", claim="Original claim two.", citation=Citation(doc_id="CL-02", ref="Ref Two")),
            ],
            "Section B": [
                Finding(topic="t3", claim="Original claim three.", citation=Citation(doc_id="CL-03", ref="Ref Three")),
            ],
        }

    def test_flatten_assigns_sequential_ids_and_omits_citations(self):
        payload, index = _flatten_findings_for_drafting(self.findings_by_section)
        self.assertEqual(len(payload), 3)
        self.assertEqual([p["id"] for p in payload], [0, 1, 2])
        self.assertNotIn("citation", payload[0])
        self.assertEqual(index, [("Section A", 0), ("Section A", 1), ("Section B", 0)])

    def test_apply_drafted_claims_replaces_claim_but_keeps_citation_and_topic(self):
        _, index = _flatten_findings_for_drafting(self.findings_by_section)
        drafted = {0: "Polished claim one.", 2: "Polished claim three."}
        result = _apply_drafted_claims(self.findings_by_section, index, drafted)

        self.assertEqual(result["Section A"][0].claim, "Polished claim one.")
        self.assertEqual(result["Section A"][0].topic, "t1")
        self.assertEqual(result["Section A"][0].citation.doc_id, "CL-01")
        self.assertEqual(result["Section A"][0].citation.ref, "Ref One")

        # id 1 was not drafted -> original claim preserved, nothing dropped
        self.assertEqual(result["Section A"][1].claim, "Original claim two.")

        self.assertEqual(result["Section B"][0].claim, "Polished claim three.")
        self.assertEqual(result["Section B"][0].citation.doc_id, "CL-03")

    def test_apply_drafted_claims_handles_fully_empty_response(self):
        _, index = _flatten_findings_for_drafting(self.findings_by_section)
        result = _apply_drafted_claims(self.findings_by_section, index, {})

        self.assertEqual(result["Section A"][0].claim, "Original claim one.")
        self.assertEqual(result["Section A"][1].claim, "Original claim two.")
        self.assertEqual(result["Section B"][0].claim, "Original claim three.")
        self.assertEqual(len(result["Section A"]), 2)
        self.assertEqual(len(result["Section B"]), 1)

    def test_apply_drafted_claims_ignores_unknown_ids(self):
        _, index = _flatten_findings_for_drafting(self.findings_by_section)
        # id 99 doesn't correspond to any real finding (e.g. a malformed/
        # hallucinated response) -- must not raise or corrupt anything.
        drafted = {0: "Polished claim one.", 99: "Should be ignored."}
        result = _apply_drafted_claims(self.findings_by_section, index, drafted)

        self.assertEqual(result["Section A"][0].claim, "Polished claim one.")
        self.assertEqual(len(result["Section A"]), 2)
        self.assertEqual(len(result["Section B"]), 1)


class RepairJsonTests(unittest.TestCase):
    def test_valid_json_passes_through_unchanged(self):
        text = '{"a": [1, 2, 3]}'
        self.assertEqual(json.loads(_repair_json(text)), {"a": [1, 2, 3]})

    def test_strips_markdown_fences(self):
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(json.loads(_repair_json(text)), {"a": 1})

    def test_repairs_truncated_array_cut_mid_item(self):
        # Last element cut off mid-string. Least-destructive repair closes
        # the dangling string + brackets, keeping both items (the second
        # with its claim truncated at the cut point) rather than discarding
        # it outright — downstream per-item validation handles any item
        # that ends up missing a required key, so this function doesn't
        # need to decide that itself.
        text = '{"items": [{"id": 1, "claim": "ok"}, {"id": 2, "claim": "cut of'
        repaired = _repair_json(text)
        parsed = json.loads(repaired)  # must not raise
        self.assertEqual(parsed["items"][0], {"id": 1, "claim": "ok"})
        self.assertEqual(len(parsed["items"]), 2)
        self.assertEqual(parsed["items"][1]["id"], 2)

    def test_repairs_truncated_object_missing_closing_brace(self):
        text = '{"findings_by_section": {"Section A": [{"id": 0, "claim": "x"}]}'
        repaired = _repair_json(text)
        parsed = json.loads(repaired)
        self.assertEqual(parsed, {"findings_by_section": {"Section A": [{"id": 0, "claim": "x"}]}})

    def test_leaves_unbalanced_unfixable_text_for_caller_to_reject(self):
        # Nothing safe to trim back to (no comma at any open depth) -> caller's
        # json.loads will still fail, which is correct: this isn't a case
        # _repair_json claims to fix, so it must not fabricate content.
        text = '{"a"'
        result = _repair_json(text)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(result)


class ComputeBatchSizeTests(unittest.TestCase):
    def test_sizes_batches_to_fit_one_wave_within_clamp(self):
        # 27 items, concurrency 4 -> ceil(27/4)=7, within [3,8] -> batch=7,
        # giving ceil(27/7)=4 batches, which fits in one wave of 4.
        size = _compute_batch_size(27, concurrency=4)
        self.assertEqual(size, 7)
        import math

        self.assertLessEqual(math.ceil(27 / size), 4)

    def test_clamps_to_minimum_for_small_item_counts(self):
        self.assertEqual(_compute_batch_size(2, concurrency=4), 3)

    def test_clamps_to_maximum_for_large_item_counts(self):
        self.assertEqual(_compute_batch_size(1000, concurrency=4), 8)

    def test_zero_items(self):
        self.assertEqual(_compute_batch_size(0, concurrency=4), 3)


if __name__ == "__main__":
    unittest.main()
