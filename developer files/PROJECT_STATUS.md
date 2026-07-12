# Project Status — NeuroLady_Final

## Recent changes

- **Fixed a live-tested UX issue: Start Chat sent two stacked "please write" messages.** Live
  Telegram testing showed the fallback intro ("Hey, it's Sofia 💋 ... write me?") immediately
  followed by a separate "You're all set — say something" message — both nudging the same action,
  reading as robotic/redundant. Fix: `send_persona_intro` now accepts a `reply_markup` and the
  keyboard is attached directly to the single intro message (video note or fallback text); the
  `on_start_chat` handler no longer sends a second `chat_ready_view` message. Updated `F-001`
  **FR-001-12** to state this explicitly (keyboard attached to the intro delivery, no separate
  follow-up), and logged the general pattern as a dated CLAUDE.md preference ("don't stack two
  consecutive nudge messages"). Updated `test_uc_001_04_...` accordingly. **48/48 tests still
  green.** (The `/start` resume path and the menu's "Resume chat" still show a single
  `chat_ready_view` message each — those are not stacked with anything, so unaffected.)
- **F-001 implementation complete on `feature/f-001-onboarding` — 48 tests green.** Added the
  Telegram I/O layer (aiogram 3): `keyboards.py` (welcome Start button; ◀ counter ▶ + Start Chat
  card kb; persistent reply kb 💋 Choose Lady + ≡ Menu; menu kb), `views.py` (pure `(text, keyboard)`
  builders — system copy in user locale, card copy in the persona's language), `handlers/onboarding.py`
  (/start → Welcome or resume; Start → gallery; card:<i> cyclic nav; startchat:<id> → session +
  intro-once + reply kb; Choose Lady / Menu / Resume), `middlewares.py` (per-update DB session),
  `app.py` + `__main__.py` (build_dispatcher + polling entrypoint; refuses to start without a token).
  Intro delivery sends a video note from `intro_videonote_ref` when present, else a graceful text
  fallback (FR-001-18). Tests: `test_f001_views.py` (9) + `test_f001_handlers.py` (10, handlers
  driven with mocked aiogram objects over a real in-memory DB) on top of the 29 domain tests =
  **48 passing**, covering FR-001-01..20 and NFR-001-04/09/10 behaviors. Remaining: **manual
  real-device acceptance (TC-US-001-*)** in Telegram — needs the regenerated bot token — then merge
  to `master`.
- **Started F-001 implementation (branch `feature/f-001-onboarding`) — domain foundation, 29 tests
  green.** Stack: Python 3.11+, **aiogram 3.x**, **SQLAlchemy 2 async** + aiosqlite (dev). Added
  `pyproject.toml`, `services/bot/` package: `config.py` (env/.env via pydantic-settings, no
  hard-coded secrets), `db.py` (async engine/sessionmaker/init), `models.py` (USER/PERSONA/SESSION —
  a faithful subset of the §5.1 ERD, extra later-feature fields modelled up front), `i18n.py`
  (RU/EN copy catalog), `personas_seed.py` (starter roster: 3 RU + 3 EN), and pure **domain** logic
  (`domain/users.py` get-or-create; `domain/gallery.py` active/locale-filtered + cyclic pagination;
  `domain/sessions.py` create/reuse/switch with one-active-session invariant). Repo-root `tests/`
  with `conftest.py` (in-memory async SQLite) + `test_f001_onboarding_domain.py`: **29 passing**
  tests traced to TC ids covering FR-001-01/05/06/07/08/10/14/15/17/20 and NFR-001-10. Env note: the
  Git-Bash `python` is a MinGW build with no PyPI wheels; the venv must be built from the python.org
  CPython (`AppData/Local/Programs/Python/Python312`). **Next:** aiogram handlers + keyboards +
  entrypoint (the Telegram I/O layer) and their tests, then run end-to-end and merge to master once
  all `tests/` pass.
- **SECURITY: scrubbed a real Telegram bot token from `.env.example`.** A real token had been placed
  in the tracked template `.env.example` (which is intentionally NOT git-ignored) and pushed in
  commit `69782ba` — i.e. exposed in the public repo. Restored the placeholder (`TELEGRAM_BOT_TOKEN=`
  empty). **The exposed token is compromised and must be revoked/regenerated via @BotFather** — it
  remains in git history (commit `69782ba`), so scrubbing the current file does not undo the exposure;
  only revocation does. The real token belongs only in `.env` (git-ignored), never in `.env.example`.
- **Wrote the F-004 test spec: `developer files/tests/F-004-memory-system.md`** (mirror name of the
  feature file) — **147 tests total**: **98 functional** (FR-004-01..43, 2 each, 3 for the 12 critical
  ones: FR-004-04/05/07/09/10/11/21/24/25/36/39/40), **39 non-functional** (NFR-004-01..18, 2 each,
  3 for the 3 critical ones: NFR-004-03/07/16), and **10 manual real-device acceptance tests** keyed
  to the user stories (US-004-01..10). **Coverage verified by grep: 43/43 FR, 18/18 NFR, 10/10 US,
  no numbering gaps; grand total 147 in the 100-150 band.** Every `TC-` id embeds the `FR-`/`NFR-`/
  `US-` id it verifies; cases vary across unit / integration / inter-service / data-flow / component /
  e2e / performance / load / security / consistency / concurrency / persistence and happy / negative /
  boundary / empty / error / idempotency / mapping. Because F-004 is the **memory subsystem itself**
  (not the reply loop), tests assert on **storage, dual-store referential integrity (SQL row ↔
  `embedding_ref` ↔ vector-point payload), fact categorization, semantic recall of old facts,
  structured recall by active-only category, fact supersession (old soft-superseded / new active /
  re-embed), persona biography answered by scope with no self-contradiction across layers, fused
  `query` ranking/relevance, per-user isolation (security tests on the vector owner-filter),
  retention across restart, re-embed on update, reconciliation/drift healing, Qdrant-down graceful
  degrade, and export/delete from BOTH stores** — reply-content correctness stays owned by F-002.
  A boundary note states F-002's own spec tests the turn that *uses* memory while this spec tests the
  subsystem *behind* that call. **Next step:** implementation of Phase 1 (conversation core + memory)
  once the F-001..F-004 specs are approved.
- **Started the codebase (infra foundation).** Added `architecture.md` **§6.2c — dependency
  isolation & model-runner environments**: each self-hosted model is its own isolated runner
  (own env + weights) behind a fixed network API; locally one `uv` venv per runner
  (`chat/.venv`, `image/.venv`, …), in prod one Docker image per runner; the day/night scheduler
  owns which runner holds the GPU. Created the **`chat/` runner** per §6.3: `chat/{models,prompts}`,
  `README.md`, `download_model.py`, isolated `chat/.venv` (uv, Python 3.11). **Downloading the chat
  LLM** `HauhauCS/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive` **Q6_K GGUF (~28.5 GB)** into
  `chat/models/` (fits the 48 GB Quadro RTX 8000 with KV-cache headroom). Added a hardened
  **`.gitignore`** (secrets `.env`, venvs, model weights, generated `media/`, local DBs) and
  **`.env.example`** (secrets template — real `.env` is git-ignored so keys never reach GitHub).
  **Kicked off F-001 implementation on branch `feature/f-001-onboarding`** (delegated to a coding
  subagent; onboarding needs no model, so it proceeds while the LLM downloads).
- **Closed the 6 architecture gaps F-004 relies on (`architecture.md`), so the schema matches the
  feature.** (1) **`USER_FACT`** gains `status (active|superseded)`, `superseded_by`, `confidence`,
  `updated_at` — enabling fact supersession/recency (F-004 FR-004-11..14). (2) **Vector point-payload
  contract** documented in §3.4: every Qdrant point carries `user_id` (facts) / `persona_id`
  (biography) in its payload and all semantic queries filter by these keys — provable per-user
  isolation (NFR-002-07). (3) **Memory export/delete endpoints** added to §2.2:
  `GET`/`DELETE /memory/user-data/{userId}` (erase from both stores), wired into §6.5. (4)
  **Life-Engine→Memory write contract** `POST /memory/biography-layer` (upsert + re-embed a layer;
  Memory stores/indexes, Life Engine authors). (5) **Store reconciliation/repair** added to §3.4
  (heal orphan/missing embeddings + drift) with new **memory-store consistency metrics + drift alert**
  in §6.4. (6) **`scope` vs epoch-name reconciliation:** `BIOGRAPHY_LAYER.scope` is the pyramid
  **level only** (`epoch|year|month|week|day`); the epoch names `childhood|youth|current` are
  **`period_key` values under `scope=epoch`** — fixed the biography API to
  `?scope=epoch|year|month|week|day[&period_key=]` (§2.2) and clarified §4.5/§5.1 accordingly. Also
  expanded §3.4 Memory Service into the full dual-store spec (fused ranked `query`, async re-embed,
  supersession, reconciliation, privacy). Verified F-004 IDs are clean and contiguous
  (10 US / 19 UC / 43 FR / 18 NFR) with valid F-002 cross-refs.
- **Wrote the fourth feature file: `developer files/features/F-004-memory-system.md`** (mirror-named
  after the coming test spec), written under the "describe every feature maximally in detail" rule.
  **F-004 is the Memory subsystem as a standalone capability** — the **dual-store** engine
  (structured **PostgreSQL** relational + **Qdrant** vector) behind two kinds of recall: the
  **persona's own biography** (the time-pyramid layers epoch/year/month/week/day, architecture.md
  §4.5) and the **user's biography** (categorized `USER_FACT`s). Covers all eight requested facets:
  (1) dual-store architecture + `embedding_ref` referential integrity; (2) user-fact memory
  (categorize/store/embed, structured + semantic recall, **superseding contradictory facts**,
  recency/confidence/dedup); (3) persona self-biography (store/index/serve layers by scope +
  semantically, **no self-contradiction across layers**); (4) **fused `query`** contract
  (`POST /memory/query`) ranking structured + semantic + biography, not letting irrelevant facts
  dominate; (5) consistency/correctness (faithful to stored truth); (6) retention/durability
  (persist until deletion, embeddings in sync, **re-embed on update**, drift reconciliation);
  (7) privacy/isolation (provable per-user isolation, shared-biography vs private-facts, export +
  delete from **both** stores, §6.5); (8) failure/degrade (Qdrant-down → degrade to structured +
  recent history; SQL-down defined & safe, no fabrication; async embedding backlog off the hot
  path). Follows `feature_description_guide.md`: header + **Scope boundary** note, **10 user stories**
  (US-004-01..10 — A2 unprompted recall + A2 months-later returning recall, A8 skeptic probing her
  biography and his memory-of-him for contradictions, A6 reliable/consistent recall, A1 fact-update/
  supersede, privacy-conscious isolation+export/delete, A4 disclosures-honored, returning-user
  answers-about-her-own-life-by-scope, and a durability story), **5 Mermaid user flows** (unprompted
  old-fact recall; answering about her own life by scope; contradictory fact supersedes; vector-store
  degrade; export/delete), **19 Gherkin use cases** (UC-004-01..19, incl. **2 Scenario Outlines** —
  fact categorization across categories, and biography answers across scopes), and **61 requirements
  — 43 functional (FR-004-01..43) + 18 non-functional (NFR-004-01..18)**.
  **F-002 vs F-004 boundary (consumer/capability split):** F-002 owns the *conversation turn that
  consumes memory* (assemble context, produce reply) and is a **consumer** of the F-004 contract;
  **F-004 owns the memory subsystem itself** and specifies *how* store/categorize/embed/recall/fuse
  work. To avoid duplication, F-004 **cross-references** F-002 ids instead of restating them:
  **FR-002-04** (recent raw history in-context — F-002 owns carrying it), **FR-002-10** (extraction
  trigger — F-004 owns store/categorize/embed/supersede of the result), **FR-002-11..12**
  (categorize/embed — realized inside F-004's pipeline, FR-004-07/08), **FR-002-13..14** (recall +
  fuse — served by F-004's `query`, FR-004-24..28), **FR-002-20 / NFR-002-07** (per-user isolation —
  enforced inside F-004's stores/vector filters, FR-004-36/NFR-004-03/16), **NFR-002-05** (Qdrant-down
  degrade — implemented by FR-004-40/NFR-004-07).
  **Life-Engine-generates vs F-004-stores/serves split (biography):** stated in the Scope boundary and
  in **FR-004-22** — the **Life Engine** (§3.5/§4.5/§4.6) *authors, reflects on, and hierarchically
  compresses* the biography layers and relationship state; **F-004 only stores, indexes, keeps
  consistent, and serves** them (by scope via `GET /persona/{id}/biography?scope=` and semantically),
  and exposes a write/index contract the Life Engine calls (UC-004-19). **Out of scope:** reply
  content/pacing/styling (F-002/F-003); autonomous reflection/biography compression (Life Engine);
  onboarding (F-001); media/voice (later phases); monetization (deferred, §3.7).
  **Next step:** the mirror test spec `developer files/tests/F-004-memory-system.md` per
  `test_driven_development.md` (~2-3 tests per requirement, each `TC-` addressed to an
  `FR-`/`NFR-`/`US-` id) — with 61 requirements this lands high in the 100-150 test band.
- **Wrote the F-003 test spec: `developer files/tests/F-003-human-like-communication.md`**
  (mirror name of the feature file) — **147 tests total**: **97 functional** (FR-003-01..38, 2-3
  each), **41 non-functional** (NFR-003-01..17, 2-3 each incl. 1 manual localization check
  TC-NFR-003-05-03), and **9 manual real-device acceptance tests** keyed to the user stories
  (US-003-01..09). Coverage verified: **38/38 FR, 17/17 NFR, 9/9 US**. Every `TC-` id embeds the
  `FR-`/`NFR-`/`US-` id it verifies; cases vary across unit / integration / component / e2e /
  performance / load / statistical / concurrency / error and happy / negative / boundary / mapping /
  consistency / persistence / localization / idempotency. Because F-003 governs *delivery/style*
  (not content), tests assert on timing (delay bounded & additive-not-slowing-compute, typing
  indicator), chunking (ordering/integrity, natural boundaries, capped count), emoji/register/slang
  realism, anti-repetition (statistical), per-persona + per-user style tunability, and the
  correctness-preservation boundary (FR-003-38). Sits near the top of the 100-150 band by design (55
  requirements). **Next step:** implementation of Phase 1 once the F-001/F-002/F-003 specs are approved.
- **Verified F-003 spec and documented its `comm_settings_json` dependency in `architecture.md`.**
  Reviewed the F-003 feature file end-to-end: sections complete per the guide; IDs confirmed as
  **9 US (US-003-01..09) / 18 UC / 38 FR / 17 NFR** with valid F-002 cross-refs. Fixed one dangling
  reference (`NFR-003-08` pointed at a nonexistent `US-003-16`; corrected to `UC-003-16`) and
  corrected the previous status note that miscounted 10 user stories (it is 9 — the 10th was the
  typo'd id). Architecture updates so the schema matches what F-003 relies on: **§3.3** now describes
  the per-persona **`comm_settings_json`** human-likeness knobs (pacing/typing_speed, verbosity/
  chunking, emoji_frequency, register/slang_level/typo_rate, variability_strength, mood_expressiveness,
  followup_policy); **§5.1** annotates `PERSONA.comm_settings_json` and adds
  **`USER.interaction_style_json`** (the per-user low-emoji/literal overlay, F-003 FR-003-37);
  **§3.2** step 5 now names the F-003 human-likeness styling + pacing (added on top of fast compute,
  never altering reply content). **Next step:** the F-003 test spec.
- **Wrote the third feature file: `developer files/features/F-003-human-like-communication.md`**
  (mirror-named after the coming test spec), written under the "describe every feature maximally in
  detail" rule and deliberately **more thorough than F-002**. Follows `feature_description_guide.md`:
  header + **Scope boundary** note, **9 user stories** (US-003-01..09, mapped to Audience segments
  A1 "bot energy", A8 skeptic, A2 emotional texture, A4 unhurried pacing, A6 neurodivergent
  literal/low-emoji, A7 gentle register, plus returning-user "same texting personality" continuity
  and anti-repetition), **4 Mermaid user flows** (single paced reply with typing indicator; long
  reply split into several messages; the emoji/register/variability styling path; not-over-eager
  mood + in-exchange follow-up), **18 Gherkin use cases** (UC-003-01..18, incl. a Scenario Outline
  for reply length → pace/chunk count), and **55 requirements — 38 functional (FR-003-01..38) + 17
  non-functional (NFR-003-01..17)**. **Scope:** the **believability/delivery layer on top of
  F-002's correct-reply loop** — it shapes *how* an already-decided reply is timed, chunked, and
  styled (architecture.md §3.2 steps 4–6, §4.1 style-tuning, §4.2 communication-style, and the
  per-persona **`comm_settings_json`** in §3.3/§5.1). Covers: deliberate **variable reply pacing**
  with the Telegram "typing…" indicator (proportional to length, slower when "busy"/night, with an
  **upper bound** so it never feels ignored); **message-length/volume realism** (split long replies
  into several short consecutive messages with pauses+typing between chunks, no walls of text, no
  bullet/essay/assistant formatting); **sparse persona-tuned emoji**; **informal texting register**
  (casual lowercase, contractions, slang, rare typo, RU/EN localized); **anti-repetition** (varied
  greetings/openings/catchphrases); a **not-over-eager, not-assistant-polite tone** with real mood
  (tease/sulk/quiet) and an in-exchange short follow-up; and **per-persona tunability + style
  consistency** driven by `comm_settings_json`. **Pacing-vs-fast-compute nuance handled
  explicitly** (FR-003-07, NFR-003-02, UC-003-14): the deliberate pause is an **additive wait after
  fast warm-model compute**, never an extension of compute — consistent with §4.1/F-002, not
  contradictory. **Neurodivergent low-emoji tension handled** via a per-user interaction-style
  overlay (FR-003-37, UC-003-09, NFR-003-14, US-003-05) that reduces emoji + increases literalness
  on top of persona defaults. **Out of scope (stated in the Scope boundary):** reply *content* +
  memory (→ **F-002**); onboarding/persona selection/intro (→ **F-001**); cold-start/model-load
  latency itself (architecture.md §4.1/§6.1 — F-003 assumes fast compute); voice (ElevenLabs) and
  photos/videos (later phases); autonomous **cross-session** proactive "she messages first" / daily
  circles / Life Engine (separate feature — F-003's only proactivity is the in-exchange follow-up,
  FR-003-32/33); monetization (deferred, §3.7). **Next step:** the mirror test spec
  `developer files/tests/F-003-human-like-communication.md` per `test_driven_development.md`
  (~2-3 tests per requirement, each `TC-` addressed to an `FR-`/`NFR-`/`US-` id).
- **New rule (CLAUDE.md preference): describe every feature maximally in detail.** F-002 was
  under-detailed relative to F-001; going forward each feature file must be thorough (exhaustive user
  stories per segment, full flows, a rich set of Gherkin use cases, and a granular full `FR-`/`NFR-`
  set). Spec thoroughness is separate from the ~2-3-tests-per-requirement rule (more requirements →
  more tests overall). Next feature to be written under this rule: **F-003 — human-likeness of
  communication** (reply pacing/timing, message length/volume, realistic emoji use, informal texting
  register, variability, not-over-eager tone).
- **Wrote the F-002 test spec: `developer files/tests/F-002-conversation-and-memory.md`**
  (mirror name of the feature file) — **115 tests total**: **73 functional** (FR-002-01..24, 3 each
  except FR-002-04 which has 4), **36 non-functional** (NFR-002-01..12, 3 each incl. 1 manual
  localization check TC-NFR-002-06-03), and **6 manual real-device acceptance tests** keyed to the
  user stories (US-002-01..06). Every `TC-` id embeds the `FR-`/`NFR-`/`US-` id it verifies; cases
  vary across unit / integration / inter-service / data-flow / component / e2e / performance / load /
  security / consistency and happy / negative / boundary / empty / error / concurrency / idempotency /
  localization / persistence / mapping. Walks DFD-1 (conversation turn) and the failover/cold-start
  paths. Explicitly covers the **cold-start** items: warm-model latency (NFR-002-01), pre-warm +
  keep-warm + bounded cold reply (NFR-002-12), and the in-character typing/holding-line
  acknowledgement while the model loads with no system-voice leak (FR-002-24); plus memory behaviors
  (fact extraction/categorization/embedding FR-002-10..12, semantic + unprompted old-fact recall
  FR-002-13..14, recent-raw-history hard requirement FR-002-04), persona-never-breaks-character
  (FR-002-08 / NFR-002-10), per-user memory isolation (FR-002-20 / NFR-002-07 security),
  LLM/Qdrant failover degrade-don't-fail (FR-002-19 / NFR-002-04/05), and Russian localization
  (FR-002-21 / NFR-002-06). Count verified in-band (100-150). **Next step:** implementation of the
  conversation core (Phase 1) once feature+test specs are approved.
- **Added model cold-start / warm-up latency as a first-class concern** across the docs. In
  `architecture.md`: §4.1 gets a bullet on model-load ("cold-start") latency requiring **pre-warming
  before the serving window, keep-warm (resident) during awake hours, and a graceful cold path**
  (immediate "typing…"/in-character holding line if a request hits a loading model); §6.1 day/night
  scheduler must finish **reload + warm-up inference before the awake window opens** and treats "model
  warm" (not "process started") as the readiness gate; DFD-3 wake node updated to "reload + warm up
  before serving"; §6.4 observability adds chat-LLM readiness/warm-up metrics + an alert if the model
  isn't warm at the start of a serving window. In `F-002`: refined **NFR-002-01** (the <5s budget is
  for a **warm** model), added **NFR-002-12** (cold-start must not leak to users; pre-warm + bounded
  worst-case cold reply), **FR-002-24** (immediate in-character acknowledgement while the model
  loads), and **UC-002-12** (message during model load is not left hanging). F-002 now has 24 FR +
  12 NFR + 12 UC.
- **Wrote the second feature file: `developer files/features/F-002-conversation-and-memory.md`**
  (mirror-named after the coming test spec). Follows `feature_description_guide.md`: header +
  **Scope boundary** note, **6 user stories** (US-002-01..06, mapped to Audience segments
  A1/A2/A4/A6/A8 + returning user), **3 Mermaid user flows** (single conversation turn;
  returning-days-later "she remembers"; skeptic probing memory/consistency), **11 Gherkin use cases**
  (UC-002-01..11, incl. a varied-message Scenario Outline, plus first-reply, recent-raw-history
  carry-through, fact extraction, old-fact recall, in-character-under-provocation, LLM
  timeout/fallback, long-history trimming, no-cross-user-leakage, Russian reply, media-request
  acknowledged-but-not-delivered), and **34 requirements** — **23 functional (FR-002-01..23)** +
  **11 non-functional (NFR-002-01..11)**. **Scope:** the live **text** conversation turn + memory
  that serve the reply loop (architecture.md §3.2/§3.4/§4.2/§4.6, DFD-1) — message intake → load
  session/relationship → assemble context (persona prompt + biography layers + user facts +
  relationship summary + **recent raw history verbatim, called out as its own hard-requirement
  FR-002-04**) → uncensored Chat LLM call → post-process → in-character reply → persist `MESSAGE`
  rows → extract + categorize + embed `USER_FACT` (Qdrant) → recall fused into later turns →
  relationship-state update; covers empty/very-long history + context-budget trimming, LLM
  timeout/fallback, per-user memory isolation, persona never-breaks-character, and Russian
  localization. **Out of scope (stated in the Scope boundary):** onboarding/persona
  selection/video-note intro (→ F-001); photo/video sending & media generation (Phase 2+, media
  intent only *acknowledged* in-character); voice replies/ElevenLabs (future); the Life Engine's
  autonomous planning/reflection/goals/proactive "she messages first" (separate feature — F-002
  only consumes memory/relationship state as reply inputs); monetization/quota/subscriptions
  (deferred, §3.7). **Next step:** the mirror test spec `developer files/tests/F-002-*.md` per
  `test_driven_development.md` (~2-3 tests per requirement, each `TC-` addressed to an
  `FR-`/`NFR-`/`US-` id).
- **Wrote the F-001 test spec: `developer files/tests/F-001-onboarding-persona-selection.md`**
  (mirror name of the feature file) — **100 tests total**: 64 functional (FR-001-01..20, 3-4 each),
  30 non-functional (NFR-001-01..10, 3 each incl. 1 manual localization check), 6 manual real-device
  acceptance tests keyed to the user stories (US-001-01..06). Every `TC-` id embeds the
  `FR-`/`NFR-`/`US-` id it verifies. Cases vary across unit/integration/component/e2e/performance/
  load/security/concurrency and happy/negative/boundary/error/idempotency/localization/persistence.
- **New rule (CLAUDE.md + `test_driven_development.md`): test volume scales with feature
  granularity.** For finely-split features, ~2-3 tests per requirement (≈100-150 per feature), not a
  fixed 1000+. Test-spec file names must mirror feature file names; every test must be addressed to a
  specific `FR-`/`NFR-`/`US-` id via a consistent `TC-` id (ID scheme in the TDD guide extended to
  allow user-story-addressed tests). Logged as a dated preference in CLAUDE.md.
- **Wrote the first feature file: `developer files/features/F-001-onboarding-persona-selection.md`**
  (the first real feature; `F-000` remains the guide's reserved example). Follows
  `feature_description_guide.md`: header, **6 user stories** (US-001-01..06, mapped to Audience
  segments A1/A2/A7/A8 + returning/switching users), **3 Mermaid user flows** (first-time,
  returning, switch-persona), **9 Gherkin use cases** (UC-001-01..09, incl. a pagination Scenario
  Outline), and **30 requirements** — **20 functional (FR-001-01..20)** + **10 non-functional
  (NFR-001-01..10)**. Scope: `/start` → Welcome screen → "Choose Lady" card carousel (photo/name/
  profession/age/first-person description, ◀ 1/N ▶, Start Chat) → video-note "circle" intro →
  ready chat with the `💋 Choose Lady` + menu reply keyboard; includes returning-user resume,
  persona switching, idempotency, missing-intro fallback, and localization. **Out of scope
  (→ F-002):** the actual message↔reply conversation loop + memory; monetization and age-gating are
  deferred. Next step: the mirror test spec `developer files/tests/F-001-*.md` (~1000 tests) per
  `test_driven_development.md`.
- **Rewrote `architecture.md` §8 roadmap as a Mermaid diagram** and removed all billing/monetization
  from it. New phase order (each phase depends on the previous): **Phase 1** conversation core
  (chat LLM → orchestrator → memory → dynamic persona/Life Engine → voice replies); **Phase 2**
  photo sending (SFW + intimate) via the night-batch image pipeline + `media/` archive; **Phase 3**
  daily talking-head video circles (HunyuanVideo-Avatar); **Phase 4** intimate video (Wan 2.2);
  **Phase 5** open-source Pygmalion packaging. The old "5-free-messages" and "photo-access
  subscriptions" mentions were dropped (monetization is deferred, §3.7).
- **Reworked the data model (`architecture.md` §5 ERD/DFD + related prose).** Product-driven
  changes to the persona/media schema:
  - **Removed `SCHEDULE_SLOT`.** The daily schedule now lives as **free text in
    `DAILY_PLAN.plan_text`**. Media-gen prompts are synthesized on demand by handing the external
    LLM the schedule text + the persona's current time and asking for a prompt matching her current
    activity (updated §3.5, §3.6, §4.3, DFD-2, and the `/media/request` + `/life/plan` API notes).
  - **Removed `MEDIA_ASSET.schedule_slot_id`;** `meta_json` now also carries `activity` +
    `time_of_day`. `MEDIA_ASSET.id` uses scheme **`MED-<persona>-<nnnnn>`** and is also the file name.
  - **`PERSONA` changes:** `big_five_json` → **`big_five`** (plain text, for uniformity); added
    **`timezone`** (IANA, defines her "current time"); added explicit reference-photo paths
    **`face_ref`** + **`fullbody_ref`**; all `*_ref` fields documented as **relative paths** into a
    new external **`media/`** library.
  - **New external `media/` folder** (§6.3), one subfolder per persona
    (`media/<persona_slug>/{reference,gallery,avatar,intro,voice,photos,videos}`); generated files
    named by their `MED-id` so DB rows ↔ files map 1:1. Backed by object storage (MinIO/S3) in prod.
  - **Removed `SUBSCRIPTION` and `DAILY_USAGE` tables** — monetization is deferred; `§3.7 Billing`,
    the `billing/` dir, and `§6.5` entitlement gating are marked deferred (the intended future
    design is kept, but no tables/paywall are in the current model). Note: `§1` UX copy and `§2.2`
    still mention the future 5-free-messages/subscription flow as intent.
- **Locked in the concrete self-hosted model stack** (replacing the earlier "candidate" lists)
  across `architecture.md` (§0 diagram, Pygmalion framework, §4.1, §4.3, §4.7, §6.2b, §6.3, §8)
  and `Project Concept.md`. Decisions:
  - **Chat LLM:** `Qwen3.5-35B-A3B-Uncensored` (HauhauCS "Aggressive") — uncensored MoE 35B/3B-
    active, 262K context (→1M YaRN), 0/465 refusals, Apache 2.0. Supersedes the old Llama 3.1 /
    Wizard-Vicuna candidates.
  - **Image gen/edit:** `Qwen-Image-Edit-Rapid-AIO` v23 **NSFW** variant — distilled + FP8 AIO
    build on Qwen-Image-Edit-2511 (~28 GB, 4–8 steps, community NSFW LoRAs baked in). Replaces
    Flux Ultra + IP-Adapter (Flux Ultra is closed/API-only — incompatible with the all-on-server
    requirement).
  - **Video split into two dedicated models:** intimate/no-speech → `Wan 2.2` (distilled);
    talking-head circles → `HunyuanVideo-Avatar` (audio-driven emotion). The latter **removes the
    external Hedra dependency** — all video is now self-hosted. `video/models/` now has
    `wan22/` and `hunyuan_avatar/` subdirs.
  - **Inference accelerator:** **LightX2V** — an inference *framework* (not a model) giving 4-step
    distilled checkpoints + INT8/FP8/NVFP4 for the image/video models so the night batch fits the
    GPU/time budget.
  - **Voice:** still **ElevenLabs** — now the *only* external/cloud model; noted open decision to
    self-host later (F5-TTS / XTTS-v2 / CosyVoice candidates).
  - Net result: the entire chat + image + video stack is self-hosted; only ElevenLabs (voice) and
    the external planning/reflection LLM remain off-server.
- Refined `architecture.md` §1 (UX) to match the reference Figma design ("🧠 AIT"): concrete
  **Welcome/Start screen** (flirty copy + single `Start` inline button), **"Choose Lady"**
  persona **card carousel** with `◀ 1/6 ▶` pagination — each card shows photo + **Name /
  Profession / Age / first-person Description** — and a `Start Chat` button; reply keyboard with
  **`💋 Choose Lady`** + menu (≡); video-note intro fires on Start Chat. Added gallery-card fields
  (`profession`, `age`, `card_description`, `gallery_photo_ref`) to the `PERSONA` entity in the
  ERD and to the Persona Service + persona-construction template. Updated the §1 flow diagram.
- Incorporated clarifications from the product Google Doc into `architecture.md` and
  `Project Concept.md`: the engine is the open-source **Pygmalion** framework (Digital Persona /
  Digital Human / Digital Self); **voice moved into scope** (ElevenLabs, personalized voice
  replies, first 5/day free); **proactive daily video circles**; concrete monetization
  (**5 free messages/day**, erotic photo access as daily/weekly/monthly subs); **roster of 10
  personas (5 RU + 5 EN)**; example persona Alina = Moscow psychologist/fitness; **Big Five**
  traits + voice profile + language in the persona model and ERD; added `DAILY_USAGE` entity for
  the free-message quota; named the candidate stack (Qwen/Llama 3.1/Wizard-Vicuna chat, Flux Ultra
  + IP Adapter imagery, Hedra talking-head video, ElevenLabs voice, Qdrant vector DB);
  distinguished self-hosted vs external/cloud model services; added a phased implementation
  roadmap (bot → daily circles+photos → adult media+storage → open-source Pygmalion) and a
  `voice/` module in the repo layout.
- Added `developer files/issue_log.md` — a tracker for problems the user reports where a feature
  doesn't work / the logic is wrong **despite all tests passing**. Each report gets an
  `ISS-<NNN>` id, a clear formulation, and a yes/no `[ ]`/`[x]` "fixed" checkbox; it is closed by
  fixing the gap at its source (adding `TC-` tests, refining `architecture.md`, adding/adjusting
  `FR-`/`NFR-` requirements). Has an index table, how-it-works steps, and an entry template. This
  is the mechanism for modernizing the architecture/coverage from real findings. Added the
  corresponding rule to `CLAUDE.md`.
- Added `developer files/architecture.md` — full system architecture across six levels:
  (1) UX (Telegram bot: welcome → persona gallery → video-note intro → chat with reply/inline
  keyboards → main menu/subscription); (2) API (Telegram webhook ingress + internal service
  endpoints, auth/idempotency/contracts); (3) Services (Bot Gateway, Conversation Orchestrator,
  Persona, Memory [SQL structured + vector semantic], Life Engine, Media Delivery, Billing,
  Persona Studio, media-gen services); (4) AI services (uncensored high-context chat LLM served
  by day; context assembly incl. recent raw messages; night-batch img2img photos + image+text
  video with pose/background/intimacy metadata; external LLM for planning/reflection/goals/
  relationship; biography time-pyramid day→…→epoch; persona construction via template +
  questionnaire Studio; versioned per-module prompts); (5) Data (Mermaid ERD + three DFDs:
  conversation turn, life cycle, night media gen); (6) Infrastructure (self-hosted GPU,
  containers, day/night GPU scheduler that unloads chat LLM to run media batch, data stores,
  module/dir layout, CI/CD with the tests/ merge gate, security/compliance). Persona "Alina" is
  just a configurable instance; core is persona-agnostic.
- Updated `test_driven_development.md` to make tests the **bridge between requirements and
  architecture**: added a core principle, a new "Architecture-driven testing" section (cover
  inter-service/integration paths, API contracts, all DFD flows, e2e journeys, cross-subsystem
  consistency, ERD integrity — "cover all scenarios the architecture makes possible"), and new
  test levels/checklist items (inter-service/contract, data-flow).
- Added `CLAUDE.md`: `architecture.md` added to the "before coding, re-read these" list.
- Added `developer files/test_driven_development.md` — English guide for how tests are designed:
  every requirement (`FR-`/`NFR-`) gets a *whole set* of tests (never one), aiming for exhaustive
  coverage (10k+ tests is normal/desired); test IDs `TC-<requirement-id>-<nn>` map back to
  requirement IDs; tests span levels (unit, integration, component/API, automated e2e, manual
  real-device e2e via physically opening Telegram, and non-functional perf/load/security). Two
  locations distinguished: **test specs** as one markdown per feature in `developer files/tests/`
  (mirroring `features/`), and **test code** in the repo-root `tests/` folder (the one the merge
  rule gates on). Includes a per-requirement coverage checklist, minimum-coverage rules, a
  template, and a worked example expanding one requirement into a set of tests.
- Moved `feature_description_guide.md` from `developer files/features/` up to `developer files/`
  (both guides now sit at the developer-files root). Created empty `developer files/tests/` folder
  (kept via `.gitkeep`) for per-feature test specs; `features/` keeps a `.gitkeep` too.
- Added `CLAUDE.md` rules: (a) before any coding/development, re-read and keep in context the core
  guides + relevant feature/test files; (b) every requirement is covered by a full set of tests
  documented in `developer files/tests/`.
- Created `developer files/features/` folder and added `feature_description_guide.md` —
  a full English
  guide for how to document every product feature. Defines: file naming (`F-<NNN>-<slug>.md`),
  an ID scheme for traceability to tests (`F-`, `US-`, `UC-`, `FR-`, `NFR-`), and the required
  per-feature structure — (1) user stories per user category ("As a … I want … so that …" +
  concrete narrative), (2) user-flow diagrams (Mermaid, per user), (3) use cases in Gherkin/BDD
  (Given/When/Then, And/But, Scenario Outline), (4) functional + non-functional requirements
  each with a stable ID. Includes a copy-paste template and a complete worked example (F-000
  onboarding). Added a pointer to this guide in `CLAUDE.md` under the feature-branching rule.
- Rewrote `developer files/user_metrics.md` to remove all numeric targets (they weren't
  well-understood yet) and instead describe, in words, the **ideal use case** and requirements
  per audience segment. Opens with shared quality dimensions (conversational realism, SFW photo
  hyper-realism, NSFW intimate realism, memory, responsiveness, feeling alive/available), then
  gives a narrative "ideal scenario + what he wants/requires" for every segment in Groups A/B/C.
- (Superseded) Previously `user_metrics.md` held a numeric SMART metric catalog (M1–M8) with
  per-segment priority ratings; replaced by the qualitative version above at the user's request.
- Added `developer files/Project Concept.md` — the core product concept plus a per-segment
  mapping of how NeuroLady solves each audience's pain. Opens with the product definition and
  four believability pillars (human conversation with long-term memory, consistent appearance,
  consistent + auto-updating biography, rich proactive media incl. adult content where legal;
  north star = extended real-world Turing test), then walks all ~16 audience segments from
  `Audience.md` (Groups A/B/C) describing pain → concrete solution for each.
- Added a CLAUDE.md rule for future feature work: self-contained features must be built on a
  dedicated branch (`feature/<short-name>`), not directly on `master`; a feature branch may
  only be merged into `master` after all tests in `tests/` pass. Doc-only/config changes are
  unaffected and continue to go straight to `master` per the existing workflow.
- Moved `Audience.md` into `developer files/` (was briefly at the repo root). All future
  project documentation (concept, audience, research/planning notes) is now stored in
  `developer files/` — the intended single place for developer context — with `CLAUDE.md`
  as the sole exception, staying at the repo root so Claude Code auto-loads it.
- Added `Audience.md` — the product's target-audience definition. Structured
  into three macro-groups (A: B2C end users, B: B2B operators/businesses using NeuroLady as an
  engine, C: academic/scientific community) with ~16 segments profiled across geography, age,
  gender, income, tech-savviness, psychographics, pain points/JTBD, willingness to pay,
  acquisition channels, retention drivers, and objections/risks. Includes prioritization
  (beachhead = Russian-speaking Gen Z) and an ethics/positioning note. `Project Concept.md`
  is intentionally deferred to the next step per the user's request to start with audience.
- Moved `CLAUDE.md` back to the repo root (Claude Code auto-loads CLAUDE.md from the project
  root, so it needs to live there). `PROJECT_STATUS.md` and `VERSION` remain inside
  `developer files/`.
- Moved `CLAUDE.md`, `PROJECT_STATUS.md`, and `VERSION` into a `developer files/` subfolder
  at the repo root (were previously at the repo root directly). `CLAUDE.md` was updated to
  reference the new paths.
- Added `CLAUDE.md` rule requiring this `PROJECT_STATUS.md` file to be kept up to date with
  technical details after every meaningful change.

## Repository setup

- Local project directory: `/home/human/NeuroLady_Final`.
- Git repository initialized locally (`git init`), default branch `master`.
- Remote `origin` set to `https://github.com/b3ly4ck/NeuroLady_Persona_Engine.git`, branch
  `master` pushed and tracking `origin/master`.
- Authentication: HTTPS via a GitHub Personal Access Token, stored through git's own
  credential store (`git config credential.helper store`, entry in `~/.git-credentials` as
  `https://x-access-token:<token>@github.com`). The token itself is intentionally **not**
  recorded in any memory/markdown file for security reasons.
- Global git identity was corrected: `~/.gitconfig` previously had a stale/unrelated identity
  (`igor-rah <ibryzhikov@ya.ru>`), which was replaced with `user.name = b3ly4ck` and
  `user.email = viktorbeliakovv@gmail.com`. All existing commits in this repo were rewritten
  (via `git filter-branch`) to this identity and force-pushed to GitHub.

## CLAUDE.md conventions established for this project

- **Git workflow**: every change to the project is committed and pushed to `origin master`
  automatically, without asking for confirmation for the commit/push itself.
- **Commit message format**: `v{MAJOR.MINOR.PATCH} [{type}]: {description}`, with the version
  tracked in a `VERSION` file at the repo root and bumped per change type (`fix`/`refactor`/
  `docs`/`chore`/`style`/`test` → patch bump; `add`/`feat` → minor bump; breaking changes →
  major bump).
- **Feature branching**: self-contained features go on a dedicated `feature/<short-name>`
  branch and may only be merged into `master` once all tests in `tests/` pass.
- **Before coding**: re-read the core guides (`feature_description_guide.md`,
  `test_driven_development.md`) and relevant feature/test files before starting development.
- **Testing**: every requirement is covered by a whole set of tests (test specs in
  `developer files/tests/`, test code in the repo-root `tests/` folder).
- **Feedback logging**: whenever the user corrects an approach or states a preference, it is
  appended to the "Preferences and feedback" section of `CLAUDE.md` with a date, so it isn't
  repeated.
- **Language**: all `.md` files in this project must be written in English.
- **Project status**: this file (`PROJECT_STATUS.md`) must be kept current with technical
  detail on what has been built, to preserve context across sessions.

## Product / concept documentation

- `developer files/Audience.md` — target audience definition (see Recent changes).
- `developer files/Project Concept.md` — core product concept (Telegram-based hyper-realistic
  AI companion, personality engine, four believability pillars, extended real-world Turing test
  as the north-star goal) plus a per-audience-segment pain → solution mapping.
- `developer files/user_metrics.md` — qualitative (no numbers) description of the ideal use
  case and requirements per audience segment, plus shared quality dimensions.
- `developer files/feature_description_guide.md` — guide for how to document features
  (structure, ID scheme, template, worked example). Individual feature files (`F-<NNN>-*.md`)
  go in `developer files/features/` — none written yet.
- `developer files/test_driven_development.md` — guide for how to design tests (set of tests per
  requirement, levels/categories, ID scheme, template, worked example; architecture-driven
  testing section bridging requirements ↔ architecture). Per-feature test specs
  (`F-<NNN>-*.md`) go in `developer files/tests/` — none written yet.
- `developer files/architecture.md` — six-level system architecture (UX, API, services, AI
  services, data ERD/DFD, infrastructure) with Mermaid diagrams; persona-agnostic core,
  day/night GPU schedule, Life Engine reflection pyramid.
- `developer files/issue_log.md` — tracker for reported problems that pass tests but are still
  wrong; `ISS-<NNN>` ids with fixed/not-fixed checkboxes, closed by improving docs/tests/arch.

## Current state of the codebase

- No application code yet — the repository contains `CLAUDE.md` at the root, plus a
  `developer files/` folder with `VERSION`, `Audience.md`, `Project Concept.md`,
  `user_metrics.md`, `feature_description_guide.md`, `test_driven_development.md`, this
  `PROJECT_STATUS.md`, and empty `features/` and `tests/` subfolders (kept via `.gitkeep`). No
  NeuroLady persona engine code, and no repo-root `tests/` code folder, has been added so far.
