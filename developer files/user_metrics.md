# User Metrics — NeuroLady

This document defines the **user-facing metrics** for NeuroLady: what actually matters to
users, expressed as measurable, checkable targets (SMART). It maps those metrics onto each
audience segment from [`Audience.md`](Audience.md).

**How to read this:**
- No product exists yet, so every number below is a **target threshold to validate against**,
  not a measured result.
- Each metric has an ID, a one-line definition, how it is measured, and a numeric target.
- "Blind test" = human evaluators judge samples without knowing which are AI/real.
- Per-segment sections reference the catalog metrics (M1–M8) and tighten targets where a
  segment cares about something more than average.

---

## Part 1 — Core metric catalog

### M1 — Communication realism (writes like a living person, not a neural net)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M1.1 | **Text Turing-fail rate** — evaluators who *cannot* correctly tell she is AI | Blind test after a ≥30-message / ≥15-minute chat | **≥70%** fail to identify as AI (stretch **≥85%**) |
| M1.2 | Human-likeness rating | Post-chat user rating "felt like a real person" (1–5) | **≥4.5 / 5** |
| M1.3 | "Sounds like a bot" flag rate | % of her messages users flag as robotic/AI-like | **<2%** |
| M1.4 | Emotional-appropriateness | Human raters score emotional fit to context | **≥95%** of responses rated appropriate |
| M1.5 | Tone/register adaptation | She matches the user's style (formality, slang, mood) | Detectable shift within **≤5 messages**, ≥90% rater-confirmed |
| M1.6 | Persona-consistency (self) | Statements that contradict her own established bio | **<1%** contradiction rate |

### M2 — Photo hyper-realism, SFW (looks shot on an iPhone, not AI-perfect)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M2.1 | **Real-vs-AI blind pass** | Viewers classify her photo as a real phone photo | **≥70%** judge "real" |
| M2.2 | Artifact rate | % of delivered photos with a visible gen artifact (hands, teeth, over-smooth skin, background warp) | **<3%** |
| M2.3 | Identity consistency | Photo judged "same person" as canonical appearance | **≥98%** |
| M2.4 | Amateur/"iPhone" look | Rated casual phone shot vs studio/AI-perfect | **≥80%** rated amateur/candid |

### M3 — Intimate photo realism, NSFW (where legal; adult personas only)
> Compliance note: all depicted personas are clearly adult; NSFW is delivered only in permitted
> jurisdictions and behind age verification. Metrics here are about *realism quality*, not
> content itself.

| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M3.1 | **Anatomical-accuracy / artifact rate across poses** | Artifact rate over a fixed set of **≥15 defined poses** | **<2%** |
| M3.2 | Real-amateur blind pass | Classified as a real amateur nude (not AI / not studio-pornstar) | **≥70%** judge "real amateur" |
| M3.3 | Identity consistency across poses | Same person as canonical appearance | **≥98%** |
| M3.4 | Appeal rating | Target-audience appeal score (1–5) | **≥4.0 / 5** |

### M4 — Memory & context retention
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M4.1 | **Recall accuracy** | Previously-stated user facts recalled correctly when relevant | **≥95%** |
| M4.2 | **Memory horizon** | Correctly recalls facts stated long ago | **≥180 days** (≥6 months) |
| M4.3 | Proactive callback | She references a relevant past user statement unprompted | **≥1 meaningful callback per ~20 messages** of relevant context |
| M4.4 | Memory-contradiction rate | Statements contradicting stored user facts | **<1%** |

### M5 — Response speed, text (fast, and operator-configurable)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M5.1 | Median text latency (default) | Request → first reply, default profile | **≤3 s** |
| M5.2 | p95 text latency (default) | 95th percentile | **≤6 s** |
| M5.3 | **Configurable pacing** | Operator sets a target latency (e.g. slow "human typing" feel) | Any value in **1–120 s**, actual within **±15%** of target |

### M6 — Media speed (photos & video on request)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M6.1 | SFW photo delivery p95 | Request → photo delivered | **≤10 s** |
| M6.2 | NSFW photo delivery p95 | Request → photo delivered | **≤15 s** |
| M6.3 | Video delivery p95 | Request → video delivered | **≤60 s** |

