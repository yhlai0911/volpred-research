"""Compatibility surface for :mod:`volpred.diagnostics`."""

from typing import Any

from volpred import diagnostics as _canonical

PROJECT_ROOT = _canonical.PROJECT_ROOT
LOG_DIR = _canonical.LOG_DIR
_persist_enabled = _canonical._persist_enabled


def warn(tag: str, msg: str, *, stream=None, **ctx: Any) -> None:
    """Forward while preserving legacy ``LOG_DIR`` monkeypatches."""
    _canonical.LOG_DIR = LOG_DIR
    _canonical.warn(tag, msg, stream=stream, **ctx)


__all__ = ["warn", "PROJECT_ROOT", "LOG_DIR"]
