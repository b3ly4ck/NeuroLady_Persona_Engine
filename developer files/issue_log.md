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
| ISS-008 | Photo metadata describes the generation REQUEST, not the rendered image | [x] | 2026-07-23 | 2026-07-23 |
| ISS-007 | A slow turn locks SQLite → the next message dies and the user gets total silence | [x] | 2026-07-23 | 2026-07-23 |
| ISS-006 | She invents a background for a photo she just sent — the sent photo is not in her context | [x] | 2026-07-23 | 2026-07-23 |
| ISS-009 | The intimate-request keyword classifier is English-only — a Russian intimate ask reads as SFW | [x] | 2026-07-23 | 2026-07-23 |
| ISS-010 | A send is recorded for a photo that was never delivered (missing file) — the frame is burned forever | [x] | 2026-07-23 | 2026-07-23 |
| ISS-011 | Two concurrent turns can send the same photo twice — no-repeat was a read-then-write check | [x] | 2026-07-23 | 2026-07-23 |
| ISS-012 | Greeting / resume opener is a hardcoded template, not LLM-composed — reads as canned | [x] | 2026-07-24 | 2026-07-24 |

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

---

## ISS-008 — Photo metadata describes the generation REQUEST, not the rendered image

- **Status:** [x] fixed
- **Reported:** 2026-07-23
- **Report (as stated):** Follow-up to ISS-006. She no longer invents a scene from her biography,
  but she still cannot answer *"а что у тебя на фоне?"* — because what reaches her context is
  `на фоне: home; поза: high-angle selfie`, i.e. the generation request, not a description of the
  photo. The frame actually showed a dim bedroom with a bed, a lit TV and a lamp; none of that is
  recorded anywhere.
- **Observed vs expected:** request-shaped tokens (`home`, `high-angle selfie`, `evening`, half of
  them English under a Russian persona) vs a short human description of **what is visible** in the
  frame, in her language, that she can speak from naturally.
- **Root cause:** `SlotMeta` carries only planner fields — `pose / background / location /
  activity / time_of_day` — and `background` is populated from the *location phrase*
  (`batch_planner`: `background = _location_phrase(...) or slot.activity`), so it duplicates
  `location` rather than describing a background. `pose` holds framing jargon ("high-angle selfie").
  The rich scene text does exist inside `meta_json["prompt"]`, but it is the English technical
  generation prompt (with "Camera signature: shot on an iPhone…") and is deliberately stripped at
  the delivery boundary — leaking it into her voice would be worse than saying nothing.
- **Why tests didn't catch it (the gap):** F-008 FR-008-08 requires the five slot fields to be
  stored, and they are — the tests assert *presence*, never *usefulness*. **No requirement ever
  said the metadata must describe the rendered image** or be readable in the persona's language, so
  a field that merely echoes another field satisfies every existing assertion.
- **Second consequence (blocks F-021):** archive reuse and specific-request matching
  (F-021 FR-021-11, US-021-05 "покажи, где ты гуляла") can only be as good as this metadata — with
  `background: home` there is nothing to match on. One fix pays for both features.
- **Resolution (2026-07-23):** a new `SlotMeta.scene_description` — one plain sentence, authored
  from the same slot as the prompt, in `PERSONA.language`, containing no framing/technical
  vocabulary and never her appearance (FR-010-19/20/21). Stored in `meta_json` by F-008
  (FR-008-19), served by F-012 (`SCENE_FIELDS`, `recent_sends`, delivery meta — FR-012-16), and
  rendered by F-002's context block as the line itself, with the labelled request-fields kept only
  as the fallback for pre-fix assets.

  **The non-obvious half of the fix:** authoring a description that names a sofa and a blanket while
  the prompt's `Scene:` section said only *"at home"* would have moved the confabulation out of her
  mouth and into our code — the objects would still not be in the frame. So `scene_objects()` is now
  the single source read by BOTH: the prompt requests the objects (`…with the sofa, a floor lamp,
  the TV on and a blanket visible around her`) and the description names the same ones in her
  language. `TC-FR-010-19-05` pins that agreement.

  Two defects were caught by the new tests rather than in production:
  - the F-011 wiring adapter never passed `PERSONA.language`, so production would have authored
    English descriptions for a Russian persona (`TC-FR-010-20-04` now executes the adapter);
  - adding `language` as a positional parameter of `author_jobs()` silently shifted `style` — two
    existing F-010 tests went red because the persona's palette and outfit stopped being applied.
    `language` is keyword-only for that reason.

  `SCENE_OBJECTS` covers the full canonical location vocabulary emitted by
  `batch_planner._guess_location` (`home / cafe / office / restaurant / gym / outdoors`) plus a
  safe default, so an unmapped location degrades instead of producing an empty scene.

  Tests: `tests/test_iss_008_scene_description.py` (22, all executing the real path —
  `author_jobs` → `store_asset` → `deliver_photo` → `recent_sends` → `handle_turn`).



