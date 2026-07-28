#!/usr/bin/env python3
"""Keep `scripts/cron_*.sh` (canonical) and `~/.volpred/bin/` (what launchd execs) in lockstep.

The trap this closes
--------------------
launchd execs `~/.volpred/bin/cron_<x>.sh`; it never reads `scripts/cron_<x>.sh`.
Every wrapper's own header tells you to `cp` it across after editing, and for
months nobody did: on 2026-07-10 eleven of forty wrappers had drifted, including
`cron_hourly_dispatch.sh` (the dispatch backbone) and `cron_market_cal.sh`, whose
live copy was three months behind and did not even source `cron_lib.sh`. Editing
the canonical copy looked like it worked and changed nothing. Same bug class as
the cron freshness marker: the artifact you edit is decoupled from the thing that
executes.

`config/cron_wrapper_manifest.json` is the fix. It is a committed hash of every
canonical wrapper, which makes the coupling checkable from two places that see
different halves of the world:

- CI (`scripts/tests/test_cron_wrapper_manifest.py`) sees the repo but not
  `~/.volpred/bin`. It compares canonical against the manifest, so editing a
  wrapper without running `--render-manifest` fails the build.
- The host (`scripts/check_alerts.py::_check_piggy_back_drift`) sees both. It
  compares the live copy against canonical and reports `wrapper_drift: <id>`.

Population = every `scripts/cron_*.sh` except `cron_lib.sh`. That is deliberately
a superset of what `config/runtime_schedules.json` declares: the config splits
host wrappers across `system_crontab.items[].wrapper_script` AND
`cron_jobs[].tcc_bypass_copy` / `.script` / `.command`, and a subset audit that
reads only the first section misses the backbone (that is exactly how
`cron_hourly_dispatch.sh` stayed invisible). The glob cannot miss a section.

Render and deploy are deliberately separate
-------------------------------------------
Generating a reviewable manifest is repository authoring and is safe from any
checkout. Installing a wrapper is a production effect and is allowed only after
the wrapper and manifest bytes are committed on canonical `main`:

1. edit in a worktree and run `--render-manifest`;
2. commit and merge the wrapper plus manifest;
3. from canonical `main`, run `--apply`.

This ordering prevents a live wrapper from referring to code that has not reached
the production checkout yet.

Live install is an atomic rename, never `cp`
--------------------------------------------
bash reads a script incrementally by byte offset while executing it. `cp` truncates
and rewrites the *same inode*, so overwriting a wrapper that a launchd job is
running mid-flight makes bash resume at a stale offset in new bytes. `os.replace`
swaps the directory entry instead: a running process keeps the old inode until it
exits. Every `cp scripts/... ~/.volpred/bin/` line in the wrapper headers is
subtly wrong; use this script.

When a committed main snapshot removes a managed wrapper, `--apply` moves the
obsolete live executable into `~/.volpred/retired-cron-wrappers/` and writes a
durable receipt beside it. This makes retirement converge without an
irrecoverable unlink or a stale executable surviving outside Git ownership.

Usage:
    uv run python scripts/sync_cron_wrappers.py            # --check (default)
    uv run python scripts/sync_cron_wrappers.py --render-manifest
    uv run python scripts/sync_cron_wrappers.py --apply    # committed main only
    uv run python scripts/sync_cron_wrappers.py --check --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from volpred.ops.git_writer_lock import (
    GitWriterLockError,
    git_writer_lock,
)
from volpred.ops.git_writer_lock import (
    require_canonical_main_checkout as require_git_canonical_main_checkout,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_RELPATH = Path("config") / "cron_wrapper_manifest.json"

# The directory launchd actually execs from. Machine-local: absent in CI, which is
# why the manifest exists at all.
DEFAULT_INSTALL_DIR = Path.home() / ".volpred" / "bin"

# Sourced in place from the repo checkout (`source scripts/cron_lib.sh` after the
# wrapper cd's here), so it is never installed. Changes to it take effect live on
# the next fire — that is the design, not an oversight.
NOT_INSTALLED = frozenset({"cron_lib.sh"})

_HOST_WRAPPER_RE = re.compile(r"[^\s'\"]*\.volpred/bin/(cron_[^\s'\"]+\.sh)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_canonical_wrappers(root: Path = PROJECT_ROOT) -> list[Path]:
    """Every wrapper that belongs in the install dir, sorted by name."""
    return sorted(
        p for p in (root / "scripts").glob("cron_*.sh") if p.name not in NOT_INSTALLED
    )


def build_manifest_entries(root: Path = PROJECT_ROOT) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in iter_canonical_wrappers(root)}


def manifest_path(root: Path = PROJECT_ROOT) -> Path:
    return root / MANIFEST_RELPATH


def load_manifest(root: Path = PROJECT_ROOT) -> dict[str, str]:
    path = manifest_path(root)
    if not path.exists():
        raise FileNotFoundError(f"manifest missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("wrappers") or {})


def write_manifest(entries: dict[str, str], root: Path = PROJECT_ROOT) -> Path:
    path = manifest_path(root)
    payload = {
        "_comment": (
            "sha256 of every canonical scripts/cron_*.sh. launchd execs the copy in "
            "~/.volpred/bin, not this repo — this manifest is the only thing CI can "
            "see that proves the reviewed wrapper set is internally consistent. "
            "Regenerate without live effects using "
            "`uv run python scripts/sync_cron_wrappers.py --render-manifest`; commit "
            "it with the wrappers, then deploy from canonical main using `--apply`. "
            "Never hand-edit."
        ),
        "install_dir": "~/.volpred/bin",
        "not_installed": sorted(NOT_INSTALLED),
        "wrappers": dict(sorted(entries.items())),
    }
    # No generated_at: a timestamp would churn the diff on every regen and prove
    # nothing the hashes don't already prove.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def declared_host_wrappers(root: Path = PROJECT_ROOT) -> dict[str, str]:
    """basename -> job id, for every host wrapper named anywhere in runtime_schedules.json.

    Walks the whole config rather than one section: host wrapper paths appear under
    `system_crontab.items[].wrapper_script`, `cron_jobs[].tcc_bypass_copy`,
    `cron_jobs[].script` and `cron_jobs[].command`, and new sections will keep
    appearing. Matching on the path shape is section-agnostic.
    """
    config = json.loads((root / "config" / "runtime_schedules.json").read_text(encoding="utf-8"))
    found: dict[str, str] = {}

    def walk(node, job_id: str) -> None:
        if isinstance(node, dict):
            job_id = node.get("id") or node.get("name") or job_id
            for value in node.values():
                walk(value, job_id)
        elif isinstance(node, list):
            for value in node:
                walk(value, job_id)
        elif isinstance(node, str):
            for basename in _HOST_WRAPPER_RE.findall(node):
                found.setdefault(basename, job_id)

    walk(config, "<unknown>")
    return found


def check_manifest(root: Path = PROJECT_ROOT) -> list[str]:
    """Repo-only invariants. Safe in CI: never touches the install dir."""
    problems: list[str] = []
    try:
        recorded = load_manifest(root)
    except FileNotFoundError as exc:
        return [f"manifest_missing: {exc}"]
    except json.JSONDecodeError as exc:
        return [f"manifest_unparsable: {exc}"]

    actual = build_manifest_entries(root)

    for name in sorted(set(actual) - set(recorded)):
        problems.append(f"manifest_missing_entry: {name} (new wrapper never synced)")
    for name in sorted(set(recorded) - set(actual)):
        problems.append(f"manifest_stale_entry: {name} (canonical deleted or renamed)")
    for name in sorted(set(actual) & set(recorded)):
        if actual[name] != recorded[name]:
            problems.append(
                f"manifest_stale: {name} canonical={actual[name][:12]} "
                f"manifest={recorded[name][:12]} "
                "(edited without --render-manifest)"
            )

    # A wrapper the scheduler will exec but the repo cannot version is unfixable by
    # definition — you cannot edit-and-sync what has no canonical.
    for basename, job_id in sorted(declared_host_wrappers(root).items()):
        if not (root / "scripts" / basename).exists():
            problems.append(f"canonical_missing: {basename} (job={job_id}) has no scripts/ copy")

    return problems


def detect_live_drift(
    root: Path = PROJECT_ROOT, install_dir: Path | None = None
) -> list[dict[str, str]]:
    """Host-only: does the complete live population match canonical?

    Returns [] when the install dir is absent (CI, another machine) — this check is
    about a specific host's state, and having no install dir is not drift.
    """
    # An empty population means `root` is not a checkout (callers monkeypatch
    # PROJECT_ROOT to a bare tmp dir). Comparing nothing against nothing is not a
    # silent fallback — it is an empty domain, and a real checkout always has 40+.
    # A checkout that genuinely lost its wrappers is caught by check_manifest's
    # `manifest_stale_entry`, which reads the committed manifest rather than the glob.
    canonical_wrappers = iter_canonical_wrappers(root)
    if not canonical_wrappers:
        return []

    install_dir = install_dir or DEFAULT_INSTALL_DIR
    if not install_dir.is_dir():
        return []

    job_ids = declared_host_wrappers(root)
    findings: list[dict[str, str]] = []
    canonical_by_name = {path.name: path for path in canonical_wrappers}
    live_by_name = {
        path.name: path
        for path in install_dir.glob("cron_*.sh")
        if path.name not in NOT_INSTALLED
    }
    for name in sorted(set(live_by_name) - set(canonical_by_name)):
        findings.append(
            {
                "kind": "wrapper_obsolete_live",
                "job_id": job_ids.get(name, name),
                "detail": str(live_by_name[name]),
            }
        )
    for canonical in canonical_wrappers:
        live = install_dir / canonical.name
        job_id = job_ids.get(canonical.name, canonical.name)
        if live.is_symlink():
            findings.append(
                {
                    "kind": "wrapper_invalid_type",
                    "job_id": job_id,
                    "detail": f"{live} is a symlink",
                }
            )
            continue
        if not live.exists():
            findings.append(
                {"kind": "wrapper_not_installed", "job_id": job_id, "detail": str(live)}
            )
            continue
        if not live.is_file():
            findings.append(
                {
                    "kind": "wrapper_invalid_type",
                    "job_id": job_id,
                    "detail": f"{live} is not a regular file",
                }
            )
            continue
        live_mode = stat.S_IMODE(live.stat().st_mode)
        if live_mode != 0o755:
            findings.append(
                {
                    "kind": "wrapper_mode_drift",
                    "job_id": job_id,
                    "detail": f"live={live_mode:04o} canonical=0755",
                }
            )
        canonical_sha = sha256_file(canonical)
        live_sha = sha256_file(live)
        if canonical_sha != live_sha:
            findings.append(
                {
                    "kind": "wrapper_drift",
                    "job_id": job_id,
                    "detail": f"live={live_sha[:12]} canonical={canonical_sha[:12]}",
                }
            )
    return findings


def install_atomic(src: Path, dst: Path) -> None:
    """Replace `dst` without ever truncating the inode a running bash may be reading."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dst)  # atomic within the same filesystem
    finally:
        tmp.unlink(missing_ok=True)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot verify committed cron wrappers: {exc}") from exc


