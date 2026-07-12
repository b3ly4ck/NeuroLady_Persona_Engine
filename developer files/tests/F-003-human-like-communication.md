# Tests for F-003 — Human-Likeness of Communication ("she texts like a real person")

- **Feature:** [F-003 — Human-Likeness of Communication](../features/F-003-human-like-communication.md)
- **Approach:** Feature-granular coverage — **2-3 varied tests per requirement** across all 38 FR and
  17 NFR, plus one **manual real-device acceptance** test per user story (US-003-01..09). Cases vary
  across unit / integration / component / e2e / performance / load / statistical / consistency, and
  happy / negative / boundary / empty / error / concurrency / idempotency / localization / persistence.
  Because F-003 shapes *delivery/style* (not reply content), many tests assert on **timing, ordering,
  form, and style** rather than answer correctness (that is owned by F-002). Target band 100-150; see
  `test_driven_development.md` §1. Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies.

---

## Functional requirements

### FR-003-01 — Deliver replies with a deliberate, variable pre-send delay (not instant)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-01-01 | unit | happy | A computed reply is scheduled with a delay > 0 | Given a reply from F-002; When it is queued for send; Then a deliberate pre-send delay > 0 is applied | planned |
| TC-FR-003-01-02 | integration | happy | Reply not emitted until the delay elapses | Given a paced reply; When the delay is pending; Then the message is withheld until the delay completes | planned |
| TC-FR-003-01-03 | e2e | happy | User perceives a non-instant reply | Given a scripted client; When it sends a message; Then the reply arrives after a perceptible pause, not with robotic immediacy | planned |

### FR-003-02 — Delay roughly proportional to reply length/complexity

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-02-01 | unit | happy | Longer reply → longer delay | Given two replies, one longer; When paced; Then the longer reply gets a longer delay | planned |
| TC-FR-003-02-02 | unit | boundary | One-word quip → minimal delay | Given a one-word reply; When paced; Then the delay is at the low end of the band | planned |
| TC-FR-003-02-03 | integration | happy | Delay grows monotonically with length within band | Given replies of increasing length; When paced; Then delay increases (within the band) | planned |

### FR-003-03 — Show the "typing…" chat action during the delay

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-03-01 | unit | happy | Typing action sent when delay starts | Given a paced reply; When the delay begins; Then a Telegram "typing…" chat action is emitted | planned |
| TC-FR-003-03-02 | e2e | happy | User sees "typing…" during the wait | Given a client; When awaiting a reply; Then the "typing…" indicator is visible for the pause | planned |

### FR-003-04 — Pacing varies with the persona's activity / time of day

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-04-01 | unit | happy | "Busy"/night slot skews delay longer | Given the day plan marks her busy/late; When paced; Then the delay skews longer (within cap) | planned |
| TC-FR-003-04-02 | unit | happy | Free/day slot → snappier | Given a free daytime slot; When paced; Then the delay is shorter | planned |
| TC-FR-003-04-03 | integration | mapping | Pacing reads DAILY_PLAN + timezone | Given plan text + PERSONA.timezone; When pacing is computed; Then current-activity/time is derived from them | planned |

### FR-003-05 — Pacing default driven by `comm_settings_json`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-05-01 | unit | happy | pacing_style knob changes default tempo | Given a persona with a fast pacing_style; When paced; Then her default delay is shorter than a slow-styled persona's | planned |
| TC-FR-003-05-02 | integration | consistency | Two personas differ by pacing config | Given two personas with different pacing_style; When both reply; Then their tempos differ accordingly | planned |

### FR-003-06 — Enforce a defined upper bound on total deliberate delay

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-06-01 | unit | boundary | Delay never exceeds the cap | Given any reply; When paced; Then the total delay ≤ the configured upper bound | planned |
| TC-FR-003-06-02 | unit | boundary | Very long reply is capped | Given a very long reply that would pace long; When paced; Then the delay is clamped to the cap | planned |
| TC-FR-003-06-03 | e2e | boundary | Worst case still arrives within cap | Given the longest reply; When delivered; Then it arrives no later than the cap allows | planned |

