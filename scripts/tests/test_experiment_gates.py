"""The gates must arm where the agent actually works, and stay wired.

Two failures made this file necessary, both the same class:

1. The detectors were right and never ran. A dispatched agent works in a git
   worktree, runs its own `test_kXXXX.py`, and never runs `scripts/tests/`.
   K1701 was caught by hand; K1709 reproduced it 30 hours later with the
   nested-DM ratchet sitting unrun. A whole xhigh experiment was wasted.
2. The canonical-write guard had the mirror-image bug: `conftest.py` was
   .gitignore'd, so no worktree checkout ever received it and the guard was
   blind exactly where agents write.

So the two things worth asserting are not "does the detector work" -- the
ratchets already own that -- but "does the gate arm away from the canonical
checkout" and "is it still connected to the runner". A gate wired to nothing is
the bug we are fixing, so it gets its own test.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATE = REPO_ROOT / "scripts" / "experiment_gates.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import experiment_gates as eg  # noqa: E402


# The exact shape that got past everything on 2026-07-14: an augmented model
# built from the baseline's own columns, judged with a raw DM whose verdict
# feeds the claim sink.
K1709_V1 = """
base_cols = ["har_d", "har_w", "har_m"]
aug_cols = base_cols + ["etf_flow"]


def evaluate(loss_base, loss_aug):
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)
    verdict = "PASS" if dm_p < 0.05 else "NULL"
    return {"verdict": verdict, "dm_t": dm_t, "dm_p": dm_p}
"""

CLEAN = """
def compare(arima_loss, garch_loss):
    # Nonnested pair: raw DM is the right test here.
    dm_t, dm_p = dm_test(arima_loss, garch_loss, h=1)
    return dm_t, dm_p
