# Tests for F-013 — Dynamic Persona Presentation

- **Feature:** [F-013 — Dynamic Persona Presentation](../features/F-013-dynamic-persona-presentation.md)
- **Approach:** 2–3 tests per requirement (3 for instant/single-message/hot-path-free), plus one
  manual/GPU acceptance per user story. Greeting composition, archive photo selection, single-message
  delivery, cross-open variation, SFW-only, hot-path-free, empty-archive fallback, per-persona voice,
  and the F-001 boundary are automatable with fakes; **greeting↔photo coherence and identity** are
  human/GPU-judged (marked). Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-013-01 — Time/activity-aware greeting in her voice
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-01-01 | integration | happy | Given a midday cafe slot; When opened; Then the greeting reflects that moment + time | passing |
| TC-FR-013-01-02 | unit | mapping | Given F-006 state; When composing; Then slot + local time drive the text | passing |

### FR-013-02 — Paired with a fitting archive photo
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-02-01 | integration | happy | Given today's archive; When opened; Then a context-matching photo is selected | passing |
| TC-FR-013-02-02 | unit | mapping | Given selection; When run; Then it uses F-012-style tag matching | passing |

### FR-013-03 — One combined message (no double nudge)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-03-01 | integration | happy | Given a greeting; When sent; Then exactly one message with photo + keyboard | passing |
| TC-FR-013-03-02 | unit | negative | Given delivery; When traced; Then no separate follow-up "say something" message | passing |
| TC-FR-013-03-03 | integration | boundary | Given a keyboard is needed; When sent; Then it rides on the same message | passing |

### FR-013-04 — Varies across opens (not a fixed promo)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-04-01 | integration | happy | Given opens at different times; When composed; Then greeting/photo differ | passing |
| TC-FR-013-04-02 | unit | boundary | Given two opens same slot; When composed; Then still not byte-identical promo (varies within reason) | passing |

### FR-013-05 — Identity-consistent + coherent photo
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-05-01 | benchmark | happy | Given the welcome photo; When checked; Then it is the same girl (F-009) | skip (human/GPU) |
| TC-FR-013-05-02 | integration | happy | Given the greeting mentions a place; When the photo is chosen; Then tags match the moment | passing |

### FR-013-06 — Welcome photo always SFW
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-06-01 | unit | negative | Given any persona; When the welcome photo is chosen; Then it is SFW | passing |
| TC-FR-013-06-02 | integration | negative | Given the archive; When selecting for welcome; Then intimate assets are excluded | passing |

### FR-013-07 — No hot-path generation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-07-01 | integration | happy | Given a persona open; When the card is built; Then no image generation call occurs | passing |
| TC-FR-013-07-02 | benchmark | perf | Given the open; When timed; Then latency ≈ lookup, not generation | skip (human/GPU) |

### FR-013-08 — Graceful empty-archive fallback
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-08-01 | integration | empty | Given no archive photo; When opened; Then a config-default greeting shows, no error | passing |
| TC-FR-013-08-02 | unit | negative | Given empty archive; When composing; Then never a broken image | passing |

### FR-013-09 — Honors per-persona character
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-09-01 | unit | happy | Given a shy vs bubbly persona config; When composed; Then greetings differ in tone | passing |
| TC-FR-013-09-02 | integration | happy | Given edited voice config; When applied; Then greeting tone changes, no code change | passing |

### FR-013-10 — Content-only; navigation stays F-001
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-10-01 | unit | mapping | Given F-013; When inspected; Then it composes content, not gallery/nav | passing |
| TC-FR-013-10-02 | integration | happy | Given F-001 selection; When completed; Then F-013 supplies the post-selection card | passing |

### FR-013-11 — Hands off to normal chat after greeting
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-11-01 | integration | happy | Given the greeting sent; When the user replies; Then control is F-002/F-003 | passing |

### FR-013-12 — Gallery photo sourced from the archive (ISS-002)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-12-01 | integration | happy | Given a persona with an archive; When provisioning runs; Then gallery_photo_ref points at a real SFW frame from it | planned |
| TC-FR-013-12-02 | unit | negative | Given the archive; When a card photo is chosen; Then an intimate asset is never selected | planned |

---

## Non-functional requirements