### M7 — Framework / persona-construction (architecture & publishability)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M7.1 | **Time to build a new persona** | One person, from scratch to live persona | **≤2 hours** |
| M7.2 | Config-driven identity | Appearance + biography + voice defined via config | **100%** via config, **0** code changes to add a persona |
| M7.3 | Channel modularity | Core engine reused across delivery channels (Telegram now, others later) | **≥2 channels** with **no core rewrite** |
| M7.4 | Reproducibility / publishability | Pipeline + eval documented enough to reproduce for a paper | **100%** of headline metrics reproducible from docs |

### M8 — Availability & reliability (supporting metric)
| ID | Metric | How measured | Target |
|----|--------|--------------|--------|
| M8.1 | Uptime | Monthly service availability | **≥99.5%** |
| M8.2 | Time-zone availability | She responds regardless of hour | **24/7**, no latency penalty by hour |
| M8.3 | Low-bandwidth success | Message/media delivery on weak connections | **≥99%** delivery success at ≤1 Mbps |

---

## Part 2 — Metrics that matter per audience segment

Priority key: **★★★ Critical** · **★★ High** · **★ Relevant**. Numbers are the segment's own
target (defaults from the catalog unless tightened).

### Group A — End users (B2C)

#### A1 — Russian-speaking Gen Z (beachhead)
- ★★★ **M1 communication realism** — M1.1 ≥70%, M1.3 <2% (they instantly clock "bot" energy).
- ★★★ **M5 speed** — M5.1 ≤3 s (chat-native expectations, they abandon slow bots).
- ★★ **M2 photos** — M2.1 ≥70%, M2.4 ≥80% "looks like a real girl's selfie."
- ★★ **M4 memory** — M4.1 ≥95% (relationship must feel like it accumulates).
- ★ M3 intimate realism (present, not the primary draw here).

#### A2 — The lonely / socially isolated
- ★★★ **M4 memory** — this is the segment's core: M4.1 ≥95%, **M4.2 ≥180 days**, M4.3 proactive
  callbacks, M4.4 <1%. If she jumps back to something they said months ago, attachment forms.
