"""Shared diagnostics helper — replaces scattered ``_warn_<module>()`` helpers.

Spec: ``.claude/rules/no-silent-fallback.md``. Background: 2026-06-23
governance sweep found 30+ ad-hoc ``_warn_<module>()`` helpers across
``scripts/`` with inconsistent formats. This module unifies them.

Usage::

    from volpred.diagnostics import warn
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "storage" / "logs" / "diagnostics"

_TRUE = {"1", "true", "yes", "on"}
_MAX_CTX_VALUE_LEN = 200

# Persistence is bounded by construction. A warning that fires every tick is
# exactly the case this log exists to catch, so the log must survive that case
# without becoming the next disk incident: at most one rotation generation is
# kept, capping a tag at 2 * _MAX_LOG_BYTES no matter how long the loop runs.
# (The FileReceiptStore reached 27.6 MB on the same premise that "it will not
# grow much" — an unbounded append-only diagnostic file is a known failure.)
_MAX_LOG_BYTES = 2 * 1024 * 1024


def _persist_enabled() -> bool:
    return os.environ.get("VOLPRED_DIAGNOSTICS_PERSIST", "").strip().lower() in _TRUE


def _rotate_if_oversized(path: Path) -> None:
    """Keep `<tag>.jsonl` under the cap, retaining one previous generation."""
    try:
        if path.stat().st_size < _MAX_LOG_BYTES:
            return
    except FileNotFoundError:
        return  # silent-ok: nothing written yet, nothing to rotate
    path.replace(path.with_suffix(".jsonl.1"))


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
            log_path = LOG_DIR / f"{tag}.jsonl"
            _rotate_if_oversized(log_path)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(
                f"[diagnostics] WARN persist failed | tag={tag} | err={exc}",
                file=sys.stderr,
            )
