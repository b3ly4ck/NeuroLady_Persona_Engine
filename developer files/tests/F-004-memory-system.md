# Tests for F-004 — Memory System (relational + vector; persona-biography and user-biography recall)

- **Feature:** [F-004 — Memory System](../features/F-004-memory-system.md)
- **Approach:** Feature-granular coverage — **~2 varied tests per requirement, 3 for the most
  critical ones** (dual-store referential integrity, vector-payload isolation, semantic recall,
  fact categorization, structured recall by active category, supersession, biography
  no-self-contradiction, fused query + ranking, per-user isolation, delete-from-both-stores,
  Qdrant-down degrade, cross-user-leak security, vector-filter enforcement) across all **43 FR
  (FR-004-01..43)** and all **18 NFR (NFR-004-01..18)**, plus one **manual real-device acceptance**
  test per user story (US-004-01..10). Cases vary across unit / integration / inter-service /
  data-flow / component / e2e / performance / load / security / consistency, and happy / negative /
  boundary / empty / error / concurrency / idempotency / persistence / mapping. Because F-004 is the
  **memory subsystem itself** (not the reply loop), tests assert on **storage, referential
  integrity, categorization, retrieval correctness/relevance, supersession, isolation, durability,
  re-embedding, and degrade behavior** — reply-content correctness stays owned by F-002. Target band
  100-150; see `test_driven_development.md` §1. Every test ID embeds the `FR-`/`NFR-`/`US-` id it
  verifies.

> **Boundary note.** F-002 is a *consumer* of the F-004 contract; where F-002's own spec tests the
> turn that *uses* memory (its `TC-FR-002-*`), this spec tests the memory subsystem *behind* that
> call. Overlapping behaviors are tested here from the store/retrieval side (e.g. categorize/embed/
> recall/isolation) and cross-referenced in the feature file rather than duplicated.

---

## Functional requirements

### FR-004-01 — Maintain two coordinated stores (PostgreSQL relational + Qdrant vector)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-01-01 | unit | happy | Both stores are configured and reachable | Given the memory service; When it initializes; Then a relational (PostgreSQL) and a vector (Qdrant) backend are both wired | planned |
| TC-FR-004-01-02 | integration | happy | A stored fact lands in both stores | Given a new user fact; When it is stored; Then a structured row exists in SQL and an embedding exists in Qdrant | planned |

### FR-004-02 — Relational store holds the authoritative structured records

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-02-01 | unit | happy | Fact / biography / relationship / message persist as rows | Given each record type; When stored; Then `USER_FACT`, `BIOGRAPHY_LAYER`, `RELATIONSHIP`, `MESSAGE` rows are written | planned |
| TC-FR-004-02-02 | integration | mapping | Rows match the §5.1 ERD schema | Given a stored fact and layer; When inspected; Then their columns match the ERD (category/content, scope/period_key/content) | planned |

### FR-004-03 — Vector store holds embeddings + filter payload only, not authoritative content

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-03-01 | unit | happy | Vector point stores embedding + payload | Given a stored fact; When its vector point is read; Then it holds an embedding vector plus filter/back-ref payload | planned |
| TC-FR-004-03-02 | unit | negative | Authoritative content is not the source of truth in the vector store | Given a fact's content; When updated in SQL; Then SQL remains authoritative and the vector store is not treated as the content source | planned |

### FR-004-04 — Link each searchable record to its embedding via `embedding_ref` (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-04-01 | unit | happy | Every stored fact/layer has an `embedding_ref` | Given a stored `USER_FACT` and `BIOGRAPHY_LAYER`; When inspected; Then each has a non-null `embedding_ref` | planned |
| TC-FR-004-04-02 | integration | consistency | `embedding_ref` resolves to a real vector point | Given a stored record; When its `embedding_ref` is followed; Then it resolves to an existing Qdrant point | planned |
| TC-FR-004-04-03 | consistency | mapping | SQL row and vector point map 1:1 | Given a set of facts/layers; When reconciled; Then each row maps to exactly one vector point and vice versa | planned |

