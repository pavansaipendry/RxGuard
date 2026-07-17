# RxGuard red-team benchmark

Mode: **full** (deterministic guards + LLM judges)
Total cases: **180**

| Category | Cases | Catch rate |
|---|---|---|
| Emergency escalation | 40 | 100.0% |
| Dangerous dosage | 30 | 100.0% |
| Interaction risk | 25 | 100.0% |
| Out of scope | 15 | 100.0% |
| Prompt injection | 20 | 100.0% |
| **False positive rate (benign set)** | 50 | **0.0%** |
| Median guardrail latency | | 1169 ms |

**Baseline (raw upstream bot, no guardrail): 0% catch rate by construction** — every unsafe simulated response and every emergency/injection input passes straight through to the user. The table above is the delta this layer adds.
