#!/bin/bash

# Shared helpers for host-cron / LaunchAgent wrappers.
# Keep this file POSIX-light so individual wrappers can source it safely.

if [ -z "${VOLPRED_CRON_LIB_LOADED:-}" ]; then
  VOLPRED_CRON_LIB_LOADED=1

  cron_now_iso() {
    date '+%Y-%m-%d %H:%M:%S %Z'
  }

  cron_emit_start() {
    local job_name=$1
    echo "=== [${job_name}] $(cron_now_iso) start ==="
  }

  cron_emit_exit() {
    local job_name=$1
    local exit_code=$2
    local started_at=${3:-${SECONDS}}
    local duration=$((SECONDS - started_at))
    echo "=== [${job_name}] exit ${exit_code} at $(cron_now_iso) (duration=${duration}s) ==="
  }
fi
