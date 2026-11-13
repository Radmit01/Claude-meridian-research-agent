# Architecture — Meridian Research Pack System

## Topology

Coordinator + 7 subagent roles. The brief names four specific minimum roles —
Search, Document Analysis, Synthesis, Drafting — and permits additional roles
for meaningful decomposition. This system covers all four named roles plus
three more: Triage + Retrieval together implement Search (split because
Triage must cheaply classify all 28 documents before Retrieval selects a
subset to deep-analyze), Document Analysis, Conflict Detection (an added
role — the corpus was read in full during design and confirmed to embed its
primary conflict (CL-05 vs EX-07) and reinforcing signals *across* source
sets, not within one; folding conflict detection into Synthesis would have
made that step overloaded and harder to test/inspect in isolation), Synthesis
+ Recommendations (split from one combined call so they run in parallel —
see "Parallelism" below), and Drafting.

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
   │ agent (batch)│        │ agent (batch)│        │ agent (batch)│   fan-out,
   └──────┬──────┘        └──────┬──────┘        └──────┬──────┘   a fixed-
          │                      │                      │          size batch
          └──────────────────────┼──────────────────────┘          of docs
                                 │                                   per call
                 ┌───────────────┴───────────────┐
                 │ Stage 3: Conflict Detection    │   sequential (1 agent)
                 │  - groups findings by topic     │
                 │  - flags contradictions         │
                 │  - proposes resolution basis     │
                 │    (recency/authority/independence)│
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 4: Synthesis             │
          ┌──────┤  + Recommendations (PARALLEL)  ├──────┐
          │      │  - Synthesis builds sub-headed  │      │
          │      │    Findings, derives Gaps       │      │
          │      │  - Recommendations derives       │      │
          │      │    grounded engagement focus     │      │
          │      │    areas, independently          │      │
          │      └──────────────────────────────────┘      │
          └──────────────────────┬───────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 5: Drafting (PARALLEL    │   batched, same
                 │  across batches)                │   pattern as Stage 2
                 │  - rewrites each finding's claim│
                 │    into polished client prose   │
                 │  - sees/returns {id,topic,claim}│
                 │    ONLY — never citations, so   │
                 │    it cannot corrupt one         │
                 └───────────────┬───────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Render + Validate (no SDK call)│   deterministic code,
                 │  - renders the 4 mandatory      │   not an agent — see
                 │    sections as markdown          │   "Drafting agent"
                 │  - citation validator (fuzzy     │   below
                 │    match vs. extracted outlines) │
                 │  - structural sanity checks       │
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
conflict detection → synthesis → deterministic render) keeps each agent's job
single-purpose and inspectable, and makes the cross-set reasoning an explicit,
dedicated stage rather than an emergent side effect.

## Drafting agent

The brief names "drafting" as one of the four minimum subagent roles by
name, so it is implemented as a real, used SDK call — not subsumed into
deterministic rendering. An earlier version of this pipeline called a
Drafting subagent but discarded its response entirely, rendering the pack
deterministically regardless (DECISIONS.md #11) — an API call that changed
nothing. This version fixes that by actually wiring Drafting's output in,
while keeping its blast radius deliberately small:

- Drafting is given only `{id, topic, claim}` for every finding, across every
  section (including Recommendations) — **never the citation**. It cannot
  see a DOC-ID or ref, so it has no way to invent, corrupt, or reformat one.
- It returns only `{id, claim}` pairs — the polished prose. Citations and
  topics are always taken from the original `Finding` object and stitched
  back in deterministically by id (`_apply_drafted_claims` in
  `coordinator.py`), never from the model's response.
- If Drafting's response is missing an id, malformed, or a whole batch call
  fails, that finding simply keeps its original (Synthesis-authored) claim
  text — it is never dropped, duplicated, or left without a citation.
- The deterministic renderer and citation validator still run exactly as
  before, over whatever claim text Drafting produced, so the one place
  correctness matters most for scoring (section structure, exact required
  sentences, citation format) retains zero model unpredictability.

This means Drafting genuinely does the job the brief names it for (turning
structured claims into client-ready prose) while the earlier prototype's
actual problem — an API call with no effect on the output — is solved by
giving it real, narrowly-scoped work instead of discarding it.

## Parallelism

Three stages are parallelized, each for the same reason: independent units
of work with no shared state or ordering dependency between them.

- **Stage 2 (Document Analysis)** — documents are grouped into fixed-size
  batches (see `_DOC_ANALYSIS_BATCH_SIZE`), each batch analyzed by an
  independent subagent call, run with bounded concurrency
  (`_DOC_ANALYSIS_CONCURRENCY`).
- **Stage 4 (Synthesis + Recommendations)** — these were one combined call;
  splitting them lets both run concurrently instead of sequentially, since
  Recommendations only needs the same raw findings/conflicts Synthesis
  gets, not Synthesis's organized output.
- **Stage 5 (Drafting)** — findings are grouped into fixed-size batches (see
  `_DRAFTING_BATCH_SIZE`) for the same reason as Stage 2: one call per
  finding would multiply subprocess spawns, one call for every finding at
  once risks an oversized response.

Every other stage consumes the full output of the previous stage and cannot
start earlier, so they run sequentially. Stage 0 (triage) is cheap enough
(metadata/open-check, not full reasoning) that it runs as a single pass
rather than 28 parallel agents — fanning out 28 trivial opens would add
coordination overhead without saving wall-clock time that matters at this
corpus size. (Stage 0's local file *extraction*, as opposed to its one
subagent call, does run concurrently across all 28 documents via worker
threads — pure local parsing, no subprocess/network involved, so this is a
free speed-up rather than a design tradeoff.)

Batching documents/findings into a single subagent call, rather than one
call per item, is also the dominant lever for reliability on a
memory-constrained host: the SDK spawns a fresh CLI subprocess per call, and
that spawn — not model latency or per-call token volume — was the actual
cost/crash bottleneck observed in practice. Fewer, larger calls means fewer
spawns.

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
  full extracted text, in fixed-size batches (`_DOC_ANALYSIS_BATCH_SIZE`)
  rather than the full retrieved set at once. Its output is a compact list of
  structured `Finding` objects (claim, citation, topic tags) — the raw text
  never leaves this stage.
- Stages 3–4 (conflict detection, synthesis + recommendations) operate purely
  on the structured `Finding`/`Conflict`/`Gap` objects accumulated so far,
  never on raw document text. This keeps their context bounded by the number
  of *extracted claims*, not by corpus size.
- Stage 5 (drafting) narrows the funnel further still: it never sees
  citations, document IDs, or raw corpus text at all — only `{id, topic,
  claim}` triples, in fixed-size batches. This is the smallest possible
  surface area for the one stage whose entire job is rewriting prose, and is
  what makes it structurally impossible for Drafting to corrupt a citation.
  Final rendering is a deterministic function over the same structured
  objects — no SDK call, no context at all in the usual sense.

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
rendered pack, confirms the DOC-ID exists in the corpus manifest, and confirms
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
- Document Analysis parallelism is per-batch, not per-document; very large
  documents are not further split, since none in this corpus require it.
- Drafting polishes a claim's wording but cannot independently verify that
  the original claim was accurate — it inherits whatever correctness
  Document Analysis/Synthesis already established. The citation validator
  still checks the (unchanged) citation after drafting, but not the drafted
  prose's faithfulness to the claim it replaced; the prompt instructs the
  model not to alter facts/figures/names, but this is not mechanically
  re-verified the way citation format is.
