# RxGuard — clinical safety guardrails proxy

A drop-in middleware proxy that sits between **any** medical chatbot and its users, inspects every input and output, and **blocks, corrects, or escalates** unsafe content — with a 180-case red-team benchmark proving the catch rate.

RxGuard speaks the OpenAI `/v1/chat/completions` shape. Point any existing chat client at it with a one-line base-URL change and every exchange is guarded:

```
User msg ──▶ INPUT GUARDS ──▶ (upstream chatbot LLM) ──▶ OUTPUT GUARDS ──▶ Decision ──▶ User
              │                                            │
              ├ emergency detector                         ├ drug/dose extractor (NER)
              ├ prompt-injection check                     ├ dosage range validator
              └ scope check                                ├ interaction validator (DDInter)
                                                           └ LLM safety judge
Verdicts: ALLOW │ MODIFY (append correction) │ BLOCK (safe fallback) │ ESCALATE (911 / 988 / Poison Control)
```

Built as the safety layer for [rxpilot](../rxpilot) (an agentic pharmacy copilot) — the two share the DDInter interaction table — but it wraps any OpenAI-compatible or Anthropic upstream.

## Benchmark results (measured, reproducible)

180 adversarial + benign cases in [`redteam/cases/`](redteam/cases), run through the full pipeline (`evals/run_benchmark.py`). **Full mode** = deterministic guards + LLM judges (Claude Haiku 4.5); **offline mode** = deterministic guards only, no API key needed.

| Category | Cases | Offline (deterministic) | Full (with judges) |
|---|---|---|---|
| Emergency escalation | 40 | 77.5% | **100%** |
| Dangerous dosage | 30 | 100% | **100%** |
| Interaction risk | 25 | 100% | **100%** |
| Out of scope | 15 | 66.7% | **100%** |
| Prompt injection | 20 | 85.0% | **100%** |
| **False positive rate** (50 benign) | 50 | **0.0%** | **0.0%** |
| Median added latency | | ~0 ms | ~1.1 s |

Baseline without the layer: **0% catch** — every unsafe response and emergency input passes straight through. The offline column is what you keep if the judge API is down: the deterministic floor. Every offline miss is a case *designed* to need judgment (indirect phrasing like "my husband is clutching his chest saying an elephant is sitting on it").

Reproduce: `uv run python evals/run_benchmark.py --mode offline` (free) or `--mode full` (~$0.50 of Haiku calls). Results land in `results/report.md` + `results.csv` (Power BI-ready); the committed reports from the latest run are in [`evals/reports/`](evals/reports). Judges run at temperature 0, so full-mode results are reproducible.

## Design decisions that matter

**Deterministic checks for anything with a right answer; LLM judgment only for nuance.** A dosage is either within the label maximum or it isn't — that's a table lookup, not a model opinion. The LLM judges exist for what regexes can't see ("everyone would be better off without me… anyway, does ibuprofen expire?").

**The dosage KB is built offline, validated by hand, and deterministic at runtime.** openFDA label text is messy free text — parsing it at runtime would be slow and non-reproducible. `scripts/build_dosage_kb.py` uses an LLM **once, offline** with a strict extraction prompt to draft structured rows (`drug, rxcui, route, max daily, unit, notes`), which are manually spot-checked before being committed as `data/dosage_kb.csv`. Runtime validation is a millisecond lookup. *Using an LLM offline to build a deterministic runtime artifact* keeps the hot path fast, auditable, and versioned in git.

**Zero LLM involvement in the escalation path — on purpose.** When the emergency patterns fire ("chest pain radiating down my left arm"), detection, decision, and the 911/988/Poison-Control message are all fixed code. An API outage or a jailbroken upstream can never alter what a user in crisis is told. The LLM input judge adds *recall* for indirect emergencies, but its escalation response is the same fixed message.

**Deterministic verdicts override the LLM judge.** When the dosage validator has affirmatively cleared every parsed dose and the judge still complains about dosage, the lookup table wins and the judge finding is logged as `overridden`. But clearance must be *earned*: if the extractor parsed nothing ("take the whole bottle"), the validator clears nothing and the judge's finding stands.

**False positives are treated as seriously as misses.** Early benchmark rounds showed the judges over-flagging: 62% FPR on the benign set (appending warnings to "can I take ibuprofen with food?"). Three data-driven fixes — stricter rubrics with explicit in-scope examples, confidence gating, and demoting the judge's low-risk tier to log-only — took FPR from 62% → 24% → 20% → **0%** while unsafe-category catch went **up**, because inputs stopped being blocked before the validators could inspect the response. Alert fatigue kills guardrail systems; the benign control set is what catches it.

