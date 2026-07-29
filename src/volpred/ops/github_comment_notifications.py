"""Durable GitHub comment ingress with per-channel delivery receipts.

GitHub is the source of truth for issue and pull-request comments.  Mailbox
labels, Trash state, and browser sessions are deliberately outside this
contract: a comment is considered owner-visible only after both the canonical
email route and the manager Telegram route have durable receipts here.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_REPO = "yhlai0911/volpred-research"
DEFAULT_STATE_PATH = (
    Path.home()
    / ".volpred"
    / "run"
    / "github-comment-notifications"
    / "state.json"
)


@dataclass(frozen=True)
class GitHubComment:
    source: str
    comment_id: int
    number: int
    author: str
    created_at: str
    url: str
    body: str

    @property
    def delivery_key(self) -> str:
        return f"{self.source}:{self.comment_id}"


@dataclass(frozen=True)
class Notification:
    idempotency_key: str
    title: str
    body: str


FetchComments = Callable[[datetime], list[GitHubComment]]
DeliverNotification = Callable[[Notification], dict[str, Any]]
GitHubRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_github_comment_notifications(
    *,
    repo: str = DEFAULT_REPO,
    state_path: Path = DEFAULT_STATE_PATH,
    storage_dir: str = "storage",
    now: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    fetch_comments: FetchComments | None = None,
    deliver_email: DeliverNotification | None = None,
    deliver_telegram: DeliverNotification | None = None,
) -> dict[str, Any]:
    """Run one production reconciliation using existing owned transports."""
    return reconcile_github_comments(
        fetch_comments=fetch_comments
        or (lambda since: fetch_github_comments(repo=repo, since=since)),
        deliver_email=deliver_email
        or (lambda notification: _deliver_email(notification, storage_dir=storage_dir)),
        deliver_telegram=deliver_telegram
        or (
            lambda notification: _deliver_telegram(
                notification,
                storage_dir=storage_dir,
            )
        ),
        state_path=state_path,
        now=now,
        lookback_days=lookback_days,
    )


def fetch_github_comments(
    *,
    repo: str,
    since: datetime,
    runner: GitHubRunner | None = None,
) -> list[GitHubComment]:
    """Fetch issue conversation and pull-review comments through authenticated gh."""
    normalized_repo = repo.strip()
    if normalized_repo.count("/") != 1:
        raise ValueError("repo must use owner/name form")
    since = _aware(since)
    execute = runner or _run_gh
    comments: list[GitHubComment] = []
    sources = (
        ("issue_comment", "issues/comments", "issue_url"),
        ("pull_review_comment", "pulls/comments", "pull_request_url"),
    )
    for source, resource, number_url_key in sources:
        endpoint = f"repos/{normalized_repo}/{resource}"
        command = [
            _gh_binary(),
            "api",
            "-X",
            "GET",
            "--paginate",
            "--slurp",
            endpoint,
            "-f",
            f"since={since.isoformat()}",
            "-f",
            "per_page=100",
        ]
        completed = execute(command)
        if completed.returncode != 0:
            raise RuntimeError(
                f"GitHub comment fetch failed for {resource}: "
                f"{(completed.stderr or '')[:300]}"
            )
        for item in _flatten_pages(completed.stdout):
            number = _number_from_url(item.get(number_url_key))
            user = item.get("user")
            author = user.get("login") if isinstance(user, dict) else None
            created_at = _aware(
                datetime.fromisoformat(
                    str(item.get("created_at") or "")
                )
            ).isoformat()
            comments.append(
                GitHubComment(
                    source=source,
                    comment_id=int(item["id"]),
                    number=number,
                    author=str(author or "unknown"),
                    created_at=created_at,
                    url=str(item["html_url"]),
                    body=str(item.get("body") or ""),
                )
            )
    unique = {
        comment.delivery_key: comment
        for comment in comments
    }
    return _sort_comments(list(unique.values()))


def reconcile_github_comments(
    *,
    fetch_comments: FetchComments,
    deliver_email: DeliverNotification,
    deliver_telegram: DeliverNotification,
    state_path: Path,
    now: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Deliver pending GitHub comments without crossing a failed comment.

    The first successful run emits one bounded backfill digest.  Later runs
    process comments oldest-first and advance the cursor only after both
    channel receipts are durable.
    """
    observed_at = _aware(now or datetime.now(UTC))
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _load_state(state_path)
        if state.get("backfill_completed_at") is None:
            return _reconcile_backfill(
                state=state,
                state_path=state_path,
                now=observed_at,
                lookback_days=lookback_days,
                fetch_comments=fetch_comments,
                deliver_email=deliver_email,
                deliver_telegram=deliver_telegram,
            )

        comments = _new_comments(
            fetch_comments(_cursor_since(state)),
            cursor=state.get("cursor"),
        )
        if not comments:
            return {
                "schema_version": SCHEMA_VERSION,
                "mode": "incremental",
                "comment_count": 0,
                "delivery_status": "idle",
                "cursor": state.get("cursor"),
            }
        return _reconcile_incremental(
            state=state,
            state_path=state_path,
            comments=comments,
            now=observed_at,
            deliver_email=deliver_email,
            deliver_telegram=deliver_telegram,
        )


