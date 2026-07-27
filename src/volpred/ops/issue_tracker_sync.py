"""Bridge canonical runtime tasks to their GitHub planning issue.

``issue_ref`` is an optional foreign key, not a second queue.  New task ingress
stores one canonical spelling (``#<positive integer>``); tolerant read paths can
use :func:`issue_number` to skip malformed historical rows without blocking
local dispatch.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


_SHORT_ISSUE_REF = re.compile(r"^#?([1-9]\d*)$")
_GITHUB_ISSUE_URL = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/issues/([1-9]\d*)/?$",
    re.IGNORECASE,
)


def issue_number(value: Any) -> int | None:
    """Return the positive issue number represented by ``value``."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    match = _SHORT_ISSUE_REF.fullmatch(raw) or _GITHUB_ISSUE_URL.fullmatch(raw)
    return int(match.group(1)) if match else None


def normalize_issue_ref(value: Any) -> str:
    """Return canonical ``#N`` or raise for a malformed new task reference."""
    number = issue_number(value)
    if number is None:
        raise ValueError(
            "issue_ref must be '#<positive integer>' or a GitHub issue URL"
        )
    return f"#{number}"


def _resolve_gh_binary(explicit: str | None = None) -> str | None:
    """Resolve ``gh`` in interactive and stripped cron/Codex environments."""
    if explicit:
        return explicit
    configured = os.environ.get("GH_BIN")
    if configured:
        return configured
    discovered = shutil.which("gh")
    if discovered:
        return discovered
    homebrew = Path("/opt/homebrew/bin/gh")
    return str(homebrew) if homebrew.is_file() else None


