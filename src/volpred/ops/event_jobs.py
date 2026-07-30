from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import get_optional_schedule_items, load_runtime_schedules

from volpred.canonical_write import guard_canonical_write
from volpred.publisher.arc_dedup import normalize_event_series_slot
from .common import project_path
from .local_control_plane import expire_queued_task, supersede_queued_task
from .next_tasks import write_tasks_to_handle
from .shared_lock import shared_state_lock


REACTION_EARLY_RELEASE_DAYS = 3
REACTION_POST_DAYS = 7
FORWARD_TITLE_SIGNALS = (
    "前瞻",
    "預告",
    "倒數",
    "前夕",
    "來臨",
    "即將",
    "展望",
    "前7天",
    "前 7 天",
    "前七天",
    "前2天",
    "前 2 天",
    "前兩天",
    "t-7",
    "t-2",
    "t-3",
    "t-5",
    "今晚",
    "明天",
    "明日",
    "稍後",
    "將在",
    "將於",
    "等待",
    "等消息",
    "尚未",
    "還沒",
    "會前",
    "宣布前",
)
EVENT_TYPE_ALIASES = {
    "nfp": ("非農", "非農就業", "nonfarm", "payroll", "就業報告", "nfp"),
    "cpi": ("cpi", "消費者物價", "通膨", "通脹", "物價指數"),
    "pce": ("pce", "個人消費支出", "個人消費"),
    "ppi": ("ppi", "生產者物價"),
    "fomc": ("fomc", "聯準會", "利率決策", "點陣圖", "議息", "降息", "升息", "fed"),
    "gdp": ("gdp", "國內生產毛額", "經濟成長"),
    "tsmc_revenue": ("台積電", "tsmc", "營收"),
    "earnings": ("財報", "earnings"),
}
QUEUE_EXPIRABLE_STATUSES = {"pending", "pending_main_thread", "blocked"}


def _storage_root(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "ops")


def _event_ledger_root(storage_dir: str = "storage") -> Path:
    root = _storage_root(storage_dir) / "event_ledger"
    if not root.exists():
        guard_canonical_write(root)
        root.mkdir(parents=True, exist_ok=True)
    return root


def _warn_event_jobs(message: str, exc: Exception) -> None:
    print(f"[event_jobs] WARN {message}: {type(exc).__name__}: {exc}")


def _runtime_timezone() -> ZoneInfo:
    metadata = load_runtime_schedules().get("metadata", {})
    timezone_name = str(metadata.get("timezone") or "UTC")
    try:
        return ZoneInfo(timezone_name)
    except Exception as exc:
        _warn_event_jobs(f"invalid runtime timezone {timezone_name!r}; using UTC", exc)
        return ZoneInfo("UTC")


def _coerce_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_runtime_timezone())
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _event_items() -> list[dict[str, Any]]:
    return get_optional_schedule_items("event_jobs")


def _ledger_path(dedupe_key: str, storage_dir: str = "storage") -> Path:
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    return _event_ledger_root(storage_dir) / f"{digest}.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _next_tasks_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "next_tasks.json")


def _feed_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "reports", "feed.json")


def _dedup_log_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "logs", "dedup_decisions.jsonl")


def _slot_is_reaction(slot: str) -> bool:
    """T+0/T-0/T+N are result-known; T-N (N>=1) are forward slots."""

    match = re.match(r"^t([+-])(\d+)", str(slot or "").strip().lower().replace(" ", ""))
    if match is None:
        return False
    sign, number = match.group(1), int(match.group(2))
    return not (sign == "-" and number >= 1)


def _event_type_aliases(event_type: str) -> list[str]:
    normalized = str(event_type or "").strip().lower()
    aliases: set[str] = set()
    if normalized:
        aliases.add(normalized)
        aliases.add(normalized.split("_")[0])
    for key, values in EVENT_TYPE_ALIASES.items():
        if normalized.startswith(key) or key in normalized:
            aliases.update(values)
    return [alias for alias in aliases if alias]


def _looks_forward(title: str) -> bool:
    lowered = str(title or "").lower()
    return any(signal in lowered for signal in FORWARD_TITLE_SIGNALS)


