# F-007 — Life Engine Scheduler — test specification

Mirror of `developer files/features/F-007-life-engine-scheduler.md`. Every TC id embeds the
`FR-`/`NFR-`/`US-` id it verifies. Automated tests drive the per-persona **tick** with a fake chat
client and a **controlled clock** (a fixed `now_utc`) so due-detection, idempotency, the compression
cascade, goal/future updates, and degrade are all fast and deterministic — no live model.

## Functional

### FR-007-01 — Autonomous scheduler runs the loop on a cadence
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-01-01 | integration | happy | Scheduler tick iterates the active roster | Given active personas; When one scheduler pass runs; Then each persona's tick is invoked | automated |
| TC-FR-007-01-02 | unit | happy | A tick is callable without any manual step wiring | Given a persona; When run_tick is called; Then it completes and reports what ran | automated |

### FR-007-02 — Tick runs only the due steps at the persona's local time (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-02-01 | integration | happy | Local morning ⇒ plan is authored | Given local morning and no plan today; When a tick runs; Then a DAILY_PLAN is stored | automated |
| TC-FR-007-02-02 | integration | happy | Local end-of-day ⇒ reflection is authored | Given local end-of-day with a plan and no reflection; When a tick runs; Then a daily REFLECTION is stored | automated |
| TC-FR-007-02-03 | integration | negative | Mid-afternoon ⇒ nothing due, no LLM call | Given neither morning nor end-of-day; When a tick runs; Then no plan/reflection is created and no LLM call is made | automated |

### FR-007-03 — Idempotent per period (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-03-01 | integration | idempotency | Two morning ticks ⇒ one plan | Given local morning; When two ticks run; Then exactly one DAILY_PLAN exists for today | automated |
| TC-FR-007-03-02 | integration | idempotency | Two end-of-day ticks ⇒ one reflection | Given local end-of-day; When two ticks run; Then exactly one daily REFLECTION exists for today | automated |
| TC-FR-007-03-03 | integration | boundary | New local day ⇒ a fresh plan is allowed | Given a plan for yesterday and it is a new local morning; When a tick runs; Then a plan for the new date is created | automated |

### FR-007-04 — Compression cascade after reflection (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-04-01 | integration | happy | 7 daily reflections compress into a weekly layer | Given 7 uncompressed daily reflections; When the cascade runs; Then a weekly BIOGRAPHY_LAYER is stored | automated |
| TC-FR-007-04-02 | integration | boundary | Below threshold ⇒ no compression | Given fewer than 7 daily reflections; When the cascade runs; Then no weekly layer is created | automated |
| TC-FR-007-04-03 | integration | happy | Cascade climbs multiple levels when thresholds met | Given enough weeks to also make a month; When the cascade runs; Then both weekly and monthly layers appear | automated |

### FR-007-05 — Goal update applied on cadence
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-05-01 | integration | happy | Goal-update adds/completes goals | Given an LLM goal-update; When applied; Then goals are added/completed accordingly | automated |
| TC-FR-007-05-02 | integration | negative | No update on empty/failed goal step | Given the goal step returns nothing; When applied; Then goals are unchanged | automated |

### FR-007-06 — Future-self re-authored (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-06-01 | integration | happy | Future-update rewrites the projections | Given seeded projections and an LLM future-update; When it runs; Then the FUTURE_PROJECTION contents change | automated |
| TC-FR-007-06-02 | integration | idempotency | Still one row per horizon after update | Given a future-update; When applied; Then there is exactly one row per horizon | automated |
| TC-FR-007-06-03 | integration | negative | Failed future step keeps last good projections | Given the future step returns nothing; When applied; Then existing projections are unchanged | automated |

### FR-007-07 — Off the reply hot path
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-07-01 | unit | mapping | Tick is separate from handle_turn | Given the reply path; When inspected; Then it does not invoke plan/reflect/compress inline | automated |
| TC-FR-007-07-02 | integration | happy | A reply succeeds while a tick is in flight | Given a tick running; When a reply is produced; Then it completes independently | automated |

### FR-007-08 — Degrade on failure (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-08-01 | integration | error | LLM-down tick writes nothing, does not raise | Given the chat client fails; When a tick runs; Then no plan/reflection is written and no exception escapes | automated |
| TC-FR-007-08-02 | integration | error | One persona's failure doesn't stop the roster | Given persona A fails; When the scheduler pass runs; Then persona B is still ticked | automated |

