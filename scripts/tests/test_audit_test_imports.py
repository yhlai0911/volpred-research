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

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "audit_test_imports.py"

sys.path.insert(0, str(REPO / "scripts"))

import audit_test_imports  # noqa: E402


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


def _run_index(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(root), "--index"],
        capture_output=True,
        text=True,
        check=False,
    )


def _script_tree(root: Path, test: str, scripts: dict[str, str] | None = None) -> Path:
    (root / "src" / "volpred").mkdir(parents=True)
    (root / "src" / "volpred" / "__init__.py").write_text("", encoding="utf-8")
    (root / "scripts").mkdir()
    for rel, source in (scripts or {}).items():
        path = root / "scripts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_script_ref.py").write_text(test, encoding="utf-8")
    return root


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


def test_catches_attribute_missing_from_imported_submodule(tmp_path: Path) -> None:
    """The 5e36d1720 signature: old module landed, new attribute did not.

    Merely proving that ``failure_class.py`` exists is insufficient.  The staged
    test and worker both used a new attribute which only the omitted working-tree
    version supplied, so the candidate was importable but not executable.
    """
    _tree(
        tmp_path,
        source="def classify_output(output):\n    return None\n",
        test=(
            "from volpred.publisher import arc_dedup as failure_class\n\n"
            "def test_dead_shape():\n"
            "    assert failure_class.is_terse_fatal_only('Execution error')\n"
        ),
    )
    res = _run(tmp_path)
    assert res.returncode == 1, f"partial module surface passed:\n{res.stdout}{res.stderr}"
    assert "failure_class.is_terse_fatal_only" in res.stdout
    assert "does not define 'is_terse_fatal_only'" in res.stdout


