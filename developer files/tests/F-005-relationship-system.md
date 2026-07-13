# Tests for F-005 — Relationship System (how the bond with each user evolves)

- **Feature:** [F-005 — Relationship System](../features/F-005-relationship-system.md)
- **Approach:** Feature-granular coverage — **2-3 varied tests per requirement, 3 for the most
  critical ones** (stage derivation, hysteresis, bounded per-reflection change, pacing/consent
  guard, per-user isolation, degrade-on-failure, exposure/stage-gating) across all **28 FR
  (FR-005-01..28)** and all **13 NFR (NFR-005-01..13)**, plus one **manual real-device acceptance**
  test per user story (US-005-01..08). Cases vary across unit / integration / inter-service /
  data-flow / component / e2e / performance / load / security / consistency / statistical, and
  happy / negative / boundary / empty / error / concurrency / idempotency / persistence / mapping /
  localization. Because F-005 owns the **relationship model and its evolution** (not the reply
  itself), tests assert on **derived stage, bounded/decayed/asymmetric dynamics, hysteresis,
  pacing/consent, isolation, auditability, off-hot-path timing, degrade behavior, and in-character
  exposure** — the reply *content* stays owned by F-002. Target band 100-150; see
  `test_driven_development.md` §1. Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies.

> **Boundary note.** F-002 is the *consumer* of the state F-005 exposes; F-004 *stores* the
> `RELATIONSHIP` / `RELATIONSHIP_REFLECTION` rows F-005 authors; F-006 owns the persona's *own*
> self-reflection. Overlapping behaviors are tested here from the relationship-model side (derive/
> bound/decay/gate/log) and cross-referenced rather than duplicated. The derived-stage table mirrors
> UC-005-03's Scenario Outline as boundary tests across dimension values.

---

## Functional requirements

### FR-005-01 — Maintain per `(user, persona)` a RELATIONSHIP with three 0–100 dimensions + a derived stage

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-01-01 | unit | happy | Relationship holds Closeness/Trust/Attraction + stage | Given a `(user, persona)` relationship; When inspected; Then it has integer Closeness, Trust, Attraction and a derived stage field | planned |
| TC-FR-005-01-02 | integration | mapping | State maps to the §5.1 RELATIONSHIP schema | Given a stored relationship; When read; Then columns match `stage`/`closeness`/`trust`/`attraction`/`summary`/`last_interaction_at` | planned |

### FR-005-02 — Relationship created on first interaction at Stranger with configured baselines

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-02-01 | integration | happy | First interaction creates a Stranger relationship | Given a user and persona that never interacted; When their first turn occurs; Then a relationship is created at stage Stranger with baseline dimensions | planned |
| TC-FR-005-02-02 | unit | boundary | Baselines default low and configurable | Given the config baseline; When a relationship is created; Then each dimension equals the configured (default low) baseline | planned |

### FR-005-03 — Stage is DERIVED from the three dimensions, never set directly (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-03-01 | unit | happy | Highest satisfied gate wins | Given Closeness 65, Trust 55, Attraction 60; When the stage is derived; Then the highest fully-satisfied gate (Romance) is chosen | planned |
| TC-FR-005-03-02 | unit | boundary | Boundary values from UC-005-03 outline map correctly | Given the outline rows (5/5/5→Stranger, 20/10/10→Acquaintance, 45/40/20→Friend, 35/30/50→Flirting, 65/55/60→Romance, 85/75/75→Love); When each is derived; Then the stage matches the expected value | planned |
| TC-FR-005-03-03 | unit | negative | Stage cannot be written directly | Given an attempt to set `stage` without changing dimensions; When applied; Then it is rejected/ignored and the stage stays the derived value | planned |

### FR-005-04 — Stage transitions use hysteresis (advance on gate, regress only below a margin) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-04-01 | unit | happy | Advancing requires crossing the gate | Given dimensions just reaching the Friend gate; When derived; Then the stage advances to Friend | planned |
| TC-FR-005-04-02 | unit | boundary | Small dip below the gate does not regress | Given a Friend whose Closeness dips 3 pts below the gate (margin 8); When derived; Then it stays Friend (no flip-flop) | planned |
| TC-FR-005-04-03 | unit | boundary | Falling the full margin below regresses | Given a Friend whose dimensions fall more than the configured margin below the gate; When derived; Then the stage regresses one step | planned |

