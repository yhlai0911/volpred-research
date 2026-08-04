"""A gate that inspects an empty set must fail, not pass.

Every sweep-style audit in this repo ends in a universal quantifier: no
corrupted file, no hidden dependency, no orphaned marker. `all([])` is True and
`if bad:` is False when nothing was collected, so an audit whose collector
breaks does not go quiet -- it goes GREEN, and prints a reassuring summary with
a zero in it that nobody reads twice.

This is not hypothetical. On 2026-08-04 a CI wait loop filtered runs on a field
that returned zero rows; `[] | length == 0` meant "nothing is still running",
so it declared a 14-minute suite complete after 25 seconds, and a red gate was
reported to the owner as green (docs/error_log.md). The same afternoon,
audit_ci_paths_ignore was found to print "0 recorded dependencies ... OK" when
handed an empty recording -- the gate protecting CI's trigger rules could
itself verify nothing and say so approvingly.

Each case below BLINDS a real gate the way a broken collector would, and
asserts it refuses. Adding a sweep-style audit? Add it here, or state in its
own code why an empty scan is legitimate for it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_source_encoding_audit_refuses_an_empty_sweep(tmp_path: Path) -> None:
    """Roots that exist but yield no files mean the collector is broken.

    The pre-existing missing-root check does not cover this: a renamed
    directory is caught, a filter that silently excludes everything is not.
    """
    for name in ("src", "tests", "scripts"):
        (tmp_path / name).mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_source_encoding.py"),
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        "a sweep that collected zero files reported success:\n" + result.stdout
    )
    assert "0 files" in result.stderr


def test_paths_ignore_audit_refuses_an_empty_recording(monkeypatch) -> None:
    """An empty dependency recording makes the overlap check vacuous."""
    import audit_ci_paths_ignore as gate

    monkeypatch.setattr(gate, "load_dependencies", lambda: [])

    assert gate.cmd_check(argparse.Namespace()) == 1


def test_paths_ignore_audit_refuses_a_blind_marker_sweep(monkeypatch) -> None:
    """Finding no real_queue tests means the sweep broke, or the split is dead.

    Either way the orphan check below it proves nothing, and Test Suite is
    still deselecting a marker while queue-invariants.yml still exists.
    """
    import audit_ci_paths_ignore as gate

    monkeypatch.setattr(gate, "find_real_queue_test_files", lambda: [])

    assert gate.cmd_check(argparse.Namespace()) == 1


def test_provenance_ratchet_refuses_an_empty_knowledge_base(tmp_path: Path) -> None:
    """Zero entries yield zero violations, which any baseline accepts.

    The ratchet asks "violations <= 284?". A truncated or wrongly-pathed
    knowledge.json answers 0, passes, and reports the knowledge base as clean
    at the exact moment it has been emptied.
    """
    empty = tmp_path / "knowledge.json"
    empty.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_knowledge_provenance.py"),
            "--path",
            str(empty),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        "an empty knowledge base was reported as clean:\n" + result.stdout
    )
    assert "no entries" in result.stderr


def test_provenance_ratchet_still_passes_on_the_real_knowledge_base() -> None:
    """The guard must not red the healthy path."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_knowledge_provenance.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_source_encoding_audit_passes_on_a_populated_tree(tmp_path: Path) -> None:
    """The fail-closed guard must not turn a healthy sweep red.

    Paired with the blinding test on purpose: a guard that rejects everything
    satisfies that one alone, and is worse than the hole it closes.

    Deliberately a fixture tree rather than this repo. Sweeping the real tree
    makes audit_source_encoding py_compile every file, and inside the pytest
    job those __pycache__ directories are already root-owned from the sudo
    system-dependency step, so the healthy path fails on PermissionError for
    reasons that have nothing to do with encoding. The real tree is swept by
    the Source Encoding Gate workflow in its own clean job -- that is its
    owner, and repeating it here buys nothing.
    """
    for name in ("src", "tests", "scripts"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "clean.py").write_text(
            "# clean UTF-8, em-dash included — should not trip the sweep\n",
            encoding="utf-8",
        )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_source_encoding.py"),
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 files checked" in result.stdout
