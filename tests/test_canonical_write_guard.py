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
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from volpred.canonical_write import (
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


def test_guard_sentinel_pierces_broad_exception_handler():
    """Best-effort production fallbacks must not turn a blocked write green."""

    def application_fail_open_boundary() -> str:
        try:
            guard_canonical_write(ROOT / "storage" / "next_tasks.json")
        except Exception:  # noqa: BLE001 - models the production fail-open sites
            return "swallowed"
        return "unreachable"

    assert issubclass(CanonicalWriteBlocked, BaseException)
    assert not issubclass(CanonicalWriteBlocked, Exception)
    with pytest.raises(CanonicalWriteBlocked):
        application_fail_open_boundary()


@pytest.mark.parametrize(
    ("module_name", "argv", "call_style"),
    [
        ("scripts.backfill_null_task_ids", ["backfill_null_task_ids.py", "--dry-run"], "argv"),
        ("scripts.backfill_task_types", ["backfill_task_types.py", "--dry-run"], "argv"),
        ("scripts.dedupe_next_tasks", ["dedupe_next_tasks.py"], "argv"),
        ("scripts.unblock_expired_blocked_tasks", [], "apply_false"),
    ],
)
def test_queue_maintenance_dry_run_does_not_trip_write_guard(
    module_name, argv, call_style, monkeypatch, tmp_path
):
    """Audit modes may read/lock the queue but must guard only before mutation."""
    import volpred.canonical_write as canonical_write

    fake_root = tmp_path / "checkout"
    queue = fake_root / "storage" / "next_tasks.json"
    queue.parent.mkdir(parents=True)
    queue.write_text("[]\n", encoding="utf-8")
    before = queue.read_bytes()

    monkeypatch.setattr(canonical_write, "_repo_root", lambda: fake_root)
    module = importlib.import_module(module_name)
    if hasattr(module, "NEXT_TASKS"):
        monkeypatch.setattr(module, "NEXT_TASKS", queue)
    if hasattr(module, "PATH"):
        monkeypatch.setattr(module, "PATH", queue)
    if hasattr(module, "ARCHIVE_DIR"):
        monkeypatch.setattr(module, "ARCHIVE_DIR", fake_root / "storage" / "next_tasks_archive")

    if call_style == "argv":
        monkeypatch.setattr(sys, "argv", argv)
        result = module.main()
    else:
        result = module.main(apply=False)

    assert result == 0
    assert queue.read_bytes() == before


def test_unblock_archive_writer_is_guarded(monkeypatch, tmp_path):
    import volpred.canonical_write as canonical_write
    from scripts import unblock_expired_blocked_tasks as module

    fake_root = tmp_path / "checkout"
    archive_dir = fake_root / "storage" / "next_tasks_archive"
    monkeypatch.setattr(canonical_write, "_repo_root", lambda: fake_root)
    monkeypatch.setattr(module, "ARCHIVE_DIR", archive_dir)

    with pytest.raises(CanonicalWriteBlocked):
        module._persist_archive([{"id": "guard_probe"}])
    assert not archive_dir.exists()


def test_base64_apply_blocks_before_remote_upload(monkeypatch, tmp_path):
    import volpred.canonical_write as canonical_write
    from scripts import extract_base64_images
    from volpred.publisher import publisher

    fake_root = tmp_path / "checkout"
    feed = fake_root / "storage" / "reports" / "feed.json"
    feed.parent.mkdir(parents=True)
    feed.write_text(
        json.dumps(
            [
                {
                    "id": "guard_probe",
                    "content": "![probe](data:image/png;base64,AAAA)",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(canonical_write, "_repo_root", lambda: fake_root)

    uploaded = False

    def unexpected_upload(*args, **kwargs):
        nonlocal uploaded
        uploaded = True
        return args[0]

    monkeypatch.setattr(publisher, "_extract_base64_images", unexpected_upload)
    monkeypatch.setattr(
        sys,
        "argv",
        ["extract_base64_images.py", "--apply", "--no-sync", "--feed", str(feed)],
    )

    with pytest.raises(CanonicalWriteBlocked):
        extract_base64_images.main()
    assert not uploaded


def test_guard_owner_import_does_not_initialize_ops_package():
    """The guard is a dependency leaf; importing it must not execute volpred.ops."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import volpred.canonical_write; "
            "assert 'volpred.ops' not in sys.modules",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_common_dump_json_refuses_canonical_path():
    from volpred.ops.common import dump_json

    with pytest.raises(CanonicalWriteBlocked):
        dump_json(ROOT / "storage" / "ops" / "guard_probe.json", {})


def test_next_tasks_low_level_writer_refuses_canonical_path():
    from volpred.ops.next_tasks import write_tasks_locked

    with pytest.raises(CanonicalWriteBlocked):
        write_tasks_locked(ROOT / "storage" / "next_tasks.json", [])


def test_memory_index_writer_refuses_canonical_path():
    from volpred.memory.system import MemorySystem

    # Bypass __init__: this probe targets the append primitive, independent of
    # which storage subdirectories happen to exist in a clean checkout.
    memory = object.__new__(MemorySystem)
    memory.storage_dir = ROOT / "storage"
    memory.memory_dir = ROOT / "storage" / "memory"
    memory.results_dir = ROOT / "storage" / "results"
    with pytest.raises(CanonicalWriteBlocked):
        memory._append_to_index("experiments.json", {"experiment_id": "guard_probe"})


def test_publisher_unpublish_and_rewrite_refuse_canonical_feed(monkeypatch):
    from volpred.publisher.publisher import Publisher

    publisher = object.__new__(Publisher)
    publisher.reports_dir = ROOT / "storage" / "reports"
    publisher._feed_file = publisher.reports_dir / "feed.json"
    monkeypatch.setattr(publisher, "_load_feed", lambda: [{"id": "guard_probe"}])

    with pytest.raises(CanonicalWriteBlocked):
        publisher._append_to_feed({"id": "guard_probe"})
    with pytest.raises(CanonicalWriteBlocked):
        publisher.unpublish("guard_probe")
    with pytest.raises(CanonicalWriteBlocked):
        publisher._rewrite_feed_entry("guard_probe", {"id": "guard_probe"})


def test_work_log_append_refuses_canonical_path():
    from append_work_log import append_entry

    with pytest.raises(CanonicalWriteBlocked):
        append_entry(
            {"task_id": "guard_probe"},
            path=ROOT / "storage" / "work_log.json",
            lock_path=ROOT / "storage" / ".work_log.lock",
        )


def test_control_plane_atomic_writer_refuses_canonical_path():
    from volpred.ops.local_control_plane import _atomic_write_json

    with pytest.raises(CanonicalWriteBlocked):
        _atomic_write_json(ROOT / "storage" / "ops" / "tasks" / "guard_probe.json", {})


def test_event_ledger_write_and_delete_refuse_canonical_paths(monkeypatch):
    from volpred.ops import event_jobs

    ledger = ROOT / "storage" / "ops" / "event_ledger" / "guard_probe.json"
    with pytest.raises(CanonicalWriteBlocked):
        event_jobs._write_json(ledger, {})

    # Exercise the GC deletion boundary without creating a real ledger entry.
    monkeypatch.setattr(event_jobs, "_event_ledger_root", lambda storage_dir="storage": ledger.parent)
    monkeypatch.setattr(event_jobs, "_read_json", lambda path: {"gc_after": "2000-01-01T00:00:00+00:00"})
    monkeypatch.setattr(Path, "glob", lambda self, pattern: [ledger])
    with pytest.raises(CanonicalWriteBlocked):
        event_jobs.gc_event_ledger()


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


def test_builder_atomic_primitive_refuses_canonical_output():
    """The primitive itself is guarded; a caller cannot bypass main()'s check."""
    import build_publication_candidates

    with pytest.raises(CanonicalWriteBlocked):
        build_publication_candidates._write_output_atomically({"guard_probe": True})


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

    # Bypass construction so this method-level probe is hermetic in both the
    # live checkout (where storage/notifications may already exist) and a clean
    # clone (where __init__ correctly blocks creating it). Constructor behavior
    # is covered independently below.
    notifier = object.__new__(EmailNotifier)
    notifier.notifications_dir = ROOT / "storage" / "notifications"

    with pytest.raises(CanonicalWriteBlocked):
        notifier._write_notification_file({"id": "guard_probe", "body": "x"})

    with pytest.raises(CanonicalWriteBlocked):
        notifier._save_log([])

    assert not (ROOT / "storage" / "notifications" / "guard_probe.json").exists()


def test_notification_constructor_guards_only_missing_directory(monkeypatch, tmp_path):
    """Construction stays read-only when the directory exists and blocks its creation."""
    import volpred.canonical_write as canonical_write
    from volpred.publisher.email_notifier import EmailNotifier

    fake_root = tmp_path / "checkout"
    storage = fake_root / "storage"
    storage.mkdir(parents=True)
    monkeypatch.setattr(canonical_write, "_repo_root", lambda: fake_root)

    with pytest.raises(CanonicalWriteBlocked):
        EmailNotifier(storage_dir=str(storage))
    assert not (storage / "notifications").exists()

    (storage / "notifications").mkdir()
    notifier = EmailNotifier(storage_dir=str(storage))
    assert notifier.notifications_dir == storage / "notifications"


def test_immediate_dispatch_slots_full_is_read_only(monkeypatch, tmp_path):
    """A capacity check that returns early must not guard the untouched marker."""
    import volpred.canonical_write as canonical_write
    from scripts import gmail_inbox_poll
    from scripts.dispatch_supervisor import scheduler, state

    fake_root = tmp_path / "checkout"
    marker = fake_root / "storage" / "ops" / ".last_email_immediate_dispatch"
    monkeypatch.setattr(canonical_write, "_repo_root", lambda: fake_root)
    monkeypatch.setattr(gmail_inbox_poll, "_TRIGGER_MARKER", marker)
    monkeypatch.setattr(state, "read_state", lambda: {"current_jobs": [{"job_id": "busy"}]})
    monkeypatch.setattr(scheduler, "load_max_slots", lambda: 1)

    result = gmail_inbox_poll._trigger_immediate_dispatch([{"task_id": "email-1"}])

    assert result["reason"] == "dispatch_slots_full"
    assert not marker.exists()


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
