#!/bin/bash
# Hourly dispatch trigger via macOS LaunchAgent.
# Schedule: HH:07 every hour (24 slots/day). Reverted from 4-hourly per user
# directive 2026-05-16. Task scoping must fit ~50min cap (smaller units;
# heavy work goes to compute_queue.py for async worker pickup).
#
# Canonical source: scripts/cron_hourly_dispatch.sh + scripts/cron_hourly_dispatch_prompt.md
# TCC copy: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh

REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/Desktop/volpred-research}"
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
AUTH_PREFLIGHT_TIMEOUT_SEC="${AUTH_PREFLIGHT_TIMEOUT_SEC:-90}"
AUTH_PREFLIGHT_MODEL="${AUTH_PREFLIGHT_MODEL:-claude-sonnet-4-6}"
# Backoff before a 3rd preflight attempt — the first 2 attempts fire within
# seconds (launchd-env + zshrc-source), so a transient Claude API blip
# ("An unknown error occurred (Unexpected)") defeats both. ~8% of runs hit
# this and self-recover the next hour; this backoff lets the blip clear within
# the same run instead of skipping a dispatch slot. 2026-05-30 (05:08 incident).
AUTH_PREFLIGHT_BACKOFF_SEC="${AUTH_PREFLIGHT_BACKOFF_SEC:-20}"
AUTH_HOTFIX_CMD="${AUTH_HOTFIX_CMD:-security set-generic-password-partition-list -S apple-tool:,apple:,launchd:,unsigned: -s \"Claude Code-credentials\" -k login.keychain}"

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

# Orchestrator model = opus-4-7 (per CLAUDE.md model selection table; high-risk
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

run_auth_preflight() {
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$AUTH_PREFLIGHT_TIMEOUT_SEC" \
    "$CLAUDE_BIN" -p --dangerously-skip-permissions \
    --model "$AUTH_PREFLIGHT_MODEL" "ping" 2>&1
  return $?
}

send_auth_preflight_alert() {
  local first_output=$1
  local retry_output=$2
  local auth_body tmp
  auth_body=$(printf '%s\n' \
"## 觸發條件" \
"- \`cron_hourly_dispatch.sh\` auth pre-flight 在 launchd env 失敗，且 source \`~/.zshrc\` 後重試仍失敗" \
"- pre-flight timeout: ${AUTH_PREFLIGHT_TIMEOUT_SEC}s" \
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
  tmp=$(mktemp -t hourly_auth_fail.XXXXXX).md
  echo "$auth_body" > "$tmp"
  "$UV_BIN" run volpred ops send-alert \
    --level critical \
    --title "hourly-dispatch auth preflight failed $(date '+%H:%M')" \
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
  local cp
  if [ -f "$FAILOVER_PROMPT_FILE" ]; then
    cp=$(cat "$FAILOVER_PROMPT_FILE")
  else
    cp="新一輪 hourly tick（Claude dispatch 失敗 failover）。cat storage/ops/handoff_latest.md，依同樣流程 claim 下一個 Codex-eligible pending task → 完整完成 → complete → commit [codex]。reader-facing / email_reply / FB / paper_body 類留給 Claude，不要碰。"
  fi
  # Same perl-alarm hang cap as the Claude path.
  /usr/bin/perl -e 'alarm shift; exec @ARGV' "$HOURLY_CAP_SEC" \
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
  "$UV_BIN" run volpred ops send-alert \
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
    echo "[AUTH-PREFLIGHT] sourcing $ZSHRC_PATH then retry"
    # shellcheck source=/dev/null
    source "$ZSHRC_PATH" 2>/dev/null || true
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
      send_auth_preflight_alert "$AUTH_PREFLIGHT_OUTPUT" "$AUTH_PREFLIGHT_RETRY3_OUTPUT"
      # Claude auth/quota dead → Codex failover (ChatGPT auth is independent).
      # Retrying claude -p in the 3-attempt main flow would be futile, so we
      # hand the slot to Codex here and exit without touching the Claude path.
      run_codex_failover "auth-preflight-dead"
      if [ "$CODEX_FAILOVER_RC" -eq 0 ]; then
        if [ -n "$(/usr/bin/git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then
          echo "[FAILOVER] committing work Codex left after auth-dead failover"
          /usr/bin/git -C "$REPO_ROOT" add -A 2>&1 | tail -1
          /usr/bin/git -C "$REPO_ROOT" commit -m "ops(hourly $(date '+%H:%M')): codex failover auto-commit (claude auth dead)" 2>&1 | tail -1
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
    DISPATCH_MODEL=claude-sonnet-4-6  # fallback (downgrade)
  else
    DISPATCH_MODEL=claude-opus-4-7    # primary
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
  "$UV_BIN" run volpred ops send-alert \
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
# All state/log noise is gitignored, so `git add -A` only stages real work.
if [ -n "$(/usr/bin/git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then
  echo "[PHASE-Z-safety] uncommitted changes after dispatch — auto-committing"
  /usr/bin/git -C "$REPO_ROOT" add -A 2>&1 | tail -1
  /usr/bin/git -C "$REPO_ROOT" commit -m "ops(hourly $(date '+%H:%M')): PHASE-Z safety-net auto-commit (agent left uncommitted)" 2>&1 | tail -1
else
  echo "[PHASE-Z-safety] working tree clean — agent PHASE Z committed everything"
fi

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="
# Canonical exit banner — host_cron_fail alert (src/volpred/ops/alerts.py
# _CRON_EXIT_RE) only recognises the `=== [<job>] exit <N> at <ts> ===` form.
# Without this line a failed hourly-dispatch run never alerts.
echo "=== [hourly_dispatch] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# macOS notification (heredoc avoids nested-quote issues)
LATEST_COMMIT=$(/usr/bin/git -C /Users/yhlai0911/Desktop/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100 | tr -d '"\\')
NOW=$(date '+%H:%M')
/usr/bin/osascript <<OSAEND 2>/dev/null || true
display notification "${LATEST_COMMIT}" with title "volpred hourly-dispatch ${NOW}" sound name "Pop"
OSAEND
