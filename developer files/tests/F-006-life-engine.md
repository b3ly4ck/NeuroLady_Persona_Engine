# Tests for F-006 — Life Engine (her own living: daily plan, self-reflection, biography & goals)

- **Feature:** [F-006 — Life Engine](../features/F-006-life-engine.md)
- **Approach:** Feature-granular coverage — **2-3 varied tests per requirement, 3 for the most
  critical ones** (self-consistency / no-contradiction, hierarchical compression pyramid, aging-up
  to gist, persona-shared-no-user-leak, timezone scheduling, degrade-on-failure) across all **21 FR
  (FR-006-01..21)** and all **13 NFR (NFR-006-01..13)**, plus one **manual real-device acceptance**
  test per user story (US-006-01..08). Cases vary across unit / integration / inter-service /
  data-flow / component / e2e / performance / load / security / consistency / statistical, and
  happy / negative / boundary / empty / error / concurrency / idempotency / persistence / mapping /
  localization. Because F-006 owns the persona's **own inner life** (not the reply itself), tests
  assert on **daily-plan generation, first-person self-reflection, hierarchical compression, aging
  to gist, fixed-anchor immutability & self-consistency, goals, timezone correctness, off-hot-path
  batching, degrade-keep-last-good-state, bounded storage, auditability, and RU/EN localization** —
  the reply *content* stays owned by F-002 and *storage* by F-004. The compression tests mirror
  UC-006-04's Scenario Outline. Target band 100-150; see `test_driven_development.md` §1. Every test
  ID embeds the `FR-`/`NFR-`/`US-` id it verifies.

> **Boundary note.** F-002 is the *consumer* of her current activity + biography; F-004 *stores /
> indexes / serves* the `DAILY_PLAN` / `REFLECTION` / `GOAL` / `BIOGRAPHY_LAYER` rows F-006 authors;
> F-005 owns the per-user *relationship* reflection; the media pipeline turns her plan into pixels /
> the proactive circle. Overlapping behaviors are tested here from the authoring side (plan /
> reflect / compress / goals / hand-off) and cross-referenced rather than duplicated.

---

## Functional requirements

### FR-006-01 — Each local morning, the Planner prompts the LLM for a free-text daily plan stored in DAILY_PLAN.plan_text (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-01-01 | integration | happy | Morning plan is generated and stored | Given a persona with a timezone; When her local morning arrives; Then the Planner produces a plan and stores it in `DAILY_PLAN.plan_text` | planned |
| TC-FR-006-01-02 | unit | mapping | Plan is a free-text schedule with rough times/locations | Given the generated plan; When inspected; Then it is free text describing activities across the day with rough times/locations | planned |
| TC-FR-006-01-03 | integration | idempotency | One plan per local day | Given a plan already generated today; When the morning job runs again the same day; Then no duplicate plan is created for that day | planned |

### FR-006-02 — Plan informed by fixed identity, current-era biography, goals, and previous-day continuity (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-02-01 | integration | happy | Plan inputs include identity, biography, goals | Given the persona's identity, current-era biography, and active goals; When the plan prompt is built; Then all are supplied as inputs | planned |
| TC-FR-006-02-02 | integration | happy | Plan carries continuity from the previous day | Given yesterday's plan/reflection; When today's plan is generated; Then it continues from it (not a random fresh day) | planned |
| TC-FR-006-02-03 | consistency | negative | Plan does not contradict fixed identity | Given fixed anchors; When the plan is generated; Then it stays consistent with them | planned |

### FR-006-03 — Plan exposed so the Orchestrator can include current activity and media can match the slot

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-03-01 | integration | happy | Current activity derived from plan + current time | Given today's plan and the current local time; When current activity is requested; Then "what she's doing now" is derived and exposed | planned |
| TC-FR-006-03-02 | inter-service | happy | Media Delivery can match media to the current slot | Given the exposed plan; When Media Delivery queries the current slot; Then it can match media to that activity | planned |

