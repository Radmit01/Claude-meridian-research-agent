"""Run the full pipeline end to end on Q1 (the narrowest mandatory question),
per the brief's own recommended "establish a baseline first" approach.

    python run_q1.py

Writes the rendered pack to output/Q1_Regulatory_and_Compliance_Exposure.md
and prints a summary of any citation/structure issues found.
"""
from __future__ import annotations

import asyncio
import os
import traceback

from src.coordinator import run_research

QUESTION = "What are Meridian Financial Group's principal regulatory and compliance exposures?"
CORPUS_DIR = "Corpus"
OUTPUT_PATH = "output/Q1_Regulatory_and_Compliance_Exposure.md"


async def main() -> None:
    os.makedirs("output", exist_ok=True)
    try:
        result = await run_research(QUESTION, CORPUS_DIR)
    except Exception:
        print("\n--- RUN FAILED — full traceback below ---")
        traceback.print_exc()
        print(
            "\nNote which [n/6] step was the last one printed above — that's "
            "the stage that failed, not necessarily where the traceback's "
            "innermost frame points."
        )
        raise

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(result["markdown"])

    print(f"\nPack written to {OUTPUT_PATH}")
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


if __name__ == "__main__":
    asyncio.run(main())
