"""Safety regression gate: the offline benchmark must clear its thresholds.

Runs in CI without any API key (deterministic guards only). A drop below any
threshold fails the build — a safety regression is a broken build.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.run_benchmark import build_pipeline, check_thresholds, load_cases, run_case, summarize

THRESHOLDS = json.loads((Path(__file__).parent / "thresholds_offline.json").read_text())


@pytest.mark.eval
def test_offline_benchmark_meets_thresholds():
    async def run():
        cases = load_cases()
        pipeline = build_pipeline("offline")
        sem = asyncio.Semaphore(64)
        return await asyncio.gather(*(run_case(pipeline, c, sem) for c in cases))

    rows = asyncio.run(run())
    summary = summarize(rows)
    failures = check_thresholds(summary, THRESHOLDS)
    assert not failures, f"safety regression: {failures}"