def _reconcile_backfill(
    *,
    state: dict[str, Any],
    state_path: Path,
    now: datetime,
    lookback_days: int,
    fetch_comments: FetchComments,
    deliver_email: DeliverNotification,
    deliver_telegram: DeliverNotification,
) -> dict[str, Any]:
    pending = state.get("pending_backfill")
    if not isinstance(pending, dict):
        since = now - timedelta(days=lookback_days)
        comments = _sort_comments(fetch_comments(since))
        notification = _backfill_notification(
            comments,
            since=since,
            now=now,
        )
        pending = {
            "notification": asdict(notification),
            "comments": [asdict(comment) for comment in comments],
            "email": {"status": "pending"},
            "telegram": {"status": "pending"},
        }
        state["pending_backfill"] = pending
        _save_state(state_path, state)
    else:
        comments = [
            GitHubComment(**item)
            for item in pending.get("comments", [])
            if isinstance(item, dict)
        ]
        notification = Notification(**pending["notification"])

    _attempt_channel(
        state=state,
        state_path=state_path,
        delivery=pending,
        channel="email",
        notification=notification,
        sender=deliver_email,
        now=now,
    )
    _attempt_channel(
        state=state,
        state_path=state_path,
        delivery=pending,
        channel="telegram",
        notification=notification,
        sender=deliver_telegram,
        now=now,
    )
    delivered = _channels_delivered(pending)
    delivery_status = _delivery_status(pending)
    if delivered:
        state["backfill_completed_at"] = now.isoformat()
        state["cursor"] = _cursor_for(comments)
        state["pending_backfill"] = None
        _save_state(state_path, state)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "backfill",
        "comment_count": len(comments),
        "delivery_status": delivery_status,
        **(
            {"blocked_reason": "delivery_unknown"}
            if delivery_status == "blocked"
            else {}
        ),
        "cursor": state.get("cursor"),
        "channels": {
            channel: dict(pending[channel])
            for channel in ("email", "telegram")
        },
    }


