#!/bin/bash

set -euo pipefail

ROOT="${VOLPRED_HOOK_ROOT:-/Users/yhlai0911/volpred-research}"
INPUT="$(cat)"
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')"

ADDITIONAL_CONTEXT=""
UPDATED_COMMAND=""
DECISION_REASON=""

# ── L1 deny 清單（2026-07-10 topology-audit-pretooluse-deny：CLAUDE.md『絕對禁止』prose → 機械攔截）──
# 第一批保守：只收既往事故項（worktree 誤刪 / 繞過 safe-deploy / 整檔讀 canonical JSON）。
# fail-open：所有 grep 皆在 if 條件內，無 match 不觸發 set -e；deny 走 permissionDecision 與本檔既有 JSON 輸出一致。
# Regression: scripts/tests/test_pretooluse_deny.sh
# 危險 token 只在「指令段起點」才 deny（行首或 shell operator ;&|( 之後），
# 避免誤擋 commit message / echo / grep pattern 裡提到這些字串的 git commit 等命令
# （2026-07-10 首次上線即被自身 commit message 的 "zeabur deploy" 誤擋 → 治本錨定邊界）。
CMD_START='(^|[;&|(])[[:space:]]*'
# force flag 必須落在 `git worktree remove` 自己的指令段內。
# 舊版把 --force/-f 當成全 COMMAND 的獨立條件 → `rm -f x && git worktree remove y`
# 這種無 force 的合法清理被誤擋（2026-07-10 18:20 實際踩到）。
# 段界＝ ; & | ；換行不必列入 — grep 逐行比對，match 本來就跨不過換行。
SEG_TAIL='[^;&|]*'
# flag 比對不可只認死 `-f` / `--force`：git parse-options 接受長選項的不歧義縮寫
# （`--for` / `--forc`）與 short flag 聚合（`-ff`，即文件建議用來移 locked worktree
# 的 `-f -f`）。2026-07-10 實測三者 git 全收，而舊 regex 全放行 — 擋得住老實人，
# 擋不住卡住的 agent。`worktree remove` 的唯一長選項是 --force，唯一 short flag 是
# -f，故「`--f` 開頭」或「短 flag 群含 f」即可安全判定為 force。
FORCE_FLAG='(--f[[:alpha:]]*|-[[:alpha:]]*f[[:alpha:]]*)'
DENY_REASON=""
if printf '%s' "$COMMAND" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+remove${SEG_TAIL}[[:space:]]${FORCE_FLAG}([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止 git worktree remove --force（CLAUDE.md『絕對禁止』；K1032/K1618 誤刪未合併實驗事故）。改用 bash scripts/merge_worktree.sh 正常合併；worktree 從 stale base 分出時用 git checkout <branch> -- experiments/kXXXX/ path-scoped 抽取。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}(npx[[:space:]]+)?zeabur[[:space:]]+deploy([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止直呼 zeabur deploy（frontend-and-deploy.md）。部署一律走 frontend-v2-fix/scripts/deploy-zeabur-safe.sh（鎖正確 service ID + 安全檢查）。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}(cat|less|more)[[:space:]].*(storage/reports/feed\.json|storage/memory/knowledge\.json)([[:space:]]|\$|[^A-Za-z0-9_./])"; then
  DENY_REASON="🚫 禁止整檔讀取 feed.json / knowledge.json（CLAUDE.md Token 紀律）。改用 grep / jq / 單篇 storage/reports/<id>.json；jq、grep、head 皆不受此攔截。"
fi
if [[ -n "$DENY_REASON" ]]; then
  printf '%s' "$INPUT" | jq --arg reason "$DENY_REASON" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
  exit 0
fi

if printf '%s' "$COMMAND" | grep -qE 'python[^[:space:]]*[[:space:]].*(experiments/|scripts/k)'; then
  ADDITIONAL_CONTEXT="⚠️ 實驗代碼執行前檢查：
1) signal.shift(1) 確認了嗎？（lag 必須在代碼裡）
2) Codex 審過這份代碼了嗎？（寫完先審再跑）
3) baseline 用同樣 lag 嗎？
4) 結果好得不像真的 = 90% 有 bug
如果以上任何一項沒做，先停下來做完再跑。"
fi

if printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]])(uv run pytest|pytest|python -m pytest|npm test|pnpm test|yarn test|go test)([[:space:]]|$)'; then
  ESCAPED_COMMAND="$(printf '%q' "$COMMAND")"
  UPDATED_COMMAND="/bin/bash \"$ROOT/.claude/hooks/run-compact-bash.sh\" test $ESCAPED_COMMAND"
  DECISION_REASON="Compact verbose test runner output to save context"
fi

if [[ -z "$UPDATED_COMMAND" ]] && printf '%s' "$COMMAND" | grep -qE '^git[[:space:]]+status([[:space:]]|$)' && ! printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]])(--porcelain|-z)([[:space:]]|$)'; then
  ESCAPED_COMMAND="$(printf '%q' "$COMMAND")"
  UPDATED_COMMAND="/bin/bash \"$ROOT/.claude/hooks/run-compact-bash.sh\" git_status $ESCAPED_COMMAND"
  DECISION_REASON="Compact noisy git status output to reduce dirty-worktree context tax"
fi

if [[ -z "$UPDATED_COMMAND" ]] && printf '%s' "$COMMAND" | grep -qE '^tail([[:space:]]|$)' && printf '%s' "$COMMAND" | grep -qE '(storage/logs/|\.log([[:space:]]|$))' && ! printf '%s' "$COMMAND" | grep -qE '(^|[[:space:]])-f([[:space:]]|$)|(^|[[:space:]])-F([[:space:]]|$)'; then
  ESCAPED_COMMAND="$(printf '%q' "$COMMAND")"
  UPDATED_COMMAND="/bin/bash \"$ROOT/.claude/hooks/run-compact-bash.sh\" tail_log $ESCAPED_COMMAND"
  DECISION_REASON="Compact large log tail output to reduce context noise"
fi

if [[ -z "$ADDITIONAL_CONTEXT" && -z "$UPDATED_COMMAND" ]]; then
  echo '{}'
  exit 0
fi

printf '%s' "$INPUT" | jq \
  --arg updated_command "$UPDATED_COMMAND" \
  --arg additional_context "$ADDITIONAL_CONTEXT" \
  --arg decision_reason "$DECISION_REASON" \
  '
  .tool_input as $tool_input
  | {hookSpecificOutput: {hookEventName: "PreToolUse"}}
  | if $updated_command != "" then
      .hookSpecificOutput.permissionDecision = "allow"
      | .hookSpecificOutput.permissionDecisionReason = $decision_reason
      | .hookSpecificOutput.updatedInput = ($tool_input + {command: $updated_command})
    else
      .
    end
  | if $additional_context != "" then
      .hookSpecificOutput.additionalContext = $additional_context
    else
      .
    end
  '