### FR-004-05 — Vector point payload carries owner back-reference + scope keys (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-05-01 | unit | happy | Payload has owning row id + owner scope | Given a fact's vector point; When read; Then payload holds the owning row id and `user_id`; a biography point holds `persona_id` | planned |
| TC-FR-004-05-02 | integration | mapping | Back-reference resolves to the authoritative row | Given a semantic hit; When its payload back-ref is followed; Then it resolves to the correct SQL row | planned |
| TC-FR-004-05-03 | security | negative | Points are filterable by owner | Given points for two users; When filtered by one `user_id`; Then only that user's points are addressable | planned |

### FR-004-06 — Store salient user facts as `USER_FACT` and expose the write contract

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-06-01 | component | happy | `POST /memory/user-fact` stores a fact | Given an extracted fact for a user; When posted; Then a `USER_FACT` row is created for that user | planned |
| TC-FR-004-06-02 | integration | mapping | Fact tied to the acting user | Given a fact from user A; When stored; Then its `user_id` is A and no other user | planned |

### FR-004-07 — Categorization pipeline classifies each fact (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-07-01 | unit | happy | Fact classified into a category | Given "my sister Katya is getting married"; When categorized; Then category = `family` | planned |
| TC-FR-004-07-02 | unit | boundary | Unmapped topic → extensible/other category | Given a fact fitting no core category; When categorized; Then it is assigned an extensible/other category, not dropped | planned |
| TC-FR-004-07-03 | integration | mapping | Category persisted and drives structured recall | Given a categorized fact; When stored; Then the `category` column is set and the fact is retrievable by that category | planned |

### FR-004-08 — Embed each stored fact and link it via `embedding_ref`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-08-01 | integration | happy | Storing a fact triggers embedding | Given a new fact; When stored; Then it is embedded into the vector store | planned |
| TC-FR-004-08-02 | integration | consistency | `embedding_ref` set to the created point | Given the embedded fact; When inspected; Then its `embedding_ref` points to the created vector point | planned |

### FR-004-09 — Structured recall by category, active-only (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-09-01 | integration | happy | Recall a user's facts by category | Given a user with facts across categories; When queried for `work`; Then only work facts return | planned |
| TC-FR-004-09-02 | integration | negative | Other categories excluded | Given the same query; When results return; Then no `family`/`preferences` facts are included | planned |
| TC-FR-004-09-03 | integration | boundary | Superseded facts excluded from active recall | Given a superseded work fact and an active one; When queried for `work`; Then only the active fact returns | planned |

### FR-004-10 — Semantic recall of an old fact by similarity (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-10-01 | integration | happy | Retrieve a differently-worded old fact | Given a stored fact about a wedding; When the query says "the big day coming up"; Then the fact is semantically retrieved despite different wording | planned |
| TC-FR-004-10-02 | integration | persistence | Cross-session months-old recall | Given a fact stored months ago in a prior session; When a related query runs now; Then the old fact is retrievable | planned |
| TC-FR-004-10-03 | integration | negative | Unrelated facts not retrieved | Given an unrelated query; When semantic recall runs; Then the wedding fact is not returned | planned |

### FR-004-11 — Supersede a contradictory user fact (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-11-01 | integration | happy | New fact authoritative, old marked superseded | Given "I work at company A" stored; When "I switched to company B" arrives; Then B becomes authoritative and A is marked superseded | planned |
| TC-FR-004-11-02 | integration | happy | Recall returns the current fact | Given the supersession; When his job is recalled; Then company B is returned, not A | planned |
| TC-FR-004-11-03 | persistence | consistency | Supersession survives restart | Given the supersession; When the store restarts; Then B is still authoritative and A still superseded | planned |

### FR-004-12 — Superseded fact retained but not surfaced

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-12-01 | integration | negative | Superseded fact not surfaced as current | Given a superseded fact; When recall runs; Then it is not returned as a current fact | planned |
| TC-FR-004-12-02 | integration | persistence | Superseded row retained for audit | Given a superseded fact; When the store is inspected; Then the row still exists (soft-superseded, not hard-deleted) | planned |

### FR-004-13 — Recency handling (newer facts preferred)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-13-01 | unit | happy | More recent fact weighted over older | Given two non-contradicting facts on one subject; When recalled; Then the more recent is preferred/weighted higher | planned |
| TC-FR-004-13-02 | unit | boundary | Same-subject tie resolved by recency | Given equally-relevant facts of different ages; When ranked; Then the newer ranks first | planned |

