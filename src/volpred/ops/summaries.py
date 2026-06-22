from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import csv
import sys
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import project_path
from .alerts import build_alert_condition_report
from .content import build_platform_cycle_summary
from .health import health_snapshot
from .local_control_plane import build_control_plane_snapshot
from .questions import get_member_question_ranking_summary
from .scheduler import get_scheduler_state, scheduler_preview
from .schedules import build_schedule_report


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _display_path(path: Path) -> str:
    root = project_path()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _warn_ops_summaries(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[ops_summaries] WARN {message} "
        f"path={_display_path(path)} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _compact_decision(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(decision, dict) or not decision:
        return None
    return {
        "task_id": decision.get("task_id"),
        "title": decision.get("title"),
        "agent": decision.get("agent"),
        "mode": decision.get("mode"),
        "brief_status": decision.get("brief_status"),
    }


def _runtime_idle_policy() -> dict[str, Any]:
    payload = _read_json_dict(project_path("config", "runtime_schedules.json")) or {}
    idle = payload.get("idle_policy") if isinstance(payload.get("idle_policy"), dict) else {}
    return {
        "source_label": idle.get("source_label"),
        "max_concurrent_agents": int(idle.get("max_concurrent_agents", 4) or 4),
    }


def build_queue_summary(storage_dir: str = "storage") -> dict[str, Any]:
    snapshot = build_control_plane_snapshot(storage_dir=storage_dir)
    preview = scheduler_preview(storage_dir=storage_dir)
    task_counts = snapshot.get("task_counts") if isinstance(snapshot.get("task_counts"), dict) else {}
    brief_counts = (
        snapshot.get("brief_status_counts")
        if isinstance(snapshot.get("brief_status_counts"), dict)
        else {}
    )
    scheduler = snapshot.get("scheduler") if isinstance(snapshot.get("scheduler"), dict) else {}
    agents = snapshot.get("agents") if isinstance(snapshot.get("agents"), list) else []
    active_agents = [
        str(agent.get("session_key") or agent.get("agent") or "unknown")
        for agent in agents
        if str(agent.get("status") or "offline") != "offline"
    ]
    queue_head: list[dict[str, Any]] = []
    for row in (preview.get("queue_snapshot") or [])[:3]:
        if not isinstance(row, dict):
            continue
        queue_head.append(
            {
                "task_id": row.get("task_id"),
                "title": row.get("title"),
                "target_agent": row.get("target_agent"),
                "brief_status": row.get("brief_status"),
                "runnable": row.get("runnable"),
                "blocked_reason": row.get("blocked_reason"),
            }
        )
    return {
        "generated_at": _generated_at(),
        "queued": int(task_counts.get("queued", 0) or 0),
        "running": int(task_counts.get("running", 0) or 0),
        "blocked": int(task_counts.get("blocked", 0) or 0),
        "succeeded": int(task_counts.get("succeeded", 0) or 0),
        "failed": int(task_counts.get("failed", 0) or 0),
        "brief_ready": int(brief_counts.get("ready", 0) or 0),
        "brief_pending": int(brief_counts.get("pending", 0) or 0),
        "pending_user_tasks": int(snapshot.get("pending_user_tasks", 0) or 0),
        "discovery_allowed": bool(snapshot.get("discovery_allowed")),
        "active_agents": active_agents,
        "scheduler_last_tick_at": scheduler.get("last_tick_at"),
        "scheduler_last_status": scheduler.get("last_status"),
        "next_decision": _compact_decision(preview.get("decision")),
        "queue_head": queue_head,
    }


def build_continue_task_maintenance(storage_dir: str = "storage") -> dict[str, Any]:
    snapshot = build_control_plane_snapshot(storage_dir=storage_dir)
    preview = scheduler_preview(storage_dir=storage_dir)
    idle_policy = _runtime_idle_policy()
    agents = snapshot.get("agents") if isinstance(snapshot.get("agents"), list) else []
    busy_agents = [
        str(agent.get("session_key") or agent.get("agent_name") or "unknown")
        for agent in agents
        if str(agent.get("status") or "offline") == "busy"
    ]
    max_concurrent_agents = int(idle_policy.get("max_concurrent_agents", 4) or 4)
    queued_count = int(preview.get("queued_count", 0) or 0)
    next_decision = _compact_decision(preview.get("decision"))
    queue_head = []
    for row in (preview.get("queue_snapshot") or [])[:3]:
        if not isinstance(row, dict):
            continue
        queue_head.append(
            {
                "task_id": row.get("task_id"),
                "title": row.get("title"),
                "target_agent": row.get("target_agent"),
                "runnable": row.get("runnable"),
                "blocked_reason": row.get("blocked_reason"),
                "brief_status": row.get("brief_status"),
            }
        )

    # 2026-04-29 architectural fix: integrate alert breach state into
    # heartbeat output. Previously `queued_count==0` returned skip=no_work
    # even when CRITICAL alerts (e.g. draft_pool=0, release_pool gap, member_qa
    # stale, host_cron_fail) were unaddressed → LLM main thread saw "no work"
    # and silent-skipped 7 consecutive slots while draft_pool=0 burned for ~10h.
    # Mission-critical alerts must surface as actionable, not be elided by
    # queue-only skip logic. See `docs/error_log.md` 2026-04-29 alert-action gap.
    alert_report = build_alert_condition_report(storage_dir=storage_dir)
    breached_alerts = [
        {
            "id": cond.get("id"),
            "level": cond.get("level"),
            "title": cond.get("title"),
            "body": cond.get("body", ""),
            "details": cond.get("details", {}),
        }
        for cond in alert_report.get("conditions", [])
        if cond.get("breached")
    ]
    critical_alert_count = sum(
        1 for a in breached_alerts if str(a.get("level") or "").lower() == "critical"
    )
    warn_alert_count = sum(
        1 for a in breached_alerts if str(a.get("level") or "").lower() == "warn"
    )
    has_actionable_alert = bool(breached_alerts)

    skip = False
    action = "review_next_task"
    reason = "dispatch_candidate"
    if len(busy_agents) >= max_concurrent_agents and next_decision is None:
        skip = True
        action = "skip"
        reason = "slot_full"
    elif has_actionable_alert and next_decision is None and queued_count == 0:
        # ALERT path: even with no formal queue work, breached alerts are
        # actionable (e.g. draft pool empty, release pool stalled). Do not
        # skip; LLM must inspect alerts and act.
        skip = False
        action = "address_alert"
        reason = (
            f"alert_breach_critical={critical_alert_count}_warn={warn_alert_count}"
        )
    elif queued_count == 0 and next_decision is None:
        skip = True
        action = "skip"
        reason = "no_work"
    elif next_decision is None:
        action = "inspect_queue"
        reason = "blocked_queue"

    followup_commands = _compact_command_list(
        "uv run volpred ops check-alerts" if has_actionable_alert else None,
        "uv run volpred ops queue-summary",
        "uv run volpred ops check-alerts" if (not skip and not has_actionable_alert) else None,
        "uv run volpred ops scheduler-summary" if not skip else None,
    )

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": action,
        "reason": reason,
        "needs_followup": not skip,
        "max_concurrent_agents": max_concurrent_agents,
        "busy_agents": busy_agents,
        "busy_agent_count": len(busy_agents),
        "queued_count": queued_count,
        "pending_user_tasks": int(snapshot.get("pending_user_tasks", 0) or 0),
        "discovery_allowed": bool(snapshot.get("discovery_allowed")),
        "next_decision": next_decision,
        "queue_head": queue_head,
        "alerts": {
            "breach_count": len(breached_alerts),
            "critical_count": critical_alert_count,
            "warn_count": warn_alert_count,
            "items": breached_alerts,
        },
        "followup_commands": followup_commands,
        "detail_hints": {
            "maintain": "uv run volpred ops continue-task-maintain --stub-if-no-work",
            "queue": "uv run volpred ops queue-summary",
            "scheduler": "uv run volpred ops scheduler-summary",
            "alerts": "uv run volpred ops check-alerts",
        },
        "policy": {
            "source_label": idle_policy.get("source_label"),
            "max_concurrent_agents": max_concurrent_agents,
        },
    }


