# F-017 — Daily-Life Video Clips — test specification

Mirror of `developer files/features/F-017-daily-life-video-clips.md`. Every TC id embeds the
`FR-`/`NFR-`/`US-` id it verifies. F-017 is a **planner/catalog client** of the F-016 engine, so
nearly everything is **automated** with the F-016 job API stubbed — the only GPU-real cases are the
end-to-end `benchmark` acceptance rows.

## Functional

### FR-017-01 — Nightly planner selects clip-worthy slots within budget
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-01-01 | unit | happy | HH:MM slots from tomorrow's plan are parsed and ranked | automated |
| TC-FR-017-01-02 | unit | boundary | At most `budget` slots selected; distinct activities preferred | automated |
| TC-FR-017-01-03 | unit | negative | No parseable slots → no jobs, logged skip (degrade) | automated |

### FR-017-02 — SFW prompt + conditioning still per slot
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-02-01 | unit | happy | Each selected slot gets an authored SFW motion prompt tagged with time/activity | automated |
| TC-FR-017-02-02 | unit | mapping | A matching SFW still (F-009 ref / F-011 archive photo) is attached | automated |
| TC-FR-017-02-03 | unit | negative | Slot with no available still → skipped cleanly, not submitted | automated |

### FR-017-03 — Jobs go through the F-016 API unchanged (no second engine)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-03-01 | unit | mapping | Submitted payloads match the F-016 job schema, intimate=false | automated |
| TC-FR-017-03-02 | unit | security | The planner performs no model load / GPU call of its own | automated |

### FR-017-04 — MEDIA_ASSET catalog rows
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-04-01 | integration | happy | A produced clip yields kind=video, intimate=false, slot/date-tagged row | automated |
| TC-FR-017-04-02 | integration | mapping | The row records activity/location + source still reference | automated |

### FR-017-05 — Strictly SFW by construction (CRITICAL)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-05-01 | unit | security | Payloads never carry intimacy fields | automated |
| TC-FR-017-05-02 | unit | error | An intimate-drifting prompt is rejected at planning | automated |
| TC-FR-017-05-03 | unit | security | Rejection never reroutes into the gated F-016 intimate path | automated |

### FR-017-06 — Idempotent & resumable
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-06-01 | integration | idempotency | Re-run skips completed MED-ids | automated |
| TC-FR-017-06-02 | integration | idempotency | Crashed night resume → no duplicates in the archive | automated |

### FR-017-07 — Per-slot degrade
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-07-01 | integration | error | One failed slot recorded + skipped; batch continues | automated |
| TC-FR-017-07-02 | integration | error | Failure leaves no partial catalog row | automated |

### FR-017-08 — Schedule-aware (night video slot)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-08-01 | unit | happy | The planner runs only inside the configured night window | automated |
| TC-FR-017-08-02 | unit | boundary | Outside the window → no jobs submitted | automated |

### FR-017-09 — Auditable provenance chain
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-09-01 | unit | happy | Slot choice, prompt, job result, timing recorded per clip | automated |
| TC-FR-017-09-02 | consistency | mapping | plan→prompt→job→asset chain is reconstructible | automated |

### FR-017-10 — Config-driven volume
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-017-10-01 | unit | happy | Budget/preferences/window come from config, no code change | automated |

## Non-functional

### NFR-017-01 — Throughput fits the window
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-017-01-01 | unit | boundary | Overcommitted config (budget×roster×90s > window) is refused + logged at planning | automated |
| TC-NFR-017-01-02 | benchmark | load | A real roster night fits the video slot | benchmark |

### NFR-017-02 — No hot-path work
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-017-02-01 | unit | mapping | No reply path invokes planning/generation | automated |

### NFR-017-03 — Tag consistency / atomic catalog
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-017-03-01 | integration | persistence | Crash mid-catalog → row+file consistent or absent | automated |
| TC-NFR-017-03-02 | consistency | mapping | Clip tags always equal the source plan slot | automated |

### NFR-017-04 — Isolation
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-017-04-01 | unit | security | services/bot does not import planner/runner internals | automated |

### NFR-017-05 — Roster scale
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-017-05-01 | integration | error | One persona's bad plan doesn't stop the others | automated |

## User-story acceptance (manual / benchmark)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-US-017-01-01 | e2e | manual | She shows a moment of her day in motion, and it lands | benchmark |
| TC-US-017-02-01 | e2e | manual | Clip matches her stated activity/time under skeptic probing | benchmark |
| TC-US-017-03-01 | benchmark | manual | The night produced SFW clips on the same engine (no extra runner) | benchmark |

## Coverage summary
- **Functional FR-017-01..10:** 22 automated TCs (3 for the critical SFW-by-construction FR-017-05).
- **Non-functional NFR-017-01..05:** 7 TCs (6 automated, 1 benchmark).
- **User stories:** 3 manual/benchmark acceptance TCs.
- **Grand total: 32 enumerated tests** — proportionate to a planner/catalog feature that reuses the
  F-016 engine (the engine's own behavior is covered by the F-016 spec).