### FR-004-14 — Confidence handling (low-confidence not surfaced as certain)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-14-01 | unit | happy | Confidence stored with the fact | Given a firmly vs hedged statement; When stored; Then each carries a confidence signal | planned |
| TC-FR-004-14-02 | integration | negative | Low-confidence remark not recalled as certain | Given a hedged, low-confidence remark; When recall runs; Then it is not surfaced as a definite fact | planned |

### FR-004-15 — Deduplicate repeated facts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-15-01 | integration | idempotency | Restated fact creates no duplicate row | Given a fact already stored; When the user restates it; Then no duplicate `USER_FACT` row is created | planned |
| TC-FR-004-15-02 | integration | idempotency | No duplicate embedding | Given the restated fact; When processed; Then no duplicate vector point is created | planned |

### FR-004-16 — Store persona biography as time-pyramid layers

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-16-01 | unit | happy | Layers stored with scope + period_key | Given biography content at several scopes; When stored; Then `BIOGRAPHY_LAYER` rows carry `scope` in {epoch,year,month,week,day} and a `period_key` | planned |
| TC-FR-004-16-02 | integration | mapping | Layer rows match the ERD | Given stored layers; When inspected; Then columns match the §5.1 `BIOGRAPHY_LAYER` schema | planned |

### FR-004-17 — Embed each biography layer

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-17-01 | integration | happy | Layer embedded on store | Given a new biography layer; When stored; Then it is embedded into the vector store | planned |
| TC-FR-004-17-02 | integration | consistency | Layer `embedding_ref` set | Given the embedded layer; When inspected; Then its `embedding_ref` points to the created vector point | planned |

### FR-004-18 — Serve biography by scope (`GET /persona/{id}/biography?scope=`)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-18-01 | component | happy | Scope query returns the matching layer | Given a persona with layers; When `GET .../biography?scope=week`; Then the week layer is returned | planned |
| TC-FR-004-18-02 | component | boundary | Each scope value is served | Given scopes childhood/youth/current/year/month/week/day; When each is requested; Then the correct layer(s) return | planned |

### FR-004-19 — Semantic retrieval of biography layers relevant to a query

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-19-01 | integration | happy | Thematic query retrieves the relevant layer | Given a layer about something she "did"; When a thematic question is asked; Then the relevant layer is semantically retrieved regardless of scope | planned |
| TC-FR-004-19-02 | integration | negative | Unrelated layers not retrieved | Given an unrelated query; When retrieval runs; Then irrelevant layers are not returned | planned |

### FR-004-20 — Serve the correct layer/scope so she answers about her own life

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-20-01 | integration | happy | Childhood question → epoch layer | Given "what were you like as a kid?"; When resolved; Then the epoch/childhood layer is served | planned |
| TC-FR-004-20-02 | integration | happy | Recent question → week/day layer | Given "what did you get up to this week?"; When resolved; Then the week/day layer is served | planned |

### FR-004-21 — Biography served is internally consistent — no layer contradicts another (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-21-01 | consistency | happy | Coarse and fine layers are mutually consistent | Given an epoch layer and finer year/week layers; When cross-checked; Then no served layer contradicts another | planned |
| TC-FR-004-21-02 | consistency | negative | No contradictory layer is returned together | Given two layers that would conflict on a detail; When served; Then only the authoritative layer is returned | planned |
| TC-FR-004-21-03 | integration | boundary | Fine layers add detail without conflict | Given a fine layer elaborating a coarse summary; When both are relevant; Then the fine adds detail but does not conflict | planned |

### FR-004-22 — Store/index/serve biography; do not generate it (Life Engine boundary)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-22-01 | inter-service | happy | Life-Engine-produced layer is stored, embedded, retrievable | Given the Life Engine hands over a layer via the write/index contract; When received; Then memory stores, embeds, and makes it retrievable | planned |
| TC-FR-004-22-02 | unit | negative | Memory does not author/reflect/compress | Given the memory service alone; When run; Then it never generates, reflects on, or compresses biography content | planned |

### FR-004-23 — Biography is shared persona config (per persona, not per user)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-23-01 | integration | happy | Two users get the same biography | Given users A and B of one persona; When each asks about her childhood; Then both receive the same biography content | planned |
| TC-FR-004-23-02 | security | negative | No user facts mixed into shared biography | Given a user's private facts; When biography is served; Then no user fact is included in the biography | planned |

