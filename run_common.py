"""Shared runner used by run_q1.py / run_q2.py / run_q3.py — executes
run_research for one question, writes the pack, and prints timing plus a
validation summary. Consolidated here so the three entry-point scripts stay
in sync instead of drifting as near-duplicate copies; it has no effect on
coordinator.py's pipeline logic or the resulting pack content.
"""
from __future__ import annotations

import asyncio
import os
import time
import traceback

from src.coordinator import run_research

CORPUS_DIR = "Corpus"


async def run_pack(question: str, output_path: str) -> None:
    os.makedirs("output", exist_ok=True)
    start = time.monotonic()
    try:
        result = await run_research(question, CORPUS_DIR)
    except Exception:
        elapsed = time.monotonic() - start
        print(f"\n--- RUN FAILED after {elapsed:.1f}s — full traceback below ---")
        traceback.print_exc()
        print(
            "\nNote which [n/6] step was the last one printed above — that's "
            "the stage that failed, not necessarily where the traceback's "
            "innermost frame points."
        )
        raise
    elapsed = time.monotonic() - start

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result["markdown"])

    print(f"\nPack written to {output_path}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print(f"Citation issues: {len(result['citation_issues'])}")
    for issue in result["citation_issues"]:
        print(f"  - {issue}")
    print(f"Structure issues: {len(result['structure_issues'])}")
    for issue in result["structure_issues"]:
        print(f"  - {issue}")

    pack = result["pack"]
    print(f"\nSections: {list(pack.findings_by_section.keys())}")
    print(f"Conflicts found: {len(pack.conflicts)}")
    print(f"Coverage gaps: {len(pack.gaps)}")
    print(f"Sources consulted: {len(pack.sources_consulted)}")


def main(question: str, output_path: str) -> None:
    asyncio.run(run_pack(question, output_path))
