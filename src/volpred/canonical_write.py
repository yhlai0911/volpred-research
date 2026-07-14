"""Fail closed before test code mutates this checkout's canonical state.

This module deliberately lives directly under :mod:`volpred`: importing the
guard must not execute the eager ``volpred.ops`` package initializer. Writer
primitives use it at their lowest mutation boundary so indirect callers and
subprocesses inherit the same protection.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "ENV_FLAG",
    "CanonicalWriteBlocked",
    "canonical_writes_disabled",
    "guard_canonical_write",
    "is_canonical_path",
]

ENV_FLAG = "VOLPRED_NO_CANONICAL_WRITE"
GUARDED_DIRS = ("storage",)


class CanonicalWriteBlocked(BaseException):
    """Non-recoverable test-gate sentinel for a canonical write attempt.

    This deliberately derives directly from :class:`BaseException`, not from
    ``Exception``.  Production writers contain many best-effort
    ``except Exception`` boundaries (alerts, audit logs, refill fallbacks).  If
    the sentinel were an ordinary application exception, one of those
    boundaries could turn a blocked canonical write into an apparently passing
    test.  The flag is test-only, so treating this like ``KeyboardInterrupt`` or
    ``SystemExit`` is intentional: cleanup ``finally`` blocks still run, while
    application-level fail-open handlers cannot consume the enforcement signal.
    """


def _repo_root() -> Path:
    # src/volpred/canonical_write.py -> volpred -> src -> <repo root>
    return Path(__file__).resolve().parents[2]


def canonical_writes_disabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def is_canonical_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is canonical state in this checkout."""
    target = Path(path).resolve()
    root = _repo_root()
    return any(
        target == guarded or guarded in target.parents
        for guarded in ((root / name).resolve() for name in GUARDED_DIRS)
    )


def guard_canonical_write(path: str | os.PathLike[str]) -> None:
    """Raise before a canonical mutation when the test-side gate is armed.

    Paths outside this checkout (including pytest ``tmp_path`` directories)
    remain writable.
    """
    if canonical_writes_disabled() and is_canonical_path(path):
        raise CanonicalWriteBlocked(
            f"{ENV_FLAG}=1 blocks write to canonical state: {Path(path).resolve()}\n"
            "A test tried to rewrite shared repo state. Redirect every writer "
            "path to tmp_path, including paths reached through subprocesses."
        )