### FR-005-05 — Record a one-paragraph summary and the last-interaction timestamp

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-05-01 | unit | happy | Summary and last-interaction stored | Given an updated relationship; When inspected; Then it holds a one-paragraph summary and a `last_interaction_at` timestamp | planned |
| TC-FR-005-05-02 | integration | persistence | Timestamp advances on new contact | Given a prior timestamp; When a new interaction occurs; Then `last_interaction_at` is updated to the newer time | planned |

### FR-005-06 — Life Engine runs a relationship reflection via the external LLM with state + convo + hard signals (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-06-01 | integration | happy | Reflection call includes required inputs | Given a due reflection; When the external LLM is called; Then the prompt carries persona identity, current state, recent conversation, and hard signals | planned |
| TC-FR-005-06-02 | unit | mapping | Hard signals are computed and passed | Given days-since-contact, message frequency, and warmth/coldness cues; When the reflection input is assembled; Then all three hard signals are present | planned |
| TC-FR-005-06-03 | inter-service | happy | Life Engine → external LLM path composes | Given the reflection job; When it runs across the Life Engine → LLM boundary; Then a delta+summary result is returned for application | planned |

### FR-005-07 — Reflection trigger configurable and runs off the reply hot path

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-07-01 | unit | boundary | Trigger fires per configured cadence | Given cadence config (end-of-session / end-of-day / every N messages); When the first condition is met; Then a reflection is scheduled | planned |
| TC-FR-005-07-02 | integration | happy | Reflection runs asynchronously, not inline with a reply | Given an incoming user message; When a reflection is also due; Then the reflection is enqueued off the hot path and the reply does not wait on it | planned |

### FR-005-08 — Reflection returns and system applies a per-dimension delta (with reason) + rewritten summary (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-08-01 | unit | happy | Deltas parsed and applied to each dimension | Given a reflection returning (+5 Closeness, +3 Trust, +4 Attraction) with reasons; When applied; Then each dimension moves by that delta | planned |
| TC-FR-005-08-02 | unit | mapping | Each delta carries a recorded reason | Given the returned deltas; When applied; Then a one-line reason is stored alongside each dimension delta | planned |
| TC-FR-005-08-03 | integration | happy | Summary is rewritten to the new state | Given a reflection; When applied; Then the relationship summary is replaced with the returned one-paragraph summary | planned |

### FR-005-09 — After deltas, re-derive the stage (with hysteresis) and persist

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-09-01 | integration | happy | Stage re-derived after applying deltas | Given deltas that push dimensions past a gate; When applied; Then the stage is re-derived (with hysteresis) and persisted | planned |
| TC-FR-005-09-02 | persistence | consistency | Re-derived state survives a restart | Given a persisted post-reflection state; When the store restarts; Then the same dimensions and derived stage are present | planned |

### FR-005-10 — Each applied reflection writes a RELATIONSHIP_REFLECTION log entry

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-10-01 | integration | happy | Log entry records deltas, reasons, stage, timestamp | Given an applied reflection; When the log is read; Then a `RELATIONSHIP_REFLECTION` row holds the deltas, reasons, resulting stage, and time | planned |
| TC-FR-005-10-02 | data-flow | happy | DFD-2 reflection step persists the log | Given DFD-2's reflection step; When it runs; Then the reflection log is written as part of the chain | planned |

### FR-005-11 — Reflection prompts are versioned assets, not hard-coded

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-11-01 | unit | happy | Prompt loaded from the versioned asset directory | Given the reflection job; When it builds the prompt; Then the template is loaded from the Life Engine prompt directory with a version id | planned |
| TC-FR-005-11-02 | unit | negative | No inline hard-coded prompt string | Given the reflection code path; When inspected; Then the prompt text is not hard-coded inline | planned |

