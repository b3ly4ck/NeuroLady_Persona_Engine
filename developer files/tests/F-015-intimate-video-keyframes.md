# Tests for F-015 — Intimate Video Keyframes

- **Feature:** [F-015 — Intimate Video Keyframes](../features/F-015-intimate-video-keyframes.md)
- **Approach:** 2–3 tests per requirement (3 on the inherited hard gate), plus one manual/GPU
  acceptance per user story. Gate reuse (incl. adversarial hard-block battery), start/end prompt
  authoring, linked-pair storage + intimate labeling, off-hot-path queuing, ceiling clamp inheritance,
  forward-compatible pairing contract, and audit logging are automatable with fakes; **pair identity
  and motion coherence** are human/GPU-judged (marked). Video synthesis is deferred and not tested
  here. Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-015-01 — Reuses the identical F-014 gate (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-01-01 | integration | happy | Given a keyframe request; When gated; Then it runs the same F-014 gate | planned |
| TC-FR-015-01-02 | security | negative | Given a prohibited request; When gated; Then blocked before any frame | planned |
| TC-FR-015-01-03 | integration | negative | Given non-opted-in/early-stage; When requested; Then withheld exactly as F-014 | planned |

### FR-015-02 — Authors a coherent start/end motion span
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-02-01 | unit | happy | Given a keyframe request; When authored; Then a start-frame and an end-frame prompt are produced | planned |
| TC-FR-015-02-02 | unit | boundary | Given the two prompts; When compared; Then same setting/outfit, plausible pose delta | planned |

### FR-015-03 — Both frames same girl + same scene via F-008/F-009
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-03-01 | integration | mapping | Given the jobs; When built; Then both use F-009 conditioning + the same scene | planned |
| TC-FR-015-03-02 | benchmark | happy | Given the pair; When compared; Then same identity | planned |

### FR-015-04 — Stored as linked keyframe pair with intimate labeling
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-04-01 | integration | happy | Given a stored pair; When read; Then kind=video_keyframe, intimate=true + level | planned |
| TC-FR-015-04-02 | unit | mapping | Given meta_json; When parsed; Then first/last + link id pair the two rows | planned |

### FR-015-05 — Night-batch/queued, never inline
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-05-01 | integration | happy | Given a keyframe request; When handled; Then generation is queued | planned |
| TC-FR-015-05-02 | unit | negative | Given the reply path; When traced; Then no keyframe generation inline | planned |

### FR-015-06 — Ceiling clamp applies to keyframes
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-06-01 | unit | negative | Given a low-ceiling persona; When above-ceiling keyframes requested; Then not produced | planned |
| TC-FR-015-06-02 | security | negative | Given any config; When applied; Then keyframe intimacy never exceeds the platform limit | planned |

### FR-015-07 — Keyframe-ready / video-model-agnostic
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-07-01 | unit | mapping | Given the stored pair; When validated; Then it fits a generic i2v (first,last) input contract | planned |
| TC-FR-015-07-02 | integration | consistency | Given a future i2v runner shape; When fed the pair; Then no schema change is needed | planned |

### FR-015-08 — Video synthesis explicitly out of scope; no blocking
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-08-01 | unit | happy | Given no video model present; When keyframes are produced; Then F-015 completes (stores pair, stops) | planned |
| TC-FR-015-08-02 | unit | negative | Given F-015; When inspected; Then it contains no video-synthesis dependency | planned |

### FR-015-09 — Gate decisions logged; content not persisted
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-015-09-01 | integration | happy | Given a keyframe gate decision; When made; Then it is logged via the F-014 audit path | planned |
| TC-FR-015-09-02 | security | negative | Given a blocked request; When logged; Then prohibited content is not persisted | planned |

---

## Non-functional requirements

### NFR-015-01 — Inherited hard boundary (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-01-01 | security | negative | Given the F-014 adversarial battery; When run against keyframes; Then zero prohibited outputs | planned |
| TC-NFR-015-01-02 | security | negative | Given every stage/config combo; When probed; Then prohibited stays blocked | planned |

### NFR-015-02 — Identity across the pair
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-02-01 | benchmark | happy | Given the pair; When measured; Then both are the same girl (F-009 standard) | planned |

### NFR-015-03 — Motion coherence
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-03-01 | manual | happy | Given the pair; When reviewed; Then it reads as one continuous moment | planned |

### NFR-015-04 — Off hot path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-04-01 | integration | perf | Given the reply path; When traced; Then no keyframe generation inline | planned |

### NFR-015-05 — Ceiling clamp safety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-05-01 | security | negative | Given any config; When applied; Then keyframe intimacy stays within limits | planned |

### NFR-015-06 — Keyframe-ready / forward-compatible
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-06-01 | unit | mapping | Given the pairing contract; When validated; Then a future i2v model consumes it with no schema change | planned |

### NFR-015-07 — Auditability
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-015-07-01 | integration | happy | Given decisions; When reviewed; Then each is logged, no prohibited content stored | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-015-01-01** — clips (when enabled) are clearly her and smoothly coherent. planned
- **TC-US-015-02-01** — operator: video inherits the identical F-014 gate, no looser path. planned
- **TC-US-015-03-01** — operator: keyframe-ready now, video switchable later, no redesign. planned
- **TC-US-015-04-01** — B1/B2: persona ceiling respected for keyframes. planned

## Coverage summary
FR-015-01..09 (9) + NFR-015-01..07 (7) + US-015-01..04 (4) — all covered; pair identity/motion
coherence TCs are human/GPU-judged, video synthesis deferred (marked). Every TC id traces to its
FR/NFR/US id.
