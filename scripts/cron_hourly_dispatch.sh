#!/bin/bash
# Hourly dispatch trigger via macOS LaunchAgent.
# Schedule: HH:07 every hour (24 slots/day). Reverted from 4-hourly per user
# directive 2026-05-16. Task scoping must fit ~50min cap (smaller units;
# heavy work goes to compute_queue.py for async worker pickup).
#
# Canonical source: scripts/cron_hourly_dispatch.sh + scripts/cron_hourly_dispatch_prompt.md
# TCC copy: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh

REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/volpred-research}"
VOLPRED_HOME_DIR="${VOLPRED_HOME_DIR:-/Users/yhlai0911/.volpred}"
HOURLY_LOG_PATH="${HOURLY_LOG_PATH:-$VOLPRED_HOME_DIR/logs/hourly_dispatch.log}"
# 2026-06-22: REVERTED the explicit-version pin back to the symlink.
# History: 2026-05-30 we pinned to 2.1.156 because 2.1.157 had a launchd
# auth regression (`claude -p` → "unknown error" under launchd). BUT pinning an
# explicit version is structurally fragile: claude auto-update DELETED 2.1.156,
# so the pinned path vanished → every hourly dispatch since failed silently with
# "no such file or directory" (binary not found, sub-second exit, 0 content
# generated all day — caused the 06-22 發文脫班 + missing daily digest).
# Silent binary-not-found is WORSE than the launchd auth regression (which the
# auth-preflight below DETECTS and alerts on). And the regression is gone:
# 2026-06-22 verified `env -i PATH=/usr/bin:/bin CLAUDE_CODE_OAUTH_TOKEN=… \
# <symlink> -p` returns AUTHOK under a clean launchd-like env on current 2.1.181.
# So: use the always-current symlink; the long-lived OAuth token handles auth
# across versions, and run_auth_preflight() gives graceful, alerted degradation
# if a future version ever re-breaks launchd auth. Override with CLAUDE_BIN env.
CLAUDE_BIN="${CLAUDE_BIN:-/Users/yhlai0911/.local/bin/claude}"
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
PROMPT_FILE="${PROMPT_FILE:-$REPO_ROOT/scripts/cron_hourly_dispatch_prompt.md}"
ZSHRC_PATH="${ZSHRC_PATH:-$HOME/.zshrc}"
# 2026-07-02 fix (boss「他根本沒讓我輸入的機會啊」incident): 90s occasionally too
# tight under real concurrent load on this machine — a live manual repro found
# a genuinely-successful ping taking ~54s with load average ~7-8 (multiple
# claude/codex processes running at once, which this platform does by design).
# Bumped to 120s for headroom; 3 attempts + backoff still fits comfortably
# inside the 50min hourly-slot budget.
AUTH_PREFLIGHT_TIMEOUT_SEC="${AUTH_PREFLIGHT_TIMEOUT_SEC:-120}"
AUTH_PREFLIGHT_MODEL="${AUTH_PREFLIGHT_MODEL:-claude-sonnet-5}"
# Backoff before a 3rd preflight attempt — the first 2 attempts fire within
# seconds (launchd-env + zshrc-source), so a transient Claude API blip
# ("An unknown error occurred (Unexpected)") defeats both. ~8% of runs hit
# this and self-recover the next hour; this backoff lets the blip clear within
# the same run instead of skipping a dispatch slot. 2026-05-30 (05:08 incident).
AUTH_PREFLIGHT_BACKOFF_SEC="${AUTH_PREFLIGHT_BACKOFF_SEC:-20}"
AUTH_HOTFIX_CMD="${AUTH_HOTFIX_CMD:-security set-generic-password-partition-list -S apple-tool:,apple:,launchd:,unsigned: -s \"Claude Code-credentials\" -k login.keychain}"
# 2026-07-02 fix (05:07 incident: `source "$ZSHRC_PATH"` hung ~15min with zero
# timeout protection — a stuck `conda shell.zsh hook` child blocked it; killing
# that PID was the only way to unblock the run). `source` is a bash builtin so
# perl's `alarm+exec` pattern can't wrap it in place. Scoped fix: probe the rc
# file via an external, alarm-able `zsh -c` subprocess and only pull PATH back
# (the one plausibly load-bearing side effect — finding `security`/nvm/conda
# binaries for the keychain-fallback path); drop everything else on timeout.
# The CLAUDE_CODE_OAUTH_TOKEN bypass above is the actual load-bearing auth
# fix, so this has always been best-effort, never required for correctness.
ZSHRC_SOURCE_TIMEOUT_SEC="${ZSHRC_SOURCE_TIMEOUT_SEC:-20}"
# 2026-07-02 fix (same incident): two separate `send-alert` calls each hung
# 4-6min with near-zero CPU (file-locking ruled out in alerts.py; suspected but
# unconfirmed DNS-resolution stall inside smtplib.SMTP()'s connect phase, not
# reliably bounded by its own timeout=20 param under load). Every send-alert
# invocation in this script now goes through run_send_alert() below so a hung
# email send can never again burn the rest of the hourly slot.
SEND_ALERT_TIMEOUT_SEC="${SEND_ALERT_TIMEOUT_SEC:-45}"
# 2026-07-02 fix (same incident, live during this very fix): the SAME 06:07
# fire that this fix was meant to verify hit TWO MORE unguarded hangs before
# even reaching the auth-preflight section this patch already covers —
# `git_conflict_guard.py` (~6min, stuck in a getcwd()/open() syscall per
# `sample`) and `hourly_dispatch_pregate.py` (~5min, identical stuck syscall).
# Both are plain `uv run python ...` calls with zero timeout protection —
# the same missing-ceiling pattern as the other three, just not yet
# discovered because they'd never hung before tonight. Ceilings below are
# generous relative to each check's normal (sub-second to low-single-digit
# second) runtime.
GIT_CONFLICT_GUARD_TIMEOUT_SEC="${GIT_CONFLICT_GUARD_TIMEOUT_SEC:-30}"
PREGATE_TIMEOUT_SEC="${PREGATE_TIMEOUT_SEC:-30}"

# Log target lives OUTSIDE Desktop/ — macOS TCC protects ~/Desktop and blocks
# launchd-spawned processes from opening files there (2026-05-21 incident:
# plist StandardOutPath under Desktop → spawn failed EX_CONFIG/78, script body
# never ran). storage/logs/cron/hourly_dispatch.log is a symlink to this.
mkdir -p "$(dirname "$HOURLY_LOG_PATH")"
exec >> "$HOURLY_LOG_PATH" 2>&1
cd "$REPO_ROOT" || exit 1

