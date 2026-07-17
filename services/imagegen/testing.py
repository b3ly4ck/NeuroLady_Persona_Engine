"""Test doubles for the F-008 runner — a deterministic in-process ModelBackend.

Lets the whole job lifecycle (queue → generate → atomic store → row) run without a GPU: output
bytes are a function of (prompt, seed, steps) so reproducibility (TC-FR-008-06-03) and swap
tests (TC-FR-008-03-*) have real assertions.
"""
from __future__ import annotations

import hashlib

from services.imagegen.backends import GenerationFailed
from services.imagegen.contract import GenerationJob

# A minimal valid 1x1 PNG (so stored files are real PNGs, not arbitrary bytes).
_PNG_STUB = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class FakeBackend:
    """Deterministic fake: records calls, can be scripted to fail N times (FR-008-13 tests)."""

    def __init__(self, fail_times: int = 0, name: str = "fake-A") -> None:
        self.name = name
        self.fail_times = fail_times
        self.loaded = False
        self.closed = False
        self.load_calls = 0
        self.close_calls = 0
        self.generate_calls: list[GenerationJob] = []

    def load(self) -> None:
        self.loaded = True
        self.load_calls += 1

    def close(self) -> None:
        self.loaded = False
        self.closed = True
        self.close_calls += 1

    def generate(self, job: GenerationJob) -> bytes:
        self.generate_calls.append(job)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise GenerationFailed("scripted transient failure")
        # Deterministic per (prompt, seed, steps): same inputs → same bytes (FR-008-06-03).
        digest = hashlib.sha256(
            f"{self.name}|{job.prompt}|{job.params.seed}|{job.params.steps}".encode()
        ).digest()
        return _PNG_STUB + digest


class AlwaysFailBackend(FakeBackend):
    """Permanent failure — exercises give-up + skip (TC-FR-008-13-02)."""

    def generate(self, job: GenerationJob) -> bytes:
        self.generate_calls.append(job)
        raise GenerationFailed("scripted permanent failure")


class RecordingHandoff:
    """Records the handoff order relative to backend load/close (TC-FR-008-15-*)."""

    def __init__(self) -> None:
        self.events: list[str] = []

    async def unload_chat(self) -> None:
        self.events.append("chat_unloaded")

    async def reload_chat(self) -> None:
        self.events.append("chat_reloaded")
