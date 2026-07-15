#!/bin/bash
# Idempotently install repo hooks into the common Git directory.  Linked
# worktrees have a .git *file*, so "$ROOT/.git/hooks" is not a valid owner.
set -euo pipefail

SOURCE_ROOT="$(/usr/bin/git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
COMMON_DIR="$(/usr/bin/git -C "$SOURCE_ROOT" rev-parse --path-format=absolute --git-common-dir)"
ROOT="$(cd "$(dirname "$COMMON_DIR")" && pwd -P)"
SOURCE_ROOT="$(cd "$SOURCE_ROOT" && pwd -P)"
if [ "$SOURCE_ROOT" != "$ROOT" ]; then
  echo "[git-hooks] REFUSED: install must run from canonical main root, not linked worktree $SOURCE_ROOT" >&2
  exit 1
fi
if [ "$(/usr/bin/git -C "$ROOT" symbolic-ref -q HEAD 2>/dev/null || true)" != "refs/heads/main" ]; then
  echo "[git-hooks] REFUSED: canonical checkout must have symbolic HEAD=refs/heads/main" >&2
  exit 1
fi

# Hook replacement is itself a Git control-plane write.  Re-enter once under
# the same canonical lease used by commits/merges; validate-inherited checks
# the kernel FD plus the non-recreatable capability FD, not a marker variable.
LOCK_HELPER="$ROOT/scripts/git_writer_lock.py"
if ! /usr/bin/python3 "$LOCK_HELPER" validate-inherited \
      --repo "$ROOT" --actor git-hook-installer >/dev/null 2>&1; then
  exec /usr/bin/python3 "$LOCK_HELPER" run --repo "$ROOT" \
    --actor git-hook-installer --command-timeout 120 -- /bin/bash "$0"
fi

HOOK_DIR="$COMMON_DIR/hooks"
/bin/mkdir -p "$HOOK_DIR"
umask 077

install_one() {
  local h="$1" src="$ROOT/scripts/git_hooks/$1" dst="$HOOK_DIR/$1" tmp
  tmp="$HOOK_DIR/.$1.tmp.$$"
  if ! /bin/cp "$src" "$tmp" || ! /bin/chmod 0755 "$tmp"; then
    /bin/rm -f "$tmp"
    return 1
  fi
  # Same-directory rename is atomic: live hooks are never truncated/empty.
  if ! /bin/mv -f "$tmp" "$dst"; then
    /bin/rm -f "$tmp"
    return 1
  fi
  echo "[git-hooks] installed $h → $HOOK_DIR/$h"
}

# The gate must never point at a missing verifier.  Install capability first,
# auxiliary hooks next, and replace reference-transaction last.
for h in git-writer-lease-verify.py pre-push pre-commit prepare-commit-msg reference-transaction; do
  install_one "$h"
done