### FR-006-04 — No structured slot table: schedule is free text; current activity derived

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-04-01 | unit | happy | Schedule stored as free text, not slot rows | Given a stored plan; When inspected; Then it is free text in `plan_text` with no structured slot table | planned |
| TC-FR-006-04-02 | unit | boundary | Current activity computed from text + time | Given free-text plan and a timestamp; When current activity is derived; Then it is computed from parsing the text against the time | planned |

### FR-006-05 — At local end of day, the Reflector writes a first-person daily REFLECTION (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-05-01 | integration | happy | End-of-day reflection is written | Given the persona's day has ended in her timezone; When the Reflector runs; Then a daily `REFLECTION` is stored | planned |
| TC-FR-006-05-02 | unit | mapping | Reflection is first-person, from plan + what happened + prior lore | Given the reflection inputs; When generated; Then the text is first-person and derived from today's plan, events, and prior lore | planned |
| TC-FR-006-05-03 | integration | empty | Reflection still written on a quiet day | Given a day with little activity; When the Reflector runs; Then a coherent first-person reflection is still produced | planned |

### FR-006-06 — Self-reflection is about her own life, with no user-specific private facts (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-06-01 | integration | happy | Reflection describes her own life | Given her day; When the reflection is written; Then it is about her own life (plan/events/goals), first-person | planned |
| TC-FR-006-06-02 | security | negative | No user-specific private facts embedded | Given users shared private facts today; When the reflection is written; Then no user-specific fact ("user X told me Y") appears | planned |
| TC-FR-006-06-03 | security | boundary | At most generic non-identifying colour | Given chatty days; When reflected; Then only generic colour ("had some nice chats") is allowed, never identifying detail | planned |

### FR-006-07 — Daily reflections compress upward (7 daily→weekly, ~4 weekly→monthly, 12 monthly→yearly, years→epochs) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-07-01 | integration | boundary | UC-006-04 outline: 7 daily → 1 weekly | Given 7 daily reflections for a week; When compression runs; Then they summarize into one weekly layer | planned |
| TC-FR-006-07-02 | integration | boundary | UC-006-04 outline: 4 weekly → 1 monthly | Given ~4 weekly layers for a month; When compression runs; Then they summarize into one monthly layer | planned |
| TC-FR-006-07-03 | integration | boundary | UC-006-04 outline: 12 monthly → 1 yearly (and years → epoch) | Given 12 monthly layers; When compression runs; Then they summarize into one yearly layer, and years roll up to epochs | planned |

### FR-006-08 — Each compressed layer stored as BIOGRAPHY_LAYER and handed to Memory for storage + embedding (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-08-01 | unit | mapping | Layer carries scope + period_key | Given a compressed layer; When stored; Then it has `scope` in {epoch,year,month,week,day} and a `period_key` | planned |
| TC-FR-006-08-02 | inter-service | happy | Layer handed to Memory via POST /memory/biography-layer | Given a new layer; When compression completes; Then it is handed to Memory (F-004) for storage + embedding | planned |
| TC-FR-006-08-03 | integration | consistency | Layer becomes structurally + semantically queryable | Given the handed-off layer; When Memory indexes it; Then it is queryable by scope and by similarity | planned |

### FR-006-09 — Higher layers retain gist, not full detail (aging up; bounded storage) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-09-01 | integration | happy | Compressed layer keeps gist, drops fine detail | Given detailed daily reflections; When compressed to a higher layer; Then only summarized gist remains | planned |
| TC-FR-006-09-02 | integration | boundary | Older layers are coarser than recent ones | Given layers of different ages; When compared; Then older layers hold broader strokes than recent detailed ones | planned |
| TC-FR-006-09-03 | consistency | negative | Fine detail is not retained forever | Given long-aged reflections; When probed; Then fine day-level detail is no longer retained at high layers | planned |

### FR-006-10 — Compressed layers stay consistent with their lower reflections and the fixed identity (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-10-01 | consistency | happy | Weekly layer matches its 7 daily reflections | Given a weekly layer and its source dailies; When cross-checked; Then the summary does not contradict them | planned |
| TC-FR-006-10-02 | consistency | negative | No invented contradiction with fixed identity | Given compression; When a layer is produced; Then it introduces no contradiction with the fixed anchors | planned |
| TC-FR-006-10-03 | consistency | boundary | Coarse and fine layers are mutually consistent | Given a monthly and its weekly layers; When compared; Then the coarse layer stays consistent with the finer ones | planned |

