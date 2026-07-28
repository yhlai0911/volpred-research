#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/codex_update.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_codex_update.sh.
# After editing this file, sync with:
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
#
# 目的：codex-cli 作為輔助 agent 降低 Claude Code token 消耗，需定期更新到最新。
# 每週把 @openai/codex 更新到 latest（含 darwin-arm64 optional binary，缺它會 crash）。
# 僅在版本實際變動時寄 info email 給老闆，無變動安靜結束。

set -u
cd /Users/yhlai0911/volpred-research || exit 1

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
  echo "version changed ${BEFORE} -> ${AFTER}; regenerating CLI reference"

  # 升級後必須重生參考文件，否則 codex-cli skill 的參數表會停在舊版 —— 那正是
  # 2026-07-17 K1729 的成因（文件教了 exec 上不存在的 -a，照抄得到 exit 2 靜默失敗）。
  # 這一步跟升級綁在一起，文件才不會再落後 binary。
  REGEN=$(/opt/homebrew/bin/uv run python scripts/gen_codex_cli_reference.py 2>&1 | tail -1)
  echo "regen: ${REGEN}"

  # smoke：config 的 model 若不被新 CLI 支援會 API 400 靜默失敗（2026-07-10 事故卡死全平台）。
  SMOKE_OUT=$(bash scripts/codex_exec_bounded.sh --timeout 60 --skip-git-repo-check "echo TEST" 2>/dev/null)
  SMOKE_RC=$?
  echo "smoke: rc=${SMOKE_RC} out=${SMOKE_OUT}"
  if [ "$SMOKE_RC" -eq 0 ]; then
    SMOKE_LINE="✅ smoke 通過（\`echo TEST\` → exit 0）"
    LEVEL="info"
  else
    SMOKE_LINE="🚨 **smoke 失敗（rc=${SMOKE_RC}）— 升級後 codex 可能整條掛掉，請優先查**"
    LEVEL="warn"
  fi

  echo "emailing boss (level=${LEVEL})"
  /opt/homebrew/bin/uv run volpred ops send-alert --level "${LEVEL}" \
    --title "codex-cli 自動更新 ${BEFORE} → ${AFTER}" \
    --body "## 觸發條件
週度 codex-cli 自動更新 job (cron_codex_update.sh) 偵測到新版本。
before=${BEFORE} after=${AFTER}

## 影響
codex-cli 是降低 Claude Code token 消耗的輔助 agent（code review / 第二意見 / 針對性修正）。保持最新確保 model whitelist 與 bug fix 同步。

## 升級後自動驗證
- ${SMOKE_LINE}
- 參考文件已重生：\`${REGEN}\`（\`~/.claude/skills/codex-cli/references/cli-reference.md\`）

## 建議行動
smoke 通過則無需動作。若 codex_loop / codex review 出現異常，依 .claude/rules/experiments.md 的 Codex diagnostic 5 步排查。
⚠️ 0.144.5 起 dangerous-command 偵測收緊（更多 forced \`rm\` 形式被拒）—— 若自動化腳本原本會跑 \`rm\`，升級後可能開始被擋。" 2>&1 | tail -2
elif [ "$RC" -ne 0 ]; then
  echo "WARN: npm update failed (rc=$RC)"
else
  echo "no version change (${AFTER}); quiet exit"
fi
echo "=== [codex_update] exit ${RC} at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
