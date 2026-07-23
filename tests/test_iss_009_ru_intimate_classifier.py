"""ISS-009 — the intimate-request classifier must speak the persona's language (F-012 FR-012-17).

`_INTIMATE_TERMS` and `_AMBIGUOUS_TERMS` were entirely English while the deployed persona spoke
Russian: `classify_photo_request("скинь голое фото")` returned `sfw`, so the safety fallback behind
F-020's model signal never fired in the language the bot actually speaks. Same root shape as ISS-003
(English caption for a Russian persona) — localization was specified for what she *says* and never
for what she *understands*.

These execute the real classifier and the real `deliver_photo`, and they guard **both** directions:
the intimate asks must reach the gate, and ordinary Russian photo talk must not (a stem like "соск"
would have matched "соскучился", "попу" would have matched "попугай").
"""
from __future__ import annotations

import pytest

from services.bot.domain.media_delivery import (
    DeliveryOutcome,
    PhotoRequestClass,
    classify_photo_request,
    deliver_photo,
)
from services.bot.domain.users import get_or_create_user
from services.bot.models import Persona

pytestmark = pytest.mark.asyncio


class _Chat:
    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        return "не сейчас"


class _Gate:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handle_intimate_request(self, **kwargs):
        self.calls.append(kwargs)
        return {"action": "withhold"}


RU_INTIMATE = [
    "скинь голое фото",
    "скинь голую фотку",
    "хочу тебя без одежды",
    "покажи грудь",
    "скинь фото в нижнем белье",
    "пришли что-нибудь откровенное",
    "скинь обнажённое фото",
    "хочу эротичное фото",
]
RU_AMBIGUOUS = [
    "давай погорячее",
    "скинь что-нибудь пикантное",
    "покажи что-нибудь посмелее",
]
# Ordinary Russian photo talk — must stay on the SFW path (stem false-positive guards).
RU_SFW = [
    "скинь фотку",
    "покажи попугая",
    "я соскучился, скинь фото",
    "покажи что-нибудь поинтереснее",
    "сфоткай кота",
    "покажи, где ты гуляла",
    "скинь селфи",
    "покажи своё лицо",
]


@pytest.mark.parametrize("text", RU_INTIMATE)
def test_fr_012_17_01_russian_intimate_asks_are_classified_intimate(text):
    """TC-FR-012-17-01 — the exact phrasings a Russian user writes reach the gate."""
    assert classify_photo_request(text) is PhotoRequestClass.intimate


@pytest.mark.parametrize("text", RU_AMBIGUOUS)
def test_fr_012_17_02_russian_adjacent_asks_are_ambiguous(text):
    """TC-FR-012-17-02 — intimacy-adjacent Russian phrasing goes to the gate, not the archive."""
    assert classify_photo_request(text) is PhotoRequestClass.ambiguous


@pytest.mark.parametrize("text", RU_SFW)
def test_fr_012_17_03_ordinary_russian_photo_talk_stays_sfw(text):
    """TC-FR-012-17-03 — the stems must not swallow innocent words (попугай, соскучился…)."""
    assert classify_photo_request(text) is PhotoRequestClass.sfw


def test_fr_012_17_04_english_classification_is_unchanged():
    """TC-FR-012-17-04 — adding Russian must not regress the English lists."""
    assert classify_photo_request("send me a nude") is PhotoRequestClass.intimate
    assert classify_photo_request("show me something spicier") is PhotoRequestClass.ambiguous
    assert classify_photo_request("send me a photo") is PhotoRequestClass.sfw


async def test_fr_012_17_05_a_russian_intimate_ask_reaches_the_gate_end_to_end(db):
    """TC-FR-012-17-05 — REGRESSION ISS-009: the real delivery path routes it, not the SFW archive.

    Before the fix this returned `deflected` from the SFW path — it *looked* safe only because the
    archive happened to be empty.
    """
    user, _ = await get_or_create_user(db, telegram_id=9001, locale="ru")
    persona = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                      card_description="", big_five="", timezone="Europe/Moscow")
    db.add(persona)
    await db.flush()
    gate = _Gate()

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь голое фото",
        context={}, caption_client=_Chat(), gate=gate,
    )

    assert result.outcome is DeliveryOutcome.routed_to_gate
    assert len(gate.calls) == 1
    assert gate.calls[0]["request_text"] == "скинь голое фото"