def build_daily_planning_maintenance(
    storage_dir: str = "storage", *, source: str = "user", limit: int = 5
) -> dict[str, Any]:
    queue = build_queue_summary(storage_dir=storage_dir)
    scheduler = build_scheduler_summary(storage_dir=storage_dir)
    platform = build_platform_patrol_maintenance(storage_dir=storage_dir, source=source, limit=limit)

    reasons: list[str] = []
    if int(queue.get("pending_user_tasks", 0) or 0) > 0:
        reasons.append("pending_user_tasks")
    if int(queue.get("queued", 0) or 0) > 0:
        reasons.append("queued_tasks")
    if int(scheduler.get("missing_system_task_count", 0) or 0) > 0:
        reasons.append("scheduler_gap")
    for reason in (platform.get("trigger_reasons") or []):
        if isinstance(reason, str) and reason:
            reasons.append(f"platform:{reason}")

    skip = not reasons
    followup_commands = _compact_command_list(
        "uv run volpred ops queue-summary" if int(queue.get("queued", 0) or 0) > 0 else None,
        "uv run volpred ops scheduler-summary" if int(scheduler.get("missing_system_task_count", 0) or 0) > 0 else None,
        "uv run volpred ops platform-patrol-maintain --stub-if-no-work" if not platform.get("skip") else None,
    )

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "source": source,
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": "skip" if skip else "review_planning",
        "needs_followup": not skip,
        "trigger_reasons": reasons,
        "queue": {
            "queued": int(queue.get("queued", 0) or 0),
            "running": int(queue.get("running", 0) or 0),
            "pending_user_tasks": int(queue.get("pending_user_tasks", 0) or 0),
            "discovery_allowed": bool(queue.get("discovery_allowed")),
            "next_decision": queue.get("next_decision"),
            "queue_head": list(queue.get("queue_head") or [])[:3],
        },
        "scheduler": {
            "missing_system_task_count": int(scheduler.get("missing_system_task_count", 0) or 0),
            "missing_system_tasks": list(scheduler.get("missing_system_tasks") or [])[:5],
            "queued_count": int(scheduler.get("queued_count", 0) or 0),
            "last_tick_at": scheduler.get("scheduler_last_tick_at"),
            "last_status": scheduler.get("scheduler_last_status"),
        },
        "platform_gate": {
            "skip": bool(platform.get("skip")),
            "action": platform.get("action"),
            "trigger_reasons": list(platform.get("trigger_reasons") or []),
            "release_due": bool(platform.get("release_due")),
            "alert_breach_count": int(platform.get("alert_breach_count", 0) or 0),
            "pending_questions": int(platform.get("pending_questions", 0) or 0),
        },
        "followup_commands": followup_commands,
        "detail_hints": {
            "maintain": "uv run volpred ops daily-planning-maintain --stub-if-no-work",
            "queue": "uv run volpred ops queue-summary",
            "scheduler": "uv run volpred ops scheduler-summary",
            "platform": "uv run volpred ops platform-patrol-maintain --stub-if-no-work",
        },
    }


def build_scheduler_summary(storage_dir: str = "storage") -> dict[str, Any]:
    report = build_schedule_report()
    state = get_scheduler_state(storage_dir=storage_dir)
    preview = scheduler_preview(storage_dir=storage_dir)
    matched = report.get("matched_system_tasks") if isinstance(report.get("matched_system_tasks"), list) else []
    missing = report.get("missing_system_tasks") if isinstance(report.get("missing_system_tasks"), list) else []
    return {
        "generated_at": _generated_at(),
        "scheduler_last_tick_at": state.get("last_tick_at"),
        "scheduler_last_status": state.get("last_status"),
        "scheduler_last_reason": state.get("last_reason"),
        "expected_system_task_count": int(report.get("expected_system_task_count", 0) or 0),
        "matched_system_task_count": len(matched),
        "missing_system_task_count": len(missing),
        "missing_system_tasks": missing,
        "session_cron_count": int(report.get("session_cron_count", 0) or 0),
        "remote_trigger_count": int(report.get("remote_trigger_count", 0) or 0),
        "live_system_crontab_available": bool(report.get("live_system_crontab_available")),
        "live_system_crontab_count": int(report.get("live_system_crontab_count", 0) or 0),
        "queued_count": int(preview.get("queued_count", 0) or 0),
        "next_decision": _compact_decision(preview.get("decision")),
    }


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _compact_totals(totals: dict[str, Any] | None) -> dict[str, Any]:
    totals = totals if isinstance(totals, dict) else {}
    return {
        "estimated_cost_usd": float(totals.get("estimated_cost_usd", 0.0) or 0.0),
        "billable_total": int(totals.get("billable_total", 0) or 0),
        "cache_create_tokens": int(totals.get("cache_create_tokens", 0) or 0),
        "assistant_messages": int(totals.get("assistant_messages", 0) or 0),
        "unique_sessions": int(totals.get("unique_sessions", 0) or 0),
    }


def _iter_daily_reports(report_dir: Path) -> list[tuple[date, dict[str, Any]]]:
    rows: list[tuple[date, dict[str, Any]]] = []
    for path in report_dir.glob("daily_*.json"):
        try:
            report_date = date.fromisoformat(path.stem.removeprefix("daily_"))
        except ValueError as exc:
            _warn_ops_summaries(
                "token usage daily report date parse failed; skipping",
                path,
                exc,
            )
            continue
        payload = _read_json_dict(path)
        if payload is None:
            continue
        rows.append((report_date, payload))
    rows.sort(key=lambda row: row[0])
    return rows


def build_token_summary(storage_dir: str = "storage", *, days: int = 7) -> dict[str, Any]:
    report_dir = project_path(storage_dir, "reports", "token_usage")
    if not report_dir.exists():
        return {
            "generated_at": _generated_at(),
            "available": False,
            "rolling_window_days": max(days, 1),
            "daily_reports_available": 0,
        }

    daily_rows = _iter_daily_reports(report_dir)
    latest_daily = daily_rows[-1] if daily_rows else None
    latest_daily_date = latest_daily[0] if latest_daily else None
    rolling_days = max(days, 1)
    rolling_selected = (
        [
            row
            for row in daily_rows
            if row[0] >= latest_daily_date - timedelta(days=rolling_days - 1)
        ]
        if latest_daily_date is not None
        else []
    )
    rolling_cost = 0.0
    rolling_billable = 0
    rolling_cache_create = 0
    for _, payload in rolling_selected:
        totals = payload.get("totals") if isinstance(payload, dict) else {}
        rolling_cost += float(totals.get("estimated_cost_usd", 0.0) or 0.0)
        rolling_billable += int(totals.get("billable_total", 0) or 0)
        rolling_cache_create += int(totals.get("cache_create_tokens", 0) or 0)

    weekly_paths = sorted(report_dir.glob("weekly_*.json"))
    latest_weekly_path = weekly_paths[-1] if weekly_paths else None
    latest_weekly_payload = _read_json_dict(latest_weekly_path) if latest_weekly_path else None

    latest_daily_payload = latest_daily[1] if latest_daily else None
    return {
        "generated_at": _generated_at(),
        "available": bool(latest_daily_payload or latest_weekly_payload),
        "rolling_window_days": rolling_days,
        "daily_reports_available": len(daily_rows),
        "latest_daily": (
            {
                "date": latest_daily_date.isoformat() if latest_daily_date else None,
                **_compact_totals(latest_daily_payload.get("totals") if latest_daily_payload else {}),
            }
            if latest_daily_payload is not None
            else None
        ),
        "rolling_window": {
            "start_date": rolling_selected[0][0].isoformat() if rolling_selected else None,
            "end_date": rolling_selected[-1][0].isoformat() if rolling_selected else None,
            "report_count": len(rolling_selected),
            "estimated_cost_usd": round(rolling_cost, 4),
            "billable_total": rolling_billable,
            "cache_create_tokens": rolling_cache_create,
        },
        "latest_weekly": (
            {
                "week_start": latest_weekly_payload.get("week_start"),
                "week_end": latest_weekly_payload.get("week_end"),
                **_compact_totals(latest_weekly_payload.get("totals")),
            }
            if latest_weekly_payload is not None
            else None
        ),
    }


