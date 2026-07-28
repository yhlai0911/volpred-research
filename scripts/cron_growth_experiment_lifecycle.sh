#!/bin/bash
# Operations Core-owned Issue #27 growth lifecycle reconciler.

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/growth_experiment_lifecycle.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh || exit 1

_start=$SECONDS
cron_emit_start "growth_experiment_lifecycle" || exit 1
/usr/bin/perl -e 'alarm shift; exec @ARGV' 90 \
  /opt/homebrew/bin/uv run volpred ops growth-experiment reconcile-template \
  --template-json config/growth_experiments/article-share-cta-copy-v1.template.json
_ec=$?
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] growth experiment lifecycle exceeded 90s"
fi
cron_emit_exit "growth_experiment_lifecycle" "$_ec" "$_start"
exit "$_ec"
