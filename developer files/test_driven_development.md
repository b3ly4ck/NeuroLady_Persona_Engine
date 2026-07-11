# How to Write Tests — Test-Driven Development Guide

This guide defines how tests are designed and documented for NeuroLady. It is the companion to
`feature_description_guide.md`: features define **requirements**, and this guide defines how each
requirement is covered by tests.

Read this guide (and the relevant feature file) before writing any tests or any code that a test
will cover.

---

## 1. Core principles

- **Every requirement gets a *set* of tests, never a single one.** For each functional (`FR-`)
  and non-functional (`NFR-`) requirement, write a whole battery of tests covering every case
  you can think of — happy path, negative inputs, boundaries, edge cases, error/failure modes,
  concurrency, localization, etc.
- **Aim for exhaustive coverage.** Enumerate *all plausible* behaviors, not just the obvious one.
  A mature project may have thousands — even 10,000+ — tests. That is normal and desired, not a
  problem. More coverage is better.
- **Every test traces to a requirement.** Each test's ID embeds the requirement ID it verifies,
  so we always know which requirement a failing test protects.
- **Tests span multiple levels and categories** (unit → integration → end-to-end → manual
  real-device → non-functional). A requirement is not "covered" until it has tests at the levels
  that make sense for it.
- **Design tests before/alongside the code** (test-driven): the test spec for a feature exists
  before the feature is merged, and the code is written to make those tests pass.
- **Tests are the bridge between requirements and architecture.** A requirement says *what* must
  be true; the architecture (`architecture.md`) says *which services, data stores, AI services,
  and flows* realize it. Tests must cover **both** — not only isolated units, but the
  **integration and inter-service paths, the data flows (DFDs), and the end-to-end journeys**
  through the architecture. For every architectural flow, cover **as many scenarios as possible**.

---

## 2. Where tests live (two distinct places)

| What | Where | Format |
|------|-------|--------|
| **Test specifications** (the design: every test enumerated, described, traced to a requirement) | `developer files/tests/` — one `.md` per feature | Markdown, this guide's format |
| **Test code** (the actual runnable tests) | repo-root `tests/` folder | code (per project stack) |

- Each feature file `developer files/features/F-<NNN>-<slug>.md` has a mirror test spec
  `developer files/tests/F-<NNN>-<slug>.md` describing **all** tests for that feature.
- The runnable test code in the repo-root `tests/` folder is what the merge rule in `CLAUDE.md`
  refers to ("a feature branch may only be merged into `master` after all tests in `tests/`
  pass"). Test code should reference the test IDs from the spec (in the test name or an
  annotation/comment) so coverage is traceable both ways.

---

## 3. Test ID scheme (traceability to requirements)

Test IDs are built directly from the requirement they verify:

```
TC-<requirement-id>-<nn>
```

- `<requirement-id>` is the full requirement ID, e.g. `FR-001-02` or `NFR-001-01`.
- `<nn>` is a two-digit sequence for the multiple tests of that requirement (`01`, `02`, …).

Examples:
- `TC-FR-001-02-01`, `TC-FR-001-02-02`, `TC-FR-001-02-03` — three different tests, all verifying
  functional requirement `FR-001-02`.
- `TC-NFR-001-01-01`, `TC-NFR-001-01-02` — two tests verifying non-functional requirement
  `NFR-001-01`.

Rules:
- Every test verifies **exactly one primary requirement** (the one in its ID). It may touch
  others, but it's owned by one.
- IDs are **immutable** once written. Retire a test as `DEPRECATED`; never reuse its ID.
- Every requirement must end up with **at least several** `TC-` tests (see §6 minimum coverage).

---

## 4. Test levels

Pick every level that applies to a requirement — most functional requirements deserve tests at
several levels.

- **Unit** — a single function/module in isolation, dependencies mocked. Fast, many of them.
- **Integration** — several components together (e.g. dialogue engine + memory store), real
  wiring, external services stubbed.
- **Component / API** — a service or bot handler exercised through its interface.
- **Inter-service / contract** — two or more services exercised across their real boundary
  (the API contracts in `architecture.md` §2), verifying the composed path and each hop.
- **End-to-end (automated)** — the whole flow driven programmatically (e.g. a scripted Telegram
  client sends `/start` and asserts on the reply).
- **Manual / real-device E2E** — a human runs the scenario by physically opening Telegram on
  their own computer/phone and following written steps. Used for things automation can't fully
  judge (does she *feel* human? does the photo *look* real?) and for final acceptance.
- **Non-functional** — performance/latency, load/scale, reliability/failover, security,
  privacy/compliance. These verify `NFR-` requirements.

---

## 4b. Architecture-driven testing (tests as the bridge to `architecture.md`)

Requirements alone don't tell you every path that can break — the **architecture** does. When
writing a feature's tests, walk the architecture (`architecture.md`) and cover **every scenario**
each relevant piece can produce. This is where **integration, inter-service, and end-to-end**
tests come from.

For each feature, map its requirements onto the architecture and add tests for:

