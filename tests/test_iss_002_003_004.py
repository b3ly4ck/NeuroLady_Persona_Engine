"""Regression tests for ISS-002 / ISS-003 / ISS-004, found testing the bot live.

- ISS-002 (F-001 FR-001-25/26, F-013 FR-013-12): the gallery card rendered text-only because
  `gallery_photo_ref` pointed at a file provisioning never created.
- ISS-003 (F-012 FR-012-12): the photo caption came back in English under a Russian persona.
- ISS-004 (F-003 FR-003-42, F-012 FR-012-13): the photo landed instantly — no human pacing.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from sqlalchemy import select

from services.bot.domain.humanize import (
    MEDIA_DELAY_MAX_S,
    MEDIA_DELAY_MIN_S,
    CommSettings,
    media_pacing_delay,
)
from services.bot.domain.media_delivery import (
    fallback_caption,
    fallback_deflection,
    request_caption,
    request_deflection,
)
from services.bot.models import MediaAsset, MediaKind, Persona
from services.imagegen.gallery import (
    check_gallery_photos,
    gallery_ref,
    provision_gallery_photo,
)

BOT_DIR = Path(__file__).resolve().parent.parent / "services" / "bot"


class CaptureClient:
    """Records the prompt it was asked with; returns a canned caption."""

    def __init__(self, reply: str = "ок") -> None:
        self.reply = reply
        self.messages = None

    async def complete(self, messages, **kw) -> str:
        self.messages = messages
        return self.reply


def _persona(name="Alina", language="ru") -> Persona:
    return Persona(name=name, language=language)


def _asset(persona_id=1, aid="MED-alina-00001", intimate=False, pose="close selfie") -> MediaAsset:
    import json
    return MediaAsset(
        id=aid, persona_id=persona_id, kind=MediaKind.photo, intimate=intimate,
        intimacy_level=0, storage_ref=f"media/alina/photos/{aid}.png",
        meta_json=json.dumps({"pose": pose, "activity": "кофе", "location": "cafe",
                              "time_of_day": "afternoon"}),
    )


# ═══ ISS-003 — caption language (FR-012-12) ═════════════════════════════════════════════════════


async def test_iss_003_caption_prompt_requests_persona_language_ru():
    client = CaptureClient()
    await request_caption(client, persona=_persona(language="ru"), asset=_asset(),
                          context={}, stage="Stranger")
    system = client.messages[0]["content"]
    assert "Russian" in system, "the caption prompt must name her language (ISS-003)"


async def test_iss_003_caption_prompt_requests_english_for_en_persona():
    client = CaptureClient()
    await request_caption(client, persona=_persona(name="Olivia", language="en"), asset=_asset(),
                          context={}, stage="Stranger")
    assert "English" in client.messages[0]["content"]


async def test_iss_003_deflection_also_localized():
    client = CaptureClient()
    await request_deflection(client, persona=_persona(language="ru"), reason="paced", context={})
    assert "Russian" in client.messages[0]["content"]


def test_iss_003_fallback_lines_are_localized():
    ru, en = _persona(language="ru"), _persona(name="Olivia", language="en")
    assert fallback_caption(ru) != fallback_caption(en)
    assert any(c.isalpha() and c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
               for c in fallback_caption(ru)), "ru fallback must be Russian"
    assert "you're eager" in fallback_deflection(en, "paced")
    assert fallback_deflection(ru, "paced") != fallback_deflection(en, "paced")


def test_iss_003_unknown_language_falls_back_to_english():
    assert fallback_caption(_persona(language="zz")) == fallback_caption(_persona(language="en"))


# ═══ ISS-004 — media pacing (FR-003-42 / FR-012-13) ═════════════════════════════════════════════


def test_iss_004_media_delay_is_within_bounds():
    s = CommSettings()
    for _ in range(50):
        d = media_pacing_delay(s)
        assert MEDIA_DELAY_MIN_S <= d <= MEDIA_DELAY_MAX_S


def test_iss_004_media_delay_is_length_independent():
    """Unlike text pacing, the beat does not depend on any text — it's 'grabbing a photo'."""
    sig = inspect.signature(media_pacing_delay)
    assert "text" not in sig.parameters and "chunks" not in sig.parameters


def test_iss_004_faster_persona_is_quicker():
    import random
    fast = media_pacing_delay(CommSettings(typing_speed=3.0), random.Random(1))
    slow = media_pacing_delay(CommSettings(typing_speed=1.0), random.Random(1))
    assert fast <= slow


def test_iss_004_photo_path_sleeps_before_sending():
    """REGRESSION: the photo branch used to send the upload action and deliver immediately."""
    src = (BOT_DIR / "handlers" / "conversation.py").read_text()
    photo_branch = src.split("looks_like_photo_request(message.text):", 1)[1].split("return", 1)[0]
    assert "media_pacing_delay" in photo_branch and "_sleep" in photo_branch
    assert photo_branch.index("_sleep") < photo_branch.index("serve_photo_request"), \
        "the delay must precede the send"


# ═══ ISS-002 — gallery card photo (FR-001-25/26, FR-013-12) ═════════════════════════════════════


async def test_iss_002_provisions_gallery_photo_from_archive(db, tmp_path):
    persona = Persona(name="Alina", language="ru")
    db.add(persona)
    await db.flush()
    photos = tmp_path / "alina" / "photos"
    photos.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (64, 64), (120, 120, 120)).save(photos / "MED-alina-00001.png")
    db.add(_asset(persona_id=persona.id))
    await db.flush()

    ref = await provision_gallery_photo(db, persona, tmp_path)
    assert ref == gallery_ref("alina")
    assert (tmp_path / "alina" / "gallery" / "card.jpg").exists()
    assert persona.gallery_photo_ref == ref


async def test_iss_002_never_uses_an_intimate_asset(db, tmp_path):
    persona = Persona(name="Alina", language="ru")
    db.add(persona)
    await db.flush()
    photos = tmp_path / "alina" / "photos"
    photos.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (64, 64), (10, 10, 10)).save(photos / "MED-alina-00002.png")
    db.add(_asset(persona_id=persona.id, aid="MED-alina-00002", intimate=True))
    await db.flush()

    assert await provision_gallery_photo(db, persona, tmp_path) is None  # only intimate → refuse


async def test_iss_002_no_archive_keeps_text_fallback(db, tmp_path):
    persona = Persona(name="Newgirl")
    db.add(persona)
    await db.flush()
    assert await provision_gallery_photo(db, persona, tmp_path) is None  # documented fallback


async def test_iss_002_health_check_flags_missing_photo(db, tmp_path, caplog):
    db.add(Persona(name="Alina", gallery_photo_ref="media/alina/gallery/card.jpg"))
    await db.flush()
    with caplog.at_level("WARNING"):
        checks = await check_gallery_photos(db, tmp_path)
    assert checks and not checks[0].ok
    assert "MISSING" in caplog.text, "a missing gallery photo must be operator-visible, not silent"


async def test_iss_002_health_check_passes_when_provisioned(db, tmp_path):
    persona = Persona(name="Alina", gallery_photo_ref=gallery_ref("alina"))
    db.add(persona)
    await db.flush()
    card = tmp_path / "alina" / "gallery" / "card.jpg"
    card.parent.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (32, 32), (200, 200, 200)).save(card)
    checks = await check_gallery_photos(db, tmp_path)
    assert checks[0].ok
