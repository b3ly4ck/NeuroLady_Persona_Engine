# Tests for F-008 — Appearance & Identity Consistency

- **Feature:** [F-008 — Appearance & Identity Consistency](../features/F-008-appearance-identity-consistency.md)
- **Approach:** 2–3 tests per requirement (3 for identity-fidelity/isolation/no-reference-safety),
  plus one **manual/GPU acceptance** per user story. The **conditioning policy** (reference
  selection, forwarding through the F-007 job, per-persona isolation, no-reference safe path,
  config-driven selection) is automatable; **identity fidelity** across settings / time /
  SFW↔intimate is judged by human acceptance + a face-similarity metric on generated images
  (GPU/benchmark), marked as such. Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-008-01 — Persona has reference image(s) under media/<slug>/reference/
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-01-01 | unit | happy | Given a provisioned persona; When inspected; Then face_ref (and optionally fullbody_ref) point under media/<slug>/reference/ | planned |
| TC-FR-008-01-02 | integration | mapping | Given uploaded references; When stored; Then the paths resolve to real files | planned |

### FR-008-02 — Every generation conditioned on the reference(s) (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-02-01 | integration | happy | Given a generation job; When built; Then the persona's reference is included as identity conditioning | planned |
| TC-FR-008-02-02 | benchmark | happy | Given generated output; When compared to the reference; Then it depicts the same person (face-similarity metric) | planned |
| TC-FR-008-02-03 | unit | mapping | Given the job payload; When inspected; Then the reference path is present and correct | planned |

### FR-008-03 — Configurable conditioning policy (reference per shot, strength)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-03-01 | unit | happy | Given a face-focused shot; When the policy runs; Then the face anchor is selected | planned |
| TC-FR-008-03-02 | unit | boundary | Given a full-body shot; When the policy runs; Then the full-body anchor is selected | planned |
| TC-FR-008-03-03 | integration | happy | Given an edited policy config; When applied; Then the new selection/strength takes effect, no code change | planned |

### FR-008-04 — Identity holds across varied settings within a day
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-04-01 | benchmark | happy | Given gym/cafe/home shots; When compared; Then all are the same person | planned |
| TC-FR-008-04-02 | manual | happy | Given a day's varied archive; When a reviewer scans it; Then it's obviously one consistent woman | planned |

### FR-008-05 — Identity holds across SFW↔intimate
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-05-01 | benchmark | happy | Given an SFW and an intimate shot; When compared; Then same face/body | planned |
| TC-FR-008-05-02 | manual | boundary | Given the two; When reviewed; Then no "body-double" effect | planned |

### FR-008-06 — Identity stable across days/weeks
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-06-01 | benchmark | happy | Given assets across many days; When compared; Then no identity drift | planned |
| TC-FR-008-06-02 | consistency | boundary | Given the same reference over time; When conditioning runs; Then the anchor is unchanged | planned |

### FR-008-07 — Strict per-persona isolation (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-07-01 | integration | happy | Given two personas; When each generates; Then each job uses only its own reference | planned |
| TC-FR-008-07-02 | security | negative | Given the roster; When jobs run; Then no persona's reference is used for another | planned |
| TC-FR-008-07-03 | benchmark | negative | Given two personas' outputs; When compared; Then no identity blur/mixing | planned |

### FR-008-08 — No-reference behavior defined and safe (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-08-01 | unit | empty | Given a persona with no reference; When generation is requested; Then it is skipped or uses a config placeholder | planned |
| TC-FR-008-08-02 | integration | negative | Given no reference; When run; Then no wrong-identity image is published as hers | planned |

### FR-008-09 — References authored via Persona Studio
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-09-01 | integration | happy | Given a Studio upload; When provisioned; Then face_ref/fullbody_ref are wired | planned |
| TC-FR-008-09-02 | unit | negative | Given F-008 code; When inspected; Then it consumes references, doesn't capture them | planned |

### FR-008-10 — Conditioning through the fixed F-007 job contract (model-agnostic)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-008-10-01 | integration | happy | Given the job contract; When conditioning is applied; Then it rides in the job payload, not model glue | planned |
| TC-FR-008-10-02 | integration | consistency | Given an A→B model swap; When jobs run; Then identity conditioning still applies unchanged | planned |

---

## Non-functional requirements

### NFR-008-01 — Identity fidelity (CRITICAL, human/metric-judged)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-01-01 | benchmark | happy | Given a labeled set; When measured; Then same-person rate ≥ target (face+body) | planned |
| TC-NFR-008-01-02 | manual | happy | Given generated photos; When a reviewer checks the face; Then it's clearly her | planned |
| TC-NFR-008-01-03 | benchmark | boundary | Given hard angles/lighting; When measured; Then fidelity stays above threshold | planned |

### NFR-008-02 — Consistency across settings
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-02-01 | benchmark | boundary | Given varied backgrounds/poses; When measured; Then same-person holds | planned |

### NFR-008-03 — Consistency over time
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-03-01 | benchmark | boundary | Given dated archives; When compared; Then no drift over time | planned |

### NFR-008-04 — Per-persona isolation provable (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-04-01 | security | negative | Given many personas; When probed; Then no cross-persona identity contamination | planned |

### NFR-008-05 — Model-agnostic conditioning
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-05-01 | integration | consistency | Given A↔B; When conditioned; Then identity holds via the fixed contract | planned |

### NFR-008-06 — Realism preserved alongside identity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-06-01 | manual | happy | Given conditioned output; When reviewed; Then it's both her and realistic (no waxy "same-face" artifact) | planned |

### NFR-008-07 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-008-07-01 | integration | happy | Given edited ref-selection/strength config; When applied; Then honored without a code change | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-008-01-01** — A8: compare varied shots; obviously the same woman. planned
- **TC-US-008-02-01** — A3: over weeks, her face/figure stay exactly consistent. planned
- **TC-US-008-03-01** — B1: upload references in Studio; every shot is that exact woman. planned
- **TC-US-008-04-01** — operator: across the 10-persona roster, each stays distinctly herself. planned
- **TC-US-008-05-01** — A3/A8: intimate shots are the same girl as her SFW photos. planned

## Coverage summary
FR-008-01..10 (10) + NFR-008-01..07 (7) + US-008-01..05 (5) — all covered; identity-fidelity TCs
are benchmark/human-judged (marked). Every TC id traces to its FR/NFR/US id.
