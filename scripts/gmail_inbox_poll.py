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


def _detect_priority(text: str) -> int:
    low = text.lower()
    if any(k in low for k in URGENCY_KEYWORDS_HIGH):
        return 1
    if any(k in low for k in URGENCY_KEYWORDS_MED):
        return 2
    return 3


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


def poll(max_messages: int = 20, dry_run: bool = False) -> dict[str, Any]:
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

    queued: list[dict[str, Any]] = []
    skipped = 0

    try:
        M = imaplib.IMAP4_SSL(imap_host, imap_port)
        M.login(user, pwd)
        M.select(mailbox)

        # Search unseen mails. Optionally restrict to From == owner for replies.
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK":
            _log(f"ERROR: IMAP search failed: {typ}")
            M.logout()
            return {"ok": False, "reason": "search_failed"}

        uids = data[0].split() if data and data[0] else []
        _log(f"UNSEEN count: {len(uids)} (cap={max_messages})")

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

            # Dedup by Message-ID across polls
            if message_id and message_id in processed_ids:
                skipped += 1
                continue

            # Filter: only treat as actionable if it looks like a reply OR is from owner
            is_reply = bool(
                in_reply_to
                or references
                or subject.lower().startswith("re:")
                or subject.lower().startswith("re：")
            )
            from_owner = user.lower() in sender.lower()

            if not (is_reply or from_owner):
                # Not a reply and not from owner — leave UNSEEN, skip
                skipped += 1
                continue

            body = _extract_body(msg)
            reply, quoted = _split_reply_and_quote(body)

            if not reply.strip() and not quoted.strip():
                skipped += 1
                continue

            task = _build_task(uid, msg, reply, quoted)
            task_id = _append_task(task, dry_run=dry_run)
            queued.append({"task_id": task_id, "uid": uid, "subject": subject})

            if message_id:
                processed_ids.add(message_id)

            # Mark as Seen (skip in dry-run)
            if not dry_run:
                M.store(raw_uid, "+FLAGS", "\\Seen")

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Do not write task / mark seen")
    p.add_argument("--max", type=int, default=20, help="Max messages per poll")
    args = p.parse_args()

    result = poll(max_messages=args.max, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
