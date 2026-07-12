"""F-001 view/keyboard tests — pure `(text, keyboard)` builders, no bot needed.

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
        status=PersonaStatus.active,
    )
    base.update(kw)
    return Persona(**base)


# ── Welcome (FR-001-02, NFR-001-04) ─────────────────────────────────────────────────────────


def test_fr_001_02_01_welcome_single_start_button():
    """TC-FR-001-02-01/02 — Welcome has the header and exactly one 'Start' inline button."""
    text, kb = views.welcome_view("en")
    assert "NeuroLady AI" in text
    assert isinstance(kb, InlineKeyboardMarkup)
    assert len(kb.inline_keyboard) == 1 and len(kb.inline_keyboard[0]) == 1
    assert kb.inline_keyboard[0][0].callback_data == "start"


def test_nfr_001_04_01_welcome_localized():
    """TC-NFR-001-04-01 — RU welcome is Russian, EN welcome is English (no mix)."""
    ru, _ = views.welcome_view("ru")
    en, _ = views.welcome_view("en")
    assert "Погрузись" in ru and "Step into" in en
    assert "Step into" not in ru


# ── Gallery card (FR-001-03/04/05/06/09) ────────────────────────────────────────────────────


def test_fr_001_04_01_card_shows_all_fields():
    """TC-FR-001-04-01 — card shows name, profession, age, and description."""
    p = make_persona()
    text, _ = views.gallery_card_view(p, index=0, total=5, user_locale="en")
    assert "Olivia" in text and "Psychologist" in text and "30" in text
    assert "I listen closely" in text


def test_fr_001_05_01_counter_and_controls():
    """TC-FR-001-05-01 — card carries a '1/N' counter and ◀ / ▶ controls."""
    p = make_persona()
    _, kb = views.gallery_card_view(p, index=0, total=5, user_locale="en")
    row = kb.inline_keyboard[0]
    assert [b.text for b in row] == ["◀", "1/5", "▶"]


def test_fr_001_06_01_pagination_callbacks_are_cyclic():
    """TC-FR-001-06-01/02 — ◀ from the first card wraps to the last; ▶ to the next."""
    p = make_persona()
    _, kb = views.gallery_card_view(p, index=0, total=5, user_locale="en")
    left, _counter, right = kb.inline_keyboard[0]
    assert left.callback_data == "card:4"   # wrap back
    assert right.callback_data == "card:1"  # forward


def test_fr_001_09_01_start_chat_button():
    """TC-FR-001-09-01 — card has a 'Start Chat' button carrying the persona id."""
    p = make_persona(id=7)
    _, kb = views.gallery_card_view(p, index=0, total=5, user_locale="en")
    start_btn = kb.inline_keyboard[1][0]
    assert start_btn.callback_data == "startchat:7"


def test_fr_001_08_04_card_copy_in_persona_language():
    """TC-FR-001-08-04 — an EN user browsing a RU persona still sees her copy (her language field)."""
    ru_persona = make_persona(id=2, name="Alina", profession="Психолог", age=28,
                              language="ru", card_description="Слушаю лучше всех.")
    text, _ = views.gallery_card_view(ru_persona, index=0, total=5, user_locale="en")
    assert "Слушаю лучше всех." in text and "Психолог" in text


# ── Chat-ready + menu (FR-001-12/16) ────────────────────────────────────────────────────────


def test_fr_001_12_01_chat_ready_reply_keyboard():
    """TC-FR-001-12-01 — reply keyboard has '💋 Choose Lady' and a menu (≡) button."""
    p = make_persona()
    text, kb = views.chat_ready_view(p, "en")
    assert isinstance(kb, ReplyKeyboardMarkup)
    labels = [b.text for row in kb.keyboard for b in row]
    assert any("Choose Lady" in x for x in labels)
    assert any("Menu" in x or "≡" in x for x in labels)
    assert "Olivia" in text


def test_fr_001_16_01_menu_actions():
    """TC-FR-001-16-01 — menu exposes Choose Lady and Resume, one tap each."""
    _, kb = views.menu_view("en")
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "choose_lady" in callbacks and "resume" in callbacks
