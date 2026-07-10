"""Regression gate for the 2026-07-10 canonical-state leak.

A full `pytest` run rewrote storage/publication_candidates.json: a refill test
monkeypatched CANDIDATES to tmp_path but not ROOT, its fixture had no
`generated_at`, so _ensure_candidates_fresh() judged the candidates stale and
spawned the real builder against the live checkout.

The gate lives at the writer, not at each caller: `_ensure_candidates_fresh()` may
still decide to spawn the builder, but the builder itself refuses to land on
canonical state. That holds through `subprocess`/`uv run` because env is inherited.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from volpred.ops.canonical_write import (
    ENV_FLAG,
    CanonicalWriteBlocked,
    canonical_writes_disabled,
    guard_canonical_write,
)

ROOT = Path(__file__).resolve().parents[1]


def test_conftest_enables_the_gate():
    """If this fails, every other guard in this file is inert."""
    assert canonical_writes_disabled(), f"{ENV_FLAG} must be set by tests/conftest.py"


@pytest.mark.parametrize(
    "rel",
    [
        "storage/publication_candidates.json",
        "storage/reports/feed.json",
        "storage/memory/knowledge.json",
        "storage/nested/deep/whatever.json",
        "storage",
    ],
)
def test_guard_blocks_canonical_paths(rel):
    with pytest.raises(CanonicalWriteBlocked):
        guard_canonical_write(ROOT / rel)


def test_guard_allows_tmp_path(tmp_path):
    guard_canonical_write(tmp_path / "storage" / "publication_candidates.json")


def test_guard_allows_repo_paths_outside_storage():
    guard_canonical_write(ROOT / "experiments" / "k9999" / "k9999_results.json")


def test_guard_is_noop_when_flag_unset(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    guard_canonical_write(ROOT / "storage" / "publication_candidates.json")


@pytest.mark.parametrize(
    "launcher",
    [
        pytest.param([sys.executable], id="python"),
        # The form refill_task_pool._ensure_candidates_fresh() actually spawns.
        pytest.param(["uv", "run", "python"], id="uv-run"),
    ],
)
def test_builder_refuses_to_write_canonical_output_in_subprocess(launcher):
    """The gate must survive the subprocess hop — that's how refill reaches the builder.

    Env is inherited, so the child hits guard_canonical_write() and exits non-zero
    instead of clobbering the live file.
    """
    canonical = ROOT / "storage" / "publication_candidates.json"
    before = canonical.stat().st_mtime_ns if canonical.exists() else None

    proc = subprocess.run(
        [*launcher, str(ROOT / "scripts" / "build_publication_candidates.py")],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=str(ROOT),
    )

    assert proc.returncode != 0, "builder must fail closed, not rewrite canonical state"
    assert "CanonicalWriteBlocked" in proc.stderr or ENV_FLAG in proc.stderr, proc.stderr[-2000:]

    after = canonical.stat().st_mtime_ns if canonical.exists() else None
    assert after == before, f"builder rewrote {canonical}"
