#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/codex_update.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_codex_update.sh.
# After editing this file, sync with:
#   cp scripts/cron_codex_update.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_codex_update.sh
#
# 目的：codex-cli 作為輔助 agent 降低 Claude Code token 消耗，需定期更新到最新。
# 每週把 @openai/codex 更新到 latest（含 darwin-arm64 optional binary，缺它會 crash）。
# 僅在版本實際變動時寄 info email 給老闆，無變動安靜結束。

set -u
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

# nvm node 的 npm / codex 路徑（cron/launchd env 無 nvm shim）
export PATH="/Users/yhlai0911/.nvm/versions/node/v22.20.0/bin:$PATH"

echo "=== [codex_update] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="
BEFORE=$(codex --version 2>/dev/null | awk '{print $NF}')
echo "before: ${BEFORE:-unknown}"

npm install -g @openai/codex@latest --include=optional 2>&1 | tail -5
RC=$?

AFTER=$(codex --version 2>/dev/null | awk '{print $NF}')
echo "after: ${AFTER:-unknown} (npm rc=$RC)"

if [ "$RC" -eq 0 ] && [ -n "$AFTER" ] && [ "$BEFORE" != "$AFTER" ]; then
  echo "version changed ${BEFORE} -> ${AFTER}; emailing boss"
  /opt/homebrew/bin/uv run volpred ops send-alert --level info \
    --title "codex-cli 自動更新 ${BEFORE} → ${AFTER}" \
    --body "## 觸發條件
週度 codex-cli 自動更新 job (cron_codex_update.sh) 偵測到新版本。
before=${BEFORE} after=${AFTER}

## 影響
codex-cli 是降低 Claude Code token 消耗的輔助 agent（code review / 第二意見 / 針對性修正）。保持最新確保 model whitelist 與 bug fix 同步。

## 建議行動
無需動作。若 codex_loop / codex review 出現異常，依 .claude/rules/experiments.md 的 Codex diagnostic 5 步排查。" 2>&1 | tail -2
elif [ "$RC" -ne 0 ]; then
  echo "WARN: npm update failed (rc=$RC)"
else
  echo "no version change (${AFTER}); quiet exit"
fi
echo "=== [codex_update] exit ${RC} at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
