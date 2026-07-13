"""F-003 human-likeness — delivery mechanics (pacing + chunking) + comm-settings parsing.

This module owns the *mechanical* half of F-003: turning one decided reply (from F-002) into a
humanly-paced, possibly-chunked delivery — a length-scaled, jittered, **capped** pre-send delay
shown as "typing…", and splitting a wall of text into a few short consecutive messages at natural
sentence boundaries. It never changes the reply's meaning (FR-003-38): chunk boundaries fall
between sentences, and the concatenation of the chunks equals the original text.

The *stylistic* half (informal register, sparse emoji, verbosity, no assistant formatting) is
realized in the persona system prompt from the same `comm_settings_json` (architecture.md §4.2 —
communication style is part of the persona prompt), so the model writes in-style; this module then
paces and chunks what it wrote.

All knobs come from the persona's `comm_settings_json` (FR-003-34, single source of truth); missing
keys fall back to sane defaults so an unconfigured persona still behaves well.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from services.bot.models import Persona

# NFR-003-01 — hard upper cap on the total deliberate delay; a reply is never withheld longer.
MAX_DELAY_S = 6.0
# Wall-of-text threshold (chars) above which a reply is split into several messages (FR-003-09).
CHUNK_THRESHOLD = 180
# FR-003-14 — chunk count is capped so the user is never flooded.
MAX_CHUNKS = 4


@dataclass(frozen=True)
class CommSettings:
    typing_speed: float = 1.0      # multiplier; >1 = faster typist = shorter delays (FR-003-05)
    verbosity: float = 1.0         # >1 chattier; scales chunk threshold (FR-003-12/15)
    max_chunks: int = MAX_CHUNKS   # cap on chunk count (FR-003-14)
    emoji_frequency: float = 0.4   # 0..1, fed to the prompt (FR-003-16/17)
    register: str = "casual"       # "casual" | "gentle" | "literal" (FR-003-21/24)
    slang_level: float = 0.4       # 0..1, fed to the prompt (FR-003-22)


def parse_settings(persona: Persona) -> CommSettings:
    raw = persona.comm_settings_json
    if not raw:
        return CommSettings()
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return CommSettings()
    defaults = CommSettings()
    return CommSettings(
        typing_speed=float(d.get("typing_speed", defaults.typing_speed)),
        verbosity=float(d.get("verbosity", defaults.verbosity)),
        max_chunks=int(d.get("max_chunks", defaults.max_chunks)),
        emoji_frequency=float(d.get("emoji_frequency", defaults.emoji_frequency)),
        register=str(d.get("register", defaults.register)),
        slang_level=float(d.get("slang_level", defaults.slang_level)),
    )


# Split on sentence-final punctuation (Latin + Cyrillic ellipsis), keeping the delimiter.
_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]+[\s]*|[^.!?…]+$", re.UNICODE)


def _sentences(text: str) -> list[str]:
    parts = [m.group().strip() for m in _SENTENCE_RE.finditer(text.strip())]
    return [p for p in parts if p]


def chunk_reply(text: str, settings: CommSettings) -> list[str]:
    """Split a long reply into several short messages at sentence boundaries (FR-003-09/11/14).

    Short replies return a single chunk. Boundaries never fall mid-word; the chunks always
    reconstruct the original text (join with a space), so meaning is preserved (FR-003-38).
    """
    text = text.strip()
    threshold = CHUNK_THRESHOLD * max(settings.verbosity, 0.1)
    if len(text) <= threshold:
        return [text]

    sentences = _sentences(text)
    if len(sentences) <= 1:
        return [text]  # one long sentence — don't split mid-clause

    cap = max(1, min(settings.max_chunks, MAX_CHUNKS))
    # Greedily pack sentences into up to `cap` chunks of roughly equal size.
    target = max(threshold, len(text) / cap)
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > target and len(chunks) < cap - 1:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def pacing_delay(text: str, settings: CommSettings, rng: random.Random | None = None) -> float:
    """A deliberate, length-scaled, jittered, capped pre-send delay (FR-003-01/02/06/08).

    Additive wait *after* fast compute — never slows the model (FR-003-07). Always in [0.3, cap].
    """
    r = rng or random
    base = 0.6 + len(text) * 0.02          # longer text → longer "typing" (FR-003-02)
    base /= max(settings.typing_speed, 0.1)  # faster typist → shorter (FR-003-05)
    jitter = r.uniform(0.85, 1.15)         # not a fixed constant (FR-003-08)
    return max(0.3, min(MAX_DELAY_S, base * jitter))
