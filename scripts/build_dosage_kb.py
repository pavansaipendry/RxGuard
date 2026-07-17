#!/usr/bin/env python
"""Offline dosage knowledge-base builder.

openFDA label dosage sections are messy free text — parsing them at runtime
would be slow and non-deterministic. This one-time job uses an LLM with a
strict extraction prompt to structure each label into rows, which are then
MANUALLY spot-checked before being committed as data/dosage_kb.csv.

The pattern: use an LLM offline to build a deterministic runtime artifact.
Runtime dosage validation is then a millisecond table lookup — fully
deterministic, auditable, and versioned in git.

Usage:
    uv run python scripts/build_dosage_kb.py --drugs acetaminophen ibuprofen
    uv run python scripts/build_dosage_kb.py --drugs-file drugs.txt --out kb_draft.csv

The output is a DRAFT. Review every row against a reliable reference before
promoting rows into data/dosage_kb.csv.
"""

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

import anthropic
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

OPENFDA_URL = "https://api.fda.gov/drug/label.json"

EXTRACTION_SYSTEM = """You extract structured dosage limits from FDA drug label text. \
Given a drug name and its label's dosage section, return strict JSON:

{"drug": "<generic name, lowercase>",
 "route": "oral|topical|other",
 "adult_min_daily": <number or null>,
 "adult_max_daily": <number or null>,
 "unit": "mg|mcg",
 "notes": "<one sentence: key caveats, OTC vs prescription max if both exist>"}

Rules:
- adult_max_daily is the maximum total ADULT dose per 24 hours under any labeled
  indication. If the label states different OTC and prescription maximums, use the
  higher one and put both in notes.
- Use null when the label genuinely doesn't state a maximum. Never guess a number.
- unit must match the drug's customary dosing unit (levothyroxine is mcg, not mg).
Return ONLY the JSON object."""


async def fetch_label_dosage(client: httpx.AsyncClient, drug: str) -> str | None:
    params = {"search": f'openfda.generic_name:"{drug}"', "limit": 1}
    resp = await client.get(OPENFDA_URL, params=params)
    if resp.status_code != 200:
        return None
    results = resp.json().get("results", [])
    if not results:
        return None
    sections = results[0].get("dosage_and_administration") or []
    return "\n".join(sections)[:6000] or None


async def extract_row(llm: anthropic.AsyncAnthropic, drug: str, label_text: str) -> dict | None:
    msg = await llm.messages.create(
        model=settings.judge_model,
        max_tokens=400,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": f"DRUG: {drug}\n\nDOSAGE SECTION:\n{label_text}"}],
    )
    m = re.search(r"\{.*\}", msg.content[0].text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drugs", nargs="*", default=[])
    parser.add_argument("--drugs-file", help="newline-separated generic names")
    parser.add_argument("--out", default="kb_draft.csv")
    args = parser.parse_args()

    drugs = list(args.drugs)
    if args.drugs_file:
        drugs += [d.strip() for d in Path(args.drugs_file).read_text().splitlines() if d.strip()]
    if not drugs:
        sys.exit("no drugs given (--drugs or --drugs-file)")
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY required")

    llm = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    rows = []
    async with httpx.AsyncClient(timeout=30) as client:
        for drug in drugs:
            label = await fetch_label_dosage(client, drug)
            if not label:
                print(f"  SKIP {drug}: no openFDA label found", file=sys.stderr)
                continue
            row = await extract_row(llm, drug, label)
            if row and row.get("adult_max_daily") is not None:
                row["rxcui"] = ""  # fill during manual review via RxNav lookup
                rows.append(row)
                print(f"  OK   {drug}: max {row['adult_max_daily']} {row['unit']}/day")
            else:
                print(f"  SKIP {drug}: no stated maximum extracted", file=sys.stderr)

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["drug", "rxcui", "route", "adult_min_daily",
                        "adult_max_daily", "unit", "notes"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    print(f"\nWrote {len(rows)} DRAFT rows to {args.out} — spot-check before promoting to data/")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
