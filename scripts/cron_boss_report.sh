#!/bin/bash
# Boss report wrapper — the SOLE periodic operations email cadence (WS-H2).
# Canonical source; install via scripts/sync_cron_wrappers.py --apply.
#
# Editions by Taiwan-time fire hour (config boss_report_4h: 10 8,14,20 * * *):
#   08:10 -> --window-hours 12  (covers overnight since the 20:10 close)
#   14:10 -> --window-hours 6   (covers since 08:10)
#   20:10 -> --daily-close      (24h window + day-close sections; replaces the
#                                retired work_summary_6h job, 2026-07-20 WS-H2)
# Any other hour (e.g. a stale host crontab line not yet reconciled via
# scripts/install_host_crontab.sh) falls back to the plain 4h edition.
cd /Users/yhlai0911/volpred-research
HOUR_TW="$(TZ=Asia/Taipei date +%H)"
FLAGS=""
case "$HOUR_TW" in
  08) FLAGS="--window-hours 12" ;;
  14) FLAGS="--window-hours 6" ;;
  20) FLAGS="--daily-close" ;;
esac
echo "=== [boss_report] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) (tw_hour=$HOUR_TW flags='$FLAGS') ==="
/opt/homebrew/bin/uv run python scripts/boss_report.py $FLAGS
EC=$?
echo "=== [boss_report] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
