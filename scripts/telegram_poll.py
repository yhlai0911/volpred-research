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

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
INBOX = ROOT / "storage" / "ops" / "telegram_inbox.jsonl"


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def _archive(update: dict) -> None:
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(update, ensure_ascii=False) + "\n")


def _append_task(text: str, msg_id: int, sender: str) -> str:
    """Append a P1 telegram_reply task to the pending queue (gmail-poll contract)."""
    tasks = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    task_id = f"telegram-{msg_id}"
    if any(t.get("id") == task_id for t in tasks):
        return task_id  # idempotent on daemon restart replay
    tasks.append({
        "id": task_id,
        "task_type": "telegram_reply",
        "priority": "P1",
        "source": "telegram",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": f"回覆老闆 Telegram 訊息（msg {msg_id}）",
        "description": (
            f"老闆（{sender}）經 Telegram 傳來訊息，全文：\n---\n{text}\n---\n"
            "處理規則：與 email_reply 同級（user-assigned P1）。完成實事後**必須用 "
            "Telegram 回覆**（`uv run volpred ops telegram-send --text \"...\"` 或 "
            "python: volpred.ops.telegram.send_telegram）。回覆要短、直接、口語 — "
            "這是即時聊天不是報告；長內容給結論 + 一行說明細節在哪。"
        ),
    })
    tmp = NEXT_TASKS.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
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
    task_id = _append_task(text, msg.get("message_id", 0), sender)
    _log(f"task queued: {task_id} ({text[:40]!r})")
    send_telegram(f"收到（已排 P1：{task_id}）。處理中，完成回報。", disable_notification=True)
    _spawn_responder()


def _spawn_responder() -> None:
    """即時 spawn headless responder 處理剛進池的 telegram_reply 任務。

    單飛鎖在 responder script 內（同時多訊息 → 一個 responder drain 全部）。
    Fail-open：spawn 失敗不影響訊息入池（hourly dispatch 兜底，最壞 ~1h）。
    """
    import subprocess
    script = ROOT / "scripts" / "telegram_responder.sh"
    try:
        subprocess.Popen(
            ["bash", str(script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log("responder spawned")
    except Exception as exc:  # noqa: BLE001 — hourly dispatch 兜底
        _log(f"responder spawn failed (hourly 兜底): {exc}")


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
        except Exception as exc:  # noqa: BLE001 — daemon must survive transient errors
            _log(f"poll_pass error: {exc}")
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
