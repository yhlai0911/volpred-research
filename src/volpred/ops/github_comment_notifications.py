"""Durable GitHub comment ingress with per-issue delivery receipts.

GitHub is the source of truth for issue and pull-request comments.  Mailbox
labels, Trash state, and browser sessions are deliberately outside this
contract. Incremental comments are durably buffered by Issue/PR for fifteen
minutes, then delivered as one email digest. Telegram remains owned by the
interactive/progress pipeline instead of mirroring every GitHub comment.
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
from typing import Any, Iterable

SCHEMA_VERSION = 3
LEGACY_SCHEMA_VERSION = 2
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_REPO = "yhlai0911/volpred-research"
COMMENT_SOURCES = ("issue_comment", "pull_review_comment")
TELEGRAM_MAX_MESSAGE_CHARS = 4096
COMMENT_BATCH_WINDOW = timedelta(minutes=15)
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
    subject_kind: str = "issue"

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
ResolveRepair = Callable[[GitHubComment], dict[str, Any]]


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
    self_authors: Iterable[str] | None = None,
    resolve_repair: ResolveRepair | None = None,
) -> dict[str, Any]:
    """Run one production reconciliation using existing owned transports.

    Production callers default self-authorship to the repository owner.  Tests
    and library callers can pass an explicit empty iterable to preserve every
    comment as an owner-visible event.
    """
    authors = (
        default_self_authors(repo)
        if self_authors is None
        else _normalize_authors(self_authors)
    )
    repair_resolver = resolve_repair
    if repair_resolver is None:
        from volpred.ops.github_comment_repair import resolve_github_comment_repair

        repair_resolver = lambda comment: resolve_github_comment_repair(  # noqa: E731
            comment, storage_dir=storage_dir
        )
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
        self_authors=authors,
        resolve_repair=repair_resolver,
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
            html_url = str(item["html_url"])
            subject_kind = (
                "pull_request"
                if source == "pull_review_comment" or "/pull/" in html_url
                else "issue"
            )
            comments.append(
                GitHubComment(
                    source=source,
                    comment_id=int(item["id"]),
                    number=number,
                    author=str(author or "unknown"),
                    created_at=created_at,
                    url=html_url,
                    body=str(item.get("body") or ""),
                    subject_kind=subject_kind,
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
    self_authors: Iterable[str] = (),
    resolve_repair: ResolveRepair | None = None,
) -> dict[str, Any]:
    """Durably ingest GitHub comments and reconcile their owner notification.

    The first successful run emits one bounded backfill digest.  Later runs
    stage each complete comment into a per-thread batch before advancing its
    source cursor. A batch is owner-visible only after its email receipt is
    durable; an indeterminate external attempt remains blocked rather than
    being replayed.
    """
    observed_at = _aware(now or datetime.now(UTC))
    normalized_self_authors = _normalize_authors(self_authors)
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state, migrated = _load_state(state_path)
        if migrated:
            _save_state(state_path, state)
        if state.get("backfill_completed_at") is None:
            return _reconcile_backfill(
                state=state,
                state_path=state_path,
                now=observed_at,
                lookback_days=lookback_days,
                fetch_comments=fetch_comments,
                deliver_email=deliver_email,
                deliver_telegram=deliver_telegram,
                self_authors=normalized_self_authors,
            )

        comments = _new_comments(
            fetch_comments(_cursor_since(state)),
            cursors=state.get("cursors"),
        )
        comments, ignored_comments = _partition_self_authored(
            comments, normalized_self_authors
        )
        ignored_count = _record_ignored_self_authored(
            state, ignored_comments
        )
        repair_results = _resolve_repairs(comments, resolve_repair)
        if not comments and not state.get("pending_batches"):
            if ignored_count:
                _save_state(state_path, state)
            return {
                "schema_version": SCHEMA_VERSION,
                "mode": "incremental",
                "comment_count": 0,
                "ignored_self_authored_count": ignored_count,
                "repair_results": repair_results,
                "delivery_status": "idle",
                "pending_batch_count": 0,
                "cursor": _latest_cursor(state),
                "cursors": state.get("cursors"),
                "receipt_count": _receipt_count(state),
            }
        return _reconcile_incremental(
            state=state,
            state_path=state_path,
            comments=comments,
            now=observed_at,
            deliver_email=deliver_email,
            deliver_telegram=deliver_telegram,
            ignored_count=ignored_count,
            repair_results=repair_results,
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
    self_authors: frozenset[str],
) -> dict[str, Any]:
    pending = state.get("pending_backfill")
    if not isinstance(pending, dict):
        since = now - timedelta(days=lookback_days)
        all_comments = _sort_comments(fetch_comments(since))
        comments, ignored_comments = _partition_self_authored(
            all_comments, self_authors
        )
        ignored_count = _record_ignored_self_authored(state, ignored_comments)
        if not comments:
            state["backfill_completed_at"] = now.isoformat()
            state["cursors"] = _merge_cursors(
                state.get("cursors"), _cursors_for(all_comments, baseline=now)
            )
            state["pending_backfill"] = None
            _save_state(state_path, state)
            return {
                "schema_version": SCHEMA_VERSION,
                "mode": "backfill",
                "comment_count": 0,
                "ignored_self_authored_count": ignored_count,
                "delivery_status": "idle",
                "cursor": _latest_cursor(state),
                "cursors": state.get("cursors"),
                "receipt_count": _receipt_count(state),
                "channels": {},
            }
        notification = _backfill_notification(
            comments,
            since=since,
            now=now,
        )
        pending = {
            "notification": asdict(notification),
            "comments": [asdict(comment) for comment in comments],
            "ignored_self_authored_count": ignored_count,
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
        receipt_keys: dict[str, str] = {}
        receipts = state.setdefault("receipts", {})
        for channel in ("email", "telegram"):
            receipt_key = f"{notification.idempotency_key}:{channel}"
            receipts[receipt_key] = dict(pending[channel])
            receipt_keys[channel] = receipt_key
        deliveries = state.setdefault("deliveries", {})
        for comment in comments:
            deliveries[comment.delivery_key] = {
                "comment": asdict(comment),
                "status": "delivered",
                "delivered_via": notification.idempotency_key,
                "receipt_keys": dict(receipt_keys),
            }
        state["backfill_completed_at"] = now.isoformat()
        state["cursors"] = _merge_cursors(
            state.get("cursors"), _cursors_for(comments, baseline=now)
        )
        state["pending_backfill"] = None
        _save_state(state_path, state)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "backfill",
        "comment_count": len(comments),
        "ignored_self_authored_count": int(
            pending.get("ignored_self_authored_count") or 0
        ),
        "delivery_status": delivery_status,
        **(
            {"blocked_reason": "delivery_unknown"}
            if delivery_status == "blocked"
            else {}
        ),
        "cursor": _latest_cursor(state),
        "cursors": state.get("cursors"),
        "receipt_count": _receipt_count(state),
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
    if _receipt_is_complete(receipt):
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
    ignored_count: int = 0,
    repair_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stage comments durably, then deliver due per-issue email batches.

    ``deliver_telegram`` remains in the public signature for the one-time
    backfill path and caller compatibility. Incremental batches deliberately do
    not call it: Telegram's single owner is the interactive/progress pipeline.
    """
    del deliver_telegram
    deliveries = state.setdefault("deliveries", {})
    batches = state.setdefault("pending_batches", {})
    if not isinstance(batches, dict):
        raise TypeError("pending_batches must be an object")
    repair_by_key = {
        str(item.get("comment_key")): item
        for item in (repair_results or [])
        if isinstance(item, dict) and item.get("comment_key")
    }

    staged = 0
    for comment in comments:
        delivery = deliveries.get(comment.delivery_key)
        if isinstance(delivery, dict):
            # A crash after the durable stage but before cursor persistence is
            # harmless: replay sees the comment identity here and only repairs
            # the cursor. It never appends the comment twice.
            _advance_source_cursor(state, comment)
            continue
        repair = repair_by_key.get(comment.delivery_key)
        if repair is not None and repair.get("action") != "notify_only":
            # An explicit repair request is an execution ingress, not an owner
            # notification.  Keep the durable receipt/cursor, then let the
            # verified completion path send the only owner-visible message.
            deliveries[comment.delivery_key] = {
                "comment": asdict(comment),
                "status": "repair_pending",
                "repair": repair,
            }
            _advance_source_cursor(state, comment)
            continue
        batch = _open_subject_batch(batches, comment, now=now)
        if batch is None:
            batch_id = (
                f"{comment.subject_kind}:{comment.number}:"
                f"{comment.delivery_key}"
            )
            batch = {
                "batch_id": batch_id,
                "subject_kind": comment.subject_kind,
                "number": comment.number,
                "opened_at": now.isoformat(),
                "due_at": (now + COMMENT_BATCH_WINDOW).isoformat(),
                "comments": [],
                "email": {"status": "pending"},
            }
            batches[batch_id] = batch
        batch["comments"].append(asdict(comment))
        delivery_receipt = {
            "comment": asdict(comment),
            "status": "buffered",
            "batch_id": batch["batch_id"],
        }
        repair = repair_by_key.get(comment.delivery_key)
        if repair is not None:
            delivery_receipt["repair"] = repair
        deliveries[comment.delivery_key] = delivery_receipt
        _advance_source_cursor(state, comment)
        staged += 1
    if comments:
        _save_state(state_path, state)

    delivered_batches = 0
    blocked_batch: str | None = None
    latest_channels: dict[str, Any] = {}
    for batch_id, batch in sorted(
        batches.items(),
        key=lambda item: (str(item[1].get("due_at") or ""), item[0]),
    ):
        due_at = _aware(datetime.fromisoformat(str(batch.get("due_at") or "")))
        if due_at > now:
            continue
        notification_data = batch.get("notification")
        if isinstance(notification_data, dict):
            notification = Notification(**notification_data)
        else:
            notification = _batch_notification(batch)
            batch["notification"] = asdict(notification)
            _save_state(state_path, state)
        _attempt_channel(
            state=state,
            state_path=state_path,
            delivery=batch,
            channel="email",
            notification=notification,
            sender=deliver_email,
            now=now,
        )
        latest_channels = {"email": dict(batch["email"])}
        email_status = batch["email"].get("status")
        if email_status == "delivery_unknown":
            blocked_batch = batch_id
            continue
        if email_status != "delivered":
            continue

        receipt_key = f"{notification.idempotency_key}:email"
        state.setdefault("receipts", {})[receipt_key] = dict(batch["email"])
        for item in batch.get("comments", []):
            comment = GitHubComment(**item)
            delivery = deliveries[comment.delivery_key]
            delivery.update(
                status="delivered",
                delivered_via=notification.idempotency_key,
                receipt_keys={"email": receipt_key},
            )
        del batches[batch_id]
        delivered_batches += 1
        _save_state(state_path, state)

    pending_count = len(batches)
    if blocked_batch is not None:
        delivery_status = "blocked"
    elif any(
        isinstance(batch, dict)
        and isinstance(batch.get("email"), dict)
        and batch["email"].get("status") == "failed"
        for batch in batches.values()
    ):
        delivery_status = "pending"
    elif pending_count:
        delivery_status = "buffered"
    elif delivered_batches:
        delivery_status = "delivered"
    else:
        delivery_status = "idle"

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "incremental",
        "comment_count": staged,
        "ignored_self_authored_count": ignored_count,
        "repair_results": repair_results or [],
        "delivery_status": delivery_status,
        "pending_batch_count": pending_count,
        "delivered_batch_count": delivered_batches,
        **(
            {
                "blocked_reason": "delivery_unknown",
                "blocked_batch": blocked_batch,
            }
            if blocked_batch is not None
            else {}
        ),
        "cursor": _latest_cursor(state),
        "cursors": state.get("cursors"),
        "receipt_count": _receipt_count(state),
        "channels": latest_channels,
    }