"""


def _plant(root: Path, name: str, source: str) -> Path:
    path = root / "experiments" / name / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _portable_checkout(tmp_path: Path) -> Path:
    """A tree that has the gate and its baselines but is NOT the canonical repo.

    This is what a git worktree is, as far as the gate is concerned: the same
    tracked files at a different absolute path. If the gate only arms at the
    canonical root, it dies here -- which is precisely how the canonical-write
    guard stayed blind for agents.
    """
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "storage" / "ops").mkdir(parents=True)

    shutil.copy2(GATE, root / "scripts" / "experiment_gates.py")
    shutil.copy2(
        REPO_ROOT / "scripts" / "experiment_claim_surface.py",
        root / "scripts" / "experiment_claim_surface.py",
    )
    for gate in eg.GATES:
        shutil.copy2(
            REPO_ROOT / "storage" / "ops" / gate.baseline,
            root / "storage" / "ops" / gate.baseline,
        )
    for auditor in ("nested_dm_misuse", "dm_hac_lag", "mdd_scale_artifact", "fevd_ordering"):
        shutil.copy2(
            REPO_ROOT / "scripts" / f"audit_{auditor}.py",
            root / "scripts" / f"audit_{auditor}.py",
        )
    return root


def _run_gate(root: Path, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/experiment_gates.py", "run", "--path", target],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_k1709_v1_is_rejected(tmp_path: Path) -> None:
    """The fixture that wasted an xhigh experiment must not get through."""
    root = _portable_checkout(tmp_path)
    _plant(root, "k1709", K1709_V1)

    proc = _run_gate(root, "experiments/k1709")

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "nested-dm-misuse" in proc.stderr
    assert "experiments/k1709/k1709.py" in proc.stderr


def test_gate_arms_outside_the_canonical_checkout(tmp_path: Path) -> None:
    """The whole point: it must bite at a path that is not the canonical repo.

    The canonical-write guard passed in the main checkout and failed in every
    worktree, so it protected nothing where agents actually work. Run the gate
    from a tree that is not this repo and assert it still finds the violation.
    """
    root = _portable_checkout(tmp_path)
    _plant(root, "k9999", K1709_V1)
    assert root != REPO_ROOT

    proc = _run_gate(root, "experiments/k9999")

    assert proc.returncode == 1, (
        "The gate went blind away from the canonical checkout -- exactly the bug "
        "it exists to close.\n" + proc.stdout + proc.stderr
    )
    assert "experiments/k9999/k9999.py" in proc.stderr


def test_a_clean_experiment_passes(tmp_path: Path) -> None:
    """A gate that fails everything is not a gate."""
    root = _portable_checkout(tmp_path)
    _plant(root, "k9998", CLEAN)

    proc = _run_gate(root, "experiments/k9998")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout


def test_frozen_legacy_debt_does_not_block_a_new_agent(tmp_path: Path) -> None:
    """Baselined sites stay the ratchets' problem, not the agent's.

    An agent must never be failed for debt it did not create, or the gate will
    be routed around within a week.
    """
    root = _portable_checkout(tmp_path)
    baselined = json.loads(
        (root / "storage" / "ops" / "nested_dm_misuse_baseline.json").read_text()
    )["active"]["exposed"][0]

    src = REPO_ROOT / baselined
    dst = root / baselined
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    proc = _run_gate(root, str(Path(baselined).parent))

    assert proc.returncode == 0, (
        f"{baselined} is frozen in the baseline; the gate must not re-litigate "
        "it.\n" + proc.stdout + proc.stderr
    )


def test_invalid_fixed_memory_role_can_never_hide_behind_legacy_baseline(
    tmp_path: Path,
) -> None:
    root = _portable_checkout(tmp_path)
    baselined = json.loads(
        (root / "storage" / "ops" / "nested_dm_misuse_baseline.json").read_text()
    )["active"]["exposed"][0]
    source = (
        '"""Nested PRIMARY GW/DM verdict; nested-dm: diagnostic-only."""\n'
        "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {'schema': 'fake'}\n"
        "base_cols = ['x']\n"
        "aug_cols = base_cols + ['s']\n"
        "def classify(loss_base, loss_aug):\n"
        "    dm_t, _ = dm_test(loss_aug, loss_base, h=1)\n"
        "    return 'PASS' if dm_t < -3 else 'NULL'\n"
    )
    path = root / baselined
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    proc = _run_gate(root, str(path.parent))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "invalid_fixed_memory_evidence" in proc.stderr


def test_repeated_experiments_segment_cannot_alias_a_baselined_site(
    tmp_path: Path,
) -> None:
    root = _portable_checkout(tmp_path)
    path = root / "experiments" / "new" / "experiments" / "k1681" / "k1681.py"
    path.parent.mkdir(parents=True)
    path.write_text(K1709_V1, encoding="utf-8")
    proc = _run_gate(root, str(root / "experiments" / "new"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "experiments/new/experiments/k1681/k1681.py" in proc.stderr


def test_every_gate_has_a_baseline_and_a_named_owner() -> None:
    for gate in eg.GATES:
        assert (REPO_ROOT / "storage" / "ops" / gate.baseline).exists(), gate.name
        assert "Owner: scripts/tests/" in gate.remedy, (
            f"{gate.name} must name the ratchet that owns it, so a failing agent "
            "knows where the rule lives."
        )


def test_certify_arms_the_stdlib_mdd_owner() -> None:
    assert [gate.name for gate in eg.CERTIFY_GATES] == ["mdd-scale-artifact"]


def test_retired_sites_are_not_frozen_again(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(eg, "BASELINE_DIR", tmp_path)
    (tmp_path / "fixture.json").write_text(
        json.dumps(
            {
                "sites": ["experiments/legacy/legacy.py::raw_claim"],
                "retired": ["experiments/fixed/fixed.py::raw_claim"],
            }
        ),
        encoding="utf-8",
    )

    frozen = eg._baseline_sites("fixture.json")

    assert "experiments/legacy/legacy.py::raw_claim" in frozen
    assert "experiments/fixed/fixed.py::raw_claim" not in frozen


def test_the_runner_actually_calls_the_gate() -> None:
    """The gate must stay wired into the compute-queue completion path.

    This is the load-bearing assertion. Every other test here checks that the
    gate *works*; the bug we are fixing was a gate that worked and was never
    reached. `run_next` marking a job `completed` without consulting the gate is
    how K1709 shipped, so assert the call is there, on that path, by AST -- not
    by grep, and not by trusting that nobody will refactor it out.
    """
    source = (REPO_ROOT / "scripts" / "compute_queue.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    run_next = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_next"
    )
    calls = {
        node.func.id
        for node in ast.walk(run_next)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_experiment_gate_failure" in calls, (
        "run_next() no longer consults the experiment gates before marking a job "
        "completed. That is the K1709 hole reopening: the detectors are fine, "
        "they just never run on the agent's work."
    )

    completes = [
        node
        for node in ast.walk(run_next)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name)
            and t.value.id == "job"
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == "status"
            for t in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and node.value.value == "completed"
    ]
    assert len(completes) == 1, (
        "There must be exactly one place run_next() calls a job completed, so "
        "the gate cannot be bypassed by a second path."
    )