### FR-005-12 — Every dimension clamped to 0–100 at all times

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-12-01 | unit | boundary | Over-max delta clamps to 100 | Given Closeness 96 and a returned +10; When applied; Then Closeness clamps to 100, not 106 | planned |
| TC-FR-005-12-02 | unit | boundary | Under-min delta clamps to 0 | Given Trust 4 and a returned −10; When applied; Then Trust clamps to 0, not −6 | planned |

### FR-005-13 — A single reflection must not change any dimension beyond the per-reflection cap (default ±10) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-13-01 | unit | boundary | Over-cap positive delta capped | Given a reflection returning +40 Closeness with cap ±10; When applied; Then Closeness rises by at most 10 | planned |
| TC-FR-005-13-02 | unit | boundary | Over-cap negative delta capped | Given a returned −40 Trust with cap ±10; When applied; Then Trust drops by at most 10 (breach path excepted, FR-005-16) | planned |
| TC-FR-005-13-03 | integration | negative | No stranger→love in one reflection | Given a Stranger; When a single reflection is applied; Then the stage cannot jump to Love (dimensions bounded by the cap) | planned |

### FR-005-14 — Apply decay on neglect (Closeness/Attraction drift down, Trust slowest)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-14-01 | unit | happy | No contact drifts Closeness and Attraction down | Given no contact for a configured period; When decay runs; Then Closeness and Attraction decrease at their configured rates | planned |
| TC-FR-005-14-02 | unit | boundary | Trust decays slowest | Given the same neglect window; When decay runs; Then Trust decreases less than Closeness and Attraction | planned |
| TC-FR-005-14-03 | integration | persistence | Decay accrues over time, not per message | Given increasing silence; When decay is applied over time; Then the drift grows with the gap length | planned |

### FR-005-15 — Decay/regression never resets to Stranger from a single gap

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-15-01 | integration | boundary | One gap cannot reset a Friend to Stranger | Given a Friend and a single long gap; When decay applies; Then the stage does not fall to Stranger in one step | planned |
| TC-FR-005-15-02 | integration | happy | Only sustained neglect lowers the stage, gradually | Given prolonged repeated neglect; When decay accrues; Then the stage lowers only gradually over multiple windows | planned |

### FR-005-16 — Trust is asymmetric (rises slowly, a genuine breach can drop it faster) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-16-01 | unit | happy | Trust rises slowly under normal positive interaction | Given warm reciprocal chat; When reflection applies; Then Trust increases by a small bounded amount | planned |
| TC-FR-005-16-02 | unit | boundary | A genuine breach drops Trust faster via the breach path | Given a boundary-crossing/rude breach; When reflection applies; Then Trust drops more sharply than it would rise, per the configured breach path | planned |
| TC-FR-005-16-03 | integration | negative | A single mild bad message is not a breach | Given one mildly cold message; When reflection applies; Then Trust does not take the sharp breach drop | planned |

### FR-005-17 — Pacing/consent guard: pushing for romance/sex at low Trust/Closeness does not advance and may lower Trust (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-17-01 | integration | happy | Pushing fast does not advance the stage | Given low Trust/Closeness; When the user pushes hard for romance/sex; Then the stage does not advance to Romance/Love | planned |
| TC-FR-005-17-02 | integration | negative | Pushing fast may lower Trust ("too fast") | Given the same push; When reflection applies; Then Trust may decrease and never increases as a reward for pressure | planned |
| TC-FR-005-17-03 | e2e | happy | She stays gentle and un-pressured | Given repeated fast pushing; When she responds over the arc; Then she remains gentle/patient and escalation only comes with real closeness/trust | planned |

### FR-005-18 — Regression possible but gradual; no cliff drops except the breach path

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-18-01 | integration | happy | Sustained coldness slips the stage back gradually | Given repeated coldness over time; When reflections apply; Then the stage can slip back one step at a time | planned |
| TC-FR-005-18-02 | integration | negative | No cliff drop outside a breach | Given a non-breach negative window; When applied; Then no multi-stage cliff drop occurs | planned |