def _friday_week_range(target_date: date) -> tuple[date, date]:
    weekday = target_date.weekday()
    days_since_friday = (weekday - 4) % 7
    week_start = target_date - timedelta(days=days_since_friday)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def build_token_usage_maintenance(
    storage_dir: str = "storage",
    *,
    days: int = 7,
    target_date: date | None = None,
) -> dict[str, Any]:
    target = target_date or datetime.now(timezone.utc).date()
    report_dir = project_path(storage_dir, "reports", "token_usage")
    summary = build_token_summary(storage_dir=storage_dir, days=days)

    daily_path = report_dir / f"daily_{target.isoformat()}.json"
    week_start, week_end = _friday_week_range(target)
    weekly_path = report_dir / f"weekly_{week_start.isoformat()}.json"

    daily_exists = daily_path.exists()
    weekly_due = target.weekday() == 4
    weekly_exists = weekly_path.exists()

    actions: list[str] = []
    execution_commands: list[str] = []
    if not daily_exists:
        actions.append("generate_daily_report")
        execution_commands.append(
            f"uv run python scripts/token_usage_report.py --date {target.isoformat()}"
        )
    if weekly_due and not weekly_exists:
        actions.append("generate_weekly_report")
        execution_commands.append(
            f"uv run python scripts/token_usage_report.py --weekly --week-start {week_start.isoformat()}"
        )

    if not actions:
        action = "skip"
    elif len(actions) == 2:
        action = "generate_daily_and_weekly"
    else:
        action = actions[0]

    skip = not actions
    suggestions: list[str] = []
    if skip:
        suggestions.append("日報與本週週報都已就緒；維持低噪音 summary 巡檢即可。")
    else:
        if not daily_exists:
            suggestions.append("今日 token 日報尚未生成；先跑 daily report 再讀 summary。")
        if weekly_due and not weekly_exists:
            suggestions.append("今天是週五且本週週報缺失；補 weekly detail 後再看趨勢。")

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "target_date": target.isoformat(),
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": action,
        "needs_followup": not skip,
        "rolling_window_days": max(days, 1),
        "daily_report_exists": daily_exists,
        "daily_report_path": _display_path(daily_path),
        "weekly_due": weekly_due,
        "weekly_report_exists": weekly_exists,
        "weekly_report_path": _display_path(weekly_path),
        "week_start": week_start.isoformat(),
        "week_end_exclusive": week_end.isoformat(),
        "recommended_actions": actions,
        "execution_commands": execution_commands,
        "followup_commands": _compact_command_list(
            *execution_commands,
            "uv run volpred ops token-summary",
        ),
        "detail_hints": {
            "maintain": "uv run volpred ops token-usage-maintain --stub-if-no-work",
            "summary": "uv run volpred ops token-summary",
            "daily_report": f"uv run python scripts/token_usage_report.py --date {target.isoformat()}",
            "weekly_report": f"uv run python scripts/token_usage_report.py --weekly --week-start {week_start.isoformat()}",
        },
        "latest_daily": summary.get("latest_daily"),
        "latest_weekly": summary.get("latest_weekly"),
        "rolling_window": summary.get("rolling_window"),
        "suggestions": suggestions,
    }


def build_token_policy_summary(policy_path: str = "config/token_policy.json") -> dict[str, Any]:
    path = project_path(policy_path)
    payload = _read_json_dict(path)
    if payload is None:
        return {
            "generated_at": _generated_at(),
            "available": False,
            "path": _display_path(path),
        }

    context = payload.get("context_boundaries") if isinstance(payload.get("context_boundaries"), dict) else {}
    statusline = payload.get("statusline_colors") if isinstance(payload.get("statusline_colors"), dict) else {}
    session_health = payload.get("session_health") if isinstance(payload.get("session_health"), dict) else {}
    sources = payload.get("canonical_sources") if isinstance(payload.get("canonical_sources"), dict) else {}
    guidance = payload.get("guidance") if isinstance(payload.get("guidance"), dict) else {}

    normal_max = int(context.get("normal_max_pct", 55) or 55)
    compact_min = int(context.get("compact_min_pct", 62) or 62)
    clear_min = int(context.get("clear_min_pct", 70) or 70)
    compact_warn = int(statusline.get("compact_warn_pct", compact_min) or compact_min)
    warn_pct = int(statusline.get("warn_pct", 75) or 75)
    danger_pct = int(statusline.get("danger_pct", 90) or 90)

    return {
        "generated_at": _generated_at(),
        "available": True,
        "path": _display_path(path),
        "auto_compact_pct_override": int(payload.get("auto_compact_pct_override", compact_min) or compact_min),
        "context_boundaries": {
            "normal_max_pct": normal_max,
            "compact_min_pct": compact_min,
            "clear_min_pct": clear_min,
        },
        "statusline_colors": {
            "compact_warn_pct": compact_warn,
            "warn_pct": warn_pct,
            "danger_pct": danger_pct,
        },
        "session_health": {
            "lifetime_cost_usd": float(session_health.get("lifetime_cost_usd", 200.0) or 200.0),
            "lifetime_hours": float(session_health.get("lifetime_hours", 24.0) or 24.0),
            "cache_read_tokens": int(session_health.get("cache_read_tokens", 1_000_000_000) or 1_000_000_000),
            "messages": int(session_health.get("messages", 1500) or 1500),
            "active_window_minutes": int(session_health.get("active_window_minutes", 60) or 60),
        },
        "guidance": {
            "between_normal_and_compact": guidance.get("between_normal_and_compact"),
            "between_compact_and_clear": guidance.get("between_compact_and_clear"),
            "above_clear": guidance.get("above_clear"),
        },
        "canonical_sources": {
            "runtime_schedules": sources.get("runtime_schedules"),
            "workflow_index": sources.get("workflow_index"),
            "commands": sources.get("commands") if isinstance(sources.get("commands"), list) else [],
        },
        "policy_digest": {
            "direct_start_below_pct": normal_max,
            "compact_at_or_above_pct": compact_min,
            "clear_at_or_above_pct": clear_min,
            "statusline_colors": [compact_warn, warn_pct, danger_pct],
        },
    }


