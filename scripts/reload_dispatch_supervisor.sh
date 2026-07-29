#!/bin/bash
# Reload the dispatch-supervisor daemon after a supervisor-code change.
#
# WHY THIS EXISTS (2026-07-10, ops-superv-restart-noise-20260710):
#   - The daemon freezes its Python image at boot; a change to
#     scripts/dispatch_supervisor/**.py only takes effect on reload.
#   - A durable-intent SIGTERM ends the exact running instance and launchd's
#     KeepAlive respawns it — which, on plain reload, fired an INFO
#     "supervisor restart" email every time (5 in 80min during a dev session →
#     boss Telegram msg 352 noise complaint).
#   - This wrapper drops a short-lived planned-restart marker BEFORE SIGTERM;
#     the fresh boot consumes it and downgrades that one restart alert to a
#     log-only breadcrumb. Genuine (unexpected) KeepAlive respawns have no
#     marker and still alert.
#
# It ALSO enforces the reload safety gate from control-plane.md: refuse to
# reload while a worker is in flight (the restart orphan-cleanup would kill it).
#
# Usage:  bash scripts/reload_dispatch_supervisor.sh [--force|--defer] [--reason <r>]
#   --force   reload even if current_jobs is non-empty (kills in-flight workers)
#   --defer   persist a request; the daemon reloads itself after full drain
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
STATE="${DISPATCH_STATE_PATH:-storage/ops/dispatch_state.json}"
REASON="deploy"
FORCE=0
DEFER=0
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

if [ -n "${VOLPRED_UV_BIN:-}" ]; then
  UV_BIN="$VOLPRED_UV_BIN"
elif [ -x /opt/homebrew/bin/uv ]; then
  UV_BIN=/opt/homebrew/bin/uv
else
  UV_BIN="$(command -v uv || true)"
fi
if [ -z "$UV_BIN" ] || [ "${UV_BIN#/}" = "$UV_BIN" ] || [ ! -x "$UV_BIN" ]; then
  echo "verified absolute uv executable not found" >&2
  exit 1
fi

read_active_count() {
  jq -er '(((.current_jobs // []) as $jobs
      | if ($jobs | length) > 0 then $jobs
        elif .current_job then [.current_job] else [] end) | length)
    + (if ((.phase_z_pending // []) | length) > 0 then 1 else 0 end)' \
    "$STATE" 2>/dev/null || echo "ERR"
}

arm_durable_release() {
  REQUEST_JSON="$(
    "$UV_BIN" run python -m scripts.dispatch_supervisor.deferred_reload arm \
      --state "$STATE" --reason "$REASON" --max-wait-s "$DEFER_MAX_WAIT_S"
  )"
  REQUEST_ID="$(printf '%s' "$REQUEST_JSON" | jq -er '.request_id')"
  CREATED="$(printf '%s' "$REQUEST_JSON" | jq -er '.created')"
  echo "DURABLE: immutable release request ${REQUEST_ID} armed (created=${CREATED}, max ${DEFER_MAX_WAIT_S}s)."
  echo "The dispatch-supervisor health loop owns drain, activation, signal, and fresh-boot receipt."
}

# Durable ownership transfer: --defer never spawns a child poller.  The active
# supervisor health loop consumes this mode-0600 request after current_jobs and
# phase_z_pending drain, so caller/session teardown cannot cancel deployment.
if [ "$DEFER" -eq 1 ]; then
  arm_durable_release
  exit 0
fi

# 1. In-flight guard — never yank the rug from a running worker.
ACTIVE_COUNT="$(read_active_count)"
if [ "$ACTIVE_COUNT" != "0" ] && [ "$FORCE" -ne 1 ]; then
  echo "REFUSED: current_jobs has ${ACTIVE_COUNT} in-flight worker(s):" >&2
  jq -c '.current_jobs // (if .current_job then [.current_job] else [] end)' "$STATE" >&2 || true
  echo "Wait for it to finish, --defer to reload when it does, or --force (kills the worker)." >&2
  exit 1
fi

if [ "${VOLPRED_RELOAD_CHECK_ONLY:-0}" = "1" ]; then
  echo "SAFE: no current_jobs/current_job/phase_z_pending"
  exit 0
fi

# Normal deploys always go through an immutable committed release image.  The
# direct termination path below is break-glass --force only.
if [ "$FORCE" -ne 1 ]; then
  arm_durable_release
  exit 0
fi

# 2. Break-glass force: drop the planned-restart marker before termination.
"$UV_BIN" run python -c '
import sys
from scripts.dispatch_supervisor import state
reason = sys.argv[1]
exp = state.write_planned_restart_marker(reason=reason)
print(f"planned-restart marker written (reason={reason}, expires_at={exp})")
' "$REASON"

# 3. Reload the daemon.
UID_NUM="$(id -u)"
echo "durable SIGTERM + KeepAlive restart gui/${UID_NUM}/${LABEL} ..."
"$UV_BIN" run python scripts/termination_launchd_restart.py \
  --service "gui/${UID_NUM}/${LABEL}" --reason "dispatch_supervisor_reload:${REASON}"
echo "Reload requested. Verify: launchctl list | grep dispatch-supervisor"
echo "The next boot's 'supervisor restart' INFO alert is suppressed (deploy)."
