# Project Status — NeuroLady_Final

## Recent changes

- Moved `CLAUDE.md`, `PROJECT_STATUS.md`, and `VERSION` into a `developer files/` subfolder
  at the repo root (were previously at the repo root directly). `CLAUDE.md` was updated to
  reference the new paths.
- Added `CLAUDE.md` rule requiring this `PROJECT_STATUS.md` file to be kept up to date with
  technical details after every meaningful change.

## Repository setup

- Local project directory: `/home/human/NeuroLady_Final`.
- Git repository initialized locally (`git init`), default branch `master`.
- Remote `origin` set to `https://github.com/b3ly4ck/NeuroLady_Persona_Engine.git`, branch
  `master` pushed and tracking `origin/master`.
- Authentication: HTTPS via a GitHub Personal Access Token, stored through git's own
  credential store (`git config credential.helper store`, entry in `~/.git-credentials` as
  `https://x-access-token:<token>@github.com`). The token itself is intentionally **not**
  recorded in any memory/markdown file for security reasons.
- Global git identity was corrected: `~/.gitconfig` previously had a stale/unrelated identity
  (`igor-rah <ibryzhikov@ya.ru>`), which was replaced with `user.name = b3ly4ck` and
  `user.email = viktorbeliakovv@gmail.com`. All existing commits in this repo were rewritten
  (via `git filter-branch`) to this identity and force-pushed to GitHub.

## CLAUDE.md conventions established for this project

- **Git workflow**: every change to the project is committed and pushed to `origin master`
  automatically, without asking for confirmation for the commit/push itself.
- **Commit message format**: `v{MAJOR.MINOR.PATCH} [{type}]: {description}`, with the version
  tracked in a `VERSION` file at the repo root and bumped per change type (`fix`/`refactor`/
  `docs`/`chore`/`style`/`test` → patch bump; `add`/`feat` → minor bump; breaking changes →
  major bump).
- **Feedback logging**: whenever the user corrects an approach or states a preference, it is
  appended to the "Preferences and feedback" section of `CLAUDE.md` with a date, so it isn't
  repeated.
- **Language**: all `.md` files in this project must be written in English.
- **Project status**: this file (`PROJECT_STATUS.md`) must be kept current with technical
  detail on what has been built, to preserve context across sessions.

## Current state of the codebase

- No application code yet — the repository currently only contains a `developer files/`
  folder with `CLAUDE.md`, `VERSION`, and this `PROJECT_STATUS.md`. No NeuroLady persona
  engine code has been added so far.
