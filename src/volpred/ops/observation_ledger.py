"""Observation-period deadline ledger (WS-F5, refactor_plan_ops_master_2026_07).

Design principle 5 mechanized: any shadow / disabled-but-alive / deprecated
"observation" state must carry an explicit deadline and an action-on-expiry at
creation time. An expired item nobody decided on is a BREACH that
``scripts/dreaming_review.py::detect_observation_ledger_breach`` surfaces —
"still observing" without a deadline is how pregate shadow ran 18 days past its
"~1 week" note and how three disabled-but-alive legacies accumulated with no
retirement date (plan P3).

Single owner of the schema + path. Entry points:
    CLI:      uv run volpred ops observation {add,list,resolve,extend}
    detector: scripts/dreaming_review.py (reads via this module)

Statuses:
    observing  — active observation window; ``deadline`` REQUIRED.
    permanent  — deliberately observational forever (e.g. pregate shadow after
                 the token_ops_waste gate ruled "do not flip enforce"); deadline
                 forbidden, ``note`` REQUIRED (must cite the ruling).
    decided    — closed: the expiry action (or an explicit decision) happened.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import dump_json, load_json, project_path

SCHEMA = "observation_ledger.v1"
LEDGER_FILENAME = "observation_ledger.json"

STATUS_OBSERVING = "observing"
STATUS_PERMANENT = "permanent"
STATUS_DECIDED = "decided"
OPEN_STATUSES = frozenset({STATUS_OBSERVING, STATUS_PERMANENT})
ALL_STATUSES = frozenset({STATUS_OBSERVING, STATUS_PERMANENT, STATUS_DECIDED})


def ledger_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir) / "ops" / LEDGER_FILENAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_deadline(raw: Any) -> datetime | None:
    """Parse an ISO timestamp (date-only allowed → end of that day UTC)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None  # silent-ok: parse helper returns None for non-ISO input by design
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_ledger(storage_dir: str = "storage") -> dict[str, Any]:
    data = load_json(ledger_path(storage_dir), {"schema": SCHEMA, "updated_at": None, "items": []})
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    return {"schema": SCHEMA, "updated_at": data.get("updated_at"), "items": items}


def save_ledger(storage_dir: str, ledger: dict[str, Any]) -> None:
    ledger["schema"] = SCHEMA
    ledger["updated_at"] = _utc_now().isoformat()
    dump_json(ledger_path(storage_dir), ledger)


def _find(items: list[Any], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def add_item(
    storage_dir: str,
    *,
    item_id: str,
    what: str,
    action_on_expiry: str | None = None,
    deadline: str | None = None,
    status: str = STATUS_OBSERVING,
    started_at: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Register an observation item. Enforces principle 5 at creation time."""
    item_id = (item_id or "").strip()
    if not item_id:
        raise ValueError("observation item needs a non-empty id")
    if status not in (STATUS_OBSERVING, STATUS_PERMANENT):
        raise ValueError(f"new items must be 'observing' or 'permanent', got: {status}")
    if not (what or "").strip():
        raise ValueError("observation item needs a non-empty 'what'")

    if status == STATUS_OBSERVING:
        # Principle 5 core: an observation window without a deadline is the
        # exact failure mode this ledger exists to prevent.
        if parse_deadline(deadline) is None:
            raise ValueError(
                "observing items require a parseable ISO deadline "
                "(design principle 5: every observation window has an expiry)"
            )
        if not (action_on_expiry or "").strip():
            raise ValueError("observing items require action_on_expiry (what happens at the deadline)")
    else:  # permanent
        if deadline:
            raise ValueError("permanent-observational items must not carry a deadline")
        if not (note or "").strip():
            raise ValueError(
                "permanent items require a note citing the ruling that made them "
                "deadline-exempt (e.g. the token_ops_waste gate adjudication)"
            )

    current = (now or _utc_now()).astimezone(timezone.utc)
    ledger = load_ledger(storage_dir)
    if _find(ledger["items"], item_id) is not None:
        raise ValueError(f"observation item already exists: {item_id}")
    item: dict[str, Any] = {
        "id": item_id,
        "what": what.strip(),
        "started_at": (started_at or current.isoformat()),
        "deadline": deadline,
        "action_on_expiry": action_on_expiry,
        "status": status,
    }
    if note:
        item["note"] = note
    ledger["items"].append(item)
    save_ledger(storage_dir, ledger)
    return item


def resolve_item(
    storage_dir: str,
    item_id: str,
    *,
    resolution: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Close an item: the expiry action (or an explicit decision) happened."""
    if not (resolution or "").strip():
        raise ValueError("resolve requires a non-empty resolution (what was decided/done)")
    ledger = load_ledger(storage_dir)
    item = _find(ledger["items"], item_id)
    if item is None:
        raise ValueError(f"observation item not found: {item_id}")
    current = (now or _utc_now()).astimezone(timezone.utc)
    item["status"] = STATUS_DECIDED
    item["decided_at"] = current.isoformat()
    item["resolution"] = resolution.strip()
    save_ledger(storage_dir, ledger)
    return item


def extend_deadline(
    storage_dir: str,
    item_id: str,
    *,
    deadline: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Push an observing item's deadline out — allowed only WITH a reason.

    The audit trail of extensions stays on the item so "extended 5 times" is
    itself visible evidence, not silent drift back to deadline-less limbo.
    """
    if parse_deadline(deadline) is None:
        raise ValueError("extend requires a parseable ISO deadline")
    if not (reason or "").strip():
        raise ValueError("extend requires a non-empty reason")
    ledger = load_ledger(storage_dir)
    item = _find(ledger["items"], item_id)
    if item is None:
        raise ValueError(f"observation item not found: {item_id}")
    if item.get("status") != STATUS_OBSERVING:
        raise ValueError(f"only observing items can be extended (status={item.get('status')})")
    current = (now or _utc_now()).astimezone(timezone.utc)
    extensions = item.setdefault("extensions", [])
    extensions.append(
        {
            "at": current.isoformat(),
            "from": item.get("deadline"),
            "to": deadline,
            "reason": reason.strip(),
        }
    )
    item["deadline"] = deadline
    save_ledger(storage_dir, ledger)
    return item


def overdue_items(storage_dir: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Observing items past deadline, or malformed ones with no parseable deadline.

    Permanent items are exempt by definition (their exemption is the recorded
    ruling); decided items are closed. A malformed observing item (missing /
    unparseable deadline — only possible by editing the JSON around the CLI)
    is REPORTED as overdue rather than skipped: it is exactly the deadline-less
    limbo the ledger exists to prevent.
    """
    current = (now or _utc_now()).astimezone(timezone.utc)
    out: list[dict[str, Any]] = []
    for item in load_ledger(storage_dir)["items"]:
        if not isinstance(item, dict):
            continue
        if item.get("status") != STATUS_OBSERVING:
            continue
        deadline = parse_deadline(item.get("deadline"))
        if deadline is None or deadline < current:
            out.append(item)
    return out
