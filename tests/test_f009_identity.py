"""F-009 Appearance & Identity Consistency tests — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-009-appearance-identity-consistency.md`. The reference-
conditioning POLICY (services/imagegen/identity.py) runs for real: shot classification, reference
selection per shot type, forwarding onto the fixed F-008 job contract, strict per-persona
isolation, the no-reference safe path, and config-driven tuning are all automatable. Identity
*fidelity* on real images (same-person across settings / time / SFW↔intimate) is GPU/human-judged
and is left as explicit skips (same discipline as the F-008 suite).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.bot.models import Persona
from services.imagegen.contract import GenerationJob, GenParams, SlotMeta
from services.imagegen.identity import (
    IdentityPolicy,
    IdentityPolicySettings,
    NoReferenceAction,
    NoReferenceError,
    ShotType,
    face_reference_path,
    fullbody_reference_path,
)

IDENTITY_SRC = (
    Path(__file__).resolve().parent.parent / "services" / "imagegen" / "identity.py"
).read_text()


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────


def make_persona(slug: str = "testgirl", *, face: bool = True, body: bool = True) -> Persona:
    """A transient Persona carrying (or lacking) her reference anchors — no DB needed."""
    return Persona(
        name=slug.capitalize(),
        face_ref=face_reference_path(slug) if face else None,
        fullbody_ref=fullbody_reference_path(slug) if body else None,
    )


def face_job(key: str = "j1", slug: str = "testgirl") -> GenerationJob:
    return GenerationJob(
        job_key=key, persona_slug=slug, prompt="a casual selfie at the cafe",
        slot=SlotMeta(pose="mirror selfie", background="cafe", activity="coffee"),
        params=GenParams(steps=4, seed=1),
    )


def full_body_job(key: str = "j2", slug: str = "testgirl") -> GenerationJob:
    return GenerationJob(
        job_key=key, persona_slug=slug, prompt="a full body photo showing her outfit of the day",
        slot=SlotMeta(pose="standing full length", background="bedroom", activity="posing"),
        params=GenParams(steps=4, seed=2),
    )


def policy(**overrides) -> IdentityPolicy:
    return IdentityPolicy(IdentityPolicySettings(**overrides))


# ═══ FR-009-01 — persona has reference image(s) under media/<slug>/reference/ ════════════════════


def test_fr_009_01_01_face_ref_under_reference_dir():
    p = make_persona("alina")
    assert p.face_ref == "media/alina/reference/face.png"
    assert p.fullbody_ref == "media/alina/reference/fullbody.png"
    assert "/reference/" in p.face_ref and "/reference/" in p.fullbody_ref


def test_fr_009_01_02_reference_paths_resolve_to_real_files(tmp_path):
    slug = "vika"
    for rel in (face_reference_path(slug), fullbody_reference_path(slug)):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"img")
    assert (tmp_path / face_reference_path(slug)).exists()
    assert (tmp_path / fullbody_reference_path(slug)).is_file()


# ═══ FR-009-02 — every generation conditioned on the reference(s) (CRITICAL) ═════════════════════


def test_fr_009_02_01_job_conditioned_on_persona_reference():
    p = make_persona()
    job = face_job()
    selection = policy().apply(p, job)
    assert not selection.skipped
    assert job.references, "the persona's reference must condition the generation"
    assert p.face_ref in job.references


def test_fr_009_02_02_identity_fidelity_metric():
    pytest.skip("TC-FR-009-02-02: face-similarity metric on generated output vs reference — "
                "GPU/benchmark, out-of-band")


def test_fr_009_02_03_reference_path_present_and_correct_in_payload():
    p = make_persona()
    job = face_job()
    policy().apply(p, job)
    # survives the fixed-contract round-trip untouched (rides the job payload, FR-009-10)
    round_tripped = GenerationJob.from_json(job.to_json())
    assert round_tripped.references[0] == p.face_ref


# ═══ FR-009-03 — configurable conditioning policy (reference per shot, strength) ═════════════════


def test_fr_009_03_01_face_shot_selects_face_anchor():
    p = make_persona()
    sel = policy().select(p, face_job())
    assert sel.shot_type is ShotType.face
    assert sel.primary == p.face_ref


def test_fr_009_03_02_full_body_shot_attaches_the_body_anchor():
    p = make_persona()
    sel = policy().select(p, full_body_job())
    assert sel.shot_type is ShotType.full_body
    # face is ALWAYS Picture 1 (directive order); the body anchor is attached as Picture 2 for a
    # full-body shot (FR-009-19). It is *used*, just never primary.
    assert sel.references == [p.face_ref, p.fullbody_ref]
    assert p.fullbody_ref in sel.references


def test_fr_009_03_03_edited_config_changes_selection_and_strength():
    p = make_persona()
    job = face_job()
    # re-tune: treat "cafe" as a full-body trigger and change strengths — no code change
    tuned = policy(full_body_keywords=("cafe",), full_body_strength=0.5, face_strength=0.99)
    sel = tuned.select(p, job)
    assert sel.shot_type is ShotType.full_body  # keyword re-tuned selection
    assert sel.references == [p.face_ref, p.fullbody_ref]  # body anchor attached, face first
    assert sel.strength == 0.5                   # strength honored from config
    # and the default policy still classifies the same job as a face shot (face anchor only)
    default = policy().select(p, job)
    assert default.strength == 0.9 and default.references == [p.face_ref]


# ═══ FR-009-04 — identity holds across varied settings within a day (GPU/manual) ═════════════════


def test_fr_009_04_01_same_person_across_settings_benchmark():
    pytest.skip("TC-FR-009-04-01: same-person comparison across gym/cafe/home — GPU benchmark")


def test_fr_009_04_02_day_archive_one_woman_manual():
    pytest.skip("TC-FR-009-04-02: reviewer scans a day's archive — manual acceptance")


def test_fr_009_04_03_varied_settings_reuse_same_anchor():
    # Automatable core of FR-009-04: whatever the setting, the SAME identity anchor conditions it.
    p = make_persona()
    jobs = [
        GenerationJob(job_key="gym", persona_slug="testgirl", prompt="gym selfie",
                      slot=SlotMeta(location="gym")),
        GenerationJob(job_key="cafe", persona_slug="testgirl", prompt="cafe selfie",
                      slot=SlotMeta(location="cafe")),
        GenerationJob(job_key="home", persona_slug="testgirl", prompt="home selfie",
                      slot=SlotMeta(location="home")),
    ]
    anchors = {policy().select(p, j).primary for j in jobs}
    assert anchors == {p.face_ref}  # one consistent anchor across all settings


# ═══ FR-009-05 — identity holds across SFW↔intimate (GPU/manual) ════════════════════════════════


def test_fr_009_05_01_sfw_vs_intimate_same_person_benchmark():
    pytest.skip("TC-FR-009-05-01: SFW vs intimate compared for same face/body — GPU benchmark")


def test_fr_009_05_02_no_body_double_manual():
    pytest.skip("TC-FR-009-05-02: reviewer confirms no body-double across SFW↔intimate — manual")


def test_fr_009_05_03_sfw_vs_intimate_same_anchor():
    # Automatable core of FR-009-05: the anchor is chosen from shot framing, NOT the intimacy flag —
    # so intimate and SFW shots condition on the same identity (same girl, never a body-double).
    p = make_persona()
    sfw = GenerationJob(job_key="sfw", persona_slug="testgirl", prompt="a cafe selfie",
                        intimate=False)
    intimate = GenerationJob(job_key="int", persona_slug="testgirl", prompt="a cafe selfie",
                             intimate=True, intimacy_level=3)
    assert policy().select(p, sfw).primary == policy().select(p, intimate).primary == p.face_ref


# ═══ FR-009-06 — identity stable across days/weeks ══════════════════════════════════════════════


def test_fr_009_06_01_no_drift_benchmark():
    pytest.skip("TC-FR-009-06-01: identity drift across dated archives — GPU benchmark")


def test_fr_009_06_02_same_reference_yields_stable_anchor():
    # Deterministic: the same persona + shot always resolves to the same anchor (no drift in policy).
    p = make_persona()
    first = policy().select(p, face_job("day-1"))
    later = policy().select(p, face_job("day-30"))
    # a face shot conditions on the face anchor alone (FR-009-19); the point here is STABILITY
    assert first.references == later.references == [p.face_ref]


# ═══ FR-009-07 — strict per-persona isolation (CRITICAL) ════════════════════════════════════════


def test_fr_009_07_01_each_job_uses_only_its_own_reference():
    a, b = make_persona("alina"), make_persona("kira")
    ja, jb = face_job("a", "alina"), face_job("b", "kira")
    policy().apply(a, ja)
    policy().apply(b, jb)
    assert ja.references == [a.face_ref]  # face shots → face anchor only (FR-009-19)
    assert jb.references == [b.face_ref]
    assert not (set(ja.references) & set(jb.references))  # zero overlap


def test_fr_009_07_02_no_persona_reference_used_for_another():
    roster = [make_persona(s) for s in ("alina", "kira", "mia", "vika", "sofia")]
    pol = policy()
    for owner in roster:
        job = face_job("j", owner.name.lower())
        pol.apply(owner, job)
        others = {r for p in roster if p is not owner for r in (p.face_ref, p.fullbody_ref)}
        assert others.isdisjoint(job.references)  # never another persona's anchor


def test_fr_009_07_03_no_identity_blur_benchmark():
    pytest.skip("TC-FR-009-07-03: two personas' outputs compared for identity blur — GPU benchmark")


# ═══ FR-009-08 — no-reference behavior defined and safe (CRITICAL) ══════════════════════════════


def test_fr_009_08_01_no_reference_skipped_or_placeholder():
    p = make_persona(face=False, body=False)
    skip_sel = policy().select(p, face_job())
    assert skip_sel.skipped and skip_sel.references == []
    ph = policy(no_reference_action=NoReferenceAction.placeholder,
                placeholder_reference="media/_placeholder/reference/face.png")
    ph_sel = ph.select(p, face_job())
    assert not ph_sel.skipped
    assert ph_sel.references == ["media/_placeholder/reference/face.png"]


def test_fr_009_08_02_no_wrong_identity_published():
    p = make_persona(face=False, body=False)
    job = face_job()
    sel = policy().apply(p, job)
    assert sel.skipped and job.references == []  # reference-less → engine rejects, never wrong face
    # strict callers get a defined exception rather than a silent skip
    with pytest.raises(NoReferenceError):
        policy().require(p, face_job())


def test_fr_009_08_03_full_body_falls_back_to_face_anchor_safely():
    # A full-figure shot for a persona with only a face anchor uses the face anchor (right identity),
    # never nothing and never a placeholder.
    p = make_persona(face=True, body=False)
    sel = policy().select(p, full_body_job())
    assert not sel.skipped
    assert sel.references == [p.face_ref]


# ═══ FR-009-09 — references authored via Persona Studio (consumed, not captured) ════════════════


def test_fr_009_09_01_studio_wired_refs_are_consumed():
    # Simulate a Studio-provisioned persona (refs already wired) — the policy consumes them as-is.
    p = Persona(name="Studio", face_ref="media/studio/reference/face.png",
                fullbody_ref="media/studio/reference/fullbody.png")
    job = face_job(slug="studio")
    policy().apply(p, job)
    assert job.references[0] == p.face_ref


def test_fr_009_09_02_policy_consumes_not_captures():
    # F-009 must not implement upload/capture/persistence of references — it only reads them.
    src = IDENTITY_SRC.lower()
    for banned in ("upload", "def save", "open(", ".write_bytes", ".write_text", "shutil.copy"):
        assert banned not in src, f"identity policy must not author references: {banned}"


# ═══ FR-009-10 — conditioning through the fixed F-008 job contract (model-agnostic) ═════════════


def test_fr_009_10_01_conditioning_rides_the_job_payload():
    p = make_persona()
    job = face_job()
    policy().apply(p, job)
    # the ONLY thing written is the contract's references field; it serializes with the job
    assert '"references"' in job.to_json()
    assert p.face_ref in job.to_json()


def test_fr_009_10_02_no_model_glue_in_policy():
    # Model-agnostic: the policy imports no model code (torch/ComfyUI/HTTP) — pure contract usage.
    src = IDENTITY_SRC.lower()
    for banned in ("import torch", "diffusers", "comfyui", "urllib.request", "subprocess"):
        assert banned not in src, f"identity policy leaks model glue: {banned}"


# ═══ NFR-009-01 — identity fidelity (CRITICAL, human/metric-judged) ═════════════════════════════


def test_nfr_009_01_01_same_person_rate_benchmark():
    pytest.skip("TC-NFR-009-01-01: same-person rate over a labeled set — GPU/metric benchmark")


def test_nfr_009_01_02_face_clearly_hers_manual():
    pytest.skip("TC-NFR-009-01-02: reviewer confirms the face is clearly hers — manual acceptance")


def test_nfr_009_01_03_hard_angles_fidelity_benchmark():
    pytest.skip("TC-NFR-009-01-03: fidelity under hard angles/lighting — GPU benchmark")


# ═══ NFR-009-02 — consistency across settings ═══════════════════════════════════════════════════


def test_nfr_009_02_01_same_person_across_backgrounds_benchmark():
    pytest.skip("TC-NFR-009-02-01: same-person across varied backgrounds/poses — GPU benchmark")


# ═══ NFR-009-03 — consistency over time ═════════════════════════════════════════════════════════


def test_nfr_009_03_01_no_drift_over_time_benchmark():
    pytest.skip("TC-NFR-009-03-01: no drift across dated archives — GPU benchmark")


# ═══ NFR-009-04 — per-persona isolation provable (CRITICAL) ═════════════════════════════════════


def test_nfr_009_04_01_no_cross_persona_contamination():
    # Probe the whole roster: every job carries strictly its own anchors, nothing from anyone else.
    roster = [make_persona(s) for s in ("alina", "kira", "mia", "vika", "sofia", "nadia")]
    pol = policy()
    used: dict[str, set[str]] = {}
    for owner in roster:
        job = full_body_job("j", owner.name.lower())
        pol.apply(owner, job)
        used[owner.name] = set(job.references)
    # each persona's used set is exactly her own two anchors and disjoint from all others
    for owner in roster:
        assert used[owner.name] == {owner.face_ref, owner.fullbody_ref}
    all_sets = list(used.values())
    for i in range(len(all_sets)):
        for j in range(i + 1, len(all_sets)):
            assert all_sets[i].isdisjoint(all_sets[j])


# ═══ NFR-009-05 — model-agnostic conditioning ══════════════════════════════════════════════════


def test_nfr_009_05_01_identity_holds_via_fixed_contract_across_swap():
    # The policy output depends only on persona + job, never on which backend (A/B) will run it.
    p = make_persona()
    job_a = face_job("swap-a")
    job_b = face_job("swap-b")
    sel_a = policy().apply(p, job_a)
    sel_b = policy().apply(p, job_b)
    assert sel_a.references == sel_b.references == job_a.references == job_b.references


# ═══ NFR-009-06 — realism preserved alongside identity (manual) ═════════════════════════════════


def test_nfr_009_06_01_identity_and_realism_manual():
    pytest.skip("TC-NFR-009-06-01: reviewer confirms it's both her and realistic — manual")


# ═══ NFR-009-07 — config-driven ════════════════════════════════════════════════════════════════


def test_nfr_009_07_01_config_honored_without_code_change(monkeypatch):
    # Selection + strength are re-tunable purely via env (the pydantic-settings surface).
    monkeypatch.setenv("IDENTITY_FACE_STRENGTH", "0.42")
    monkeypatch.setenv("IDENTITY_INCLUDE_SECONDARY_REFERENCE", "false")
    pol = IdentityPolicy(IdentityPolicySettings())
    sel = pol.select(make_persona(), face_job())
    assert sel.strength == 0.42               # strength from env
    assert sel.references == [make_persona().face_ref]  # secondary suppressed by config


def test_nfr_009_07_02_no_reference_action_config_driven():
    p = make_persona(face=False, body=False)
    assert policy(no_reference_action=NoReferenceAction.skip).select(p, face_job()).skipped
    assert not policy(
        no_reference_action=NoReferenceAction.placeholder,
        placeholder_reference="media/_ph/reference/face.png",
    ).select(p, face_job()).skipped


# ═══ User-story acceptance (manual / GPU) ═══════════════════════════════════════════════════════


@pytest.mark.parametrize("tc", [
    "TC-US-009-01-01 A8: varied shots are obviously the same woman",
    "TC-US-009-02-01 A3: over weeks her face/figure stay exactly consistent",
    "TC-US-009-03-01 B1: upload references in Studio; every shot is that exact woman",
    "TC-US-009-04-01 operator: across the 10-persona roster, each stays distinctly herself",
    "TC-US-009-05-01 A3/A8: intimate shots are the same girl as her SFW photos",
])
def test_us_009_manual_gpu_acceptance(tc):
    pytest.skip(f"{tc} — manual GPU/human acceptance, run out-of-band")