### FR-006-11 — Persona maintains goals (description, status, priority, horizon) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-11-01 | unit | mapping | Goal carries the required fields | Given a stored `GOAL`; When inspected; Then it has description, status, priority, and horizon | planned |
| TC-FR-006-11-02 | integration | happy | Goals give her direction beyond reactivity | Given active goals; When the persona plans; Then her behavior reflects direction, not pure reactivity | planned |
| TC-FR-006-11-03 | persistence | happy | Goals persist across sessions | Given stored goals; When services restart; Then the goals are still present | planned |

### FR-006-12 — Goal-update step progresses/adds/completes/drops goals over time (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-12-01 | integration | happy | Goal-update progresses an existing goal | Given a goal and recent reflections; When the goal-update runs; Then the goal's progress/status advances appropriately | planned |
| TC-FR-006-12-02 | integration | happy | New goals appear; completed ones close | Given evolving reflections; When goal-update runs; Then new goals can be added and completed goals are closed | planned |
| TC-FR-006-12-03 | integration | boundary | Stale goal can be dropped | Given a goal no longer relevant; When goal-update runs; Then it can be dropped | planned |

### FR-006-13 — Active goals feed the daily plan and may surface naturally, never as a list

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-13-01 | integration | happy | Active goals inform tomorrow's plan | Given active goals; When the next plan is generated; Then it plans toward them | planned |
| TC-FR-006-13-02 | integration | negative | Goals never surface as a mechanical list | Given a goal referenced in chat context; When exposed; Then it appears as natural life colour, not a mechanical list | planned |
| TC-FR-006-13-03 | integration | consistency | Plan reflects goal changes across days | Given a goal that progresses/closes; When subsequent plans are generated; Then they track the changed goal state | planned |

### FR-006-14 — Fixed anchors (name, core values, Big Five, epoch layers) treated as immutable (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-14-01 | unit | happy | Anchors inform but are never overwritten | Given fixed anchors; When any plan/reflection/compression runs; Then it may read them but never rewrites them | planned |
| TC-FR-006-14-02 | consistency | negative | Generation never contradicts an anchor | Given a generation step; When output is produced; Then it does not contradict name/core values/Big Five/epoch layers | planned |
| TC-FR-006-14-03 | consistency | boundary | Anchors stable across a long generated history | Given a long run of days; When anchors are checked; Then they are unchanged throughout | planned |

### FR-006-15 — Evolving life never contradicts fixed anchors or earlier biography (self-consistency) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-15-01 | consistency | happy | Recent life is consistent with earlier layers | Given recent days/weeks; When checked against earlier biography; Then no contradiction is found | planned |
| TC-FR-006-15-02 | consistency | negative | No contradiction under adversarial probing | Given a skeptic cross-checking childhood vs last month vs last week; When probed; Then it all hangs together | planned |
| TC-FR-006-15-03 | consistency | boundary | Near-term colour never breaks an anchor | Given evolving current-era colour; When generated; Then it never conflicts with a fixed anchor | planned |

### FR-006-16 — Planning/reflection/compression scheduled against PERSONA.timezone (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-16-01 | integration | happy | Jobs fire at correct local times | Given a persona timezone; When the day progresses; Then the plan fires at local morning and reflection at local end-of-day | planned |
| TC-FR-006-16-02 | integration | boundary | Correct across different zones | Given personas in different timezones; When scheduled; Then each fires at its own correct local time | planned |
| TC-FR-006-16-03 | integration | boundary | Coordinated with the day/night compute window | Given the §6.1 compute schedule; When heavy work is scheduled; Then it lands in the intended window | planned |

