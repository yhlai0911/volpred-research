#!/bin/bash
# Codex hourly loop — runs in your VSCode terminal, fires every hour.
# First tick creates a session; subsequent ticks `resume --last` so the
# transcript / tool context / full agent features persist across ticks.
#
# Behaves like an always-on Codex agent sitting next to Claude Code,
# but tied to your VSCode session: terminal open -> loop runs;
# Ctrl-C stops it cleanly. A single-instance lock prevents duplicate
# orphan loops when a terminal is closed unexpectedly.
#
# Usage:
#   bash scripts/codex_loop.sh              # default: every 1h
#   INTERVAL_SEC=1800 bash scripts/codex_loop.sh   # every 30 min
#   FIRST_PROMPT_OVERRIDE='...' bash scripts/codex_loop.sh

set -m
cd "$(dirname "$0")/.." || exit 1

SELF=$$
LOCK_DIR="${CODEX_LOOP_LOCK_DIR:-${TMPDIR:-/tmp}/volpred_codex_loop.lock}"
LOCK_ACQUIRED=0

cleanup_single_instance_lock() {
  if [ "${LOCK_ACQUIRED:-0}" = "1" ] && [ -n "${LOCK_DIR:-}" ]; then
    rm -rf "$LOCK_DIR"
  fi
}

stop_loop() {
  echo
  echo "[loop] stopped by Ctrl-C at $(date +%H:%M:%S)"
  cleanup_single_instance_lock
  exit 0
}

# 2026-06-24: `pgrep -f 'scripts/codex_loop.sh'` empirically returns 0 on this
# host even when `ps -ax` lists 24 live instances (pgrep -f matching is broken
# here). That silent miss is exactly why the first upgraded loop failed to reap
# the pre-existing orphans. Detect siblings via ps, which works reliably.
list_codex_loop_pids() {
  ps -ax -o pid,command 2>/dev/null \
    | grep 'scripts/codex_loop.sh' \
    | grep -v grep \
    | awk '{print $1}'
}

acquire_single_instance_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_ACQUIRED=1
    echo "$SELF" > "$LOCK_DIR/pid"
    return
  fi

  existing_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "[loop] single-instance guard: codex_loop.sh already running pid=${existing_pid}; exiting"
    exit 0
  fi

  echo "[loop] single-instance guard: removing stale lock ${LOCK_DIR}"
  rm -rf "$LOCK_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_ACQUIRED=1
    echo "$SELF" > "$LOCK_DIR/pid"
    return
  fi

  echo "[loop] single-instance guard: failed to acquire lock ${LOCK_DIR}; exiting"
  exit 1
}

cleanup_legacy_codex_loop_siblings() {
  if [ "${CODEX_LOOP_SKIP_LEGACY_CLEANUP:-0}" = "1" ]; then
    return
  fi

  # 2026-06-23 fix: before the lock existed, closing VSCode terminal windows
  # orphaned loops under PPID=1. The first upgraded loop cleans those up.
  # Use ps-based detection (list_codex_loop_pids) — pgrep -f is broken here.
  SIBLINGS=$(list_codex_loop_pids | grep -vx "$SELF" || true)
  if [ -n "$SIBLINGS" ]; then
    echo "[loop] single-instance guard: stopping $(echo "$SIBLINGS" | wc -l | tr -d ' ') existing codex_loop.sh: $(echo "$SIBLINGS" | tr '\n' ' ')"
    for opid in $SIBLINGS; do kill -TERM "$opid" 2>/dev/null; done
    sleep 2
    for opid in $(list_codex_loop_pids | grep -vx "$SELF" || true); do kill -KILL "$opid" 2>/dev/null; done
  fi
}

acquire_single_instance_lock
trap cleanup_single_instance_lock EXIT
trap stop_loop INT TERM
cleanup_legacy_codex_loop_siblings

if [ "${CODEX_LOOP_GUARD_ONLY:-0}" = "1" ]; then
  echo "[loop] guard-only mode: single-instance guard acquired and released"
  exit 0
fi

INTERVAL_SEC="${INTERVAL_SEC:-3600}"
OWNER="${CODEX_OWNER:-codex-vscode}"

# ────────────────────────────────────────────────────────────
# First-tick prompt: full self-contained brief. AGENTS.md is auto-loaded
# by Codex from cwd so the workflow detail doesn't repeat here.
# ────────────────────────────────────────────────────────────
FIRST_PROMPT="${FIRST_PROMPT_OVERRIDE:-讀 AGENTS.md「Codex 每小時任務池工作流」執行：
1. cat storage/ops/handoff_latest.md
2. 從 section 4 pending top 8 挑一個 Codex 適合的 task_type（platform_ops / experiment / governance / code review / daily_article — 詳見 AGENTS.md 對照表）
3. uv run python scripts/task_pool_claim.py claim --id <id> --owner ${OWNER}
4. already_claimed → 換下一筆；全被 claim → 找 docs/error_log.md 近 7 天 actionable lint/refactor
5. start → 完整完成（50min 內收尾，不留半成品）→ complete
6. commit 訊息開頭加 [codex]，不 push
7. 結束回報：完成項目 + commit hash}"