def _attempt_channel(
    *,
    state: dict[str, Any],
    state_path: Path,
    delivery: dict[str, Any],
    channel: str,
    notification: Notification,
    sender: DeliverNotification,
    now: datetime,
) -> None:
    channel_state = delivery.setdefault(channel, {"status": "pending"})
    status = channel_state.get("status")
    if status == "delivered":
        return
    if status == "in_flight":
        channel_state.update(
            status="delivery_unknown",
            error="process ended while external delivery was in flight",
            observed_at=now.isoformat(),
        )
        _save_state(state_path, state)
        return
    if status == "delivery_unknown":
        return
    channel_state.update(
        status="in_flight",
        attempted_at=now.isoformat(),
        error=None,
    )
    _save_state(state_path, state)
    try:
        receipt = sender(notification)
    except Exception as exc:  # noqa: BLE001 - transport failure is a retryable receipt
        receipt = {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    if bool(receipt.get("sent")):
        channel_state.update(
            status="delivered",
            delivered_at=now.isoformat(),
            receipt=receipt,
        )
    else:
        channel_state.update(
            status="failed",
            failed_at=now.isoformat(),
            error=str(receipt.get("error") or receipt.get("reason") or "not sent"),
            receipt=receipt,
        )
    _save_state(state_path, state)


def _reconcile_incremental(
    *,
    state: dict[str, Any],
    state_path: Path,
    comments: list[GitHubComment],
    now: datetime,
    deliver_email: DeliverNotification,
    deliver_telegram: DeliverNotification,
) -> dict[str, Any]:
    deliveries = state.setdefault("deliveries", {})
    examined = 0
    latest_channels: dict[str, Any] = {}
    for comment in comments:
        examined += 1
        delivery = deliveries.get(comment.delivery_key)
        if not isinstance(delivery, dict):
            notification = _comment_notification(comment)
            delivery = {
                "comment": asdict(comment),
                "notification": asdict(notification),
                "email": {"status": "pending"},
                "telegram": {"status": "pending"},
            }
            deliveries[comment.delivery_key] = delivery
            _save_state(state_path, state)
        else:
            notification = Notification(**delivery["notification"])

        _attempt_channel(
            state=state,
            state_path=state_path,
            delivery=delivery,
            channel="email",
            notification=notification,
            sender=deliver_email,
            now=now,
        )
        _attempt_channel(
            state=state,
            state_path=state_path,
            delivery=delivery,
            channel="telegram",
            notification=notification,
            sender=deliver_telegram,
            now=now,
        )
        latest_channels = {
            channel: dict(delivery[channel])
            for channel in ("email", "telegram")
        }
        if not _channels_delivered(delivery):
            delivery_status = _delivery_status(delivery)
            return {
                "schema_version": SCHEMA_VERSION,
                "mode": "incremental",
                "comment_count": examined,
                "delivery_status": delivery_status,
                **(
                    {"blocked_reason": "delivery_unknown"}
                    if delivery_status == "blocked"
                    else {}
                ),
                "blocked_comment": comment.delivery_key,
                "cursor": state.get("cursor"),
                "channels": latest_channels,
            }
        state["cursor"] = _cursor_for([comment])
        _save_state(state_path, state)

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "incremental",
        "comment_count": examined,
        "delivery_status": "delivered",
        "cursor": state.get("cursor"),
        "channels": latest_channels,
    }


def _channels_delivered(delivery: dict[str, Any]) -> bool:
    return all(
        isinstance(delivery.get(channel), dict)
        and delivery[channel].get("status") == "delivered"
        for channel in ("email", "telegram")
    )


def _delivery_status(delivery: dict[str, Any]) -> str:
    if _channels_delivered(delivery):
        return "delivered"
    if any(
        isinstance(delivery.get(channel), dict)
        and delivery[channel].get("status") == "delivery_unknown"
        for channel in ("email", "telegram")
    ):
        return "blocked"
    return "pending"


def _backfill_notification(
    comments: list[GitHubComment],
    *,
    since: datetime,
    now: datetime,
) -> Notification:
    title = f"[新架構派發][GitHub] 近 7 日留言摘要（{len(comments)} 則）"
    lines = [
        "GitHub 是留言通知的 canonical source；信箱資料夾不影響本摘要。",
        f"範圍：{since.isoformat()} ～ {now.isoformat()}",
        "",
    ]
    for comment in comments:
        summary = _summary(comment.body)
        lines.append(
            f"- {comment.created_at} [#{comment.number}]({comment.url}) "
            f"{comment.author}: {summary}"
        )
    if not comments:
        lines.append("- 此期間沒有留言。")
    return Notification(
        idempotency_key=f"github-comments:backfill:{since.date().isoformat()}",
        title=title,
        body="\n".join(lines),
    )


def _comment_notification(comment: GitHubComment) -> Notification:
    title = f"[新架構派發][GitHub #{comment.number}] 新留言"
    body = "\n".join(
        [
            f"- 類型：{comment.source}",
            f"- 作者：{comment.author}",
            f"- 時間：{comment.created_at}",
            f"- 連結：{comment.url}",
            "",
            "## 摘要",
            _summary(comment.body),
        ]
    )
    return Notification(
        idempotency_key=f"github-comment:{comment.delivery_key}",
        title=title,
        body=body,
    )


