"""Regression gate for scripts/audit_test_imports.py.

Anchored on the 2026-07-14 incident: commit 0fef6fa3b carried
tests/test_arc_dedup_calibration.py importing ARC_SIGNATURE_SCHEMA_VERSION,
is_arc_near_miss and strip_exclusion_scopes from volpred.publisher.arc_dedup —
none of which that commit's arc_dedup.py defined. pytest died at collection and
the main Test Suite was red until the source commit landed.

The first test below reconstructs exactly that shape. If it ever passes the
audit, the pre-push gate has stopped gating and the incident can recur.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "audit_test_imports.py"


def _tree(root: Path, source: str, test: str) -> Path:
    (root / "src" / "volpred" / "publisher").mkdir(parents=True)
    (root / "src" / "volpred" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "volpred" / "publisher" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "volpred" / "publisher" / "arc_dedup.py").write_text(source, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_arc.py").write_text(test, encoding="utf-8")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_catches_test_importing_symbol_source_does_not_define(tmp_path: Path) -> None:
    """The 0fef6fa3b signature: test landed, source change did not."""
    _tree(
        tmp_path,
        source="def arc_signature(x):\n    return x\n",
        test="from volpred.publisher.arc_dedup import ARC_SIGNATURE_SCHEMA_VERSION, arc_signature\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 1, f"gate did not fire:\n{res.stdout}{res.stderr}"
    assert "ARC_SIGNATURE_SCHEMA_VERSION" in res.stdout
    assert "arc_signature" not in res.stdout.replace("ARC_SIGNATURE_SCHEMA_VERSION", "")


def test_passes_when_source_defines_everything(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source='ARC_SIGNATURE_SCHEMA_VERSION = "v4"\n\n\ndef arc_signature(x):\n    return x\n',
        test="from volpred.publisher.arc_dedup import ARC_SIGNATURE_SCHEMA_VERSION, arc_signature\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"false positive:\n{res.stdout}{res.stderr}"


def test_catches_import_from_module_that_does_not_exist(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source="X = 1\n",
        test="from volpred.publisher.ghost import X\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "does not exist" in res.stdout


def test_submodule_import_is_not_a_false_positive(tmp_path: Path) -> None:
    """`from volpred.publisher import arc_dedup` — a submodule, not an __init__ binding."""
    _tree(tmp_path, source="X = 1\n", test="from volpred.publisher import arc_dedup\n")
    res = _run(tmp_path)
    assert res.returncode == 0, f"submodule flagged as missing:\n{res.stdout}"


def test_star_reexport_module_is_treated_as_opaque(tmp_path: Path) -> None:
    """A module doing `from x import *` re-exports names we cannot enumerate; do not guess."""
    _tree(
        tmp_path,
        source="from math import *  # noqa: F403\n",
        test="from volpred.publisher.arc_dedup import sqrt\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"opaque module produced a false BAD:\n{res.stdout}"


def test_real_repo_tree_is_clean() -> None:
    """The live tree must satisfy its own gate — and the gate must actually scan it."""
    res = _run(REPO)
    assert res.returncode == 0, f"repo has broken test imports:\n{res.stdout}"
    assert "test files checked" in res.stdout
    checked = int(res.stdout.split("] ")[1].split(" test files")[0])
    assert checked > 0, "coverage canary: audit scanned 0 test files"


@pytest.mark.parametrize("missing", ["src", "src/volpred"])
def test_refuses_to_pass_a_tree_it_cannot_read(tmp_path: Path, missing: str) -> None:
    """A gate that cannot see the source must exit 2, not 0."""
    (tmp_path / "tests").mkdir()
    res = _run(tmp_path)
    assert res.returncode == 2, f"missing {missing} tree silently passed:\n{res.stdout}{res.stderr}"