---

## ISS-009 — The intimate-request keyword classifier is English-only

- **Status:** [x] fixed
- **Reported:** 2026-07-23 (found while writing the F-021 suite, not by a user)
- **Report (as stated):** `classify_photo_request("скинь голое фото")` returns `sfw`. Every term in
  `_INTIMATE_TERMS` and `_AMBIGUOUS_TERMS` is English (`nude`, `naked`, `topless`, `lingerie`,
  `sexy`…), while the deployed persona and every live test message are **Russian**. The safety
  classifier that F-012 NFR-012-08 relies on is therefore blind in the language the bot actually
  speaks.
- **Observed vs expected:** a Russian intimate ask takes the SFW archive path (it gets deflected
  only because no matching asset exists) vs being routed to the F-014 gate like its English
  equivalent.
- **Severity note:** in production the F-020 LLM intent signal usually catches these first and sets
  `force_gate`, so this is a **defence-in-depth** failure rather than an open leak — but the keyword
  classifier exists precisely as the fallback for when the model's signal is absent or malformed,
  and a fallback that only works in English is not a fallback for this deployment.
- **Why tests didn't catch it (the gap):** every F-012 classification test asserts on English
  fixtures (`"send me a nude"`, `"show me something spicier"`). No requirement said the classifier
  must cover the **persona's language**, so an English-only list satisfies the whole suite. Same
  root shape as ISS-003 (English caption for a Russian persona): localization was specified for what
  she *says* and never for what she *understands*.
- **Resolution (2026-07-23):** **F-012 FR-012-17** now requires the fallback classifier to cover
  every language a deployed persona speaks, including that language's inflected forms.
  `_INTIMATE_TERMS` / `_AMBIGUOUS_TERMS` gained Russian entries stored as **stems** matched as
  substrings, so голое / голую / голой / голышом all hit one entry.

  **Stem choice is the delicate part** and is pinned by tests in both directions: `"соск"` would
  have matched *соскучился* and `"попу"` would have matched *попугай* — an innocent "я соскучился,
  скинь фотку" routed to the intimacy gate is its own defect — so those are spelled out
  (`"соски"`, `"попка"`) instead. Likewise `"поинтересне"` was dropped from the ambiguous list.

  Tests: `tests/test_iss_009_ru_intimate_classifier.py` (21) — RU intimate, RU ambiguous, RU
  ordinary photo talk (the false-positive guards), unchanged English behaviour, and an end-to-end
  `deliver_photo` regression proving the ask reaches the gate rather than the SFW archive.

---

## ISS-010 — A send is recorded for a photo that was never delivered

- **Status:** [x] fixed
- **Reported:** 2026-07-23 (found by TC-NFR-021-01-03, which was written to look for exactly this)
- **Report (as stated):** `deliver_photo` selected an asset, captioned it and wrote the `MediaSend`
  row; the handler then discovered the file was missing and sent a text line instead. The user
  received no photo, yet per-user no-repeat now excludes that asset **forever** — a paid-for frame
  destroyed without ever being seen.
- **Observed vs expected:** `answer_photo` not called + a `MediaSend` row present, vs either a
  delivered photo or no send record at all.
- **Root cause:** the two halves of "send" lived in different layers. The domain
  (`media_delivery.deliver_photo`) committed the send; the handler
  (`handlers/media.serve_photo_request`) resolved the path and discovered the file. Nothing verified
  the file **before** the commitment. Latent until now (F-008 writes the file before the row, so a
  row without a file was unreachable) — **F-021 eviction makes it reachable**: a frame can be
  selected and evicted before the send completes.
- **Why tests didn't catch it (the gap):** every delivery test planted rows **without files** and
  asserted on the returned `DeliveryResult`, so "the file exists" was never part of any assertion —
  the whole suite was blind to the distinction. The handler's own `os.path.exists` fallback made the
  behaviour look handled while silently burning the asset.
- **Resolution (2026-07-23):** path resolution moved into the domain (`asset_abspath` /
  `asset_file_exists` in `media_delivery.py`, re-exported by the handler so there is exactly one
  resolution), and `deliver_photo` now selects through `select_deliverable_asset()`: it verifies the
  winner's file, skips a frame whose file is gone, and tries the next-best (bounded) before
  degrading in voice. A `MediaSend` row is written only for a photo that can actually be sent
  (F-021 NFR-021-01). The F-012 and ISS-008 fixtures now write real PNGs, so "a row implies a file"
  is asserted by the suite rather than assumed.
  Tests: `TC-NFR-021-01-03` in `tests/test_f021_retention_and_reuse.py` (executes the real
  `on_text` with the files deleted under it and asserts the turn is not silent **and** no
  `MediaSend` row was written).


---

## ISS-011 — Two concurrent turns can deliver the same photo twice

