# Tests for F-019 — Conversational Intimacy Gate (text)

- **Feature:** [F-019 — Conversational Intimacy Gate](../features/F-019-conversational-intimacy-gate.md)
- **Approach:** 2–3 tests per requirement, **densest coverage on the safety-critical paths** (hard
  boundary battery, consent, stage gating, ceiling clamp) plus a **no-false-positive corpus** — a
  gate that sterilizes ordinary conversation is as much a defect as one that leaks. The gate is a
  local deterministic check, so nearly everything is automatable; only "does she still feel natural
  in a live chat" is manual. Every TC id embeds its `FR-`/`NFR-`/`US-` id.

> **Boundary note.** F-014 owns the policy core (hard scan, stage→level map, ceiling clamp, audit
> table); these tests assert F-019 **reuses** it and applies it to text, rather than re-testing
> F-014's internals.

---

## Functional requirements

### FR-019-01 — Enforcement on the outbound reply (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-01-01 | unit | happy | Given an explicit candidate reply beyond the unlocked level; When gated; Then it is replaced, not sent | planned |
| TC-FR-019-01-02 | integration | negative | Given the model ignores the prompt directive; When the turn runs; Then the gate still enforces (prompt is not the enforcement point) | planned |
| TC-FR-019-01-03 | unit | mapping | Given the turn pipeline; When inspected; Then the gate runs on the generated reply (post-process, §3.2 step 5) | planned |

### FR-019-02 — Hard safety boundary in text (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-02-01 | security | negative | Given a prohibited-category candidate reply; When gated; Then it is blocked and never sent | planned |
| TC-FR-019-02-02 | security | negative | Given the most permissive config + deepest stage + opted-in adult; When prohibited; Then still blocked | planned |
| TC-FR-019-02-03 | unit | mapping | Given the implementation; When inspected; Then it reuses F-014 `hard_safety_scan` (no duplicate policy) | planned |

### FR-019-03 — Age/consent gate
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-03-01 | unit | negative | Given a non-adult user; When an explicit reply is produced; Then it is withheld | planned |
| TC-FR-019-03-02 | unit | negative | Given adult but not opted in; When explicit; Then withheld with the consent reason | planned |
| TC-FR-019-03-03 | unit | happy | Given verified adult + opted in at a sufficient stage; When explicit; Then allowed | planned |

### FR-019-04 — Stage-gated explicitness
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-04-01 | unit | negative | Given Stranger stage; When an explicit reply is produced; Then withheld ("not yet") | planned |
| TC-FR-019-04-02 | unit | happy | Given a deeply bonded stage; When explicit; Then allowed | planned |
| TC-FR-019-04-03 | unit | boundary | Given the exact threshold stage; When evaluated; Then it unlocks | planned |

### FR-019-05 — Per-persona ceiling, clamped
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-05-01 | unit | happy | Given a tamer persona ceiling; When a bonded user pushes; Then her ceiling applies | planned |
| TC-FR-019-05-02 | security | negative | Given a config above the platform limit; When applied; Then min(persona, platform) wins | planned |

### FR-019-06 — Explicitness classification
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-06-01 | unit | happy | Given clearly explicit text; When classified; Then explicit | planned |
| TC-FR-019-06-02 | unit | boundary | Given suggestive-but-not-explicit text; When classified; Then the suggestive tier (defaults safe) | planned |
| TC-FR-019-06-03 | unit | negative | Given ordinary affection/flirting; When classified; Then NOT explicit | planned |

### FR-019-07 — In-character substitution (CRITICAL for the illusion)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-07-01 | unit | happy | Given a withheld reply; When substituted; Then a persona-voiced line is returned | planned |
| TC-FR-019-07-02 | unit | negative | Given any substitution; When inspected; Then no assistant-voice leakage ("as an AI", "I can't assist") | planned |
| TC-FR-019-07-03 | unit | mapping | Given RU and EN personas; When substituted; Then the line matches her language | planned |
| TC-FR-019-07-04 | unit | boundary | Given each reason (consent / not-yet / hard block); When substituted; Then a distinct appropriate line | planned |

### FR-019-08 — SFW conversation untouched
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-08-01 | unit | happy | Given a non-explicit reply; When gated; Then it is returned byte-identical | planned |
| TC-FR-019-08-02 | unit | negative | Given a corpus of warm/flirty/emotional replies; When gated; Then zero are modified (no false positives) | planned |

### FR-019-09 — Audit
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-09-01 | integration | happy | Given any decision; When made; Then a GateDecision row records action/reason | planned |
| TC-FR-019-09-02 | security | negative | Given a blocked reply; When logged; Then the prohibited text is not persisted | planned |

### FR-019-10 — Channel consistency with F-014
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-10-01 | integration | consistency | Given the same user/persona/stage/level; When gated as text and as media; Then the verdicts agree | planned |

### FR-019-11 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-11-01 | unit | happy | Given edited vocabulary/thresholds/lines; When applied; Then honored without a code change | planned |

### FR-019-12 — No extra LLM round-trip
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-019-12-01 | unit | perf | Given the gate; When traced; Then it makes no model call (pure local check) | planned |

---

## Non-functional requirements

### NFR-019-01 — Hard boundary absolute (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-01-01 | security | negative | Given the adversarial battery (wrappers/obfuscation/injection); When run; Then zero prohibited text | planned |
| TC-NFR-019-01-02 | security | negative | Given every stage×config combination; When probed; Then prohibited stays blocked | planned |

### NFR-019-02 — Consent enforcement (CRITICAL)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-02-01 | security | negative | Given non-adult/non-opted-in probed exhaustively; Then explicit text never delivered | planned |

### NFR-019-03 — No false positives
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-03-01 | unit | negative | Given the SFW corpus; When gated; Then 100% pass unmodified | planned |

### NFR-019-04 — Illusion preserved
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-04-01 | unit | negative | Given all deflection lines; When scanned; Then no assistant-voice phrases | planned |
| TC-NFR-019-04-02 | manual | happy | Given a live chat; When she deflects; Then it feels like her, not a filter | out-of-band (manual) |

### NFR-019-05 — Latency
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-05-01 | unit | perf | Given the gate on a long reply; When timed; Then sub-millisecond, no model call | planned |

### NFR-019-06 — Cross-channel consistency
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-06-01 | integration | consistency | Given identical inputs; When both gates run; Then identical verdicts | planned |

### NFR-019-07 — Auditability
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-07-01 | integration | happy | Given decisions; When reviewed; Then reason present, no prohibited content stored | planned |

### NFR-019-08 — Config-driven
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-NFR-019-08-01 | unit | happy | Given edited config; When applied; Then honored, no code change | planned |

---

## User-story acceptance
- **TC-US-019-01-01** (manual) — intimacy in conversation builds with the bond. out-of-band
- **TC-US-019-02-01** (integration) — one policy across text and media. planned
- **TC-US-019-03-01** (security) — hard boundary holds in conversation. planned
- **TC-US-019-04-01** (manual) — refusals stay in character. out-of-band
- **TC-US-019-05-01** (unit) — per-persona ceiling configurable within the limit. planned

## Coverage summary
FR-019-01..12 (12) + NFR-019-01..08 (8) + US-019-01..05 (5). Safety-critical paths get adversarial
batteries; the no-false-positive corpus guards against over-blocking.
