"""Mechanical gate: a cron wrapper edited in `scripts/` must be re-synced to the copy launchd execs.

launchd runs `~/.volpred/bin/cron_<x>.sh`, never `scripts/cron_<x>.sh`. That path is
machine-local and does not exist in CI, so CI cannot diff against it directly. What
CI *can* see is `config/cron_wrapper_manifest.json`, whose hashes only match when
someone ran `scripts/sync_cron_wrappers.py --apply` — and that command installs the
wrappers as its first act. A green manifest is therefore evidence the sync happened.

The host half of this gate lives in `scripts/check_alerts.py::_check_piggy_back_drift`,
which reports `wrapper_drift: <id>` by comparing the live copy against canonical.

Bug class: observability/execution decoupled from the artifact you edit. Sixth
occurrence on 2026-07-10; `.claude/rules/control-plane.md` requires a mechanical
gate from the second.
"""
from __future__ import annotations

import importlib.util
import sys
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


def test_manifest_matches_canonical_wrappers(sync):
    """The gate. Edit any scripts/cron_*.sh without `--apply` and this fails."""
    problems = sync.check_manifest(PROJECT_ROOT)
    assert problems == [], (
        "cron wrapper manifest is out of date — the copy launchd execs in "
        "~/.volpred/bin will NOT have your edit.\n"
        "Fix: uv run python scripts/sync_cron_wrappers.py --apply\n"
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
    (install / "cron_demo.sh").write_text("#!/bin/bash\necho old\n", encoding="utf-8")

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
