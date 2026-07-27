#!/bin/bash
# Operations Core-owned Issue #46 typed-signal producer.

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/legacy_retirement_signal_materialize.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh

_start=$SECONDS
cron_emit_start "legacy_retirement_signal_materialize"
/usr/bin/perl -e 'alarm shift; exec @ARGV' 60 \
  /opt/homebrew/bin/uv run python scripts/materialize_legacy_business_fire_signal.py
_ec=$?
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] legacy retirement signal materializer exceeded 60s"
fi
cron_emit_exit "legacy_retirement_signal_materialize" "$_ec" "$_start"
exit "$_ec"