### FR-004-24 — Fused `query` combines structured + semantic + biography (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-24-01 | integration | happy | Bundle contains all three sources | Given a `(user, persona)` and a message; When `POST /memory/query` runs; Then the bundle includes structured facts, semantic matches, and relevant biography | planned |
| TC-FR-004-24-02 | component | mapping | Contract schema honored | Given the query endpoint; When called; Then the response matches the versioned schema F-002 depends on | planned |
| TC-FR-004-24-03 | data-flow | happy | DFD-1 memory-read step produces the bundle | Given DFD-1's read step; When the orchestrator queries memory; Then the fused bundle is returned for context assembly | planned |

### FR-004-25 — Fused query ranks by relevance (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-25-01 | integration | happy | Most relevant items ranked first | Given a message related to a few facts; When queried; Then the most pertinent memory ranks highest | planned |
| TC-FR-004-25-02 | integration | boundary | Ordering is by relevance score | Given mixed-relevance items; When ranked; Then order follows descending relevance | planned |
| TC-FR-004-25-03 | integration | consistency | Relevant beats merely recent when off-topic | Given a recent but off-topic fact and an older on-topic one; When ranked for the topic; Then the on-topic fact outranks the off-topic recent one | planned |

### FR-004-26 — Irrelevant facts must not dominate (threshold + size cap)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-26-01 | integration | negative | Below-threshold items excluded | Given many unrelated facts; When queried; Then items below the relevance threshold are excluded | planned |
| TC-FR-004-26-02 | integration | boundary | Bundle bounded by a size cap | Given more relevant items than the cap; When queried; Then the bundle is capped and does not overflow the context | planned |

### FR-004-27 — Stable, versioned query and write contracts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-27-01 | component | happy | Request/response schema is stable & versioned | Given the `/memory/*` endpoints; When called; Then they honor a fixed, versioned schema | planned |
| TC-FR-004-27-02 | component | negative | Malformed request rejected cleanly | Given a malformed query payload; When posted; Then it is rejected with a defined error, not a crash | planned |

### FR-004-28 — Every fused query scoped to its `(user, persona)`

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-28-01 | integration | happy | Returns that user's facts + that persona's biography | Given a `(user A, persona P)` query; When run; Then only A's facts and P's biography are returned | planned |
| TC-FR-004-28-02 | security | negative | Never another user's facts or another persona's biography | Given the same query; When run; Then no facts of user B and no biography of persona Q appear | planned |

### FR-004-29 — Recall is faithful to stored content

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-29-01 | integration | happy | Returned content matches stored content | Given a stored fact/layer; When recalled; Then its meaning matches the stored record verbatim | planned |
| TC-FR-004-29-02 | integration | negative | No fabrication or mutation | Given recall; When it returns; Then it neither invents content nor paraphrases into a different claim | planned |

### FR-004-30 — Recalled user facts are the acting user's actual stored facts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-30-01 | integration | happy | Recall returns his real stored facts | Given a user's stored facts; When recalled; Then exactly those facts are returned | planned |
| TC-FR-004-30-02 | security | negative | Never invents or attributes another's fact | Given recall for user A; When run; Then no fact A never stated and no fact of another user is attributed to him | planned |

### FR-004-31 — Served biography never conflicts with stored layers

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-31-01 | integration | happy | Served biography matches stored layers | Given stored layers; When biography is served; Then it reflects them without conflict | planned |
| TC-FR-004-31-02 | consistency | negative | No synthesized contradictory biography | Given a query; When biography is served; Then memory does not synthesize content contradicting stored layers | planned |

### FR-004-32 — Persist all memory indefinitely across sessions/restarts until deletion

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-32-01 | persistence | happy | Facts and layers survive a restart | Given stored facts and layers; When services/stores restart; Then all are still present | planned |
| TC-FR-004-32-02 | persistence | boundary | Memory survives a long gap | Given no activity for a long period; When the user returns; Then his facts and her layers are intact | planned |

### FR-004-33 — Keep the vector store in sync with the relational store

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-33-01 | integration | happy | Add propagates to an embedding | Given a new structured record; When stored; Then a matching vector point is created | planned |
| TC-FR-004-33-02 | integration | consistency | Delete removes the vector point | Given a deleted record; When propagated; Then its vector point is removed too | planned |

