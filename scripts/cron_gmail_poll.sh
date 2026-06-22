#!/bin/bash
# Gmail inbox poll — fetch unseen mails, identify replies, queue as email_reply tasks.
# Schedule: */15 * * * * via host crontab.
# Canonical source: scripts/gmail_inbox_poll.py
# TCC copy: ~/.volpred/bin/cron_gmail_poll.sh

exec >> /Users/yhlai0911/.volpred/logs/gmail_poll.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

ulimit -Sn 65536 2>/dev/null || true

echo "=== gmail-poll $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Hard 180s cap. 2026-06-22: raised 60s→180s after gmail-poll stalled 2.5h —
# the poll does ~20 sequential IMAP FETCH round-trips and total latency is highly
# variable under the launchd context (measured 9s interactive / 33s minimal-env /
# >60s under real launchd as the SINCE-window email count grows). 60s was too tight
# and SIGALRM-killed legitimate work every fire (exit=142) → state froze, boss-email
# pipeline silently stalled. 180s gives headroom without overlap risk (fires every
# 15min). Genuine hang protection retained at the higher ceiling.
# Root-cause detail + dead-man check: docs/error_log.md 2026-06-22 gmail-poll entry.
/usr/bin/perl -e 'alarm shift; exec @ARGV' 180 \
  /Users/yhlai0911/.local/bin/uv run python /Users/yhlai0911/Desktop/volpred-research/scripts/gmail_inbox_poll.py --max 20
EXIT_CODE=$?

echo "=== gmail-poll end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="
# Canonical exit banner for src/volpred/ops/alerts.py host_cron_fail recogniser
echo "=== [gmail_poll] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
