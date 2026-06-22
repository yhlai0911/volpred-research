"""Supervisor observability aggregator.

Surface historical work distribution, feed rhythm, followup backlog and
token-usage trend so T1 supervisor can make informed rotation decisions
instead of only seeing current queue state.

Layer-1 of the supervisor observability upgrade (L1 in 2026-04-18 design).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .local_control_plane import (
    list_tasks as _list_tasks,
    list_pending_curations as _list_pending_curations,
)


_RULES_PATH_DEFAULT = "config/supervisor_rules.json"


def _warn_supervisor(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[ops_supervisor] WARN {message} "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def load_supervisor_rules(path: str = _RULES_PATH_DEFAULT) -> dict[str, Any]:
    """Load supervisor decision rules from canonical config. Runtime read — any
    change to the JSON takes effect on the next supervisor tick without
    needing a session restart."""
    rules_path = Path(path)
    if not rules_path.exists():
        return {}
    try:
        return json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn_supervisor("supervisor rules read failed; using defaults", rules_path, exc)
        return {}


_ISO_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for fmt in _ISO_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _task_activity(tasks: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    by_family: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_worker: Counter[str] = Counter()
    by_day: dict[str, dict[str, int]] = {}
    cycle_hours: list[float] = []
    recent_tasks = 0

    for task in tasks:
        finished = _parse_ts(task.get("finished_at"))
        claimed = _parse_ts(task.get("claimed_at"))
        reference_ts = finished or _parse_ts(task.get("updated_at"))
        if reference_ts is None or reference_ts < cutoff:
            continue
        recent_tasks += 1
        family = str(task.get("task_family") or "unknown")
        source = str(task.get("source") or "unknown")
        status = str(task.get("status") or "unknown")
        worker = str(task.get("claimed_by_session_key") or task.get("claimed_by") or "unassigned")
        by_family[family] += 1
        by_source[source] += 1
        by_status[status] += 1
        by_worker[worker] += 1
        day_key = reference_ts.astimezone(timezone.utc).date().isoformat()
        day_bucket = by_day.setdefault(day_key, {"succeeded": 0, "failed": 0, "other": 0})
        if status == "succeeded":
            day_bucket["succeeded"] += 1
        elif status == "failed":
            day_bucket["failed"] += 1
        else:
            day_bucket["other"] += 1
        if finished and claimed:
            cycle_hours.append((finished - claimed).total_seconds() / 3600.0)

    avg_cycle = sum(cycle_hours) / len(cycle_hours) if cycle_hours else None
    return {
        "total_tasks_in_window": recent_tasks,
        "by_family": dict(by_family),
        "by_source": dict(by_source),
        "by_status": dict(by_status),
        "by_worker": dict(by_worker),
        "by_day": dict(sorted(by_day.items())),
        "avg_cycle_hours": round(avg_cycle, 2) if avg_cycle is not None else None,
    }


def _curation_snapshot(storage_dir: str, cutoff: datetime) -> dict[str, Any]:
    pending = _list_pending_curations(storage_dir=storage_dir)
    if pending:
        oldest = pending[0]
        oldest_finished = oldest.get("finished_at") or oldest.get("updated_at")
    else:
        oldest_finished = None

    recently_curated = 0
    all_tasks = _list_tasks(storage_dir=storage_dir)
    for task in all_tasks:
        curated_ts = _parse_ts(task.get("curated_at"))
        if curated_ts and curated_ts >= cutoff:
            recently_curated += 1
    return {
        "pending_curations_count": len(pending),
        "oldest_pending_finished_at": oldest_finished,
        "recently_curated_in_window": recently_curated,
        "pending_sample": [
            {
                "id": task.get("id"),
                "title": (task.get("title") or "")[:80],
                "family": task.get("task_family"),
                "finished_at": task.get("finished_at"),
            }
            for task in pending[:5]
        ],
    }


def _followup_backlog(tasks: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    """Count followup_task_candidates surfaced by workers but not yet materialized.

    Conservative heuristic: a candidate is considered "unmaterialized" if no
    existing task title matches (case-insensitive substring of first 50 chars).
    L3 will replace this with a canonical followup_index; for now L1 uses this
    scan to give supervisor a rough backlog gauge.
    """
    existing_titles = {str(task.get("title") or "").strip().lower()[:50] for task in tasks if task.get("title")}
    candidates: list[dict[str, Any]] = []
    for task in tasks:
        finished = _parse_ts(task.get("finished_at"))
        if finished is None or finished < cutoff:
            continue
        signal = task.get("signal_payload") or {}
        if not isinstance(signal, dict):
            continue
        followups = signal.get("followup_task_candidates")
        if not isinstance(followups, list):
            continue
        for fup in followups:
            if not isinstance(fup, dict):
                continue
            title = str(fup.get("title") or "").strip()
            if not title:
                continue
            key = title.lower()[:50]
            if key in existing_titles:
                continue
            candidates.append(
                {
                    "source_task_id": task.get("id"),
                    "source_task_family": task.get("task_family"),
                    "title": title[:120],
                    "priority": fup.get("priority"),
                    "preferred_family": fup.get("preferred_family"),
                    "discovered_at": task.get("finished_at"),
                }
            )
    return {
        "unmaterialized_count": len(candidates),
        "sample": candidates[:10],
    }


def _feed_rhythm(storage_dir: str, cutoff: datetime) -> dict[str, Any]:
    feed_path = Path(storage_dir) / "reports" / "feed.json"
    if not feed_path.exists():
        return {"available": False}
    try:
        articles = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _warn_supervisor("feed rhythm read failed; marking unavailable", feed_path, exc)
        return {"available": False, "error": "feed.json unreadable"}
    if not isinstance(articles, list):
        return {"available": False, "error": "unexpected feed shape"}

    total_articles = len(articles)
    published = [a for a in articles if a.get("status") == "published"]
    drafts = [a for a in articles if a.get("status") == "draft"]
    scheduled = [a for a in articles if a.get("status") == "scheduled"]

    recent_published = []
    audience_counts: Counter[str] = Counter()
    for article in published:
        ts = _parse_ts(article.get("published_at"))
        if ts is None:
            continue
        if ts >= cutoff:
            recent_published.append(article)
            audience_counts[str(article.get("audience") or "unknown")] += 1

    last_publish_ts = None
    for article in published:
        ts = _parse_ts(article.get("published_at"))
        if ts is None:
            continue
        if last_publish_ts is None or ts > last_publish_ts:
            last_publish_ts = ts

    days_since_last = None
    if last_publish_ts is not None:
        delta = datetime.now(timezone.utc) - last_publish_ts
        days_since_last = round(delta.total_seconds() / 86400.0, 2)

    return {
        "available": True,
        "total_articles": total_articles,
        "published_total": len(published),
        "published_in_window": len(recent_published),
        "draft_count": len(drafts),
        "scheduled_count": len(scheduled),
        "last_publish_at": _iso(last_publish_ts) if last_publish_ts else None,
        "days_since_last_publish": days_since_last,
        "by_audience_in_window": dict(audience_counts),
    }


def _token_usage_trend(storage_dir: str, days: int) -> dict[str, Any]:
    report_dir = Path(storage_dir) / "reports" / "token_usage"
    if not report_dir.exists():
        return {"available": False}

    today = datetime.now(timezone.utc).date()
    trend: list[dict[str, Any]] = []
    total_cost = 0.0
    for offset in range(days):
        day = today - timedelta(days=offset)
        path = report_dir / f"daily_{day.isoformat()}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        totals = data.get("totals", {}) if isinstance(data, dict) else {}
        cost = float(totals.get("estimated_cost_usd", 0.0) or 0.0)
        total_cost += cost
        trend.append(
            {
                "date": day.isoformat(),
                "cost_usd": round(cost, 2),
                "billable_total": totals.get("billable_total"),
                "assistant_messages": totals.get("assistant_messages"),
            }
        )
    trend.sort(key=lambda row: row["date"])
    return {
        "available": bool(trend),
        "window_days": days,
        "total_cost_usd": round(total_cost, 2),
        "daily": trend,
    }


def _family_coverage_deficit(
    activity: dict[str, Any],
    window_days: int,
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Identify task families with low/no activity in window.

    Reads floors from `config/supervisor_rules.json` via `rules` argument;
    falls back to conservative defaults if config unavailable. Floors are
    runtime-mutable — editing the JSON takes effect on next tick.
    """
    fam_rules = rules.get("family_minimums", {}) if isinstance(rules, dict) else {}
    configured_window = int(fam_rules.get("window_days") or window_days)
    floors = fam_rules.get("floors") or {}
    if not isinstance(floors, dict) or not floors:
        floors = {
            "research": 3,
            "content": 2,
            "review": 2,
            "ops": 3,
            "member": 1,
            "code": 1,
            "strategy": 0,
            "paper": 1,
        }

    # Scale floors to actual window if caller requested a different days value
    if configured_window and configured_window != window_days and configured_window > 0:
        ratio = window_days / configured_window
        floors = {family: max(0, round(float(floor) * ratio)) for family, floor in floors.items()}

    caps = fam_rules.get("weekly_caps") or {}
    by_family = activity.get("by_family", {})
    deficit: list[dict[str, Any]] = []
    exceeded_caps: list[dict[str, Any]] = []
    for family, floor in floors.items():
        count = int(by_family.get(family, 0))
        floor_int = int(floor)
        if count < floor_int:
            deficit.append(
                {
                    "family": family,
                    "actual": count,
                    "floor": floor_int,
                    "gap": floor_int - count,
                }
            )
        cap = caps.get(family)
        if cap and int(cap) > 0 and count > int(cap):
            exceeded_caps.append(
                {
                    "family": family,
                    "actual": count,
                    "cap": int(cap),
                    "excess": count - int(cap),
                }
            )
    deficit.sort(key=lambda row: row["gap"], reverse=True)
    return {
        "window_days": window_days,
        "floors_source": "config/supervisor_rules.json" if fam_rules else "supervisor.py defaults (config missing)",
        "families_below_floor": deficit,
        "families_exceeding_cap": exceeded_caps,
    }


