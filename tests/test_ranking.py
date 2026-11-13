"""Tests for the dependency-free BM25 ranking helper — pure code, no API
key, no real corpus."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ranking import build_index, score, tokenize


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(tokenize("Sanctions Screening, Tuning!"), ["sanction", "screen", "tun"])

    def test_drops_stopwords_and_single_chars(self):
        tokens = tokenize("the control is a key risk to the business")
        self.assertNotIn("the", tokens)
        self.assertNotIn("a", tokens)
        self.assertNotIn("is", tokens)
        self.assertIn("control", tokens)
        self.assertIn("risk", tokens)

    def test_empty_text(self):
        self.assertEqual(tokenize(""), [])


class RankingOrderTests(unittest.TestCase):
    def test_document_with_more_query_term_overlap_scores_higher(self):
        docs = {
            "A": "Financial crime remediation programme status and sanctions screening tuning review.",
            "B": "Investor presentation covering share price and dividend policy for the quarter.",
        }
        index = build_index(docs)
        scores = score("sanctions screening tuning remediation", index)
        self.assertGreater(scores["A"], scores["B"])

    def test_every_indexed_doc_gets_a_score_entry(self):
        docs = {"A": "alpha beta", "B": "gamma delta"}
        index = build_index(docs)
        scores = score("alpha", index)
        self.assertEqual(set(scores.keys()), {"A", "B"})
        self.assertGreater(scores["A"], scores["B"])  # B has no overlap -> stays at 0.0
        self.assertEqual(scores["B"], 0.0)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_index(self):
        index = build_index({})
        self.assertEqual(len(index), 0)
        self.assertEqual(score("anything", index), {})

    def test_empty_query(self):
        index = build_index({"A": "some content here"})
        scores = score("", index)
        self.assertEqual(scores, {"A": 0.0})

    def test_query_terms_not_present_in_any_document(self):
        index = build_index({"A": "alpha beta", "B": "gamma delta"})
        scores = score("zzz nonexistent term", index)
        self.assertEqual(scores, {"A": 0.0, "B": 0.0})


if __name__ == "__main__":
    unittest.main()
