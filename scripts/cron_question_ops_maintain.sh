#!/bin/bash
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/question_ops_maintain.log 2>&1
# Canonical source. cron-exec target at ~/.volpred/bin/cron_question_ops_maintain.sh
# After editing this file, sync with:
#   uv run python scripts/sync_cron_wrappers.py --apply
cd /Users/yhlai0911/volpred-research
echo "=== question-ops-maintain $(date '+%Y-%m-%d %H:%M:%S') ==="
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "question_ops_maintain"
/opt/homebrew/bin/uv run volpred ops question-ops-maintain --source user --auto-create-task --stub-if-no-work
_ec=$?
cron_emit_exit "question_ops_maintain" "$_ec" "$_start"
exit "$_ec"
