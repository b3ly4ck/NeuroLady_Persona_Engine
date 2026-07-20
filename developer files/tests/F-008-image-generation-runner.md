# Tests for F-008 — Image Generation Runner (self-hosted batch engine)

- **Feature:** [F-008 — Image Generation Runner](../features/F-008-image-generation-runner.md)
- **Approach:** 2–3 varied tests per requirement, 3 for the critical ones (job→asset, 1:1 file/row,
  atomic-no-half-file, idempotency, retry/degrade, GPU day/night handoff, never-empty-archive,
  off-hot-path, model swappability), plus one **manual real-device / GPU acceptance** per user story.
  Levels span unit / integration / inter-service / data-flow / component / e2e / performance / load /
  consistency / persistence; realism + throughput-in-window are GPU/human-judged (the F-008 A/B
  benchmark + acceptance), marked as such. Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies.

> **Boundary note.** F-010 authors the prompt, F-009 the reference-conditioning policy, F-011
> enqueues the batch, F-012 serves it. These tests assert the **engine + job lifecycle** side
> (generate → atomically store → tag → 1:1 → idempotent → retry → GPU handoff) and cross-reference
> rather than duplicate. Actual pixel realism is judged by the A/B benchmark (`image/benchmark.py`) +
> human acceptance, not a fast unit test.

---

## Functional requirements

### FR-008-01 — Self-hosted isolated runner behind a fixed job API (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-01-01 | unit | happy | Job API accepts a well-formed job | Given the runner's job contract; When a valid job is submitted; Then it is accepted and queued | implemented |
| TC-FR-008-01-02 | component | mapping | Callers don't import model code | Given the job API; When inspected; Then callers use the network/job interface, not model internals (§6.2c) | implemented |
| TC-FR-008-01-03 | unit | negative | Malformed job rejected cleanly | Given a job missing required fields; When submitted; Then it is rejected with a defined error, not a crash | implemented |

### FR-008-02 — Persona-agnostic

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-02-01 | integration | happy | Generates for any persona from the payload | Given jobs for two different personas; When run; Then each asset is stored under its own persona | implemented |
| TC-FR-008-02-02 | unit | negative | No persona hard-coded | Given the runner code; When inspected; Then no persona name/id is hard-coded | implemented |

### FR-008-03 — Model swappable behind the fixed API (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-03-01 | integration | happy | Same job runs on model A and B | Given the same job; When run against candidate A then B; Then both produce a valid asset via the same contract | implemented |
| TC-FR-008-03-02 | unit | mapping | Model chosen by config | Given a model-choice config; When the runner starts; Then it loads the configured model without code change | implemented |
| TC-FR-008-03-03 | component | consistency | Swap leaves job/asset schema unchanged | Given a model swap; When jobs run; Then the job contract and MEDIA_ASSET schema are identical | implemented |

### FR-008-04 — Generate on GPU at low distilled step count

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-04-01 | integration | happy | Image produced at 4–8 steps | Given a job with steps in {4,6,8}; When run; Then an image is generated at that step count | implemented |
| TC-FR-008-04-02 | component | boundary | Step count honored | Given steps=4 vs 8; When run; Then the pipeline uses exactly that many denoising steps | implemented |

### FR-008-05 — Reference passed to the model as conditioning

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-05-01 | integration | happy | Reference forwarded to the model | Given a job with a reference image; When generating; Then the reference is supplied to the img-edit model as input | implemented |
| TC-FR-008-05-02 | unit | empty | Missing reference handled | Given a job without a reference; When run; Then a defined behavior (reject or text-to-image per config), no crash | implemented |
| TC-FR-008-05-03 | integration | happy | All references fed, not just the first | Given a job with face+fullbody references; When the workflow is built; Then BOTH are bound (image1, image2), ordered | implemented |
| TC-FR-008-05-04 | unit | boundary | Reference count capped at the model limit | Given 4+ references; When built; Then only the first 3 are bound (node limit), no crash | implemented |

### FR-008-06 — Generation params in job/config, not hard-coded

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-06-01 | unit | happy | Steps/CFG/resolution/seed/negative read from job | Given params in the job; When generating; Then each is applied | implemented |
| TC-FR-008-06-02 | unit | negative | No inline hard-coded params | Given the runner code; When inspected; Then generation params come from job/config | implemented |
| TC-FR-008-06-03 | integration | idempotency | Fixed seed → reproducible image | Given the same seed+params+reference+prompt; When run twice; Then output is reproducible | implemented |

### FR-008-07 — File named by MED-id, 1:1 with the row (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-07-01 | integration | happy | File written under media/<slug>/photos/ named MED-id | Given a completed job; When stored; Then media/<slug>/photos/<MED-id>.png exists | implemented |
| TC-FR-008-07-02 | consistency | mapping | File name equals MEDIA_ASSET.id | Given the asset; When compared; Then the file stem equals the row id (MED-<persona>-<nnnnn>) | implemented |
| TC-FR-008-07-03 | consistency | boundary | Exactly one file per one row | Given N assets; When reconciled; Then each row has exactly one file and vice versa | implemented |