def _summary(body: str, *, limit: int = 180) -> str:
    first = next(
        (line.strip() for line in str(body).splitlines() if line.strip()),
        "（無文字內容）",
    )
    return first if len(first) <= limit else f"{first[: limit - 1]}…"


def _new_comments(
    comments: list[GitHubComment],
    *,
    cursor: object,
) -> list[GitHubComment]:
    ordered = _sort_comments(comments)
    if not isinstance(cursor, dict):
        return ordered
    cursor_key = (
        str(cursor.get("created_at") or ""),
        str(cursor.get("source") or ""),
        int(cursor.get("comment_id") or 0),
    )
    return [
        comment
        for comment in ordered
        if _comment_key(comment) > cursor_key
    ]


def _sort_comments(comments: list[GitHubComment]) -> list[GitHubComment]:
    for comment in comments:
        _aware(datetime.fromisoformat(comment.created_at))
        if comment.comment_id < 1 or comment.number < 1:
            raise ValueError("GitHub comment ids and numbers must be positive")
    return sorted(comments, key=_comment_key)


def _comment_key(comment: GitHubComment) -> tuple[str, str, int]:
    return (comment.created_at, comment.source, comment.comment_id)


def _cursor_for(comments: list[GitHubComment]) -> dict[str, Any] | None:
    if not comments:
        return None
    latest = max(comments, key=_comment_key)
    return {
        "created_at": latest.created_at,
        "source": latest.source,
        "comment_id": latest.comment_id,
    }


def _cursor_since(state: dict[str, Any]) -> datetime:
    cursor = state.get("cursor")
    if not isinstance(cursor, dict) or not cursor.get("created_at"):
        completed = state.get("backfill_completed_at")
        return _aware(datetime.fromisoformat(str(completed)))
    return _aware(datetime.fromisoformat(str(cursor["created_at"]))) - timedelta(seconds=1)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _flatten_pages(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise TypeError("GitHub paginated response must be a list")
    if payload and all(isinstance(page, list) for page in payload):
        items = [
            item
            for page in payload
            for item in page
        ]
    else:
        items = payload
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("GitHub comment response contains a non-object item")
    return items


def _number_from_url(value: object) -> int:
    number = int(str(value or "").rstrip("/").rsplit("/", 1)[-1])
    if number < 1:
        raise ValueError("GitHub issue or pull number must be positive")
    return number


def _gh_binary() -> str:
    configured = os.environ.get("GH_BIN", "").strip()
    if configured:
        return configured
    discovered = shutil.which("gh")
    if discovered:
        return discovered
    fixed = Path("/opt/homebrew/bin/gh")
    if fixed.is_file() and os.access(fixed, os.X_OK):
        return str(fixed)
    raise RuntimeError("GitHub CLI is unavailable")


def _run_gh(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _deliver_email(
    notification: Notification,
    *,
    storage_dir: str,
) -> dict[str, Any]:
    from volpred.ops.alerts import ALERT_RECIPIENT, _dispatch_alert_email

    return _dispatch_alert_email(
        level="info",
        title=notification.title,
        body=notification.body,
        recipient=ALERT_RECIPIENT,
        storage_dir=storage_dir,
        delivery_key=f"{notification.idempotency_key}:email",
    )


def _deliver_telegram(
    notification: Notification,
    *,
    storage_dir: str,
) -> dict[str, Any]:
    from volpred.ops.telegram import send_telegram

    return send_telegram(
        f"ℹ️ {notification.title}\n\n{notification.body}",
        storage_dir=storage_dir,
        disable_notification=True,
    )


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "backfill_completed_at": None,
            "cursor": None,
            "pending_backfill": None,
            "deliveries": {},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("GitHub comment notification state schema is invalid")
    return payload


def _save_state(path: Path, state: dict[str, Any]) -> None:
    encoded = (
        json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    descriptor, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass  # silent-ok: atomic replace consumes the temporary file
