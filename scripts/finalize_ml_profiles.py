#!/usr/bin/env python3
"""Finalize the permanent research/CI ML dependency split.

This file is temporary. The one-shot workflow must delete it before committing
its validated result. Every replacement is exact and fail-closed so a changed
anchor cannot produce a plausible but partial configuration.
"""
from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CI_SYNC_COMMAND = (
    "uv sync --frozen --no-default-groups "
    "--group dev --group ci-ml --extra dev"
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_pyproject() -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '[tool.uv]\n'
        '# Temporary Draft safety: until the finalizer patches the permanent workflows,\n'
        '# any delayed PR run must select the CPU profile rather than downloading CUDA.\n'
        '# The finalizer restores runtime-ml before regenerating and committing uv.lock.\n'
        'default-groups = ["dev", "ci-ml"]\n',
        '[tool.uv]\n'
        '# Existing `uv sync` / `uv run` behavior remains accelerator-capable by default.\n'
        '# CI must opt out of defaults and select `ci-ml` explicitly.\n'
        'default-groups = ["dev", "runtime-ml"]\n',
        "restore research default profile",
    )
    text = replace_once(
        text,
        '# Faster feedback on the queue, and the suite stops being cancelled by commits it did not need to run for. scripts/audit_ci_paths_ignore.py check keeps the\n',
        '# Faster feedback on the queue, and the suite stops being cancelled by a commit\n'
        '# it did not need to run for. scripts/audit_ci_paths_ignore.py check keeps the\n',
        "restore queue marker comment wrapping",
    )
    path.write_text(text, encoding="utf-8")


def patch_pytest_workflow() -> None:
    path = ROOT / ".github" / "workflows" / "pytest.yml"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '      VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST: "1"\n',
        '      VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST: "1"\n'
        '      # Only hosted CI promises the CPU-only ML environment.\n'
        '      VOLPRED_EXPECT_CPU_ML: "1"\n',
        "pytest CPU contract env",
    )
    text = replace_once(
        text,
        '      - name: Set up Python\n'
        '        run: uv python install 3.12\n'
        '      - name: Stamp a sentinel before the suite runs\n',
        '      - name: Set up Python\n'
        '        run: uv python install 3.12\n'
        '      - name: Sync explicit Linux CPU CI profile\n'
        '        run: >-\n'
        '          uv sync --frozen --no-default-groups\n'
        '          --group dev --group ci-ml --extra dev\n'
        '      - name: Stamp a sentinel before the suite runs\n',
        "pytest explicit CPU sync",
    )
    text = replace_once(
        text,
        '        run: uv run python scripts/validate_feed_audience.py\n',
        '        run: uv run --no-sync python scripts/validate_feed_audience.py\n',
        "pytest audience no-resync",
    )
    text = replace_once(
        text,
        '        run: uv run --extra dev python -m pytest -q -p no:cacheprovider -m "not real_queue"\n',
        '        run: uv run --no-sync python -m pytest -q -p no:cacheprovider -m "not real_queue"\n',
        "pytest suite no-resync",
    )
    path.write_text(text, encoding="utf-8")


def patch_queue_workflow() -> None:
    path = ROOT / ".github" / "workflows" / "queue-invariants.yml"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '      VOLPRED_NO_REMOTE_READ: "1"\n',
        '      VOLPRED_NO_REMOTE_READ: "1"\n'
        '      # This job explicitly promises the CPU-only ML runtime.\n'
        '      VOLPRED_EXPECT_CPU_ML: "1"\n',
        "queue CPU contract env",
    )
    text = replace_once(
        text,
        '      - name: Set up Python\n'
        '        run: uv python install 3.12\n'
        '      - name: Run the live-queue ratchets\n',
        '      - name: Set up Python\n'
        '        run: uv python install 3.12\n'
        '      - name: Sync explicit Linux CPU CI profile\n'
        '        run: >-\n'
        '          uv sync --frozen --no-default-groups\n'
        '          --group dev --group ci-ml --extra dev\n'
        '      - name: Run the live-queue ratchets\n',
        "queue explicit CPU sync",
    )
    text = replace_once(
        text,
        '        run: uv run --extra dev python -m pytest -q -p no:cacheprovider -m real_queue\n',
        '        run: uv run --no-sync python -m pytest -q -p no:cacheprovider -m real_queue\n',
        "queue ratchets no-resync",
    )
    path.write_text(text, encoding="utf-8")


def patch_contract_test() -> None:
    path = ROOT / "tests" / "test_linux_cpu_torch.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'ONE_SHOT_WORKFLOW = "refresh-ml-profiles-lock.yml"\n',
        "",
        "remove one-shot workflow exception",
    )
    text = replace_once(
        text,
        "def test_every_permanent_uv_workflow_is_bound_to_the_cpu_profile() -> None:\n",
        "def test_every_uv_workflow_is_bound_to_the_cpu_profile() -> None:\n",
        "rename permanent workflow audit",
    )
    text = replace_once(
        text,
        '    permanent_paths = [\n'
        '        path for path in workflow_paths if path.name != ONE_SHOT_WORKFLOW\n'
        '    ]\n'
        '    assert permanent_paths, "permanent workflow inventory unexpectedly empty"\n\n'
        '    for path in permanent_paths:\n',
        '    assert workflow_paths, "workflow inventory unexpectedly empty"\n\n'
        '    for path in workflow_paths:\n',
        "remove one-shot audit exclusion",
    )
    path.write_text(text, encoding="utf-8")


def validate_static_result() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["default-groups"] == ["dev", "runtime-ml"]

    pytest_text = (
        ROOT / ".github" / "workflows" / "pytest.yml"
    ).read_text(encoding="utf-8")
    queue_text = (
        ROOT / ".github" / "workflows" / "queue-invariants.yml"
    ).read_text(encoding="utf-8")
    for label, workflow_text in (("pytest", pytest_text), ("queue", queue_text)):
        assert 'VOLPRED_EXPECT_CPU_ML: "1"' in workflow_text, label
        assert "Sync explicit Linux CPU CI profile" in workflow_text, label
        assert CI_SYNC_COMMAND in " ".join(workflow_text.split()), label
    assert "uv run --no-sync python scripts/validate_feed_audience.py" in pytest_text
    assert (
        'uv run --no-sync python -m pytest -q -p no:cacheprovider -m "not real_queue"'
        in pytest_text
    )
    assert (
        "uv run --no-sync python -m pytest -q -p no:cacheprovider -m real_queue"
        in queue_text
    )

    test_text = (ROOT / "tests" / "test_linux_cpu_torch.py").read_text(
        encoding="utf-8"
    )
    assert "ONE_SHOT_WORKFLOW" not in test_text
    assert "test_every_uv_workflow_is_bound_to_the_cpu_profile" in test_text


def main() -> None:
    patch_pyproject()
    patch_pytest_workflow()
    patch_queue_workflow()
    patch_contract_test()
    validate_static_result()
    print("Permanent ML profile files patched and statically validated.")


if __name__ == "__main__":
    main()