def reaction_already_covered(
    event_type: str,
    event_date: datetime,
    feed: list[dict[str, Any]],
    *,
    event_key: str,
    requested_slot: str,
    release_at: datetime,
) -> dict[str, str] | None:
    """Return an existing published reaction article, conservatively.

    Exact ``event_key + requested_slot`` metadata wins. Cross-stage articles
    never count as coverage. Legacy articles without metadata may cover only a
    T+0 request, and only when an event alias appears in the *title*. Tags are
    deliberately excluded: broad portfolio tags such as ``通膨`` describe many
    unrelated articles and previously let an oil/gold digest suppress a CPI
    T+0 article. The fallback is fail-open because a false positive would
    suppress a time-sensitive article, while a false negative is still caught
    by the publisher's exact-stage gate.
    """

    try:
        aliases = _event_type_aliases(event_type)
        if not aliases:
            return None
        normalized_key = str(event_key or "").strip().casefold()
        canonical_requested_slot = normalize_event_series_slot(requested_slot)
        if not normalized_key:
            return None
        event_day = event_date.astimezone(_runtime_timezone()).date()
        lower = event_day - timedelta(days=REACTION_EARLY_RELEASE_DAYS)
        upper = event_day + timedelta(days=REACTION_POST_DAYS)
        for article in feed:
            if not isinstance(article, dict):
                continue
            if article.get("status") not in (None, "published"):
                continue
            details = (
                article.get("details")
                if isinstance(article.get("details"), dict)
                else {}
            )
            article_key = str(
                article.get("event_key") or details.get("event_key") or ""
            ).strip().casefold()
            raw_article_slot = (
                article.get("event_series_slot")
                or details.get("event_series_slot")
                or ""
            )
            article_slot = ""
            if raw_article_slot:
                try:
                    article_slot = normalize_event_series_slot(
                        str(raw_article_slot)
                    )
                except ValueError:
                    article_slot = ""
            if (
                article_key == normalized_key
                and article_slot == canonical_requested_slot
            ):
                return {"id": str(article.get("id") or ""), "match": "metadata"}
            # Structured metadata proves this is either another event or another
            # stage. Never reinterpret it through the ambiguous title fallback.
            if article_key or raw_article_slot:
                continue
            # Legacy rows have no stage identity. They can conservatively stand
            # in for the immediate reaction only, never for T+1 or another stage.
            if canonical_requested_slot != "T+0":
                continue

            title = str(article.get("title") or "")
            title_lower = title.lower()
            body_lead = str(
                article.get("description")
                or article.get("content")
                or article.get("summary")
                or ""
            )[:800]
            if not any(alias in title_lower for alias in aliases) or _looks_forward(
                f"{title}\n{body_lead}"
            ):
                continue
            published_raw = article.get("published_at") or article.get("created_at")
            if not published_raw:
                continue
            try:
                published = _coerce_datetime(published_raw)
            except (TypeError, ValueError) as exc:
                _warn_event_jobs(
                    f"invalid published_at during event coverage article_id={article.get('id')!r}",
                    exc,
                )
                continue
            if published is None:
                continue
            published_day = published.astimezone(_runtime_timezone()).date()
            if published < release_at:
                continue
            if lower <= published_day <= upper:
                return {
                    "id": str(article.get("id") or ""),
                    "match": "title_keyword",
                }
    except Exception as exc:  # noqa: BLE001 - coverage is intentionally fail-open
        _warn_event_jobs("reaction coverage check failed; allowing event task", exc)
    return None


def _log_coverage_decision(
    *,
    storage_dir: str,
    target_id: str,
    covered_by: dict[str, str],
    now: datetime,
    blocking: bool,
) -> None:
    path = _dedup_log_path(storage_dir)
    guard_canonical_write(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": now.isoformat(),
            "gate": "event_reaction_coverage",
            "target_id": target_id,
            "candidate_id": target_id,
            "decision": "skip" if blocking else "warn",
            "reason": (
                "reaction_already_covered"
                if blocking
                else "legacy_reaction_candidate_advisory"
            ),
            "dup_of": covered_by.get("id", ""),
            "match": covered_by.get("match", ""),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - audit failure must not suppress a real task
        _warn_event_jobs("coverage audit log failed", exc)


def _coverage_for_item(
    item: dict[str, Any], *, storage_dir: str, now: datetime
) -> dict[str, str] | None:
    template = item.get("task_template") or {}
    payload = template.get("payload_patch") or {} if isinstance(template, dict) else {}
    if not isinstance(payload, dict):
        return None
    slot = str(payload.get("event_series_slot") or "")
    if not _slot_is_reaction(slot):
        return None
    event_type = str(payload.get("event_type") or item.get("event_key") or "")
    try:
        event_date = _coerce_datetime(payload.get("event_date"))
    except (TypeError, ValueError) as exc:
        _warn_event_jobs(f"invalid event_date for coverage item={item.get('id')!r}", exc)
        return None
    if event_date is None:
        return None
    feed_path = _feed_path(storage_dir)
    if not feed_path.exists():
        return None
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _warn_event_jobs("feed read failed during event coverage; allowing task", exc)
        return None
    if not isinstance(feed, list):
        _warn_event_jobs(
            "feed schema invalid during event coverage; allowing task",
            TypeError(type(feed).__name__),
        )
        return None
    try:
        release_at = _coerce_datetime(item.get("not_before"))
    except (TypeError, ValueError) as exc:
        _warn_event_jobs(
            f"invalid not_before for coverage item={item.get('id')!r}",
            exc,
        )
        return None
    if release_at is None:
        return None
    covered = reaction_already_covered(
        event_type,
        event_date,
        feed,
        event_key=str(payload.get("event_key") or item.get("event_key") or ""),
        requested_slot=slot,
        release_at=release_at,
    )
    if covered:
        blocking = covered.get("match") == "metadata"
        _log_coverage_decision(
            storage_dir=storage_dir,
            target_id=_event_task_id(item),
            covered_by=covered,
            now=now,
            blocking=blocking,
        )
        if not blocking:
            # A legacy title after release is useful review evidence but cannot
            # prove the exact stage identity. Exact identity alone may cut the
            # schedule_slot -> event_task graph edge.
            return None
    return covered


def _load_feed_for_screen(storage_dir: str) -> list[dict[str, Any]] | None:
    """Feed corpus for the generation-time topic screen. Fail-open, never silent.

    Distinct from `_coverage_for_item`, which is the BLOCKING owner for
    "this exact event is already covered" (event-scoped). This feed drives the
    warn-only THEME screen — a different question ("is this theme crowded?").
    """
    feed_path = _feed_path(storage_dir)
    if not feed_path.exists():
        _warn_event_jobs(
            "feed missing during topic screen; allowing task with gate-error annotation",
            FileNotFoundError(str(feed_path)),
        )
        return None
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _warn_event_jobs("feed read failed during topic screen; allowing task", exc)
        return None
    if not isinstance(feed, list):
        _warn_event_jobs(
            "feed schema invalid during topic screen; allowing task",
            TypeError(type(feed).__name__),
        )
        return None
    return feed


def _event_task_id(item: dict[str, Any]) -> str:
    template = item.get("task_template") or {}
    if not isinstance(template, dict):
        raise RuntimeError(f"event_jobs task_template must be an object: {item.get('id')}")
    payload = template.get("payload_patch") or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"event_jobs payload_patch must be an object: {item.get('id')}")
    event_type = str(payload.get("event_type") or item.get("event_key") or "event").lower()
    event_date = str(payload.get("event_date") or "unknown-date")
    slot = str(payload.get("event_series_slot") or "T-0")
    slot_normalized = slot.lower().replace("+", "plus").replace("-", "minus")
    return f"event_article_{event_type}_{event_date}_{slot_normalized}"


