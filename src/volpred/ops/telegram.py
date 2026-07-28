"""Telegram transport for boss two-way interaction (2026-07-02 boss request).

Design (anti-stacking): this is a TRANSPORT under the existing alert/ops
messaging layer, not a new alert system — `send_alert` mirrors to Telegram
when configured; the poll daemon (scripts/telegram_poll.py) converts incoming
boss messages into next_tasks entries exactly like gmail_inbox_poll does for
email replies.

Config:
- TELEGRAM_BOT_TOKEN  — .env / env var (bot @Volpred_manager_bot)
- chat_id             — auto-captured on first /start by the poll daemon into
                        storage/ops/telegram_state.json (env TELEGRAM_CHAT_ID
                        overrides if set)

All failures are fail-open with a diagnostics trace (a broken Telegram mirror
must never break email alerts or a publish flow).
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from volpred.canonical_write import guard_canonical_write

API_BASE = "https://api.telegram.org"
MAX_MSG_CHARS = 4096  # Telegram sendMessage hard limit

_STATE_REL = Path("storage") / "ops" / "telegram_state.json"


def _warn(msg: str, **ctx: Any) -> None:
    try:
        from volpred.ops.diagnostics import warn

        warn("telegram", msg, **ctx)
    except Exception:  # noqa: BLE001 — diagnostics must remain fail-open
        print(f"  [telegram] {msg} {ctx}")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_token() -> str | None:
    """TELEGRAM_BOT_TOKEN from env, falling back to project .env."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    env_path = _project_root() / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except FileNotFoundError:
        pass  # silent-ok: .env is an optional fallback; primary token source is the env var
    except OSError as e:
        _warn("load_token .env read failed", path=str(env_path), err=str(e))
    return None


def state_path(storage_dir: str | Path = "storage") -> Path:
    root = Path(storage_dir)
    if not root.is_absolute():
        root = _project_root() / root
    return root / "ops" / "telegram_state.json"


def load_state(storage_dir: str | Path = "storage") -> dict[str, Any]:
    p = state_path(storage_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}  # silent-ok: state absent before first /start is the normal initial condition
    except (OSError, ValueError) as e:
        _warn("load_state failed", path=str(p), err=str(e))
        return {}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_state(state: dict[str, Any], storage_dir: str | Path = "storage") -> None:
    p = state_path(storage_dir)
    guard_canonical_write(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{p.name}.",
        suffix=".tmp",
        dir=p.parent,
    )
    tmp = Path(tmp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(state, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, p)
        _fsync_directory(p.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        tmp.unlink(missing_ok=True)


def get_chat_id(storage_dir: str | Path = "storage") -> str | None:
    env_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_id:
        return env_id
    cid = load_state(storage_dir).get("chat_id")
    return str(cid) if cid else None


def api_call(method: str, params: dict[str, Any] | None = None,
             *, token: str | None = None, timeout: int = 35) -> dict[str, Any]:
    """POST to Bot API; returns decoded JSON (ok=False dict on any failure)."""
    token = token or load_token()
    if not token:
        return {"ok": False, "description": "no_token"}
    url = f"{API_BASE}/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — transport fail-open by design
        _warn("api_call failed", method=method, err=str(exc)[:200])
        return {"ok": False, "description": str(exc)[:200]}


def _chunks(text: str, limit: int = MAX_MSG_CHARS) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    out: list[str] = []
    while text:
        cut = text.rfind("\n", 0, limit) if len(text) > limit else len(text)
        if cut <= 0:
            cut = min(limit, len(text))
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out


def send_telegram(text: str, *, chat_id: str | None = None,
                  storage_dir: str | Path = "storage",
                  disable_notification: bool = False) -> dict[str, Any]:
    """Send text (auto-chunked at 4096 chars) to the boss chat.

    Returns {"sent": bool, "reason"/"message_ids": ...}. Never raises.
    """
    chat_id = chat_id or get_chat_id(storage_dir)
    if not chat_id:
        return {"sent": False, "reason": "no_chat_id (boss 尚未對 bot /start)"}
    ids: list[int] = []
    for part in _chunks(text):
        resp = api_call("sendMessage", {
            "chat_id": chat_id,
            "text": part,
            "disable_notification": "true" if disable_notification else "false",
        })
        if not resp.get("ok"):
            return {"sent": bool(ids), "reason": resp.get("description", "send failed"),
                    "message_ids": ids}
        ids.append((resp.get("result") or {}).get("message_id"))
    return {"sent": bool(ids), "message_ids": ids}
