"""Launch the research dashboard (FastAPI backend + static frontend).

    python run_dashboard.py            # http://127.0.0.1:8000
    python run_dashboard.py --port 9000

Runs from the project root so `src/`, `Corpus/` and `output/` resolve the same
way they do for run_q1.py / run_q2.py / run_q3.py.
"""
from __future__ import annotations

import argparse
import os
import webbrowser

import uvicorn

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}/")
    # Single worker, no reload: runs live in this process and capture stdout.
    uvicorn.run("server.app:app", host=args.host, port=args.port, workers=1, log_level="warning")
