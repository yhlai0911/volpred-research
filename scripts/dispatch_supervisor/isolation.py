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

import json
import os
import platform
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


class IsolationUnavailable(RuntimeError):
    """The machine cannot prove the requested workspace boundary."""


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
    branch_rel = Path(branch_ref.removeprefix("refs/heads/"))

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
    """Host credential root; a seam so tests never inspect the real account."""
    return Path.home()


def _read_private_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise IsolationUnavailable(
            f"subscription credential is unavailable: {path}"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise IsolationUnavailable(
                "subscription credential must be a regular file"
            )
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise IsolationUnavailable(
                "subscription credential permissions must be owner-only"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_private_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise IsolationUnavailable(
            "cannot materialize provider subscription credential"
        ) from exc


def materialize_provider_auth(
    prepared: PreparedIsolation | dict[str, Any],
    *,
    provider_id: str,
    credential_home: Path | None = None,
) -> Path | None:
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
    source = (credential_home or _credential_home()) / ".codex" / "auth.json"
    payload = _read_private_file(source)
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
    destination = synthetic_home / ".codex" / "auth.json"
    _write_private_file(destination, payload)
    return destination


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
    "SANDBOX_EXEC",
    "isolated_environment",
    "materialize_provider_auth",
    "prepare",
    "sandbox_profile",
    "wrap_command",
    "wrap_prepared",
]
