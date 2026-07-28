#!/bin/bash
# Operations Core-owned Issue #46 canonical retirement observation recorder.

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/legacy_retirement_observe.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh || exit 1

_start=$SECONDS
cron_emit_start "legacy_retirement_observe" || exit 1
/usr/bin/perl -e 'alarm shift; exec @ARGV' 240 \
  /opt/homebrew/bin/uv run python scripts/record_legacy_retirement_observation.py
_ec=$?
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] legacy retirement observation recorder exceeded 240s"
fi
cron_emit_exit "legacy_retirement_observe" "$_ec" "$_start"
exit "$_ec"
