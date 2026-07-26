from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import (
    get_project_root,
    get_runtime_schedules_path,
    load_runtime_schedules,
)

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
    operations_core_policy = None
    if "schedule_materialization" in config:
        from volpred.ops.schedule_materialization import load_schedule_policy

        operations_core_policy = load_schedule_policy(config)
    # This report compares canonical items with the live *host crontab* only.
    # LaunchAgent/piggy-back owners deliberately set host_crontab_managed=false;
    # counting them here as missing produces a false schedule-drift alarm.
    host_spec_items = [
        item
        for item in system_spec_items
        if isinstance(item, dict) and item.get("host_crontab_managed") is not False
        and (
            operations_core_policy is None
            or operations_core_policy.owner_for(str(item.get("id") or ""))
            != "operations_core"
        )
    ]
    session_items = config.get("session_crons", {}).get("items", [])
    remote_items = config.get("remote_triggers", {}).get("items", [])
    live = read_system_crontab()

    matched: list[str] = []
    missing: list[str] = []
    for item in host_spec_items:
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
        "expected_system_task_count": len(host_spec_items),
        "matched_system_tasks": matched,
        "missing_system_tasks": missing,
        "live_system_crontab_available": live["available"],
        "live_system_crontab_count": len(live["items"]),
        "live_system_crontab_note": live["note"],
        "system_crontab_items": live["items"],
    }


# ── Job liveness single source (WS-D1, refactor_plan_ops_master_2026_07) ─────
#
# `storage/ops/cron_last_run.json` records exit-0 SUCCESS markers stamped by
# (a) run_due_jobs piggy-back fires and (b) wrappers sourcing scripts/cron_lib.sh.
# It is NOT a universal liveness source: a launchd-direct job
# (`host_crontab_managed: false`) whose wrapper does not self-report never
# refreshes there — `daily_update` sat frozen at 2026-04-25 for ~3 months while
# running healthy every morning (banner `exit 0` fresh in its execution log).
# Every monitor that judged liveness from the marker alone therefore misread a
# live job as dead, and each reader grew its own partial log-fallback patch.
#
# This block is the ONLY sanctioned way to answer "when did job X last
# run/succeed". Readers (check_alerts staleness, ops_dashboard, cron_review,
# work_dashboard_server, generate_diverse_tasks) must resolve evidence through
# `job_liveness()` instead of reading the marker file / log mtimes ad hoc
# (anti-stacking: one enforcement owner for the evidence merge).

CRON_MARKER_PATH = get_project_root() / "storage" / "ops" / "cron_last_run.json"
SCHEDULE_RECEIPT_PATH = (
    get_project_root() / "storage" / "ops" / "schedule_receipts.json"
)
CRON_MARKER_META_KEY = "_meta"
CRON_MARKER_SCOPE = "piggyback-and-cron_lib-self-report-only"

# Exit banner emitted by scripts/cron_lib.sh::cron_emit_exit and by bespoke
# wrappers (e.g. cron_daily_update.sh):  === [job] exit 0 at <ts> (duration=…) ===
_EXIT_BANNER_RE = re.compile(
    r"===\s*\[[^\]]+\]\s+exit\s+(?P<code>-?\d+)\s+at\s+"
    r"(?P<ts>"
    r"\d{4}-\d{2}-\d{2}T\S+"
    r"|"
    r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\s+CST)?"
    r")"
)
_LOG_TAIL_BYTES = 65536


@dataclass(frozen=True)
class JobLiveness:
    """Merged run evidence for one scheduled job.

    - `last_success`: freshest exit-0 evidence — max(marker, log exit-0 banner).
    - `last_activity`: freshest any-outcome evidence — max(last_success, log
      mtime). Use for "did it fire" displays; keep `last_success` for staleness
      alerting so a job that fires but always fails still goes stale (the
      marker's contract).
    """

    job_id: str
    marker_eligible: bool
    marker_raw: str | None
    marker_at: datetime | None
    schedule_receipt_at: datetime | None
    schedule_receipt_fire_key: str | None
    banner_at: datetime | None
    log_mtime: datetime | None
    log_path: Path | None
    last_success: datetime | None
    success_source: str | None  # operations_core_receipt | piggyback_marker | log_banner
    last_activity: datetime | None


