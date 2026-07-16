#!/bin/bash
# telegram_responder.sh — 即時回應老闆 Telegram 訊息的 headless responder
#
# 由 telegram_poll.py 在收到訊息時 spawn（單飛鎖防並行）。複用 hourly-dispatch
# 的 headless claude 模式，但 scope 只有一件事：drain pending telegram_reply
# 任務 → 完成實事 → 用 telegram-send 回覆 → complete。15 分鐘 watchdog。
#
# Anti-stacking：不是新排程層 — 是 telegram_poll（既有 daemon）的事件驅動子程序，
# 與 hourly-dispatch 共用 task pool 契約（claim/complete），先到先做、互不重工。
set -u
exec >> /Users/yhlai0911/.volpred/logs/telegram_responder.log 2>&1
REPO_ROOT=/Users/yhlai0911/volpred-research
cd "$REPO_ROOT" || exit 1

CLAUDE_BIN="${CLAUDE_BIN:-/Users/yhlai0911/.local/bin/claude}"
LOCK_DIR="/Users/yhlai0911/.volpred/run/telegram_responder.lock"
RESPONDER_WORKDIR="/Users/yhlai0911/.volpred/run/telegram_responder_workdir"
AUTO_MEMORY_DIR="/Users/yhlai0911/.claude/projects/-Users-yhlai0911-volpred-research/memory"
CAP_SEC=900  # 15 min hard cap — TG 是即時聊天，答不完的部分留 hourly 接手
# Model 政策（config/models.json single source of truth）：這是 boss-facing 通道，
# 回答品質優先於 token — 與 hourly-dispatch 同款 opus primary；owner 若要降速換快，
# 改 TELEGRAM_RESPONDER_MODEL env 或此 default。
RESPONDER_MODEL="${TELEGRAM_RESPONDER_MODEL:-claude-opus-4-8}"
# 2026-07-05: effort now actually wired via `--effort` (was inert everywhere).
# boss-facing 通道，品質優先 → high 底線；owner 可用 TELEGRAM_RESPONDER_EFFORT env
# 調 low|medium|high|xhigh|max（CLI fail-opens 亂值 → 警告後用 default，安全）。
RESPONDER_EFFORT="${TELEGRAM_RESPONDER_EFFORT:-high}"