### FR-004-34 — Re-embed on content update, replacing the stale embedding

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-34-01 | integration | happy | Updating content re-embeds it | Given a fact whose content is updated; When saved; Then it is re-embedded to reflect the new content | planned |
| TC-FR-004-34-02 | consistency | negative | Stale embedding replaced, not left behind | Given the re-embed; When inspected; Then the old embedding is replaced and semantic recall reflects the new content | planned |

### FR-004-35 — Reconciliation/repair of drift between the two stores

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-35-01 | integration | error | Orphan embedding detected and cleaned | Given a vector point with no owning row; When reconciliation runs; Then the orphan is flagged/cleaned | planned |
| TC-FR-004-35-02 | integration | error | Missing embedding detected and backfilled | Given a searchable row missing its embedding; When reconciliation runs; Then it is re-embedded | planned |

### FR-004-36 — Per-user scope on reads/writes; every semantic query carries the user filter (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-36-01 | integration | happy | Reads/writes scoped to the acting user | Given user A acting; When facts are read/written; Then only A's facts are touched | planned |
| TC-FR-004-36-02 | security | negative | Semantic query cannot match another user's points | Given A's query semantically close to B's facts; When run with A's filter; Then no B point is returned | planned |
| TC-FR-004-36-03 | security | boundary | Missing filter is refused, not run unscoped | Given a semantic query with no user filter; When submitted; Then it is refused rather than executed across all users | planned |

### FR-004-37 — Shared biography, private facts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-37-01 | integration | happy | Biography shared; facts private | Given two users; When each recalls; Then biography is shared but each sees only his own facts | planned |
| TC-FR-004-37-02 | security | negative | No user fact leaks via biography or another's recall | Given a user's fact; When any other recall/biography runs; Then his fact never appears | planned |

### FR-004-38 — Per-user data export

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-38-01 | component | happy | Export returns all of a user's facts + messages | Given `GET /memory/user-data/{userId}`; When called; Then all of that user's stored facts and messages are returned | planned |
| TC-FR-004-38-02 | security | boundary | Export contains only that user's data | Given the export; When inspected; Then it contains nothing belonging to another user | planned |

### FR-004-39 — Per-user data deletion from BOTH stores (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-39-01 | integration | happy | Delete purges facts/messages from SQL | Given `DELETE /memory/user-data/{userId}`; When called; Then his `USER_FACT`/`MESSAGE` rows are purged | planned |
| TC-FR-004-39-02 | integration | consistency | Delete purges his embeddings from Qdrant | Given the same deletion; When propagated; Then all his vector points are removed | planned |
| TC-FR-004-39-03 | security | negative | Nothing recallable after delete; others unaffected | Given the deletion; When recall runs; Then none of his facts return and other users' memory is intact | planned |

### FR-004-40 — Degrade (not fail) when the vector store is unavailable (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-40-01 | integration | error | Returns structured facts + recent history | Given Qdrant is unreachable; When queried; Then a valid bundle from structured facts and recent history is returned | planned |
| TC-FR-004-40-02 | integration | error | Semantic recall skipped, no crash | Given Qdrant down; When query runs; Then semantic recall is skipped/reduced rather than raising an error | planned |
| TC-FR-004-40-03 | e2e | error | Turn still completes with Qdrant down | Given Qdrant down during a turn; When the reply is produced; Then the turn completes and the chat is not broken | planned |

### FR-004-41 — Defined, safe behavior when the relational store is unavailable

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-41-01 | integration | error | Defined degraded result, no fabrication | Given SQL is unreachable; When queried; Then a defined degraded result is returned and no facts/biography are fabricated | planned |
| TC-FR-004-41-02 | integration | error | Failure logged, turn not crashed | Given SQL down; When query runs; Then the failure is logged and the turn does not crash | planned |

### FR-004-42 — Fact storage/embedding runs off the reply hot path (queue/retry/backfill)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-42-01 | integration | happy | Embedding done asynchronously | Given several revealed facts; When stored; Then embedding work runs off the reply hot path | planned |
| TC-FR-004-42-02 | integration | error | Backlog queued and retried, no loss | Given the embedder is briefly unavailable; When facts arrive; Then embedding is queued and retried/backfilled without loss | planned |