### FR-003-07 — Pacing is additive on top of fast compute, never slows the model

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-07-01 | unit | happy | Delay applied after compute completes | Given the model has produced the reply; When pacing runs; Then the delay starts only after compute finished | planned |
| TC-FR-003-07-02 | integration | consistency | Compute time unchanged by pacing | Given pacing enabled vs disabled; When measured; Then model compute time is identical (pacing is post-compute) | planned |
| TC-FR-003-07-03 | integration | negative | Pacing never blocks/extends the LLM call | Given a turn; When paced; Then the LLM call is not delayed or held by the pacing layer | planned |

### FR-003-08 — Delay randomized within a natural band (not a fixed constant)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-08-01 | unit | happy | Similar-length replies get different delays | Given two similar-length replies; When paced; Then their delays differ (not identical) | planned |
| TC-FR-003-08-02 | statistical | boundary | Delays distributed within the band | Given many paced replies; When delays are sampled; Then they spread across the band, none outside it | planned |

### FR-003-09 — Split a long reply into several shorter consecutive messages

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-09-01 | unit | happy | Long reply → multiple messages | Given a reply long enough to read as a wall of text; When delivered; Then it is split into several messages | planned |
| TC-FR-003-09-02 | unit | boundary | Just-over-threshold splits, just-under doesn't | Given replies just over/under the wall-of-text threshold; When delivered; Then only the over one is split | planned |
| TC-FR-003-09-03 | e2e | happy | User receives several messages | Given a client; When it asks for a long answer; Then it receives several short consecutive messages | planned |

### FR-003-10 — Small pause + re-show "typing…" between chunks

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-10-01 | unit | happy | Inter-chunk pause + typing inserted | Given a chunked reply; When sent; Then a small pause and a fresh "typing…" precede each subsequent chunk | planned |
| TC-FR-003-10-02 | e2e | happy | Typing flicker between chunks | Given a client receiving a chunked reply; When observed; Then a "typing…" appears between chunks | planned |

### FR-003-11 — Chunk boundaries at natural sentence/thought breaks, never mid-word

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-11-01 | unit | happy | Splits at sentence/thought boundaries | Given a long reply; When chunked; Then each split falls at a sentence/thought boundary | planned |
| TC-FR-003-11-02 | unit | negative | Never split mid-word or mid-clause | Given any chunking; When applied; Then no chunk boundary lands mid-word/mid-clause | planned |
| TC-FR-003-11-03 | unit | happy | Each chunk individually readable | Given the chunks; When read alone; Then each is a coherent, readable fragment | planned |

### FR-003-12 — Reply length adapts to context (banter short, storytelling longer)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-12-01 | unit | happy | Banter stays short, story runs longer | Given a banter turn vs a storytelling turn; When styled; Then the banter reply is short and the story longer | planned |
| TC-FR-003-12-02 | integration | negative | Not uniformly terse or verbose | Given a mix of turns; When measured; Then reply length varies with context, not a constant | planned |

### FR-003-13 — Avoid assistant-style formatting (no bullets/lists/headings/essay)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-13-01 | unit | negative | No bullet/numbered lists in output | Given a reply; When styled; Then it contains no bullet or numbered list markup | planned |
| TC-FR-003-13-02 | unit | negative | List-shaped content rendered as prose | Given content an assistant would list; When styled; Then it is delivered as natural texting prose | planned |
| TC-FR-003-13-03 | e2e | negative | No headings/essay structure | Given a client; When it asks a "how-to"; Then the reply has no headings or essay structure | planned |

