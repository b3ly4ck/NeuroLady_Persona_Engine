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

### FR-012-12 — Caption in the persona's language (ISS-003)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-12-01 | unit | happy | Given a ru persona; When the caption is requested; Then the request carries her language and asks for a Russian caption | planned |
| TC-FR-012-12-02 | unit | mapping | Given an en persona; When requested; Then English is asked for | planned |
| TC-FR-012-12-03 | regression | negative | **ISS-003:** given a ru persona; When a caption is produced; Then it is not English | out-of-band (live model) |

### FR-012-13 — Paced photo send (ISS-004)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-13-01 | unit | happy | Given a photo delivery; When it runs; Then upload_photo action precedes a bounded delay before the send | planned |
| TC-FR-012-13-02 | unit | boundary | Given the configured budget; When timed; Then the delay stays within min/max bounds | planned |
| TC-FR-012-13-03 | unit | consistency | Given NFR-012-01; When measured; Then no GENERATION happens on the hot path (instant lookup) while the user-visible send is still paced | planned |

### FR-012-14 — Delivery returns the delivered asset's metadata (ISS-006)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-14-01 | integration | happy | Given an asset tagged bedroom/evening/lying on the bed; When it is delivered; Then the result exposes its background/location/activity/pose/time-of-day | automated |
| TC-FR-012-14-02 | integration | negative | Given an exhausted archive / a paced user / an intimate request; When delivery returns; Then the metadata is empty (no scene claimed for a photo that was never sent) | automated |
| TC-FR-012-14-03 | unit | security | Given meta_json also holds the generation prompt and seed; When the result is built; Then only the five slot fields are exposed | automated |

### FR-012-15 — Bounded, per-user recent-sends lookup (ISS-006)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-012-15-01 | integration | happy | Given three photos sent at different times; When the lookup runs; Then they come back newest-first with their slot fields and sent_at | automated |
| TC-FR-012-15-02 | integration | boundary | Given ten sends, some older than the window; When the lookup runs; Then at most the configured count is returned and out-of-window sends are excluded | automated |
| TC-FR-012-15-03 | integration | security | Given user A's and user B's sends of the same persona; When A's lookup runs; Then only A's sends appear (NFR-012-06) | automated |

### FR-012-16 — Scene description served to context (ISS-008)
| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-012-16-01 | unit | happy | Delivery result carries it | Given an asset with a scene description; When delivered; Then the result meta includes it | implemented |
| TC-FR-012-16-02 | integration | happy | recent_sends carries it | Given a sent asset; When recent_sends runs; Then the descriptor includes the scene description | implemented |
| TC-FR-012-16-03 | integration | regression | **ISS-008 pinned** | Given a photo was sent; When the context block is built; Then it states what is VISIBLE, not just `на фоне: home` | implemented |
| TC-FR-012-16-04 | unit | empty | Older assets fall back | Given an asset without a description; When served; Then the slot fields are used and nothing breaks | implemented |

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

### NFR-012-09 — Metadata is served, not just stored (ISS-006)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-012-09-01 | integration | regression | **ISS-006:** given a photo delivered through the Telegram media hook; When the result comes back; Then it carries the asset's scene metadata (stored-and-never-read is the defect) | automated |
| TC-NFR-012-09-02 | integration | boundary | Given a user with far more sends than the configured cap; When the lookup runs; Then the returned set stays bounded (the consumer can never grow the prompt without limit) | automated |

---

## User-story acceptance (manual/GPU)
- **TC-US-012-01-01** — asks for a pic → gets a fitting one instantly. skip (manual/GPU)
- **TC-US-012-02-01** — she shares a fitting photo unprompted. skip (manual/GPU)
- **TC-US-012-03-01** — no photo ever repeats. skip (manual/GPU)
- **TC-US-012-04-01** — photo matches the time/activity. skip (manual/GPU)
- **TC-US-012-05-01** — operator: instant + relationship-paced, no spam. skip (manual/GPU)

## Coverage summary
FR-012-01..15 (15) + NFR-012-01..09 (9) + US-012-01..05 (5) — all covered; context-fit quality TC is
human-judged (marked). Every TC id traces to its FR/NFR/US id. The ISS-006 additions
(FR-012-14/15, NFR-012-09) are runnable in `tests/test_iss_006_media_context.py` and execute the real
delivery path — never source-text assertions (the ISS-004 lesson).
