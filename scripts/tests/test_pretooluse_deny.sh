#!/bin/bash
# Regression: .claude/hooks/pretooluse-bash-optimizer.sh deny 清單
# （2026-07-10 topology-audit-pretooluse-deny：CLAUDE.md『絕對禁止』prose → 機械攔截）
#
# Exit-code 紀律（.claude/rules/hooks-exit-code.md）：不依賴 pipeline $?，
# 逐案 parse hook 自己的 JSON 輸出（.hookSpecificOutput.permissionDecision）決定 pass/fail，
# 最後以顯式 FAIL 計數決定整體退出碼。
set -uo pipefail

HOOK="/Users/yhlai0911/volpred-research/.claude/hooks/pretooluse-bash-optimizer.sh"
PASS=0
FAIL=0

run() {  # $1=command string → hook stdout
  printf '{"tool_input":{"command":%s}}' "$(printf '%s' "$1" | jq -Rs .)" | bash "$HOOK"
}

decision() {  # $1=command → permissionDecision 或 "none"
  run "$1" | jq -r '.hookSpecificOutput.permissionDecision // "none"'
}

assert_deny() {  # $1=label $2=command
  local dec; dec="$(decision "$2")"
  if [[ "$dec" == "deny" ]]; then PASS=$((PASS + 1)); echo "PASS deny : $1";
  else FAIL=$((FAIL + 1)); echo "FAIL deny (got $dec): $1"; fi
}

assert_allow() {  # $1=label $2=command
  local dec; dec="$(decision "$2")"
  if [[ "$dec" != "deny" ]]; then PASS=$((PASS + 1)); echo "PASS allow: $1";
  else FAIL=$((FAIL + 1)); echo "FAIL allow (got deny): $1"; fi
}

# ── 應 deny（第一批既往事故項）──
assert_deny "worktree remove --force"      "git worktree remove --force .claude/worktrees/foo"
assert_deny "worktree remove -f"           "git worktree remove -f .claude/worktrees/foo"
assert_deny "npx zeabur deploy"            "npx zeabur deploy"
assert_deny "zeabur deploy direct"         "zeabur deploy --project abc"
# 2026-07-10 class sweep：舊 pattern 只認 `zeabur` / `npx zeabur`，以下 7 種全放行。
assert_deny "npx pinned version"           "npx zeabur@latest deploy"
assert_deny "npx --yes"                    "npx --yes zeabur deploy"
assert_deny "npx -y"                       "npx -y zeabur deploy"
assert_deny "bunx"                         "bunx zeabur deploy"
assert_deny "pnpm dlx"                     "pnpm dlx zeabur deploy"
assert_deny "yarn dlx"                     "yarn dlx zeabur deploy"
assert_deny "node_modules bin path"        "./node_modules/.bin/zeabur deploy"
assert_deny "cat feed.json"                "cat storage/reports/feed.json"
assert_deny "cat knowledge.json"           "cat storage/memory/knowledge.json"
assert_deny "less feed.json"               "less storage/reports/feed.json"
assert_deny "cat feed.json piped to jq"    "cat storage/reports/feed.json | jq '.items'"
assert_deny "cat after pipe"               "echo x | cat storage/memory/knowledge.json"
# 2026-07-10 class sweep：cat 的等價整檔 dumper，舊 pattern 只認 cat/less/more。
assert_deny "bat feed.json"                "bat storage/reports/feed.json"
assert_deny "nl knowledge.json"            "nl storage/memory/knowledge.json"
assert_deny "view feed.json"               "view storage/reports/feed.json"
assert_deny "tac knowledge.json"           "tac storage/memory/knowledge.json"
assert_deny "od feed.json"                 "od storage/reports/feed.json"
assert_deny "strings knowledge.json"       "strings storage/memory/knowledge.json"
assert_deny "zeabur deploy after &&"       "cd frontend-v2-fix && npx zeabur deploy"
assert_deny "worktree remove after ;"      "cd /tmp ; git worktree remove --force foo"
assert_deny "force flag after path"        "git worktree remove foo --force"
# 2026-07-10：git parse-options 收長選項不歧義縮寫與 short flag 聚合，實測 -ff/--for/--forc
# 全被 git 接受而舊 regex 全放行。-ff 正是文件建議用來移除 locked worktree 的寫法。
assert_deny "aggregated -ff"               "git worktree remove -ff foo"
assert_deny "abbrev --for"                 "git worktree remove --for foo"
assert_deny "abbrev --forc"                "git worktree remove --forc foo"
assert_deny "short cluster -vf"            "git worktree remove -vf foo"
assert_deny "aggregated -ff after path"    "git worktree remove foo -ff"
# 2026-07-10：`git -C <dir>` / `--git-dir=` 前綴繞過 worktree deny（規則假設 git 後直接接
# worktree）。我修 PHASE-Z 時親手觸發 `git -C <repo> worktree remove <path> --force`，
# 只被 git 自己的「contains modified files」擋下。amend 規則早已處理 `-C`，worktree 漏了。
assert_deny "worktree -C prefix + force"   "git -C /repo worktree remove foo --force"
assert_deny "worktree -C prefix + path+force" "git -C /repo worktree remove /tmp/x --force"
assert_deny "worktree --git-dir prefix -f" "git --git-dir=/r/.git worktree remove foo -f"
assert_deny "worktree -C + -ff after &&"   "cd /tmp && git -C /r worktree remove x -ff"
# false-positive 防護：-C 前綴但無 force 仍須放行
assert_allow "worktree -C prefix no force" "git -C /repo worktree remove .claude/worktrees/foo"
assert_allow "worktree -C prefix prune"    "git -C /repo worktree prune"

