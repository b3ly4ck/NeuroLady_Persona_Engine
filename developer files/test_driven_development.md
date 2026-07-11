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
- **End-to-end (automated)** — the whole flow driven programmatically (e.g. a scripted Telegram
  client sends `/start` and asserts on the reply).
- **Manual / real-device E2E** — a human runs the scenario by physically opening Telegram on
  their own computer/phone and following written steps. Used for things automation can't fully
  judge (does she *feel* human? does the photo *look* real?) and for final acceptance.
- **Non-functional** — performance/latency, load/scale, reliability/failover, security,
  privacy/compliance. These verify `NFR-` requirements.

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