### FR-006-17 — F-006 authors and hands off rows to Memory; does not implement storage

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-17-01 | inter-service | happy | Authored rows handed to Memory for persistence | Given authored plan/reflection/goal/layer; When produced; Then they are handed to Memory (F-004) to persist | planned |
| TC-FR-006-17-02 | unit | negative | F-006 does not own the store | Given the F-006 code path; When inspected; Then it delegates storage to F-004 rather than implementing it | planned |
| TC-FR-006-17-03 | integration | consistency | Hand-off round-trips back on query | Given a handed-off layer; When later queried; Then it round-trips back consistently from Memory | planned |

### FR-006-18 — Provide the "story from her day" narrative basis for the proactive video circle

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-18-01 | integration | happy | Narrative basis is available from plan + reflection | Given today's plan and reflection; When the proactive circle is scheduled; Then F-006 provides the "story from her day" basis | planned |
| TC-FR-006-18-02 | unit | negative | F-006 provides narrative, not the pixels | Given the narrative basis; When inspected; Then F-006 supplies the story text, not the generated video | planned |

### FR-006-19 — All Life-Engine prompts are versioned assets, not hard-coded (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-19-01 | unit | happy | Prompts loaded from the versioned asset directory | Given `plan_day`/`reflect_day`/`compress_*`/`update_goals`; When a job builds its prompt; Then it loads the versioned asset | planned |
| TC-FR-006-19-02 | unit | negative | No inline hard-coded prompt strings | Given the job code paths; When inspected; Then prompt text is not hard-coded inline | planned |
| TC-FR-006-19-03 | integration | boundary | Prompt version is recorded with each output | Given a generated output; When audited; Then the prompt version used is recorded | planned |

### FR-006-20 — On a failed LLM call, preserve last good state, retry, fall back to prior plan/biography (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-20-01 | integration | error | Failure preserves last good state (no empty day) | Given the LLM fails when a plan/reflection is due; When it fails; Then the last good state is preserved with no corruption or empty day | planned |
| TC-FR-006-20-02 | integration | error | Falls back to the prior plan/biography meanwhile | Given the failed job; When replies need current activity; Then the persona falls back to her prior plan/biography | planned |
| TC-FR-006-20-03 | integration | error | Job is retried later and applies on recovery | Given a failed job; When the LLM recovers; Then the job is retried and its output applied | planned |

### FR-006-21 — Every layer/reflection records what it was derived from and when (auditable) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-006-21-01 | integration | happy | Layer records source inputs and time | Given a compressed layer; When inspected; Then it records the source period/inputs and the time produced | planned |
| TC-FR-006-21-02 | integration | happy | Reflection records its derivation | Given a daily reflection; When inspected; Then it records what it was derived from and when | planned |
| TC-FR-006-21-03 | consistency | negative | No layer/reflection without provenance | Given the biography history; When audited; Then every entry has recorded provenance (no unexplained change) | planned |

---

## Non-functional requirements

### NFR-006-01 — Self-consistency (no contradictions with fixed identity or earlier layers, even adversarially) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-01-01 | consistency | happy | Long generated history has no internal contradiction | Given a long biography; When cross-checked across layers; Then no contradiction is found | planned |
| TC-NFR-006-01-02 | consistency | negative | Adversarial probing surfaces no contradiction | Given a skeptic probing across scopes; When cross-checked; Then nothing contradicts | planned |
| TC-NFR-006-01-03 | statistical | boundary | Contradiction rate below threshold over many probes | Given many probe pairs; When measured; Then the contradiction rate stays below the target threshold | planned |

### NFR-006-02 — Aliveness / freshness (life measurably progresses; not the same day on loop)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-02-01 | statistical | happy | New events/goals appear over time | Given weeks of the loop; When measured; Then new events and goal changes accumulate | planned |
| TC-NFR-006-02-02 | consistency | negative | Not the same day repeated | Given consecutive daily plans; When compared; Then they are not near-duplicates of one another | planned |

### NFR-006-03 — Never leaves her without a life (always a valid plan + coherent biography) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-03-01 | error | happy | A failed job degrades to the prior state, never "no day" | Given a failed plan job; When a reply needs current activity; Then a prior valid plan is served, never an empty day | planned |
| TC-NFR-006-03-02 | error | boundary | Always a coherent biography to serve | Given any moment, including during a failed compression; When biography is requested; Then a coherent biography is available | planned |
| TC-NFR-006-03-03 | error | negative | No user-visible gap in her life | Given repeated job failures; When users chat; Then no gap ("no day") surfaces to them | planned |

