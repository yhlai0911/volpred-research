"""Fail-closed OS boundary for one producer-scoped dispatch workspace.

The worker may write exactly four surfaces:

* its registered linked worktree;
* that worktree's own Git metadata, branch ref and object database;
* a per-fire synthetic HOME/TMP/cache directory;
* its already-open stdout/stderr descriptors.

Canonical ``storage/``, the shared checkout, other repositories, user config,
credentials and ``~/.volpred`` are deliberately absent from the write
allow-list.  Canonical task lifecycle and post-merge effects therefore remain
supervisor-owned operations; an isolated producer cannot bypass their locked
interfaces with a shell redirect.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import secrets
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from volpred.ops.diagnostics import warn

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


class IsolationUnavailable(RuntimeError):
    """The machine cannot prove the requested workspace boundary."""


class ProviderAuthHandoffError(IsolationUnavailable):
    """Detached cleanup did not acknowledge custody of a durable intent."""

    def __init__(self, message: str, *, receipt_path: Path):
        super().__init__(message)
        self.receipt_path = receipt_path


class ProviderAuthHandoffQuarantined(ProviderAuthHandoffError):
    """Reaper could not be acknowledged or reaped; parent retains custody."""

    def __init__(
        self,
        message: str,
        *,
        receipt_path: Path,
        reaper_process: Any,
    ):
        super().__init__(message, receipt_path=receipt_path)
        self.reaper_process = reaper_process


@dataclass(frozen=True)
class PreparedIsolation:
    """Immutable admission receipt produced before a worker can spawn."""

    profile_path: str
    run_dir: str
    synthetic_home: str
    tmp_dir: str
    pycache_dir: str
    workspace: str
    canonical_root: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _quoted(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def _git_path(workspace: Path, *args: str) -> Path:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not (result.stdout or "").strip():
        raise IsolationUnavailable(
            f"cannot resolve workspace Git identity: {' '.join(args)}"
        )
    return Path((result.stdout or "").strip()).resolve()


def _workspace_write_roots(
    *,
    canonical_root: Path,
    workspace: Path,
    run_dir: Path,
) -> tuple[Path, ...]:
    canonical = canonical_root.resolve()
    workspace = workspace.resolve()
    if workspace == canonical or canonical not in workspace.parents:
        raise IsolationUnavailable(
            "isolated workspace must be a registered child of canonical root"
        )

    common_dir = _git_path(
        workspace, "rev-parse", "--path-format=absolute", "--git-common-dir",
    )
    workspace_git_dir = _git_path(
        workspace, "rev-parse", "--absolute-git-dir",
    )
    main_common = _git_path(
        canonical, "rev-parse", "--path-format=absolute", "--git-common-dir",
    )
    if common_dir != main_common or workspace_git_dir == common_dir:
        raise IsolationUnavailable(
            "workspace is not a registered linked worktree of canonical root"
        )

    branch = subprocess.run(
        ["/usr/bin/git", "-C", str(workspace), "symbolic-ref", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    branch_ref = (branch.stdout or "").strip()
    if branch.returncode != 0 or not branch_ref.startswith("refs/heads/"):
        raise IsolationUnavailable("isolated workspace branch must be attached")
    # Producer tools edit working-tree bytes only. Git index/object/ref
    # mutations are supervisor-finalizer responsibilities, so the shared
    # common object database and branch refs are intentionally read-only.
    explicit = (workspace, run_dir.resolve(), Path("/dev"))
    return tuple(dict.fromkeys(explicit))


def sandbox_profile(
    *,
    canonical_root: Path,
    workspace: Path,
    run_dir: Path,
) -> str:
    """Return a deny-by-default macOS profile for one exact workspace."""
    roots = _workspace_write_roots(
        canonical_root=canonical_root,
        workspace=workspace,
        run_dir=run_dir,
    )
    lines = [
        "(version 1)",
        '(import "system.sb")',
        "(deny default)",
        "(allow process*)",
        # The model-provider transport needs outbound TLS. Inbound listeners
        # are not required and remain denied. Remote side effects are also
        # fenced by the synthetic HOME plus credential-env scrub in
        # ``isolated_environment``; task post-actions execute outside here.
        "(allow network-outbound)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix*)",
        "(allow dynamic-code-generation)",
        "(allow file-read*)",
    ]
    lines.extend(
        f'(allow file-write* (subpath "{_quoted(path)}"))'
        for path in roots
        if path.is_dir()
    )
    lines.extend(
        f'(allow file-write* (literal "{_quoted(path)}"))\n'
        f'(allow file-write* (literal "{_quoted(path)}.lock"))'
        for path in roots
        if not path.is_dir()
    )
    # The linked-worktree control file sits inside the otherwise writable
    # working tree. It points into the common Git directory and must remain a
    # supervisor-owned identity, not producer-editable bytes.
    lines.append(
        f'(deny file-write* (literal "{_quoted(workspace / ".git")}"))'
    )
    home = Path.home().resolve()
    credential_paths = (
        home / ".ssh",
        home / ".aws",
        home / ".netrc",
        home / ".git-credentials",
        home / ".config" / "gh",
        home / ".config" / "gcloud",
        home / ".config" / "supabase",
        home / ".codex",
        home / ".volpred" / "secrets",
        home / "Library" / "Keychains",
    )
    for path in credential_paths:
        predicate = (
            "literal"
            if path.name in {".netrc", ".git-credentials"}
            else "subpath"
        )
        lines.append(
            f'(deny file-read* ({predicate} "{_quoted(path)}"))'
        )
    # Git commit is unnecessary in the producer and remote transports are
    # explicitly excluded. The finalizer performs the only Git mutation.
    for executable in (
        Path("/usr/bin/ssh"),
        Path("/usr/bin/scp"),
        Path("/usr/bin/curl"),
        Path("/opt/homebrew/bin/gh"),
        Path("/usr/libexec/git-core/git-remote-http"),
        Path("/usr/libexec/git-core/git-remote-https"),
        Path(
            "/Library/Developer/CommandLineTools/usr/libexec/git-core/"
            "git-remote-http"
        ),
        Path(
            "/Library/Developer/CommandLineTools/usr/libexec/git-core/"
            "git-remote-https"
        ),
    ):
        lines.append(
            f'(deny process-exec (literal "{_quoted(executable)}"))'
        )
    return "\n".join(lines) + "\n"


def prepare(
    *,
    canonical_root: Path,
    workspace: Path,
    job_id: str,
    profile_root: Path,
) -> PreparedIsolation:
    """Preflight and persist the substrate before state is bound/spawned."""
    if platform.system() != "Darwin" or not SANDBOX_EXEC.is_file():
        raise IsolationUnavailable("macOS sandbox-exec is required")
    safe_job = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in "-_")
    if not safe_job:
        raise IsolationUnavailable("isolation job id is empty")
    run_dir = (profile_root / safe_job).resolve()
    synthetic_home = run_dir / "home"
    tmp_dir = run_dir / "tmp"
    pycache_dir = run_dir / "pycache"
    for path in (run_dir, synthetic_home, tmp_dir, pycache_dir):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    profile = run_dir / "sandbox.sb"
    payload = sandbox_profile(
        canonical_root=canonical_root,
        workspace=workspace,
        run_dir=run_dir,
    )
    profile.write_text(payload, encoding="utf-8")
    os.chmod(profile, 0o600)
    # Parse the profile now. A syntax/substrate failure after slot admission
    # must be handled as a defer, never as an ordinary worker failure.
    probe = subprocess.run(
        [str(SANDBOX_EXEC), "-f", str(profile), "/usr/bin/true"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if probe.returncode != 0:
        raise IsolationUnavailable(
            "sandbox profile preflight failed: "
            + ((probe.stderr or probe.stdout or "")[-300:].strip())
        )
    return PreparedIsolation(
        profile_path=str(profile),
        run_dir=str(run_dir),
        synthetic_home=str(synthetic_home),
        tmp_dir=str(tmp_dir),
        pycache_dir=str(pycache_dir),
        workspace=str(workspace.resolve()),
        canonical_root=str(canonical_root.resolve()),
    )


_PASSTHROUGH_ENV = frozenset({
    "PATH", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "SHELL",
    "USER", "LOGNAME", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    # Exact non-secret dispatch identity/configuration required by the worker
    # and fire-manifest contracts. These carry attribution, not authority.
    "VOLPRED_ACTOR", "VOLPRED_TASK_CLAIM_OWNER", "VOLPRED_DISPATCH_JOB_ID",
    "VOLPRED_DISPATCH_SLOT", "VOLPRED_FIRE_ID", "VOLPRED_FIRE_REPO_ROOT",
    "VOLPRED_DISPATCH_DEBUG_FROM_ATTEMPT", "VOLPRED_DISPATCH_EFFORT",
    "VOLPRED_DISPATCH_FATAL_POLL_S", "VOLPRED_DISPATCH_FATAL_STALL_S",
    "VOLPRED_DISPATCH_SIDECAR_DEAD_S", "VOLPRED_DISPATCH_SIDECAR_STALL_S",
    "VOLPRED_DISPATCH_SIDECAR_STARTUP_WINDOW_S",
})

_PROVIDER_AUTH_ENV: dict[str, frozenset[str]] = {
    # Claude Code's subscription token is model authority and must be scoped to
    # the Claude launch contract. In particular, never hand this bearer to a
    # Codex/AGY child merely because all providers share one parent daemon.
    "claude-cli": frozenset({"CLAUDE_CODE_OAUTH_TOKEN"}),
    # Codex desktop and AGY subscription authentication are intentionally not
    # represented by a transferable environment bearer.
    "codex-cli": frozenset(),
    "agy-cli": frozenset(),
}

_PREPARED_FIELDS = frozenset({
    "profile_path",
    "run_dir",
    "synthetic_home",
    "tmp_dir",
    "pycache_dir",
    "workspace",
    "canonical_root",
})


def _prepared_payload(
    prepared: PreparedIsolation | dict[str, Any],
) -> dict[str, str]:
    raw = (
        prepared.to_dict()
        if isinstance(prepared, PreparedIsolation)
        else {str(k): str(v) for k, v in prepared.items()}
    )
    missing = sorted(
        key for key in _PREPARED_FIELDS if not str(raw.get(key) or "").strip()
    )
    if missing:
        raise IsolationUnavailable(
            f"isolation receipt missing fields: {missing}"
        )
    return raw


def _credential_home() -> Path:
    """Operations Core's single-owner Codex credential authority.

    The interactive Codex app also rotates ``~/.codex/auth.json`` and does not
    participate in our lock.  Treating that shared file as the authoritative
    handback target made a baseline-hash check inherently racy.  Production
    leases therefore originate from a dedicated, owner-only HOME which only
    this broker may mutate.  Provisioning is explicit; a missing authority
    fails closed instead of silently copying credentials during a fire.
    """
    return (
        Path.home()
        / ".volpred"
        / "secrets"
        / "provider-auth"
        / "codex-home"
    )


_MAX_PROVIDER_AUTH_BYTES = 1024 * 1024
_PROVIDER_AUTH_LOCK_NAME = ".volpred-provider-auth.lock"


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise IsolationUnavailable(
            f"provider auth directory is unavailable or unsafe: {path}"
        ) from exc


def _open_child_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool = False,
) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            # The next O_NOFOLLOW directory open verifies the existing node.
            pass  # silent-ok: race-safe create followed by exact validation
        except OSError as exc:
            raise IsolationUnavailable(
                f"cannot create private provider auth directory: {name}"
            ) from exc
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise IsolationUnavailable(
            f"provider auth directory is missing, foreign, or a symlink: {name}"
        ) from exc
    metadata = os.fstat(fd)
    if metadata.st_uid != os.getuid():
        os.close(fd)
        raise IsolationUnavailable(
            f"provider auth directory has foreign owner: {name}"
        )
    return fd


def _read_private_at(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise IsolationUnavailable(
            f"subscription credential is unavailable: {name}"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise IsolationUnavailable(
                "subscription credential must be a regular file"
            )
        if metadata.st_uid != os.getuid():
            raise IsolationUnavailable(
                "subscription credential must be owned by the current user"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise IsolationUnavailable(
                "subscription credential permissions must be owner-only"
            )
        if metadata.st_size > _MAX_PROVIDER_AUTH_BYTES:
            raise IsolationUnavailable(
                "subscription credential exceeds the maximum safe size"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_PROVIDER_AUTH_BYTES:
                raise IsolationUnavailable(
                    "subscription credential grew beyond the maximum safe size"
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _acquire_provider_auth_lock(directory_fd: int) -> int:
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(
            _PROVIDER_AUTH_LOCK_NAME,
            flags,
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        raise IsolationUnavailable(
            "cannot open the provider credential authority lock"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise IsolationUnavailable(
                "provider credential authority lock has unsafe identity"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise IsolationUnavailable(
                "provider credential authority lock must be owner-only"
            )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IsolationUnavailable(
                "provider credential authority is already leased"
            ) from exc
        return fd
    except Exception:
        os.close(fd)
        raise


def _release_provider_auth_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _close_provider_auth_lock_reference(fd: int | None) -> None:
    """Drop one shared flock reference without unlocking sibling descriptors."""
    if fd is not None:
        os.close(fd)


def _write_private_at(directory_fd: int, name: str, payload: bytes) -> None:
    temporary = f".{name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(temporary, flags, 0o600, dir_fd=directory_fd)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(
            temporary,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.chmod(name, 0o600, dir_fd=directory_fd, follow_symlinks=False)
        os.fsync(directory_fd)
    except OSError as exc:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass  # silent-ok: failed atomic write may leave no temp to clean
        raise IsolationUnavailable(
            "cannot materialize provider subscription credential"
        ) from exc


def _validate_codex_auth(payload: bytes) -> None:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsolationUnavailable(
            "Codex subscription credential is not valid JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise IsolationUnavailable(
            "Codex subscription credential must be a JSON object"
        )
    if decoded.get("OPENAI_API_KEY"):
        raise IsolationUnavailable(
            "Codex credential contains an API key; subscription OAuth required"
        )
    tokens = decoded.get("tokens")
    required_tokens = ("access_token", "refresh_token", "id_token", "account_id")
    if not isinstance(tokens, dict) or any(
        not isinstance(tokens.get(key), str) or not tokens[key]
        for key in required_tokens
    ):
        raise IsolationUnavailable(
            "Codex subscription credential is missing OAuth token fields"
        )


@dataclass(frozen=True)
class ProviderAuthCloseReceipt:
    ok: bool
    reconciled: bool
    source_advanced: bool
    cleaned: bool
    reason: str


@dataclass(frozen=True)
class ProviderAuthHandoffReceipt:
    reaper_pid: int
    pgid: int
    receipt_path: str


@dataclass
class ProviderAuthLease:
    """One per-fire Codex OAuth copy held by a single credential authority."""

    source_home: str
    run_dir: str
    destination_path: str
    baseline_sha256: str
    lease_id: str = field(default_factory=lambda: secrets.token_hex(16))
    _authority_lock_fd: int | None = field(default=None, repr=False)
    _reconciled: bool = field(default=False, repr=False)
    _source_advanced: bool = field(default=False, repr=False)
    _destination_unlinked: bool = field(default=False, repr=False)
    _terminal_receipt: ProviderAuthCloseReceipt | None = field(
        default=None,
        repr=False,
    )

    def close(
        self,
        *,
        checkpoint: Callable[[str], None] | None = None,
    ) -> ProviderAuthCloseReceipt:
        """Reconcile and remove the synthetic credential.

        A failed close remains retryable and retains the authority lock.  Only
        a fully fsynced cleanup becomes terminal; repeated calls then return
        the exact same receipt rather than inventing a successful
        ``already_closed`` state.
        """
        if self._terminal_receipt is not None:
            return self._terminal_receipt
        if self._authority_lock_fd is None:
            return ProviderAuthCloseReceipt(
                False,
                self._reconciled,
                self._source_advanced,
                self._destination_unlinked,
                "provider credential authority lock is not held",
            )

        destination_dir_fd: int | None = None
        destination_home_fd: int | None = None
        destination_run_fd: int | None = None
        destination_dir_fsynced = False
        try:
            destination_run_fd = _open_directory(Path(self.run_dir))
            destination_home_fd = _open_child_directory(
                destination_run_fd, "home",
            )
            try:
                destination_dir_fd = _open_child_directory(
                    destination_home_fd, ".codex",
                )
            except IsolationUnavailable:
                if not self._destination_unlinked:
                    raise
                try:
                    os.stat(
                        ".codex",
                        dir_fd=destination_home_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass  # silent-ok: durable close phase permits absent dir
                else:
                    # Existing-but-unsafe is not equivalent to already clean.
                    raise
                # A prior process durably unlinked+fsynced auth.json and then
                # removed the empty directory before its terminal receipt.
                # Fsyncing HOME makes that already-clean state retryable.
                os.fsync(destination_home_fd)
                destination_dir_fsynced = True
            if self._destination_unlinked and destination_dir_fd is not None:
                try:
                    os.stat(
                        "auth.json",
                        dir_fd=destination_dir_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass  # silent-ok: authoritative post-drain re-read is empty
                else:
                    # A still-running descendant may have recreated/rotated
                    # auth after the recovery scanner's earlier snapshot.
                    self._destination_unlinked = False
            if not self._destination_unlinked:
                assert destination_dir_fd is not None
                destination_payload = _read_private_at(
                    destination_dir_fd, "auth.json",
                )
                _validate_codex_auth(destination_payload)
                destination_sha = hashlib.sha256(
                    destination_payload
                ).hexdigest()
                if (
                    destination_sha != self.baseline_sha256
                    and not self._reconciled
                    and not self._source_advanced
                ):
                    source_home_fd = _open_directory(Path(self.source_home))
                    try:
                        source_dir_fd = _open_child_directory(
                            source_home_fd, ".codex",
                        )
                        try:
                            source_payload = _read_private_at(
                                source_dir_fd, "auth.json",
                            )
                            _validate_codex_auth(source_payload)
                            source_sha = hashlib.sha256(
                                source_payload
                            ).hexdigest()
                            if source_sha == self.baseline_sha256:
                                # The lock is held for the complete lease, and
                                # this source is the dedicated Operations Core
                                # authority, not the interactive ~/.codex file.
                                # Thus no other compliant writer can enter
                                # between this comparison and replacement.
                                _write_private_at(
                                    source_dir_fd,
                                    "auth.json",
                                    destination_payload,
                                )
                                verified = _read_private_at(
                                    source_dir_fd, "auth.json",
                                )
                                if (
                                    hashlib.sha256(verified).hexdigest()
                                    != destination_sha
                                ):
                                    raise IsolationUnavailable(
                                        "Codex auth rotation handback "
                                        "verification failed"
                                    )
                                self._reconciled = True
                            else:
                                self._source_advanced = True
                        finally:
                            os.close(source_dir_fd)
                    finally:
                        os.close(source_home_fd)
                if checkpoint is not None:
                    checkpoint("unlink_intent")
                os.unlink("auth.json", dir_fd=destination_dir_fd)
                self._destination_unlinked = True
            if destination_dir_fd is not None:
                os.fsync(destination_dir_fd)
                destination_dir_fsynced = True
                if checkpoint is not None:
                    checkpoint("destination_unlinked")
        except (IsolationUnavailable, OSError) as exc:
            return ProviderAuthCloseReceipt(
                ok=False,
                reconciled=self._reconciled,
                source_advanced=self._source_advanced,
                cleaned=False,
                reason=str(exc),
            )
        finally:
            if destination_dir_fd is not None:
                os.close(destination_dir_fd)
            if destination_home_fd is not None:
                try:
                    if destination_dir_fsynced:
                        os.rmdir(".codex", dir_fd=destination_home_fd)
                        os.fsync(destination_home_fd)
                except OSError:
                    # auth.json is already unlinked+fsynced; retaining an
                    # empty/non-empty directory does not retain our secret.
                    pass  # silent-ok: best-effort empty-directory cleanup
                os.close(destination_home_fd)
            if destination_run_fd is not None:
                os.close(destination_run_fd)

        reason = (
            "rotation_reconciled"
            if self._reconciled
            else (
                "authoritative_source_advanced"
                if self._source_advanced
                else "closed"
            )
        )
        self._terminal_receipt = ProviderAuthCloseReceipt(
            ok=True,
            reconciled=self._reconciled,
            source_advanced=self._source_advanced,
            cleaned=True,
            reason=reason,
        )
        # Reaper handoff uses pass_fds, whose duplicate shares one open-file
        # description with the parent. Explicit LOCK_UN here would unlock the
        # parent's quarantine descriptor too. Close-only preserves custody
        # until the final descriptor is gone; that last close releases flock.
        _close_provider_auth_lock_reference(self._authority_lock_fd)
        self._authority_lock_fd = None
        return self._terminal_receipt


@dataclass
class _QuarantinedProviderAuthLease:
    lease: ProviderAuthLease
    pgid: int
    leader_pid: int
    leader_started_wall: str
    receipt_path: Path
    reaper_process: Any
    empty_group_reads: int = 0


_QUARANTINED_PROVIDER_AUTH_LEASES: dict[
    str, _QuarantinedProviderAuthLease
] = {}
_QUARANTINED_PROVIDER_AUTH_LOCK = threading.Lock()


def quarantine_provider_auth_lease(
    lease: ProviderAuthLease,
    *,
    pgid: int,
    leader_pid: int,
    leader_started_wall: str,
    receipt_path: Path,
    reaper_process: Any,
) -> None:
    """Keep the parent FD reachable until health proves cleanup is safe."""
    with _QUARANTINED_PROVIDER_AUTH_LOCK:
        _QUARANTINED_PROVIDER_AUTH_LEASES[lease.lease_id] = (
            _QuarantinedProviderAuthLease(
                lease=lease,
                pgid=pgid,
                leader_pid=leader_pid,
                leader_started_wall=leader_started_wall,
                receipt_path=receipt_path,
                reaper_process=reaper_process,
            )
        )


def reap_quarantined_provider_auth_leases() -> dict[str, int]:
    """Nonblocking health-tick reconciler for no-ACK cleanup children."""
    from . import procutil

    pending = 0
    cleaned = 0
    with _QUARANTINED_PROVIDER_AUTH_LOCK:
        records = list(_QUARANTINED_PROVIDER_AUTH_LEASES.items())
    for lease_id, record in records:
        try:
            child_rc = record.reaper_process.poll()
        except Exception as exc:  # noqa: BLE001
            warn(
                "provider-auth-recovery",
                "quarantined reaper liveness probe failed",
                lease_id=lease_id,
                err=str(exc),
            )
            pending += 1
            continue
        if child_rc is None:
            try:
                record.reaper_process.kill()
            except (OSError, ProcessLookupError) as exc:
                warn(
                    "provider-auth-recovery",
                    "quarantined reaper kill retry failed",
                    lease_id=lease_id,
                    err=str(exc),
                )
            pending += 1
            continue
        members = procutil.pgid_members_checked(record.pgid)
        if members == []:
            record.empty_group_reads += 1
        else:
            record.empty_group_reads = 0
        if record.empty_group_reads < 2:
            pending += 1
            continue
        terminal = _reconcile_lease_from_provider_auth_receipt(
            record.lease,
            record.receipt_path,
        )
        if terminal is not None:
            with _QUARANTINED_PROVIDER_AUTH_LOCK:
                _QUARANTINED_PROVIDER_AUTH_LEASES.pop(lease_id, None)
            cleaned += 1
            continue
        try:
            attempt, claimed = _begin_provider_auth_cleanup_attempt(
                record.receipt_path,
                owner=f"health:{os.getpid()}",
            )
        except Exception as exc:  # noqa: BLE001
            warn(
                "provider-auth-recovery",
                "quarantine cleanup attempt claim failed",
                lease_id=lease_id,
                err=str(exc),
            )
            pending += 1
            continue
        if claimed.get("state") == "cleaned":
            pending += 1
            continue
        receipt = record.lease.close(
            checkpoint=lambda phase: _transition_provider_auth_reaper_receipt(
                record.receipt_path,
                {
                    "state": "cleanup_started",
                    "attempts": attempt,
                    "close_phase": phase,
                },
            ),
        )
        if not receipt.ok:
            pending += 1
            continue
        try:
            _transition_provider_auth_reaper_receipt(
                record.receipt_path,
                {
                    "state": "cleaned",
                    "recovery": "health_quarantine_owner",
                    "close": asdict(receipt),
                },
            )
        except Exception as exc:  # terminal bytes are already clean
            warn(
                "provider-auth-recovery",
                "quarantine cleaned but terminal receipt failed",
                lease_id=lease_id,
                err=str(exc),
            )
        with _QUARANTINED_PROVIDER_AUTH_LOCK:
            _QUARANTINED_PROVIDER_AUTH_LEASES.pop(lease_id, None)
        cleaned += 1
    return {"pending": pending, "cleaned": cleaned}


def _write_provider_auth_reaper_receipt(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    directory_fd = _open_directory(path.parent)
    try:
        _write_private_at(
            directory_fd,
            path.name,
            (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        )
    finally:
        os.close(directory_fd)


_REAPER_STATE_ORDER = {
    "handoff_intent": 10,
    "waiting_for_process_group": 20,
    "handoff_failed": 21,
    "recovery_started": 22,
    "quarantined": 23,
    "cleanup_started": 25,
    "cleanup_retry": 30,
    "cleaned": 40,
}


def _transition_provider_auth_reaper_receipt(
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a monotonic reaper transition under a receipt-local flock."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        current: dict[str, Any] = {}
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass  # silent-ok: first monotonic transition creates the receipt
        except (OSError, json.JSONDecodeError) as exc:
            raise IsolationUnavailable(
                "provider auth reaper receipt is unreadable"
            ) from exc
        current_state = str(current.get("state") or "")
        next_state = str(payload.get("state") or "")
        try:
            current_attempt = int(current.get("attempts") or 0)
            next_attempt = int(payload.get("attempts") or current_attempt)
        except (TypeError, ValueError):
            current_attempt = next_attempt = 0
        if current_state == "cleaned" and next_state != "cleaned":
            return current
        if next_attempt < current_attempt:
            return current
        if (
            next_attempt == current_attempt
            and _REAPER_STATE_ORDER.get(next_state, -1)
            < _REAPER_STATE_ORDER.get(current_state, -1)
        ):
            return current
        merged = {**current, **payload}
        _write_provider_auth_reaper_receipt(path, merged)
        return merged
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _begin_provider_auth_cleanup_attempt(
    path: Path,
    *,
    owner: str,
) -> tuple[int, dict[str, Any]]:
    """Atomically claim attempt N+1 so older writers cannot hide checkpoints."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IsolationUnavailable(
                "provider auth cleanup attempt receipt is unreadable"
            ) from exc
        if current.get("state") == "cleaned":
            return int(current.get("attempts") or 0), current
        attempt = int(current.get("attempts") or 0) + 1
        merged = {
            **current,
            "state": "cleanup_started",
            "attempts": attempt,
            "cleanup_owner": owner,
        }
        _write_provider_auth_reaper_receipt(path, merged)
        return attempt, merged
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _reconcile_lease_from_provider_auth_receipt(
    lease: ProviderAuthLease,
    receipt_path: Path,
) -> ProviderAuthCloseReceipt | None:
    """Refresh stale parent Lease memory from one durable child receipt."""
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != "provider-auth-reaper.v2"
            or payload.get("lease_id") != lease.lease_id
            or Path(str(payload.get("source_home"))).resolve()
            != Path(lease.source_home).resolve()
            or Path(str(payload.get("run_dir"))).resolve()
            != Path(lease.run_dir).resolve()
            or Path(str(payload.get("destination_path"))).resolve()
            != Path(lease.destination_path).resolve()
        ):
            raise IsolationUnavailable(
                "provider auth receipt does not match parent lease identity"
            )
    except (
        IsolationUnavailable,
        OSError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        warn(
            "provider-auth-recovery",
            "cannot refresh stale parent lease from receipt",
            path=str(receipt_path),
            err=str(exc),
        )
        return None
    destination_missing = not Path(lease.destination_path).exists()
    close = payload.get("close")
    if (
        payload.get("state") == "cleaned"
        and isinstance(close, dict)
        and close.get("ok") is True
        and close.get("cleaned") is True
        and destination_missing
    ):
        terminal = ProviderAuthCloseReceipt(
            ok=True,
            reconciled=bool(close.get("reconciled")),
            source_advanced=bool(close.get("source_advanced")),
            cleaned=True,
            reason=str(close.get("reason") or "closed"),
        )
        _close_provider_auth_lock_reference(lease._authority_lock_fd)
        lease._authority_lock_fd = None
        lease._destination_unlinked = True
        lease._terminal_receipt = terminal
        return terminal
    close_phase = payload.get("close_phase")
    lease._destination_unlinked = bool(
        destination_missing
        and close_phase in {"unlink_intent", "destination_unlinked"}
    )
    return None


def wait_for_process_group_generation_drained(
    *,
    pgid: int,
    leader_pid: int,
    leader_started_wall: str | None,
    poll_seconds: float = 1.0,
) -> None:
    """Wait for one exact process-group generation, not a recycled PGID."""
    from . import procutil

    empty_reads = 0
    while empty_reads < 2:
        identity = (
            procutil.check_identity(leader_pid, leader_started_wall)
            if leader_started_wall
            else procutil.IDENTITY_UNVERIFIED
        )
        if identity == procutil.IDENTITY_UNVERIFIED:
            empty_reads = 0
            time.sleep(poll_seconds)
            continue
        # MISMATCH proves the original leader is gone, but a corrupt receipt
        # must never turn that into permission to clean early. The exact PGID
        # still needs two authoritative empty reads.
        members = procutil.pgid_members_checked(pgid)
        if members == []:
            empty_reads += 1
        else:
            empty_reads = 0
        time.sleep(poll_seconds)


def reap_provider_auth_lease_in_process(
    lease: ProviderAuthLease,
    *,
    pgid: int,
    leader_pid: int,
    leader_started_wall: str | None,
    receipt_path: Path | None = None,
    close_retry_seconds: float = 5.0,
) -> ProviderAuthCloseReceipt:
    """Fail-safe custody fallback when detached reaper handoff cannot start."""
    def checkpoint_receipt(payload: dict[str, Any]) -> None:
        if receipt_path is None:
            return
        try:
            _transition_provider_auth_reaper_receipt(
                receipt_path,
                payload,
            )
        except Exception as exc:  # receipt loss must not release live custody
            warn(
                "provider-auth-recovery",
                "synchronous custody receipt failed; cleanup continues held",
                path=str(receipt_path),
                err=str(exc),
            )

    wait_for_process_group_generation_drained(
        pgid=pgid,
        leader_pid=leader_pid,
        leader_started_wall=leader_started_wall,
    )
    attempts = 0
    while True:
        if receipt_path is not None:
            terminal = _reconcile_lease_from_provider_auth_receipt(
                lease, receipt_path,
            )
            if terminal is not None:
                return terminal
            try:
                attempts, claimed = _begin_provider_auth_cleanup_attempt(
                    receipt_path,
                    owner=f"parent:{os.getpid()}",
                )
                if claimed.get("state") == "cleaned":
                    terminal = _reconcile_lease_from_provider_auth_receipt(
                        lease, receipt_path,
                    )
                    if terminal is not None:
                        return terminal
            except Exception as exc:  # parent keeps custody without receipt IO
                warn(
                    "provider-auth-recovery",
                    "cannot claim synchronous cleanup attempt; cleanup held",
                    path=str(receipt_path),
                    err=str(exc),
                )
                attempts += 1
        else:
            attempts += 1
        if receipt_path is not None:
            checkpoint_receipt(
                {"state": "cleanup_started", "attempts": attempts}
            )
        receipt = lease.close(
            checkpoint=(
                None
                if receipt_path is None
                else lambda phase: checkpoint_receipt(
                    {
                        "state": "cleanup_started",
                        "attempts": attempts,
                        "close_phase": phase,
                    },
                )
            ),
        )
        if receipt.ok:
            return receipt
        if receipt_path is not None:
            checkpoint_receipt(
                {
                    "state": "cleanup_retry",
                    "attempts": attempts,
                    "close": {
                        "ok": receipt.ok,
                        "reason": receipt.reason,
                    },
                },
            )
        time.sleep(close_retry_seconds)


def defer_provider_auth_cleanup(
    lease: ProviderAuthLease,
    *,
    pgid: int,
    leader_pid: int,
    leader_started_wall: str,
    receipt_path: Path | None = None,
) -> ProviderAuthHandoffReceipt:
    """Transfer a live descendant's lease to a detached cleanup owner.

    The reaper inherits the already-held authority lock file descriptor, so
    there is no unlock/relock window.  It waits for two independently empty
    process-group reads before reconciling or deleting any credential bytes.
    """
    if (
        pgid <= 1
        or leader_pid <= 1
        or pgid != leader_pid
        or not leader_started_wall
    ):
        raise IsolationUnavailable("provider auth reaper requires a valid PGID")
    lock_fd = lease._authority_lock_fd
    if lock_fd is None:
        raise IsolationUnavailable(
            "provider auth lease has no authority lock to transfer"
        )
    token = secrets.token_hex(12)
    receipt_path = receipt_path or (
        Path.home() / ".volpred" / "logs" / "provider-auth-reapers"
        / f"{token}.json"
    )
    log_path = receipt_path.with_suffix(".log")
    from . import procutil

    parent_started_wall = procutil.get_process_start_wall(os.getpid())
    intent = {
        "schema_version": "provider-auth-reaper.v2",
        "state": "handoff_intent",
        "lease_id": lease.lease_id,
        "source_home": lease.source_home,
        "run_dir": lease.run_dir,
        "destination_path": lease.destination_path,
        "baseline_sha256": lease.baseline_sha256,
        "pgid": pgid,
        "leader_pid": leader_pid,
        "leader_started_wall": leader_started_wall,
        "handoff_parent_pid": os.getpid(),
        "handoff_parent_started_wall": (
            str(parent_started_wall) if parent_started_wall else None
        ),
    }
    _transition_provider_auth_reaper_receipt(receipt_path, intent)
    log_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(log_path.parent, 0o700)
    ack_read_fd, ack_write_fd = os.pipe()
    argv = [
        sys.executable,
        "-m",
        "scripts.dispatch_supervisor.auth_lease_reaper",
        "--pgid",
        str(pgid),
        "--leader-pid",
        str(leader_pid),
        "--leader-started-wall",
        leader_started_wall,
        "--source-home",
        lease.source_home,
        "--run-dir",
        lease.run_dir,
        "--destination-path",
        lease.destination_path,
        "--baseline-sha256",
        lease.baseline_sha256,
        "--lease-id",
        lease.lease_id,
        "--lock-fd",
        str(lock_fd),
        "--ack-fd",
        str(ack_write_fd),
        "--receipt-path",
        str(receipt_path),
    ]
    if lease._destination_unlinked:
        argv.append("--destination-unlinked")
    try:
        with log_path.open("ab", buffering=0) as log_handle:
            proc = subprocess.Popen(
                argv,
                cwd=str(Path(__file__).resolve().parents[2]),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                    "PYTHONUNBUFFERED": "1",
                },
                pass_fds=(lock_fd, ack_write_fd),
                start_new_session=True,
                close_fds=True,
            )
    except Exception as exc:
        os.close(ack_read_fd)
        os.close(ack_write_fd)
        _transition_provider_auth_reaper_receipt(
            receipt_path,
            {**intent, "state": "handoff_failed", "reason": str(exc)},
        )
        raise ProviderAuthHandoffError(
            "cannot start provider auth lease reaper",
            receipt_path=receipt_path,
        ) from exc
    reaper_started_wall = procutil.get_process_start_wall(proc.pid)
    _transition_provider_auth_reaper_receipt(
        receipt_path,
        {
            **intent,
            "reaper_pid": proc.pid,
            "reaper_started_wall": (
                str(reaper_started_wall) if reaper_started_wall else None
            ),
        },
    )
    os.close(ack_write_fd)
    acknowledged = b""
    try:
        try:
            ready, _, _ = select.select([ack_read_fd], [], [], 10.0)
            if ready:
                acknowledged = os.read(ack_read_fd, 64)
        except OSError:
            acknowledged = b""
    finally:
        os.close(ack_read_fd)
    if acknowledged != b"READY\n":
        try:
            proc.terminate()
        except (OSError, ProcessLookupError) as exc:
            warn(
                "provider-auth-recovery",
                "no-ACK reaper TERM failed; retaining parent custody",
                reaper_pid=proc.pid,
                err=str(exc),
            )
        reaped = False
        for _attempt in range(2):
            try:
                proc.wait(timeout=5)
                reaped = True
                break
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except (OSError, ProcessLookupError) as exc:
                    warn(
                        "provider-auth-recovery",
                        "no-ACK reaper KILL failed; quarantining custody",
                        reaper_pid=proc.pid,
                        err=str(exc),
                    )
            except (OSError, ProcessLookupError) as exc:
                warn(
                    "provider-auth-recovery",
                    "no-ACK reaper wait failed; quarantining custody",
                    reaper_pid=proc.pid,
                    err=str(exc),
                )
                break
        next_state = "handoff_failed" if reaped else "quarantined"
        try:
            _transition_provider_auth_reaper_receipt(
                receipt_path,
                {
                    **intent,
                    "state": next_state,
                    "reaper_pid": proc.pid,
                    "reaper_started_wall": (
                        str(reaper_started_wall)
                        if reaper_started_wall
                        else None
                    ),
                    "reason": "reaper did not acknowledge durable custody",
                },
            )
        except Exception as exc:  # custody decision cannot depend on receipt IO
            warn(
                "provider-auth-recovery",
                "no-ACK handoff receipt failed; custody remains in parent",
                reaper_pid=proc.pid,
                err=str(exc),
            )
        if not reaped:
            raise ProviderAuthHandoffQuarantined(
                "provider auth reaper did not acknowledge and could not be "
                "reaped; parent custody quarantined",
                receipt_path=receipt_path,
                reaper_process=proc,
            )
        raise ProviderAuthHandoffError(
            "provider auth lease reaper did not acknowledge custody",
            receipt_path=receipt_path,
        )
    # The child inherited the same open file description and therefore keeps
    # the flock continuously.  Drop only this process's descriptor.
    os.close(lock_fd)
    lease._authority_lock_fd = None
    return ProviderAuthHandoffReceipt(
        reaper_pid=proc.pid,
        pgid=pgid,
        receipt_path=str(receipt_path),
    )


