"""Bounded GitHub-comment to self-repair admission.

GitHub comments are an observation channel, not an arbitrary code-execution
API.  A comment becomes machine repair input only when it carries the explicit
marker ``<!-- volpred-repair kind=<incident-kind> -->`` and the kind already has
an incident execution contract.  Everything else remains notification-only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from volpred.ops.github_comment_notifications import GitHubComment

_REPAIR_MARKER = re.compile(
    r"<!--\s*volpred-repair\s+kind=(?P<kind>[a-z0-9_]+)\s*-->",
    re.IGNORECASE,
)


def repair_kind(body: str) -> str | None:
    """Return a normalized explicit repair kind, or ``None`` for prose."""
    match = _REPAIR_MARKER.search(str(body or ""))
    return match.group("kind").lower() if match else None


def resolve_github_comment_repair(
    comment: GitHubComment,
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Materialize one explicitly marked comment through incident lifecycle."""
    kind = repair_kind(comment.body)
    base = {
        "comment_key": comment.delivery_key,
        "comment_url": comment.url,
        "issue_ref": f"#{comment.number}",
        "kind": kind,
    }
    if kind is None:
        return {**base, "action": "notify_only", "reason": "no_repair_marker"}

    from volpred.ops import incident

    if kind not in incident.MACHINE_SELF_REPAIR_OUTPUT_PATHS:
        return {
            **base,
            "action": "blocked",
            "reason": "unsupported_repair_kind",
            "allowed_kinds": sorted(incident.MACHINE_SELF_REPAIR_OUTPUT_PATHS),
        }

    from volpred.ops.alert_remediation import remediate_internal_alert

    condition = {
        "id": kind,
        "breached": True,
        "level": "warn",
        "title": f"GitHub repair request: {kind}",
        "body": (
            f"GitHub comment `{comment.delivery_key}` explicitly requested a "
            f"bounded `{kind}` repair.\n\n{comment.body}"
        ),
        "fingerprint": [comment.url],
        "issue_ref": f"#{comment.number}",
        "github_comment_url": comment.url,
        "github_comment_key": comment.delivery_key,
    }
    result = remediate_internal_alert(
        condition,
        alert_key=kind,
        storage_dir=storage_dir,
        now=now or datetime.now(UTC),
    )
    return {
        **base,
        "action": "repair_admitted" if result.get("created") else "repair_active",
        "repair": result,
    }


__all__ = ["repair_kind", "resolve_github_comment_repair"]
