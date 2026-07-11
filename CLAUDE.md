# NeuroLady_Final

## Git workflow: commit and push after every change

After **any** change made to the project (new file, code edit, config change, etc.),
automatically:

1. `git add` the changed files.
2. `git commit` with a message following the versioning template below.
3. `git push origin master`.

No need to ask for permission for the commit/push itself — this is a standard step after
every unit of work on the project. Confirmation is only needed for unusual/dangerous git
operations (force push, reset --hard, history rewrite, etc.).

### Commit message format

```
v{MAJOR.MINOR.PATCH} [{type}]: {short description}
```

- `{MAJOR.MINOR.PATCH}` — project version, stored in `developer files/VERSION`
  (create it with value `0.1.0` if it doesn't exist yet).
- Update the version before every commit:
  - `fix` → PATCH +1
  - `add` / `feat` → MINOR +1, PATCH reset to 0
  - `refactor`, `docs`, `chore`, `style`, `test` → PATCH +1
  - Breaking/major changes → MAJOR +1, MINOR and PATCH reset to 0
- `{type}` — change type: `add`, `fix`, `refactor`, `docs`, `chore`, `style`, `test`.
- Description — specific, state exactly what was added/changed/fixed (no vague wording).

Example:
```
v0.2.0 [add]: added NeuroLady persona response generation module
v0.2.1 [fix]: fixed persona config loading error
```

## Feature branching and merging

When a separate, self-contained feature is being built (as opposed to a small doc/config edit
or a quick fix), it must be developed on its own dedicated branch rather than directly on
`master`:

1. Create a new branch for the feature (e.g. `feature/<short-name>`).
2. Commit and push work-in-progress changes to that branch as work proceeds (following the
   normal commit message/versioning rules above), not to `master`.
3. Before merging the feature branch into `master`, all tests located in the `tests/` folder
   must be run and must pass.
4. Only merge into `master` after all tests pass. If tests fail, fix the issues on the feature
   branch first — do not merge a branch with failing or skipped tests.

This rule applies going forward, once features start being implemented (application code,
not documentation-only changes).

Every feature is also documented as its own file in `developer files/features/`, following the
format defined in `developer files/features/README.md` (user stories → user flows → Gherkin
use cases → functional & non-functional requirements, each requirement with a stable ID that
tests will later reference).

## Automatically logging user feedback and preferences

If the user, during a conversation:
- points out that a mistake was made,
- says they want something done differently,
- says they don't like something (e.g. a specific UI type, code style, approach, etc.),

— this must be **immediately** appended to the "Preferences and feedback" section below in
this same file (CLAUDE.md), briefly and specifically, with a date. This is done so the same
undesired decisions aren't repeated in the future.

Entry format:
```
- [YYYY-MM-DD] <the essence of the preference/mistake — what to avoid, or what to do instead>
```

## Project status file

Maintain a `developer files/PROJECT_STATUS.md` file that describes, in technical detail,
everything that has been done in the project so far (setup steps, files/modules created,
architecture decisions, configuration, fixes, integrations, etc.). Its purpose is to preserve
context across sessions so work can be picked up without re-deriving history from `git log`.

Rules:
- Update `PROJECT_STATUS.md` every time a meaningful change is made to the project (new
  feature, fix, config change, integration, etc.) — not for trivial/no-op edits.
- Write concrete technical details (what was added, how it works, relevant file paths,
  decisions made and why), not vague summaries.
- Organize it by topic/component rather than strictly chronologically, so it stays readable
  as the project grows; keep a "Recent changes" section at the top for the latest updates.
- Include `PROJECT_STATUS.md` updates in the same commit as the change they describe,
  following the normal commit/push workflow above.

## Language

All `.md` files in this project (this file included) must be written in English.

## Developer files folder

All working/context documentation created for the project (product concept, audience,
research notes, planning docs, etc.) is stored inside `developer files/` — this is meant to be
the single place to look for developer context on the project. The only exception is this
`CLAUDE.md` file itself, which must stay at the repo root so it's auto-loaded by Claude Code.

When creating a new `.md` doc for the project, put it in `developer files/` unless the user
explicitly asks for it elsewhere.

## Preferences and feedback

- [2026-07-10] User wants CLAUDE.md and all future .md files in this project written in English, not Russian.
- [2026-07-10] User wants PROJECT_STATUS.md and VERSION kept inside a `developer files/`
  subfolder, but CLAUDE.md must stay at the repo root (not moved into that subfolder), so
  it's picked up automatically by Claude Code.
- [2026-07-10] User wants all project documentation files (e.g. Audience.md, Project
  Concept.md) stored inside `developer files/` so Claude can look there for developer context.
