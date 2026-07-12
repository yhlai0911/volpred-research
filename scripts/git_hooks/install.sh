#!/bin/bash
# Idempotently install the repo's git hooks into .git/hooks/.
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
for h in pre-push pre-commit prepare-commit-msg; do
  cp "$ROOT/scripts/git_hooks/$h" "$ROOT/.git/hooks/$h"
  chmod +x "$ROOT/.git/hooks/$h"
  echo "[git-hooks] installed $h → .git/hooks/$h"
done
