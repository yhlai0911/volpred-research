"""Shared diagnostics helper — replaces scattered ``_warn_<module>()`` helpers.

Spec: ``.claude/rules/no-silent-fallback.md``. Background: 2026-06-23
governance sweep found 30+ ad-hoc ``_warn_<module>()`` helpers across
``scripts/`` with inconsistent formats. This module unifies them.

Usage::

    from volpred.ops.diagnostics import warn
    warn("dispatch", "claim failed", task_id=tid, err=str(exc))

Output format (stderr)::

    [<tag>] WARN <msg> | k1=v1 | k2=v2

Persistence (off by default) — set ``VOLPRED_DIAGNOSTICS_PERSIST=1`` to also
append JSONL records under ``storage/logs/diagnostics/<tag>.jsonl``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["warn", "PROJECT_ROOT", "LOG_DIR"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "storage" / "logs" / "diagnostics"

_TRUE = {"1", "true", "yes", "on"}
_MAX_CTX_VALUE_LEN = 200


def _persist_enabled() -> bool:
    return os.environ.get("VOLPRED_DIAGNOSTICS_PERSIST", "").strip().lower() in _TRUE


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        s = value
    elif isinstance(value, bytes):
        s = value.decode("utf-8", errors="replace")
    else:
        s = repr(value) if isinstance(value, BaseException) else str(value)
    if len(s) > _MAX_CTX_VALUE_LEN:
        s = s[:_MAX_CTX_VALUE_LEN] + "...<truncated>"
    return s


def _format_ctx(ctx: dict[str, Any]) -> str:
    if not ctx:
        return ""
    return " | " + " | ".join(f"{k}={_stringify(v)}" for k, v in ctx.items())


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _safe(x) for k, x in value.items()}
    return _stringify(value)


def warn(tag: str, msg: str, *, stream=None, **ctx: Any) -> None:
    """Emit a structured warning.

    Parameters
    ----------
    tag : str
        Short identifier (e.g. ``"dispatch"``, ``"refill"``). Used as both
        the stderr prefix and the persisted log file basename.
    msg : str
        Human-readable summary.
    stream : file-like, optional
        Override output stream. Defaults to ``sys.stderr``.
    **ctx
        Extra key/value context appended to the stderr line and persisted.
    """
    line = f"[{tag}] WARN {msg}{_format_ctx(ctx)}"
    print(line, file=stream if stream is not None else sys.stderr)

    if _persist_enabled():
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "tag": tag,
                "msg": msg,
                "ctx": {str(k): _safe(v) for k, v in ctx.items()},
            }
            with (LOG_DIR / f"{tag}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(
                f"[diagnostics] WARN persist failed | tag={tag} | err={exc}",
                file=sys.stderr,
            )