### NFR-013-01 — Instant (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-01-01 | benchmark | perf | Given an open; When timed; Then no generation latency | skip (human/GPU) |
| TC-NFR-013-01-02 | integration | perf | Given the card; When built; Then it is lookup + compose only | passing |

### NFR-013-02 — Freshness/variety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-02-01 | integration | boundary | Given repeated opens; When compared; Then the card visibly varies | passing |

### NFR-013-03 — Coherence (greeting ↔ photo)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-03-01 | manual | happy | Given the card; When reviewed; Then text and photo agree | skip (human/GPU) |

### NFR-013-04 — Identity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-04-01 | benchmark | happy | Given the welcome photo; When measured; Then it is her (F-009) | skip (human/GPU) |

### NFR-013-05 — Single-message UX
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-05-01 | integration | negative | Given the greeting; When counted; Then exactly one outbound message | passing |

### NFR-013-06 — Graceful fallback
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-06-01 | integration | empty | Given empty archive; When opened; Then no error/broken image | passing |

### NFR-013-07 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-07-01 | integration | happy | Given edited greeting style; When applied; Then honored, no code change | passing |

### NFR-013-08 — Safety (SFW entry)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-08-01 | unit | negative | Given the entry moment; When a photo is chosen; Then never an intimate asset | passing |

### FR-013-13 — Opener is LLM-composed (ISS-012)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-13-01 | unit | happy | Given a persona and a fake chat client returning a scripted opener; When the resume opener is composed; Then the delivered text IS the model's output, not `resume_opener` | implemented |
| TC-FR-013-13-02 | unit | happy | Given a fake chat client; When the selection greeting is composed with it; Then the model's text is used, not `compose_greeting`'s template | implemented |
| TC-FR-013-13-03 | unit | context | Given a session whose last messages mention a specific topic; When the resume opener is composed; Then those recent messages are present in the prompt sent to the model (it can reference where they left off) | implemented |
| TC-FR-013-13-04 | unit | freshness | Given a real-entropy (temperature) client; When two openers are composed; Then the compose path requests a fresh generation each time (not a cached constant) | implemented |
| TC-FR-013-13-05 | integration | e2e | Given the real resume handler path with a fake chat client; When the user re-enters an active chat; Then the message sent to Telegram is the composed opener, exactly one message, with the keyboard | implemented |

### FR-013-14 — Degrade, never silence, never a leak (ISS-012)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-14-01 | unit | error | Given a chat client that raises; When the opener is composed; Then the static/template fallback is returned and nothing raises | implemented |
| TC-FR-013-14-02 | unit | empty | Given a chat client that returns "" (or whitespace); When composed; Then the fallback is used, never an empty message | implemented |
| TC-FR-013-14-03 | unit | negative | Given a model reply that appends `<<MEDIA:photo:sfw>>` or jargon; When composed; Then the signal/jargon is stripped before the opener is returned | implemented |
| TC-FR-013-14-04 | integration | error | Given the resume handler with a failing chat client; When the user re-enters; Then he still gets a greeting (the static `resume_opener`), never silence | implemented |

### FR-013-15 — Shape (ISS-012)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-15-01 | unit | happy | Given a composed opener; When inspected; Then it is a single message (no forced multi-paragraph wall) in the persona's language | implemented |
| TC-FR-013-15-02 | unit | mapping | Given an EN persona and a RU persona; When each opener is composed; Then the instruction pins the persona's language | implemented |

---

## User-story acceptance (manual/GPU)
- **TC-US-013-01-01** — first-timer feels she's alive right now → converts to chat. skip (human/GPU)
- **TC-US-013-02-01** — greeting matches time of day. skip (human/GPU)
- **TC-US-013-03-01** — presentation feels different each open. skip (human/GPU)
- **TC-US-013-04-01** — welcome photo is her and matches the narrated moment. skip (human/GPU)
- **TC-US-013-05-01** — B1: each persona's welcome expresses her character. skip (human/GPU)

## Coverage summary
FR-013-01..15 (incl. FR-013-13/14/15, ISS-012) + NFR-013-01..08 (8) + US-013-01..05 (5) — all covered;
coherence/identity TCs are human/GPU-judged (marked). Every TC id traces to its FR/NFR/US id.