def _provider_auth_reaper_root() -> Path:
    return Path.home() / ".volpred" / "logs" / "provider-auth-reapers"


def _load_recoverable_provider_auth_receipts(
    *,
    source_home: Path,
    receipt_root: Path,
) -> tuple[list[tuple[Path, dict[str, Any], bool]], int]:
    recoverable: list[tuple[Path, dict[str, Any], bool]] = []
    invalid = 0
    if not receipt_root.is_dir():
        return recoverable, invalid
    for path in sorted(receipt_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warn(
                "provider-auth-recovery",
                "receipt unreadable; admission will fail closed",
                path=str(path),
                err=str(exc),
            )
            invalid += 1
            continue
        schema = payload.get("schema_version")
        state = payload.get("state")
        close = payload.get("close")
        if schema == "provider-auth-reaper.v1":
            legacy_run_raw = payload.get("run_dir")
            if (
                not isinstance(legacy_run_raw, str)
                or not Path(legacy_run_raw).is_absolute()
            ):
                invalid += 1
                continue
            legacy_run = Path(legacy_run_raw).resolve()
            legacy_destination = (
                legacy_run / "home" / ".codex" / "auth.json"
            )
            if (
                state == "cleaned"
                and isinstance(close, dict)
                and close.get("ok") is True
                and close.get("cleaned") is True
                and not legacy_destination.exists()
            ):
                continue
            invalid += 1
            continue
        if schema != "provider-auth-reaper.v2":
            invalid += 1
            continue
        try:
            receipt_source = Path(str(payload["source_home"])).resolve()
        except (KeyError, OSError, RuntimeError) as exc:
            warn(
                "provider-auth-recovery",
                "receipt source identity invalid; admission will fail closed",
                path=str(path),
                err=str(exc),
            )
            invalid += 1
            continue
        if receipt_source != source_home.resolve():
            continue
        try:
            run_dir = Path(str(payload["run_dir"])).resolve()
            destination = Path(str(payload["destination_path"])).resolve()
            expected_destination = (
                run_dir / "home" / ".codex" / "auth.json"
            ).resolve()
            pgid = int(payload["pgid"])
            leader_pid = int(payload["leader_pid"])
            leader_started_wall_raw = payload["leader_started_wall"]
            if (
                not isinstance(leader_started_wall_raw, str)
                or not leader_started_wall_raw
            ):
                raise ValueError("leader_started_wall must be a non-empty string")
            leader_started_wall = leader_started_wall_raw
            baseline = str(payload["baseline_sha256"])
            lease_id = str(payload["lease_id"])
        except (
            KeyError,
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
        ) as exc:
            warn(
                "provider-auth-recovery",
                "receipt lease identity invalid; admission will fail closed",
                path=str(path),
                err=str(exc),
            )
            invalid += 1
            continue
        if (
            destination != expected_destination
            or pgid <= 1
            or leader_pid != pgid
            or not leader_started_wall
            or len(baseline) != 64
            or any(char not in "0123456789abcdef" for char in baseline.lower())
            or not lease_id
        ):
            invalid += 1
            continue
        if state == "quarantined":
            try:
                quarantine_pid = int(payload["reaper_pid"])
                quarantine_started_raw = payload["reaper_started_wall"]
                if (
                    not isinstance(quarantine_started_raw, str)
                    or not quarantine_started_raw
                ):
                    raise ValueError(
                        "reaper_started_wall must be a non-empty string"
                    )
                quarantine_started = quarantine_started_raw
                parent_pid = int(payload["handoff_parent_pid"])
                parent_started_raw = payload["handoff_parent_started_wall"]
                if (
                    not isinstance(parent_started_raw, str)
                    or not parent_started_raw
                ):
                    raise ValueError(
                        "handoff_parent_started_wall must be a non-empty string"
                    )
                parent_started = parent_started_raw
            except (KeyError, TypeError, ValueError) as exc:
                warn(
                    "provider-auth-recovery",
                    "quarantine owner identity invalid; admission held",
                    path=str(path),
                    err=str(exc),
                )
                invalid += 1
                continue
            if (
                quarantine_pid <= 1
                or not quarantine_started
                or parent_pid <= 1
                or not parent_started
            ):
                invalid += 1
                continue
        close_phase = payload.get("close_phase")
        destination_missing = not destination.exists()
        if state == "cleaned":
            if (
                not isinstance(close, dict)
                or close.get("ok") is not True
                or close.get("cleaned") is not True
                or not destination_missing
            ):
                invalid += 1
            continue
        if close_phase == "destination_unlinked" and not destination_missing:
            invalid += 1
            continue
        destination_unlinked = close_phase == "destination_unlinked" or (
            close_phase == "unlink_intent" and destination_missing
        )
        if destination_missing and not destination_unlinked:
            invalid += 1
            continue
        recoverable.append((path, payload, destination_unlinked))
    return recoverable, invalid


def _terminate_durable_quarantine_owner(payload: dict[str, Any]) -> bool:
    """PID-generation-safe bounded reap of a no-ACK child after restart."""
    from . import procutil

    if payload.get("state") != "quarantined":
        return False
    pid = int(payload["reaper_pid"])
    started_wall = str(payload["reaper_started_wall"])
    for sig in (signal.SIGTERM, signal.SIGKILL):
        identity = procutil.check_identity(pid, started_wall)
        if identity in {
            procutil.IDENTITY_DEAD,
            procutil.IDENTITY_MISMATCH,
        }:
            return True
        if identity != procutil.IDENTITY_MATCH:
            return False
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            warn(
                "provider-auth-recovery",
                "durable quarantine owner already exited",
                pid=pid,
            )
            return True
        except OSError as exc:
            warn(
                "provider-auth-recovery",
                "durable quarantine owner signal failed",
                pid=pid,
                signal=int(sig),
                err=str(exc),
            )
            return False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            identity = procutil.check_identity(pid, started_wall)
            if identity in {
                procutil.IDENTITY_DEAD,
                procutil.IDENTITY_MISMATCH,
            }:
                return True
            time.sleep(0.1)
    return False


def _recover_provider_auth_with_held_lock(
    *,
    source_home: Path,
    authority_lock_fd: int,
    receipt_root: Path | None = None,
) -> bool:
    """Fence one admission and transfer its held lock to stale cleanup."""
    recoverable, invalid = _load_recoverable_provider_auth_receipts(
        source_home=source_home,
        receipt_root=receipt_root or _provider_auth_reaper_root(),
    )
    if invalid:
        raise IsolationUnavailable(
            f"provider auth recovery has {invalid} invalid nonterminal receipt(s)"
        )
    if len(recoverable) > 1:
        raise IsolationUnavailable(
            "provider auth recovery found multiple nonterminal leases"
        )
    if not recoverable:
        return False
    path, payload, destination_unlinked = recoverable[0]
    lease = ProviderAuthLease(
        source_home=str(source_home),
        run_dir=str(payload["run_dir"]),
        destination_path=str(payload["destination_path"]),
        baseline_sha256=str(payload["baseline_sha256"]),
        lease_id=str(payload["lease_id"]),
        _authority_lock_fd=authority_lock_fd,
        _destination_unlinked=destination_unlinked,
    )
    _transition_provider_auth_reaper_receipt(
        path,
        {"state": "recovery_started"},
    )
    defer_provider_auth_cleanup(
        lease,
        pgid=int(payload["pgid"]),
        leader_pid=int(payload["leader_pid"]),
        leader_started_wall=str(payload["leader_started_wall"]),
        receipt_path=path,
    )
    return True


def recover_provider_auth_reapers(
    *,
    authority_home: Path | None = None,
    receipt_root: Path | None = None,
) -> dict[str, int]:
    """Recover nonterminal cleanup intents after a supervisor/reaper crash."""
    source_home = (authority_home or _credential_home()).resolve()
    root = receipt_root or _provider_auth_reaper_root()
    if (
        authority_home is None
        and receipt_root is None
        and os.environ.get("PYTEST_CURRENT_TEST")
    ):
        return {"recovered": 0, "active": 0, "invalid": 0}
    recovered = 0
    active = 0
    invalid = 0
    recoverable, invalid = _load_recoverable_provider_auth_receipts(
        source_home=source_home,
        receipt_root=root,
    )
    if invalid or len(recoverable) > 1:
        return {
            "recovered": 0,
            "active": 0,
            "invalid": invalid + max(0, len(recoverable) - 1),
        }
    for path, payload, destination_unlinked in recoverable:
        try:
            source_home_fd = _open_directory(source_home)
            try:
                source_dir_fd = _open_child_directory(
                    source_home_fd, ".codex",
                )
                try:
                    try:
                        lock_fd = _acquire_provider_auth_lock(source_dir_fd)
                    except IsolationUnavailable as exc:
                        if "already leased" not in str(exc):
                            raise
                        if _terminate_durable_quarantine_owner(payload):
                            lock_fd = None
                            for _retry in range(20):
                                try:
                                    lock_fd = _acquire_provider_auth_lock(
                                        source_dir_fd
                                    )
                                    break
                                except IsolationUnavailable as retry_exc:
                                    if "already leased" not in str(
                                        retry_exc
                                    ):
                                        raise
                                    time.sleep(0.1)
                            if lock_fd is None:
                                active += 1
                                continue
                        else:
                            active += 1
                            continue
                finally:
                    os.close(source_dir_fd)
            finally:
                os.close(source_home_fd)
            lease = ProviderAuthLease(
                source_home=str(source_home),
                run_dir=str(payload["run_dir"]),
                destination_path=str(payload["destination_path"]),
                baseline_sha256=str(payload["baseline_sha256"]),
                lease_id=str(payload["lease_id"]),
                _authority_lock_fd=lock_fd,
                _destination_unlinked=destination_unlinked,
            )
            try:
                _transition_provider_auth_reaper_receipt(
                    path,
                    {"state": "recovery_started"},
                )
                defer_provider_auth_cleanup(
                    lease,
                    pgid=int(payload["pgid"]),
                    leader_pid=int(payload["leader_pid"]),
                    leader_started_wall=str(payload["leader_started_wall"]),
                    receipt_path=path,
                )
                recovered += 1
            except Exception:
                _release_provider_auth_lock(lease._authority_lock_fd)
                lease._authority_lock_fd = None
                raise
        except (KeyError, TypeError, ValueError, OSError, IsolationUnavailable):
            invalid += 1
    return {"recovered": recovered, "active": active, "invalid": invalid}


def bootstrap_codex_auth_authority(
    *,
    interactive_home: Path | None = None,
    authority_home: Path | None = None,
) -> dict[str, Any]:
    """Enroll same-host subscription OAuth into the single-owner authority.

    This is intentionally an explicit deployment operation, not an automatic
    fire fallback.  It never overwrites an existing authority and must be run
    independently on each Mac after that host's own Codex subscription login.
    """
    source_home = (interactive_home or Path.home()).resolve()
    target_home = (authority_home or _credential_home()).resolve()
    if source_home == target_home:
        raise IsolationUnavailable(
            "interactive and authority credential homes must be distinct"
        )

    source_home_fd = _open_directory(source_home)
    try:
        source_dir_fd = _open_child_directory(source_home_fd, ".codex")
        try:
            payload = _read_private_at(source_dir_fd, "auth.json")
        finally:
            os.close(source_dir_fd)
    finally:
        os.close(source_home_fd)
    _validate_codex_auth(payload)

    target_home.mkdir(parents=True, mode=0o700, exist_ok=True)
    if target_home.is_symlink() or target_home.stat().st_uid != os.getuid():
        raise IsolationUnavailable(
            "Codex credential authority HOME has unsafe identity"
        )
    os.chmod(target_home, 0o700)
    target_home_fd = _open_directory(target_home)
    try:
        target_dir_fd = _open_child_directory(
            target_home_fd,
            ".codex",
            create=True,
        )
        authority_lock_fd: int | None = None
        try:
            authority_lock_fd = _acquire_provider_auth_lock(target_dir_fd)
            try:
                os.stat(
                    "auth.json",
                    dir_fd=target_dir_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                has_existing = False
            else:
                has_existing = True
            if has_existing:
                existing = _read_private_at(target_dir_fd, "auth.json")
                _validate_codex_auth(existing)
                if existing != payload:
                    raise IsolationUnavailable(
                        "Codex credential authority already exists; refusing "
                        "to overwrite or silently import a newer login"
                    )
                return {
                    "ok": True,
                    "action": "already_provisioned",
                    "authority_home": str(target_home),
                }
            _write_private_at(target_dir_fd, "auth.json", payload)
            verified = _read_private_at(target_dir_fd, "auth.json")
            if verified != payload:
                raise IsolationUnavailable(
                    "Codex credential authority enrollment verification failed"
                )
        finally:
            _release_provider_auth_lock(authority_lock_fd)
            os.close(target_dir_fd)
    finally:
        os.close(target_home_fd)
    return {
        "ok": True,
        "action": "provisioned",
        "authority_home": str(target_home),
    }


def materialize_provider_auth(
    prepared: PreparedIsolation | dict[str, Any],
    *,
    provider_id: str,
    credential_home: Path | None = None,
) -> ProviderAuthLease | None:
    """Materialize only the selected provider's subscription credential.

    Codex desktop auth is a rotating OAuth JSON file, not a transferable env
    bearer. Copying only that mode-600 file into the per-fire synthetic HOME
    keeps the CLI logged in without exposing host user config or permitting
    ``CODEX_HOME``/API-key overrides.
    """
    raw = _prepared_payload(prepared)
    if provider_id in {"claude-cli", "agy-cli"}:
        return None
    if provider_id != "codex-cli":
        raise IsolationUnavailable(
            f"unsupported isolated provider identity: {provider_id!r}"
        )
    run_dir = Path(raw["run_dir"]).resolve()
    synthetic_home = Path(raw["synthetic_home"]).resolve()
    if synthetic_home != run_dir / "home":
        raise IsolationUnavailable(
            "synthetic HOME is outside the exact isolation run directory"
        )
    source_home = credential_home or _credential_home()
    authority_lock_fd: int | None = None
    try:
        source_home_fd = _open_directory(source_home)
        try:
            source_dir_fd = _open_child_directory(source_home_fd, ".codex")
            try:
                authority_lock_fd = _acquire_provider_auth_lock(source_dir_fd)
                if _recover_provider_auth_with_held_lock(
                    source_home=Path(source_home),
                    authority_lock_fd=authority_lock_fd,
                ):
                    authority_lock_fd = None
                    raise IsolationUnavailable(
                        "previous provider auth lease recovery is in progress"
                    )
                payload = _read_private_at(source_dir_fd, "auth.json")
            finally:
                os.close(source_dir_fd)
        finally:
            os.close(source_home_fd)
        _validate_codex_auth(payload)
    except Exception:
        _release_provider_auth_lock(authority_lock_fd)
        raise

    try:
        run_dir_fd = _open_directory(run_dir)
        try:
            home_fd = _open_child_directory(run_dir_fd, "home")
            try:
                destination_dir_fd = _open_child_directory(
                    home_fd, ".codex", create=True,
                )
                try:
                    _write_private_at(destination_dir_fd, "auth.json", payload)
                finally:
                    os.close(destination_dir_fd)
            finally:
                os.close(home_fd)
        finally:
            os.close(run_dir_fd)
    except Exception:
        _release_provider_auth_lock(authority_lock_fd)
        raise
    destination = synthetic_home / ".codex" / "auth.json"
    return ProviderAuthLease(
        source_home=str(source_home),
        run_dir=str(run_dir),
        destination_path=str(destination),
        baseline_sha256=hashlib.sha256(payload).hexdigest(),
        _authority_lock_fd=authority_lock_fd,
    )


def isolated_environment(
    base: dict[str, str],
    prepared: PreparedIsolation | dict[str, Any],
    *,
    provider_id: str,
) -> dict[str, str]:
    """Return one provider-scoped child env with external credentials removed."""
    try:
        provider_auth = _PROVIDER_AUTH_ENV[provider_id]
    except KeyError as exc:
        raise IsolationUnavailable(
            f"unsupported isolated provider identity: {provider_id!r}"
        ) from exc
    raw = _prepared_payload(prepared)
    allowed = _PASSTHROUGH_ENV | provider_auth
    env = {
        key: value
        for key, value in base.items()
        if key in allowed or key.startswith("LC_")
    }
    env.update({
        "HOME": raw["synthetic_home"],
        "TMPDIR": raw["tmp_dir"],
        "XDG_CACHE_HOME": str(Path(raw["run_dir"]) / "cache"),
        "XDG_CONFIG_HOME": str(Path(raw["run_dir"]) / "config"),
        "PYTHONPYCACHEPREFIX": raw["pycache_dir"],
        "VOLPRED_ISOLATED_WORKSPACE": raw["workspace"],
        "VOLPRED_CANONICAL_ROOT": raw["canonical_root"],
        "VOLPRED_NO_REMOTE_WRITE": "1",
        "VOLPRED_ISOLATION_PROFILE": raw["profile_path"],
    })
    return env


def wrap_prepared(
    argv: Sequence[str],
    prepared: PreparedIsolation | dict[str, Any],
) -> list[str]:
    raw = prepared.to_dict() if isinstance(prepared, PreparedIsolation) else prepared
    profile = Path(str(raw.get("profile_path") or ""))
    if not profile.is_file():
        raise IsolationUnavailable("prepared sandbox profile is missing")
    return [str(SANDBOX_EXEC), "-f", str(profile), *argv]


def wrap_command(
    argv: Sequence[str],
    *,
    canonical_root: Path,
    workspace: Path,
    job_id: str,
    profile_dir: Path,
) -> tuple[list[str], Path]:
    """Compatibility wrapper; production admission calls :func:`prepare`."""
    prepared = prepare(
        canonical_root=canonical_root,
        workspace=workspace,
        job_id=job_id,
        profile_root=profile_dir,
    )
    return wrap_prepared(argv, prepared), Path(prepared.profile_path)


__all__ = [
    "IsolationUnavailable",
    "PreparedIsolation",
    "ProviderAuthCloseReceipt",
    "ProviderAuthHandoffError",
    "ProviderAuthHandoffQuarantined",
    "ProviderAuthHandoffReceipt",
    "ProviderAuthLease",
    "SANDBOX_EXEC",
    "bootstrap_codex_auth_authority",
    "defer_provider_auth_cleanup",
    "isolated_environment",
    "materialize_provider_auth",
    "prepare",
    "quarantine_provider_auth_lease",
    "reap_quarantined_provider_auth_leases",
    "reap_provider_auth_lease_in_process",
    "recover_provider_auth_reapers",
    "sandbox_profile",
    "wrap_command",
    "wrap_prepared",
]
