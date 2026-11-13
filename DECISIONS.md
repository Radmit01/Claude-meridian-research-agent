# Key judgment calls

1. **Pipeline stages, not a free-form delegating coordinator.** The coordinator
   does not let an LLM decide at runtime which subagent to call next; the DAG
   (triage → retrieval → parallel document analysis → conflict detection →
   synthesis → drafting) is fixed in Python. Tradeoff: less "agentic"-looking,
   but the pipeline is testable and debuggable stage-by-stage, and nothing
   about this task benefits from dynamic replanning — the brief's structure
   (fixed 4-section output, fixed failure-handling rules) is itself a fixed
   pipeline.

2. **Decomposition by pipeline stage, not by corpus source set.** Rejected an
   obvious alternative (one subagent per Set A/B/C) after reading the full
   corpus and confirming the embedded conflict and most high-value findings
   only emerge by cross-referencing across sets. A per-set split would have
   pushed that cross-referencing work back onto the coordinator itself.

3. **A 5th subagent role (dedicated Conflict Detection) beyond the 4 named in
   the brief.** Justified because the corpus has a confirmed, deliberately
   embedded conflict (CL-05 vs EX-07) with a reinforcing evidentiary chain
   across 5+ other documents — folding this into Synthesis would overload
   that stage and make conflict logic harder to test in isolation.

4. **Two-tier reading: triage (metadata-only) then selective deep analysis.**
   Stage 0 opens and classifies all 28 documents (cheap: open/outline only)
   so the Sources Consulted table can always be complete and honest, even for
   a narrow question that only deep-analyzes a handful of documents. Deep
   analysis (full text into context) is reserved for documents Retrieval
   actually selects, to keep context bounded.

5. **Citation validation is deterministic code, not another LLM call.** Judges
   mechanically check citation format; a second model call to "check the
   first model's citations" would just add another source of hallucination.
   Validation is a fuzzy string match (difflib) between the cited `ref` and
   the outline actually extracted from that document — exact match was
   rejected as too brittle (models paraphrase heading text).