def build_supervisor_snapshot(
    *,
    days: int = 7,
    storage_dir: str = "storage",
    rules_path: str = _RULES_PATH_DEFAULT,
) -> dict[str, Any]:
    """One-stop observability payload for T1 supervisor.

    Aggregates task activity, curation state, followup backlog, feed
    publishing cadence, token usage trend, and family coverage deficit.
    Intentionally read-only; writes nothing to storage.

    Rules (floors, skill dispatch table, seed priorities) loaded from
    `config/supervisor_rules.json` at call time — edits to the config are
    picked up on the next invocation without restarting the session.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    tasks = _list_tasks(storage_dir=storage_dir)
    rules = load_supervisor_rules(rules_path)

    activity = _task_activity(tasks, cutoff)
    curation = _curation_snapshot(storage_dir, cutoff)
    followups = _followup_backlog(tasks, cutoff)
    feed = _feed_rhythm(storage_dir, cutoff)
    tokens = _token_usage_trend(storage_dir, days)
    deficit = _family_coverage_deficit(activity, days, rules)

    next_priority_families = [row["family"] for row in deficit.get("families_below_floor", [])]
    return {
        "generated_at": _iso(now),
        "window_days": days,
        "cutoff_utc": _iso(cutoff),
        "rules_config_path": rules_path,
        "rules_loaded": bool(rules),
        "task_activity": activity,
        "curation": curation,
        "followup_backlog": followups,
        "feed_rhythm": feed,
        "token_usage": tokens,
        "family_coverage_deficit": deficit,
        "supervisor_next_actions": {
            "prioritize_families": next_priority_families,
            "should_run_autotune": bool(next_priority_families) or curation["pending_curations_count"] > 3,
            "followup_materialization_pending": followups["unmaterialized_count"],
            "curation_backlog": curation["pending_curations_count"],
        },
    }
