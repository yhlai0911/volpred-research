#!/bin/bash

# Shared helpers for host-cron / LaunchAgent wrappers.
# Keep this file POSIX-light so individual wrappers can source it safely.

if [ -z "${VOLPRED_CRON_LIB_LOADED:-}" ]; then
  VOLPRED_CRON_LIB_LOADED=1

  # Anchor to this file's own directory, not the caller's cwd: cron_emit_exit
  # runs at the END of a wrapper, by which time the job may have chdir'd.
  _VOLPRED_CRON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  VOLPRED_REPO_ROOT="${VOLPRED_REPO_ROOT:-$(dirname "${_VOLPRED_CRON_LIB_DIR}")}"

  # Scheduled jobs write their diagnostics somewhere a detector can read.
  # `volpred.diagnostics.warn()` — the helper .claude/rules/no-silent-fallback.md
  # mandates across the codebase — defaulted to stderr only, which in a wrapper
  # means a per-job log file nobody polls. That is how compute_queue's settlement
  # loop warned ~2,500 times over 13 days without raising anything (2026-08-03).
  # The JSONL is what alerts.py:_parse_recurring_diagnostic_warning_state reads,
  # and it is size-capped with one rotation generation, so turning it on here
  # cannot become the next unbounded-file incident.
  export VOLPRED_DIAGNOSTICS_PERSIST="${VOLPRED_DIAGNOSTICS_PERSIST:-1}"

  cron_now_iso() {
    date '+%Y-%m-%d %H:%M:%S %Z'
  }

  cron_emit_start() {
    local job_name=$1
    # The canonical config transfers business ownership before live OS schedule
    # surfaces are removed. macOS can leave a stale cron/LaunchAgent trigger
    # behind (or hang while rewriting crontab); that clock must become a no-op,
    # never a second business owner. Operations Core sets its owner explicitly
    # and bypasses this legacy-side gate.
    if [ "${VOLPRED_SCHEDULE_OWNER:-legacy}" != "operations_core" ]; then
      /usr/bin/env python3 "${VOLPRED_REPO_ROOT}/scripts/cron_owner_gate.py" \
        --wrapper "$0"
      local owner_gate_rc=$?
      if [ "${owner_gate_rc}" = "75" ]; then
        echo "=== [${job_name}] legacy trigger suppressed by Operations Core ownership ==="
        # Emit an authoritative exit-0 marker on suppression. host_cron_fail's
        # _latest_cron_exit reads the last `=== [job] exit N ... ===` line; a
        # legacy job that failed ONCE before the ownership transfer would otherwise
        # leave that failure frozen as the newest marker. These piggy-back jobs have
        # no cron expr, so the recency gate (_stale_cron_exit_reason) can't age it
        # out and the alert re-breaches every hour. Suppression is a healthy no-op —
        # the wrapper correctly deferred to Operations Core — so record it as exit 0.
        cron_emit_exit "${job_name}" 0
        exit 0
      fi
      if [ "${owner_gate_rc}" != "0" ]; then
        echo "=== [${job_name}] ERROR ownership ambiguous; fail-closed rc=${owner_gate_rc} ==="
        exit "${owner_gate_rc}"
      fi
    fi
    echo "=== [${job_name}] $(cron_now_iso) start ==="
  }

  # Record the job's last SUCCESSFUL run in storage/ops/cron_last_run.json.
  #
  # 2026-07-10: cron_emit_exit used to only echo a banner into the job's own log,
  # and the sole writer of cron_last_run.json was run_due_jobs.py. Jobs flagged
  # `piggy_back_skip: true` are never fired by run_due_jobs (their LaunchAgent
  # owns them, so the piggy-back can't double-fire), so their marker froze on the
  # day that flag went in — memory_health_daily ran every morning while the
  # freshness monitor read a 42-day-old timestamp. Only the wrapper knows it ran,
  # so the wrapper records it. See scripts/cron_mark_last_run.py.
  #
  # We pass `$0` (this wrapper's own path), NOT ${job_name}: that first argument
  # is a free-text log label, and 8 wrappers already drift from their config id
  # (market_calendar_sync logs as "market_cal", supabase_sync_drain as
  # "drain_failed_syncs", …). The helper reverse-looks-up the id from
  # config/runtime_schedules.json, so a drifting label can never route a marker
  # to a key nobody reads.
  #
  # exit 0 only: a job that runs but always FAILS must go stale — that outage is
  # precisely what the monitor exists to surface.
  #
  # Fail-open, never silent: a bookkeeping failure prints a WARN into this job's
  # log and cannot change the wrapper's exit code. Plain python3 rather than
  # `uv run` — the helper is stdlib-only, and uv has hung >6min resolving cwd in
  # a launchd context (docs/error_log.md 2026-07-02).
  cron_mark_last_run() {
    local wrapper_path=$1
    local exit_code=$2
    [ "${exit_code}" = "0" ] || return 0
    /usr/bin/env python3 "${VOLPRED_REPO_ROOT}/scripts/cron_mark_last_run.py" \
      --wrapper "${wrapper_path}" 2>&1 \
      || echo "=== WARN cron_mark_last_run failed (rc=$?) for ${wrapper_path}; marker not updated ==="
    return 0
  }

  cron_emit_exit() {
    local job_name=$1
    local exit_code=$2
    local started_at=${3:-${SECONDS}}
    local duration=$((SECONDS - started_at))
    echo "=== [${job_name}] exit ${exit_code} at $(cron_now_iso) (duration=${duration}s) ==="
    # $0 = the wrapper script being executed (source does not rewrite $0).
    cron_mark_last_run "$0" "${exit_code}"
  }
fi
