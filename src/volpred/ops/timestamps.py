"""Shared ISO-timestamp parsing helper — replaces 8+ scattered try/except sites.

Spec: ``.claude/rules/no-silent-fallback.md`` Pattern B (timestamp parse).
Background: 2026-06-23 governance sweep found repeated ``datetime.fromisoformat``
calls wrapped in try/except across the control plane with inconsistent fallback
behaviour and ad-hoc ``_warn_*`` helpers. This module unifies them on top of
``volpred.ops.diagnostics.warn``.

Usage::

    from volpred.ops.timestamps import parse_iso_warn

    dt = parse_iso_warn(
        raw_value,
        tag="dispatch",
        field_name="blocked_until",
        fallback=None,
        task_id=task.get("id"),
    )
    if dt is None:
        continue
    # `dt` is tz-aware (UTC by default); caller decides next step.

Semantics:

* ``raw=None`` / empty string → return ``fallback`` *silently* (callers
  typically pre-check; we avoid noisy WARN for missing-field cases).
* Trailing ``Z`` is rewritten to ``+00:00`` so ``2026-06-23T13:00:00Z`` parses.
* Naive datetimes get ``assume_tz`` attached (UTC by default) so callers don't
  re-implement the ``if dt.tzinfo is None: dt.replace(...)`` boilerplate.
* Any ``(TypeError, ValueError)`` from ``fromisoformat`` → ``warn(tag, ...)``
  with ``field_name`` + truncated ``raw`` + ``err`` + caller-supplied ``ctx``,
  then return ``fallback``. **Never** silently swallows a real parse failure.

The fallback is caller-specified so semantics differ per site (e.g. dispatcher
treats "no last_fire_at" as due; refill skips the item; unblock keeps the task
blocked). The helper just funnels the diagnostic.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from typing import Any

from volpred.ops.diagnostics import warn

__all__ = ["parse_iso_warn"]

_RAW_HEAD_LEN = 80


def parse_iso_warn(
    raw: Any,
    tag: str,
    field_name: str,
    fallback: Any = None,
    *,
    assume_tz: tzinfo | None = timezone.utc,
    **ctx: Any,
) -> Any:
    """Parse an ISO-8601 string with structured WARN on failure.

    Parameters
    ----------
    raw : Any
        The raw value to parse. ``None`` / empty string returns ``fallback``
        silently (no WARN — those are missing-field cases, not parse failures).
    tag : str
        Diagnostics tag, e.g. ``"dispatch"``, ``"refill"``, ``"supervisor"``.
    field_name : str
        Logical field name (e.g. ``"blocked_until"``). Logged on failure.
    fallback : Any, default ``None``
        Value returned when parsing fails or input is empty. Callers
        encode the policy (skip-item / treat-as-due / keep-blocked) by
        their choice of fallback + downstream branching.
    assume_tz : tzinfo | None, keyword-only, default ``timezone.utc``
        Timezone attached to naive datetimes. Pass ``None`` to return a
        naive datetime unchanged.
    **ctx
        Extra context forwarded to ``warn()`` (e.g. ``task_id``).

    Returns
    -------
    datetime | Any
        Parsed tz-aware ``datetime`` on success, else ``fallback``.
    """
    if raw is None:
        return fallback
    text = str(raw).strip()
    if not text:
        return fallback
    parse_input = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(parse_input)
    except (TypeError, ValueError) as exc:
        warn(
            tag,
            f"{field_name} parse failed",
            field=field_name,
            raw=text[:_RAW_HEAD_LEN],
            err=f"{type(exc).__name__}: {exc}",
            **ctx,
        )
        return fallback
    if dt.tzinfo is None and assume_tz is not None:
        dt = dt.replace(tzinfo=assume_tz)
    return dt
