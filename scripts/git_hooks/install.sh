#!/bin/bash
# Idempotently install the repo's git hooks into .git/hooks/.
ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
cp "$ROOT/scripts/git_hooks/pre-push" "$ROOT/.git/hooks/pre-push"
chmod +x "$ROOT/.git/hooks/pre-push"
echo "[git-hooks] installed pre-push → .git/hooks/pre-push"