- **Inter-service / integration paths.** Every service boundary the feature crosses gets tested
  together (real wiring, external/heavy deps stubbed). E.g. Bot Gateway → Orchestrator →
  Memory → Chat LLM → Media Delivery. Test each hop *and* the composed path.
- **API contracts.** Each internal endpoint the feature uses (§2 of `architecture.md`) gets
  contract tests: schema, auth/entitlement, idempotency keys, error responses.
- **Data-flow coverage (DFDs).** Reproduce each relevant DFD from `architecture.md` end-to-end
  and assert the data lands correctly:
  - *DFD-1 (conversation turn):* context assembly includes the recent raw messages + retrieved
    facts + relationship state; reply persists; facts get extracted; media-intent routes correctly.
  - *DFD-2 (life cycle):* plan → schedule → reflection → hierarchical compression
    (day→week→month→year→epoch) → goals/relationship updates all persist and chain correctly.
  - *DFD-3 (night media):* sleep → chat LLM unloaded → GPU freed → image/video jobs run → assets
    tagged with pose/background/location/intimacy → archive + `MEDIA_ASSET` rows → wake reloads
    chat LLM. Test the transitions and failure/rollback of each.
- **End-to-end journeys.** Full user journeys through the UX (§1) and the stack: `/start` →
  gallery → pick persona → video-note intro → chat → ask for photo/video → switch woman →
  main menu → subscription. Automated e2e where possible, **manual real-device e2e** for realism
  acceptance (does she feel human, does the media look real).
- **Cross-subsystem consistency.** e.g. media served matches the *current schedule slot*; the LLM
  "knows" what it sent (pose/background metadata) for sexting continuity; biography query returns
  the right layer; day/night switch never leaves the persona with an empty media archive.
- **Data-integrity & relationships (ERD).** Referential integrity, correct linkage across
  entities (SESSION↔MESSAGE↔MEDIA_ASSET, PERSONA↔BIOGRAPHY_LAYER, RELATIONSHIP↔reflection), and
  vector/object-store references resolve.

Rule of thumb: **cover all scenarios the architecture makes possible** for the feature — every
service hop, every branch of every DFD, every state transition — not just the requirement's happy
path. If the architecture introduces a path, there is a test for it.

---

## 5. Enumerate every case: the coverage checklist

For **each requirement**, walk this checklist and write a test for every item that applies. This
is how one requirement produces a whole set of tests.

- **Happy path** — the normal, valid case succeeds.
- **Negative / invalid input** — bad, malformed, or disallowed input is rejected gracefully.
- **Boundary / limits** — smallest/largest/first/last valid values, and just outside them.
- **Empty / null / missing** — missing message, empty history, no companion assigned, etc.
- **Error & failure modes** — dependency down, timeout, API error, partial failure, retries.
- **Concurrency / races** — simultaneous messages, double taps, parallel requests.
- **State & persistence** — correct state transitions; data survives restart/reconnect.
- **Idempotency** — repeating an action (resend, retry) doesn't corrupt state.
- **Localization / language** — behavior in Russian and other target languages.
- **Security / permissions** — only valid users/credentials succeed; abuse is blocked.
- **Compliance** (where relevant) — age/consent gating for intimate content, jurisdiction rules.
- **Performance** — latency/throughput under normal and heavy load (for the relevant NFRs).
- **Cross-device / channel** — different Telegram clients (mobile/desktop/web), weak network.
- **Inter-service path** — the composed path across every service boundary the requirement
  crosses (see §4b).
- **Data flow** — each relevant DFD from `architecture.md` reproduced end-to-end (see §4b).
- **Regression** — a test pinned to any bug once found, so it never comes back.

If you can imagine a way the requirement could break or a condition under which it must hold,
there should be a test for it.

---

## 6. Minimum coverage per requirement

A requirement is not "done" until, at minimum:

- **Functional (`FR-`)**: at least a happy-path test **plus** several negative/edge/error tests,
  at **≥2 levels** (e.g. unit + integration, and an e2e for user-visible flows).
- **Non-functional (`NFR-`)**: at least one test that directly checks the constraint, plus a
  boundary test and a behavior-under-stress/failure test where meaningful.
- **User-facing flows**: at least one **manual / real-device E2E** acceptance test.

More is always welcome — treat these as the floor, not the target.

---

## 7. Format of a per-feature test spec file

Each `developer files/tests/F-<NNN>-<slug>.md` file contains:

### 7.0 — Header
- Feature ID & title, and a link to the feature file.
- One-line note on overall test approach/coverage.

### 7.1 — Tests grouped by requirement
For **every** requirement in the feature, a subsection listing its full set of tests. Automated
tests use a table; manual tests use a steps block.

**Automated test table columns:**

| Column | Meaning |
|--------|---------|
| Test ID | `TC-<requirement-id>-<nn>` |
| Level | unit / integration / component / e2e / performance / security |
| Case | happy / negative / boundary / empty / error / concurrency / … |
| Description | what this test checks, in one line |
| Given / When / Then | the concrete condition, action, expected outcome |
| Status | planned / implemented / passing / failing / deprecated |