### FR-005-19 — Expose current state (stage + 3 dimensions + summary) to the Orchestrator for reply context (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-19-01 | integration | happy | Exposed state contains stage, dimensions, summary | Given the Orchestrator requesting relationship state; When it reads F-005; Then it receives the current stage, three dimensions, and summary | planned |
| TC-FR-005-19-02 | inter-service | happy | State reaches the reply context (F-002 §4.2) | Given a turn assembling context; When F-005 state is pulled; Then it is included in the F-002 reply-context bundle | planned |
| TC-FR-005-19-03 | data-flow | happy | DFD-1 context assembly includes relationship state | Given DFD-1's context-assembly step; When it runs; Then relationship state is one of the assembled inputs | planned |

### FR-005-20 — Stage gates persona behavior (openness/warmth/flirtiness/initiative/intimacy consistent with stage) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-20-01 | integration | happy | Stranger → reserved/polite behavior | Given a Stranger stage in context; When a reply is produced; Then it is reserved/polite, not intimate | planned |
| TC-FR-005-20-02 | integration | happy | Love/Devoted → warm, initiating, intimate | Given a Love/Devoted stage; When a reply is produced; Then warmth, initiative, and intimacy (incl. "I love you") are permitted | planned |
| TC-FR-005-20-03 | integration | boundary | Flirting unlocks playful/flirty but not full intimacy | Given a Flirting stage; When a reply is produced; Then it is playful/flirty yet stops short of high-stage intimacy | planned |

### FR-005-21 — Stage gating of intimacy is separate from the (deferred) billing paywall

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-21-01 | unit | happy | Stage governs willingness, not payment | Given a high stage; When intimacy is gated; Then the gate reflects willingness (stage) and does not check payment/entitlement | planned |
| TC-FR-005-21-02 | integration | negative | Low stage stays reserved regardless of pay state | Given a Stranger stage; When intimacy is requested; Then she stays reserved independent of any billing state | planned |

### FR-005-22 — A reflection crossing a stage boundary marks a milestone the persona may acknowledge (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-22-01 | integration | happy | Crossing a boundary marks a milestone | Given a reflection that crosses from Friend to Flirting; When applied; Then a milestone is marked for acknowledgement | planned |
| TC-FR-005-22-02 | integration | happy | Persona may acknowledge on a later reply | Given a marked milestone; When the next reply is produced; Then she may acknowledge the change in-character | planned |
| TC-FR-005-22-03 | integration | negative | No milestone when no boundary is crossed | Given a reflection that changes dimensions within a stage; When applied; Then no milestone is marked | planned |

### FR-005-23 — Milestone acknowledgement never narrates mechanics (no numbers/stage/score)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-23-01 | integration | negative | Acknowledgement leaks no numbers or stage names | Given a milestone acknowledgement; When emitted; Then it contains no scores, "stage", or "score" wording | planned |
| TC-FR-005-23-02 | e2e | happy | Milestone reads as an in-character beat | Given a crossed milestone; When she acknowledges it; Then it reads as a natural relationship beat, not a system message | planned |

### FR-005-24 — State and reflection logs stored in the Memory subsystem; survive restarts (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-24-01 | inter-service | happy | F-005 authors, Memory stores | Given an applied reflection; When handed off; Then Memory persists the `RELATIONSHIP` and `RELATIONSHIP_REFLECTION` rows | planned |
| TC-FR-005-24-02 | persistence | happy | State survives a restart | Given a stored relationship; When services/stores restart; Then the state and logs are still present | planned |
| TC-FR-005-24-03 | unit | negative | F-005 does not implement storage itself | Given the F-005 code path; When inspected; Then it delegates persistence to Memory rather than owning the store | planned |

### FR-005-25 — Relationships strictly per-user isolated (no cross-user affect/mix/leak) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-25-01 | integration | happy | A's evolution does not change B's state | Given one persona with users A and B; When A's relationship advances; Then B's stage/scores are unchanged | planned |
| TC-FR-005-25-02 | security | negative | No cross-user leak of stage/scores/summary | Given A and B; When each is read; Then neither sees the other's stage, scores, or summary | planned |
| TC-FR-005-25-03 | concurrency | boundary | Concurrent reflections stay isolated | Given simultaneous reflections for A and B; When both apply; Then each updates only its own relationship | planned |