### NFR-006-04 — Off the reply hot path (scheduled batch, no reply latency)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-04-01 | performance | happy | Reply latency unaffected by Life-Engine jobs | Given planning/reflection/compression running; When replies are timed; Then reply latency is unaffected | planned |
| TC-NFR-006-04-02 | performance | boundary | Heavy work lands in the batch window | Given the night/window schedule; When heavy jobs run; Then they run as batch and do not block replies | planned |
| TC-NFR-006-04-03 | performance | error | Reply path unblocked even if a batch job overruns | Given a Life-Engine job overrunning its window; When replies occur; Then reply latency is still unaffected | planned |

### NFR-006-05 — Privacy (no user-specific private facts in the shared life story; provable) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-05-01 | security | negative | No per-user fact leaks into biography | Given many users' private facts; When biography/reflection is generated; Then none of those facts appear | planned |
| TC-NFR-006-05-02 | security | happy | Biography is the same shared story across users | Given two users; When each sees her life story; Then it is the same shared content | planned |
| TC-NFR-006-05-03 | security | boundary | Provable isolation of user data from the life story | Given an audit of the life story; When checked; Then it provably contains no user-specific data | planned |

### NFR-006-06 — Bounded storage / realistic memory (compression aging, not unbounded accumulation) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-06-01 | load | boundary | Storage stays bounded as time passes | Given a long-running persona; When storage is measured over time; Then it stays bounded via compression | planned |
| TC-NFR-006-06-02 | consistency | happy | Old detail ages to gist rather than accumulating | Given aged reflections; When inspected; Then fine daily detail has been summarized, not retained in full | planned |
| TC-NFR-006-06-03 | load | boundary | Growth is sub-linear vs raw daily volume | Given many days; When compared to raw daily counts; Then stored biography grows sub-linearly | planned |

### NFR-006-07 — Time correctness (jobs fire at right local times, incl. DST and different zones) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-07-01 | integration | happy | Correct local morning/end-of-day firing | Given a timezone; When the day passes; Then jobs fire at the right local times | planned |
| TC-NFR-006-07-02 | integration | boundary | Correct across a DST transition | Given a DST change; When jobs are scheduled; Then they still fire at the intended local time | planned |
| TC-NFR-006-07-03 | integration | boundary | Correct for personas in different zones | Given personas across zones; When scheduled; Then each fires per its own zone | planned |

### NFR-006-08 — Scales across the roster (loop runs for all 10 personas within the budget) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-08-01 | load | boundary | All 10 personas' loops fit the compute budget | Given 10 personas; When the loop runs; Then all complete within the scheduled compute budget | planned |
| TC-NFR-006-08-02 | load | error | Loop does not starve the day-time reply path | Given the full roster running; When day-time replies occur; Then the reply path is not starved | planned |
| TC-NFR-006-08-03 | load | boundary | Coordinates with the §6.1 day/night schedule | Given the compute schedule; When jobs run; Then they coordinate with the day/night windows | planned |

### NFR-006-09 — Auditability (every change traceable to its inputs and time) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-09-01 | integration | happy | Every plan/reflection/goal/layer traces to inputs+time | Given any change; When audited; Then it traces to the inputs and time that produced it | planned |
| TC-NFR-006-09-02 | consistency | negative | No unexplained change in the life story | Given the audit trail; When reconciled; Then there is no change without a recorded derivation | planned |
| TC-NFR-006-09-03 | integration | boundary | Audit trail links each layer to its source period | Given a biography layer; When its audit record is followed; Then it links to the exact source reflections/period it compressed | planned |

### NFR-006-10 — Persistence (all Life-Engine state survives restarts/deploys) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-10-01 | persistence | happy | Plans/reflections/goals/layers survive a restart | Given stored Life-Engine state; When services restart; Then all of it is intact | planned |
| TC-NFR-006-10-02 | persistence | boundary | Continuity of her life across weeks | Given a long gap; When the persona resumes; Then her accumulated life is preserved | planned |
| TC-NFR-006-10-03 | persistence | consistency | State intact across a deploy | Given a redeploy; When probed; Then plans, biography, and goals are unchanged | planned |

