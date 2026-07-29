#!/bin/bash
# Operations Core-owned GitHub issue/PR comment notification ingress.

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/github_comment_notifications.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh || exit 1

_start=$SECONDS
cron_emit_start "github_comment_notifications" || exit 1
/usr/bin/perl -e 'alarm shift; exec @ARGV' 90 \
  /opt/homebrew/bin/uv run python scripts/github_comment_notifications.py
_ec=$?
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] GitHub comment notification ingress exceeded 90s"
fi
cron_emit_exit "github_comment_notifications" "$_ec" "$_start"
exit "$_ec"