### FR-008-08 — MEDIA_ASSET row with full metadata

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-08-01 | integration | happy | Row carries kind/intimate/intimacy/storage_ref/meta | Given a stored asset; When inspected; Then the row has kind=photo, intimate, intimacy_level, storage_ref, meta_json | implemented |
| TC-FR-008-08-02 | unit | mapping | meta_json holds pose/bg/location/activity/time_of_day | Given a job's slot metadata; When stored; Then meta_json carries all five fields | implemented |

### FR-008-09 — Atomic writes, never a half-file (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-09-01 | integration | error | Interrupted write leaves no visible partial | Given a write interrupted mid-way; When the archive is scanned; Then no partial file is visible as a finished asset | implemented |
| TC-FR-008-09-02 | unit | happy | Temp-then-rename (or equivalent) used | Given the store step; When inspected; Then it writes to a temp path and atomically renames on success | implemented |
| TC-FR-008-09-03 | consistency | negative | No MEDIA_ASSET row before the file is durable | Given a failed generation; When it aborts; Then no row is committed for a missing file | implemented |

### FR-008-10 — Writes only; never serves / never on the hot path

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-10-01 | unit | negative | Runner has no user-serving path | Given the runner API; When inspected; Then it exposes generate/store, not a user-facing send | implemented |
| TC-FR-008-10-02 | integration | happy | No generation during a reply turn | Given a reply turn; When it runs; Then the image runner is not invoked inline | implemented |

### FR-008-11 — Consume jobs as a scheduled night batch

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-11-01 | integration | happy | Jobs drained during the sleep window | Given a queue of jobs and the sleep window; When the batch runs; Then jobs are consumed | implemented |
| TC-FR-008-11-02 | integration | boundary | No batch during awake hours | Given awake/serving hours; When checked; Then the runner does not process generation jobs | implemented |

### FR-008-12 — Idempotent by job key (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-12-01 | integration | idempotency | Re-running a job creates no duplicate | Given a job already done; When its key is processed again; Then no duplicate asset is created | implemented |
| TC-FR-008-12-02 | integration | idempotency | Redelivery deduped | Given the same job delivered twice; When processed; Then exactly one asset results | implemented |
| TC-FR-008-12-03 | concurrency | race | Two workers, one job | Given two workers pick the same job; When both run; Then only one asset is committed | implemented |

### FR-008-13 — Retry with backoff, degrade, don't block the batch (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-13-01 | integration | error | Transient failure retried | Given a job that errors once; When run; Then it retries with backoff and succeeds | implemented |
| TC-FR-008-13-02 | integration | error | Permanent failure logged + skipped | Given a job that always fails; When retries exhaust; Then it is logged/skipped, no partial file | implemented |
| TC-FR-008-13-03 | integration | error | One failure doesn't block the rest | Given a failing job amid a batch; When run; Then the other jobs still complete | implemented |

### FR-008-14 — Resumable batch

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-14-01 | integration | error | Interrupted batch resumes | Given a batch interrupted mid-run; When restarted; Then remaining jobs are picked up | implemented |
| TC-FR-008-14-02 | integration | boundary | Already-done jobs not redone on resume | Given a resume; When it runs; Then completed jobs are not regenerated | implemented |

### FR-008-15 — GPU held only when chat LLM unloaded (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-15-01 | integration | happy | Chat unloaded before image loads | Given the sleep transition; When it runs; Then the chat LLM is unloaded before the image runner loads | implemented |
| TC-FR-008-15-02 | integration | happy | Image torn down before chat reloads at wake | Given the wake transition; When it runs; Then the image runner releases the GPU before the chat LLM reloads + warms | implemented |
| TC-FR-008-15-03 | integration | negative | Both never resident together | Given the schedule; When probed at any point; Then only one heavy model owns the GPU | implemented |

### FR-008-16 — Clean bring-up / tear-down, no leaked GPU memory

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-008-16-01 | integration | happy | GPU released after the batch | Given a completed batch; When the runner exits; Then GPU memory is freed | implemented |
| TC-FR-008-16-02 | integration | error | Crash still frees GPU on teardown | Given a crash mid-batch; When the scheduler tears down; Then no leaked GPU memory blocks the chat reload | implemented |

---

## Non-functional requirements

### NFR-008-01 — Realism survives scrutiny (GPU/human-judged, CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-01-01 | benchmark | happy | A/B realism comparison | Given candidates A and B; When the same prompts run; Then saved images are compared for realism (image/benchmark.py) | out-of-band (GPU/manual) |
| TC-NFR-008-01-02 | manual | happy | Human acceptance of realism | Given output images; When a reviewer scrutinizes hands/skin/background; Then they read as real phone photos | out-of-band (GPU/manual) |

