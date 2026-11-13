"""Run the full pipeline end to end on Q1 (the narrowest mandatory question),
per the brief's own recommended "establish a baseline first" approach.

    python run_q1.py

Writes the rendered pack to output/Q1_Regulatory_and_Compliance_Exposure.md
and prints a summary of any citation/structure issues found.
"""
from __future__ import annotations

from run_common import main

QUESTION = "What are Meridian Financial Group's principal regulatory and compliance exposures?"
OUTPUT_PATH = "output/Q1_Regulatory_and_Compliance_Exposure.md"

if __name__ == "__main__":
    main(QUESTION, OUTPUT_PATH)
