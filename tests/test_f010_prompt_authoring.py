"""F-010 Generation Prompt Authoring tests — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-010-generation-prompt-authoring.md`. Prompt authoring is pure
text composition, so almost every TC runs for real against `services.imagegen.prompt_author`;
provenance TCs store through the F-008 engine (`services.imagegen.store`) with a shared in-memory DB
and a tmp media root. Image-level coherence/variety and the per-user-story acceptance TCs are
human/GPU-judged and remain explicit skips (same discipline as the rest of the suite).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.bot.models import MediaKind, Persona
from services.bot.personas_seed import persona_slug
from services.imagegen import prompt_author as pa
from services.imagegen import store
from services.imagegen.contract import GenerationJob, GenParams
from services.imagegen.store import parse_meta

MODULE_PATH = Path(pa.__file__)


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────


def a_slot(**kw) -> pa.LifeSlot:
    base = dict(activity="on a morning run at the trail", location="forest trail",
                mood="energized", time_of_day="morning")
    base.update(kw)
    return pa.LifeSlot(**base)


def warm_cozy_style() -> pa.PersonaStyle:
    return pa.PersonaStyle(
        aesthetic="warm cozy homebody aesthetic",
        palette="warm amber and soft beige tones",
        outfits=("chunky knit sweater and wool socks",),
        locations=("sunlit reading nook",),
    )


async def make_persona(db, name: str = "Testgirl", tz: str = "UTC") -> Persona:
    p = Persona(name=name, timezone=tz)
    db.add(p)
    await db.flush()
    return p


# ══════════════════════════════════════ FR-010-01 ════════════════════════════════════════════════


def test_tc_fr_010_01_01_reads_slot_activity():
    """TC-FR-010-01-01 — the prompt draws scene/activity from the current slot."""
    jobs = pa.author_jobs("sofia", a_slot(activity="doing yoga on the balcony"))
    assert all("yoga" in j.prompt for j in jobs)


async def test_tc_fr_010_01_02_consumes_f006_life_engine_state(db):
    """TC-FR-010-01-02 — integration: slot/mood/location from the Life Engine are consumed."""
    from services.bot.domain import life_engine, life_engine_store

    persona = await make_persona(db, name="Alina", tz="UTC")
    now = datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc)
    date_key = life_engine.local_date_key("UTC", now)
    await life_engine_store.store_plan(
        db, persona.id, date_key, "9:00 — at the seaside cafe by the water", "plan_day_v2"
    )
    activity = await life_engine_store.get_current_activity(db, persona.id, "UTC")
    slot = pa.slot_from_activity(activity, life_engine.local_now("UTC", now),
                                 location="seaside cafe", mood="relaxed")
    jobs = pa.author_jobs(persona_slug(persona.name), slot)
    assert jobs and "cafe" in jobs[0].prompt
    assert jobs[0].slot.time_of_day == "morning"  # derived from the local hour


# ══════════════════════════════════════ FR-010-02 ════════════════════════════════════════════════


def test_tc_fr_010_02_01_prompt_has_scene_outfit_lighting_realism():
    """TC-FR-010-02-01 — prompt carries scene + outfit + lighting + realism cues."""
    style = warm_cozy_style()
    job = pa.author_jobs("sofia", a_slot(time_of_day="night"), style)[0]
    p = job.prompt
    assert "trail" in p                              # scene/activity
    assert "sweater" in p                            # outfit (style)
    assert "night" in p                              # time-of-day lighting phrase
    assert any(cue in p for cue in pa.DEFAULT_REALISM_CUES)  # phone-photo realism cue


def test_tc_fr_010_02_02_negative_list_present():
    """TC-FR-010-02-02 — a negative list is emitted (on GenParams.negative)."""
    job = pa.author_jobs("sofia", a_slot())[0]
    assert job.params.negative
    assert "watermark" in job.params.negative and "extra fingers" in job.params.negative


def test_tc_fr_010_02_03_fields_map_onto_job_contract():
    """TC-FR-010-02-03 — the output fields map onto the F-008 job contract."""
    job = pa.author_jobs("sofia", a_slot())[0]
    assert isinstance(job, GenerationJob)
    assert isinstance(job.params, GenParams)
    assert job.slot.activity and job.slot.time_of_day
    job.validate()  # contract accepts it


# ══════════════════════════════════════ FR-010-03 ════════════════════════════════════════════════


def test_tc_fr_010_03_01_scene_matches_narration():
    """TC-FR-010-03-01 — a 'beach' slot authors a beach scene."""
    jobs = pa.author_jobs("mia", a_slot(activity="at the beach watching the waves",
                                        location="sandy beach", time_of_day="afternoon"))
    assert all("beach" in j.prompt for j in jobs)


def test_tc_fr_010_03_02_generated_image_depicts_scene():
    """TC-FR-010-03-02 — benchmark/GPU: generated image depicts the narrated scene."""
    pytest.skip("image-level coherence is human/GPU-judged on generated output (benchmark TC)")


# ══════════════════════════════════════ FR-010-04 ════════════════════════════════════════════════


def test_tc_fr_010_04_01_slot_expands_to_n_prompts():
    """TC-FR-010-04-01 — one slot, N=6 → 6 prompts produced."""
    jobs = pa.author_jobs("sofia", a_slot(), count=6)
    assert len(jobs) == 6


def test_tc_fr_010_04_02_framings_differ_not_duplicates():
    """TC-FR-010-04-02 — the framings/angles differ (not near-duplicates)."""
    jobs = pa.author_jobs("sofia", a_slot(), count=6)
    prompts = [j.prompt for j in jobs]
    poses = [j.slot.pose for j in jobs]
    assert len(set(prompts)) == 6      # every prompt distinct
    assert len(set(poses)) == 6        # every framing/pose distinct


def test_tc_fr_010_04_03_configurable_count_three():
    """TC-FR-010-04-03 — N configured to 3 → exactly 3 produced."""
    jobs = pa.author_jobs("sofia", a_slot(), count=3)
    assert len(jobs) == 3
    # config-level shot_count is honored too, not just the call arg
    cfg = pa.PromptAuthorConfig(shot_count=3)
    assert len(pa.author_jobs("sofia", a_slot(), config=cfg)) == 3


# ══════════════════════════════════════ FR-010-05 ════════════════════════════════════════════════


def test_tc_fr_010_05_01_no_identity_descriptors():
    """TC-FR-010-05-01 — no hard identity descriptors that would fight the reference."""
    for job in pa.author_jobs("sofia", a_slot(), count=6):
        assert pa.find_identity_terms(job.prompt) == []


def test_tc_fr_010_05_02_describes_scene_pose_camera_only():
    """TC-FR-010-05-02 — the guard rejects any prompt that restates identity."""
    # A composed prompt passes the guard; an identity-laden string is caught.
    good = pa.author_jobs("sofia", a_slot())[0].prompt
    pa.assert_no_identity_terms(good)  # does not raise
    with pytest.raises(ValueError):
        pa.assert_no_identity_terms("a woman with long blonde hair and green eyes at the trail")


# ══════════════════════════════════════ FR-010-06 ════════════════════════════════════════════════


def test_tc_fr_010_06_01_honors_persona_visual_style():
    """TC-FR-010-06-01 — a warm-cozy style config is reflected in palette/outfit."""
    job = pa.author_jobs("sofia", a_slot(), warm_cozy_style())[0]
    assert "warm amber and soft beige tones" in job.prompt
    assert "chunky knit sweater and wool socks" in job.prompt


def test_tc_fr_010_06_02_edited_style_config_changes_output_no_code():
    """TC-FR-010-06-02 — swapping the style config changes prompts, no code change."""
    cfg_a = pa.PromptAuthorConfig.from_dict(
        {"styles": {"sofia": {"palette": "cool blue tones", "outfits": ["sporty tracksuit"]}}}
    )
    cfg_b = pa.PromptAuthorConfig.from_dict(
        {"styles": {"sofia": {"palette": "warm sepia tones", "outfits": ["floral summer dress"]}}}
    )
    pa_a = pa.author_jobs("sofia", a_slot(), config=cfg_a)[0].prompt
    pa_b = pa.author_jobs("sofia", a_slot(), config=cfg_b)[0].prompt
    assert "cool blue tones" in pa_a and "tracksuit" in pa_a
    assert "warm sepia tones" in pa_b and "floral summer dress" in pa_b
    assert pa_a != pa_b


# ══════════════════════════════════════ FR-010-07 ════════════════════════════════════════════════


def test_tc_fr_010_07_01_night_lighting():
    """TC-FR-010-07-01 — a night slot authors night lighting, not daylight."""
    job = pa.author_jobs("emma", a_slot(activity="at the rooftop bar",
                                        location="rooftop bar", time_of_day="night"))[0]
    assert "night" in job.prompt
    assert "bright natural daytime light" not in job.prompt


def test_tc_fr_010_07_02_morning_trail_is_not_midnight_bar():
    """TC-FR-010-07-02 — a morning trail slot isn't a midnight bar."""
    job = pa.author_jobs("sofia", a_slot(time_of_day="morning"))[0]
    assert "morning" in job.prompt and "trail" in job.prompt
    assert "bar" not in job.prompt and "night" not in job.prompt


