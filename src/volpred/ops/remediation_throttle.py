"""Global 24h ceiling on auto-remediation task creation (plan §7 G6).

This is the LAST line of defence: even if every piece of incident reasoning is
wrong, volume cannot run away.  The 2026-07 incident that mandated it: auto
remediation task creation grew 8 → 10 → 32 → 38 per day over four days with no
cap anywhere in the pipeline (plan §2.4 — a global grep for cap/per_day found
nothing).

Semantics (G6): within any rolling 24h window, at most
``MAX_AUTO_REMEDIATION_PER_DAY`` auto-remediation tasks may be CREATED.  Beyond
that, the disposition is refused (no task row), the refusal is appended to a
ledger, and the day's refusals are summarised into ONE owner email.

Enforcement owner (anti-stacking): this module is the single decision owner.
It is consulted from every queue-append choke point that auto-remediation
records can flow through — the ``append_task_record`` gateway, the
alert-remediation writer, and check_alerts' CI append — because those writers
hold their own flocks; the *decision* lives here only.

The daily summary email owner is :func:`flush_denial_summary`, called from the
hourly check_alerts pass; the alert transport's 24h dedup (sha256(level|title),
title carries the date) is what mechanically collapses it to one mail per day.
Denial recording never sends mail inline — several callers hold the
next_tasks.json flock at denial time and SMTP under that lock would stall
dispatch.

Escalation tasks (``source == "incident_escalation"``) are deliberately NOT
counted or capped: escalation is the loop's exit (one per incident, uniqueness
guaranteed by the escalated state).  Capping the exit could strand an incident
with no path to a human.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from volpred.canonical_write import guard_canonical_write
from volpred.ops.diagnostics import warn

#: G6 initial value (plan §7): rolling-24h ceiling on auto-remediation tasks.
MAX_AUTO_REMEDIATION_PER_DAY = 8
WINDOW = timedelta(hours=24)

LEDGER_BASENAME = "remediation_throttle_ledger.jsonl"

#: Sources whose records are auto-remediation dispositions.
AUTO_REMEDIATION_SOURCES = frozenset(
    {
        "internal_alert_remediation_router",
        "alert_remediation_bridge",
        "dispatch_workspace_gate",
        "incident_router",
    }
)

#: Id prefixes of the historical auto-remediation task families — needed so
#: the rolling count sees rows created by the pre-store paths too.
AUTO_REMEDIATION_ID_PREFIXES = (
    "alert_internal_",
    "alert_",
    "wsb_remed_",
    "worktree_salvage_",
    "ci-red-",
    "inc_",
)


def ledger_path_for(queue_path: str | Path) -> Path:
    """Ledger lives next to the queue's storage dir: <storage>/ops/<ledger>."""
    return Path(queue_path).resolve().parent / "ops" / LEDGER_BASENAME


def is_auto_remediation(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    source = str(record.get("source") or "")
    if source == "incident_escalation":
        return False  # the loop's exit is never capped (module docstring)
    if record.get("internal_alert_watermark") is True:
        return False  # bookkeeping receipt, not a disposition
    if record.get("incident_id"):
        return True
    if source in AUTO_REMEDIATION_SOURCES:
        return True
    task_id = str(record.get("id") or "")
    return task_id.startswith(AUTO_REMEDIATION_ID_PREFIXES)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):  # silent-ok: parse helper returns None for non-ISO input by design
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def recent_auto_remediation_count(
    tasks: Iterable[Any], *, now: datetime | None = None
) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    floor = current - WINDOW
    count = 0
    for task in tasks:
        if not isinstance(task, dict) or not is_auto_remediation(task):
            continue
        created = _parse_iso(task.get("created_at"))
        if created is None:
            continue  # silent-ok: machine writers always stamp created_at; unstamped rows are legacy noise, not window members
        if floor <= created <= current:
            count += 1
    return count


def over_cap(
    tasks: Iterable[Any],
    *,
    now: datetime | None = None,
    cap: int = MAX_AUTO_REMEDIATION_PER_DAY,
) -> bool:
    """Pure decision — safe to call while holding a queue flock."""
    return recent_auto_remediation_count(tasks, now=now) >= cap


