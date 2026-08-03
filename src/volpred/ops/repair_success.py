"""Success-only notifications for verified self-optimization repairs."""

from __future__ import annotations

from typing import Any


def notify_verified_repair_success(
    task: dict[str, Any],
    *,
    storage_dir: str = "storage",
) -> dict[str, Any] | None:
    """Send one deduplicated success notice after a verified task completion.

    Admission, progress, and failure are deliberately not notifications.  The
    caller invokes this only after the canonical queue row is terminal and the
    structured ``repair_verification`` contract has passed.
    """
    if str(task.get("repair_lane") or "") != "self_optimization":
        return None
    verification = task.get("repair_verification")
    if not isinstance(verification, dict):
        return {
            "sent": False,
            "skipped": True,
            "reason": "repair_verification_missing",
        }
    from volpred.ops.alerts import AlertDeliveryClass, send_routed_alert

    task_id = str(task.get("id") or "unknown")
    alert_key = str(task.get("alert_key") or "self_optimization")
    title = f"自動修復成功：{alert_key}（{task_id}）"
    problem = str(task.get("title") or alert_key)
    method = str(verification.get("method") or task.get("result") or "")
    tests = verification.get("tests")
    readback = verification.get("readback")
    body = "\n".join(
        [
            "## 發生的問題",
            problem,
            f"incident：`{task.get('incident_id') or 'n/a'}`",
            "",
            "## 最終解決步驟與方法",
            method,
            "",
            "## 驗證證據",
            f"- tests：{tests}",
            f"- detector / runtime read-back：{readback}",
            f"- completed_at：`{task.get('completed_at') or 'n/a'}`",
        ]
    )
    return send_routed_alert(
        "info",
        title,
        body,
        storage_dir=storage_dir,
        delivery_class=AlertDeliveryClass.RECOVERY,
    )


__all__ = ["notify_verified_repair_success"]