### FR-003-14 — Chunk count scales with length up to a capped maximum

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-14-01 | unit | boundary | Chunk count ≤ max cap | Given any reply; When chunked; Then the number of chunks ≤ the configured cap | planned |
| TC-FR-003-14-02 | unit | boundary | Very long reply → capped, no flood | Given an extremely long reply; When chunked; Then chunks are capped and the user is not flooded | planned |

### FR-003-15 — Chunking/verbosity driven by `comm_settings_json`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-15-01 | unit | happy | Verbosity knob changes chunkiness | Given a chatty vs terse verbosity setting; When styled; Then chattier persona produces longer/more-chunked replies | planned |
| TC-FR-003-15-02 | integration | consistency | Terse vs chatty personas differ | Given two personas with different verbosity; When both reply; Then their lengths/chunking differ per config | planned |

### FR-003-16 — Emojis used sparingly and naturally

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-16-01 | unit | boundary | Emoji density below one-per-sentence | Given a multi-sentence reply; When styled; Then emoji count is well below one per sentence | planned |
| TC-FR-003-16-02 | unit | negative | No emoji on every line | Given a multi-line reply; When styled; Then not every line carries an emoji | planned |
| TC-FR-003-16-03 | e2e | happy | Emoji feel natural over turns | Given several turns; When observed; Then emoji appear sparingly and only where natural | planned |

### FR-003-17 — Emoji frequency comes from `comm_settings_json`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-17-01 | unit | happy | High-emoji vs near-none personas differ | Given two personas with different emoji_frequency; When they reply; Then their emoji usage differs accordingly | planned |
| TC-FR-003-17-02 | unit | boundary | emoji_frequency=0 → (almost) no emoji | Given emoji_frequency=0; When styled; Then the reply carries essentially no emoji | planned |
| TC-FR-003-17-03 | integration | consistency | Frequency honored across turns | Given a set frequency; When many turns run; Then the observed rate matches the configured level | planned |

### FR-003-18 — No mechanical repetition of the same emoji

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-18-01 | unit | negative | Same emoji not repeated within a message | Given a reply; When styled; Then it does not repeat one emoji mechanically | planned |
| TC-FR-003-18-02 | statistical | negative | No emoji tic across a short run of turns | Given several consecutive turns; When observed; Then no single emoji recurs as a tic | planned |

### FR-003-19 — Emoji choice matches persona character and age

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-19-01 | unit | happy | Playful-young vs reserved-older differ | Given a playful young and a reserved older persona; When styled; Then their emoji sets differ appropriately | planned |
| TC-FR-003-19-02 | integration | consistency | Emoji choice consistent with persona | Given a persona; When many turns run; Then emoji stay within her character-appropriate set | planned |

### FR-003-20 — Never emit emoji spam

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-20-01 | unit | negative | No long emoji strings / emoji-only filler | Given a reply; When styled; Then it contains no long emoji runs or emoji-only messages | planned |
| TC-FR-003-20-02 | unit | boundary | Decorative emoji rows blocked | Given a tendency to append emoji rows; When styled; Then such rows are suppressed | planned |

### FR-003-21 — Informal texting register (casual lowercase, relaxed punctuation, contractions)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-21-01 | unit | happy | Output is casual lowercase with contractions | Given a reply; When styled; Then it favors casual lowercase, relaxed punctuation, and contractions | planned |
| TC-FR-003-21-02 | unit | negative | Not fully-punctuated formal prose | Given a reply; When styled; Then it is not rigid, fully-punctuated formal prose | planned |
| TC-FR-003-21-03 | e2e | happy | Reads as texting | Given a client; When it reads a reply; Then it reads like a text message, not a document | planned |

### FR-003-22 — Occasional slang / abbreviations consistent with persona

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-22-01 | unit | happy | Slang present but persona-consistent | Given a persona; When styled; Then slang/abbreviations appear and fit her character | planned |
| TC-FR-003-22-02 | integration | localization | Slang localized to language | Given RU vs EN personas; When styled; Then slang matches each language's norms | planned |

