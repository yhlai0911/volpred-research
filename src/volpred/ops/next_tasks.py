"""Helpers for the legacy ``storage/next_tasks.json`` pending queue."""
from __future__ import annotations

import re
from typing import Any


class InvalidTaskPriority(ValueError):
    """Raised when a task priority cannot be represented as a positive int."""


_DIGIT_PRIORITY_RE = re.compile(r"^\d+$")
_P_LABEL_PRIORITY_RE = re.compile(r"^[Pp]+(\d+)$")


def normalize_priority(value: Any, *, default: int | None = None) -> int:
    """Return an integer priority from legacy queue values.

    Accepted forms:
    - ``1`` / ``2`` / ... (int)
    - ``"1"`` / ``"2"`` / ... (legacy string int)
    - ``"P1"`` / ``"P2"`` / ... (legacy label)

    A few old rows accidentally contain repeated ``P`` prefixes because display
    code prepended ``P`` to an already-labelled value. Treat those as legacy
    labels too, so the one-time queue sweep can remove all string priorities.
    """
    if value is None:
        if default is not None:
            return _validate_priority(default)
        raise InvalidTaskPriority("priority is missing")

    if isinstance(value, bool):
        raise InvalidTaskPriority(f"priority must be int-like, got bool {value!r}")

    if isinstance(value, int):
        return _validate_priority(value)

    if isinstance(value, float) and value.is_integer():
        return _validate_priority(int(value))

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            if default is not None:
                return _validate_priority(default)
            raise InvalidTaskPriority("priority is blank")
        if _DIGIT_PRIORITY_RE.fullmatch(raw):
            return _validate_priority(int(raw))
        match = _P_LABEL_PRIORITY_RE.fullmatch(raw)
        if match:
            return _validate_priority(int(match.group(1)))

    raise InvalidTaskPriority(f"priority must be int-like, got {value!r}")


def _validate_priority(priority: int) -> int:
    if priority < 1:
        raise InvalidTaskPriority(f"priority must be >= 1, got {priority!r}")
    return priority


def normalize_task_priority(
    task: dict[str, Any],
    *,
    default_priority: int = 3,
    mutate: bool = True,
) -> bool:
    """Normalize one task's ``priority`` field.

    Returns ``True`` when the stored representation would change. Non-dict
    callers should filter before calling this helper; the function is strict on
    malformed priority values so writers fail before corrupting the queue.
    """
    old = task.get("priority")
    new = normalize_priority(old, default=default_priority)
    changed = old != new or not isinstance(old, int)
    if mutate and changed:
        task["priority"] = new
    return changed


def normalize_task_priorities(
    tasks: list[dict[str, Any]],
    *,
    default_priority: int = 3,
    mutate: bool = True,
) -> int:
    """Normalize every dict entry in a next_tasks payload; return change count."""
    changed = 0
    for task in tasks:
        if isinstance(task, dict) and normalize_task_priority(
            task,
            default_priority=default_priority,
            mutate=mutate,
        ):
            changed += 1
    return changed


def priority_sort_key(value: Any, *, default: int = 999) -> int:
    """Priority key for read paths; invalid values sort last."""
    try:
        return normalize_priority(value, default=default)
    except InvalidTaskPriority:
        return default
