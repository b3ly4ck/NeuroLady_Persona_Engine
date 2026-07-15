# Tests for F-010 — Daily SFW Photo Batch

- **Feature:** [F-010 — Daily SFW Photo Batch](../features/F-010-daily-sfw-photo-batch.md)
- **Approach:** 2–3 tests per requirement (3 for GPU-exclusivity/idempotency/coverage), plus one
  manual/GPU acceptance per user story. Orchestration behavior (slot derivation, shot-set
  commissioning, dating/slot-tagging, idempotency/resume, failure degrade, config budgets, handoff
  gating, observability) is automatable against a **fake F-007 engine**; **window throughput** and
  **real freshness/coverage on GPU** are benchmark-measured (marked). Every TC id embeds its
  `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-010-01 — Nightly batch runs only in the media window
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-01-01 | unit | happy | Given the night window; When triggered; Then the batch runs | planned |
| TC-FR-010-01-02 | unit | negative | Given the day window; When triggered; Then the batch does not run | planned |

### FR-010-02 — Reads tomorrow's plan → day's slots
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-02-01 | integration | happy | Given tomorrow's plan; When the batch starts; Then it derives the day's slots | planned |
| TC-FR-010-02-02 | unit | boundary | Given a plan with few slots; When derived; Then only those slots are covered | planned |

### FR-010-03 — Configurable SFW shot set per slot (many/day)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-03-01 | unit | happy | Given N=6; When a slot is processed; Then 6 shots are commissioned | planned |
| TC-FR-010-03-02 | integration | happy | Given all slots; When done; Then total = slots × N photos for the day | planned |
| TC-FR-010-03-03 | unit | boundary | Given N=1; When processed; Then exactly 1 shot/slot | planned |

### FR-010-04 — Dispatches via F-009 → F-007 with F-008
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-04-01 | integration | happy | Given a slot; When commissioned; Then an F-007 job with an F-009 prompt + F-008 ref is enqueued | planned |
| TC-FR-010-04-02 | unit | negative | Given F-010; When inspected; Then it does not render images itself | planned |

### FR-010-05 — Assets dated and slot-tagged
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-05-01 | integration | happy | Given a stored asset; When read; Then date + time_of_day/activity/location tags are set | planned |
| TC-FR-010-05-02 | unit | mapping | Given meta_json; When parsed; Then slot tags are selectable | planned |

### FR-010-06 — Idempotent and resumable (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-06-01 | integration | happy | Given a completed slot; When re-run; Then it is skipped (no duplicate) | planned |
| TC-FR-010-06-02 | integration | recovery | Given a mid-run crash; When restarted; Then remaining shots complete, done ones untouched | planned |
| TC-FR-010-06-03 | unit | boundary | Given an idempotency key per slot/plan; When re-run; Then keys prevent duplication | planned |

### FR-010-07 — Graceful degrade on single-shot failure
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-07-01 | integration | error | Given one shot fails; When the batch continues; Then the rest complete | planned |
| TC-FR-010-07-02 | unit | error | Given a failure; When handled; Then it is logged/retried, not fatal | planned |

### FR-010-08 — Completes before day window, no hot-path gen
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-08-01 | integration | happy | Given a finished batch; When morning chat happens; Then a fresh archive exists, no gen on hot path | planned |
| TC-FR-010-08-02 | benchmark | perf | Given the roster; When timed; Then the batch fits the nightly window | planned |

### FR-010-09 — Configurable per-persona shot budget
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-09-01 | unit | happy | Given persona A=3/slot, B=6/slot; When run; Then each honored | planned |
| TC-FR-010-09-02 | integration | happy | Given edited budget config; When applied; Then honored, no code change | planned |

### FR-010-10 — Coordinates GPU handoff with chat model
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-10-01 | integration | happy | Given the handoff mechanism; When the batch starts; Then it requests chat unload first | planned |
| TC-FR-010-10-02 | integration | recovery | Given batch end; When done; Then it signals chat reload | planned |

### FR-010-11 — Progress/outcome observable
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-11-01 | unit | happy | Given a run; When it completes; Then planned/queued/done/failed counts are logged | planned |

---

## Non-functional requirements

### NFR-010-01 — Freshness (same-day)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-01-01 | integration | happy | Given today's archive; When dates are checked; Then assets are same-day, not recycled | planned |

### NFR-010-02 — Coverage (no empty slots)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-02-01 | integration | boundary | Given a completed batch; When slots are checked; Then each has ≥ its minimum | planned |
| TC-NFR-010-02-02 | benchmark | happy | Given a real run; When reviewed; Then the day is covered morning→night | planned |

### NFR-010-03 — GPU exclusivity (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-03-01 | integration | negative | Given the chat model resident; When the batch is asked to run; Then it refuses/waits | planned |
| TC-NFR-010-03-02 | integration | happy | Given the handoff; When the batch runs; Then the chat model is unloaded | planned |

### NFR-010-04 — Resumability without duplication/corruption
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-04-01 | integration | recovery | Given repeated interruptions; When resumed; Then no duplicates/corruption | planned |

### NFR-010-05 — Throughput within the window
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-05-01 | benchmark | perf | Given the roster + distilled steps; When timed; Then within the nightly budget | planned |

### NFR-010-06 — Config-driven budgets
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-06-01 | integration | happy | Given edited budgets; When applied; Then honored, no code change | planned |

### NFR-010-07 — Per-persona isolation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-07-01 | integration | error | Given persona A fails; When the batch runs; Then persona B still completes | planned |

### NFR-010-08 — Observability
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-08-01 | unit | happy | Given a run; When inspected; Then per-run metrics/durations/failures are logged | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-010-01-01** — fresh same-day photos every day, no recycling. planned
- **TC-US-010-02-01** — coverage morning→night; a fitting shot at any hour. planned
- **TC-US-010-03-01** — operator: generation runs overnight on the freed GPU. planned
- **TC-US-010-04-01** — operator: crash mid-batch resumes cleanly. planned
- **TC-US-010-05-01** — B1: per-persona shots/slot configurable. planned

## Coverage summary
FR-010-01..11 (11) + NFR-010-01..08 (8) + US-010-01..05 (5) — all covered; throughput/real-coverage
TCs are benchmark-measured (marked). Every TC id traces to its FR/NFR/US id.
