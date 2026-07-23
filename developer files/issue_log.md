# Issue Log — NeuroLady

This file is the mechanism for tracking issues the product owner reports where **a feature does
not work, or the logic is wrong, even though all tests pass**. Passing tests do not prove the
product is right — they only prove the cases we thought of. When a real-world gap is found, it is
logged here, given an ID and a yes/no "fixed" checkbox, and closed by **updating the
documentation, tests, or architecture** to cover the gap. This is how the architecture and test
coverage get modernized from real findings over time.

---

## How it works

1. **Log it.** When the user reports such an issue, assign the next `ISS-<NNN>` id and add an
   entry below, formulating the report clearly, with the status checkbox **unchecked** `[ ]`.
2. **Investigate the gap.** Find *why the tests passed anyway* — usually a missing/incorrect
   test, an architecture flaw, or a requirement that was never written.
3. **Close it by improving the docs.** Fix the gap at its source:
   - add or correct tests (new `TC-` cases) in the relevant `developer files/tests/F-<NNN>-*.md`
     (and the runnable `tests/` code),
   - refine `architecture.md` where the design was wrong or under-specified,
   - add/adjust requirements (`FR-`/`NFR-`) in the feature file,
   - update any other affected guide.
4. **Mark it fixed.** Flip the checkbox to `[x]`, record what was changed and the date.

**ID scheme:** `ISS-<NNN>`, zero-padded, ever-increasing, **immutable**, never reused. An issue
that turns out invalid is marked `[x]` with resolution "not an issue — <why>", not deleted.

**Status meaning:** `[ ]` = open (not fixed yet) · `[x]` = fixed (gap closed in the docs/tests/
architecture).

---

## Index

| ID | Title | Fixed | Reported | Resolved |
|----|-------|:-----:|----------|----------|
| ISS-001 | Start Chat on a resumed session sends nothing and deletes S2 → empty chat | [x] | 2026-07-16 | 2026-07-16 |
| ISS-002 | Persona gallery card renders with no photo | [ ] | 2026-07-23 | — |
| ISS-003 | Photo caption arrives in English for a Russian-speaking persona | [ ] | 2026-07-23 | — |
| ISS-004 | Photo is delivered instantly — no human pacing, unlike text | [ ] | 2026-07-23 | — |
| ISS-005 | Keyword photo-intent detection misses natural phrasing | [ ] | 2026-07-23 | — |
| ISS-007 | A slow turn locks SQLite → the next message dies and the user gets total silence | [x] | 2026-07-23 | 2026-07-23 |
| ISS-006 | She invents a background for a photo she just sent — the sent photo is not in her context | [x] | 2026-07-23 | 2026-07-23 |

---

## Entry template

~~~markdown
## ISS-<NNN> — <short title>

- **Status:** [ ] fixed
- **Reported:** <YYYY-MM-DD>
- **Report (as stated):** <the user's report, formulated clearly — what doesn't work / what
  logic is wrong, and in what situation>
- **Observed vs expected:** <what happens> vs <what should happen>
- **Why tests didn't catch it (the gap):** <missing test case / wrong architecture / missing
  requirement / …>
- **Resolution:** <what was changed to close the gap — e.g. added TC-FR-003-04-07..09,
  clarified architecture.md §3.5, added NFR-003-02>
- **Resolved:** <YYYY-MM-DD, or — while open>
~~~

---

## Issues

## ISS-001 — Start Chat on a resumed session sends nothing and deletes S2 → empty chat

- **Status:** [x] fixed
- **Reported:** 2026-07-16
- **Report (as stated):** In a fresh-looking chat (the user had deleted the Telegram chat
  client-side), `/start` → gallery → Alina → **Start Chat** deletes the gallery intro + persona
  card and sends **nothing** — the chat ends up completely empty. Picking Vika instead works
  (opener arrives), and after Vika, picking Alina works too.
- **Observed vs expected:** Start Chat left the chat with zero messages vs Start Chat must always
  end with a message from the persona.