### NFR-008-02 — Batch fits the sleep window (performance)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-02-01 | performance | happy | Per-image latency measured | Given the chosen model; When generating; Then s/image at 4–8 steps is measured (benchmark) | out-of-band (GPU/manual) |
| TC-NFR-008-02-02 | load | boundary | Full day archive fits the window | Given a day's job count; When timed; Then the batch completes within the sleep window | out-of-band (GPU/manual) |

### NFR-008-03 — Never an empty archive (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-03-01 | error | happy | Failed batch degrades to prior day's archive | Given tonight's batch fails; When morning comes; Then yesterday's archive is still served, never nothing | implemented |
| TC-NFR-008-03-02 | integration | error | Empty-archive alert fires | Given a persona with no assets for the day; When observed; Then an alert fires (§6.4) | implemented |
| TC-NFR-008-03-03 | integration | negative | No user-visible gap | Given a failed batch; When a user asks for a photo; Then a valid prior asset is served, no gap surfaces | implemented |

### NFR-008-04 — Off the reply hot path (performance)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-04-01 | performance | happy | Reply latency unaffected by generation | Given a batch running; When replies are timed; Then reply latency is unaffected | out-of-band (GPU/manual) |
| TC-NFR-008-04-02 | integration | boundary | No inline generation in the reply path | Given the reply code; When inspected; Then no image generation is called inline | implemented |

### NFR-008-05 — Referential integrity (no orphans)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-05-01 | consistency | boundary | Every row has its file | Given the archive; When reconciled; Then no MEDIA_ASSET row lacks its file | implemented |
| TC-NFR-008-05-02 | consistency | negative | Every file has its row | Given the archive; When reconciled; Then no archived file lacks a row | implemented |

### NFR-008-06 — Durability across restarts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-06-01 | persistence | happy | Assets + rows survive a restart | Given stored assets; When services restart; Then files and rows are intact | implemented |

### NFR-008-07 — Environment isolation

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-07-01 | unit | happy | Image runner has its own env | Given the runner; When inspected; Then it uses its own venv/image, not the chat/video env (§6.2c) | implemented |
| TC-NFR-008-07-02 | integration | negative | No dependency conflict with chat/video | Given all runners; When installed; Then no shared-env conflict exists | out-of-band (GPU/manual) |

### NFR-008-08 — Observability

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-08-01 | integration | happy | Metrics exposed | Given the runner; When scraped; Then jobs done/failed, per-image latency, batch-vs-window, GPU mem are exposed | implemented |
| TC-NFR-008-08-02 | integration | error | Alerts on empty archive / not torn down | Given an empty archive or a stuck runner; When observed; Then the alert fires | implemented |

### NFR-008-09 — Swappability without regression

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-09-01 | integration | consistency | A→B swap keeps contract + schema | Given a model swap; When jobs run; Then the job contract and MEDIA_ASSET schema are unchanged | implemented |

### NFR-008-10 — Config-driven, no redeploy

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-008-10-01 | integration | happy | Model/steps/params/window from config | Given edited config; When the runner starts; Then the new values take effect without a code change | implemented |

---

## User-story acceptance (manual GPU / real-device E2E)

**TC-US-008-01-01 (manual/GPU) — operator: reliable overnight archive.** Run the night batch for a
persona; by morning the archive is full and valid. Status: manual (out-of-band)

**TC-US-008-02-01 (manual/GPU) — A3: instant premium photo.** Ask for a photo by day; it arrives at
once (pre-generated), premium quality. Status: manual (out-of-band)

**TC-US-008-03-01 (manual/GPU) — A8 skeptic: survives scrutiny.** Zoom into a generated photo's
hands/skin/background; it holds up as real. Status: manual (out-of-band)

**TC-US-008-04-01 (manual/GPU) — operator: no empty archive, recovers.** Force a job failure mid-
batch; the rest completes, the failure is retried/skipped, and morning's archive is complete.
Status: manual (out-of-band)

**TC-US-008-05-01 (manual/GPU) — integrator: model swap, no caller change.** Swap A→B; the same jobs
produce assets; Media Delivery and the planner are untouched. Status: manual (out-of-band)

**TC-US-008-06-01 (manual/GPU) — infra: single GPU owner.** Watch the sleep→wake transition; chat
unloads before image loads, image tears down before chat reloads+warms. Status: manual (out-of-band)

---

## Coverage summary
- **Functional:** FR-008-01..16 — ~40 tests (2–3 each; 3 for the 9 critical), 16/16 FR covered. ✓
- **Non-functional:** NFR-008-01..10 — ~18 tests; realism + throughput are benchmark/human-judged
  (marked), 10/10 NFR covered. ✓
- **User stories:** US-008-01..06 — 6 manual GPU/real-device acceptance tests. ✓
- Every TC id embeds its `FR-`/`NFR-`/`US-` id, traceable both ways.
