"""F-013 Dynamic Persona Presentation tests — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-013-dynamic-persona-presentation.md`. The greeting composition,
archive photo selection, single-combined-message delivery, cross-open variation, SFW-only,
hot-path-free, empty-archive fallback, per-persona voice and the F-001 boundary run for real against
the shared in-memory DB with planted, tag-carrying assets and frozen local times; greeting↔photo
coherence, identity and pure-latency benchmarks are human/GPU/perf-judged and explicitly skipped
(same discipline as the rest of the suite). Every test id embeds its FR-/NFR-/US- id.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import json
import pytest
from sqlalchemy import func, select

from services.bot.domain import presentation
from services.bot.domain.humanize import CommSettings
from services.bot.handlers import onboarding as ob
from services.bot.i18n import t
from services.bot.models import DailyPlan, MediaAsset, MediaJob, MediaKind, Persona

# A fixed "now" whose UTC hour == local hour for a UTC persona, so frozen times are unambiguous.
NOON = datetime(2026, 7, 17, 12, 30, tzinfo=timezone.utc)
MORNING = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
LATE_NIGHT = datetime(2026, 7, 17, 23, 30, tzinfo=timezone.utc)


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────


async def make_persona(db, name="Nadia", tz="UTC", language="en", comm=None) -> Persona:
    p = Persona(name=name, timezone=tz, language=language,
                comm_settings_json=json.dumps(comm) if comm else None)
    db.add(p)
    await db.flush()
    return p


async def plant_asset(db, persona, med_id, *, time_of_day="", activity="",
                      intimate=False, intimacy_level=0, created_at=NOON,
                      kind=MediaKind.photo) -> MediaAsset:
    meta = {"time_of_day": time_of_day, "activity": activity}
    a = MediaAsset(
        id=med_id, persona_id=persona.id, kind=kind, intimate=intimate,
        intimacy_level=intimacy_level, storage_ref=f"media/{persona.name.lower()}/photos/{med_id}.png",
        meta_json=json.dumps(meta), created_at=created_at,
    )
    db.add(a)
    await db.flush()
    return a


async def plant_plan(db, persona, plan_text, date="2026-07-17") -> DailyPlan:
    row = DailyPlan(persona_id=persona.id, date=date, plan_text=plan_text)
    db.add(row)
    await db.flush()
    return row


def fake_message(tg_id: int, lang="en", text=None):
    m = MagicMock(name="Message")
    m.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    m.chat = SimpleNamespace(id=tg_id)
    m.text = text
    m.photo = None
    m.answer = AsyncMock()
    m.answer_photo = AsyncMock()
    m.delete = AsyncMock()
    return m


def fake_callback(tg_id: int, data: str, lang="en"):
    cb = MagicMock(name="CallbackQuery")
    cb.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    cb.data = data
    cb.message = fake_message(tg_id, lang)
    cb.answer = AsyncMock()
    return cb


@pytest.fixture(autouse=True)
def _clear_handler_state():
    ob._intro_msg_ids.clear()
    ob._opener_sent_at.clear()
    yield
    ob._intro_msg_ids.clear()
    ob._opener_sent_at.clear()


GENTLE = dict(register="gentle", emoji_frequency=0.1, slang_level=0.1)   # shy → soft, no emoji
BUBBLY = dict(register="casual", emoji_frequency=0.7, slang_level=0.7)   # bubbly → peppy + emoji


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-01 — Time/activity-aware greeting in her voice
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_01_01_greeting_reflects_midday_cafe_moment(db):
    """TC-FR-013-01-01 — a midday cafe slot yields a greeting about that moment + time."""
    p = await make_persona(db, tz="UTC")
    await plant_plan(db, p, "12:00 lunch break at a cafe")
    card = await presentation.compose_presentation(db, p, media_root="/tmp/none", now=NOON, seed=1)
    assert "cafe" in card.text.lower()               # her current activity is woven in
    # midday phrasing (a break), not a morning "just woke up" line
    assert any(w in card.text.lower() for w in ("break", "breather"))


async def test_tc_fr_013_01_02_slot_and_local_time_drive_text(db):
    """TC-FR-013-01-02 — F-006 slot + local time drive the greeting text (pure compose)."""
    p = await make_persona(db, tz="UTC")
    morning = presentation.compose_greeting(p, "on my morning run", MORNING, seed=0)
    night = presentation.compose_greeting(p, "on my morning run", LATE_NIGHT, seed=0)
    assert presentation.narrative_period(MORNING.hour) == "early_morning"
    assert presentation.narrative_period(LATE_NIGHT.hour) == "night"
    assert "run" in morning.lower()                  # activity woven
    assert morning != night                          # time of day changes the wording


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-02 — Paired with a fitting archive photo
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_02_01_context_matching_photo_selected(db, tmp_path):
    """TC-FR-013-02-01 — today's archive yields a context-matching photo for the moment."""
    p = await make_persona(db)
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="morning")
    match = await plant_asset(db, p, "MED-nadia-00002", time_of_day="afternoon", activity="cafe")
    card = await presentation.compose_presentation(
        db, p, media_root=str(tmp_path), now=NOON, seed=0)  # NOON → afternoon photo period
    assert card.asset_id == match.id
    assert card.photo_ref is not None and card.photo_ref.endswith("MED-nadia-00002.png")


