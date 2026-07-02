#!/bin/bash

# Canonical wrapper for refreshing storage/publication_candidates.json.
# Runtime copy lives at ~/.volpred/bin/cron_build_publication_candidates.sh.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/publication_candidates_refresh.log 2>&1

cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh

LOCKDIR=/tmp/volpred_publication_candidates_refresh.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== [publication_candidates_refresh] $(date '+%Y-%m-%d %H:%M:%S %Z') skip - refresh lock already held ==="
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

_start=$SECONDS
cron_emit_start "publication_candidates_refresh"
/usr/bin/perl -e 'alarm shift; exec @ARGV' 180 /opt/homebrew/bin/uv run python scripts/build_publication_candidates.py
_ec=$?
cron_emit_exit "publication_candidates_refresh" "$_ec" "$_start"
exit "$_ec"