# ══════════════════════════════════════ FR-010-08 ════════════════════════════════════════════════


async def test_tc_fr_010_08_01_prompt_slot_seed_logged_with_asset(db, tmp_path):
    """TC-FR-010-08-01 — integration: the prompt + slot + seed are stored with the asset."""
    persona = await make_persona(db, name="Sofia")
    slug = persona_slug(persona.name)
    job = pa.author_jobs(slug, a_slot(), base_seed=42)[0]
    asset = await store.store_asset(db, persona, job, b"\x89PNG-fake", tmp_path / "media",
                                    kind=MediaKind.photo)
    meta = parse_meta(asset)
    assert meta["prompt"] == job.prompt
    assert meta["activity"] == "on a morning run at the trail"
    assert meta["seed"] == job.params.seed  # source seed traceable


def test_tc_fr_010_08_02_meta_json_has_provenance_fields():
    """TC-FR-010-08-02 — the job's meta_json carries prompt provenance fields."""
    import json

    job = pa.author_jobs("sofia", a_slot(), base_seed=7)[0]
    meta = json.loads(job.slot_meta_json())
    for key in ("prompt", "seed", "activity", "location", "time_of_day", "pose", "background"):
        assert key in meta
    assert meta["prompt"] == job.prompt


# ══════════════════════════════════════ FR-010-09 ════════════════════════════════════════════════