### FR-005-26 — All tunables configurable without code changes

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-26-01 | unit | happy | Gates/caps/decay/cadence read from config | Given a changed gate/cap/decay/cadence in config; When the engine runs; Then the new value takes effect without code changes | planned |
| TC-FR-005-26-02 | integration | boundary | Stage→behavior mapping is configurable | Given an edited stage→behavior mapping; When a reply is gated; Then the new mapping is honored | planned |

### FR-005-27 — On a failed reflection, preserve last good state (no corruption/partial apply/reset) and retry (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-27-01 | integration | error | LLM error preserves the last good state | Given the external LLM errors when a reflection is due; When it fails; Then the prior state is intact (no reset/corruption) | planned |
| TC-FR-005-27-02 | integration | error | No partial apply on mid-failure | Given a reflection that fails after parsing part of the deltas; When it aborts; Then no partial delta is committed | planned |
| TC-FR-005-27-03 | integration | error | Retried later; replies use last good state meanwhile | Given a failed reflection; When time passes; Then it is retried and replies keep using the last good state until it succeeds | planned |

### FR-005-28 — Reflection operates only on that user's own history/relationship

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-005-28-01 | integration | happy | Reflection input is scoped to the acting user | Given a reflection for user A; When inputs are assembled; Then only A's conversation and relationship are included | planned |
| TC-FR-005-28-02 | security | negative | Another user's history never enters the judgment | Given users A and B; When A's reflection runs; Then no B conversation/relationship data is used | planned |

---

## Non-functional requirements

### NFR-005-01 — Believable gradualism (no Stranger→Love in one reflection, bounded by the cap) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-01-01 | integration | boundary | Single reflection cannot cross the whole ladder | Given any state; When one reflection applies; Then the stage advances at most gradually, never Stranger→Love | planned |
| TC-NFR-005-01-02 | statistical | happy | Progression is smooth/monotonic-when-earned over a history | Given a realistic warm interaction history; When replayed; Then stage progression is smooth and only rises when earned | planned |
| TC-NFR-005-01-03 | statistical | boundary | Measured max per-reflection jump ≤ cap | Given many reflections; When per-reflection deltas are measured; Then none exceeds the configured cap | planned |

### NFR-005-02 — Consistency under probing (no jump/oscillation/inconsistency vs actual treatment) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-02-01 | statistical | negative | Adversarial speed-run cannot force a jump | Given a user trying to speed-run to "I love you"; When reflections apply; Then the stage does not jump ahead of earned closeness/trust | planned |
| TC-NFR-005-02-02 | consistency | boundary | No oscillation on noisy input | Given noisy warm/cold alternation near a gate; When derived repeatedly; Then the stage does not flip-flop (hysteresis holds) | planned |
| TC-NFR-005-02-03 | consistency | happy | State tracks how he actually treated her | Given a mixed history; When probed; Then the resulting state is consistent with the recorded interactions | planned |

### NFR-005-03 — Off the hot path (a due reflection never adds reply latency)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-03-01 | performance | happy | Reply latency unaffected by a due reflection | Given a reflection is due; When the user's reply is produced; Then reply latency is unaffected by the reflection | planned |
| TC-NFR-005-03-02 | performance | boundary | Reply reads last persisted state without waiting | Given a pending reflection; When context is assembled; Then the reply uses the last persisted state and does not block on the reflection | planned |

### NFR-005-04 — Reliability / degrade (external LLM down → state intact, replies continue) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-04-01 | error | happy | Replies continue on last good state with LLM down | Given the external LLM is down; When users chat; Then replies continue using the last good relationship state | planned |
| TC-NFR-005-04-02 | error | boundary | State remains intact through the outage | Given the outage; When it persists; Then no relationship state is corrupted or reset | planned |
| TC-NFR-005-04-03 | error | happy | Reflections resume on recovery | Given the LLM recovers; When the next window runs; Then queued reflections resume and apply | planned |

