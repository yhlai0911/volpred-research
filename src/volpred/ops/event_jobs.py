from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import get_optional_schedule_items, load_runtime_schedules

from .common import project_path
from .local_control_plane import create_task
from .shared_lock import shared_state_lock


def _storage_root(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "ops")


def _event_ledger_root(storage_dir: str = "storage") -> Path:
    root = _storage_root(storage_dir) / "event_ledger"
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


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _event_status(item: dict[str, Any], *, now: datetime) -> str:
    not_before = _coerce_datetime(item.get("not_before"))
    deadline = _coerce_datetime(item.get("deadline"))
    if deadline and now > deadline:
        return "expired"
    if not_before and now < not_before:
        return "pending"
    return "due"


def _materialize_task(item: dict[str, Any], *, storage_dir: str, now: datetime) -> dict[str, Any]:
    template = item.get("task_template") or {}
    if not isinstance(template, dict):
        raise RuntimeError(f"event_jobs task_template must be an object: {item.get('id')}")
    payload_patch = template.get("payload_patch") or {}
    if not isinstance(payload_patch, dict):
        raise RuntimeError(f"event_jobs payload_patch must be an object: {item.get('id')}")

    payload = dict(payload_patch)
    payload.setdefault("event_key", item.get("event_key"))
    payload.setdefault("event_job_id", item.get("id"))
    payload.setdefault("preconditions", template.get("preconditions") or [])

    task = create_task(
        title=str(template.get("title") or item.get("id") or "event-task"),
        description=str(template.get("description") or ""),
        source="schedule",
        task_family=str(template.get("task_family") or "ops"),
        priority=int(template.get("priority") or 100),
        preferred_agent=str(template.get("preferred_agent") or item.get("preferred_agent") or "auto"),
        fallback_allowed=bool(template.get("fallback_allowed", False)),
        approval_mode=str(template.get("approval_mode") or "auto"),
        risk_level=str(template.get("risk_level") or "safe"),
        public_effect=str(template.get("public_effect") or item.get("public_effect") or "none"),
        payload=payload,
        created_by="event_expander",
        storage_dir=storage_dir,
    )
    deadline = _coerce_datetime(item.get("deadline"))
    gc_after = (deadline or now) + timedelta(days=7)
    ledger = {
        "dedupe_key": str(item.get("dedupe_key") or ""),
        "event_key": str(item.get("event_key") or ""),
        "task_family": str(template.get("task_family") or ""),
        "task_id": task["id"],
        "materialized_at": now.isoformat(),
        "deadline": deadline.isoformat() if deadline else None,
        "gc_after": gc_after.isoformat(),
    }
    _write_json(_ledger_path(str(item.get("dedupe_key") or ""), storage_dir=storage_dir), ledger)
    return {"task": task, "ledger": ledger}


def gc_event_ledger(*, storage_dir: str = "storage", now: datetime | None = None) -> list[str]:
    now = now or _utc_now()
    removed: list[str] = []
    with shared_state_lock("event_ledger", storage_dir=storage_dir):
        for path in sorted(_event_ledger_root(storage_dir).glob("*.json")):
            payload = _read_json(path)
            if payload is None:
                continue
            gc_after = _coerce_datetime(payload.get("gc_after"))
            if gc_after and now > gc_after:
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
                "task_id": ledger.get("task_id") if ledger else None,
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
    removed_ledgers = gc_event_ledger(storage_dir=storage_dir, now=now)
    with shared_state_lock("event_ledger", storage_dir=storage_dir):
        for item in _event_items():
            dedupe_key = str(item.get("dedupe_key") or "")
            if not dedupe_key:
                skipped.append({"id": item.get("id"), "reason": "missing_dedupe_key"})
                continue
            status = _event_status(item, now=now)
            if status != "due":
                skipped.append({"id": item.get("id"), "reason": status})
                continue
            if _ledger_path(dedupe_key, storage_dir=storage_dir).exists():
                skipped.append({"id": item.get("id"), "reason": "already_materialized"})
                continue
            created.append(_materialize_task(item, storage_dir=storage_dir, now=now))
    return {
        "generated_at": now.isoformat(),
        "created": created,
        "skipped": skipped,
        "removed_ledgers": removed_ledgers,
    }
