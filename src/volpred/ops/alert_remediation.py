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

from volpred.ops.diagnostics import warn
from volpred.ops.next_tasks import normalize_task_priority

# The alert repaired the breach itself before sending. Its body reports the
# repair; enqueuing a task on top would double-book the work.
SELF_REMEDIATING: dict[str, str] = {
    "publishing_freshness": "scripts/remediate_publish_drought.py ladder runs in check_alerts before the email",
    "lazypack_render_stuck": "render retry is wired into the alert path",
    "series_registry": "series drift is reconciled against config/article_series.json",
    "draft_pool_low": "continue_task_dispatch._maybe_refill_draft_pool tops the pool up each fire",
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
}

_LEVEL_PRIORITY = {"critical": 1, "warn": 2, "info": 3}

_SUGGEST_HEADING = "## 建議行動"
_AUDIT_HEADING = "## 處理步驟（任務已自動建立，以下供執行者稽核）"


def _tasks_path(storage_dir: str) -> Path:
    root = Path(storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / storage_dir
    return root / "next_tasks.json"


def task_id_for(alert_id: str, now: datetime) -> str:
    """One task per alert per day — an hourly alert must not mint 24 tasks."""
    return f"alert_{alert_id}_{now.strftime('%Y%m%d')}"


def _enqueue(condition: dict[str, Any], storage_dir: str, now: datetime) -> dict[str, Any]:
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

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]\n", encoding="utf-8")

    try:
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                payload = json.load(fh)
                tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
                if not isinstance(tasks, list):
                    warn("alert_remediation", "next_tasks.json is not a list", alert_id=alert_id)
                    return {"created": False, "reason": "next_tasks_not_a_list"}

                if any(isinstance(t, dict) and t.get("id") == tid for t in tasks):
                    return {"created": False, "reason": "already_queued_today", "task_id": tid}

                tasks.append(task)
                # Serialize fully before truncating: a writer that dies mid-dump
                # must not leave the canonical pool as half a JSON document.
                blob = json.dumps(payload if isinstance(payload, dict) else tasks, indent=2, ensure_ascii=False)
                fh.seek(0)
                fh.truncate()
                fh.write(blob + "\n")
                return {"created": True, "task_id": tid, "task_type": task["task_type"], "priority": task["priority"]}
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001 — the alert pipeline must still send
        warn("alert_remediation", "enqueue failed", alert_id=alert_id, err=str(exc))
        return {"created": False, "reason": "enqueue_failed", "error": str(exc)}


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
        return {"disposition": "self_remediating", "alert_id": alert_id, "why": SELF_REMEDIATING[alert_id]}

    if alert_id in OWNER_DECISION:
        return {"disposition": "owner_decision", "alert_id": alert_id, "why": OWNER_DECISION[alert_id]}

    outcome = _enqueue(condition, storage_dir, now)
    condition["body"] = _rewrite_body(str(condition.get("body") or ""), outcome)
    condition["remediation"] = outcome
    return {"disposition": "task", "alert_id": alert_id, **outcome}


def remediate_report(
    report: dict[str, Any],
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Run dispositions across every breached condition. Call before sending."""
    return [
        remediate_condition(c, storage_dir=storage_dir, now=now)
        for c in report.get("conditions", [])
        if c.get("breached")
    ]
