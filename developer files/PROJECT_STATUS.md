# Project Status — NeuroLady_Final

## Recent changes

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
