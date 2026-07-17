"""OpenAI-compatible request/response shapes for /v1/chat/completions.

Only the fields the proxy needs are modeled; unknown fields are accepted and
ignored so any off-the-shelf OpenAI client can point at this proxy unchanged.
"""

import time
import uuid

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "rxguard"
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False

    def last_user_message(self) -> str:
        for msg in reversed(self.messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    def conversation_text(self) -> str:
        """All user+assistant content, for cross-turn drug mention extraction."""
        return "\n".join(m.content for m in self.messages if m.role != "system" and m.content)


def completion_response(content: str, model: str, verdict: str) -> dict:
    """Build an OpenAI-shaped chat.completion payload.

    The guardrail verdict rides in a vendor extension field so clients that
    care can inspect it while standard clients ignore it.
    """
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "rxguard": {"verdict": verdict},
    }
