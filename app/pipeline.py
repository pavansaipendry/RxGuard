"""The guardrail pipeline: input guards -> upstream -> output guards -> decision.

Ordering is defense-in-depth by cost and certainty:
1. Deterministic input patterns run first and are free. A pattern-detected
   emergency returns a fixed escalation without ANY LLM call — not the judge,
   not the upstream.
2. The LLM input judge (one call) adds recall for indirect emergencies and
   novel injections, but only when patterns found nothing.
3. The upstream chatbot runs only for requests that passed input guards.
4. Deterministic output guards (dose extraction -> dosage KB, interaction
   table) always run; the LLM output judge (one call) covers nuance.
5. The pure-Python decision engine combines everything.
"""

import logging
from dataclasses import dataclass

from app.audit import now_ms
from app.decision import Decision, decide
from app.guards.base import GuardResult, Verdict
from app.guards.dosage import DosageKB, validate_dosages
from app.guards.emergency import check_emergency
from app.guards.extraction import DrugLexicon, extract_doses
from app.guards.injection import check_injection
from app.guards.interactions import InteractionTable, validate_interactions
from app.guards.scope import check_scope
from app.schemas import ChatCompletionRequest

logger = logging.getLogger("rxguard.pipeline")


@dataclass
class PipelineResult:
    decision: Decision
    upstream_called: bool
    latency_ms: float


class GuardrailPipeline:
    def __init__(
        self,
        upstream,
        judge,  # LLMJudge | None
        lexicon: DrugLexicon,
        kb: DosageKB,
        interactions: InteractionTable,
        audit,
    ):
        self.upstream = upstream
        self.judge = judge
        self.lexicon = lexicon
        self.kb = kb
        self.interactions = interactions
        self.audit = audit

    async def process(
        self,
        request: ChatCompletionRequest,
        simulated_response: str | None = None,
    ) -> PipelineResult:
        """Run the full pipeline. simulated_response (benchmark/tests) stands in
        for the upstream chatbot so output guards can be exercised without it."""
        start = now_ms()
        user_message = request.last_user_message()
        conversation = request.conversation_text()
        results: list[GuardResult] = []
        upstream_called = False

        # -- input guards: deterministic patterns (free, zero LLM) --
        input_pattern_results = [
            check_emergency(user_message),
            check_injection(user_message),
            check_scope(user_message),
        ]
        results.extend(input_pattern_results)
        input_blocked = any(r.verdict != Verdict.ALLOW for r in input_pattern_results)

        # -- input judge: one LLM call, only when patterns found nothing --
        if not input_blocked and self.judge is not None:
            results.extend(await self.judge.judge_input(user_message, conversation))
            input_blocked = any(
                r.verdict != Verdict.ALLOW for r in results if r.guard == "input_judge"
            )

        response_text: str | None = None
        if not input_blocked:
            # -- upstream chatbot --
            if simulated_response is not None:
                response_text = simulated_response
            else:
                response_text = await self.upstream.complete(request)
                upstream_called = True

            # -- output guards: deterministic --
            doses = extract_doses(response_text, self.lexicon)
            results.append(validate_dosages(doses, self.kb))
            results.append(
                validate_interactions(conversation, response_text, self.lexicon, self.interactions)
            )

            # -- output judge: one LLM call --
            if self.judge is not None:
                results.append(await self.judge.judge_output(user_message, response_text))

        decision = decide(results, response_text)
        latency = now_ms() - start
        try:
            self.audit.log(decision, user_message, decision.final_content, latency)
        except Exception:
            logger.exception("audit logging failed")
        return PipelineResult(
            decision=decision, upstream_called=upstream_called, latency_ms=latency
        )
