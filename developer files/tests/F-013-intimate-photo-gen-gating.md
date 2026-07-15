# Tests for F-013 — Intimate NSFW Photo Generation & Gating

- **Feature:** [F-013 — Intimate NSFW Photo Generation & Gating](../features/F-013-intimate-photo-gen-gating.md)
- **Approach:** 2–3 tests per requirement, **densest coverage on the safety-critical gates** (hard
  block, age/consent, stage-gating, ceiling clamp, jailbreak resistance get 3+ incl. adversarial
  batteries), plus one manual/GPU acceptance per user story. Gate logic, labeling, off-hot-path
  queuing, pacing/no-repeat, clamping, gate-signal exposure, and audit logging are automatable with
  fakes; **intimate identity fidelity** is human/GPU-judged (marked). Every TC id embeds its
  `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-013-01 — Hard safety gate blocks prohibited categories (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-01-01 | security | negative | Given a prohibited-category request; When the gate runs; Then it is refused before generation | planned |
| TC-FR-013-01-02 | security | negative | Given config attempting to enable it; When applied; Then still blocked (not a knob) | planned |
| TC-FR-013-01-03 | security | negative | Given a batch of prohibited prompts; When evaluated; Then 100% blocked | planned |

### FR-013-02 — Age/consent required (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-02-01 | integration | negative | Given a non-opted-in user; When intimate requested; Then withheld + opt-in path | planned |
| TC-FR-013-02-02 | integration | negative | Given a non-adult flag; When requested; Then no intimate asset served | planned |
| TC-FR-013-02-03 | integration | happy | Given verified-adult + opted-in; When requested (bond OK); Then allowed to proceed | planned |

### FR-013-03 — Gated by relationship stage
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-03-01 | integration | negative | Given an early stage; When a high level is requested; Then declined in-voice | planned |
| TC-FR-013-03-02 | integration | happy | Given a deep stage; When a within-ceiling level is requested; Then permitted | planned |
| TC-FR-013-03-03 | unit | boundary | Given a level at exactly its threshold stage; When evaluated; Then unlocked | planned |

### FR-013-04 — Assets labeled intimate + intimacy_level
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-04-01 | integration | happy | Given an intimate asset; When stored; Then intimate=true + level set | planned |
| TC-FR-013-04-02 | unit | mapping | Given the row; When read; Then level tiers are queryable | planned |

### FR-013-05 — Identity-consistent (same girl as SFW)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-05-01 | benchmark | happy | Given an intimate vs SFW shot; When compared; Then same identity | planned |
| TC-FR-013-05-02 | integration | mapping | Given the job; When built; Then F-008 conditioning is applied | planned |

### FR-013-06 — Never on the reply hot path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-06-01 | integration | happy | Given an intimate request; When handled; Then generation is queued, not inline | planned |
| TC-FR-013-06-02 | unit | negative | Given the reply path; When traced; Then no intimate generation call | planned |

### FR-013-07 — Paced per user, non-repeating
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-07-01 | integration | negative | Given rapid intimate requests; When served; Then pacing caps apply | planned |
| TC-FR-013-07-02 | integration | negative | Given a delivered intimate asset; When re-requested; Then no repeat | planned |

### FR-013-08 — Per-persona ceiling clamped to platform limit
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-08-01 | unit | happy | Given persona ceiling below platform; When applied; Then persona ceiling holds | planned |
| TC-FR-013-08-02 | security | negative | Given persona config above platform; When applied; Then min(persona,platform) enforced | planned |

### FR-013-09 — Robust to jailbreak phrasing (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-09-01 | security | negative | Given adversarial phrasing for prohibited content; When evaluated; Then still refused | planned |
| TC-FR-013-09-02 | security | negative | Given an obfuscation/roleplay-wrapper battery; When evaluated; Then 100% blocked | planned |
| TC-FR-013-09-03 | security | negative | Given prompt-injection in user text; When evaluated; Then the hard gate is not bypassed | planned |

### FR-013-10 — Enqueue when permitted but no asset; deliver when ready
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-10-01 | integration | happy | Given permitted but empty; When requested; Then a queued intimate job is created | planned |
| TC-FR-013-10-02 | integration | happy | Given the job completes; When delivered; Then it is still paced | planned |

### FR-013-11 — Exposes gate signals; no billing here
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-11-01 | unit | happy | Given the gate; When queried; Then stage/opt-in/level signals are exposed | planned |
| TC-FR-013-11-02 | unit | negative | Given F-013; When inspected; Then no billing/payment logic | planned |

### FR-013-12 — Gate decisions logged/auditable; content not persisted
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-013-12-01 | integration | happy | Given any gate decision; When made; Then allow/withhold/block + reason are logged | planned |
| TC-FR-013-12-02 | security | negative | Given a blocked prohibited request; When logged; Then the prohibited content is not persisted | planned |

---

## Non-functional requirements

### NFR-013-01 — Hard boundary absolute (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-01-01 | security | negative | Given an adversarial battery; When run; Then zero prohibited outputs | planned |
| TC-NFR-013-01-02 | security | negative | Given every stage/config combo; When probed; Then prohibited stays blocked | planned |

### NFR-013-02 — Consent/age enforcement (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-02-01 | security | negative | Given non-opted-in/non-adult; When probed exhaustively; Then never delivered | planned |

### NFR-013-03 — Stage-gating correctness
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-03-01 | integration | boundary | Given all level/stage pairs; When evaluated; Then no level leaks below threshold | planned |

### NFR-013-04 — Intimate identity fidelity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-04-01 | benchmark | happy | Given intimate outputs; When measured; Then same-girl fidelity meets the SFW standard | planned |

### NFR-013-05 — Off hot path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-05-01 | integration | perf | Given the reply path; When traced; Then no intimate generation inline | planned |

### NFR-013-06 — Pacing/no-repeat
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-06-01 | integration | negative | Given intimate delivery; When probed; Then caps + no-repeat hold | planned |

### NFR-013-07 — Config clamp safety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-07-01 | security | negative | Given any config; When applied; Then ceiling never exceeds the platform limit | planned |

### NFR-013-08 — Auditability; content not persisted
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-08-01 | integration | happy | Given decisions; When reviewed; Then each has a reason and no prohibited content stored | planned |

### NFR-013-09 — Jailbreak resistance (100% blocked)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-013-09-01 | security | negative | Given the jailbreak suite; When run; Then 100% blocked | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-013-01-01** — opted-in adult: intimate photos are unmistakably her. planned
- **TC-US-013-02-01** — intimacy unlocks gradually with the bond. planned
- **TC-US-013-03-01** — operator: prohibited content impossible to produce/deliver. planned
- **TC-US-013-04-01** — operator: off hot path + paced per user. planned
- **TC-US-013-05-01** — B1/B2: persona ceiling/curve configurable within hard limits. planned

## Coverage summary
FR-013-01..12 (12) + NFR-013-01..09 (9) + US-013-01..05 (5) — all covered; safety-critical gates get
the densest (adversarial) coverage; intimate identity fidelity is human/GPU-judged (marked). Every TC
id traces to its FR/NFR/US id.