async def test_tc_fr_013_02_02_uses_f012_style_tag_matching(db):
    """TC-FR-013-02-02 — selection scores by F-012-style time_of_day/activity tag matching."""
    p = await make_persona(db)
    hit = await plant_asset(db, p, "MED-nadia-00001", time_of_day="afternoon", activity="cafe coffee")
    miss = await plant_asset(db, p, "MED-nadia-00002", time_of_day="night")
    s_hit = presentation._score_asset(hit, "afternoon", "midday", "grabbing coffee")
    s_miss = presentation._score_asset(miss, "afternoon", "midday", "grabbing coffee")
    assert s_hit > s_miss                            # matching tags score higher


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-03 — One combined message (no double nudge)
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_03_01_one_message_with_photo_and_keyboard(db, tmp_path):
    """TC-FR-013-03-01 — greeting delivered as exactly one message with photo + keyboard."""
    p = await make_persona(db)
    img = tmp_path / "welcome.png"
    img.write_bytes(b"\x89PNG\r\n")
    bot = AsyncMock()
    kind = await ob.send_persona_intro(
        bot, 500, p, reply_markup=MagicMock(name="kb"),
        opener="hey it's Nadia, afternoon's flying by. what's up? 🙂", photo_ref=str(img))
    assert kind == "photo"
    bot.send_photo.assert_awaited_once()             # ONE outbound message
    assert bot.send_photo.await_args.kwargs.get("caption")        # caption rides along
    assert bot.send_photo.await_args.kwargs.get("reply_markup") is not None  # keyboard rides along
    bot.send_message.assert_not_awaited()            # no separate follow-up


async def test_tc_fr_013_03_02_no_separate_follow_up_message(db):
    """TC-FR-013-03-02 — no separate 'say something' follow-up: one send, no message.answer."""
    p = await make_persona(db)
    from services.bot.domain.users import get_or_create_user
    await get_or_create_user(db, 501, "en")
    bot = AsyncMock()
    cb = fake_callback(501, data=f"startchat:{p.id}")
    await ob.on_start_chat(cb, db, bot)
    assert bot.send_message.await_count == 1          # exactly one opener (empty archive → text)
    bot.send_photo.assert_not_awaited()
    cb.message.answer.assert_not_awaited()            # no second nudge message


async def test_tc_fr_013_03_03_keyboard_rides_on_same_text_message(db):
    """TC-FR-013-03-03 — when a keyboard is needed (text-only greeting) it rides the same message."""
    p = await make_persona(db)
    bot = AsyncMock()
    await ob.send_persona_intro(bot, 502, p, reply_markup=MagicMock(name="kb"),
                                opener="hey it's Nadia. what's up?", photo_ref=None)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs.get("reply_markup") is not None


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-04 — Varies across opens (not a fixed promo)
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_04_01_different_times_differ(db, tmp_path):
    """TC-FR-013-04-01 — opens at different times give a different greeting + photo."""
    p = await make_persona(db)
    morn = await plant_asset(db, p, "MED-nadia-00001", time_of_day="morning")
    night = await plant_asset(db, p, "MED-nadia-00002", time_of_day="night")
    a = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=MORNING, seed=0)
    b = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=LATE_NIGHT, seed=0)
    assert a.text != b.text                           # greeting differs by time
    assert a.asset_id == morn.id and b.asset_id == night.id  # photo follows the moment