- **Status:** [x] fixed
- **Reported:** 2026-07-23 (found while writing TC-NFR-020-05-04)
- **Report (as stated):** F-012's "no asset is ever resent to the same user" (NFR-012-02) was
  implemented as *read the send history, then write a new row*. Two turns in flight both read
  "unsent" before either wrote, both recorded a send, and the user received the same photo twice.
- **Observed vs expected:** two `media_sends` rows for one `(user, asset)` pair vs exactly one, ever.
- **Root cause:** the invariant was expressed in application code at a point where it cannot hold.
  Between the read and the write there is a window — widened by the caption LLM call sitting exactly
  in the middle of it — and nothing in the schema forbade the duplicate.
- **Why tests didn't catch it (the gap):** every no-repeat test was **sequential**. The in-memory
  `StaticPool` fixture also hands every session the *same* connection, so "two sessions" in a test
  were never actually concurrent — the suite had no way to express the failure at all.
- **Honest scope note (important):** on **SQLite this race is not reachable through the handler**,
  because a turn holds a write transaction from the moment it persists the inbound message until it
  commits, so the second turn simply waits. It **is** reachable on the Postgres production target
  (architecture.md §6.2). This was verified rather than assumed: with the constraint removed, the
  handler-level concurrency test stayed **green**, while a direct double `record_send` produced two
  rows. A test that cannot fail is not evidence, so the invariant is pinned by
  `TC-NFR-020-05-04b` (direct, fails without the fix) and the handler-level test documents in its
  own docstring what it does *not* prove.
- **Resolution (2026-07-23):** F-012 **FR-012-19** — uniqueness moved into the schema
  (`uq_media_send_user_asset` on `MEDIA_SEND (user_id, asset_id)`). `record_send()` inserts inside a
  SAVEPOINT and returns `None` on conflict, so the losing side is refused without poisoning the
  turn's transaction (which still holds the inbound message — the ISS-007 lesson). A **requested**
  photo then degrades in voice; an **unprompted** share simply does not happen. `init_models` also
  creates the index idempotently, because `create_all` never adds a constraint to an already-created
  table and this one carries a correctness invariant.
  The constraint immediately caught an impossible state baked into an existing fixture: a test that
  filled the pacing window with four sends *of the same asset* to the same user.


---

## ISS-012 — Greeting / resume opener is hardcoded, not generated

- **Status:** [x] fixed
- **Reported:** 2026-07-24 (live Telegram test)
- **Report (as stated):** Re-entering an active chat greets with the **same fixed line every time** —
  "Снова ты 😏 А я скучала… на чём мы остановились?". The user: *"это сообщение типа я скучала …
  должно генерироваться и каждый раз быть новым, а не просто захардкожено"*. It must be LLM-composed
  and fresh, not a constant.
- **Observed vs expected:** a constant string from `i18n.resume_opener` (and, for the selection
  moment, a random pick from fixed template lists in `presentation.compose_greeting`) vs a greeting
  the model writes in her voice each time, aware of the moment and of where the conversation left off.
- **Root cause:** two separate static sources. **(a)** The **resume opener** (re-entering an active
  session) is a single hardcoded catalog entry `resume_opener` in `services/bot/i18n.py`, sent
  verbatim by the onboarding handler. **(b)** The **selection greeting** (`compose_greeting`) is
  *template* variety — `random.choice` over fixed `_OPENERS`/`_QUESTIONS` lists — which varies
  wording but is not generated and cannot reference the actual conversation. Neither path ever calls
  the chat model, even though F-013's own docstring calls the greeting "in her voice".
- **Why tests didn't catch it (the gap):** F-013 FR-013-01/09 only require a greeting "in her voice"
  honoring tone; NFR-013-02 requires *variety*, which template `random.choice` technically satisfies.
  **No requirement said the opener must be LLM-composed** or context-aware of the last exchange, so a
  canned line passes every assertion. Same shape as the recurring gap: presence/variety was
  specified, *authorship by the model* was not.
- **Resolution (2026-07-24):** F-013 FR-013-13/14/15 + `presentation.compose_opener()` — an async
  composer that builds a compact in-voice instruction (time-of-day, her current F-006 activity, bond
  stage; on the **resume** path the session's last messages are prepended so "на чём остановились?"
  is grounded in the real thread), calls the chat model, strips any stray F-020 signal, and returns
  the fresh text. **Any** failure — model down/not-ready/exception/empty — returns the fallback (the
  F-013 template for selection, the static `resume_opener` for resume), so the entry moment is never
  silent and never leaks the sentinel. Wired into `compose_presentation(chat_client=...)` (selection)
  and the `on_start_chat` resume branch via `_resume_opener()`. Live-verified: three consecutive
  resume opens produced three distinct greetings, each referencing the actual last exchange.
  Tests: `tests/test_iss_012_generated_opener.py` (12, executing `compose_opener` and the real
  `on_start_chat` handler).
