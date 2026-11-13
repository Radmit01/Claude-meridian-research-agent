"""Run the full pipeline end to end on Q3 (the full pre-engagement research
pack — deliberately broad, the hardest of the three fixed questions).

    python run_q3.py

Writes the rendered pack to output/Q3_Full_Pre_Engagement_Research_Pack.md
and prints a summary of any citation/structure issues found.
"""
from __future__ import annotations

from run_common import main

QUESTION = "Produce the full pre-engagement client research pack for Meridian Financial Group."
OUTPUT_PATH = "output/Q3_Full_Pre_Engagement_Research_Pack.md"

if __name__ == "__main__":
    main(QUESTION, OUTPUT_PATH)
