#!/bin/bash

set -euo pipefail

ROOT="${VOLPRED_HOOK_ROOT:-/Users/yhlai0911/Desktop/volpred-research}"
INPUT="$(cat)"
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')"

ADDITIONAL_CONTEXT=""
UPDATED_COMMAND=""
DECISION_REASON=""

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
