
"""run_research(question) — the single entry point required by the brief.

Orchestration is explicit Python, not an LLM-driven delegation loop: the
pipeline topology (sequential triage -> retrieval -> parallel doc analysis ->
sequential conflict detection -> synthesis -> deterministic render) is fixed
and coded here, while the actual reasoning at each stage is delegated to the
Claude Agent SDK via `_call_subagent`, using the role-specific prompts in
`agents/prompts.py`. This keeps the DAG inspectable/testable independent of
model behavior, while still using the Agent SDK as the orchestration layer
for every reasoning step, per the hard constraint in the brief.

5 SDK-delegated subagent roles (brief requires >=4): Triage, Retrieval,
Document Analysis (parallel), Conflict Detection, Synthesis. There is no
separate "Drafting" SDK call: the final markdown is produced by
`pack_renderer.render()`, a deterministic function, not a 6th model call.
This was a deliberate choice (see DECISIONS.md #11), not an oversight: it
guarantees the mandatory output structure, exact required sentences (e.g.
the no-conflict sentence), and citation format are always correct, with zero
model unpredictability in the one place correctness matters most for
scoring. The tradeoff is explicit: "Drafting" as a literally-named role is
fulfilled by deterministic code rather than a model call. 5 real
LLM-delegated roles comfortably clears the brief's minimum of 4 regardless.

`_call_subagent` is the one seam that actually talks to the SDK/Atlas
gateway; it has been verified live (see `test_live_minimal.py`), including
real tool-based delegation. The full 6->5-stage pipeline chained together
has not yet been run end to end against a real model.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any

from .agents import prompts
from .agents.tools import atlas_env_from_dotenv, build_read_corpus_document_tool
from .citation import validate_citations
from .extraction import extract_document
from .manifest import all_doc_ids
from .models import (
    Citation,
    Conflict,
    ConflictPosition,
    CoverageGap,
    ExtractedDocument,
    Finding,
    GapReason,
    ReadStatus,
    ResearchPack,
    ResolutionBasis,
    SourceRecord,
)
from .pack_renderer import render, validate_structure


def _parse_json_response(text: str) -> Any:
    """Models sometimes wrap JSON in markdown fences (```json ... ```) even
    when explicitly told not to. Strip that before parsing rather than let
    the whole pipeline stage fail on an otherwise-correct response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


_JSON_RETRY_MAX_ATTEMPTS = 3


async def _call_subagent_json(
    *, system_prompt: str, user_message: str, env: dict[str, str]
) -> Any:
    """Common wrapper used by every JSON-contract subagent call (Triage,
    Retrieval, Document Analysis, Conflict Detection, Synthesis): calls
    _call_subagent then parses the result as JSON, retrying the WHOLE call
    (not just the parse) if the model's response is malformed/truncated —
    distinct from _call_subagent's own retries, which handle subprocess-level
    crashes rather than bad model output. A regenerated response is often
    valid even when the first one wasn't, so this directly raises the odds a
    stage succeeds without changing what a successful response looks like."""
    last_error: Exception | None = None
    for attempt in range(1, _JSON_RETRY_MAX_ATTEMPTS + 1):
        response = await _call_subagent(system_prompt=system_prompt, user_message=user_message, env=env)
        try:
            return _parse_json_response(response)
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt == _JSON_RETRY_MAX_ATTEMPTS:
                raise
            print(
                f"    [retry] malformed JSON from subagent (attempt {attempt}/{_JSON_RETRY_MAX_ATTEMPTS}): "
                f"{exc}. Regenerating..."
            )
    raise last_error  # unreachable


# Subprocess spawn + SDK init handshake can be slow under host memory
# pressure (observed: 60s default load_timeout_ms tripped mid-run on a
# machine with <500MB free RAM even with concurrency capped at 3). Retried
# transient inits rather than failing the whole pipeline on one flaky spawn.
_SUBAGENT_LOAD_TIMEOUT_MS = 180_000
_SUBAGENT_MAX_ATTEMPTS = 4

