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

import ast
import json
import os
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
from volpred.ops.shared_lock import sandboxed_lock_path, shared_state_lock

ROOT = Path(__file__).resolve().parents[1]

# Some sweep findings live in scripts/, which is not a package.
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


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
    assert canonical_writes_disabled(), f"{ENV_FLAG} must be set by root conftest.py"


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


# ---------------------------------------------------------------------------
# 2026-07-10 round 3: the lock sub-class. The two writers above raise; locks must
# NOT — the code under test needs a real fcntl lock, so a CanonicalWriteBlocked
# would just delete the coverage. `shared_lock.sandboxed_lock_path` relocates the
# lock file out of the checkout instead. Found by the full-suite mtime sweep, not
# by `git status` — every path here is .gitignore'd.


def test_no_module_shadows_shared_state_lock():
    """A second `shared_state_lock` cannot inherit the sandbox — it just looks like it did.

    scripts/mark_task_blocked.py carried one for months: same name, same semantics, its
    own hardcoded LOCK_DIR. Reading `with shared_state_lock("control_plane"):` at the
    call site gave no hint it was the wrong one.
    """
    canonical = ROOT / "src" / "volpred" / "ops" / "shared_lock.py"
    offenders = []
    for path in [*(ROOT / "scripts").rglob("*.py"), *(ROOT / "src").rglob("*.py")]:
        if path.resolve() == canonical.resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "shared_state_lock":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        "shared_state_lock is redefined outside its canonical module: "
        + ", ".join(offenders)
        + " — import it from volpred.ops.shared_lock instead"
    )


def test_shared_state_lock_never_touches_the_production_lock_dir():
    """`shared_state_lock` defaults to blocking=True, so an unredirected test waits on
    whatever cron writer holds `control_plane`.

    Probes a name no production writer uses. Asserting on control_plane.lock would go
    blind the moment a stray run leaves that file behind: shared_state_lock only
    touch()es a lock file it must create, so on an existing one there is nothing for a
    before/after check to see.
    """
    name = "__canonical_write_guard_probe__"
    canonical = ROOT / "storage" / "ops" / "locks" / f"{name}.lock"
    assert not canonical.exists(), f"probe name is not supposed to exist: {canonical}"

    with shared_state_lock(name) as acquired:
        assert acquired

    assert not canonical.exists(), f"test created a lock inside the checkout: {canonical}"
    assert sandboxed_lock_path(canonical).exists(), "the lock was not taken anywhere"


def test_sandboxed_lock_path_redirects_canonical_and_passes_tmp(tmp_path):
    canonical = ROOT / "storage" / "ops" / "locks" / "control_plane.lock"
    assert sandboxed_lock_path(canonical) != canonical
    assert not sandboxed_lock_path(canonical).is_relative_to(ROOT)

    outside = tmp_path / "ops" / "locks" / "control_plane.lock"
    assert sandboxed_lock_path(outside) == outside


def test_sandboxed_lock_names_do_not_collide_across_dirs():
    """storage/ops/locks/x.lock and storage/ops/x.lock must not map to one file."""
    a = sandboxed_lock_path(ROOT / "storage" / "ops" / "locks" / "x.lock")
    b = sandboxed_lock_path(ROOT / "storage" / "ops" / "x.lock")
    assert a != b


def test_drought_single_flight_lock_is_sandboxed():
    """A test holding the real lock makes the live remediation take its silent skip.

    Byte-compare rather than exists(): `_acquire_apply_lock` truncates and rewrites the
    file with its pid, so an existing lock file left by a stray run would make an
    exists() check pass while the write still landed.
    """
    import remediate_publish_drought as mod

    canonical = ROOT / "storage" / "ops" / "remediate_publish_drought.lock"
    before = canonical.read_bytes() if canonical.exists() else None

    handle = mod._acquire_apply_lock("storage")
    assert handle is not None
    try:
        sandbox = sandboxed_lock_path(canonical)
        assert sandbox != canonical
        assert json.loads(sandbox.read_text())["pid"] == os.getpid()
    finally:
        handle.close()

    after = canonical.read_bytes() if canonical.exists() else None
    assert after == before, f"test wrote the production single-flight lock {canonical}"