- ★★★ **M1 realism** — M1.2 ≥4.5/5, M1.4 ≥95% emotional appropriateness (they need to feel *seen*).
- ★★ **M8 availability** — M8.2 24/7 (she's the "always there" presence).
- ★ M2/M3 media (supportive, not primary).

#### A3 — High-disposable-income men (premium / "whale")
- ★★★ **M3 intimate realism** — tighten: **M3.1 artifact <1%**, M3.2 ≥75%, M3.3 ≥98%, M3.4 ≥4.3/5.
- ★★★ **M2 photos** — M2.1 ≥75%, M2.2 <2% (premium expectations).
- ★★★ **M6 media speed** — tighten: M6.2 ≤10 s, M6.3 ≤45 s (priority delivery for top tier).
- ★★ **M5 speed** — M5.1 ≤2 s priority latency.
- ★★ Exclusivity/personalization (persona tuned to stated preferences — tracked qualitatively).

#### A4 — Socially anxious & introverted men
- ★★★ **M1 realism + patience** — M1.4 ≥95% (must never feel judgmental); consistently receptive.
- ★★ **M4 memory** — M4.1 ≥95% (remembers their disclosures → feels safe).
- ★★ **M5 pacing** — often *not* max speed: M5.3 set to a natural, unhurried cadence (low pressure).
- ★ M2/M3 media (secondary; confidence and safety lead).

#### A5 — Access-constrained men (geography / schedule / life stage)
- ★★★ **M8 availability** — M8.2 24/7, **M8.3 ≥99% delivery at ≤1 Mbps** (remote/low bandwidth).
- ★★ **M6 media speed** — graceful degradation; media still lands on weak links.
- ★★ **M1 realism** — companionship must feel real to be worth it.
- ★ M5 speed (nice-to-have; availability beats raw speed here).

#### A6 — Neurodivergent users
- ★★★ **M1.6 consistency / predictability** — <1% self-contradiction; stable, literal, no hidden rules.
- ★★ **M1.5 adaptation** — tunable to a more explicit/literal style.
- ★★ **M4 memory** — M4.1 ≥95% (predictable continuity).
- ★ M2/M3 media.

#### A7 — Older men re-entering dating (divorced / widowed)
- ★★★ **M1 warmth** — M1.2 ≥4.5/5, emotional steadiness over edginess.
- ★★ **Onboarding simplicity** — time-to-first-reply after install **≤2 min**, zero config (low tech comfort).
- ★★ **M4 memory** — M4.1 ≥95%.
- ★ M2/M3 media.

#### A8 — Novelty & tech-curious users (skeptic testers)
- ★★★ **M1.1 Turing-fail** — they actively probe: hold **≥70%** even under adversarial questioning.
- ★★★ **M2/M3 realism** — M2.1 ≥70%, M2.2 <3% (they zoom in on hands/skin to catch AI).
- ★★ **M4 memory** — they test recall of earlier details.
- ★ M5/M6 speed.

### Group B — Operators & businesses (B2B)

Operator-facing "user" metrics center on the **framework (M7)**, plus configurable speed and
consistency of the personas they run.

#### B1 — Solo AI-influencer creators
- ★★★ **M7 framework** — M7.1 ≤2 h to spin up a persona, M7.2 100% config-driven.
- ★★★ **M2.3 / M3.3 identity consistency ≥98%** (their persona must always look like one person).
- ★★ **M5.3 / M6 configurable speed** (control the persona's cadence and media turnaround).

#### B2 — Adult-content operators scaling
- ★★★ **M3 intimate realism** — M3.1 <2%, M3.2 ≥70%, M3.3 ≥98% (believable at volume).
- ★★★ **Throughput** — sustain **≥1,000 concurrent conversations/persona** at catalog latencies.
- ★★ **M6 media speed** — M6.2 ≤15 s at scale.
- ★★ Compliance tooling (age/consent verification) — 100% coverage.

#### B3 — Agencies & studios (multi-persona)
- ★★★ **M7.2 / M7.3 modularity** — manage **≥10 personas** from one control layer, no core rewrite.
- ★★ **Consistency across roster** — M2.3/M3.3 ≥98% per persona.
- ★★ **M8.1 uptime ≥99.5%** (client SLAs).

#### B4 — Platforms & apps (white-label / API)
- ★★★ **M7.3 / M7.4** — clean API/SDK; integrate in **≤5 working days**; documented for reuse.
- ★★ **M8.1 uptime ≥99.9%** (platform-grade).
- ★★ **M5/M6 configurable latency** exposed via API.

### Group C — Academic & scientific

For this audience the metrics *themselves* are the deliverable — the headline scientific result.

#### C1–C2 — HCI / affective-computing & AI/ML researchers
- ★★★ **M1.1 Turing-fail rate** as the primary published result (in-the-wild, over time).
- ★★★ **M4.2 memory horizon** and **M1.6 consistency** as technical contributions.
- ★★ **M7.4 reproducibility** — 100% of headline metrics reproducible from the released docs.

#### C3 — Conference reviewers & program committees
- ★★★ **Methodological rigor** — pre-registered eval protocol, blind tests, reported CIs.
- ★★★ **M7.4** reproducibility and honest reporting (baseline vs target, sample sizes).

#### C4 — AI-ethics & safety scholars
- ★★★ **Safeguard coverage** — 100% of vulnerable-user safeguards and consent/age checks
  documented and measurable.
- ★★ Transparency of the deception dimension (reported, not hidden).

---

## Summary of headline targets

The product's single most important user metric is **M1.1 — the blind text Turing-fail rate
(≥70%, stretch ≥85%)** — because "she writes like a living person, not a neural net" is the
whole promise. It is backed by **M2/M3 (visual realism, <3% / <2% artifact rates, ≥70% blind
real-pass)**, **M4 (memory: ≥95% recall over ≥180 days)**, **M5/M6 (configurable speed; text
≤3 s, media ≤10–60 s)**, and **M7 (a modular framework: new persona in ≤2 h, 100% config-driven,
reproducible for publication)**. Every audience segment weights these differently, but they draw
on the same measurable pillars.