def build_pending_event_task(
    item: dict[str, Any],
    *,
    now: datetime,
    feed: list[dict[str, Any]] | None = None,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    """Build the one canonical dispatcher row for an event window.

    `feed`: the topic is always screened for duplication at GENERATION time
    (2026-07-13 incident: generators created tasks without ever looking at the
    feed). The event lane screens in WARN mode — a hit annotates the task via
    `dedup_screen` but NEVER blocks it. None/empty corpus produces an explicit
    nonblocking gate-error annotation instead of silently skipping the screen.

    Why warn-only here, while the trending lane blocks: event articles are a
    designed T-7 / T-2 / T+0 series about one event, and every FOMC resembles the
    last FOMC. Feed event markers are too sparse to exclude same-event siblings
    from the corpus (5 items carry `details.event_series_slot`; `event_key` is
    null), so a hard block would kill the NEXT event window because the PREVIOUS
    one exists — a content hole on P1 time-sensitive work, precisely what
    `.claude/rules/dedup-gate-audit.md` forbids. The writer agent gets the near
    misses and must differentiate; the event never goes silent.
    """

    template = item.get("task_template") or {}
    if not isinstance(template, dict):
        raise RuntimeError(f"event_jobs task_template must be an object: {item.get('id')}")
    payload = template.get("payload_patch") or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"event_jobs payload_patch must be an object: {item.get('id')}")
    title = str(template.get("title") or item.get("id") or "event article")
    description = str(template.get("description") or "")
    event_type = str(payload.get("event_type") or item.get("event_key") or "event").lower()
    event_date = str(payload.get("event_date") or "unknown-date")
    slot = str(payload.get("event_series_slot") or "T-0")
    deadline = _coerce_datetime(item.get("deadline"))
    not_before = _coerce_datetime(item.get("not_before"))
    task_payload = dict(payload)
    task_payload.setdefault("event_key", item.get("event_key"))
    task_payload.setdefault("event_job_id", item.get("id"))
    task_payload.setdefault("preconditions", template.get("preconditions") or [])

    task_id = _event_task_id(item)
    from volpred.ops.topic_dedup import log_decision, screen_topic

    screen = screen_topic(
        title,
        description,
        feed=feed,
        audience="event",
        mode="warn",
    )
    log_decision(str(project_path(storage_dir)), "event_article", task_id, screen)
    dedup_screen: dict[str, Any] | None = None
    if screen.verdict != "clean":
        dedup_screen = screen.as_task_field()

    task = {
        "id": task_id,
        "title": f"[event_article] {title}",
        "description": (
            "Auto-generated by event_jobs single-owner materializer.\n"
            f"ref_event_job_id: {item.get('id')}\n"
            f"event_key: {item.get('event_key')}\n"
            f"event_type: {event_type}\n"
            f"event_date: {event_date}\n"
            f"event_series_slot: {slot}\n\n"
            f"{description}\n\n"
            "Stage-aware pre-write dedup (exact same stage blocks; cross-stage "
            "semantic overlap only warns):\n"
            "uv run python scripts/check_arc_dedup.py "
            f"--title {shlex.quote(title)} --audience event "
            f"--event-key {shlex.quote(str(item.get('event_key') or ''))} "
            f"--event-series-slot {shlex.quote(slot)}\n"
            "This stage-aware verdict supersedes legacy generic ARC DUPLICATE "
            "instructions in the source template."
        ),
        "task_type": "event_article",
        "priority": 1,
        "status": "pending",
        # Event windows are time-bounded production work.  Reserving them for
        # an interactive main thread made a correctly materialized P1 row
        # permanently undispatchable whenever no desktop session was open.
        # The Operations Core worker is already Claude-only for this task type;
        # keep the task inline inside that worker, while Codex eligibility
        # remains independently denied by task_pool_selection.
        "dispatch_lane": "agent",
        "topology": "inline",
        "created_at": now.isoformat(),
        "source": "event_expander",
        "preferred_agent": str(template.get("preferred_agent") or item.get("preferred_agent") or "claude"),
        "public_effect": str(template.get("public_effect") or item.get("public_effect") or "published"),
        "payload": task_payload,
        "ref_event_job_id": item.get("id"),
        "event_key": item.get("event_key"),
        "event_type": event_type,
        "event_date": event_date,
        "event_series_slot": slot,
        "not_before": not_before.isoformat() if not_before else None,
        "deadline": deadline.isoformat() if deadline else None,
        "tags": [
            "event_article",
            "reader_facing",
            event_type,
            slot,
            "claude-worker-only",
        ],
    }
    # Warn-only: the event still ships, but the writer agent must differentiate
    # against these near misses. Never dropped silently.
    if dedup_screen:
        task["dedup_screen"] = dedup_screen
    return task


