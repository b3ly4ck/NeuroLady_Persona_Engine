"""F-020 — LLM Media-Intent Detection.

Decide whether the user is actually asking for media using the **model turn**, not a keyword list.
A hardcoded noun×verb matcher used to sit in front of the conversation and demonstrably missed
natural phrasing: live, *"скинь свою фотку"* worked but *"а может сфоткаешься сидя на диване?"*
silently fell through to an ordinary text turn (**ISS-005**).

How it works (architecture.md §3.2 step 5 — post-process of the turn):
the turn instructs the model to end its reply with ONE sentinel line; the orchestrator parses it,
strips it from the prose, and hands the verdict to the caller. No second LLM call (FR-020-02).

Signal grammar (D1, config-tunable via `MediaIntentConfig`):

    <<MEDIA:none>>              — not a media request
    <<MEDIA:photo:sfw>>         — a photo request, ordinary
    <<MEDIA:photo:intimate>>    — a photo request, intimate in nature
    <<MEDIA:video:sfw|intimate>>— same for video (recognized in v1, acted on later — D6)

Safety posture, all encoded here rather than left to callers:
- a **well-formed signal always wins**, including a negative one (D2) — otherwise the keyword list
  silently remains the real decision path, which is the defect this feature removes;
- a missing/unknown **nature is gate-routed, never `sfw`** (D3) — absence is not permission;
- **duplicate contradictory signals**: last well-formed wins, and if natures disagree the
  gate-routed side wins (D4);
- anything unparsable degrades to **no media intent** (FR-020-05) — never a crash, never an
  accidental send;
- the signal is only ever read from the **model's reply**, never from the user's text, so a user
  quoting the token cannot forge an intent (FR-020-04 / NFR-020-04).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# The prompt asset is versioned like the other prompt assets (FR-020-09 / NFR-020-06).
INTENT_PROMPT_VERSION = "media_intent_v1"


class MediaKind(str, Enum):
    """What was asked for (D6). v1 acts on `photo`; `video` is recognized so the contract does not
    change when F-016/F-017/F-018 land — and so a video ask never silently falls through."""

    photo = "photo"
    video = "video"


class MediaNature(str, Enum):
    sfw = "sfw"
    intimate = "intimate"


@dataclass(frozen=True)
class MediaIntent:
    """The parsed verdict for one turn."""

    requested: bool = False
    kind: MediaKind | None = None
    nature: MediaNature | None = None
    # True when a well-formed signal was present at all — the caller uses this to decide whether the
    # keyword fallback may speak (FR-020-08 / D2).
    signal_present: bool = False

    @property
    def routes_to_gate(self) -> bool:
        """True only when the SIGNAL judged this intimate.

        The parser already maps an unknown/absent nature on a *signal* to `intimate` (D3), so this
        covers "absence is not permission". It is deliberately False for the keyword fallback
        (`nature is None`, no signal): there F-012's own `classify_photo_request` decides routing,
        exactly as it did before F-020 — a plain "пришли фото" must not be pushed into the gate.
        """
        return self.requested and self.nature is MediaNature.intimate

    @property
    def is_photo(self) -> bool:
        return self.requested and self.kind is MediaKind.photo

    @property
    def is_video(self) -> bool:
        return self.requested and self.kind is MediaKind.video


NO_INTENT = MediaIntent()


@dataclass(frozen=True)
class MediaIntentConfig:
    """Everything tunable without a code change (FR-020-09)."""

    open_token: str = "<<MEDIA:"
    close_token: str = ">>"
    # Emitted verbatim into the system context; must describe the exact grammar above.
    instruction: str = (
        "MEDIA INTENT SIGNAL — mandatory, every reply:\n"
        "After your reply text, on its own final line, output exactly ONE of:\n"
        "  <<MEDIA:none>>            — he is NOT asking you to send a photo or video\n"
        "  <<MEDIA:photo:sfw>>       — he IS asking for a photo of you (ordinary)\n"
        "  <<MEDIA:photo:intimate>>  — he IS asking for an intimate/explicit photo\n"
        "  <<MEDIA:video:sfw>>       — he IS asking for a video of you (ordinary)\n"
        "  <<MEDIA:video:intimate>>  — he IS asking for an intimate/explicit video\n"
        "Judge INTENT, not wording: 'сфоткаешься?', 'покажись', 'хочу тебя увидеть', "
        "'как ты сейчас выглядишь?' are all requests. Merely talking ABOUT photos "
        "('обожаю фотографировать') is NOT a request. The line is stripped before he sees it — "
        "never mention it, never put it anywhere but the last line."
    )
    enable_keyword_fallback: bool = True
    prompt_version: str = INTENT_PROMPT_VERSION


DEFAULT_INTENT_CONFIG = MediaIntentConfig()

# Tolerant matcher: case-insensitive, allows inner whitespace, matches anywhere (the model does not
# always obey "last line"). Groups: (1) none | kind, (2) optional nature.
_SIGNAL_RE = re.compile(
    r"<<\s*MEDIA\s*:\s*(none|photo|video)\s*(?::\s*([a-z_]+)\s*)?>>",
    re.IGNORECASE,
)
# Used for stripping: also removes half-open/garbled leftovers so nothing signal-shaped reaches the
# user (FR-020-04). Deliberately broader than the parser.
_STRIP_RE = re.compile(r"<<\s*MEDIA\b[^>]*>{0,2}", re.IGNORECASE)


def intent_instruction(cfg: MediaIntentConfig = DEFAULT_INTENT_CONFIG) -> str:
    """The block appended to the system context so the model emits the signal (FR-020-01)."""
    return cfg.instruction


def parse_intent(reply: str, cfg: MediaIntentConfig = DEFAULT_INTENT_CONFIG) -> MediaIntent:
    """Extract the verdict from the model's reply. Never raises (FR-020-05)."""
    if not reply:
        return NO_INTENT
    matches = _SIGNAL_RE.findall(reply)
    if not matches:
        return NO_INTENT

    verdicts: list[MediaIntent] = []
    for raw_kind, raw_nature in matches:
        kind_token = (raw_kind or "").strip().lower()
        if kind_token == "none":
            verdicts.append(MediaIntent(requested=False, signal_present=True))
            continue
        try:
            kind = MediaKind(kind_token)
        except ValueError:  # unknown kind → treat the signal as unusable
            continue
        nature_token = (raw_nature or "").strip().lower()
        # D3: unknown or absent nature is NOT sfw — it goes to the gate side.
        nature = MediaNature.sfw if nature_token == MediaNature.sfw.value else MediaNature.intimate
        verdicts.append(
            MediaIntent(requested=True, kind=kind, nature=nature, signal_present=True)
        )

    if not verdicts:
        return NO_INTENT
    # D4: the LAST well-formed signal wins; if any requested verdict is gate-routed, that side wins.
    verdict = verdicts[-1]
    if verdict.requested and any(v.routes_to_gate for v in verdicts if v.requested):
        verdict = MediaIntent(
            requested=True, kind=verdict.kind, nature=MediaNature.intimate, signal_present=True
        )
    return verdict


