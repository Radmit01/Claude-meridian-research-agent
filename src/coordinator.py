"""run_research(question) — the single entry point required by the brief.

Orchestration is explicit Python, not an LLM-driven delegation loop: the
pipeline topology (sequential triage -> retrieval -> parallel doc analysis ->
sequential conflict detection -> synthesis -> drafting) is fixed and coded
here, while the actual reasoning at each stage is delegated to the Claude
Agent SDK via `_call_subagent`, using the role-specific prompts in
`agents/prompts.py`. This keeps the DAG inspectable/testable independent of
model behavior, while still using the Agent SDK as the orchestration layer
for every reasoning step, per the hard constraint in the brief.

NOTE: this is the orchestration skeleton. `_call_subagent` is the one seam
that actually talks to the SDK/Atlas gateway; everything else (manifest,
extraction, citation validation, pack rendering) is plain Python and already
covered by tests that do not require live API access. Live end-to-end wiring
is blocked on resolving the Atlas 401 (see project memory
`project_hackathon_atlas_auth`) and has not been exercised against a real
model yet.
"""
from __future__ import annotations

import asyncio
import json
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
    )

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


async def _stage0_triage(question: str, corpus_dir: str) -> tuple[dict[str, ExtractedDocument], list[dict]]:
    extracted: dict[str, ExtractedDocument] = {
        doc_id: extract_document(doc_id, corpus_dir) for doc_id in all_doc_ids()
    }
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


async def run_research(question: str, corpus_dir: str) -> dict[str, Any]:
    env = atlas_env_from_dotenv()

    # Stage 0: triage (sequential, metadata-only, single pass)
    extracted, metadata, unreadable = await _stage0_triage(question, corpus_dir)  # type: ignore[misc]
    triage_response = await _call_subagent(
        system_prompt=prompts.TRIAGE_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "documents": metadata, "unreadable": unreadable}),
        env=env,
    )
    triage_scores = json.loads(triage_response)

    # Stage 1: retrieval (sequential)
    retrieval_response = await _call_subagent(
        system_prompt=prompts.RETRIEVAL_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "triage": triage_scores, "unreadable": unreadable}),
        env=env,
    )
    retrieval = json.loads(retrieval_response)
    selected_doc_ids: list[str] = retrieval["selected"]

    # Stage 2: document analysis (PARALLEL — genuinely independent, one doc per call)
    async def analyze_one(doc_id: str) -> list[Finding]:
        doc = extracted[doc_id]
        response = await _call_subagent(
            system_prompt=prompts.DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
            user_message=json.dumps(
                {
                    "question": question,
                    "doc_id": doc_id,
                    "outline": [o.ref for o in doc.outline],
                    "full_text": doc.full_text,
                }
            ),
            env=env,
        )
        items = json.loads(response)
        return [
            Finding(topic=i["topic"], claim=i["claim"], citation=Citation(doc_id=doc_id, ref=i["ref"]))
            for i in items
        ]

    analysis_results = await asyncio.gather(*(analyze_one(d) for d in selected_doc_ids))
    all_findings: list[Finding] = [f for sublist in analysis_results for f in sublist]

    # Stage 3: conflict detection (sequential)
    conflict_response = await _call_subagent(
        system_prompt=prompts.CONFLICT_DETECTION_SYSTEM_PROMPT,
        user_message=json.dumps(
            {"question": question, "findings": [asdict(f) for f in all_findings]}
        ),
        env=env,
    )
    conflict_items = json.loads(conflict_response)
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

    # Stage 4: synthesis (sequential)
    sources_consulted = [
        SourceRecord(doc_id=doc_id, status=doc.status, note=doc.error or "")
        for doc_id, doc in extracted.items()
    ]
    synthesis_response = await _call_subagent(
        system_prompt=prompts.SYNTHESIS_SYSTEM_PROMPT,
        user_message=json.dumps(
            {
                "question": question,
                "findings": [asdict(f) for f in all_findings],
                "conflicts": [asdict(c) for c in conflicts],
                "sources_consulted": [asdict(s) for s in sources_consulted],
            }
        ),
        env=env,
    )
    synthesis = json.loads(synthesis_response)
    findings_by_section: dict[str, list[Finding]] = {}
    for heading, items in synthesis["findings_by_section"].items():
        findings_by_section[heading] = [
            Finding(topic=i["topic"], claim=i["claim"], citation=Citation(**i["citation"]))
            for i in items
        ]
    gaps = [
        CoverageGap(
            description=g["description"],
            reason=GapReason(g["reason"]),
            source_doc_id=g.get("source_doc_id"),
            confidence_impact=g["confidence_impact"],
        )
        for g in synthesis["gaps"]
    ]

    pack = ResearchPack(
        question=question,
        findings_by_section=findings_by_section,
        conflicts=conflicts,
        gaps=gaps,
        sources_consulted=sources_consulted,
    )

    # Stage 5: drafting (sequential) — produces prose; renderer still enforces structure
    await _call_subagent(
        system_prompt=prompts.DRAFTING_SYSTEM_PROMPT,
        user_message=json.dumps({"pack": "see synthesis output above"}),
        env=env,
    )

    markdown = render(pack)
    outlines = {doc_id: doc.outline for doc_id, doc in extracted.items() if doc.status == ReadStatus.OK}
    citation_issues = validate_citations(markdown, outlines)
    structure_issues = validate_structure(pack)

    return {
        "markdown": markdown,
        "pack": pack,
        "citation_issues": citation_issues,
        "structure_issues": structure_issues,
    }
