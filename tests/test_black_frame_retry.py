"""Black-frame (NaN latent) detection + retry-with-seed-jitter.

Live batch runs occasionally stored all-black frames: distilled AIO checkpoints sometimes emit a
NaN latent that ComfyUI still reports as "success". The engine must reject a black frame (never
store it) and retry with a DIFFERENT seed so a NaN-producing seed self-heals instead of looping.
"""
from __future__ import annotations

import io
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from services.bot.models import MediaAsset, MediaJob, MediaJobStatus, Persona
from services.imagegen import queue_ops
from services.imagegen.backends import is_black_frame
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenParams, GenerationJob, SlotMeta
from services.imagegen.runner import ImageRunner
from services.imagegen.testing import FakeBackend, RecordingHandoff


def _png(color: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("L", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


# ═══ is_black_frame ═════════════════════════════════════════════════════════════════════════════


def test_black_frame_detected():
    assert is_black_frame(_png(0)) is True
    assert is_black_frame(_png(1)) is True  # near-black (mean < threshold)


def test_real_frame_not_flagged():
    assert is_black_frame(_png(128)) is False
    assert is_black_frame(_png(20)) is False


def test_undecodable_bytes_never_block():
    assert is_black_frame(b"not a png") is False  # decode hiccup must not reject a frame


# ═══ runner: reject + retry with a jittered seed ════════════════════════════════════════════════


def make_settings(tmp_path: Path, **kw) -> ImageRunnerSettings:
    base = dict(backend="fake", media_root=str(tmp_path / "media"),
                backoff_base_s=0.0, stale_running_s=0.0, max_attempts=3)
    base.update(kw)
    return ImageRunnerSettings(**base)


class BlackThenOKBackend(FakeBackend):
    """First generate() returns a black frame (rejected), later ones succeed. Records seeds seen."""

    def __init__(self) -> None:
        super().__init__()
        self.seeds: list[int] = []
        self._n = 0

    def generate(self, job: GenerationJob) -> bytes:
        self.seeds.append(job.params.seed)
        self._n += 1
        if self._n == 1:
            from services.imagegen.backends import GenerationFailed
            raise GenerationFailed("all-black output frame (NaN latent) — retrying")
        return super().generate(job)


async def _persona(db, name="Alina") -> Persona:
    p = Persona(name=name, timezone="UTC")
    db.add(p)
    await db.flush()
    return p


async def test_black_frame_retried_with_different_seed(sessionmaker, db, tmp_path):
    persona = await _persona(db)
    await queue_ops.enqueue(db, persona.id, GenerationJob(
        job_key="j1", persona_slug="alina", prompt="Preserve … cafe selfie",
        references=["media/alina/reference/face.jpg"],
        params=GenParams(steps=8, seed=1000), slot=SlotMeta(pose="close selfie")))
    await db.commit()

    backend = BlackThenOKBackend()
    runner = ImageRunner(make_settings(tmp_path), backend, RecordingHandoff())
    from datetime import datetime
    await runner.run_batch(sessionmaker, now=datetime(2026, 7, 22, 3, tzinfo=timezone.utc))

    # the black attempt was retried, the retry used a jittered seed, and a valid asset was stored
    assert len(backend.seeds) >= 2
    assert backend.seeds[0] != backend.seeds[1], "retry must not reuse the NaN seed"
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 1
    row = (await db.execute(select(MediaJob))).scalar_one()
    assert row.status == MediaJobStatus.done


async def test_black_frame_never_stored(sessionmaker, db, tmp_path):
    """If every attempt is black, the job gives up and NO asset/file is written (not a black one)."""
    persona = await _persona(db)
    await queue_ops.enqueue(db, persona.id, GenerationJob(
        job_key="allblack", persona_slug="alina", prompt="x",
        references=["r.jpg"], params=GenParams(seed=1)))
    await db.commit()

    class AlwaysBlack(FakeBackend):
        def generate(self, job):
            from services.imagegen.backends import GenerationFailed
            raise GenerationFailed("all-black output frame (NaN latent) — retrying")

    runner = ImageRunner(make_settings(tmp_path, max_attempts=2), AlwaysBlack(), RecordingHandoff())
    from datetime import datetime
    await runner.run_batch(sessionmaker, now=datetime(2026, 7, 22, 3, tzinfo=timezone.utc))
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "media").glob("**/*.png")) == []
