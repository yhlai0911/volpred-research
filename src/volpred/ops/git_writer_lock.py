"""One cross-process transaction lock for Git writes in this repository.

The live checkout has several legitimate writers (dispatch PHASE-Z, scheduled
writers, the orphan reaper, worktree integration, and interactive Codex/Claude
sessions).  Git's own ``index.lock`` protects one low-level index update; it
does not serialize a higher-level transaction such as
``status -> stash -> merge -> stash pop``.  The direct producer of the
2026-06-28 AUTO_MERGE was an unresolved ``stash pop/apply`` conflict; multiple
writers sharing one checkout made that multi-step transaction unsafe.

This owner deliberately lives in the *common* Git directory.  Linked
worktrees have different per-worktree git dirs but share one common dir, so a
lock under ``<common-dir>/volpred-git-writer.lock`` is the only path every
writer can agree on.  The sentinel is never unlinked or replaced: replacing a
flocked inode would split one lock into two independent locks.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

LOCK_BASENAME = "volpred-git-writer.lock"
LOCK_TOKEN_ENV = "VOLPRED_GIT_WRITER_LOCK_TOKEN"
LOCK_PATH_ENV = "VOLPRED_GIT_WRITER_LOCK_PATH"
LOCK_FD_ENV = "VOLPRED_GIT_WRITER_LOCK_FD"
LOCK_CAP_FD_ENV = "VOLPRED_GIT_WRITER_CAP_FD"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_POLL_S = 0.05
DEFAULT_COMMAND_TIMEOUT_S = 3600.0


class GitWriterLockError(RuntimeError):
    """The shared Git transaction lock could not be established safely."""


class GitWriterLockTimeout(GitWriterLockError):
    """Another writer retained the lock beyond this writer's bounded wait."""


@dataclass(frozen=True)
class GitWriterLease:
    path: Path
    actor: str
    token: str
    inherited: bool = False
    fd: int | None = None
    capability_fd: int | None = None
    holder_pid: int = 0

    def child_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base is None else base)
        env[LOCK_TOKEN_ENV] = self.token
        env[LOCK_PATH_ENV] = str(self.path)
        if self.fd is not None:
            env[LOCK_FD_ENV] = str(self.fd)
        if self.capability_fd is not None:
            env[LOCK_CAP_FD_ENV] = str(self.capability_fd)
        return env

    def child_pass_fds(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                fd for fd in (self.fd, self.capability_fd) if fd is not None
            )
        )


_CURRENT_LEASE: ContextVar[GitWriterLease | None] = ContextVar(
    "volpred_git_writer_lease", default=None
)


def _clear_lease_after_fork() -> None:
    """A forked child may not impersonate the Python lock holder."""
    _CURRENT_LEASE.set(None)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_clear_lease_after_fork)


