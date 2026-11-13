"""Dependency-free BM25 ranking (stdlib only).

Used only as a hint passed alongside each document's outline into the
Planning subagent's prompt — it never excludes a document itself. The model
makes the actual selection; this just gives it a cheap, deterministic
keyword-overlap signal to weigh, which is especially useful for the
documents it would otherwise have to judge from title/outline alone.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "he", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "to", "was", "were", "will", "with", "this", "these", "those", "their",
    "what", "which", "who", "whom", "we", "you", "i", "they", "them",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Light suffix stripping, not a real stemmer — just enough to collapse the
# most common plural/verb-form variants so "remediation"/"remediations" or
# "screen"/"screening" count as the same term for this small corpus.
_SUFFIXES = ("ing", "edly", "ies", "ied", "ed", "es", "ly", "s")


def _stem(token: str) -> str:
    for suffix in _SUFFIXES:
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    return [_stem(t) for t in tokens if t not in _STOPWORDS and len(t) > 1]


@dataclass
class _DocEntry:
    doc_id: str
    term_counts: dict[str, int]
    length: int


@dataclass
class BM25Index:
    docs: list[_DocEntry] = field(default_factory=list)
    doc_freq: dict[str, int] = field(default_factory=dict)
    avg_length: float = 0.0

    def __len__(self) -> int:
        return len(self.docs)


_K1 = 1.5
_B = 0.75


def build_index(docs: dict[str, str]) -> BM25Index:
    """`docs` maps doc_id -> the text to index. Returns a BM25Index ready
    for `score()`. An empty `docs` dict produces an empty (but usable)
    index — callers never need to special-case "no documents"."""
    index = BM25Index()
    total_length = 0
    for doc_id, text in docs.items():
        tokens = tokenize(text)
        counts: dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        index.docs.append(_DocEntry(doc_id=doc_id, term_counts=counts, length=len(tokens)))
        total_length += len(tokens)
        for term in counts:
            index.doc_freq[term] = index.doc_freq.get(term, 0) + 1
    index.avg_length = (total_length / len(index.docs)) if index.docs else 0.0
    return index


def score(query: str, index: BM25Index) -> dict[str, float]:
    """Returns {doc_id: bm25_score} for every document in the index, scored
    against `query`. Every indexed doc_id always gets an entry (0.0 if there
    is no term overlap, or if the query/index is empty) — callers can rank
    without filtering out missing keys."""
    query_terms = set(tokenize(query))
    n = len(index.docs)
    scores: dict[str, float] = {entry.doc_id: 0.0 for entry in index.docs}
    if n == 0 or not query_terms:
        return scores
    for term in query_terms:
        df = index.doc_freq.get(term, 0)
        if df == 0:
            continue
        idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
        for entry in index.docs:
            tf = entry.term_counts.get(term, 0)
            if tf == 0:
                continue
            norm_length = entry.length / index.avg_length if index.avg_length else 1.0
            denom = tf + _K1 * (1 - _B + _B * norm_length)
            scores[entry.doc_id] += idf * (tf * (_K1 + 1)) / denom
    return scores