# ── false-positive 防護：命令引數 / commit message / echo 裡「提到」危險字串不可誤擋 ──
assert_allow "commit msg mentions zeabur"  "git commit -m 'ban zeabur deploy direct call'"
assert_allow "commit msg mentions worktree" "git commit -m 'no more git worktree remove --force'"
assert_allow "echo mentions cat feed.json" "echo 'do not cat storage/reports/feed.json'"
assert_allow "grep for zeabur deploy str"  "grep 'zeabur deploy' docs/notes.md"

# ── 應 allow（sanctioned 用法 / 非事故項，不可誤擋）──
assert_allow "jq feed.json"                "jq '.items[0]' storage/reports/feed.json"
assert_allow "grep feed.json"              "grep NVDA storage/reports/feed.json"
assert_allow "head knowledge.json"         "head -c 500 storage/memory/knowledge.json"
assert_allow "deploy-zeabur-safe.sh"       "bash frontend-v2-fix/scripts/deploy-zeabur-safe.sh"
# class sweep 的反向防護：擴大 pattern 後不可誤擋非 deploy 的 zeabur 子命令與非 dumper
assert_allow "zeabur list (not deploy)"    "npx zeabur list"
assert_allow "zeabur@latest list"          "npx zeabur@latest list"
assert_allow "batch cmd starting with bat" "batch_render storage/reports/feed.json"
assert_allow "cat unrelated report"        "bat storage/reports/mile_abc123.json"
assert_allow "worktree remove (no force)"  "git worktree remove .claude/worktrees/foo"
# 2026-07-10 18:20：清理死 worktree 時被誤擋 — -f 屬於前一段的 rm，不屬於 worktree remove
assert_allow "rm -f then worktree remove"  "rm -f /tmp/junk && git worktree remove .claude/worktrees/foo"
assert_allow "rm -f on next line"          $'rm -f /tmp/junk\ngit worktree remove .claude/worktrees/foo'
assert_allow "worktree remove then rm -f"  "git worktree remove .claude/worktrees/foo && rm -f /tmp/junk"
# 過度攔截防護：路徑內含 -f 子字串（無前導空白）不是 flag
assert_allow "path contains -f substring"  "git worktree remove .claude/worktrees/wt-fix"
assert_allow "path named frontend-fix"     "git worktree remove .claude/worktrees/frontend-fix"
assert_allow "plain echo"                  "echo hello"
assert_allow "pytest advisory rewrite"     "uv run pytest tests/"
assert_allow "cat unrelated file"          "cat storage/reports/mile_abc123.json"