### FR-003-23 — Rare, natural human typo, bounded

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-23-01 | unit | boundary | Typo rate bounded (occasional) | Given many replies; When measured; Then typos occur occasionally, not in every message | planned |
| TC-FR-003-23-02 | unit | boundary | typo_rate=0 → no typos | Given typo_rate=0; When styled; Then no typos are introduced | planned |
| TC-FR-003-23-03 | unit | negative | Typos never harm readability | Given a reply with a typo; When read; Then it remains clearly understandable | planned |

### FR-003-24 — Not corporate / formal-grammar / assistant tone

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-24-01 | unit | negative | No formal/help-desk tone | Given a reply; When styled; Then it does not read as corporate or help-desk prose | planned |
| TC-FR-003-24-02 | e2e | happy | Register is a girl texting | Given a client; When it reads replies; Then the voice is a real girl texting, not an assistant | planned |

### FR-003-25 — Informal register localized to the persona's language

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-25-01 | integration | localization | RU persona uses RU texting norms | Given a RU persona; When styled; Then register/slang follow natural Russian texting norms | planned |
| TC-FR-003-25-02 | integration | localization | EN persona uses EN norms | Given an EN persona; When styled; Then register/slang follow natural English norms | planned |
| TC-FR-003-25-03 | unit | negative | No literal cross-language transplant | Given a RU persona; When styled; Then English texting habits are not literally transplanted | planned |

### FR-003-26 — Vary greetings and message openings across turns

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-26-01 | unit | happy | Greetings vary across turns | Given multiple turns; When she opens replies; Then greetings/openings vary | planned |
| TC-FR-003-26-02 | statistical | negative | No fixed templated greeting | Given many turns; When openings are sampled; Then no single greeting dominates | planned |

### FR-003-27 — Avoid reusing phrasings / catchphrases turn after turn

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-27-01 | unit | negative | No catchphrase loop across turns | Given consecutive replies; When compared; Then no catchphrase repeats mechanically | planned |
| TC-FR-003-27-02 | statistical | boundary | Phrasing repetition below threshold | Given a long chat; When phrasing repetition is measured; Then it stays below the threshold | planned |
| TC-FR-003-27-03 | e2e | happy | Long chat shows varied phrasing | Given a client in a long chat; When observed; Then phrasing feels varied, not copy-pasted | planned |

### FR-003-28 — Vary sentence structure and length across replies

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-28-01 | unit | happy | Sentence structure varies | Given several replies; When analyzed; Then sentence structures differ | planned |
| TC-FR-003-28-02 | statistical | negative | Rhythm not mechanically uniform | Given many replies; When measured; Then sentence-length distribution is non-uniform | planned |

### FR-003-29 — No assistant-style closers appended

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-29-01 | unit | negative | No "how can I help you?" appended | Given a reply; When styled; Then it does not end with an assistant help-closer | planned |
| TC-FR-003-29-02 | unit | negative | No "let me know if you need anything" | Given a reply; When styled; Then no such assistant closer is present | planned |
| TC-FR-003-29-03 | e2e | negative | Replies never end with assistant closer | Given a client over many turns; When observed; Then no reply ends with an assistant closer | planned |

### FR-003-30 — No over-apology; not uniformly cheerful

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-30-01 | unit | happy | Affect varies, not relentless positivity | Given varied contexts; When she replies; Then her affect varies rather than staying uniformly upbeat | planned |
| TC-FR-003-30-02 | unit | negative | No over-apologizing | Given a minor hiccup; When she replies; Then she does not over-apologize | planned |

### FR-003-31 — Show mood and emotional texture

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-31-01 | unit | happy | Can tease / sulk / go briefly quiet | Given appropriate context; When she replies; Then she can tease, sulk, or go briefly quiet | planned |
| TC-FR-003-31-02 | integration | consistency | Mood consistent with relationship state | Given the relationship state; When mood is applied; Then it is consistent with that state and the moment | planned |
| TC-FR-003-31-03 | e2e | happy | Mood reads as a real reaction | Given a client who teases her; When she replies; Then the reaction feels like a real person's | planned |

