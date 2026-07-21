"""Turn breached alerts into work the platform does, not chores the owner does.

2026-07-13, owner (two replies, same hour): 「你要立即處理 不是只建議我」/
「是你要立刻處理 不是叫我」. The `member_qa_stale` alert had emailed him an hourly
to-do list — *"主線程立即跑 question-ranking-workflow…"* — for 25 hours straight.
A sweep of `alerts.py` found the same shape in 24 of 27 alert bodies: a `## 建議行動`
section addressed to a human. Only three alerts remediated themselves.

The framing was the bug. On a platform whose premise is that the AI runs it, an
alert nobody but the owner can act on is a design failure, not a notification.
An alert *is* a task. So that is the default here, and the registry below only
names the exceptions:

* `SELF_REMEDIATING` — the alert already fixed it before emailing; a task would
  duplicate the work. Its body must say what it did.
* `OWNER_DECISION` — genuinely the owner's call (irreversible, or a policy /
  research-direction judgment). These may legitimately ask him for something.

Everything else auto-enqueues a task into the canonical pool and the email
reports what was queued. There is no "unclassified" branch that quietly falls
back to nagging: a newly added alert gets a task whether or not anyone
remembered to think about it.

Pairs with the starvation lockout in `scripts/continue_task_dispatch.py`. The
tasks created here are worthless if dispatch can skip them forever — which is
exactly what happened to the P1 `member_qa` task that sat pending for 17 hours
while this alert fired. Queuing work and guaranteeing it gets picked up are two
halves of one fix; neither works alone.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.canonical_write import guard_canonical_write
from volpred.ops.diagnostics import warn
from volpred.ops.next_tasks import normalize_task_priority, write_tasks_to_handle

# The alert repaired the breach itself before sending. Its body reports the
# repair; enqueuing a task on top would double-book the work.
# Every claim must name a mechanically verifiable OWNER — `<file>:<function>`
# whose file exists, whose function is defined there, and which the alert path
# actually invokes (tests/test_self_remediating_owners.py enforces all three).
# assign_5195e5ae D4: this used to be dict[str, str] prose, and one entry
# ("render retry is wired into the alert path") was simply false — the claimed
# mechanism did not exist, so lazypack render failures fell into a black hole
# while the registry suppressed both the task and the honest email. A claim
# without an owner is a lie waiting to happen; entries that cannot name one
# belong in the default task-creating disposition instead (series_registry was
# downgraded exactly that way: its "reconciled automatically" claim was an
# audit + a suggestion to run --apply, not a remediation).
SELF_REMEDIATING: dict[str, dict[str, str]] = {
    "publishing_freshness": {
        "claim": "remediate_publish_drought ladder runs in check_alerts before the email",
        "owner": "scripts/check_alerts.py:_auto_remediate_publish_drought",
    },
    "lazypack_render_stuck": {
        "claim": "stranded failed renders are idempotently re-enqueued hourly in "
                 "check_alerts before the email; past the attempt cap the P1 repair "
                 "task filed by compute_queue owns escalation",
        "owner": "scripts/check_alerts.py:_auto_remediate_lazypack_stuck",
    },
    "draft_pool_low": {
        "claim": "the dispatcher tops the draft pool up on every hourly fire",
        "owner": "scripts/continue_task_dispatch.py:_maybe_refill_draft_pool",
    },
}

# Genuinely the owner's call. Keep this set small and justified — every entry is
# a standing admission that the platform cannot run itself here.
OWNER_DECISION: dict[str, str] = {
    "disk_usage": "freeing or buying disk is irreversible/hardware — the platform must not delete the owner's data on its own",
}

# Which lane the auto-created task belongs in. Default platform_ops.
ALERT_TASK_TYPE: dict[str, str] = {
    "member_qa_stale": "member_qa",
    "knowledge_stale": "experiment",
    "paper_stale": "paper_review",
    "paper_website_drift": "paper_review",
    "paper_adjudication_gap": "paper_review",  # 2026-07-14 K1686 incident: gating task done, ruling missing — main-thread adjudication
    "content_quality": "governance",
    "cluster_cap_drift": "governance",
    "loop_health": "governance",
    # assign_5195e5ae D4c: downgraded from SELF_REMEDIATING — the alert audits
    # drift and *suggests* `series_registry.py --apply`; it does not apply it.
    # An audit plus advice is a task for the platform, not a completed repair.
    "series_registry": "governance",
}

_LEVEL_PRIORITY = {"critical": 1, "warn": 2, "info": 3}

# Internally-remediable alerts route through the incident store
# (volpred.ops.incident, plan docs/refactor_plan_incident_lifecycle.md).  The
# episode/attempt machinery that used to live HERE — parasitic state inside
# next_tasks.json rows (internal_alert_state, clean watermarks, attempt ids) —
# was the §2.1 root cause: dedup anchored on live task rows resets itself every
# resolve.  It was removed in P3; identity, counters and the state machine are
# owned by the store, and this module only wires detector conditions to it.
_SUGGEST_HEADING = "## 建議行動"
_AUDIT_HEADING = "## 處理步驟（任務已自動建立，以下供執行者稽核）"
_REVALIDATION_INSTRUCTION = (
    "執行任何會改變發布或外部狀態的修復前，必須先用原 detector 重新驗證"
    "警報仍在 breached。若已自然解除，只記錄 fresh no-op 後完成，不得照舊快照執行。"
)


def _tasks_path(storage_dir: str) -> Path:
    root = Path(storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / storage_dir
    return root / "next_tasks.json"


def task_id_for(alert_id: str, now: datetime) -> str:
    """One task per alert per day — an hourly alert must not mint 24 tasks."""
    return f"alert_{alert_id}_{now.strftime('%Y%m%d')}"


def _internal_task_description(condition: dict[str, Any], alert_key: str) -> str:
    return (
        f"由內部可自癒 alert_key `{alert_key}` 自動建立（固定 P1）。\n"
        "這是系統自己的修復工作；首次與修復進行中都不通知老闆。"
        "只有同一 alert_key 的修復任務連續完成但警報仍存在 >=2 次才升級。\n\n"
        f"{_REVALIDATION_INSTRUCTION}\n\n"
        f"{condition.get('body') or ''}"
    )


def _append_router_status_history(
    task: dict[str, Any],
    *,
    old_status: str,
    new_status: str,
    now: datetime,
    note: str,
) -> None:
    history = task.get("status_history")
    if not isinstance(history, list):
        history = []
        task["status_history"] = history
    history.append(
        {
            "ts": now.isoformat(),
            "from": old_status or "unknown",
            "to": new_status,
            "by": "alert_remediation_router",
            "note": note,
        }
    )


def _normalize_fingerprint(value: Any) -> set[str]:
    """Normalise a condition/state fingerprint into a comparable string set.

    A fingerprint identifies *which* concrete finding tripped the gate (e.g. the
    ``file:line`` entries a silent-fallback audit flagged as NEW), so distinct
    findings under one coarse alert_key can be told apart.  Missing/empty ⇒ empty
    set ⇒ callers fall back to the fingerprint-agnostic behaviour.
    """

    if not value:
        return set()
    if isinstance(value, str):
        items: list[Any] = [value]
    else:
        try:
            items = list(value)
        except TypeError:
            return set()
    return {text for item in items if (text := str(item or "").strip())}


def _throttled_outcome(
    tasks: list[Any],
    task: dict[str, Any],
    *,
    storage_dir: str,
    now: datetime,
) -> dict[str, Any] | None:
    """G6 choke point for this writer (decision owner = remediation_throttle).

    This writer appends under its own flock instead of the
    ``append_task_record`` gateway, so the cap must be consulted here too.
    Returns the denial outcome, or None when the append may proceed.
    """
    from volpred.ops import remediation_throttle

    if not remediation_throttle.over_cap(tasks, now=now):
        return None
    remediation_throttle.record_denial(
        task,
        ledger_path=remediation_throttle.ledger_path_for(_tasks_path(storage_dir)),
        now=now,
    )
    return {
        "created": False,
        "reason": "remediation_throttled",
        "task_id": task.get("id"),
        "escalate": False,
    }


def _enqueue(
    condition: dict[str, Any],
    storage_dir: str,
    now: datetime,
) -> dict[str, Any]:
    """Ordinary alert → one task per alert per day (unchanged by P3).

    Internal-remediable alerts no longer pass through here — they route via
    the incident store in :func:`remediate_internal_alert`.
    """
    alert_id = str(condition.get("id") or "")
    tid = task_id_for(alert_id, now)
    level = str(condition.get("level") or "warn")
    path = _tasks_path(storage_dir)

    task = {
        "id": tid,
        "title": f"[alert] {condition.get('title') or alert_id}",
        "description": (
            f"由 alert `{alert_id}` 自動建立（level={level}）。\n"
            f"這是系統自己要做的事，不是老闆的待辦。做完後下一輪巡檢會自動解除警報。\n\n"
            f"{_REVALIDATION_INSTRUCTION}\n\n"
            f"{condition.get('body') or ''}"
        ),
        "task_type": ALERT_TASK_TYPE.get(alert_id, "platform_ops"),
        "priority": _LEVEL_PRIORITY.get(level, 2),
        "status": "pending",
        "created_at": now.isoformat(),
        "source": "alert_remediation_bridge",
        "tags": ["alert", alert_id],
    }
    normalize_task_priority(task)

    # The governance guard must not be swallowed by the operational fallback:
    # candidate/pre-commit contexts deliberately forbid canonical writes.
    guard_canonical_write(path)
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[]\n", encoding="utf-8")
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                payload = json.load(fh)
                if not isinstance(payload, list):
                    warn("alert_remediation", "next_tasks.json is not a list", alert_id=alert_id)
                    return {"created": False, "reason": "next_tasks_not_a_list"}
                tasks = payload
                existing = next(
                    (t for t in tasks if isinstance(t, dict) and t.get("id") == tid),
                    None,
                )
                if existing is not None:
                    return {"created": False, "reason": "already_queued_today", "task_id": tid}

                denied = _throttled_outcome(tasks, task, storage_dir=storage_dir, now=now)
                if denied is not None:
                    return denied
                tasks.append(task)
                write_tasks_to_handle(fh, tasks)
                return {
                    "created": True,
                    "task_id": tid,
                    "task_type": task["task_type"],
                    "priority": task["priority"],
                }
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001 — caller decides whether escalation is earned
        warn("alert_remediation", "enqueue failed", alert_id=alert_id, err=str(exc))
        return {"created": False, "reason": "enqueue_failed", "error": str(exc)}


def _utc_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _close_cleared_task(task_id: str, storage_dir: str, now: datetime) -> bool:
    """Close a still-pending disposition row after its incident resolved."""
    path = _tasks_path(storage_dir)
    guard_canonical_write(path)
    if not path.exists():
        return False
    try:
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                payload = json.load(fh)
                if not isinstance(payload, list):
                    return False
                for task in payload:
                    if not isinstance(task, dict) or task.get("id") != task_id:
                        continue
                    status = str(task.get("status") or "").strip().lower()
                    if status not in {"", "pending", "pending_main_thread"}:
                        return False  # claimed/terminal worker owns its own closure
                    task["status"] = "succeeded"
                    task["completed_at"] = now.isoformat()
                    task["result"] = "internal alert cleared before dispatch"
                    _append_router_status_history(
                        task,
                        old_status=status,
                        new_status="succeeded",
                        now=now,
                        note="condition_cleared_automatically",
                    )
                    write_tasks_to_handle(fh, payload)
                    return True
                return False
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001 — closure is best-effort; resolution already persisted in the store
        warn("alert_remediation", "cleared-task close failed", task_id=task_id, err=str(exc))
        return False


def remediate_internal_alert(
    condition: dict[str, Any],
    *,
    alert_key: str,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Route one internal breach through the incident store (plan §3).

    The store decides the disposition; this wiring only executes it:

    * ``create_task``  — repair task appended via the ``append_task_record``
      gateway (deterministic per-episode id ⇒ idempotent); G6 cap may refuse it,
      which is recorded on the incident (``remediation_throttled``).
    * ``notify``       — machine_self record+notify (§6): caller (alerts.py)
      owns the transport, then acknowledges via ``incident.record_notified``.
    * ``escalate``     — caller runs ``incident.actuate_escalation`` once.
    * ``none`` / ``suppressed`` — counters moved, nothing to do.
    """
    from volpred.ops import incident

    current = _utc_now(now)
    alert_id = str(condition.get("id") or "")
    base: dict[str, Any] = {
        "disposition": "internal_remediation",
        "alert_id": alert_id,
        "alert_key": alert_key,
        "created": False,
        "escalate": False,
        "notify_due": False,
    }
    store = incident.store_path_for(storage_dir)
    queue = _tasks_path(storage_dir)
    try:
        outcome = incident.route_breach(
            store,
            kind=alert_key,
            instance_keys=sorted(_normalize_fingerprint(condition.get("fingerprint"))),
            details=str(condition.get("title") or ""),
            now=current,
            task_status_probe=incident.next_tasks_status_probe(queue),
        )
    except Exception as exc:  # noqa: BLE001 — router infra failure must surface as the critical-mail path
        warn("alert_remediation", "incident routing failed", alert_key=alert_key, err=str(exc))
        return {**base, "reason": "enqueue_failed", "error": str(exc)}

    action = str(outcome.get("action") or "")
    base.update(
        incident_id=outcome.get("incident_id"),
        state=outcome.get("state"),
        occurrence_count=outcome.get("occurrence_count"),
        episode_count=outcome.get("episode_count"),
        action=action,
    )

    if action == "create_task":
        task = {
            "id": str(outcome.get("suggested_task_id")),
            "title": f"[internal alert] {condition.get('title') or alert_key}",
            "description": _internal_task_description(condition, alert_key),
            "task_type": "platform_ops",
            "dispatch_lane": "agent",
            # P2 at the source: machine-generated repairs are not boss-urgent;
            # the admission clamp would cap a self-declared P1 anyway.
            "priority": 2,
            "status": "pending",
            "source": "internal_alert_remediation_router",
            "tags": ["alert", "internal-remediable", alert_key],
            "alert_key": alert_key,
            "internal_remediable": True,
            "incident_id": outcome.get("incident_id"),
            "created_at": current.isoformat(),
        }
        try:
            from volpred.ops.next_tasks import append_task_record

            stored, created = append_task_record(task, path=queue, if_exists="skip")
        except Exception as exc:  # noqa: BLE001 — a broken task writer is an infra failure, not an attempt
            warn("alert_remediation", "incident task append failed",
                 alert_key=alert_key, err=str(exc))
            return {**base, "reason": "enqueue_failed", "error": str(exc)}
        if stored.get("throttled_by_remediation_cap"):
            incident.record_throttled(store, str(outcome.get("incident_id")), now=current)
            return {**base, "reason": "remediation_throttled", "task_id": task["id"]}
        incident.bind_task(store, str(outcome.get("incident_id")), str(stored.get("id")), now=current)
        return {
            **base,
            "created": bool(created),
            "reason": "incident_disposition_created" if created else "remediation_active",
            "task_id": stored.get("id"),
        }

    if action == "escalate":
        return {
            **base,
            "escalate": True,
            "reason": "incident_escalation_due",
            "suggested_root_cause_task_id": outcome.get("suggested_root_cause_task_id"),
        }
    if action == "notify":
        return {**base, "notify_due": True, "reason": "incident_notification_due"}
    if action == "suppressed":
        return {**base, "reason": "incident_suppressed"}
    return {
        **base,
        "reason": "remediation_active" if outcome.get("active_task_id") else "incident_recorded",
        "task_id": outcome.get("active_task_id"),
    }