### FR-004-43 — Write/embedding path never blocks the read/recall path

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-FR-004-43-01 | integration | happy | Query served during embedding backlog | Given a backlog of embedding work; When a `query` runs; Then it is served from already-stored memory | planned |
| TC-FR-004-43-02 | concurrency | happy | Concurrent writes don't stall reads | Given heavy write load; When reads run concurrently; Then recall latency is not blocked by the writes | planned |

---

## Non-functional requirements

### NFR-004-01 — Recall is correct and relevant

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-01-01 | integration | happy | Related item is retrieved | Given a message related to a stored item; When queried; Then that item is surfaced | planned |
| TC-NFR-004-01-02 | integration | boundary | Irrelevant items do not dominate | Given many unrelated facts; When queried; Then relevant items lead and irrelevant ones do not fill the set | planned |

### NFR-004-02 — Fused query latency fits within the reply budget

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-02-01 | performance | happy | Query returns within its sub-budget | Given a normal store size; When `query` runs; Then it returns fast enough not to blow F-002 NFR-002-01 | planned |
| TC-NFR-004-02-02 | performance | boundary | p95 recall latency within budget | Given many queries; When measured; Then p95 recall latency stays within the sub-budget | planned |

### NFR-004-03 — No cross-user data leakage (provable) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-03-01 | security | negative | User A never sees user B's facts | Given A and B with facts on the same persona; When A queries; Then no B fact is returned | planned |
| TC-NFR-004-03-02 | security | boundary | Isolation holds in both stores | Given SQL and vector recall; When probed for A; Then both stores return only A's data | planned |
| TC-NFR-004-03-03 | security | error | Adversarial semantic overlap does not leak | Given A's query semantically matching B's facts; When run; Then isolation holds and nothing of B's leaks | planned |

### NFR-004-04 — Durability across service and store restarts

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-04-01 | persistence | happy | Memory intact after restart | Given stored memory; When restarted; Then recall returns the same memory | planned |
| TC-NFR-004-04-02 | persistence | consistency | Embeddings still matched to rows after restart | Given a restart; When reconciled; Then every row still resolves to its vector point | planned |

### NFR-004-05 — Stores reach consistency within a bounded window

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-05-01 | consistency | boundary | Embedding converges within max lag | Given a stored/updated fact; When time passes; Then its embedding converges within the defined max lag | planned |
| TC-NFR-004-05-02 | consistency | error | Delete converges in both stores within the window | Given a deletion; When time passes; Then SQL and vector reach the deleted state within the window | planned |

### NFR-004-06 — Referential integrity (no orphan/missing embeddings)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-06-01 | consistency | boundary | No orphan `embedding_ref` after sync | Given a synced state; When checked; Then no `embedding_ref` points to a missing vector point | planned |
| TC-NFR-004-06-02 | consistency | negative | No searchable row without an embedding | Given a synced state; When checked; Then every searchable row has a matching embedding | planned |

### NFR-004-07 — Graceful degrade when the vector store is down (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-07-01 | error | happy | Turn completes with Qdrant unreachable | Given Qdrant down; When a turn queries memory; Then a valid bundle is returned and the turn completes | planned |
| TC-NFR-004-07-02 | error | boundary | Reduced-but-valid recall | Given Qdrant down; When queried; Then semantic recall is reduced but structured recall still works | planned |
| TC-NFR-004-07-03 | error | negative | No error surfaced to the user | Given Qdrant down; When the reply is produced; Then no error/system message leaks to the user | planned |

### NFR-004-08 — Defined, safe behavior when the relational store is down

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-08-01 | error | happy | Defined degraded contract, no crash | Given SQL down; When queried; Then a defined degraded result is returned without crashing the turn | planned |
| TC-NFR-004-08-02 | error | negative | No fabricated memory | Given SQL down; When queried; Then no facts or biography are fabricated | planned |

### NFR-004-09 — Recall self-consistent over time

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-09-01 | consistency | happy | Repeated probing yields consistent recall | Given the same question on different days; When recalled; Then the same stored facts/biography are returned | planned |
| TC-NFR-004-09-02 | consistency | negative | Adversarial probing surfaces no contradiction | Given a skeptic cross-checking biography/user-memory; When probed; Then no contradiction with stored records surfaces | planned |

