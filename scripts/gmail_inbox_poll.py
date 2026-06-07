#!/usr/bin/env python3
"""Poll Gmail inbox for replies to assistant-sent mails; queue into task pool.

Strategy:
  1. IMAP fetch UNSEEN since last poll
  2. Identify replies to assistant-sent messages by:
     - Subject starts with "Re:" (case-insensitive)
     - OR In-Reply-To / References header matches a tracked sent Message-ID
     - OR From == owner email (yihao.lai@gmail.com) responding to our threads
  3. Extract reply body (strip quoted portion below "On ... wrote:" or "----- Original Message -----")
  4. Extract original assistant content (the quoted block) for context
  5. Append a new task to storage/next_tasks.json with task_type="email_reply"
  6. Mark message as Seen (\\Seen flag) so we don't reprocess
  7. Persist last UID to storage/ops/gmail_inbox_state.json

Run:
  uv run python scripts/gmail_inbox_poll.py [--dry-run] [--max N]

Cron: every 15 min via cron_gmail_poll.sh.
"""
from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "storage" / "ops" / "gmail_inbox_state.json"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
LOG_PATH = ROOT / "storage" / "logs" / "cron" / "gmail_poll.log"
TAIPEI = ZoneInfo("Asia/Taipei")

# Quoted-reply markers (Gmail / Apple Mail / Outlook common forms)
QUOTE_MARKERS = [
    re.compile(r"^On .+ wrote:\s*$", re.MULTILINE),
    re.compile(r"^在 .+寫道[：:]\s*$", re.MULTILINE),
    re.compile(r"^-----\s*Original Message\s*-----", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{20,}", re.MULTILINE),
    re.compile(r"^>{1,}", re.MULTILINE),
]

URGENCY_KEYWORDS_HIGH = ("緊急", "urgent", "asap", "立刻", "馬上", "現在")
URGENCY_KEYWORDS_MED = ("今天", "今日", "今晚", "稍後", "soon")


def _load_env() -> None:
    """Source repo .env so SMTP/IMAP creds are available."""
    for fname in (".env", ".env.local"):
        path = ROOT / fname
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_local() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{_now_local()}] {msg}\n"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(line, end="", file=sys.stderr)


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_uid": 0, "processed_message_ids": [], "last_poll_at": None}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Cap processed_message_ids to last 500 to avoid unbounded growth
    if len(state.get("processed_message_ids", [])) > 500:
        state["processed_message_ids"] = state["processed_message_ids"][-500:]
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_body(msg: Message) -> str:
    """Prefer text/plain, fall back to text/html stripped."""
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            plain = payload.decode(charset, errors="replace")

    body = plain or _html_to_text(html)
    return body.strip()


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return text


def _split_reply_and_quote(body: str) -> tuple[str, str]:
    """Return (user_reply, quoted_original). Quote everything from first marker onward."""
    earliest = len(body)
    for pat in QUOTE_MARKERS:
        m = pat.search(body)
        if m and m.start() < earliest:
            earliest = m.start()
    reply = body[:earliest].strip()
    quoted = body[earliest:].strip()
    return reply, quoted


VOLPRED_SUBJECT_MARKER = os.environ.get("VOLPRED_SUBJECT_MARKER", "[VolPred")


def _should_process(
    subject: str,
    sender: str,
    in_reply_to: str,
    references: str,
    owner_email: str,
    subject_marker: str | None = None,
) -> tuple[bool, str]:
    """Decide whether an incoming mail should be queued as email_reply task.

    Requires THREE conditions (all AND) for actionability:
      1. from_owner:        sender contains owner's email (anti-spoofing)
      2. is_reply:          Re:/Re：prefix OR In-Reply-To/References header
                            (genuine continuation, not new topic)
      3. is_volpred_thread: subject contains marker (default '[VolPred')
                            → ensures it's a reply to a system-sent mail,
                              not e.g. a friend's [Re: lunch?] forwarded chain
    """
    marker = subject_marker if subject_marker is not None else VOLPRED_SUBJECT_MARKER
    from_owner = bool(owner_email) and owner_email.lower() in (sender or "").lower()
    subj = subject or ""
    subj_low = subj.lower()
    is_reply = bool(
        (in_reply_to or "").strip()
        or (references or "").strip()
        or subj_low.startswith("re:")
        or subj_low.startswith("re：")
    )
    is_volpred_thread = bool(marker) and (marker.lower() in subj_low)

    if from_owner and is_reply and is_volpred_thread:
        return True, "from_owner_and_is_reply_and_volpred_thread"
    if not from_owner:
        return False, "not_from_owner"
    if not is_reply:
        return False, "from_owner_but_not_reply"
    return False, "from_owner_reply_but_not_volpred_thread"