# Raise file-descriptor SOFT limit. LaunchAgent-spawned processes inherit
# launchd's default (soft 256 / hard unlimited — `launchctl limit maxfiles`)
# and DO NOT source the login profile, so claude -p crashes instantly with
# "low max file descriptors" (2026-05-20: 6/12 hourly runs failed this way).
# Interactive shells get 1048576 from the profile; headless runs must set it.
# Use -Sn (soft only) — hard is unlimited so the soft raise always succeeds.
ulimit -Sn 65536 2>/dev/null || true

# ── git conflict guard (2026-06-28) ──
# Two dispatchers write this branch concurrently (Claude hourly + always-on
# codex_loop), so a 3-way merge can orphan .git/AUTO_MERGE and inject conflict
# markers into feed.json / next_tasks.json / work_log.json. Run the watchdog
# FIRST so every hourly slot starts on a clean, valid tree (it auto-restores the
# canonical HEAD blob + alerts). Fail-open: never blocks dispatch.
# 2026-07-02: perl-alarm ceiling — see GIT_CONFLICT_GUARD_TIMEOUT_SEC comment
# above. A hang here used to block the entire slot before dispatch even began.
/usr/bin/perl -e 'alarm shift; exec @ARGV' "$GIT_CONFLICT_GUARD_TIMEOUT_SEC" \
  "$UV_BIN" run python "$REPO_ROOT/scripts/git_conflict_guard.py" --quiet 2>&1 || \
  echo "[git-conflict-guard] WARN guard exited non-zero or timed out rc=$? (continuing dispatch)"

# Enable job control so background subshells get their own process group;
# `kill -- -PGID` then propagates to all descendants (claude + its forks).
set -m

echo "=== hourly-dispatch $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# ── PERMANENT AUTH FIX (2026-05-29, 3-strike: keychain ACL reset on token refresh) ──
# Root cause (evidence-based, not guessed): Claude CLI OAuth token refresh
# rewrites the macOS keychain item "Claude Code-credentials", which RESETS its
# partition-list ACL → launchd loses access → next fire "Not logged in".
# Confirmed: keychain mdat=2026-05-29 08:07 (refresh) → 09:07 fire failed; the
# 5/27 `security set-generic-password-partition-list` hotfix survived only until
# the next refresh.
# Fix: use a long-lived token (`claude setup-token`, Max subscription) exported
# via CLAUDE_CODE_OAUTH_TOKEN — bypasses keychain entirely, immune to refresh.
# Token file is chmod 600, gitignored. If absent, fall through to keychain
# (+ existing auth-preflight hotfix) so this degrades gracefully.
OAUTH_TOKEN_FILE="${OAUTH_TOKEN_FILE:-$VOLPRED_HOME_DIR/secrets/claude_oauth_token}"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -f "$OAUTH_TOKEN_FILE" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$OAUTH_TOKEN_FILE")"
  export CLAUDE_CODE_OAUTH_TOKEN
  echo "[auth] using long-lived CLAUDE_CODE_OAUTH_TOKEN from $OAUTH_TOKEN_FILE (keychain-independent)"
else
  echo "[auth] no token file at $OAUTH_TOKEN_FILE — falling back to keychain (run 'claude setup-token' for permanent fix)"
fi

# ── Pre-gate (2026-07-01): skip the ~95K claude -p cold-load on pure-stub fires ──
# Cheap pure-Python check (no LLM, 0 token): email backlog / dashboard critical /
# P1-P2 agentable pending / backlog cadence (N h). Fail-open (any error -> PROCEED).
# SHADOW default (PREGATE_SHADOW=1): logs the would-be decision to
# storage/logs/hourly_pregate.jsonl, NEVER skips — validating for ~1 week.
# Flip PREGATE_SHADOW=0 (LaunchAgent env or here) to enable real skipping.
PREGATE_ARGS="--window-hours ${PREGATE_WINDOW_HOURS:-3}"
[ "${PREGATE_SHADOW:-1}" = "1" ] && PREGATE_ARGS="$PREGATE_ARGS --shadow"
# 2026-07-02: perl-alarm ceiling — see PREGATE_TIMEOUT_SEC comment above. A
# timeout here is treated as a fail-open PROCEED (same as any other non-zero
# exit from this check), never a silent skip.
if /usr/bin/perl -e 'alarm shift; exec @ARGV' "$PREGATE_TIMEOUT_SEC" \
  "$UV_BIN" run python "$REPO_ROOT/scripts/hourly_dispatch_pregate.py" $PREGATE_ARGS 2>&1; then
  echo "[pre-gate] SKIP — no email/critical/high-prio work + backlog cadence not due ($(date '+%H:%M'))"
  echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=0, pre-gate skip) ==="
  exit 0
fi
echo "[pre-gate] PROCEED — real work or backlog cadence due"

# Cleanup trap: if launchd / external kill / shell error terminates parent
# mid-flight, ensure claude + watchdog don't orphan. Codex review 2026-05-14
# CRITICAL #2.
cleanup() {
  local exit_status=$?
  if [ -n "${CLAUDE_PID:-}" ] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
    echo "[CLEANUP] parent exiting (status=$exit_status); killing claude PGID $CLAUDE_PID"
    kill -TERM -- "-$CLAUDE_PID" 2>/dev/null || kill -TERM "$CLAUDE_PID" 2>/dev/null
    sleep 2
    kill -KILL -- "-$CLAUDE_PID" 2>/dev/null || kill -KILL "$CLAUDE_PID" 2>/dev/null
  fi
  if [ -n "${WATCHDOG_PID:-}" ] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
    kill -KILL "$WATCHDOG_PID" 2>/dev/null
  fi
}
trap cleanup EXIT TERM INT HUP

# Two-layer hang defense (50min hard cap, 60min interval - 10min buffer):
# Layer 1: perl alarm SIGALRM (verified working across exec on macOS 25.3:
#   `perl -e 'alarm 2; exec sleep 10'` → exit 142). Cheap, no extra process.
# Layer 2: background subshell + parent watchdog SIGTERM→SIGKILL. Belt-and-
#   suspenders if claude binary's node runtime installs its own SIGALRM
#   handler that ignores the signal (Gemini review 2026-05-14 concern).
# Prior hang incidents 2026-05-13 10:07 + 15:07 = strike 2 of three-strike;
# next hang triggers worker-daemon refactor per CLAUDE.md three-strike rule.
HOURLY_CAP_SEC=3000