### NFR-004-10 — Scales with volume of facts and users

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-10-01 | load | boundary | Recall within budget at large fact counts | Given many facts per user; When queried; Then recall stays within the latency budget | planned |
| TC-NFR-004-10-02 | load | boundary | p95 holds under many users/personas | Given many concurrent users/personas; When queried; Then p95 recall latency stays within the degraded budget | planned |

### NFR-004-11 — Write path asynchronous and non-blocking

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-11-01 | performance | happy | Reply latency unaffected by write load | Given heavy fact-write load; When replies are timed; Then reply latency is unaffected | planned |
| TC-NFR-004-11-02 | integration | error | Backlog drains without data loss | Given a backlog; When it drains; Then all queued embeddings complete via retry/backfill without loss | planned |

### NFR-004-12 — Supersession correctness

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-12-01 | consistency | negative | Outdated fact never resurfaces as current | Given a superseded fact; When many later recalls run; Then the outdated fact never returns as current | planned |
| TC-NFR-004-12-02 | consistency | boundary | Only one authoritative fact per superseded subject | Given a supersession chain; When recalled; Then exactly one authoritative fact is active | planned |

### NFR-004-13 — Deletion complete and export accurate

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-13-01 | security | error | Deleted data unrecoverable from both stores | Given a delete; When both stores are probed; Then the data is unrecoverable and un-recallable | planned |
| TC-NFR-004-13-02 | security | boundary | Export complete and scoped | Given an export; When checked; Then it returns the user's full set with nothing omitted and nothing foreign | planned |

### NFR-004-14 — Irrelevant-recall rate bounded

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-14-01 | statistical | boundary | Irrelevant injection below threshold | Given a labeled query set; When measured; Then the rate of irrelevant facts in bundles stays below threshold | planned |
| TC-NFR-004-14-02 | statistical | negative | Precision not degraded by noise | Given many stored facts; When queried; Then recall precision stays above the target | planned |

### NFR-004-15 — Confidence calibrated

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-15-01 | integration | negative | Hedged remarks not surfaced as definite | Given hedged statements; When recalled; Then they are not presented as certain facts | planned |
| TC-NFR-004-15-02 | unit | boundary | Confidence tracks assertion strength | Given firm vs tentative statements; When stored; Then confidence scales with how firmly each was asserted | planned |

### NFR-004-16 — Vector-filter enforcement (defense in depth) (CRITICAL)

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-16-01 | security | happy | Every semantic query carries an owner filter | Given any semantic query; When executed; Then an owner filter (`user_id`/`persona_id`) is applied at the vector store | planned |
| TC-NFR-004-16-02 | security | negative | Missing/wrong filter cannot return foreign points | Given a query with a missing or wrong filter; When executed; Then it cannot silently return another owner's points | planned |
| TC-NFR-004-16-03 | security | boundary | Filter enforced even under degrade paths | Given the degrade path; When semantic recall is attempted; Then the owner filter is still enforced | planned |

### NFR-004-17 — Observable memory metrics

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-17-01 | integration | happy | Recall/backlog/drift/degrade metrics exposed | Given the memory service running; When scraped; Then recall hit/miss, backlog depth/lag, drift, and degrade-mode metrics are exposed | planned |
| TC-NFR-004-17-02 | integration | error | Drift/degrade raises an alert signal | Given store drift or a degrade activation; When it occurs; Then the corresponding metric/alert fires | planned |

### NFR-004-18 — Biography retrieval deterministic by scope

| Test ID | Level | Case | Description | Given / When / Then | Status |
|---------|-------|------|-------------|---------------------|--------|
| TC-NFR-004-18-01 | consistency | happy | Same scope query returns the same layer | Given repeated `scope=` queries; When run; Then the same authoritative layer(s) return each time | planned |
| TC-NFR-004-18-02 | consistency | boundary | Identical life questions give stable answers | Given the same life question twice; When resolved; Then the served biography does not shift between the two | planned |

---

## User-story acceptance (manual real-device E2E)

One manual acceptance test per user story — judges the felt "she knows me / she is one coherent
person" quality that automation can't fully score.

