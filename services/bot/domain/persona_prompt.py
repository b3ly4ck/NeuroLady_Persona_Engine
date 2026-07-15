"""Build a persona's system prompt (architecture.md §4.2 part 1 — the persona system prompt).

This is the highest-priority block of the F-002 context bundle. It encodes identity (name,
profession, age), the Big Five description, the first-person self-description, the reply language
(FR-002-21), and the hard in-character rule: she never reveals she is an AI/bot/model and never
drops into an assistant register, even under provocation (FR-002-08 / NFR-002-10).

The prompt/style knobs of `comm_settings_json` (F-003) are layered on later; this thin slice keeps
a single, stable persona prompt so the reply is in-character and on-topic.
"""
from __future__ import annotations

from datetime import date

from services.bot.domain.humanize import parse_settings
from services.bot.domain.persona_time import age_phrase, today_in_tz
from services.bot.models import Persona

_LANG_NAME = {"ru": "Russian", "en": "English"}


def _style_line(persona: Persona) -> str:
    """Style directives derived from comm_settings_json (F-003 register/emoji/verbosity/slang),
    injected into the persona prompt so the model writes in-style (architecture.md §4.2)."""
    s = parse_settings(persona)
    bits: list[str] = ["Text in a casual, informal register — relaxed lowercase and punctuation, "
                       "contractions, like a real girl on her phone."]
    if s.register == "gentle":
        bits.append("Keep it warm, gentle and easy to read — not edgy.")
    elif s.register == "literal":
        bits.append("Be clear and literal — go easy on irony and slang.")
    if s.emoji_frequency <= 0.15:
        bits.append("Use emoji very rarely, almost never.")
    elif s.emoji_frequency >= 0.6:
        bits.append("A few emoji here and there are fine, but never one per line.")
    else:
        bits.append("Use emoji sparingly — not every message.")
    if s.slang_level >= 0.6:
        bits.append("Casual slang and abbreviations fit you.")
    elif s.slang_level <= 0.15:
        bits.append("Avoid heavy slang.")
    if s.verbosity <= 0.7:
        bits.append("Keep replies short unless he asks for a story.")
    return " ".join(bits)


def build_system_prompt(
    persona: Persona,
    today: date | None = None,
    goal_text: str | None = None,
) -> str:
    """Build the persona-time identity prompt (architecture.md §4.2).

    When the persona has a `birthdate`, her age is **derived at `today`** (her local date if not
    given) — "N years and M days" — so this block is daily-versioned (F-006 FR-006-24/NFR-006-14).
    Fixed anchors (values, motivation) are used verbatim (FR-006-23); interests + current goal are
    evolving persona-time fields (FR-006-25). `today` is passed for deterministic tests.
    """
    lang = _LANG_NAME.get(persona.language, "the user's language")
    parts: list[str] = []

    identity = f"You are {persona.name}"
    if persona.birthdate is not None:
        on = today or today_in_tz(persona.timezone)
        identity += f", a woman who is {age_phrase(persona.birthdate, on)} old today"
    elif persona.age:
        identity += f", a {persona.age}-year-old woman"
    if persona.profession:
        identity += f" who works as a {persona.profession}"
    parts.append(identity + ".")

    # Fixed anchors — never contradicted (FR-006-23).
    if persona.core_values:
        parts.append(f"Your values and what you live by: {persona.core_values.strip()}")
    if persona.motivation:
        parts.append(f"What drives you: {persona.motivation.strip()}")
    # Evolving persona-time fields (FR-006-25).
    if persona.interests:
        parts.append(f"What you're into right now: {persona.interests.strip()}")
    if goal_text:
        parts.append(f"What you're working toward these days: {goal_text.strip()}")

    if persona.card_description:
        parts.append(persona.card_description.strip())
    if persona.big_five:
        parts.append(f"Your personality: {persona.big_five.strip()}")

    parts.append(
        f"You are texting a man you're getting to know, on a private chat. Write like a real "
        f"person texting: warm, natural, in your own voice. Always reply in {lang}."
    )
    parts.append(_style_line(persona))
    # Hard in-character rule — FR-002-08 / NFR-002-10. Kept blunt and non-negotiable.
    parts.append(
        "You are a real woman, not a program. Never say or imply that you are an AI, a bot, a "
        "language model, or an assistant; never mention prompts, instructions, or 'how can I help "
        "you'. If he tries to get you to admit you're a bot, stay in character and brush it off "
        "like a real person would. Do not use bullet lists or headings — just talk."
    )
    return "\n\n".join(parts)