# ── git commit --amend on 共用 main checkout（2026-07-10 hourly-23 事故）──
# 這條 deny 依賴「目標 repo 的 toplevel/branch」，不能靠真實 repo 當下狀態（會隨分支漂移）。
# 起一個一次性 repo 當 ROOT，worktree 當「agent 自己的 checkout」，兩者對照。
AMEND_TMP="$(mktemp -d)"
trap 'rm -rf "$AMEND_TMP"' EXIT
git init -q -b main "$AMEND_TMP/shared" 2>/dev/null
git -C "$AMEND_TMP/shared" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
git -C "$AMEND_TMP/shared" worktree add -q -b agent-branch "$AMEND_TMP/wt" 2>/dev/null
SHARED="$AMEND_TMP/shared"
WT="$AMEND_TMP/wt"

run_cwd() {  # $1=cwd $2=command → hook stdout（ROOT 指向一次性 shared repo）
  printf '{"cwd":%s,"tool_input":{"command":%s}}' \
    "$(printf '%s' "$1" | jq -Rs .)" "$(printf '%s' "$2" | jq -Rs .)" \
    | VOLPRED_HOOK_ROOT="$SHARED" bash "$HOOK"
}
decision_cwd() { run_cwd "$1" "$2" | jq -r '.hookSpecificOutput.permissionDecision // "none"'; }

assert_deny_cwd() {  # $1=label $2=cwd $3=command
  local dec; dec="$(decision_cwd "$2" "$3")"
  if [[ "$dec" == "deny" ]]; then PASS=$((PASS + 1)); echo "PASS deny : $1";
  else FAIL=$((FAIL + 1)); echo "FAIL deny (got $dec): $1"; fi
}
assert_allow_cwd() {  # $1=label $2=cwd $3=command
  local dec; dec="$(decision_cwd "$2" "$3")"
  if [[ "$dec" != "deny" ]]; then PASS=$((PASS + 1)); echo "PASS allow: $1";
  else FAIL=$((FAIL + 1)); echo "FAIL allow (got deny): $1"; fi
}

assert_deny_cwd  "amend on shared main"        "$SHARED" "git commit --amend -m x"
assert_deny_cwd  "amend abbrev --amen"         "$SHARED" "git commit --amen -m x"
assert_deny_cwd  "amend abbrev --am"           "$SHARED" "git commit --am -m x"
assert_deny_cwd  "amend after &&"              "$SHARED" "git add -A && git commit --amend --no-edit"
# 從 worktree 用 `git -C <main>` 打回共用 checkout —— cwd 看起來安全，目標不安全
assert_deny_cwd  "git -C shared from worktree" "$WT"     "git -C $SHARED commit --amend --no-edit"

# agent 在自己的 worktree 分支上 amend：單一 owner，無覆蓋他人之虞
assert_allow_cwd "amend in own worktree"       "$WT"     "git commit --amend --no-edit"
# 主 checkout 但不在 main 分支
git -C "$SHARED" checkout -q -b side
assert_allow_cwd "amend on shared side-branch" "$SHARED" "git commit --amend --no-edit"
git -C "$SHARED" checkout -q main
# false positive 防護：引號內提到 --amend、以及 `git commit -C <commit>`（沿用 message，非 amend）
assert_allow_cwd "commit msg mentions amend"   "$SHARED" "git commit -m 'ban --amend on shared main'"
assert_allow_cwd "commit -C reuse message"     "$SHARED" "git commit -C HEAD~1"
assert_allow_cwd "plain commit on shared main" "$SHARED" "git commit -m normal"