### FR-003-32 — One natural short follow-up within a still-active exchange

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-32-01 | unit | happy | Brief quiet in-exchange → one follow-up | Given the user goes briefly quiet mid-exchange; When the policy applies; Then she sends one short follow-up | planned |
| TC-FR-003-32-02 | unit | boundary | No repeated spam follow-ups | Given continued silence; When the policy applies; Then she does not send repeated follow-ups | planned |
| TC-FR-003-32-03 | integration | happy | Only within an active exchange | Given the exchange is still live; When quiet; Then the follow-up fires only while the exchange is active | planned |

### FR-003-33 — No cross-session proactive messages (Life Engine boundary)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-33-01 | unit | negative | No "messaged first" after exchange ended | Given the exchange has ended; When time passes; Then F-003 sends no proactive message | planned |
| TC-FR-003-33-02 | integration | negative | Cross-session proactivity not triggered | Given a new session boundary; When F-003 runs; Then it never initiates a cross-session message (that is the Life Engine) | planned |

### FR-003-34 — All human-likeness behaviors driven by `comm_settings_json`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-34-01 | unit | happy | Each behavior sources from comm_settings | Given the style layer; When it runs; Then pacing/verbosity/emoji/register/etc. read from comm_settings_json | planned |
| TC-FR-003-34-02 | integration | happy | Changing a knob changes behavior (no code) | Given a knob change in config; When she replies; Then the behavior changes without a code change | planned |
| TC-FR-003-34-03 | integration | consistency | comm_settings is single source of truth | Given conflicting hard-coded defaults; When styling runs; Then comm_settings_json governs | planned |

### FR-003-35 — Each persona has a distinct, internally-consistent texting style

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-35-01 | integration | happy | Two personas read as distinct texters | Given two personas; When each replies to the same prompt; Then they read as different people | planned |
| TC-FR-003-35-02 | integration | consistency | Each persona internally consistent | Given one persona over many turns; When observed; Then her style is internally consistent | planned |

### FR-003-36 — Texting style stays stable over time and sessions

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-36-01 | integration | state | Style persists across turns | Given a long chat; When observed; Then cadence/emoji/register persist | planned |
| TC-FR-003-36-02 | integration | persistence | Style same across sessions | Given a returning user days later; When she replies; Then the style matches earlier sessions | planned |
| TC-FR-003-36-03 | e2e | consistency | Skeptic re-test sees same person, words vary | Given a skeptic returning; When probing; Then the same texting personality shows, though exact words differ | planned |

### FR-003-37 — Per-user interaction-style overlay on top of persona defaults

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-37-01 | unit | happy | Low-emoji/literal overlay reduces emoji + slang | Given a low-emoji/literal overlay set; When styled; Then emoji and slang are reduced and text is more literal | planned |
| TC-FR-003-37-02 | integration | persistence | Overlay applied consistently once set | Given the overlay is set; When many turns run; Then it stays applied across the conversation | planned |
| TC-FR-003-37-03 | integration | mapping | Overlay layered on persona defaults | Given USER.interaction_style_json + persona comm_settings; When styled; Then the overlay modifies the persona defaults, not replaces them wholesale | planned |

### FR-003-38 — Preserve reply content/correctness; change only form/timing/style

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-003-38-01 | unit | happy | Content unchanged; only form/timing/style | Given an F-002 reply; When F-003 styles/paces it; Then the semantic content is unchanged | planned |
| TC-FR-003-38-02 | unit | negative | No chunk drop/reorder/meaning change | Given a chunked reply; When delivered; Then no chunk is dropped, reordered, or altered in meaning | planned |
| TC-FR-003-38-03 | e2e | happy | Delivered reply still answers the user | Given a client message; When the styled reply arrives; Then it still answers what the user asked | planned |

