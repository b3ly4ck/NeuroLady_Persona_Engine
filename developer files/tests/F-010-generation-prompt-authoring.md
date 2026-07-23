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
| TC-FR-010-01-01 | unit | happy | Given a current slot (morning run); When authoring; Then the prompt draws scene/activity from it | pass |
| TC-FR-010-01-02 | integration | happy | Given F-006 state; When a prompt is built; Then slot/mood/location are consumed | pass |

### FR-010-02 — Structured, model-ready prompt with realism cues + negatives
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-02-01 | unit | happy | Given any authored prompt; When inspected; Then it has scene+outfit+lighting+realism cues | pass |
| TC-FR-010-02-02 | unit | happy | Given any authored prompt; When inspected; Then a negative list is present | pass |
| TC-FR-010-02-03 | unit | mapping | Given the output; When parsed; Then fields map onto the F-008 job contract | pass |

### FR-010-03 — Prompt matches narrated day (coherence)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-03-01 | unit | happy | Given a "beach" slot; When authoring; Then the scene text is a beach | pass |
| TC-FR-010-03-02 | benchmark | happy | Given generated image; When reviewed; Then it depicts the narrated scene | skip (benchmark) |

### FR-010-04 — A slot expands to N distinct framings
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-04-01 | unit | happy | Given one slot, N=6; When authored; Then 6 prompts are produced | pass |
| TC-FR-010-04-02 | unit | boundary | Given the set; When compared; Then framings/angles differ (not duplicates) | pass |
| TC-FR-010-04-03 | unit | boundary | Given N configured to 3; When authored; Then exactly 3 are produced | pass |

### FR-010-05 — Does not restate/override identity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-05-01 | unit | negative | Given an authored prompt; When inspected; Then it has no hard identity descriptors that fight the reference | pass |
| TC-FR-010-05-02 | unit | happy | Given the prompt; When inspected; Then it describes scene/pose/camera only | pass |

### FR-010-06 — Honors persona visual style (config)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-06-01 | unit | happy | Given a warm-cozy style config; When authoring; Then palette/outfit reflect it | pass |
| TC-FR-010-06-02 | integration | happy | Given an edited style config; When applied; Then prompts change, no code change | pass |

### FR-010-07 — Time-of-day / location coherence in prompt
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-07-01 | unit | happy | Given a night slot; When authored; Then lighting reads night | pass |
| TC-FR-010-07-02 | unit | boundary | Given a morning trail slot; When authored; Then it isn't a midnight bar | pass |

### FR-010-08 — Prompt + source slot logged with the asset
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-08-01 | integration | happy | Given a generated asset; When provenance is read; Then the prompt + slot/seed are recorded | pass |
| TC-FR-010-08-02 | unit | mapping | Given meta_json; When parsed; Then prompt provenance fields are present | pass |

### FR-010-09 — Safe default when life state missing
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-09-01 | unit | empty | Given no current slot; When a prompt is requested; Then a config default scene is authored | pass |
| TC-FR-010-09-02 | unit | negative | Given empty life state; When authoring; Then no crash, coherent default | pass |

### FR-010-10 — Conforms to fixed F-008 job contract (model-agnostic)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-10-01 | unit | mapping | Given the authored output; When validated; Then it fits the job contract schema | pass |
| TC-FR-010-10-02 | integration | consistency | Given A↔B; When the same prompt is used; Then it is accepted by both runners | pass |

### FR-010-11 — Shot metadata carried into MEDIA_ASSET meta_json
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-11-01 | integration | happy | Given authored shot meta (pose/bg/location/activity/time); When stored via F-008; Then meta_json holds them | pass |
| TC-FR-010-11-02 | unit | mapping | Given the meta fields; When On-Demand (F-012) queries; Then they are selectable | pass |

### FR-010-12 — Prompt OPENS with the identity-preservation directive (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-12-01 | unit | happy | Given an authored prompt; When inspected; Then it BEGINS with the preservation directive, before any scene text | implemented |
| TC-FR-010-12-02 | unit | negative | Given any authored prompt; When inspected; Then it never opens with a generic unbound subject ("candid photo of a woman") | implemented |
| TC-FR-010-12-03 | unit | happy | Given two anchors supplied; When authored; Then the directive references both pictures and the scene follows after it | implemented |

### FR-010-13 — Directive wording owned by F-009, only placed here
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-13-01 | unit | mapping | Given F-010 source; When inspected; Then the directive text comes from F-009, not re-authored locally | implemented |
| TC-FR-010-13-02 | unit | consistency | Given F-009's directive changes; When prompts are authored; Then the new wording flows through unchanged | implemented |

### FR-010-14 — iPhone hyperrealism block (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-14-01 | unit | happy | Given an authored prompt; When inspected; Then it carries the labeled sections (Photo type/Scene/Composition/Lighting/Skin/Camera/Processing) with concrete imperfections | implemented |
| TC-FR-010-14-02 | unit | negative | Given every framing; When inspected; Then each is a selfie-POV or companion-POV, no studio/editorial composition | implemented |
| TC-FR-010-14-03 | unit | negative | Given the lighting map; When inspected; Then no beauty-light vocabulary (golden hour / cinematic), imperfect-light terms present | implemented |
| TC-FR-010-14-04 | manual | happy | Given regenerated frames; When reviewed; Then they read as real iPhone shots (user acceptance) | out-of-band (GPU/manual) |