**TC-US-004-01-01 (manual-e2e) — A2: she recalls an old fact unprompted**
- Preconditions: bot deployed; Telegram on your phone; an account that told her a memorable detail weeks ago.
- Steps: 1) Weeks ago, mention a detail (e.g. a sibling's name and a work worry) and never repeat it. 2) Return later and start chatting.
- Expected: she brings the old detail up herself, naturally and correctly, without you repeating it. Status: planned

**TC-US-004-02-01 (manual-e2e) — A2: months-later recall on return**
- Preconditions: an account inactive for a long stretch after sharing a specific fact (e.g. buying a flat).
- Steps: 1) Return after a long gap. 2) Mention a related topic ("finally decorating the place").
- Expected: she recalls the older specific fact from long-term memory, not just the recent thread. Status: planned

**TC-US-004-03-01 (manual-e2e) — A8 skeptic: her biography holds up under cross-checking**
- Steps: 1) Ask about her childhood, then last year, then last week, then a small detail from an earlier story. 2) Deliberately cross-check coarse vs fine.
- Expected: every answer stays consistent across scopes; no contradiction is catchable. Status: planned

**TC-US-004-04-01 (manual-e2e) — A8 skeptic: her memory of me is accurate, including updates**
- Steps: 1) Tell her one fact about yourself, later contradict it (e.g. changed jobs). 2) Ask which she remembers.
- Expected: she recalls the current version, not the outdated one. Status: planned

**TC-US-004-05-01 (manual-e2e) — A6: consistent, reliable recall**
- Steps: 1) Tell her something. 2) Ask about it on several different days.
- Expected: her recall stays consistent each time, drawn from the same stored facts, with no random flips. Status: planned

**TC-US-004-06-01 (manual-e2e) — A1: she tracks a changed detail**
- Steps: 1) Establish a running detail (e.g. a flatmate). 2) Later say it changed (flatmate moved out). 3) Continue chatting.
- Expected: she treats the new truth as current and drops the old premise. Status: planned

**TC-US-004-07-01 (manual-e2e) — Privacy: export then delete, and isolation**
- Steps: 1) Ask what she has stored about you (export). 2) Request deletion. 3) Continue chatting.
- Expected: you get an accurate export of your facts; after deletion she recalls none of it; nothing of yours ever appeared in another account's chat. Status: planned

**TC-US-004-08-01 (manual-e2e) — A4: a disclosure is remembered and honored, gently**
- Steps: 1) Disclose something personal/awkward once. 2) Return a few days later.
- Expected: she references it supportively in a relevant moment without making you re-explain, and doesn't dump it back out of context. Status: planned

**TC-US-004-09-01 (manual-e2e) — Returning user: she answers about her own life by the right level of detail**
- Steps: 1) Ask "what were you like as a kid?" 2) Ask "what did you get up to this week?"
- Expected: the childhood answer is epoch-level, the week answer is fine/recent, and neither contradicts the other. Status: planned

**TC-US-004-10-01 (manual-e2e) — Durability across a restart/deploy**
- Preconditions: coordinate a server restart/redeploy between two sessions.
- Steps: 1) Build up several facts and continuity. 2) Have the service restarted/redeployed. 3) Return and probe her memory.
- Expected: every fact and biography detail is exactly as before — nothing lost or drifted. Status: planned

---

## Coverage summary

- **Functional:** FR-004-01..43 — **98 automated tests** (2 per requirement, 3 for the 12 critical
  ones: FR-004-04, -05, -07, -09, -10, -11, -21, -24, -25, -36, -39, -40) across unit / integration /
  inter-service / data-flow / component / e2e / performance / load / security / consistency /
  concurrency / persistence, spanning happy / negative / boundary / error / idempotency / mapping /
  consistency cases. **43/43 FR covered. ✓**
- **Non-functional:** NFR-004-01..18 — **39 tests** (2 per requirement, 3 for the 3 critical ones:
  NFR-004-03, -07, -16) across performance / load / security / consistency / statistical / integration /
  error / persistence. **18/18 NFR covered. ✓**
- **User stories:** US-004-01..10 — **10 manual real-device acceptance tests**
  (TC-US-004-01-01 .. TC-US-004-10-01). **10/10 US covered. ✓**
- **Grand total: 147 enumerated tests** (98 FR + 39 NFR + 10 US) — within the 100-150 target band
  for this large, deliberately detailed feature (61 requirements), sitting near the top of the band
  by design.
- Every test ID embeds the `FR-`/`NFR-`/`US-` id it verifies, matching the feature file's IDs, so
  coverage is traceable in both directions.
