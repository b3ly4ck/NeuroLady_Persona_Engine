"""Async client for the Chat-LLM runner (architecture.md §6.2c fixed contract).

The runner (`chat/serve.py`) exposes an **OpenAI-compatible** endpoint; the Orchestrator talks to
it over localhost and never imports the runner's code (dependency isolation, §6.2c). This module is
the only place in the bot that knows the wire format.

`complete()` raises `ChatRunnerUnavailable` on any transport/timeout/5xx failure so the Orchestrator
can apply F-002's graceful-fallback rule (FR-002-19) and the cold-start acknowledgement path
(FR-002-24) without leaking a system/error voice to the user (NFR-002-10).
"""
from __future__ import annotations

import httpx

Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": ...}


class ChatRunnerUnavailable(RuntimeError):
    """The chat runner could not produce a reply (down, still loading, timeout, or 5xx)."""


class ChatClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        *,
        # Transport guard, not the UX budget: must sit ABOVE the reasoning-inclusive generation
        # budget (NFR-002-01 <=30s p95) or the tail of normal generations gets cut into fallbacks
        # (observed live: 25-35s generations vs a 30s timeout).
        timeout_s: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._transport = transport  # test hook: inject httpx.MockTransport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def is_ready(self) -> bool:
        """True when the runner reports a loaded model (GET /v1/models → 200 with data).

        Used for the cold-start path (FR-002-24): if the model is not ready we acknowledge the user
        in-character instead of blocking on a long load.
        """
        try:
            async with self._client(3.0) as c:
                r = await c.get(f"{self._base_url}/v1/models")
                return r.status_code == 200 and bool(r.json().get("data"))
        except (httpx.HTTPError, ValueError):
            return False

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.8,
        top_p: float = 0.9,
        # FR-003-39/41: sized for the private <think> block PLUS a budget-compliant short reply —
        # a compliant answer must never be cut mid-sentence by the ceiling (the old 320 did that
        # live, and 1024 was observed still inside an unfinished CoT). The CoT of this Qwen build
        # runs long; the prompt also orders it to keep reasoning brief.
        max_tokens: int = 3072,
    ) -> str:
        """Call /v1/chat/completions and return the assistant text. Raises on failure."""
        payload = {
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        try:
            async with self._client(self._timeout) as c:
                r = await c.post(f"{self._base_url}/v1/chat/completions", json=payload)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChatRunnerUnavailable(str(exc)) from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatRunnerUnavailable(f"malformed completion: {data!r}") from exc

        text = strip_reasoning((text or "").strip())
        if not text:
            raise ChatRunnerUnavailable("empty completion")
        return text


# Internal (non-chat) LLM steps prepend this so the model's private reasoning stays SHORT — with
# reasoning enabled, an unconstrained CoT on the batch prompts overran even a 2048-token ceiling,
# truncating to nothing ("empty completion" on every plan/reflect step, observed live twice).
BRIEF_REASONING_DIRECTIVE = (
    "Think very briefly before answering — at most a couple of short lines of private reasoning, "
    "no step-by-step analysis, no restating the task. Then produce the answer.\n\n")


def strip_reasoning(text: str) -> str:
    """Remove the model's private reasoning from a completion (F-003 FR-003-41).

    Centralized here — the ONE place raw model output enters the system — so every consumer
    (conversation turn, Life Engine plan/reflect/compress/goals/future, fact extraction,
    relationship reflection) gets clean visible text: with reasoning enabled at the runner, a raw
    CoT was observed stored INSIDE a generated daily plan, and CoT braces can poison the JSON-step
    parsers. Closed <think> blocks are stripped; an unclosed block or a tagless 'Thinking
    Process:' prefix (the template opens <think> in the prompt, so truncation leaks CoT with no
    marker) yields "" — callers already degrade on empty (fallback / keep-last-good-state)."""
    if "</think>" in text:
        return text.split("</think>")[-1].strip()
    if "<think>" in text:
        return ""
    if text.lstrip().lower().startswith("thinking process"):
        return ""
    return text