mkdir -p "$(dirname "$LOCK_DIR")" "$RESPONDER_WORKDIR"
chmod 700 "$RESPONDER_WORKDIR"
RESPONDER_REAL="$(cd "$RESPONDER_WORKDIR" && pwd -P)" || exit 1
REPO_REAL="$(cd "$REPO_ROOT" && pwd -P)" || exit 1
case "$RESPONDER_REAL" in
    "$REPO_REAL"|"$REPO_REAL"/*)
        echo "[FATAL] responder scratch resolves inside canonical repo: $RESPONDER_REAL"
        exit 1 ;;
esac
if /usr/bin/git -C "$RESPONDER_REAL" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[FATAL] responder scratch belongs to a Git working tree: $RESPONDER_REAL"
    exit 1
fi
if [ ! -r "$AUTO_MEMORY_DIR/MEMORY.md" ]; then
    echo "[FATAL] canonical auto-memory index missing: $AUTO_MEMORY_DIR/MEMORY.md"
    exit 1
fi
# /usr/bin/python3 (macOS system, stdlib-only) — 不用 brew jq：brew 二進位會隨
# upgrade/uninstall 消失，launchd 下無 PATH fallback 就 FATAL（2026-07-16 事故）。
if ! RESPONDER_SETTINGS_JSON=$(
    /usr/bin/python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
cfg["autoMemoryDirectory"] = sys.argv[2]
json.dump(cfg, sys.stdout, ensure_ascii=False, separators=(",", ":"))
' "$REPO_ROOT/.claude/settings.json" "$AUTO_MEMORY_DIR"
); then
    echo "[FATAL] cannot bind responder settings to canonical auto-memory"
    exit 1
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    LOCK_PID=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[$(date '+%F %T')] responder already running (pid $LOCK_PID) — 它會 drain 新任務，skip"
        exit 0
    fi
    echo "[$(date '+%F %T')] stale lock (pid ${LOCK_PID:-none} dead) — 接管"
    rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR" || exit 0
fi
echo $$ > "$LOCK_DIR/pid"
cleanup() { rm -rf "$LOCK_DIR"; }
trap cleanup EXIT INT TERM

echo "=== telegram responder start $(date '+%F %T') ==="

PROMPT='你是 VolPred 平台的 Telegram 即時回應者。唯一任務：處理老闆經 Telegram 傳來的待辦訊息，然後結束。

流程（嚴格照做）：
0. launcher cwd 是 repo 外的隔離目錄，但 CLI 的 `autoMemoryDirectory` 已綁到 canonical `/Users/yhlai0911/.claude/projects/-Users-yhlai0911-volpred-research/memory/`；先讀 repo 的 AGENTS.md，再使用內建 auto-memory（`MEMORY.md` 索引、按需讀單筆）。若本次是「記住：…」類長期指示，用內建 memory 工作法寫入（一檔一事實 + `MEMORY.md` pointer）。禁止呼叫已廢棄的 `telegram_memory.py`，也禁止建立 scratch/channel 專屬平行記憶。
1. 從 canonical root 讀 storage/next_tasks.json，找出全部 status=="pending" 且 task_type=="telegram_reply" 的任務（可能多筆，全部處理）。沒有 → 直接結束，不做別的事。
2. 逐筆用 canonical 絕對入口執行 task_pool_claim.py claim/complete（`uv --project /Users/yhlai0911/volpred-research run python /Users/yhlai0911/volpred-research/scripts/task_pool_claim.py ...`）→ 查詢/診斷可直接完成；任何 repo 程式、文件、Git/index/ref 修改一律不在 responder 做，改用正式 task-pool writer建立後續任務交 hourly dispatch（禁止直接 append JSON），並回覆老闆「已排入任務池」→ 用 `uv --project /Users/yhlai0911/volpred-research run volpred ops telegram-send --text "..."` 回覆老闆。
3. 回覆風格：短、直接、口語 — 這是即時聊天。結論先講；細節一行帶過或說在哪。禁止長報告。
4. 研究誠實原則適用：數字必須真查真算，不確定就說不確定。時間戳用 `TZ=Asia/Taipei date`。
5. 全部 drain 完就結束。不進 ops loop、不派 agent、不碰 feed/paper、不執行任何 git mutation。15 分鐘內收尾。'

pending_count() {
    (cd "$REPO_ROOT" && /opt/homebrew/bin/uv run --no-sync python -c "
import json
tasks = json.load(open('storage/next_tasks.json'))
print(sum(1 for t in tasks if t.get('task_type')=='telegram_reply' and t.get('status')=='pending'))") 2>/dev/null || echo 0
}

run_claude_pass() {
    # watchdog：CAP_SEC 後殺 responder
    (
        cd "$RESPONDER_WORKDIR" || exit 1
        "$CLAUDE_BIN" -p --dangerously-skip-permissions \
            --effort "$RESPONDER_EFFORT" --model "$RESPONDER_MODEL" \
            --add-dir "$REPO_ROOT" --add-dir "$AUTO_MEMORY_DIR" \
            --settings "$RESPONDER_SETTINGS_JSON" \
            "$PROMPT" 2>&1 &
        CPID=$!
        (
            sleep "$CAP_SEC"
            if kill -0 "$CPID" 2>/dev/null; then
                echo "[WATCHDOG] cap ${CAP_SEC}s reached — killing responder $CPID"
                kill -TERM "$CPID" 2>/dev/null; sleep 5; kill -KILL "$CPID" 2>/dev/null
            fi
        ) &
        WPID=$!
        wait "$CPID"; RC=$?
        kill "$WPID" 2>/dev/null
        exit "$RC"
    )
}

# Drain loop（2026-07-02 race fix：responder 跑的期間進來的新訊息會被單飛鎖 skip，
# 原版收尾就走人 → 新任務卡到下則訊息才被撿。改為收尾前回頭看佇列，有 pending
# 就再跑一輪；上限 3 輪防無限迴圈，剩的留 hourly 兜底）。
RC=0
for ROUND in 1 2 3; do
    run_claude_pass; RC=$?
    LEFT=$(pending_count)
    echo "[round $ROUND] exit=$RC, pending 剩 $LEFT"
    [ "$LEFT" = "0" ] && break
done
echo "=== telegram responder end $(date '+%F %T') (exit=$RC) ==="
exit "$RC"
