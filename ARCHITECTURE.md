# Architecture — Meridian Research Pack System

## Topology

Coordinator + 5 subagent roles (minimum required was 4; a 5th — dedicated conflict
detection — was added because the corpus was read in full during design and
confirmed to embed its primary conflict (CL-05 vs EX-07) and reinforcing signals
*across* source sets, not within one. Folding conflict detection into Synthesis
would have made that step overloaded and harder to test/inspect in isolation.)

```
                         ┌───────────────┐
                         │  Coordinator  │
                         └───────┬───────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 0: Triage (all 28 docs)  │   sequential, lightweight
                 │  - open every doc              │
                 │  - classify: ok / empty /      │
                 │    open-error                  │
                 │  - 1-line relevance score per   │
                 │    doc vs. the question         │
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 1: Search/Retrieval      │   sequential (1 agent)
                 │  - picks relevant doc subset    │
                 │    from triage output           │
                 │  - justifies inclusion/exclusion│
                 └───────────────┬───────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
   ┌──────┴──────┐        ┌──────┴──────┐        ┌──────┴──────┐
   │ Doc Analysis │  ...   │ Doc Analysis │  ...   │ Doc Analysis │   PARALLEL
   │  agent (doc) │        │  agent (doc) │        │  agent (doc) │   fan-out,
   └──────┬──────┘        └──────┬──────┘        └──────┬──────┘   1 per doc
          │                      │                      │          (or small
          └──────────────────────┼──────────────────────┘           disjoint
                                 │                                   batch)
                 ┌───────────────┴───────────────┐
                 │ Stage 3: Conflict Detection    │   sequential (1 agent)
                 │  - groups findings by topic     │
                 │  - flags contradictions         │
                 │  - proposes resolution basis     │
                 │    (recency/authority/independence)│
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 4: Synthesis             │   sequential (1 agent)
                 │  - builds sub-headed Findings   │
                 │  - derives Coverage Gaps        │
                 │    (failed/empty/withheld/      │
                 │     not-covered-by-any-doc)     │
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 5: Drafting              │   sequential (1 agent)
                 │  - renders the 4 mandatory      │
                 │    sections in final prose      │
                 │  - citation format pass          │
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Post-process: Citation         │   deterministic code,
                 │ Validator (non-LLM)            │   not an agent
                 └───────────────┬───────────────┘
                                 │
                         research pack .md
```

## Why this decomposition (not a per-source-set split)

Corpus analysis (see project memory `project_hackathon_corpus_notes`) showed the
corpus is deliberately interwoven: nearly every self-disclosed gap in Set A
(client) is independently corroborated in Set B (external) and mapped onto a
named Protiviti capability/POV in Set C. The embedded conflict (CL-05 vs EX-07)
and its reinforcing chain (CL-01, CL-10, EX-02, EX-03, PV-04, PV-08) only surface
by reading *across* sets. A coordinator that assigned one subagent per source set
would force conflict/cross-reference detection either nowhere or back onto the
coordinator itself, defeating the purpose of delegation. Splitting by **pipeline
stage** instead (triage → retrieval → per-document analysis → cross-document
conflict detection → synthesis → drafting) keeps each agent's job single-purpose
and inspectable, and makes the cross-set reasoning an explicit, dedicated stage
rather than an emergent side effect.

## Parallelism

Only Stage 2 (Document Analysis) is parallelized. Each instance is handed a
single document (or, for very short documents, a small fixed batch) and extracts
structured `Finding` objects independently — no shared state, no ordering
dependency between documents, so this is genuine parallelism. Every other stage
consumes the full output of the previous stage and cannot start earlier, so they
run sequentially. Stage 0 (triage) is cheap enough (metadata/open-check, not full
reasoning) that it runs as a single pass rather than 28 parallel agents — fanning
out 28 trivial opens would add coordination overhead without saving wall-clock
time that matters at this corpus size.

## Context strategy

The biggest context-discipline risk in this system is a 28-document, 3-format
corpus landing in full inside the coordinator's or synthesis agent's context
window. The design avoids this with a strict information-funnel:

- Stage 0 (triage) only ever sees per-document metadata (doc id, title, a short
  extracted outline of headings/sheet names, open/empty status) — never full
  body text — because all it needs to do is classify readability and score
  topical relevance.
- Stage 1 (retrieval) sees the triage table (not raw content) and the question,
  and returns a shortlist of doc IDs with a one-line justification each.
- Stage 2 (document analysis) is the only stage that ever loads a document's
  full extracted text, and only one document's worth at a time per agent
  instance. Its output is a compact list of structured `Finding` objects
  (claim, citation, topic tags) — the raw text never leaves this stage.
- Stages 3–5 (conflict detection, synthesis, drafting) operate purely on the
  structured `Finding`/`Conflict`/`Gap` objects accumulated so far, never on raw
  document text. This keeps their context bounded by the number of *extracted
  claims*, not by corpus size.

## Failure handling

Two distinct failure modes are handled, matching what was found in the corpus
(see `project_hackathon_corpus_notes`), plus a third discovered only at the
content level:

1. **Open/parse failure** — the extraction tool cannot produce any text at all
   (corrupt file, unreadable format). Recorded in Sources Consulted as
   `failed to process`.
2. **Parsed-but-empty** — the file opens and validates (e.g. PV-06: well-formed
   `.docx`, correct `Content-Types`/`rels`, but an empty `document.xml` body).
   Recorded distinctly as `processed — no extractable content`, never conflated
   with case 1, because the correct Coverage Gaps narrative differs ("this
   document exists and is well-formed but contains nothing" vs. "this document
   could not be opened").
3. **Content intentionally withheld within an otherwise-readable document**
   (e.g. CL-06's confidential regulatory-correspondence annex, referenced but
   "not reproduced here"). This cannot be detected by the extraction tool (the
   document opens and has plenty of text) — it is a semantic finding made by
   the Stage 2 Document Analysis agent for that document, and is carried
   forward as a scoped Coverage Gap in Synthesis, distinct from cases 1 and 2.

All three propagate to the final pack's Coverage Gaps section with a reason code
and, where applicable, confidence impact. None of them are silently dropped or
papered over, per the hard constraint in the brief.

Conflicts are never auto-resolved by picking a side. Stage 3 may propose a
resolution basis (recency, authority/independence of source) but if the
evidence genuinely does not support declaring a winner — as is the case for the
CL-05/EX-07 remediation-closure conflict, where the honest conclusion is
"management assertion vs. independent/supervisory validation, not reconcilable
from the corpus alone" — it must say so explicitly rather than force a
resolution.

## Citation validation

Citation integrity is checked deterministically, by code, not by another LLM
call: a post-processing pass extracts every `[DOC-ID, ref]` citation from the
drafted pack, confirms the DOC-ID exists in the corpus manifest, and confirms
the `ref` string plausibly matches a heading/section/sheet-name actually
extracted from that document during Stage 2 (fuzzy match against the doc's
outline, not exact string match, since models won't reproduce heading text
byte-for-byte). This catches fabricated citations and filename/page-number-only
citations before the pack is considered final, independent of model behavior.

## Known limitations

- Topical relevance scoring in Stage 0/1 is LLM-judgment-based, not a vector
  search — reasonable at 28 documents, would not scale to a much larger corpus.
- The citation validator confirms a cited section/sheet *exists* in the cited
  document; it does not verify the claim's content is actually supported by
  that section (true semantic grounding would require re-reading the source
  passage against the claim, which is a stretch goal, not implemented in v1).
- Document Analysis parallelism is per-document; very large documents are not
  further split, since none in this corpus require it.
