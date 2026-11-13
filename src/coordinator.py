
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
named roles plus three more: Triage + Retrieval together implement Search,
now issued as ONE subagent call (DECISIONS.md #22) since Retrieval never
needed a second round-trip once Triage's scores exist — a BM25 score/rank
(src/ranking.py, stdlib only, DECISIONS.md #22) is given as a selection
hint, never as a filter. Document Analysis (batched, parallel — DECISIONS.md
#13/#20), Conflict Detection (an added role — DECISIONS.md #3), Synthesis +
Recommendations (split from one combined call for parallelism —
DECISIONS.md #13), and Drafting.

Conflict Detection, Synthesis, and Recommendations reference findings by a
stable integer id rather than re-emitting each finding's topic/claim/
citation (DECISIONS.md #23) — the model sees ids plus free-text (subject,
position wording, resolution notes, recommendation claims), and the
coordinator looks up every citation from the referenced finding afterward.
This both cuts Synthesis's output tokens (previously the dominant cost for
a broad question with 100+ findings) and makes citation fabrication
structurally impossible rather than just prompt-discouraged (DECISIONS.md
#14, the PV-06 fix, is now enforced by code, not only by instruction).

Drafting is deliberately scoped the same way for prose: it only ever sees
and returns {id, topic, claim} tuples for each finding — never citations —
so the model has no way to invent, corrupt, or reformat a citation. The
deterministic renderer (`pack_renderer.render()`) still enforces the
mandatory 4-section structure, exact required sentences, and citation
format on top of whatever Drafting produces, regardless of its output. See
DECISIONS.md #11 for why this scope was chosen (an earlier prototype called
a Drafting subagent and discarded its output entirely; this version
actually uses it, with its blast radius limited to prose only).

`_call_subagent` is the one seam that actually talks to the SDK/Atlas
gateway; it has been verified live (see `test_live_minimal.py`), including
real tool-based delegation.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import math
import os
import re
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
from .ranking import build_index, score

# Per-run call-stats collector (DECISIONS.md #17). Set fresh at the top of
# every run_research() call; _call_subagent appends one entry per subagent
# call if a collector is active. A ContextVar rather than a module global so
# concurrent run_research() calls (see --parallel in run_common.py) each get
# their own isolated list, not a shared/interleaved one.
_call_stats_var: contextvars.ContextVar[list] = contextvars.ContextVar("call_stats")

# Process-wide concurrency cap (DECISIONS.md #20), shared by Document
# Analysis and Drafting via ONE semaphore object rather than one per stage,
# so --parallel mode (multiple run_research() calls at once) can't exceed
# this cap in aggregate — each question's stages contend for the same
# slots instead of each getting its own separate allowance.
_MAX_CONCURRENT_SUBAGENTS = int(os.environ.get("MAX_CONCURRENT_SUBAGENTS", "4"))
_subagent_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SUBAGENTS)

# Optional model tiering (DECISIONS.md #15 and #21): unset by default, so
# the default behavior is unchanged (every stage uses ANTHROPIC_MODEL).
# When set, routes Planning and Drafting — the two stages that don't need
# the same depth of reasoning as Document Analysis/Conflict Detection/
# Synthesis/Recommendations — to a different (typically faster/cheaper)
# model. DECISIONS.md #15 found no measured speed benefit from doing this
# with Haiku on this Atlas gateway, and one run hit transient
# tier-specific "model unavailable" errors that cost more in retry backoff
# than any latency it saved — the plumbing is kept and documented honestly
# rather than deleted, since a different gateway/tenant may behave
# differently, but leaving this unset is the recommended default.
_FAST_MODEL = os.environ.get("CLAUDE_MODEL_FAST") or None


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


def _repair_json(text: str) -> str:
    """Best-effort repair for a JSON response truncated mid-generation
    (DECISIONS.md #18). Strips markdown fences (same as _parse_json_response),
    then — only if parsing still fails — trims back to the last comma that
    sits outside any open string/bracket and closes whatever brackets are
    still open at that point. This only fixes a response cut off cleanly at
    the end; anything malformed in the middle still falls through to
    _call_subagent_json's regenerate-the-whole-call fallback.

    Tries candidates from least to most destructive, validating each with an
    actual json.loads rather than guessing: first just close whatever
    string/brackets are still open at the end (preserves every complete
    field — correct when the response was simply cut off after its last
    closing brace), then, only if that still doesn't parse, trim back to
    progressively earlier commas (dropping an incomplete trailing element)
    until one produces valid JSON. A dropped-but-incomplete trailing item
    (e.g. missing its "claim" key) is left for the existing per-item
    defensive parsing elsewhere to filter out, not something this function
    needs to clean up itself."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        json.loads(stripped)
        return stripped  # already valid; nothing to repair
    except json.JSONDecodeError:
        pass

    stack: list[str] = []
    in_string = False
    escape = False
    comma_snapshots: list[tuple[int, list[str]]] = []
    for idx, ch in enumerate(stripped):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == "," and stack:
            comma_snapshots.append((idx, list(stack)))

    candidates: list[str] = []
    closers = "".join(reversed(stack))
    if in_string:
        candidates.append(stripped + '"' + closers)
    if stack:
        candidates.append(stripped + closers)
    for pos, snapshot in reversed(comma_snapshots):
        candidates.append(stripped[:pos] + "".join(reversed(snapshot)))

    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return stripped  # nothing worked; caller's json.loads will raise as before


_JSON_RETRY_MAX_ATTEMPTS = 3


async def _call_subagent_json(
    *, system_prompt: str, user_message: str, env: dict[str, str], label: str = "unlabeled", model: str | None = None
) -> Any:
    """Common wrapper used by every JSON-contract subagent call: calls
    _call_subagent then parses the result as JSON. On a parse failure, first
    tries a cheap local repair (_repair_json) — a response truncated cleanly
    at the end is often fixable without paying for another subprocess spawn
    + model call — and only regenerates the WHOLE call (not just the parse)
    if the repair doesn't produce valid JSON either. Regenerating is
    distinct from _call_subagent's own retries, which handle subprocess-level
    crashes rather than bad model output."""
    last_error: Exception | None = None
    for attempt in range(1, _JSON_RETRY_MAX_ATTEMPTS + 1):
        response = await _call_subagent(
            system_prompt=system_prompt, user_message=user_message, env=env, label=label, model=model
        )
        try:
            return _parse_json_response(response)
        except json.JSONDecodeError as exc:
            try:
                repaired = _parse_json_response(_repair_json(response))
                print(f"    [repair] {label}: truncated JSON repaired locally, no regenerate needed.")
                return repaired
            except json.JSONDecodeError:
                pass
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

# Batching for Stage 2 (Document Analysis) and Stage 5 (Drafting): grouping
# several items into one subagent call cuts the number of SDK subprocess
# spawns roughly BATCH_SIZE-fold versus one call per item — the dominant
# cost/reliability bottleneck on a memory-constrained host is spawning the
# CLI subprocess, not model latency or per-call token volume. Batch size is
# now computed per run (see _compute_batch_size, DECISIONS.md #20) rather
# than fixed, so the number of batches matches the configured concurrency —
# every batch runs in one wave instead of several sequential rounds,
# whenever the item count fits within concurrency * max_size.
#
# Document Analysis and Drafting use DIFFERENT max_size values, not the
# same clamp, because their per-item payload sizes are not comparable: a
# Document Analysis item carries a full document's extracted text, while a
# Drafting item is a tiny {id, topic, claim} triple with no document text
# and no citation (DECISIONS.md #16). Measured live: capping Drafting's
# batch at the same 8-item ceiling as Document Analysis pushed a 114-finding
# Q1 run from 1 wave to 4 sequential rounds (127.9s instead of ~20-55s) —
# a real regression, not a theoretical one, so Drafting gets a much higher
# ceiling to restore the "fits in one wave" property at realistic finding
# counts (DECISIONS.md #20 records this as a deliberate, measured deviation
# from applying one formula uniformly to both stages).
_BATCH_SIZE_MIN = 3
_DOC_ANALYSIS_BATCH_SIZE_MAX = 8
_DRAFTING_BATCH_SIZE_MAX = 60


def _compute_batch_size(num_items: int, concurrency: int, max_size: int = _DOC_ANALYSIS_BATCH_SIZE_MAX) -> int:
    if num_items <= 0:
        return _BATCH_SIZE_MIN
    ideal = math.ceil(num_items / max(concurrency, 1))
    return max(_BATCH_SIZE_MIN, min(max_size, ideal))


# Dev-only Document Analysis cache (DECISIONS.md #24) — OFF unless
# RESEARCH_CACHE=1 is set. Never used for submission packs or the judged
# demo (see README.md): it exists purely to speed up local iteration on
# prompts/batching without re-paying for every document's findings on
# every test run. Keyed by (corpus file's own SHA-256, question,
# prompts.PROMPT_VERSION) so a changed document, question, or prompt
# contract can never silently serve a stale cached result.
_CACHE_ENABLED = os.environ.get("RESEARCH_CACHE") == "1"
_CACHE_DIR = os.path.join("output", ".cache", "analysis")


def _doc_file_sha256(corpus_dir: str, doc_id: str) -> str | None:
    """Hashes the actual corpus file's bytes. Returns None (never caches)
    if the file can't be uniquely located — correctness over a cache hit."""
    import glob

    from .manifest import get as get_manifest_entry

    try:
        entry = get_manifest_entry(doc_id)
    except KeyError:
        return None
    matches = glob.glob(os.path.join(corpus_dir, entry.filename_glob))
    if len(matches) != 1:
        return None
    with open(matches[0], "rb") as f:
        import hashlib

        return hashlib.sha256(f.read()).hexdigest()


def _analysis_cache_key(corpus_dir: str, doc_id: str, question: str) -> str | None:
    file_hash = _doc_file_sha256(corpus_dir, doc_id)
    if file_hash is None:
        return None
    import hashlib

    raw = f"{file_hash}:{question}:{prompts.PROMPT_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_cached_findings(doc_id: str, cache_key: str) -> list[Finding] | None:
    path = os.path.join(_CACHE_DIR, f"{cache_key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        return [
            Finding(topic=i["topic"], claim=i["claim"], citation=Citation(doc_id=doc_id, ref=i["ref"]))
            for i in items
        ]
    except Exception:
        return None  # any cache-read problem just falls back to a live call


def _save_cached_findings(cache_key: str, findings: list[Finding]) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        items = [{"topic": f.topic, "claim": f.claim, "ref": f.citation.ref} for f in findings]
        with open(os.path.join(_CACHE_DIR, f"{cache_key}.json"), "w", encoding="utf-8") as f:
            json.dump(items, f)
    except Exception:
        pass  # caching is a dev convenience; never fail a run over it


_SUBAGENT_RETRY_BACKOFF_CAP_S = 15


async def _call_subagent(
    *,
    system_prompt: str,
    user_message: str,
    env: dict[str, str],
    corpus_dir: str | None = None,
    label: str = "unlabeled",
    model: str | None = None,
) -> str:
    """The one seam that talks to the Claude Agent SDK. Returns the
    subagent's final text response. Logs a `[timing]` line and, if a
    collector is active (see `_call_stats_var`), records spawn/total time,
    token usage, and cost for this call — DECISIONS.md #17. `model`
    overrides the gateway's configured default (ANTHROPIC_MODEL) for this
    call only — see `_FAST_MODEL`/DECISIONS.md #21; leave unset (the
    default) to use whatever ANTHROPIC_MODEL specifies."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query  # type: ignore

    allowed_tools = []
    mcp_servers: dict[str, Any] = {}
    max_turns: int | None = None
    if corpus_dir is not None:
        from claude_agent_sdk import create_sdk_mcp_server  # type: ignore

        read_tool = build_read_corpus_document_tool(corpus_dir)
        server = create_sdk_mcp_server(name="corpus", version="1.0.0", tools=[read_tool])
        mcp_servers = {"corpus": server}
        allowed_tools = ["mcp__corpus__read_corpus_document"]
    else:
        # Every non-tool call in this pipeline is single-shot JSON generation
        # with nothing to act on between turns, so more than one turn is
        # never needed. Left unset on the tool-use path above: calling the
        # corpus-read tool and then answering from its result genuinely
        # takes two turns, and that live-tool-delegation path is what
        # test_live_minimal.py demonstrates (DECISIONS.md #19).
        max_turns = 1

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        env=env,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        load_timeout_ms=_SUBAGENT_LOAD_TIMEOUT_MS,
        max_turns=max_turns,
        model=model,
    )

    for attempt in range(1, _SUBAGENT_MAX_ATTEMPTS + 1):
        try:
            # AssistantMessage.content is a list of content blocks (TextBlock,
            # ThinkingBlock, ToolUseBlock, ToolResultBlock); only TextBlock carries
            # the model's text output. There is no flat `.text` on the message
            # itself — that was an earlier, incorrect assumption that silently
            # returned "" on every call. See project memory for detail.
            chunks: list[str] = []
            start = time.monotonic()
            first_message_at: float | None = None
            usage: dict[str, Any] | None = None
            cost_usd: float | None = None
            async for message in query(prompt=user_message, options=options):
                if first_message_at is None:
                    first_message_at = time.monotonic()
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)
                elif isinstance(message, ResultMessage):
                    usage = message.usage
                    cost_usd = message.total_cost_usd
            total_s = time.monotonic() - start
            spawn_s = (first_message_at - start) if first_message_at is not None else total_s
            text = "".join(chunks)
            # "input_tokens" alone badly undercounts real usage: most of a
            # call's input lands in cache_creation/cache_read instead (the
            # system prompt is identical across calls within a run, so the
            # CLI caches it) — verified live: a trivial call reported
            # input_tokens=2 but cache_creation_input_tokens=22074. Sum all
            # three for a figure that actually reflects what was billed;
            # total_cost_usd (summed separately below) was already correct
            # either way, since the SDK computes it from the full usage.
            in_tok = (
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
                if usage
                else None
            )
            out_tok = usage.get("output_tokens") if usage else None
            cost_str = f"${cost_usd:.4f}" if cost_usd is not None else "$?"
            print(
                f"    [timing] {label} spawn={spawn_s:.1f}s total={total_s:.1f}s "
                f"in_tok={in_tok} out_tok={out_tok} cost={cost_str}"
            )
            stats = _call_stats_var.get(None)
            if stats is not None:
                stats.append(
                    {
                        "label": label,
                        "spawn_s": spawn_s,
                        "total_s": total_s,
                        "chars": len(text),
                        "in_tok": in_tok,
                        "out_tok": out_tok,
                        "cost_usd": cost_usd,
                    }
                )
            return text
        except Exception as exc:
            if attempt == _SUBAGENT_MAX_ATTEMPTS:
                raise
            print(
                f"    [retry] subagent call failed (attempt {attempt}/{_SUBAGENT_MAX_ATTEMPTS}): "
                f"{type(exc).__name__}: {exc}. Retrying..."
            )
            await asyncio.sleep(min(5 * attempt, _SUBAGENT_RETRY_BACKOFF_CAP_S))
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


async def run_research(question: str, corpus_dir: str = "Corpus", verbose: bool = True) -> dict[str, Any]:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    call_stats: list[dict[str, Any]] = []
    _call_stats_var.set(call_stats)

    log("[0/7] Building Atlas env (Entra login may open a browser now)...")
    env = atlas_env_from_dotenv()
    log("[0/7] Env ready.")

    # Stage 0+1: planning (ONE subagent call implementing both halves of the
    # Search role). Triage classifies all 28 docs; Retrieval selects a
    # subset from Triage's scores — merged into one call since Retrieval
    # never needed a second round-trip once those scores exist (DECISIONS.md
    # #22). A BM25 keyword-overlap score/rank (src/ranking.py, stdlib only)
    # is given to the model as a hint only — it never excludes a document
    # itself, the model makes the actual selection. Both [1/7] and [2/7]
    # are still logged separately (run_manager.py's dashboard parses this
    # exact format) even though one call now does both jobs, so Retrieval's
    # own duration below is near-zero by design — the real cost shows up in
    # Triage's duration instead.
    _t0 = time.monotonic()
    log("[1/7] Stage 0 (Triage): opening and classifying all 28 corpus documents...")
    extracted, metadata, unreadable = await _stage0_triage(question, corpus_dir)  # type: ignore[misc]

    rank_index = build_index({m["doc_id"]: extracted[m["doc_id"]].full_text for m in metadata})
    bm25_scores = score(question, rank_index)
    ranked_doc_ids = sorted(bm25_scores, key=lambda d: bm25_scores[d], reverse=True)
    bm25_rank = {doc_id: i + 1 for i, doc_id in enumerate(ranked_doc_ids)}
    for m in metadata:
        m["bm25_score"] = round(bm25_scores.get(m["doc_id"], 0.0), 3)
        m["bm25_rank"] = bm25_rank.get(m["doc_id"])

    log(f"[1/7] Triage input ready: {len(metadata)} readable, {len(unreadable)} unreadable/empty. Calling subagent...")
    planning = await _call_subagent_json(
        system_prompt=prompts.PLANNING_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "documents": metadata, "unreadable": unreadable}),
        env=env,
        label="planning",
    )
    sub_questions: list[str] = planning.get("sub_questions") or []
    triage_scores = planning.get("triage") or []
    log(f"[1/7] Triage complete: {len(triage_scores)} documents scored. ({time.monotonic() - _t0:.1f}s)")

    _t1 = time.monotonic()
    log("[2/7] Stage 1 (Retrieval): selecting which documents to deep-analyze...")
    selected_doc_ids: list[str] = planning.get("selected") or []
    log(
        f"[2/7] Retrieval complete: {len(selected_doc_ids)} documents selected: "
        f"{selected_doc_ids} ({time.monotonic() - _t1:.1f}s)"
    )
    if sub_questions:
        log(f"      Sub-questions: {sub_questions}")

    # Stage 2: document analysis (PARALLEL across batches). Multiple
    # documents are grouped into a single subagent call to cut down the
    # number of SDK subprocess spawns — the real cost/reliability
    # bottleneck on a memory-constrained host — while every finding is
    # still attributed to its own doc_id exactly as before. Batch size is
    # computed so all batches fit in one wave at the configured concurrency
    # (DECISIONS.md #20); this changes nothing about the Finding schema,
    # citation format, or final pack content, only how many round-trips
    # produce them.
    _t2 = time.monotonic()
    doc_batch_size = _compute_batch_size(len(selected_doc_ids), _MAX_CONCURRENT_SUBAGENTS)
    batches = _chunk(selected_doc_ids, doc_batch_size)
    log(
        f"[3/7] Stage 2 (Document Analysis): analyzing {len(selected_doc_ids)} documents "
        f"in {len(batches)} batch(es) of up to {doc_batch_size}..."
    )

    async def analyze_batch(doc_ids: list[str], batch_idx: int) -> list[Finding]:
        # Dev-only cache check (RESEARCH_CACHE=1 only — off by default, never
        # used for submission packs or the demo, see README.md). A cache hit
        # for a doc skips sending it to the model at all; only uncached docs
        # go into this batch's subagent call.
        cache_keys: dict[str, str] = {}
        batch_findings: list[Finding] = []
        uncached_doc_ids: list[str] = list(doc_ids)
        if _CACHE_ENABLED:
            uncached_doc_ids = []
            for doc_id in doc_ids:
                key = _analysis_cache_key(corpus_dir, doc_id, question)
                hit = _load_cached_findings(doc_id, key) if key else None
                if hit is not None:
                    log(f"[3/7]   {doc_id}: {len(hit)} findings (cached).")
                    batch_findings.extend(hit)
                else:
                    uncached_doc_ids.append(doc_id)
                    if key:
                        cache_keys[doc_id] = key

        if not uncached_doc_ids:
            return batch_findings

        async with _subagent_semaphore:
            documents_payload = [
                {
                    "doc_id": doc_id,
                    "outline": [o.ref for o in extracted[doc_id].outline],
                    "full_text": extracted[doc_id].full_text,
                }
                for doc_id in uncached_doc_ids
            ]
            by_doc_id = await _call_subagent_json(
                system_prompt=prompts.DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
                user_message=json.dumps(
                    {"question": question, "sub_questions": sub_questions, "documents": documents_payload}
                ),
                env=env,
                label=f"document_analysis[{batch_idx}]",
            )
            for doc_id in uncached_doc_ids:
                items = by_doc_id.get(doc_id, []) if isinstance(by_doc_id, dict) else []
                findings: list[Finding] = []
                for i in items:
                    if not isinstance(i, dict) or "topic" not in i or "claim" not in i or "ref" not in i:
                        print(f"    [warn] skipping malformed finding for {doc_id!r}: {i!r}")
                        continue
                    findings.append(Finding(topic=i["topic"], claim=i["claim"], citation=Citation(doc_id=doc_id, ref=i["ref"])))
                log(f"[3/7]   {doc_id}: {len(findings)} findings extracted.")
                batch_findings.extend(findings)
                if doc_id in cache_keys:
                    _save_cached_findings(cache_keys[doc_id], findings)
        return batch_findings

    analysis_results = await asyncio.gather(*(analyze_batch(b, idx) for idx, b in enumerate(batches)))
    all_findings: list[Finding] = [f for sublist in analysis_results for f in sublist]
    log(
        f"[3/7] Document Analysis complete: {len(all_findings)} total findings across "
        f"{len(selected_doc_ids)} documents. ({time.monotonic() - _t2:.1f}s)"
    )

    # Every finding gets a stable integer id from here on, used by Conflict
    # Detection, Synthesis, and Recommendations to REFERENCE a finding
    # instead of re-emitting its topic/claim/citation (DECISIONS.md #23):
    # this is what cuts Synthesis's output tokens, previously the dominant
    # cost for broad questions with 100+ findings. Citations/topics are
    # always looked up from this dict afterward, never retyped by a model,
    # which also makes citation fabrication (DECISIONS.md #14) structurally
    # impossible rather than just prompt-discouraged.
    finding_by_id: dict[int, Finding] = dict(enumerate(all_findings))
    findings_payload = [
        {"id": fid, "topic": f.topic, "claim": f.claim, "citation": asdict(f.citation)}
        for fid, f in finding_by_id.items()
    ]

    # Stage 3: conflict detection (sequential)
    _t3 = time.monotonic()
    log("[4/7] Stage 3 (Conflict Detection): comparing findings for contradictions...")
    conflict_items = await _call_subagent_json(
        system_prompt=prompts.CONFLICT_DETECTION_SYSTEM_PROMPT,
        user_message=json.dumps({"question": question, "findings": findings_payload}),
        env=env,
        label="conflict_detection",
    )
    conflicts: list[Conflict] = []
    for c in conflict_items:
        try:
            finding_a = finding_by_id[int(c["position_a_id"])]
            finding_b = finding_by_id[int(c["position_b_id"])]
        except (KeyError, TypeError, ValueError):
            print(f"    [warn] dropping conflict with unknown finding id: {c!r}")
            continue
        conflicts.append(
            Conflict(
                subject=c["subject"],
                position_a=ConflictPosition(citation=finding_a.citation, position=c["position_a_text"]),
                position_b=ConflictPosition(citation=finding_b.citation, position=c["position_b_text"]),
                resolution_basis=ResolutionBasis(c["resolution_basis"]),
                resolution_note=c["resolution_note"],
            )
        )
    log(f"[4/7] Conflict Detection complete: {len(conflicts)} conflict(s) found. ({time.monotonic() - _t3:.1f}s)")

    # Stage 4: synthesis + recommendations (PARALLEL). Both calls consume
    # the same raw findings/conflicts/sources_consulted — Synthesis groups
    # finding ids under sections and derives coverage gaps, while
    # Recommendations independently derives the grounded "Recommended
    # Engagement Focus Areas" list by referencing a finding_id. These were
    # one combined call; splitting them lets both run concurrently instead
    # of sequentially (DECISIONS.md #13).
    _t4 = time.monotonic()
    log("[5/7] Stage 4 (Synthesis): organizing findings, deriving gaps and recommendations...")
    sources_consulted = [
        SourceRecord(doc_id=doc_id, status=doc.status, note=doc.error or "")
        for doc_id, doc in extracted.items()
    ]
    shared_payload = json.dumps(
        {
            "question": question,
            "sub_questions": sub_questions,
            "findings": findings_payload,
            "conflicts": [asdict(c) for c in conflicts],
            "sources_consulted": [asdict(s) for s in sources_consulted],
        }
    )
    synthesis, recommendations = await asyncio.gather(
        _call_subagent_json(
            system_prompt=prompts.SYNTHESIS_SYSTEM_PROMPT, user_message=shared_payload, env=env, label="synthesis"
        ),
        _call_subagent_json(
            system_prompt=prompts.RECOMMENDATIONS_SYSTEM_PROMPT,
            user_message=shared_payload,
            env=env,
            label="recommendations",
        ),
    )

    findings_by_section: dict[str, list[Finding]] = {}
    for heading, ids in (synthesis.get("findings_by_section") or {}).items():
        section_findings: list[Finding] = []
        for raw_id in ids if isinstance(ids, list) else []:
            try:
                section_findings.append(finding_by_id[int(raw_id)])
            except (KeyError, TypeError, ValueError):
                print(f"    [warn] Synthesis referenced unknown finding id {raw_id!r} under {heading!r}; ignored.")
        findings_by_section[heading] = section_findings

    recommendation_findings: list[Finding] = []
    for rec in recommendations.get("recommendations", []):
        if not isinstance(rec, dict) or "finding_id" not in rec or "claim" not in rec or "topic" not in rec:
            print(f"    [warn] skipping malformed recommendation: {rec!r}")
            continue
        try:
            source_finding = finding_by_id[int(rec["finding_id"])]
        except (KeyError, TypeError, ValueError):
            print(f"    [warn] dropping recommendation with unknown finding_id: {rec!r}")
            continue
        recommendation_findings.append(Finding(topic=rec["topic"], claim=rec["claim"], citation=source_finding.citation))
    findings_by_section["Recommended Engagement Focus Areas"] = recommendation_findings

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
        f"{len(recommendation_findings)} recommendation(s) derived. ({time.monotonic() - _t4:.1f}s)"
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
    drafting_batch_size = _compute_batch_size(
        len(drafting_payload), _MAX_CONCURRENT_SUBAGENTS, max_size=_DRAFTING_BATCH_SIZE_MAX
    )
    drafting_batches = _chunk(drafting_payload, drafting_batch_size)
    log(
        f"[6/7] Stage 5 (Drafting): polishing {len(drafting_payload)} finding(s) "
        f"in {len(drafting_batches)} batch(es) of up to {drafting_batch_size}..."
    )

    async def draft_batch(batch: list[dict], batch_idx: int) -> dict[int, str]:
        async with _subagent_semaphore:
            response = await _call_subagent_json(
                system_prompt=prompts.DRAFTING_SYSTEM_PROMPT,
                user_message=json.dumps({"question": question, "findings": batch}),
                env=env,
                label=f"drafting[{batch_idx}]",
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

    drafted_batch_maps = await asyncio.gather(*(draft_batch(b, idx) for idx, b in enumerate(drafting_batches)))
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

    # Per-stage timings + token/cost totals (DECISIONS.md #17) — additive new
    # return keys, every existing key unchanged.
    timings: dict[str, float] = {}
    for entry in call_stats:
        stage_key = entry["label"].split("[")[0]
        timings[stage_key] = timings.get(stage_key, 0.0) + entry["total_s"]
    usage = {
        "total_in_tok": sum(e["in_tok"] or 0 for e in call_stats),
        "total_out_tok": sum(e["out_tok"] or 0 for e in call_stats),
        "total_cost_usd": sum(e["cost_usd"] or 0.0 for e in call_stats),
        "call_count": len(call_stats),
    }

    return {
        "markdown": markdown,
        "pack": pack,
        "citation_issues": citation_issues,
        "structure_issues": structure_issues,
        "sub_questions": sub_questions,
        "timings": timings,
        "usage": usage,
    }
