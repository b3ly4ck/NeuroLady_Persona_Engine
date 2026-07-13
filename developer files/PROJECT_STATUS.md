# Project Status — NeuroLady_Final

## Recent changes

- **Etap 3 — F-003 human-likeness slice (delivery pacing + chunking + comm-settings style) on branch
  `feature/f-002-conversation`.** Layered the "she texts like a real person" behaviour onto the F-002
  loop; no new infra (pure delivery/style, consistent with the Postgres-only slice). Validated live.
  - **`services/bot/domain/humanize.py`** — the mechanical half of F-003: `parse_settings` (reads the
    persona's `comm_settings_json`, defaults when absent/garbled — FR-003-34), `chunk_reply` (splits a
    wall of text into ≤`MAX_CHUNKS` short messages at sentence boundaries, single/one-sentence replies
    stay whole, chunks reconstruct the original text so meaning is preserved — FR-003-09/11/14/38),
    `pacing_delay` (length-scaled, typing-speed-scaled, jittered, **capped at 6 s** — FR-003-01/02/05/06/08).
  - **`services/bot/handlers/conversation.py`** — delivery now sends `typing…` + a paced pause before
    each chunk and answers chunk-by-chunk in order (FR-003-03/09/10). `_sleep` indirection lets tests
    skip the real pauses.
  - **`services/bot/domain/persona_prompt.py`** — the stylistic half: a style line derived from
    `comm_settings` (register, emoji frequency, slang, verbosity) is injected into the persona system
    prompt (architecture.md §4.2 — communication style is part of the prompt), so the model writes
    in-style (FR-003-16/17/21/24). Content/correctness stays owned by F-002 (FR-003-38).
  - **`services/bot/personas_seed.py`** — the 6 starter personas now carry distinct `comm_settings`
    (pacing/verbosity/emoji/register/slang) + `big_five`, so they read as different texters (FR-003-35).
  - **Tests:** `tests/test_f003_humanize.py` (15) — settings parse/defaults/bad-json, chunking
    (short→1, long→several, cap, single-long-sentence, meaning preserved), delay bounds/scaling/cap,
    prompt style directives, and a handler test asserting a long reply is delivered as several ordered
    messages. Updated the F-002 handler test for the new chunked delivery. **Full suite: 93 passed**
    (58 F-001 + 20 F-002 + 15 F-003).
  - **Live check:** Alina's long weekend story split into 4 natural chunks (~4–6 s typing each); Vika
    (emoji/slang) vs Olivia (gentle, ~no emoji) read as visibly different texters from the same prompt.
  - **Deferred (next):** F-003's statistical anti-repetition/variability, per-user interaction-style
    overlay (`USER.interaction_style_json`), and in-exchange follow-up; plus F-004 memory + F-005
    relationship on the orchestrator TODO hooks.
