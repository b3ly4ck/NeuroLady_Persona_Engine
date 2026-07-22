"""Anchor-framing fixes (F-009 FR-009-15..19, F-010 FR-010-17/18).

The second live run exposed three defects traced to how the reference anchors are FRAMED (not the
prompt): weak identity from a loose face crop, wardrobe leaking from a full styled body anchor, and
the subject rendered twice. These tests pin the code fixes: face is always Picture 1, the body
anchor is attached only for full-body shots, the directive forbids duplication and outfit copying,
negatives include duplication terms, and the anchor-prep crops/validation behave.
"""
from __future__ import annotations

from pathlib import Path

from services.imagegen.anchor_prep import (
    head_crop_body,
    tighten_face,
    validate_body_anchor,
)
from services.imagegen.contract import GenerationJob, SlotMeta
from services.imagegen.identity import (
    IdentityPolicy,
    IdentityPolicySettings,
    ShotType,
    preservation_directive,
)
from services.imagegen.prompt_author import DEFAULT_NEGATIVES, LifeSlot, author_jobs

FACE = "media/alina/reference/face.jpg"
BODY = "media/alina/reference/body.jpg"


class P:
    face_ref = FACE
    fullbody_ref = BODY


def _job(pose: str, prompt: str = "") -> GenerationJob:
    return GenerationJob(job_key="k", persona_slug="alina", prompt=prompt or pose,
                         slot=SlotMeta(pose=pose))


# ═══ FR-009-19 — shot-type-conditional secondary anchor ═════════════════════════════════════════


def test_fr_009_19_01_full_body_shot_attaches_both_face_first():
    sel = IdentityPolicy().select(P(), _job("mirror selfie, full-length framing"))
    assert sel.shot_type is ShotType.full_body
    assert sel.references == [FACE, BODY], "face is Picture 1, body is Picture 2"


def test_fr_009_19_02_face_shot_uses_face_anchor_only():
    sel = IdentityPolicy().select(P(), _job("close-up selfie", "a close-up selfie portrait"))
    assert sel.shot_type is ShotType.face
    assert sel.references == [FACE], "no body anchor on a selfie → no wardrobe/second-face leak"


def test_fr_009_19_03_config_toggle_restores_always_both():
    policy = IdentityPolicy(IdentityPolicySettings(secondary_only_for_full_body=False))
    sel = policy.select(P(), _job("close-up selfie", "a close-up selfie"))
    assert sel.references == [FACE, BODY]  # previous always-both behaviour, still face-first


def test_face_is_always_picture_1_even_for_full_body():
    # regression: select() used to put the body anchor FIRST for full-body shots, contradicting the
    # directive ("face = Picture 1"). Face must lead in every case.
    sel = IdentityPolicy().select(P(), _job("full body standing shot"))
    assert sel.references[0] == FACE


# ═══ FR-009-17 — anti-duplication in the directive ══════════════════════════════════════════════


def test_fr_009_17_01_directive_forbids_duplication():
    for n in (1, 2):
        d = preservation_directive(n).lower()
        assert "only one person" in d or "one person" in d
        assert "exactly once" in d and "never duplicated" in d


# ═══ FR-009-18 — body anchor does not dictate wardrobe ══════════════════════════════════════════


def test_fr_009_18_01_two_anchor_directive_excludes_anchor_clothing():
    d = preservation_directive(2).lower()
    assert "only the body proportions" in d or "only the body" in d
    assert "do not copy the clothing" in d or "do not copy" in d


# ═══ FR-010-17 — wardrobe authored in the prompt ════════════════════════════════════════════════


def test_fr_010_17_01_outfit_section_rejects_reference_clothing():
    j = author_jobs("alina", slot=LifeSlot(activity="coffee", location="cafe",
                                           time_of_day="afternoon"),
                    count=1, references=[FACE, BODY])[0]
    assert "not the clothing from the reference pictures" in j.prompt


# ═══ FR-010-18 — anti-duplication negatives ═════════════════════════════════════════════════════


def test_fr_010_18_01_negatives_include_duplication_terms():
    joined = " ".join(DEFAULT_NEGATIVES).lower()
    for term in ("two people", "duplicate person", "multiple women", "same person twice"):
        assert term in joined


# ═══ FR-009-15/16 — anchor preparation & validation ═════════════════════════════════════════════


def _make_img(path: Path, w: int, h: int) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (128, 128, 128)).save(path)
    return path


def test_fr_009_16_01_head_crop_body_drops_the_top(tmp_path):
    src = _make_img(tmp_path / "body.png", 640, 900)
    out = head_crop_body(src, tmp_path / "body_torso.png", top_fraction=0.25)
    from PIL import Image
    w, h = Image.open(out).size
    assert w == 640 and h == int(900 * 0.75)  # top quarter (the head) removed


def test_fr_009_16_02_validate_body_anchor_flags_landscape(tmp_path):
    # advisory orientation check: a portrait torso crop passes; a landscape image is clearly not a
    # body anchor and warns. (True face-in-frame detection needs a detector — provisioning's job.)
    torso = _make_img(tmp_path / "torso.png", 500, 900)
    landscape = _make_img(tmp_path / "wide.png", 900, 500)
    assert validate_body_anchor(torso).ok is True
    assert validate_body_anchor(landscape).ok is False


def test_fr_009_15_01_tighten_face_returns_centered_square(tmp_path):
    src = _make_img(tmp_path / "face.png", 640, 640)
    out = tighten_face(src, tmp_path / "face_tight.png", keep=0.7)
    from PIL import Image
    w, h = Image.open(out).size
    assert w == h == int(640 * 0.7)  # tighter square → face is a bigger share of the 384x384 encode
