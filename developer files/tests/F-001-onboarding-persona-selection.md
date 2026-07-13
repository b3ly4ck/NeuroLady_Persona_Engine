# Tests for F-001 — Onboarding & Persona Selection ("Choose Lady")

- **Feature:** [F-001 — Onboarding & Persona Selection](../features/F-001-onboarding-persona-selection.md)
- **Approach:** Feature-granular coverage — **2-4 varied tests per requirement** (happy / negative /
  boundary / error / concurrency / localization / integration / e2e), plus one **manual real-device
  acceptance** test per user story. Target ~110-130 tests total (not thousands — F-001 is a finely
  scoped feature; see `test_driven_development.md` §1). Every test ID embeds the `FR-`/`NFR-`/`US-`
  id it is addressed to.

---

## Functional requirements

### FR-001-01 — `/start` from a new id creates a `USER` record exactly once

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-01-01 | unit | happy | New id creates a USER row | Given no user for tg-id X; When `/start`; Then one USER(telegram_id=X, locale, created_at) exists | planned |
| TC-FR-001-01-02 | unit | idempotency | `/start` twice creates one USER | Given a new id; When `/start` sent twice; Then exactly one USER row exists | planned |
| TC-FR-001-01-03 | integration | error | DB write failure is handled | Given the USER insert fails once; When `/start`; Then it retries and no crash, user still onboarded | planned |

### FR-001-02 — Welcome screen shows header, flirty copy, single "Start" button

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-02-01 | unit | happy | Welcome payload structure | Given `/start`; When welcome is built; Then it has the "NeuroLady AI" header, welcome copy, and exactly one "Start" inline button | planned |
| TC-FR-001-02-02 | component | boundary | Only one full-width Start button | Given the welcome screen; When rendered; Then there is a single full-width inline button, no extras | planned |
| TC-FR-001-02-03 | e2e | happy | Scripted `/start` returns welcome | Given an automated client; When it sends `/start`; Then it receives the welcome screen with a Start button | planned |

### FR-001-03 — Tapping "Start" opens the Choose Lady gallery (intro + first card)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-03-01 | unit | happy | Start → gallery intro + first card | Given welcome shown; When "Start" tapped; Then an intro message and the first persona card are produced | planned |
| TC-FR-001-03-02 | integration | happy | Persona Service queried for first active persona | Given active personas exist; When "Start" tapped; Then Persona Service returns the first card's data | planned |
| TC-FR-001-03-03 | e2e | happy | First card visible after Start | Given a client on welcome; When it taps Start; Then it sees the first persona card | planned |

### FR-001-04 — Each card shows photo, name, profession, age, first-person description

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-04-01 | unit | happy | All five card fields rendered | Given a persona; When its card renders; Then photo, name, profession, age, description are all present | planned |
| TC-FR-001-04-02 | unit | mapping | Card fields map to PERSONA columns | Given a PERSONA row; When the card is built; Then fields come from name/profession/age/card_description/gallery_photo_ref | planned |
| TC-FR-001-04-03 | integration | empty | Missing gallery photo handled | Given a persona with no gallery photo; When the card renders; Then a safe placeholder is used, no crash | planned |
| TC-FR-001-04-04 | e2e | happy | User sees full card content | Given a client in the gallery; When a card loads; Then all five fields are visible and readable | planned |

### FR-001-05 — One persona per view with `"index/total"` counter and ◀ / ▶

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-05-01 | unit | happy | View has one card + counter + arrows | Given the gallery; When rendered; Then one card, a "1/N" counter, and ◀/▶ controls are shown | planned |
| TC-FR-001-05-02 | integration | boundary | Counter total equals active count | Given N active personas; When gallery opens; Then the counter total reads N | planned |
| TC-FR-001-05-03 | e2e | happy | Only one card visible at a time | Given a client; When browsing; Then never more than one persona card per view | planned |

### FR-001-06 — ◀ / ▶ navigation is cyclic (wraps at both ends)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-06-01 | unit | boundary | ▶ from last wraps to first | Given card N/N; When ▶ tapped; Then card 1/N is shown | planned |
| TC-FR-001-06-02 | unit | boundary | ◀ from first wraps to last | Given card 1/N; When ◀ tapped; Then card N/N is shown | planned |
| TC-FR-001-06-03 | e2e | happy | Full loop both directions | Given a client; When it pages ▶ past the end and ◀ before the start; Then it wraps correctly both ways | planned |

