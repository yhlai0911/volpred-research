"""Auto-generated 「已完成（本班）」/「已排程」 sections for the boss-facing report.

Boss ask (Telegram msg 973, 2026-07-18): 「以後回報是不是要列出近期已排定任務的
時程和已完成的任務列表？」— yes. The structured block emitted by
``scripts/progress_report.py`` gains two more fields after 下一步.

The whole point is that both fields are **derived, never hand-typed** (task
``assign_6349aa2c``): a hand-written「已完成」list is exactly the kind of claim
the 驗證 field was invented to stop. So:

  已完成（本班） := tasks in ``storage/next_tasks.json`` whose status_history
                    records a transition to ``succeeded`` **by this fire's owner
                    token** (slot_id + job_id — precise per-shift attribution).
  已排程         := next fire of each cron job in ``config/runtime_schedules.json``
                    within the next 24h, plus pending P1/P2 tasks (which get
                    picked up by the next hourly dispatch fire).

Both fields are capped (``MAX_ITEMS`` each) with a ``+N 件`` overflow line — the
boss wants to scan progress at a glance, not read a dump of 30+ pending rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEXT_TASKS_PATH = PROJECT_ROOT / "storage" / "next_tasks.json"
SCHEDULES_PATH = PROJECT_ROOT / "config" / "runtime_schedules.json"

TAIPEI = ZoneInfo("Asia/Taipei")
MAX_ITEMS = 5
TITLE_MAX = 34
LINE_MAX = 62  # 一行掃得完；id 保留全長，超出的預算從標題扣
# 已排程 mixes two sources; reserve slots so a burst of cron jobs cannot crowd
# out the pending work the boss actually cares about (and vice versa).
MAX_JOBS = 2
MAX_PENDING = 3
SCHEDULED_HORIZON_H = 24
# Sections that carry a `cron` expression. event_jobs are one-shot event windows
# with no cron field; daemons/cron_jobs are lists, handled generically below.
SCHEDULE_SECTIONS = ("system_crontab", "session_crons", "remote_triggers", "cron_jobs", "daemons")


def _load_json(path: Path) -> Any:
    """Canonical JSON, or None with a trace.

    Never silent: both callers pass a canonical path (`next_tasks.json`,
    `runtime_schedules.json`) that always exists in a healthy checkout, and a
    None here degrades to an EMPTY 「已完成」/「已排程」 section. Empty reads to the
    boss as "this shift did nothing" — the report cannot tell him it failed to
    read the file unless we say so here.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        from volpred.ops.diagnostics import warn

        warn(
            "report_sections",
            "canonical source unreadable; report section degrades to empty",
            path=str(path),
            err=f"{type(exc).__name__}: {exc}",
        )
        return None