def _detect_priority(text: str) -> int:
    low = text.lower()
    if any(k in low for k in URGENCY_KEYWORDS_HIGH):
        return 1
    if any(k in low for k in URGENCY_KEYWORDS_MED):
        return 2
    return 3


def _next_dispatch_eta() -> tuple[str, int]:
    """Return (台灣時間 HH:07 string, minutes_from_now). Dispatch fires at HH:07."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tw = datetime.now(ZoneInfo("Asia/Taipei"))
    target = tw.replace(minute=7, second=0, microsecond=0)
    if tw.minute >= 7:
        target = target + timedelta(hours=1)
    delta_min = int((target - tw).total_seconds() / 60)
    return target.strftime("%H:%M"), delta_min


def _send_ack_email(task: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Immediately send acknowledgment email after queueing the email_reply task.

    Per user 2026-05-25 directive: 收到 email 後立即回覆「已收到任務 + 決策（馬上做 / 推入任務池）
    + 類型 + 執行時間 + 完成後 email 回報」— 不等 dispatch tick。
    """
    if dry_run:
        return {"ok": True, "dry_run": True}
    try:
        # Lazy import to keep poll script lean
        import subprocess
        from pathlib import Path as _P

        eta_hhmm, eta_min = _next_dispatch_eta()
        priority = task.get("priority", 3)
        priority_label = {1: "P1 最高優先", 2: "P2 中高優先", 3: "P3 普通優先"}.get(priority, f"P{priority}")
        priority_note = ""
        if priority == 1:
            priority_note = "（**含緊急關鍵字，將排所有 task 之前**）"

        # ACK 邏輯：所有 email_reply 都走 dispatch（gmail-poll 無法 immediately
        # spawn Claude session）。但如果用戶問題能 0-cost 答（例如「現在狀態」
        # 類），dispatch 一輪內收尾；複雜任務可能跨多輪 tick。Ack 老實說
        # 「推入任務池」並標 ETA。
        body_md = f"""# 已收到你的回信

| 欄位 | 值 |
|---|---|
| Task ID | `{task.get('id')}` |
| 類型 | `email_reply` |
| Priority | **{priority_label}** {priority_note} |
| 主旨 | {task.get('email_subject', '')[:80]} |
| 收信時間 | {task.get('created_at', '')[:19].replace('T', ' ')} UTC |

## 決策

**已推入統一任務池** — `storage/next_tasks.json` 中 `task_type=email_reply`

## 執行時間

- **下次 Claude `hourly-dispatch` fire**：今天 {eta_hhmm}（台灣時間，約 {eta_min} 分鐘後）
- Claude 主線程會於該 tick 自動 claim + 分析 + 執行
- 若任務跨多 tick → 中間不會 spam；最後一次 tick 收尾發 close email

## 完成後通知

✅ 全部處理完成時會寄 **close email** 給你（同 thread 回覆）— 含完成項目 / commit hash / 對應 sub-task id

---

*Auto-sent by `gmail_inbox_poll.py` on queue insertion ({_P(__file__).name})*
"""
        # Use subprocess to invoke CLI (avoids needing volpred module on path here)
        cmd = [
            "/Users/yhlai0911/.local/bin/uv", "run", "volpred", "ops", "send-alert",
            "--level", "info",
            # [ACK] prefix to visually distinguish from close email (2026-05-26
            # user complaint email-11748: ack & close subjects identical → user
            # could not tell which was which in inbox)
            "--title", f"[ACK] Re: {task.get('email_subject', '(no subject)')[:115]}",
            "--force",  # bypass dedup — ack must always go out
        ]
        # Write body to temp file and pass via --body-md (avoids shell quoting issues)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
            tf.write(body_md)
            tmppath = tf.name
        cmd.extend(["--body-md", tmppath])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(ROOT))
        try:
            _P(tmppath).unlink()
        except Exception:
            pass
        if proc.returncode != 0:
            _log(f"  ack send FAILED for {task.get('id')}: {proc.stderr[-200:]}")
            return {"ok": False, "stderr": proc.stderr[-200:]}
        _log(f"  ack email sent for {task.get('id')} (ETA next dispatch {eta_hhmm} ~{eta_min}min)")
        return {"ok": True, "eta": eta_hhmm, "eta_minutes": eta_min}
    except Exception as exc:
        _log(f"  ack send EXCEPTION for {task.get('id')}: {exc!r}")
        return {"ok": False, "error": str(exc)}


