#!/usr/bin/env sh
# safe-checkout.sh <ref> — inspect the TARGET ref for the symlink landmine BEFORE switching to it.
#
# The whole reason the checkpoint died a second time: the pre-flight check was run against the ref
# we were ON, not the ref we were switching TO. `git ls-files` describes HEAD; it says nothing about
# where you are going. This inspects the target tree itself, so a stale/behind branch that still
# carries the tracked symlinks is caught before `git checkout` can materialize them.
#
# Usage:  scripts/safe-checkout.sh master      # inspect, then checkout only if clean
#         scripts/safe-checkout.sh --check origin/master   # inspect only, no checkout
set -eu

[ $# -ge 1 ] || { echo "usage: $0 [--check] <ref>" >&2; exit 2; }
CHECK_ONLY=0
[ "$1" = "--check" ] && { CHECK_ONLY=1; shift; }
REF="$1"

echo ">> fetching so the local view of remotes is current..."
git fetch --quiet --all --prune || echo "   (fetch failed — proceeding with local refs)"

# Inspect the TARGET tree, not HEAD.
symlinks=$(git ls-tree -r "$REF" 2>/dev/null | awk '$1==120000 {print "  "$4}')
if [ -n "$symlinks" ]; then
  echo "============================================================================" >&2
  echo " REFUSING to checkout '$REF' — its tree carries tracked SYMLINK(s):" >&2
  echo "$symlinks" >&2
  echo "" >&2
  echo " Checking this out would materialize them over your real directories and" >&2
  echo " delete the gitignored heavy assets underneath (the checkpoint-loss landmine)." >&2
  echo " This ref is unsafe; do not switch to it. See CLAUDE.md 'NEVER destroy heavy assets'." >&2
  echo "============================================================================" >&2
  exit 1
fi

# Also warn if the local ref is behind its remote — a behind branch is a restored snapshot of
# whatever landmine existed at that older point, even if HEAD/origin look clean now.
if git rev-parse --verify --quiet "origin/$REF" >/dev/null 2>&1; then
  behind=$(git rev-list --count "$REF..origin/$REF" 2>/dev/null || echo 0)
  [ "$behind" -gt 0 ] && echo ">> NOTE: '$REF' is $behind commit(s) BEHIND origin/$REF — consider pulling first."
fi

echo ">> '$REF' tree is clean of tracked symlinks."
[ "$CHECK_ONLY" = "1" ] && exit 0
echo ">> checking out '$REF'..."
git checkout "$REF"