def build_git_sync_maintenance() -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=project_path(),
        capture_output=True,
        text=True,
    )

    branch_line = None
    entries: list[str] = []
    if completed.returncode == 0:
        lines = [line.rstrip("\n") for line in completed.stdout.splitlines() if line.strip()]
        if lines and lines[0].startswith("##"):
            branch_line = lines[0]
            entries = lines[1:]
        else:
            entries = lines

    branch = None
    upstream = None
    branch_state = branch_line[3:].strip() if isinstance(branch_line, str) else ""
    ahead = 0
    behind = 0
    upstream_gone = False
    if branch_state:
        branch = branch_state
        if "..." in branch_state:
            branch, remainder = branch_state.split("...", 1)
            branch = branch.strip()
            if " [" in remainder:
                upstream, detail = remainder.split(" [", 1)
                upstream = upstream.strip()
                detail = detail.rstrip("]").strip()
                if detail == "gone":
                    upstream_gone = True
                else:
                    for part in [item.strip() for item in detail.split(",") if item.strip()]:
                        if part.startswith("ahead "):
                            ahead = int(part.removeprefix("ahead ").strip() or 0)
                        elif part.startswith("behind "):
                            behind = int(part.removeprefix("behind ").strip() or 0)
            else:
                upstream = remainder.strip()

    changed_paths: list[dict[str, Any]] = []
    staged_count = 0
    unstaged_count = 0
    untracked_count = 0
    deleted_count = 0
    conflicted_count = 0
    for raw in entries:
        status = raw[:2]
        path = raw[3:] if len(raw) > 3 else raw
        x = status[0] if len(status) > 0 else " "
        y = status[1] if len(status) > 1 else " "
        if status == "??":
            untracked_count += 1
        if x not in {" ", "?"}:
            staged_count += 1
        if y not in {" ", "?"}:
            unstaged_count += 1
        if "D" in status:
            deleted_count += 1
        if "U" in status or status in {"AA", "DD"}:
            conflicted_count += 1
        changed_paths.append({"status": status, "path": path})

    diverged = ahead > 0 and behind > 0
    if completed.returncode != 0:
        action = "inspect_git_status"
        reason = "status_failed"
        skip = False
    elif conflicted_count > 0:
        action = "resolve_conflicts"
        reason = "merge_conflict"
        skip = False
    elif changed_paths:
        action = "review_changes"
        reason = "working_tree_dirty"
        skip = False
    elif upstream_gone:
        action = "inspect_upstream"
        reason = "upstream_missing"
        skip = False
    elif diverged or behind > 0:
        action = "pull_before_push"
        reason = "branch_not_synced"
        skip = False
    elif ahead > 0:
        action = "push_pending_commits"
        reason = "ahead_of_remote"
        skip = False
    else:
        action = "skip"
        reason = "clean"
        skip = True

    followup_commands = _compact_command_list(
        "git status --short --branch",
        "git diff --stat" if changed_paths else None,
        "git add <meaningful paths>" if changed_paths else None,
        'git commit -m "ops: sync meaningful changes"' if changed_paths else None,
        "git pull --no-rebase" if behind > 0 or diverged else None,
        "git push" if ahead > 0 or changed_paths else None,
    )

    return {
        "generated_at": _generated_at(),
        "repo_root": _display_path(project_path()),
        "available": completed.returncode == 0,
        "mode": "skip" if skip else ("error" if completed.returncode != 0 else "review"),
        "skip": skip,
        "action": action,
        "reason": reason,
        "needs_followup": not skip,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "diverged": diverged,
        "upstream_gone": upstream_gone,
        "working_tree_changes": len(changed_paths),
        "staged_count": staged_count,
        "unstaged_count": unstaged_count,
        "untracked_count": untracked_count,
        "deleted_count": deleted_count,
        "conflicted_count": conflicted_count,
        "changed_paths": changed_paths[:8],
        "followup_commands": followup_commands,
        "detail_hints": {
            "maintain": "uv run volpred ops git-sync-maintain --stub-if-no-work",
            "status": "git status --short --branch",
            "diff": "git diff --stat",
        },
        "stderr_tail": _tail_text_lines(completed.stderr, limit=4),
    }


_NDC_REQUIRED_ITEMS = {
    "leading_indicator": "景氣領先指標不含趨勢指數(點)",
    "signal_score": "景氣對策信號(分)",
}


def _parse_month_period(value: str | None) -> tuple[int, int] | None:
    if not isinstance(value, str) or "M" not in value:
        return None
    year_text, month_text = value.split("M", 1)
    try:
        year = int(year_text)
        month = int(month_text)
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return year, month


def _period_key(value: str | None) -> tuple[int, int] | None:
    parsed = _parse_month_period(value)
    return parsed


def _expected_ndc_period(target_date: date) -> str:
    month = target_date.month - 2
    year = target_date.year
    if month <= 0:
        month += 12
        year -= 1
    return f"{year}M{month:02d}"


def _latest_period_for_item(csv_path: Path, item_name: str) -> str | None:
    latest: tuple[int, int] | None = None
    latest_text: str | None = None
    with csv_path.open("r", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("item") != item_name:
                continue
            period = row.get("period")
            key = _period_key(period)
            if key is None:
                continue
            if latest is None or key > latest:
                latest = key
                latest_text = period
    return latest_text


def build_ndc_indicator_maintenance(
    storage_dir: str = "storage",
    *,
    target_date: date | None = None,
) -> dict[str, Any]:
    target = target_date or datetime.now(timezone.utc).date()
    csv_path = project_path(storage_dir, "macro", "tw_dgbas_bci_m.csv")
    expected_period = _expected_ndc_period(target)
    expected_key = _period_key(expected_period)

    if not csv_path.exists():
        return {
            "generated_at": _generated_at(),
            "storage_dir": _display_path(project_path(storage_dir)),
            "path": _display_path(csv_path),
            "target_date": target.isoformat(),
            "expected_period": expected_period,
            "mode": "review",
            "skip": False,
            "action": "manual_refresh",
            "reason": "csv_missing",
            "needs_followup": True,
            "available": False,
            "required_series": {},
            "stale_series_count": len(_NDC_REQUIRED_ITEMS),
            "followup_commands": _compact_command_list(
                "uv run python scripts/collect_ndc_bci.py --check",
                "uv run python scripts/collect_ndc_bci.py",
            ),
            "detail_hints": {
                "maintain": "uv run volpred ops ndc-indicator-maintain --stub-if-no-work",
                "check": "uv run python scripts/collect_ndc_bci.py --check",
                "collect": "uv run python scripts/collect_ndc_bci.py",
                "csv": _display_path(csv_path),
            },
            "suggestions": ["NDC canonical CSV 缺失；先檢查來源檔，再依現有 NDC 流程手動補資料。"],
        }

    required_series: dict[str, Any] = {}
    stale_keys: list[str] = []
    for key, item_name in _NDC_REQUIRED_ITEMS.items():
        latest_period = _latest_period_for_item(csv_path, item_name)
        latest_key = _period_key(latest_period)
        is_fresh = latest_key is not None and expected_key is not None and latest_key >= expected_key
        if not is_fresh:
            stale_keys.append(key)
        required_series[key] = {
            "item": item_name,
            "latest_period": latest_period,
            "fresh": is_fresh,
        }

    modified_at = datetime.fromtimestamp(csv_path.stat().st_mtime, timezone.utc).isoformat()
    skip = not stale_keys
    action = "skip" if skip else "manual_refresh"
    suggestions: list[str] = []
    if skip:
        suggestions.append("NDC 景氣指標 canonical CSV 已達預期月份；本月不需再展開手動更新。")
    else:
        stale_preview = ", ".join(
            f"{required_series[key]['item']}={required_series[key]['latest_period'] or 'missing'}"
            for key in stale_keys
        )
        suggestions.append(
            f"NDC canonical CSV 仍落後預期月份 {expected_period}；請先用 check 腳本確認缺口，再依現有人工流程補資料（{stale_preview}）。"
        )

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "path": _display_path(csv_path),
        "target_date": target.isoformat(),
        "expected_period": expected_period,
        "modified_at": modified_at,
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": action,
        "reason": "fresh" if skip else "stale_series",
        "needs_followup": not skip,
        "available": True,
        "required_series": required_series,
        "stale_series_count": len(stale_keys),
        "stale_series": stale_keys,
        "followup_commands": _compact_command_list(
            "uv run python scripts/collect_ndc_bci.py --check",
            "uv run python scripts/collect_ndc_bci.py" if not skip else None,
        ),
        "detail_hints": {
            "maintain": "uv run volpred ops ndc-indicator-maintain --stub-if-no-work",
            "check": "uv run python scripts/collect_ndc_bci.py --check",
            "collect": "uv run python scripts/collect_ndc_bci.py",
            "csv": _display_path(csv_path),
        },
        "suggestions": suggestions,
    }


