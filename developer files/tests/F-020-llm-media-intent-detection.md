# Tests for F-020 — LLM Media-Intent Detection

- **Feature:** [F-020 — LLM Media-Intent Detection](../features/F-020-llm-media-intent-detection.md)
- **Approach:** 2–3 tests per requirement. Signal parsing, stripping, routing, safe degrade, the
  fallback path and single-call latency are automatable with a **fake chat client**; **recall and
  precision** are quality properties of the real model and are measured out-of-band against labeled
  corpora (marked). The live-failing phrasing from **ISS-005** is pinned as an explicit regression
  case. Every TC id embeds its `FR-`/`NFR-`/`US-` id.

---

## Functional requirements

### FR-020-01 — Detection in the model turn (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-01-01 | unit | happy | Given a turn; When built; Then the prompt instructs the model to emit the media-intent signal | planned |
| TC-FR-020-01-02 | integration | happy | Given a reply carrying the signal; When post-processed; Then intent is taken from the signal, not from keywords | planned |
| TC-FR-020-01-03 | unit | mapping | Given the pipeline; When inspected; Then the keyword matcher is no longer the decision path | planned |

### FR-020-02 — No extra round-trip
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-02-01 | unit | perf | Given one turn; When processed; Then exactly one chat-model call is made | planned |

### FR-020-03 — Signal carries request + nature
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-03-01 | unit | happy | Given an sfw photo request signal; When parsed; Then requested=true, nature=sfw | planned |
| TC-FR-020-03-02 | unit | happy | Given an intimate request signal; When parsed; Then nature=intimate and delivery routes to the F-014 gate | planned |

### FR-020-04 — Signal stripped from the reply
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-04-01 | unit | happy | Given a reply containing the signal; When sent; Then the user-visible text contains no signal token | planned |
| TC-FR-020-04-02 | unit | boundary | Given a signal at the start/end/middle; When stripped; Then the remaining prose is clean and unbroken | planned |

### FR-020-05 — Safe degrade
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-05-01 | unit | empty | Given no signal in the reply; When parsed; Then no media intent, plain text turn | planned |
| TC-FR-020-05-02 | unit | error | Given a malformed signal; When parsed; Then no media intent, no crash | planned |
| TC-FR-020-05-03 | unit | negative | Given garbage where the signal should be; When parsed; Then nothing is sent by accident | planned |

### FR-020-06 — Recall on natural phrasing
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-06-01 | regression | happy | **ISS-005:** given "а может сфоткаешься сидя на диване?"; When classified by the model; Then it IS a photo request | out-of-band (live model) |
| TC-FR-020-06-02 | benchmark | happy | Given the labeled RU/EN request corpus; When classified; Then recall ≥ target | out-of-band (live model) |

### FR-020-07 — Precision on topic mentions
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-07-01 | benchmark | negative | Given the labeled photo-*topic* corpus ("обожаю фотографировать закаты"); When classified; Then no delivery is triggered | out-of-band (live model) |

### FR-020-08 — Keyword fallback (defence in depth)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-08-01 | unit | error | Given the runner is unavailable; When an obvious request arrives; Then the fallback still triggers delivery | planned |
| TC-FR-020-08-02 | unit | mapping | Given a present valid signal; When processed; Then the signal wins over the fallback | planned |

### FR-020-09 — Config-driven, versioned prompt
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-09-01 | unit | happy | Given edited instruction/format/fallback config; When applied; Then honored without a code change | planned |
| TC-FR-020-09-02 | unit | mapping | Given the prompt asset; When inspected; Then it carries a version stamp | planned |

### FR-020-10 — Language-agnostic
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-020-10-01 | benchmark | happy | Given equivalent RU and EN requests; When classified; Then both are recognized | out-of-band (live model) |

---

## Non-functional requirements

### NFR-020-01 — Latency unchanged
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-01-01 | unit | perf | Given a turn; When traced; Then one model call, no added delay | planned |

### NFR-020-02 — Recall (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-02-01 | benchmark | happy | Given the request corpus incl. ISS-005; When measured; Then recall ≥ target | out-of-band (live model) |

### NFR-020-03 — Precision
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-03-01 | benchmark | negative | Given the topic corpus; When measured; Then false-positive sends ≈ 0 | out-of-band (live model) |

### NFR-020-04 — Safety on ambiguity
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-04-01 | unit | negative | Given an ambiguous nature; When routed; Then it goes to the gate side, never the SFW archive | planned |

### NFR-020-05 — Robustness
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-05-01 | unit | error | Given adversarial/garbled model output; When parsed; Then no crash and no accidental send | planned |

### NFR-020-06 — Config/versioned prompt
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-020-06-01 | unit | happy | Given config edits; When applied; Then honored, version stamp recorded | planned |

---

## User-story acceptance
- **TC-US-020-01-01** (manual) — any natural way of asking lands as a photo request. out-of-band
- **TC-US-020-02-01** (manual) — talking about photos doesn't trigger a send. out-of-band
- **TC-US-020-03-01** (unit) — detection is part of the model turn, not a word list. planned
- **TC-US-020-04-01** (unit) — no extra round-trip. planned

## Coverage summary
FR-020-01..10 (10) + NFR-020-01..06 (6) + US-020-01..04 (4). Parsing/routing/degrade/fallback are
automatable; recall & precision are live-model measurements (marked), with ISS-005 pinned as an
explicit regression case.