def _open_subject_batch(
    batches: dict[str, Any],
    comment: GitHubComment,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Return the unfrozen batch for one Issue/PR, if one exists."""
    for batch in batches.values():
        if not isinstance(batch, dict) or isinstance(batch.get("notification"), dict):
            continue
        due_at = _aware(datetime.fromisoformat(str(batch.get("due_at") or "")))
        if due_at <= now:
            continue
        if (
            batch.get("subject_kind") == comment.subject_kind
            and batch.get("number") == comment.number
        ):
            return batch
    return None


def _batch_notification(batch: dict[str, Any]) -> Notification:
    comments = [
        GitHubComment(**item)
        for item in batch.get("comments", [])
        if isinstance(item, dict)
    ]
    if not comments:
        raise ValueError("GitHub comment batch cannot be empty")
    comments = _sort_comments(comments)
    subject = "PR" if batch.get("subject_kind") == "pull_request" else "Issue"
    number = int(batch["number"])
    lines = [
        "同一討論串 15 分鐘內的留言已合併；GitHub 是完整內容的 canonical source。",
        "",
    ]
    for comment in comments:
        lines.extend(
            [
                f"- `{comment.delivery_key}`｜{comment.created_at}｜{comment.author}",
                f"  - {_summary(comment.body)}",
                f"  - {comment.url}",
            ]
        )
    first = comments[0]
    return Notification(
        idempotency_key=(
            f"github-comments:batch:{first.subject_kind}:{number}:"
            f"{first.delivery_key}"
        ),
        title=(
            f"[新架構派發][GitHub #{number}] {subject} 留言摘要"
            f"（{len(comments)} 則）"
        ),
        body="\n".join(lines),
    )


def _channels_delivered(delivery: dict[str, Any]) -> bool:
    return all(
        isinstance(delivery.get(channel), dict)
        and delivery[channel].get("status") == "delivered"
        for channel in ("email", "telegram")
    )


def _receipt_is_complete(receipt: dict[str, Any]) -> bool:
    return bool(receipt.get("sent")) and not any(
        receipt.get(key)
        for key in ("error", "reason", "send_error")
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
    telegram_prefix = f"ℹ️ {title}\n\n"
    for index, comment in enumerate(comments):
        summary = _summary(comment.body)
        subject = "PR" if comment.subject_kind == "pull_request" else "Issue"
        line = (
            f"- {comment.created_at} [{subject} #{comment.number}]({comment.url}) "
            f"{comment.author}: {summary}"
        )
        remaining_after = len(comments) - index - 1
        omission_line = (
            f"- 另有 {remaining_after} 則已納入 durable receipt；"
            "完整內容請見 GitHub Issues/PR。"
        )
        candidate_lines = [*lines, line]
        if remaining_after:
            candidate_lines.append(omission_line)
        if len(telegram_prefix + "\n".join(candidate_lines)) <= (
            TELEGRAM_MAX_MESSAGE_CHARS
        ):
            lines.append(line)
            continue
        omitted = len(comments) - index
        lines.append(
            f"- 另有 {omitted} 則已納入 durable receipt；完整內容請見 GitHub Issues/PR。"
        )
        break
    if not comments:
        lines.append("- 此期間沒有留言。")
    notification = Notification(
        idempotency_key=f"github-comments:backfill:{since.date().isoformat()}",
        title=title,
        body="\n".join(lines),
    )
    _telegram_payload(notification)
    return notification


def _comment_notification(comment: GitHubComment) -> Notification:
    subject = "PR" if comment.subject_kind == "pull_request" else "Issue"
    title = f"[新架構派發][GitHub #{comment.number}] {subject} 新留言"
    body = "\n".join(
        [
            f"- 類型：{subject}（{comment.source}）",
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


def default_self_authors(repo: str = DEFAULT_REPO) -> frozenset[str]:
    """Return production self-authors from env, falling back to repo owner."""
    configured = os.environ.get("VOLPRED_GITHUB_SELF_AUTHORS", "")
    if configured.strip():
        return _normalize_authors(configured.split(","))
    owner = repo.split("/", 1)[0].strip() if "/" in repo else ""
    return _normalize_authors((owner,)) if owner else frozenset()


def _normalize_authors(authors: Iterable[str]) -> frozenset[str]:
    return frozenset(
        text.lower()
        for item in authors
        if (text := str(item or "").strip())
    )


def _partition_self_authored(
    comments: list[GitHubComment], self_authors: frozenset[str]
) -> tuple[list[GitHubComment], list[GitHubComment]]:
    if not self_authors:
        return comments, []
    owner_comments: list[GitHubComment] = []
    external_comments: list[GitHubComment] = []
    for comment in comments:
        if comment.author.strip().lower() in self_authors:
            owner_comments.append(comment)
        else:
            external_comments.append(comment)
    return external_comments, owner_comments


def _record_ignored_self_authored(
    state: dict[str, Any], comments: list[GitHubComment]
) -> int:
    """Advance cursors and preserve a non-delivery audit receipt for self comments."""
    if not comments:
        return 0
    deliveries = state.setdefault("deliveries", {})
    observed_at = datetime.now(UTC).isoformat()
    for comment in comments:
        if comment.delivery_key in deliveries:
            _advance_source_cursor(state, comment)
            continue
        deliveries[comment.delivery_key] = {
            "comment": asdict(comment),
            "status": "ignored_self_authored",
            "ignored_reason": "self_authored_progress_or_receipt",
            "ignored_at": observed_at,
        }
        _advance_source_cursor(state, comment)
    return len(comments)


def _resolve_repairs(
    comments: list[GitHubComment],
    resolver: ResolveRepair | None,
) -> list[dict[str, Any]]:
    """Run the bounded repair adapter without hiding a resolver failure."""
    if resolver is None:
        return []
    results: list[dict[str, Any]] = []
    for comment in comments:
        try:
            result = resolver(comment)
        except Exception as exc:  # noqa: BLE001 - notification must still reconcile
            result = {
                "comment_key": comment.delivery_key,
                "comment_url": comment.url,
                "action": "repair_error",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        results.append(result if isinstance(result, dict) else {
            "comment_key": comment.delivery_key,
            "action": "repair_error",
            "reason": "resolver_returned_non_object",
        })
    return results


def _new_comments(
    comments: list[GitHubComment],
    *,
    cursors: object,
) -> list[GitHubComment]:
    ordered = _sort_comments(comments)
    if not isinstance(cursors, dict):
        return ordered
    unseen: list[GitHubComment] = []
    for comment in ordered:
        cursor = cursors.get(comment.source)
        if not isinstance(cursor, dict):
            unseen.append(comment)
            continue
        cursor_key = (
            str(cursor.get("created_at") or ""),
            int(cursor.get("comment_id") or 0),
        )
        if _source_comment_key(comment) > cursor_key:
            unseen.append(comment)
    return unseen


def _sort_comments(comments: list[GitHubComment]) -> list[GitHubComment]:
    for comment in comments:
        _aware(datetime.fromisoformat(comment.created_at))
        if comment.comment_id < 1 or comment.number < 1:
            raise ValueError("GitHub comment ids and numbers must be positive")
    return sorted(comments, key=_comment_key)


def _comment_key(comment: GitHubComment) -> tuple[str, str, int]:
    return (comment.created_at, comment.source, comment.comment_id)


def _source_comment_key(comment: GitHubComment) -> tuple[str, int]:
    return (comment.created_at, comment.comment_id)


def _cursor_for(comment: GitHubComment) -> dict[str, Any]:
    return {
        "created_at": comment.created_at,
        "source": comment.source,
        "comment_id": comment.comment_id,
    }


def _cursors_for(
    comments: list[GitHubComment],
    *,
    baseline: datetime,
) -> dict[str, dict[str, Any]]:
    cursors = {
        source: {
            "created_at": baseline.isoformat(),
            "source": source,
            "comment_id": 0,
        }
        for source in COMMENT_SOURCES
    }
    for source in COMMENT_SOURCES:
        matches = [comment for comment in comments if comment.source == source]
        if matches:
            cursors[source] = _cursor_for(max(matches, key=_source_comment_key))
    return cursors


def _merge_cursors(
    existing: object,
    candidate: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep the furthest cursor per source across ignored and delivered rows."""
    merged = {
        source: dict(value)
        for source, value in candidate.items()
        if isinstance(value, dict)
    }
    if not isinstance(existing, dict):
        return merged
    for source, value in existing.items():
        if not isinstance(value, dict) or not value.get("created_at"):
            continue
        current = merged.setdefault(source, dict(value))
        if _cursor_value(value) > _cursor_value(current):
            merged[source] = dict(value)
    return merged


def _cursor_value(cursor: dict[str, Any]) -> tuple[str, int]:
    return (
        str(cursor.get("created_at") or ""),
        int(cursor.get("comment_id") or 0),
    )


def _advance_source_cursor(state: dict[str, Any], comment: GitHubComment) -> None:
    cursors = state.setdefault("cursors", {})
    current = cursors.get(comment.source)
    candidate = _cursor_for(comment)
    if not isinstance(current, dict) or _source_comment_key(comment) > (
        str(current.get("created_at") or ""),
        int(current.get("comment_id") or 0),
    ):
        cursors[comment.source] = candidate


def _latest_cursor(state: dict[str, Any]) -> dict[str, Any] | None:
    cursors = state.get("cursors")
    if not isinstance(cursors, dict):
        return None
    valid = [
        cursor
        for cursor in cursors.values()
        if isinstance(cursor, dict) and cursor.get("created_at")
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda cursor: (
            str(cursor.get("created_at") or ""),
            str(cursor.get("source") or ""),
            int(cursor.get("comment_id") or 0),
        ),
    )


def _cursor_since(state: dict[str, Any]) -> datetime:
    cursors = state.get("cursors")
    if not isinstance(cursors, dict):
        cursors = {}
    cursor_times = [
        _aware(datetime.fromisoformat(str(cursor["created_at"])))
        for cursor in cursors.values()
        if isinstance(cursor, dict) and cursor.get("created_at")
    ]
    if not cursor_times:
        completed = state.get("backfill_completed_at")
        return _aware(datetime.fromisoformat(str(completed)))
    return min(cursor_times) - timedelta(seconds=1)


def _receipt_count(state: dict[str, Any]) -> int:
    count = len(state.get("receipts", {}))
    deliveries = state.get("deliveries")
    if not isinstance(deliveries, dict):
        return count
    for delivery in deliveries.values():
        if not isinstance(delivery, dict) or delivery.get("delivered_via"):
            continue
        count += sum(
            isinstance(delivery.get(channel), dict)
            and delivery[channel].get("status") == "delivered"
            for channel in ("email", "telegram")
        )
    return count


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
        _telegram_payload(notification),
        storage_dir=storage_dir,
        disable_notification=True,
    )