# 2026-07-11 strike 3：git commit -m 內嵌非 ASCII → 非 UTF-8 commit message，push 後不可回復
assert_deny  "commit -m 中文"              "git commit -m '修正波動率計算'"
assert_deny  "commit -m 中文（雙引號）"    "git commit -m \"修正波動率計算\""
assert_deny  "commit --message 中文"       "git commit --message '修正'"
assert_deny  "commit --message=中文"       "git commit --message='修正'"
assert_deny  "commit -m attached 中文"     "git commit -m修正"
assert_deny  "commit -am 中文"             "git commit -am '修正'"
assert_deny  "commit -qm attached 中文"    "git commit -qm修正"
assert_deny  "commit -im attached 中文"    "git commit -im修正"
assert_deny  "commit -om 中文"             "git commit -om '中文訊息'"
assert_deny  "commit -zm attached 中文"    "git commit -zm中文訊息"
assert_deny  "commit unquoted hash 中文"   "git commit -m fix#中文"
assert_deny  "multiple -m one 中文"        "git commit -m 'fix: ascii subject' -m '中文 body'"
assert_deny  "commit -m emoji"             "git commit -m 'fix: 🚫 ban this'"
assert_deny  "git -C commit -m 中文"       "git -C /tmp/repo commit -m '中文訊息'"
assert_deny  "git -c commit -m 中文"       "git -c user.name=test commit -m '中文訊息'"
assert_deny  "git --no-pager commit 中文"  "git --no-pager commit --m='中文訊息'"
assert_deny  "absolute git commit 中文"    "/usr/bin/git commit -m '中文訊息'"
assert_deny  "env git commit 中文"         "env LC_ALL=C git commit -m '中文訊息'"
assert_deny  "command git commit 中文"     "command git commit -m '中文訊息'"
assert_deny  "assignment git commit 中文"  "LC_ALL=C git commit -m '中文訊息'"
assert_deny  "if git commit 中文"          "if git commit -m '中文訊息'; then :; fi"
assert_deny  "then git commit 中文"        "if true; then git commit -m '中文訊息'; fi"
assert_deny  "brace git commit 中文"       "{ git commit -m '中文訊息'; }"
assert_deny  "negated git commit 中文"     "! git commit -m '中文訊息'"
assert_deny  "time git commit 中文"        "time -p git commit -m '中文訊息'"
assert_deny  "exec git commit 中文"        "exec git commit -m '中文訊息'"
assert_deny  "prefix redirect commit 中文" ">/tmp/commit.log git commit -m '中文訊息'"
assert_deny  "fd redirect commit 中文"     "2>/tmp/commit.log git commit -m '中文訊息'"
assert_deny  "env unset commit 中文"       "env -u LC_ALL git commit -m '中文訊息'"
assert_deny  "else git commit 中文"        "if false; then :; else git commit -m '中文訊息'; fi"
assert_deny  "append assignment 中文"      "PATH+=:/tmp git commit -m '中文訊息'"
assert_deny  "quoted git executable 中文"  "'git' commit -m '中文訊息'"
assert_deny  "continued git head 中文"     $'git \\\n  commit -m \'中文訊息\''
assert_deny  "second commit has 中文"      "git commit -m 'fix: ascii' && git commit -m '中文訊息'"
assert_deny  "inline trailer 中文"         "git commit -m 'fix: ascii' --trailer 'Reviewed-by: 王小明'"
assert_deny  "abbrev trailer 中文"         "git commit -m 'fix: ascii' --tr='Reviewed-by: 王小明'"
assert_allow "dynamic -m deferred to Git hook" "git commit -m \"\$(printf '中文')\""
assert_deny  "line-continuation -m 中文"   $'git commit \\\n  -m \'中文訊息\''
assert_deny  "multiline quoted 中文"       $'git commit -m \'第一行\n第二行\''
assert_allow "malformed quote left to shell" "git commit -m '中文"
assert_allow "expanded variable deferred"  'MSG=中文; git commit -m "$MSG"'
assert_allow "ANSI-C escape deferred"      "git commit -m \$'\\u4e2d\\u6587'"
assert_allow "commit -F 中文檔（合法解）"  "git commit -F /tmp/中文訊息.txt"
assert_allow "commit -m 純 ASCII"          "git commit -m 'fix: ban non-ascii -m'"
assert_allow "ASCII multiline -m"          $'git commit -m \'ascii subject\nascii body\''
assert_allow "single-quoted dollar literal" "git commit -m '\$MSG'"
assert_allow "command -v does not execute" "command -v git commit -m '中文訊息'"
assert_allow "command -V does not execute" "command -V git commit -m '中文訊息'"
assert_allow "非 commit 指令含中文"        "echo '中文' > /tmp/x"