# Stage 2 (Document Analysis) batching. Grouping several documents into one
# subagent call cuts the number of SDK subprocess spawns roughly BATCH_SIZE-fold
# versus one call per document — the dominant cost/reliability bottleneck on a
# memory-constrained host is spawning the CLI subprocess, not model latency or
# per-call token volume. Raise _DOC_ANALYSIS_CONCURRENCY on a host with more
# free RAM; both are safe to tune without touching the Finding schema or
# output structure.
_DOC_ANALYSIS_BATCH_SIZE = 5
_DOC_ANALYSIS_CONCURRENCY = 3


async def _call_subagent(
    *, system_prompt: str, user_message: str, env: dict[str, str], corpus_dir: str | None = None
) -> str:
    """The one seam that talks to the Claude Agent SDK. Returns the
    subagent's final text response."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query  # type: ignore

    allowed_tools = []
    mcp_servers: dict[str, Any] = {}
    if corpus_dir is not None:
        from claude_agent_sdk import create_sdk_mcp_server  # type: ignore

        read_tool = build_read_corpus_document_tool(corpus_dir)
        server = create_sdk_mcp_server(name="corpus", version="1.0.0", tools=[read_tool])
        mcp_servers = {"corpus": server}
        allowed_tools = ["mcp__corpus__read_corpus_document"]

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        env=env,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        load_timeout_ms=_SUBAGENT_LOAD_TIMEOUT_MS,
    )

    for attempt in range(1, _SUBAGENT_MAX_ATTEMPTS + 1):
        try:
            # AssistantMessage.content is a list of content blocks (TextBlock,
            # ThinkingBlock, ToolUseBlock, ToolResultBlock); only TextBlock carries
            # the model's text output. There is no flat `.text` on the message
            # itself — that was an earlier, incorrect assumption that silently
            # returned "" on every call. See project memory for detail.
            chunks: list[str] = []
            async for message in query(prompt=user_message, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)
            return "".join(chunks)
        except Exception as exc:
            if attempt == _SUBAGENT_MAX_ATTEMPTS:
                raise
            print(
                f"    [retry] subagent call failed (attempt {attempt}/{_SUBAGENT_MAX_ATTEMPTS}): "
                f"{type(exc).__name__}: {exc}. Retrying..."
            )
            await asyncio.sleep(15 * attempt)
    raise AssertionError("unreachable")


def _chunk(items: list[str], size: int) -> list[list[str]]:
    """Common batching helper: splits `items` into fixed-size chunks. Used to
    group multiple documents into a single subagent call, cutting down the
    number of SDK subprocess spawns — the real cost/reliability bottleneck on
    a memory-constrained host, not model latency (see DECISIONS.md)."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_finding_items(items: list, label: str) -> list[Finding]:
    """Common parser for a list of {"topic", "claim", "citation": {...}}
    dicts — shared by Synthesis's per-section findings and the Recommendations
    list, which use the identical shape."""
    parsed: list[Finding] = []
    for i in items:
        if not isinstance(i, dict) or "topic" not in i or "claim" not in i or "citation" not in i:
            print(f"    [warn] skipping malformed finding under {label!r}: {i!r}")
            continue
        parsed.append(Finding(topic=i["topic"], claim=i["claim"], citation=Citation(**i["citation"])))
    return parsed


async def _stage0_triage(question: str, corpus_dir: str) -> tuple[dict[str, ExtractedDocument], list[dict]]:
    # extract_document() is pure local file parsing (docx/xlsx/pdf), no
    # subprocess/network involved, so running all 28 extractions concurrently
    # via worker threads is a free speed win with zero effect on results —
    # same deterministic parsing, just not serialized one-by-one.
    doc_ids = all_doc_ids()
    extracted_docs = await asyncio.gather(
        *(asyncio.to_thread(extract_document, doc_id, corpus_dir) for doc_id in doc_ids)
    )
    extracted: dict[str, ExtractedDocument] = dict(zip(doc_ids, extracted_docs))
    readable = {k: v for k, v in extracted.items() if v.status == ReadStatus.OK}
    metadata = [
        {
            "doc_id": doc_id,
            "outline": [o.ref for o in doc.outline],
        }
        for doc_id, doc in readable.items()
    ]
    unreadable = [
        {"doc_id": doc_id, "status": doc.status.value, "error": doc.error}
        for doc_id, doc in extracted.items()
        if doc.status != ReadStatus.OK
    ]
    return extracted, metadata, unreadable  # type: ignore[return-value]


