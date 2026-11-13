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

    (The fixed `_DOC_ANALYSIS_BATCH_SIZE`/`_DOC_ANALYSIS_CONCURRENCY`/
    `_DRAFTING_BATCH_SIZE` constants named above no longer exist as fixed
    values — #20 replaced them with a per-run `_compute_batch_size`
    formula and one shared `_subagent_semaphore`. The reasoning in this
    entry for *why* batching helps is still accurate; only the mechanism
    changed.)

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

15. **Model tiering by role — tried, measured, reverted.** The hypothesis
    was that Triage/Retrieval/Drafting (comparatively mechanical: relevance
    scoring, doc-ID selection, prose rewriting with facts held fixed) could
    run on a faster/cheaper model tier while Document Analysis/Conflict
    Detection/Synthesis/Recommendations (where corpus-wide judgment calls
    actually happen) kept the configured default. Implemented via an
    optional `model` override on `_call_subagent`/`ClaudeAgentOptions`,
    verified live with a trivial round-trip call before wiring it into the
    full pipeline. Two live Q1 runs afterward showed no net benefit: one hit
    four transient "model unavailable" errors specifically on the faster
    tier (costing far more in retry backoff than any latency saved), and
    the other — with zero retries — still ran slower end to end than the
    established single-model baseline, with Drafting processing findings
    at a lower per-finding rate than the single-model baseline had managed.
    The working theory is that on this Atlas gateway, subprocess-spawn and
    network round-trip overhead dominate total latency more than model
    generation speed, so a nominally faster model doesn't show up as a win
    while adding a new tier-specific availability risk. Reverted rather than
    kept "just in case" — DECISIONS.md records the attempt and the measured
    reason it didn't stick, consistent with documenting judgment calls
    whichever way they land, not only the ones that worked.

16. **Drafting's batch size can be much larger than Document Analysis's.**
    Both stages batch items into a single subagent call for the same reason
    (fewer SDK subprocess spawns — #13), but they aren't symmetric: a
    Document Analysis batch carries full extracted document text, while a
    Drafting batch carries only `{id, topic, claim}` triples with no
    document text and no citations. Raised `_DRAFTING_BATCH_SIZE` from 25
    to 50 on that basis — half as many Drafting round-trips for a given
    finding count, with no new risk introduced (no model change, no
    increase in concurrent subprocess count, same per-item payload shape),
    unlike the model-tiering attempt in #15. (Superseded by #20's dynamic
    formula, which replaced the fixed 50 with a per-run computed value —
    the reasoning above is still why Drafting gets a much higher ceiling
    than Document Analysis in that formula.)

17. **Per-call timing/token/cost instrumentation, with a per-run collector
    instead of a module global.** Every `_call_subagent` call now records
    spawn time (time to the first streamed message — subprocess spawn +
    SDK init), total time, input/output tokens, and cost, logged as
    `[timing] <label> spawn=Xs total=Ys in_tok=… out_tok=… cost=$…` and
    aggregated into `run_research()`'s returned `timings`/`usage` dicts
    (additive keys; every existing key is unchanged). Token/cost fields
    come from the SDK's `ResultMessage` (`usage`, `total_cost_usd`) rather
    than an estimate — inspected live first to confirm the actual field
    names and shapes rather than guessing. One correction made from that
    inspection: `usage["input_tokens"]` alone drastically undercounts real
    usage, since the system prompt is cached across calls within a run and
    the cached portion lands in `cache_creation_input_tokens`/
    `cache_read_input_tokens` instead — a trivial test call showed
    `input_tokens=2` but `cache_creation_input_tokens=22074`. `in_tok` sums
    all three so it reflects what was actually billed; `total_cost_usd` was
    already correct either way, since the SDK computes it from the full
    usage regardless of which bucket each token landed in. The collector is
    a `contextvars.ContextVar` holding a fresh list per `run_research()`
    call, not a module-level global, so `--parallel` (item 7) running
    multiple questions concurrently in one process gives each its own
    isolated stats rather than an interleaved shared one.

18. **JSON repair tried before paying for a full regenerate, validated by
    actually parsing each candidate rather than guessing.** A response
    truncated mid-generation (the same failure mode that motivated #13's
    Synthesis/Recommendations split) is often fixable locally: `_repair_json`
    tries candidates from least to most destructive — first just closing
    whatever string/brackets are still open (preserves every complete
    field), only falling back to trimming at progressively earlier commas
    (dropping an incomplete trailing element) if that doesn't parse — and
    returns the first candidate that an actual `json.loads` accepts, never
    a guessed-correct one. The first implementation got the trim-vs-close
    ordering backwards (tried trimming first, which could needlessly drop a
    trailing field when simply closing a brace would have preserved it
    intact — caught by testing both failure shapes, not just one). A
    dropped-but-incomplete trailing item (e.g. missing its `claim` key) is
    left for the existing per-item defensive parsing elsewhere to filter
    out — this function's job is producing valid JSON, not deciding what's
    semantically complete.

19. **`max_turns=1` for every JSON-contract call; left unset on the
    tool-use path.** Every stage except the live corpus-read-tool
    demonstration (`test_live_minimal.py`) is single-shot JSON generation
    with nothing to act on between turns, so more than one turn is never
    needed there. The tool-use path genuinely needs two turns (call the
    tool, then answer from its result), so `max_turns` stays unset
    specifically on that path — capping it at 1 there would break the
    brief's "agent invokes a tool" capability the live-tool test
    demonstrates.

