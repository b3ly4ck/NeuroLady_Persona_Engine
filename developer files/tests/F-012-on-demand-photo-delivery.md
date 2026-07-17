# Tests for F-012 — On-Demand Photo Delivery

- **Feature:** [F-012 — On-Demand Photo Delivery](../features/F-012-on-demand-photo-delivery.md)
- **Approach:** 2–3 tests per requirement (3 for no-repeat/hot-path-free/pacing), plus one
  manual/GPU acceptance per user story. Selection, per-user no-repeat, slot fallback, hot-path-free
  delivery, caption request, relationship pacing/gating, intimate routing, graceful exhaustion,
  proactive-share pacing, send recording, and config weighting are automatable with fakes; **real
  context-fit quality** is human-judged (marked). Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-012-01 — Context-matched selection from today's archive
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-01-01 | integration | happy | Given a photo request + current slot; When selecting; Then a matching archive asset is chosen | automated |
| TC-FR-012-01-02 | unit | mapping | Given context (time/activity); When matched; Then meta tags drive selection | automated |

### FR-012-02 — Per-user sent history, never resend (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-02-01 | integration | happy | Given asset X already sent; When re-requested; Then X is excluded | automated |
| TC-FR-012-02-02 | integration | boundary | Given all seen but one; When requested; Then the last unseen is chosen | automated |
| TC-FR-012-02-03 | unit | negative | Given the send log; When selection runs; Then seen assets are filtered out | automated |

### FR-012-03 — Prefer closest slot match with fallback
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-03-01 | unit | happy | Given exact slot match available; When selecting; Then it is preferred | automated |
| TC-FR-012-03-02 | unit | boundary | Given no exact match; When selecting; Then a sensible nearest slot is chosen | automated |

### FR-012-04 — No hot-path generation (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-04-01 | integration | happy | Given a request; When served; Then only a lookup+send occurs (no generation call) | automated |
| TC-FR-012-04-02 | unit | negative | Given the delivery path; When traced; Then no image-model invocation | automated |
| TC-FR-012-04-03 | benchmark | perf | Given delivery; When timed; Then latency ≈ DB lookup, not generation | skip (out-of-band) |

### FR-012-05 — Caption in her voice
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-05-01 | integration | happy | Given a delivered photo; When sent; Then a persona-voice caption accompanies it | automated |
| TC-FR-012-05-02 | unit | mapping | Given caption authoring; When invoked; Then it routes through F-002/F-003, not F-012 | automated |

### FR-012-06 — Paced/gated by relationship stage
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-06-01 | integration | happy | Given a new-user stage; When photos are spam-requested; Then pacing limits apply | automated |
| TC-FR-012-06-02 | integration | boundary | Given a bonded stage; When requested; Then sharing is freer | automated |

### FR-012-07 — Intimate requests routed to F-014 gate
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-07-01 | unit | happy | Given an intimate request; When classified; Then it routes to F-014, not the SFW archive | automated |
| TC-FR-012-07-02 | unit | negative | Given the SFW path; When run; Then it never serves an intimate asset | automated |

### FR-012-08 — Graceful in-voice degrade when nothing fits
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-08-01 | integration | empty | Given an exhausted archive; When requested; Then an in-voice deflection, no error | automated |
| TC-FR-012-08-02 | unit | negative | Given no fit; When degrading; Then never a placeholder or a repeat | automated |

### FR-012-09 — Proactive sharing when it fits + pacing allows
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-09-01 | integration | happy | Given conversation matches her activity + pacing OK; When she shares; Then a fitting unsent asset is sent unprompted | automated |
| TC-FR-012-09-02 | unit | boundary | Given pacing not allowed; When evaluated; Then no proactive share | automated |

### FR-012-10 — Delivery via Media path, send recorded
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-10-01 | integration | happy | Given a delivery; When completed; Then the send (user/asset/time) is recorded | automated |
| TC-FR-012-10-02 | unit | mapping | Given delivery; When traced; Then it uses the §3.6 Media path | automated |

### FR-012-11 — Config-driven selection/pacing/caption
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-11-01 | integration | happy | Given edited match-weight/frequency config; When applied; Then honored, no code change | automated |

---

## Non-functional requirements

### NFR-012-01 — Instant delivery (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-01-01 | benchmark | perf | Given delivery; When timed; Then p95 well under the reply budget | skip (out-of-band) |
| TC-NFR-012-01-02 | integration | perf | Given a request; When served; Then it is a lookup+send, no gen | automated |

### NFR-012-02 — No repeats (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-02-01 | integration | negative | Given many requests; When served; Then no asset repeats for the user | automated |

### NFR-012-03 — Context fit
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-03-01 | manual | happy | Given delivered photos; When reviewed; Then they fit the current time/activity | skip (human-judged) |

### NFR-012-04 — Pacing correctness
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-04-01 | integration | negative | Given a new user; When spamming requests; Then per-stage caps hold | automated |

### NFR-012-05 — Graceful exhaustion
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-05-01 | integration | empty | Given exhaustion; When requested; Then in-voice degrade, no error | automated |

### NFR-012-06 — Per-user isolation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-06-01 | integration | negative | Given user A's history; When user B selects; Then B is unaffected | automated |

### NFR-012-07 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-07-01 | integration | happy | Given edited weighting/caps; When applied; Then honored, no code change | automated |

### NFR-012-08 — Safety (SFW path never serves intimate)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-08-01 | unit | negative | Given an ambiguous request; When classified; Then it defaults to SFW/gate-routed, never leaks intimate | automated |

---

## User-story acceptance (manual/GPU)
- **TC-US-012-01-01** — asks for a pic → gets a fitting one instantly. skip (manual/GPU)
- **TC-US-012-02-01** — she shares a fitting photo unprompted. skip (manual/GPU)
- **TC-US-012-03-01** — no photo ever repeats. skip (manual/GPU)
- **TC-US-012-04-01** — photo matches the time/activity. skip (manual/GPU)
- **TC-US-012-05-01** — operator: instant + relationship-paced, no spam. skip (manual/GPU)

## Coverage summary
FR-012-01..11 (11) + NFR-012-01..08 (8) + US-012-01..05 (5) — all covered; context-fit quality TC is
human-judged (marked). Every TC id traces to its FR/NFR/US id.