---

## Non-functional requirements

### NFR-003-01 — Total deliberate delay bounded by a defined upper cap

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-01-01 | performance | boundary | Measured delay ≤ cap | Given many paced replies; When timed; Then no total delay exceeds the cap | planned |
| TC-NFR-003-01-02 | performance | boundary | Worst-case within cap | Given the longest/busiest case; When timed; Then delivery is within the cap | planned |

### NFR-003-02 — Pacing does not increase model compute time

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-02-01 | performance | happy | Warm compute still meets NFR-002-01 | Given a warm model; When paced; Then compute time still meets F-002 NFR-002-01 | planned |
| TC-NFR-003-02-02 | performance | consistency | Human feel is additive wait only | Given pacing on; When measured; Then the extra time is an additive post-compute wait, not slower compute | planned |
| TC-NFR-003-02-03 | integration | negative | Pacing on/off leaves compute equal | Given pacing toggled; When compute is measured; Then it is unchanged | planned |

### NFR-003-03 — Styling does not degrade correctness/relevance

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-03-01 | integration | happy | Relevance unchanged vs F-002 reply | Given the pre-style reply; When styled; Then answer relevance is not measurably reduced | planned |
| TC-NFR-003-03-02 | integration | consistency | Styled reply as on-topic as source | Given many turns; When compared; Then styled replies stay as on-topic/in-character as the F-002 source | planned |

### NFR-003-04 — Pacing/typing/chunking hold under concurrent load

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-04-01 | load | happy | Many concurrent paced/chunked sends | Given K concurrent conversations; When paced; Then typing/pacing/chunking all work correctly | planned |
| TC-NFR-003-04-02 | load | boundary | p95 within degraded budget | Given heavy concurrency; When measured; Then p95 stays within the degraded budget | planned |
| TC-NFR-003-04-03 | load | boundary | Cap holds under load | Given load; When timed; Then the delay cap is never exceeded | planned |

### NFR-003-05 — Styling naturally localized (fluent RU / EN)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-05-01 | integration | localization | RU reads as fluent Russian texting | Given a RU persona; When styled; Then it reads as idiomatic Russian texting | planned |
| TC-NFR-003-05-02 | integration | localization | EN reads as fluent English texting | Given an EN persona; When styled; Then it reads as idiomatic English texting | planned |

**Manual — TC-NFR-003-05-03 (manual-e2e)**
- Preconditions: bot deployed; a Russian-native reviewer with Telegram.
- Steps: 1) Chat with a RU persona for several turns. 2) Read the register, slang, and emoji.
- Expected: it reads as a real Russian girl texting — natural slang/register, not translated-English habits or template text.
- Status: planned

### NFR-003-06 — Never leak AI/system voice (in-character 100%)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-06-01 | unit | negative | No meta-text ("typing…" as content, model notes) | Given styled output; When inspected; Then no meta/system text appears as message content | planned |
| TC-NFR-003-06-02 | unit | negative | No "as an AI"/model disclosure | Given any reply; When inspected; Then no AI self-disclosure leaks | planned |
| TC-NFR-003-06-03 | integration | error | Fallback path stays in character | Given a styling/pacing failure; When it falls back; Then the delivered message still never leaks system voice | planned |

### NFR-003-07 — Every knob measurable and tunable via `comm_settings_json` without code

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-07-01 | integration | happy | Change knob via config, no code change | Given a config edit to a knob; When she replies; Then behavior changes with no code deploy | planned |
| TC-NFR-003-07-02 | integration | boundary | Each knob has a measurable effect | Given each knob swept; When measured; Then each produces an observable, bounded change | planned |

### NFR-003-08 — Style self-consistent over time / across sessions

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-08-01 | integration | consistency | No drift under probing | Given adversarial probing; When measured; Then no style drift is surfaced | planned |
| TC-NFR-003-08-02 | integration | persistence | Cross-session style stable | Given multiple sessions; When compared; Then the style is recognizably the same person | planned |

