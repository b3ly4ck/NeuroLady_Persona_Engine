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

- `{MAJOR.MINOR.PATCH}` — project version, stored in the `VERSION` file at the repo root
  (create `VERSION` with value `0.1.0` if it doesn't exist yet).
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

## Language

All `.md` files in this project (this file included) must be written in English.

## Preferences and feedback

- [2026-07-10] User wants CLAUDE.md and all future .md files in this project written in English, not Russian.
