"""Agent SDK tool + env wiring.

Imports of `claude_agent_sdk` are deferred into function bodies so this module
(and anything that imports it) stays importable in environments/tests that
don't have the SDK installed — only `run_research`'s actual execution path
needs it.
"""
from __future__ import annotations

import os
from typing import Any

from ..extraction import extract_document
from ..manifest import all_doc_ids
from ..models import ReadStatus


def read_corpus_document_impl(doc_id: str, corpus_dir: str) -> dict[str, Any]:
    """Plain-Python implementation, reused directly by tests and by the
    SDK tool wrapper below."""
    doc = extract_document(doc_id, corpus_dir)
    return {
        "doc_id": doc.doc_id,
        "status": doc.status.value,
        "error": doc.error,
        "outline": [{"ref": o.ref, "preview": o.preview} for o in doc.outline],
        "full_text": doc.full_text,
    }


def build_read_corpus_document_tool(corpus_dir: str):
    """Returns an SDK `@tool`-decorated function bound to `corpus_dir`.

    Deferred import of claude_agent_sdk — only needed when actually wiring up
    a live run.
    """
    from claude_agent_sdk import tool  # type: ignore

    @tool(
        "read_corpus_document",
        "Read one document from the fixed Meridian corpus by its DOC-ID "
        "(e.g. 'CL-05', 'EX-07', 'PV-06') and return its extracted text plus "
        "an outline of citable section/heading/sheet references. Valid "
        "DOC-IDs are listed in the corpus manifest.",
        {"doc_id": str},
    )
    async def read_corpus_document(args: dict[str, Any]) -> dict[str, Any]:
        doc_id = args["doc_id"]
        if doc_id not in all_doc_ids():
            return {
                "content": [
                    {"type": "text", "text": f"'{doc_id}' is not a valid corpus DOC-ID."}
                ],
                "isError": True,
            }
        result = read_corpus_document_impl(doc_id, corpus_dir)
        return {"content": [{"type": "text", "text": _format_for_model(result)}]}

    return read_corpus_document


def _format_for_model(result: dict[str, Any]) -> str:
    if result["status"] != ReadStatus.OK.value:
        return f"DOC-ID {result['doc_id']}: status={result['status']} error={result.get('error')}"
    outline_lines = "\n".join(f"- {o['ref']}" for o in result["outline"])
    return (
        f"DOC-ID {result['doc_id']} (status: ok)\n\n"
        f"OUTLINE (cite these exact labels):\n{outline_lines}\n\n"
        f"FULL TEXT:\n{result['full_text']}"
    )


def atlas_env_from_dotenv() -> dict[str, str]:
    """Builds the ClaudeAgentOptions(env=...) dict for the Atlas gateway, per
    project memory `project_hackathon_atlas_auth`. Fetches a fresh Entra
    bearer token once per process launch — revisit with `apiKeyHelper`
    rotation if a single run risks outliving the token lifetime.
    """
    from azure.identity import InteractiveBrowserCredential  # type: ignore
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(override=True)
    client_id = os.environ["CLIENT_ID"]
    tenant_id = os.environ["TENANT_ID"]
    token_scope = os.environ["TOKEN_SCOPE"]
    subscription_key = os.environ["MSF_SUBSCRIPTION_KEY"]
    base_url = os.environ["ANTHROPIC_BASE_URL"]
    auth_type = os.environ.get("AUTHENTICATION_TYPE_VALUE", "EntraID")
    model = os.environ["ANTHROPIC_MODEL"]

    credential = InteractiveBrowserCredential(client_id=client_id, tenant_id=tenant_id)
    bearer_token = credential.get_token(token_scope).token

    return {
        "ANTHROPIC_BASE_URL": base_url.rstrip("/"),
        "ANTHROPIC_AUTH_TOKEN": bearer_token,
        "ANTHROPIC_CUSTOM_HEADERS": (
            f"MSF-Subscription-Key: {subscription_key}\nAtlasAuthType: {auth_type}"
        ),
        "ANTHROPIC_MODEL": model,
        # Deliberately never set ANTHROPIC_API_KEY here: if both are present
        # the CLI prefers ANTHROPIC_API_KEY and silently bypasses the gateway.
    }