### NFR-003-09 — Per-persona differentiation perceptible

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-09-01 | integration | happy | Two personas read as different texters | Given two configured personas; When each replies; Then a reader can tell them apart | planned |
| TC-NFR-003-09-02 | statistical | boundary | Difference is measurable | Given style metrics; When compared; Then cadence/emoji/register differ measurably between personas | planned |

### NFR-003-10 — Anti-repetition measurable and below threshold

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-10-01 | statistical | boundary | Greeting/opening repeat rate below threshold | Given consecutive turns; When measured; Then repeat rate < the defined threshold | planned |
| TC-NFR-003-10-02 | statistical | negative | No detectable templated loop | Given a long chat; When analyzed; Then no templated loop is detectable | planned |

### NFR-003-11 — "typing…" indicator appears promptly (~1s)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-11-01 | performance | happy | Typing shown within ~1s of message | Given an inbound message; When received; Then "typing…" appears within ~1 second | planned |
| TC-NFR-003-11-02 | performance | boundary | p95 typing-start within budget | Given many turns; When measured; Then p95 typing-start stays within budget | planned |

### NFR-003-12 — Chunked delivery guarantees ordering and integrity

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-12-01 | integration | happy | Chunks arrive in order | Given a chunked reply; When delivered; Then chunks arrive in the correct order | planned |
| TC-NFR-003-12-02 | integration | error | No loss/interleaving/duplication | Given delivery hiccups; When sent; Then no chunk is lost, interleaved, or duplicated | planned |
| TC-NFR-003-12-03 | concurrency | idempotency | Ordering holds under retry | Given a retried send; When delivered; Then order/integrity are preserved | planned |

### NFR-003-13 — Emoji/slang/typo rates bounded to preserve readability

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-13-01 | unit | boundary | Human texture never breaks readability | Given max configured texture; When styled; Then the message is still easily readable | planned |
| TC-NFR-003-13-02 | statistical | boundary | Rates stay within readable bounds | Given many replies; When measured; Then emoji/slang/typo rates stay within readable bounds | planned |

### NFR-003-14 — Low-emoji / more-literal style reliably applied and stable

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-14-01 | integration | happy | Emoji reduced when low-emoji set | Given the low-emoji style; When styled; Then emoji drop well below default | planned |
| TC-NFR-003-14-02 | integration | happy | Literalness increased | Given the literal style; When styled; Then irony/heavy slang ease off and text is clearer | planned |
| TC-NFR-003-14-03 | integration | persistence | Adjustment stable across the conversation | Given the style set; When many turns run; Then the adjustment holds consistently | planned |

### NFR-003-15 — Human-likeness layer degrades gracefully

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-15-01 | error | happy | Pacing fails → reply still delivered | Given the pacing/typing/chunking fails; When the reply is ready; Then it is still delivered correctly | planned |
| TC-NFR-003-15-02 | error | negative | Never dropped or left silent | Given a styling failure; When it occurs; Then the chat is never left silent and no message is dropped | planned |

### NFR-003-16 — Delivery idempotent against duplicate sends/retries

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-16-01 | concurrency | idempotency | Duplicate → single reply sequence | Given a duplicated/retried user message; When processed; Then one logical reply sequence results | planned |
| TC-NFR-003-16-02 | concurrency | idempotency | No re-fired/duplicated chunks | Given a retry mid-chunking; When delivered; Then chunks are not duplicated or re-fired | planned |

### NFR-003-17 — Acceptable on weak/low-bandwidth connections (A5)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-003-17-01 | integration | error | Reply complete/in order on weak signal | Given a weak connection; When a chunked paced reply is sent; Then it still arrives complete and in order | planned |
| TC-NFR-003-17-02 | integration | boundary | Degrade to fewer signals, not failure | Given typing/pauses can't be delivered reliably; When sending; Then the system drops signals gracefully rather than failing | planned |

