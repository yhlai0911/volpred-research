#!/bin/bash
# Canonical Graphify freshness reconciliation. The formal schedule is
# config/runtime_schedules.json; this wrapper is installed to ~/.volpred/bin.
REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/volpred-research}"
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
LOG="${REPO_ROOT}/storage/logs/cron/graphify_maintain.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
cd "$REPO_ROOT" || exit 1
echo "=== graphify-maintain $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exec "$UV_BIN" run python scripts/graphify_integration.py update --graph all
