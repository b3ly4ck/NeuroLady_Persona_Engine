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
| _(none yet)_ | | | | |

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

_(none logged yet)_
