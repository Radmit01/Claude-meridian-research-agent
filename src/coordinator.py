
"""run_research(question) — the single entry point required by the brief.

Orchestration is explicit Python, not an LLM-driven delegation loop: the
pipeline topology (triage -> retrieval -> parallel document analysis ->
conflict detection -> parallel synthesis+recommendations -> drafting ->
deterministic render) is fixed and coded here, while the actual reasoning at
each stage is delegated to the Claude Agent SDK via `_call_subagent`, using
the role-specific prompts in `agents/prompts.py`. This keeps the DAG
inspectable/testable independent of model behavior, while still using the
Agent SDK as the orchestration layer for every reasoning step, per the hard
constraint in the brief.

7 SDK-delegated subagent roles. The brief names four specific minimum roles
by name — Search, Document Analysis, Synthesis, Drafting — and permits
additional roles for meaningful decomposition. This pipeline covers all four
named roles plus three more: Triage + Retrieval together implement Search
(split because Triage must cheaply classify all 28 documents before
Retrieval selects a subset to deep-analyze — see DECISIONS.md #4), Document
Analysis (batched, parallel — DECISIONS.md #13), Conflict Detection (an
added role — DECISIONS.md #3), Synthesis + Recommendations (split from one
combined call for parallelism — DECISIONS.md #13), and Drafting.

Drafting is deliberately scoped narrowly: it only ever sees and returns
{id, topic, claim} tuples for each finding — never citations — so the model
has no way to invent, corrupt, or reformat a citation. The deterministic
renderer (`pack_renderer.render()`) still enforces the mandatory 4-section
structure, exact required sentences, and citation format on top of whatever
Drafting produces, regardless of its output. See DECISIONS.md #11 for why
this scope was chosen (an earlier prototype called a Drafting subagent and
discarded its output entirely; this version actually uses it, with its
blast radius limited to prose only).

`_call_subagent` is the one seam that actually talks to the SDK/Atlas
gateway; it has been verified live (see `test_live_minimal.py`), including
real tool-based delegation.
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

# Stage 5 (Drafting) batching, same rationale as Stage 2: one call per
# finding would multiply subprocess spawns; one call for ALL findings risks
# a single oversized response (same truncation failure mode Synthesis hit
# before it was split — see DECISIONS.md #13). A fixed batch size keeps each
# call's output bounded regardless of how many findings a given question
# produces.
_DRAFTING_BATCH_SIZE = 25


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


def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    """Common batching helper: splits `items` into fixed-size chunks. Used to
    group multiple documents (Stage 2) or findings (Stage 5 Drafting) into a
    single subagent call, cutting down the number of SDK subprocess spawns —
    the real cost/reliability bottleneck on a memory-constrained host, not
    model latency (see DECISIONS.md)."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _flatten_findings_for_drafting(
    findings_by_section: dict[str, list[Finding]]
) -> tuple[list[dict], list[tuple[str, int]]]:
    """Builds the id-ordered payload sent to Drafting (topic+claim only — no
    citations, so the model has no way to touch them) and a parallel index
    mapping id -> (section heading, position in that section's list), used to
    stitch the drafted text back into the original structure afterward."""
    payload: list[dict] = []
    index: list[tuple[str, int]] = []
    i = 0
    for heading, items in findings_by_section.items():
        for pos, finding in enumerate(items):
            payload.append({"id": i, "topic": finding.topic, "claim": finding.claim})
            index.append((heading, pos))
            i += 1
    return payload, index