# `_commit_message_has_non_ascii` 只能看 message argv，不能看整條 Bash command。
# 2026-07-12 hourly-01 的實際 false positive：同一 tool call 先用 heredoc 寫中文，
# 後面再以純 ASCII -m commit；舊版因整條 COMMAND 含中文而誤擋。
assert_allow "中文 before ASCII commit"    "printf '%s' '中文' > /tmp/note && git commit -m 'fix: ascii only'"
assert_allow "中文 after ASCII commit"     "git commit -m 'fix: ascii only' && printf '%s' '中文'"
assert_allow "python -m 中文 + ASCII commit" "python -m 中文 && git commit -m 'fix: ascii only'"
assert_allow "Unicode author + ASCII commit" "git commit --author='王小明 <x@example.com>' -m 'fix: ascii only'"
assert_allow "Unicode path + ASCII commit" "git -C /tmp/中文 commit -m 'fix: ascii only'"
assert_allow "Unicode pathspec + ASCII commit" "git commit -m 'fix: ascii only' -- 中文檔.txt"
assert_allow "two ASCII -m + unrelated 中文" "printf '%s' '中文' && git commit -m 'fix: subject' -m 'ascii body'"
assert_allow "Unicode comment + ASCII commit" "git commit -m 'fix: ascii only' # 中文註解"
assert_allow "Unicode -F then ASCII -m"    "git commit -F /tmp/中文訊息.txt && git commit -m 'fix: ascii only'"
assert_allow "echo fake 中文 commit"       "echo \"git commit -m '中文'\" && git commit -m 'fix: ascii only'"
assert_allow "unquoted echo fake 中文 commit" "echo git commit -m 中文 && git commit -m 'fix: ascii only'"
assert_allow "line-continuation ASCII + 中文 elsewhere" $'printf 中文 && git commit \\\n  -m \'fix: ascii only\''
assert_allow "arithmetic shift + ASCII commit" "(( x = 1 << 2 )); printf 中文; git commit -m 'fix: ascii only'"
assert_allow "multiline ASCII message"     $'git commit -m \'first line\nsecond line\''
assert_allow "command -v is lookup only"  "command -v git commit -m 中文"
assert_allow "parameter text with shift token" "x=\${v:-a<<b}; git commit -m 'fix: ascii only'"
assert_allow "array arithmetic shift"      "arr[1<<2]=x; git commit -m 'fix: ascii only'"

HEREDOC_CJK_ASCII_COMMIT=$'python3 - <<\'PY\'\nprint("中文內容")\nPY\ngit commit -m "fix: ascii only"'
assert_allow "中文 heredoc + ASCII commit" "$HEREDOC_CJK_ASCII_COMMIT"

# heredoc body 裡的 `git commit -m 中文` 是被寫入檔案的資料，不是本次 shell 會執行的命令。
# parser 必須跳過 body，不能只用 shlex 把每一行都當成 simple command。
HEREDOC_FAKE_COMMIT=$'cat > /tmp/example.sh <<\'SCRIPT\'\ngit commit -m \'中文範例\'\nSCRIPT\ngit commit -m \'fix: ascii only\''
assert_allow "heredoc fake 中文 commit + real ASCII commit" "$HEREDOC_FAKE_COMMIT"

HEREDOC_STRIP_TABS=$'cat <<-\'EOF\' > /tmp/note\n\t中文內容\n\tEOF\ngit commit -m \'fix: ascii only\''
assert_allow "tab-stripped 中文 heredoc + ASCII commit" "$HEREDOC_STRIP_TABS"

HEREDOC_FIFO=$'cat <<\'ONE\' <<\'TWO\' > /tmp/note\n第一段中文\nONE\n第二段中文\nTWO\ngit commit -m \'fix: ascii only\''
assert_allow "two queued 中文 heredocs + ASCII commit" "$HEREDOC_FIFO"