def load_cron_marker_state(path: Path | None = None) -> dict[str, str]:
    """Canonical reader of cron_last_run.json (drops `_`-prefixed meta keys).

    Corrupt / missing file → {} plus, for corruption, a diagnostics warn — the
    liveness merge then falls back to execution-log evidence rather than
    crashing every monitor at once.
    """
    marker_path = path or CRON_MARKER_PATH
    if not marker_path.exists():
        return {}
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        from volpred.ops.diagnostics import warn

        warn("schedules", "cron_last_run read failed; markers unavailable",
             path=str(marker_path), err=f"{type(exc).__name__}: {exc}")
        return {}
    if not isinstance(data, dict):
        from volpred.ops.diagnostics import warn

        warn("schedules", "cron_last_run schema is not an object; markers unavailable",
             path=str(marker_path))
        return {}
    return {
        key: value
        for key, value in data.items()
        if isinstance(key, str) and not key.startswith("_")
    }


def load_schedule_receipt_success(
    path: Path | None = None,
) -> dict[str, tuple[datetime, str]]:
    """Freshest successful Operations Core receipt per job.

    ``schedule_receipts.json`` is stronger evidence than wrapper-internal
    markers or log parsing: it is written by the owner that claimed the exact
    fire and contains the fenced generation/fire identity.  Failed, timed-out,
    claimed, and running attempts never count as success.
    """
    receipt_path = path or SCHEDULE_RECEIPT_PATH
    if not receipt_path.exists():
        return {}
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        from volpred.ops.diagnostics import warn

        warn(
            "schedules",
            "schedule receipt ledger read failed; receipt evidence unavailable",
            path=str(receipt_path),
            err=f"{type(exc).__name__}: {exc}",
        )
        return {}
    fires = payload.get("fires") if isinstance(payload, dict) else None
    if not isinstance(fires, dict):
        from volpred.ops.diagnostics import warn

        warn(
            "schedules",
            "schedule receipt ledger schema invalid; receipt evidence unavailable",
            path=str(receipt_path),
        )
        return {}
    latest: dict[str, tuple[datetime, str]] = {}
    for fire_key, record in fires.items():
        if not isinstance(record, dict) or record.get("state") != "succeeded":
            continue
        job_id = record.get("job_id")
        finished_at = _parse_marker_ts(record.get("finished_at"))
        if not isinstance(job_id, str) or not job_id or finished_at is None:
            continue
        previous = latest.get(job_id)
        if previous is None or finished_at > previous[0]:
            latest[job_id] = (finished_at, str(fire_key))
    return latest


def marker_eligible(item: dict[str, Any]) -> bool:
    """Is cron_last_run a *live* source for this job?

    Mirrors the run_due_jobs dispatch predicate: `host_crontab_managed: false`
    jobs are never piggy-back fired unless they opt back in with
    `piggy_back_enabled: true`. (A self-reporting wrapper may still stamp a
    marker for an ineligible job — `job_liveness` treats any present marker as
    genuine success evidence but never as the *only* source for such jobs.)
    """
    managed = item.get("host_crontab_managed")
    return not (managed is False and item.get("piggy_back_enabled") is not True)


def _parse_marker_ts(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:  # silent-ok: caller keeps marker_raw and surfaces it loudly (evaluate_cron_staleness unparsable_marker verdict + WARN; gdt log-fallback WARN)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_banner_ts(raw: str) -> datetime | None:
    """Parse a wrapper banner timestamp (`2026-07-20T08:08:09+0800`, UTC ISO,
    bespoke ``2026-07-20 08:08:09 CST``, or naive local) → aware UTC.

    The host's ``date %Z`` renders Asia/Taipei as the ambiguous abbreviation
    ``CST``.  Wrapper receipts are explicitly host-local, so strip that display
    suffix and apply the canonical host timezone rather than interpreting it as
    North American Central time.
    """
    candidate = raw.strip().rstrip(",;")
    if candidate.endswith(" CST"):
        candidate = candidate.removesuffix(" CST")
    m = re.match(r"(.*[+-]\d{2})(\d{2})$", candidate)
    if m:  # +0800 → +08:00 (fromisoformat on older interpreters)
        candidate = f"{m.group(1)}:{m.group(2)}"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:  # silent-ok: probe — non-timestamp token means try the next banner line; log mtime remains the activity floor either way
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_TAIPEI_TZ)  # wrappers log in host-local time
    return parsed.astimezone(timezone.utc)


