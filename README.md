# Meridian Financial Group Research Pack System

Multi-agent research system (Protiviti Claude Hackathon 2026, Use Case 02)
that answers 3 fixed questions about a fictional client, Meridian Financial
Group, using only a fixed 28-document corpus. See `ARCHITECTURE.md` for the
pipeline design and `DECISIONS.md` for judgment calls and tradeoffs.

## Status

Complete and verified end to end against a real model. All 7 pipeline
stages (Triage, Retrieval, Document Analysis, Conflict Detection, Synthesis,
Recommendations, Drafting, plus deterministic rendering) have been run live,
repeatedly, against all three fixed questions, producing all three research
packs in `output/` with 0 citation and 0 structure issues on every clean
run. See `ARCHITECTURE.md` for the pipeline design and `DECISIONS.md` for
the judgment calls behind it, including the performance tuning in #13 and
the Drafting subagent's scope in #11.

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Copy `.env.example` (ask a teammate if you don't have one) to `.env` and fill
in the Atlas/Entra values below.

## Environment variables (`.env`)

This organization does not issue plain `ANTHROPIC_API_KEY` values — access is
via an internal gateway ("Atlas") authenticated with Microsoft Entra ID OAuth.
Required values:

| Variable | Purpose |
|---|---|
| `CLIENT_ID` | Entra ID app registration client ID |
| `TENANT_ID` | Entra ID tenant ID |
| `TOKEN_SCOPE` | OAuth scope requested for the bearer token |
| `MSF_SUBSCRIPTION_KEY` | Atlas gateway subscription key 
| `ANTHROPIC_BASE_URL` | Atlas gateway root URL (no trailing `/v1/messages`) |
| `AUTHENTICATION_TYPE_VALUE` | `EntraID` |
| `ANTHROPIC_MODEL` | Atlas-side model identifier |

**Do not set `ANTHROPIC_API_KEY`.** If both it and `ANTHROPIC_AUTH_TOKEN` are
present, the Claude Code CLI (which the Agent SDK launches as a subprocess)
silently prefers `ANTHROPIC_API_KEY` and bypasses the Atlas gateway entirely.

Run `python check_env.py` to confirm all required values are present and
look well-formed (it never prints secret values, only presence/length). Run
`python atlas_client.py` to confirm the gateway itself is reachable — this is
the first thing to re-check if a live run fails with a 401/403.

### Optional performance/dev env vars

All optional; the pipeline behaves exactly as before if none of these are
set.

| Variable | Default | Purpose |
|---|---|---|
| `MAX_CONCURRENT_SUBAGENTS` | `4` | Process-wide cap on concurrent SDK subprocess calls, shared by Document Analysis and Drafting (and, in aggregate, across all questions if `run_common.py --parallel` is used) — see DECISIONS.md #20. |
| `CLAUDE_MODEL_FAST` | unset | Routes Planning and Drafting to a different model (e.g. a faster/cheaper tier) if set; every other stage always uses `ANTHROPIC_MODEL`. DECISIONS.md #15 found no measured speedup from this with Haiku on this gateway — left as an opt-in, not recommended by default, see DECISIONS.md #21. |
| `RESEARCH_CACHE` | unset (`0`) | Set to `1` to cache Document Analysis findings per document in `output/.cache/analysis/`, keyed by the corpus file's own content hash + question + prompt version (DECISIONS.md #24). **Dev-only — never use this for a submission pack or the graded demo**, since a cached run doesn't actually exercise the live model call for that document. |

## Running

The three fixed questions each have a dedicated entry-point script:

```bash
python run_q1.py   # regulatory/compliance exposure
python run_q2.py   # prior Protiviti relationship
python run_q3.py   # full pre-engagement pack
```

Each writes its research pack to `output/` and prints a citation/structure
validation summary, per-stage timings, and token/cost usage. Run all three
in one command/process with:

```bash
python run_common.py
```

This runs Q1 → Q2 → Q3 **in that order, sequentially** by default, as the
brief requires for the graded demo. For local iteration, `--parallel` runs
all three concurrently instead — never use this for the submission pack or
the judged demo, only for your own faster feedback loop while developing:

```bash
python run_common.py --parallel
```

(Opens a browser for Entra login on first use; subsequent stages reuse the
same bearer token for the whole run.) The underlying entry point, if calling
it directly rather than through these scripts:

```python
from src.coordinator import run_research
import asyncio

result = asyncio.run(run_research(
    "What is Meridian's regulatory/compliance exposure?",
    # corpus_dir defaults to "Corpus" — pass a different path to override.
))
print(result["markdown"])
```

`result` also contains `pack` (the structured `ResearchPack`), `citation_issues`
(any citations that failed deterministic validation), `structure_issues`
(structural sanity checks on the pack), `sub_questions` (the Planning
subagent's breakdown of the question), `timings` (summed model-call seconds
per stage), and `usage` (`call_count`, `total_in_tok`, `total_out_tok`,
`total_cost_usd` across the whole run).

## Dashboard (frontend)

A browser dashboard wraps the same pipeline. `run_research` is not changed.
From the project venv:

```bash
pip install -r requirements.txt   # adds fastapi + uvicorn
python run_dashboard.py           # opens http://127.0.0.1:8000 (API docs at /api/docs)
```

What it does:
- **Runs:** start Q1/Q2/Q3 or a custom question, then watch each stage and the log live.
- **Packs:** browse findings, focus areas, conflicts, gaps and sources. Import a `.md` pack,
  or delete custom/imported ones (Q1–Q3 can't be deleted).
- **Corpus:**
  - upload a new document (`.docx`, `.pdf` or `.xlsx`; it gets the next DOC-ID in its set,
    e.g. `CL-11`);
  - replace a document's file (one of the original 28 must keep its format);
  - restore the previous file, delete uploaded documents, download any file;
  - **Sync corpus** rescans `Corpus/`, re-parses only changed files, and reports
    added/modified/missing files and files no DOC-ID claims (shift-click to force a full re-parse).
- **System:** env-var and dependency checks (presence only, never values).

**`ALLOW_CORPUS_EDITS`** (unset by default): the hackathon rules require
using only the fixed corpus supplied, with no additions, removals, or
replacements. Upload/replace/restore/delete are disabled (HTTP 403) unless
this is explicitly set to `1`; sync/list/download stay available since
they're read-only. The frontend hides the upload/replace/restore/delete
controls whenever `/api/health` reports the flag is off, so this isn't
just a backend-only guard.

Notes on uploads (only relevant with `ALLOW_CORPUS_EDITS=1`):
- Replaced and deleted files are moved to `Corpus/.backup/`, not destroyed.
- Uploaded documents are recorded in `Corpus/.custom_manifest.json` and added to the
  manifest only inside the dashboard process. `run_qN.py` still uses the original 28.
- Corpus changes are blocked while a run is in progress.

### Layout

```
server/
  app.py            FastAPI app: mounts routers + static frontend
  config.py         paths and limits
  schemas.py        request bodies
  deps.py           route guards (no corpus changes during a run)
  routers/          system.py · packs.py · corpus.py · runs.py
  services/         corpus_service (extract cache, sync, upload)
                    manifest_service (uploaded DOC-IDs)
                    pack_service · pack_parser · run_manager
frontend/
  index.html
  css/              styles.css (tokens, layout) · components.css (modal, upload, sync)
  js/api.js         client for every backend endpoint
  js/store.js       shared state (active run, corpus listing)
  js/router.js      hash router
  js/components/    modal, drawer, docDrawer, uploadDocModal, importPackModal, dropzone,
                    syncReport, citeChip, pipeline, runsTable, statusBar, toast, …
  js/pages/         overview, runNew, runWatch, runHistory, packList, packView, corpus, system
```

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/overview` | KPIs, fixed questions, packs, recent runs |
| GET | `/api/health` | env / dependency checks |
| GET | `/api/questions` | the three fixed questions |
| GET | `/api/packs` · `/api/packs/{name}` · `/api/packs/{name}/raw` | list / parsed pack / markdown |
| POST | `/api/packs/upload?filename=` | import a pack (raw `.md` body) |
| DELETE | `/api/packs/{name}` | delete a custom or imported pack |
| GET | `/api/corpus` · `/api/corpus/{id}` · `/api/corpus/{id}/file` | list / detail / download |
| POST | `/api/corpus/sync` | rescan + re-extract changed files, report changes |
| POST | `/api/corpus/upload?filename=&mode=new\|replace&set_key=&doc_id=&title=` | upload (raw file body) |
| POST | `/api/corpus/{id}/restore` | restore the previous file from `.backup` |
| DELETE | `/api/corpus/{id}` | delete an uploaded document |
| GET/POST | `/api/runs` | list / start a run |
| GET | `/api/runs/{id}` · `/api/runs/{id}/stream` | run detail / live server-sent events |
| POST | `/api/runs/{id}/cancel` | cancel a run |

## Testing

All tests run against synthetic fixtures generated in-test (tiny `.docx`/
`.xlsx` files built with `python-docx`/`openpyxl`) — **no real corpus and no
API key required**:

```bash
python -m unittest discover -s tests -v
```

Covers: document extraction (readable / parsed-empty / unresolvable-file
failure modes), citation validation (valid, fuzzy-matched, unknown DOC-ID,
bare page number, ref-not-found, doc-never-analyzed), pack rendering
(no-conflict sentence, conflict section, gap-reason distinctions, sources
table including failed/empty statuses, duplicate-source detection), and the
Drafting stage's pure flatten/stitch logic (citations/topics are never
touched by the model and always survive a malformed, partial, or missing
drafting response unchanged — see `test_coordinator_helpers.py`).

## Auth notes

Atlas authentication is confirmed working. The original teammate-provided
sample used a header name (`TokenCollector-Subscription-Key`) that didn't
match this tenant's actual gateway configuration, which produced a 401
"missing subscription key" error; the correct header for this tenant is
`MSF-Subscription-Key`, and `.env`/code have been updated accordingly
(`SUBSCRIPTION_KEY` → `MSF_SUBSCRIPTION_KEY`).

If `python atlas_client.py`'s browser-based login ever hangs (e.g. on a
locked-down corporate network that blocks the local redirect listener), set
`AUTH_METHOD=device_code` in `.env` to fall back to a device-code flow that
doesn't require an automatic browser launch.
