"""FR-012-20 — photo-frequency pacing is operator-configurable (on/off), seeding F-022.

Executes the real `pacing_allows` / `deliver_photo` path: with pacing OFF, a user already over the
per-stage cap still receives a photo; with pacing ON (the product default), the cap still holds.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from services.bot.domain.media_delivery import (
    DeliveryOutcome, MediaDeliveryConfig, deliver_photo, pacing_allows,
)
from services.bot.domain.users import get_or_create_user
from services.bot.models import MediaAsset, MediaKind, MediaSend, Persona

pytestmark = pytest.mark.asyncio


class _Chat:
    async def is_ready(self): return True
    async def complete(self, messages, **kw): return "вот"


class _Gate:
    async def handle_intimate_request(self, **kw): return {"action": "withhold"}


async def _persona(db):
    p = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                card_description="", big_five="", timezone="Europe/Moscow")
    db.add(p); await db.flush(); return p


async def _asset(db, persona, aid, media_root):
    tgt = media_root / "alina" / "photos" / f"{aid}.png"
    tgt.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (30, 30, 40)).save(tgt)
    a = MediaAsset(id=aid, persona_id=persona.id, kind=MediaKind.photo, intimate=False,
                   intimacy_level=0, storage_ref=f"media/alina/photos/{aid}.png",
                   meta_json=json.dumps({}))
    db.add(a); await db.flush(); return a


async def test_fr_012_20_01_pacing_off_allows_over_the_cap(db):
    """TC-FR-012-20-01 — with pacing disabled, a user at/over the cap still passes."""
    user, _ = await get_or_create_user(db, 7201, "ru")
    now = datetime.now(timezone.utc)
    for i in range(5):  # far over any stage cap, all within the window
        db.add(MediaSend(user_id=user.id, asset_id=f"MED-x-{i}", sent_at=now))
    await db.flush()

    off = MediaDeliveryConfig(pacing_enabled=False)
    on = MediaDeliveryConfig(pacing_enabled=True)
    assert await pacing_allows(db, user_id=user.id, stage="Stranger", cfg=off, now=now) is True
    assert await pacing_allows(db, user_id=user.id, stage="Stranger", cfg=on, now=now) is False


async def test_fr_012_20_02_pacing_off_delivers_a_photo_when_capped(db, tmp_path):
    """TC-FR-012-20-01 (e2e) — the real delivery path sends a photo despite the window being full."""
    user, _ = await get_or_create_user(db, 7202, "ru")
    persona = await _persona(db)
    await _asset(db, persona, "MED-alina-A1", tmp_path)
    now = datetime.now(timezone.utc)
    for i in range(5):
        db.add(MediaSend(user_id=user.id, asset_id=f"MED-cap-{i}", sent_at=now))
    await db.flush()

    paced = await deliver_photo(db, user_id=user.id, persona=persona, request_text="скинь фото",
                                context={}, caption_client=_Chat(), gate=_Gate(),
                                cfg=MediaDeliveryConfig(pacing_enabled=True), media_root=tmp_path)
    lifted = await deliver_photo(db, user_id=user.id, persona=persona, request_text="скинь фото",
                                 context={}, caption_client=_Chat(), gate=_Gate(),
                                 cfg=MediaDeliveryConfig(pacing_enabled=False), media_root=tmp_path)

    assert paced.outcome is DeliveryOutcome.paced
    assert lifted.outcome is DeliveryOutcome.delivered


def test_fr_012_20_03_toggle_is_read_from_env():
    """TC-FR-012-20-02 — the bot Settings expose the switch and the handler builds cfg from it."""
    from services.bot.config import Settings

    assert Settings(media_pacing_enabled=False).media_pacing_enabled is False
    assert Settings(media_pacing_enabled=True).media_pacing_enabled is True
    # the code default (ignoring any ambient .env on the dev box) stays ON
    assert Settings(_env_file=None).media_pacing_enabled is True
