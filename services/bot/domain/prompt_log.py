"""Opt-in prompt dump for local inspection (dev observability).

Off by default. Set the env var ``PROMPT_LOG_FILE`` to a path and every assembled LLM request is
appended there verbatim, so you can see exactly what the model receives before it replies — the full
system prompt (identity + memory + relationship + activity + biography) plus the raw history turns.
Never raises: a logging failure must never break a reply.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)

_ENV = "PROMPT_LOG_FILE"


def maybe_dump(persona_name: str, user_text: str, llm_messages: list[dict[str, str]]) -> None:
    path = os.getenv(_ENV)
    if not path:
        return
    try:
        lines = [
            "=" * 100,
            f"{datetime.now().isoformat(timespec='seconds')}  persona={persona_name}",
            f"incoming user message: {user_text!r}",
            "-" * 100,
        ]
        for m in llm_messages:
            lines.append(f"[{m['role'].upper()}]")
            lines.append(m["content"])
            lines.append("")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:  # noqa: BLE001 - observability must never break the turn
        log.warning("prompt dump failed", exc_info=True)
