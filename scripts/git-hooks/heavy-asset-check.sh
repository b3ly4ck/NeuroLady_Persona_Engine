#!/usr/bin/env sh
# Shared detector used by post-checkout and post-merge. Runs right AFTER git touched the tree and
# screams if any heavy asset path became a symlink (the landmine materialized) or vanished. It
# cannot undo the operation, but it turns a silent 30G loss into an immediate, unmissable stop —
# and blocks the follow-on merge that last time erased the evidence.
#
# These paths are gitignored real directories. A symlink where one belongs = STOP.
set -u

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
GUARDED="image/models image/comfyui image/.venv chat/models"

problems=""
for rel in $GUARDED; do
  p="$REPO_ROOT/$rel"
  if [ -L "$p" ]; then
    problems="$problems\n  SYMLINK where a real directory belongs: $rel -> $(readlink "$p")"
  elif [ ! -e "$p" ]; then
    # Missing is worth a warning but not always fatal (a fresh clone has none yet); flag it.
    problems="$problems\n  MISSING (was it clobbered?): $rel"
  fi
done

if [ -n "$problems" ]; then
  echo "============================================================================" >&2
  echo " !!! HEAVY-ASSET GUARD TRIPPED — STOP, do not run any further git command !!!" >&2
  printf "%b\n" "$problems" >&2
  echo "" >&2
  echo " A symlink where a real dir belongs is the checkpoint-destroying landmine." >&2
  echo " Do NOT merge/checkout/pull further. See CLAUDE.md 'NEVER destroy heavy assets'." >&2
  echo " Recover the missing asset(s) via image/download_model.py + image/_install_comfy.sh," >&2
  echo " and preferably relocate them OUTSIDE the repo, referenced by IMAGE_* env vars." >&2
  echo "============================================================================" >&2
  exit 1
fi
exit 0
