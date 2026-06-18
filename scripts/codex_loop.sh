#!/bin/bash
# Codex hourly loop — runs in your VSCode terminal, fires every hour.
# First tick creates a session; subsequent ticks `resume --last` so the
# transcript / tool context / full agent features persist across ticks.
#
# Behaves like an always-on Codex agent sitting next to Claude Code,
# but tied to your VSCode session: terminal open → loop runs;
# Ctrl-C or close → loop stops. Zero launchd / cron / background daemon.
#
# Usage:
#   bash scripts/codex_loop.sh              # default: every 1h
#   INTERVAL_SEC=1800 bash scripts/codex_loop.sh   # every 30 min
#   FIRST_PROMPT_OVERRIDE='...' bash scripts/codex_loop.sh

set -m
cd "$(dirname "$0")/.." || exit 1

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

trap 'echo; echo "[loop] stopped by Ctrl-C at $(date +%H:%M:%S)"; exit 0' INT TERM

echo "[loop] start at $(date '+%Y-%m-%d %H:%M:%S')  interval=${INTERVAL_SEC}s  owner=${OWNER}"
echo "[loop] Ctrl-C to stop. AGENTS.md is auto-loaded by Codex."
echo

TICK=0
while true; do
  TICK=$((TICK + 1))
  echo "════════════════════════════════════════════════════════"
  echo "[tick #${TICK}] $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════════════"

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

  echo
  echo "[tick #${TICK}] exit=$RC  done at $(date '+%H:%M:%S')"
  echo "[loop] sleeping ${INTERVAL_SEC}s before next tick (Ctrl-C to stop)"
  sleep "$INTERVAL_SEC"
done