def _tail_lines(path: Path, *, lines: int) -> list[str]:
    if lines <= 0:
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=lines)]


def _summarize_log_group(group_dir: Path, *, limit: int, tail_lines: int) -> dict[str, Any]:
    files = sorted(
        [path for path in group_dir.glob("*.log") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    entries: list[dict[str, Any]] = []
    for path in files[: max(limit, 0)]:
        stat = path.stat()
        entries.append(
            {
                "path": _display_path(path),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
                "tail": _tail_lines(path, lines=tail_lines),
            }
        )
    return {
        "count": len(files),
        "latest": entries,
    }


def build_log_summary(storage_dir: str = "storage", *, limit: int = 3, tail_lines: int = 3) -> dict[str, Any]:
    logs_dir = project_path(storage_dir, "logs")
    cron_dir = logs_dir / "cron"
    hooks_dir = logs_dir / "hooks"
    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "cron_logs": _summarize_log_group(cron_dir, limit=limit, tail_lines=tail_lines)
        if cron_dir.exists()
        else {"count": 0, "latest": []},
        "hook_logs": _summarize_log_group(hooks_dir, limit=limit, tail_lines=tail_lines)
        if hooks_dir.exists()
        else {"count": 0, "latest": []},
    }


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _knowledge_index_watch_files(storage_dir: str = "storage") -> list[Path]:
    storage_path = project_path(storage_dir)
    memory_dir = storage_path / "memory"
    files = list(sorted(memory_dir.glob("*.json")))
    files.append(storage_path / "reports" / "feed.json")
    files.append(project_path("research_program.md"))
    ref_dir = project_path(".claude", "skills", "autonomous-research", "references")
    if ref_dir.exists():
        files.extend(sorted(ref_dir.glob("*.md")))
    paper_complete = project_path("paper_complete.md")
    if paper_complete.exists():
        files.append(paper_complete)
    return [path for path in files if path.exists()]


def _knowledge_index_state(storage_dir: str = "storage") -> dict[str, Any]:
    state_path = project_path(storage_dir, ".knowledge_index_state.json")
    current = {
        path.name: path.stat().st_mtime
        for path in _knowledge_index_watch_files(storage_dir=storage_dir)
    }
    raw_saved = _read_json_value(state_path)
    saved = raw_saved if isinstance(raw_saved, dict) else {}
    changed = sorted([key for key, value in current.items() if saved.get(key) != value])
    removed = sorted([key for key in saved if key not in current])
    return {
        "path": state_path,
        "exists": state_path.exists(),
        "saved": saved,
        "current": current,
        "changed": changed,
        "removed": removed,
    }


def _sync_knowledge_index_state(storage_dir: str = "storage") -> dict[str, float]:
    state = _knowledge_index_state(storage_dir=storage_dir)
    state_path = state["path"]
    current = state["current"] if isinstance(state["current"], dict) else {}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return current


def _knowledge_index_table_summary(index_dir: Path) -> dict[str, Any]:
    try:
        import lancedb
    except Exception as exc:  # pragma: no cover - dependency import failure is environment-specific
        return {"available": False, "error": f"lancedb_import_failed: {exc}"}

    try:
        db = lancedb.connect(str(index_dir))
        # Robust against lancedb API drift: newer list_tables() returns a
        # paginated structure like [('tables', ['research_memory']),
        # ('page_token', None)], while older list_tables() / table_names()
        # return a flat list of strings. Skip the listing step entirely and
        # just attempt to open the table — that surfaces a real "table missing"
        # error without depending on the listing API shape.
        try:
            table = db.open_table("research_memory")
        except FileNotFoundError:
            return {"available": False, "error": "research_memory_table_missing"}
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "does not exist" in msg or "no such" in msg:
                return {"available": False, "error": "research_memory_table_missing"}
            raise
        frame = table.to_pandas()
    except Exception as exc:
        return {"available": False, "error": f"index_open_failed: {exc}"}

    source_counts = (
        frame["source"].value_counts().to_dict()
        if "source" in frame.columns
        else {}
    )
    top_sources = [
        {"source": str(source), "count": int(count)}
        for source, count in sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    return {
        "available": True,
        "total_entries": int(len(frame)),
        "top_sources": top_sources,
    }


def build_knowledge_index_summary(storage_dir: str = "storage") -> dict[str, Any]:
    storage_path = project_path(storage_dir)
    index_dir = storage_path / "knowledge_index"
    state = _knowledge_index_state(storage_dir=storage_dir)
    table = _knowledge_index_table_summary(index_dir) if index_dir.exists() else {"available": False, "error": "index_dir_missing"}

    saved = state["saved"] if isinstance(state["saved"], dict) else {}
    current = state["current"] if isinstance(state["current"], dict) else {}
    changed = state["changed"] if isinstance(state["changed"], list) else []
    removed = state["removed"] if isinstance(state["removed"], list) else []
    drift_detected = bool(changed or removed or current != saved)

    if not index_dir.exists() or not state["exists"]:
        status = "missing"
    elif not table.get("available"):
        status = "broken"
    elif drift_detected:
        status = "stale"
    else:
        status = "fresh"

    last_indexed_at = (
        datetime.fromtimestamp(max(saved.values()), timezone.utc).isoformat()
        if saved
        else None
    )
    latest_source_at = (
        datetime.fromtimestamp(max(current.values()), timezone.utc).isoformat()
        if current
        else None
    )

    recommended_action = "skip"
    recommended_command = None
    fallback_command = None
    if status in {"missing", "stale"}:
        recommended_action = "auto"
        recommended_command = "uv run python scripts/build_knowledge_index.py auto"
        fallback_command = "uv run python scripts/build_knowledge_index.py build"
    elif status == "broken":
        if table.get("error") == "research_memory_table_missing":
            recommended_action = "auto"
            recommended_command = "uv run python scripts/build_knowledge_index.py auto"
            fallback_command = "uv run python scripts/build_knowledge_index.py build"
        else:
            recommended_action = "build"
            recommended_command = "uv run python scripts/build_knowledge_index.py build"

    suggestions: list[str] = []
    if status == "missing":
        suggestions.append("知識索引或 state file 缺失；先跑 auto，必要時再 full build。")
    elif status == "broken":
        suggestions.append("知識索引存在但無法讀取；先看 recommended_action，再決定 auto 或 full build。")
    elif status == "stale":
        changed_preview = ", ".join((changed + removed)[:3])
        suggestions.append(f"偵測到索引 drift（{changed_preview or 'watched files changed'}）；先跑 auto，不要直接 full build。")
    else:
        suggestions.append("知識索引狀態新鮮；維持 summary-first 檢查即可。")

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(storage_path),
        "path": _display_path(index_dir),
        "state_file": _display_path(state["path"]),
        "status": status,
        "available": bool(table.get("available")),
        "drift_detected": drift_detected,
        "tracked_files": len(current),
        "changed_files_count": len(changed),
        "removed_files_count": len(removed),
        "changed_files": changed[:5],
        "removed_files": removed[:5],
        "last_indexed_at": last_indexed_at,
        "latest_source_at": latest_source_at,
        "index_size_bytes": _dir_size_bytes(index_dir),
        "index_size_mb": round(_dir_size_bytes(index_dir) / 1024 / 1024, 3),
        "total_entries": int(table.get("total_entries", 0) or 0),
        "top_sources": table.get("top_sources") if isinstance(table.get("top_sources"), list) else [],
        "error": table.get("error"),
        "recommended_action": recommended_action,
        "recommended_command": recommended_command,
        "fallback_command": fallback_command,
        "detail_hints": {
            "summary": "uv run volpred ops knowledge-index-summary",
            "maintain": "uv run volpred ops knowledge-index-maintain --stub-if-no-work",
            "auto": "uv run python scripts/build_knowledge_index.py auto",
            "build": "uv run python scripts/build_knowledge_index.py build",
            "update": "uv run python scripts/build_knowledge_index.py update",
            "stats": "uv run python scripts/build_knowledge_index.py stats",
        },
        "suggestions": suggestions,
    }


def _tail_text_lines(text: str, limit: int = 6) -> list[str]:
    if limit <= 0:
        return []
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def _compact_command_list(*commands: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for command in commands:
        if not isinstance(command, str) or not command.strip() or command in seen:
            continue
        seen.add(command)
        ordered.append(command)
    return ordered


def run_token_usage_maintenance(
    storage_dir: str = "storage",
    *,
    days: int = 7,
    execute: bool = True,
    tail_lines: int = 6,
    target_date: date | None = None,
) -> dict[str, Any]:
    before = build_token_usage_maintenance(
        storage_dir=storage_dir,
        days=days,
        target_date=target_date,
    )
    commands = list(before.get("execution_commands") or [])

    result: dict[str, Any] = {
        "generated_at": _generated_at(),
        "storage_dir": before.get("storage_dir"),
        "mode": "skip" if before.get("skip") else ("executed" if execute else "check_only"),
        "skip": bool(before.get("skip")),
        "executed": False,
        "success": True,
        "action": before.get("action"),
        "before": before,
        "after": before if before.get("skip") else None,
        "before_action": before.get("action"),
        "after_action": before.get("action"),
        "runs": [],
        "needs_followup": False,
    }

    if before.get("skip") or not commands:
        return result

    if not execute:
        result["needs_followup"] = True
        return result

    runs: list[dict[str, Any]] = []
    success = True
    for command in commands:
        completed = subprocess.run(
            shlex.split(str(command)),
            cwd=project_path(),
            capture_output=True,
            text=True,
        )
        runs.append(
            {
                "command": command,
                "returncode": int(completed.returncode),
                "stdout_tail": _tail_text_lines(completed.stdout, limit=tail_lines),
                "stderr_tail": _tail_text_lines(completed.stderr, limit=tail_lines),
            }
        )
        if completed.returncode != 0:
            success = False
            break

    after = build_token_usage_maintenance(
        storage_dir=storage_dir,
        days=days,
        target_date=target_date,
    )
    result["executed"] = True
    result["success"] = success
    result["runs"] = runs
    result["after"] = after
    result["after_action"] = after.get("action")
    result["needs_followup"] = bool((not success) or not after.get("skip"))
    return result


def run_knowledge_index_maintenance(
    storage_dir: str = "storage",
    *,
    execute: bool = True,
    tail_lines: int = 6,
) -> dict[str, Any]:
    before = build_knowledge_index_summary(storage_dir=storage_dir)
    action = str(before.get("recommended_action") or "skip")
    command = before.get("recommended_command")

    result: dict[str, Any] = {
        "generated_at": _generated_at(),
        "storage_dir": before.get("storage_dir"),
        "mode": "skip" if action == "skip" else ("executed" if execute else "check_only"),
        "skip": action == "skip",
        "executed": False,
        "success": True,
        "action": action,
        "command": command,
        "fallback_command": before.get("fallback_command"),
        "before": before,
        "before_status": before.get("status"),
        "after": before if action == "skip" else None,
        "after_status": before.get("status"),
        "needs_followup": False,
        "state_synced": False,
        "stdout_tail": [],
        "stderr_tail": [],
    }

    if action == "skip" or not command:
        return result

    if not execute:
        result["success"] = True
        result["needs_followup"] = True
        return result

    completed = subprocess.run(
        shlex.split(str(command)),
        cwd=project_path(),
        capture_output=True,
        text=True,
    )
    result["executed"] = True
    result["returncode"] = int(completed.returncode)
    result["stdout_tail"] = _tail_text_lines(completed.stdout, limit=tail_lines)
    result["stderr_tail"] = _tail_text_lines(completed.stderr, limit=tail_lines)

    if completed.returncode == 0:
        _sync_knowledge_index_state(storage_dir=storage_dir)
        result["state_synced"] = True

    after = build_knowledge_index_summary(storage_dir=storage_dir)
    result["after"] = after
    result["after_status"] = after.get("status")
    result["success"] = completed.returncode == 0
    result["needs_followup"] = bool(
        completed.returncode != 0 or after.get("recommended_action") != "skip"
    )
    return result


def _memory_health_specs(storage_dir: str = "storage") -> list[dict[str, Any]]:
    return [
        {
            "label": "knowledge",
            "path": project_path(storage_dir, "memory", "knowledge.json"),
            "warn_bytes": 5 * 1024 * 1024,
            "danger_bytes": 10 * 1024 * 1024,
        },
        {
            "label": "thinking_journal",
            "path": project_path(storage_dir, "memory", "thinking_journal.json"),
            "warn_bytes": 3 * 1024 * 1024,
            "danger_bytes": 5 * 1024 * 1024,
        },
        {
            "label": "experiment_experiences",
            "path": project_path(storage_dir, "memory", "experiment_experiences.json"),
            "warn_bytes": 200 * 1024,
            "danger_bytes": 500 * 1024,
        },
        {
            "label": "experiments",
            "path": project_path(storage_dir, "memory", "experiments.json"),
            "warn_bytes": 1024 * 1024,
            "danger_bytes": 2 * 1024 * 1024,
        },
    ]


def _memory_health_worktrees_dir() -> Path:
    return project_path(".claude", "worktrees")


def _severity_rank(status: str) -> int:
    order = {
        "ok": 0,
        "warn": 1,
        "danger": 2,
        "missing": 3,
        "invalid_json": 3,
    }
    return order.get(status, 0)


def _entry_count(payload: Any) -> int | None:
    if isinstance(payload, (list, dict)):
        return len(payload)
    return None


def _file_health_status(*, exists: bool, parse_ok: bool, size_bytes: int, warn_bytes: int, danger_bytes: int) -> str:
    if not exists:
        return "missing"
    if not parse_ok:
        return "invalid_json"
    if size_bytes > danger_bytes:
        return "danger"
    if size_bytes > warn_bytes:
        return "warn"
    return "ok"


def _build_memory_file_summary(spec: dict[str, Any]) -> dict[str, Any]:
    path = spec["path"]
    exists = path.exists()
    payload = _read_json_value(path) if exists else None
    parse_ok = payload is not None
    size_bytes = path.stat().st_size if exists else 0
    status = _file_health_status(
        exists=exists,
        parse_ok=parse_ok,
        size_bytes=size_bytes,
        warn_bytes=int(spec["warn_bytes"]),
        danger_bytes=int(spec["danger_bytes"]),
    )
    return {
        "label": spec["label"],
        "path": _display_path(path),
        "status": status,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 3) if exists else None,
        "entry_count": _entry_count(payload),
        "warn_mb": round(int(spec["warn_bytes"]) / 1024 / 1024, 3),
        "danger_mb": round(int(spec["danger_bytes"]) / 1024 / 1024, 3),
    }


def _knowledge_duplicate_summary(path: Path) -> dict[str, Any]:
    payload = _read_json_value(path)
    if not isinstance(payload, list):
        return {"checked": False, "status": "invalid_json"}

    seen: set[str] = set()
    duplicates = 0
    for item in payload:
        digest = hashlib.md5(
            json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        if digest in seen:
            duplicates += 1
        seen.add(digest)
    status = "warn" if duplicates > 0 else "ok"
    return {
        "checked": True,
        "status": status,
        "total_entries": len(payload),
        "duplicates": duplicates,
        "unique_entries": len(seen),
    }


def _worktree_health_summary() -> dict[str, Any]:
    worktrees_dir = _memory_health_worktrees_dir()
    if not worktrees_dir.exists():
        return {
            "path": _display_path(worktrees_dir),
            "count": 0,
            "orphan_count": 0,
            "orphans": [],
            "status": "ok",
        }

    entries = sorted(
        [path for path in worktrees_dir.glob("agent-*") if path.is_dir()],
        key=lambda path: path.name,
    )
    orphans = [
        path.name
        for path in entries
        if not (path / ".git").exists()
    ]
    status = "warn" if orphans else "ok"
    return {
        "path": _display_path(worktrees_dir),
        "count": len(entries),
        "orphan_count": len(orphans),
        "orphans": orphans[:5],
        "status": status,
    }


def build_memory_health_summary(storage_dir: str = "storage") -> dict[str, Any]:
    files = [_build_memory_file_summary(spec) for spec in _memory_health_specs(storage_dir=storage_dir)]
    files_by_label = {item["label"]: item for item in files}
    knowledge_path = project_path(storage_dir, "memory", "knowledge.json")
    duplicates = _knowledge_duplicate_summary(knowledge_path)
    worktrees = _worktree_health_summary()

    overall_status = "ok"
    for status in [item["status"] for item in files] + [duplicates.get("status", "ok"), worktrees.get("status", "ok")]:
        if _severity_rank(status) > _severity_rank(overall_status):
            overall_status = status

    suggestions: list[str] = []
    large_files = [item["label"] for item in files if item["status"] in {"warn", "danger"}]
    if large_files:
        suggestions.append(f"記憶檔偏大：{', '.join(large_files)}；先做 targeted 檢查，不要整檔讀取。")
    if duplicates.get("duplicates", 0):
        suggestions.append(
            f"knowledge.json 有 {duplicates['duplicates']} 筆重複，必要時再執行去重修復。"
        )
    if worktrees.get("orphan_count", 0):
        suggestions.append(
            f".claude/worktrees/ 有 {worktrees['orphan_count']} 個 orphan 目錄，需人工確認後清理。"
        )
    invalid_files = [item["label"] for item in files if item["status"] in {"missing", "invalid_json"}]
    if invalid_files:
        suggestions.append(f"記憶檔異常：{', '.join(invalid_files)}，先修 JSON/檔案可讀性再做後續動作。")
    if not suggestions:
        suggestions.append("記憶檔狀態健康；維持每週一次 compact 檢查即可。")

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "overall_status": overall_status,
        "files": files,
        "knowledge_duplicates": duplicates,
        "worktrees": worktrees,
        "detail_hints": {
            "skill": ".claude/skills/memory-health/SKILL.md",
            "knowledge_index": "uv run python scripts/build_knowledge_index.py stats",
            "size_checks": "uv run volpred ops memory-health-summary",
        },
        "suggestions": suggestions[:4],
        "highlights": {
            "knowledge": files_by_label.get("knowledge"),
            "thinking_journal": files_by_label.get("thinking_journal"),
        },
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _compact_publication_candidate_rows(rows: Any, *, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in (rows if isinstance(rows, list) else [])[: max(limit, 0)]:
        if not isinstance(row, dict):
            continue
        item = {
            "k_id": row.get("k_id"),
            "score": int(row.get("score", 0) or 0),
            "title": row.get("title"),
        }
        audiences = row.get("already_covered_for")
        if isinstance(audiences, list) and audiences:
            item["already_covered_for"] = audiences
        entries.append(item)
    return entries


def build_publication_candidates_summary(
    storage_dir: str = "storage", *, limit: int = 5
) -> dict[str, Any]:
    path = project_path(storage_dir, "publication_candidates.json")
    payload = _read_json_dict(path)
    rebuild_hint = "uv run python scripts/build_publication_candidates.py"
    if payload is None:
        return {
            "generated_at": _generated_at(),
            "available": False,
            "path": _display_path(path),
            "limit": max(limit, 0),
            "rebuild_hint": rebuild_hint,
        }

    source_generated_at = payload.get("generated_at")
    source_dt = _parse_iso_datetime(source_generated_at)
    age_hours = (
        round((datetime.now(timezone.utc) - source_dt).total_seconds() / 3600, 2)
        if source_dt is not None
        else None
    )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "generated_at": _generated_at(),
        "available": True,
        "path": _display_path(path),
        "source_generated_at": source_generated_at,
        "source_age_hours": age_hours,
        "total_k": int(summary.get("total_k", 0) or 0),
        "uncovered": int(summary.get("uncovered", 0) or 0),
        "high_priority_uncovered": int(summary.get("high_priority_uncovered", 0) or 0),
        "missing_general_audience": int(summary.get("missing_general_audience", 0) or 0),
        "missing_research_audience": int(summary.get("missing_research_audience", 0) or 0),
        "top_uncovered": _compact_publication_candidate_rows(
            payload.get("top_10_uncovered"),
            limit=limit,
        ),
        "missing_general": _compact_publication_candidate_rows(
            payload.get("missing_general_top5"),
            limit=limit,
        ),
        "missing_research": _compact_publication_candidate_rows(
            payload.get("missing_research_top5"),
            limit=limit,
        ),
        "rebuild_hint": rebuild_hint,
    }


def build_platform_patrol_summary(
    storage_dir: str = "storage", *, source: str = "user", limit: int = 5
) -> dict[str, Any]:
    cycle = build_platform_cycle_summary(
        storage_dir=storage_dir,
        source=source,
        limit=max(limit, 1),
        write_latest=False,
    )
    alerts = build_alert_condition_report(storage_dir=storage_dir)
    scheduler = build_scheduler_summary(storage_dir=storage_dir)
    health = health_snapshot(storage_dir=storage_dir)

    release_preview = cycle.get("release_preview") if isinstance(cycle.get("release_preview"), dict) else {}
    question_ranking = cycle.get("question_ranking") if isinstance(cycle.get("question_ranking"), dict) else {}
    question_health = (
        question_ranking.get("health") if isinstance(question_ranking.get("health"), dict) else {}
    )
    breached_conditions = [
        {
            "id": item.get("id"),
            "level": item.get("level"),
            "title": item.get("title"),
        }
        for item in (alerts.get("conditions") or [])
        if isinstance(item, dict) and item.get("breached")
    ]

    return {
        "generated_at": _generated_at(),
        "storage_dir": _display_path(project_path(storage_dir)),
        "release_mode": release_preview.get("mode"),
        "release_due": bool(release_preview.get("due_now")),
        "next_release_at": release_preview.get("next_release_at"),
        "pool_counts": release_preview.get("pool_counts") if isinstance(release_preview.get("pool_counts"), dict) else {},
        "next_release_candidates": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "audience": item.get("audience"),
            }
            for item in (release_preview.get("next_candidates") or [])[: max(limit, 0)]
            if isinstance(item, dict)
        ],
        "pending_questions": int(question_health.get("pending_evaluation", 0) or 0),
        "active_ranked_questions": int(question_health.get("active_ranked", 0) or 0),
        "question_candidate_pool": int(question_health.get("candidate_pool", 0) or 0),
        "alert_breach_count": int(alerts.get("breach_count", 0) or 0),
        "breached_alerts": breached_conditions,
        "scheduler": {
            "last_tick_at": scheduler.get("scheduler_last_tick_at"),
            "last_status": scheduler.get("scheduler_last_status"),
            "last_reason": scheduler.get("scheduler_last_reason"),
            "missing_system_task_count": scheduler.get("missing_system_task_count"),
            "queued_count": scheduler.get("queued_count"),
        },
        "health": {
            "failed_supabase_syncs": health.get("failed_supabase_syncs"),
            "open_questions": health.get("open_questions"),
            "event_ledger_entries": health.get("event_ledger_entries"),
            "rollback_points": health.get("rollback_points"),
            "agent_cli_health": (
                health.get("agent_cli_health", {}).get("status")
                if isinstance(health.get("agent_cli_health"), dict)
                else None
            ),
        },
        "suggestions": list(cycle.get("suggestions") or [])[:3],
        "detail_hints": {
            "maintain": "uv run volpred ops platform-patrol-maintain --stub-if-no-work",
            "alerts": "uv run volpred ops check-alerts",
            "cycle": f"uv run volpred ops platform-cycle-summary --limit {max(limit, 1)}",
            "scheduler": "uv run volpred ops scheduler-summary",
            "logs": "uv run volpred ops log-summary",
            "health": "uv run volpred ops health",
        },
    }


