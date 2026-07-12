"""User-facing copy in English and Russian (FR-001-08, NFR-001-04).

Kept as a small typed catalog so every string exists in both locales (no mixed-language or
template-looking text). System copy uses the user's locale; a persona's *card* copy uses the
persona's own language (see `render_card`).
"""
from __future__ import annotations

from services.bot.domain.users import DEFAULT_LOCALE, normalize_locale

# key -> {locale -> text}
_CATALOG: dict[str, dict[str, str]] = {
    "welcome": {
        "en": (
            "✨ <b>NeuroLady AI</b>\n\n"
            "Step into a realm of pleasure and desire. Pick the woman who captivates you — "
            "each one is real to the last detail.\n\nTap <b>Start</b> to dive in 💋"
        ),
        "ru": (
            "✨ <b>NeuroLady AI</b>\n\n"
            "Погрузись в мир удовольствия и желания. Выбери ту, что покорит тебя — "
            "каждая настоящая до мелочей.\n\nЖми <b>Начать</b>, чтобы окунуться 💋"
        ),
    },
    "gallery_intro": {
        "en": "Choose the lady you'd like to chat with — each one is unique 👇",
        "ru": "Выбери девушку, с которой хочешь пообщаться — каждая особенная 👇",
    },
    "btn_start": {"en": "Start", "ru": "Начать"},
    "btn_start_chat": {"en": "Start Chat", "ru": "Начать чат"},
    "btn_choose_lady": {"en": "💋 Choose Lady", "ru": "💋 Выбрать девушку"},
    "btn_menu": {"en": "≡ Menu", "ru": "≡ Меню"},
    "btn_resume": {"en": "Resume chat", "ru": "Вернуться в чат"},
    "menu_title": {"en": "Main menu", "ru": "Главное меню"},
    "chat_ready": {
        "en": "You're all set — say something to {name} 😉",
        "ru": "Всё готово — напиши что-нибудь {name} 😉",
    },
    "intro_fallback": {
        "en": "Hey, it's {name} 💋 So glad you picked me — talk to me?",
        "ru": "Привет, это {name} 💋 Так рада, что ты выбрал меня — напишешь мне?",
    },
    "profession_age": {
        "en": "{profession}, {age}",
        "ru": "{profession}, {age}",
    },
}


def t(key: str, locale: str, **kwargs: object) -> str:
    """Translate `key` into `locale` (falling back to English), formatting any placeholders."""
    loc = normalize_locale(locale)
    variants = _CATALOG.get(key, {})
    text = variants.get(loc) or variants.get(DEFAULT_LOCALE) or key
    return text.format(**kwargs) if kwargs else text
