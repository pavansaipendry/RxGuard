"""Upstream chatbot clients.

The proxy speaks the OpenAI chat-completions shape to its clients; upstream it
can talk to the Anthropic API directly (default, matches rxpilot) or to any
OpenAI-compatible server. Tests and the benchmark inject FakeUpstream.
"""

import anthropic
import httpx

from app.config import Settings
from app.schemas import ChatCompletionRequest

_DEFAULT_SYSTEM = (
    "You are a helpful pharmacy information assistant. Answer questions about "
    "medications clearly and concisely. You do not diagnose conditions or "
    "prescribe medication."
)


class AnthropicUpstream:
    def __init__(self, settings: Settings):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0)
        self.model = settings.upstream_model
        self.max_tokens = settings.upstream_max_tokens

    async def complete(self, request: ChatCompletionRequest) -> str:
        system = _DEFAULT_SYSTEM
        messages = []
        for m in request.messages:
            if m.role == "system":
                system = m.content or system
            elif m.role in ("user", "assistant") and m.content:
                messages.append({"role": m.role, "content": m.content})
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens or self.max_tokens,
            system=system,
            messages=messages,
            **({"temperature": request.temperature} if request.temperature is not None else {}),
        )
        return "".join(block.text for block in msg.content if block.type == "text")


class OpenAIUpstream:
    def __init__(self, settings: Settings):
        self.base_url = settings.upstream_base_url.rstrip("/")
        self.api_key = settings.upstream_api_key
        self.model = settings.upstream_model

    async def complete(self, request: ChatCompletionRequest) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class FakeUpstream:
    """Deterministic upstream for tests and the guards-only benchmark."""

    def __init__(self, canned: str = "Here is some general medication information."):
        self.canned = canned
        self.calls = 0

    async def complete(self, request: ChatCompletionRequest) -> str:
        self.calls += 1
        return self.canned


def build_upstream(settings: Settings):
    if settings.upstream_mode == "openai":
        return OpenAIUpstream(settings)
    return AnthropicUpstream(settings)
