#!/bin/bash
# Reload the dispatch-supervisor daemon after a supervisor-code change.
#
# WHY THIS EXISTS (2026-07-10, ops-superv-restart-noise-20260710):
#   - The daemon freezes its Python image at boot; a change to
#     scripts/dispatch_supervisor/**.py only takes effect on reload.
#   - `launchctl kickstart -k` SIGTERMs the running instance (exit 143) and
#     launchd's KeepAlive respawns it — which, on plain reload, fired an INFO
#     "supervisor restart" email every time (5 in 80min during a dev session →
#     boss Telegram msg 352 noise complaint).
#   - This wrapper drops a short-lived planned-restart marker BEFORE kickstart;
#     the fresh boot consumes it and downgrades that one restart alert to a
#     log-only breadcrumb. Genuine (unexpected) KeepAlive respawns have no
#     marker and still alert.
#
# It ALSO enforces the reload safety gate from control-plane.md: refuse to
# reload while a worker is in flight (the restart orphan-cleanup would kill it).
#
# Usage:  bash scripts/reload_dispatch_supervisor.sh [--force] [--reason <r>]
#   --force   reload even if current_job is non-null (kills the in-flight worker)
#   --reason  marker reason label (default: deploy)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

LABEL="com.volpred.dispatch-supervisor"
STATE="storage/ops/dispatch_state.json"
REASON="deploy"
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --reason) REASON="${2:-deploy}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# 1. In-flight guard — never yank the rug from a running worker.
CURRENT_JOB="$(jq -r '.current_job // "null"' "$STATE" 2>/dev/null || echo "null")"
if [ "$CURRENT_JOB" != "null" ] && [ "$FORCE" -ne 1 ]; then
  echo "REFUSED: current_job is not null (a worker is in flight):" >&2
  jq -c '.current_job' "$STATE" >&2 || true
  echo "Wait for it to finish, or pass --force to reload anyway (kills the worker)." >&2
  exit 1
fi

# 2. Drop the planned-restart marker so the imminent restart alert is suppressed.
uv run python -c "
from scripts.dispatch_supervisor import state
exp = state.write_planned_restart_marker(reason='${REASON}')
print(f'planned-restart marker written (reason=${REASON}, expires_at={exp})')
"

# 3. Reload the daemon.
UID_NUM="$(id -u)"
echo "kickstart -k gui/${UID_NUM}/${LABEL} ..."
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"
echo "Reload requested. Verify: launchctl list | grep dispatch-supervisor"
echo "The next boot's 'supervisor restart' INFO alert is suppressed (deploy)."