- **Root cause:** the user still had an **active DB session** with Alina from earlier use (sessions
  survive bot restarts and the user's client-side chat deletion, which the bot cannot see).
  `start_or_switch_session` returned `is_new_intro=False` (same-persona reuse), and `on_start_chat`
  applied FR-001-17's "don't re-send the intro" to **every** reuse — then deleted the S2 card +
  intro, leaving a void. Vika had no active session (new → opener); re-picking Alina after Vika is
  a *switch* (new session → opener) — which is exactly why the bug looked persona-specific.
- **Why tests didn't catch it (the gap):** `TC-FR-001-17-*` asserted *no duplicate intro* on
  double-tap, but **no test asserted that a resumed-session Start Chat still sends anything**, and
  FR-001-17 itself conflated two different situations (rapid double-tap vs returning via the
  gallery later).
- **Resolution:** FR-001-17 reworded (F-001 feature + test spec): rapid duplicate taps are
  **deduplicated** (a short in-memory guard window), but a resumed-session Start Chat **always
  sends a short in-character resume opener** — Start Chat never leaves the chat without a persona
  message (architecture.md §1.3 principle added). Code: `on_start_chat` resume branch +
  `resume_opener` view + i18n copy + opener guard; tests updated/added
  (`test_fr_001_17_*` reworked, resume-sends-message + double-tap-dedup cases).
- **Resolved:** 2026-07-16

---

## ISS-002 — Persona gallery card renders with no photo

- **Status:** [ ] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** In the S2 gallery the persona card (Alina — Psychologist, 28) shows only
  text and the ◀ 1/3 ▶ / "Начать чат" controls — **no photo**, so the gallery looks broken/unfinished.
- **Observed vs expected:** a text-only card vs a card with her photo (the gallery is the first
  impression and the conversion point — architecture.md §1).
- **Root cause:** `PERSONA.gallery_photo_ref` is seeded to `media/<slug>/gallery/card.jpg`, but that
  file was **never provisioned** — `media/<slug>/gallery/` does not exist. `_photo_file()` correctly
  returns `None` for a missing path and `_send_card` degrades to a text-only card. So the code
  behaves as designed; what is missing is **provisioning**: nothing ever produces the gallery photo.
  Note the pipeline now *does* generate a per-persona archive (F-011) — nothing wires it to the card.
- **Why tests didn't catch it (the gap):** F-001 tests assert both branches of `_send_card`
  (photo when the file exists, text-only when it does not) — the text-only path is *tested and
  passing*. **No requirement ever stated that a published persona MUST have a gallery photo**, and
  no test asserts the seeded `gallery_photo_ref` actually resolves to a file. A degrade path was
  silently treated as the normal path.
- **Resolution:** _pending_ — see F-001/F-013 requirement additions below.

---

## ISS-003 — Photo caption arrives in English for a Russian-speaking persona

- **Status:** [ ] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** Alina speaks Russian throughout, but the photo she sent carried the caption
  *"Just curled up on the couch with my favorite series, loving this cozy night."* — English.
- **Observed vs expected:** English caption vs a caption in **her** language (`PERSONA.language`),
  consistent with the rest of her voice.
- **Root cause:** `media_delivery.request_caption()` builds an English-only system/user prompt
  (*"You are {name}. Write ONE short, natural first-person caption…"*) and **never passes
  `persona.language`**, so the model answers in the prompt's language. The conversation path styles
  language correctly (F-002/F-003 persona prompt); the caption path is a separate, thinner prompt
  that was written without the language field.
- **Why tests didn't catch it (the gap):** F-012 caption tests use a **fake caption client** and only
  assert that *a* caption accompanies the photo — they never assert its language. **No requirement
  stated the caption must be in the persona's language**, so neither spec nor test covered it.
- **Resolution:** _pending_ — see F-012 requirement addition below.

---

## ISS-004 — Photo is delivered instantly — no human pacing, unlike text

- **Status:** [ ] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** The photo "приходит слишком быстро" — it lands immediately after the
  request, which reads as machine-fast and breaks the human-likeness illusion.
- **Observed vs expected:** instant photo vs a believable delay (a real person takes a moment to
  pick/take and send a photo), consistent with the F-003 pacing already applied to text.
- **Root cause:** the text path in `handlers/conversation.py` applies F-003 pacing
  (`pacing_delays` + per-chunk sleeps + typing indicator). The **photo path short-circuits before
  that**: it sends an `UPLOAD_PHOTO` chat action and then delivers immediately — **no delay at all**.
  F-003's human-likeness layer was specified for *text replies* and never extended to media sends.
- **Why tests didn't catch it (the gap):** F-003 pacing tests cover text chunking/delays; F-012
  delivery tests assert *speed* (NFR-012-01: "instant, no generation latency") — which is about
  **not generating on the hot path**, not about the *user-visible* send timing. The two requirements
  were never reconciled: "instant lookup" was silently implemented as "instant to the user".
- **Resolution:** _pending_ — see F-003/F-012 requirement additions below.

---

## ISS-005 — Keyword photo-intent detection misses natural phrasing

- **Status:** [ ] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** Photo intent must be detected properly by the LLM, not by keyword
  matching. Observed live: *"скинь свою фотку"* → photo (worked), but
  *"а может сфоткаешься сидя на диване?"* → **no photo**, she answered in text only.
- **Observed vs expected:** a natural request for a photo silently falls through to an ordinary text
  turn vs any phrasing that means "send me a photo" is recognized.
- **Root cause:** `looks_like_photo_request()` requires a **noun AND a verb** from two hardcoded
  lists. In the failing message the noun matched (`фотка` inside *сфоткаешься*) but no verb did
  (`может` ≠ `можно`, and *сфоткаешься* does not contain *сфоткай*), so intent evaluated to false.
  The whole approach is brittle: it cannot cover morphology, paraphrase, or implicit requests
  ("хочу тебя увидеть", "покажись").
- **Why tests didn't catch it (the gap):** the intent detector was added as **integration wiring
  without a requirement or a spec** (flagged at the time) — architecture.md §3.2 assigns
  *media-intent detection* to the Orchestrator as a **post-process step on the LLM turn**, but the
  implementation put a keyword pre-filter *before* the LLM instead. Its tests only encode the
  keyword behaviour they were written against, so they pass by construction.
- **Resolution:** _pending_ — new feature **F-020 (LLM media-intent detection)**, specced separately.

---

## ISS-006 — She invents a background for a photo she just sent — the sent photo is not in her context

- **Status:** [x] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** Alina sent a real photo (a dim bedroom: a bed, a monitor/TV screen, she is
  in a dark tee holding her head). Two messages later the user asked *"а что у тебя на фоне"* and she
  answered *"на фоне книжные полки, саксофон в углу и разбросанные листы акварели… и чашка кофе"* —
  **none of which is in the photo**. She invented a background out of her biography.
- **Observed vs expected:** she confabulates a scene that contradicts the image the user is looking
  at vs she describes **the photo she actually sent** (background, location, what she's doing, time
  of day) — a real girl remembers what she just showed you. This is the core believability illusion
  and the foundation of sexting continuity (§3.6, §4.2).
- **Root cause:** the metadata exists and is **stored but never consumed**. `MEDIA_ASSET.meta_json`
  carries `pose / background / location / activity / time_of_day` (F-008 FR-008-08, written by
  F-010's `SlotMeta`), and the architecture requires serving it back **three times** — §2
  (`POST /media/request` returns "the media … plus its metadata … for sexting continuity"), §4.2/
  §3.6 ("Returns the media **plus its metadata** … so the Orchestrator/LLM can **sext consistently**
  ('knows what she sent')") and §5.1. But `deliver_photo()` returned only the asset + caption, and
  `services/bot/orchestrator.py` contained **no reference to media at all** — the assembled context
  had persona/memory/relationship/life/biography blocks and no "what she sent" block. So on the next
  turn the LLM has zero evidence a photo ever existed and answers the question from her biography,
  which is exactly the material the prompt *does* carry. The architecture was implemented halfway:
  the write side (F-008/F-011/F-012 `MediaSend`) without the read side (F-002 context assembly).
- **Why tests didn't catch it (the gap):** `test_driven_development.md` §4b names this exact scenario
  under *cross-subsystem consistency* — "the LLM 'knows' what it sent (pose/background metadata) for
  sexting continuity" — but **no requirement ever encoded it**: F-012 stopped at "record the send"
  (FR-012-10) and F-002's context-assembly requirements (FR-002-03/04) list persona prompt, biography,
  facts, relationship and raw history, with **no media descriptors**. With no FR there was no TC, and
  the F-012 tests assert only that the send row is written — never that anything ever reads it back.
  A stored-and-never-read column looks identical to a working feature from the test suite's side.
- **Resolution:** new requirements + tests + code.
  - **F-012:** `FR-012-14` (delivery returns the delivered asset's slot metadata to the caller — the
    §2/§4.2 contract) and `FR-012-15` (a bounded, per-user, recency-ordered **recent-sends query**
    joining `MediaSend` → `MEDIA_ASSET.meta_json`, provenance fields excluded).
  - **F-002:** `FR-002-25` (the assembled context must include what she recently sent — background /
    location / activity / pose / time-of-day plus roughly when), `FR-002-26` (bounded + config-driven:
    max N sends within a recency window, single cheap query, no LLM call, no hot-path generation) and
    `NFR-002-13` (media self-consistency: she never contradicts the metadata of a photo she sent).
  - **architecture.md:** §3.2 step 3 and §4.2 now list recently-sent media descriptors as part of the
    assembled context, with the ISS-006 note that storing metadata without consuming it is the defect.
  - **Tests:** `TC-FR-012-14-01..03`, `TC-FR-012-15-01..03`, `TC-FR-002-25-01..04`, `TC-FR-002-26-01..03`,
    `TC-NFR-002-13-01..02` in the two mirror specs; runnable in `tests/test_iss_006_media_context.py`
    (all execute the real delivery/orchestrator/handler paths, per the ISS-004 lesson that
    source-text assertions prove nothing).
  - **Code:** `DeliveryResult.meta` + `recent_sends()` + `RecentSend` in
    `services/bot/domain/media_delivery.py`; `_recent_media_block()` fused into the single system
    message in `services/bot/orchestrator.py`.
- **Resolved:** 2026-07-23

---

## ISS-007 — A slow turn locks SQLite → the next message dies and the user gets total silence

- **Status:** [ ] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** The user asked "что ты сейчас делаешь и где находишься?", she answered,
  then he sent **"скинь фото"** — and **nothing came back at all**. Not a photo, not a deflection,
  not an error: silence.
- **Observed vs expected:** zero outbound messages vs *every* inbound message ends with something
  the user can see (the same invariant F-020's spec makes non-negotiable for media requests).
- **Root cause (two independent defects, both required to produce the silence):**
  1. **Write lock held across slow LLM calls.** After the reply is delivered the turn still runs
     `update_user_memory` (F-004 fact extraction) and `update_relationship` (F-005 reflection) —
     **two more LLM calls, ~20-30 s each** — inside the *same* request-scoped session. The previous
     turn measured **78 s** end-to-end. SQLite's `busy_timeout` is 30 s (`db.py`), so the next
     message's `INSERT INTO messages` waited, exceeded it, and raised
     `OperationalError: database is locked`. The orchestrator already commits before the *main*
     generation for exactly this reason — the post-turn work was never given the same treatment,
     and the code itself notes "production would move both to a background queue".
  2. **No safety net turns that exception into silence.** `DbSessionMiddleware` rolls back and
     **re-raises**; `on_text` has no `except`, and no aiogram error handler is registered. Any
     exception anywhere in a turn therefore produces **no user-visible message at all**.
- **Why tests didn't catch it (the gap):** the suite runs each test on its own in-memory SQLite with
  **no concurrency**, so a lock contention path simply cannot occur; and **no requirement ever stated
  that a turn must always answer** — the silence invariant existed only inside F-020's media tests,
  not as a global rule for `on_text`. A crash-equals-silence design looks identical to a working one
  until two messages overlap in production.
- **Resolution:** F-002 **FR-002-27** (no write transaction across an LLM call — both post-turn
  calls now commit first), **FR-002-28** (a dispatcher-level last-resort handler answers in
  character whatever the turn failed to answer; the turn also degrades on ANY model exception, not
  just `ChatRunnerUnavailable`), **FR-002-29** (post-turn failures swallowed), **NFR-002-14**
  (concurrency). Writing the concurrency test surfaced a **third** defect it then fixed: two
  overlapping messages both created the relationship row → `UNIQUE constraint failed` killed the
  turn; `relationship_store.get_or_create` now inserts inside a SAVEPOINT and re-reads the winner's
  row (a full rollback would have discarded the inbound message too).
  Tests: `tests/test_iss_007_lock_and_silence.py` (11), incl. a **file-backed SQLite concurrency
  test** — the in-memory fixture cannot reproduce lock contention, which is exactly why the suite
  never caught this.
- **Resolved:** 2026-07-23

