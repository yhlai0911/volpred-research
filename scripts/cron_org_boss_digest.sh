#!/bin/bash

# Canonical source for the launchd-safe wrapper installed at
# ~/.volpred/bin/cron_org_boss_digest.sh.
#
# Delivery only — the judgement already happened. The coordinator decides what
# goes in (manager/outbox/digest_pending.md) and departments report into
# manager/inbox; this fires twice a day and folds whatever is there into ONE
# message. A quiet org sends nothing at all.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/org_boss_digest.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "org_boss_digest"
/opt/homebrew/bin/uv run python scripts/org/boss_digest.py --send
_ec=$?
cron_emit_exit "org_boss_digest" "$_ec" "$_start"
exit "$_ec"
