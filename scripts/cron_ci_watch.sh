#!/bin/bash
# Dedicated five-minute CI incident owner. Canonical schedule:
# config/runtime_schedules.json -> Operations Core.

source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh || exit 1

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/ci_watch.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1

STARTED_AT=${SECONDS}
cron_emit_start "ci_watch"

/opt/homebrew/bin/uv run python scripts/check_alerts.py --ci-only
EXIT_CODE=$?

cron_emit_exit "ci_watch" "${EXIT_CODE}" "${STARTED_AT}"
exit "${EXIT_CODE}"
