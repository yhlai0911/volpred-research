#!/bin/bash
# Gmail inbox poll — fetch unseen mails, identify replies, queue as email_reply tasks.
# Schedule: */15 * * * * via host crontab.
# Canonical source: scripts/gmail_inbox_poll.py
# TCC copy: ~/.volpred/bin/cron_gmail_poll.sh

exec >> /Users/yhlai0911/.volpred/logs/gmail_poll.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

ulimit -Sn 65536 2>/dev/null || true

echo "=== gmail-poll $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Hard 60s cap — IMAP fetch should complete in seconds; if hung, kill cleanly
/usr/bin/perl -e 'alarm shift; exec @ARGV' 60 \
  /Users/yhlai0911/.local/bin/uv run python /Users/yhlai0911/Desktop/volpred-research/scripts/gmail_inbox_poll.py --max 20
EXIT_CODE=$?

echo "=== gmail-poll end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="
# Canonical exit banner for src/volpred/ops/alerts.py host_cron_fail recogniser
echo "=== [gmail_poll] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
