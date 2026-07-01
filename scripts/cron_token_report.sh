#!/bin/bash
# Daily token-usage report email (multi-angle HTML). Canonical source; cp to ~/.volpred/bin/.
REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/Desktop/volpred-research}"
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
LOG="${REPO_ROOT}/storage/logs/cron/token_report.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
cd "$REPO_ROOT" || exit 1
echo "=== token-report $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exec "$UV_BIN" run python "$REPO_ROOT/scripts/token_report_email.py"