def _telegram_payload(notification: Notification) -> str:
    text = f"ℹ️ {notification.title}\n\n{notification.body}"
    if len(text) > TELEGRAM_MAX_MESSAGE_CHARS:
        raise ValueError(
            "GitHub notification exceeds the single-message Telegram contract"
        )
    return text


def _migrate_v2_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade v2 per-comment channel state without losing partial delivery.

    Email is the v3 owner-visibility channel. A delivered v2 email becomes a
    terminal historical receipt (Telegram history is preserved when present).
    Pending/failed email work becomes a due batch; in-flight/unknown remains
    indeterminate in that batch so replay cannot duplicate an external send.
    """
    deliveries = payload.get("deliveries")
    receipts = payload.get("receipts")
    if not isinstance(deliveries, dict) or not isinstance(receipts, dict):
        raise TypeError("GitHub comment notification v2 state is malformed")
    batches: dict[str, Any] = {}
    for delivery_key, delivery in list(deliveries.items()):
        if not isinstance(delivery, dict):
            raise TypeError("GitHub comment notification v2 delivery is malformed")
        # Backfill rows already carry one aggregate durable receipt.
        if delivery.get("status") == "delivered" and delivery.get("delivered_via"):
            continue
        comment_data = delivery.get("comment")
        if not isinstance(comment_data, dict):
            raise TypeError("GitHub comment notification v2 comment is malformed")
        comment = GitHubComment(**comment_data)
        if comment.delivery_key != delivery_key:
            raise ValueError("GitHub comment notification v2 identity mismatch")
        email = delivery.get("email")
        if not isinstance(email, dict):
            raise TypeError("GitHub comment notification v2 email state is malformed")
        email_status = email.get("status")
        notification_data = delivery.get("notification")
        if isinstance(notification_data, dict):
            notification = Notification(**notification_data)
        else:
            notification = _comment_notification(comment)

        if email_status == "delivered":
            receipt_keys: dict[str, str] = {}
            for channel in ("email", "telegram"):
                channel_state = delivery.get(channel)
                if (
                    isinstance(channel_state, dict)
                    and channel_state.get("status") == "delivered"
                ):
                    receipt_key = f"{notification.idempotency_key}:{channel}"
                    receipts.setdefault(receipt_key, dict(channel_state))
                    receipt_keys[channel] = receipt_key
            delivery.update(
                status="delivered",
                delivered_via=notification.idempotency_key,
                receipt_keys=receipt_keys,
            )
            _advance_source_cursor(payload, comment)
            continue
        if email_status not in {
            "pending", "failed", "in_flight", "delivery_unknown",
        }:
            raise ValueError(
                "GitHub comment notification v2 email status is invalid"
            )
        batch_id = (
            f"{comment.subject_kind}:{comment.number}:{comment.delivery_key}"
        )
        batches[batch_id] = {
            "batch_id": batch_id,
            "subject_kind": comment.subject_kind,
            "number": comment.number,
            "opened_at": comment.created_at,
            # It has already waited in v2. Make it immediately eligible while
            # preserving its exact old delivery disposition below.
            "due_at": comment.created_at,
            "comments": [asdict(comment)],
            "email": dict(email),
        }
        deliveries[delivery_key] = {
            "comment": asdict(comment),
            "status": "buffered",
            "batch_id": batch_id,
            "migrated_from_schema": LEGACY_SCHEMA_VERSION,
        }
        _advance_source_cursor(payload, comment)
    payload["schema_version"] = SCHEMA_VERSION
    payload["pending_batches"] = batches
    return payload


def _load_state(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "backfill_completed_at": None,
            "cursors": {},
            "pending_backfill": None,
            "pending_batches": {},
            "deliveries": {},
            "receipts": {},
        }, False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("GitHub comment notification state schema is invalid")
    version = payload.get("schema_version")
    if version == LEGACY_SCHEMA_VERSION:
        return _migrate_v2_state(payload), True
    if version != SCHEMA_VERSION:
        raise ValueError("GitHub comment notification state schema is invalid")
    if not isinstance(payload.get("pending_batches", {}), dict):
        raise TypeError("GitHub comment notification pending_batches is invalid")
    payload.setdefault("pending_batches", {})
    return payload, False


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