### FR-001-07 — Gallery lists only `active` personas in a stable order

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-07-01 | unit | negative | Inactive personas excluded | Given a mix of active/inactive personas; When the gallery loads; Then only active ones appear | planned |
| TC-FR-001-07-02 | integration | state | Order stable across visits | Given the gallery; When opened twice; Then the persona order is identical | planned |
| TC-FR-001-07-03 | integration | state | Deactivation removes a persona | Given a persona set to inactive; When the gallery reloads; Then that persona is gone and the counter total drops by one | planned |

### FR-001-08 — Card copy in persona's language; personas match user locale

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-08-01 | integration | localization | RU user → RU personas + RU copy | Given a ru-locale user; When the gallery opens; Then Russian-speaking personas and Russian copy are shown | planned |
| TC-FR-001-08-02 | integration | localization | EN user → EN personas + EN copy | Given an en-locale user; When the gallery opens; Then English personas and English copy are shown | planned |
| TC-FR-001-08-03 | unit | boundary | Unknown locale → default | Given a user with an unsupported locale; When the gallery opens; Then a defined default (English) is used, no crash | planned |
| TC-FR-001-08-04 | unit | mapping | Copy language follows persona, not UI | Given an en-user viewing a card; When rendered; Then the card copy is in the persona's language field | planned |

### FR-001-09 — Each card carries a "Start Chat" button

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-09-01 | unit | happy | Card includes Start Chat | Given a card; When built; Then it has a "Start Chat" inline button | planned |
| TC-FR-001-09-02 | e2e | happy | Button present under shown card | Given a client browsing; When a card shows; Then "Start Chat" is tappable under it | planned |
| TC-FR-001-09-03 | unit | mapping | Button payload carries persona id | Given a card for persona P; When built; Then its "Start Chat" callback encodes P's id | planned |

### FR-001-10 — "Start Chat" creates or reuses a `SESSION(user, persona)`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-10-01 | unit | happy | Creates a started session | Given no session; When "Start Chat" on persona P; Then SESSION(user,P) is created in started state | planned |
| TC-FR-001-10-02 | unit | idempotency | Reuses an existing session | Given an existing session for (user,P); When "Start Chat" on P; Then the same session is reused, not duplicated | planned |
| TC-FR-001-10-03 | integration | persistence | Session persisted and retrievable | Given "Start Chat"; When the session is looked up; Then it is found with correct user/persona/state | planned |
| TC-FR-001-10-04 | integration | error | Session store failure handled | Given the session write fails; When "Start Chat"; Then it retries/recovers and does not crash | planned |

### FR-001-11 — Persona sends her intro as a video note from `intro_videonote_ref`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-11-01 | unit | happy | Sends video note from ref | Given persona P with intro_videonote_ref; When "Start Chat"; Then a Telegram video note is sent from that ref | planned |
| TC-FR-001-11-02 | integration | happy | Correct stored circle fetched | Given P's stored intro; When intro is delivered; Then the media resolved matches P's intro_videonote_ref path | planned |
| TC-FR-001-11-03 | e2e | happy | User receives a circle | Given a client; When it taps Start Chat; Then it receives a video note (circle) | planned |

### FR-001-12 — Reply keyboard with a single "💋 Choose Lady" button appears after intro (no menu)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-12-01 | unit | happy | Keyboard has exactly one button | Given intro sent; When the keyboard is built; Then it has exactly the "💋 Choose Lady" button and no menu/other button | planned |
| TC-FR-001-12-02 | e2e | happy | Keyboard visible after intro | Given a client just onboarded; When the intro arrives; Then the reply keyboard is shown | planned |
| TC-FR-001-12-03 | integration | state | Keyboard persists across the session | Given the reply keyboard shown; When the user sends further updates; Then the keyboard remains attached | planned |

