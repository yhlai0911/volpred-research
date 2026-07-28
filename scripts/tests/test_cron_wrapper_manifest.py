"""Mechanical gate: a cron wrapper edited in `scripts/` must be re-synced to the copy launchd execs.

launchd runs `~/.volpred/bin/cron_<x>.sh`, never `scripts/cron_<x>.sh`. That path is
machine-local and does not exist in CI, so CI cannot diff against it directly. What
CI *can* see is `config/cron_wrapper_manifest.json`. A worktree renders it without
live effects, commits it with the wrapper, and only then may canonical main deploy
those committed bytes. The host-side drift check is the evidence that deployment
actually happened.

The host half of this gate lives in `scripts/check_alerts.py::_check_piggy_back_drift`,
which reports `wrapper_drift: <id>` by comparing the live copy against canonical.

Bug class: observability/execution decoupled from the artifact you edit. Sixth
occurrence on 2026-07-10; `.claude/rules/control-plane.md` requires a mechanical
gate from the second.
"""
from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_sync_module():
    script_path = PROJECT_ROOT / "scripts" / "sync_cron_wrappers.py"
    spec = importlib.util.spec_from_file_location("sync_cron_wrappers_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync():
    return _load_sync_module()


def _reviewed_wrapper_repo(sync, repo: Path, *, body: str) -> Path:
    (repo / "scripts").mkdir(parents=True)
    (repo / "config").mkdir()
    wrapper = repo / "scripts" / "cron_demo.sh"
    wrapper.write_text(body, encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    sync.render_manifest(repo)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=VolPred Test",
            "-c",
            "user.email=test@volpred.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    return wrapper


def _add_linked_worktree(repo: Path, linked: Path) -> None:
    subprocess.run(
        ["git", "worktree", "add", "-b", "candidate", str(linked)],
        cwd=repo,
        check=True,
    )


def test_manifest_matches_canonical_wrappers(sync):
    """Edit a wrapper without `--render-manifest` and CI fails."""
    problems = sync.check_manifest(PROJECT_ROOT)
    assert problems == [], (
        "cron wrapper manifest is out of date — the copy launchd execs in "
        "~/.volpred/bin will NOT have your edit.\n"
        "Fix: uv run python scripts/sync_cron_wrappers.py --render-manifest\n"
        + "\n".join(f"  - {p}" for p in problems)
    )


def test_manifest_covers_every_canonical_wrapper(sync):
    recorded = set(sync.load_manifest(PROJECT_ROOT))
    canonical = {p.name for p in sync.iter_canonical_wrappers(PROJECT_ROOT)}
    assert recorded == canonical


def test_every_config_declared_host_wrapper_has_a_canonical(sync):
    """A wrapper the scheduler execs but the repo cannot version is unfixable by definition.

    Four wrappers (audit_publish_sync, audit_fb_pipeline, ops_dashboard, boss_report)
    lived only in ~/.volpred/bin until 2026-07-10 — no canonical, so no way to edit
    them under review at all.
    """
    missing = [
        f"{basename} (job={job_id})"
        for basename, job_id in sorted(sync.declared_host_wrappers(PROJECT_ROOT).items())
        if not (PROJECT_ROOT / "scripts" / basename).exists()
    ]
    assert missing == [], f"host wrappers with no scripts/ canonical: {missing}"


def test_declared_host_wrappers_scans_every_config_section(sync):
    """Guards the subset-audit blind spot that hid the dispatch backbone.

    `system_crontab.items[].wrapper_script` is not the only place host wrappers are
    named: `cron_jobs[].tcc_bypass_copy` holds `cron_hourly_dispatch.sh`. A scan that
    reads only the first section reports "all clean" while the backbone drifts.
    """
    declared = sync.declared_host_wrappers(PROJECT_ROOT)
    assert "cron_hourly_dispatch.sh" in declared, (
        "cron_hourly_dispatch.sh is declared under cron_jobs[].tcc_bypass_copy, not "
        "system_crontab — the config walk must not be section-scoped"
    )
    assert "cron_check_alerts.sh" in declared  # system_crontab.items[].wrapper_script


def test_cron_lib_is_never_installed(sync):
    """cron_lib.sh is sourced from the repo checkout, so it must stay out of the manifest."""
    names = {p.name for p in sync.iter_canonical_wrappers(PROJECT_ROOT)}
    assert "cron_lib.sh" not in names
    assert (PROJECT_ROOT / "scripts" / "cron_lib.sh").exists()


def test_check_manifest_detects_a_tampered_wrapper(sync, tmp_path):
    """Negative control: the gate actually fires. A passing suite proves nothing otherwise."""
    root = tmp_path
    (root / "scripts").mkdir()
    (root / "config").mkdir()
    wrapper = root / "scripts" / "cron_demo.sh"
    wrapper.write_text("#!/bin/bash\necho v1\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    sync.write_manifest(sync.build_manifest_entries(root), root)
    assert sync.check_manifest(root) == []

    wrapper.write_text("#!/bin/bash\necho v2\n", encoding="utf-8")
    problems = sync.check_manifest(root)
    assert any(p.startswith("manifest_stale: cron_demo.sh") for p in problems), problems
    assert any("--render-manifest" in p for p in problems)


def test_detect_live_drift_is_quiet_without_an_install_dir(sync, tmp_path):
    """CI has no ~/.volpred/bin. A missing install dir is not drift."""
    assert sync.detect_live_drift(PROJECT_ROOT, tmp_path / "absent") == []


def test_detect_live_drift_flags_a_stale_live_copy(sync, tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "scripts" / "cron_demo.sh").write_text("#!/bin/bash\necho new\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    install = tmp_path / "bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho old\n", encoding="utf-8")
    live.chmod(0o755)

    findings = sync.detect_live_drift(root, install)
    assert [f["kind"] for f in findings] == ["wrapper_drift"]
    assert findings[0]["job_id"] == "cron_demo.sh"


def test_detect_live_drift_flags_an_uninstalled_wrapper(sync, tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "scripts" / "cron_demo.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    install = tmp_path / "bin"
    install.mkdir()

    findings = sync.detect_live_drift(root, install)
    assert [f["kind"] for f in findings] == ["wrapper_not_installed"]


def test_detect_live_drift_flags_an_obsolete_live_wrapper(sync, tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    canonical = root / "scripts" / "cron_demo.sh"
    canonical.write_text("#!/bin/bash\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    install = tmp_path / "bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_bytes(canonical.read_bytes())
    live.chmod(0o755)
    obsolete = install / "cron_deleted.sh"
    obsolete.write_text("#!/bin/bash\n", encoding="utf-8")
    obsolete.chmod(0o755)

    findings = sync.detect_live_drift(root, install)

    assert [finding["kind"] for finding in findings] == ["wrapper_obsolete_live"]
    assert findings[0]["job_id"] == "cron_deleted.sh"


def test_detect_live_drift_flags_exact_mode_drift(sync, tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    canonical = root / "scripts" / "cron_demo.sh"
    canonical.write_text("#!/bin/bash\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    install = tmp_path / "bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_bytes(canonical.read_bytes())
    live.chmod(0o700)

    findings = sync.detect_live_drift(root, install)

    assert [finding["kind"] for finding in findings] == ["wrapper_mode_drift"]
    assert findings[0]["detail"] == "live=0700 canonical=0755"


def test_detect_live_drift_rejects_a_symlink(sync, tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    canonical = root / "scripts" / "cron_demo.sh"
    canonical.write_text("#!/bin/bash\n", encoding="utf-8")
    (root / "config" / "runtime_schedules.json").write_text("{}", encoding="utf-8")

    install = tmp_path / "bin"
    install.mkdir()
    target = tmp_path / "target.sh"
    target.write_bytes(canonical.read_bytes())
    target.chmod(0o755)
    (install / "cron_demo.sh").symlink_to(target)

    findings = sync.detect_live_drift(root, install)

    assert [finding["kind"] for finding in findings] == ["wrapper_invalid_type"]
    assert "symlink" in findings[0]["detail"]


def test_install_atomic_does_not_truncate_a_running_scripts_inode(sync, tmp_path):
    """`cp` rewrites the inode a running bash is mid-read of; os.replace swaps the dirent.

    Holding an open fd to the old file stands in for a launchd job executing it: after
    install, the fd must still see the old bytes.
    """
    src = tmp_path / "new.sh"
    dst = tmp_path / "live.sh"
    src.write_text("#!/bin/bash\necho new\n", encoding="utf-8")
    dst.write_text("#!/bin/bash\necho old\n", encoding="utf-8")

    with dst.open("rb") as running:
        sync.install_atomic(src, dst)
        assert running.read() == b"#!/bin/bash\necho old\n"  # running process unaffected

    assert dst.read_text(encoding="utf-8") == "#!/bin/bash\necho new\n"
    assert dst.stat().st_mode & 0o111, "installed wrapper must be executable"
    assert not list(tmp_path.glob(".*tmp*")), "temp file must not be left behind"


def test_apply_rejects_linked_worktree_before_installing(sync, tmp_path):
    """A reviewed wrapper must reach canonical main before it can become live."""
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    install = tmp_path / "live-bin"
    _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho reviewed\n",
    )
    _add_linked_worktree(repo, linked)

    with pytest.raises(RuntimeError, match="canonical main checkout"):
        sync.apply_sync(linked, install)

    assert not install.exists()


def test_apply_from_canonical_main_installs_atomically(sync, tmp_path):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    wrapper = _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho reviewed\n",
    )

    result = sync.apply_sync(repo, install)

    assert result == {
        "installed": ["cron_demo.sh"],
        "unchanged": [],
        "retired": [],
    }
    assert (install / "cron_demo.sh").read_bytes() == wrapper.read_bytes()
    assert stat.S_IMODE((install / "cron_demo.sh").stat().st_mode) == 0o755
    assert sync.check_manifest(repo) == []


def test_apply_repairs_matching_but_non_executable_live_wrapper(sync, tmp_path):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    committed = "#!/bin/bash\necho reviewed\n"
    _reviewed_wrapper_repo(sync, repo, body=committed)
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text(committed, encoding="utf-8")
    live.chmod(0o700)

    result = sync.apply_sync(repo, install)

    assert result == {
        "installed": ["cron_demo.sh"],
        "unchanged": [],
        "retired": [],
    }
    assert stat.S_IMODE(live.stat().st_mode) == 0o755


def test_apply_quarantines_a_committed_wrapper_deletion_with_receipt(
    sync,
    tmp_path,
):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    committed = "#!/bin/bash\necho retired\n"
    wrapper = _reviewed_wrapper_repo(sync, repo, body=committed)
    sync.apply_sync(repo, install)
    subprocess.run(["git", "rm", str(wrapper.relative_to(repo))], cwd=repo, check=True)
    sync.render_manifest(repo)
    subprocess.run(
        ["git", "add", "config/cron_wrapper_manifest.json"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=VolPred Test",
            "-c",
            "user.email=test@volpred.invalid",
            "commit",
            "-m",
            "retire wrapper",
        ],
        cwd=repo,
        check=True,
    )

    result = sync.apply_sync(repo, install)

    assert result["retired"] == ["cron_demo.sh"]
    assert not (install / "cron_demo.sh").exists()
    quarantine = tmp_path / "retired-cron-wrappers"
    retired = list(quarantine.glob("cron_demo.sh.*.retired"))
    receipts = list(quarantine.glob("cron_demo.sh.*.receipt.json"))
    assert len(retired) == 1
    assert retired[0].read_text(encoding="utf-8") == committed
    assert len(receipts) == 1
    receipt = sync.json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["state"] == "retired"
    assert receipt["original_name"] == "cron_demo.sh"
    assert receipt["quarantine_path"] == str(retired[0])


def test_retirement_fsyncs_destination_before_persisting_source_removal(
    sync,
    tmp_path,
    monkeypatch,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho retired\n", encoding="utf-8")
    quarantine = tmp_path / "retired-cron-wrappers"
    events: list[tuple[str, str]] = []
    real_replace = sync.os.replace

    def record_receipt(path: Path, payload: dict) -> None:
        events.append(("receipt", payload["state"]))

    def record_replace(source: Path, destination: Path) -> None:
        events.append(("replace", source.name))
        real_replace(source, destination)

    def record_fsync(path: Path) -> None:
        events.append(("fsync", str(path)))

    monkeypatch.setattr(sync, "_atomic_write_retirement_receipt", record_receipt)
    monkeypatch.setattr(sync.os, "replace", record_replace)
    monkeypatch.setattr(sync, "_fsync_directory", record_fsync)

    retired = sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)

    assert retired == ["cron_demo.sh"]
    assert events == [
        ("fsync", str(quarantine)),
        ("fsync", str(tmp_path)),
        ("receipt", "prepared"),
        ("replace", "cron_demo.sh"),
        ("fsync", str(quarantine)),
        ("fsync", str(install)),
        ("receipt", "retired"),
    ]


def test_retirement_recovers_a_crash_after_prepared_receipt(
    sync,
    tmp_path,
    monkeypatch,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho retired\n", encoding="utf-8")
    live.chmod(0o755)
    real_replace = sync.os.replace
    fail_live_rename = True

    def crash_before_live_rename(source: Path, destination: Path) -> None:
        nonlocal fail_live_rename
        if Path(source) == live and fail_live_rename:
            fail_live_rename = False
            raise OSError("injected crash before retirement rename")
        real_replace(source, destination)

    monkeypatch.setattr(sync.os, "replace", crash_before_live_rename)

    with pytest.raises(OSError, match="injected crash"):
        sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)

    receipt_path = next(
        (tmp_path / "retired-cron-wrappers").glob("*.receipt.json")
    )
    assert sync.json.loads(receipt_path.read_text())["state"] == "prepared"
    assert live.exists()

    recovered = sync.recover_prepared_retirements(install)

    assert recovered == ["cron_demo.sh"]
    assert not live.exists()
    receipt = sync.json.loads(receipt_path.read_text())
    assert receipt["state"] == "retired"
    assert "recovered_at" in receipt


def test_retirement_recovers_a_crash_after_durable_rename(
    sync,
    tmp_path,
    monkeypatch,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho retired\n", encoding="utf-8")
    live.chmod(0o755)
    real_write = sync._atomic_write_retirement_receipt
    fail_retired_receipt = True

    def crash_before_final_receipt(path: Path, payload: dict) -> None:
        nonlocal fail_retired_receipt
        if payload["state"] == "retired" and fail_retired_receipt:
            fail_retired_receipt = False
            raise OSError("injected crash before retired receipt")
        real_write(path, payload)

    monkeypatch.setattr(
        sync,
        "_atomic_write_retirement_receipt",
        crash_before_final_receipt,
    )

    with pytest.raises(OSError, match="injected crash"):
        sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)

    quarantine = tmp_path / "retired-cron-wrappers"
    receipt_path = next(quarantine.glob("*.receipt.json"))
    assert sync.json.loads(receipt_path.read_text())["state"] == "prepared"
    assert not live.exists()
    assert len(list(quarantine.glob("*.retired"))) == 1

    recovered = sync.recover_prepared_retirements(install)

    assert recovered == ["cron_demo.sh"]
    assert sync.json.loads(receipt_path.read_text())["state"] == "retired"


def test_retirement_recovery_fails_closed_on_artifact_mismatch(
    sync,
    tmp_path,
    monkeypatch,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho retired\n", encoding="utf-8")
    live.chmod(0o755)
    real_replace = sync.os.replace

    def crash_before_live_rename(source: Path, destination: Path) -> None:
        if Path(source) == live:
            raise OSError("injected crash")
        real_replace(source, destination)

    monkeypatch.setattr(sync.os, "replace", crash_before_live_rename)
    with pytest.raises(OSError, match="injected crash"):
        sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)
    live.write_text("#!/bin/bash\necho tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="hash mismatch"):
        sync.recover_prepared_retirements(install)


def test_retirement_verifies_artifact_before_finalizing_receipt(
    sync,
    tmp_path,
    monkeypatch,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho original\n", encoding="utf-8")
    live.chmod(0o755)
    real_write = sync._atomic_write_retirement_receipt

    def mutate_after_prepared_receipt(path: Path, payload: dict) -> None:
        real_write(path, payload)
        if payload["state"] == "prepared":
            live.write_text("#!/bin/bash\necho replaced\n", encoding="utf-8")

    monkeypatch.setattr(
        sync,
        "_atomic_write_retirement_receipt",
        mutate_after_prepared_receipt,
    )

    with pytest.raises(RuntimeError, match="hash mismatch"):
        sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)

    quarantine = tmp_path / "retired-cron-wrappers"
    receipt_path = next(quarantine.glob("*.receipt.json"))
    assert sync.json.loads(receipt_path.read_text())["state"] == "prepared"


def test_retirement_detects_tampered_finalized_artifact(sync, tmp_path):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho original\n", encoding="utf-8")
    live.chmod(0o755)
    sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)
    quarantine = tmp_path / "retired-cron-wrappers"
    retired = next(quarantine.glob("*.retired"))
    retired.write_text("#!/bin/bash\necho tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="hash mismatch"):
        sync.recover_prepared_retirements(install)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "artifact is missing"),
        ("symlink", "not a regular file"),
        ("mode", "mode mismatch"),
    ],
)
def test_retirement_audits_finalized_artifact_contract(
    sync,
    tmp_path,
    mutation,
    error,
):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho original\n", encoding="utf-8")
    live.chmod(0o755)
    sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)
    quarantine = tmp_path / "retired-cron-wrappers"
    retired = next(quarantine.glob("*.retired"))
    if mutation == "missing":
        retired.unlink()
    elif mutation == "symlink":
        retired.unlink()
        retired.symlink_to(tmp_path / "outside")
    else:
        retired.chmod(0o700)

    with pytest.raises(RuntimeError, match=error):
        sync.recover_prepared_retirements(install)


def test_retirement_rejects_a_symlink_quarantine(sync, tmp_path):
    install = tmp_path / "live-bin"
    install.mkdir()
    live = install / "cron_demo.sh"
    live.write_text("#!/bin/bash\necho retired\n", encoding="utf-8")
    live.chmod(0o755)
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    (tmp_path / "retired-cron-wrappers").symlink_to(
        redirected,
        target_is_directory=True,
    )

    with pytest.raises(RuntimeError, match="not a regular directory"):
        sync.retire_obsolete_live_wrappers({}, install, head_oid="a" * 40)

    assert live.exists()
    assert list(redirected.iterdir()) == []


def test_apply_rejects_uncommitted_main_wrapper_before_installing(sync, tmp_path):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    wrapper = _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho committed\n",
    )
    wrapper.write_text("#!/bin/bash\necho unreviewed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="committed"):
        sync.apply_sync(repo, install)

    assert not install.exists()


def test_apply_installs_head_snapshot_when_worktree_changes_after_preflight(
    sync,
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    committed = "#!/bin/bash\necho committed\n"
    wrapper = _reviewed_wrapper_repo(sync, repo, body=committed)
    install_atomic = sync.install_atomic

    def mutate_then_install(src: Path, dst: Path) -> None:
        wrapper.write_text("#!/bin/bash\necho unreviewed\n", encoding="utf-8")
        install_atomic(src, dst)

    monkeypatch.setattr(sync, "install_atomic", mutate_then_install)

    sync.apply_sync(repo, install)

    assert (install / "cron_demo.sh").read_text(encoding="utf-8") == committed
    assert wrapper.read_text(encoding="utf-8") != committed


def test_apply_serializes_concurrent_deployers(sync, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho committed\n",
    )
    install_atomic = sync.install_atomic
    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    call_lock = threading.Lock()
    call_count = 0
    errors: list[BaseException] = []

    def blocking_install(src: Path, dst: Path) -> None:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_entered.set()
            assert release_first.wait(timeout=3)
        else:
            second_entered.set()
        install_atomic(src, dst)

    def deploy() -> None:
        try:
            sync.apply_sync(repo, install)
        except BaseException as exc:  # noqa: BLE001 - thread failures are asserted below
            errors.append(exc)

    monkeypatch.setattr(sync, "install_atomic", blocking_install)
    first = threading.Thread(target=deploy)
    second = threading.Thread(target=deploy)
    first.start()
    assert first_entered.wait(timeout=3)
    second.start()
    try:
        assert not second_entered.wait(timeout=0.2)
    finally:
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert call_count == 1


def test_apply_fails_when_post_install_readback_is_tampered(
    sync,
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho committed\n",
    )
    install_atomic = sync.install_atomic

    def install_then_tamper(src: Path, dst: Path) -> None:
        install_atomic(src, dst)
        dst.write_text("#!/bin/bash\necho tampered\n", encoding="utf-8")

    monkeypatch.setattr(sync, "install_atomic", install_then_tamper)

    with pytest.raises(RuntimeError, match="read-back mismatch"):
        sync.apply_sync(repo, install)


def test_apply_rejects_deleted_committed_wrapper_without_live_or_manifest_write(
    sync,
    tmp_path,
):
    repo = tmp_path / "repo"
    install = tmp_path / "live-bin"
    wrapper = _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho committed\n",
    )
    manifest = repo / "config" / "cron_wrapper_manifest.json"
    manifest_before = manifest.read_bytes()
    wrapper.unlink()

    with pytest.raises(RuntimeError, match="complete wrapper population"):
        sync.apply_sync(repo, install)

    assert not install.exists()
    assert manifest.read_bytes() == manifest_before


def test_render_manifest_is_safe_in_a_linked_worktree(sync, tmp_path):
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    _reviewed_wrapper_repo(
        sync,
        repo,
        body="#!/bin/bash\necho base\n",
    )
    _add_linked_worktree(repo, linked)
    (linked / "scripts" / "cron_demo.sh").write_text(
        "#!/bin/bash\necho candidate\n",
        encoding="utf-8",
    )

    rendered = sync.render_manifest(linked)

    assert rendered == linked / "config" / "cron_wrapper_manifest.json"
    assert sync.check_manifest(linked) == []
