# Tests for F-022 — Operator Control Panel

- **Feature:** [F-022 — Operator Control Panel](../features/F-022-operator-control-panel.md)
- **Status:** planned (specification only — the feature is not implemented yet). Every TC below is
  `planned`; they are written now so the build is test-driven from day one, per the project's
  docs-first rule. When F-022 is built, split the runnable suite across the three sub-areas
  (observe / act / access-audit) and keep the ~2-3-tests-per-requirement ratio.
- **Method (same non-negotiables as the rest of the project):** behavioural tests **execute the real
  API/handler** against a test DB + temp media root and assert on observable outcomes (HTTP status,
  the rows written, the audit entries produced, what the bot then reads) — never on source text.
  RBAC and audit are asserted by *calling the endpoint as each role* and checking the effect, not by
  grepping the router. Isolation is asserted by driving the bot while the panel is down.

---

## Access & audit (CRITICAL — test first)

### FR-022-15 — Authentication
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-15-01 | integration | negative | Given no/invalid credentials; When any endpoint is called; Then 401, nothing is read or mutated | planned |
| TC-FR-022-15-02 | integration | happy | Given valid operator credentials; When authenticating; Then a scoped session is issued | planned |
| TC-FR-022-15-03 | security | negative | Given repeated failed logins; When the threshold is passed; Then auth is rate-limited | planned |

### FR-022-16 — Role-based authorization
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-16-01 | integration | negative | Given a `viewer`; When they open a private transcript or mutate; Then 403 on the server (not just hidden in UI) and the attempt is logged | planned |
| TC-FR-022-16-02 | integration | happy | Given an `operator`; When they observe and perform a non-sensitive mutation; Then allowed | planned |
| TC-FR-022-16-03 | integration | negative | Given an `operator` (not `admin`); When they perform a sensitive/consent action; Then 403 | planned |
| TC-FR-022-16-04 | integration | happy | Given an `admin`; When they perform a sensitive action with a reason; Then allowed + audited | planned |

### FR-022-19 — Audit every mutation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-19-01 | integration | happy | Given any mutating endpoint; When called; Then an append-only audit row records actor/role/target/before/after/timestamp | planned |
| TC-FR-022-19-02 | integration | negative | Given the panel; When something tries to edit/delete an audit row; Then it is refused (append-only) | planned |
| TC-FR-022-19-03 | integration | boundary | Given a sensitive action; When performed without a reason; Then it is rejected (reason mandatory) | planned |

### FR-022-20 — Sensitive-read logging
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-20-01 | integration | happy | Given an operator opens a private conversation; When the transcript loads; Then a sensitive-read entry (actor/target/time) is written | planned |
| TC-FR-022-20-02 | integration | negative | Given a viewer; When they attempt a sensitive read; Then forbidden and the attempt is logged | planned |

### FR-022-17 / NFR-022-01/07 — Isolation from the bot
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-17-01 | integration | happy | Given the panel process is stopped; When users drive the bot; Then the bot serves normally (panel not on the reply path) | planned |
| TC-FR-022-17-02 | structural | negative | Given the reply-path modules; When imports are scanned; Then no admin/panel module is imported into the bot turn (additive to 17-01) | planned |
| TC-NFR-022-01-01 | integration | boundary | Given panel queries under load; When the bot writes a turn; Then the bot's WAL write path is not blocked | planned |

### FR-022-21 — No impersonation
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-21-01 | integration | negative | Given the panel; When any action is attempted that would send a message AS the user to a third party; Then there is no such capability/endpoint | planned |

---

## Observe

### FR-022-01 — User roster
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-01-01 | integration | happy | Given N users; When the roster is fetched; Then all appear with persona/stage/last-active/counts, paged | planned |
| TC-FR-022-01-02 | performance | boundary | Given a large user base; When the roster is queried; Then it is paged and index-backed (no full scan) | planned |

### FR-022-03 — Conversation transcript
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-03-01 | integration | happy | Given a session with messages and sent photos; When opened; Then messages render chronologically with media inline (from MESSAGE rows only) | planned |
| TC-FR-022-03-02 | integration | boundary | Given a very long history; When opened; Then it pages without loading everything at once | planned |

### FR-022-05/06/07 — Health, metrics, effective config
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-05-01 | integration | happy | Given running services; When health is fetched; Then chat/runner/DB/Qdrant/GPU states are reported without touching the reply path | planned |
| TC-FR-022-06-01 | integration | happy | Given activity over a range; When metrics are queried; Then delivered/deflected/paced photo counts and intent/gate outcomes are returned | planned |
| TC-FR-022-07-01 | integration | happy | Given a global override and a per-user override; When effective config is fetched; Then each value shows its source (default/global/per-user) | planned |

---

## Act

### FR-022-08 — Per-user overrides (applied by the bot)
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-08-01 | integration | happy | Given a user at "Acquaintance"; When the operator sets "Friend"; Then the store updates, the bot reads it next turn, and it is audited | planned |
| TC-FR-022-08-02 | integration | happy | Given a paced user; When pacing is disabled for them; Then the next real photo request delivers (F-012 FR-012-20) | planned |
| TC-FR-022-08-03 | integration | negative | Given an invalid stage value; When set; Then rejected, nothing changes | planned |

### FR-022-09 / FR-022-18 / NFR-022-06 — Global settings, validated & safe
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-09-01 | integration | happy | Given retention cap 60; When set to 40 in range; Then the next retention run uses 40, no redeploy | planned |
| TC-FR-022-18-01 | integration | negative | Given a negative/malformed value; When saved; Then rejected and the previous value stands | planned |
| TC-NFR-022-06-01 | integration | negative | Given an input that would empty an archive or disable the F-014 hard floor; When attempted; Then refused server-side | planned |

### FR-022-11 — Archive curation via the F-021 path
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-11-01 | integration | happy | Given an archive frame; When deleted from the panel; Then file+row go together (F-021 FR-021-07) and reconcile is clean | planned |
| TC-FR-022-11-02 | structural | negative | Given deletion; When traced; Then it calls the existing F-021 eviction, not a second routine (additive to 11-01) | planned |

### FR-022-12/13 — Safety moderation & consent
| Test ID | Level | Case | Given / When / Then | Status |
|---------|-------|------|---------------------|--------|
| TC-FR-022-12-01 | security | negative | Given the panel; When any action tries to loosen the F-014 hard floor; Then it is impossible (not a gate bypass) | planned |
| TC-FR-022-13-01 | integration | happy | Given an admin; When they verify a user's 18+ with a reason; Then it persists, adult content stays gated on it, and it is audited as sensitive | planned |
| TC-FR-022-13-02 | integration | negative | Given a non-admin; When they attempt a consent change; Then 403 | planned |

---

## User-story acceptance (manual)
- **TC-US-022-02-01** — operator can actually read a real conversation and it reads correctly. manual
- **TC-US-022-04-01** — operator edits a global knob and sees the product behave differently. manual
- **TC-US-022-07-01** — the health view tells the operator the machine is healthy at a glance. manual
- UI/UX quality and operator workflow ergonomics are manual throughout.

## Coverage summary
Access-audit (FR-022-15/16/17/19/20/21 + NFR-022-01) is specified **first** and most heavily — it is
the feature's real risk surface (private chats, consent). Observe (01/03/05/06/07) and Act
(08/09/11/12/13/18) each get happy + negative + boundary. Every TC id traces to one FR/NFR/US id;
all are `planned` until the feature is built.
