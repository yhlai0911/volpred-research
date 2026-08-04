"""The pytest workflow's paths-ignore must never hide a file the suite reads.

Every paths-ignore entry is an assertion that changing those files cannot change
a test outcome. Such an assertion is true when written and goes false silently:
a test grows a new dependency, the entry stays, and CI starts reporting green
for commits it never ran. The failure mode is a PASSING build, so nothing but a
mechanical check will catch it — see docs/error_log.md 2026-08-04, where a
blanket '**/*.md' let a governance commit break the suite unreported.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_ci_paths_ignore import (  # noqa: E402
    DEPENDENCIES,
    covered_by,
    load_paths_ignore,
)


def test_paths_ignore_hides_nothing_the_suite_reads() -> None:
    patterns = load_paths_ignore()
    recorded = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
    read_by = recorded.get("read_by", {})

    hidden = []
    for path in recorded["paths"]:
        pattern = covered_by(path, patterns)
        if pattern:
            hidden.append(f"{path} (read by {read_by.get(path, '?')}) hidden by {pattern!r}")

    assert not hidden, (
        "paths-ignore covers files the suite actually opens, so CI would skip "
        "commits that can break tests:\n  " + "\n  ".join(hidden)
    )


def test_recorded_dependencies_are_still_tracked() -> None:
    """A recording of untracked paths would be dead weight that never fails.

    Untracked files cannot appear in a commit, so paths-ignore can never hide
    them. When one gets retired from Git (as the workspace receipt ledger was
    in 3fb25fabc), its entry should leave the recording too — otherwise the
    audit slowly fills with paths that constrain nothing.
    """
    recorded = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "storage"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )

    stale = [p for p in recorded["paths"] if p not in tracked]
    assert not stale, (
        "these recorded dependencies are no longer tracked by Git; re-freeze "
        "the recording:\n  " + "\n  ".join(stale)
    )


def test_audit_cli_check_passes() -> None:
    """The CLI is the entry point a human runs; keep it green too."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_ci_paths_ignore.py"), "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_audit_fails_when_it_can_see_nothing(monkeypatch) -> None:
    """An audit that inspects an empty set must fail, not pass.

    Every check in cmd_check is a universal quantifier, and `all([])` is True:
    an empty dependency recording finds no violations, an empty marker sweep
    finds no orphans, and the audit prints OK having verified nothing. The
    same shape shipped a real misreport on 2026-08-04 — a CI watcher filtered
    on a field that returned zero rows, so its wait loop declared a 14-minute
    suite complete in 25 seconds (docs/error_log.md).

    Truncate config/ci_test_repo_dependencies.json, or break the marker sweep,
    and this gate has to say so rather than wave the build through.
    """
    import argparse

    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_ci_paths_ignore as gate

    monkeypatch.setattr(gate, "load_dependencies", lambda: [])
    assert gate.cmd_check(argparse.Namespace()) == 1, (
        "an empty dependency recording must fail the audit"
    )

    # Restore dependencies, blind the other sweep instead.
    monkeypatch.undo()
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_ci_paths_ignore as gate2

    monkeypatch.setattr(gate2, "find_real_queue_test_files", lambda: [])
    assert gate2.cmd_check(argparse.Namespace()) == 1, (
        "a marker sweep that finds nothing must fail the audit"
    )