### FR-010-15 — Anti-studio negative list
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-15-01 | unit | happy | Given the negative list; When inspected; Then studio/retouch/beauty-filter/bokeh terms are present | implemented |
| TC-FR-010-15-02 | unit | negative | Given the negative list; When inspected; Then nothing suppresses natural phone artifacts (no bare "blurry") | implemented |

### FR-010-16 — Quality budget params (8 steps / 1024²)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-16-01 | unit | happy | Given default config; When jobs are authored; Then params are steps=8, 1024x1024 (config-tunable) | implemented |

### FR-010-17 — Wardrobe authored here, not inherited from anchors
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-17-01 | unit | happy | Given an authored prompt; When inspected; Then it states the reference clothing must not be copied | implemented |
| TC-FR-010-17-02 | benchmark | negative | Given regenerated frames; When reviewed; Then the outfit follows the prompt, not the body anchor | out-of-band (GPU/detector) |

### FR-010-18 — Anti-duplication negatives
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-010-18-01 | unit | happy | Given the negative list; When inspected; Then duplication terms are present | implemented |

### FR-010-19/20/21 — Human-readable scene description (ISS-008)
| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-010-19-01 | unit | happy | A description is emitted per shot | Given a slot; When jobs are authored; Then each carries a non-empty `scene_description` | implemented |
| TC-FR-010-19-02 | unit | happy | It names visible things, not just the place | Given an evening-at-home slot; When authored; Then the text mentions concrete objects/light, not only the location token | implemented |
| TC-FR-010-19-03 | unit | boundary | Empty slot degrades safely | Given no life state; When authored; Then a default description is produced, never empty/None | implemented |
| TC-FR-010-19-05 | unit | integration | Prompt and description agree | Given a slot; When authored; Then every object named in the description was also requested in the prompt's Scene section (one source — otherwise the description invents furniture) | implemented |
| TC-FR-010-20-01 | unit | happy | Written in the persona's language (ru) | Given a ru persona; When authored; Then the description is Russian | implemented |
| TC-FR-010-20-02 | unit | mapping | English persona gets English | Given an en persona; When authored; Then the description is English | implemented |
| TC-FR-010-21-01 | unit | negative | No generation jargon | Given any description; When scanned; Then no framing/technical terms ("high-angle selfie", "Camera signature", "negative") appear | implemented |
| TC-FR-010-21-02 | unit | negative | Never the raw prompt | Given the description; When compared; Then it is not the technical prompt nor a substring of it | implemented |
| TC-FR-010-21-03 | unit | negative | No appearance descriptors | Given the description; When scanned by the identity guard; Then it describes the scene, never her looks (FR-010-05) | implemented |

---

## Non-functional requirements

### NFR-010-01 — Coherence (CRITICAL, human/GPU-judged)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-01-01 | benchmark | happy | Given labeled slot/photo pairs; When judged; Then match rate ≥ target | skip (benchmark) |
| TC-NFR-010-01-02 | manual | happy | Given narration + photo; When reviewed; Then they agree | skip (manual) |
| TC-NFR-010-01-03 | benchmark | boundary | Given unusual slots; When judged; Then coherence holds | skip (benchmark) |

### NFR-010-02 — Variety
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-02-01 | unit | boundary | Given a slot's prompt set; When diversity is scored; Then framings are distinct | pass |
| TC-NFR-010-02-02 | manual | happy | Given the generated set; When reviewed; Then it looks like several real shots | skip (manual) |

### NFR-010-03 — Determinism/reproducibility
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-03-01 | unit | consistency | Given same slot + seed; When authored twice; Then identical prompts | pass |

### NFR-010-04 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-04-01 | integration | happy | Given edited style/N/negatives config; When applied; Then honored, no code change | pass |

### NFR-010-05 — Model-agnostic vocabulary
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-05-01 | integration | consistency | Given A↔B; When authored; Then the prompt is portable | pass |

### NFR-010-06 — Cheap to author (no heavy GPU)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-06-01 | unit | perf | Given authoring; When profiled; Then it is pure text composition, no model call | pass |

### NFR-010-07 — Safety-aware (SFW stays SFW)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-010-07-01 | unit | negative | Given SFW authoring; When inspected; Then no explicit vocabulary leaks in | pass |

---

## User-story acceptance (manual/GPU)
- **TC-US-010-01-01** — photo matches what she said she's doing. skip (manual)
- **TC-US-010-02-01** — photos read as candid phone snaps of her day. skip (manual)
- **TC-US-010-03-01** — a slot yields a few genuinely different angles. skip (manual)
- **TC-US-010-04-01** — B1: persona style tuning reflected in her photos. skip (manual)
- **TC-US-010-05-01** — operator: every asset traces to a logged prompt + slot. skip (manual)

## Coverage summary
FR-010-01..11 (11) + NFR-010-01..07 (7) + US-010-01..05 (5) — all covered; image-level coherence/
variety TCs are benchmark/human-judged (marked). Every TC id traces to its FR/NFR/US id.
