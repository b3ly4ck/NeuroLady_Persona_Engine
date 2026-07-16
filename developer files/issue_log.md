# Issue Log — NeuroLady

This file is the mechanism for tracking issues the product owner reports where **a feature does
not work, or the logic is wrong, even though all tests pass**. Passing tests do not prove the
product is right — they only prove the cases we thought of. When a real-world gap is found, it is
logged here, given an ID and a yes/no "fixed" checkbox, and closed by **updating the
documentation, tests, or architecture** to cover the gap. This is how the architecture and test
coverage get modernized from real findings over time.

---

## How it works

1. **Log it.** When the user reports such an issue, assign the next `ISS-<NNN>` id and add an
   entry below, formulating the report clearly, with the status checkbox **unchecked** `[ ]`.
2. **Investigate the gap.** Find *why the tests passed anyway* — usually a missing/incorrect
   test, an architecture flaw, or a requirement that was never written.
3. **Close it by improving the docs.** Fix the gap at its source:
   - add or correct tests (new `TC-` cases) in the relevant `developer files/tests/F-<NNN>-*.md`
     (and the runnable `tests/` code),
   - refine `architecture.md` where the design was wrong or under-specified,
   - add/adjust requirements (`FR-`/`NFR-`) in the feature file,
   - update any other affected guide.
4. **Mark it fixed.** Flip the checkbox to `[x]`, record what was changed and the date.

**ID scheme:** `ISS-<NNN>`, zero-padded, ever-increasing, **immutable**, never reused. An issue
that turns out invalid is marked `[x]` with resolution "not an issue — <why>", not deleted.

**Status meaning:** `[ ]` = open (not fixed yet) · `[x]` = fixed (gap closed in the docs/tests/
architecture).

---

## Index

| ID | Title | Fixed | Reported | Resolved |
|----|-------|:-----:|----------|----------|
| ISS-001 | Start Chat on a resumed session sends nothing and deletes S2 → empty chat | [x] | 2026-07-16 | 2026-07-16 |

---

## Entry template

~~~markdown
## ISS-<NNN> — <short title>

- **Status:** [ ] fixed
- **Reported:** <YYYY-MM-DD>
- **Report (as stated):** <the user's report, formulated clearly — what doesn't work / what
  logic is wrong, and in what situation>
- **Observed vs expected:** <what happens> vs <what should happen>
- **Why tests didn't catch it (the gap):** <missing test case / wrong architecture / missing
  requirement / …>
- **Resolution:** <what was changed to close the gap — e.g. added TC-FR-003-04-07..09,
  clarified architecture.md §3.5, added NFR-003-02>
- **Resolved:** <YYYY-MM-DD, or — while open>
~~~

---

## Issues

## ISS-001 — Start Chat on a resumed session sends nothing and deletes S2 → empty chat

- **Status:** [x] fixed
- **Reported:** 2026-07-16
- **Report (as stated):** In a fresh-looking chat (the user had deleted the Telegram chat
  client-side), `/start` → gallery → Alina → **Start Chat** deletes the gallery intro + persona
  card and sends **nothing** — the chat ends up completely empty. Picking Vika instead works
  (opener arrives), and after Vika, picking Alina works too.
- **Observed vs expected:** Start Chat left the chat with zero messages vs Start Chat must always
  end with a message from the persona.
- **Root cause:** the user still had an **active DB session** with Alina from earlier use (sessions
  survive bot restarts and the user's client-side chat deletion, which the bot cannot see).
  `start_or_switch_session` returned `is_new_intro=False` (same-persona reuse), and `on_start_chat`
  applied FR-001-17's "don't re-send the intro" to **every** reuse — then deleted the S2 card +
  intro, leaving a void. Vika had no active session (new → opener); re-picking Alina after Vika is
  a *switch* (new session → opener) — which is exactly why the bug looked persona-specific.
- **Why tests didn't catch it (the gap):** `TC-FR-001-17-*` asserted *no duplicate intro* on
  double-tap, but **no test asserted that a resumed-session Start Chat still sends anything**, and
  FR-001-17 itself conflated two different situations (rapid double-tap vs returning via the
  gallery later).
- **Resolution:** FR-001-17 reworded (F-001 feature + test spec): rapid duplicate taps are
  **deduplicated** (a short in-memory guard window), but a resumed-session Start Chat **always
  sends a short in-character resume opener** — Start Chat never leaves the chat without a persona
  message (architecture.md §1.3 principle added). Code: `on_start_chat` resume branch +
  `resume_opener` view + i18n copy + opener guard; tests updated/added
  (`test_fr_001_17_*` reworked, resume-sends-message + double-tap-dedup cases).
- **Resolved:** 2026-07-16