def assign_issue(
    issue_ref: Any,
    *,
    repo_root: str | Path | None = None,
    gh_binary: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Best-effort assignee sync; never raises into the local claim path."""
    number = issue_number(issue_ref)
    if number is None:
        return {
            "ok": False,
            "action": "assign",
            "reason": "invalid_issue_ref",
        }
    canonical = f"#{number}"
    binary = _resolve_gh_binary(gh_binary)
    if binary is None:
        return {
            "ok": False,
            "action": "assign",
            "issue_ref": canonical,
            "issue_number": number,
            "reason": "gh_unavailable",
        }
    try:
        completed = runner(
            [
                binary,
                "issue",
                "edit",
                str(number),
                "--add-assignee",
                "@me",
            ],
            cwd=Path(repo_root).resolve() if repo_root is not None else None,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "action": "assign",
            "issue_ref": canonical,
            "issue_number": number,
            "reason": "gh_execution_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "action": "assign",
            "issue_ref": canonical,
            "issue_number": number,
            "reason": "gh_command_failed",
            "detail": str(completed.stderr or "").strip()[-500:],
        }
    return {
        "ok": True,
        "action": "assign",
        "issue_ref": canonical,
        "issue_number": number,
    }


_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def close_issue(
    *,
    issue_ref: Any,
    commit_sha: str,
    task_id: str,
    summary: str,
    repo_root: str | Path | None = None,
    gh_binary: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Close one linked issue with a commit-bound, task-stable comment."""
    number = issue_number(issue_ref)
    if number is None:
        return {"ok": False, "action": "close", "reason": "invalid_issue_ref"}
    if _GIT_OBJECT_ID.fullmatch(str(commit_sha or "")) is None:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "invalid_commit_sha",
        }
    binary = _resolve_gh_binary(gh_binary)
    if binary is None:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "gh_unavailable",
        }
    bounded_summary = " ".join(str(summary or "").split())[:500]
    marker = f"volpred-task:{task_id}:commit:{commit_sha}"
    comment = (
        f"Runtime task `{task_id}` completed in commit `{commit_sha}`."
        + (f"\n\n{bounded_summary}" if bounded_summary else "")
        + f"\n\n<!-- {marker} -->"
    )
    try:
        observed = runner(
            [
                binary,
                "issue",
                "view",
                str(number),
                "--json",
                "state,comments",
            ],
            cwd=Path(repo_root).resolve() if repo_root is not None else None,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
        if observed.returncode != 0:
            return {
                "ok": False,
                "action": "close",
                "issue_ref": f"#{number}",
                "issue_number": number,
                "reason": "gh_readback_failed",
                "detail": str(observed.stderr or "").strip()[-500:],
            }
        try:
            evidence = json.loads(observed.stdout)
            state = str(evidence["state"]).upper()
            comments = evidence.get("comments", [])
            marker_seen = any(
                marker in str(item.get("body") or "")
                for item in comments
                if isinstance(item, dict)
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "action": "close",
                "issue_ref": f"#{number}",
                "issue_number": number,
                "reason": "gh_readback_invalid",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        if state == "CLOSED":
            if marker_seen:
                return {
                    "ok": True,
                    "action": "close",
                    "issue_ref": f"#{number}",
                    "issue_number": number,
                    "already_closed": True,
                }
            return {
                "ok": False,
                "action": "close",
                "issue_ref": f"#{number}",
                "issue_number": number,
                "reason": "issue_closed_without_receipt",
            }
        if marker_seen:
            return {
                "ok": False,
                "action": "close",
                "issue_ref": f"#{number}",
                "issue_number": number,
                "reason": "issue_reopened_after_receipt",
            }
        if state != "OPEN":
            return {
                "ok": False,
                "action": "close",
                "issue_ref": f"#{number}",
                "issue_number": number,
                "reason": "unexpected_issue_state",
                "detail": state,
            }
        completed = runner(
            [
                binary,
                "issue",
                "close",
                str(number),
                "--comment",
                comment,
            ],
            cwd=Path(repo_root).resolve() if repo_root is not None else None,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "gh_execution_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "gh_command_failed",
            "detail": str(completed.stderr or "").strip()[-500:],
        }
    try:
        verified = runner(
            [
                binary,
                "issue",
                "view",
                str(number),
                "--json",
                "state,comments",
            ],
            cwd=Path(repo_root).resolve() if repo_root is not None else None,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "close_readback_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    try:
        verified_payload = json.loads(verified.stdout)
        verified_state = str(verified_payload["state"]).upper()
        verified_comments = verified_payload.get("comments", [])
        verified_marker = any(
            marker in str(item.get("body") or "")
            for item in verified_comments
            if isinstance(item, dict)
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "close_readback_invalid",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    if (
        verified.returncode != 0
        or verified_state != "CLOSED"
        or not verified_marker
    ):
        return {
            "ok": False,
            "action": "close",
            "issue_ref": f"#{number}",
            "issue_number": number,
            "reason": "close_readback_mismatch",
            "detail": {
                "returncode": verified.returncode,
                "state": verified_state,
                "marker_seen": verified_marker,
            },
        }
    return {
        "ok": True,
        "action": "close",
        "issue_ref": f"#{number}",
        "issue_number": number,
        "already_closed": False,
    }


def pending_issue_task_ids_for_owners(
    *,
    path: str | Path,
    claim_owners: set[str] | list[str] | tuple[str, ...],
) -> set[str]:
    """Snapshot linked terminal task IDs owned by immutable fire identities."""
    owners = {str(owner).strip() for owner in claim_owners if str(owner).strip()}
    queue = Path(path)
    if not owners or not queue.exists():
        return set()
    with queue.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            payload = json.load(handle)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if not isinstance(payload, list):
        raise ValueError("next_tasks.json root is not a list")
    return {
        str(task["id"])
        for task in payload
        if isinstance(task, dict)
        and task.get("status") == "succeeded"
        and task.get("id")
        and isinstance(task.get("issue_close_pending"), dict)
        and str(task["issue_close_pending"].get("completion_owner") or "") in owners
    }


def settle_completed_task_issues(
    *,
    path: str | Path,
    claim_owners: set[str] | list[str] | tuple[str, ...],
    commit_sha: str,
    commit_parent_sha: str,
    completed_task_ids: set[str] | list[str] | tuple[str, ...] = (),
    repo_root: str | Path | None = None,
    closer: Callable[..., dict[str, Any]] = close_issue,
) -> list[dict[str, Any]]:
    """Bind eligible receipts, close their issues, then acknowledge readback.

    A newly completed task may bind only to the direct child of the HEAD
    observed by ``complete``.  Once bound, retries keep that original SHA even
    if a later commit by the same owner triggers settlement.  GitHub IO stays
    outside the queue lock; the final phase acknowledges only an unchanged
    terminal receipt.
    """
    sha = str(commit_sha or "").strip().lower()
    parent_sha = str(commit_parent_sha or "").strip().lower()
    if _GIT_OBJECT_ID.fullmatch(sha) is None:
        raise ValueError("commit_sha must be a full Git object id")
    if _GIT_OBJECT_ID.fullmatch(parent_sha) is None:
        raise ValueError("commit_parent_sha must be a full Git object id")
    owners = {str(owner).strip() for owner in claim_owners if str(owner).strip()}
    explicit_task_ids = {
        str(task_id).strip()
        for task_id in completed_task_ids
        if str(task_id).strip()
    }
    if not owners:
        return []
    queue = Path(path)
    if not queue.exists():
        return []

    from volpred.ops.next_tasks import write_tasks_to_handle

    candidates: list[dict[str, Any]] = []
    with queue.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            payload = json.load(handle)
            if not isinstance(payload, list):
                raise ValueError("next_tasks.json root is not a list")
            changed = False
            for task in payload:
                if not isinstance(task, dict) or task.get("status") != "succeeded":
                    continue
                pending = task.get("issue_close_pending")
                if not isinstance(pending, dict):
                    continue
                if (
                    task.get("issue_disposition") != "close"
                    or pending.get("issue_disposition") != "close"
                ):
                    continue
                owner = str(pending.get("completion_owner") or "")
                if owner not in owners:
                    continue
                task_id = str(task.get("id") or "")
                issue_ref = pending.get("issue_ref")
                task_issue_ref = task.get("issue_ref")
                if (
                    not task_id
                    or str(pending.get("task_id") or "") != task_id
                    or issue_number(issue_ref) is None
                    or issue_number(task_issue_ref) is None
                    or normalize_issue_ref(task_issue_ref)
                    != normalize_issue_ref(issue_ref)
                    or pending.get("completed_at")
                    != task.get("completed_at")
                ):
                    continue

                bound_sha = str(pending.get("commit_sha") or "").strip().lower()
                if bound_sha:
                    if _GIT_OBJECT_ID.fullmatch(bound_sha) is None:
                        continue
                elif (
                    task_id in explicit_task_ids
                    if explicit_task_ids
                    else pending.get("completion_base_commit") == parent_sha
                ):
                    bound_sha = sha
                    pending = dict(pending)
                    pending["commit_sha"] = bound_sha
                    task["issue_close_pending"] = pending
                    changed = True
                else:
                    continue
                candidates.append(
                    {
                        "task_id": task_id,
                        "issue_ref": normalize_issue_ref(issue_ref),
                        "pending": pending,
                        "summary": str(task.get("result") or ""),
                        "commit_sha": bound_sha,
                    }
                )
            if changed:
                write_tasks_to_handle(handle, payload)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    successful: list[dict[str, Any]] = []
    for candidate in candidates:
        result = closer(
            issue_ref=candidate["issue_ref"],
            commit_sha=candidate["commit_sha"],
            task_id=candidate["task_id"],
            summary=candidate["summary"],
            repo_root=Path(repo_root) if repo_root is not None else None,
        )
        if result.get("ok"):
            successful.append(
                {
                    "task_id": candidate["task_id"],
                    "issue_ref": candidate["issue_ref"],
                    "issue_number": issue_number(candidate["issue_ref"]),
                    "commit_sha": candidate["commit_sha"],
                    "pending": candidate["pending"],
                }
            )
    if not successful:
        return []

    acknowledged: list[dict[str, Any]] = []
    with queue.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = json.load(handle)
            if not isinstance(current, list):
                raise ValueError("next_tasks.json root is not a list")
            by_id = {
                str(task.get("id")): task
                for task in current
                if isinstance(task, dict) and task.get("id")
            }
            closed_at = datetime.now(timezone.utc).isoformat()
            for receipt in successful:
                task = by_id.get(receipt["task_id"])
                if (
                    task is None
                    or task.get("status") != "succeeded"
                    or task.get("issue_disposition") != "close"
                    or task.get("issue_close_pending") != receipt["pending"]
                    or str(receipt["pending"].get("task_id") or "")
                    != receipt["task_id"]
                    or issue_number(task.get("issue_ref")) is None
                    or normalize_issue_ref(task.get("issue_ref"))
                    != receipt["issue_ref"]
                    or receipt["pending"].get("completed_at")
                    != task.get("completed_at")
                ):
                    continue
                task.pop("issue_close_pending", None)
                task["issue_closed_at"] = closed_at
                task["issue_closed_commit"] = receipt["commit_sha"]
                acknowledged.append(
                    {
                        key: receipt[key]
                        for key in (
                            "task_id",
                            "issue_ref",
                            "issue_number",
                            "commit_sha",
                        )
                    }
                )
            if acknowledged:
                write_tasks_to_handle(handle, current)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return acknowledged


__all__ = [
    "assign_issue",
    "close_issue",
    "issue_number",
    "normalize_issue_ref",
    "pending_issue_task_ids_for_owners",
    "settle_completed_task_issues",
]
