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
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


class IsolationUnavailable(RuntimeError):
    """The machine cannot prove the requested workspace boundary."""


class ProviderAuthHandoffError(IsolationUnavailable):
    """Detached cleanup did not acknowledge custody of a durable intent."""

    def __init__(self, message: str, *, receipt_path: Path):
        super().__init__(message)
        self.receipt_path = receipt_path


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

    def close(self) -> ProviderAuthCloseReceipt:
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
            destination_dir_fd = _open_child_directory(
                destination_home_fd, ".codex",
            )
            if not self._destination_unlinked:
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
                os.unlink("auth.json", dir_fd=destination_dir_fd)
                self._destination_unlinked = True
            os.fsync(destination_dir_fd)
            destination_dir_fsynced = True
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
        _release_provider_auth_lock(self._authority_lock_fd)
        self._authority_lock_fd = None
        return self._terminal_receipt


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
        if _REAPER_STATE_ORDER.get(next_state, -1) < _REAPER_STATE_ORDER.get(
            current_state, -1
        ):
            return current
        merged = {**current, **payload}
        _write_provider_auth_reaper_receipt(path, merged)
        return merged
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


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
        if identity == procutil.IDENTITY_MISMATCH:
            # A PID can only be reused after the old process, and therefore
            # its old session-leader identity, has gone away.
            return
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
    close_retry_seconds: float = 5.0,
) -> ProviderAuthCloseReceipt:
    """Fail-safe custody fallback when detached reaper handoff cannot start."""
    wait_for_process_group_generation_drained(
        pgid=pgid,
        leader_pid=leader_pid,
        leader_started_wall=leader_started_wall,
    )
    while True:
        receipt = lease.close()
        if receipt.ok:
            return receipt
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
    if pgid <= 1 or leader_pid <= 1 or not leader_started_wall:
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
        except ProcessLookupError:
            pass  # silent-ok: missing reaper already relinquished child custody
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except ProcessLookupError:
                pass  # silent-ok: reaper exited during TERM-to-KILL race
            proc.wait(timeout=5)
        _transition_provider_auth_reaper_receipt(
            receipt_path,
            {
                **intent,
                "state": "handoff_failed",
                "reaper_pid": proc.pid,
                "reason": "reaper did not acknowledge durable custody",
            },
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


def recover_provider_auth_reapers(
    *,
    authority_home: Path | None = None,
    receipt_root: Path | None = None,
) -> dict[str, int]:
    """Recover nonterminal cleanup intents after a supervisor/reaper crash."""
    source_home = (authority_home or _credential_home()).resolve()
    root = receipt_root or (
        Path.home() / ".volpred" / "logs" / "provider-auth-reapers"
    )
    if (
        authority_home is None
        and receipt_root is None
        and os.environ.get("PYTEST_CURRENT_TEST")
    ):
        return {"recovered": 0, "active": 0, "invalid": 0}
    recovered = 0
    active = 0
    invalid = 0
    if not root.is_dir():
        return {"recovered": 0, "active": 0, "invalid": 0}
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") != "provider-auth-reaper.v2"
                or payload.get("state") == "cleaned"
                or Path(str(payload["source_home"])).resolve() != source_home
            ):
                continue
            source_home_fd = _open_directory(source_home)
            try:
                source_dir_fd = _open_child_directory(
                    source_home_fd, ".codex",
                )
                try:
                    try:
                        lock_fd = _acquire_provider_auth_lock(source_dir_fd)
                    except IsolationUnavailable as exc:
                        if "already leased" in str(exc):
                            active += 1
                            continue
                        raise
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
    "ProviderAuthHandoffReceipt",
    "ProviderAuthLease",
    "SANDBOX_EXEC",
    "bootstrap_codex_auth_authority",
    "defer_provider_auth_cleanup",
    "isolated_environment",
    "materialize_provider_auth",
    "prepare",
    "reap_provider_auth_lease_in_process",
    "recover_provider_auth_reapers",
    "sandbox_profile",
    "wrap_command",
    "wrap_prepared",
]