# ────────────────────────────────────────────────────────────
# Subsequent-tick prompt: shorter, leverages resumed transcript memory.
# ────────────────────────────────────────────────────────────
RESUME_PROMPT="新一輪 hourly tick。重新 cat storage/ops/handoff_latest.md（每小時 :50 已重生），依同樣流程 claim 下一個 pending task → 完整完成 → complete → commit [codex]。若上一輪有未完事項，先收尾再挑新工。"

CODEX=/Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
BACKFILL_WORK_LOG_SCRIPT="${BACKFILL_WORK_LOG_SCRIPT:-scripts/backfill_work_log_from_commits.py}"

codex_work_log_backfill_since() {
  if [ -n "${CODEX_WORK_LOG_BACKFILL_SINCE:-}" ]; then
    printf '%s\n' "$CODEX_WORK_LOG_BACKFILL_SINCE"
    return
  fi
  date -v-2d '+%Y-%m-%d 00:00 %z' 2>/dev/null && return
  python3 - <<'PY'
from datetime import datetime, timedelta

now = datetime.now().astimezone()
start = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
print(start.strftime("%Y-%m-%d %H:%M %z"))
PY
}

backfill_codex_work_log_after_tick() {
  local rc="$1"
  local before_head="$2"
  local after_head="$3"

  if [ "$rc" -ne 0 ]; then
    echo "[work-log-hook] skip: codex rc=$rc"
    return 0
  fi
  if [ -z "$before_head" ] || [ -z "$after_head" ] || [ "$before_head" = "$after_head" ]; then
    echo "[work-log-hook] skip: no new commit from codex tick"
    return 0
  fi
  if [ -n "$(/usr/bin/git status --porcelain -- storage/work_log.json 2>/dev/null)" ]; then
    echo "[work-log-hook] skip: storage/work_log.json already dirty before backfill"
    return 0
  fi

  local since
  since="$(codex_work_log_backfill_since)"
  echo "[work-log-hook] codex HEAD advanced ${before_head:0:9}→${after_head:0:9}; backfill since=${since}"
  if ! "$UV_BIN" run python "$BACKFILL_WORK_LOG_SCRIPT" --since "$since" --apply; then
    echo "[work-log-hook] WARN backfill_work_log_from_commits.py failed"
    return 0
  fi

  if [ -z "$(/usr/bin/git status --porcelain -- storage/work_log.json 2>/dev/null)" ]; then
    echo "[work-log-hook] no work_log changes after backfill"
    return 0
  fi

  if [ "${CODEX_WORK_LOG_BACKFILL_AUTOCOMMIT:-1}" != "1" ]; then
    echo "[work-log-hook] backfilled work_log; autocommit disabled"
    return 0
  fi

  local short_after
  short_after="$(/usr/bin/git rev-parse --short "$after_head" 2>/dev/null || printf '%s' "${after_head:0:9}")"
  /usr/bin/git add storage/work_log.json
  if /usr/bin/git commit -m "ops(codex-loop): backfill work_log after ${short_after}"; then
    echo "[work-log-hook] committed work_log backfill for ${short_after}"
  else
    echo "[work-log-hook] WARN git commit failed after backfill"
  fi
}

if [ "${CODEX_LOOP_BACKFILL_HOOK_ONLY:-0}" = "1" ]; then
  backfill_codex_work_log_after_tick \
    "${CODEX_LOOP_HOOK_RC:-0}" \
    "${CODEX_LOOP_HOOK_BEFORE:-before}" \
    "${CODEX_LOOP_HOOK_AFTER:-after}"
  exit 0
fi

echo "[loop] start at $(date '+%Y-%m-%d %H:%M:%S')  interval=${INTERVAL_SEC}s  owner=${OWNER}"
echo "[loop] Ctrl-C to stop. AGENTS.md is auto-loaded by Codex."
echo

TICK=0
while true; do
  TICK=$((TICK + 1))
  echo "════════════════════════════════════════════════════════"
  echo "[tick #${TICK}] $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════════════"

  BEFORE_HEAD=$(/usr/bin/git rev-parse HEAD 2>/dev/null || true)
  if [ "$TICK" -eq 1 ]; then
    # 2026-06-18: dropped `-s workspace-write` — it overrode the global
    # config.toml `sandbox_mode = "danger-full-access"` and downgraded to a
    # mode that write-protects .git, so codex's own `git commit` silently
    # failed (.git/index.lock unwritable) and left every tick's work
    # uncommitted (K1501 incident). No flag = inherit config's full-access
    # mode → codex can commit its own [codex] work as AGENTS.md instructs.
    "$CODEX" exec --skip-git-repo-check "$FIRST_PROMPT"
  else
    # resume inherits sandbox from parent session; no -s flag needed (not accepted)
    "$CODEX" exec resume --last --skip-git-repo-check "$RESUME_PROMPT"
  fi
  RC=$?
  AFTER_HEAD=$(/usr/bin/git rev-parse HEAD 2>/dev/null || true)
  backfill_codex_work_log_after_tick "$RC" "$BEFORE_HEAD" "$AFTER_HEAD"

  echo
  echo "[tick #${TICK}] exit=$RC  done at $(date '+%H:%M:%S')"
  if [ "${CODEX_LOOP_ONCE:-0}" = "1" ]; then
    echo "[loop] CODEX_LOOP_ONCE=1; exiting after one tick"
    exit "$RC"
  fi
  echo "[loop] sleeping ${INTERVAL_SEC}s before next tick (Ctrl-C to stop)"
  sleep "$INTERVAL_SEC"
done
