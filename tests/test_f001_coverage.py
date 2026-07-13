"""F-001 supplementary coverage — automatable TC cases from the spec not covered by the other
F-001 test files (gallery active-only/order/locale, cyclic pagination boundaries, session
switch/reuse, restart persistence, tap-only flow). Manual-e2e and performance TCs are out of scope
here (they can't be fast unit tests).

Each test maps to a `TC-` id from developer files/tests/F-001-onboarding-persona-selection.md.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.bot.db import init_models, make_sessionmaker
from services.bot.domain.gallery import counter_label, cyclic_index, list_gallery_personas
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user, normalize_locale
from services.bot.models import Persona, PersonaStatus, Session, SessionState, User
from services.bot.personas_seed import seed_personas


# ── FR-001-05 — one per view + counter ─────────────────────────────────────────────────────────


def test_fr_001_05_01_counter_label_is_one_based():
    """TC-FR-001-05-01 — the '1/N' counter is 1-based over a 0-based index."""
    assert counter_label(0, 6) == "1/6"
    assert counter_label(5, 6) == "6/6"


async def test_fr_001_05_02_counter_total_equals_active_count(seeded_db):
    """TC-FR-001-05-02 — the counter total equals the number of personas shown."""
    personas = await list_gallery_personas(seeded_db, "ru")
    assert counter_label(0, len(personas)).endswith(f"/{len(personas)}")


# ── FR-001-06 — cyclic pagination ──────────────────────────────────────────────────────────────


def test_fr_001_06_01_next_from_last_wraps_to_first():
    """TC-FR-001-06-01 — ▶ past the last card wraps to the first."""
    assert cyclic_index(4, +1, 5) == 0


def test_fr_001_06_02_prev_from_first_wraps_to_last():
    """TC-FR-001-06-02 — ◀ before the first card wraps to the last."""
    assert cyclic_index(0, -1, 5) == 4


def test_nfr_001_10_01_cyclic_index_never_out_of_range():
    """TC-NFR-001-10-01 — rapidly repeated taps (any int) always land in [0, total)."""
    for cur in (-9, -1, 0, 3, 100):
        for delta in (-3, -1, 1, 4):
            assert 0 <= cyclic_index(cur, delta, 5) < 5


def test_fr_001_06_03_empty_gallery_pagination_rejected():
    """TC-FR-001-06-03 — paginating an empty gallery raises rather than dividing by zero."""
    with pytest.raises(ValueError):
        cyclic_index(0, 1, 0)


# ── FR-001-07 — active-only, stable order ──────────────────────────────────────────────────────


async def test_fr_001_07_01_inactive_personas_excluded(seeded_db):
    """TC-FR-001-07-01 — a persona set inactive is not listed in the gallery."""
    personas = await list_gallery_personas(seeded_db, "ru")
    victim = personas[0]
    victim.status = PersonaStatus.inactive
    await seeded_db.flush()
    after = await list_gallery_personas(seeded_db, "ru")
    assert victim.id not in [p.id for p in after]


async def test_fr_001_07_02_order_is_stable_across_calls(seeded_db):
    """TC-FR-001-07-02 — the persona order is identical on repeat visits."""
    a = [p.id for p in await list_gallery_personas(seeded_db, "en")]
    b = [p.id for p in await list_gallery_personas(seeded_db, "en")]
    assert a == b == sorted(a)  # deterministic, by id


async def test_fr_001_07_03_deactivation_drops_count(seeded_db):
    """TC-FR-001-07-03 — deactivating a persona drops the gallery count by one."""
    before = await list_gallery_personas(seeded_db, "en")
    before[0].status = PersonaStatus.inactive
    await seeded_db.flush()
    after = await list_gallery_personas(seeded_db, "en")
    assert len(after) == len(before) - 1


# ── FR-001-08 — locale-appropriate personas ────────────────────────────────────────────────────


async def test_fr_001_08_01_ru_user_sees_only_ru_personas(seeded_db):
    """TC-FR-001-08-01 — a ru-locale user is shown only Russian-speaking personas."""
    personas = await list_gallery_personas(seeded_db, "ru")
    assert personas and all(p.language == "ru" for p in personas)


async def test_fr_001_08_02_en_user_sees_only_en_personas(seeded_db):
    """TC-FR-001-08-02 — an en-locale user is shown only English personas."""
    personas = await list_gallery_personas(seeded_db, "en")
    assert personas and all(p.language == "en" for p in personas)


async def test_fr_001_08_03_unknown_locale_gallery_not_empty(seeded_db):
    """TC-FR-001-08-03 — an unsupported locale still gets a non-empty gallery (safe fallback)."""
    personas = await list_gallery_personas(seeded_db, "de")
    assert len(personas) > 0


@pytest.mark.parametrize("raw,expected", [
    ("ru", "ru"), ("RU", "ru"), ("ru-RU", "ru"), ("en_US", "en"), ("fr", "en"), (None, "en"),
])
def test_fr_001_08_03_locale_normalization(raw, expected):
    """TC-FR-001-08-03 — locale codes normalize to a supported locale or the default."""
    assert normalize_locale(raw) == expected


# ── FR-001-10 / FR-001-14 — session create / reuse / switch ────────────────────────────────────


async def test_fr_001_10_01_start_chat_creates_active_session(seeded_db):
    """TC-FR-001-10-01 — Start Chat creates an active SESSION(user, persona)."""
    user, _ = await get_or_create_user(seeded_db, 3001, "ru")
    p = (await list_gallery_personas(seeded_db, "ru"))[0]
    session, is_new = await start_or_switch_session(seeded_db, user.id, p.id)
    assert is_new and session.state == SessionState.active and session.persona_id == p.id


async def test_fr_001_10_02_reuse_same_persona_is_idempotent(seeded_db):
    """TC-FR-001-10-02 — Start Chat again on the same persona reuses the session (no new intro)."""
    user, _ = await get_or_create_user(seeded_db, 3002, "ru")
    p = (await list_gallery_personas(seeded_db, "ru"))[0]
    s1, new1 = await start_or_switch_session(seeded_db, user.id, p.id)
    s2, new2 = await start_or_switch_session(seeded_db, user.id, p.id)
    assert s1.id == s2.id and new1 is True and new2 is False
    count = (await seeded_db.execute(select(func.count()).select_from(Session))).scalar_one()
    assert count == 1


async def test_fr_001_14_01_switch_persona_switches_active_session(seeded_db):
    """TC-FR-001-14-01/02 — switching persona activates the new one and ends the old session."""
    user, _ = await get_or_create_user(seeded_db, 3003, "ru")
    personas = await list_gallery_personas(seeded_db, "ru")
    x, y = personas[0], personas[1]
    sx, _ = await start_or_switch_session(seeded_db, user.id, x.id)
    sy, new = await start_or_switch_session(seeded_db, user.id, y.id)
    assert new is True
    active = await get_active_session(seeded_db, user.id)
    assert active.persona_id == y.id
    await seeded_db.refresh(sx)
    assert sx.state == SessionState.ended  # prior session ended on switch


# ── FR-001-15 — existing user, no duplicate ────────────────────────────────────────────────────


async def test_fr_001_15_01_no_duplicate_user(seeded_db):
    """TC-FR-001-15-01 — repeat get-or-create for a telegram id makes no duplicate USER."""
    await get_or_create_user(seeded_db, 3004, "en")
    await get_or_create_user(seeded_db, 3004, "en")
    n = (await seeded_db.execute(
        select(func.count()).select_from(User).where(User.telegram_id == 3004))).scalar_one()
    assert n == 1


async def test_fr_001_15_03_no_session_means_no_active(seeded_db):
    """TC-FR-001-15-03 — a known user without a session has no active session (→ gallery on /start)."""
    user, _ = await get_or_create_user(seeded_db, 3005, "en")
    assert await get_active_session(seeded_db, user.id) is None


# ── NFR-001-08 — state survives a restart (durable persistence) ─────────────────────────────────


async def test_nfr_001_08_01_user_and_session_survive_restart(tmp_path):
    """TC-NFR-001-08-01/02 — a user + session persisted to disk are recovered after 'restart'."""
    db_url = f"sqlite+aiosqlite:///{tmp_path/'nl.sqlite3'}"

    # session 1: create user + session, then dispose the engine (simulate shutdown)
    eng1 = create_async_engine(db_url)
    await init_models(eng1)
    sm1: async_sessionmaker = make_sessionmaker(eng1)
    async with sm1() as db:
        await seed_personas(db)
        user, _ = await get_or_create_user(db, 4242, "ru")
        p = (await list_gallery_personas(db, "ru"))[0]
        await start_or_switch_session(db, user.id, p.id)
        await db.commit()
    await eng1.dispose()

    # session 2: fresh engine on the same file → the returning user + session are still there
    eng2 = create_async_engine(db_url)
    sm2 = make_sessionmaker(eng2)
    async with sm2() as db:
        again, created = await get_or_create_user(db, 4242, "ru")
        assert created is False  # recognized, not re-onboarded
        active = await get_active_session(db, again.id)
        assert active is not None
    await eng2.dispose()


# ── FR-001-19 / NFR-001-07 — tap-only flow, single back path ───────────────────────────────────


def test_fr_001_19_01_only_start_is_a_typed_command():
    """TC-FR-001-19-03 — the only slash-command handler is /start; everything else is button/text."""
    from aiogram.filters import CommandStart

    from services.bot.handlers import onboarding as ob

    command_handlers = [
        h for h in ob.router.message.handlers
        if any(isinstance(f.callback, CommandStart) for f in h.filters)
    ]
    assert len(command_handlers) == 1  # exactly /start, no other typed command needed


def test_nfr_001_07_01_reply_keyboard_single_back_action():
    """TC-NFR-001-07-01 — the persistent reply keyboard offers exactly one back path (Choose Lady)."""
    from services.bot import keyboards

    kb = keyboards.reply_kb("en")
    buttons = [b.text for row in kb.keyboard for b in row]
    assert len(buttons) == 1 and "Choose Lady" in buttons[0]
