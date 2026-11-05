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
    boundaries are detected by line-shape heuristics (numbered/labelled lines,
    short all-caps lines) rather than true structural parsing. This is a
    known soft spot — flagged in ARCHITECTURE.md's Known Limitations — to be
    revisited once the real PDF files are available to check heuristic
    accuracy against their actual layout.