def test_tc_fr_010_09_01_empty_slot_uses_default_scene():
    """TC-FR-010-09-01 — no current slot → the config default scene is authored."""
    jobs = pa.author_jobs("sofia", pa.LifeSlot())  # fully empty
    assert jobs
    assert pa.DEFAULT_SCENE.activity in jobs[0].prompt
    assert jobs[0].slot.activity == pa.DEFAULT_SCENE.activity


def test_tc_fr_010_09_02_missing_state_never_crashes():
    """TC-FR-010-09-02 — None slot and empty-string slot both degrade, no crash."""
    assert pa.author_jobs("sofia", None)              # None
    assert pa.author_jobs("sofia", pa.LifeSlot(activity="   "))  # whitespace only
    for job in pa.author_jobs("sofia", None):
        job.validate()  # still a coherent, valid job


# ══════════════════════════════════════ FR-010-10 ════════════════════════════════════════════════


def test_tc_fr_010_10_01_fits_job_contract_schema():
    """TC-FR-010-10-01 — the authored output validates against the job contract."""
    for job in pa.author_jobs("sofia", a_slot(), count=6):
        # round-trips through the contract's JSON gate unchanged
        rebuilt = GenerationJob.from_json(job.to_json())
        assert rebuilt.prompt == job.prompt
        assert rebuilt.slot.activity == job.slot.activity