def _apply_drafted_claims(
    findings_by_section: dict[str, list[Finding]],
    index: list[tuple[str, int]],
    drafted_claims: dict[int, str],
) -> dict[str, list[Finding]]:
    """Pure, deterministic stitching of Drafting's polished claim text back
    into the original Finding objects. Citations and topics are never sent to
    or returned by the model and always come from the original finding — so
    a Drafting glitch (a missing id, a malformed item, a dropped batch) can
    at worst leave a claim's original wording in place; it can never corrupt
    a citation, drop a finding, duplicate one, or break the mandatory
    structure the renderer and citation validator enforce downstream."""
    result: dict[str, list[Finding]] = {heading: list(items) for heading, items in findings_by_section.items()}
    missing = 0
    for fid, (heading, pos) in enumerate(index):
        original = result[heading][pos]
        new_claim = drafted_claims.get(fid)
        if new_claim is None:
            missing += 1
            continue
        result[heading][pos] = Finding(topic=original.topic, claim=new_claim, citation=original.citation)
    if missing:
        print(f"    [warn] Drafting did not return {missing}/{len(index)} finding(s); kept original claim text for those.")
    return result


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

    log("[0/7] Building Atlas env (Entra login may open a browser now)...")
    env = atlas_env_from_dotenv()
    log("[0/7] Env ready.")

    # Stage 0: triage (sequential, metadata-only, single pass)
    _t0 = time.monotonic()
    log("[1/7] Stage 0 (Triage): opening and classifying all 28 corpus documents...")
    extracted, metadata, unreadable = await _stage0_triage(question, corpus_dir)  # type: ignore[misc]
    log(f"[1/7] Triage input ready: {len(metadata)} readable, {len(unreadable)} unreadable/empty. Calling subagent...")
    triage_scores = await _call_subagent_json(
        system_prompt=prompts.TRIAGE_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "documents": metadata, "unreadable": unreadable}),
        env=env,
    )
    log(f"[1/7] Triage complete: {len(triage_scores)} documents scored. ({time.monotonic() - _t0:.1f}s)")

    # Stage 1: retrieval (sequential)
    _t1 = time.monotonic()
    log("[2/7] Stage 1 (Retrieval): selecting which documents to deep-analyze...")
    retrieval = await _call_subagent_json(
        system_prompt=prompts.RETRIEVAL_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "triage": triage_scores, "unreadable": unreadable}),
        env=env,
    )
    selected_doc_ids: list[str] = retrieval["selected"]
    log(f"[2/7] Retrieval complete: {len(selected_doc_ids)} documents selected: {selected_doc_ids} ({time.monotonic() - _t1:.1f}s)")

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
        f"[3/7] Stage 2 (Document Analysis): analyzing {len(selected_doc_ids)} documents "
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
                log(f"[3/7]   {doc_id}: {len(findings)} findings extracted.")
                batch_findings.extend(findings)
            return batch_findings

    analysis_results = await asyncio.gather(*(analyze_batch(b) for b in batches))
    all_findings: list[Finding] = [f for sublist in analysis_results for f in sublist]
    log(
        f"[3/7] Document Analysis complete: {len(all_findings)} total findings across "
        f"{len(selected_doc_ids)} documents. ({time.monotonic() - _t2:.1f}s)"
    )

    # Stage 3: conflict detection (sequential)
    _t3 = time.monotonic()
    log("[4/7] Stage 3 (Conflict Detection): comparing findings for contradictions...")
    conflict_items = await _call_subagent_json(
        system_prompt=prompts.CONFLICT_DETECTION_SYSTEM_PROMPT,
        user_message=json.dumps(
            {"question": question, "findings": [asdict(f) for f in all_findings]}
        ),
        env=env,
    )
    log(f"[4/7] Conflict Detection complete: {len(conflict_items)} conflict(s) found. ({time.monotonic() - _t3:.1f}s)")
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
    log("[5/7] Stage 4 (Synthesis): organizing findings, deriving gaps and recommendations...")
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
        f"[5/7] Synthesis complete: {len(findings_by_section)} section(s), {len(gaps)} coverage gap(s), "
        f"{len(findings_by_section['Recommended Engagement Focus Areas'])} recommendation(s) derived. "
        f"({time.monotonic() - _t4:.1f}s)"
    )

    # Stage 5: drafting (PARALLEL across batches, same pattern as Stage 2).
    # Rewrites each finding's claim into polished client-facing prose.
    # Citations and topics are never sent to or returned by this subagent —
    # only {id, topic, claim} round-trips — so a Drafting glitch (a dropped
    # batch, a malformed item, a missing id) can at worst leave a claim's
    # original wording in place; it can never corrupt a citation, drop a
    # finding, or break the mandatory structure the renderer and citation
    # validator enforce afterward. See DECISIONS.md #11 for why this scope
    # was chosen and why Drafting is a real, used subagent call here.
    _t5 = time.monotonic()
    drafting_payload, drafting_index = _flatten_findings_for_drafting(findings_by_section)
    drafting_batches = _chunk(drafting_payload, _DRAFTING_BATCH_SIZE)
    log(
        f"[6/7] Stage 5 (Drafting): polishing {len(drafting_payload)} finding(s) "
        f"in {len(drafting_batches)} batch(es) of up to {_DRAFTING_BATCH_SIZE}..."
    )
    drafting_semaphore = asyncio.Semaphore(_DOC_ANALYSIS_CONCURRENCY)

    async def draft_batch(batch: list[dict]) -> dict[int, str]:
        async with drafting_semaphore:
            response = await _call_subagent_json(
                system_prompt=prompts.DRAFTING_SYSTEM_PROMPT,
                user_message=json.dumps({"question": question, "findings": batch}),
                env=env,
            )
            items = response.get("drafted", []) if isinstance(response, dict) else []
            batch_result: dict[int, str] = {}
            for item in items:
                if not isinstance(item, dict) or "id" not in item or "claim" not in item:
                    continue
                try:
                    fid = int(item["id"])
                except (TypeError, ValueError):
                    continue
                if isinstance(item["claim"], str) and item["claim"].strip():
                    batch_result[fid] = item["claim"]
            return batch_result

    drafted_batch_maps = await asyncio.gather(*(draft_batch(b) for b in drafting_batches))
    drafted_claims: dict[int, str] = {}
    for m in drafted_batch_maps:
        drafted_claims.update(m)
    findings_by_section = _apply_drafted_claims(findings_by_section, drafting_index, drafted_claims)
    log(
        f"[6/7] Drafting complete: {len(drafted_claims)}/{len(drafting_payload)} finding(s) redrafted. "
        f"({time.monotonic() - _t5:.1f}s)"
    )

    pack = ResearchPack(
        question=question,
        findings_by_section=findings_by_section,
        conflicts=conflicts,
        gaps=gaps,
        sources_consulted=sources_consulted,
    )

    # Final rendering is deterministic, not an 8th SDK call — it guarantees
    # the mandatory structure/citation format regardless of what Drafting
    # produced. See the module docstring and DECISIONS.md #11.
    log("[7/7] Rendering final pack and running citation/structure validation...")
    markdown = render(pack)
    outlines = {doc_id: doc.outline for doc_id, doc in extracted.items() if doc.status == ReadStatus.OK}
    citation_issues = validate_citations(markdown, outlines)
    structure_issues = validate_structure(pack)
    log(
        f"[7/7] Done. {len(citation_issues)} citation issue(s), "
        f"{len(structure_issues)} structure issue(s) flagged."
    )

    return {
        "markdown": markdown,
        "pack": pack,
        "citation_issues": citation_issues,
        "structure_issues": structure_issues,
    }