def record_denial(
    record: dict[str, Any],
    *,
    ledger_path: str | Path,
    now: datetime | None = None,
    reason: str = "remediation_cap_24h",
) -> dict[str, Any]:
    """Append the refusal to the ledger (fast local IO only; no mail here)."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    entry = {
        "at": current.isoformat(),
        "task_id": str(record.get("id") or ""),
        "source": str(record.get("source") or ""),
        "incident_id": str(record.get("incident_id") or "") or None,
        "title": str(record.get("title") or "")[:160],
        "reason": reason,
        "cap": MAX_AUTO_REMEDIATION_PER_DAY,
    }
    path = Path(ledger_path)
    try:
        guard_canonical_write(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — the denial already held; losing the receipt must still be visible
        warn(
            "remediation_throttle",
            "denial ledger append failed",
            task_id=entry["task_id"],
            err=f"{type(exc).__name__}: {exc}",
        )
        entry["ledger_error"] = str(exc)[:200]
    warn(
        "remediation_throttle",
        "auto-remediation task refused by 24h cap",
        task_id=entry["task_id"],
        source=entry["source"],
        cap=MAX_AUTO_REMEDIATION_PER_DAY,
    )
    return entry


def _todays_denials(ledger_path: Path, *, now: datetime) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    day = now.date().isoformat()
    entries: list[dict[str, Any]] = []
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        warn("remediation_throttle", "ledger read failed", err=str(exc))
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            warn("remediation_throttle", "ledger line unparseable", err=str(exc), head=line[:80])
            continue
        stamp = _parse_iso(entry.get("at")) if isinstance(entry, dict) else None
        if stamp is not None and stamp.date().isoformat() == day:
            entries.append(entry)
    return entries


def flush_denial_summary(
    *,
    ledger_path: str | Path,
    now: datetime | None = None,
    notify: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send ONE daily summary of today's cap refusals (G6 last clause).

    The title embeds the UTC date, so the alert transport's 24h
    sha256(level|title) dedup collapses hourly flush calls into a single
    delivered mail per day — no second dedup layer here (anti-stacking).
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    denials = _todays_denials(Path(ledger_path), now=current)
    if not denials:
        return {"sent": False, "reason": "no_denials_today", "denials": 0}
    if notify is None:
        from volpred.ops.alerts import send_alert as notify  # lazy: alerts is heavy

    listed = "\n".join(
        f"- {d.get('at')} `{d.get('task_id')}`（source={d.get('source')}）"
        for d in denials[:20]
    )
    more = "" if len(denials) <= 20 else f"\n…及另外 {len(denials) - 20} 筆（見 ledger）"
    title = f"自動補救任務 24h 上限觸發（{current.date().isoformat()}）"
    body = "\n".join(
        [
            "## 觸發條件",
            f"滾動 24h 內自動補救任務已達上限 {MAX_AUTO_REMEDIATION_PER_DAY} 張，"
            f"今日共拒絕 {len(denials)} 張新開單：",
            listed + more,
            f"Ledger：`{Path(ledger_path)}`",
            "",
            "## 影響",
            "這是止血 gate（G6）在工作：同根因不再無限開單；被拒的條件仍在 incident "
            "store 計數，不會遺失。",
            "",
            "## 系統已自動執行",
            "超額開單一律拒絕並記錄。若拒絕清單顯示同一 incident 反覆被拒，"
            "escalation 路徑會把它升級成單一根因重構任務，無需老闆逐張處理。",
        ]
    )
    try:
        delivery = notify("warn", title, body)
    except Exception as exc:  # noqa: BLE001 — summary transport failure must not break the alert pass
        warn("remediation_throttle", "denial summary send failed", err=str(exc))
        return {"sent": False, "reason": f"notify_failed: {exc}", "denials": len(denials)}
    return {"sent": bool(delivery.get("sent")), "denials": len(denials),
            "title": title, "delivery": delivery}
