from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import get_runtime_schedules_path, load_runtime_schedules

_TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _expand_cron_field(
    raw: str,
    *,
    min_value: int,
    max_value: int,
    normalize_sunday: bool = False,
) -> set[int]:
    values: set[int] = set()
    field = str(raw or "").strip()
    if not field:
        raise ValueError("empty cron field")
    if field == "?":
        field = "*"

    def normalize(value: int) -> int:
        if normalize_sunday and value == 7:
            return 0
        return value

    upper_bound = 7 if normalize_sunday and max_value == 6 else max_value
    for part in field.split(","):
        token = part.strip()
        if not token:
            continue
        if "/" in token:
            base, step_raw = token.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError(f"invalid cron step: {token}")
        else:
            base, step = token, 1

        if base in ("", "*"):
            start, end = min_value, upper_bound
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start, end = int(start_raw), int(end_raw)
        else:
            start = end = int(base)

        if start < min_value or end > upper_bound or start > end:
            raise ValueError(f"cron field out of range: {raw}")
        values.update(normalize(value) for value in range(start, end + 1, step))

    return values


def cron_matches_date(cron_expr: str, target_date: date) -> bool:
    """Return whether a standard 5-field cron can fire on target_date.

    This is a date-level guard for missed-fire triage. It intentionally answers
    "could this job fire on that local date?" before anyone manually reruns a job.
    """
    parts = str(cron_expr or "").split()
    if len(parts) != 5:
        raise ValueError(f"expected 5-field cron expression, got: {cron_expr!r}")

    minute_values = _expand_cron_field(parts[0], min_value=0, max_value=59)
    hour_values = _expand_cron_field(parts[1], min_value=0, max_value=23)
    day_values = _expand_cron_field(parts[2], min_value=1, max_value=31)
    month_values = _expand_cron_field(parts[3], min_value=1, max_value=12)
    dow_values = _expand_cron_field(
        parts[4],
        min_value=0,
        max_value=6,
        normalize_sunday=True,
    )
    if not minute_values or not hour_values:
        return False
    if target_date.month not in month_values:
        return False

    day_of_month_matches = target_date.day in day_values
    cron_dow = (target_date.weekday() + 1) % 7  # Python Monday=0; cron Sunday=0/7.
    day_of_week_matches = cron_dow in dow_values
    dom_restricted = parts[2].strip() not in ("*", "?")
    dow_restricted = parts[4].strip() not in ("*", "?")

    if dom_restricted and dow_restricted:
        return day_of_month_matches or day_of_week_matches
    if dom_restricted:
        return day_of_month_matches
    if dow_restricted:
        return day_of_week_matches
    return True


def _iter_schedule_items(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for section_name, section in config.items():
        if isinstance(section, dict) and isinstance(section.get("items"), list):
            items.extend(
                (section_name, item)
                for item in section["items"]
                if isinstance(item, dict)
            )
    if isinstance(config.get("cron_jobs"), list):
        items.extend(
            ("cron_jobs", item)
            for item in config["cron_jobs"]
            if isinstance(item, dict)
        )
    return items


def get_job_cron(job_id: str, *, config: dict[str, Any] | None = None) -> str | None:
    """Canonical cron expression for a scheduled job id, or None if absent.

    Single source of truth for "when is job X expected to fire". Monitors and
    freshness checks MUST resolve cron here instead of hardcoding expressions in
    their own tables.

    2026-06-28 root cause: scripts/cron_review.py hardcoded daily_update's cron
    as '0 6 * * *' (daily 06:00) while canonical is '3 8 * * 1-6' (Mon-Sat
    08:03), false-flagging every Sunday as a ~22h missed run. health.py hardcoded
    the same 08:03/Mon-Sat assumption as module constants. Both now derive from
    here, so a single config edit can never silently drift the monitors again.
    """
    config = config if config is not None else load_runtime_schedules()
    for _section, item in _iter_schedule_items(config):
        if str(item.get("id") or "") == job_id:
            cron = item.get("cron") or item.get("schedule")
            if isinstance(cron, str) and cron.strip():
                return cron.strip()
            return None
    return None


def previous_scheduled_fire(
    cron_expr: str,
    *,
    now: datetime | None = None,
    tz: tzinfo | None = None,
    grace_hours: float = 0.0,
) -> datetime:
    """Most recent scheduled fire of `cron_expr` that is >= grace_hours before now.

    Returns a tz-aware datetime in `tz` (default Asia/Taipei). Uses croniter so
    day-of-week restrictions (e.g. Mon-Sat `1-6`) are honoured: on a Sunday the
    previous fire of a Mon-Sat schedule correctly resolves to the prior Saturday.
    Raises ImportError if croniter is unavailable (callers on the alert path
    should catch and fall back rather than crash).
    """
    from croniter import croniter

    tz = tz or _TAIPEI_TZ
    anchor = (now or datetime.now(tz)).astimezone(tz) - timedelta(hours=grace_hours)
    prev = croniter(cron_expr, anchor).get_prev(datetime)
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=tz)
    return prev.astimezone(tz)