### FR-007-09 — Runs across the roster, each on its own timezone
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-09-01 | integration | happy | Two zones ⇒ due independently | Given personas in Moscow and New York at a UTC instant that is morning in one only; When a pass runs; Then only the due persona is planned | automated |
| TC-FR-007-09-02 | integration | boundary | Whole active roster is visited | Given N active personas; When a pass runs; Then all N are ticked | automated |

### FR-007-10 — Auditable autonomous changes
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-10-01 | integration | happy | Plan/reflection/layer record prompt_version + source | Given autonomous steps ran; When rows are read; Then prompt_version and source_period are populated | automated |
| TC-FR-007-10-02 | consistency | mapping | Compressed layer links to its source period | Given a weekly layer; When audited; Then its source_period references the compressed dailies | automated |

### FR-007-11 — Config-driven cadence
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-11-01 | unit | happy | Schedule hours come from config | Given a config with custom morning/end-of-day hours; When due-detection runs; Then it honors them | automated |
| TC-FR-007-11-02 | unit | boundary | Compression ratios come from config | Given custom ratios; When should_compress runs; Then the new thresholds apply | automated |

### FR-007-12 — On-demand run for one persona
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-007-12-01 | integration | happy | run_persona_now forces all steps regardless of hour | Given mid-afternoon; When run_persona_now is called; Then plan/reflection/goals/future all run | automated |
| TC-FR-007-12-02 | integration | idempotency | On-demand stays idempotent per period | Given run_persona_now twice; When counted; Then still one plan and one reflection for the day | automated |

## Non-functional

### NFR-007-01 — No reply starvation
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-01-01 | performance | boundary | Reply path independent of the tick | Given the tick is a background task; When a reply runs; Then it does not await the tick | automated |
| TC-NFR-007-01-02 | load | boundary | Full-roster pass does not block replies | Given a roster pass; When replies occur; Then they are not starved | planned |

### NFR-007-02 — Timezone/DST correctness
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-02-01 | unit | boundary | Due-detection correct across a DST change | Given a DST transition; When due-detection runs; Then the local hour is still correct | automated |
| TC-NFR-007-02-02 | unit | boundary | Correct for different zones at one instant | Given one UTC instant; When evaluated per zone; Then each persona's local hour is right | automated |

### NFR-007-04 — Idempotent & safe under repeats
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-04-01 | consistency | idempotency | Repeated ticks converge | Given many repeated ticks in one window; When counted; Then state is unchanged after the first | automated |
| TC-NFR-007-04-02 | consistency | error | Restart mid-window doesn't duplicate | Given a restart during the morning window; When a tick runs again; Then no duplicate plan is created | automated |

### NFR-007-05 — Survives restart
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-05-01 | persistence | happy | Progression persists across a restart | Given autonomous progress; When services restart; Then plans/reflections/layers/goals/future remain | automated |

### NFR-007-06 — Degrade, don't crash the loop
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-06-01 | error | negative | A raising persona tick is caught by the scheduler | Given a persona whose tick raises; When the pass runs; Then the scheduler catches it and continues | automated |

### NFR-007-07 — Observability
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-007-07-01 | unit | happy | Tick reports what ran/skipped | Given a tick; When it completes; Then it returns a summary of actions taken | automated |

## User-story acceptance (manual real-device / multi-day)

| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-US-007-01-01 | e2e | manual | Over days, her plan/activity/biography visibly advance | planned |
| TC-US-007-02-01 | e2e | manual | Progression stays consistent under skeptic probing | planned |
| TC-US-007-05-01 | e2e | manual | On-demand run moves a persona forward for a demo | planned |

## Coverage summary
- **Functional FR-007-01..12:** 27 automated TCs (2–3 each; 3 for the critical due-detection,
  idempotency, cascade, future-self, degrade).
- **Non-functional NFR-007-01..08:** 9 TCs (8 automated, 1 load planned).
- **User stories:** 3 manual acceptance TCs.
- **Grand total: 39 enumerated tests** — proportionate to a focused driver feature.
- Every TC id embeds the `FR-`/`NFR-`/`US-` id it verifies.