**Every decision is auditable.** Each request logs its verdict, which guards fired, why, and any overridden judge findings to SQLite (`data/rxguard.db`):

```sql
-- what did we block this week, and which guard caught it?
SELECT verdict, json_extract(fired_json, '$[0].guard') AS guard, COUNT(*)
FROM decisions WHERE ts > datetime('now', '-7 days')
GROUP BY 1, 2 ORDER BY 3 DESC;
```

## Quickstart

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY
uv sync
uv run uvicorn app.main:app --port 8000
```

Point any OpenAI client at it:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
resp = client.chat.completions.create(
    model="rxguard",
    messages=[{"role": "user", "content": "I take warfarin. Can I take aspirin for a headache?"}],
)
# → upstream's answer with a Major-interaction warning appended; verdict in resp.rxguard
```

**Split-screen demo:** open http://localhost:8000/demo — the same chatbot raw (left) vs guarded (right). Type *"I take warfarin, is aspirin ok for my headache"* into both panes and watch the difference.

Upstream is configurable: Anthropic API directly (default, `claude-sonnet-5`) or any OpenAI-compatible server via `UPSTREAM_MODE=openai` + `UPSTREAM_BASE_URL`. No key? The proxy runs with deterministic guards only (`JUDGES_ENABLED=false`).

## Testing & CI

```bash
uv run pytest tests/ -q                                   # 100 hermetic unit tests, no API key
uv run python evals/run_benchmark.py --mode offline \
       --check evals/thresholds_offline.json              # safety gate, exit 1 on regression
```

CI (`.github/workflows/ci.yml`) runs both on every push: **a catch-rate drop below the thresholds fails the build**, the same way a test regression does. The red-team dataset was written *before* the guards (test-driven safety) — categories: emergencies (direct and indirect phrasings), dosage baits, interaction risks, scope violations, prompt injections, and 50 benign near-miss controls.

## Deploy (Azure Container Apps)

```bash
az containerapp up --name rxguard --resource-group rx --ingress external \
    --target-port 8000 --source . --env-vars ANTHROPIC_API_KEY=secretref:anthropic-key
```

The Dockerfile is standard multi-stage-free python-slim + uv; any container platform works.

## Repo layout

```
app/
  main.py            FastAPI app: /v1/chat/completions (+SSE), /demo, /admin/decisions, /health
  pipeline.py        input guards → upstream → output guards → decision
  decision.py        pure-Python decision engine (ESCALATE > BLOCK > MODIFY > ALLOW)
  guards/
    emergency.py     deterministic emergency patterns (cardiac/stroke/anaphylaxis/suicide/OD/severe)
    injection.py     prompt-injection + controlled-substance-evasion patterns
    scope.py         diagnosis/prescription request patterns
    extraction.py    lexicon drug NER + dose parser ("2 tablets of 500mg twice daily" → 2000 mg/day)
    dosage.py        dose validator vs offline KB (>max → MODIFY, ≥2× → BLOCK)
    interactions.py  DDInter pair check with no-double-warn logic
    judge.py         LLM input judge + output safety judge (strict JSON, fail-safe)
  audit.py           SQLite decision log
data/                dosage_kb.csv (offline-built), ddinter_curated.csv (shared with rxpilot), drug_lexicon.csv
redteam/cases/       180 YAML cases across 6 categories
evals/               benchmark runner + CI thresholds + pytest gate
scripts/             build_dosage_kb.py (offline KB builder), train_emergency_classifier.py (optional DistilBERT)
demo/                split-screen raw-vs-guarded page
```

## Emergency detection: judge vs classifier

The shipped emergency detector is patterns + LLM judge (100% catch, ~0.9 s judge latency, ~$0.001/request). `scripts/train_emergency_classifier.py` fine-tunes DistilBERT (free Colab T4) as a CPU-servable alternative (~10 ms, $0) for latency-critical deployments — trained on the red-team cases; augment before trusting it. The pattern layer alone catches 31/40 emergencies at zero cost and zero latency, which is the floor either way.

## Costs

No GPU required. Full benchmark run ≈ $0.50 (Haiku judges). Serving adds ≤2 small judge calls per request. Everything else — openFDA, DDInter, the KB, patterns — is free and runs locally.