**Manual test block fields:** Test ID, Level (`manual-e2e`), Preconditions, Steps (numbered,
what to physically do in Telegram), Expected result, Status.

### 7.2 — Coverage summary
A short note (or matrix) confirming every requirement has its minimum set of tests.

---

## 8. Copy-paste template

> Wrapped in `~~~` fences so the inner ` ``` ` blocks display correctly; use normal backticks in
> the real file.

~~~markdown
# Tests for F-<NNN> — <Feature title>

- **Feature:** [F-<NNN> — <title>](../features/F-<NNN>-<slug>.md)
- **Approach:** <one line on how this feature is tested and how exhaustive the coverage is>

## FR-<NNN>-01 — <requirement text>

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-<NNN>-01-01 | unit | happy | <...> | Given <...> When <...> Then <...> | planned |
| TC-FR-<NNN>-01-02 | unit | negative | <...> | Given <...> When <...> Then <...> | planned |
| TC-FR-<NNN>-01-03 | integration | error | <...> | Given <...> When <...> Then <...> | planned |
| TC-FR-<NNN>-01-04 | e2e | happy | <...> | Given <...> When <...> Then <...> | planned |

**Manual — TC-FR-<NNN>-01-05 (manual-e2e)**
- Preconditions: <...>
- Steps:
  1. Open Telegram on your computer and start the bot.
  2. <...>
- Expected: <...>
- Status: planned

## NFR-<NNN>-01 — <requirement text>

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-<NNN>-01-01 | performance | happy | <...> | Given <...> When <...> Then <...> | planned |
| TC-NFR-<NNN>-01-02 | performance | boundary | <...> | Given <...> When <...> Then <...> | planned |
| TC-NFR-<NNN>-01-03 | performance | error | under failure/load | Given <...> When <...> Then <...> | planned |

## Coverage summary
- FR-<NNN>-01: <n> tests across <levels> ✓
- NFR-<NNN>-01: <n> tests ✓
~~~

---

## 9. Worked example (tests for the F-000 onboarding example)

Showing how a single requirement expands into a *set* of tests across levels and cases.

### FR-000-01 — The user must be able to start the bot with `/start` and receive an opening message

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-000-01-01 | unit | happy | `/start` handler returns an opening message | Given a new user; When `/start` is handled; Then an opening message object is produced | planned |
| TC-FR-000-01-02 | unit | empty | `/start` with no prior state still works | Given no stored user; When `/start`; Then onboarding is triggered | planned |
| TC-FR-000-01-03 | integration | happy | handler + companion assignment + sender wired together | Given the bot is running; When `/start` arrives; Then a companion is assigned and one message is sent | planned |
| TC-FR-000-01-04 | integration | error | messaging backend is down | Given the send API fails; When `/start`; Then the error is handled and retried, no crash | planned |
| TC-FR-000-01-05 | e2e | happy | scripted client sends `/start`, asserts a reply arrives | Given an automated Telegram client; When it sends `/start`; Then it receives exactly one in-character opening message | planned |
| TC-FR-000-01-06 | e2e | concurrency | two `/start` in quick succession | Given a user; When `/start` is sent twice fast; Then only one companion/onboarding results (idempotent) | planned |
| TC-FR-000-01-07 | integration | localization | Russian-language opening | Given a Russian-locale user; When `/start`; Then the opening message is in natural Russian | planned |

**Manual — TC-FR-000-01-08 (manual-e2e)**
- Preconditions: the bot is deployed; you have Telegram on your computer.
- Steps:
  1. Open Telegram on your computer and find the bot.
  2. Press Start / send `/start`.
  3. Read the opening message.
- Expected: within a moment a warm, natural, in-character greeting arrives that does not read as
  a robotic template.
- Status: planned

### NFR-000-01 — The opening message after `/start` must be delivered in under 3 seconds

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-000-01-01 | performance | happy | measure latency under normal conditions | Given a running bot; When `/start` is sent; Then the opening message arrives in < 3s | planned |
| TC-NFR-000-01-02 | performance | boundary | p95 latency across many runs stays under budget | Given 1000 `/start` calls; When measured; Then p95 < 3s | planned |
| TC-NFR-000-01-03 | performance | error | latency under heavy concurrent load | Given many simultaneous new users; When they `/start`; Then latency stays within the agreed degraded budget | planned |

*(Every other requirement in F-000 — FR-000-02..04, NFR-000-02..03 — would be expanded the same
way, each into its own set of tests.)*

---

## 10. Checklist before a feature's tests are "done"
- [ ] A `developer files/tests/F-<NNN>-<slug>.md` exists, mirroring the feature file.
- [ ] **Every** `FR-` and `NFR-` requirement has its own subsection.
- [ ] Each requirement has a **set** of tests (never just one), following the coverage checklist.
- [ ] Each requirement meets the minimum coverage (levels + case variety) in §6.
- [ ] Every user-facing flow has at least one manual / real-device E2E test.
- [ ] Every test has a unique `TC-` ID that embeds its requirement ID.
- [ ] Test code in the repo-root `tests/` folder references these IDs and all passes before merge.
