"""Repository-level ownership gates for daemon-written runtime state."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRENDING_VERIFICATION_LOG = (
    "storage/logs/trending_primary_source_verification.jsonl"
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_trending_verification_audit_is_runtime_owned_not_git_owned() -> None:
    """Scheduled audit append churn must never enter PHASE-Z dirty ownership."""
    ignored = _git(
        "check-ignore",
        "--no-index",
        "--quiet",
        "--",
        TRENDING_VERIFICATION_LOG,
    )
    assert ignored.returncode == 0, (
        "the scheduled trending verification audit lacks committed ignore policy"
    )

    tracked = _git("ls-files", "--error-unmatch", "--", TRENDING_VERIFICATION_LOG)
    assert tracked.returncode != 0, (
        "the scheduled trending verification audit is still Git-owned"
    )
