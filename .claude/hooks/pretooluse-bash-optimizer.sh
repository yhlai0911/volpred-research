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
# git 全域選項前綴：`git -C <dir>` / `git --git-dir=<p>` / `git -c k=v` 可夾在
# `git` 與子命令之間。2026-07-10：`git -C <dir> worktree remove <path> --force`
# 整串繞過 worktree deny（規則假設 `git` 後面直接接 `worktree`）——我在修 PHASE-Z
# 時親手觸發，remove 未合併 worktree 前一刻才被 git 自己的「contains modified files」
# 擋下。amend 規則早已用 `(-C …)?` 處理同一件事，worktree 規則漏了：同 bug class，
# 一條學到、另一條沒有。`[^;&|]*?` 惰性吃掉任意數量的全域選項，不跨指令段界。
GIT_GLOBAL_OPTS='([[:space:]]+-[^[:space:];&|]+([[:space:]]+[^[:space:];&|-][^[:space:];&|]*)?)*'
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

# 2026-07-11 hourly-22（strike 3）：`git commit -m` 內嵌非 ASCII 會產出非 UTF-8 的 commit 訊息
# （git 自己會警告 `commit message did not conform to UTF-8`，但那只是 warning，commit 照樣成立）。
# 訊息一旦 push 出去就只能 force push 才改得掉，而 force push 是禁止的 —— 亦即這個錯誤「不可回復」。
# error_log 早在 2026-05 就寫了「中文 commit 一律 Write 檔案 + `git commit -F <file>`」，
# 但 prose 擋不住趕時間的 agent：cea826ad0 中招、2369c7d07 又中招（同一週）。散文 → 機械 gate。
# 判定用「commit 指令段 + `-m`/`--message` + 整行含非 ASCII 字元」；`-F` / `-C` / 純 ASCII 訊息不受影響。
# 這裡刻意比對含引號的原始 COMMAND（不能用 COMMAND_NOQ —— 訊息本體正是被引號包住的那一段）。
MESSAGE_FLAG='(-m|--m[[:alpha:]]*)'
_commit_message_has_non_ascii() {
  printf '%s' "$COMMAND" | LC_ALL=C grep -q '[^[:print:][:space:]]'
}

DENY_REASON=""
if printf '%s' "$COMMAND" | grep -qE "${CMD_START}git${GIT_GLOBAL_OPTS}[[:space:]]+worktree[[:space:]]+remove${SEG_TAIL}[[:space:]]${FORCE_FLAG}([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止 git worktree remove --force（CLAUDE.md『絕對禁止』；K1032/K1618 誤刪未合併實驗事故）。改用 bash scripts/merge_worktree.sh 正常合併；worktree 從 stale base 分出時用 git checkout <branch> -- experiments/kXXXX/ path-scoped 抽取。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}${PKG_RUNNER}${ZEABUR_BIN}[[:space:]]+deploy([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止直呼 zeabur deploy（frontend-and-deploy.md）。部署一律走 frontend-v2-fix/scripts/deploy-zeabur-safe.sh（鎖正確 service ID + 安全檢查）。"
elif printf '%s' "$COMMAND" | grep -qE "${CMD_START}${FULL_READERS}[[:space:]].*(storage/reports/feed\.json|storage/memory/knowledge\.json)([[:space:]]|\$|[^A-Za-z0-9_./])"; then
  DENY_REASON="🚫 禁止整檔讀取 feed.json / knowledge.json（CLAUDE.md Token 紀律）。改用 grep / jq / 單篇 storage/reports/<id>.json；jq、grep、head 皆不受此攔截。"
elif printf '%s' "$COMMAND_NOQ" | grep -qE "${CMD_START}codex[[:space:]]+exec([[:space:]]|\$)"; then
  DENY_REASON="🚫 禁止裸跑 codex exec（2026-07-11 事故：hourly agent 在 session 內直接 codex exec 補渲染 lazypack，卡住 >30min 無輸出，agent 阻塞在無 timeout 的 Bash → 撞 supervisor 3000s hard cap → SIGKILL → hang_killed）。codex exec 是 agentic loop，可以跑很久而且不會自己停；Bash tool 沒有 timeout，macOS 也沒有 coreutils timeout 指令，所以「裸跑」= 把整個 fire 的命運交給一個沒有上界的呼叫。改法二選一：(1) 互動 / review 等你會盯著的短工作 → bash scripts/codex_exec_bounded.sh --timeout 300 <args>（有界，逾時 exit 124）；(2) 重活（渲染、長 review、任何你不會坐著等的）→ uv run python scripts/compute_queue.py enqueue --script <path> --timeout 1800，交給 */15 async worker。Python 內用 subprocess.run(timeout=) 呼叫 codex 不受此攔截（那本來就有界）。"
elif printf '%s' "$COMMAND_NOQ" | grep -qE "${CMD_START}git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?commit${SEG_TAIL}[[:space:]]${AMEND_FLAG}([[:space:]]|\$)" \
     && _amend_target_is_shared_main; then
  DENY_REASON="🚫 禁止在共用 main checkout 的 main 分支上 git commit --amend（2026-07-10 hourly-23 事故：amend 打在另一個 agent 剛做的 commit 上，覆蓋其 message 並吞掉它 5 個未提交的在途檔案）。主 checkout 同時有 dispatch worker / codex-vscode / rescue agent 在 commit，HEAD 不保證是你做的。改法：要修訊息或補內容，就再疊一個 commit（歷史多一行，勝過覆蓋別人的一行）。在自己的 worktree 分支上 amend 不受此攔截。"
elif printf '%s' "$COMMAND_NOQ" | grep -qE "${CMD_START}git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?commit${SEG_TAIL}[[:space:]]${MESSAGE_FLAG}([[:space:]]|=|\$)" \
     && _commit_message_has_non_ascii; then
  DENY_REASON="🚫 禁止用 git commit -m 內嵌非 ASCII（中文 / emoji）訊息（strike 3：cea826ad0、2369c7d07 同週兩次；error_log 2026-05 的散文規則擋不住）。經過 shell 會產出非 UTF-8 的 commit message，git 只給 warning 照樣 commit，push 出去後只有 force push 改得掉 —— 而 force push 是禁止的，等於不可回復。改法：用 Write 工具把訊息寫成 /tmp/msg.txt，再 git commit -F /tmp/msg.txt。純 ASCII 訊息、-F、--amend 走既有規則，皆不受此攔截。"
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
