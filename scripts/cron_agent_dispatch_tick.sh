#!/bin/bash

# Operations Core is the only clock. This wrapper delivers one tick to the
# KeepAlive dispatch executor, which owns worker concurrency and health only.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/agent_dispatch_tick.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "agent_dispatch_tick"

/opt/homebrew/bin/uv run python -m scripts.dispatch_supervisor.trigger \
  --reason operations_core_tick \
  --timeout-seconds 20
_ec=$?

cron_emit_exit "agent_dispatch_tick" "$_ec" "$_start"
exit "$_ec"
