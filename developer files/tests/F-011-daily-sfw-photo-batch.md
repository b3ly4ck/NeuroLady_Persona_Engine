# Tests for F-011 — Daily SFW Photo Batch

- **Feature:** [F-011 — Daily SFW Photo Batch](../features/F-011-daily-sfw-photo-batch.md)
- **Approach:** 2–3 tests per requirement (3 for GPU-exclusivity/idempotency/coverage), plus one
  manual/GPU acceptance per user story. Orchestration behavior (slot derivation, shot-set
  commissioning, dating/slot-tagging, idempotency/resume, failure degrade, config budgets, handoff
  gating, observability) is automatable against a **fake F-008 engine**; **window throughput** and
  **real freshness/coverage on GPU** are benchmark-measured (marked). Every TC id embeds its
  `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-011-01 — Nightly batch runs only in the media window
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-01-01 | unit | happy | Given the night window; When triggered; Then the batch runs | planned |
| TC-FR-011-01-02 | unit | negative | Given the day window; When triggered; Then the batch does not run | planned |

### FR-011-02 — Reads tomorrow's plan → day's slots
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-02-01 | integration | happy | Given tomorrow's plan; When the batch starts; Then it derives the day's slots | planned |
| TC-FR-011-02-02 | unit | boundary | Given a plan with few slots; When derived; Then only those slots are covered | planned |

### FR-011-03 — Configurable SFW shot set per slot (many/day)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-03-01 | unit | happy | Given N=6; When a slot is processed; Then 6 shots are commissioned | planned |
| TC-FR-011-03-02 | integration | happy | Given all slots; When done; Then total = slots × N photos for the day | planned |
| TC-FR-011-03-03 | unit | boundary | Given N=1; When processed; Then exactly 1 shot/slot | planned |

### FR-011-04 — Dispatches via F-010 → F-008 with F-009
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-04-01 | integration | happy | Given a slot; When commissioned; Then an F-008 job with an F-010 prompt + F-009 ref is enqueued | planned |
| TC-FR-011-04-02 | unit | negative | Given F-011; When inspected; Then it does not render images itself | planned |

### FR-011-05 — Assets dated and slot-tagged
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-05-01 | integration | happy | Given a stored asset; When read; Then date + time_of_day/activity/location tags are set | planned |
| TC-FR-011-05-02 | unit | mapping | Given meta_json; When parsed; Then slot tags are selectable | planned |

### FR-011-06 — Idempotent and resumable (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-06-01 | integration | happy | Given a completed slot; When re-run; Then it is skipped (no duplicate) | planned |
| TC-FR-011-06-02 | integration | recovery | Given a mid-run crash; When restarted; Then remaining shots complete, done ones untouched | planned |
| TC-FR-011-06-03 | unit | boundary | Given an idempotency key per slot/plan; When re-run; Then keys prevent duplication | planned |

### FR-011-07 — Graceful degrade on single-shot failure
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-07-01 | integration | error | Given one shot fails; When the batch continues; Then the rest complete | planned |
| TC-FR-011-07-02 | unit | error | Given a failure; When handled; Then it is logged/retried, not fatal | planned |

### FR-011-08 — Completes before day window, no hot-path gen
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-08-01 | integration | happy | Given a finished batch; When morning chat happens; Then a fresh archive exists, no gen on hot path | planned |
| TC-FR-011-08-02 | benchmark | perf | Given the roster; When timed; Then the batch fits the nightly window | planned |

### FR-011-09 — Configurable per-persona shot budget
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-09-01 | unit | happy | Given persona A=3/slot, B=6/slot; When run; Then each honored | planned |
| TC-FR-011-09-02 | integration | happy | Given edited budget config; When applied; Then honored, no code change | planned |

### FR-011-10 — Coordinates GPU handoff with chat model
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-10-01 | integration | happy | Given the handoff mechanism; When the batch starts; Then it requests chat unload first | planned |
| TC-FR-011-10-02 | integration | recovery | Given batch end; When done; Then it signals chat reload | planned |

### FR-011-11 — Progress/outcome observable
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-011-11-01 | unit | happy | Given a run; When it completes; Then planned/queued/done/failed counts are logged | planned |

---

## Non-functional requirements

### NFR-011-01 — Freshness (same-day)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-01-01 | integration | happy | Given today's archive; When dates are checked; Then assets are same-day, not recycled | planned |

### NFR-011-02 — Coverage (no empty slots)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-02-01 | integration | boundary | Given a completed batch; When slots are checked; Then each has ≥ its minimum | planned |
| TC-NFR-011-02-02 | benchmark | happy | Given a real run; When reviewed; Then the day is covered morning→night | planned |

### NFR-011-03 — GPU exclusivity (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-03-01 | integration | negative | Given the chat model resident; When the batch is asked to run; Then it refuses/waits | planned |
| TC-NFR-011-03-02 | integration | happy | Given the handoff; When the batch runs; Then the chat model is unloaded | planned |

### NFR-011-04 — Resumability without duplication/corruption
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-04-01 | integration | recovery | Given repeated interruptions; When resumed; Then no duplicates/corruption | planned |

### NFR-011-05 — Throughput within the window
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-05-01 | benchmark | perf | Given the roster + distilled steps; When timed; Then within the nightly budget | planned |

### NFR-011-06 — Config-driven budgets
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-06-01 | integration | happy | Given edited budgets; When applied; Then honored, no code change | planned |

### NFR-011-07 — Per-persona isolation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-07-01 | integration | error | Given persona A fails; When the batch runs; Then persona B still completes | planned |

### NFR-011-08 — Observability
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-011-08-01 | unit | happy | Given a run; When inspected; Then per-run metrics/durations/failures are logged | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-011-01-01** — fresh same-day photos every day, no recycling. planned
- **TC-US-011-02-01** — coverage morning→night; a fitting shot at any hour. planned
- **TC-US-011-03-01** — operator: generation runs overnight on the freed GPU. planned
- **TC-US-011-04-01** — operator: crash mid-batch resumes cleanly. planned
- **TC-US-011-05-01** — B1: per-persona shots/slot configurable. planned

## Coverage summary
FR-011-01..11 (11) + NFR-011-01..08 (8) + US-011-01..05 (5) — all covered; throughput/real-coverage
TCs are benchmark-measured (marked). Every TC id traces to its FR/NFR/US id.
