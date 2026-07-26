"""Bridge canonical runtime tasks to their GitHub planning issue.

``issue_ref`` is an optional foreign key, not a second queue.  New task ingress
stores one canonical spelling (``#<positive integer>``); tolerant read paths can
use :func:`issue_number` to skip malformed historical rows without blocking
local dispatch.
"""
from __future__ import annotations

import re
from typing import Any


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


__all__ = ["issue_number", "normalize_issue_ref"]
