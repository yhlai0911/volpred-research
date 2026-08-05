#!/bin/bash

# Canonical source for the launchd-safe wrapper installed at
# ~/.volpred/bin/cron_org_manager_tick.sh.
# Live since 2026-08-05: the zero-cost hard-fact gate still runs first and skips
# without spawning anything; when it fires, it wakes the coordinator — its live
# cockpit pane if one is idle, otherwise one headless round under a lease.
# Roll back to observation-only by appending --shadow to the command below.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/org_manager_tick.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "org_manager_tick"
# Intake runs first so the gate evaluates a pool that already contains whatever
# the issue tracker registered this round. Its exit code is deliberately not the
# wrapper's: an unreachable GitHub must never stop the coordinator from being
# woken for everything else. Whether it ran is visible in this log and in the
# github_intake receipt, so "it silently stopped" cannot masquerade as "quiet".
/opt/homebrew/bin/uv run python scripts/org/org_intake.py --github --apply || \
    echo "[org_manager_tick] github intake failed (rc=$?) — 繼續跑 gate"
/opt/homebrew/bin/uv run python scripts/org/manager_tick.py
_ec=$?
cron_emit_exit "org_manager_tick" "$_ec" "$_start"
exit "$_ec"
