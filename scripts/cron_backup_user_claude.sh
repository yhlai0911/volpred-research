#!/bin/bash
# 每日自動快照 user-level ~/.claude → ops/claude_user_backup/（隨 git_push_backup commit+push）。
# 讓 global CLAUDE.md / user skills / memory 持續保鮮、隨 main repo 轉移，無需換機前手動跑。
# Canonical source；runtime copy 在 ~/.volpred/bin/cron_backup_user_claude.sh。
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/backup_user_claude.log 2>&1
cd /Users/yhlai0911/volpred-research
echo "=== [backup_user_claude] start $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
bash scripts/backup_user_claude.sh
_ec=$?
# 變動交給 git_push_backup 的 safety-net 自動 commit+push（不在此重複 commit 避免衝突）
echo "=== [backup_user_claude] exit ${_ec} at $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
exit ${_ec}
