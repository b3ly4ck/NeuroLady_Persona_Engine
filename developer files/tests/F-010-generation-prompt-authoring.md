# Tests for F-010 — Generation Prompt Authoring

- **Feature:** [F-010 — Generation Prompt Authoring](../features/F-010-generation-prompt-authoring.md)
- **Approach:** 2–3 tests per requirement (3 for coherence/variety/safe-default), plus one
  manual/GPU acceptance per user story. Prompt-level behavior (reading life state, prompt structure,
  no-identity-restatement, N-angle variety, style honoring, time/location coherence in the *text*,
  provenance logging, safe default, job-contract conformance) is automatable; **image-level coherence
  and visual variety** are human/GPU-judged (marked). Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-010-01 — Reads Life Engine state as scene source
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-01-01 | unit | happy | Given a current slot (morning run); When authoring; Then the prompt draws scene/activity from it | planned |
| TC-FR-010-01-02 | integration | happy | Given F-006 state; When a prompt is built; Then slot/mood/location are consumed | planned |

### FR-010-02 — Structured, model-ready prompt with realism cues + negatives
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-02-01 | unit | happy | Given any authored prompt; When inspected; Then it has scene+outfit+lighting+realism cues | planned |
| TC-FR-010-02-02 | unit | happy | Given any authored prompt; When inspected; Then a negative list is present | planned |
| TC-FR-010-02-03 | unit | mapping | Given the output; When parsed; Then fields map onto the F-008 job contract | planned |

### FR-010-03 — Prompt matches narrated day (coherence)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-03-01 | unit | happy | Given a "beach" slot; When authoring; Then the scene text is a beach | planned |
| TC-FR-010-03-02 | benchmark | happy | Given generated image; When reviewed; Then it depicts the narrated scene | planned |

### FR-010-04 — A slot expands to N distinct framings
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-04-01 | unit | happy | Given one slot, N=6; When authored; Then 6 prompts are produced | planned |
| TC-FR-010-04-02 | unit | boundary | Given the set; When compared; Then framings/angles differ (not duplicates) | planned |
| TC-FR-010-04-03 | unit | boundary | Given N configured to 3; When authored; Then exactly 3 are produced | planned |

### FR-010-05 — Does not restate/override identity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-05-01 | unit | negative | Given an authored prompt; When inspected; Then it has no hard identity descriptors that fight the reference | planned |
| TC-FR-010-05-02 | unit | happy | Given the prompt; When inspected; Then it describes scene/pose/camera only | planned |

### FR-010-06 — Honors persona visual style (config)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-06-01 | unit | happy | Given a warm-cozy style config; When authoring; Then palette/outfit reflect it | planned |
| TC-FR-010-06-02 | integration | happy | Given an edited style config; When applied; Then prompts change, no code change | planned |

### FR-010-07 — Time-of-day / location coherence in prompt
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-07-01 | unit | happy | Given a night slot; When authored; Then lighting reads night | planned |
| TC-FR-010-07-02 | unit | boundary | Given a morning trail slot; When authored; Then it isn't a midnight bar | planned |

### FR-010-08 — Prompt + source slot logged with the asset
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-08-01 | integration | happy | Given a generated asset; When provenance is read; Then the prompt + slot/seed are recorded | planned |
| TC-FR-010-08-02 | unit | mapping | Given meta_json; When parsed; Then prompt provenance fields are present | planned |

### FR-010-09 — Safe default when life state missing
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-09-01 | unit | empty | Given no current slot; When a prompt is requested; Then a config default scene is authored | planned |
| TC-FR-010-09-02 | unit | negative | Given empty life state; When authoring; Then no crash, coherent default | planned |

### FR-010-10 — Conforms to fixed F-008 job contract (model-agnostic)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-10-01 | unit | mapping | Given the authored output; When validated; Then it fits the job contract schema | planned |
| TC-FR-010-10-02 | integration | consistency | Given A↔B; When the same prompt is used; Then it is accepted by both runners | planned |

### FR-010-11 — Shot metadata carried into MEDIA_ASSET meta_json
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-11-01 | integration | happy | Given authored shot meta (pose/bg/location/activity/time); When stored via F-008; Then meta_json holds them | planned |
| TC-FR-010-11-02 | unit | mapping | Given the meta fields; When On-Demand (F-012) queries; Then they are selectable | planned |

---

## Non-functional requirements

### NFR-010-01 — Coherence (CRITICAL, human/GPU-judged)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-01-01 | benchmark | happy | Given labeled slot/photo pairs; When judged; Then match rate ≥ target | planned |
| TC-NFR-010-01-02 | manual | happy | Given narration + photo; When reviewed; Then they agree | planned |
| TC-NFR-010-01-03 | benchmark | boundary | Given unusual slots; When judged; Then coherence holds | planned |

### NFR-010-02 — Variety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-02-01 | unit | boundary | Given a slot's prompt set; When diversity is scored; Then framings are distinct | planned |
| TC-NFR-010-02-02 | manual | happy | Given the generated set; When reviewed; Then it looks like several real shots | planned |

### NFR-010-03 — Determinism/reproducibility
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-03-01 | unit | consistency | Given same slot + seed; When authored twice; Then identical prompts | planned |

### NFR-010-04 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-04-01 | integration | happy | Given edited style/N/negatives config; When applied; Then honored, no code change | planned |

### NFR-010-05 — Model-agnostic vocabulary
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-05-01 | integration | consistency | Given A↔B; When authored; Then the prompt is portable | planned |

### NFR-010-06 — Cheap to author (no heavy GPU)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-06-01 | unit | perf | Given authoring; When profiled; Then it is pure text composition, no model call | planned |

### NFR-010-07 — Safety-aware (SFW stays SFW)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-07-01 | unit | negative | Given SFW authoring; When inspected; Then no explicit vocabulary leaks in | planned |

---

## User-story acceptance (manual/GPU)
- **TC-US-010-01-01** — photo matches what she said she's doing. planned
- **TC-US-010-02-01** — photos read as candid phone snaps of her day. planned
- **TC-US-010-03-01** — a slot yields a few genuinely different angles. planned
- **TC-US-010-04-01** — B1: persona style tuning reflected in her photos. planned
- **TC-US-010-05-01** — operator: every asset traces to a logged prompt + slot. planned

## Coverage summary
FR-010-01..11 (11) + NFR-010-01..07 (7) + US-010-01..05 (5) — all covered; image-level coherence/
variety TCs are benchmark/human-judged (marked). Every TC id traces to its FR/NFR/US id.