# Orchestrator model = opus-4-8 (current; 2026-07-01 un-pinned from stale opus-4-7; high-risk
# decision tier for triage / claim / brief 撰寫 / routing). Subagents spawned
# per-task get task-type-specific model via scripts/model_router.py.
#
# Retry-with-backoff + fallback (added 2026-05-25, K1751 alert root cause):
#  - 17:07 / 18:07 fire 都 hit Anthropic API 529 Overloaded → single-shot
#    exit 1 → pool 連 2 hour 沒消化 → CRITICAL alert
#  - Fix: 最多 3 attempts (opus → wait 90s → opus → wait 90s → sonnet fallback)
#    若 attempt < HOURLY_CAP_SEC 還有時間就再試；確認 API 真死才 exit 1
#
CLAUDE_CMD_PATTERN="claude"

# 2026-07-01 fix (3-strike: hourly_dispatch.log:exit1 recurred 82x/8.6d, root
# cause confirmed live): bare "ping" gets loaded with full CLAUDE.md, whose
# autonomous-loop mandate tells the model to investigate ops state and keep
# working after replying — that blows the 90s alarm and SIGALRM-kills the
# probe (exit=142), which this script then misreads as an auth failure and
# escalates to Codex failover / CRITICAL alert even though auth was fine the
# whole time. Fix: make the probe text itself override the mandate — explicit,
# example-cited "not a work session" framing outranks the general instruction.
AUTH_PREFLIGHT_PROMPT='SYSTEM AUTH-PREFLIGHT PROBE (not a real user, not a work session): reply with exactly one word, PONG, and stop there. Do not call any tools, do not read files, do not run an ops loop, do not schedule a wakeup. This message only checks that you can respond at all.'

run_auth_preflight() {
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$AUTH_PREFLIGHT_TIMEOUT_SEC" \
    "$CLAUDE_BIN" -p --dangerously-skip-permissions \
    --model "$AUTH_PREFLIGHT_MODEL" "$AUTH_PREFLIGHT_PROMPT" 2>&1
  return $?
}

# 2026-07-02 fix — see SEND_ALERT_TIMEOUT_SEC comment above. Every
# `send-alert` call in this script must go through this wrapper, never call
# "$UV_BIN" run volpred ops send-alert directly.
run_send_alert() {
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$SEND_ALERT_TIMEOUT_SEC" \
    "$UV_BIN" run volpred ops send-alert "$@"
  local rc=$?
  if [ "$rc" -eq 142 ]; then
    echo "[send-alert] TIMED OUT after ${SEND_ALERT_TIMEOUT_SEC}s (rc=142) — email not sent this round, continuing (never block dispatch on alert delivery)"
  fi
  return "$rc"
}