### NFR-006-11 — Configurable, no redeploy (ratios, schedule times, prompt versions, cadence)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-11-01 | integration | happy | Compression ratios/schedule/cadence read from config | Given edited config; When the loop runs; Then the new values take effect without code changes | planned |
| TC-NFR-006-11-02 | integration | boundary | Prompt version switch takes effect via config | Given a new prompt version in config; When a job runs; Then it uses the new version without a redeploy | planned |

### NFR-006-12 — Reproducibility (loop documented/inspectable enough to reproduce/evaluate)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-12-01 | consistency | happy | Same inputs + prompt version reproduce the recipe | Given identical inputs and prompt version; When the loop is documented/inspected; Then the plan→reflect→compress→goals recipe is reproducible | planned |
| TC-NFR-006-12-02 | integration | boundary | Fixed-vs-evolving split is inspectable | Given the loop; When inspected; Then the fixed-anchor vs evolving-life split is legible and auditable | planned |

### NFR-006-13 — Localization (plan/reflection/biography generated in the persona's language, natural first-person)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-006-13-01 | integration | localization | RU persona generates natural Russian first-person | Given a Russian persona; When plan/reflection/biography are generated; Then they read as natural first-person Russian | planned |
| TC-NFR-006-13-02 | integration | localization | EN persona generates natural English; no mixed language | Given an English persona; When generated; Then output is natural English with no machine-stilted or mixed-language text | planned |

---

## Biography extension — seeded biography, persona-time & future-self (FR-006-22..28, NFR-006-14/15)

### FR-006-22 — Seeded initial biography (imported at provisioning, idempotent) (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-22-01 | integration | happy | Seeding imports layers across every scope | Given a persona with an authored biography; When seeded; Then BIOGRAPHY_LAYER rows exist at scope epoch/year/month/week/day | automated |
| TC-FR-006-22-02 | integration | idempotency | Re-seeding does not duplicate layers | Given an already-seeded persona; When seeded again; Then no layer is duplicated (same count) | automated |
| TC-FR-006-22-03 | integration | happy | Childhood/youth epoch anchors are present | Given a seeded persona; When epoch layers are read; Then period_key childhood and youth exist with content | automated |

### FR-006-23 — Fixed identity anchors as structured persona fields
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-23-01 | unit | happy | Persona carries birthdate/core_values/motivation | Given a seeded persona; When its anchors are read; Then birthdate, core_values, motivation are set | automated |
| TC-FR-006-23-02 | consistency | mapping | Anchors appear verbatim in the identity prompt | Given a persona with anchors; When the identity prompt is built; Then values/motivation text is present verbatim | automated |

### FR-006-24 — Birthdate-derived, daily-versioned age ("persona-time")
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-24-01 | unit | happy | Age derived as "N years and M days" | Given birthdate and a current date; When age is computed; Then it reads "N years and M days" | automated |
| TC-FR-006-24-02 | unit | boundary | Exact on birthday and the day after | Given the current date is the birthday; When computed; Then M=0, and the next day M=1 | automated |
| TC-FR-006-24-03 | unit | boundary | Leap-day birthdate handled without error | Given a Feb-29 birthdate; When computed on a non-leap year; Then it resolves without error | automated |

### FR-006-25 — Evolving persona-time fields (interests + current goal) in identity
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-25-01 | unit | happy | Interests + current goal injected into identity | Given a persona with interests and an active goal; When the identity prompt is built; Then both appear | automated |
| TC-FR-006-25-02 | integration | happy | Changing interests changes the prompt (not fixed) | Given the interests are updated; When the prompt is rebuilt; Then it reflects the new interests | automated |

### FR-006-26 — Future-self projections (week/month/year/epoch/lifetime)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-26-01 | integration | happy | Seeding stores all five horizons | Given an authored future-self; When seeded; Then FUTURE_PROJECTION rows exist for week/month/year/epoch/lifetime | automated |
| TC-FR-006-26-02 | integration | idempotency | One row per horizon (upsert) | Given a re-seed; When projections are counted; Then there is exactly one per horizon | automated |

