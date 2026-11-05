# Meridian Financial Group Research Pack System

Multi-agent research system (Protiviti Claude Hackathon 2026, Use Case 02)
that answers 3 fixed questions about a fictional client, Meridian Financial
Group, using only a fixed 28-document corpus. See `ARCHITECTURE.md` for the
pipeline design and `DECISIONS.md` for judgment calls and tradeoffs.

## Status

Design finalized; corpus-handling, citation-validation, and pack-rendering
code written and unit-tested (no API key required for these — see Testing
below). Live end-to-end wiring against the Claude Agent SDK is written but
**not yet exercised against a real model**: it is blocked on resolving a 401
("missing subscription key") from the organization's Atlas gateway. See the
"Auth" section below before attempting a live run.

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
| `SUBSCRIPTION_KEY` | Atlas gateway subscription key |
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

## Running

```python
from src.coordinator import run_research
import asyncio

result = asyncio.run(run_research(
    question="What is Meridian's regulatory/compliance exposure?",
    corpus_dir="/path/to/corpus",
))
print(result["markdown"])
```

`result` also contains `pack` (the structured `ResearchPack`), `citation_issues`
(any citations that failed deterministic validation), and `structure_issues`
(structural sanity checks on the pack).

## Testing

All tests run against synthetic fixtures generated in-test (tiny `.docx`/
`.xlsx` files built with `python-docx`/`openpyxl`) — **no real corpus and no
API key required**:

```bash
python -m unittest discover -s tests -v
```

Covers: document extraction (readable / parsed-empty / unresolvable-file
failure modes), citation validation (valid, fuzzy-matched, unknown DOC-ID,
bare page number, ref-not-found, doc-never-analyzed), and pack rendering
(no-conflict sentence, conflict section, gap-reason distinctions, sources
table including failed/empty statuses, duplicate-source detection).

## Known open issue

Atlas gateway returns a 401 "missing subscription key" even with all `.env`
values present and well-formed. Most likely causes (not yet confirmed):
the `SUBSCRIPTION_KEY` may not be provisioned for this specific account, or
the header name `TokenCollector-Subscription-Key` may not match this
tenant's actual gateway configuration. Flagged for SME/teammate follow-up per
the hackathon's own guidance on escalating environment/auth issues.