send_auth_preflight_alert() {
  local first_output=$1
  local retry_output=$2
  local retry3_output=$3
  local auth_body tmp
  # 2026-07-02 fix (boss「不是啊 他根本沒讓我輸入的機會啊」— the keychain-ACL
  # remediation didn't even apply, because keychain ACL reset was never the
  # cause THIS time): all 3 attempts return exit=142 (perl SIGALRM) with EMPTY
  # output in the timeout-under-load case — no "Not logged in" / "please
  # run /login" / auth-rejection text ever appears, because the process never
  # got a response at all, it just ran out of time. That is a categorically
  # different failure from a genuine credential rejection (which responds fast
  # with explicit rejection text). Distinguish them by grepping the captured
  # output for an actual auth-failure signature before recommending the
  # keychain-ACL hotfix — a load-timeout call needs a longer timeout / less
  # concurrent load, not a Keychain permission change.
  local combined="${first_output}${retry_output}${retry3_output}"
  local looks_like_real_auth_failure=0
  if printf '%s' "$combined" | grep -qiE "not logged in|please run|/login|unauthorized|invalid_grant|re-?authenticate|401|403"; then
    looks_like_real_auth_failure=1
  fi

  # 2026-07-02 fix (c) — TCC-shaped failure recognition (docs/error_log.md 10:55 entry).
  # When claude CLI auto-updates, the new binary loses its per-binary macOS TCC
  # Desktop-folder grant; launchd-context jobs (cwd in ~/Desktop) then fail with
  # Operation-not-permitted / getcwd / EINTR signatures — NOT auth, NOT load.
  # Reboot and keychain hotfix are both wrong here; the fix is: open an
  # interactive session (authorized context) to re-trigger the grant.
  local looks_like_tcc_failure=0
  if printf '%s' "$combined" | grep -qiE "operation not permitted|getcwd|cannot access parent director|interrupted system call|EINTR|current directory does not exist"; then
    looks_like_tcc_failure=1
  fi
  # Did the claude symlink switch recently (~<=18h)? Strong corroboration that a
  # CLI auto-update just invalidated the TCC grant.
  local claude_link_age_h=999
  local _link_mtime
  _link_mtime=$(stat -f %m "$CLAUDE_BIN" 2>/dev/null)
  if [ -n "$_link_mtime" ]; then
    claude_link_age_h=$(( ( $(date +%s) - _link_mtime ) / 3600 ))
  fi

  if [ "$looks_like_tcc_failure" -eq 1 ]; then
    local _updated_note
    if [ "$claude_link_age_h" -le 18 ]; then
      _updated_note="claude symlink 在約 ${claude_link_age_h}h 前才切換過（=CLI 剛自動更新）——**這就是根因**：新版 binary 尚未取得 Desktop TCC 授權。"
    else
      _updated_note="claude symlink 已 ${claude_link_age_h}h 未變更；TCC Desktop 授權可能因其他原因失效（仍非 auth/load 問題）。"
    fi
    auth_body=$(printf '%s\n' \
"## 觸發條件（TCC-shaped 失敗，非 auth、非負載）" \
"- auth-preflight 輸出含 \`Operation not permitted\` / \`getcwd\` / \`Interrupted system call (EINTR)\` / \`Current directory does not exist\` 特徵" \
"- ${_updated_note}" \
"" \
"## 根因（已於 2026-07-02 決定性實驗確認）" \
"- macOS TCC 的 Desktop 資料夾授權**綁定 binary 路徑+雜湊**；claude CLI 每 1-2 天自動更新，新版 binary 對 \`~/Desktop\` 預設**無授權**" \
"- 歷史事故（2026-07-02，當時 repo 還在 ~/Desktop/volpred-research TCC 保護區；現已搬至 ~/volpred-research，正常情況不應再出現此類失敗）→ launchd context 無 UI 可跳授權 → TCC 請求懸置 → 拖累 tccd → 跨行程逾時/EINTR 全滅" \
"- 互動 session 不受影響（走已授權 parent app 快速路徑）" \
"" \
"## 正確處置（**不要**重開機、**不要**跑 keychain 指令）" \
"1. **開一個互動 Claude session**（在 Desktop 下）即可從授權 context 重新觸發 TCC 授權，launchd 排程隨即自癒——這是唯一有效且必要的動作" \
"2. SessionStart hook \`warm_tcc_authorization.sh\` 已會在偵測到版本變更時自動暖授權；若此信仍出現，代表更新後尚無互動 session 開啟" \
"3. 重開機無效：TCC.db 是持久化資料庫，重開機不會補回缺失授權" \
"" \
"詳見 docs/error_log.md 2026-07-02 10:55「ROOT CAUSE CONFIRMED」條目。")
  elif [ "$looks_like_real_auth_failure" -eq 1 ]; then
    auth_body=$(printf '%s\n' \
"## 觸發條件" \
"- \`cron_hourly_dispatch.sh\` auth pre-flight 在 launchd env 失敗，且 source \`~/.zshrc\` 後重試仍失敗" \
"- pre-flight timeout: ${AUTH_PREFLIGHT_TIMEOUT_SEC}s" \
"- 輸出內含明確的認證拒絕訊號（非純逾時），判定為真正的 auth/credential 問題" \
"" \
"首次輸出：" \
'```' \
"${first_output}" \
'```' \
"" \
"重試輸出：" \
'```' \
"${retry_output}" \
'```' \
"" \
"## 影響" \
"- 本輪 hourly dispatch 不會進入 3-attempt 主流程，避免無效重試與重複 generic CRITICAL" \
"- 直到 keychain / Claude CLI auth 恢復前，排程派工會持續停擺" \
"" \
"## 建議行動" \
'```' \
"${AUTH_HOTFIX_CMD}" \
'```' \
"" \
"執行後可用：" \
'```' \
"env -i HOME=\$HOME PATH=\$PATH ${CLAUDE_BIN} -p \"say hi\" 2>&1 | head -3" \
'```' \
"確認不再出現 \`Not logged in · Please run /login\`")
  else
    auth_body=$(printf '%s\n' \
"## 觸發條件" \
"- \`cron_hourly_dispatch.sh\` auth pre-flight 連 3 次都逾時（exit=142，SIGALRM @ ${AUTH_PREFLIGHT_TIMEOUT_SEC}s），**輸出完全空白**" \
"- 空白輸出 = claude CLI 從未真正回應，不是收到了明確的認證拒絕訊息——這通常代表回應太慢（機器同時跑多個 claude/codex process 造成資源競爭、或 API 端暫時延遲），**不代表帳號額度或憑證真的壞掉**" \
"- 這次 email 標題雖然沿用同一個 alert（歷史上 2026-05-29 曾發生過 keychain ACL 被 token refresh 重置），但**這次沒有偵測到任何認證拒絕文字**，请不要直接假設是同一根因" \
"" \
"## 影響" \
"- 本輪 hourly dispatch 改由 Codex failover 接手（見下一封 codex failover 信）" \
"- 通常下一輪（或機器負載降下來後）會自行恢復，不需要人工介入" \
"" \
"## 建議行動（診斷順序，不要一開始就跑 keychain 指令）" \
"1. \`uptime\` 看目前 load average；\`ps aux | grep -E 'claude -p|codex exec'\` 看是否有多個並行的 claude/codex process 同時搶資源" \
"2. 若 load 明顯偏高（此機器 10 核心，load > 8 算重載）→ 屬於資源競爭造成的暫時逾時，等負載降下來即可，不需改任何設定" \
"3. 只有在輸出裡真的出現 \`Not logged in\` / \`please run /login\` 這類文字時，才需要跑 keychain ACL 指令：" \
'```' \
"${AUTH_HOTFIX_CMD}" \
'```')
  fi
  tmp=$(mktemp -t hourly_auth_fail.XXXXXX).md
  echo "$auth_body" > "$tmp"
  local alert_level alert_title
  if [ "$looks_like_tcc_failure" -eq 1 ]; then
    alert_level="critical"
    alert_title="hourly-dispatch TCC 授權失效 (claude 更新 → Desktop 無授權，開互動 session 修復) $(date '+%H:%M')"
  elif [ "$looks_like_real_auth_failure" -eq 1 ]; then
    alert_level="critical"
    alert_title="hourly-dispatch auth preflight failed $(date '+%H:%M')"
  else
    alert_level="warn"
    alert_title="hourly-dispatch auth preflight timed out (likely load, not auth) $(date '+%H:%M')"
  fi
  run_send_alert \
    --level "$alert_level" \
    --title "$alert_title" \
    --body-md "$tmp" --force 2>&1 | tail -1
  rm -f "$tmp"
}

# ── Claude→Codex failover (2026-06-28, user directive「claude -p 失敗 → codex exec 重跑同任務」)──
# When the Claude hourly dispatch cannot run (auth/quota dead OR all 3 model
# attempts exhausted), fall back to Codex. Codex authenticates via ChatGPT
# (~/.codex), wholly independent of the Claude subscription quota, and already
# knows the handoff-driven hourly tick from AGENTS.md. On Codex success the
# hourly slot still produced work, so the caller treats the run as recovered
# (EXIT_CODE=0 → PHASE-Z commits whatever Codex left). Always warns the boss
# that Claude degraded (visibility). codex exec is headless + workspace-write;
# its stdout streams into this same dispatch log.
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || echo /Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex)}"
FAILOVER_PROMPT_FILE="${FAILOVER_PROMPT_FILE:-$REPO_ROOT/scripts/cron_hourly_dispatch_codex_failover_prompt.md}"
# Codex failover budget (2026-06-30 fix #1, after 2026-06-29 21:07 incident).
# Root cause: failover gave Codex the full 50min HOURLY_CAP_SEC, so when both
# Anthropic and ChatGPT API outage'd together, Codex SIGALRM'd at 50min and the
# 21:07 fire ran 2h52min wall-clock total (incl. 1h57min post-codex hang) →
# LaunchAgent skipped 22:07 + 23:07 fires (same Label no-concurrency rule).
# Fix: (a) cheap local-binary preflight (codex --version, ~80ms, 0 tokens) so
# truly dead/missing binary aborts immediately, (b) failover task cap = 10min
# not 50min — if Codex API also dead the wrapper exits 21:13 not 22:02, leaving
# enough buffer for 22:07 LaunchAgent fire. Trade-off: large failover tasks
# won't fit 10min; acceptable since the primary path is Claude and failover is
# supposed to handle simple Codex-eligible items.
CODEX_PREFLIGHT_TIMEOUT_SEC="${CODEX_PREFLIGHT_TIMEOUT_SEC:-30}"
CODEX_FAILOVER_CAP_SEC="${CODEX_FAILOVER_CAP_SEC:-600}"
CODEX_FAILOVER_RC=1

