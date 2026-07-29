from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import release_image

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "dispatch_supervisor_bootstrap.py"
STAGE0 = ROOT / "scripts" / "dispatch_supervisor_stage0.py"
CLAIM_RELEASE = ROOT / "scripts" / "dispatch_supervisor" / "claim_release.py"
IDENTITY = ROOT / "scripts" / "dispatch_supervisor" / "identity.py"


def test_private_directory_converges_owner_owned_readonly_bits(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "release"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)

    release_image._ensure_private_directory(directory)

    assert directory.stat().st_mode & 0o777 == 0o700


def test_private_directory_rejects_group_writable_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "release"
    directory.mkdir(mode=0o775)
    directory.chmod(0o775)

    with pytest.raises(release_image.ReleaseImageError, match="not private"):
        release_image._ensure_private_directory(directory)


def _release(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    run_root = tmp_path / "run"
    releases = run_root / "releases"
    run_root.mkdir(mode=0o700)
    releases.mkdir(mode=0o700)
    canonical = tmp_path / "canonical"
    (canonical / "scripts" / "dispatch_supervisor").mkdir(parents=True)
    (canonical / "scripts" / "dispatch_supervisor" / "pinned_probe.py").write_text(
        "VALUE = 999\n",
        encoding="utf-8",
    )
    mutable_escape = canonical / "scripts" / "mutable_escape.py"
    mutable_escape.write_text("VALUE = 999\n", encoding="utf-8")
    output = tmp_path / "loaded.json"
    provisional = releases / "provisional.zip"
    module = (
        "import importlib.util, json, os, sys\n"
        "from pathlib import Path\n"
        "from volpred.ops import RELEASE_VALUE\n"
        "sys.path.insert(0, str(Path.cwd()))\n"
        "from scripts.dispatch_supervisor import pinned_probe\n"
        "from scripts.dispatch_supervisor import claim_release\n"
        "task_pool = claim_release._task_pool_claim()\n"
        "denied = False\n"
        "try:\n"
        "  spec = importlib.util.spec_from_file_location(\n"
        "      'mutable_escape', os.environ['BOOTSTRAP_TEST_MUTABLE_PY'])\n"
        "  escape = importlib.util.module_from_spec(spec)\n"
        "  spec.loader.exec_module(escape)\n"
        "except RuntimeError as exc:\n"
        "  denied = 'refusing mutable Python execution' in str(exc)\n"
        "Path(os.environ['BOOTSTRAP_TEST_OUTPUT']).write_text(json.dumps({\n"
        "  'module_file': __file__,\n"
        "  'release_id': os.environ['VOLPRED_SUPERVISOR_RELEASE_ID'],\n"
        "  'release_sha': os.environ['VOLPRED_SUPERVISOR_RELEASE_SHA256'],\n"
        "  'release_commit': os.environ['VOLPRED_SUPERVISOR_RELEASE_COMMIT'],\n"
        "  'release_value': RELEASE_VALUE,\n"
        "  'pinned_probe': pinned_probe.VALUE,\n"
        "  'task_pool_value': task_pool.PINNED_TASK_POOL_VALUE,\n"
        "  'task_pool_file': task_pool.__file__,\n"
        "  'mutable_python_denied': denied,\n"
        "  'loader': type(__loader__).__name__,\n"
        "}), encoding='utf-8')\n"
    )
    entries = {
        "scripts/__init__.py": "",
        "scripts/dispatch_supervisor/__init__.py": "",
        "scripts/dispatch_supervisor/supervisor.py": module,
        "scripts/dispatch_supervisor/pinned_probe.py": "VALUE = 7\n",
        "scripts/dispatch_supervisor/claim_release.py": (
            CLAIM_RELEASE.read_text(encoding="utf-8")
        ),
        "scripts/dispatch_supervisor/identity.py": IDENTITY.read_text(
            encoding="utf-8"
        ),
        "scripts/task_pool_claim.py": "PINNED_TASK_POOL_VALUE = 73\n",
        "src/volpred/__init__.py": "",
        "src/volpred/ops/__init__.py": "RELEASE_VALUE = 42\n",
        "src/volpred/ops/termination.py": (
            ROOT / "src" / "volpred" / "ops" / "termination.py"
        ).read_text(encoding="utf-8"),
    }
    commit = "b" * 40
    with zipfile.ZipFile(provisional, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        archive.writestr(
            "VOLPRED_RELEASE.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "release_commit": commit,
                    "entries": sorted(entries),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    release_sha = hashlib.sha256(provisional.read_bytes()).hexdigest()
    archive_path = releases / f"{release_sha}.zip"
    provisional.rename(archive_path)
    archive_path.chmod(0o400)
    request_id = "a" * 64
    bootstrap_bytes = BOOTSTRAP.read_bytes()
    bootstrap_sha = hashlib.sha256(bootstrap_bytes).hexdigest()
    bootstraps = run_root / "bootstraps"
    bootstraps.mkdir(mode=0o700)
    bootstrap = bootstraps / f"{bootstrap_sha}.py"
    bootstrap.write_bytes(bootstrap_bytes)
    bootstrap.chmod(0o400)
    stage0 = run_root / "dispatch-supervisor-stage0.py"
    stage0.write_bytes(STAGE0.read_bytes())
    stage0.chmod(0o500)
    pointer = {
        "schema_version": 2,
        "activation_state": "stable",
        "request_id": request_id,
        "release_archive": str(archive_path),
        "release_sha256": release_sha,
        "release_commit": commit,
        "bootstrap_path": str(bootstrap),
        "bootstrap_sha256": bootstrap_sha,
        "stage0_path": str(stage0),
        "stage0_sha256": hashlib.sha256(stage0.read_bytes()).hexdigest(),
    }
    pointer_path = run_root / "current_release.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    pointer_path.chmod(0o600)
    return run_root, output, pointer


def test_bootstrap_imports_supervisor_only_from_pinned_release(tmp_path: Path) -> None:
    run_root, output, pointer = _release(tmp_path)

    result = subprocess.run(
        [sys.executable, pointer["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
            "BOOTSTRAP_TEST_OUTPUT": str(output),
            "BOOTSTRAP_TEST_MUTABLE_PY": str(
                tmp_path / "canonical" / "scripts" / "mutable_escape.py"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["release_id"] == pointer["request_id"]
    assert loaded["release_sha"] == pointer["release_sha256"]
    assert loaded["release_commit"] == pointer["release_commit"]
    assert loaded["release_value"] == 42
    assert loaded["module_file"] == str(
        tmp_path / "canonical" / "scripts" / "dispatch_supervisor" / "supervisor.py"
    )
    assert loaded["loader"] == "_PinnedReleaseLoader"
    assert loaded["pinned_probe"] == 7
    assert loaded["task_pool_value"] == 73
    assert loaded["task_pool_file"] == str(
        tmp_path / "canonical" / "scripts" / "task_pool_claim.py"
    )
    assert loaded["mutable_python_denied"] is True


def test_bootstrap_fails_closed_on_release_digest_drift(tmp_path: Path) -> None:
    run_root, output, pointer = _release(tmp_path)
    archive = Path(pointer["release_archive"])
    archive.chmod(0o600)
    archive.write_bytes(archive.read_bytes() + b"drift")
    archive.chmod(0o400)

    result = subprocess.run(
        [sys.executable, pointer["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
            "BOOTSTRAP_TEST_OUTPUT": str(output),
            "BOOTSTRAP_TEST_MUTABLE_PY": str(
                tmp_path / "canonical" / "scripts" / "mutable_escape.py"
            ),
        },
    )

    assert result.returncode != 0
    assert "release digest mismatch" in result.stderr
    assert not output.exists()


def test_bootstrap_fails_closed_when_manifest_commit_does_not_match_pointer(
    tmp_path: Path,
) -> None:
    run_root, output, pointer = _release(tmp_path)
    pointer["release_commit"] = "c" * 40
    pointer_path = run_root / "current_release.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    pointer_path.chmod(0o600)

    result = subprocess.run(
        [sys.executable, pointer["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
            "BOOTSTRAP_TEST_OUTPUT": str(output),
            "BOOTSTRAP_TEST_MUTABLE_PY": str(
                tmp_path / "canonical" / "scripts" / "mutable_escape.py"
            ),
        },
    )

    assert result.returncode != 0
    assert "manifest commit mismatch" in result.stderr
    assert not output.exists()


def test_stage0_rolls_back_broken_candidate_to_last_known_good(
    tmp_path: Path,
) -> None:
    run_root, output, previous = _release(tmp_path)
    releases = run_root / "releases"
    provisional = releases / "broken.zip"
    entries = {
        "scripts/__init__.py": "",
        "scripts/dispatch_supervisor/__init__.py": "",
        "scripts/dispatch_supervisor/supervisor.py": (
            "raise RuntimeError('broken candidate boot')\n"
        ),
    }
    commit = "c" * 40
    with zipfile.ZipFile(provisional, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        archive.writestr(
            "VOLPRED_RELEASE.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "release_commit": commit,
                    "entries": sorted(entries),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    release_sha = hashlib.sha256(provisional.read_bytes()).hexdigest()
    candidate_archive = releases / f"{release_sha}.zip"
    provisional.rename(candidate_archive)
    candidate_archive.chmod(0o400)
    request_id = "d" * 64
    candidate = {
        **{
            key: value
            for key, value in previous.items()
            if key
            in {
                "bootstrap_path",
                "bootstrap_sha256",
                "stage0_path",
                "stage0_sha256",
            }
        },
        "schema_version": 2,
        "activation_state": "candidate",
        "max_boot_attempts": 2,
        "startup_timeout_s": 2.0,
        "request_id": request_id,
        "release_archive": str(candidate_archive),
        "release_sha256": release_sha,
        "release_commit": commit,
        "previous_release": previous,
    }
    pointer_path = run_root / "current_release.json"
    pointer_path.write_text(json.dumps(candidate), encoding="utf-8")
    pointer_path.chmod(0o600)
    env = {
        **os.environ,
        "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
        "BOOTSTRAP_TEST_OUTPUT": str(output),
        "BOOTSTRAP_TEST_MUTABLE_PY": str(
            tmp_path / "canonical" / "scripts" / "mutable_escape.py"
        ),
    }

    first = subprocess.run(
        [sys.executable, candidate["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    second = subprocess.run(
        [sys.executable, candidate["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    recovered = subprocess.run(
        [sys.executable, candidate["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert first.returncode != 0
    assert second.returncode != 0
    assert recovered.returncode == 0, recovered.stderr
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["activation_state"] == "stable"
    assert pointer["release_sha256"] == previous["release_sha256"]
    receipt = json.loads(
        (
            run_root / "rollback_receipts" / f"{request_id}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "rolled_back_failed_boot"
    assert receipt["boot_attempts"] == 2
    assert output.exists()


def test_stage0_times_out_hung_candidate_and_boots_last_known_good(
    tmp_path: Path,
) -> None:
    run_root, output, previous = _release(tmp_path)
    releases = run_root / "releases"
    provisional = releases / "hung.zip"
    entries = {
        "scripts/__init__.py": "",
        "scripts/dispatch_supervisor/__init__.py": "",
        "scripts/dispatch_supervisor/supervisor.py": (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(30)\n"
        ),
    }
    commit = "1" * 40
    with zipfile.ZipFile(provisional, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        archive.writestr(
            "VOLPRED_RELEASE.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "release_commit": commit,
                    "entries": sorted(entries),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    release_sha = hashlib.sha256(provisional.read_bytes()).hexdigest()
    candidate_archive = releases / f"{release_sha}.zip"
    provisional.rename(candidate_archive)
    candidate_archive.chmod(0o400)
    request_id = "2" * 64
    candidate = {
        **{
            key: value
            for key, value in previous.items()
            if key
            in {
                "bootstrap_path",
                "bootstrap_sha256",
                "stage0_path",
                "stage0_sha256",
            }
        },
        "schema_version": 2,
        "activation_state": "candidate",
        "max_boot_attempts": 2,
        "startup_timeout_s": 0.2,
        "request_id": request_id,
        "release_archive": str(candidate_archive),
        "release_sha256": release_sha,
        "release_commit": commit,
        "previous_release": previous,
    }
    pointer_path = run_root / "current_release.json"
    pointer_path.write_text(json.dumps(candidate), encoding="utf-8")
    pointer_path.chmod(0o600)

    result = subprocess.run(
        [sys.executable, candidate["stage0_path"]],
        cwd=tmp_path / "canonical",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={
            **os.environ,
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
            "BOOTSTRAP_TEST_OUTPUT": str(output),
            "BOOTSTRAP_TEST_MUTABLE_PY": str(
                tmp_path / "canonical" / "scripts" / "mutable_escape.py"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert pointer["activation_state"] == "stable"
    assert pointer["release_sha256"] == previous["release_sha256"]
    receipt = json.loads(
        (
            run_root / "rollback_receipts" / f"{request_id}.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["state"] == "rolled_back_failed_boot"
    assert receipt["reason"] == "startup_timeout"
    termination_events = [
        json.loads(line)
        for line in (
            run_root / "termination_intents.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in termination_events] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
        "signal_attempted",
        "signal_result",
    ]
    assert termination_events[0]["reason"] == "candidate_startup_timeout"
    assert termination_events[0]["actor"] == "dispatch-supervisor-stage0"
    assert termination_events[0]["signal_sequence"] == [
        signal.SIGTERM,
        signal.SIGKILL,
    ]
    assert termination_events[1]["signum"] == signal.SIGTERM
    assert termination_events[2]["status"] in {"sent", "gone"}
    assert termination_events[3]["signum"] == signal.SIGKILL
    assert termination_events[4]["status"] in {"sent", "gone"}
    exact_generation = {
        key: termination_events[0][key]
        for key in (
            "intent_id",
            "target_kind",
            "target_id",
            "target_identity",
        )
    }
    assert exact_generation["target_kind"] == "pid"
    assert all(
        {
            key: event[key]
            for key in exact_generation
        } == exact_generation
        for event in termination_events[1:]
    )
    assert output.exists()


def test_full_release_imports_real_health_and_task_pool_under_uv_venv(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    releases = run_root / "releases"
    bootstraps = run_root / "bootstraps"
    for directory in (run_root, releases, bootstraps):
        directory.mkdir(mode=0o700)
    entries: dict[str, bytes] = {"scripts/__init__.py": b""}
    for source_root in (ROOT / "scripts", ROOT / "src" / "volpred"):
        for path in source_root.rglob("*.py"):
            entries[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    payload = release_image._deterministic_zip(
        entries,
        commit="test-fixture",
    )
    release_sha = hashlib.sha256(payload).hexdigest()
    archive = releases / f"{release_sha}.zip"
    archive.write_bytes(payload)
    archive.chmod(0o400)
    bootstrap_payload = BOOTSTRAP.read_bytes()
    bootstrap_sha = hashlib.sha256(bootstrap_payload).hexdigest()
    bootstrap = bootstraps / f"{bootstrap_sha}.py"
    bootstrap.write_bytes(bootstrap_payload)
    bootstrap.chmod(0o400)
    pointer = {
        "schema_version": 2,
        "activation_state": "stable",
        "request_id": "e" * 64,
        "release_archive": str(archive),
        "release_sha256": release_sha,
        "release_commit": "test-fixture",
        "bootstrap_path": str(bootstrap),
        "bootstrap_sha256": bootstrap_sha,
    }
    pointer_path = run_root / "current_release.json"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    pointer_path.chmod(0o600)
    probe = (
        "import importlib.util, json, sys\n"
        f"spec=importlib.util.spec_from_file_location('release_bootstrap', {str(bootstrap)!r})\n"
        "boot=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(boot)\n"
        "release=boot._load_pointer()\n"
        "boot._activate_import_path(release)\n"
        "from scripts.dispatch_supervisor import claim_release, health\n"
        "from volpred.ops import git_writer_lock\n"
        "task_pool=claim_release._task_pool_claim()\n"
        "termination=git_writer_lock._termination_owner()\n"
        "print(json.dumps({\n"
        "  'health_loader': type(health.__loader__).__name__,\n"
        "  'task_pool_loader': type(task_pool.__loader__).__name__,\n"
        "  'termination_loader': type(termination.__loader__).__name__,\n"
        "  'venv': sys.prefix,\n"
        "}))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "VOLPRED_DEFERRED_RELOAD_ROOT": str(run_root),
        },
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["health_loader"] == "_PinnedReleaseLoader"
    assert observed["task_pool_loader"] == "_PinnedReleaseLoader"
    assert observed["termination_loader"] == "_PinnedReleaseLoader"
    assert ".venv" in observed["venv"]


def test_release_image_pins_committed_bytes_and_rejects_dirty_rebuild(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts" / "dispatch_supervisor").mkdir(parents=True)
    (repo / "src" / "volpred" / "ops").mkdir(parents=True)
    (repo / "scripts" / "dispatch_supervisor" / "worker.py").write_text(
        "VERSION = 1\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "dispatch_supervisor_bootstrap.py").write_text(
        "# stable bootstrap\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "dispatch_supervisor_stage0.py").write_text(
        "# stable stage zero\n",
        encoding="utf-8",
    )
    (repo / "src" / "volpred" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "volpred" / "ops" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True)
    run_root = tmp_path / "run"

    release = release_image.materialize(repo_root=repo, run_root=run_root)
    source = repo / "scripts" / "dispatch_supervisor" / "worker.py"
    source.write_text("VERSION = 2\n", encoding="utf-8")

    with zipfile.ZipFile(release["release_archive"]) as archive:
        assert (
            archive.read("scripts/dispatch_supervisor/worker.py")
            == b"VERSION = 1\n"
        )
    with pytest.raises(
        release_image.ReleaseImageError,
        match="monitored source is uncommitted",
    ):
        release_image.materialize(repo_root=repo, run_root=run_root)