6. **Three distinct failure/gap categories, never collapsed into one.** Open/
   parse failure, parsed-but-empty (PV-06's exact failure mode), and
   content-intentionally-withheld-within-a-readable-doc (CL-06's annex) are
   modeled as separate `GapReason` values. Collapsing these into a single
   "couldn't read it" bucket would lose information the brief explicitly asks
   the Coverage Gaps section to report (why, specifically).

7. **Conflicts can resolve to "unresolved," and must say why.** The resolution
   schema requires a `resolution_note` even when `resolution_basis` is
   `unresolved` — a design that structurally prevents a lazy "no conflict
   found" output when the evidence doesn't cleanly support declaring a winner
   (the real corpus's CL-05/EX-07 conflict is exactly this case: management
   assertion vs. independent/supervisory validation, not reconcilable from the
   corpus alone).

8. **Dataclasses, not pydantic.** The project environment used for design/test
   work did not have reliable internet access for installing third-party
   validation libraries; stdlib dataclasses plus `unittest` keep the core
   logic (manifest, extraction, citation, pack rendering) testable with zero
   non-stdlib dependencies beyond the document-parsing libraries themselves
   (`python-docx`, `openpyxl`, `pypdf`), which are declared in
   `requirements.txt` for the real run environment.

9. **Atlas/Entra auth fetched once per process launch, not per-stage.** A
   single bearer token is fetched at the start of `run_research` and reused
   for all stages via `ClaudeAgentOptions(env=...)`. Token rotation via Claude
   Code's `apiKeyHelper` mechanism was identified as the right fix if a full
   Q3 (broad pack) run risks outliving the Entra token's lifetime, but is not
   implemented yet — deferred until the Atlas 401 blocker is resolved and an
   actual run's wall-clock time can be measured.

10. **PDF heading detection is heuristic, not format-native.** PDFs (EX-01,
    EX-03) don't carry heading styles the way docx does, so section
    boundaries are detected by line-shape heuristics. Originally only
    numbered-label and ALL-CAPS patterns were implemented; once the real
    corpus files were available, both PDFs turned out to use title-case
    headings (e.g. "Priority Area One — Financial Crime Controls") that
    matched neither pattern, so each was only capturing 1 outline entry.
    Added a title-case heuristic (first letter of each non-stopword
    capitalized, short line, no trailing sentence punctuation) and verified
    against the real files: EX-01 now correctly captures all 6 "Priority
    Area" headings plus "Purpose of this Notice" (11 entries total, including
    a few harmless fragments from wrapped title/footer text); EX-03 captures
    all 4 real headings. This mattered specifically because the brief's own
    output template cites `[EX-01, Priority Area One]` by name as its
    worked example — an outline that couldn't produce that exact ref would
    have made the template's own example citation fail validation.

11. **Drafting is a real, narrowly-scoped SDK call — not discarded.** The
    brief names "drafting" as one of the four minimum roles by name, not
    just "any 4 roles total." An earlier version of this pipeline called a
    Drafting subagent but discarded its response entirely, rendering the
    pack deterministically regardless — an API call that changed nothing,
    and which also would not have satisfied the brief's literal requirement
    even though it technically "ran." The fix was not to drop the call but
    to scope it so it can be wired in safely: Drafting is given only
    `{id, topic, claim}` for every finding — **never a citation** — and
    returns only `{id, claim}` pairs. Citations and topics always come from
    the original `Finding` object, stitched back in deterministically by id
    (`_apply_drafted_claims`). A missing id, a malformed item, or a failed
    batch call simply falls back to the original claim text for that
    finding — it can never drop a finding, duplicate one, or produce a
    citation the model invented. This keeps the same guarantee the original
    decision was protecting (zero model unpredictability in structure/
    citation format) while actually using Drafting for what it's named for:
    rewriting claims into client-ready prose.

12. **Subagent JSON contracts made explicit and parsing made defensive.**
    The original prompts for Synthesis and Conflict Detection told the model
    to return "JSON matching the X shape" without ever showing that shape —
    risky, since `coordinator.py` parses specific keys (e.g.
    `findings_by_section`, and `GapReason` values that must match one of
    four exact long strings character-for-character). Rewrote every stage
    prompt to show the literal expected JSON structure and explicitly
    forbid markdown code fences. Also added `_parse_json_response()`, a
    small defensive unwrapper that strips a ```` ``` ```` fence if the model
    adds one anyway, rather than let an otherwise-correct response fail
    `json.loads` on a stray fence alone.

13. **Batching + parallelism, tuned after measuring where time actually
    went.** The real cost/reliability bottleneck on the dev host turned out
    to be the number of SDK subprocess spawns, not model latency or per-call
    token volume (each `_call_subagent` call launches a fresh CLI
    subprocess, and that spawn is what a memory-constrained host struggles
    with — observed directly as OOM crashes and init timeouts under load).
    Three changes followed from measuring this rather than guessing:
    - **Stage 2 (Document Analysis)** groups documents into fixed-size
      batches (`_DOC_ANALYSIS_BATCH_SIZE`) per subagent call instead of one
      call per document, with bounded concurrency
      (`_DOC_ANALYSIS_CONCURRENCY`) — fewer spawns, same `Finding` schema.
    - **Stage 4 (Synthesis + Recommendations)** were originally one combined
      call; per-stage timing showed this had become the single largest
      stage once Recommendations were added. Split into two independent
      calls over the same raw inputs, run in parallel via `asyncio.gather`
      — Recommendations never needed Synthesis's organized section output,
      only the same findings/conflicts Synthesis also receives.
    - **Stage 5 (Drafting)** uses the same batching pattern as Stage 2, for
      the same reason: one call per finding multiplies spawns, one call for
      every finding risks an oversized response (the same truncation
      failure mode Synthesis hit before it was split).
    None of this changes the final pack's schema, citation format, or
    section structure — it only changes how many subagent round-trips
    produce the same content, verified by independently re-checking
    citations against extracted outlines after every tuning change, not
    just trusting the pipeline's own self-reported issue count.

14. **A recommendation with no real finding to cite must be omitted, not
    given a fabricated citation.** The Recommendations subagent was asked to
    always cite a specific piece of evidence, but documents with no
    extractable content (e.g. PV-06) have no real findings to cite — the
    model's first instinct was to invent a "citation" by quoting the
    document's own Sources Consulted status text as if it were a section
    heading (`[PV-06, sources_consulted — status: processed — no
    extractable content]`), which the deterministic citation validator
    correctly flagged (fuzzy-match ratio 0.00 against an empty outline).
    Rather than relax the validator, the prompt was tightened: if the only
    "evidence" for a potential recommendation is a document that failed to
    process or yielded nothing, omit that recommendation — the gap is
    already captured separately in Synthesis's Coverage Gaps output, so
    nothing is lost by not re-raising it as an ungrounded recommendation.