def _send_fast_path_answer(task: dict[str, Any], answer_md: str, pattern_id: str, dry_run: bool) -> dict[str, Any]:
    """Send the fast-path answer email immediately (replaces ack + close)."""
    if dry_run:
        return {"ok": True, "dry_run": True}
    try:
        import subprocess
        import tempfile
        from pathlib import Path as _P

        # Append closure footer
        footer = f"""

---

| 元信息 | 值 |
|---|---|
| Task ID | `{task.get('id')}` |
| Fast-path pattern | `{pattern_id}` |
| 處理方式 | **inline Python heuristic（無需 hourly-dispatch）** |
| 從 reply 到回信延遲 | ≤15 min（gmail-poll 週期） + 立即答 |

*若你需要更深入的分析或執行其他動作，這個 fast-path 答完後就 close 案子了。再 reply 就會再開新 task。*
"""
        full_body = answer_md.rstrip() + footer

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
            tf.write(full_body)
            tmppath = tf.name

        cmd = [
            "/Users/yhlai0911/.local/bin/uv", "run", "volpred", "ops", "send-alert",
            "--level", "info",
            "--title", f"Re: {task.get('email_subject', '(no subject)')[:120]}",
            "--body-md", tmppath, "--force",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(ROOT))
        try:
            _P(tmppath).unlink()
        except Exception:
            pass
        if proc.returncode != 0:
            _log(f"  fast_path answer send FAILED: {proc.stderr[-200:]}")
            return {"ok": False, "stderr": proc.stderr[-200:]}
        _log(f"  fast_path answer sent for {task.get('id')} pattern={pattern_id}")
        return {"ok": True}
    except Exception as exc:
        _log(f"  fast_path answer EXCEPTION: {exc!r}")
        return {"ok": False, "error": str(exc)}


def _append_task(task: dict[str, Any], dry_run: bool) -> str:
    """Atomically append task to next_tasks.json (file lock + read-modify-write)."""
    if dry_run:
        return task["id"]
    import fcntl

    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]", encoding="utf-8")

    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError("next_tasks.json is not a list")
            data.append(task)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=2, ensure_ascii=False)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return task["id"]


def _build_task(uid: int, msg: Message, reply: str, quoted: str) -> dict[str, Any]:
    subject = _decode(msg.get("Subject"))
    sender = _decode(msg.get("From"))
    date_hdr = _decode(msg.get("Date"))
    message_id = (msg.get("Message-ID") or "").strip()

    title = f"[email_reply] {subject[:80]}" if subject else "[email_reply] (no subject)"
    priority = _detect_priority(reply)

    description = (
        f"Gmail UID: {uid}\n"
        f"Message-ID: {message_id}\n"
        f"From: {sender}\n"
        f"Date: {date_hdr}\n"
        f"Subject: {subject}\n\n"
        f"--- 用戶回信內容 ---\n{reply or '(empty)'}\n\n"
        f"--- 原始助理寄出內容（引用部分） ---\n{quoted[:4000] or '(no quote)'}\n"
    )

    return {
        "id": f"email-{uid}-{uuid.uuid4().hex[:6]}",
        "title": title,
        "description": description,
        "task_type": "email_reply",
        "priority": priority,
        "status": "pending",
        "tags": ["email_reply", "user_input"],
        "created_at": _now_iso(),
        "source": "gmail_inbox_poll",
        "email_uid": uid,
        "email_message_id": message_id,
        "email_subject": subject,
        "email_from": sender,
    }


def _normalize_subject(subject: str) -> str:
    """Strip leading Re:/Fwd: chains + collapse whitespace for thread matching."""
    s = (subject or "").strip()
    for _ in range(10):
        low = s.lower()
        if low.startswith("re:") or low.startswith("re："):
            s = s[3:].strip()
        elif low.startswith("fwd:") or low.startswith("fw:"):
            s = s.split(":", 1)[1].strip()
        else:
            break
    return " ".join(s.split())


def _existing_task_keys() -> tuple[set[str], set[str]]:
    """Read next_tasks.json and return (message_ids, normalized_subjects)
    already queued as email_reply tasks (any status)."""
    path = ROOT / "storage" / "next_tasks.json"
    if not path.exists():
        return set(), set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), set()
    if not isinstance(data, list):
        return set(), set()
    mids: set[str] = set()
    subs: set[str] = set()
    for t in data:
        if not isinstance(t, dict):
            continue
        if t.get("task_type") != "email_reply":
            continue
        mid = (t.get("email_message_id") or "").strip()
        if mid:
            mids.add(mid)
        subj_norm = _normalize_subject(t.get("email_subject") or t.get("title") or "")
        if subj_norm:
            subs.add(subj_norm)
    return mids, subs


