# CLAUDE.md

Guidance for an AI assistant (or future me) picking this project back up.

## What this is

A solo hackathon submission (Protiviti Claude Hackathon 2026, Use Case 02:
Multi-Agent Research System). `run_research(question, corpus_dir)` in
`src/coordinator.py` is the single required entry point. Full design
rationale is in `ARCHITECTURE.md`; judgment calls are in `DECISIONS.md`.

## Project layout

- `src/manifest.py` — the 28 DOC-IDs, titles, source sets, formats. Single
  source of truth for valid citation IDs.
- `src/extraction.py` — docx/xlsx/pdf → `ExtractedDocument` (status + outline
  of citable section/heading/sheet refs + full text).
- `src/models.py` — all shared dataclasses (`Finding`, `Conflict`,
  `CoverageGap`, `SourceRecord`, `ResearchPack`, status enums). No
  third-party dependency (stdlib `dataclasses`/`enum` only) by design.
- `src/citation.py` — deterministic (non-LLM) citation validator.
- `src/pack_renderer.py` — renders a `ResearchPack` into the mandatory
  4-section markdown; also has `validate_structure` sanity checks.
- `src/agents/prompts.py` — system prompt per pipeline stage/role.
- `src/agents/tools.py` — the Agent SDK tool wrapping `extraction.py`, and
  the Atlas/Entra env-var builder (`atlas_env_from_dotenv`).
- `src/ranking.py` — dependency-free (stdlib-only) BM25, used only as a
  selection hint inside the merged Planning call (DECISIONS.md #22); never
  excludes a document, the model still decides.
- `src/coordinator.py` — the actual pipeline: ONE merged Planning call
  (Triage+Retrieval, DECISIONS.md #22) → parallel (dynamically batched)
  document analysis → conflict detection → parallel synthesis +
  recommendations → parallel (batched) drafting → render + validate.
  `_call_subagent` is the only function that talks to the SDK, and now logs
  per-call timing/token/cost (DECISIONS.md #17) and accepts an optional
  `model` override (DECISIONS.md #21, unset by default). Conflict
  Detection/Synthesis/Recommendations reference findings by a stable
  integer id rather than re-emitting them (DECISIONS.md #23) — citations
  are always looked up from the referenced finding, never model-written,
  which is also what makes citation fabrication structurally impossible
  now, not just prompt-discouraged. Drafting is a real subagent call (not
  discarded): it only ever sees/returns `{id, topic, claim}` — never
  citations — so it cannot corrupt one; see `_apply_drafted_claims` and
  DECISIONS.md #11.
- `tests/` — unit tests against synthetic fixtures, runnable with
  `python -m unittest discover -s tests -v`, no API key or real corpus
  required. Includes `test_coordinator_helpers.py` (Drafting's pure
  flatten/stitch logic, `_repair_json`, `_compute_batch_size` — no SDK
  needed) and `test_ranking.py` (BM25 tokenize/index/score).

## Things to know before touching this

- **Do not** set `ANTHROPIC_API_KEY` anywhere — this org uses an Atlas
  gateway + Entra ID bearer token instead, and `ANTHROPIC_API_KEY` silently
  wins and bypasses it if both are set. See `README.md`'s env var table and
  `atlas_client.py`.
- The corpus has a confirmed, deliberately embedded conflict (CL-05 board
  minutes "remediation substantially complete" vs. EX-07 press report "four
  findings remain open") and a confirmed broken source (PV-06 — valid docx,
  zero extractable text). Both are modeled explicitly in `src/models.py`
  (`GapReason`, `ResolutionBasis.UNRESOLVED`) — don't "fix" the system to
  always find a resolution or always find content; those are test cases the
  design is supposed to handle, not bugs.
- Citation format is mechanically checked: `[DOC-ID, section/sheet ref]`,
  never a filename, never a bare page number, never a paraphrase. See
  `src/citation.py`.
- Corpus decomposition is deliberately by pipeline stage, not by source set
  (Client/External/Protiviti) — see DECISIONS.md #2 for why.
- Development/testing environment for this repo's Python logic did not have
  general internet access for pip installs beyond what's preinstalled
  (`python-docx`, `openpyxl`, `pypdf` were available; `pydantic`/`pytest` were
  not) — hence stdlib dataclasses + `unittest` rather than those libraries.
  The real run environment (Windows venv, see `requirements.txt`) should have
  everything needed including `claude-agent-sdk`.
- Atlas auth is resolved (correct header is `MSF-Subscription-Key`, env var
  `MSF_SUBSCRIPTION_KEY` — see `README.md`). The full `run_research` pipeline
  (all 7 stages, all 7 subagent roles) has been run live end to end,
  repeatedly, against all three fixed questions, with 0 citation and 0
  structure issues on every clean run — see `output/` for the current
  generated packs. `run_q1.py` / `run_q2.py` / `run_q3.py` each run one
  question; `run_common.py` run directly (`python run_common.py`) runs all
  three in sequence in one process.
- Known runtime characteristics on a memory-constrained host, after the
  merged Planning call, id-referencing Synthesis/Conflict Detection/
  Recommendations, and the per-run batch-size formula (DECISIONS.md
  #20/#22/#23): Q1 ~2.7–3.3 min, Q2 ~2.7 min, Q3 (broadest question, most
  findings) ~4–5 min — a real improvement over the pre-#20/#22/#23 baseline
  (Q1/Q2 ~2.5–4.5 min, Q3 ~3.5–5+ min with occasional 299s runs from a
  batch-size misconfiguration caught and fixed live, see DECISIONS.md #20).
  Document Analysis and Drafting's own durations are now fairly stable
  (~35–55s each at default concurrency); the remaining variance is almost
  entirely Synthesis/Recommendations' model-response latency, which
  dropped sharply once Synthesis stopped re-emitting every finding as full
  JSON (DECISIONS.md #23) but still isn't perfectly constant run to run.
  `result["timings"]` and `result["usage"]` (DECISIONS.md #17) give exact
  per-stage seconds and token/cost figures for any given run rather than
  estimates — check those first before assuming a slowdown is a regression.
- The pipeline includes automatic retries at two independent layers:
  subprocess-level crashes/timeouts (`_call_subagent`, up to 4 attempts) and
  malformed/truncated JSON responses (`_call_subagent_json`, up to 3
  attempts, regenerating the whole call). Transient `[retry]` lines in the
  logs are expected and not a sign of a broken run.