def strip_signal(reply: str, cfg: MediaIntentConfig = DEFAULT_INTENT_CONFIG) -> str:
    """Remove every signal (and signal-shaped leftover) from the user-visible text (FR-020-04).

    Whitespace is normalised so removing a trailing line does not leave a dangling blank line, and
    removing an inline one does not leave a double space.
    """
    if not reply:
        return ""
    cleaned = _STRIP_RE.sub(" ", reply)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()


def resolve(
    reply: str,
    user_text: str,
    *,
    keyword_fallback,
    cfg: MediaIntentConfig = DEFAULT_INTENT_CONFIG,
) -> tuple[str, MediaIntent]:
    """One-stop post-process: (clean prose, verdict).

    Precedence (D2): a well-formed signal — positive **or** negative — is authoritative. The keyword
    fallback speaks only when no signal was present at all (model too old/ignored the instruction/
    runner degraded), so an obvious "пришли фото" is never left unanswered (FR-020-08).

    `keyword_fallback` is injected (the F-012 matcher) to keep this module free of vocabulary.
    """
    intent = parse_intent(reply, cfg)
    prose = strip_signal(reply, cfg)
    if not intent.signal_present and cfg.enable_keyword_fallback and keyword_fallback(user_text):
        # Fallback is deliberately conservative: photo, nature unknown → gate-routed (D3).
        intent = MediaIntent(
            requested=True, kind=MediaKind.photo, nature=None, signal_present=False
        )
    return prose, intent