def _read_git_blob(root: Path, revision_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", revision_path],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot read committed cron wrapper: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"cannot read committed cron wrapper: {revision_path}")
    return result.stdout


def require_canonical_main_checkout(root: Path) -> None:
    """Expose the shared canonical-checkout contract with deployment wording."""

    try:
        require_git_canonical_main_checkout(root)
    except GitWriterLockError as exc:
        raise RuntimeError(
            "live cron wrapper deployment requires the canonical main checkout"
        ) from exc


def committed_wrapper_snapshot(root: Path) -> tuple[str, dict[str, bytes]]:
    """Return immutable HEAD bytes after rejecting any working-tree drift."""

    repo_root = Path(root).resolve()
    head_probe = _run_git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    head_oid = head_probe.stdout.strip()
    if head_probe.returncode != 0 or not head_oid:
        raise RuntimeError("cannot resolve committed cron wrapper revision")
    working_wrappers = {
        str(path.relative_to(repo_root))
        for path in iter_canonical_wrappers(repo_root)
    }
    head = _run_git(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        head_oid,
        "--",
        "scripts",
    )
    if head.returncode != 0:
        raise RuntimeError("cannot read committed cron wrapper population")
    head_wrappers = {
        path
        for path in head.stdout.splitlines()
        if Path(path).parent == Path("scripts")
        and Path(path).name.startswith("cron_")
        and Path(path).suffix == ".sh"
        and Path(path).name not in NOT_INSTALLED
    }
    if working_wrappers != head_wrappers:
        raise RuntimeError(
            "live cron wrapper deployment requires the complete wrapper population "
            "to be committed on main"
        )
    manifest_in_head = _run_git(
        repo_root,
        "cat-file",
        "-e",
        f"{head_oid}:{MANIFEST_RELPATH.as_posix()}",
    )
    if manifest_in_head.returncode != 0:
        raise RuntimeError("committed cron wrapper manifest is missing")
    committed_paths = sorted(head_wrappers) + [MANIFEST_RELPATH.as_posix()]
    diff = _run_git(repo_root, "diff", "--quiet", head_oid, "--", *committed_paths)
    if diff.returncode == 1:
        raise RuntimeError(
            "live cron wrapper deployment requires wrapper and manifest bytes "
            "to be committed on main"
        )
    if diff.returncode != 0:
        raise RuntimeError("cannot compare committed cron wrapper bytes")
    snapshot = {
        Path(path).name: _read_git_blob(repo_root, f"{head_oid}:{path}")
        for path in sorted(head_wrappers)
    }
    manifest_bytes = _read_git_blob(
        repo_root,
        f"{head_oid}:{MANIFEST_RELPATH.as_posix()}",
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        recorded = dict(manifest.get("wrappers") or {})
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise RuntimeError("committed cron wrapper manifest is invalid") from exc
    expected = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in snapshot.items()
    }
    if recorded != expected:
        raise RuntimeError(
            "committed cron wrapper manifest is stale; run --render-manifest "
            "before commit"
        )
    return head_oid, snapshot


def render_manifest(root: Path = PROJECT_ROOT) -> Path:
    """Render reviewable wrapper hashes without touching the live install."""

    return write_manifest(build_manifest_entries(root), root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_retirement_receipt(path: Path, payload: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _validated_quarantine_directory(
    install_dir: Path,
    *,
    create: bool,
) -> Path | None:
    """Return a private regular directory, durably anchored when newly created."""

    quarantine = install_dir.parent / "retired-cron-wrappers"
    try:
        quarantine_stat = quarantine.lstat()
    except FileNotFoundError:
        if not create:
            return None
        quarantine.mkdir(mode=0o700)
        os.chmod(quarantine, 0o700)
        _fsync_directory(quarantine)
        _fsync_directory(quarantine.parent)
        return quarantine
    if stat.S_ISLNK(quarantine_stat.st_mode) or not stat.S_ISDIR(
        quarantine_stat.st_mode
    ):
        raise RuntimeError(
            "cron wrapper retirement quarantine is not a regular directory"
        )
    if stat.S_IMODE(quarantine_stat.st_mode) != 0o700:
        os.chmod(quarantine, 0o700)
        _fsync_directory(quarantine)
    if stat.S_IMODE(quarantine.stat().st_mode) != 0o700:
        raise RuntimeError("cron wrapper retirement quarantine mode is not 0700")
    # Also re-anchor an existing directory: a prior process may have crashed after
    # mkdir but before its parent fsync completed.
    _fsync_directory(quarantine.parent)
    return quarantine


def _load_retirement_receipt(path: Path, install_dir: Path) -> tuple[dict, Path]:
    """Parse and validate a receipt without trusting any path stored inside it."""

    receipt_stat = path.lstat()
    if stat.S_ISLNK(receipt_stat.st_mode) or not stat.S_ISREG(receipt_stat.st_mode):
        raise RuntimeError(f"retirement receipt is not a regular file: {path.name}")
    if stat.S_IMODE(receipt_stat.st_mode) != 0o600:
        raise RuntimeError(f"retirement receipt mode is not 0600: {path.name}")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"retirement receipt is invalid: {path.name}") from exc
    try:
        original_name = receipt.get("original_name")
    except AttributeError as exc:
        raise RuntimeError(f"retirement receipt is invalid: {path.name}") from exc
    if (
        receipt.get("schema_version") != "cron-wrapper-retirement.v1"
        or receipt.get("state") not in {"prepared", "retired"}
        or not isinstance(original_name, str)
        or Path(original_name).name != original_name
        or not original_name.startswith("cron_")
        or not original_name.endswith(".sh")
    ):
        raise RuntimeError(f"retirement receipt contract is invalid: {path.name}")
    suffix = ".receipt.json"
    if not path.name.endswith(suffix):
        raise RuntimeError(f"retirement receipt name is invalid: {path.name}")
    retired_path = path.with_name(f"{path.name[: -len(suffix)]}.retired")
    expected_original = install_dir / original_name
    sha256 = receipt.get("sha256")
    mode = receipt.get("mode")
    head_oid = receipt.get("head_oid")
    if (
        receipt.get("original_path") != str(expected_original)
        or receipt.get("quarantine_path") != str(retired_path)
        or not retired_path.name.startswith(f"{original_name}.")
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        or not isinstance(mode, str)
        or re.fullmatch(r"0o[0-7]{3,4}", mode) is None
        or not isinstance(head_oid, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head_oid) is None
    ):
        raise RuntimeError(f"retirement receipt evidence is invalid: {path.name}")
    return receipt, retired_path


def _verify_retirement_artifact(path: Path, receipt: dict) -> None:
    artifact_stat = path.lstat()
    if stat.S_ISLNK(artifact_stat.st_mode) or not stat.S_ISREG(artifact_stat.st_mode):
        raise RuntimeError(f"retirement artifact is not a regular file: {path.name}")
    if sha256_file(path) != receipt["sha256"]:
        raise RuntimeError(f"retirement artifact hash mismatch: {path.name}")
    if oct(stat.S_IMODE(artifact_stat.st_mode)) != receipt["mode"]:
        raise RuntimeError(f"retirement artifact mode mismatch: {path.name}")


def recover_prepared_retirements(install_dir: Path) -> list[str]:
    """Converge durable prepared transactions before starting new retirements."""

    quarantine = _validated_quarantine_directory(install_dir, create=False)
    if quarantine is None:
        return []
    recovered: list[str] = []
    for receipt_path in sorted(quarantine.glob("*.receipt.json")):
        receipt, retired_path = _load_retirement_receipt(receipt_path, install_dir)
        if receipt["state"] == "retired":
            if not retired_path.is_symlink() and not retired_path.exists():
                raise RuntimeError(
                    f"finalized retirement artifact is missing: {retired_path.name}"
                )
            _verify_retirement_artifact(retired_path, receipt)
            continue
        live = install_dir / receipt["original_name"]
        live_exists = live.is_symlink() or live.exists()
        retired_exists = retired_path.is_symlink() or retired_path.exists()
        if live_exists == retired_exists:
            raise RuntimeError(
                "prepared cron wrapper retirement has ambiguous source/destination "
                f"state: {receipt['original_name']}"
            )
        if live_exists:
            _verify_retirement_artifact(live, receipt)
            os.replace(live, retired_path)
            _fsync_directory(quarantine)
            _fsync_directory(install_dir)
        else:
            _verify_retirement_artifact(retired_path, receipt)
        receipt["state"] = "retired"
        receipt["retired_at"] = datetime.now(UTC).isoformat()
        receipt["recovered_at"] = receipt["retired_at"]
        _atomic_write_retirement_receipt(receipt_path, receipt)
        recovered.append(receipt["original_name"])
    return recovered


def retire_obsolete_live_wrappers(
    snapshot: dict[str, bytes],
    install_dir: Path,
    *,
    head_oid: str,
) -> list[str]:
    """Atomically quarantine obsolete managed executables with durable receipts."""

    obsolete = sorted(
        path
        for path in install_dir.glob("cron_*.sh")
        if path.name not in snapshot and path.name not in NOT_INSTALLED
    )
    if not obsolete:
        return []
    quarantine = _validated_quarantine_directory(install_dir, create=True)
    assert quarantine is not None
    retired: list[str] = []
    for live in obsolete:
        if live.is_symlink() or not live.is_file():
            raise RuntimeError(
                f"obsolete live cron wrapper is not a regular file: {live.name}"
            )
        source_stat = live.stat()
        observed_at = datetime.now(UTC)
        token = f"{observed_at.strftime('%Y%m%dT%H%M%S%fZ')}.{uuid.uuid4().hex[:12]}"
        stem = f"{live.name}.{token}"
        retired_path = quarantine / f"{stem}.retired"
        receipt_path = quarantine / f"{stem}.receipt.json"
        receipt = {
            "schema_version": "cron-wrapper-retirement.v1",
            "state": "prepared",
            "head_oid": head_oid,
            "original_name": live.name,
            "original_path": str(live),
            "quarantine_path": str(retired_path),
            "sha256": sha256_file(live),
            "mode": oct(stat.S_IMODE(source_stat.st_mode)),
            "prepared_at": observed_at.isoformat(),
        }
        _atomic_write_retirement_receipt(receipt_path, receipt)
        os.replace(live, retired_path)
        # Persist the destination entry before persisting source removal. Reversing
        # this order creates a power-loss window where neither name is durable.
        _fsync_directory(quarantine)
        _fsync_directory(install_dir)
        _verify_retirement_artifact(retired_path, receipt)
        receipt["state"] = "retired"
        receipt["retired_at"] = datetime.now(UTC).isoformat()
        _atomic_write_retirement_receipt(receipt_path, receipt)
        retired.append(live.name)
    return retired


def verify_live_snapshot(snapshot: dict[str, bytes], install_dir: Path) -> None:
    """Read back the complete managed live population before reporting success."""

    expected_population = set(snapshot)
    actual_population = {
        path.name
        for path in install_dir.glob("cron_*.sh")
        if path.name not in NOT_INSTALLED
    }
    if actual_population != expected_population:
        raise RuntimeError(
            "live cron wrapper population does not match the committed snapshot"
        )
    for name, payload in snapshot.items():
        live = install_dir / name
        if live.is_symlink() or not live.is_file():
            raise RuntimeError(f"live cron wrapper is not a regular file: {name}")
        if sha256_file(live) != hashlib.sha256(payload).hexdigest():
            raise RuntimeError(f"live cron wrapper read-back mismatch: {name}")
        if stat.S_IMODE(live.stat().st_mode) != 0o755:
            raise RuntimeError(f"live cron wrapper mode is not 0755: {name}")


def apply_sync(root: Path = PROJECT_ROOT, install_dir: Path | None = None) -> dict:
    require_canonical_main_checkout(root)
    install_dir = install_dir or DEFAULT_INSTALL_DIR
    installed: list[str] = []
    unchanged: list[str] = []
    retired: list[str] = []
    with git_writer_lock(root, actor="cron-wrapper-deploy", timeout_s=120):
        require_canonical_main_checkout(root)
        head_oid, snapshot = committed_wrapper_snapshot(root)
        retired = recover_prepared_retirements(install_dir)
        retired.extend(
            retire_obsolete_live_wrappers(
                snapshot,
                install_dir,
                head_oid=head_oid,
            )
        )
        with tempfile.TemporaryDirectory(
            prefix="volpred-cron-wrapper-snapshot-"
        ) as tmp:
            snapshot_dir = Path(tmp)
            for name, payload in snapshot.items():
                source = snapshot_dir / name
                source.write_bytes(payload)
                live = install_dir / name
                expected_hash = hashlib.sha256(payload).hexdigest()
                if (
                    live.is_file()
                    and not live.is_symlink()
                    and stat.S_IMODE(live.stat().st_mode) == 0o755
                    and sha256_file(live) == expected_hash
                ):
                    unchanged.append(name)
                    continue
                install_atomic(source, live)
                installed.append(name)
        verify_live_snapshot(snapshot, install_dir)
    return {"installed": installed, "unchanged": unchanged, "retired": retired}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="install committed wrappers from canonical main",
    )
    mode.add_argument(
        "--render-manifest",
        action="store_true",
        help="regenerate the reviewable manifest without live effects",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="report drift, exit 1 if any (default)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--install-dir", type=Path, default=None, help="override ~/.volpred/bin")
    args = parser.parse_args(argv)

    if args.apply:
        result = apply_sync(PROJECT_ROOT, args.install_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(
                f"installed: {len(result['installed'])}  "
                f"unchanged: {len(result['unchanged'])}  "
                f"retired: {len(result['retired'])}"
            )
            for name in result["installed"]:
                print(f"  + {name}")
            for name in result["retired"]:
                print(f"  - {name}")
        return 0
    if args.render_manifest:
        rendered = render_manifest(PROJECT_ROOT)
        if args.json:
            print(json.dumps({"manifest": str(rendered)}, ensure_ascii=False, indent=2))
        else:
            print(f"manifest: {rendered.relative_to(PROJECT_ROOT)}")
        return 0

    problems = check_manifest(PROJECT_ROOT)
    live = detect_live_drift(PROJECT_ROOT, args.install_dir)
    problems.extend(f"{f['kind']}: {f['job_id']} {f['detail']}" for f in live)

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    elif problems:
        print("cron wrapper drift:")
        for entry in problems:
            print(f"  - {entry}")
        print(
            "\nfix: uv run python scripts/sync_cron_wrappers.py --render-manifest "
            "then commit/merge and deploy from canonical main with --apply"
        )
    else:
        print("cron wrappers: in lockstep (canonical == manifest == ~/.volpred/bin)")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
