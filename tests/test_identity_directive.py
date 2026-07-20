"""Identity-preservation directive + multi-anchor conditioning.

Covers the requirements added after the live review found generated prompts opening with a generic
"candid photo of a woman" (no binding to the reference) and the engine feeding only the FIRST
reference — throwing away F-009's full-body anatomy anchor:
  F-009 FR-009-11..14 (multi-anchor, directive, preserve≠describe, model-agnostic)
  F-010 FR-010-12/13  (prompt OPENS with the directive; wording owned by F-009)
  F-008 FR-008-05     (all references fed, capped at the node's 3-image limit)
See architecture.md §4.3b for the binding contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.imagegen.backends import ComfyUIBackend, GenerationFailed
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob
from services.imagegen.identity import (
    IdentityPolicy,
    IdentityPolicySettings,
    preservation_directive,
)
from services.imagegen.prompt_author import (
    LifeSlot,
    author_jobs,
    find_identity_terms,
)

APPEARANCE_WORDS = (
    "blonde", "brunette", "redhead", "blue eyes", "green eyes", "slim", "curvy",
    "tall", "petite", "tanned", "freckled",
)


class FakePersona:
    def __init__(self, face=None, body=None):
        self.face_ref = face
        self.fullbody_ref = body


def job(prompt="a cafe scene", refs=None) -> GenerationJob:
    return GenerationJob(job_key="k1", persona_slug="alina", prompt=prompt,
                         references=list(refs or []))


SLOT = LifeSlot(activity="coffee at the cafe", location="cafe", time_of_day="afternoon")
FACE = "media/alina/reference/face.png"
BODY = "media/alina/reference/body.png"


# ═══ FR-009-11 — multi-anchor conditioning ══════════════════════════════════════════════════════


def test_fr_009_11_01_both_anchors_returned_face_first():
    sel = IdentityPolicy().select(FakePersona(FACE, BODY), job())
    assert sel.references == [FACE, BODY], "face anchor first, body anchor second (Picture 1/2)"


def test_fr_009_11_02_single_anchor_stays_single():
    sel = IdentityPolicy().select(FakePersona(FACE, None), job())
    assert sel.references == [FACE]  # no fabricated body anchor


def test_fr_009_11_03_capped_at_model_limit():
    policy = IdentityPolicy(IdentityPolicySettings(max_references=1))
    sel = policy.select(FakePersona(FACE, BODY), job())
    assert len(sel.references) == 1  # honors the configured/model cap


# ═══ FR-009-12 — the directive ══════════════════════════════════════════════════════════════════


def test_fr_009_12_01_one_anchor_directive_names_picture_1():
    d = preservation_directive(1).lower()
    assert "picture 1" in d
    assert "preserve" in d and "face" in d and "body proportions" in d


def test_fr_009_12_02_two_anchors_directive_names_both_pictures():
    d = preservation_directive(2).lower()
    assert "picture 1" in d and "picture 2" in d
    assert "same person" in d


def test_fr_009_12_03_no_generic_unbound_subject():
    for n in (1, 2):
        d = preservation_directive(n).lower()
        assert "picture" in d, "the subject is always bound to an input picture, never generic"
    assert preservation_directive(0) == ""  # nothing to bind to → no directive


# ═══ FR-009-13 — preserve, never describe ═══════════════════════════════════════════════════════


def test_fr_009_13_01_directive_contains_no_appearance_descriptors():
    for n in (1, 2):
        d = preservation_directive(n).lower()
        for w in APPEARANCE_WORDS:
            assert w not in d, f"directive must preserve, not describe: {w!r}"


def test_fr_009_13_02_directive_exempt_from_banned_vocabulary_guard():
    prompt = author_jobs("alina", slot=SLOT, count=1, references=[FACE, BODY])[0].prompt
    assert prompt.startswith(preservation_directive(2))
    # the guard runs on the authored scene text and must not reject a prompt carrying the directive
    assert find_identity_terms(prompt.replace(preservation_directive(2), "")) == []


# ═══ FR-009-14 — model-agnostic (fixed contract only) ═══════════════════════════════════════════


def test_fr_009_14_01_directive_and_anchors_ride_the_fixed_contract():
    j = author_jobs("alina", slot=SLOT, count=1, references=[FACE, BODY])[0]
    assert j.prompt.startswith("Preserve")          # directive lives in prompt text
    assert j.references == [FACE, BODY]             # anchors live in ordered `references`
    assert json.loads(j.to_json())["references"] == [FACE, BODY]  # survives serialization


def test_fr_009_14_02_survives_a_backend_swap():
    j = author_jobs("alina", slot=SLOT, count=1, references=[FACE, BODY])[0]
    round_tripped = GenerationJob.from_json(j.to_json())
    assert round_tripped.prompt == j.prompt and round_tripped.references == j.references


# ═══ FR-010-12/13 — the prompt OPENS with the directive ═════════════════════════════════════════


def test_fr_010_12_01_prompt_begins_with_directive():
    j = author_jobs("alina", slot=SLOT, count=1, references=[FACE])[0]
    assert j.prompt.startswith(preservation_directive(1))
    assert j.prompt.index("Preserve") == 0, "directive precedes all scene content"


def test_fr_010_12_02_never_opens_with_generic_subject():
    for refs in ([FACE], [FACE, BODY]):
        for j in author_jobs("alina", slot=SLOT, count=3, references=refs):
            low = j.prompt.lower()
            assert not low.startswith("candid photo of a woman"), "regression: unbound subject"
            assert low.startswith("preserve the exact face")
            # the subject is bound to an input picture inside the opening directive
            assert "picture 1" in low[: len(preservation_directive(len(refs)))]


def test_fr_010_12_03_two_anchors_directive_then_scene():
    j = author_jobs("alina", slot=SLOT, count=1, references=[FACE, BODY])[0]
    assert "Picture 2" in j.prompt
    assert j.prompt.index("Picture 2") < j.prompt.lower().index("cafe"), "directive before scene"


def test_fr_010_13_01_wording_comes_from_f009_not_reauthored():
    src = (Path(__file__).resolve().parent.parent
           / "services" / "imagegen" / "prompt_author.py").read_text()
    assert "preservation_directive" in src
    assert "Preserve the exact face" not in src, "wording must live in F-009, not be duplicated here"


def test_fr_010_13_02_directive_change_flows_through(monkeypatch):
    monkeypatch.setattr("services.imagegen.prompt_author.preservation_directive",
                        lambda n: "SENTINEL DIRECTIVE. ")
    j = author_jobs("alina", slot=SLOT, count=1, references=[FACE])[0]
    assert j.prompt.startswith("SENTINEL DIRECTIVE. ")


# ═══ FR-008-05 — the engine feeds ALL references ════════════════════════════════════════════════


def _backend(tmp_path: Path) -> ComfyUIBackend:
    comfy = tmp_path / "comfyui"
    (comfy / "input").mkdir(parents=True)
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "__REFERENCE__"}},
        "3": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["1", 1], "vae": ["1", 2], "image1": ["2", 0],
                         "prompt": "__PROMPT__"}},
        "4": {"class_type": "TextEncodeQwenImageEditPlus",
              "inputs": {"clip": ["1", 1], "prompt": ""}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                         "seed": "__SEED__", "steps": "__STEPS__", "cfg": 1.0}},
    }
    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps(wf))
    media = tmp_path / "media"
    (media / "alina" / "reference").mkdir(parents=True)
    for n in ("face.png", "body.png", "extra1.png", "extra2.png"):
        (media / "alina" / "reference" / n).write_bytes(b"png")
    return ComfyUIBackend(ImageRunnerSettings(
        backend="comfyui-aio", comfy_dir=str(comfy), workflow_path=str(wf_path),
        media_root=str(media)))


def test_fr_008_05_03_both_references_bound_in_order(tmp_path):
    backend = _backend(tmp_path)
    wf = backend._build_workflow(job(refs=[FACE, BODY]))
    encoder = wf["3"]["inputs"]
    assert "image1" in encoder and "image2" in encoder, "both anchors reach the model"
    staged1 = wf[encoder["image1"][0]]["inputs"]["image"]
    staged2 = wf[encoder["image2"][0]]["inputs"]["image"]
    assert staged1.endswith("_0.png") and staged2.endswith("_1.png")  # order preserved


def test_fr_008_05_04_reference_count_capped_at_three(tmp_path):
    backend = _backend(tmp_path)
    refs = [FACE, BODY, "media/alina/reference/extra1.png", "media/alina/reference/extra2.png"]
    wf = backend._build_workflow(job(refs=refs))
    encoder = wf["3"]["inputs"]
    bound = [k for k in encoder if k.startswith("image")]
    assert sorted(bound) == ["image1", "image2", "image3"]  # node limit, no crash on the 4th


def test_fr_008_05_02_missing_reference_still_defined_error(tmp_path):
    backend = _backend(tmp_path)
    with pytest.raises(GenerationFailed, match="no reference"):
        backend._stage_references(job(refs=[]))