run_codex_failover() {
  local reason="$1"
  CODEX_FAILOVER_RC=1
  echo "=== [FAILOVER] Claude dispatch unavailable ($reason) → Codex exec at $(date '+%H:%M:%S') ==="
  if [ ! -x "$CODEX_BIN" ] && ! command -v codex >/dev/null 2>&1; then
    echo "[FAILOVER] codex binary not found ($CODEX_BIN) — cannot failover"
    CODEX_FAILOVER_RC=127
    return 127
  fi
  # ── Local-binary preflight (2026-06-30 fix #1a) ──
  # codex --version: ~80ms + 0 tokens, no API call. Confirms binary exists and
  # node runtime can load it. Doesn't test API reachability — that's covered by
  # the short CODEX_FAILOVER_CAP_SEC (fix #1b) so a dead API can't burn 50min.
  echo "[FAILOVER] codex --version preflight (${CODEX_PREFLIGHT_TIMEOUT_SEC}s ceiling) at $(date '+%H:%M:%S')"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$CODEX_PREFLIGHT_TIMEOUT_SEC" \
    "$CODEX_BIN" --version >/dev/null 2>&1
  local preflight_rc=$?
  if [ "$preflight_rc" -ne 0 ]; then
    CODEX_FAILOVER_RC=$preflight_rc
    # 2026-07-02 fix (05:07 incident): a bare non-zero rc here used to be
    # unconditionally reported as "binary broken" — but rc=142 is perl's
    # SIGALRM, meaning `codex --version` simply never returned within
    # ${CODEX_PREFLIGHT_TIMEOUT_SEC}s, not that the binary is broken. Live
    # verification that night: running `codex --version` manually right after
    # this fired returned instantly with `codex-cli 0.142.3` rc=0 — the
    # "binary broken" diagnosis was a false positive caused by system load,
    # the exact same misdiagnosis class already fixed for the Claude
    # auth-preflight above. Distinguish the two so the alert (and the human
    # reading it) isn't sent chasing a phantom binary problem.
    local pbody ptmp preflight_level preflight_reason preflight_action
    if [ "$preflight_rc" -eq 142 ]; then
      echo "[FAILOVER] codex --version preflight TIMED OUT rc=142 (${CODEX_PREFLIGHT_TIMEOUT_SEC}s ceiling, likely load not a broken binary) at $(date '+%H:%M:%S') — abort failover this round only"
      preflight_level="warn"
      preflight_reason="逾時（SIGALRM @ ${CODEX_PREFLIGHT_TIMEOUT_SEC}s），**輸出空白，非 binary 損壞的錯誤訊息**——通常是機器同時跑多個 claude/codex process 造成資源競爭"
      preflight_action="- 通常負載降下來後下一輪會自行恢復，不需要人工介入\n- 可跑 \`uptime\` 確認 load average；\`ps aux | grep -E 'claude -p|codex exec'\` 看是否有多個並行 process\n- 只有再次手動跑 \`codex --version\` 也逾時/報錯時，才需要懷疑 binary 本身"
    else
      echo "[FAILOVER] codex --version preflight failed rc=$preflight_rc at $(date '+%H:%M:%S') — binary broken, abort failover"
      preflight_level="critical"
      preflight_reason="rc=${preflight_rc}（非逾時的 SIGALRM 142），可能是 binary 損壞 / node runtime 問題 / 系統資源耗盡"
      preflight_action="- 跑 \`codex --version\` 看 binary 狀態\n- 跑 \`ls -la $CODEX_BIN\` 確認檔案存在\n- 必要時 npm reinstall codex-cli"
    fi
    pbody=$(printf '%s\n' \
"## 觸發條件" \
"- Claude hourly dispatch 失敗（${reason}）→ 啟動 Codex failover" \
"- Codex --version 也失敗：${preflight_reason}" \
"" \
"## 影響" \
"- 本班 hourly dispatch 直接 abort，不會浪費時間跑死 task" \
"- 下班 LaunchAgent fire (HH+1:07) 能正常啟動" \
"" \
"## 建議行動" \
"$(printf '%b' "$preflight_action")")
    ptmp=$(mktemp -t codex_preflight_fail.XXXXXX).md
    echo "$pbody" > "$ptmp"
    run_send_alert \
      --level "$preflight_level" \
      --title "hourly-dispatch Codex binary preflight $([ "$preflight_rc" -eq 142 ] && echo "timed out (likely load)" || echo "失敗") $(date '+%H:%M')" \
      --body-md "$ptmp" --force 2>&1 | tail -1
    rm -f "$ptmp"
    return "$CODEX_FAILOVER_RC"
  fi
  echo "[FAILOVER] codex --version preflight OK — proceeding to full failover at $(date '+%H:%M:%S')"
  local cp
  if [ -f "$FAILOVER_PROMPT_FILE" ]; then
    cp=$(cat "$FAILOVER_PROMPT_FILE")
  else
    cp="新一輪 hourly tick（Claude dispatch 失敗 failover）。cat storage/ops/handoff_latest.md，依同樣流程 claim 下一個 Codex-eligible pending task → 完整完成 → complete → commit [codex]。reader-facing / email_reply / FB / paper_body 類留給 Claude，不要碰。"
  fi
  # ── Short failover cap (2026-06-30 fix #1b) ──
  # 10min cap not 50min: failover is supposed to do *something* not everything.
  # If Codex API is also dead, SIGALRM fires at 10min not 50min, and the next
  # LaunchAgent slot at HH+1:07 isn't starved. Large failover tasks won't fit
  # 10min — acceptable since primary path is Claude and failover is best-effort.
  echo "[FAILOVER] codex exec start (cap=${CODEX_FAILOVER_CAP_SEC}s) at $(date '+%H:%M:%S')"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$CODEX_FAILOVER_CAP_SEC" \
    "$CODEX_BIN" exec --skip-git-repo-check -s workspace-write "$cp"
  CODEX_FAILOVER_RC=$?
  echo "=== [FAILOVER] codex exec rc=$CODEX_FAILOVER_RC at $(date '+%H:%M:%S') ==="
  local fbody tmp
  fbody=$(printf '%s\n' \
"## 觸發條件" \
"- Claude hourly dispatch 失敗（${reason}）→ 啟動 Codex failover" \
"- Codex exec 結果 exit code: ${CODEX_FAILOVER_RC}（0=Codex 接手成功，非0=雙雙失敗）" \
"" \
"## 影響" \
"- Claude 那條線暫時不可用（額度/auth/API）；本輪由 Codex（ChatGPT auth，獨立額度）接手 Codex-eligible 工作" \
"- reader-facing / email / FB / paper_body 仍需 Claude，Claude 恢復前會累積" \
"" \
"## 建議行動" \
"- Codex 接手 = Claude 端有問題；查 Claude 額度 / status.claude.com" \
"- 若 Claude 額度耗盡：加 Anthropic API key 當 overflow，或讓 Codex 主力撐到額度恢復")
  tmp=$(mktemp -t hourly_failover.XXXXXX).md
  echo "$fbody" > "$tmp"
  run_send_alert \
    --level warn \
    --title "hourly-dispatch Claude→Codex failover (codex rc=$CODEX_FAILOVER_RC) $(date '+%H:%M')" \
    --body-md "$tmp" --force 2>&1 | tail -1
  rm -f "$tmp"
  return "$CODEX_FAILOVER_RC"
}

