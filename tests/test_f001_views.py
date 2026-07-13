"""F-001 view/keyboard tests — pure builders, no bot needed.

Maps to TC ids for FR-001-02/03/04/05/06/09/12/16 and NFR-001-04 (localization).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from services.bot import views
from services.bot.models import Persona, PersonaStatus


def make_persona(**kw) -> Persona:
    base = dict(
        id=1, name="Olivia", profession="Psychologist", age=30, timezone="UTC",
        language="en", card_description="I listen closely and tease often.",
        status=PersonaStatus.active, gallery_photo_ref=None,
    )
    base.update(kw)
    return Persona(**base)


# ── S1 Welcome (FR-001-02, NFR-001-04) ──────────────────────────────────────────────────────


def test_fr_001_02_01_welcome_single_start_button():
    """TC-FR-001-02-01/02 — Welcome has flirty copy and exactly one 'Start' inline button."""
    text, kb = views.welcome_view("en")
    assert "Step into a realm" in text
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1 and len(kb.inline_keyboard[0]) == 1
    assert kb.inline_keyboard[0][0].callback_data == "start"


def test_nfr_001_04_01_welcome_localized():
    """TC-NFR-001-04-01 — RU welcome is Russian, EN welcome is English (no mix)."""
    ru, _ = views.welcome_view("ru")
    en, _ = views.welcome_view("en")
    assert "Погрузись" in ru and "Step into" in en
    assert "Step into" not in ru


# ── S2 gallery intro + reply keyboard (FR-001-03/12) ────────────────────────────────────────


def test_fr_001_03_01_gallery_intro_carries_reply_keyboard():
    """TC-FR-001-03-01 — the S2 intro message carries the reply keyboard (Choose Lady only, no menu)."""
    text, kb = views.gallery_intro_view("en")
    assert "Choose the lady" in text
    assert isinstance(kb, ReplyKeyboardMarkup)
    labels = [b.text for row in kb.keyboard for b in row]
    assert len(labels) == 1
    assert "Choose Lady" in labels[0]


# ── S2 persona card (FR-001-04/05/06/09) ────────────────────────────────────────────────────


def test_fr_001_04_01_card_shows_labeled_fields():
    """TC-FR-001-04-01 — card body shows Name + Profession:/Age:/Description: labels and values."""
    body = views.card_body(make_persona())
    assert "Olivia" in body
    assert "Profession:" in body and "Psychologist" in body
    assert "Age:" in body and "30 years" in body
    assert "Description:" in body and "I listen closely" in body


def test_fr_001_04_02_card_content_photo_and_keyboard():
    """TC-FR-001-04-02 — gallery_card_view returns photo_ref + body + card keyboard."""
    card = views.gallery_card_view(make_persona(gallery_photo_ref=None), index=0, total=5, user_locale="en")
    assert card.photo_ref is None  # seed personas have no photo yet -> text card
    assert "Olivia" in card.body
    row = card.keyboard.inline_keyboard[0]
    assert [b.text for b in row] == ["◀", "1/5", "▶"]


def test_fr_001_06_01_pagination_callbacks_are_cyclic():
    """TC-FR-001-06-01/02 — ◀ from the first card wraps to the last; ▶ to the next."""
    card = views.gallery_card_view(make_persona(), index=0, total=5, user_locale="en")
    left, _counter, right = card.keyboard.inline_keyboard[0]
    assert left.callback_data == "card:4"   # wrap back
    assert right.callback_data == "card:1"  # forward


def test_fr_001_09_01_start_chat_button():
    """TC-FR-001-09-01 — card has a 'Start Chat' button carrying the persona id."""
    card = views.gallery_card_view(make_persona(id=7), index=0, total=5, user_locale="en")
    assert card.keyboard.inline_keyboard[1][0].callback_data == "startchat:7"


def test_fr_001_08_04_card_copy_in_persona_language():
    """TC-FR-001-08-04 — a RU persona's card uses Russian labels + copy regardless of user locale."""
    ru = make_persona(id=2, name="Alina", profession="Психолог", age=28,
                      language="ru", card_description="Слушаю лучше всех.")
    body = views.card_body(ru)
    assert "Профессия:" in body and "Психолог" in body
    assert "Возраст:" in body and "28 лет" in body
    assert "Описание:" in body and "Слушаю лучше всех." in body


# ── S3 opener (FR-001-11) ────────────────────────────────────────────────────────────────────


def test_fr_001_11_01_intro_opener_names_persona():
    """TC-FR-001-11-01 — the S3 opener is a first-person message naming the persona."""
    assert "Olivia" in views.intro_opener(make_persona())


def test_fr_001_12_04_reply_kb_has_only_choose_lady():
    """TC-FR-001-12-01 — the reply keyboard has exactly one button: 💋 Choose Lady (no menu)."""
    from services.bot import keyboards

    kb = keyboards.reply_kb("en")
    buttons = [b.text for row in kb.keyboard for b in row]
    assert len(buttons) == 1
    assert "Choose Lady" in buttons[0]
