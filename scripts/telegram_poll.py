#!/usr/bin/env python3
"""Telegram long-poll daemon — boss two-way channel (2026-07-02).

Mirrors gmail_inbox_poll.py's contract but with ~instant latency:
  1. Long-poll getUpdates (timeout 25s) with persisted offset.
  2. First contact (/start or any message when chat_id unknown): capture
     chat_id into storage/ops/telegram_state.json + send welcome (handshake —
     this is also the end-to-end send-path verification).
  3. Every boss message → append task_type="telegram_reply" (priority P1,
     source="telegram") to storage/next_tasks.json — same pending-queue
     contract as email_reply — and send an immediate ack with the ETA.
  4. All raw messages archived to storage/ops/telegram_inbox.jsonl.

Run modes:
  --once     one getUpdates pass (cron/test friendly)
  --daemon   loop forever (LaunchAgent KeepAlive)

Anti-stacking: transport lives in src/volpred/ops/telegram.py (shared with the
send_alert mirror); this script only adds the inbound loop, following the
established gmail-poll pattern (state file / ack / next_tasks append).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.telegram import (  # noqa: E402
    api_call,
    get_chat_id,
    load_state,
    load_token,
    save_state,
    send_telegram,
)
from volpred.ops.next_tasks import normalize_task_priorities  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
INBOX = ROOT / "storage" / "ops" / "telegram_inbox.jsonl"
HEARTBEAT_LOG_INTERVAL_SECONDS = 3600


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def _parse_state_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        # Only genuine corruption reaches here (absent/empty caught above); a
        # bad self-written timestamp → None (caller self-heals) but must be
        # visible per no-silent-fallback rule.
        warn("telegram_poll_state", "unparseable state datetime", raw=raw[:40], err=str(exc))
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_poll_success() -> None:
    """Persist a successful getUpdates heartbeat without clobbering state."""
    now = datetime.now(timezone.utc)
    state = load_state()
    state["last_success_at"] = now.isoformat()

    last_log_at = _parse_state_datetime(state.get("last_heartbeat_log_at"))
    if (
        last_log_at is None
        or (now - last_log_at).total_seconds() >= HEARTBEAT_LOG_INTERVAL_SECONDS
    ):
        _log(f"poll ok offset={state.get('update_offset')}")
        state["last_heartbeat_log_at"] = now.isoformat()

    save_state(state)


def _archive(update: dict) -> None:
    guard_canonical_write(INBOX)
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(update, ensure_ascii=False) + "\n")


def _append_task(text: str, msg_id: int, sender: str, reply_context: str = "") -> str:
    """Append a P1 telegram_reply task to the pending queue (gmail-poll contract)."""
    tasks = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    task_id = f"telegram-{msg_id}"
    if any(t.get("id") == task_id for t in tasks):
        return task_id  # idempotent on daemon restart replay
    ctx_block = (
        f"\n老闆是在**回覆這則訊息**（指代「這個/那個」時以此為準）：\n---\n{reply_context}\n---\n"
        if reply_context else ""
    )
    tasks.append({
        "id": task_id,
        "task_type": "telegram_reply",
        "priority": 1,
        "source": "telegram",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": f"回覆老闆 Telegram 訊息（msg {msg_id}）",
        "description": (
            f"老闆（{sender}）經 Telegram 傳來訊息，全文：\n---\n{text}\n---\n{ctx_block}"
            "處理規則：與 email_reply 同級（user-assigned P1）。完成實事後**必須用 "
            "Telegram 回覆**（`uv run volpred ops telegram-send --text \"...\"` 或 "
            "python: volpred.ops.telegram.send_telegram）。回覆要短、直接、口語 — "
            "這是即時聊天不是報告；長內容給結論 + 一行說明細節在哪。"
        ),
    })
    normalize_task_priorities(tasks)
    guard_canonical_write(NEXT_TASKS)
    tmp = NEXT_TASKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(NEXT_TASKS)
    return task_id


def _handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    text = (msg.get("text") or "").strip()
    if not chat.get("id") or not text:
        return
    _archive(update)
    state = load_state()
    first_contact = not state.get("chat_id")
    if first_contact:
        state["chat_id"] = chat["id"]
        state["chat_first_name"] = (msg.get("from") or {}).get("first_name")
        state["handshake_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        _log(f"handshake: captured chat_id={chat['id']}")
        send_telegram(
            "✅ VolPred 營運經理連線完成。這個通道雙向可用：\n"
            "• 我會把 alert / 重大進度即時鏡射到這裡（email 仍是完整版）\n"
            "• 你傳的任何訊息會直接進任務池（P1 user-assigned），我處理完在這裡回你\n"
            "隨時吩咐。"
        )
    if text == "/start":
        return  # handshake handled above; /start itself is not a task
    sender = (msg.get("from") or {}).get("first_name") or "boss"
    reply_ctx = ((msg.get("reply_to_message") or {}).get("text") or "")[:800]
    task_id = _append_task(text, msg.get("message_id", 0), sender, reply_context=reply_ctx)
    _log(f"task queued: {task_id} ({text[:40]!r})")
    # 2026-07-10 (boss msg 349「為什麼持續出現這個訊息」)：正常路徑不再發
    # 「收到（已排 P1）處理中」ack — responder 稍後會回真正答覆，這句只是
    # 每則訊息都重複一次的噪音。只有 responder 派不出去（fail-open）時才回
    # 一次「已排入、稍後處理」，讓 boss 知道訊息沒掉。
    if not _spawn_responder(model=_pick_model(text)):
        send_telegram(
            f"收到（已排 P1：{task_id}）。即時處理器暫時忙碌，稍後由排程接手回你。",
            disable_notification=True,
        )


def _pick_model(text: str) -> str:
    """TG responder model 選擇。

    Owner directive 2026-07-05：所有 subagent 一律用 opus（4.8）。responder 是
    headless 派出的 subagent，故 default 固定 opus，不再依訊息輕重在 sonnet↔opus
    二選（原 heuristic 已退役）。唯一例外：owner 在訊息裡**顯式**指名 model
    （fable / sonnet / haiku）— 那是 owner 明確要求，尊重覆寫（2026-07-02 boss：
    「在 telegram 要求該次派工用 fable 可行嗎」→ 可；fable headless 已實測）。
    """
    tl = text.strip().lower()
    explicit = (("fable", "claude-fable-5"), ("opus", "claude-opus-4-8"),
                ("sonnet", "claude-sonnet-5"), ("haiku", "claude-haiku-4-5-20251001"))
    for kw, model in explicit:
        if kw in tl:
            return model
    return "claude-opus-4-8"  # all-opus default（2026-07-05 directive）


def _spawn_responder(model: str = "claude-opus-4-8") -> bool:
    """即時 spawn headless responder 處理剛進池的 telegram_reply 任務。

    單飛鎖在 responder script 內（同時多訊息 → 一個 responder drain 全部）。
    回傳 True=spawn 成功、False=**連 spawn 都失敗**（caller 據此發 fallback ack）。

    ⚠️ True 只代表 Popen 成功，**不代表 responder 會成功回覆** —— 它之後 exit=1
    （額度耗盡）或 FATAL（缺依賴）我們在這裡看不到。訊息是否真的被回，由
    `_retry_stuck_replies()` 以佇列殘留量測，不靠這個回傳值。
    """
    import os
    import subprocess
    script = ROOT / "scripts" / "telegram_responder.sh"
    env = dict(os.environ)
    env["TELEGRAM_RESPONDER_MODEL"] = model
    try:
        subprocess.Popen(
            ["bash", str(script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=env,
        )
        _log(f"responder spawned (model={model})")
        return True
    except Exception as exc:  # noqa: BLE001 — 訊息已入池，retry loop 會接手
        _log(f"responder spawn failed (retry loop 會接手): {exc}")
        return False  # silent-ok: 上一行 _log 已留 trace；訊息已入池，_retry_stuck_replies 負責重試


# responder spawn 後 2 分鐘內應該已 claim 到任務；仍 pending = 它沒接住。
RETRY_AGE_THRESHOLD_SEC = 120
# 額度耗盡時每 ~25s 一次 poll pass，不能每 pass 都重燒一次 opus。
RETRY_MIN_INTERVAL_SEC = 300
_last_retry_spawn: datetime | None = None


def _retry_stuck_replies() -> None:
    """老闆的訊息躺在佇列沒被回 → 重新 spawn responder（2026-07-16）。

    responder 是純 event-driven：只在**新訊息進來**時被 spawn。它一旦失敗
    （Claude 額度耗盡 exit=1 / 缺依賴 FATAL / crash），沒有任何東西會重試 ——
    訊息就一直躺著，直到老闆**再傳一則**才被下一個 responder 的 drain loop
    順便清掉。額度恢復了也不會自動重跑。

    原本的程式碼註解宣稱「hourly dispatch 兜底，最壞 ~1h」，**那個兜底不存在**：
    `.claude/rules/task-routing.md` 明確把 telegram_reply 標為「不進一般
    hourly/Codex claim」。老闆 2026-07-16 21:46 的訊息就是這樣卡住的 —— 撞
    session limit 三輪 exit=1，額度 22:20 恢復後仍無人重試，41 分鐘後由老闆
    自己追問才被發現。

    poll daemon 本來就在 while-loop 裡，是天然的 retry driver；把重試收編進來，
    不新增排程層（anti-stacking）。responder 自帶單飛鎖，重複 spawn 安全。
    """
    global _last_retry_spawn
    now = datetime.now(timezone.utc)
    if (
        _last_retry_spawn is not None
        and (now - _last_retry_spawn).total_seconds() < RETRY_MIN_INTERVAL_SEC
    ):
        return

    tasks_path = ROOT / "storage" / "next_tasks.json"
    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — daemon 不能因佇列讀取失敗而死
        warn(
            "telegram_poll_retry",
            "next_tasks read failed",
            path=str(tasks_path),
            err=f"{type(exc).__name__}: {exc}",
        )
        return
    if not isinstance(tasks, list):
        warn(
            "telegram_poll_retry",
            "next_tasks not a list",
            got=type(tasks).__name__,
        )
        return

    stuck = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("task_type") != "telegram_reply" or task.get("status") != "pending":
            continue
        raw_created = task.get("created_at")
        if not isinstance(raw_created, str):
            continue
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except ValueError:
            warn(
                "telegram_poll_retry",
                "unparseable created_at on reply task",
                task_id=str(task.get("id")),
                raw=raw_created[:40],
            )
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).total_seconds() >= RETRY_AGE_THRESHOLD_SEC:
            stuck.append(task.get("id"))

    if not stuck:
        return
    _last_retry_spawn = now
    _log(f"retry: {len(stuck)} unanswered reply task(s) {stuck[:3]} — respawning responder")
    _spawn_responder()


def poll_pass(timeout: int = 25) -> int:
    """One getUpdates pass; returns number of updates handled."""
    state = load_state()
    offset = state.get("update_offset")
    params: dict = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = api_call("getUpdates", params, timeout=timeout + 10)
    if not resp.get("ok"):
        _log(f"getUpdates failed: {resp.get('description')}")
        return 0
    updates = resp.get("result") or []
    for u in updates:
        try:
            _handle_update(u)
        except Exception as exc:  # noqa: BLE001 — one bad update must not kill the loop
            _log(f"update {u.get('update_id')} failed: {exc}")
        state = load_state()
        state["update_offset"] = u["update_id"] + 1
        save_state(state)
    _record_poll_success()
    return len(updates)


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--daemon", action="store_true")
    args = ap.parse_args()
    if not load_token():
        _log("no TELEGRAM_BOT_TOKEN — exiting")
        return 1
    if args.once:
        n = poll_pass(timeout=3)
        _log(f"once: handled {n} update(s); chat_id={get_chat_id() or 'not yet captured'}")
        return 0
    _log("daemon start")
    while True:
        try:
            poll_pass()
            # responder 失敗（額度 / 缺依賴）不會自己重試 —— poll loop 兼任
            # retry driver。放在 poll_pass 之後：新訊息先入池，再統一檢查殘留。
            _retry_stuck_replies()
        except Exception as exc:  # noqa: BLE001 — daemon must survive transient errors
            _log(f"poll_pass error: {exc}")
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