echo "=== auth-preflight $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
AUTH_PREFLIGHT_OUTPUT=$(run_auth_preflight)
AUTH_PREFLIGHT_CODE=$?
if [ $AUTH_PREFLIGHT_CODE -ne 0 ]; then
  echo "[AUTH-PREFLIGHT] launchd env failed exit=$AUTH_PREFLIGHT_CODE"
  echo "$AUTH_PREFLIGHT_OUTPUT"
  if [ -f "$ZSHRC_PATH" ]; then
    echo "[AUTH-PREFLIGHT] sourcing $ZSHRC_PATH then retry (${ZSHRC_SOURCE_TIMEOUT_SEC}s ceiling)"
    # See ZSHRC_SOURCE_TIMEOUT_SEC comment above (2026-07-02 fix). `source` is
    # a bash builtin so it can't be perl-alarm-wrapped in place; instead run
    # the rc file in an external, alarm-able `zsh -c` subprocess and pull back
    # only PATH (the one plausibly load-bearing side effect for the keychain
    # fallback path below). On timeout, skip silently — never block on this.
    ZSHRC_ENV_FILE=$(mktemp -t zshrc_env.XXXXXX)
    /usr/bin/perl -e 'alarm shift; exec @ARGV' "$ZSHRC_SOURCE_TIMEOUT_SEC" \
      /bin/zsh -c "source '$ZSHRC_PATH' >/dev/null 2>&1; echo \"PATH=\$PATH\"" \
      > "$ZSHRC_ENV_FILE" 2>/dev/null
    ZSHRC_SOURCE_RC=$?
    if [ "$ZSHRC_SOURCE_RC" -eq 0 ] && grep -q '^PATH=' "$ZSHRC_ENV_FILE"; then
      export PATH="$(grep '^PATH=' "$ZSHRC_ENV_FILE" | head -1 | cut -d= -f2-)"
      echo "[AUTH-PREFLIGHT] zshrc sourced via subprocess ok (PATH refreshed)"
    else
      echo "[AUTH-PREFLIGHT] zshrc source timed out/failed rc=$ZSHRC_SOURCE_RC (${ZSHRC_SOURCE_TIMEOUT_SEC}s ceiling) — skipping; CLAUDE_CODE_OAUTH_TOKEN bypass above is the load-bearing auth path, this fallback is best-effort only"
    fi
    rm -f "$ZSHRC_ENV_FILE"
  else
    echo "[AUTH-PREFLIGHT] no zshrc at $ZSHRC_PATH"
  fi
  AUTH_PREFLIGHT_RETRY_OUTPUT=$(run_auth_preflight)
  AUTH_PREFLIGHT_RETRY_CODE=$?
  if [ $AUTH_PREFLIGHT_RETRY_CODE -ne 0 ]; then
    echo "[AUTH-PREFLIGHT] retry failed exit=$AUTH_PREFLIGHT_RETRY_CODE"
    echo "$AUTH_PREFLIGHT_RETRY_OUTPUT"
    # 3rd attempt with backoff — env-source can't fix a transient API blip
    # because attempts 1-2 fire within seconds. Let the blip clear, then retry.
    echo "[AUTH-PREFLIGHT] backoff ${AUTH_PREFLIGHT_BACKOFF_SEC}s then 3rd attempt"
    sleep "$AUTH_PREFLIGHT_BACKOFF_SEC"
    AUTH_PREFLIGHT_RETRY3_OUTPUT=$(run_auth_preflight)
    AUTH_PREFLIGHT_RETRY3_CODE=$?
    if [ $AUTH_PREFLIGHT_RETRY3_CODE -ne 0 ]; then
      echo "[AUTH-PREFLIGHT] 3rd attempt failed exit=$AUTH_PREFLIGHT_RETRY3_CODE"
      echo "$AUTH_PREFLIGHT_RETRY3_OUTPUT"
      send_auth_preflight_alert "$AUTH_PREFLIGHT_OUTPUT" "$AUTH_PREFLIGHT_RETRY_OUTPUT" "$AUTH_PREFLIGHT_RETRY3_OUTPUT"
      # Claude auth/quota dead → Codex failover (ChatGPT auth is independent).
      # Retrying claude -p in the 3-attempt main flow would be futile, so we
      # hand the slot to Codex here and exit without touching the Claude path.
      run_codex_failover "auth-preflight-dead"
      if [ "$CODEX_FAILOVER_RC" -eq 0 ]; then
        # 2026-07-02: same perl-alarm ceiling already used in the PHASE-Z
        # block below — these git calls were the one spot that had been
        # missed, and tonight showed even local git-adjacent filesystem
        # syscalls can stall under load.
        if [ -n "$(/usr/bin/perl -e 'alarm shift; exec @ARGV' 30 /usr/bin/git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then
          echo "[FAILOVER] committing work Codex left after auth-dead failover"
          /usr/bin/perl -e 'alarm shift; exec @ARGV' 30 /usr/bin/git -C "$REPO_ROOT" add -A 2>&1 | tail -1
          /usr/bin/perl -e 'alarm shift; exec @ARGV' 60 /usr/bin/git -C "$REPO_ROOT" commit -m "ops(hourly $(date '+%H:%M')): codex failover auto-commit (claude auth dead)" 2>&1 | tail -1
        fi
        echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=0 codex-failover-recovered) ==="
        echo "=== [hourly_dispatch] exit 0 at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
        exit 0
      fi
      echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=1 preflight-auth + codex-failover-failed) ==="
      echo "=== [hourly_dispatch] exit 1 at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
      exit 1
    fi
    echo "[AUTH-PREFLIGHT] recovered after backoff 3rd attempt"
  else
    echo "[AUTH-PREFLIGHT] recovered after sourcing zshrc"
  fi
else
  echo "[AUTH-PREFLIGHT] ok"
fi