def build_platform_patrol_maintenance(
    storage_dir: str = "storage", *, source: str = "user", limit: int = 5
) -> dict[str, Any]:
    summary = build_platform_patrol_summary(storage_dir=storage_dir, source=source, limit=limit)
    reasons: list[str] = []
    if int(summary.get("alert_breach_count", 0) or 0) > 0:
        reasons.append("alert_breach")
    if bool(summary.get("release_due")):
        reasons.append("release_due")
    if int(summary.get("pending_questions", 0) or 0) > 0:
        reasons.append("pending_questions")

    skip = not reasons
    detail_hints = summary.get("detail_hints") if isinstance(summary.get("detail_hints"), dict) else {}
    followup_commands = _compact_command_list(
        detail_hints.get("alerts") if "alert_breach" in reasons else None,
        detail_hints.get("cycle") if "release_due" in reasons else None,
        detail_hints.get("cycle") if "pending_questions" in reasons else None,
        detail_hints.get("scheduler") if reasons else None,
        detail_hints.get("logs") if reasons else None,
    )
    return {
        "generated_at": summary.get("generated_at") or _generated_at(),
        "storage_dir": summary.get("storage_dir"),
        "source": source,
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": "skip" if skip else "inspect_detail",
        "needs_followup": not skip,
        "trigger_reasons": reasons,
        "release_due": bool(summary.get("release_due")),
        "alert_breach_count": int(summary.get("alert_breach_count", 0) or 0),
        "pending_questions": int(summary.get("pending_questions", 0) or 0),
        "next_release_at": summary.get("next_release_at"),
        "breached_alerts": list(summary.get("breached_alerts") or [])[:3],
        "next_release_candidates": list(summary.get("next_release_candidates") or [])[: max(limit, 0)],
        "suggestions": list(summary.get("suggestions") or [])[:3],
        "followup_commands": followup_commands,
        "detail_hints": detail_hints,
    }