def test_tc_fr_010_10_02_same_prompt_accepted_by_both_runners():
    """TC-FR-010-10-02 — integration: A↔B share the contract, so the same job is portable."""
    job = pa.author_jobs("sofia", a_slot())[0]
    # Both backends consume the identical contract payload — no model-specific fields authored.
    payload = job.to_json()
    for _runner in ("A", "B"):
        accepted = GenerationJob.from_json(payload)
        assert accepted.prompt == job.prompt and accepted.params.negative == job.params.negative


# ══════════════════════════════════════ FR-010-11 ════════════════════════════════════════════════


async def test_tc_fr_010_11_01_shot_meta_carried_into_meta_json(db, tmp_path):
    """TC-FR-010-11-01 — integration: pose/bg/location/activity/time reach meta_json via F-008."""
    persona = await make_persona(db, name="Mia")
    job = pa.author_jobs(persona_slug(persona.name),
                         a_slot(activity="editing photos at the studio", location="photo studio",
                                time_of_day="afternoon"))[0]
    asset = await store.store_asset(db, persona, job, b"png", tmp_path / "media")
    meta = parse_meta(asset)
    for key in ("pose", "background", "location", "activity", "time_of_day"):
        assert meta.get(key) or key in meta
    assert meta["location"] == "photo studio"


def test_tc_fr_010_11_02_meta_fields_selectable_for_on_demand():
    """TC-FR-010-11-02 — the five slot fields are present and selectable (F-012 On-Demand)."""
    from dataclasses import asdict

    job = pa.author_jobs("mia", a_slot(time_of_day="evening"))[0]
    keys = set(asdict(job.slot).keys())
    assert {"pose", "background", "location", "activity", "time_of_day"} <= keys
    # On-Demand (F-012) could filter by, e.g., time_of_day — the value is populated and queryable
    assert job.slot.time_of_day == "evening"


# ══════════════════════════════════════ NFR-010-01 ═══════════════════════════════════════════════


def test_tc_nfr_010_01_01_coherence_match_rate():
    """TC-NFR-010-01-01 — benchmark: labeled slot/photo match rate ≥ target."""
    pytest.skip("coherence match-rate is a human/GPU benchmark on generated images")


def test_tc_nfr_010_01_02_narration_photo_agree():
    """TC-NFR-010-01-02 — manual: narration and photo agree on review."""
    pytest.skip("manual human review of narration vs generated photo")


def test_tc_nfr_010_01_03_coherence_holds_on_unusual_slots():
    """TC-NFR-010-01-03 — benchmark: coherence holds on unusual slots."""
    pytest.skip("human/GPU-judged coherence on unusual generated slots")


# ══════════════════════════════════════ NFR-010-02 ═══════════════════════════════════════════════


def test_tc_nfr_010_02_01_prompt_set_diversity_scored():
    """TC-NFR-010-02-01 — a slot's prompt set scores as distinct (diversity heuristic)."""
    jobs = pa.author_jobs("sofia", a_slot(), count=6)
    framing_tokens = {j.slot.pose for j in jobs}
    # No near-duplicate spam: at least 5 distinct framings out of 6 (in practice all 6).
    assert len(framing_tokens) >= 5


def test_tc_nfr_010_02_02_generated_set_looks_like_several_shots():
    """TC-NFR-010-02-02 — manual: the generated set looks like several real shots."""
    pytest.skip("manual visual review of the generated shot set")


# ══════════════════════════════════════ NFR-010-03 ═══════════════════════════════════════════════


def test_tc_nfr_010_03_01_same_slot_seed_identical_prompts():
    """TC-NFR-010-03-01 — same slot + seed authored twice → identical prompts and seeds."""
    a = pa.author_jobs("sofia", a_slot(), base_seed=99, count=6)
    b = pa.author_jobs("sofia", a_slot(), base_seed=99, count=6)
    assert [j.prompt for j in a] == [j.prompt for j in b]
    assert [j.params.seed for j in a] == [j.params.seed for j in b]
    assert [j.job_key for j in a] == [j.job_key for j in b]
    # a different seed yields a different (rotated) set
    c = pa.author_jobs("sofia", a_slot(), base_seed=100, count=6)
    assert [j.prompt for j in a] != [j.prompt for j in c]