if [ "${HOURLY_PREFLIGHT_ONLY:-0}" = "1" ]; then
  echo "[AUTH-PREFLIGHT] test-only exit after successful preflight"
  echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=0 preflight-only) ==="
  echo "=== [hourly_dispatch] exit 0 at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  exit 0
fi

# Read prompt from external file to avoid bash quoting hell with Chinese + backticks
PROMPT=$(cat "$PROMPT_FILE")

# Single dispatch attempt with full hang-defense (perl alarm + watchdog).
# Returns claude's exit code via global EXIT_CODE. Sets CLAUDE_PID for trap.
run_one_attempt() {
  local model=$1

  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$HOURLY_CAP_SEC" \
    "$CLAUDE_BIN" -p --dangerously-skip-permissions \
    --model "$model" "$PROMPT" &
  CLAUDE_PID=$!

  (
    sleep $((HOURLY_CAP_SEC + 60))
    ACTUAL_CMD=$(ps -p "$CLAUDE_PID" -o comm= 2>/dev/null | tr -d '[:space:]')
    if kill -0 "$CLAUDE_PID" 2>/dev/null && [[ "$ACTUAL_CMD" == *"$CLAUDE_CMD_PATTERN"* ]]; then
      echo "[WATCHDOG] claude PID $CLAUDE_PID (cmd=$ACTUAL_CMD) alive past cap+60s; SIGTERM to PGID"
      kill -TERM -- "-$CLAUDE_PID" 2>/dev/null || kill -TERM "$CLAUDE_PID" 2>/dev/null
      sleep 10
      ACTUAL_CMD2=$(ps -p "$CLAUDE_PID" -o comm= 2>/dev/null | tr -d '[:space:]')
      if kill -0 "$CLAUDE_PID" 2>/dev/null && [[ "$ACTUAL_CMD2" == *"$CLAUDE_CMD_PATTERN"* ]]; then
        echo "[WATCHDOG] SIGTERM ignored; SIGKILL to PGID"
        kill -KILL -- "-$CLAUDE_PID" 2>/dev/null || kill -KILL "$CLAUDE_PID" 2>/dev/null
      fi
    elif [ -n "$ACTUAL_CMD" ] && [[ "$ACTUAL_CMD" != *"$CLAUDE_CMD_PATTERN"* ]]; then
      echo "[WATCHDOG] aborted — PID $CLAUDE_PID now belongs to '$ACTUAL_CMD' (PID reuse)"
    fi
  ) &
  WATCHDOG_PID=$!

  wait $CLAUDE_PID
  EXIT_CODE=$?

  kill $WATCHDOG_PID 2>/dev/null
  WATCHDOG_PID=""

  if [ $EXIT_CODE -eq 142 ]; then
    echo "[HANG-KILLED] claude -p exceeded ${HOURLY_CAP_SEC}s cap (SIGALRM via perl alarm)"
  elif [ $EXIT_CODE -eq 143 ] || [ $EXIT_CODE -eq 137 ]; then
    echo "[HANG-KILLED] claude -p killed by watchdog (SIGTERM=143 / SIGKILL=137)"
  fi
}

# Retry loop with model fallback (added 2026-05-25 — 17:07/18:07 fire 都 hit
# Anthropic API 529 Overloaded → previous single-shot exit 1 → pool 連 2 hour
# 沒消化 → CRITICAL alert. Fix: ≤3 attempts, exponential-ish wait, sonnet
# fallback on last try).
MAX_ATTEMPTS=3
ATTEMPT=1
EXIT_CODE=1

while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
  if [ $ATTEMPT -eq 3 ]; then
    DISPATCH_MODEL=claude-sonnet-5    # fallback (downgrade)
  else
    DISPATCH_MODEL=claude-opus-4-8    # primary
  fi
  echo "=== attempt $ATTEMPT/$MAX_ATTEMPTS model=$DISPATCH_MODEL at $(date '+%H:%M:%S') ==="

  run_one_attempt "$DISPATCH_MODEL"

  # Success → done
  if [ $EXIT_CODE -eq 0 ]; then
    break
  fi

  # Hang-killed → NO retry (real timeout, not transient)
  if [ $EXIT_CODE -eq 142 ] || [ $EXIT_CODE -eq 143 ] || [ $EXIT_CODE -eq 137 ]; then
    echo "[NO-RETRY] hang detected (exit=$EXIT_CODE), aborting retry loop"
    break
  fi

  # Transient (API 529, network, etc) → wait + retry
  if [ $ATTEMPT -lt $MAX_ATTEMPTS ]; then
    WAIT=90  # 90s backoff before next attempt
    echo "[RETRY] attempt $ATTEMPT failed exit=$EXIT_CODE; sleep ${WAIT}s before next"
    sleep $WAIT
  fi
  ATTEMPT=$((ATTEMPT + 1))
done

