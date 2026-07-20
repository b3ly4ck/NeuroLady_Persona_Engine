# Tests for F-009 — Appearance & Identity Consistency

- **Feature:** [F-009 — Appearance & Identity Consistency](../features/F-009-appearance-identity-consistency.md)
- **Approach:** 2–3 tests per requirement (3 for identity-fidelity/isolation/no-reference-safety),
  plus one **manual/GPU acceptance** per user story. The **conditioning policy** (reference
  selection, forwarding through the F-008 job, per-persona isolation, no-reference safe path,
  config-driven selection) is automatable; **identity fidelity** across settings / time /
  SFW↔intimate is judged by human acceptance + a face-similarity metric on generated images
  (GPU/benchmark), marked as such. Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-009-01 — Persona has reference image(s) under media/<slug>/reference/
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-01-01 | unit | happy | Given a provisioned persona; When inspected; Then face_ref (and optionally fullbody_ref) point under media/<slug>/reference/ | implemented |
| TC-FR-009-01-02 | integration | mapping | Given uploaded references; When stored; Then the paths resolve to real files | implemented |

### FR-009-02 — Every generation conditioned on the reference(s) (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-02-01 | integration | happy | Given a generation job; When built; Then the persona's reference is included as identity conditioning | implemented |
| TC-FR-009-02-02 | benchmark | happy | Given generated output; When compared to the reference; Then it depicts the same person (face-similarity metric) | out-of-band (GPU) |
| TC-FR-009-02-03 | unit | mapping | Given the job payload; When inspected; Then the reference path is present and correct | implemented |

### FR-009-03 — Configurable conditioning policy (reference per shot, strength)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-03-01 | unit | happy | Given a face-focused shot; When the policy runs; Then the face anchor is selected | implemented |
| TC-FR-009-03-02 | unit | boundary | Given a full-body shot; When the policy runs; Then the full-body anchor is selected | implemented |
| TC-FR-009-03-03 | integration | happy | Given an edited policy config; When applied; Then the new selection/strength takes effect, no code change | implemented |

### FR-009-04 — Identity holds across varied settings within a day
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-04-01 | benchmark | happy | Given gym/cafe/home shots; When compared; Then all are the same person | out-of-band (GPU) |
| TC-FR-009-04-02 | manual | happy | Given a day's varied archive; When a reviewer scans it; Then it's obviously one consistent woman | out-of-band (manual) |
| TC-FR-009-04-03 | unit | happy | Given gym/cafe/home jobs; When the policy runs; Then all resolve to the same identity anchor (automatable core) | implemented |

### FR-009-05 — Identity holds across SFW↔intimate
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-05-01 | benchmark | happy | Given an SFW and an intimate shot; When compared; Then same face/body | out-of-band (GPU) |
| TC-FR-009-05-02 | manual | boundary | Given the two; When reviewed; Then no "body-double" effect | out-of-band (manual) |
| TC-FR-009-05-03 | unit | happy | Given an SFW vs an intimate job; When the policy runs; Then the same anchor conditions both (anchor is framing-driven, not intimacy-driven) | implemented |

### FR-009-06 — Identity stable across days/weeks
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-06-01 | benchmark | happy | Given assets across many days; When compared; Then no identity drift | out-of-band (GPU) |
| TC-FR-009-06-02 | consistency | boundary | Given the same reference over time; When conditioning runs; Then the anchor is unchanged | implemented |

### FR-009-07 — Strict per-persona isolation (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-07-01 | integration | happy | Given two personas; When each generates; Then each job uses only its own reference | implemented |
| TC-FR-009-07-02 | security | negative | Given the roster; When jobs run; Then no persona's reference is used for another | implemented |
| TC-FR-009-07-03 | benchmark | negative | Given two personas' outputs; When compared; Then no identity blur/mixing | out-of-band (GPU) |

### FR-009-08 — No-reference behavior defined and safe (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-08-01 | unit | empty | Given a persona with no reference; When generation is requested; Then it is skipped or uses a config placeholder | implemented |
| TC-FR-009-08-02 | integration | negative | Given no reference; When run; Then no wrong-identity image is published as hers (strict callers get a defined exception) | implemented |
| TC-FR-009-08-03 | unit | boundary | Given a full-body shot but only a face anchor; When the policy runs; Then it safely falls back to the face anchor (right identity), never nothing/wrong | implemented |

### FR-009-09 — References authored via Persona Studio
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-09-01 | integration | happy | Given a Studio upload; When provisioned; Then face_ref/fullbody_ref are wired | implemented |
| TC-FR-009-09-02 | unit | negative | Given F-009 code; When inspected; Then it consumes references, doesn't capture them | implemented |

### FR-009-10 — Conditioning through the fixed F-008 job contract (model-agnostic)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-10-01 | integration | happy | Given the job contract; When conditioning is applied; Then it rides in the job payload, not model glue | implemented |
| TC-FR-009-10-02 | integration | consistency | Given an A→B model swap; When jobs run; Then identity conditioning still applies unchanged | implemented |