def build_question_ops_summary(*, source: str = "user", limit: int = 5) -> dict[str, Any]:
    summary = get_member_question_ranking_summary(source=source, limit=max(limit, 1))
    health = summary.get("health") if isinstance(summary.get("health"), dict) else {}
    ranked = summary.get("ranked_table") if isinstance(summary.get("ranked_table"), list) else []
    pending = summary.get("pending_questions") if isinstance(summary.get("pending_questions"), list) else []
    candidates = summary.get("candidate_pool") if isinstance(summary.get("candidate_pool"), list) else []

    return {
        "generated_at": summary.get("generated_at") or _generated_at(),
        "source": source,
        "pending_questions": int(health.get("pending_evaluation", 0) or 0),
        "active_ranked_questions": int(health.get("active_ranked", 0) or 0),
        "researching_questions": int(health.get("researching", 0) or 0),
        "answered_questions": int(health.get("answered", 0) or 0),
        "candidate_pool": int(health.get("candidate_pool", 0) or 0),
        "latest_member_question_at": health.get("latest_member_question_at"),
        "latest_answered_at": health.get("latest_answered_at"),
        "top_ranked": [
            {
                "rank": item.get("rank"),
                "question_id": item.get("question_id"),
                "proposer": item.get("proposer"),
                "status": item.get("status"),
                "score": item.get("score"),
                "linked_articles_count": item.get("linked_articles_count"),
            }
            for item in ranked[: max(limit, 0)]
            if isinstance(item, dict)
        ],
        "pending_preview": [
            {
                "question_id": item.get("question_id"),
                "proposer": item.get("proposer"),
                "status": item.get("status"),
                "linked_articles_count": item.get("linked_articles_count"),
                "created_at": item.get("created_at"),
            }
            for item in pending[: max(limit, 0)]
            if isinstance(item, dict)
        ],
        "candidate_preview": [
            {
                "question_id": item.get("question_id"),
                "status": item.get("status"),
                "requested_by": item.get("requested_by"),
                "claimed_by": item.get("claimed_by"),
                "linked_articles_count": item.get("linked_articles_count"),
            }
            for item in candidates[: max(limit, 0)]
            if isinstance(item, dict)
        ],
        "suggestions": list(summary.get("suggestions") or [])[:3],
        "detail_hints": {
            "maintain": f"uv run volpred ops question-ops-maintain --source {source} --auto-create-task --stub-if-no-work",
            "summary": f"uv run volpred ops question-ranking-summary --source {source} --limit {max(limit, 1)}",
            "workflow": f"uv run volpred ops question-ranking-workflow --source {source} --limit {max(limit, 1)}",
            "rerank": "uv run volpred ops question-rerank --evaluations-json /path/to/evaluations.json",
        },
    }