def _resolve_log_path(item: dict[str, Any], repo_root: Path) -> Path | None:
    raw = item.get("log_path") or item.get("log")
    if not raw or not isinstance(raw, str):
        return None
    expanded = Path(raw).expanduser()
    return expanded if expanded.is_absolute() else repo_root / expanded


def _log_evidence(log_path: Path | None) -> tuple[datetime | None, datetime | None]:
    """(last exit-0 banner ts, log mtime) from the tail of the execution log."""
    if log_path is None or not log_path.exists():
        return None, None
    if not log_path.is_file():
        from volpred.ops.diagnostics import warn

        warn("schedules", "cron log path exists but is not a file; no log evidence",
             path=str(log_path))
        return None, None
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        mtime = None
    banner_at: datetime | None = None
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="ignore")
    except OSError as exc:
        from volpred.ops.diagnostics import warn

        warn("schedules", "cron log tail read failed; banner evidence unavailable",
             path=str(log_path), err=f"{type(exc).__name__}: {exc}")
        return None, mtime
    for line in reversed(tail.splitlines()):
        m = _EXIT_BANNER_RE.search(line)
        if m is None:
            continue
        if m.group("code") != "0":
            continue  # success evidence only; failures must be allowed to go stale
        banner_at = _parse_banner_ts(m.group("ts"))
        if banner_at is not None:
            break
    return banner_at, mtime


def job_liveness(
    item: dict[str, Any],
    *,
    marker_state: dict[str, str] | None = None,
    receipt_state: dict[str, tuple[datetime, str]] | None = None,
    repo_root: Path | None = None,
) -> JobLiveness:
    """Merge marker + execution-log evidence for one schedule item.

    `item` is a `system_crontab.items` entry (or a synthetic dict with at least
    `id`, optionally `log_path` / `host_crontab_managed` / `piggy_back_enabled`).
    Pass a preloaded `marker_state` when evaluating many jobs; omit it to read
    the canonical marker file.
    """
    root = repo_root or get_project_root()
    job_id = str(item.get("id") or "")
    state = marker_state if marker_state is not None else load_cron_marker_state()
    raw = state.get(job_id)
    marker_raw = raw if isinstance(raw, str) else None
    marker_at = _parse_marker_ts(marker_raw)
    receipts = (
        receipt_state
        if receipt_state is not None
        else load_schedule_receipt_success(
            root / "storage" / "ops" / "schedule_receipts.json"
        )
    )
    receipt = receipts.get(job_id)
    schedule_receipt_at = receipt[0] if receipt is not None else None
    schedule_receipt_fire_key = receipt[1] if receipt is not None else None
    banner_at, log_mtime = _log_evidence(_resolve_log_path(item, root))

    success_candidates = [
        (schedule_receipt_at, "operations_core_receipt"),
        (marker_at, "piggyback_marker"),
        (banner_at, "log_banner"),
    ]
    last_success, success_source = None, None
    for ts, source in success_candidates:
        if ts is not None and (last_success is None or ts > last_success):
            last_success, success_source = ts, source

    activity_candidates = [ts for ts in (last_success, log_mtime) if ts is not None]
    last_activity = max(activity_candidates) if activity_candidates else None

    return JobLiveness(
        job_id=job_id,
        marker_eligible=marker_eligible(item),
        marker_raw=marker_raw,
        marker_at=marker_at,
        schedule_receipt_at=schedule_receipt_at,
        schedule_receipt_fire_key=schedule_receipt_fire_key,
        banner_at=banner_at,
        log_mtime=log_mtime,
        log_path=_resolve_log_path(item, root),
        last_success=last_success,
        success_source=success_source,
        last_activity=last_activity,
    )
