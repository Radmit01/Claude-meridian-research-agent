"""Run the full pipeline end to end on Q2 (prior relationship with Protiviti).

    python run_q2.py

Writes the rendered pack to output/Q2_Prior_Relationship.md
and prints a summary of any citation/structure issues found.
"""
from __future__ import annotations

from run_common import main

QUESTION = "Where has Protiviti worked with Meridian before, and what did we learn?"
OUTPUT_PATH = "output/Q2_Prior_Relationship.md"

if __name__ == "__main__":
    main(QUESTION, OUTPUT_PATH)