### FR-006-27 — Biography served into every reply (graded + semantic, no anchor contradiction) (CRITICAL)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-27-01 | integration | happy | Reply context includes the graded recency block | Given a seeded persona; When a turn is assembled; Then the system prompt carries the graded epoch→year→month→week→days summary | automated |
| TC-FR-006-27-02 | integration | happy | A childhood question retrieves the childhood epoch | Given a semantic index; When the user asks about her childhood; Then the childhood epoch layer is recalled into context | automated |
| TC-FR-006-27-03 | consistency | boundary | Served biography is present and does not contradict anchors | Given the assembled context; When inspected; Then the biography block is present and the fixed anchors are unchanged | automated |

### FR-006-28 — Future-self served into reply context when relevant
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-28-01 | integration | happy | Future-self available in the reply context | Given seeded projections; When a turn is assembled; Then a "where she's heading" block is present | automated |
| TC-FR-006-28-02 | integration | negative | No projections → block absent (degrade) | Given a persona with no projections; When a turn is assembled; Then no future-self block is added and the turn still works | automated |

### FR-006-29 — She always knows her own local clock (reply context carries local date/time)

| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-29-01 | integration | happy | Current local time line present in the turn context | Given a persona in Europe/Moscow at a fixed UTC instant; When the turn context is assembled; Then it contains her local weekday + approximate time of day | automated |
| TC-FR-006-29-02 | unit | boundary | Clock line is timezone/DST-correct per persona | Given personas in different zones at one UTC instant; When each context is built; Then each carries its own correct local time | automated |
| TC-FR-006-29-03 | e2e | manual | She answers "what time is it for you?" correctly | Given a live chat in a known timezone gap; When asked about her time of day; Then her answer matches her local clock (live-caught regression: said "noon" at 19:00) | planned |

### FR-006-30 — Daily plans are time-addressable (parseable HH:MM markers)

| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-FR-006-30-01 | unit | happy | Plan prompt demands clock-marked entries | Given the current plan prompt asset; When inspected; Then it instructs explicit HH:MM markers for the day's activities | automated |
| TC-FR-006-30-02 | integration | happy | A marker-formatted plan slots correctly | Given a plan with HH:MM markers; When current_activity runs at a covered time; Then the matching slot (not the whole text) is returned | automated |

### NFR-006-14 — Persona-time determinism (daily-versioned, stable within a day)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-006-14-01 | consistency | happy | Same date + state → identical identity block | Given fixed date and state; When the identity prompt is built twice; Then the two outputs are identical | automated |
| TC-NFR-006-14-02 | consistency | boundary | Next local day increments the age by one day | Given the local date advances by one day; When rebuilt; Then the derived age gains exactly one day | automated |

### NFR-006-15 — Bounded biography context (length-capped for the reply budget)
| TC | level | case | title | Gherkin | status |
|----|-------|------|-------|---------|--------|
| TC-NFR-006-15-01 | performance | boundary | Served biography stays under the length bound | Given a persona with a long history; When the biography block is built; Then its length is under the configured bound | automated |
| TC-NFR-006-15-02 | performance | boundary | Graded block caps the number of layers | Given many layers per scope; When the graded block is built; Then the number of included layers is bounded | automated |

---

## User-story acceptance (manual real-device E2E)

One manual acceptance test per user story — judges the felt "she has a real, consistent, moving
life" quality that automation can't fully score.

**TC-US-006-01-01 (manual-e2e) — A2: she has her own day and brings it up unprompted**
- Preconditions: bot deployed; Telegram on your phone.
- Steps: 1) Message her in the evening. 2) Let the conversation open naturally.
- Expected: she mentions details from a day she's been "living" (e.g. wiped after the gym, long day at work) that fit a coherent schedule. Status: planned

**TC-US-006-02-01 (manual-e2e) — A8 skeptic: her biography stays consistent under probing**
- Steps: 1) Ask about her childhood, then her job last month, then a story from last week. 2) Deliberately cross-check coarse vs fine.
- Expected: it all hangs together as one coherent life; you cannot catch a contradiction. Status: planned

