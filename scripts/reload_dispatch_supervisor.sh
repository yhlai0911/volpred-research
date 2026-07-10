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
# Usage:  bash scripts/reload_dispatch_supervisor.sh [--force|--defer] [--reason <r>]
#   --force   reload even if current_job is non-null (kills the in-flight worker)
#   --defer   if a worker is in flight, detach and reload once it finishes
#   --reason  marker reason label (default: deploy)
#
# --defer exists because the commonest reloader is an hourly-dispatch fire that
# changed supervisor code — it IS the in-flight worker, so it can neither reload
# now (guard refuses, correctly) nor --force (that would kill itself). Deferring
# keeps "code change → live" inside the fire that made the change, instead of
# leaving a stale-code daemon for the next fire's alert to discover.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

LABEL="com.volpred.dispatch-supervisor"
STATE="storage/ops/dispatch_state.json"
REASON="deploy"
FORCE=0
DEFER=0
DEFER_POLL_S="${DEFER_POLL_S:-30}"
DEFER_MAX_WAIT_S="${DEFER_MAX_WAIT_S:-3900}"  # 65min — one hourly cap (50min) + slack
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --defer) DEFER=1; shift ;;
    --reason) REASON="${2:-deploy}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ "$FORCE" -eq 1 ] && [ "$DEFER" -eq 1 ]; then
  echo "--force and --defer are mutually exclusive" >&2
  exit 2
fi

read_current_job() { jq -r '.current_job // "null"' "$STATE" 2>/dev/null || echo "null"; }

# 1. In-flight guard — never yank the rug from a running worker.
CURRENT_JOB="$(read_current_job)"
if [ "$CURRENT_JOB" != "null" ] && [ "$FORCE" -ne 1 ]; then
  if [ "$DEFER" -ne 1 ]; then
    echo "REFUSED: current_job is not null (a worker is in flight):" >&2
    jq -c '.current_job' "$STATE" >&2 || true
    echo "Wait for it to finish, --defer to reload when it does, or --force (kills the worker)." >&2
    exit 1
  fi
  # Detached waiter: poll until the worker clears, then re-enter this script.
  # Re-entering (rather than inlining the reload) keeps the marker + kickstart
  # path single-source. `setsid`-equivalent detach so it outlives this fire.
  echo "DEFERRED: worker in flight; reload will fire when current_job clears (max ${DEFER_MAX_WAIT_S}s)."
  DEFER_LOG="${HOME}/.volpred/logs/supervisor_deferred_reload.log"
  mkdir -p "$(dirname "$DEFER_LOG")"
  nohup bash -c '
    deadline=$(( $(date +%s) + '"$DEFER_MAX_WAIT_S"' ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
      sleep '"$DEFER_POLL_S"'
      cj=$(jq -r ".current_job // \"null\"" "'"$REPO/$STATE"'" 2>/dev/null || echo null)
      if [ "$cj" = "null" ]; then
        echo "[$(date "+%F %T")] worker cleared — reloading (reason='"$REASON"')"
        exec bash "'"$REPO"'/scripts/reload_dispatch_supervisor.sh" --reason "'"$REASON"'"
      fi
    done
    echo "[$(date "+%F %T")] DEFER TIMED OUT after '"$DEFER_MAX_WAIT_S"'s — supervisor still running stale code."
    echo "[$(date "+%F %T")] The dispatch_supervisor_stale_code alert is the backstop; reload manually."
  ' >> "$DEFER_LOG" 2>&1 < /dev/null &
  disown $! 2>/dev/null || true
  echo "Waiter detached (pid $!). Log: $DEFER_LOG"
  exit 0
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
