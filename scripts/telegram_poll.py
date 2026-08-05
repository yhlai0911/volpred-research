#!/usr/bin/env python3
"""Telegram long-poll daemon — boss two-way channel (2026-07-02).

Mirrors gmail_inbox_poll.py's contract but with ~instant latency:
  1. Long-poll getUpdates (timeout 25s) with persisted offset.
  2. First contact (/start or any message when chat_id unknown): capture
     chat_id into storage/ops/telegram_state.json + send welcome (handshake —
     this is also the end-to-end send-path verification).
  3. Every boss message → append task_type="telegram_reply" (priority P1,
     source="telegram") to storage/next_tasks.json — same pending-queue
     contract as email_reply.  The responder later sends the real reply;
     normal admission does not emit a redundant "received" ack.
  4. All raw messages archived to storage/ops/telegram_inbox.jsonl.

Run modes:
  --once     one getUpdates pass (cron/test friendly)
  --daemon   loop forever (LaunchAgent KeepAlive)

Anti-stacking: transport lives in src/volpred/ops/telegram.py.  This script
owns the inbound loop and handshake only; alert disposition routing does not
mirror through Telegram.  It follows the established gmail-poll pattern
(state file / admission diagnostics / next_tasks append).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
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
from volpred.ops.next_tasks import append_task_record  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.canonical_write import guard_canonical_write  # noqa: E402

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
INBOX = ROOT / "storage" / "ops" / "telegram_inbox.jsonl"

# An update is consumed from Telegram the moment the offset advances, and
# Telegram will never hand it back. So the offset may only mean "we have it",
# never "we processed it" -- anything that fails after the offset moves has to
# survive somewhere local or it is gone.
#
# 2026-08-05: it was gone. Two owner messages (updates 351935633/351935634,
# 09:41 and 09:42 Taipei) raised `cannot import name
# 'normalize_task_type_value' from 'volpred.ops.next_tasks'` inside
# _handle_update. The loop logged one line, advanced the offset anyway, and
# moved on. The owner asked hours later whether Telegram still accepted tasks;
# nothing else would ever have said otherwise. The import works from every
# static entry point and could not be reproduced, which is the point: the fix
# cannot depend on knowing why a handler failed. Poison message, ImportError,
# full disk, Supabase down -- the message has to outlive all of them.
#
# So: still advance the offset (a poison update must not wedge the loop -- that
# part of the old behaviour was right), but first write the raw update here, and
# retry it at the top of every pass. A transient failure self-heals within one
# poll interval. A persistent one escalates instead of accumulating in silence.
DEADLETTER = ROOT / "storage" / "ops" / "telegram_failed_updates.jsonl"
DEADLETTER_MAX_ATTEMPTS = 5
HEARTBEAT_LOG_INTERVAL_SECONDS = 3600
TELEGRAM_POLL_LOG = Path(
    os.environ.get(
        "VOLPRED_TELEGRAM_POLL_LOG",
        str(Path.home() / ".volpred" / "logs" / "telegram_poll.log"),
    )
)


def _log(msg: str) -> None:
    """Append one record through a fresh inode lookup.

    The old shell-level ``exec >> telegram_poll.log`` kept one descriptor for
    the daemon's entire lifetime. Atomic log rotation replaced the pathname
    but the process kept writing the unlinked inode, making live logs appear
    frozen. Opening with ``O_APPEND`` per record follows the current pathname
    after every rotation while keeping each line a single append.
    """
    record = (
        f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] "
        f"{msg}\n"
    ).encode("utf-8", errors="replace")
    path = TELEGRAM_POLL_LOG
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError(
                    f"telegram poll log is not a regular file: {path}"
                )
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(record)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("telegram poll log append made no progress")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)
    except Exception as exc:  # noqa: BLE001 - daemon must retain a visible fallback
        print(
            f"[telegram_poll] log append failed path={path} "
            f"error={type(exc).__name__}: {exc}; record={msg}",
            file=sys.stderr,
            flush=True,
        )


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
    """Append a P1 telegram_reply task to the pending queue (gmail-poll contract).

    WS-A1b: routed through the canonical append helper. The old tmp+replace
    wrote WITHOUT LOCK_EX (a concurrent claim/dispatch write could be clobbered
    wholesale) and with indent=1 (canonical is 2 → every append rewrote the
    whole file as a diff, polluting PHASE-Z authorship). append_task_record
    keeps the ``telegram-<msg_id>`` id contract (reply-right guard) and the
    idempotent daemon-restart replay, now checked under the same lock.
    """
    task_id = f"telegram-{msg_id}"
    ctx_block = (
        f"\n老闆是在**回覆這則訊息**（指代「這個/那個」時以此為準）：\n---\n{reply_context}\n---\n"
        if reply_context else ""
    )
    record = {
        "id": task_id,
        "task_type": "telegram_reply",
        "priority": 1,
        "source": "telegram",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": f"回覆老闆 Telegram 訊息（msg {msg_id}）",
        "description": (
            f"老闆（{sender}）經 Telegram 傳來訊息，全文：\n---\n{text}\n---\n{ctx_block}"
            "處理規則：與 email_reply 同級（user-assigned P1）。**先 claim 本任務再開工**"
            "（task_pool_claim.py claim + start；claim 被拒 = 另一個 session 在處理，立刻停手不得回覆）。"
            "完成實事後**必須用 Telegram 回覆**，且一律帶 reply-right guard：\n"
            f"`uv run volpred ops telegram-send --reply-to-task telegram-{msg_id} --text \"...\"`\n"
            "（guard 會在任務已被別的 session 完成時拒發，防雙回覆。）回覆要短、直接、口語 — "
            "這是即時聊天不是報告；長內容給結論 + 一行說明細節在哪。回覆送出後才 complete 本任務。"
        ),
    }
    # append_task_record 內建的 _request_urgent_fire 對 telegram_reply 是 no-op：
    # 它有專屬 owner（下面 _spawn_responder / _maybe_retry_stuck），is_urgent()
    # 對 DEDICATED_OWNER_TASK_TYPES 一律回 False。理由完整寫在
    # next_tasks._request_urgent_fire 的 docstring，由 test_urgent_task_lane.py
    # 的 dedicated-owner 測試釘住。
    append_task_record(record, path=NEXT_TASKS, if_exists="skip")
    return task_id


def _mirror_to_org(text: str, msg_id: int, task_id: str) -> bool:
    """Put the boss's instruction in front of the coordinator, now.

    The responder answers the chat; it does not run the platform. Before this
    existed, an instruction like "研究部先停，把 draft 池補起來" was answered in
    the chat and then evaporated: the org's only coordinator never learned the
    boss had spoken, and any organizational consequence waited for whichever
    30-minute tick happened to notice something downstream. 急件直達 is a
    standing rule (`feedback_urgent_bypasses_scheduler_by_design`), and a
    coordinator that learns about the boss's orders on a half-hour delay is a
    scheduler in the path of an urgent message.

    Detached on purpose: waking the coordinator can mean prompting a live pane
    or spawning a headless round, and the poll loop must not sit behind either.
    Ordering is what makes that safe — intake writes the inbox item before it
    wakes anyone, so the instruction is durable even if the wake never lands
    (the next tick then collects it). The two halves stay disjoint: the chat
    reply belongs to ``task_id`` and its reply-right guard, which the inbox item
    states explicitly so the coordinator does not answer a second time.
    """
    import subprocess

    tool = ROOT / "scripts" / "org" / "org_intake.py"
    try:
        subprocess.Popen(
            [sys.executable, str(tool), "--boss-message", text,
             "--channel", "telegram", "--msg-id", str(msg_id),
             "--canonical-task-id", task_id],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log(f"org intake spawned (msg {msg_id} → manager inbox + immediate wake)")
        return True
    except Exception as exc:  # noqa: BLE001 — the org must never break the reply path
        warn(
            "telegram_org_intake",
            "org intake spawn failed; manager will only see this at the next tick",
            err=str(exc), msg_id=msg_id, task_id=task_id,
        )
        return False


def _load_deadletter() -> list[dict]:
    if not DEADLETTER.is_file():
        return []
    rows: list[dict] = []
    for line in DEADLETTER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            # Never drop a parked message just because a neighbouring line is
            # corrupt -- dropping is the whole failure this file exists to stop.
            warn("telegram_deadletter", "unparsable row kept verbatim", error=str(exc))
            rows.append({"_raw": line, "attempts": 0})
    return rows


def _save_deadletter(rows: list[dict]) -> None:
    guard_canonical_write(DEADLETTER)
    DEADLETTER.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    tmp = DEADLETTER.with_suffix(".jsonl.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(DEADLETTER)


def _record_failed_update(update: dict, exc: Exception) -> None:
    """Park an update that failed to become a task, so a retry can find it."""
    update_id = update.get("update_id")
    rows = _load_deadletter()
    for row in rows:
        if row.get("update", {}).get("update_id") == update_id:
            row["attempts"] = int(row.get("attempts") or 0) + 1
            row["last_error"] = f"{type(exc).__name__}: {exc}"
            break
    else:
        rows.append({
            "update": update,
            "attempts": 1,
            "first_failed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": f"{type(exc).__name__}: {exc}",
        })
    _save_deadletter(rows)
    _log(f"update {update_id} parked for retry: {exc}")
    warn(
        "telegram_deadletter",
        "update failed to become a task; parked for retry",
        update_id=update_id,
        error=f"{type(exc).__name__}: {exc}",
        parked=len(rows),
    )


def _drain_failed_updates() -> int:
    """Retry parked updates. Returns how many finally became tasks.

    Runs before each poll so a transient failure costs one poll interval, not
    the message. `_append_task` keys on `telegram-<message_id>`, so replaying an
    update that partly succeeded cannot create a second task.
    """
    rows = _load_deadletter()
    if not rows:
        return 0
    kept: list[dict] = []
    recovered = 0
    mutated = False
    for row in rows:
        update = row.get("update")
        if not isinstance(update, dict):
            kept.append(row)  # unparsable; keep for a human, never discard
            continue
        try:
            _handle_update(update)
            recovered += 1
            _log(f"update {update.get('update_id')} recovered from deadletter")
        except Exception as exc:  # noqa: BLE001 — retry must not kill the daemon
            row["attempts"] = int(row.get("attempts") or 0) + 1
            row["last_error"] = f"{type(exc).__name__}: {exc}"
            kept.append(row)
            mutated = True
            if row["attempts"] >= DEADLETTER_MAX_ATTEMPTS:
                # Escalate rather than let it sit. The row stays parked: an
                # owner message is never deleted because retrying it is hard.
                warn(
                    "telegram_deadletter_stuck",
                    "owner message still not queued after repeated retries",
                    update_id=update.get("update_id"),
                    attempts=row["attempts"],
                    error=row["last_error"],
                    text=str((update.get("message") or {}).get("text") or "")[:200],
                )
    # Persist whenever anything changed at all, not only when a row left the
    # queue. The first version only saved on recovery, so a row that kept
    # failing had its attempt counter incremented in memory and thrown away --
    # the escalation threshold could never be reached and a permanently stuck
    # owner message would have retried in silence forever.
    if recovered or mutated or len(kept) != len(rows):
        _save_deadletter(kept)
    return recovered


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
            "• 這裡提供互動回覆、逐程序進度與有 delivery receipt 的指定事件通知；"
            "告警與週期摘要走 email\n"
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
            f"收到（已排 P1：{task_id}）。即時處理器暫時忙碌，兩分鐘內自動重派，不用等排程。",
            disable_notification=True,
        )
    _mirror_to_org(text, msg.get("message_id", 0), task_id)


def _pick_model(text: str) -> str:
    """TG responder model 選擇。

    Owner directive 2026-07-05：所有 subagent 一律用 opus（4.8）。responder 是
    headless 派出的 subagent，故 default 固定 opus，不再依訊息輕重在 sonnet↔opus
    二選（原 heuristic 已退役）。唯一例外：owner 在訊息裡**顯式**指名 model
    （fable / sonnet / haiku）— 那是 owner 明確要求，尊重覆寫（2026-07-02 boss：
    「在 telegram 要求該次派工用 fable 可行嗎」→ 可；fable headless 已實測）。
    """
    tl = text.strip().lower()
    explicit = (("fable", "claude-fable-5"), ("opus", "claude-opus-5"),
                ("sonnet", "claude-sonnet-5"), ("haiku", "claude-haiku-4-5-20251001"))
    for kw, model in explicit:
        if kw in tl:
            return model
    return "claude-opus-5"  # all-opus default（2026-07-28 generation upgrade）


def _spawn_responder(model: str = "claude-opus-5") -> bool:
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
    # Before asking Telegram for anything new, finish what we already owe.
    _drain_failed_updates()
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
            # Park it before the offset moves. The log line alone is what let
            # two owner messages disappear on 2026-08-05.
            _record_failed_update(u, exc)
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