### FR-001-13 — "💋 Choose Lady" reopens the gallery

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-13-01 | unit | happy | Choose Lady → gallery | Given a chat; When "💋 Choose Lady" tapped; Then the Choose Lady gallery is shown again | planned |
| TC-FR-001-13-02 | e2e | happy | Return to gallery from chat | Given a client in chat; When it taps "💋 Choose Lady"; Then it sees the gallery | planned |
| TC-FR-001-13-03 | integration | state | Gallery reopens at a defined position | Given a chat with persona P; When the gallery reopens; Then it starts at a defined card (first, or P's) consistently | planned |

### FR-001-14 — Selecting a different persona switches the active session

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-14-01 | unit | happy | Switch active session to Y | Given active session with X; When "Start Chat" on Y; Then the active session becomes (user,Y) | planned |
| TC-FR-001-14-02 | integration | state | Prior session closed/paused | Given switch X→Y; When completed; Then X's session is ended/paused and Y's is active | planned |
| TC-FR-001-14-03 | e2e | happy | Y's intro sent on switch | Given a client with X; When it picks Y; Then Y's video-note intro is delivered | planned |

### FR-001-15 — Existing user: no duplicate `USER`; resume-or-gallery

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-15-01 | unit | idempotency | No duplicate USER on repeat `/start` | Given an existing user; When `/start`; Then no new USER row is created | planned |
| TC-FR-001-15-02 | unit | state | Existing user with an active session → straight to gallery, session preserved | Given a user with a session for P; When `/start`; Then the Choose Lady gallery is shown (not a resume-into-chat), and the session for P remains active/untouched | planned |
| TC-FR-001-15-03 | unit | empty | No session → show gallery | Given a known user with no session; When `/start`; Then the Choose Lady gallery is shown | planned |

### FR-001-16 — `DEPRECATED`: main menu (≡) exposing Choose Lady + Resume chat

> Removed by explicit user request — there is no main menu, ever (architecture.md §1.3). IDs are
> immutable and never reused; these tests are retired, not deleted.

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-16-01 | unit | happy | Menu lists required actions | *(feature removed — no main menu screen exists)* | deprecated |
| TC-FR-001-16-02 | e2e | happy | Each action reachable in one tap | *(feature removed — no main menu screen exists)* | deprecated |
| TC-FR-001-16-03 | integration | happy | Resume chat returns to active persona | *(feature removed — resuming is now: pick the same persona again on Choose Lady, FR-001-10)* | deprecated |

### FR-001-17 — Repeated "Start" / "Start Chat" taps are idempotent

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-17-01 | integration | concurrency | Double-tap Start Chat → 1 session, 1 intro | Given a card; When "Start Chat" tapped twice fast; Then one session and one intro result | planned |
| TC-FR-001-17-02 | integration | concurrency | Double-tap Start → no dup welcome/state | Given welcome; When "Start" tapped twice fast; Then no duplicated state or double gallery | planned |
| TC-FR-001-17-03 | integration | idempotency | Idempotency key dedups replays | Given the same update delivered twice; When processed; Then the second is a no-op | planned |

### FR-001-18 — Persona without an intro note falls back gracefully

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-18-01 | unit | negative | Missing ref → fallback intro | Given persona with no intro_videonote_ref; When "Start Chat"; Then a text/photo fallback intro is sent | planned |
| TC-FR-001-18-02 | unit | error | Chat still opens on missing intro | Given the missing ref; When "Start Chat"; Then the session opens and the reply keyboard still shows | planned |
| TC-FR-001-18-03 | integration | error | Broken media ref handled | Given intro_videonote_ref points to a missing file; When intro is attempted; Then fallback fires, no crash | planned |
| TC-FR-001-18-04 | e2e | error | User still onboarded without circle | Given a client picking a persona with no circle; When Start Chat; Then it still ends ready-to-chat | planned |

### FR-001-19 — Whole flow completable with no command beyond `/start`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-19-01 | e2e | happy | Tap-only onboarding | Given a client; When it uses only taps after `/start`; Then it reaches a ready chat without typing a command | planned |
| TC-FR-001-19-02 | e2e | negative | No step demands a typed command | Given the flow; When walked end to end; Then no screen requires a slash-command to proceed | planned |
| TC-FR-001-19-03 | integration | happy | Every action has a button trigger | Given each onboarding action; When inspected; Then it is reachable via an inline/reply button, not text | planned |

### FR-001-20 — Delivered intro media belongs to the selected persona

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-20-01 | unit | happy | Media persona_id == selected | Given "Start Chat" on P; When media is delivered; Then its persona_id equals P | planned |
| TC-FR-001-20-02 | integration | negative | Switch sends new persona's media | Given switch X→Y; When Y's intro delivers; Then it is Y's media, never X's | planned |
| TC-FR-001-20-03 | integration | consistency | No cross-persona media mixup under load | Given many concurrent Start Chats; When intros deliver; Then each user gets their own selected persona's media | planned |

### FR-001-21 — Start Chat deletes both S2 messages, only after the S3 opener sends (send-before-delete)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-21-01 | unit | happy | Card deleted after Start Chat | Given "Start Chat"; When the opener sends successfully; Then the persona-card message is deleted | planned |
| TC-FR-001-21-02 | unit | happy | Tracked intro deleted after Start Chat | Given a tracked S2 intro message id; When "Start Chat" succeeds; Then that intro message is also deleted | planned |
| TC-FR-001-21-03 | integration | error | Failed opener send → nothing deleted | Given the opener send raises; When "Start Chat" is tapped; Then neither the card nor the intro is deleted (old screen stays, no blank chat) | planned |

### FR-001-22 — S2 card and S3 opener include the persona's photo when available

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-22-01 | unit | happy | Card sent as photo when a real file exists | Given a persona with a real gallery_photo_ref file; When the card renders; Then it is sent as a photo message with the card body as caption | planned |
| TC-FR-001-22-02 | unit | happy | Opener sent as photo when a real file exists | Given the same persona; When the S3 opener is sent; Then it is a photo message with the opener text as caption | planned |
| TC-FR-001-22-03 | unit | empty | No photo file → text-only fallback | Given no real photo file at the ref (or ref is None); When card/opener render; Then both degrade to text-only (FR-001-18) | planned |

### FR-001-23 — `/start` command deleted only after a successful response (send-before-delete)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-23-01 | unit | happy | `/start` deleted after the response is sent | Given `/start`; When the Welcome/gallery response sends successfully; Then the `/start` message is deleted | planned |
| TC-FR-001-23-02 | integration | error | Failed response → `/start` is NOT deleted | Given the response send raises; When `/start` is handled; Then the `/start` message is left in place | planned |

### FR-001-24 — The "💋 Choose Lady" reply-keyboard tap is deleted only after its response sends

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-001-24-01 | unit | happy | Tap deleted after the gallery is shown | Given a "💋 Choose Lady" tap; When the gallery card sends successfully; Then the tap message is deleted | planned |
| TC-FR-001-24-02 | integration | error | Failed response → tap is NOT deleted | Given the gallery send raises; When the tap is handled; Then the tap message is left in place | planned |

---

## Non-functional requirements

### NFR-001-01 — Welcome delivered under 3 seconds after `/start`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-01-01 | performance | happy | Welcome latency < 3s | Given a running bot; When `/start`; Then the welcome arrives in < 3s | planned |
| TC-NFR-001-01-02 | performance | boundary | p95 welcome latency < 3s | Given 1000 `/start` calls; When measured; Then p95 < 3s | planned |
| TC-NFR-001-01-03 | performance | error | Latency holds under load | Given heavy concurrent `/start`; When measured; Then welcome stays within the agreed degraded budget | planned |

### NFR-001-02 — Carousel navigation updates under 1 second

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-02-01 | performance | happy | ◀/▶ response < 1s | Given the gallery; When ◀/▶ tapped; Then the new card renders in < 1s | planned |
| TC-NFR-001-02-02 | performance | boundary | p95 nav latency < 1s | Given many nav taps; When measured; Then p95 < 1s | planned |
| TC-NFR-001-02-03 | performance | error | Nav stays snappy under load | Given many users paging concurrently; When measured; Then nav latency stays within budget | planned |

### NFR-001-03 — Intro video note begins sending within 3 seconds

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-03-01 | performance | happy | Intro send starts < 3s | Given "Start Chat"; When triggered; Then the intro begins sending in < 3s | planned |
| TC-NFR-001-03-02 | performance | boundary | p95 intro-start < 3s | Given many Start Chats; When measured; Then p95 intro-start < 3s | planned |
| TC-NFR-001-03-03 | performance | error | Slow media store still within budget | Given a slow object-storage read; When the intro is fetched; Then it still begins within the degraded budget | planned |

### NFR-001-04 — All copy correctly localized (natural RU / EN)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-04-01 | integration | localization | No placeholder/untranslated strings (RU) | Given a ru user; When screens render; Then no raw keys/English leak into RU copy | planned |
| TC-NFR-001-04-02 | integration | localization | No mixed-language strings | Given either locale; When screens render; Then each string is single-language | planned |

**Manual — TC-NFR-001-04-03 (manual-e2e)**
- Preconditions: bot deployed; a Russian-native reviewer with Telegram.
- Steps: 1) Open the bot with a Russian client. 2) Walk `/start` → gallery → Start Chat. 3) Read all copy.
- Expected: every string reads as natural, native Russian (not machine-translated or templated).
- Status: planned

