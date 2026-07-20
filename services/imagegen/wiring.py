"""Production wiring for the image pipeline — the real F-009/F-010 behind F-011's protocols.

The parallel feature builds shipped protocol stubs (`DefaultPromptAuthor`,
`DefaultReferenceProvider`) so each module tested standalone. This module is the ONE place the
stubs are replaced with the real implementations, per each spec's integration note:

  F-011 batch planner ──author──▶ F-010 `prompt_author.author_jobs` (scene/pose/variety)
                      ──refs────▶ F-009 `identity.IdentityPolicy` (same-girl conditioning)

`build_production_planner()` is what ops/scheduling code should instantiate; the planner's own
defaults remain as safe fallbacks for isolated tests.
"""
from __future__ import annotations

import logging

from services.bot.models import Persona
from services.bot.personas_seed import persona_slug
from services.imagegen.batch_planner import (
    AuthoredShot,
    BatchPlanConfig,
    BatchPlanner,
    SlotContext,
)
from services.imagegen.contract import GenerationJob
from services.imagegen.identity import IdentityPolicy, NoReferenceError
from services.imagegen.prompt_author import (
    DEFAULT_CONFIG as PROMPT_CONFIG,
    LifeSlot,
    PromptAuthorConfig,
    author_jobs,
)

log = logging.getLogger(__name__)


class F010PromptAuthor:
    """Adapter: F-011's per-shot `PromptAuthor` protocol over F-010's set-based `author_jobs`.

    Deterministic: the slot's identity (activity+time) seeds F-010, and shot_index picks the
    framing out of the authored set — same slot+index always yields the same prompt (NFR-010-03).
    """

    def __init__(
        self,
        config: PromptAuthorConfig = PROMPT_CONFIG,
        references: "IdentityReferenceProvider | None" = None,
    ) -> None:
        self._config = config
        # The directive's wording depends on HOW MANY anchors get bound (Picture 1 vs 1+2), and the
        # planner resolves references separately — so the author must resolve the same anchors here
        # or it would emit a prompt with no identity binding at all (F-010 FR-010-12).
        self._references = references or IdentityReferenceProvider()

    def author(self, persona: Persona, slot: SlotContext, shot_index: int) -> AuthoredShot:
        slug = persona_slug(persona.name)
        life_slot = LifeSlot(
            activity=slot.activity,
            location=slot.location,
            time_of_day=slot.time_of_day,
        )
        base_seed = abs(hash((slug, slot.activity, slot.time_of_day))) % 100_000
        jobs: list[GenerationJob] = author_jobs(
            slug, slot=life_slot, config=self._config,
            count=shot_index + 1, base_seed=base_seed,
            references=self._references.references_for(persona),
        )
        job = jobs[shot_index]
        return AuthoredShot(prompt=job.prompt, negative=job.params.negative, slot=job.slot)


class IdentityReferenceProvider:
    """Adapter: F-011's `ReferenceProvider` protocol over F-009's `IdentityPolicy`.

    The policy orders the persona's anchors (face first) per its config; a persona with no
    references resolves to [] — the F-008 backend then fails that job with a DEFINED error
    (never a wrong-identity image), which is F-009's no-reference safe path (FR-009-08).
    """

    def __init__(self, policy: IdentityPolicy | None = None) -> None:
        self._policy = policy or IdentityPolicy()

    def references_for(self, persona: Persona) -> list[str]:
        probe = GenerationJob(
            job_key="ref-probe",
            persona_slug=persona_slug(persona.name),
            prompt="",
        )
        try:
            selection = self._policy.select(persona, probe)
        except NoReferenceError:
            log.warning("persona %s has no reference images — jobs will be skipped", persona.name)
            return []
        return list(selection.references)


def build_production_planner(
    config: BatchPlanConfig | None = None,
    *,
    prompt_config: PromptAuthorConfig = PROMPT_CONFIG,
    identity_policy: IdentityPolicy | None = None,
) -> BatchPlanner:
    """The fully-wired nightly planner: F-010 authors, F-009 conditions, F-008 renders."""
    refs = IdentityReferenceProvider(identity_policy)
    return BatchPlanner(
        config=config or BatchPlanConfig(),
        # same provider on both seams: the prompt's directive and the bound anchors must agree
        author=F010PromptAuthor(prompt_config, references=refs),
        references=refs,
    )