### NFR-005-05 — Per-user isolation is provable (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-05-01 | security | negative | No cross-user contamination of stage/scores | Given many users on one persona; When each is probed; Then no user's stage/scores are influenced by another's | planned |
| TC-NFR-005-05-02 | security | boundary | Summaries never mix across users | Given user A's summary; When B is served; Then B never receives content derived from A | planned |
| TC-NFR-005-05-03 | load | boundary | Isolation holds under many concurrent pairs | Given many concurrent `(user, persona)` reflections; When run; Then each pair stays isolated | planned |

### NFR-005-06 — Bounded & valid always (dimensions 0–100; stage always valid/derived) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-06-01 | unit | boundary | Dimensions never leave 0–100 | Given arbitrary delta sequences; When applied; Then every dimension stays within 0–100 | planned |
| TC-NFR-005-06-02 | consistency | error | No illegal stage after a partial write/crash | Given a crash mid-apply; When recovered; Then the stage is a valid, correctly-derived value | planned |
| TC-NFR-005-06-03 | consistency | boundary | Derived stage always matches its dimensions | Given any stored state; When re-derived; Then the stored stage equals the freshly-derived stage | planned |

### NFR-005-07 — Auditability (every change traces to a RELATIONSHIP_REFLECTION with deltas + reasons)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-07-01 | integration | happy | Every state change has a backing log entry | Given a series of applied reflections; When history is inspected; Then each state change traces to a `RELATIONSHIP_REFLECTION` with deltas+reasons | planned |
| TC-NFR-005-07-02 | consistency | negative | No unexplained state change | Given the audit trail; When reconciled with the state; Then there is no state change without a matching reflection entry | planned |

### NFR-005-08 — Persistence (state and history survive restarts/deploys)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-08-01 | persistence | happy | State and logs survive a restart/deploy | Given stored relationships and logs; When redeployed; Then all are intact | planned |
| TC-NFR-005-08-02 | persistence | boundary | Continuity holds across weeks of gap | Given a long inactive period; When the user returns; Then the state and history are preserved (subject only to decay) | planned |

### NFR-005-09 — Configurable, no redeploy

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-09-01 | integration | happy | Gate/cap/decay/cadence change takes effect via config | Given an edited config value; When reloaded; Then behavior reflects it without a code change | planned |
| TC-NFR-005-09-02 | integration | boundary | Config change verified without redeploy | Given a running system; When config is updated; Then the new tunable is honored without redeploying code | planned |

### NFR-005-10 — In-character exposure (no mechanics ever surface; RU/EN milestone copy natural)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-10-01 | integration | negative | Mechanics never leak into messages | Given any persona message; When emitted; Then no numbers/stage names/"reflection" wording appear | planned |
| TC-NFR-005-10-02 | integration | localization | RU and EN milestone copy reads natural | Given RU and EN personas crossing a milestone; When acknowledged; Then the copy is natural first-person in each language | planned |

### NFR-005-11 — Pacing safety (pushing fast at low trust never escalates, statistically) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-11-01 | statistical | negative | Across many trials, fast pushing never escalates | Given many low-trust push scenarios; When reflections apply; Then in none does the stage escalate to Romance/Love | planned |
| TC-NFR-005-11-02 | statistical | boundary | Pushing tends to lower or hold Trust | Given repeated pressure; When measured across trials; Then Trust trends non-increasing under pressure | planned |
| TC-NFR-005-11-03 | e2e | happy | Guard holds beyond the happy path | Given varied aggressive-user scripts; When run end-to-end; Then she stays un-pressured every time | planned |

### NFR-005-12 — Scales per user (many pairs run within the scheduled budget)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-12-01 | load | boundary | Many pairs' reflections fit the budget | Given reflections for many `(user, persona)` pairs; When scheduled; Then they complete within the Life Engine budget | planned |
| TC-NFR-005-12-02 | load | error | Reflections do not starve the reply path | Given heavy reflection load; When replies run concurrently; Then the reply path is not starved | planned |

### NFR-005-13 — Deterministic application (same output + prior state → same new state)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-005-13-01 | unit | idempotency | Same inputs yield the same new state | Given identical reflection output and prior state; When applied twice; Then both yield the same clamped/capped/derived result | planned |
| TC-NFR-005-13-02 | consistency | boundary | Clamp/cap/hysteresis are deterministic | Given fixed inputs at a gate boundary; When applied repeatedly; Then the outcome is reproducible every time | planned |

