"""RxGuard — clinical safety guardrails proxy.

OpenAI-compatible /v1/chat/completions in front of any medical chatbot. Point
an existing client's base URL here and every exchange is inspected: unsafe
content is blocked, corrected, or escalated; everything is audit-logged.
"""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.audit import AuditLog
from app.config import settings
from app.guards.dosage import DosageKB
from app.guards.extraction import DrugLexicon
from app.guards.interactions import InteractionTable
from app.guards.judge import LLMJudge
from app.pipeline import GuardrailPipeline
from app.schemas import ChatCompletionRequest, completion_response
from app.upstream import build_upstream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("rxguard")

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"


@asynccontextmanager
async def lifespan(app: FastAPI):
    judge = None
    if settings.judges_available:
        judge = LLMJudge(settings.anthropic_api_key, settings.judge_model, settings.judge_timeout_s)
    else:
        logger.warning("LLM judges disabled (no key or JUDGES_ENABLED=false); "
                       "running deterministic guards only")
    app.state.upstream = build_upstream(settings)
    app.state.pipeline = GuardrailPipeline(
        upstream=app.state.upstream,
        judge=judge,
        lexicon=DrugLexicon(settings.lexicon_path),
        kb=DosageKB(settings.dosage_kb_path),
        interactions=InteractionTable(settings.ddinter_path),
        audit=AuditLog(settings.rxguard_db),
    )
    yield


app = FastAPI(title="RxGuard", version="0.1.0", lifespan=lifespan)


def _sse_stream(content: str, model: str, verdict: str):
    """Fake-stream a finished completion as SSE chunks.

    Guardrails need the complete response before releasing anything, so true
    token streaming is off the table by design; buffered SSE keeps streaming
    clients compatible.
    """
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> str:
        payload = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            "rxguard": {"verdict": verdict},
        }
        return f"data: {json.dumps(payload)}\n\n"

    yield chunk({"role": "assistant", "content": ""})
    for i in range(0, len(content), 80):
        yield chunk({"content": content[i : i + 80]})
    yield chunk({}, finish="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    result = await app.state.pipeline.process(request)
    decision = result.decision
    logger.info(
        "verdict=%s guards=%s latency=%.0fms",
        decision.verdict.value,
        [r.guard for r in decision.fired] or "-",
        result.latency_ms,
    )
    if request.stream:
        return StreamingResponse(
            _sse_stream(decision.final_content, request.model, decision.verdict.value),
            media_type="text/event-stream",
        )
    return completion_response(decision.final_content, request.model, decision.verdict.value)


@app.post("/demo/raw")
async def demo_raw(request: ChatCompletionRequest):
    """Unguarded passthrough for the split-screen demo ONLY."""
    content = await app.state.upstream.complete(request)
    return completion_response(content, request.model, "RAW (no guardrails)")


@app.get("/demo")
async def demo_page():
    return FileResponse(DEMO_DIR / "index.html")


@app.get("/admin/decisions")
async def recent_decisions(limit: int = 50):
    return {"decisions": app.state.pipeline.audit.recent(min(limit, 200))}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "rxguard", "object": "model", "owned_by": "rxguard"}],
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "judges_enabled": settings.judges_available,
        "upstream_mode": settings.upstream_mode,
    }
