#!/usr/bin/env sh
# Point git at the versioned hooks in scripts/git-hooks. Run ONCE per clone/worktree.
#   sh scripts/install-git-hooks.sh
#
# core.hooksPath is a local git setting — it does NOT travel with a clone, so a fresh checkout has
# no protection until this runs. The heavy-asset landmine has cost real money twice; installing
# these hooks is the first thing to do after cloning, before any checkout/merge/pull.
set -eu
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath scripts/git-hooks
chmod +x scripts/git-hooks/pre-commit scripts/git-hooks/post-checkout \
         scripts/git-hooks/post-merge scripts/git-hooks/heavy-asset-check.sh \
         scripts/safe-checkout.sh 2>/dev/null || true
echo "installed: core.hooksPath -> scripts/git-hooks"
echo "  pre-commit      : refuses to commit any symlink (the landmine can never enter a ref)"
echo "  post-checkout   : screams if a heavy asset became a symlink or vanished"
echo "  post-merge      : same, after merge/pull"
echo "  safe-checkout.sh: inspect a TARGET ref for symlinks before switching to it"