def test_tc_fr_013_04_02_same_slot_varies_within_reason():
    """TC-FR-013-04-02 — two opens in the same slot are not a byte-identical promo (seeded variety)."""
    p = Persona(name="Nadia", timezone="UTC", language="en")
    seen = {presentation.compose_greeting(p, "reading a book", NOON, seed=s) for s in range(30)}
    assert len(seen) > 1                              # phrasing varies across opens


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-05 — Identity-consistent + coherent photo
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_fr_013_05_01_welcome_photo_is_her_identity():
    """TC-FR-013-05-01 — identity of the welcome photo (F-009) is GPU/benchmark-judged."""
    pytest.skip("identity (F-009) is a GPU/benchmark-judged acceptance, not unit-automatable")


async def test_tc_fr_013_05_02_photo_tags_match_narrated_moment(db, tmp_path):
    """TC-FR-013-05-02 — the chosen photo's tags match the greeting's narrated moment."""
    p = await make_persona(db)
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="morning")
    evening = await plant_asset(db, p, "MED-nadia-00002", time_of_day="evening")
    now = datetime(2026, 7, 17, 19, 0, tzinfo=timezone.utc)  # evening
    card = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=now, seed=0)
    assert card.asset_id == evening.id


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-06 — Welcome photo always SFW
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_fr_013_06_01_is_sfw_rejects_intimate():
    """TC-FR-013-06-01 — an intimate asset is never SFW for the welcome moment."""
    clean = MediaAsset(id="a", persona_id=1, intimate=False, intimacy_level=0, storage_ref="x")
    spicy = MediaAsset(id="b", persona_id=1, intimate=True, intimacy_level=2, storage_ref="y")
    assert presentation.is_sfw(clean) is True
    assert presentation.is_sfw(spicy) is False


async def test_tc_fr_013_06_02_selection_excludes_intimate_assets(db, tmp_path):
    """TC-FR-013-06-02 — selecting for the welcome excludes intimate assets even if better-tagged."""
    p = await make_persona(db)
    # The intimate one carries the matching tag, but must still be skipped.
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="afternoon", intimate=True, intimacy_level=2)
    sfw = await plant_asset(db, p, "MED-nadia-00002", time_of_day="morning")
    card = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=NOON, seed=0)
    assert card.asset_id == sfw.id                    # the SFW (worse-tagged) asset is chosen


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-07 — No hot-path generation
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_07_01_no_image_generation_on_open(db, tmp_path):
    """TC-FR-013-07-01 — building the card enqueues/creates nothing: pure read, no generation."""
    p = await make_persona(db)
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="afternoon")
    before_assets = (await db.execute(select(func.count()).select_from(MediaAsset))).scalar_one()
    await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=NOON, seed=0)
    after_assets = (await db.execute(select(func.count()).select_from(MediaAsset))).scalar_one()
    jobs = (await db.execute(select(func.count()).select_from(MediaJob))).scalar_one()
    assert after_assets == before_assets              # no new asset generated
    assert jobs == 0                                  # no generation job enqueued


def test_tc_fr_013_07_02_latency_is_lookup_not_generation():
    """TC-FR-013-07-02 — pure-lookup latency vs generation is a GPU/perf benchmark."""
    pytest.skip("latency-vs-generation is a GPU/perf benchmark, not unit-automatable")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-08 — Graceful empty-archive fallback
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_08_01_empty_archive_config_default_greeting(db, tmp_path):
    """TC-FR-013-08-01 — an empty archive still yields a config-default greeting, no error."""
    p = await make_persona(db)
    card = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=NOON, seed=0)
    assert card.text                                  # a real greeting, not empty/an error
    assert card.photo_ref is None                     # text-only degrade
    assert card.asset_id is None