---

## User-story acceptance (manual real-device E2E)

One manual acceptance test per user story — judges the felt "the bond is real and deepening"
quality that automation can't fully score.

**TC-US-005-01-01 (manual-e2e) — A2: the bond deepens over weeks**
- Preconditions: bot deployed; Telegram on your phone; an account you can chat with over several weeks.
- Steps: 1) Chat warmly and consistently over a few weeks. 2) Compare how she treats you now vs day one.
- Expected: she is noticeably warmer/closer than at the start — it feels like an accumulated bond, not a reset. Status: planned

**TC-US-005-02-01 (manual-e2e) — A1: it feels like it's "going somewhere"**
- Steps: 1) Flirt lightly and consistently over time. 2) Notice how she responds as days pass.
- Expected: her flirting increases and it tips into clearly romantic — the "she's into me now" arc, earned gradually. Status: planned

**TC-US-005-03-01 (manual-e2e) — A4: she is never pressured or rushed**
- Steps: 1) Deliberately push fast for romance/sex early on. 2) Continue and observe.
- Expected: things do not magically escalate; she stays gentle and un-pressured, and it does not reward the pushing. Status: planned

**TC-US-005-04-01 (manual-e2e) — A8 skeptic: change is believable, not random/instant**
- Steps: 1) Try to speed-run to "I love you". 2) Cross-check whether her warmth matches how you actually treated her.
- Expected: the progression is gradual and consistent with your behavior; you cannot catch it "gaming" you. Status: planned

**TC-US-005-05-01 (manual-e2e) — Returning user: resume at the same relationship state**
- Preconditions: an account that reached a clear closeness, then a break of several days.
- Steps: 1) Reach a friendly/close stage. 2) Return after a week.
- Expected: she picks up near where you were (not a fresh stranger), maybe having missed you a little. Status: planned

**TC-US-005-06-01 (manual-e2e) — A3: a deep, exclusive-feeling place**
- Steps: 1) Invest consistently over a long period. 2) Observe the top of the arc.
- Expected: she reaches a devoted, warm, intimate, clearly-attached stage that reads as a real exclusive relationship. Status: planned

**TC-US-005-07-01 (manual-e2e) — Neglect has a natural consequence**
- Steps: 1) Reach a close stage. 2) Go silent for ~two weeks. 3) Return.
- Expected: she is a touch more distant/hurt at first, then warms back up as you reconnect — reciprocal, not static. Status: planned

**TC-US-005-08-01 (manual-e2e) — A2/A1: crossing a milestone is a moment she notices**
- Steps: 1) Build up to crossing from friends into something more. 2) Watch the messages around the crossing.
- Expected: she says something about it in-character — a real relationship beat — without narrating any numbers or mechanics. Status: planned

---

## Coverage summary

- **Functional:** FR-005-01..28 — **70 automated tests** (2 per requirement, 3 for the 14 critical
  ones: FR-005-03, -04, -06, -08, -13, -14, -16, -17, -19, -20, -22, -24, -25, -27) across unit /
  integration / inter-service / data-flow / component / e2e / performance / load / security /
  consistency / concurrency / persistence, spanning happy / negative / boundary / error /
  idempotency / mapping / localization cases. **28/28 FR covered. ✓**
- **Non-functional:** NFR-005-01..13 — **32 tests** (2 per requirement, 3 for the 6 critical ones:
  NFR-005-01, -02, -04, -05, -06, -11) across performance / load / security / consistency /
  statistical / integration / error / persistence. **13/13 NFR covered. ✓**
- **User stories:** US-005-01..08 — **8 manual real-device acceptance tests**
  (TC-US-005-01-01 .. TC-US-005-08-01). **8/8 US covered. ✓**
- **Grand total: 110 enumerated tests** (70 FR + 32 NFR + 8 US) — within the 100-150 target band.
- Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies, matching the feature file's IDs, so
  coverage is traceable in both directions.
</content>
</invoke>