def git_writer_subprocess_kwargs(
    base_env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return env/pass_fds that keep the active lease alive in a child.

    Direct API callers must apply these kwargs to every subprocess launched
    inside a transaction.  If the Python parent is SIGKILLed mid-command, the
    child retains the same kernel lock FD until its Git mutation finishes.
    """
    lease = _CURRENT_LEASE.get()
    if lease is None or lease.holder_pid != os.getpid():
        return {"env": base_env} if base_env is not None else {}
    return {
        "env": lease.child_env(base_env),
        "pass_fds": lease.child_pass_fds(),
    }


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitWriterLockError(f"cannot resolve Git metadata: {exc}") from exc


def git_common_dir(repo_root: Path) -> Path:
    """Return Git's absolute common dir; never guess from ``repo/.git``."""
    root = Path(repo_root).resolve()
    proc = _run_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        detail = (proc.stderr or proc.stdout or "not a git repository").strip()
        raise GitWriterLockError(f"git common-dir probe failed: {detail[:300]}")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_dir():
        raise GitWriterLockError(f"git common dir is not a directory: {path}")
    return path


def git_writer_lock_path(repo_root: Path) -> Path:
    return git_common_dir(repo_root) / LOCK_BASENAME


def require_canonical_main_checkout(repo_root: Path) -> None:
    """Fail unless ``repo_root`` is the canonical checkout on symbolic main.

    A lease serializes writers; it does not decide which ref a writer should
    advance.  Every owner that publishes to the shared checkout must make this
    branch invariant explicit before touching its index or refs.
    """
    root = Path(repo_root).resolve()
    top = _run_git(root, "rev-parse", "--path-format=absolute", "--show-toplevel")
    symbolic = _run_git(root, "symbolic-ref", "-q", "HEAD")
    expected_root = git_common_dir(root).parent.resolve()
    actual = (
        Path((top.stdout or "").strip()).resolve()
        if top.returncode == 0 and (top.stdout or "").strip()
        else None
    )
    if (
        actual != expected_root
        or symbolic.returncode != 0
        or (symbolic.stdout or "").strip() != "refs/heads/main"
    ):
        raise GitWriterLockError(
            "canonical Git writer requires the main checkout with "
            "symbolic HEAD=refs/heads/main"
        )


def _read_metadata(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):  # silent-ok: unreadable metadata is empty evidence and every lease validator fails closed.
        return {}
    return data if isinstance(data, dict) else {}


def _inherited_lease(path: Path, actor: str) -> GitWriterLease | None:
    """Recognise a child of the current lock holder without reacquiring.

    The token is diagnostic/cooperative, not a security boundary.  It prevents
    a wrapper such as ``merge_worktree.sh`` from deadlocking when one of its
    descendants uses the same canonical helper.  First-party writers are also
    statically ratcheted by the lock regression suite.
    """
    token = os.environ.get(LOCK_TOKEN_ENV, "")
    declared_path = os.environ.get(LOCK_PATH_ENV, "")
    declared_fd = os.environ.get(LOCK_FD_ENV, "")
    declared_cap_fd = os.environ.get(LOCK_CAP_FD_ENV, "")
    if not token or not declared_path or not declared_fd or not declared_cap_fd:
        return None
    try:
        same_path = Path(declared_path).resolve() == path.resolve()
        fd = int(declared_fd)
        capability_fd = int(declared_cap_fd)
        opened = os.fstat(fd)
        capability = os.fstat(capability_fd)
        current = path.stat()
        same_inode = (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
    except (OSError, ValueError):  # silent-ok: invalid inherited descriptors simply refuse the inherited-lease path.
        return None
    metadata = _read_metadata(path)
    if (
        not same_path
        or not same_inode
        or metadata.get("state") != "held"
        or metadata.get("token") != token
        or metadata.get("capability_dev") != capability.st_dev
        or metadata.get("capability_ino") != capability.st_ino
    ):
        return None
    probe_fd: int | None = None
    try:
        # First prove that the kernel lock was already occupied.  Calling
        # flock() only on ``fd`` is insufficient: after a holder crash, a
        # separately opened fd could acquire an otherwise stale metadata token.
        probe_fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:  # silent-ok: EWOULDBLOCK is the positive proof that an active holder owns the flock.
            pass
        else:
            fcntl.flock(probe_fd, fcntl.LOCK_UN)
            return None
        finally:
            os.close(probe_fd)
            probe_fd = None

        # Idempotent for the inherited open-file-description.  A separately
        # opened FD with a copied token is blocked by the already-proven holder.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):  # silent-ok: any flock/probe failure refuses inherited authority.
        return None
    metadata_after = _read_metadata(path)
    if (
        metadata_after.get("state") != "held"
        or metadata_after.get("token") != token
        or metadata_after.get("capability_dev") != capability.st_dev
        or metadata_after.get("capability_ino") != capability.st_ino
    ):
        return None
    return GitWriterLease(
        path=path,
        actor=actor,
        token=token,
        inherited=True,
        fd=fd,
        capability_fd=capability_fd,
        holder_pid=os.getpid(),
    )


@contextmanager
def git_writer_lock(
    repo_root: Path,
    *,
    actor: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
) -> Iterator[GitWriterLease]:
    """Acquire the repo-wide Git transaction lock with a bounded wait.

    Failure is always fail-closed: the caller receives an exception and must
    leave HEAD/index/working bytes untouched.  ``flock`` releases on process
    exit, so a crashed writer cannot create a stale ownership claim.
    """
    if not str(actor).strip():
        raise ValueError("git writer actor must be non-empty")
    if not math.isfinite(timeout_s) or timeout_s < 0:
        raise ValueError("timeout_s must be finite and non-negative")
    if not math.isfinite(poll_s) or poll_s <= 0:
        raise ValueError("poll_s must be finite and positive")

    path = git_writer_lock_path(Path(repo_root))
    current_lease = _CURRENT_LEASE.get()
    if (
        current_lease is not None
        and current_lease.holder_pid == os.getpid()
        and current_lease.path.resolve() == path.resolve()
    ):
        # Same-process composition borrows the existing open file description.
        # Forked children cannot enter here: the PID is process-bound and the
        # copied ContextVar is cleared by register_at_fork.
        yield current_lease
        return

    inherited = _inherited_lease(path, actor)
    if inherited is not None:
        context_token = _CURRENT_LEASE.set(inherited)
        try:
            yield inherited
        finally:
            _CURRENT_LEASE.reset(context_token)
        return

    # Create once with owner-only permissions. It is intentionally never
    # removed; fchmod also repairs a sentinel created by an older permissive
    # umask without replacing its inode.
    fd: int | None = None
    capability_fd: int | None = None
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "r+", encoding="utf-8")
    except OSError as exc:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:  # silent-ok: best-effort cleanup preserves the primary sentinel-open exception.
                pass
        raise GitWriterLockError(f"cannot open Git writer sentinel {path}: {exc}") from exc
    deadline = time.monotonic() + timeout_s
    acquired = False
    holder_pid = os.getpid()
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    owner = _read_metadata(path)
                    raise GitWriterLockTimeout(
                        f"git writer lock busy after {timeout_s:.2f}s; "
                        f"owner={owner.get('actor', '<unknown>')} "
                        f"pid={owner.get('pid', '<unknown>')}"
                    )
                time.sleep(max(poll_s, 0.001))

        # A cleanup process must never replace the stable lock inode. Detect a
        # replacement between open() and flock() before trusting the lease.
        opened = os.fstat(handle.fileno())
        current = path.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise GitWriterLockError(f"git writer lockfile was replaced: {path}")

        token = uuid.uuid4().hex
        capability_fd, capability_write_fd = os.pipe()
        os.close(capability_write_fd)
        os.set_inheritable(capability_fd, True)
        capability = os.fstat(capability_fd)
        metadata = {
            "version": 2,
            "state": "held",
            "actor": actor,
            "pid": os.getpid(),
            "token": token,
            "capability_dev": capability.st_dev,
            "capability_ino": capability.st_ino,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        handle.seek(0)
        handle.truncate()
        json.dump(metadata, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

        lease = GitWriterLease(
            path=path,
            actor=actor,
            token=token,
            fd=handle.fileno(),
            capability_fd=capability_fd,
            holder_pid=holder_pid,
        )
        context_token = _CURRENT_LEASE.set(lease)
        try:
            yield lease
        finally:
            _CURRENT_LEASE.reset(context_token)
    finally:
        try:
            if acquired and os.getpid() == holder_pid:
                handle.seek(0)
                handle.truncate()
                json.dump(
                    {
                        "version": 1,
                        "state": "released",
                        "actor": actor,
                        "pid": os.getpid(),
                        "released_at": datetime.now(timezone.utc).isoformat(),
                    },
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            # Do not issue an explicit LOCK_UN.  A managed child receives this
            # same open file description; closing the parent's copy keeps the
            # lease alive if the parent is killed while the child finishes its
            # Git command.  The kernel releases it when the final copy closes.
            handle.close()
            if capability_fd is not None:
                try:
                    os.close(capability_fd)
                except OSError:  # silent-ok: process teardown will close an already-invalid capability descriptor.
                    pass


def run_locked(
    repo_root: Path,
    command: Sequence[str],
    *,
    actor: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> subprocess.CompletedProcess[str]:
    """Run one foreground process tree under the shared lease.

    The command gets a dedicated session.  Once its foreground leader exits,
    background descendants are terminated before release; otherwise ``cmd &``
    could retain the inherited lock FD while metadata said ``released``.
    """
    if not command:
        raise ValueError("locked command must not be empty")
    if not math.isfinite(command_timeout_s) or command_timeout_s <= 0:
        raise ValueError("command_timeout_s must be finite and positive")
    with git_writer_lock(repo_root, actor=actor, timeout_s=timeout_s):
        proc = subprocess.Popen(
            list(command),
            cwd=str(Path(repo_root).resolve()),
            **git_writer_subprocess_kwargs(),
            text=True,
            start_new_session=True,
        )
        timed_out = False
        forwarded_signal = 0
        previous_handlers: dict[int, object] = {}

        def _forward(signum: int, _frame: object) -> None:
            nonlocal forwarded_signal
            forwarded_signal = signum
            try:
                os.killpg(proc.pid, signum)
            except (ProcessLookupError, PermissionError):  # silent-ok: forwarding races with exit; bounded group cleanup still runs before lease release.
                pass

        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _forward)
        try:
            returncode = proc.wait(timeout=command_timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(proc.pid)
            proc.wait(timeout=5)
            returncode = 124
        finally:
            if not timed_out:
                _terminate_process_group(proc.pid)
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
        if forwarded_signal:
            returncode = 128 + forwarded_signal
        return subprocess.CompletedProcess(list(command), returncode)


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:  # silent-ok: ESRCH is the expected negative liveness result.
        return False
    except PermissionError:  # silent-ok: an unprobeable group is conservatively treated as alive.
        return True
    return True


def _terminate_process_group(pgid: int) -> None:
    """Bound cleanup for descendants accidentally left by ``run_locked``."""
    if not _process_group_exists(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:  # silent-ok: the process group exited between the liveness probe and TERM.
        return
    deadline = time.monotonic() + 1.0
    while _process_group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _process_group_exists(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # silent-ok: final KILL may race with exit; inherited descriptors keep any survivor serialized.
            pass


def is_registered_linked_worktree(repo_root: Path, workdir: Path) -> bool:
    """True only for a registered, non-main worktree sharing this repo."""
    root = Path(repo_root).resolve()
    candidate = Path(workdir).resolve()
    if candidate == root or not candidate.is_dir():
        return False
    try:
        if git_common_dir(candidate) != git_common_dir(root):
            return False
    except GitWriterLockError:  # silent-ok: inability to prove common-dir identity rejects linked-worktree registration.
        return False
    top = _run_git(candidate, "rev-parse", "--show-toplevel")
    branch = _run_git(candidate, "rev-parse", "--abbrev-ref", "HEAD")
    if top.returncode != 0 or Path((top.stdout or "").strip()).resolve() != candidate:
        return False
    if branch.returncode != 0 or (branch.stdout or "").strip() in {"", "HEAD", "main"}:
        return False
    listed = _run_git(root, "worktree", "list", "--porcelain")
    if listed.returncode != 0:
        return False
    registered = {
        Path(line.removeprefix("worktree ")).resolve()
        for line in (listed.stdout or "").splitlines()
        if line.startswith("worktree ")
    }
    return candidate in registered