### NFR-001-05 — Correct and within budget under concurrent load

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-05-01 | load | happy | Many concurrent new users onboard | Given K simultaneous `/start`; When processed; Then all onboard correctly, no errors | planned |
| TC-NFR-001-05-02 | load | boundary | p95 within degraded budget | Given heavy concurrency; When measured; Then p95 stays within the agreed degraded budget | planned |
| TC-NFR-001-05-03 | load | error | No partial onboarding under load | Given a spike of new users; When processed; Then each ends fully onboarded or cleanly retried — never half-created | planned |

### NFR-001-06 — Telegram send failures retried with backoff, no crash

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-06-01 | error | happy | Transient send failure retried | Given the send API fails once; When sending a screen; Then it retries with backoff and succeeds | planned |
| TC-NFR-001-06-02 | error | boundary | Persistent failure degrades gracefully | Given the send API keeps failing; When retries exhaust; Then the service logs and stays up, no crash | planned |
| TC-NFR-001-06-03 | error | idempotency | Retry doesn't double-send | Given a send that actually succeeded but reported failure; When retried; Then the user does not receive a duplicate message | planned |

### NFR-001-07 — Fully tap-driven with a one-tap back path on every screen

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-07-01 | usability | happy | Every screen has a back-to-gallery path | Given each onboarding screen; When inspected; Then a one-tap "💋 Choose Lady" route to the gallery exists (no menu) | planned |
| TC-NFR-001-07-02 | e2e | negative | No dead-ends | Given the flow; When walked; Then no screen traps the user with no forward/back control | planned |
| TC-NFR-001-07-03 | usability | boundary | Choose Lady reachable from every chat state | Given any active chat state; When the user wants to browse personas; Then "💋 Choose Lady" is reachable in one tap | planned |