HEREDOC_HEADER_COMMIT=$'cat <<\'EOF\' > /tmp/note && git commit -m \'fix: ascii only\'\n中文內容\nEOF'
assert_allow "same header heredoc + ASCII commit" "$HEREDOC_HEADER_COMMIT"

HEREDOC_CONTINUED_HEADER=$'cat <<\'EOF\' > /tmp/note \\\n  && git commit -m \'中文訊息\'\nheredoc body\nEOF'
assert_deny "continued heredoc header + 中文 commit" "$HEREDOC_CONTINUED_HEADER"

# ── 2026-07-12 3-STRIKE class sweep：fire 內無界 agentic 子程序 ──────────────
# 7/11 只擋了 class 的一個成員（codex exec）；隔天同 root cause 換執行檔（claude -p）
# 又炸三次 hang_killed，三次 duration 全是 3001.3s（＝supervisor 的 3000s hard cap）。
# 這批 assert 鎖住「class 不是成員」：新成員（agy -p）與繞過寫法（絕對路徑）一併蓋住。
#
# 這條 deny 是 actor-scoped（只在 fire 內生效），所以 assert 必須顯式指定 VOLPRED_ACTOR —
# 不可讓它繼承跑測試那個人的環境（否則 hourly fire 跑 CI 與人手跑 CI 會得到不同結果）。
decision_actor() {  # $1=actor $2=command → permissionDecision 或 "none"
  printf '{"tool_input":{"command":%s}}' "$(printf '%s' "$2" | jq -Rs .)" \
    | VOLPRED_ACTOR="$1" bash "$HOOK" | jq -r '.hookSpecificOutput.permissionDecision // "none"'
}
assert_deny_actor() {  # $1=label $2=actor $3=command
  local dec; dec="$(decision_actor "$2" "$3")"
  if [[ "$dec" == "deny" ]]; then PASS=$((PASS + 1)); echo "PASS deny : $1";
  else FAIL=$((FAIL + 1)); echo "FAIL deny (got $dec): $1"; fi
}
assert_allow_actor() {  # $1=label $2=actor $3=command
  local dec; dec="$(decision_actor "$2" "$3")"
  if [[ "$dec" != "deny" ]]; then PASS=$((PASS + 1)); echo "PASS allow: $1";
  else FAIL=$((FAIL + 1)); echo "FAIL allow (got deny): $1"; fi
}

FIRE="dispatch-worker:volpred-hourly-dispatch:0135"

# fire 內 = 有 3000s hard cap 的容器 → 無界 agentic 子程序一律擋
assert_deny_actor  "fire: claude -p"              "$FIRE" "claude -p --effort xhigh 'brief'"
assert_deny_actor  "fire: claude --print"         "$FIRE" "claude --print 'brief'"
assert_deny_actor  "fire: claude -p 絕對路徑"      "$FIRE" "/usr/local/bin/claude -p 'x'"
assert_deny_actor  "fire: agy -p（class 新成員）"  "$FIRE" "agy -p '審查這段'"
assert_deny_actor  "fire: codex exec"             "$FIRE" "codex exec 'review'"
assert_deny_actor  "fire: codex exec 絕對路徑"     "$FIRE" "/opt/homebrew/bin/codex exec 'x'"
assert_deny_actor  "fire: && 串接 claude -p"      "$FIRE" "cd /tmp && claude -p 'x'"

# fire 外 = 沒有 cap（互動有人盯著 / compute worker 是 detached）→ 合法，不可誤擋
assert_allow_actor "互動 session: claude -p"      "interactive"     "claude -p 'x'"
assert_allow_actor "queue runner 的 agent"        "agent-job:k1684" "claude -p 'x'"
# 合法出路本身不可被自己的 deny 擋住（否則 agent 無路可走 → 又回去硬 spawn）
assert_allow_actor "fire: enqueue-agent（正解）"  "$FIRE" \
  "uv run python scripts/compute_queue.py enqueue-agent --brief-file /tmp/b.md --effort xhigh"
# false positive 防護：提到字串 ≠ 執行它
assert_allow_actor "fire: grep 提到 claude -p"    "$FIRE" "grep -rn 'claude -p' docs/"

echo "---"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
