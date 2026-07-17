# Tests for F-014 — Intimate NSFW Photo Generation & Gating

- **Feature:** [F-014 — Intimate NSFW Photo Generation & Gating](../features/F-014-intimate-photo-gen-gating.md)
- **Approach:** 2–3 tests per requirement, **densest coverage on the safety-critical gates** (hard
  block, age/consent, stage-gating, ceiling clamp, jailbreak resistance get 3+ incl. adversarial
  batteries), plus one manual/GPU acceptance per user story. Gate logic, labeling, off-hot-path
  queuing, pacing/no-repeat, clamping, gate-signal exposure, and audit logging are automatable with
  fakes; **intimate identity fidelity** is human/GPU-judged (marked). Every TC id embeds its
  `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-014-01 — Hard safety gate blocks prohibited categories (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-01-01 | security | negative | Given a prohibited-category request; When the gate runs; Then it is refused before generation | pass |
| TC-FR-014-01-02 | security | negative | Given config attempting to enable it; When applied; Then still blocked (not a knob) | pass |
| TC-FR-014-01-03 | security | negative | Given a batch of prohibited prompts; When evaluated; Then 100% blocked | pass |

### FR-014-02 — Age/consent required (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-02-01 | integration | negative | Given a non-opted-in user; When intimate requested; Then withheld + opt-in path | pass |
| TC-FR-014-02-02 | integration | negative | Given a non-adult flag; When requested; Then no intimate asset served | pass |
| TC-FR-014-02-03 | integration | happy | Given verified-adult + opted-in; When requested (bond OK); Then allowed to proceed | pass |

### FR-014-03 — Gated by relationship stage
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-03-01 | integration | negative | Given an early stage; When a high level is requested; Then declined in-voice | pass |
| TC-FR-014-03-02 | integration | happy | Given a deep stage; When a within-ceiling level is requested; Then permitted | pass |
| TC-FR-014-03-03 | unit | boundary | Given a level at exactly its threshold stage; When evaluated; Then unlocked | pass |

### FR-014-04 — Assets labeled intimate + intimacy_level
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-04-01 | integration | happy | Given an intimate asset; When stored; Then intimate=true + level set | pass |
| TC-FR-014-04-02 | unit | mapping | Given the row; When read; Then level tiers are queryable | pass |

### FR-014-05 — Identity-consistent (same girl as SFW)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-05-01 | benchmark | happy | Given an intimate vs SFW shot; When compared; Then same identity | skip (GPU/human) |
| TC-FR-014-05-02 | integration | mapping | Given the job; When built; Then F-009 conditioning is applied | pass |

### FR-014-06 — Never on the reply hot path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-06-01 | integration | happy | Given an intimate request; When handled; Then generation is queued, not inline | pass |
| TC-FR-014-06-02 | unit | negative | Given the reply path; When traced; Then no intimate generation call | pass |

### FR-014-07 — Paced per user, non-repeating
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-07-01 | integration | negative | Given rapid intimate requests; When served; Then pacing caps apply | pass |
| TC-FR-014-07-02 | integration | negative | Given a delivered intimate asset; When re-requested; Then no repeat | pass |

### FR-014-08 — Per-persona ceiling clamped to platform limit
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-08-01 | unit | happy | Given persona ceiling below platform; When applied; Then persona ceiling holds | pass |
| TC-FR-014-08-02 | security | negative | Given persona config above platform; When applied; Then min(persona,platform) enforced | pass |

### FR-014-09 — Robust to jailbreak phrasing (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-09-01 | security | negative | Given adversarial phrasing for prohibited content; When evaluated; Then still refused | pass |
| TC-FR-014-09-02 | security | negative | Given an obfuscation/roleplay-wrapper battery; When evaluated; Then 100% blocked | pass |
| TC-FR-014-09-03 | security | negative | Given prompt-injection in user text; When evaluated; Then the hard gate is not bypassed | pass |

### FR-014-10 — Enqueue when permitted but no asset; deliver when ready
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-10-01 | integration | happy | Given permitted but empty; When requested; Then a queued intimate job is created | pass |
| TC-FR-014-10-02 | integration | happy | Given the job completes; When delivered; Then it is still paced | pass |

### FR-014-11 — Exposes gate signals; no billing here
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-11-01 | unit | happy | Given the gate; When queried; Then stage/opt-in/level signals are exposed | pass |
| TC-FR-014-11-02 | unit | negative | Given F-014; When inspected; Then no billing/payment logic | pass |

### FR-014-12 — Gate decisions logged/auditable; content not persisted
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-014-12-01 | integration | happy | Given any gate decision; When made; Then allow/withhold/block + reason are logged | pass |
| TC-FR-014-12-02 | security | negative | Given a blocked prohibited request; When logged; Then the prohibited content is not persisted | pass |

---

## Non-functional requirements

### NFR-014-01 — Hard boundary absolute (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-01-01 | security | negative | Given an adversarial battery; When run; Then zero prohibited outputs | pass |
| TC-NFR-014-01-02 | security | negative | Given every stage/config combo; When probed; Then prohibited stays blocked | pass |

### NFR-014-02 — Consent/age enforcement (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-02-01 | security | negative | Given non-opted-in/non-adult; When probed exhaustively; Then never delivered | pass |

### NFR-014-03 — Stage-gating correctness
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-03-01 | integration | boundary | Given all level/stage pairs; When evaluated; Then no level leaks below threshold | pass |

### NFR-014-04 — Intimate identity fidelity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-04-01 | benchmark | happy | Given intimate outputs; When measured; Then same-girl fidelity meets the SFW standard | skip (GPU/human) |

### NFR-014-05 — Off hot path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-05-01 | integration | perf | Given the reply path; When traced; Then no intimate generation inline | pass |

### NFR-014-06 — Pacing/no-repeat
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-06-01 | integration | negative | Given intimate delivery; When probed; Then caps + no-repeat hold | pass |

### NFR-014-07 — Config clamp safety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-07-01 | security | negative | Given any config; When applied; Then ceiling never exceeds the platform limit | pass |

### NFR-014-08 — Auditability; content not persisted
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-08-01 | integration | happy | Given decisions; When reviewed; Then each has a reason and no prohibited content stored | pass |

### NFR-014-09 — Jailbreak resistance (100% blocked)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-014-09-01 | security | negative | Given the jailbreak suite; When run; Then 100% blocked | pass |

---

## User-story acceptance (manual/GPU)
- **TC-US-014-01-01** — opted-in adult: intimate photos are unmistakably her. skip (GPU/human)
- **TC-US-014-02-01** — intimacy unlocks gradually with the bond. pass
- **TC-US-014-03-01** — operator: prohibited content impossible to produce/deliver. pass
- **TC-US-014-04-01** — operator: off hot path + paced per user. pass
- **TC-US-014-05-01** — B1/B2: persona ceiling/curve configurable within hard limits. pass

## Coverage summary
FR-014-01..12 (12) + NFR-014-01..09 (9) + US-014-01..05 (5) — all covered; safety-critical gates get
the densest (adversarial) coverage; intimate identity fidelity is human/GPU-judged (marked). Every TC
id traces to its FR/NFR/US id.
