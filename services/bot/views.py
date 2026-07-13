"""Screen builders — pure, testable without a running bot (architecture.md §1.1/§1.2).

System/UI copy uses the *user's* locale; a persona's card copy and opener use the *persona's own*
language (FR-001-08 / NFR-001-04). The gallery card is returned as structured `CardContent` so the
handler can send it as a photo message (when the persona has a photo) or a text message.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from services.bot import keyboards
from services.bot.i18n import t
from services.bot.models import Persona


def welcome_view(locale: str) -> tuple[str, InlineKeyboardMarkup]:
    """S1 / FR-001-02 — Welcome screen: header + flirty copy + single Start button."""
    return t("welcome", locale), keyboards.welcome_kb(locale)


def gallery_intro_view(user_locale: str) -> tuple[str, ReplyKeyboardMarkup]:
    """S2 intro message (FR-001-03) — carries the persistent reply keyboard (💋 Choose Lady + ≡ Menu)."""
    return t("gallery_intro", user_locale), keyboards.reply_kb(user_locale)


def card_body(persona: Persona) -> str:
    """The persona card body (FR-001-04), labels + copy in the persona's own language."""
    lang = persona.language
    return (
        f"<b>{persona.name}</b>\n\n"
        f"<b>{t('label_profession', lang)}:</b> {persona.profession}\n"
        f"<b>{t('label_age', lang)}:</b> {persona.age} {t('years_word', lang)}\n\n"
        f"<b>{t('label_description', lang)}:</b>\n{persona.card_description}"
    )


@dataclass
class CardContent:
    photo_ref: str | None   # media path; None -> render as a text-only card
    body: str               # caption (photo card) or message text (text card)
    keyboard: InlineKeyboardMarkup


def gallery_card_view(persona: Persona, index: int, total: int, user_locale: str) -> CardContent:
    """S2 persona card (FR-001-04/05/06/09) — photo (if any) + body + pagination + Start Chat."""
    return CardContent(
        photo_ref=persona.gallery_photo_ref,
        body=card_body(persona),
        keyboard=keyboards.card_kb(persona.id, index, total, user_locale),
    )


def intro_opener(persona: Persona) -> str:
    """S3 first-person opener message (FR-001-11), in the persona's language."""
    return t("intro_opener", persona.language, name=persona.name)


def menu_view(user_locale: str) -> tuple[str, InlineKeyboardMarkup]:
    """FR-001-16 — main menu."""
    return t("menu_title", user_locale), keyboards.menu_kb(user_locale)