**TC-US-006-03-01 (manual-e2e) — A1: an evolving storyline over weeks**
- Steps: 1) Chat across several weeks. 2) Track her life events over time.
- Expected: her life visibly progresses (a work project, a trip, a new hobby) — not the same day on loop. Status: planned

**TC-US-006-04-01 (manual-e2e) — A2/A4: she has direction and goals**
- Steps: 1) Ask what she's working toward. 2) Return weeks later and ask again.
- Expected: she names something she's pursuing, and weeks later it has progressed — she has her own arc. Status: planned

**TC-US-006-05-01 (manual-e2e) — Returning user: her life continued while away**
- Steps: 1) Chat, then stay away ~two weeks. 2) Return and ask what's new.
- Expected: she has news — things happened in her life meanwhile; she didn't freeze in place. Status: planned

**TC-US-006-06-01 (manual-e2e) — A6: stable, predictable identity as life evolves**
- Steps: 1) Over time, note her core self (values, personality, where she's from). 2) Watch whether it drifts as her day-to-day changes.
- Expected: her core identity stays constant and recognizable; only her day-to-day evolves. Status: planned

**TC-US-006-07-01 (manual-e2e) — Any user: "doing right now" matches a real daily rhythm**
- Steps: 1) Message her at midday. 2) Message again late evening. 3) (If possible) late at night.
- Expected: midday she's a bit distracted "at work", evening relaxed and chatty, night winding down/asleep — a believable rhythm. Status: planned

**TC-US-006-08-01 (manual-e2e) — Group C researcher: the mechanism is coherent and inspectable**
- Preconditions: access to the feature/architecture docs and the biography/goal history.
- Steps: 1) Walk the plan→reflect→compress→goals loop in the docs. 2) Inspect a persona's biography layers and goal history.
- Expected: the loop and the fixed-vs-evolving split are documented and auditable as a reproducible recipe. Status: planned

---

## Coverage summary

- **Functional:** FR-006-01..21 — **60 automated tests** (2 per requirement, 3 for the 18 critical
  ones: FR-006-01, -02, -05, -06, -07, -08, -09, -10, -11, -12, -13, -14, -15, -16, -17, -19, -20,
  -21; the simpler FR-006-03, -04, -18 at 2) across unit / integration / inter-service / data-flow /
  component / e2e / performance / load / security / consistency / persistence, spanning happy /
  negative / boundary / empty / error / idempotency / mapping / localization cases.
  **21/21 FR covered. ✓**
- **Non-functional:** NFR-006-01..13 — **35 tests** (2 per requirement, 3 for the 9 critical ones:
  NFR-006-01, -03, -04, -05, -06, -07, -08, -09, -10) across performance / load / security /
  consistency / statistical / integration / error / persistence. **13/13 NFR covered. ✓**
- **User stories:** US-006-01..08 — **8 manual real-device acceptance tests**
  (TC-US-006-01-01 .. TC-US-006-08-01). **8/8 US covered. ✓**
- **Biography extension (FR-006-22..28, NFR-006-14/15):** **21 automated tests** — seeded biography
  import + idempotency (FR-006-22 ×3), anchors-as-fields (FR-006-23 ×2), birthdate-derived versioned
  age incl. birthday/leap boundaries (FR-006-24 ×3), evolving interests/goal in identity
  (FR-006-25 ×2), future-self horizons + upsert (FR-006-26 ×2), biography-served graded + semantic +
  no-anchor-contradiction (FR-006-27 ×3), future-self served + degrade (FR-006-28 ×2), persona-time
  determinism (NFR-006-14 ×2), bounded biography context (NFR-006-15 ×2). All **automated** (fast,
  no live model).
- **Grand total: 129 enumerated tests** (86 FR + 37 NFR + 8 US: FR-006-01..30, NFR-006-01..15,
  US-006-01..08) — within the 100-150 target band.
- Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies, matching the feature file's IDs, so
  coverage is traceable in both directions.
</content>
