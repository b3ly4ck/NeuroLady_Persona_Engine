# Tests for F-021 — Media Archive Retention & Reuse

- **Feature:** [F-021 — Media Archive Retention & Reuse](../features/F-021-media-archive-retention-and-reuse.md)
- **Approach:** 2–3+ tests per requirement, at ≥2 levels each. Everything F-021 owns is deterministic
  and therefore automatable with an **in-memory DB + a temp media root**: candidate widening,
  freshness-vs-fit ranking, today-exhausted fallback, the cap/floor/eviction order, atomic file+row
  removal, `MediaSend` survival, per-persona isolation, age-independent intimacy gating, and the
  integrity reconciliation. The only genuinely human verdicts — *"does her camera roll feel alive
  over a week"* and *"does a specific ask find the right old frame given today's real metadata"* —
  are marked `out-of-band (manual)`. Every TC id embeds its `FR-`/`NFR-`/`US-` id and is owned by
  exactly one artifact.

### Testing method rules for this feature (non-negotiable)

1. **Execute the path, never grep it.** A test that only inspects *source text* (e.g. "does
   `select_asset` mention `retained_candidates`") passes even when that code path raises on its very
   first line — this exact mistake shipped a bug where every photo request died with a `TypeError`
   and the user got **silence** while 766 tests stayed green (ISS-004 lesson). Therefore **every**
   test about selection, delivery or retention behaviour must **invoke the real functions** —
   `services/bot/domain/media_delivery.py::select_asset` / `deliver_photo`, the retention entry point,
   and where a user-visible outcome is claimed, `services/bot/handlers/conversation.py::on_text` —
   with fakes (fake `Bot`, fake `ChatClient`, fake `IntimacyGate`, in-memory DB, `tmp_path` media
   root) and assert on **observable outcomes**: which asset object was returned/sent, which rows
   exist in `media_assets` / `media_sends` afterwards, and which files exist under the media root.
2. **Structural checks are additive only.** Where a source/structure assertion is genuinely useful
   (e.g. "retention is not called from the reply path"), it must accompany an executing test of the
   same behaviour, never replace it. Structural tests are marked `Case = structural` and always sit
   next to an executing sibling in the same subsection.
3. **Files and rows are both asserted, always.** A retention test that checks only the DB is
   incomplete, and so is one that checks only the filesystem. Every eviction test asserts **both**
   sides plus `services/imagegen/store.py::reconcile` reporting `{rows_missing_file: [],
   files_missing_row: []}`.
4. **The silence invariant carries over from F-020.** Any turn that widens or narrows the candidate
   pool must still end with **something the user can see** — media or an in-voice line. Zero
   outbound sends is always a failure.
5. **Fixtures.** `archive(persona, days={-3: [...], -1: [...], 0: [...]})` builds dated assets with
   real files under a temp media root; `sent(user, asset_ids)` inserts `MediaSend` rows;
   `RetentionConfig(cap=…, floor=…, freshness_bonus=…, freshness_decay=…)` drives every config knob;
   `run_retention(persona)` is the real scheduled step, callable twice for idempotency checks.

---

## Functional requirements

### FR-021-01 — Freshness ranks, it does not filter (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-01-01 | unit | happy | The candidate set spans all retained days, not one | Given a persona with 6 assets from today and 6 from three days ago, none sent; When the candidate set is built; Then all 12 are candidates (the replacement for `latest_available_assets`' one-day window returns 12, not 6) | implemented |
| TC-FR-021-01-02 | integration | regression | **The live Alina case pinned:** yesterday's frames are reachable again | Given the measured live state — 6 frames on day D-1 and 6 on day D, all unsent — and the user has already received every frame of day D; When `select_asset` runs; Then it returns one of the D-1 frames instead of `None` (before F-021 this returned `None` and the user got a deflection while 6 paid-for frames sat on disk) | implemented |
| TC-FR-021-01-03 | integration | empty | No retained assets at all still degrades, never raises | Given a persona with zero assets; When `select_asset` runs; Then it returns `None` cleanly and the caller emits an in-voice deflection — the degrade guarantee is preserved, not weakened | implemented |
| TC-FR-021-01-04 | integration | negative | Widening does not smuggle in ineligible assets | Given the retained library also contains intimate assets and assets already sent to this user; When the SFW candidate set is built; Then neither appears — widening changes *age* eligibility only | implemented |
| TC-FR-021-01-05 | inter-service | happy | Composed path F-011 batch → archive → F-021 retention → F-012 selection | Given the F-011 batch writes day D-2, D-1 and D archives, retention runs after each night, and a user then asks for a photo through the real handler; When the turn completes; Then the delivered asset came from the widened retained pool, exactly one photo reached the fake bot, and a `MediaSend` row was written | implemented |
| TC-FR-021-01-06 | unit | structural | The one-day filter is gone from the selection path | Given the delivery module; When inspected; Then `latest_available_assets`' single-day return is no longer what bounds candidacy (it may survive only as an F-008 NFR-008-03 degrade helper) — **additive to** TC-FR-021-01-01/02 which execute the path | implemented |

---

### FR-021-02 — Config-driven freshness bonus (today wins, all else equal)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-02-01 | unit | happy | Equal fit → today wins (UC-021-02) | Given two assets with identical slot metadata, one created today and one three days ago, both unsent; When scored and ranked; Then today's is selected | implemented |
| TC-FR-021-02-02 | unit | boundary | The bonus decays monotonically with age | Given otherwise identical assets aged 0, 1, 3, 7 and 30 days; When scored; Then the freshness component is strictly non-increasing with age and never negative-flips the ordering among equals | implemented |
| TC-FR-021-02-03 | unit | boundary | A very large bonus degenerates to "today only in practice" | Given `freshness_bonus` set far above the maximum achievable context-fit spread; When a poorly-fitting today frame competes with a perfectly-fitting week-old one; Then today's wins — the documented high-bonus regime | implemented |
| TC-FR-021-02-04 | integration | happy | A small bonus yields variety across repeated asks | Given `freshness_bonus` set near zero and a mixed-age unsent pool; When ten consecutive requests are served through the real delivery path; Then the delivered set spans several days rather than draining today first | implemented |

---

### FR-021-03 — A materially better context fit can beat freshness

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-03-01 | unit | happy | UC-021-03: outdoor ask picks the old walk over tonight's sofa | Given tonight's frames are all `background=home` and an older frame is `activity=walk, background=street`, and the request context is a walk; When ranked; Then the older outdoor frame wins | implemented |
| TC-FR-021-03-02 | unit | boundary | The trade-off point is exactly the configured threshold | Given a fit advantage set just **below** the configured margin and then just **above** it, with the same age gap; When ranked in both cases; Then the fresh frame wins in the first and the older frame wins in the second — the tipping point is config, not code | implemented |
| TC-FR-021-03-03 | integration | negative | A marginal fit advantage does not override freshness | Given an older frame that fits only trivially better than today's; When selection runs through the real path; Then today's is still delivered — "materially better" is required, not "any better" | implemented |

---

### FR-021-04 — Per-persona retention cap (count-based, config-driven)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-04-01 | integration | happy | Under the cap, retention keeps everything | Given a persona with 20 assets and `cap=60`; When retention runs; Then 20 rows and 20 files remain, zero evictions are reported | implemented |
| TC-FR-021-04-02 | integration | boundary | Exactly at the cap evicts nothing | Given `cap=30` and exactly 30 assets; When retention runs; Then nothing is deleted (the cap is inclusive) | implemented |
| TC-FR-021-04-03 | integration | happy | Over the cap comes back to the cap, not below | Given `cap=30`, `floor=10` and 42 assets; When retention runs; Then exactly 30 remain — 12 evicted, no over-eviction | implemented |
| TC-FR-021-04-04 | unit | negative | Age alone never evicts | Given a persona whose whole archive is 90 days old but well under the cap; When retention runs; Then nothing is deleted — retention is count-based, not age-based (the economics note: storage is cheap, GPU is not) | implemented |

---

### FR-021-05 — Eviction order: already-sent oldest first, then un-sent oldest (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-05-01 | integration | happy | UC-021-06: sent frames go before un-sent ones | Given `cap=10` and 14 assets — 6 old already-sent, 8 newer un-sent — ; When retention runs; Then the 4 evicted are all from the already-sent set and every un-sent frame survives | implemented |
| TC-FR-021-05-02 | integration | boundary | Within each class, oldest goes first | Given `cap=8` and 12 already-sent assets of distinct ages; When retention runs; Then exactly the 4 oldest by `created_at` are gone and the 8 newest remain | implemented |
| TC-FR-021-05-03 | integration | boundary | All frames un-sent → oldest un-sent are evicted | Given `cap=10`, `floor=4` and 13 assets none of which was ever sent; When retention runs; Then the 3 oldest un-sent are evicted and 10 remain — the un-sent tier is used only after the sent tier is empty | implemented |
| TC-FR-021-05-04 | integration | boundary | All frames already sent → straightforward oldest-first | Given `cap=10` and 15 assets all of which were sent to at least one user; When retention runs; Then the 5 oldest are evicted, 10 remain | implemented |
| TC-FR-021-05-05 | integration | boundary | Mixed tiers where the sent tier is not enough | Given `cap=10`, `floor=4`, 3 old already-sent assets and 12 un-sent assets (15 total); When retention runs; Then all 3 sent go first and only then the 2 oldest un-sent — evicting 5, leaving 10, and never touching an un-sent frame while a sent one remained | implemented |
| TC-FR-021-05-06 | unit | boundary | "Sent" means sent to *any* user | Given an asset delivered to user A only, while user B has never seen it, and a same-age asset nobody has seen; When the eviction tiering is computed; Then the A-sent asset is in the cheaper tier — an asset consumed by anyone counts as consumed GPU work | implemented |

---

### FR-021-06 — Retention floor: never below the minimum, never an empty archive

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-06-01 | integration | happy | The floor stops eviction | Given `cap=20`, `floor=6` and 8 assets where a hypothetical aggressive pass would take more; When retention runs; Then at least 6 assets remain in every case | implemented |
| TC-FR-021-06-02 | integration | boundary | `cap == floor` is stable and terminates | Given `cap=floor=6` and 9 assets; When retention runs; Then exactly 6 remain, the run terminates (no loop), and a second run evicts nothing | implemented |
| TC-FR-021-06-03 | integration | boundary | Cap smaller than today's batch keeps the newest, honours the floor | Given tonight's F-011 batch wrote 6 frames, `cap=4`, `floor=3`, and the archive holds only those 6; When retention runs; Then between `floor` and `cap` frames survive, the survivors are the **newest**, and no un-sent frame was evicted while a sent one existed | implemented |
| TC-FR-021-06-04 | integration | boundary | Floor greater than cap (misconfiguration) resolves deterministically | Given `cap=5`, `floor=8` and 12 assets; When retention runs; Then the documented resolution applies — **the floor wins** (8 survive, the cap is reported as unsatisfiable) — and the run logs the misconfiguration rather than emptying the archive; see the open question in the ambiguities section | implemented |
| TC-FR-021-06-05 | integration | empty | A single-asset archive is never emptied | Given a persona with exactly 1 asset and any cap (including `cap=0`); When retention runs; Then that asset survives — the F-008 NFR-008-03 "never an empty archive" invariant holds under every config | implemented |

---

### FR-021-07 — Atomic eviction: file and row die together; `MediaSend` history survives

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-07-01 | integration | happy | UC-021-08: both sides removed | Given an asset with a real file under the temp media root; When it is evicted; Then its `media_assets` row is gone **and** its file is gone, and `reconcile()` reports zero orphan rows and zero orphan files | implemented |
| TC-FR-021-07-02 | integration | error | File deletion fails → row is kept (no orphan row) | Given the file is made undeletable (permission error) for one victim; When retention runs; Then that asset's row is **not** deleted, the failure is logged, the rest of the run completes, and `reconcile()` is still clean | implemented |
| TC-FR-021-07-03 | integration | error | Row deletion fails → file is kept (no orphan file) | Given the row delete raises mid-transaction for one victim; When retention runs; Then that victim's file still exists, the transaction is rolled back for it, and `reconcile()` reports zero orphans of either kind | implemented |
| TC-FR-021-07-04 | integration | happy | **`MediaSend` survives its asset (the subtle one)** | Given user U received asset X and X is then evicted; When the `media_sends` table is queried; Then U's row for X is still there with its `sent_at`, and `sent_asset_ids(db, U)` still contains `X` | implemented |
| TC-FR-021-07-05 | integration | negative | An evicted asset never becomes re-sendable | Given X was sent to U and evicted, and a later batch writes new assets; When `select_asset` runs for U; Then X is not among the candidates (it no longer exists) **and** the history exclusion for X is still applied — if X's id were ever re-issued to a new file, that new asset would be wrongly excluded, so this test also asserts the id was **not** reused | implemented |
| TC-FR-021-07-06 | integration | boundary | Recent-sends context degrades cleanly when its asset is evicted | Given `recent_sends` performs an inner join `MEDIA_SEND ⋈ MEDIA_ASSET` (F-012 FR-012-15) and one of the recent sends has been evicted; When the lookup runs; Then it returns the surviving sends without raising, the evicted one is simply absent from the context block, and no `NULL`-scene entry leaks into the prompt — see the open question about evicting inside the recency window | implemented |

---

### FR-021-08 — Retention runs as scheduled maintenance, never on the reply hot path

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-08-01 | integration | happy | The night job invokes retention after the batch | Given the F-011 night batch completes for a persona; When the scheduled media window step runs; Then retention is executed for that persona and reports its counts | implemented |
| TC-FR-021-08-02 | integration | negative | A user turn never triggers retention | Given an instrumented retention entry point that records every invocation; When 20 turns — including photo requests — are driven through the real `on_text`; Then the retention counter is zero | implemented |
| TC-FR-021-08-03 | performance | boundary | Turn latency is unaffected by archive size | Given archives of 12 and 600 retained assets; When a photo request is served through the real path; Then the turn latency difference stays within the NFR-021-04 budget and no retention work happens inline | implemented |
| TC-FR-021-08-04 | integration | data flow | **DFD-3 touchpoint** reproduced | Given the DFD-3 night sequence (sleep → chat LLM unloaded → GPU freed → image jobs → assets tagged → archive + `MEDIA_ASSET` rows → **retention pass** → wake reloads the chat LLM); When the window is simulated end-to-end; Then retention runs after the rows land and before wake, and the chat model is never loaded concurrently with it | implemented |

---

### FR-021-09 — Intimacy is age-independent

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-09-01 | integration | negative | UC-021-09: an old intimate asset is not served by the SFW path | Given the retained library contains a 30-day-old intimate asset that would be the best context fit; When the SFW `select_asset` runs; Then it is never returned | implemented |
| TC-FR-021-09-02 | inter-service | happy | An old intimate asset still goes through F-014's gate | Given an intimate request and only aged intimate assets available; When the composed path runs; Then the F-014 gate is invoked with the intimate flag and its verdict (allow/withhold) is exactly what the user sees — age changes nothing | implemented |
| TC-FR-021-09-03 | security | negative | Retention/eligibility is not a gate bypass | Given every age bucket (today, yesterday, 30 days) populated with intimate assets and a gate that always withholds; When repeated requests are served; Then zero intimate assets reach the fake bot from any bucket | implemented |
| TC-FR-021-09-04 | integration | boundary | Eviction tiering ignores the intimate flag | Given a mixed archive over the cap; When victims are picked; Then the sent/un-sent age order alone decides — intimate assets are neither preferentially protected nor preferentially destroyed | implemented |

---

### FR-021-10 — Per-persona isolation

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-10-01 | integration | happy | Eviction touches only the target persona | Given persona A is 20 over her cap and persona B is under hers; When retention runs for both; Then only A's assets and files are removed and B's archive is byte-for-byte unchanged | implemented |
| TC-FR-021-10-02 | unit | negative | Candidacy never crosses personas | Given personas A and B both have unsent assets; When A's candidate set is built; Then no B asset appears, regardless of age or fit | implemented |
| TC-FR-021-10-03 | integration | boundary | Cap and floor are per persona, not global | Given `cap=10` and three personas with 15 assets each; When retention runs; Then each ends with 10 (30 total), not 10 in total | implemented |
| TC-FR-021-10-04 | integration | error | A failure on one persona does not block the others | Given retention raises while processing persona B; When the scheduled run executes over A, B, C; Then A and C are still processed and the B failure is reported (mirrors F-011 NFR-011-07) | implemented |

---

### FR-021-11 — Specific-request matching over the whole retained library (v1 groundwork)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-11-01 | integration | happy | The whole library is searched, not just today | Given a request whose context names an outdoor walk, today's archive holding only indoor frames, and a matching `activity=walk` frame from five days ago; When selection runs through the real path; Then the old walk frame is delivered | implemented |
| TC-FR-021-11-02 | unit | negative | No match anywhere degrades, it does not invent one | Given a specific ask that matches nothing in the retained metadata; When selection runs; Then the best available fallback is served **or** `None` is returned for an in-voice deflection — never a raise and never a repeat | implemented |
| TC-FR-021-11-03 | manual | boundary | Live match quality with today's real metadata | Given the live archive whose `meta_json` carries the *generation request* (`background: "home"`, `pose: "high-angle selfie"`) rather than a scene description; When "покажи, где ты гуляла" is asked; Then it is recorded whether a fitting frame is found — this measures the **F-010 metadata dependency**, not F-021's search, and its failure is an F-010 finding | out-of-band (manual) |

---

### FR-021-12 — Observability: kept/evicted counts and resulting archive size per persona

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-021-12-01 | unit | happy | The run report carries the three numbers | Given a run that evicts 4 of 14 for a persona; When it completes; Then the report contains `kept=10`, `evicted=4`, `archive_size=10` for that persona id | implemented |
| TC-FR-021-12-02 | integration | boundary | A no-op run still reports | Given an archive under the cap; When retention runs; Then a report is still emitted with `evicted=0` — silence is not an acceptable "nothing happened" signal | implemented |
| TC-FR-021-12-03 | integration | error | Partial-failure runs report what failed | Given one victim's deletion fails (TC-FR-021-07-02); When the run reports; Then the counts reflect what was actually removed and the failure is surfaced, not swallowed | implemented |
| TC-FR-021-12-04 | integration | happy | The §6.4 empty-archive alert condition is still evaluated after retention | Given retention has just run across the roster; When `empty_archive_personas` is evaluated; Then it returns an empty list — retention can never be the cause of an alertable empty archive | implemented |

---

## Non-functional requirements

### NFR-021-01 — No repeats, ever (widening must not weaken F-012's guarantee) — CRITICAL

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-01-01 | integration | happy | Direct check: drain the whole widened pool without a repeat | Given a persona with 30 retained unsent assets across 5 days; When 30 requests are served through the real delivery path (pacing lifted); Then 30 distinct asset ids were sent and the 31st request degrades in voice | implemented |
| TC-NFR-021-01-02 | integration | boundary | An evicted-then-forgotten asset cannot return | Given asset X was sent to U and later evicted; When a *new* batch runs and retention runs again and U asks repeatedly; Then X's id never appears in a send again — `media_sends` remains the authority even with no row in `media_assets` | implemented |
| TC-NFR-021-01-03 | integration | concurrency | Retention running while a delivery is selecting | Given `select_asset` has picked asset X and retention evicts X before the send completes; When the turn finishes; Then either X is delivered from a still-valid file or the delivery re-selects/deflects in voice — never a send of a missing file, never a `MediaSend` row for a file that was never delivered, and never zero outbound messages | implemented |
| TC-NFR-021-01-04 | integration | idempotency | A redelivered Telegram update does not double-send from the widened pool | Given the same update is processed twice against a large retained pool; When both turns complete; Then the same asset is not sent twice and only one `MediaSend` row exists for it | implemented |

---

### NFR-021-02 — Bounded storage: per-persona size stays within the cap

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-02-01 | integration | happy | Direct check after a run | Given any starting archive above the cap; When retention runs; Then both the row count and the on-disk file count for that persona are ≤ cap (or == floor when the floor binds) | implemented |
| TC-NFR-021-02-02 | integration | boundary | Bounded across 30 simulated nights | Given 30 consecutive simulated nights each adding 6 frames with retention after each; When the archive is measured at the end; Then it never exceeded the cap at any checkpoint and ends within `[floor, cap]` | implemented |
| TC-NFR-021-02-03 | integration | error | A batch far above the cap in one night is still bounded | Given a single night writes 5× the cap (misconfigured F-011 budget); When retention runs once; Then the archive is back within the cap in that single pass — no multi-night catch-up backlog | implemented |

---

### NFR-021-03 — No un-sent loss while sent frames exist

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-03-01 | integration | happy | Direct check: the invariant across a randomized battery | Given 200 randomized archives (varied sizes, ages, sent ratios, caps and floors); When retention runs on each; Then in every run, **no un-sent asset was evicted while any already-sent asset remained** | implemented |
| TC-NFR-021-03-02 | integration | boundary | Exactly one sent frame is enough to spare an un-sent one | Given the archive is exactly one over the cap, with 1 sent asset and the rest un-sent; When retention runs; Then the single sent asset is the only victim | implemented |
| TC-NFR-021-03-03 | integration | boundary | Under-stress: the floor binds before un-sent loss becomes avoidable | Given an archive of only un-sent frames, far above the cap; When retention runs; Then un-sent frames *are* evicted (correctly — no cheaper candidate exists), the newest survive, and the count lands on the cap/floor exactly | implemented |

---

### NFR-021-04 — Selection stays cheap (bounded, indexed lookup on the reply path)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-04-01 | performance | happy | Direct check at cap size | Given a persona at her full retention cap; When `select_asset` is called 100 times; Then p95 stays well within the F-012 NFR-012-01 budget | implemented |
| TC-NFR-021-04-02 | performance | boundary | Query count does not grow with archive size | Given archives of 12, 120 and 1200 assets and a statement counter; When selection runs; Then the number of SQL statements is constant and the candidate query is index-backed on `(persona_id, created_at)` — no per-asset N+1 | implemented |
| TC-NFR-021-04-03 | performance | error | Under a large sent-history | Given a user with thousands of `media_sends` rows; When selection runs; Then the no-repeat exclusion stays a single bounded query and latency stays within budget | implemented |

---

### NFR-021-05 — Never an empty archive after eviction

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-05-01 | integration | happy | Direct check across every config permutation | Given a matrix of caps `{0,1,5,30}` × floors `{0,1,3,10}` × archive sizes `{1,2,7,50}`; When retention runs on each; Then no combination produces an archive of zero assets for a persona that had at least one | implemented |
| TC-NFR-021-05-02 | integration | boundary | `cap=0` / `floor=0` still leaves at least one frame | Given the most aggressive possible configuration; When retention runs; Then at least one asset survives and the run logs that the configured cap was clamped | implemented |
| TC-NFR-021-05-03 | integration | error | Post-run alert condition is clean | Given retention has run over the whole roster with aggressive settings; When the §6.4 empty-archive alert check runs; Then it does not fire — ties F-008 NFR-008-03 | implemented |

---

### NFR-021-06 — Config-driven (cap, floor, freshness bonus/decay, cadence)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-06-01 | integration | happy | Direct check: changing cap/floor changes behaviour with no code change | Given the same archive run under `cap=10` and then `cap=30`; When retention runs; Then 10 and 30 assets remain respectively | implemented |
| TC-NFR-021-06-02 | unit | happy | Freshness bonus/decay are read from config at call time | Given two different bonus/decay settings and the same pair of candidates; When ranked; Then the winner differs according to configuration alone | implemented |
| TC-NFR-021-06-03 | integration | boundary | Per-persona overrides beat the global default | Given a global `cap=30` and a per-persona override of 8; When retention runs for that persona and one without an override; Then 8 and 30 respectively | implemented |
| TC-NFR-021-06-04 | unit | error | Missing/invalid config degrades to documented defaults | Given absent, negative or non-numeric cap/floor/bonus values; When retention and selection load config; Then documented defaults apply, the run completes, and the degraded state is logged — a broken config never means "delete everything" | implemented |

---

### NFR-021-07 — Integrity: zero orphan rows and zero orphan files after any run

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-021-07-01 | integration | happy | Direct check: reconciliation is clean after a normal run | Given a normal over-cap archive; When retention runs and `store.reconcile(db, media_root)` is called; Then both `rows_missing_file` and `files_missing_row` are empty | implemented |
| TC-NFR-021-07-02 | integration | idempotency | Running retention twice changes nothing | Given retention has just completed; When it runs a second time immediately; Then zero further evictions, identical row and file sets, and a clean reconciliation | implemented |
| TC-NFR-021-07-03 | integration | error | Interrupted run leaves no orphan of either kind | Given the process is killed between the file delete and the row delete (simulated by raising at that point); When the next retention run starts; Then it detects and repairs the inconsistency and `reconcile()` is clean afterwards | implemented |
| TC-NFR-021-07-04 | integration | boundary | Pre-existing orphans are not made worse | Given the media root already contains a stray `.png` with no row (an F-008 leftover); When retention runs; Then it does not delete rows for other assets by mistake, the stray is reported by `reconcile()`, and the result is deterministic | implemented |

---

## User-story acceptance

### US-021-01 — "Her photos feel like a real, growing camera roll"

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-021-01-01 | e2e | happy | A simulated week never repeats and never runs dry | Given 7 simulated nights of F-011 batches with retention after each, and a user asking for 3 photos a day through the real handler; When the week completes; Then all 21 photos are distinct, none is a repeat, and no day ends in an "I have nothing" deflection caused by the one-day window | implemented |

**Manual — TC-US-021-01-02 (manual-e2e)**
- Preconditions: the bot is deployed with the night batch and retention enabled for one persona; you
  have Telegram on your phone; the archive already holds at least two days.
- Steps:
  1. Over **seven consecutive days**, ask her for photos a few times each day, at different hours.
  2. Keep a note of every photo you receive (a screenshot roll is enough).
  3. On day 7, scroll back through the whole chat.
- Expected: no photo ever repeated; the photos read as *her* days rather than a loop of six frames;
  older frames appear naturally when today's are used up, and they still feel like her.
- Status: out-of-band (manual)

---

### US-021-02 — "Today's moments come first"

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-021-02-01 | e2e | happy | Evening ask at 8pm yields tonight's evening frame | Given today's and last Tuesday's evening frames are both unsent and equally fitting; When the user asks at 20:00 through the real handler; Then tonight's frame is delivered | implemented |
| TC-US-021-02-02 | e2e | boundary | Today exhausted → yesterday's evening frame, never silence (UC-021-04) | Given every one of today's frames was already sent to this user and yesterday's evening frame is unsent; When he asks again (pacing permitting); Then yesterday's evening frame is delivered — not a repeat, not a deflection | implemented |

---

### US-021-03 — Operator: the archive is bounded while un-sent work is preserved

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-021-03-01 | integration | happy | 30-night simulation: bounded size, un-sent preserved | Given 30 simulated nights with a realistic send rate; When measured at the end; Then archive size never exceeded the cap and the count of evicted un-sent frames is zero for as long as sent frames existed | implemented |
| TC-US-021-03-02 | integration | happy | Disk growth is bounded across the roster | Given 10 personas at the cap; When total on-disk media is measured after 30 nights; Then it is bounded by `10 × cap × frame_size` and does not grow further | implemented |

---

### US-021-04 — Operator: eviction never throws away un-seen GPU work while cheaper candidates exist

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-021-04-01 | integration | happy | Acceptance restatement of the invariant | Given the randomized battery of TC-NFR-021-03-01; When each run is audited; Then the "wasted GPU-hours" counter (un-sent frames destroyed while sent ones survived) is exactly zero | implemented |
| TC-US-021-04-02 | integration | boundary | The report makes the trade-off visible | Given a run that had to evict un-sent frames because nothing cheaper existed; When it reports; Then it explicitly counts `evicted_unsent` so the operator can raise the cap — the loss is never silent | implemented |

---

### US-021-05 — "A specific ask finds the right photo anywhere in her library"

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-US-021-05-01 | e2e | happy | Journey: outdoor ask → old outdoor frame | Given a signalled photo request whose context is a walk, today's frames all indoors, and a fitting outdoor frame from four days ago; When the turn runs through the real handler; Then the outdoor frame is delivered with an in-voice caption and its scene metadata is returned to the caller (F-012 FR-012-14) | implemented |

**Manual — TC-US-021-05-02 (manual-e2e)**
- Preconditions: the bot is deployed with a real multi-day archive for one persona; retention has run
  at least twice.
- Steps:
  1. Open Telegram and ask her, in RU, for a *specific* kind of photo she has not sent today —
     e.g. "покажи, где ты гуляла".
  2. Repeat with two other specific asks tied to different slots (a cafe, the gym).
- Expected: the photo she sends plausibly matches the ask, drawn from anywhere in her retained
  library — or, if it does not, record which metadata field was missing; that is an **F-010** finding
  (the dependency note), not an F-021 defect.
- Status: out-of-band (manual)

---

## Architecture-driven coverage map (guide §4b)

No new IDs — this maps the tests above onto `architecture.md` paths so every architectural hop this
feature crosses is demonstrably covered.

| Architectural path / artefact | Covered by |
|---|---|
| **Composed path** F-011 nightly batch → `media/` archive + `MEDIA_ASSET` rows → F-021 retention → F-012 selection → send | TC-FR-021-01-05, TC-US-021-01-01, TC-US-021-03-01 |
| **DFD-3** (night media): sleep → chat LLM unloaded → GPU freed → jobs → tagging → archive + rows → **retention pass** → wake reload | TC-FR-021-08-04, TC-FR-021-08-01 |
| §3.6 Media Delivery hop — asset selected from the widened pool reaches the Telegram send API once | TC-FR-021-01-05, TC-US-021-05-01 |
| §3.2a / F-014 gate hop — intimate assets of any age | TC-FR-021-09-02, TC-FR-021-09-03 |
| §5.1 ERD data integrity — `MEDIA_ASSET` 1:1 with its file; `MEDIA_SEND.asset_id` referential behaviour after eviction | TC-FR-021-07-01/02/03/04, TC-NFR-021-07-01..04 |
| §5.1 cross-entity consistency — `MEDIA_SEND ⋈ MEDIA_ASSET` recent-sends lookup (ISS-006 context block) after eviction | TC-FR-021-07-06 |
| §4.8 prompt/model & config management — cap, floor, bonus, decay, cadence tunable without code | TC-NFR-021-06-01..04 |
| §6.4 observability & alerting — kept/evicted/size metrics; empty-archive alert must never fire because of retention | TC-FR-021-12-01..04, TC-NFR-021-05-03 |
| Per-persona isolation across the roster (mirrors F-011 NFR-011-07) | TC-FR-021-10-01..04 |
| Reply hot path is untouched by retention (§3.2, §3.6, F-008 NFR-008-04) | TC-FR-021-08-02/03, TC-NFR-021-04-01..03 |
| Concurrency between the maintenance job and a live turn | TC-NFR-021-01-03, TC-NFR-021-07-02/03 |

---

## Regression pins

| Pin | Test(s) | Note |
|---|---|---|
| **Live measurement (2026-07-23)** — Alina held 12 frames across 2 days and the 6 older ones were permanently unreachable because a newer day existed | TC-FR-021-01-02 | Executes `select_asset` against the exact measured state; before F-021 it returned `None` while 6 paid-for frames sat on disk |
| **ISS-004 lesson** — a source-text-only regression test stayed green while the photo branch raised on its first line and the user got silence | Every behavioural TC in this spec executes the real function/handler; the only structural test is TC-FR-021-01-06 and it sits beside TC-FR-021-01-01/02 | Structural checks are additive, never the proof |
| **ISS-006 interaction** — the recent-sends context block joins `MEDIA_SEND ⋈ MEDIA_ASSET`; eviction can silently empty it | TC-FR-021-07-06 | Guards the F-012 FR-012-15 contract against F-021's deletions |

---

## Open questions — RESOLVED at implementation (2026-07-23)

Each was raised while writing this spec and carried an *assumed* resolution so the suite stayed
writable. All eight were settled during implementation; the assumptions held except where noted, and
the tests below now assert the settled behaviour.

| # | Question | Resolution |
|---|---|---|
| 1 | `floor > cap` | **Floor wins** (D4). The cap is reported unsatisfiable and logged. As assumed. |
| 2 | `cap < today's batch` | A **grace window** (`grace_hours`, default 24 h) protects frames younger than N hours regardless of the eviction order (D5) — the economics argument won. The cap is temporarily exceeded and reported. |
| 3 | "Already sent" | **Sent to any user** (D6). Per-user no-repeat is unaffected because it reads `MediaSend`, not the asset's presence. As assumed. |
| 4 | `MEDIA_SEND.asset_id` FK | The **FK was dropped**; `asset_id` is a plain indexed `String(96)` that outlives its asset (FR-021-14). Nulling it would have made the frame re-sendable. `MediaIdSequence` guarantees the id is never reissued. |
| 5 | Eviction inside the recency window | **Refused** — assets sent within `context_recency_hours` are untouchable and that protection outranks the cap (FR-021-15 / D3). Stronger than the assumed "clean degrade": evicting them would reopen ISS-006. |
| 6 | "Materially better" threshold | **Absolute margin on one scale** (D7): the margin an older frame must beat is exactly the freshness it forfeits. One knob, as assumed. |
| 7 | MED-id reuse | **Fixed before eviction shipped** (FR-021-13 / D1): a monotonic `MediaIdSequence` per persona, seeded from the highest suffix ever seen across live assets *and* send history. |
| 8 | Cadence vs the batch | **After** the batch, before wake (D8), so victims are chosen against the archive as it will be served. As assumed. |

Two decisions were **added** during implementation because the spec's wording was unachievable as
written — see D9 (freshness must decay proportionally, or a large bonus does nothing) and D10/D11
(eviction staging, and the guard that stops a bad media root from wiping an archive).

1. **`floor > cap` (misconfiguration).** FR-021-04 and FR-021-06 can contradict each other. Assumed
   in TC-FR-021-06-04: **the floor wins**, the cap is reported as unsatisfiable, and the run logs the
   misconfiguration. The alternative (cap wins, floor clamped) would violate NFR-021-05's spirit.
2. **`cap < today's batch size`.** FR-021-05's order would evict today's own un-sent frames within
   hours of paying for them. Assumed in TC-FR-021-06-03: the newest survive and the floor binds.
   Should there additionally be a **grace period** protecting frames younger than N hours from
   eviction regardless of order? The economics note argues yes; the spec does not say.
3. **What "already sent" means.** Assumed in TC-FR-021-05-06: sent to *any* user. In a multi-user
   deployment an asset sent to one of a thousand users is still un-seen by 999 of them, so a
   *per-user-value* notion (e.g. "sent to ≥ K users") may be wanted. The spec says only "already-sent".
4. **`MEDIA_SEND.asset_id` is a real foreign key** to `media_assets.id` (`services/bot/models.py:424`).
   FR-021-07 requires the send row to outlive its asset, which the current schema **forbids**. A
   migration decision is needed: drop the FK and keep `asset_id` as a plain string, or add
   `ON DELETE SET NULL` plus a separate immutable id column, or keep an evicted-asset tombstone
   table. TC-FR-021-07-04/05 assume **the id string survives intact** — anything that nulls it breaks
   NFR-021-01.
5. **Eviction inside the recent-sends recency window.** `recent_sends` inner-joins the asset
   (F-012 FR-012-15), so evicting an asset sent an hour ago silently removes it from her context and
   she can again invent a background for a photo she just sent (the ISS-006 failure mode). Should
   retention **refuse to evict assets sent within `context_recency_hours`**? TC-FR-021-07-06 currently
   only asserts a clean degrade.
6. **"Materially better" fit threshold.** FR-021-03 says the trade-off point is config; the spec does
   not name the knob or say whether it is an absolute score delta or a ratio. TC-FR-021-03-02 assumes
   an **absolute margin** compared against the freshness bonus.
7. **MED-id reuse after eviction.** Nothing in F-008 or F-021 states that `MED-<persona>-<nnnnn>`
   counters never rewind after rows are deleted. If the counter is derived from `MAX(id)` or a row
   count, eviction makes reuse possible and TC-FR-021-07-05 would fail. The id allocator needs an
   explicit monotonic guarantee stated in F-008.
8. **Retention cadence vs the batch.** FR-021-08 says "with the night batch". Before or after the
   batch writes? Assumed **after** (TC-FR-021-08-04), so the newest frames are already present when
   victims are chosen; running before would evict against a stale count.

---

## Coverage summary

| Requirement | Tests | Levels | Minimum met |
|---|---|---|---|
| FR-021-01 | 6 | unit, integration, inter-service | ✓ happy + regression + empty + negative + structural |
| FR-021-02 | 4 | unit, integration | ✓ happy + boundary ×2 + config regime |
| FR-021-03 | 3 | unit, integration | ✓ happy + boundary + negative |
| FR-021-04 | 4 | unit, integration | ✓ happy + boundary + negative |
| FR-021-05 | 6 | unit, integration | ✓ happy + 4 boundaries (all-unsent, all-sent, mixed, tier meaning) |
| FR-021-06 | 5 | integration | ✓ happy + cap==floor + cap<batch + floor>cap + empty |
| FR-021-07 | 6 | integration | ✓ happy + 2 error/rollback + MediaSend survival + no-resend + ISS-006 join |
| FR-021-08 | 4 | integration, performance | ✓ happy + negative + performance + DFD-3 |
| FR-021-09 | 4 | integration, inter-service, security | ✓ negative + gate hop + security + tiering |
| FR-021-10 | 4 | unit, integration | ✓ happy + negative + boundary + error |
| FR-021-11 | 3 | unit, integration, manual | ✓ happy + negative (+1 out-of-band) |
| FR-021-12 | 4 | unit, integration | ✓ happy + no-op + partial failure + alert tie-in |
| NFR-021-01 | 4 | integration | ✓ direct + boundary + concurrency + idempotency |
| NFR-021-02 | 3 | integration | ✓ direct + boundary (30 nights) + under-stress |
| NFR-021-03 | 3 | integration | ✓ direct (randomized battery) + boundary + under-stress |
| NFR-021-04 | 3 | performance | ✓ direct + boundary (query count) + under-stress |
| NFR-021-05 | 3 | integration | ✓ direct (config matrix) + boundary + alert check |
| NFR-021-06 | 4 | unit, integration | ✓ direct + boundary + per-persona override + failure |
| NFR-021-07 | 4 | integration | ✓ direct + idempotency + interruption + pre-existing orphans |
| US-021-01 | 2 (incl. 1 manual) | e2e, manual | ✓ |
| US-021-02 | 2 | e2e | ✓ |
| US-021-03 | 2 | integration | ✓ |
| US-021-04 | 2 | integration | ✓ |
| US-021-05 | 2 (incl. 1 manual) | e2e, manual | ✓ |

- **Total: 87 tests** (53 FR + 24 NFR + 10 US) — 84 `planned` (automatable with an in-memory DB, a
  temp media root and fakes) and 3 `out-of-band (manual)`.
- Every `FR-021-01..12`, `NFR-021-01..07` and `US-021-01..05` has its own subsection and a *set* of
  tests at ≥2 levels; every user-facing story has an e2e, and the two stories whose verdict is a
  human feeling (US-021-01 "camera roll feels alive", US-021-05 specific-ask quality) have a manual
  real-device block.
- Out-of-band tests are exactly those whose verdict depends on **human judgement over real time or
  real metadata** — a week of lived chat (TC-US-021-01-02), live specific-ask quality
  (TC-US-021-05-02, TC-FR-021-11-03). Everything F-021 itself owns is deterministic and automated.
- Every TC id embeds and traces to exactly one `FR-`/`NFR-`/`US-` id.