### NFR-001-08 — `USER`/`SESSION` state survives a service restart

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-08-01 | integration | persistence | Returning user recognized after restart | Given an onboarded user; When the service restarts; Then `/start` recognizes them (no re-onboard) | planned |
| TC-NFR-001-08-02 | integration | persistence | Session restored after restart | Given an active session; When the service restarts; Then the session resumes with the same persona | planned |
| TC-NFR-001-08-03 | integration | error | In-flight onboarding survives restart | Given a user mid-onboarding; When the service restarts; Then they resume cleanly, not stuck in a broken half-state | planned |

### NFR-001-09 — Only the acting user's records affected; updates validated

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-09-01 | security | permissions | No cross-user session mutation | Given users A and B; When A acts; Then B's session/records are unchanged | planned |
| TC-NFR-001-09-02 | security | negative | Forged/invalid update rejected | Given an update failing webhook authenticity; When received; Then it is rejected, no state change | planned |
| TC-NFR-001-09-03 | security | boundary | Abuse/flood is rate-limited | Given a flood of updates from one id; When received; Then rate limiting kicks in without harming other users | planned |

### NFR-001-10 — Carousel navigation never desyncs card from counter

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-10-01 | concurrency | race | Rapid ◀/▶ keeps card == counter | Given rapid repeated nav taps; When processed; Then the shown card always matches its counter | planned |
| TC-NFR-001-10-02 | concurrency | race | Stale callback ignored | Given an out-of-order/stale nav callback; When it arrives; Then it is ignored, no desync | planned |
| TC-NFR-001-10-03 | concurrency | race | Start Chat during nav is consistent | Given a Start Chat tapped amid rapid nav; When processed; Then the persona started matches the card actually shown | planned |

