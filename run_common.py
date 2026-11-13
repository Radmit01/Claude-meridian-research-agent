"""Shared runner used by run_q1.py / run_q2.py / run_q3.py — executes
run_research for one question, writes the pack, and prints timing plus a
validation summary. Consolidated here so the three entry-point scripts stay
in sync instead of drifting as near-duplicate copies; it has no effect on
coordinator.py's pipeline logic or the resulting pack content.

Run this file directly to execute all three in one command/process:

    python run_common.py

Each question still runs end to end independently (Q2's failure, for
example, doesn't stop Q3 from being attempted); a summary of which
succeeded/failed is printed at the end, and the exit code is non-zero if any
question failed.
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


async def run_all() -> bool:
    """Runs Q1, then Q2, then Q3 in one process so all three research packs
    are produced from a single command. QUESTION/OUTPUT_PATH are imported
    from each run_qN.py rather than duplicated here, so there is still only
    one place that defines each question's text and output filename.
    Imported inside this function (not at module top-level) because each
    run_qN.py itself does `from run_common import main` — importing them at
    module load time would be circular.
    """
    import run_q1
    import run_q2
    import run_q3

    entries = [
        ("run_q1.py", run_q1.QUESTION, run_q1.OUTPUT_PATH),
        ("run_q2.py", run_q2.QUESTION, run_q2.OUTPUT_PATH),
        ("run_q3.py", run_q3.QUESTION, run_q3.OUTPUT_PATH),
    ]
    results: list[tuple[str, bool]] = []
    for name, question, output_path in entries:
        print(f"\n{'=' * 70}\nRunning {name} -> {output_path}\n{'=' * 70}")
        try:
            await run_pack(question, output_path)
            results.append((name, True))
        except Exception:
            results.append((name, False))
            print(f"\n{name} FAILED — continuing with the remaining question(s).")

    print(f"\n{'=' * 70}\nSummary\n{'=' * 70}")
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAILED'}")

    return all(ok for _, ok in results)


if __name__ == "__main__":
    import sys

    all_ok = asyncio.run(run_all())
    sys.exit(0 if all_ok else 1)