def _ledger_receipt_ids(ledger: dict[str, Any] | None) -> set[str]:
    if not isinstance(ledger, dict):
        return set()
    values = [ledger.get("receipt_task_id"), ledger.get("task_id")]
    if isinstance(ledger.get("receipt_task_ids"), list):
        values.extend(ledger["receipt_task_ids"])
    return {str(value).strip() for value in values if str(value or "").strip()}


def _legacy_event_job_ids(ledger: dict[str, Any] | None, *, storage_dir: str) -> set[str]:
    ids: set[str] = set()
    receipt_ids = _ledger_receipt_ids(ledger)
    for receipt_id in receipt_ids:
        receipt_path = project_path(storage_dir, "ops", "tasks", f"{receipt_id}.json")
        if not receipt_path.exists():
            continue
        try:
            receipt = _read_json(receipt_path) or {}
        except (OSError, json.JSONDecodeError) as exc:
            _warn_event_jobs(f"legacy event receipt read failed path={receipt_path}", exc)
            continue
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        if isinstance(payload, dict) and payload.get("event_job_id"):
            ids.add(str(payload["event_job_id"]))
    return ids


def _ensure_next_task(
    item: dict[str, Any],
    *,
    storage_dir: str,
    now: datetime,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotently materialize one event into the canonical pending queue."""

    task = build_pending_event_task(
        item, now=now, feed=_load_feed_for_screen(storage_dir), storage_dir=storage_dir
    )
    queue_path = _next_tasks_path(storage_dir)
    guard_canonical_write(queue_path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_event_ids = {str(item.get("id") or "")}
    candidate_event_ids.update(_legacy_event_job_ids(ledger, storage_dir=storage_dir))
    candidate_event_ids.discard("")
    with queue_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            tasks = json.loads(raw) if raw else []
            if not isinstance(tasks, list):
                raise RuntimeError(f"next_tasks.json must be a list: {queue_path}")
            existing: dict[str, Any] | None = None
            for candidate in tasks:
                if not isinstance(candidate, dict):
                    continue
                candidate_event_job_id = str(candidate.get("ref_event_job_id") or "")
                if candidate.get("id") == task["id"] or (
                    candidate_event_job_id
                    and candidate_event_job_id in candidate_event_ids
                ):
                    existing = candidate
                    break
            if existing is not None:
                status = str(existing.get("status") or "").strip().lower()
                if status in QUEUE_EXPIRABLE_STATUSES:
                    covered = _coverage_for_item(item, storage_dir=storage_dir, now=now)
                    if covered:
                        existing["status"] = "superseded"
                        existing["completed_at"] = now.isoformat()
                        existing["superseded_at"] = now.isoformat()
                        existing["result"] = "reaction_already_covered"
                        existing["covered_by"] = covered
                        write_tasks_to_handle(handle, tasks)
                        return {
                            "task": existing,
                            "created": False,
                            "updated": True,
                            "reason": "reaction_already_covered",
                            "covered_by": covered,
                        }
                changed = False
                if (
                    status in {"pending", "pending_main_thread"}
                    and existing.get("description") != task.get("description")
                ):
                    # Pending rows are still generator-owned. Refresh the brief
                    # when the event contract changes so a row materialized one
                    # minute before a hotfix cannot keep executing obsolete
                    # dedup instructions. Claimed/in-progress rows are worker-
                    # owned and must never be rewritten underneath them.
                    existing["description"] = task["description"]
                    changed = True
                if status in {"pending", "pending_main_thread"}:
                    for key in (
                        "deadline",
                        "not_before",
                        "ref_event_job_id",
                        "event_key",
                        "event_type",
                        "event_date",
                        "event_series_slot",
                    ):
                        if not existing.get(key) and task.get(key):
                            existing[key] = task[key]
                            changed = True
                    # Pending event rows remain generator-owned, so routing
                    # migrations must replace obsolete values rather than only
                    # fill missing fields.  Otherwise a main_thread-only row
                    # survives every five-minute reconcile forever.
                    for key in (
                        "dispatch_lane",
                        "preferred_agent",
                        "topology",
                        "tags",
                    ):
                        if existing.get(key) != task.get(key):
                            existing[key] = task.get(key)
                            changed = True
                if changed:
                    write_tasks_to_handle(handle, tasks)
                return {
                    "task": existing,
                    "created": False,
                    "updated": changed,
                    "reason": "already_in_next_tasks",
                }

            covered = _coverage_for_item(item, storage_dir=storage_dir, now=now)
            if covered:
                if not raw:
                    # ``a+`` creates a missing queue file. Keep the canonical
                    # JSON valid even when coverage means no row is appended.
                    write_tasks_to_handle(handle, tasks)
                return {
                    "task": None,
                    "created": False,
                    "updated": False,
                    "reason": "reaction_already_covered",
                    "covered_by": covered,
                }

            tasks.append(task)
            write_tasks_to_handle(handle, tasks)
            return {"task": task, "created": True, "updated": False, "reason": "created"}
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _discover_legacy_receipt_ids(
    ledger: dict[str, Any],
    *,
    storage_dir: str,
    event_job_ids: set[str] | None = None,
) -> set[str]:
    """Find every pre-cutover receipt sharing a logical event-job ID."""

    receipt_ids = _ledger_receipt_ids(ledger)
    aliases = {str(value).strip() for value in (event_job_ids or set()) if str(value).strip()}
    tasks_root = project_path(storage_dir, "ops", "tasks")

    for receipt_id in list(receipt_ids):
        receipt_path = tasks_root / f"{receipt_id}.json"
        if not receipt_path.exists():
            continue
        try:
            candidate = _read_json(receipt_path)
        except (OSError, json.JSONDecodeError) as exc:
            _warn_event_jobs(f"legacy receipt discovery read failed path={receipt_path}", exc)
            continue
        payload = candidate.get("payload") if isinstance(candidate, dict) else None
        if isinstance(payload, dict) and payload.get("event_job_id"):
            aliases.add(str(payload["event_job_id"]))

    if not aliases or not tasks_root.exists():
        return receipt_ids
    for candidate_path in sorted(tasks_root.glob("*.json")):
        try:
            candidate = _read_json(candidate_path)
        except (OSError, json.JSONDecodeError) as exc:
            _warn_event_jobs(f"legacy receipt discovery read failed path={candidate_path}", exc)
            continue
        payload = candidate.get("payload") if isinstance(candidate, dict) else None
        if isinstance(payload, dict) and str(payload.get("event_job_id") or "") in aliases:
            receipt_ids.add(str(candidate.get("id") or candidate_path.stem))
    return receipt_ids


def _prepare_legacy_receipt_cutover(
    item: dict[str, Any],
    ledger: dict[str, Any],
    *,
    storage_dir: str,
    now: datetime,
) -> dict[str, Any]:
    """Close the old lifecycle before making its canonical replacement claimable."""

    replacement_id = _event_task_id(item)
    tasks_root = project_path(storage_dir, "ops", "tasks")
    receipt_ids = _discover_legacy_receipt_ids(
        ledger,
        storage_dir=storage_dir,
        event_job_ids={str(item.get("id") or "")},
    )

    receipt_ids.discard("")
    receipt_ids.discard(replacement_id)
    if not receipt_ids:
        return {"proceed": True, "reason": "no_legacy_receipt"}

    ordered_ids = sorted(receipt_ids)
    ledger["receipt_task_id"] = ordered_ids[0]
    ledger["receipt_task_ids"] = ordered_ids
    dispositions: dict[str, str] = {}
    conflicts: list[tuple[str, str]] = []
    for receipt_id in ordered_ids:
        receipt_path = tasks_root / f"{receipt_id}.json"
        if not receipt_path.exists():
            dispositions[receipt_id] = "legacy_receipt_absent"
            continue
        try:
            transition = supersede_queued_task(
                receipt_id,
                replacement_task_id=replacement_id,
                now=now.isoformat(),
                storage_dir=storage_dir,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _warn_event_jobs(f"legacy event receipt cutover failed task_id={receipt_id}", exc)
            dispositions[receipt_id] = "legacy_receipt_cutover_error"
            conflicts.append((receipt_id, "cutover_error"))
            continue

        reason = str(transition.get("reason") or "unknown")
        dispositions[receipt_id] = reason
        state = transition.get("task") if isinstance(transition.get("task"), dict) else {}
        status = str(state.get("status") or "").strip().lower()
        if transition.get("changed"):
            continue
        if (
            reason == "terminal"
            and status == "cancelled"
            and state.get("migration_candidate_id") == replacement_id
        ):
            continue
        conflicts.append((receipt_id, status or reason))

    ledger["legacy_receipt_dispositions"] = dispositions
    ledger["legacy_receipt_disposition"] = dispositions.get(ordered_ids[0])
    if not conflicts:
        return {"proceed": True, "reason": "legacy_cutover_prepared"}
    conflict_id, conflict_status = conflicts[0]
    return {
        "proceed": False,
        "reason": f"legacy_receipt_conflict:{conflict_status}",
        "conflict_receipt_id": conflict_id,
        "conflict_count": len(conflicts),
    }


def _suppress_canonical_for_legacy_conflict(
    item: dict[str, Any],
    *,
    legacy_receipt_id: str,
    legacy_event_job_ids: set[str] | None = None,
    candidate_task_ids: set[str] | None = None,
    storage_dir: str,
    now: datetime,
) -> dict[str, Any]:
    """Prevent a pre-existing canonical row from racing an active legacy owner."""

    queue_path = _next_tasks_path(storage_dir)
    if not queue_path.exists():
        return {"changed": False, "reason": "canonical_absent", "task": None}
    guard_canonical_write(queue_path)
    with queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(handle)
            if not isinstance(tasks, list):
                raise RuntimeError(f"next_tasks.json must be a list: {queue_path}")
            target_ids = {_event_task_id(item), *(candidate_task_ids or set())} - {""}
            event_job_ids = {
                str(item.get("id") or ""),
                *(legacy_event_job_ids or set()),
            } - {""}
            existing = next(
                (
                    task
                    for task in tasks
                    if isinstance(task, dict)
                    and (
                        str(task.get("id") or "") in target_ids
                        or str(task.get("ref_event_job_id") or "") in event_job_ids
                    )
                ),
                None,
            )
            if existing is None:
                return {"changed": False, "reason": "canonical_absent", "task": None}
            status = str(existing.get("status") or "").strip().lower()
            if status in QUEUE_EXPIRABLE_STATUSES:
                existing["status"] = "superseded"
                existing["completed_at"] = now.isoformat()
                existing["superseded_at"] = now.isoformat()
                existing["superseded_by"] = legacy_receipt_id
                existing["result"] = "legacy_event_receipt_already_active"
                history = existing.setdefault("status_history", [])
                if isinstance(history, list):
                    history.append(
                        {
                            "ts": now.isoformat(),
                            "from": status,
                            "to": "superseded",
                            "by": "system:event_expander",
                            "note": "legacy_receipt_won_cutover_race",
                        }
                    )
                write_tasks_to_handle(handle, tasks)
                return {
                    "changed": True,
                    "reason": "canonical_suppressed_for_active_legacy",
                    "task": existing,
                }
            if status in {"claimed", "in_progress"}:
                return {
                    "changed": False,
                    "reason": f"dual_active_lifecycle_conflict:{status}",
                    "task": existing,
                }
            return {
                "changed": False,
                "reason": f"canonical_already_terminal:{status or 'unknown'}",
                "task": existing,
            }
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _reconcile_legacy_conflict(
    item: dict[str, Any],
    ledger: dict[str, Any],
    cutover: dict[str, Any],
    *,
    storage_dir: str,
    now: datetime,
) -> str:
    """Record and suppress the other lifecycle after legacy wins the CAS."""

    receipt_id = str(
        cutover.get("conflict_receipt_id")
        or ledger.get("receipt_task_id")
        or ledger.get("task_id")
        or ""
    )
    suppression = _suppress_canonical_for_legacy_conflict(
        item,
        legacy_receipt_id=receipt_id,
        legacy_event_job_ids=_legacy_event_job_ids(ledger, storage_dir=storage_dir),
        candidate_task_ids={str(ledger.get("next_task_id") or "")},
        storage_dir=storage_dir,
        now=now,
    )
    ledger["disposition"] = cutover.get("reason")
    ledger["canonical_conflict_disposition"] = suppression.get("reason")
    task = suppression.get("task")
    if isinstance(task, dict):
        ledger["next_task_id"] = task.get("id")
    reason = str(suppression.get("reason") or cutover.get("reason"))
    if not reason.startswith("dual_active_lifecycle_conflict"):
        reason = str(cutover.get("reason"))
    return reason


def _seed_event_ledger(
    item: dict[str, Any], ledger: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Restore invariant fields when recovering an old or truncated ledger."""

    deadline = _coerce_datetime(item.get("deadline"))
    if deadline is None:
        raise RuntimeError(f"event_jobs deadline is required: {item.get('id')}")
    ledger["dedupe_key"] = str(item.get("dedupe_key") or "")
    ledger["event_key"] = str(item.get("event_key") or "")
    ledger.setdefault("task_family", "content")
    ledger.setdefault("materialized_at", now.isoformat())
    ledger["deadline"] = deadline.isoformat()
    ledger["gc_after"] = (deadline + timedelta(days=7)).isoformat()
    return ledger


def _event_status(item: dict[str, Any], *, now: datetime) -> str:
    not_before = _coerce_datetime(item.get("not_before"))
    deadline = _coerce_datetime(item.get("deadline"))
    if deadline and now > deadline:
        return "expired"
    if not_before and now < not_before:
        return "pending"
    return "due"


def _materialize_task(item: dict[str, Any], *, storage_dir: str, now: datetime) -> dict[str, Any]:
    # The event expander is the sole pending-task owner.  Older code called
    # create_task() here (ops/tasks audit store) while a separate daily refiller
    # sometimes wrote next_tasks.json.  That split is why TSMC_REVENUE 2026-07-10
    # had a queued receipt no dispatcher could see.  New events go directly to
    # the canonical pending queue; the ledger below is the materialization audit.
    guard_canonical_write(_ledger_path(str(item.get("dedupe_key") or ""), storage_dir=storage_dir))
    deadline = _coerce_datetime(item.get("deadline"))
    if deadline is None:
        raise RuntimeError(f"event_jobs deadline is required: {item.get('id')}")
    ensured = _ensure_next_task(item, storage_dir=storage_dir, now=now)
    gc_after = (deadline or now) + timedelta(days=7)
    task = ensured.get("task")
    ledger = {
        "dedupe_key": str(item.get("dedupe_key") or ""),
        "event_key": str(item.get("event_key") or ""),
        "task_family": "content",
        "task_id": task.get("id") if isinstance(task, dict) else None,
        "next_task_id": task.get("id") if isinstance(task, dict) else None,
        "record_kind": "next_tasks_materialization",
        "disposition": ensured.get("reason"),
        "covered_by": ensured.get("covered_by"),
        "materialized_at": now.isoformat(),
        "deadline": deadline.isoformat() if deadline else None,
        "gc_after": gc_after.isoformat(),
    }
    _write_json(_ledger_path(str(item.get("dedupe_key") or ""), storage_dir=storage_dir), ledger)
    return {
        "task": task,
        "ledger": ledger,
        "queue_created": bool(ensured.get("created")),
        "queue_updated": bool(ensured.get("updated")),
        "reason": ensured.get("reason"),
        "covered_by": ensured.get("covered_by"),
    }


def _expire_next_tasks(*, storage_dir: str, now: datetime) -> list[str]:
    """CAS pending event rows to ``expired`` under the claim-file lock."""

    queue_path = _next_tasks_path(storage_dir)
    if not queue_path.exists():
        return []
    guard_canonical_write(queue_path)
    expired: list[str] = []
    with queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(handle)
            if not isinstance(tasks, list):
                raise RuntimeError(f"next_tasks.json must be a list: {queue_path}")
            for task in tasks:
                if not isinstance(task, dict) or task.get("task_type") != "event_article":
                    continue
                status = str(task.get("status") or "").strip().lower()
                if status not in QUEUE_EXPIRABLE_STATUSES:
                    continue
                deadline_raw = task.get("deadline")
                if not deadline_raw:
                    continue
                try:
                    deadline = _coerce_datetime(deadline_raw)
                except (TypeError, ValueError) as exc:
                    _warn_event_jobs(
                        f"invalid next_tasks event deadline task_id={task.get('id')!r}", exc
                    )
                    continue
                if deadline is None or now <= deadline:
                    continue
                task_id = str(task.get("id") or "")
                task["status"] = "expired"
                task["expired_at"] = now.isoformat()
                task["completed_at"] = now.isoformat()
                task["result"] = "event_deadline_expired_before_dispatch"
                task["last_error"] = "deadline_expired_never_dispatched"
                expired.append(task_id)
            if expired:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return expired


def _expire_legacy_receipts(*, storage_dir: str, now: datetime) -> list[str]:
    """Close pre-cutover queued TaskRecords; new events never create these."""

    expired: list[str] = []
    ledger_root = _event_ledger_root(storage_dir)
    for path in sorted(ledger_root.glob("*.json")):
        try:
            ledger = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            _warn_event_jobs(f"legacy expiry ledger read failed path={path}", exc)
            continue
        if not isinstance(ledger, dict):
            continue
        try:
            deadline = _coerce_datetime(ledger.get("deadline"))
        except (TypeError, ValueError) as exc:
            _warn_event_jobs(f"legacy expiry deadline invalid path={path}", exc)
            continue
        if deadline is None or now <= deadline:
            continue
        receipt_ids = _discover_legacy_receipt_ids(ledger, storage_dir=storage_dir)
        for receipt_id in sorted(receipt_ids):
            receipt_path = project_path(storage_dir, "ops", "tasks", f"{receipt_id}.json")
            if not receipt_path.exists():
                continue
            try:
                result = expire_queued_task(
                    receipt_id,
                    reason="deadline_expired_never_dispatched",
                    summary="Event deadline expired before the legacy receipt was dispatched",
                    now=now.isoformat(),
                    storage_dir=storage_dir,
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _warn_event_jobs(f"legacy event receipt expiry failed task_id={receipt_id}", exc)
                continue
            if result.get("changed"):
                expired.append(receipt_id)
    return expired


def expire_overdue_event_tasks(
    *, storage_dir: str = "storage", now: datetime | None = None
) -> dict[str, list[str]]:
    """Self-heal expired event work in both canonical and legacy stores.

    Lock order is deliberate: the next_tasks flock is released before any
    legacy control-plane lock is acquired, avoiding a cross-store deadlock.
    """

    now = now or _utc_now()
    queue = _expire_next_tasks(storage_dir=storage_dir, now=now)
    legacy = _expire_legacy_receipts(storage_dir=storage_dir, now=now)
    return {"next_tasks": queue, "legacy_receipts": legacy}


def gc_event_ledger(*, storage_dir: str = "storage", now: datetime | None = None) -> list[str]:
    now = now or _utc_now()
    removed: list[str] = []
    with shared_state_lock("event_ledger", storage_dir=storage_dir):
        for path in sorted(_event_ledger_root(storage_dir).glob("*.json")):
            try:
                payload = _read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                _warn_event_jobs(f"event ledger GC read failed path={path}", exc)
                continue
            if payload is None:
                continue
            if not isinstance(payload, dict):
                _warn_event_jobs(
                    f"event ledger GC schema invalid path={path}",
                    TypeError(type(payload).__name__),
                )
                continue
            try:
                gc_after = _coerce_datetime(payload.get("gc_after"))
            except (TypeError, ValueError) as exc:
                _warn_event_jobs(f"event ledger GC timestamp invalid path={path}", exc)
                continue
            if gc_after and now > gc_after:
                guard_canonical_write(path)
                path.unlink(missing_ok=True)
                removed.append(path.name)
    return removed


def preview_event_jobs(*, storage_dir: str = "storage", now: datetime | None = None) -> dict[str, Any]:
    now = now or _utc_now()
    items: list[dict[str, Any]] = []
    for item in _event_items():
        dedupe_key = str(item.get("dedupe_key") or "")
        ledger = _read_json(_ledger_path(dedupe_key, storage_dir=storage_dir)) if dedupe_key else None
        items.append(
            {
                "id": item.get("id"),
                "event_key": item.get("event_key"),
                "trigger_mode": item.get("trigger_mode"),
                "dedupe_key": dedupe_key,
                "status": _event_status(item, now=now),
                "materialized": ledger is not None,
                "task_id": (
                    ledger.get("next_task_id") or ledger.get("task_id") if ledger else None
                ),
                "not_before": item.get("not_before"),
                "deadline": item.get("deadline"),
            }
        )
    return {
        "generated_at": now.isoformat(),
        "items": items,
    }


def expand_due_event_jobs(*, storage_dir: str = "storage", now: datetime | None = None) -> dict[str, Any]:
    now = now or _utc_now()
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    expired_tasks = expire_overdue_event_tasks(storage_dir=storage_dir, now=now)
    removed_ledgers = gc_event_ledger(storage_dir=storage_dir, now=now)
    with shared_state_lock("event_ledger", storage_dir=storage_dir):
        for item in _event_items():
            if not str(item.get("id") or "").strip():
                skipped.append({"id": None, "reason": "missing_id"})
                continue
            dedupe_key = str(item.get("dedupe_key") or "")
            if not dedupe_key:
                skipped.append({"id": item.get("id"), "reason": "missing_dedupe_key"})
                continue
            if not item.get("deadline"):
                skipped.append({"id": item.get("id"), "reason": "missing_deadline"})
                continue
            try:
                _coerce_datetime(item.get("deadline"))
            except (TypeError, ValueError) as exc:
                _warn_event_jobs(f"invalid deadline item={item.get('id')!r}", exc)
                skipped.append({"id": item.get("id"), "reason": "invalid_deadline"})
                continue
            try:
                status = _event_status(item, now=now)
            except (TypeError, ValueError) as exc:
                _warn_event_jobs(f"invalid event window item={item.get('id')!r}", exc)
                skipped.append({"id": item.get("id"), "reason": "invalid_event_window"})
                continue
            if status != "due":
                skipped.append({"id": item.get("id"), "reason": status})
                continue
            ledger_path = _ledger_path(dedupe_key, storage_dir=storage_dir)
            if ledger_path.exists():
                try:
                    ledger = _read_json(ledger_path)
                except (OSError, json.JSONDecodeError) as exc:
                    _warn_event_jobs(
                        f"corrupt event ledger will be reconstructed path={ledger_path}", exc
                    )
                    ledger = {}
                if ledger is None:
                    raise RuntimeError(f"event ledger disappeared during expansion: {ledger_path}")
                if not isinstance(ledger, dict):
                    _warn_event_jobs(
                        f"corrupt event ledger schema will be reconstructed path={ledger_path}",
                        TypeError(type(ledger).__name__),
                    )
                    ledger = {}
                ledger = _seed_event_ledger(item, ledger, now=now)

                # The legacy TaskRecord lock is acquired before the canonical
                # queue flock.  If a worker already owns the old row, do not
                # create a second dispatchable lifecycle.
                cutover = _prepare_legacy_receipt_cutover(
                    item,
                    ledger,
                    storage_dir=storage_dir,
                    now=now,
                )
                if not cutover.get("proceed"):
                    conflict_reason = _reconcile_legacy_conflict(
                        item,
                        ledger,
                        cutover,
                        storage_dir=storage_dir,
                        now=now,
                    )
                    _write_json(ledger_path, ledger)
                    skipped.append(
                        {
                            "id": item.get("id"),
                            "reason": conflict_reason,
                        }
                    )
                    continue

                # Reconcile every due ledger, not merely missing ledgers.  If a
                # prior process crashed after writing the ledger/legacy receipt
                # but before next_tasks, the next hourly tick repairs the bridge.
                ensured = _ensure_next_task(
                    item,
                    storage_dir=storage_dir,
                    now=now,
                    ledger=ledger,
                )
                task = ensured.get("task")
                if isinstance(task, dict):
                    ledger["next_task_id"] = task.get("id")
                    ledger["record_kind"] = "next_tasks_materialization"
                if ensured.get("reason") == "reaction_already_covered":
                    ledger["disposition"] = "reaction_already_covered"
                    ledger["covered_by"] = ensured.get("covered_by")
                    _write_json(ledger_path, ledger)
                    skipped.append(
                        {
                            "id": item.get("id"),
                            "reason": "reaction_already_covered",
                            "covered_by": ensured.get("covered_by"),
                        }
                    )
                    continue
                if isinstance(task, dict):
                    ledger["disposition"] = ensured.get("reason")
                    _write_json(ledger_path, ledger)
                if ensured.get("created"):
                    created.append(
                        {
                            "task": task,
                            "ledger": ledger,
                            "queue_created": True,
                            "queue_updated": False,
                            "reason": "recovered_missing_next_task",
                        }
                    )
                else:
                    skipped.append(
                        {
                            "id": item.get("id"),
                            "reason": "already_materialized",
                            "next_task_id": task.get("id") if isinstance(task, dict) else None,
                            "queue_updated": bool(ensured.get("updated")),
                        }
                    )
                continue

            # Also reconcile pre-cutover receipts left behind by a crash before
            # the old writer managed to create its ledger file.
            provisional_ledger = _seed_event_ledger(item, {}, now=now)
            cutover = _prepare_legacy_receipt_cutover(
                item,
                provisional_ledger,
                storage_dir=storage_dir,
                now=now,
            )
            if not cutover.get("proceed"):
                conflict_reason = _reconcile_legacy_conflict(
                    item,
                    provisional_ledger,
                    cutover,
                    storage_dir=storage_dir,
                    now=now,
                )
                _write_json(ledger_path, provisional_ledger)
                skipped.append({"id": item.get("id"), "reason": conflict_reason})
                continue
            materialized = _materialize_task(item, storage_dir=storage_dir, now=now)
            for key in (
                "receipt_task_id",
                "receipt_task_ids",
                "legacy_receipt_disposition",
                "legacy_receipt_dispositions",
            ):
                if provisional_ledger.get(key):
                    materialized["ledger"][key] = provisional_ledger[key]
            if provisional_ledger.get("receipt_task_id"):
                _write_json(ledger_path, materialized["ledger"])
            if materialized.get("reason") == "reaction_already_covered":
                skipped.append(
                    {
                        "id": item.get("id"),
                        "reason": "reaction_already_covered",
                        "covered_by": materialized.get("covered_by"),
                    }
                )
            else:
                created.append(materialized)
    return {
        "generated_at": now.isoformat(),
        "created": created,
        "skipped": skipped,
        "expired_tasks": expired_tasks,
        "removed_ledgers": removed_ledgers,
    }