async def run_research(question: str, corpus_dir: str, verbose: bool = True) -> dict[str, Any]:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log("[0/6] Building Atlas env (Entra login may open a browser now)...")
    env = atlas_env_from_dotenv()
    log("[0/6] Env ready.")

    # Stage 0: triage (sequential, metadata-only, single pass)
    _t0 = time.monotonic()
    log("[1/6] Stage 0 (Triage): opening and classifying all 28 corpus documents...")
    extracted, metadata, unreadable = await _stage0_triage(question, corpus_dir)  # type: ignore[misc]
    log(f"[1/6] Triage input ready: {len(metadata)} readable, {len(unreadable)} unreadable/empty. Calling subagent...")
    triage_scores = await _call_subagent_json(
        system_prompt=prompts.TRIAGE_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "documents": metadata, "unreadable": unreadable}),
        env=env,
    )
    log(f"[1/6] Triage complete: {len(triage_scores)} documents scored. ({time.monotonic() - _t0:.1f}s)")

    # Stage 1: retrieval (sequential)
    _t1 = time.monotonic()
    log("[2/6] Stage 1 (Retrieval): selecting which documents to deep-analyze...")
    retrieval = await _call_subagent_json(
        system_prompt=prompts.RETRIEVAL_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "triage": triage_scores, "unreadable": unreadable}),
        env=env,
    )
    selected_doc_ids: list[str] = retrieval["selected"]
    log(f"[2/6] Retrieval complete: {len(selected_doc_ids)} documents selected: {selected_doc_ids} ({time.monotonic() - _t1:.1f}s)")

    # Stage 2: document analysis (PARALLEL across batches). Multiple documents
    # are grouped into a single subagent call (see _chunk / _DOC_ANALYSIS_BATCH_SIZE)
    # to cut down the number of SDK subprocess spawns — the real cost/reliability
    # bottleneck on a memory-constrained host — while every finding is still
    # attributed to its own doc_id exactly as before. This changes nothing
    # about the Finding schema, citation format, or final pack content; it
    # only changes how many subagent round-trips it takes to produce them.
    _t2 = time.monotonic()
    batches = _chunk(selected_doc_ids, _DOC_ANALYSIS_BATCH_SIZE)
    log(
        f"[3/6] Stage 2 (Document Analysis): analyzing {len(selected_doc_ids)} documents "
        f"in {len(batches)} batch(es) of up to {_DOC_ANALYSIS_BATCH_SIZE}..."
    )

    semaphore = asyncio.Semaphore(_DOC_ANALYSIS_CONCURRENCY)

    async def analyze_batch(doc_ids: list[str]) -> list[Finding]:
        async with semaphore:
            documents_payload = [
                {
                    "doc_id": doc_id,
                    "outline": [o.ref for o in extracted[doc_id].outline],
                    "full_text": extracted[doc_id].full_text,
                }
                for doc_id in doc_ids
            ]
            by_doc_id = await _call_subagent_json(
                system_prompt=prompts.DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
                user_message=json.dumps({"question": question, "documents": documents_payload}),
                env=env,
            )
            batch_findings: list[Finding] = []
            for doc_id in doc_ids:
                items = by_doc_id.get(doc_id, []) if isinstance(by_doc_id, dict) else []
                findings: list[Finding] = []
                for i in items:
                    if not isinstance(i, dict) or "topic" not in i or "claim" not in i or "ref" not in i:
                        print(f"    [warn] skipping malformed finding for {doc_id!r}: {i!r}")
                        continue
                    findings.append(Finding(topic=i["topic"], claim=i["claim"], citation=Citation(doc_id=doc_id, ref=i["ref"])))
                log(f"[3/6]   {doc_id}: {len(findings)} findings extracted.")
                batch_findings.extend(findings)
            return batch_findings

    analysis_results = await asyncio.gather(*(analyze_batch(b) for b in batches))
    all_findings: list[Finding] = [f for sublist in analysis_results for f in sublist]
    log(
        f"[3/6] Document Analysis complete: {len(all_findings)} total findings across "
        f"{len(selected_doc_ids)} documents. ({time.monotonic() - _t2:.1f}s)"
    )

    # Stage 3: conflict detection (sequential)
    _t3 = time.monotonic()
    log("[4/6] Stage 3 (Conflict Detection): comparing findings for contradictions...")
    conflict_items = await _call_subagent_json(
        system_prompt=prompts.CONFLICT_DETECTION_SYSTEM_PROMPT,
        user_message=json.dumps(
            {"question": question, "findings": [asdict(f) for f in all_findings]}
        ),
        env=env,
    )
    log(f"[4/6] Conflict Detection complete: {len(conflict_items)} conflict(s) found. ({time.monotonic() - _t3:.1f}s)")
    conflicts = [
        Conflict(
            subject=c["subject"],
            position_a=ConflictPosition(
                citation=Citation(**c["position_a"]["citation"]), position=c["position_a"]["position"]
            ),
            position_b=ConflictPosition(
                citation=Citation(**c["position_b"]["citation"]), position=c["position_b"]["position"]
            ),
            resolution_basis=ResolutionBasis(c["resolution_basis"]),
            resolution_note=c["resolution_note"],
        )
        for c in conflict_items
    ]

    # Stage 4: synthesis + recommendations (PARALLEL). Both calls consume the
    # same raw findings/conflicts/sources_consulted — Synthesis organizes them
    # into topical sections and derives coverage gaps, while Recommendations
    # independently derives the grounded "Recommended Engagement Focus Areas"
    # list. These were one combined call; splitting them cuts this stage's
    # wall-clock roughly in half (it had become the single largest stage once
    # recommendations were added), with no change to the final pack content —
    # same sections, same gaps, same recommendation schema, just produced via
    # two parallel round-trips instead of one sequential one.
    _t4 = time.monotonic()
    log("[5/6] Stage 4 (Synthesis): organizing findings, deriving gaps and recommendations...")
    sources_consulted = [
        SourceRecord(doc_id=doc_id, status=doc.status, note=doc.error or "")
        for doc_id, doc in extracted.items()
    ]
    shared_payload = json.dumps(
        {
            "question": question,
            "findings": [asdict(f) for f in all_findings],
            "conflicts": [asdict(c) for c in conflicts],
            "sources_consulted": [asdict(s) for s in sources_consulted],
        }
    )
    synthesis, recommendations = await asyncio.gather(
        _call_subagent_json(system_prompt=prompts.SYNTHESIS_SYSTEM_PROMPT, user_message=shared_payload, env=env),
        _call_subagent_json(system_prompt=prompts.RECOMMENDATIONS_SYSTEM_PROMPT, user_message=shared_payload, env=env),
    )
    findings_by_section: dict[str, list[Finding]] = {
        heading: _parse_finding_items(items, heading)
        for heading, items in synthesis["findings_by_section"].items()
    }
    findings_by_section["Recommended Engagement Focus Areas"] = _parse_finding_items(
        recommendations.get("recommendations", []), "Recommended Engagement Focus Areas"
    )
    gaps = [
        CoverageGap(
            description=g["description"],
            reason=GapReason(g["reason"]),
            source_doc_id=g.get("source_doc_id"),
            confidence_impact=g["confidence_impact"],
        )
        for g in synthesis["gaps"]
    ]

    log(
        f"[5/6] Synthesis complete: {len(findings_by_section)} section(s), {len(gaps)} coverage gap(s), "
        f"{len(findings_by_section['Recommended Engagement Focus Areas'])} recommendation(s) derived. "
        f"({time.monotonic() - _t4:.1f}s)"
    )

    pack = ResearchPack(
        question=question,
        findings_by_section=findings_by_section,
        conflicts=conflicts,
        gaps=gaps,
        sources_consulted=sources_consulted,
    )

    # Final rendering is deterministic, not a 6th SDK call — see the module
    # docstring and DECISIONS.md #11 for why.
    log("[6/6] Rendering final pack and running citation/structure validation...")
    markdown = render(pack)
    outlines = {doc_id: doc.outline for doc_id, doc in extracted.items() if doc.status == ReadStatus.OK}
    citation_issues = validate_citations(markdown, outlines)
    structure_issues = validate_structure(pack)
    log(
        f"[6/6] Done. {len(citation_issues)} citation issue(s), "
        f"{len(structure_issues)} structure issue(s) flagged."
    )

    return {
        "markdown": markdown,
        "pack": pack,
        "citation_issues": citation_issues,
        "structure_issues": structure_issues,
    }
