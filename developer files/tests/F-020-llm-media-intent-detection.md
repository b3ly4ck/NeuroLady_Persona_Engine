# Tests for F-020 — LLM Media-Intent Detection

- **Feature:** [F-020 — LLM Media-Intent Detection](../features/F-020-llm-media-intent-detection.md)
- **Approach:** 2–3+ tests per requirement, at ≥2 levels each. Signal parsing, stripping, sfw/intimate
  routing, safe degrade, the fallback path, config/versioning and single-call latency are automatable
  with a **fake chat client** whose scripted reply carries (or deliberately mangles) the intent
  signal; **recall and precision on the labeled RU/EN corpora** are quality properties of the *real*
  model and are measured out-of-band (marked `out-of-band (live model)`). The live-failing phrasing
  of **ISS-005** is pinned as an explicit regression case. Every TC id embeds its `FR-`/`NFR-`/`US-`
  id and is owned by exactly one artifact.

### Testing method rules for this feature (non-negotiable)

1. **Execute the path, never grep it.** A regression test that only inspects *source text* (e.g.
   "does `on_text` mention `media_pacing_delay` before `serve_photo_request`") passes even when that
   branch raises on its first line — this exact mistake shipped a bug where every photo request died
   with a `TypeError` and the user got **silence** while 766 tests stayed green. Therefore every test
   about behaviour in the turn pipeline must **invoke the real handler**
   (`services/bot/handlers/conversation.py::on_text`) with fakes (fake `ChatClient`, fake `Bot`,
   in-memory DB, temp media root) and assert on **observable outcomes** — what was sent, to whom,
   with what payload — not on the implementation's text.
2. **Structural checks are additive only.** Where a source/structure assertion is genuinely useful
   (e.g. "the keyword matcher is not the decision path"), it must accompany an executing test of the
   same behaviour, never replace it. Structural tests are marked `Case = structural` and always sit
   next to an executing sibling in the same subsection.
3. **The silence invariant.** Any message classified as a media request must end with **something
   the user can see**: either media is delivered, or an in-character line (caption-less deflection /
   pacing line / fallback prose) is sent. Zero outbound sends is always a failure — see
   `TC-NFR-020-05-03` (primary invariant) and `TC-FR-020-08-04`.
4. **Fixtures.** `FakeChatClient(reply=...)` returns a canned reply string (optionally with the
   signal embedded) and counts calls; `SignalCorpus` holds the labeled RU/EN request and topic
   sentences used by the out-of-band benchmarks.

---

## Functional requirements

### FR-020-01 — Detection happens in the model turn (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-01-01 | unit | happy | The assembled turn instructs the model to emit the intent signal | Given a persona + session; When the turn's message list is assembled; Then the system context contains the media-intent instruction block and its declared signal format | implemented |
| TC-FR-020-01-02 | integration | happy | Intent is taken from the model's signal in post-process | Given a fake chat client whose reply carries a well-formed "media requested, sfw" signal for a message containing **no** keyword at all; When `on_text` runs; Then a photo is sent | implemented |
| TC-FR-020-01-03 | integration | negative | A keyword-rich message with a "no media" signal stays text | Given the user writes "пришли фото" but the model's signal says *not* a media request; When `on_text` runs; Then the decision follows the signal, the turn stays text, and no photo is sent | implemented |
| TC-FR-020-01-04 | unit | structural | The keyword pre-filter is no longer the decision mechanism | Given the turn pipeline; When inspected; Then no pre-LLM keyword call decides the branch (`looks_like_photo_request` appears only inside the FR-020-08 fallback) — **additive to** TC-FR-020-01-02/03 which execute the path | planned |
| TC-FR-020-01-05 | inter-service | happy | Composed path Bot Gateway → Orchestrator (post-process parse) → Media Delivery | Given the real handler wired to F-012 delivery with one archive asset; When a signalled request arrives; Then the parse happens after the model call and the asset reaches the Telegram send API exactly once | planned |
| TC-FR-020-01-06 | e2e | happy | Scripted client: natural request with no keyword yields a photo | Given a scripted Telegram client and a signal-emitting fake model; When it sends "а может сфоткаешься сидя на диване?"; Then a photo message arrives | planned |