### NFR-001-11 — Process self-heals from a Telegram connectivity failure at startup (never crash-exit)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-001-11-01 | integration | error | Retries after a network failure, then succeeds | Given `start_polling` raises `TelegramNetworkError` once; When retried; Then it retries with backoff and succeeds, no crash | passing |
| TC-NFR-001-11-02 | integration | error | Raw `OSError` (e.g. WinError 121) is retried too | Given `start_polling` raises a raw `OSError`; When retried; Then it is treated the same as a network error, not fatal | passing |
| TC-NFR-001-11-03 | integration | boundary | Backoff grows and is capped | Given repeated failures; When retried; Then delays are non-decreasing and stay within (0, 60] seconds | passing |

---

## User-story acceptance (manual real-device E2E)

One manual acceptance test per user story — judges the felt experience automation can't (does it
feel fast, warm, simple, believable, continuous).

**TC-US-001-01-01 (manual-e2e) — A1 Gen-Z: fast, shareable first contact**
- Preconditions: bot deployed; Telegram on your phone.
- Steps: 1) Open the bot, tap Start. 2) Swipe through a few girls. 3) Tap Start Chat on one.
- Expected: within seconds you get a video circle that looks real; the whole thing feels fast and
  worth screenshotting. Status: planned

**TC-US-001-02-01 (manual-e2e) — A2 lonely: warm, personal first contact**
- Preconditions: bot deployed.
- Steps: 1) `/start`. 2) Read the welcome. 3) Pick a girl and watch her intro.
- Expected: the greeting and intro feel warm and personal, like meeting someone — not launching an
  app. Status: planned

**TC-US-001-03-01 (manual-e2e) — A7 older / low tech: dead-simple, no commands**
- Preconditions: bot deployed; a low-tech-comfort tester.
- Steps: 1) Open the bot. 2) Complete onboarding using only buttons.
- Expected: the tester reaches a ready chat without confusion and without typing any command beyond
  opening the bot. Status: planned

**TC-US-001-04-01 (manual-e2e) — A8 skeptic: distinct personas, scrutinized circle**
- Preconditions: bot deployed.
- Steps: 1) Browse the whole carousel. 2) Compare personas. 3) Pick one and scrutinize the circle.
- Expected: personas read as genuinely different people; the video-note intro survives a skeptic's
  first look. Status: planned

**TC-US-001-05-01 (manual-e2e) — Returning user continues with the same girl**
- Preconditions: an already-onboarded account with an active chat with persona P.
- Steps: 1) Close the bot. 2) Reopen the next day and send `/start`. 3) On the Choose Lady screen,
  pick P again and tap "Start Chat".
- Expected: `/start` takes you to Choose Lady (not straight back into the old chat); picking P again
  continues that same relationship/session, not a fresh onboarding — no separate "Resume" menu step
  is needed (there is no main menu). Status: planned

**TC-US-001-06-01 (manual-e2e) — Switch persona mid-chat**
- Preconditions: onboarded, in a chat with persona X.
- Steps: 1) Tap "💋 Choose Lady". 2) Pick persona Y. 3) Tap Start Chat.
- Expected: the chat switches to Y and Y sends her own intro; it feels seamless. Status: planned

---

## Coverage summary

- **Functional:** FR-001-01..24 — **74 automated tests** across unit / integration / component /
  e2e, spanning happy / negative / boundary / error / concurrency / localization / persistence /
  consistency / idempotency cases. **FR-001-16 is `DEPRECATED`** (main menu removed by explicit user
  request — architecture.md §1.3); its 3 tests are retained with `Status: deprecated` per the TDD
  guide (ids immutable, never reused, never deleted). FR-001-21..24 (send-before-delete cleanup,
  photo wiring) were added after the original spec and are now covered (9 tests). 24/24 FR ids
  present. ✓
- **Non-functional:** NFR-001-01..11 — **33 tests** (performance / load / error / usability /
  persistence / security / concurrency), including 1 manual localization check and **NFR-001-11**
  (process self-heals from a Telegram connectivity failure — 3 tests, implemented and passing in
  `tests/test_f001_reconnect.py`). 11/11 NFR ids present. ✓
- **User stories:** US-001-01..06 — **6 manual real-device acceptance tests**, updated to reflect
  `/start` always landing on Choose Lady (no auto-resume-into-chat) and the no-menu UI. ✓
- **Total: 113 enumerated tests** (110 active + 3 deprecated) — within the 100-150 target band.
- Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies, matching the feature file's IDs.