- **Etap 2 — F-002 conversation turn (thin vertical slice) wired onto the F-001 bot (branch
  `feature/f-002-conversation`, off `feature/chat-inference`).** The persona now actually talks:
  plain text in an active session → in-character LLM reply, validated end-to-end against the live
  chat runner. Scope per the agreed thin slice: one persona, Postgres/SQLite only, memory
  (F-004)/relationship (F-005)/human-likeness styling (F-003) stubbed with TODO hooks.
  - **`services/bot/models.py`** — added the `MESSAGE` model + `MessageSender` enum
    (ERD §5.1 SESSION||--o{MESSAGE); `media_asset_id` nullable now so the media feature needs no
    migration.
  - **`services/bot/chat_client.py`** — async OpenAI-compatible client to the runner (§6.2c). Raises
    `ChatRunnerUnavailable` on transport/timeout/5xx/empty so the Orchestrator can fall back
    in-character (FR-002-19); `is_ready()` for the cold path (FR-002-24). Optional `transport` hook
    for tests.
  - **`services/bot/domain/messages.py`** — persist a turn + `load_recent()` (last-N verbatim window,
    FR-002-04) + `to_openai_messages()` role mapping (persona→assistant).
  - **`services/bot/domain/persona_prompt.py`** — builds the persona system prompt (§4.2 part 1):
    identity + Big Five + self-description + reply-language instruction (FR-002-21) + the hard
    never-reveal-AI / no-assistant-voice rule (FR-002-08/NFR-002-10).
  - **`services/bot/orchestrator.py`** — the turn (§3.2/DFD-1): persist user msg first (input never
    lost on failure) → assemble system + recent raw history → call runner → post-process (strip stray
    `<think>`) → in-character fallback on failure → persist reply. TODO hooks mark where F-004/F-005/
    F-003 slot in.
  - **`services/bot/handlers/conversation.py`** — new router (included *after* onboarding so `/start`,
    gallery callbacks and the 💋 Choose Lady button keep priority) handling non-command text in an
    active session: send `typing…` immediately (FR-002-24), run the turn, answer; nudge to Choose Lady
    if no active session. `ChatClient` injected via dispatcher workflow data.
  - **Wiring:** `handlers/__init__.py` now a parent router (onboarding → conversation);
    `app.build_dispatcher` builds/injects the `ChatClient`; `config.chat_base_url` +
    `.env.example CHAT_BASE_URL` (corrected the stale `CHAT_LLM_BASE_URL:8001` placeholder to the
    real `:8080`); `pyproject.toml` gains `httpx`.
  - **Tests:** `tests/test_f002_conversation.py` — 20 tests (context assembly incl. verbatim history,
    persistence + order, empty-history first turn, post-processing, fallback + input-preserved,
    persona-prompt in-character rule + language, recent-history helpers, ChatClient wire contract via
    `httpx.MockTransport`, handler typing-then-reply + no-session nudge). **Full suite: 78 passed**
    (58 F-001 + 20 F-002). Live end-to-end check confirmed in-character RU replies and that the
    "are you a bot?" probe does not break character.
  - **Next:** layer F-004 memory (Postgres + Qdrant) and F-003 styling onto the TODO hooks; live
    Telegram test needs a fresh `TELEGRAM_BOT_TOKEN` (the earlier one leaked in the public repo and
    must be revoked via BotFather).
- **Etap 1 — chat inference reference is live (branch `feature/chat-inference`).** Stood up the
  self-hosted Chat-LLM serving layer (architecture.md §4.1/§6.1/§6.2c) and validated it end-to-end
  on the target GPU (Quadro RTX 8000, 48 GB, Turing sm_75, CUDA 12.1):
  - **Backend:** `llama-cpp-python[server]` (prebuilt cu121 wheel, CUDA offload confirmed), installed
    into the isolated `chat/.venv` only. Exposes the fixed **OpenAI-compatible** contract
    `POST 127.0.0.1:8080/v1/chat/completions` the Orchestrator (F-002) will call.
  - **`chat/serve.py`** — supervisor that launches the server with tuned defaults (full GPU offload
    `--n_gpu_layers -1`, `--n_ctx 16384`, `--flash_attn`, prompt cache), waits until the model is
    loaded, fires a **warm-up inference**, then writes `chat/.runner_ready` + logs `READY: model
    warm` — the readiness gate from §4.1 (never "process started", always "model warm"). All knobs
    are env-overridable (documented in the file header).
  - **Reasoning disabled by default.** This Qwen3.5-A3B GGUF is a *reasoning* model: its chat
    template opens a `<think>` block at every turn, so out of the box it emitted a long
    "Thinking Process: …" chain-of-thought that ate the whole token budget and >5 s of latency
    before any reply. Fixed by passing `--chat_template_kwargs '{"enable_thinking": false}'` at model
    load (env toggle `CHAT_ENABLE_THINKING=1` to re-enable). With thinking off the model answers
    directly and in-character.
  - **`chat/smoke.py`** — the reference benchmark (latency + tok/s). Measured on this box:
    weights **28 GB / 48 GB** VRAM (≈20 GB headroom for KV cache), warm-up **0.34 s**, warm replies
    **~0.8–1.0 s** for short texts (~40–65 tok/s), comfortably under the F-002 `NFR-002-01` <5 s
    budget. Output is clean, in-character, natural Russian.
  - **`chat/prompts/context_assembly.md`** — versioned prompt asset describing the F-002 context
    bundle priority order (§4.2); notes the thin-slice assembly (persona system prompt + recent raw
    history + current message) with memory/relationship layers added later without changing the
    contract.
  - `chat/README.md` Serving section updated to the real install/run commands (docs-first).
  - **Next (Etap 2):** extend the existing F-001 bot with the F-002 conversation turn — add a
    `MESSAGE` model, a chat-runner client, an Orchestrator (assemble persona system prompt + last-N
    raw history → call the endpoint → reply), and a plain-text handler. One persona (Alina), Postgres
    only (Qdrant/F-004 deferred), per the agreed thin vertical slice.
- **Wrote the F-006 test spec** (`developer files/tests/F-006-life-engine.md`), the mirror test
  specification for the Life Engine feature, per `test_driven_development.md` §7 and the F-004
  example. Covers **all 21 FR (FR-006-01..21)** and **all 13 NFR (NFR-006-01..13)** at 2-3 tests each
  (3 for the critical ones: daily plan FR-006-01, plan-inputs FR-006-02, self-reflection FR-006-05/-06,
  compression pyramid FR-006-07/-08, aging-up FR-006-09, layer-consistency FR-006-10, goals
  FR-006-11/-12/-13, fixed-anchor immutability FR-006-14, self-consistency FR-006-15, timezone
  FR-006-16, hand-off FR-006-17, versioned prompts FR-006-19, degrade FR-006-20, auditability
  FR-006-21; and NFR-006-01/-03/-04/-05/-06/-07/-08/-09/-10), plus **1 manual real-device acceptance
  test per user story** (US-006-01..08). Emphasizes the daily-plan free-text schedule + current-activity
  derivation, first-person self-reflection with no user-fact leak, the hierarchical compression
  (7 daily→weekly→monthly→yearly→epoch, mirroring the UC-006-04 outline), gist-not-detail aging,
  fixed-anchor immutability + no self-contradiction under probing, goals progress/feed-plan, timezone
  correctness (different zones + DST), off-hot-path batch, degrade-keep-last-good-state (never "no
  day"), bounded storage, auditability, and RU/EN localization. Levels span unit/integration/
  inter-service/data-flow/component/e2e/performance/load/security/consistency/statistical.
  **Counts: 60 FR + 35 NFR + 8 US = 103 tests (21/21 FR, 13/13 NFR, 8/8 US — full coverage, in the
  100-150 band).** Every TC id embeds its `FR-`/`NFR-`/`US-` id. Life Engine (F-005 + F-006) now has
  both feature files and both mirror test specs.
- **Wrote the F-005 test spec** (`developer files/tests/F-005-relationship-system.md`), the mirror
  test specification for the Relationship System feature, per `test_driven_development.md` §7 and the
  F-004 example. Covers **all 28 FR (FR-005-01..28)** and **all 13 NFR (NFR-005-01..13)** at 2-3 tests
  each (3 for the critical ones: stage derivation FR-005-03, hysteresis FR-005-04, bounded change
  FR-005-13, asymmetric trust FR-005-16, pacing/consent FR-005-17, exposure FR-005-19, stage-gating
  FR-005-20, milestones FR-005-22, storage-hand-off FR-005-24, per-user isolation FR-005-25,
  degrade-on-failure FR-005-27; and NFR-005-01/-02/-04/-05/-06/-11), plus **1 manual real-device
  acceptance test per user story** (US-005-01..08). Emphasizes the derived-stage table (mirrors the
  UC-005-03 outline as boundary tests), hysteresis advance/regress margins, bounded per-reflection
  delta (no stranger→love jump), decay-on-neglect, asymmetric trust, pacing/consent guard (statistical
  no-escalation), clamp 0-100 always valid, auditability (RELATIONSHIP_REFLECTION logged), per-user
  isolation, off-hot-path timing, degrade-keep-last-good-state, and no-mechanics-leak. Levels span
  unit/integration/inter-service/data-flow/component/e2e/performance/load/security/consistency/
  statistical; cases span happy/negative/boundary/error/idempotency/mapping/localization.
  **Counts: 70 FR + 32 NFR + 8 US = 110 tests (28/28 FR, 13/13 NFR, 8/8 US — full coverage, in the
  100-150 band).** Every TC id embeds its `FR-`/`NFR-`/`US-` id. **Next:** the F-006 test spec.
- **Designed & wrote F-006 — Life Engine** (`developer files/features/F-006-life-engine.md`): the
  persona's *own* living, the sibling of F-005 (F-005 = per-user relationship; F-006 = her own life).
  The living loop: **morning Planner** → `DAILY_PLAN.plan_text` free-text schedule (drives media +
  "what she's doing now"); **end-of-day self-Reflector** → first-person daily `REFLECTION`;
  **hierarchical compression** 7 daily→weekly→~4 weekly→monthly→12 monthly→yearly→epochs, each an LLM
  prompt, stored as `BIOGRAPHY_LAYER` handed to Memory (F-004) for embedding; **goals** that progress/
  add/complete and feed the plan. Key design points: **fixed anchors** (name/core values/Big Five/
  epochs) immutable & never contradicted vs **evolving** recent life; **aging up** (old detail → gist,
  bounded storage); **timezone-driven** scheduling coordinated with the day/night compute window;
  **persona-shared, not per-user** (no user-specific facts leak into the shared biography — privacy);
  degrade-on-LLM-failure (keep last good state, never "no day"). Includes a **Design model** section +
  **8 US / 13 UC / 21 FR / 13 NFR**. **Scope boundary:** F-006 authors her inner life; F-005 owns the
  relationship reflection, F-004 stores the rows, media pipeline generates the pixels/circles (F-006
  gives the "story from her day" basis), F-002 consumes her current activity/biography, Persona Studio
  authors initial identity. **Architecture synced:** §3.5 (F-006 spec pointer), §4.5 (authored-by
  note), §5.1 `GOAL` gains `status enum`/`horizon`/`created_at`. Life Engine subsystem (§3.5) now
  fully specced across F-005 + F-006. **Next:** test specs for F-005 and F-006.
- **Designed & wrote F-005 — Relationship System** (`developer files/features/F-005-relationship-system.md`),
  fulfilling architecture.md §4.6's "relationship scale is a design deliverable". **Design:** per
  `(user, persona)`, three configurable 0–100 dimensions **Closeness / Trust / Attraction** (the
  owner's "significance / trust / (third)" — chose Attraction over the vague "intention" for the
  flirt→love arc) + a **derived stage** `Stranger→Acquaintance→Friend→Flirting→Romance→Love→Devoted`
  (highest gate met, with **hysteresis**). Evolves via a **relationship reflection**: the Life Engine
  hands the external LLM the current state + recent conversation + hard signals (days since contact,
  frequency, warmth) → bounded per-dimension deltas + rewritten summary → clamp 0–100, per-reflection
  cap (gradual, no jumps), re-derive stage, log a `RELATIONSHIP_REFLECTION`. Guardrails: neglect
  **decay**, **asymmetric trust** (slow up, faster breach), **pacing/consent** (pushing fast at low
  trust doesn't escalate and can lower trust — A4 safety), gentle regression, per-user isolation,
  degrade-on-LLM-failure (keep last good state). State is fed into every reply (F-002 §4.2) and
  **gates the persona's openness/flirtiness/intimacy by stage** — the progression is *felt*.
  Includes a **Design model** section + **8 US / 13 UC / 28 FR / 13 NFR**. **Scope boundary:** F-005
  owns the model + evolution; F-002 generates replies (consumes the state), F-004 stores the rows,
  the sibling Life Engine feature (F-006, next) owns her *own* self-reflection/biography/goals/daily
  plan; intimate-media *paywall* is separate/deferred. **Architecture synced:** §4.6 (concrete
  relationship model), §5.1 `RELATIONSHIP` entity (`scale_json` → `stage`/`closeness`/`trust`/
  `attraction`/`summary`/`last_interaction_at`), §3.5 relationship-reflection bullet. **Next:** the
  F-005 test spec, and F-006 (Life Engine: daily plan, self-reflection, biography pyramid, goals).
- **F-001 live-tested and approved by the user; noted a future-work item.** User confirmed the
  reworked onboarding flow works correctly end-to-end in live Telegram testing. Logged a **known
  future work** note in `F-001`'s Scope boundary: the S3 opener (`intro_opener`) and the S2/S3 photo
  are currently **static** (one canned line + one fixed image per persona); once the Chat LLM (F-002)
  and media generation (roadmap Phase 2) exist, both should become **dynamically generated** — an
  LLM-written, in-character hook drawing the user into replying, paired with a generated/selected
  photo, rather than the same static line/image for every user. Not implemented now — tracked so
  it isn't lost. **Merged `feature/f-001-onboarding` into `master`** (58/58 tests green, per the
  CLAUDE.md merge rule).
- **Removed the main menu entirely — explicit product decision: "no menu, ever" (docs-first).** The
  user rejected the `≡ Menu` screen (Choose Lady / Resume chat) outright — one reply-keyboard action
  only: `💋 Choose Lady`. Docs first: `architecture.md` §1.1 (flow diagram no longer has a MENU node;
  canonical order note updated), §1.2 (reply keyboard = single Choose Lady button; dropped the "Main
  menu" bullet), §1.3 (new "No main menu" principle). `F-001`: **FR-001-16 marked `DEPRECATED`** (ids
  are immutable — never deleted/reused, per `feature_description_guide.md`); FR-001-12/03/15/24 and
  NFR-001-07 reworded to drop all menu/resume wording; user flows and UC-001-04/05 updated (resuming
  is now just "pick the same persona again on Choose Lady" via FR-001-10's session reuse — no
  separate resume action). While in the file, also **backfilled test-spec coverage that had drifted
  out of sync** with the feature file: added missing FR-001-21/22/23/24 and NFR-001-11 sections
  (were added to the feature earlier but never given tests in the spec), updated FR-001-15/16 tests
  and the US-001-05 manual test for current behavior. Test spec now 113 tests (110 active + 3
  deprecated), 24/24 FR + 11/11 NFR + 6/6 US ids present.
  Code: removed `keyboards.menu_kb`, `views.menu_view`, `i18n` menu/resume/resumed keys,
  `on_choose_lady_cb`/`on_menu_text`/`on_resume` handlers, `_MENU_LABELS`, and the now-unused
  `get_active_session` import; `reply_kb` now renders a single button. Updated/added tests
  accordingly (incl. a guard test asserting the menu handlers no longer exist). **58 tests green.**
- **Fixed a live-tested bug: Start Chat deleted the S2 screen and sent nothing (docs-first).** The
  prior implementation deleted the card + intro *before* sending the S3 opener; if that send raised
  (e.g. a transient network error — the unwrapped photo/text send paths in `send_persona_intro` had
  no try/except), the exception aborted the handler after the deletes but before anything new
  landed, leaving the chat blank. Root-caused to a missing **send-before-delete** ordering guarantee.
  Fixed the **general rule** first: `architecture.md` §1.3 now states it explicitly (new content
  must be sent, and the send must succeed, *before* old content is deleted — never the reverse; on
  a failed send, old content stays); `F-001` **FR-001-21/23/24** reworded to require this ordering.
  Then code: `on_start_chat` now sends the S3 opener **first**, and only deletes the S2 card/intro
  **after** that succeeds (wrapped so `cb.answer()` still fires via `finally` even on failure, and
  the exception still propagates/logs rather than being swallowed); `_open_gallery` likewise sends
  the new intro before deleting any stale tracked one. Added
  `test_fr_001_21_03_send_before_delete_failed_send_keeps_old_screen` (asserts nothing is deleted
  when the send raises). **58 tests green.**
- **"Hide the bot chrome" — delete transient/utility messages so the chat reads like a real
  conversation (docs-first).** New UX principle in `architecture.md` §1.3 (delete the user's slash
  commands, reply-keyboard button taps, the gallery intro, and stale cards once they've served their
  purpose; **hard rule: never delete a user's command before it has been processed/responded to**).
  In `F-001`: extended **FR-001-21** (Start Chat now deletes **both** S2 messages — card **and**
  intro) and added **FR-001-23** (delete the `/start` message, only *after* responding) and
  **FR-001-24** (delete `💋 Choose Lady` / `≡ Menu` reply-keyboard taps after handling). Then
  implemented: `_open_gallery` tracks the intro message id (in-memory `_intro_msg_ids`, per chat;
  noted as dev-single-process — Redis/FSM for multi-instance); `on_start_chat` deletes the card +
  tracked intro; `cmd_start` deletes `/start` after the response; `on_choose_lady_text`/`on_menu_text`
  delete the tap. All deletes are best-effort (`_safe_delete_*`). **57 tests green** (added intro-
  delete, intro-tracking, and menu-tap-delete tests; asserted /start and Choose-Lady taps are
  deleted).
- **Bot process now self-heals from Telegram network blips instead of crashing (docs-first).** The
  process died 3× during live testing with `OSError [WinError 121] semaphore timeout` connecting to
  `api.telegram.org` — a flaky-network issue (matches the user's own reported internet drops), but
  the process had no retry around the initial `getMe()` check, so it exited and needed a manual
  restart every time. Added **NFR-001-11** to `F-001` and a matching "Bot Gateway resilience to
  network blips" note to `architecture.md` §6.1 (retry with capped exponential backoff
  indefinitely, never crash-exit), then implemented `_run_polling_with_reconnect` in `app.py`
  (wraps `dp.start_polling`, catches `TelegramNetworkError`/`OSError`, backs off 1→2→4→8→16→30→60s
  capped, retries forever) and wired it into `main()`. Added `tests/test_f001_reconnect.py` (3
  tests: retries-then-succeeds, raw `OSError` also retried, backoff grows and is capped).
  **54 tests green.**
- **Final F-001 polish: delete the stale card on Start Chat + wire persona photos (docs-first).**
  Added `F-001` **FR-001-21** (on Start Chat, delete the persona-card message so it doesn't linger)
  and **FR-001-22** (S2 card and S3 opener include the persona's photo when one exists), updated the
  flow diagram + `architecture.md` §1.1/§1.2, then implemented: `on_start_chat` deletes `cb.message`
  (the card) before sending the opener; `personas_seed` sets each persona's `gallery_photo_ref` to
  `media/<slug>/gallery/card.jpg` (helpers `persona_slug` / `gallery_photo_path`). The photo path was
  already supported by `_send_card` (photo message + caption) and `send_persona_intro` (photo opener);
  it stays a graceful text fallback until a real image is dropped at that path (`media/` is
  git-ignored; per-persona `gallery/` folders created locally). **51 tests green** (added
  `test_fr_001_21_01` card-delete and `test_fr_001_22_01` photo-on-card-and-opener using a temp file).
- **`/start` is now a "home" action — always goes to Choose Lady, never resume-locks (docs-first).**
  Per the reference, `/start` must take the user to the Choose Lady main screen even mid-chat.
  Updated docs first (`F-001` FR-001-15 + UC-001-05 + returning-user flow; `architecture.md` §1.1
  note), then code: `cmd_start` now shows Welcome (S1) only to a **brand-new** user (first ever
  `/start`) and drops a **returning** user straight onto Choose Lady (S2); it no longer resumes the
  active chat. The active session is **preserved** (not ended), so `Menu → Resume chat` still returns
  to that persona. Updated `test_fr_001_15_02` accordingly. **49 tests green.**
- **Reworked the onboarding screen flow to match the reference design (docs-first).** The user
  supplied reference screenshots defining the canonical screen order S1→S2→S3 and screen contents;
  per the reaffirmed **docs-first rule** (now in CLAUDE.md), documentation was updated *before* code:
  `architecture.md` §1.1 (new S1/S2/S3 flow diagram + explicit "canonical screen order" list) and
  §1.2 (S2 = intro message carrying the reply keyboard **+** a separate persona-card message with
  photo + `Profession:`/`Age:`/`Description:`; S3 = photo/video-note + first-person opener; reply
  keyboard first appears on S2; `🎧 Chat via Audio` deferred to the voice phase), and `F-001`
  (FR-001-03/04/11, first-time user flow). Then the bot was reimplemented to match: `i18n.py` richer
  gallery intro + labeled card fields + opener + `resumed` copy (RU/EN); `views.py` `gallery_intro_view`,
  `card_body` (labeled, persona-language), `CardContent` (photo_ref + body + kb), `intro_opener`;
  `handlers/onboarding.py` opens S2 as intro+card, paginates by **editing the card in place**, and
  S3 sends a single opener (photo-caption / text) carrying the reply keyboard (video-note path sends
  the circle then the opener). **49 tests green.** New docs-first workflow rule + the earlier
  "no stacked nudges" rule are logged in CLAUDE.md.
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