def poll(max_messages: int = 20, dry_run: bool = False, since_days: int = 2) -> dict[str, Any]:
    _load_env()
    user = os.environ.get("SMTP_USERNAME")
    pwd = os.environ.get("SMTP_PASSWORD")
    if not user or not pwd:
        _log("ERROR: SMTP_USERNAME / SMTP_PASSWORD not set; skip poll")
        return {"ok": False, "reason": "no_creds"}

    imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))
    mailbox = os.environ.get("IMAP_MAILBOX", "INBOX")

    state = _load_state()
    processed_ids = set(state.get("processed_message_ids", []))

    # Subject + Message-ID dedup against next_tasks.json (canonical "已接單" check).
    # Means: same thread won't be queued twice even if user re-reads / Gmail un-Seens it.
    existing_mids, existing_subs = _existing_task_keys()

    queued: list[dict[str, Any]] = []
    skipped = 0

    try:
        M = imaplib.IMAP4_SSL(imap_host, imap_port)
        M.login(user, pwd)
        M.select(mailbox)

        # Search by date window (last N days) instead of UNSEEN — Gmail's auto-
        # mark-read on preview makes UNSEEN unreliable. Dedup against existing
        # next_tasks (by Message-ID + normalized subject) makes re-scan safe.
        from datetime import datetime, timedelta
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE "{since_date}")')
        if typ != "OK":
            _log(f"ERROR: IMAP search failed: {typ}")
            M.logout()
            return {"ok": False, "reason": "search_failed"}

        uids = data[0].split() if data and data[0] else []
        # Process newest-first so latest reply gets priority if duplicates
        uids = list(reversed(uids))
        _log(f"SINCE {since_date} count: {len(uids)} (cap={max_messages}, existing_email_tasks: mids={len(existing_mids)} subs={len(existing_subs)})")

        for raw_uid in uids[:max_messages]:
            uid = int(raw_uid)
            typ, msg_data = M.fetch(raw_uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                skipped += 1
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            message_id = (msg.get("Message-ID") or "").strip()
            subject = _decode(msg.get("Subject"))
            sender = _decode(msg.get("From"))
            in_reply_to = (msg.get("In-Reply-To") or "").strip()
            references = (msg.get("References") or "").strip()

            # Filter: only actionable if BOTH from owner AND looks like a reply
            decision, reason = _should_process(subject, sender, in_reply_to, references, user)
            if not decision:
                skipped += 1
                continue

            # 「是否已接單」dedup — 三層防護：
            # (1) next_tasks.json 已有同 Message-ID 的 email_reply task
            # (2) next_tasks.json 已有同 normalized subject 的 email_reply task（thread match）
            # (3) state file processed_message_ids（legacy fallback）
            if message_id and message_id in existing_mids:
                _log(f"  skip uid={uid} reason=already_queued_by_msgid subj={subject[:50]!r}")
                skipped += 1
                continue
            norm_subj = _normalize_subject(subject)
            if norm_subj and norm_subj in existing_subs:
                _log(f"  skip uid={uid} reason=already_queued_by_subject subj={subject[:50]!r}")
                skipped += 1
                continue
            if message_id and message_id in processed_ids:
                skipped += 1
                continue

            body = _extract_body(msg)
            reply, quoted = _split_reply_and_quote(body)

            if not reply.strip() and not quoted.strip():
                skipped += 1
                continue

            # FAST PATH: try heuristic Python answer before queuing.
            # If hit → answer email IS the response (no ack, no dispatch wait).
            # If miss → fall through to normal queue + ack flow.
            fp = None
            try:
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location("efp", ROOT / "scripts" / "email_fast_path.py")
                _efp = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_efp)
                fp = _efp.try_fast_path(reply, subject)
            except Exception as _e:
                _log(f"  fast_path import/call error: {_e!r}")
                fp = None

            task = _build_task(uid, msg, reply, quoted)

            if fp:
                # Fast-path hit — mark task already-resolved + send answer.
                task["status"] = "succeeded"
                task["fast_path_pattern"] = fp["pattern_id"]
                task["result"] = f"[fast_path:{fp['pattern_id']}] answered inline at queue time (no dispatch)"
                task["completed_at"] = _now_iso()
                task_id = _append_task(task, dry_run=dry_run)
                queued.append({"task_id": task_id, "uid": uid, "subject": subject, "fast_path": fp["pattern_id"]})
                _log(f"  fast_path HIT uid={uid} pattern={fp['pattern_id']} task_id={task_id}")
                # Send answer email (acts as ack + close in one shot)
                _send_fast_path_answer(task, fp["answer_md"], fp["pattern_id"], dry_run=dry_run)
            else:
                task_id = _append_task(task, dry_run=dry_run)
                queued.append({"task_id": task_id, "uid": uid, "subject": subject})
                _log(f"  queued uid={uid} task_id={task_id} subj={subject[:50]!r}")
                # Ack email — only for queued (non-fast-path) tasks
                ack_result = _send_ack_email(task, dry_run=dry_run)
                if not ack_result.get("ok"):
                    _log(f"  WARNING: ack failed but task still queued (will be processed at next dispatch)")

            # Update in-memory dedup sets so subsequent iterations within this
            # poll don't re-queue (e.g. user sent two replies on same thread)
            if message_id:
                processed_ids.add(message_id)
                existing_mids.add(message_id)
            if norm_subj:
                existing_subs.add(norm_subj)

            # Do NOT set \Seen — user may want to read in Gmail too; we now
            # rely on next_tasks.json dedup, not IMAP flag.

        M.close()
        M.logout()
    except imaplib.IMAP4.error as exc:
        _log(f"IMAP error: {exc}")
        return {"ok": False, "reason": "imap_error", "error": str(exc)}
    except Exception as exc:
        _log(f"Unexpected error: {exc!r}")
        return {"ok": False, "reason": "exception", "error": str(exc)}

    state["last_uid"] = max([state.get("last_uid", 0)] + [q["uid"] for q in queued])
    state["processed_message_ids"] = sorted(processed_ids)
    state["last_poll_at"] = _now_iso()
    if not dry_run:
        _save_state(state)

    _log(f"poll done: queued={len(queued)} skipped={skipped} dry_run={dry_run}")
    return {"ok": True, "queued": queued, "skipped": skipped, "dry_run": dry_run}


