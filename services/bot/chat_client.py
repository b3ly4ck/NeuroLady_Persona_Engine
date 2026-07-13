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
        timeout_s: float = 30.0,
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
        max_tokens: int = 320,
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

        text = (text or "").strip()
        if not text:
            raise ChatRunnerUnavailable("empty completion")
        return text
