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


@pytest.fixture(autouse=True)
def _require_gate_armed():
    """Prove the gate is armed BEFORE any probe below performs a forbidden write.

    The destructive probes here deliberately aim a real writer at a real canonical
    path and rely on the gate to raise. If the flag is not armed, the write simply
    succeeds and the assertion fails afterwards — too late. Not hypothetical: on
    2026-07-10 23:02 a sibling gate-probe under `scripts/tests/` (a tree no conftest
    covers, so the flag was never set there) blanked the live dispatch_state.json
    and caused a duplicate opus dispatch.

    `test_conftest_enables_the_gate` below is not sufficient on its own: nothing
    orders it first, and selecting a single probe by node id skips it entirely.
    """
    if not canonical_writes_disabled():
        pytest.fail(
            f"{ENV_FLAG} is not armed — refusing to run the canonical-write probes; "
            "they would write live state instead of being blocked. Check that a "
            "conftest.py covering this directory sets the flag."
        )


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


# ---------------------------------------------------------------------------
# 2026-07-10 round 2. The first sweep watched files git could see. These two
# writers land on gitignored canonical state, so `git status` stays clean while
# the damage accumulates — they were found by diffing the storage/ tree against
# a timestamp marker across a full suite run, not by reading the diff.


def test_pending_sessions_writer_refuses_canonical_path():
    """run_due_jobs binds PENDING_SESSIONS_PATH at import from the real PROJECT_ROOT,
    so redirecting PROJECT_ROOT alone still lands on the live control-plane file."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_due_jobs_guard_probe", ROOT / "scripts" / "run_due_jobs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    canonical = ROOT / "storage" / "ops" / "pending_sessions.json"
    before = canonical.stat().st_mtime_ns if canonical.exists() else None

    with pytest.raises(CanonicalWriteBlocked):
        module._save_pending_sessions({"jobs": {}})

    after = canonical.stat().st_mtime_ns if canonical.exists() else None
    assert after == before, f"_save_pending_sessions rewrote {canonical}"


def test_notification_writer_refuses_canonical_path():
    """VOLPRED_NO_EMAIL blocks the SMTP send, not the local record. An alert fired
    from any test used to persist a real notification into storage/notifications/."""
    from volpred.publisher.email_notifier import EmailNotifier

    notifier = EmailNotifier()  # default storage_dir="storage" → repo-relative

    with pytest.raises(CanonicalWriteBlocked):
        notifier._write_notification_file({"id": "guard_probe", "body": "x"})

    with pytest.raises(CanonicalWriteBlocked):
        notifier._save_log([])

    assert not (ROOT / "storage" / "notifications" / "guard_probe.json").exists()


def test_notification_writer_allows_tmp_storage(tmp_path):
    """A test that genuinely exercises alerting redirects storage_dir and stays green."""
    from volpred.publisher.email_notifier import EmailNotifier

    notifier = EmailNotifier(storage_dir=str(tmp_path / "storage"))
    notifier._write_notification_file({"id": "ok", "body": "x"})

    assert (tmp_path / "storage" / "notifications" / "ok.json").exists()