def build_question_ops_maintenance(*, source: str = "user", limit: int = 5) -> dict[str, Any]:
    summary = build_question_ops_summary(source=source, limit=limit)
    pending_questions = int(summary.get("pending_questions", 0) or 0)
    skip = pending_questions <= 0
    detail_hints = summary.get("detail_hints") if isinstance(summary.get("detail_hints"), dict) else {}
    return {
        "generated_at": summary.get("generated_at") or _generated_at(),
        "source": source,
        "mode": "skip" if skip else "review",
        "skip": skip,
        "action": "skip" if skip else "load_workflow",
        "needs_followup": not skip,
        "pending_questions": pending_questions,
        "active_ranked_questions": int(summary.get("active_ranked_questions", 0) or 0),
        "researching_questions": int(summary.get("researching_questions", 0) or 0),
        "candidate_pool": int(summary.get("candidate_pool", 0) or 0),
        "pending_preview": list(summary.get("pending_preview") or [])[: max(limit, 0)],
        "top_ranked": list(summary.get("top_ranked") or [])[: max(limit, 0)],
        "suggestions": list(summary.get("suggestions") or [])[:3],
        "followup_commands": _compact_command_list(
            detail_hints.get("workflow") if not skip else None,
            detail_hints.get("rerank") if not skip else None,
        ),
        "detail_hints": detail_hints,
    }