# Proactive failure report (added 2026-05-25 per user directive 「遇到失敗也要回報進度」)
# If all retries failed, immediately email user with diagnosis — don't wait
# for check_alerts at next :00 to detect it. Skip if 0 exit (success) or
# hang-killed (different alert path, less mysterious).
if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 142 ] && [ $EXIT_CODE -ne 143 ] && [ $EXIT_CODE -ne 137 ]; then
  echo "[FAIL-REPORT] all $MAX_ATTEMPTS attempts failed, sending proactive alert"
  FAIL_BODY=$(cat <<FAILEOF
# Hourly-dispatch 連續 $MAX_ATTEMPTS 次 attempt 全失敗

## 時間

- Fire 開始: $(date '+%Y-%m-%d %H:%M:%S %Z')
- 最後 exit code: \`$EXIT_CODE\`
- Models tried: opus → opus → sonnet (fallback)

## 最後 30 行 dispatch log

\`\`\`
$(tail -30 "$HOURLY_LOG_PATH" 2>&1 | sed 's/\`/<bt>/g')
\`\`\`

## 影響範圍

- 本輪 dispatch 沒派工 → agentable queue 沒消化（main_thread queue 可能仍有待辦；pending email_reply 持續累積）
- 下次 fire 在 1 小時後（HH+1:07）

## 可能根因

- Anthropic API 持續過載（連 sonnet fallback 也 fail）
- 網路斷線
- claude CLI binary 損壞
- 系統資源耗盡（ulimit / memory）

## 建議行動

\`\`\`
tail -100 $HOURLY_LOG_PATH
curl -s https://status.claude.com/api/v2/status.json | jq .status
ps -ef | grep claude | head
\`\`\`

---

*Auto-sent by cron_hourly_dispatch.sh fail-report (proactive, bypasses check_alerts dedup)*
FAILEOF
)
  TMP=$(mktemp -t hourly_fail.XXXXXX).md
  echo "$FAIL_BODY" > "$TMP"
  run_send_alert \
    --level critical \
    --title "hourly-dispatch 全 attempt 失敗 (exit $EXIT_CODE) $(date '+%H:%M')" \
    --body-md "$TMP" --force 2>&1 | tail -1
  rm -f "$TMP"
fi

# ── Claude→Codex failover after all retries exhausted (2026-06-28) ──
# All 3 Claude attempts failed for a non-hang reason (529 storm / network /
# quota / binary). Hand the slot to Codex before giving up. On Codex success
# treat the run as recovered (EXIT_CODE=0) so PHASE-Z commits its work and the
# exit banner reports success — the hourly slot did NOT go dark.
if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 142 ] && [ $EXIT_CODE -ne 143 ] && [ $EXIT_CODE -ne 137 ]; then
  run_codex_failover "retries-exhausted-exit-$EXIT_CODE"
  if [ "$CODEX_FAILOVER_RC" -eq 0 ]; then
    echo "[FAILOVER] Codex recovered the slot; treating run as success (EXIT_CODE 0)"
    EXIT_CODE=0
  fi
fi

# ── PHASE Z safety-net (2026-05-29): wrapper-enforced commit ──
# PHASE Z in the dispatch prompt is agent-discretion → ~90% reliable (15:07
# fire left scan_trending_agy.py untracked despite git-add-A instruction).
# This deterministic post-dispatch commit catches whatever the agent missed.
# All state/log noise is gitignored, so `git add -A` only stages real work —
# BUT that assumption only holds while the file has never been tracked; once
# any process (stash-pop, a stray `git add <path>`, an old pre-gitignore
# commit) re-tracks a gitignored runtime-state file even once, `git add -A`
# happily re-stages every future mutation forever, since gitignore does not
# apply to already-tracked paths. 2026-07-01 incident: storage/.release_settings.json
# (+ notification_log.json, session_state.json, writer_log.jsonl) had drifted
# back into tracking this way; a PHASE-Z auto-commit captured a stale
# interval_minutes=60 snapshot and silently reverted the boss's 2026-06-30
# "3h→6h" cadence directive back to a 1h cadence. Line below untracks any
# specific flat runtime-state file that matches .gitignore but is still
# tracked, BEFORE staging, so this can't recur. Scoped to the known flat
# state-file list (not storage/ops/{tasks,agents,executions,approvals,
# rollback_points,locks}/ — those are directories with potentially large
# historical content and need a separate, deliberate cleanup pass, not an
# unattended hourly rm --cached) and never touches paper/*/main.pdf
# (deliberately force-tracked exception). NOTE: `git check-ignore` reports
# already-tracked paths as NOT ignored (by design) — must use
# `git ls-files -ci --exclude-standard` instead, which is the only ls-files
# combination that actually lists tracked-but-ignored paths.
# 2026-06-30 fix #3: timestamp echo to diagnose 22:02→23:59 1h57min hang
# (2026-06-29 21:07 incident — wrapper invisibly hung after codex failover exit;
# unclear if hang was in `git status`, send-alert subprocess boot, or git commit).
echo "[PHASE-Z-safety] start $(date '+%H:%M:%S')"
echo "[PHASE-Z-safety] git status check $(date '+%H:%M:%S')"
PHASE_Z_STATUS=$(/usr/bin/perl -e 'alarm shift; exec @ARGV' 30 \
  /usr/bin/git -C "$REPO_ROOT" status --porcelain 2>/dev/null)
echo "[PHASE-Z-safety] git status returned $(date '+%H:%M:%S')"
if [ -n "$PHASE_Z_STATUS" ]; then
  echo "[PHASE-Z-safety] uncommitted changes after dispatch — auto-committing"
  PHASE_Z_LEAKED_IGNORED=$(/usr/bin/perl -e 'alarm shift; exec @ARGV' 30 \
    /usr/bin/git -C "$REPO_ROOT" ls-files -ci --exclude-standard -- \
    storage/ops/dashboard_latest.json storage/ops/alert_dedup.json \
    storage/ops/cron_last_run.json storage/ops/pending_sessions.json \
    storage/ops/gmail_inbox_state.json storage/ops/dispatch_report_latest.json \
    storage/ops/handoff_latest.md storage/ops/writer_log.jsonl \
    storage/.release_settings.json storage/.supabase_sync_state.json \
    storage/market_status.json 'storage/notifications/*.json' \
    storage/session_state.json storage/work_log.json.append 2>/dev/null || true)
  if [ -n "$PHASE_Z_LEAKED_IGNORED" ]; then
    echo "[PHASE-Z-safety] untracking accidentally-tracked ignored state file(s):"
    echo "$PHASE_Z_LEAKED_IGNORED" | sed 's/^/[PHASE-Z-safety]   /'
    echo "$PHASE_Z_LEAKED_IGNORED" | /usr/bin/xargs -I{} /usr/bin/perl -e 'alarm shift; exec @ARGV' 30 /usr/bin/git -C "$REPO_ROOT" rm --cached -q -- "{}" 2>/dev/null || true
  fi
  /usr/bin/perl -e 'alarm shift; exec @ARGV' 30 \
    /usr/bin/git -C "$REPO_ROOT" add -A 2>&1 | tail -1
  echo "[PHASE-Z-safety] git add done $(date '+%H:%M:%S')"
  /usr/bin/perl -e 'alarm shift; exec @ARGV' 60 \
    /usr/bin/git -C "$REPO_ROOT" commit -m "ops(hourly $(date '+%H:%M')): PHASE-Z safety-net auto-commit (agent left uncommitted)" 2>&1 | tail -1
  echo "[PHASE-Z-safety] git commit done $(date '+%H:%M:%S')"
else
  echo "[PHASE-Z-safety] working tree clean — agent PHASE Z committed everything"
fi
echo "[PHASE-Z-safety] end $(date '+%H:%M:%S')"

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="
# Canonical exit banner — host_cron_fail alert (src/volpred/ops/alerts.py
# _CRON_EXIT_RE) only recognises the `=== [<job>] exit <N> at <ts> ===` form.
# Without this line a failed hourly-dispatch run never alerts.
echo "=== [hourly_dispatch] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# macOS notification (heredoc avoids nested-quote issues)
LATEST_COMMIT=$(/usr/bin/perl -e 'alarm shift; exec @ARGV' 15 /usr/bin/git -C /Users/yhlai0911/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100 | tr -d '"\\')
NOW=$(date '+%H:%M')
/usr/bin/osascript <<OSAEND 2>/dev/null || true
display notification "${LATEST_COMMIT}" with title "volpred hourly-dispatch ${NOW}" sound name "Pop"
OSAEND
