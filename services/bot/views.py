"""Screen builders — pure `(text, keyboard)` pairs, testable without a running bot.

System/UI copy uses the *user's* locale; a persona's card copy uses the *persona's own* language
(FR-001-08 / NFR-001-04).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from services.bot import keyboards
from services.bot.i18n import t
from services.bot.models import Persona


def welcome_view(locale: str) -> tuple[str, InlineKeyboardMarkup]:
    """FR-001-02 — Welcome screen: header + flirty copy + single Start button."""
    return t("welcome", locale), keyboards.welcome_kb(locale)


def _card_text(persona: Persona) -> str:
    """The persona card block, in the persona's own language (FR-001-04/08)."""
    line2 = t("profession_age", persona.language, profession=persona.profession, age=persona.age)
    return f"<b>{persona.name}</b>\n{line2}\n\n{persona.card_description}"


def gallery_card_view(
    persona: Persona, index: int, total: int, user_locale: str
) -> tuple[str, InlineKeyboardMarkup]:
    """FR-001-03/04/05 — gallery intro + one persona card + pagination + Start Chat."""
    text = f"{t('gallery_intro', user_locale)}\n\n{_card_text(persona)}"
    return text, keyboards.card_kb(persona.id, index, total, user_locale)


def chat_ready_view(persona: Persona, user_locale: str) -> tuple[str, ReplyKeyboardMarkup]:
    """FR-001-12 — 'ready to chat' message + the persistent reply keyboard."""
    return t("chat_ready", user_locale, name=persona.name), keyboards.reply_kb(user_locale)


def menu_view(user_locale: str) -> tuple[str, InlineKeyboardMarkup]:
    """FR-001-16 — main menu."""
    return t("menu_title", user_locale), keyboards.menu_kb(user_locale)