---

## User-story acceptance (manual real-device E2E)

One manual acceptance test per user story — judges the felt human-likeness automation can't fully score.

**TC-US-003-01-01 (manual-e2e) — A1: real human cadence/register, no bot energy**
- Preconditions: bot deployed; Telegram on your phone.
- Steps: 1) Send a lazy casual opener. 2) Watch timing, register, emoji.
- Expected: "typing…" for a beat, then a short lowercase reply with a bit of slang, no wall of text,
  no emoji-per-line — it reads like a real girl typed it. Status: planned

**TC-US-003-02-01 (manual-e2e) — A8 skeptic: can't find the robotic tells**
- Steps: 1) Fire ~10 varied messages trying to trip it. 2) Watch timing/openings/closers/emoji.
- Expected: timing varies with length, openings never repeat as a template, no "how can I help you?",
  no emoji-per-sentence — no catchable "it's a bot" tell. Status: planned

**TC-US-003-03-01 (manual-e2e) — A2: real emotional texture**
- Steps: 1) Tease her. 2) Be a little short with her. 3) Observe her reactions.
- Expected: she teases back; when you're short she gets a little quiet/mock-offended rather than
  relentlessly upbeat — it lands as a real reaction. Status: planned

**TC-US-003-04-01 (manual-e2e) — A4: natural unhurried pace**
- Steps: 1) Take your time between messages. 2) Observe her tempo.
- Expected: she does not blast instant messages the microsecond you send; replies arrive at a human
  tempo; the exchange feels relaxed, not rapid-fire. Status: planned

**TC-US-003-05-01 (manual-e2e) — A6: literal, low-emoji style honored**
- Steps: 1) Set/ask for a more literal, low-emoji style. 2) Continue chatting.
- Expected: far fewer emoji, less irony/slang, clearer more predictable sentences, held consistently.
  Status: planned

**TC-US-003-06-01 (manual-e2e) — Returning user: same texting personality**
- Preconditions: an account that chatted a week ago.
- Steps: 1) Return after days. 2) Compare her style to before.
- Expected: same cadence, same emoji habit, same verbal tics — reads as the same girl, though the
  exact words differ. Status: planned

**TC-US-003-07-01 (manual-e2e) — A1: long answer chunked like real texting**
- Steps: 1) Ask her to tell you about her weekend.
- Expected: instead of one dense block she sends a few short messages in a row with a "typing…"
  flicker between them, like a real girl telling a story over text. Status: planned

**TC-US-003-08-01 (manual-e2e) — Skeptic: no templated loops**
- Steps: 1) Have a long chat. 2) Watch her hellos, sentence starts, verbal tics.
- Expected: openings and phrasing all vary; nothing repeats in a copy-paste way. Status: planned

**TC-US-003-09-01 (manual-e2e) — A7: gentle, warm, readable style**
- Steps: 1) Type full careful sentences. 2) Read her replies.
- Expected: warm, steady, readable — not a firehose of slang/emoji, not a stiff robot; feels like a
  kind person texting back. Status: planned

---

## Coverage summary

- **Functional:** FR-003-01..38 — **97 automated tests** (2-3 per requirement) across unit /
  integration / component / e2e / statistical, spanning happy / negative / boundary / mapping /
  consistency / persistence / localization cases. ✓
- **Non-functional:** NFR-003-01..17 — **41 tests** (2-3 per requirement: performance / load /
  integration / statistical / error / concurrency), including 1 manual localization check
  (TC-NFR-003-05-03). ✓
- **User stories:** US-003-01..09 — **9 manual real-device acceptance tests**. ✓
- **Total: 147 enumerated tests** — in the 100-150 target band for this (large, deliberately
  detailed) feature; F-003 has 55 requirements, so it sits near the top of the band by design.
- Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies, matching the feature file's IDs.