### FR-009-11 — Multi-anchor conditioning: face + full-body, ordered (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-11-01 | unit | happy | Given a persona with face_ref AND fullbody_ref; When the policy selects; Then BOTH are returned, face first | implemented |
| TC-FR-009-11-02 | unit | boundary | Given only a face_ref; When selecting; Then exactly one reference is returned (no fabricated body anchor) | implemented |
| TC-FR-009-11-03 | unit | boundary | Given more anchors than the model limit (3); When selecting; Then the list is capped at 3, ordered by priority | implemented |

### FR-009-12 — Identity-preservation directive exposed (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-12-01 | unit | happy | Given one anchor; When the directive is built; Then it names Picture 1 and asserts preserving the exact face/features/body | implemented |
| TC-FR-009-12-02 | unit | happy | Given two anchors; When built; Then it names Picture 1 AND Picture 2 | implemented |
| TC-FR-009-12-03 | unit | negative | Given the directive; When inspected; Then it never yields a generic unbound subject ("a woman" alone) | implemented |

### FR-009-13 — Preserve, never describe
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-13-01 | unit | negative | Given the directive; When scanned; Then it contains no appearance descriptors (hair/eye colour, body type) | implemented |
| TC-FR-009-13-02 | unit | mapping | Given F-010's banned-vocabulary guard; When applied to a prompt opening with the directive; Then the directive is exempt and passes | implemented |

### FR-009-14 — Directive + ordering are model-agnostic
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-009-14-01 | unit | mapping | Given the built job; When inspected; Then directive rides in prompt text and anchors in ordered `references` (fixed contract only) | implemented |
| TC-FR-009-14-02 | integration | consistency | Given a backend swap; When jobs run; Then both the directive and the anchor order survive unchanged | implemented |

---

## Non-functional requirements

### NFR-009-01 — Identity fidelity (CRITICAL, human/metric-judged)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-01-01 | benchmark | happy | Given a labeled set; When measured; Then same-person rate ≥ target (face+body) | out-of-band (GPU) |
| TC-NFR-009-01-02 | manual | happy | Given generated photos; When a reviewer checks the face; Then it's clearly her | out-of-band (manual) |
| TC-NFR-009-01-03 | benchmark | boundary | Given hard angles/lighting; When measured; Then fidelity stays above threshold | out-of-band (GPU) |

### NFR-009-02 — Consistency across settings
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-02-01 | benchmark | boundary | Given varied backgrounds/poses; When measured; Then same-person holds | out-of-band (GPU) |

### NFR-009-03 — Consistency over time
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-03-01 | benchmark | boundary | Given dated archives; When compared; Then no drift over time | out-of-band (GPU) |

### NFR-009-04 — Per-persona isolation provable (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-04-01 | security | negative | Given many personas; When probed; Then no cross-persona identity contamination | implemented |

### NFR-009-05 — Model-agnostic conditioning
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-05-01 | integration | consistency | Given A↔B; When conditioned; Then identity holds via the fixed contract | implemented |

### NFR-009-06 — Realism preserved alongside identity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-06-01 | manual | happy | Given conditioned output; When reviewed; Then it's both her and realistic (no waxy "same-face" artifact) | out-of-band (manual) |

### NFR-009-07 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-009-07-01 | integration | happy | Given edited ref-selection/strength config (via env); When applied; Then honored without a code change | implemented |
| TC-NFR-009-07-02 | unit | boundary | Given the no-reference action is switched (skip↔placeholder) via config; When the policy runs; Then the behaviour follows config | implemented |

---

## User-story acceptance (manual/GPU)
- **TC-US-009-01-01** — A8: compare varied shots; obviously the same woman. out-of-band (manual/GPU)
- **TC-US-009-02-01** — A3: over weeks, her face/figure stay exactly consistent. out-of-band (manual/GPU)
- **TC-US-009-03-01** — B1: upload references in Studio; every shot is that exact woman. out-of-band (manual/GPU)
- **TC-US-009-04-01** — operator: across the 10-persona roster, each stays distinctly herself. out-of-band (manual/GPU)
- **TC-US-009-05-01** — A3/A8: intimate shots are the same girl as her SFW photos. out-of-band (manual/GPU)

## Coverage summary
FR-009-01..10 (10) + NFR-009-01..07 (7) + US-009-01..05 (5) — all covered. Runnable code lives in
`tests/test_f009_identity.py` (23 automatable tests pass; 18 GPU/manual TCs are explicit skips).
Supplementary automatable TCs added during implementation: TC-FR-009-04-03, TC-FR-009-05-03,
TC-FR-009-08-03, TC-NFR-009-07-02. Identity-fidelity TCs (same-person across settings / time /
SFW↔intimate) remain benchmark/human-judged (marked out-of-band). Every TC id traces to its
FR/NFR/US id.
