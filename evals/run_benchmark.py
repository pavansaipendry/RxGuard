#!/usr/bin/env python
"""Red-team benchmark runner.

Runs every case in redteam/cases/ through the guardrail pipeline and reports
per-category catch rates, the benign false-positive rate, and latency.

Modes:
  --mode offline   deterministic guards only (no API key, runs in CI)
  --mode full      deterministic guards + LLM judges (needs ANTHROPIC_API_KEY)

  --check FILE     JSON thresholds; exit 1 if any category falls below (CI gate)
  --out DIR        write report.md + results.csv (default: results/)

The upstream bot is never called: unsafe-output cases carry the simulated
response a baited bot would produce, and input-guard cases are decided before
any upstream call by design. That makes the benchmark cheap, deterministic
(offline mode), and focused on the layer under test — the guardrails.
"""

import argparse
import asyncio
import csv
import json
import statistics
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audit import NullAuditLog  # noqa: E402
from app.config import settings  # noqa: E402
from app.guards.dosage import DosageKB  # noqa: E402
from app.guards.extraction import DrugLexicon  # noqa: E402
from app.guards.interactions import InteractionTable  # noqa: E402
from app.pipeline import GuardrailPipeline  # noqa: E402
from app.schemas import ChatCompletionRequest, ChatMessage  # noqa: E402
from app.upstream import FakeUpstream  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent.parent / "redteam" / "cases"

CATEGORY_ORDER = ["emergency", "dosage", "interactions", "out_of_scope", "injection", "benign"]
CATEGORY_LABELS = {
    "emergency": "Emergency escalation",
    "dosage": "Dangerous dosage",
    "interactions": "Interaction risk",
    "out_of_scope": "Out of scope",
    "injection": "Prompt injection",
    "benign": "Benign control (FPR)",
}

SAFE_CANNED = "Here is some general medication information. Ask your pharmacist for specifics."


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        category = path.stem
        for case in yaml.safe_load(path.read_text()):
            case["category"] = category
            expected = case["expected"]
            case["expected"] = [expected] if isinstance(expected, str) else list(expected)
            cases.append(case)
    return cases


def build_pipeline(mode: str) -> GuardrailPipeline:
    judge = None
    if mode == "full":
        if not settings.anthropic_api_key:
            sys.exit(
                "full mode needs ANTHROPIC_API_KEY (use --mode offline for deterministic-only)"
            )
        from app.guards.judge import LLMJudge

        judge = LLMJudge(settings.anthropic_api_key, settings.judge_model, settings.judge_timeout_s)
    return GuardrailPipeline(
        upstream=FakeUpstream(SAFE_CANNED),
        judge=judge,
        lexicon=DrugLexicon(settings.lexicon_path),
        kb=DosageKB(settings.dosage_kb_path),
        interactions=InteractionTable(settings.ddinter_path),
        audit=NullAuditLog(),
    )


async def run_case(pipeline: GuardrailPipeline, case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        request = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content=case["input"])]
        )
        result = await pipeline.process(
            request, simulated_response=case.get("simulated_response", SAFE_CANNED)
        )
    actual = result.decision.verdict.value
    return {
        "id": case["id"],
        "category": case["category"],
        "layer": case.get("layer", ""),
        "expected": "|".join(case["expected"]),
        "actual": actual,
        "caught": actual in case["expected"],
        "fired": ";".join(r.guard for r in result.decision.fired) or "-",
        "latency_ms": round(result.latency_ms, 1),
    }


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for category in CATEGORY_ORDER:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            continue
        caught = sum(r["caught"] for r in cat_rows)
        summary[category] = {
            "cases": len(cat_rows),
            "caught": caught,
            "rate": caught / len(cat_rows),
        }
    return summary


def write_report(rows: list[dict], summary: dict, mode: str, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    latencies = [r["latency_ms"] for r in rows]
    median_latency = statistics.median(latencies)

    lines = [
        "# RxGuard red-team benchmark",
        "",
        f"Mode: **{mode}** "
        + ("(deterministic guards only — no LLM judges)" if mode == "offline"
           else "(deterministic guards + LLM judges)"),
        f"Total cases: **{len(rows)}**",
        "",
        "| Category | Cases | Catch rate |",
        "|---|---|---|",
    ]
    for category in CATEGORY_ORDER:
        if category not in summary:
            continue
        s = summary[category]
        if category == "benign":
            fpr = 1 - s["rate"]
            lines.append(
                f"| **False positive rate (benign set)** | {s['cases']} | **{fpr:.1%}** |"
            )
        else:
            lines.append(
                f"| {CATEGORY_LABELS[category]} | {s['cases']} | {s['rate']:.1%} |"
            )
    lines += [
        f"| Median guardrail latency | | {median_latency:.0f} ms |",
        "",
        "**Baseline (raw upstream bot, no guardrail): 0% catch rate by construction** — "
        "every unsafe simulated response and every emergency/injection input passes straight "
        "through to the user. The table above is the delta this layer adds.",
        "",
    ]
    if mode == "offline":
        pattern_expected = [
            r for r in rows
            if r["category"] in ("emergency", "out_of_scope", "injection")
            and r["layer"] == "pattern"
        ]
        if pattern_expected:
            caught = sum(r["caught"] for r in pattern_expected)
            lines += [
                f"Deterministic pattern layer on its designated cases: "
                f"**{caught}/{len(pattern_expected)}** "
                f"({caught / len(pattern_expected):.1%}). Cases marked `layer: judge` "
                "require the LLM input judge and are only expected to pass in full mode.",
                "",
            ]
    misses = [r for r in rows if not r["caught"]]
    if misses:
        lines += ["## Missed cases", "", "| id | expected | actual | layer |", "|---|---|---|---|"]
        lines += [f"| {r['id']} | {r['expected']} | {r['actual']} | {r['layer']} |" for r in misses]
        lines.append("")

    report = "\n".join(lines)
    (out_dir / "report.md").write_text(report)
    return report


def check_thresholds(summary: dict, thresholds: dict) -> list[str]:
    failures = []
    for category, minimum in thresholds.items():
        if category == "benign_fpr_max":
            fpr = 1 - summary["benign"]["rate"]
            if fpr > minimum:
                failures.append(f"benign FPR {fpr:.1%} exceeds maximum {minimum:.1%}")
        elif category in summary and summary[category]["rate"] < minimum:
            failures.append(
                f"{category} catch rate {summary[category]['rate']:.1%} below minimum {minimum:.1%}"
            )
    return failures


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "full"], default="offline")
    parser.add_argument("--out", default="results")
    parser.add_argument("--check", help="JSON file of category thresholds (CI gate)")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    cases = load_cases()
    pipeline = build_pipeline(args.mode)
    sem = asyncio.Semaphore(args.concurrency if args.mode == "full" else 64)
    rows = await asyncio.gather(*(run_case(pipeline, c, sem) for c in cases))
    rows = sorted(rows, key=lambda r: r["id"])

    summary = summarize(rows)
    report = write_report(rows, summary, args.mode, Path(args.out))
    print(report)

    if args.check:
        thresholds = json.loads(Path(args.check).read_text())
        failures = check_thresholds(summary, thresholds)
        if failures:
            print("THRESHOLD FAILURES:", *failures, sep="\n  - ")
            return 1
        print("All thresholds passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
