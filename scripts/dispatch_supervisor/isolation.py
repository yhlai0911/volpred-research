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

import os
import platform
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
        home / ".volpred",
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
    # Exact model-provider credentials only. Broad OPENAI_*/CODEX_* prefixes
    # also contain remote-effect configuration and are intentionally rejected.
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY",
    "CODEX_API_KEY",
})


def isolated_environment(
    base: dict[str, str],
    prepared: PreparedIsolation | dict[str, Any],
) -> dict[str, str]:
    """Return the child env with non-model external credentials removed."""
    raw = (
        prepared.to_dict()
        if isinstance(prepared, PreparedIsolation)
        else {str(k): str(v) for k, v in prepared.items()}
    )
    env = {
        key: value
        for key, value in base.items()
        if key in _PASSTHROUGH_ENV or key.startswith("LC_")
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
    "prepare",
    "sandbox_profile",
    "wrap_command",
    "wrap_prepared",
]