def test_tc_fr_013_08_02_empty_archive_never_broken_image():
    """TC-FR-013-08-02 — with no assets the selector returns no photo, never a broken ref."""
    chosen, ref = presentation.select_welcome_photo([], NOON, None, "/tmp/none", seed=0)
    assert chosen is None and ref is None


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-09 — Honors per-persona character
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_fr_013_09_01_shy_vs_bubbly_differ_in_tone():
    """TC-FR-013-09-01 — a shy (gentle) persona and a bubbly (bold) one read differently."""
    shy = Persona(name="Mila", timezone="UTC", language="en", comm_settings_json=json.dumps(GENTLE))
    bubbly = Persona(name="Mila", timezone="UTC", language="en", comm_settings_json=json.dumps(BUBBLY))
    emoji = presentation._PERIOD_EMOJI[presentation.narrative_period(NOON.hour)]
    g_shy = presentation.compose_greeting(shy, None, NOON, seed=0)
    g_bubbly = presentation.compose_greeting(bubbly, None, NOON, seed=0)
    assert g_shy != g_bubbly
    assert emoji in g_bubbly and emoji not in g_shy   # only the emoji-using persona gets emoji


async def test_tc_fr_013_09_02_edited_voice_config_changes_tone(db):
    """TC-FR-013-09-02 — editing the persona's voice config changes tone, no code change."""
    p = await make_persona(db, comm=GENTLE)
    before = presentation.compose_greeting(p, None, NOON, seed=0)
    p.comm_settings_json = json.dumps(BUBBLY)         # config edit only
    after = presentation.compose_greeting(p, None, NOON, seed=0)
    assert before != after


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-10 — Content-only; navigation stays F-001
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_fr_013_10_01_composes_content_not_navigation():
    """TC-FR-013-10-01 — F-013 composes content; it owns no gallery/router/navigation."""
    card = presentation.PresentationCard(text="hi", photo_ref=None, asset_id=None)
    assert set(vars(card)) == {"text", "photo_ref", "asset_id"}  # content only, no keyboard/nav
    assert not hasattr(presentation, "router")        # no handlers/navigation live here
    assert not hasattr(presentation, "gallery_card_view")


async def test_tc_fr_013_10_02_f001_selection_supplies_f013_card(db):
    """TC-FR-013-10-02 — completing F-001 selection sends the F-013 card, not the static opener."""
    p = await make_persona(db)
    from services.bot.domain.users import get_or_create_user
    await get_or_create_user(db, 601, "en")
    bot = AsyncMock()
    cb = fake_callback(601, data=f"startchat:{p.id}")
    await ob.on_start_chat(cb, db, bot)
    sent = bot.send_message.await_args.args[1]
    assert sent != t("intro_opener", p.language, name=p.name)  # dynamic F-013 greeting, not static
    assert p.name in sent                              # still the selected persona


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FR-013-11 — Hands off to normal chat after greeting
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_fr_013_11_01_hands_off_to_normal_chat(db):
    """TC-FR-013-11-01 — after the greeting a normal reply is not captured by onboarding (F-002/3)."""
    p = await make_persona(db)
    from services.bot.domain.sessions import get_active_session
    from services.bot.domain.users import get_or_create_user
    user, _ = await get_or_create_user(db, 602, "en")
    bot = AsyncMock()
    await ob.on_start_chat(fake_callback(602, data=f"startchat:{p.id}"), db, bot)
    assert (await get_active_session(db, user.id)) is not None  # session live for F-002/F-003
    # onboarding only claims the '💋 Choose Lady' label; a normal reply falls through to chat.
    assert "hi there, how are you?" not in ob._CHOOSE_LADY_LABELS


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-01 — Instant (CRITICAL)
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_nfr_013_01_01_no_generation_latency():
    """TC-NFR-013-01-01 — zero generation latency is a GPU/perf benchmark."""
    pytest.skip("generation-latency benchmark is GPU/perf-judged, not unit-automatable")