def resolve_internal_alert(
    *,
    alert_key: str,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record ONE clean observation; the store resolves on a sustained streak.

    This is the G7 inversion of the old contract: a single clean no longer
    closes the episode (the resolve→refire oscillation of plan §2.1).  The
    incident resolves only after K clean observations spanning ≥24h, and the
    counters survive resolution.
    """
    from volpred.ops import incident

    current = _utc_now(now)
    store = incident.store_path_for(storage_dir)
    queue = _tasks_path(storage_dir)
    try:
        outcome = incident.observe_clean(
            store,
            kind=alert_key,
            now=current,
            task_status_probe=incident.next_tasks_status_probe(queue),
        )
    except Exception as exc:  # noqa: BLE001 — resolution is housekeeping; failure must stay visible
        warn("alert_remediation", "incident clean observation failed",
             alert_key=alert_key, err=str(exc))
        return {"alert_key": alert_key, "resolved": False,
                "reason": "resolve_failed", "error": str(exc)}
    closable = outcome.get("closable_task_id")
    if outcome.get("resolved") and closable:
        outcome["closed_task"] = _close_cleared_task(str(closable), storage_dir, current)
    return {"alert_key": alert_key, **outcome}


def _rewrite_body(body: str, outcome: dict[str, Any]) -> str:
    """Lead with what the platform did; demote the human-addressed steps to audit."""
    if outcome.get("created"):
        header = (
            "## 已自動處理\n"
            f"已建立任務 `{outcome['task_id']}`（{outcome['task_type']}, P{outcome['priority']}），"
            "下一班 dispatch 會認領執行。任務逾時未被認領時，dispatcher 的 starvation lockout "
            "會強制把它推上候選清單。**老闆無需動作。**\n"
        )
    elif outcome.get("reason") == "already_queued_today":
        header = (
            "## 已自動處理\n"
            f"任務 `{outcome['task_id']}` 今日稍早已建立，仍在處理中。**老闆無需動作。**\n"
        )
    elif outcome.get("reason") == "remediation_throttled":
        header = (
            "## 已達自動補救上限（G6 止血）\n"
            "滾動 24h 內自動補救任務已達全域上限，本警報此次不開單；"
            "拒絕已記入 throttle ledger，每日彙整一封摘要信。**老闆無需動作。**\n"
        )
    else:
        header = (
            "## ⚠️ 自動建任務失敗\n"
            f"原因：`{outcome.get('reason') or outcome.get('error')}`。"
            "此警報暫時退回人工，這本身是一個要修的 bug。\n"
        )

    demoted = body.replace(_SUGGEST_HEADING, _AUDIT_HEADING) if _SUGGEST_HEADING in body else body
    return f"{header}\n{demoted}"


def remediate_condition(
    condition: dict[str, Any],
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply the disposition for one breached condition, mutating its body in place."""
    now = now or datetime.now(timezone.utc)
    alert_id = str(condition.get("id") or "")

    if not condition.get("breached"):
        return {"disposition": "not_breached", "alert_id": alert_id}

    if alert_id in SELF_REMEDIATING:
        entry = SELF_REMEDIATING[alert_id]
        return {
            "disposition": "self_remediating",
            "alert_id": alert_id,
            "why": entry["claim"],
            "owner": entry["owner"],
        }

    if alert_id in OWNER_DECISION:
        return {"disposition": "owner_decision", "alert_id": alert_id, "why": OWNER_DECISION[alert_id]}

    outcome = _enqueue(condition, storage_dir, now)
    condition["body"] = _rewrite_body(str(condition.get("body") or ""), outcome)
    condition["remediation"] = outcome
    return {"disposition": "task", "alert_id": alert_id, **outcome}


def _sweep_cleared_ordinary_tasks(
    cleared_alert_ids: set[str],
    storage_dir: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Close pending bridge tasks whose ordinary alert has cleared.

    Symmetric to the breached→task path in `_enqueue`: when an ordinary alert
    stops firing, the task it minted is no longer real work. Without this, that
    task sits pending until the dispatcher's 24h starvation lockout force-feeds
    it to a fire, which re-validates, finds the condition gone, and burns a
    whole slot on a no-op — exactly what happened to
    `alert_telegram_reply_backlog_20260716` on 2026-07-17. Internal alerts
    already self-resolve via `_route_internal_task`, and `push_backlog` had a
    one-off close in `alerts.py`; every *other* ordinary alert lacked one. Tags
    (extensions/ids) are an open set, so close generically by alert-id tag
    rather than enumerating alerts one at a time.
    """
    if not cleared_alert_ids:
        return []
    path = _tasks_path(storage_dir)
    guard_canonical_write(path)
    if not path.exists():
        return []
    resolutions: list[dict[str, Any]] = []
    try:
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                payload = json.load(fh)
                if not isinstance(payload, list):
                    return []
                changed = False
                for task in payload:
                    if not isinstance(task, dict):
                        continue
                    if task.get("source") != "alert_remediation_bridge":
                        continue
                    if task.get("internal_remediable") is True:
                        continue  # internal alerts resolve via _route_internal_task
                    status = str(task.get("status") or "").strip().lower()
                    if status not in {"", "pending", "pending_main_thread"}:
                        continue
                    tags = [t for t in (task.get("tags") or []) if t != "alert"]
                    alert_id = tags[0] if tags else None
                    if alert_id not in cleared_alert_ids:
                        continue
                    task["status"] = "succeeded"
                    task["completed_at"] = now.isoformat()
                    task["result"] = "ordinary alert cleared before dispatch"
                    _append_router_status_history(
                        task,
                        old_status=status,
                        new_status="succeeded",
                        now=now,
                        note="condition_cleared_automatically",
                    )
                    changed = True
                    resolutions.append(
                        {
                            "disposition": "ordinary_resolution",
                            "alert_id": alert_id,
                            "task_id": task.get("id"),
                            "resolved": True,
                        }
                    )
                if changed:
                    write_tasks_to_handle(fh, payload)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001 — sweep is best-effort; never block the email
        warn("alert_remediation", "cleared-task sweep failed", err=str(exc))
        return []
    return resolutions


def remediate_report(
    report: dict[str, Any],
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Run dispositions across every condition. Call before sending.

    Breached conditions mint/refresh a task; conditions that are present but no
    longer breached close any task they previously minted, so a self-cleared
    alert cannot leave a pending task to be force-dispatched later.
    """
    now = now or datetime.now(timezone.utc)
    dispositions = [
        remediate_condition(c, storage_dir=storage_dir, now=now)
        for c in report.get("conditions", [])
        if c.get("breached")
    ]
    cleared = {
        str(c.get("id") or "")
        for c in report.get("conditions", [])
        if not c.get("breached")
        and str(c.get("id") or "") not in SELF_REMEDIATING
        and str(c.get("id") or "") not in OWNER_DECISION
    }
    cleared.discard("")
    dispositions.extend(_sweep_cleared_ordinary_tasks(cleared, storage_dir, now))
    return dispositions