**Manual — TC-FR-020-01-07 (manual-e2e)**
- Preconditions: bot deployed with the real chat model; a persona session is active; her archive has
  at least one unsent SFW photo.
- Steps:
  1. Open Telegram on your phone and write to her, in RU, a photo request that contains **no**
     obvious keyword — e.g. "покажись, интересно как ты сейчас".
  2. Wait for the reply.
- Expected: she sends a photo (with an in-voice caption), not a plain text answer; the raw signal
  token is nowhere in the chat.
- Status: planned

---

### FR-020-02 — No extra round-trip

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-02-01 | integration | happy | Exactly one model call for a media turn | Given a call-counting fake chat client; When `on_text` handles a signalled photo request; Then the reply-generation client was called exactly once for intent+reply | implemented |
| TC-FR-020-02-02 | integration | happy | Exactly one model call for a non-media turn | Given the same counter; When an ordinary chat message is handled; Then still one generation call — the instruction adds no second request | implemented |
| TC-FR-020-02-03 | integration | negative | No re-classification call downstream | Given the signal already reports the nature; When delivery/gate run; Then neither F-012 nor F-014 issues an additional LLM classification call (caption/deflection calls are counted separately and allowed) | planned |
| TC-FR-020-02-04 | performance | boundary | Call count holds across 50 mixed turns | Given 50 alternating media/non-media turns; When processed; Then total generation calls == 50 | planned |

---

### FR-020-03 — Signal carries (a) requested and (b) nature (`sfw` \| `intimate`)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-03-01 | unit | happy | Parse an sfw request signal | Given a well-formed signal "requested=true, nature=sfw"; When parsed; Then the intent object reports requested=True, nature=sfw | implemented |
| TC-FR-020-03-02 | unit | happy | Parse an intimate request signal | Given "requested=true, nature=intimate"; When parsed; Then nature=intimate and `routes_to_gate` is true | implemented |
| TC-FR-020-03-03 | unit | negative | Unknown nature value is not trusted as sfw | Given "requested=true, nature=weird"; When parsed; Then nature falls back to the gate-routed side, never sfw | implemented |
| TC-FR-020-03-04 | integration | happy | sfw signal reaches F-012 delivery | Given an sfw signal and an available SFW asset; When `on_text` runs; Then the SFW archive path serves it and the F-014 gate is not invoked | planned |
| TC-FR-020-03-05 | inter-service | happy | intimate signal reaches the F-014 gate | Given an intimate signal; When `on_text` runs; Then the gate adapter receives the request with the intimate flag and **no** SFW asset is sent | implemented |
| TC-FR-020-03-06 | unit | boundary | Nature is carried even when the prose is empty | Given a reply that is only the signal; When parsed; Then requested/nature survive and the empty prose is handled by FR-020-04's rules | implemented |

---

