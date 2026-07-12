"""F-001 onboarding — domain-layer tests (no Telegram needed).

Each test maps to a `TC-` id from developer files/tests/F-001-onboarding-persona-selection.md.
Handler/e2e-level tests (aiogram) are added separately.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from services.bot.domain.gallery import (
    counter_label,
    cyclic_index,
    list_gallery_personas,
)
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user, normalize_locale
from services.bot.models import Persona, PersonaStatus, Session, SessionState, User

# ── FR-001-01 / FR-001-15 — user get-or-create, no duplicates ────────────────────────────────


async def test_fr_001_01_01_creates_user_once(db):
    """TC-FR-001-01-01 — /start from a new id creates exactly one USER."""
    user, created = await get_or_create_user(db, telegram_id=111, locale="en")
    assert created is True
    assert user.telegram_id == 111
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1


async def test_fr_001_15_01_no_duplicate_on_repeat_start(db):
    """TC-FR-001-15-01 — repeat /start does not create a duplicate USER."""
    u1, c1 = await get_or_create_user(db, telegram_id=222, locale="en")
    u2, c2 = await get_or_create_user(db, telegram_id=222, locale="en")
    assert c1 is True and c2 is False
    assert u1.id == u2.id
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1


# ── FR-001-08 — locale handling ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [("ru", "ru"), ("ru-RU", "ru"), ("en-US", "en"), ("de", "en"), (None, "en"), ("", "en")],
)
def test_fr_001_08_03_locale_normalization(raw, expected):
    """TC-FR-001-08-03 — unknown/regional locales map to a supported default."""
    assert normalize_locale(raw) == expected


async def test_fr_001_08_01_ru_user_sees_ru_personas(seeded_db):
    """TC-FR-001-08-01 — a ru-locale user is shown Russian-speaking personas."""
    personas = await list_gallery_personas(seeded_db, user_locale="ru")
    assert personas, "gallery should not be empty"
    assert all(p.language == "ru" for p in personas)


async def test_fr_001_08_02_en_user_sees_en_personas(seeded_db):
    """TC-FR-001-08-02 — an en-locale user is shown English personas."""
    personas = await list_gallery_personas(seeded_db, user_locale="en")
    assert personas
    assert all(p.language == "en" for p in personas)


# ── FR-001-07 — active-only, deterministic stable order ─────────────────────────────────────


async def test_fr_001_07_01_only_active_and_stable_order(seeded_db):
    """TC-FR-001-07-01 — inactive personas are excluded; order is stable (by id)."""
    # Deactivate one EN persona.
    en = await list_gallery_personas(seeded_db, "en")
    target = en[0]
    target.status = PersonaStatus.inactive
    await seeded_db.commit()

    again = await list_gallery_personas(seeded_db, "en")
    assert target.id not in [p.id for p in again]
    assert [p.id for p in again] == sorted(p.id for p in again)  # stable/ascending


async def test_fr_001_07_02_order_stable_across_calls(seeded_db):
    """TC-FR-001-07-02 — repeated visits return the same order."""
    first = [p.id for p in await list_gallery_personas(seeded_db, "en")]
    second = [p.id for p in await list_gallery_personas(seeded_db, "en")]
    assert first == second


# ── FR-001-05 / FR-001-06 / NFR-001-10 — pagination ─────────────────────────────────────────


def test_fr_001_05_01_counter_label():
    """TC-FR-001-05-01 — counter renders 1-based '<index>/<total>'."""
    assert counter_label(0, 5) == "1/5"
    assert counter_label(4, 5) == "5/5"


@pytest.mark.parametrize(
    "frm,total,delta,to",
    [
        (0, 5, +1, 1),  # UC-001-03: 1/5 ▶ -> 2
        (1, 5, +1, 2),  # 2 ▶ -> 3
        (1, 5, -1, 0),  # 2 ◀ -> 1
        (0, 5, -1, 4),  # 1 ◀ -> 5 (wrap back)
        (4, 5, +1, 0),  # 5 ▶ -> 1 (wrap forward)
    ],
)
def test_fr_001_06_cyclic_navigation(frm, total, delta, to):
    """TC-FR-001-06-01/02 (+ UC-001-03 outline) — ◀/▶ wraps at both ends."""
    assert cyclic_index(frm, delta, total) == to


@pytest.mark.parametrize("delta", [3, 7, -6, 11, -13, 100, -100])
def test_nfr_001_10_01_index_never_out_of_range(delta):
    """TC-NFR-001-10-01 — rapid/large repeated nav can never desync (stays in [0,total))."""
    total = 5
    idx = cyclic_index(0, delta, total)
    assert 0 <= idx < total


# ── FR-001-10 / FR-001-14 / FR-001-17 — sessions ────────────────────────────────────────────


async def _user_and_two_personas(db):
    user, _ = await get_or_create_user(db, telegram_id=999, locale="en")
    en = await list_gallery_personas(db, "en")
    return user, en[0], en[1]


async def test_fr_001_10_01_start_creates_active_session(seeded_db):
    """TC-FR-001-10-01 — Start Chat creates an active SESSION for (user, persona)."""
    user, p1, _ = await _user_and_two_personas(seeded_db)
    session, is_new_intro = await start_or_switch_session(seeded_db, user.id, p1.id)
    assert is_new_intro is True
    assert session.state == SessionState.active
    assert session.user_id == user.id and session.persona_id == p1.id


async def test_fr_001_17_01_double_tap_idempotent(seeded_db):
    """TC-FR-001-17-01 — double Start Chat on the same persona -> one session, no second intro."""
    user, p1, _ = await _user_and_two_personas(seeded_db)
    s1, intro1 = await start_or_switch_session(seeded_db, user.id, p1.id)
    s2, intro2 = await start_or_switch_session(seeded_db, user.id, p1.id)
    assert s1.id == s2.id
    assert intro1 is True and intro2 is False  # second tap does not re-send the intro
    count = (
        await seeded_db.execute(select(func.count()).select_from(Session))
    ).scalar_one()
    assert count == 1


async def test_fr_001_14_01_switch_persona(seeded_db):
    """TC-FR-001-14-01/02 — switching persona ends the old session and activates the new one."""
    user, p1, p2 = await _user_and_two_personas(seeded_db)
    await start_or_switch_session(seeded_db, user.id, p1.id)
    s2, intro2 = await start_or_switch_session(seeded_db, user.id, p2.id)
    assert intro2 is True and s2.persona_id == p2.id

    active = await get_active_session(seeded_db, user.id)
    assert active is not None and active.persona_id == p2.id  # exactly one active, the new one

    active_count = (
        await seeded_db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.state == SessionState.active)
        )
    ).scalar_one()
    assert active_count == 1


async def test_fr_001_20_01_media_belongs_to_selected_persona(seeded_db):
    """TC-FR-001-20-01 — the session (and thus its intro media) is linked to the chosen persona."""
    user, p1, _ = await _user_and_two_personas(seeded_db)
    session, _ = await start_or_switch_session(seeded_db, user.id, p1.id)
    persona = (
        await seeded_db.execute(select(Persona).where(Persona.id == session.persona_id))
    ).scalar_one()
    assert persona.id == p1.id
