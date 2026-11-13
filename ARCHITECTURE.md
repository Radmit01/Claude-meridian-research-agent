# Architecture — Meridian Research Pack System

## Topology

Coordinator + 7 subagent roles. The brief names four specific minimum roles —
Search, Document Analysis, Synthesis, Drafting — and permits additional roles
for meaningful decomposition. This system covers all four named roles plus
three more: Triage + Retrieval together implement Search, issued as ONE
subagent call (DECISIONS.md #22) since Retrieval never needed a second
round-trip once Triage's scores exist — a dependency-free BM25
keyword-overlap score (`src/ranking.py`) is passed in as a selection hint,
never as a filter. Document Analysis (batched, parallel — DECISIONS.md
#13/#20), Conflict Detection (an added role — the corpus was read in full
during design and confirmed to embed its primary conflict (CL-05 vs EX-07)
and reinforcing signals *across* source sets, not within one; folding
conflict detection into Synthesis would have made that step overloaded and
harder to test/inspect in isolation), Synthesis + Recommendations (split
from one combined call so they run in parallel — see "Parallelism" below),
and Drafting.

```
                         ┌───────────────┐
                         │  Coordinator  │
                         └───────┬───────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 0+1: Planning            │   ONE subagent call —
                 │  - open & classify all 28 docs │   logged as two stages
                 │  - BM25 score/rank (hint only,  │   ([1/7] Triage, [2/7]
                 │    local computation, never a   │   Retrieval) for
                 │    filter)                       │   dashboard/log
                 │  - score relevance, select a    │   compatibility, but
                 │    subset to deep-analyze        │   one round-trip does
                 │  - derive 3-8 sub_questions      │   both jobs
                 └───────────────┬───────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
   ┌──────┴──────┐        ┌──────┴──────┐        ┌──────┴──────┐
   │ Doc Analysis │  ...   │ Doc Analysis │  ...   │ Doc Analysis │   PARALLEL
   │ agent (batch)│        │ agent (batch)│        │ agent (batch)│   fan-out,
   └──────┬──────┘        └──────┬──────┘        └──────┬──────┘   batch size
          │                      │                      │          computed to
          └──────────────────────┼──────────────────────┘          fit one wave
                                 │                                   at the
                   (every finding gets a stable                      configured
                    integer id — DECISIONS.md #23)                   concurrency
                 ┌───────────────┴───────────────┐
                 │ Stage 3: Conflict Detection    │   sequential (1 agent),
                 │  - groups findings by topic     │   references findings
                 │  - flags contradictions         │   by id — citations are
                 │  - proposes resolution basis     │   looked up from the
                 │    (recency/authority/independence)│ referenced finding,
                 └───────────────┬───────────────┘   never model-written
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 4: Synthesis             │   also id-referencing:
          ┌──────┤  + Recommendations (PARALLEL)  ├──────┐  sections list
          │      │  - Synthesis groups finding ids │      │  finding ids, not
          │      │    under sections, derives Gaps │      │  full objects —
          │      │  - Recommendations references a  │      │  this is what cut
          │      │    finding_id per recommendation │      │  Synthesis's
          │      └──────────────────────────────────┘      │  output tokens
          └──────────────────────┬───────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │ Stage 5: Drafting (PARALLEL    │   batched (higher batch-
                 │  across batches)                │   size ceiling than
                 │  - rewrites each finding's claim│   Document Analysis —
                 │    into polished client prose   │   tiny payload, no doc
                 │  - sees/returns {id,topic,claim}│   text, no citation, so
                 │    ONLY — never citations, so   │   it cannot corrupt one
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

- **Stage 2 (Document Analysis)** — documents are grouped into batches
  sized by `_compute_batch_size` (DECISIONS.md #20): computed per run so
  the number of batches fits within `MAX_CONCURRENT_SUBAGENTS` wherever the
  document count allows, rather than a fixed size. Every batch then runs
  under one shared, module-level semaphore.
- **Stage 4 (Synthesis + Recommendations)** — these were one combined call;
  splitting them lets both run concurrently instead of sequentially, since
  Recommendations only needs the same raw findings/conflicts Synthesis
  gets, not Synthesis's organized output. Both reference findings by id
  (DECISIONS.md #23) rather than re-emitting them, which is what let
  Synthesis's own generation time drop sharply once it no longer had to
  retype every finding's topic/claim/citation in its response.
- **Stage 5 (Drafting)** — findings are grouped into batches sized by the
  same `_compute_batch_size`, but with a much higher ceiling than Document
  Analysis's (60 vs 8): a Drafting item is a tiny `{id, topic, claim}`
  triple with no document text and no citation, so a far larger batch
  still fits comfortably, and measured live, capping it at the same
  ceiling as Document Analysis regressed a 114-finding run from one wave
  to four sequential rounds (127.9s instead of the ~20-55s the larger
  ceiling restores).

Every other stage consumes the full output of the previous stage and cannot
start earlier, so they run sequentially. The merged Planning call (Stage
0+1, DECISIONS.md #22) doesn't parallelize Triage against Retrieval because
there was never real parallelism to extract — Retrieval strictly needed
Triage's scores, so merging them into one round-trip is the correct fix,
not fanning them out. Stage 0's local file *extraction* (as opposed to its
one subagent call) does run concurrently across all 28 documents via worker
threads — pure local parsing, no subprocess/network involved, so this is a
free speed-up rather than a design tradeoff.

Batching documents/findings into a single subagent call, rather than one
call per item, is also the dominant lever for reliability on a
memory-constrained host: the SDK spawns a fresh CLI subprocess per call, and
that spawn — not model latency or per-call token volume — was the actual
cost/crash bottleneck observed in practice. Fewer, larger calls means fewer
spawns. The concurrency semaphore (`_subagent_semaphore`) is a single
module-level object shared by Document Analysis and Drafting rather than
one per stage, so `run_common.py --parallel` (running all three questions
at once) can't exceed the configured cap in aggregate — every question's
stages contend for the same slots instead of each question getting its own
separate allowance.

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
  full extracted text, in batches sized by `_compute_batch_size` (DECISIONS.md
  #20) rather than the full retrieved set at once. Its output is a compact
  list of structured `Finding` objects (claim, citation, topic tags) — the
  raw text never leaves this stage.
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
