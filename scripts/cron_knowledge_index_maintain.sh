#!/bin/bash

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/knowledge_index_maintain.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "knowledge_index_maintain"
/opt/homebrew/bin/uv run volpred ops knowledge-index-maintain --stub-if-no-work
_ec=$?
cron_emit_exit "knowledge_index_maintain" "$_ec" "$_start"
exit "$_ec"