def _tasks(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("tasks", [])
    else:
        return []
    return [t for t in items if isinstance(t, dict)]


def _shorten(text: str, limit: int = TITLE_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _succeeded_by_owner(task: dict, owner: str) -> bool:
    for step in task.get("status_history") or []:
        if isinstance(step, dict) and step.get("to") == "succeeded" and step.get("by") == owner:
            return True
    return False


def completed_this_shift(
    owner: str | None,
    *,
    tasks: Iterable[dict] | None = None,
    limit: int = MAX_ITEMS,
) -> list[str]:
    """Task ids + one-liners this fire flipped to ``succeeded``.

    Attribution is by owner token, not by time window: two slots run
    concurrently, so "completed in the last hour" would credit this shift with
    a sibling slot's work.
    """
    if not owner:
        return []
    rows = list(tasks) if tasks is not None else _tasks(_load_json(NEXT_TASKS_PATH))
    mine = [t for t in rows if _succeeded_by_owner(t, owner)]
    mine.sort(key=lambda t: str(t.get("completed_at") or ""))
    lines = [f"{t.get('id', '?')} — {_shorten(t.get('title'))}" for t in mine[:limit]]
    if len(mine) > limit:
        lines.append(f"+{len(mine) - limit} 件")
    return lines


def _iter_cron_entries(spec: Any) -> Iterable[tuple[str, str, str]]:
    """Yield (id, cron_expr, label) for every cron-carrying schedule entry."""
    if not isinstance(spec, dict):
        return
    for section in SCHEDULE_SECTIONS:
        block = spec.get(section)
        items = block.get("items", []) if isinstance(block, dict) else block
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            cron = item.get("cron")
            if not isinstance(cron, str) or not cron.strip():
                continue
            label = item.get("label") or item.get("description") or ""
            yield str(item.get("id") or "?"), cron.strip(), _shorten(label)


def upcoming_jobs(
    now: datetime | None = None,
    *,
    spec: Any = None,
    horizon_h: int = SCHEDULED_HORIZON_H,
    limit: int = MAX_JOBS,
) -> list[tuple[datetime, str]]:
    """(next_fire, label) for cron jobs firing within ``horizon_h`` hours."""
    from croniter import croniter

    now = now or datetime.now(TAIPEI)
    spec = spec if spec is not None else _load_json(SCHEDULES_PATH)
    deadline = now + timedelta(hours=horizon_h)
    out: list[tuple[datetime, str]] = []
    for job_id, cron, label in _iter_cron_entries(spec):
        try:
            nxt = croniter(cron, now).get_next(datetime)
        except (ValueError, KeyError) as exc:
            # A malformed row must not take the whole report down — but skipping
            # it silently makes a job that will never fire look merely idle, and
            # 「已排程」 is precisely where the boss would look to notice that.
            from volpred.ops.diagnostics import warn

            warn(
                "report_sections",
                "unparseable cron spec; job omitted from 已排程",
                job_id=str(job_id),
                cron=str(cron)[:60],
                err=f"{type(exc).__name__}: {exc}",
            )
            continue
        if nxt > deadline:
            continue
        out.append((nxt, f"{job_id}{' — ' + label if label else ''}"))
    out.sort(key=lambda row: row[0])
    return out[:limit]


def _next_dispatch_fire(now: datetime) -> datetime:
    """Hourly dispatch fires at HH:07 — when a pending task gets picked up."""
    nxt = now.replace(minute=7, second=0, microsecond=0)
    return nxt if nxt > now else nxt + timedelta(hours=1)


def pending_hot_tasks(
    now: datetime | None = None,
    *,
    tasks: Iterable[dict] | None = None,
    limit: int = MAX_PENDING,
) -> tuple[list[tuple[datetime, str]], int]:
    """((eta, label), overflow) for pending P1/P2 tasks, priority then age."""
    now = now or datetime.now(TAIPEI)
    rows = list(tasks) if tasks is not None else _tasks(_load_json(NEXT_TASKS_PATH))
    hot = [
        t
        for t in rows
        if t.get("status") == "pending" and t.get("priority") in (1, 2)
    ]
    hot.sort(key=lambda t: (t.get("priority", 9), str(t.get("created_at") or "")))
    eta = _next_dispatch_fire(now)
    shown = []
    for t in hot[:limit]:
        tid = str(t.get("id", "?"))
        # 長 alert id 會把整行撐爆；id 要能複製查詢所以留全，改壓標題
        title = _shorten(t.get("title"), max(12, LINE_MAX - len(tid)))
        shown.append((eta, f"{tid} P{t.get('priority')} {title}"))
    return shown, max(0, len(hot) - limit)


def scheduled_next_24h(
    now: datetime | None = None,
    *,
    tasks: Iterable[dict] | None = None,
    spec: Any = None,
    limit: int = MAX_ITEMS,
) -> list[str]:
    """Merged「已排程」lines: cron jobs + pending P1/P2, earliest first."""
    now = now or datetime.now(TAIPEI)
    jobs = upcoming_jobs(now, spec=spec)
    pending, overflow = pending_hot_tasks(now, tasks=tasks)
    merged = sorted(jobs + pending, key=lambda row: row[0])[:limit]
    lines = [f"{when:%m-%d %H:%M} {label}" for when, label in merged]
    if overflow:
        lines.append(f"+{overflow} 件 pending P1-P2 待派")
    return lines


def render_sections(owner: str | None, *, indent: str = "　", now: datetime | None = None) -> list[str]:
    """The two report fields as rendered lines, ready to append to the block.

    Never raises: a broken queue file degrades to「（讀取失敗）」rather than
    blocking a report the boss is waiting for.
    """
    out: list[str] = []
    for header, builder in (
        ("📗 已完成（本班）", lambda: completed_this_shift(owner)),
        ("🗓 已排程", lambda: scheduled_next_24h(now)),
    ):
        out += ["", header]
        try:
            lines = builder()
        except Exception as exc:  # noqa: BLE001 — report must still emit
            lines = [f"（讀取失敗：{exc}）"]
        out += [f"{indent}{line}" for line in (lines or ["無"])]
    return out