def test_passes_attribute_present_on_imported_submodule(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source=(
            "def classify_output(output):\n    return None\n\n"
            "def is_terse_fatal_only(output):\n    return output == 'Execution error'\n"
        ),
        test=(
            "from volpred.publisher import arc_dedup as failure_class\n\n"
            "def test_dead_shape():\n"
            "    assert failure_class.is_terse_fatal_only('Execution error')\n"
        ),
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"complete module surface rejected:\n{res.stdout}{res.stderr}"


def test_dynamic_module_getattr_remains_opaque(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source="def __getattr__(name):\n    return 1\n",
        test="from volpred.publisher import arc_dedup\nVALUE = arc_dedup.runtime_value\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"dynamic module produced a false BAD:\n{res.stdout}{res.stderr}"


def test_star_reexport_module_is_treated_as_opaque(tmp_path: Path) -> None:
    """A module doing `from x import *` re-exports names we cannot enumerate; do not guess."""
    _tree(
        tmp_path,
        source="from math import *  # noqa: F403\n",
        test="from volpred.publisher.arc_dedup import sqrt\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"opaque module produced a false BAD:\n{res.stdout}"


@pytest.mark.parametrize(
    "statement",
    [
        "from scripts import missing_worker\n",
        "import scripts.missing_worker\n",
        "from scripts.missing_worker import run\n",
    ],
)
def test_catches_missing_scripts_imports(tmp_path: Path, statement: str) -> None:
    _script_tree(tmp_path, statement)
    res = _run(tmp_path)
    assert res.returncode == 1, f"missing scripts dependency passed:\n{res.stdout}{res.stderr}"
    assert "missing_worker" in res.stdout


@pytest.mark.parametrize(
    "statement",
    [
        'import importlib\nworker = importlib.import_module("scripts.missing_worker")\n',
        'import importlib as il\nworker = il.import_module("scripts.missing_worker")\n',
        'from importlib import import_module as load\nworker = load("scripts.missing_worker")\n',
        'worker = __import__("scripts.missing_worker")\n',
    ],
)
def test_catches_missing_literal_dynamic_imports(tmp_path: Path, statement: str) -> None:
    _script_tree(tmp_path, statement)
    res = _run(tmp_path)
    assert res.returncode == 1, f"dynamic dependency escaped:\n{res.stdout}{res.stderr}"
    assert "dynamically imports 'scripts.missing_worker'" in res.stdout


def test_marker_text_alone_does_not_make_module_opaque(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        source='NOTE = "globals()[ is documentation, not dynamic binding"\n',
        test="from volpred.publisher.arc_dedup import missing_name\n",
    )
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "missing_name" in res.stdout


def test_passes_scripts_module_and_namespace_package_imports(tmp_path: Path) -> None:
    _script_tree(
        tmp_path,
        "from scripts import worker\nfrom scripts.supervisor import phase_z\nimport scripts.worker\n",
        {
            "worker.py": "def run():\n    return 1\n",
            "supervisor/__init__.py": "",
            "supervisor/phase_z.py": "X = 1\n",
        },
    )
    res = _run(tmp_path)
    assert res.returncode == 0, f"valid scripts imports were rejected:\n{res.stdout}{res.stderr}"


def test_catches_missing_dynamic_script_spec_location(tmp_path: Path) -> None:
    _script_tree(
        tmp_path,
        """import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "missing_worker.py"
SPEC = importlib.util.spec_from_file_location("missing_worker", MODULE_PATH)
""",
    )
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "references missing 'scripts/missing_worker.py'" in res.stdout


def _init_index_repo(root: Path, *, include_auditor: bool = True) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _script_tree(root, "from scripts import worktree_only\n")
    (root / "scripts" / "worktree_only.py").write_text("X = 1\n", encoding="utf-8")
    if include_auditor:
        shutil.copy2(AUDIT, root / AUDIT.relative_to(REPO))
        subprocess.run(
            ["git", "-C", str(root), "add", "src", "tests", "scripts/audit_test_imports.py"],
            check=True,
        )
    else:
        subprocess.run(["git", "-C", str(root), "add", "src", "tests"], check=True)


def test_index_mode_ignores_working_tree_only_implementation(tmp_path: Path) -> None:
    _init_index_repo(tmp_path)
    res = _run_index(tmp_path)
    assert res.returncode == 1, f"working-tree-only script satisfied candidate:\n{res.stdout}{res.stderr}"
    assert "worktree_only" in res.stdout

    subprocess.run(["git", "-C", str(tmp_path), "add", "scripts/worktree_only.py"], check=True)
    complete = _run_index(tmp_path)
    assert complete.returncode == 0, f"complete candidate rejected:\n{complete.stdout}{complete.stderr}"


def test_index_mode_rejects_worktree_only_submodule_attribute(tmp_path: Path) -> None:
    """The exact 5e36d1720 split cannot become a candidate commit."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _tree(
        tmp_path,
        source="def classify_output(output):\n    return None\n",
        test="from volpred.publisher import arc_dedup as failure_class\n",
    )
    (tmp_path / "scripts").mkdir()
    shutil.copy2(AUDIT, tmp_path / AUDIT.relative_to(REPO))
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "src", "tests", "scripts/audit_test_imports.py"],
        check=True,
    )

    # The implementation grows the symbol in the working tree, but only its
    # consumer is staged.  A filesystem-based check would pass; candidate-index
    # closure must inspect the old staged module and reject the split.
    (tmp_path / "src/volpred/publisher/arc_dedup.py").write_text(
        "def classify_output(output):\n    return None\n\n"
        "def is_terse_fatal_only(output):\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/test_arc.py").write_text(
        "from volpred.publisher import arc_dedup as failure_class\n"
        "assert failure_class.is_terse_fatal_only('Execution error')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "tests/test_arc.py"], check=True)

    split = _run_index(tmp_path)
    assert split.returncode == 1, f"split candidate passed:\n{split.stdout}{split.stderr}"
    assert "failure_class.is_terse_fatal_only" in split.stdout

    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "src/volpred/publisher/arc_dedup.py"],
        check=True,
    )
    complete = _run_index(tmp_path)
    assert complete.returncode == 0, f"complete candidate rejected:\n{complete.stdout}{complete.stderr}"


def test_index_mode_fails_closed_without_candidate_auditor(tmp_path: Path) -> None:
    _init_index_repo(tmp_path, include_auditor=False)
    res = _run_index(tmp_path)
    assert res.returncode == 2
    assert "removes its own gate" in res.stderr


def test_trusted_index_mode_cannot_be_weakened_by_candidate_auditor(tmp_path: Path) -> None:
    _init_index_repo(tmp_path)
    candidate_auditor = tmp_path / "scripts" / "audit_test_imports.py"
    candidate_auditor.write_text(
        '#!/usr/bin/env python3\nprint("[audit-test-imports] 1 test files checked, 1 dependencies resolved, 0 bad")\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "scripts/audit_test_imports.py"],
        check=True,
    )

    res = _run_index(tmp_path)

    assert res.returncode == 1, f"candidate weakened its own bootstrap:\n{res.stdout}{res.stderr}"
    assert "worktree_only" in res.stdout


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


def test_bare_scripts_import_left_untracked_is_a_partial_commit(tmp_path: Path) -> None:
    """The 2026-07-19 CI red: committed test, untracked implementation.

    ``scripts/tests/test_check_experiment_artifacts.py`` put ``scripts/`` on
    ``sys.path`` and then imported its subject by BARE name, which matches no
    IMPORT_ROOTS prefix — so this gate passed the commit and CI died at
    collection instead.  The signature is index-vs-worktree, not "is it
    installed": a third-party name has no ``scripts/<name>.py`` on either side.
    """
    worktree, candidate = tmp_path / "wt", tmp_path / "cand"
    for root in (worktree, candidate):
        (root / "scripts" / "tests").mkdir(parents=True)
        (root / "scripts" / "tests" / "test_subject.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "import pytest\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "import subject\n",
            encoding="utf-8",
        )
    (worktree / "scripts" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")

    bad, _, _ = audit_test_imports.audit(candidate, worktree=worktree)
    assert [line for line in bad if "'subject'" in line], bad
    assert not [line for line in bad if "pytest" in line], (
        "third-party import must never be mistaken for a scripts-dir module"
    )

    (candidate / "scripts" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert audit_test_imports.audit(candidate, worktree=worktree)[0] == []