20. **Batch size computed per run instead of fixed, plus one process-wide
    concurrency semaphore instead of one per stage.** `_compute_batch_size`
    sizes each stage's batches so the number of batches fits within the
    configured concurrency (`MAX_CONCURRENT_SUBAGENTS`, default 4) wherever
    the item count allows — every batch runs in one wave instead of several
    sequential rounds. Document Analysis and Drafting use different
    `max_size` ceilings (8 vs 60) for the same reason #16 gave Drafting a
    bigger fixed batch: a Document Analysis item carries full document
    text, a Drafting item is a tiny `{id, topic, claim}` triple. This
    wasn't a theoretical distinction — applying the Document Analysis
    ceiling to Drafting too (as a first pass, following the literal
    instruction to use "the same" formula for both) was measured live to
    regress a 114-finding Q1 run from one wave to four sequential rounds
    (127.9s instead of the ~20-55s a larger ceiling achieves), because 8
    was far too small a cap once finding counts exceeded `concurrency * 8`.
    Giving Drafting its own larger ceiling restored the one-wave property
    without touching Document Analysis's. The semaphore itself is also now
    a single module-level object shared by both stages (and, implicitly, by
    every concurrently-running question under `--parallel`), rather than a
    fresh one per stage — this is what makes the concurrency cap a true
    process-wide limit instead of a per-stage allowance that multiplies
    with however many things happen to run at once.

21. **Model tiering re-added as an explicit opt-in, default unset.** #15
    found no net benefit from Haiku on this gateway and reverted it. Re-adding
    the `model` override plumbing (unset by default — every stage still uses
    whatever `ANTHROPIC_MODEL` specifies unless `CLAUDE_MODEL_FAST` is set)
    keeps the capability available without re-enabling a change that was
    already measured not to help here; a different gateway or tenant may
    behave differently, and the plumbing costs nothing to keep while
    defaulting off. Planning and Drafting are the two stages that would use
    it if set, for the same reasoning #15 gave for Triage/Retrieval/Drafting.

22. **Triage and Retrieval merged into one Planning call, with a BM25 hint
    (never a filter).** Retrieval's prompt never needed a second round-trip
    once Triage's relevance scores exist in context — the two were always
    sequential and dependent, never genuinely parallel work. Merging them
    into one subagent call removes one full subprocess spawn + round-trip
    per run. `src/ranking.py` adds a dependency-free (stdlib-only) BM25
    implementation scored against each document's full extracted text
    (pure local computation, not sent to any LLM — distinct from the
    context-funnel rule that keeps full text OUT of what's sent to the
    model); the score/rank is passed to the Planning subagent as a hint
    alongside the outline, and the model still makes the actual relevance
    judgment and selection — BM25 never excludes a document itself. The
    `[1/7]`/`[2/7]` log lines are still emitted separately even though one
    call now does both jobs, since `server/services/run_manager.py`'s
    dashboard parses that exact format; Retrieval's own reported duration
    is correspondingly near-zero by design (the real cost shows up under
    Triage's duration instead), not a bug.

    Planning also now derives 3-8 sub_questions breaking the research
    question down into concrete things a pack answering it should cover.
    These are passed into Document Analysis (as guidance on what counts as
    material) and into Synthesis (as a preferred section structure) — live
    output shows Synthesis's chosen section headings tracking the
    sub_questions closely when they're relevant, which is the intended
    effect, not a coincidence.

23. **Conflict Detection, Synthesis, and Recommendations reference findings
    by id instead of re-emitting topic/claim/citation.** Every finding gets
    a stable integer id (plain Python `enumerate()` over `all_findings`,
    not a new field on the `Finding` dataclass — the schema stays exactly
    as it was, per the hard constraint on keeping `Finding`/`Conflict`/
    `CoverageGap`/`ResearchPack` unchanged). All three stages still *see*
    each finding's topic/claim/citation in their input (they need the
    content to reason about it), but their *output* only ever references a
    finding by id; the coordinator looks up the real citation from
    `finding_by_id` afterward, never from model-written text. This was the
    direct fix for the stated bottleneck ("Synthesis re-emits every finding
    as full JSON... so output tokens dominate") and measured as one: a
    147-finding Q1 run's Synthesis+Recommendations stage (already split
    into two parallel calls per the pre-existing #13 decision) dropped to
    ~35s, versus the 55-108s range observed before this change on
    comparable finding counts. It also has a correctness side effect worth
    keeping regardless of the speed win: #14's PV-06 citation-fabrication
    fix was a prompt instruction ("don't invent a citation"); under the
    id-only output contract, fabricating a citation is no longer something
    the model's output format even has room to do, since there is no
    citation field in Conflict Detection's, Synthesis's, or
    Recommendations's responses for it to put one in.

    One side effect caught in live testing and fixed by prompt instruction
    (not by changing the id mechanism itself): the model would occasionally
    leak a raw id number into its own free-text fields (a resolution_note
    reading "...(see finding 82)..." and "...(id 9)...") — harmless
    structurally (ids are never parsed out of free text, only out of the
    dedicated id fields) but confusing to a human reader, who has no way to
    know what "finding 82" refers to. Each prompt that receives id-bearing
    findings now explicitly says not to reference an id number in prose.

24. **Dev-only Document Analysis cache, explicitly never used for
    submission packs or the demo.** Keyed by (the corpus file's own
    SHA-256 — not the DOC-ID or a path, so a file edited in place still
    invalidates correctly, question text, `prompts.PROMPT_VERSION`), so a
    changed document, a different question, or a changed prompt contract
    can never silently serve stale cached findings. Off unless
    `RESEARCH_CACHE=1`; any cache-read/write problem falls back to a live
    call rather than failing a run — caching is a local-iteration
    convenience, not something a run should ever depend on.