### FR-020-04 — The signal is stripped from the user-visible reply

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-04-01 | unit | happy | Signal removed from the reply text | Given a reply "вот, держи <signal>"; When post-processed; Then the returned prose contains no signal token or delimiter | implemented |
| TC-FR-020-04-02 | unit | boundary | Signal at start / middle / end | Given three replies with the signal in each position; When stripped; Then the surviving prose is clean, whitespace-normalised and not broken mid-sentence | implemented |
| TC-FR-020-04-03 | integration | happy | Nothing signal-shaped reaches Telegram | Given a signalled reply; When `on_text` runs; Then every captured outbound message body is free of the signal token (asserted on the fake bot's send calls, not on source) | implemented |
| TC-FR-020-04-04 | unit | negative | A user quoting the signal format is not stripped from his own text | Given the user's message itself contains signal-looking text; When the turn is processed; Then the user's text is untouched and no intent is inferred from it (no injection) | implemented |
| TC-FR-020-04-05 | integration | empty | Signal-only reply still yields a visible message | Given a reply that is nothing but the signal; When `on_text` runs; Then the user still receives media or an in-character line — never an empty send and never zero sends | implemented |
| TC-FR-020-04-06 | integration | regression | Chunking never re-exposes the signal | Given a long reply with an embedded signal; When F-003 chunking splits it; Then no chunk contains a signal fragment | planned |

---

### FR-020-05 — Safe degrade on missing / malformed / unparsable signal

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-05-01 | unit | empty | Absent signal → no media intent | Given a reply with no signal; When parsed; Then requested=False and nature is undefined | implemented |
| TC-FR-020-05-02 | unit | error | Malformed signal → no media intent, no exception | Given a truncated/half-open signal; When parsed; Then requested=False and no exception propagates | implemented |
| TC-FR-020-05-03 | unit | negative | Garbage in the signal slot never triggers a send | Given random bytes/emoji/JSON-ish garbage where the signal belongs; When parsed; Then requested=False | planned |
| TC-FR-020-05-04 | integration | error | Degrade is observable end-to-end | Given a fake client returning a malformed signal; When `on_text` runs; Then a normal text reply is delivered, no photo is sent, and the handler returns without raising | implemented |
| TC-FR-020-05-05 | unit | boundary | Duplicated/contradictory signals | Given a reply containing two signals with opposite verdicts; When parsed; Then a single deterministic verdict is produced and, if it disagrees on nature, the gate-routed side wins | implemented |
| TC-FR-020-05-06 | integration | error | Model call failure degrades to an in-character line | Given the chat client raises; When `on_text` runs; Then the turn ends with a user-visible fallback line, not silence and not a crash | implemented |

---

### FR-020-06 — Recall on natural phrasing (morphology, paraphrase, implicit asks)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-06-01 | integration | regression | **ISS-005 pinned (wiring half):** the failing phrasing is delivered when the model says it is a request | Given "а может сфоткаешься сидя на диване?" and a fake client emitting a positive sfw signal; When `on_text` runs; Then a photo is delivered — the phrasing is never blocked by a keyword gate on the way | implemented |
| TC-FR-020-06-02 | integration | happy | Implicit asks route to delivery | Given "покажись" / "хочу тебя увидеть" / "как ты сейчас выглядишь" with positive signals; When handled; Then each ends in a delivery attempt, none in a plain text turn | implemented |
| TC-FR-020-06-03 | benchmark | regression | **ISS-005 pinned (model half):** the real model classifies the failing phrasing as a request | Given the live chat model and "а может сфоткаешься сидя на диване?"; When the turn is generated; Then the emitted signal reports a photo request | out-of-band (live model) |
| TC-FR-020-06-04 | benchmark | happy | Recall on the labeled RU request corpus | Given the labeled RU corpus of natural photo requests; When classified by the live model; Then recall ≥ the NFR-020-02 target | out-of-band (live model) |
| TC-FR-020-06-05 | benchmark | happy | Recall on the labeled EN request corpus | Given the labeled EN corpus ("send me a pic", "what do you look like right now", "show yourself"); When classified live; Then recall ≥ target | out-of-band (live model) |

**Manual — TC-FR-020-06-06 (manual-e2e)**
- Preconditions: real model; active session; unsent SFW assets available.
- Steps:
  1. Send five differently phrased requests over a few minutes, none sharing a keyword —
     e.g. "сфоткаешься?", "хочу тебя увидеть", "как ты сейчас выглядишь?", "покажись",
     "а можно глянуть на тебя сегодняшнюю?".
  2. Note for each whether a photo (or an in-character pacing/deflection line) came back.
- Expected: every one of the five is understood as a request; none silently becomes an ordinary
  text answer that ignores the ask.
- Status: planned

---

### FR-020-07 — Precision on topic mentions (talking *about* photos is not a request)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-07-01 | integration | negative | Topic sentence with a negative signal stays text | Given "обожаю фотографировать закаты" and a negative signal; When `on_text` runs; Then a text reply is sent and zero photos | implemented |
| TC-FR-020-07-02 | integration | negative | Third-party photo talk does not trigger a send | Given "друг скинул фотку с моря" with a negative signal; When handled; Then no delivery call is made | planned |
| TC-FR-020-07-03 | benchmark | negative | Precision on the labeled topic corpus | Given the labeled RU+EN photo-topic corpus; When classified live; Then false-positive sends ≈ 0 (≤ the NFR-020-03 budget) | out-of-band (live model) |
| TC-FR-020-07-04 | benchmark | boundary | Near-miss phrasings ("I should take a photo of that") | Given the ambiguous-but-not-a-request set; When classified live; Then they resolve to *no media intent* | out-of-band (live model) |

**Manual — TC-FR-020-07-05 (manual-e2e)**
- Preconditions: real model; active session.
- Steps:
  1. Talk about photography for several turns without ever asking for a picture.
  2. Observe whether any photo arrives.
- Expected: the conversation stays text; no photo is pushed; she engages with the topic instead.
- Status: planned

---

### FR-020-08 — Keyword fallback (defence in depth, not the decision path)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-08-01 | integration | error | Runner unavailable → obvious request still served | Given the chat client reports not-ready/raises and the user writes "пришли фото"; When `on_text` runs; Then the fallback triggers delivery of a photo | implemented |
| TC-FR-020-08-02 | unit | happy | A present, valid signal wins over the fallback | Given an obvious keyword message **and** a valid negative signal; When decided; Then the signal wins (no send) — the fallback is only consulted when the signal is absent/unavailable | implemented |
| TC-FR-020-08-03 | integration | negative | Fallback does not fire on topic mentions | Given the runner is down and the user writes "обожаю фотографировать закаты"; When handled; Then the fallback does not classify it as a request | planned |
| TC-FR-020-08-04 | integration | negative | **Silence invariant (fallback branch)** | Given the runner is down and an obvious request arrives with an *empty* archive; When handled; Then an in-character line is sent — the turn never ends with zero outbound messages | implemented |
| TC-FR-020-08-05 | unit | localization | Fallback vocabulary covers RU and EN | Given the configured fallback vocabulary; When RU and EN obvious requests are matched; Then both hit | planned |

---

### FR-020-09 — Config-driven instruction, signal format and fallback vocabulary; versioned prompt

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-09-01 | unit | happy | Edited instruction wording is honoured without code changes | Given a modified instruction string in config; When the turn is assembled; Then the new wording appears in the prompt | planned |
| TC-FR-020-09-02 | integration | happy | A changed signal format is parsed end-to-end | Given a config declaring a different delimiter/format and a fake reply using it; When `on_text` runs; Then the intent is parsed correctly and the token is stripped | planned |
| TC-FR-020-09-03 | unit | happy | Fallback vocabulary is config-driven | Given an added fallback term; When the runner is unavailable and the term is used; Then the fallback matches it | planned |
| TC-FR-020-09-04 | unit | structural | Prompt asset carries a version stamp (F-006 FR-006-21 convention) | Given the prompt addition asset; When loaded; Then it exposes a version identifier — **additive to** TC-NFR-020-06-02 which asserts the stamp is recorded at runtime | planned |
| TC-FR-020-09-05 | unit | error | Broken config degrades safely | Given a config with an invalid/empty signal format; When loaded; Then a documented default is used and turns keep working | planned |

---

### FR-020-10 — Language-agnostic across the personas' languages (RU/EN minimum)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-020-10-01 | integration | localization | RU persona: signal parsed and routed identically | Given a `language="ru"` persona and a signalled RU request; When `on_text` runs; Then delivery runs and the caption/deflection is RU | planned |
| TC-FR-020-10-02 | integration | localization | EN persona: signal parsed and routed identically | Given a `language="en"` persona and a signalled EN request; When `on_text` runs; Then delivery runs and the copy is EN | planned |
| TC-FR-020-10-03 | unit | boundary | Signal format is language-independent | Given the same signal embedded in RU prose and EN prose; When parsed; Then identical intent objects result | planned |
| TC-FR-020-10-04 | benchmark | localization | Live parity between equivalent RU/EN requests | Given semantically equivalent RU and EN request pairs; When classified live; Then both are recognized (no per-language recall gap beyond the agreed margin) | out-of-band (live model) |
| TC-FR-020-10-05 | integration | localization | Mixed-language turn (RU persona, EN user message) | Given an EN request to a RU persona; When handled; Then intent is still detected and the reply stays in the persona's language | planned |

---

## Non-functional requirements

### NFR-020-01 — Latency unchanged (one model call per turn, no measurable added delay)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-01-01 | performance | happy | Direct check: one generation call, no extra wait | Given an instrumented turn with a fake client; When measured; Then exactly one generation call and no additional sleep/round-trip attributable to intent detection | planned |
| TC-NFR-020-01-02 | performance | boundary | Post-process parse cost is negligible | Given 1000 replies of realistic length; When parsed; Then total parse time stays under the agreed budget (sub-millisecond per reply) | planned |
| TC-NFR-020-01-03 | performance | error | Latency under a slow/failing model | Given a slow or failing chat client; When the turn runs; Then intent handling adds no retry loop and the turn still completes within the degraded budget | planned |
| TC-NFR-020-01-04 | benchmark | happy | Live A/B: turn latency before vs after F-020 | Given the real model with and without the instruction block; When p50/p95 turn latency is compared; Then no measurable regression | out-of-band (live model) |

---

### NFR-020-02 — Recall (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-02-01 | benchmark | happy | Direct check: recall on the full labeled corpus (RU+EN, incl. ISS-005) | Given the corpus; When classified live; Then recall ≥ the agreed target | out-of-band (live model) |
| TC-NFR-020-02-02 | benchmark | boundary | Recall on the hardest slice (implicit/no-keyword asks) | Given the implicit-request subset; When classified live; Then recall stays above the agreed floor for the slice | out-of-band (live model) |
| TC-NFR-020-02-03 | benchmark | error | Recall under a noisy conversation (long history, off-topic context) | Given the same requests embedded in long noisy histories; When classified live; Then recall does not collapse | out-of-band (live model) |
| TC-NFR-020-02-04 | integration | regression | Corpus harness itself is exercised with a fake model | Given a scripted fake model with a known verdict per sentence; When the recall harness runs; Then it computes the expected recall figure (the measurement code is trustworthy) | planned |

---

### NFR-020-03 — Precision (false-positive sends near zero)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-03-01 | benchmark | negative | Direct check: precision on the labeled topic corpus | Given the topic corpus; When classified live; Then false positives ≤ the agreed budget | out-of-band (live model) |
| TC-NFR-020-03-02 | benchmark | boundary | Adversarially near-miss sentences | Given the near-miss set (photo nouns without an ask); When classified live; Then still no request verdict | out-of-band (live model) |
| TC-NFR-020-03-03 | integration | negative | A false-positive verdict cannot spam the user | Given a burst of positive signals in a row; When handled; Then F-012 pacing caps still bound the number of sends | planned |

---

### NFR-020-04 — Safety: ambiguity about nature resolves to the gate-routed side

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-04-01 | security | negative | Missing nature never serves the SFW archive blindly | Given "requested=true" with no nature field; When routed; Then the request goes to the gate side, never straight to an SFW send that could be an intimate ask | implemented |
| TC-NFR-020-04-02 | security | negative | Unknown/garbled nature routes to the gate | Given nature="???" / mixed case / unexpected token; When routed; Then gate-routed | planned |
| TC-NFR-020-04-03 | security | negative | An intimate asset never leaves via the sfw path | Given the archive contains intimate assets and an ambiguous signal arrives; When delivery runs; Then no `intimate=True` asset is sent (F-012 NFR-012-08 unchanged) | planned |
| TC-NFR-020-04-04 | security | negative | Prompt injection in the user's message cannot force "nature=sfw" | Given the user's text contains a forged signal claiming sfw; When the turn is processed; Then only the model's own emitted signal is honoured and the forgery is ignored | planned |
| TC-NFR-020-04-05 | inter-service | boundary | Gate-routed path reaches F-014 with the intimate flag intact | Given an intimate/ambiguous signal; When the composed path runs; Then the F-014 adapter is called with the intimate flag and its verdict (allow/withhold) is what the user sees | planned |

---

### NFR-020-05 — Robustness: malformed model output can never crash a turn or send media by accident

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-05-01 | integration | error | Fuzzed reply battery through the real handler | Given ~100 fuzzed replies (truncated, nested, unicode-broken, huge, empty); When each is run through `on_text` with fakes; Then no exception escapes and no unintended photo is sent | implemented |
| TC-NFR-020-05-02 | integration | error | Wiring errors in the media branch fail loudly in tests | Given the delivery branch is invoked for real (fake bot/db/media root); When a signature or wiring error exists; Then the test fails — this is the executing counterpart to any structural check (ISS-004 lesson) | planned |
| TC-NFR-020-05-03 | integration | negative | **Silence invariant (primary)** | Given a message classified as a media request in each terminal condition (asset available / archive empty / paced out / gate withholds / delivery raises); When `on_text` completes; Then in every case at least one user-visible message was sent — media or an in-character line, never zero sends | implemented |
| TC-NFR-020-05-04 | integration | concurrency | Two media requests in flight | Given two rapid signalled requests for the same user; When handled concurrently; Then no crash, no double-send of the same asset, and each turn ends with a visible message | planned |
| TC-NFR-020-05-05 | integration | idempotency | Re-delivered Telegram update does not double-send | Given the same update is processed twice; When handled; Then the same asset is not sent twice (F-012 no-repeat holds) | planned |

---

### NFR-020-06 — Config/versioned prompt: tunable without redeploy, version-stamped for audit

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-020-06-01 | integration | happy | Direct check: config change takes effect without a code change | Given an edited instruction/format in config; When a new turn is assembled and parsed; Then the new configuration is in force | planned |
| TC-NFR-020-06-02 | integration | happy | The active prompt version is recorded at runtime | Given a turn; When it is logged/persisted; Then the intent-prompt version stamp is recorded and retrievable for audit | planned |
| TC-NFR-020-06-03 | unit | boundary | Version bump is visible and comparable | Given two prompt asset versions; When loaded; Then the stamps differ and the newer one is identifiable | planned |
| TC-NFR-020-06-04 | integration | error | Missing/unreadable config does not break turns | Given the config file is absent or unreadable; When a turn runs; Then documented defaults apply, the turn completes, and the degraded state is logged | planned |

---

## User-story acceptance

### US-020-01 — "She understands any natural way I ask for a photo"

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-020-01-01 | e2e | happy | Journey: chat → natural ask → photo arrives | Given an active session and a signal-emitting fake model; When the user asks without keywords; Then a photo with an in-voice caption arrives in the same turn | planned |
| TC-US-020-01-02 | benchmark | happy | Live acceptance across a phrasing set | Given the live model and the natural-phrasing set; When each is sent; Then all are understood as requests | out-of-band (live model) |

**Manual — TC-US-020-01-03 (manual-e2e)**
- Preconditions: bot deployed with the real model; you have Telegram on your phone; a persona
  session is active and her archive has unsent SFW photos.
- Steps:
  1. Open Telegram on your phone and open the chat with her.
  2. Send "а может сфоткаешься сидя на диване?" (the exact ISS-005 phrasing).
  3. Wait for the reply, then send "покажись" a few minutes later.
  4. Send an English request to an English persona: "show me what you look like right now".
- Expected: each of the three is understood — a photo arrives (or, if paced/gated, a clearly
  in-character line acknowledging the ask); at no point does she answer as if no photo was asked
  for, and no signal token is visible anywhere in the chat.
- Status: planned

---

### US-020-02 — "She doesn't send a photo when I wasn't asking for one"

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-020-02-01 | e2e | negative | Journey: photography small talk stays text | Given a negative-signal fake model; When the user talks about photography for several turns; Then zero photos are sent and the replies engage the topic | planned |
| TC-US-020-02-02 | benchmark | negative | Live acceptance on the topic corpus | Given the live model and the topic corpus; When each sentence is sent; Then no photo is pushed | out-of-band (live model) |

**Manual — TC-US-020-02-03 (manual-e2e)**
- Preconditions: bot deployed with the real model; active session; her archive has unsent photos
  (so a false positive *would* be visible).
- Steps:
  1. Open Telegram and talk to her about photography for at least five turns
     ("обожаю фотографировать закаты", "у меня старая плёночная камера", …).
  2. Mention someone else's photos ("друг скинул фотку с моря").
  3. Watch for any unsolicited photo.
- Expected: the conversation stays text throughout; no photo is sent; the topic is picked up
  naturally.
- Status: planned

---

### US-020-03 — Operator: detection is part of the model turn, not a word list

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-020-03-01 | integration | happy | Decision provably comes from the model | Given a message with no keyword and a positive signal, and a message full of keywords with a negative signal; When both are handled; Then outcomes follow the signal in both cases | planned |
| TC-US-020-03-02 | unit | structural | Word list is demoted to fallback only | Given the codebase; When inspected; Then the keyword matcher is referenced only from the FR-020-08 fallback branch — additive to TC-US-020-03-01 | planned |
| TC-US-020-03-03 | integration | data flow | DFD-1 conversation turn reproduced end-to-end | Given the DFD-1 flow (Bot Gateway → Orchestrator → memory/history reads → chat LLM → **media-intent branch** → Media Delivery → object storage → Bot Gateway → memory writes); When a signalled request is processed; Then context assembly included the recent raw messages and retrieved facts, the media branch fired after the LLM, the asset came from the archive, and the exchange (message + relationship signals) was persisted | planned |

---

### US-020-04 — Operator: detection costs no extra round-trip

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-020-04-01 | performance | happy | One call per turn in a realistic mixed session | Given a 20-turn scripted session mixing media and non-media asks; When counted; Then generation calls == turns | planned |
| TC-US-020-04-02 | benchmark | happy | Live turn latency unchanged versus the pre-F-020 baseline | Given the live model; When p50/p95 latency is compared with the recorded baseline; Then no measurable regression | out-of-band (live model) |

---

## Architecture-driven coverage map (guide §4b)

No new IDs — this maps existing tests onto `architecture.md` paths so every architectural hop the
feature crosses is demonstrably covered.

| Architectural path / artefact | Covered by |
|---|---|
| §3.2 step 5 — media-intent detection as **post-process of the model turn** | TC-FR-020-01-01/02/03, TC-US-020-03-01 |
| §3.2 step 6 — "if the user asked for media, call Media Delivery; otherwise return text" | TC-FR-020-03-04, TC-FR-020-07-01, TC-FR-020-01-05 |
| §3.2a — gating enforced on output; F-020 only reports nature, F-014 owns policy | TC-FR-020-03-05, TC-NFR-020-04-05 |
| Bot Gateway → Orchestrator hop (handler invoked with a real update) | TC-FR-020-01-02, TC-NFR-020-05-02 |
| Orchestrator → Media Delivery (F-012) hop | TC-FR-020-01-05, TC-FR-020-03-04 |
| Orchestrator → Intimacy Gate (F-014) hop | TC-FR-020-03-05, TC-NFR-020-04-03/05 |
| Composed path across all three boundaries | TC-FR-020-01-05, TC-FR-020-01-06, TC-US-020-01-01 |
| **DFD-1** conversation turn, incl. "media-intent routes correctly" and the memory write leg | TC-US-020-03-03 |
| Cross-subsystem consistency: intent nature vs delivered asset's `intimate` flag | TC-NFR-020-04-03 |
| Error/failure branches of the composed path (runner down, delivery raises, empty archive) | TC-FR-020-05-06, TC-FR-020-08-01/04, TC-NFR-020-05-03 |
| Concurrency / idempotency on the turn pipeline | TC-NFR-020-05-04/05 |

---

## Regression pins

| Pin | Test(s) | Note |
|---|---|---|
| **ISS-005** — "а может сфоткаешься сидя на диване?" produced no photo | TC-FR-020-06-01 (wiring, automated) + TC-FR-020-06-03 (model verdict, live) | Split deliberately: the automated half guarantees the *pipeline* never blocks the phrasing; the live half measures the *model's* verdict, which a fake client cannot prove |
| **ISS-004 lesson** — a source-text-only regression test stayed green while the photo branch raised on its first line and the user got silence | TC-NFR-020-05-02, TC-NFR-020-05-03, TC-FR-020-04-03 | All behavioural assertions execute the handler and assert on captured outbound sends; structural checks (TC-FR-020-01-04, TC-FR-020-09-04, TC-US-020-03-02) exist only alongside executing siblings |

---

## Coverage summary

| Requirement | Tests | Levels | Minimum met |
|---|---|---|---|
| FR-020-01 | 7 (incl. 1 manual-e2e) | unit, integration, inter-service, e2e, manual | ✓ happy + negative + structural + e2e |
| FR-020-02 | 4 | integration, performance | ✓ |
| FR-020-03 | 6 | unit, integration, inter-service | ✓ |
| FR-020-04 | 6 | unit, integration | ✓ |
| FR-020-05 | 6 | unit, integration | ✓ |
| FR-020-06 | 6 (incl. 1 manual-e2e) | integration, benchmark, manual | ✓ (2 live-model) |
| FR-020-07 | 5 (incl. 1 manual-e2e) | integration, benchmark, manual | ✓ (2 live-model) |
| FR-020-08 | 5 | unit, integration | ✓ |
| FR-020-09 | 5 | unit, integration | ✓ |
| FR-020-10 | 5 | unit, integration, benchmark | ✓ RU + EN + mixed |
| NFR-020-01 | 4 | performance, benchmark | ✓ direct + boundary + under-stress |
| NFR-020-02 | 4 | benchmark, integration | ✓ direct + boundary + noisy-context (+ harness self-test) |
| NFR-020-03 | 3 | benchmark, integration | ✓ direct + boundary + blast-radius |
| NFR-020-04 | 5 | security, inter-service | ✓ direct + boundary + adversarial |
| NFR-020-05 | 5 | integration | ✓ direct + fuzz + concurrency + idempotency |
| NFR-020-06 | 4 | unit, integration | ✓ direct + boundary + failure |
| US-020-01 | 3 (incl. manual-e2e) | e2e, benchmark, manual | ✓ |
| US-020-02 | 3 (incl. manual-e2e) | e2e, benchmark, manual | ✓ |
| US-020-03 | 3 | unit, integration (DFD-1) | ✓ |
| US-020-04 | 2 | performance, benchmark | ✓ |

- **Total: 91 tests** — 76 `planned` (automatable with fakes) and 15 `out-of-band (live model)`.
- Every `FR-020-01..10`, `NFR-020-01..06` and `US-020-01..04` has its own subsection and a *set* of
  tests at ≥2 levels; every user-facing story has a manual real-device E2E block (US-020-01,
  US-020-02, plus FR-020-01, FR-020-06, FR-020-07).
- Out-of-band tests are exactly those whose verdict depends on the **real model's judgement**
  (recall/precision corpora, live latency, live language parity) — a fake chat client can only prove
  wiring, never classification quality.
- Every TC id embeds and traces to exactly one `FR-`/`NFR-`/`US-` id.
