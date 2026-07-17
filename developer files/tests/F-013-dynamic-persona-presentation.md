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

---

## User-story acceptance (manual/GPU)
- **TC-US-013-01-01** — first-timer feels she's alive right now → converts to chat. skip (human/GPU)
- **TC-US-013-02-01** — greeting matches time of day. skip (human/GPU)
- **TC-US-013-03-01** — presentation feels different each open. skip (human/GPU)
- **TC-US-013-04-01** — welcome photo is her and matches the narrated moment. skip (human/GPU)
- **TC-US-013-05-01** — B1: each persona's welcome expresses her character. skip (human/GPU)

## Coverage summary
FR-013-01..11 (11) + NFR-013-01..08 (8) + US-013-01..05 (5) — all covered; coherence/identity TCs are
human/GPU-judged (marked). Every TC id traces to its FR/NFR/US id.
