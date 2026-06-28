#!/bin/bash
# Daily safety net: reconstruct missing work_log entries from recent [codex] commits.
# Canonical source: scripts/cron_backfill_work_log_from_commits.sh
# Runtime copy: ~/.volpred/bin/cron_backfill_work_log_from_commits.sh

REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/Desktop/volpred-research}"
VOLPRED_HOME_DIR="${VOLPRED_HOME_DIR:-/Users/yhlai0911/.volpred}"
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
LOG_PATH="${LOG_PATH:-$VOLPRED_HOME_DIR/logs/codex_work_log_backfill.log}"

mkdir -p "$(dirname "$LOG_PATH")"
exec >> "$LOG_PATH" 2>&1
cd "$REPO_ROOT" || exit 1

echo "=== [codex_work_log_backfill] fire at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

if [ -n "$(/usr/bin/git status --porcelain -- storage/work_log.json 2>/dev/null)" ]; then
  echo "[codex_work_log_backfill] storage/work_log.json already dirty; skip to avoid mixing state"
  echo "=== [codex_work_log_backfill] exit 0 at $(date '+%Y-%m-%d %H:%M:%S %Z') (dirty-skip) ==="
  exit 0
fi

SINCE=$(python3 - <<'PY'
from datetime import datetime, timedelta

now = datetime.now().astimezone()
start = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
print(start.strftime("%Y-%m-%d %H:%M %z"))
PY
)

"$UV_BIN" run python scripts/backfill_work_log_from_commits.py --since "$SINCE" --apply
RC=$?

if [ "$RC" -eq 0 ] && [ -n "$(/usr/bin/git status --porcelain -- storage/work_log.json 2>/dev/null)" ]; then
  /usr/bin/git add storage/work_log.json
  /usr/bin/git commit -m "ops(codex-loop): daily work_log backfill"
fi

echo "=== [codex_work_log_backfill] exit $RC at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exit "$RC"