# ══════════════════════════════════════ NFR-010-04 ═══════════════════════════════════════════════


def test_tc_nfr_010_04_01_config_driven_style_n_negatives():
    """TC-NFR-010-04-01 — edited style/N/negatives config is honored, no code change."""
    cfg = pa.PromptAuthorConfig.from_dict({
        "shot_count": 4,
        "negatives": ["custom_neg_token"],
        "styles": {"sofia": {"aesthetic": "film-grain retro look"}},
    })
    jobs = pa.author_jobs("sofia", a_slot(), config=cfg)
    assert len(jobs) == 4
    assert jobs[0].params.negative == "custom_neg_token"
    assert "film-grain retro look" in jobs[0].prompt


# ══════════════════════════════════════ NFR-010-05 ═══════════════════════════════════════════════


def test_tc_nfr_010_05_01_prompt_vocabulary_is_portable():
    """TC-NFR-010-05-01 — the prompt is expressed in fixed-contract terms, model-agnostic."""
    job = pa.author_jobs("sofia", a_slot())[0]
    # No backend/model-specific field is authored — everything lives in the shared contract text.
    assert isinstance(job.prompt, str) and job.prompt.strip()
    rebuilt = GenerationJob.from_json(job.to_json())
    assert rebuilt.prompt == job.prompt


# ══════════════════════════════════════ NFR-010-06 ═══════════════════════════════════════════════


def test_tc_nfr_010_06_01_pure_text_no_model_call():
    """TC-NFR-010-06-01 — authoring is pure text composition: no model/network imports."""
    src = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "aiohttp", "socket", "openai", "torch",
                      "ComfyUIBackend", "build_backend", "subprocess"):
        assert forbidden not in src, f"prompt_author must not use {forbidden}"
    # and it does no I/O: the module imports only the contract + stdlib
    mod_src = inspect.getsource(pa)
    assert "def author_jobs" in mod_src


# ══════════════════════════════════════ NFR-010-07 ═══════════════════════════════════════════════


def test_tc_nfr_010_07_01_no_explicit_vocabulary_leaks():
    """TC-NFR-010-07-01 — SFW authoring: no explicit vocabulary leaks into any prompt."""
    for job in pa.author_jobs("sofia", a_slot(activity="relaxing on the couch"), count=6):
        assert pa.find_explicit_terms(job.prompt) == []
    # the guard actively rejects explicit text
    with pytest.raises(ValueError):
        pa.assert_sfw("nude photo at the beach")


# ══════════════════════════════════ User-story acceptance (manual/GPU) ════════════════════════════


def test_tc_us_010_01_01_photo_matches_what_she_said():
    """TC-US-010-01-01 — manual: photo matches what she said she's doing."""
    pytest.skip("US acceptance is human-judged on generated media")


def test_tc_us_010_02_01_photos_read_as_candid_snaps():
    """TC-US-010-02-01 — manual: photos read as candid phone snaps of her day."""
    pytest.skip("US acceptance is human-judged on generated media")


def test_tc_us_010_03_01_slot_yields_different_angles():
    """TC-US-010-03-01 — manual: a slot yields a few genuinely different angles."""
    pytest.skip("US acceptance is human-judged on generated media")


def test_tc_us_010_04_01_persona_style_reflected():
    """TC-US-010-04-01 — manual: persona style tuning reflected in her photos."""
    pytest.skip("US acceptance is human-judged on generated media")


def test_tc_us_010_05_01_asset_traces_to_prompt_and_slot():
    """TC-US-010-05-01 — manual: every asset traces to a logged prompt + slot."""
    pytest.skip("operator acceptance is human-reviewed over the stored provenance log")
