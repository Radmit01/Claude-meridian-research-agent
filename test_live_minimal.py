"""Manual live test of the Claude Agent SDK + Atlas wiring.

This is deliberately NOT part of tests/ (which must run with no API key and
no network access per the hackathon brief). Run it by hand:

    python test_live_minimal.py

It does two things, in order:
  1. A trivial no-tool call to the Agent SDK, to prove ClaudeAgentOptions +
     the Atlas env wiring actually reach a live model and a text response
     comes back correctly (exercises the AssistantMessage/TextBlock fix).
  2. A call WITH the real read_corpus_document tool, asking the model to
     read CL-01 (a real corpus file) and report back a specific fact from
     it, to prove tool-based delegation works end to end (parent -> subagent
     -> tool -> real extracted text -> model's answer).

A browser window will open for Entra login the first time atlas_env_from_dotenv()
runs (or prints a device code if AUTH_METHOD=device_code is set in .env).
"""
from __future__ import annotations

import asyncio

from src.agents.tools import atlas_env_from_dotenv
from src.coordinator import _call_subagent


async def main() -> None:
    print("[1/4] Building Atlas env (Entra login may open a browser now)...")
    env = atlas_env_from_dotenv()
    print("[1/4] Env built successfully.")

    print("[2/4] Calling a trivial subagent with no tools...")
    reply = await _call_subagent(
        system_prompt="You are a test agent. Reply with exactly one word.",
        user_message="Reply with exactly one word: PONG",
        env=env,
    )
    print(f"[2/4] Reply: {reply!r}")
    if "PONG" not in reply:
        print("    WARNING: expected 'PONG' in the reply but did not find it.")
    else:
        print("    OK: no-tool minimal agent loop works.")

    print("[3/4] Calling a subagent WITH the real corpus read tool (doc_id=CL-01)...")
    reply_with_tool = await _call_subagent(
        system_prompt=(
            "You are a document retrieval test agent. You have exactly one "
            "tool, read_corpus_document. Call it with doc_id='CL-01'. Then, "
            "using only the text it returns, report the Group's total assets "
            "under administration figure at 31 December 2025, and nothing else."
        ),
        user_message="Read CL-01 and report the requested figure.",
        env=env,
        corpus_dir="Corpus",
    )
    print(f"[3/4] Reply: {reply_with_tool!r}")
    if "91.4" in reply_with_tool:
        print("    OK: tool-based subagent delegation works (correct figure retrieved).")
    else:
        print("    WARNING: expected figure 'GBP 91.4 billion' not found in reply — inspect manually.")

    print("[4/4] All live checks completed without raising.")


if __name__ == "__main__":
    asyncio.run(main())
