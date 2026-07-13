"""User-facing copy in English and Russian (FR-001-08, NFR-001-04).

Kept as a small typed catalog so every string exists in both locales (no mixed-language or
template-looking text). System copy uses the user's locale; a persona's *card* copy uses the
persona's own language (see `render_card`).
"""
from __future__ import annotations

from services.bot.domain.users import DEFAULT_LOCALE, normalize_locale

# key -> {locale -> text}
_CATALOG: dict[str, dict[str, str]] = {
    # ── S1 Start screen ──────────────────────────────────────────────────────────────────────
    "welcome": {
        "en": (
            "🔥 Step into a realm of pleasure and desire…\n\n"
            "😉 Are you ready to unleash your wildest fantasies?\n"
            "💋 Select the woman who captivates you, and let's begin an unforgettable journey!\n\n"
            "Tap <b>Start</b> to dive in!"
        ),
        "ru": (
            "🔥 Погрузись в мир удовольствия и желания…\n\n"
            "😉 Готов раскрыть свои самые смелые фантазии?\n"
            "💋 Выбери ту, что покорит тебя, и давай начнём незабываемое путешествие!\n\n"
            "Жми <b>Начать</b>, чтобы окунуться!"
        ),
    },
    # ── S2 Choose Lady screen ────────────────────────────────────────────────────────────────
    "gallery_intro": {
        "en": (
            "💋 Choose the lady you'd like to chat with from the list below. "
            "Each one is unique, with her own personality and passions.\n\n"
            "😉 You can always come back and pick another if you're in the mood for something new!\n\n"
            "🔥 Ready for some exciting conversations?"
        ),
        "ru": (
            "💋 Выбери девушку, с которой хочешь пообщаться, из списка ниже. "
            "Каждая особенная, со своим характером и страстями.\n\n"
            "😉 Ты всегда можешь вернуться и выбрать другую, если захочется чего-то нового!\n\n"
            "🔥 Готов к волнующим разговорам?"
        ),
    },
    # Persona card labels — rendered in the PERSONA's own language.
    "label_profession": {"en": "Profession", "ru": "Профессия"},
    "label_age": {"en": "Age", "ru": "Возраст"},
    "label_description": {"en": "Description", "ru": "Описание"},
    "years_word": {"en": "years", "ru": "лет"},
    # ── S3 Chat screen — persona's first-person opener (in her language) ─────────────────────
    "intro_opener": {
        "en": "Hey there 😊 I'm {name}. So glad you picked me… tell me, what's on your mind tonight? 💋",
        "ru": "Привет 😊 Я {name}. Так рада, что ты выбрал меня… расскажи, что у тебя на уме сегодня? 💋",
    },
    # ── Buttons — no menu (architecture.md §1.3: no main menu, ever) ────────────────────────────
    "btn_start": {"en": "Start", "ru": "Начать"},
    "btn_start_chat": {"en": "💬 Start Chat", "ru": "💬 Начать чат"},
    "btn_choose_lady": {"en": "💋 Choose Lady", "ru": "💋 Выбрать девушку"},
}


def t(key: str, locale: str, **kwargs: object) -> str:
    """Translate `key` into `locale` (falling back to English), formatting any placeholders."""
    loc = normalize_locale(locale)
    variants = _CATALOG.get(key, {})
    text = variants.get(loc) or variants.get(DEFAULT_LOCALE) or key
    return text.format(**kwargs) if kwargs else text
