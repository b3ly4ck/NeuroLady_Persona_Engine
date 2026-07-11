# Project Status — NeuroLady_Final

## Recent changes

- Rewrote `developer files/user_metrics.md` to remove all numeric targets (they weren't
  well-understood yet) and instead describe, in words, the **ideal use case** and requirements
  per audience segment. Opens with shared quality dimensions (conversational realism, SFW photo
  hyper-realism, NSFW intimate realism, memory, responsiveness, feeling alive/available), then
  gives a narrative "ideal scenario + what he wants/requires" for every segment in Groups A/B/C.
- (Superseded) Previously `user_metrics.md` held a numeric SMART metric catalog (M1–M8) with
  per-segment priority ratings; replaced by the qualitative version above at the user's request.
- Added `developer files/Project Concept.md` — the core product concept plus a per-segment
  mapping of how NeuroLady solves each audience's pain. Opens with the product definition and
  four believability pillars (human conversation with long-term memory, consistent appearance,
  consistent + auto-updating biography, rich proactive media incl. adult content where legal;
  north star = extended real-world Turing test), then walks all ~16 audience segments from
  `Audience.md` (Groups A/B/C) describing pain → concrete solution for each.
- Added a CLAUDE.md rule for future feature work: self-contained features must be built on a
  dedicated branch (`feature/<short-name>`), not directly on `master`; a feature branch may
  only be merged into `master` after all tests in `tests/` pass. Doc-only/config changes are
  unaffected and continue to go straight to `master` per the existing workflow.
- Moved `Audience.md` into `developer files/` (was briefly at the repo root). All future
  project documentation (concept, audience, research/planning notes) is now stored in
  `developer files/` — the intended single place for developer context — with `CLAUDE.md`
  as the sole exception, staying at the repo root so Claude Code auto-loads it.
- Added `Audience.md` — the product's target-audience definition. Structured
  into three macro-groups (A: B2C end users, B: B2B operators/businesses using NeuroLady as an
  engine, C: academic/scientific community) with ~16 segments profiled across geography, age,
  gender, income, tech-savviness, psychographics, pain points/JTBD, willingness to pay,
  acquisition channels, retention drivers, and objections/risks. Includes prioritization
  (beachhead = Russian-speaking Gen Z) and an ethics/positioning note. `Project Concept.md`
  is intentionally deferred to the next step per the user's request to start with audience.
- Moved `CLAUDE.md` back to the repo root (Claude Code auto-loads CLAUDE.md from the project
  root, so it needs to live there). `PROJECT_STATUS.md` and `VERSION` remain inside
  `developer files/`.
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
- **Feature branching**: self-contained features go on a dedicated `feature/<short-name>`
  branch and may only be merged into `master` once all tests in `tests/` pass.
- **Feedback logging**: whenever the user corrects an approach or states a preference, it is
  appended to the "Preferences and feedback" section of `CLAUDE.md` with a date, so it isn't
  repeated.
- **Language**: all `.md` files in this project must be written in English.
- **Project status**: this file (`PROJECT_STATUS.md`) must be kept current with technical
  detail on what has been built, to preserve context across sessions.

## Product / concept documentation

- `developer files/Audience.md` — target audience definition (see Recent changes).
- `developer files/Project Concept.md` — core product concept (Telegram-based hyper-realistic
  AI companion, personality engine, four believability pillars, extended real-world Turing test
  as the north-star goal) plus a per-audience-segment pain → solution mapping.
- `developer files/user_metrics.md` — qualitative (no numbers) description of the ideal use
  case and requirements per audience segment, plus shared quality dimensions.

## Current state of the codebase

- No application code yet — the repository contains `CLAUDE.md` at the root, plus a
  `developer files/` folder with `VERSION`, `Audience.md`, `Project Concept.md`,
  `user_metrics.md`, and this `PROJECT_STATUS.md`. No NeuroLady persona engine code has been
  added so far.