def build_schedule_due_report(
    job_id: str,
    *,
    target_date: str | date | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config if config is not None else load_runtime_schedules()
    if target_date is None:
        local_date = datetime.now(_TAIPEI_TZ).date()
    elif isinstance(target_date, date) and not isinstance(target_date, datetime):
        local_date = target_date
    else:
        local_date = date.fromisoformat(str(target_date))

    matches = [
        (section, item)
        for section, item in _iter_schedule_items(config)
        if str(item.get("id") or "") == job_id
    ]
    if not matches:
        raise ValueError(f"schedule job not found: {job_id}")

    section, item = matches[0]
    cron_expr = item.get("cron") or item.get("schedule")
    if not isinstance(cron_expr, str) or not cron_expr.strip():
        scheduled = None
        reason = "schedule item has no cron/schedule expression"
    else:
        scheduled = cron_matches_date(cron_expr, local_date)
        reason = (
            f"{local_date.isoformat()} ({local_date.strftime('%A')}) "
            f"{'matches' if scheduled else 'does not match'} cron {cron_expr!r}"
        )

    return {
        "job_id": job_id,
        "found": True,
        "matched_items": len(matches),
        "section": section,
        "cron": cron_expr,
        "date": local_date.isoformat(),
        "timezone": "Asia/Taipei",
        "scheduled": scheduled,
        "reason": reason,
        "log_path": item.get("log_path") or item.get("log"),
        "label": item.get("label"),
    }


def _parse_crontab(raw: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in raw.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        parts = trimmed.split()
        if len(parts) < 6:
            continue
        items.append(
            {
                "cron": " ".join(parts[:5]),
                "command": " ".join(parts[5:]),
                "raw": trimmed,
            }
        )
    return items


def read_system_crontab() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            check=True,
            capture_output=True,
            text=True,
        )
        raw = f"{result.stdout}{result.stderr}".strip()
        return {
            "available": True,
            "items": _parse_crontab(raw),
            "note": "Live `crontab -l` read succeeded.",
        }
    except Exception as exc:
        return {
            "available": False,
            "items": [],
            "note": f"Unable to read live `crontab -l`: {exc}",
        }


def build_schedule_report() -> dict[str, Any]:
    config = load_runtime_schedules()
    system_spec_items = config.get("system_crontab", {}).get("items", [])
    session_items = config.get("session_crons", {}).get("items", [])
    remote_items = config.get("remote_triggers", {}).get("items", [])
    live = read_system_crontab()

    matched: list[str] = []
    missing: list[str] = []
    for item in system_spec_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("id") or "unknown")
        matchers = item.get("matchers") or []
        if not isinstance(matchers, list):
            matchers = []
        has_match = any(
            any(str(matcher) in crontab_item.get("command", "") for matcher in matchers)
            for crontab_item in live["items"]
        )
        if has_match:
            matched.append(label)
        else:
            missing.append(label)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_path": str(get_runtime_schedules_path()),
        "session_cron_count": len(session_items),
        "remote_trigger_count": len(remote_items),
        "expected_system_task_count": len(system_spec_items),
        "matched_system_tasks": matched,
        "missing_system_tasks": missing,
        "live_system_crontab_available": live["available"],
        "live_system_crontab_count": len(live["items"]),
        "live_system_crontab_note": live["note"],
        "system_crontab_items": live["items"],
    }
