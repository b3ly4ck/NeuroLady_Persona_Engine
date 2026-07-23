"""The fixed job API of the F-008 runner (FR-008-01) — the ONLY thing callers depend on.

A job says *what* to generate (persona, reference(s), prompt, params, slot metadata, intimacy
tags); the engine decides nothing about content (F-010 authors prompts, F-009 the reference
policy, F-014 the intimacy gate). The contract is model-agnostic (FR-008-03/NFR-008-09): the same
payload runs against any configured backend.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


class InvalidJob(ValueError):
    """A malformed job payload — rejected with a defined error, never a crash (TC-FR-008-01-03)."""


@dataclass
class GenParams:
    """Generation knobs — from the job/config, never hard-coded in the engine (FR-008-06)."""

    steps: int = 4          # distilled low step count (FR-008-04, §4.3)
    cfg: float = 1.0
    width: int = 1024
    height: int = 1024
    seed: int = 0
    negative: str = ""


@dataclass
class SlotMeta:
    """Life-slot metadata carried onto MEDIA_ASSET.meta_json (FR-008-08; authored by F-010)."""

    pose: str = ""
    background: str = ""
    location: str = ""
    activity: str = ""
    time_of_day: str = ""
    # F-010 FR-010-19 (ISS-008): a short, human-readable sentence naming WHAT IS VISIBLE in the
    # frame, in the persona's language — the thing she can actually say when asked "что у тебя на
    # фоне?". The five fields above describe the generation *request*; this one describes the photo.
    scene_description: str = ""


@dataclass
class GenerationJob:
    """`{persona, reference(s), prompt, params}` → one stored asset (feature §2 flow)."""

    job_key: str                      # idempotency key (FR-008-12)
    persona_slug: str                 # persona-agnostic: everything from the payload (FR-008-02)
    prompt: str
    references: list[str] = field(default_factory=list)  # media-library paths (FR-008-05, F-009)
    params: GenParams = field(default_factory=GenParams)
    slot: SlotMeta = field(default_factory=SlotMeta)
    intimate: bool = False            # tags only — the gate lives in F-014, not here
    intimacy_level: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "GenerationJob":
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidJob(f"payload is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationJob":
        if not isinstance(data, dict):
            raise InvalidJob("job payload must be an object")
        missing = [k for k in ("job_key", "persona_slug", "prompt") if not data.get(k)]
        if missing:
            raise InvalidJob(f"missing required job fields: {', '.join(missing)}")
        try:
            params = GenParams(**data.get("params", {}))
            slot = SlotMeta(**data.get("slot", {}))
        except TypeError as exc:
            raise InvalidJob(f"unknown field in params/slot: {exc}") from exc
        job = cls(
            job_key=str(data["job_key"]),
            persona_slug=str(data["persona_slug"]),
            prompt=str(data["prompt"]),
            references=[str(r) for r in data.get("references", [])],
            params=params,
            slot=slot,
            intimate=bool(data.get("intimate", False)),
            intimacy_level=int(data.get("intimacy_level", 0)),
        )
        job.validate()
        return job

    def validate(self) -> None:
        if not self.job_key.strip():
            raise InvalidJob("job_key must be non-empty")
        if not self.persona_slug.strip():
            raise InvalidJob("persona_slug must be non-empty")
        if not self.prompt.strip():
            raise InvalidJob("prompt must be non-empty")
        if not (1 <= self.params.steps <= 50):
            raise InvalidJob(f"steps out of range: {self.params.steps}")
        if self.params.width <= 0 or self.params.height <= 0:
            raise InvalidJob("resolution must be positive")
        if self.intimacy_level < 0:
            raise InvalidJob("intimacy_level must be >= 0")

    def slot_meta_json(self) -> str:
        """meta_json for the MEDIA_ASSET row: the five slot fields + provenance (FR-008-08)."""
        meta = asdict(self.slot)
        meta["prompt"] = self.prompt
        meta["seed"] = self.params.seed
        return json.dumps(meta, ensure_ascii=False)