async def test_tc_nfr_013_01_02_card_is_lookup_plus_compose_only(db, tmp_path):
    """TC-NFR-013-01-02 — the card is built from a lookup + compose, touching no generation queue."""
    p = await make_persona(db)
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="afternoon")
    card = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=NOON, seed=0)
    assert card.text and card.photo_ref               # produced from existing data
    assert (await db.execute(select(func.count()).select_from(MediaJob))).scalar_one() == 0


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-02 — Freshness/variety
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_nfr_013_02_01_repeated_opens_visibly_vary():
    """TC-NFR-013-02-01 — across repeated opens the greeting visibly varies."""
    p = Persona(name="Nadia", timezone="UTC", language="en")
    variants = {presentation.compose_greeting(p, None, NOON, seed=s) for s in range(40)}
    assert len(variants) >= 2


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-03 — Coherence (greeting ↔ photo)
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_nfr_013_03_01_greeting_and_photo_agree():
    """TC-NFR-013-03-01 — greeting↔photo coherence is human-judged on a sample."""
    pytest.skip("greeting↔photo coherence is human-judged, not unit-automatable")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-04 — Identity
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_nfr_013_04_01_welcome_photo_is_her():
    """TC-NFR-013-04-01 — welcome-photo identity is a GPU/benchmark metric."""
    pytest.skip("welcome-photo identity is GPU/benchmark-judged, not unit-automatable")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-05 — Single-message UX
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_nfr_013_05_01_exactly_one_outbound_message(db):
    """TC-NFR-013-05-01 — the greeting is exactly one outbound message (no double nudge)."""
    p = await make_persona(db)
    from services.bot.domain.users import get_or_create_user
    await get_or_create_user(db, 603, "en")
    bot = AsyncMock()
    cb = fake_callback(603, data=f"startchat:{p.id}")
    await ob.on_start_chat(cb, db, bot)
    total = bot.send_message.await_count + bot.send_photo.await_count + cb.message.answer.await_count
    assert total == 1


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-06 — Graceful fallback
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_nfr_013_06_01_empty_archive_no_error_or_broken_image(db):
    """TC-NFR-013-06-01 — opening with an empty archive never errors or shows a broken image."""
    p = await make_persona(db)
    from services.bot.domain.users import get_or_create_user
    await get_or_create_user(db, 604, "en")
    bot = AsyncMock()
    cb = fake_callback(604, data=f"startchat:{p.id}")
    await ob.on_start_chat(cb, db, bot)               # no exception
    bot.send_message.assert_awaited_once()            # text greeting
    bot.send_photo.assert_not_awaited()               # no (broken) image attempted


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-07 — Config-driven
# ════════════════════════════════════════════════════════════════════════════════════════════════


def test_tc_nfr_013_07_01_greeting_style_is_config_driven():
    """TC-NFR-013-07-01 — greeting style honors edited config with no code change (emoji toggle)."""
    quiet = Persona(name="Nadia", timezone="UTC", language="en",
                    comm_settings_json=json.dumps(dict(emoji_frequency=0.0)))
    loud = Persona(name="Nadia", timezone="UTC", language="en",
                   comm_settings_json=json.dumps(dict(emoji_frequency=0.8)))
    emoji = presentation._PERIOD_EMOJI[presentation.narrative_period(NOON.hour)]
    assert emoji not in presentation.compose_greeting(quiet, None, NOON, seed=0)
    assert emoji in presentation.compose_greeting(loud, None, NOON, seed=0)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NFR-013-08 — Safety (SFW entry)
# ════════════════════════════════════════════════════════════════════════════════════════════════


async def test_tc_nfr_013_08_01_entry_never_picks_intimate(db, tmp_path):
    """TC-NFR-013-08-01 — even if ONLY intimate assets exist, the entry moment picks no photo."""
    p = await make_persona(db)
    await plant_asset(db, p, "MED-nadia-00001", time_of_day="afternoon", intimate=True, intimacy_level=3)
    card = await presentation.compose_presentation(db, p, media_root=str(tmp_path), now=NOON, seed=0)
    assert card.asset_id is None and card.photo_ref is None  # never an intimate asset at entry


# ════════════════════════════════════════════════════════════════════════════════════════════════
# User-story acceptance (manual / GPU)
# ════════════════════════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("tc", [
    "TC-US-013-01-01", "TC-US-013-02-01", "TC-US-013-03-01", "TC-US-013-04-01", "TC-US-013-05-01",
])
def test_user_story_acceptance_manual(tc):
    """US acceptance (alive-now conversion, time match, per-open freshness, identity, per-persona
    character) is human/GPU-judged on real sessions, not unit-automatable."""
    pytest.skip(f"{tc} is a human/GPU-judged user-story acceptance")