_DISPATCH_WRAPPER = "/Users/yhlai0911/.volpred/bin/cron_hourly_dispatch.sh"
_TRIGGER_MARKER = ROOT / "storage" / "ops" / ".last_email_immediate_dispatch"
_TRIGGER_MIN_GAP_SEC = 240  # don't immediate-fire more than once per 4 min


def _trigger_immediate_dispatch(queued: list[dict[str, Any]]) -> dict[str, Any]:
    """On a NEW owner reply, fire the dispatch wrapper NOW (its PHASE-0 handles
    email_reply first) instead of waiting up to ~1h for the next hourly tick.
    User directive 2026-06-07「收到信馬上啟動讀信」. Guarded so it never collides
    with a running dispatch or double-fires.
    """
    import subprocess, time
    # only for genuine queued tasks that still need handling (fast-path already answered)
    pending = [q for q in queued if not q.get("fast_path")]
    if not pending:
        return {"fired": False, "reason": "no_pending_reply"}
    # guard 1: a dispatch already running → it will pick up PHASE-0 email itself
    try:
        r = subprocess.run(["pgrep", "-f", "cron_hourly_dispatch.sh"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return {"fired": False, "reason": "dispatch_already_running"}
    except Exception:
        pass
    # guard 2: min-gap since last immediate fire
    try:
        if _TRIGGER_MARKER.exists():
            age = time.time() - _TRIGGER_MARKER.stat().st_mtime
            if age < _TRIGGER_MIN_GAP_SEC:
                return {"fired": False, "reason": f"min_gap_{int(age)}s"}
    except Exception:
        pass
    if not Path(_DISPATCH_WRAPPER).exists():
        return {"fired": False, "reason": "wrapper_missing"}
    try:
        _TRIGGER_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _TRIGGER_MARKER.write_text(_now_iso(), encoding="utf-8")
        subprocess.Popen(["/bin/bash", _DISPATCH_WRAPPER],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        _log(f"  IMMEDIATE DISPATCH fired for {len(pending)} new reply(ies) "
             f"(tasks: {[q['task_id'] for q in pending]})")
        return {"fired": True, "count": len(pending)}
    except Exception as exc:
        _log(f"  immediate dispatch FAILED: {exc!r}")
        return {"fired": False, "reason": f"error:{exc}"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Do not write task / mark seen")
    p.add_argument("--max", type=int, default=20, help="Max messages per poll")
    p.add_argument("--no-immediate-dispatch", action="store_true",
                   help="Skip firing dispatch on new reply (queue only)")
    args = p.parse_args()

    result = poll(max_messages=args.max, dry_run=args.dry_run)
    # 收到信馬上啟動讀信：new owner reply → fire dispatch now (PHASE-0 email).
    if result.get("ok") and not args.dry_run and not args.no_immediate_dispatch:
        result["immediate_dispatch"] = _trigger_immediate_dispatch(result.get("queued", []))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
