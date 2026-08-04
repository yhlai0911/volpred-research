"""python_files must not feed gate_history/ blobs to the per-path gates.

Regression for 2026-08-05 K1730: the drift gate requires preserving as-run
entrypoint bytes under gate_history/ (never edited, by manifest contract),
while experiment_gates.python_files fed that same blob to the nested-dm scan
as a live violation — a deadlock on exactly the file the rules force to exist.
audit_nested_dm_misuse.scan_population already excludes gate_history (its
comment names the class: "this audit ... had simply not been told"); this
locks the same rule into the per-path iterator so the two can't drift apart
again.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from experiment_gates import python_files  # noqa: E402


def test_gate_history_blobs_are_excluded(tmp_path: Path) -> None:
    exp = tmp_path / "experiments" / "k9001"
    (exp / "gate_history").mkdir(parents=True)
    live = exp / "k9001.py"
    live.write_text("x = 1\n")
    blob = exp / "gate_history" / "deadbeef__k9001.py"
    blob.write_text("x = 0\n")
    (exp / "__pycache__").mkdir()
    cached = exp / "__pycache__" / "k9001.cpython-312.py"
    cached.write_text("x = 2\n")

    found = python_files(exp)
    assert live in found
    assert blob not in found, "gate_history blob leaked into the gate population"
    assert cached not in found


def test_explicit_file_target_still_returned(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    assert python_files(f) == [f]
