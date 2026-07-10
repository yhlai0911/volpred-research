#!/bin/bash

set -euo pipefail

ROOT="${VOLPRED_HOOK_ROOT:-/Users/yhlai0911/volpred-research}"
INPUT="$(cat)"
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""')"
HOOK_CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""')"
[[ -z "$HOOK_CWD" ]] && HOOK_CWD="$PWD"

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

# 2026-07-10 class sweep：上面那個「pattern 只認人類慣常拼法」的 bug 不是 worktree 規則
# 獨有 — 三條 deny 全中。以下兩條同步補上 agent 卡住時真的會伸手拿的等價寫法。
#
# zeabur：npx 慣用 `pkg@version` 與 `-y/--yes`；同類 runner 有 bunx / pnpm dlx / yarn dlx；
# 也可能直呼 ./node_modules/.bin/zeabur。實測舊 pattern 對這 7 種全部放行。
PKG_RUNNER='((npx|bunx)([[:space:]]+(-y|--yes))?[[:space:]]+|(pnpm|yarn)[[:space:]]+dlx[[:space:]]+)?'
ZEABUR_BIN='([^[:space:];&|()]*/)?zeabur(@[^[:space:]]+)?'
# 整檔讀：cat 的等價 dumper 遠不只 less/more。列舉「會吐出整份檔案」的讀取器；
# grep / jq / head 是 CLAUDE.md 明文放行的取用方式，不列入。
FULL_READERS='(cat|bat|less|more|most|nl|od|tac|strings|view)'

# 2026-07-10 hourly-23：主 checkout 是共用的 —— dispatch worker、codex-vscode、rescue agent
# 會同時在 /Users/yhlai0911/volpred-research 上 commit。`git commit --amend` 假設「HEAD 是我剛做的」，
# 這個假設在共用 checkout 裡不成立：當班 amend 打在 1c7275bae 上，把別的 agent 的 commit message
# 換成自己的，並把它尚未提交的 5 個在途檔案一起吞進來。amend 沒有「只有我碰過 HEAD」的檢查，
# 而 reflog 顯示兩個 actor 的 commit 是交錯的。worktree 內 amend 自己的分支無此風險（單一 owner），
# 故只擋「目標 repo == 共用 main checkout 且在 main 分支」這一格。
# 補救不是 amend 而是「再疊一個 commit」——歷史多一行，勝過覆蓋別人的一行。
# git parse-options 收長選項不歧義縮寫：`--amend` 之外 `--am/--ame/--amen` git 全收（commit 沒有
# 其他 `--am` 開頭選項）。引號內字串先剝掉，否則 `git commit -m 'fix --amend hazard'` 會被誤擋。
AMEND_FLAG='--am[[:alpha:]]*'
COMMAND_NOQ="$(printf '%s' "$COMMAND" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# `git -C <dir> commit --amend` 從 worktree 也能打到 main checkout —— 目標目錄以 `-C` 為準
# （必須落在子命令 `commit` 之前；`git commit -C <commit>` 的 -C 是「沿用某 commit 的 message」，
# 語意完全不同，不可誤取）。無 `-C` 時目標即本次 Bash 的 cwd。
_amend_target_is_shared_main() {
  local target toplevel branch root_real
  target="$(printf '%s' "$COMMAND_NOQ" | sed -nE 's|.*git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+commit.*|\1|p' | head -1)"
  [[ -z "$target" ]] && target="$HOOK_CWD"
  toplevel="$(git -C "$target" rev-parse --show-toplevel 2>/dev/null)" || return 1
  branch="$(git -C "$target" rev-parse --abbrev-ref HEAD 2>/dev/null)" || return 1
  root_real="$(cd "$ROOT" 2>/dev/null && pwd -P)" || return 1
  toplevel="$(cd "$toplevel" 2>/dev/null && pwd -P)" || return 1
  [[ "$toplevel" == "$root_real" && "$branch" == "main" ]]
}

DENY_REASON=""
if printf '%s' "$COMMAND" | grep -qE "${CMD_START}git[[:space:]]+worktree[[:space:]]+remove${SEG_TAIL}[[:space:]]${FORCE_FLAG}([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止 git worktree remove --force（CLAUDE.md『絕對禁止』；K1032/K1618 誤刪未合併實驗事故）。改用 bash scripts/merge_worktree.sh 正常合併；worktree 從 stale base 分出時用 git checkout <branch> -- experiments/kXXXX/ path-scoped 抽取。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}${PKG_RUNNER}${ZEABUR_BIN}[[:space:]]+deploy([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止直呼 zeabur deploy（frontend-and-deploy.md）。部署一律走 frontend-v2-fix/scripts/deploy-zeabur-safe.sh（鎖正確 service ID + 安全檢查）。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}${FULL_READERS}[[:space:]].*(storage/reports/feed\.json|storage/memory/knowledge\.json)([[:space:]]|\$|[^A-Za-z0-9_./])"; then
  DENY_REASON="🚫 禁止整檔讀取 feed.json / knowledge.json（CLAUDE.md Token 紀律）。改用 grep / jq / 單篇 storage/reports/<id>.json；jq、grep、head 皆不受此攔截。"
elif printf '%s' "$COMMAND_NOQ" | grep -qE "${CMD_START}git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?commit${SEG_TAIL}[[:space:]]${AMEND_FLAG}([[:space:]]|\$)" \
     && _amend_target_is_shared_main; then
  DENY_REASON="🚫 禁止在共用 main checkout 的 main 分支上 git commit --amend（2026-07-10 hourly-23 事故：amend 打在另一個 agent 剛做的 commit 上，覆蓋其 message 並吞掉它 5 個未提交的在途檔案）。主 checkout 同時有 dispatch worker / codex-vscode / rescue agent 在 commit，HEAD 不保證是你做的。改法：要修訊息或補內容，就再疊一個 commit（歷史多一行，勝過覆蓋別人的一行）。在自己的 worktree 分支上 amend 不受此攔截。"
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
