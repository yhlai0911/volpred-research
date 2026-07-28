#!/usr/bin/env python3
"""CLI for the single Git-writer transaction lock.

Examples:
  uv run python scripts/git_writer_lock.py run --actor merge-worktree -- \
      bash scripts/merge_worktree.sh agent-name
  uv run python scripts/git_writer_lock.py commit --actor codex-vscode \
      --message '[codex] describe change' -- path/to/a.py path/to/test.py
  uv run python scripts/git_writer_lock.py commit --actor change-delivery \
      --expected-head <full-object-id> --message 'land proposal' -- owned.py
  uv run python scripts/git_writer_lock.py untrack-preserve \
      --actor machine-state-migration --expected-head <full-object-id> \
      --message 'retire runtime state from Git' -- storage/runtime.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]

# This adapter must run under macOS /usr/bin/python3 before uv is available
# (notably merge_worktree.sh).  Import the stdlib-only owner by file location;
# importing ``volpred.ops`` would eagerly import croniter and other app deps.
_OWNER_PATH = ROOT / "src" / "volpred" / "ops" / "git_writer_lock.py"
_SPEC = importlib.util.spec_from_file_location("_volpred_git_writer_lock", _OWNER_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - corrupt install
    raise SystemExit(f"cannot load Git writer lock owner: {_OWNER_PATH}")
_OWNER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _OWNER
_SPEC.loader.exec_module(_OWNER)

DEFAULT_TIMEOUT_S = _OWNER.DEFAULT_TIMEOUT_S
DEFAULT_COMMAND_TIMEOUT_S = _OWNER.DEFAULT_COMMAND_TIMEOUT_S
GitWriterLockError = _OWNER.GitWriterLockError
GitWriterLockTimeout = _OWNER.GitWriterLockTimeout
git_writer_lock = _OWNER.git_writer_lock
run_locked = _OWNER.run_locked
git_writer_lock_path = _OWNER.git_writer_lock_path
git_common_dir = _OWNER.git_common_dir
require_canonical_main_checkout = _OWNER.require_canonical_main_checkout
is_registered_linked_worktree = _OWNER.is_registered_linked_worktree
_inherited_lease = _OWNER._inherited_lease

EX_TEMPFAIL = 75


def _strip_separator(values: list[str]) -> list[str]:
    return values[1:] if values and values[0] == "--" else values


def _repo(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def _normalize_paths(repo: Path, raw_paths: list[str]) -> list[str]:
    """Return deduplicated repo-relative literal file paths.

    A transaction owns files, never a directory or an open-ended pathspec.
    Deleted tracked files are valid even though they no longer exist.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        if not raw or "\0" in raw or raw.startswith(":"):
            raise ValueError(f"unsafe Git transaction path: {raw!r}")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = repo / candidate
        candidate = Path(os.path.abspath(os.path.normpath(candidate)))
        try:
            relative = candidate.relative_to(repo)
        except ValueError as exc:
            raise ValueError(f"path is outside repository: {raw}") from exc
        if relative == Path(".") or candidate.is_dir() or relative.parts[0] == ".git":
            raise ValueError(f"transaction path must name one file: {raw}")
        value = relative.as_posix()
        tracked = subprocess.run(
            ["git", "--literal-pathspecs", "ls-files", "--", value],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if tracked.returncode != 0:
            raise ValueError(f"cannot classify transaction path: {raw}")
        matches = [line for line in tracked.stdout.splitlines() if line]
        if any(match != value for match in matches):
            raise ValueError(f"transaction path expands beyond one file: {raw}")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _git(*args: str) -> list[str]:
    return ["git", "--literal-pathspecs", *args]


def _expected_head(raw: str | None) -> str | None:
    if raw is None:
        return None
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", raw) is None:
        raise ValueError(
            "expected-head must be a full lowercase Git object ID "
            "(40 or 64 hexadecimal characters)"
        )
    return raw


def _expected_content_hashes(
    repo: Path,
    raw_values: list[str],
) -> dict[str, str]:
    """Normalize optional ``PATH=SHA256`` assertions for an exact-path commit."""
    expected: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(
                "expected-content-hash must use PATH=SHA256 syntax"
            )
        raw_path, sha256 = raw.rsplit("=", 1)
        paths = _normalize_paths(repo, [raw_path])
        if len(paths) != 1:
            raise ValueError(
                "expected-content-hash must name exactly one file"
            )
        path = paths[0]
        if path in expected:
            raise ValueError(f"duplicate expected content hash path: {path}")
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError(
                f"expected content hash for {path} must be 64 lowercase "
                "hexadecimal characters"
            )
        expected[path] = sha256
    return expected


def _source_workspace(raw: str | None) -> Path | None:
    if raw is None:
        return None
    source = Path(raw).expanduser()
    if not source.is_absolute():
        raise ValueError("source-workspace must be an absolute path")
    return source.resolve()


def _workspace_dirty_paths(workspace: Path) -> tuple[str, ...]:
    status = subprocess.run(
        _git(
            "-c",
            "core.quotepath=false",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ),
        cwd=workspace,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError("cannot inspect source-workspace Git status")
    entries = status.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ValueError("source-workspace returned an invalid Git status entry")
        state = entry[:2]
        path = entry[3:]
        if "R" in state or "C" in state:
            if index < len(entries):
                index += 1
            raise ValueError("source-workspace rename/copy materialization is unsupported")
        if state[0] not in {" ", "?"}:
            raise ValueError("source-workspace index must be clean")
        if "D" in state:
            raise ValueError("source-workspace deletion materialization is unsupported")
        normalized = _normalize_paths(workspace, [path])
        if len(normalized) != 1:
            raise ValueError("source-workspace dirty path is not one exact file")
        dirty.append(normalized[0])
    if len(dirty) != len(set(dirty)):
        raise ValueError("source-workspace reported duplicate dirty paths")
    return tuple(sorted(dirty))


def _git_blob(repo: Path, revision: str, path: str) -> bytes | None:
    blob = subprocess.run(
        _git("show", f"{revision}:{path}"),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if blob.returncode == 0:
        return blob.stdout
    missing = subprocess.run(
        _git("cat-file", "-e", f"{revision}:{path}"),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if missing.returncode != 0:
        return None
    raise ValueError(f"cannot read canonical base blob: {path}")


def _git_blob_mode(repo: Path, revision: str, path: str) -> str | None:
    tree = subprocess.run(
        _git("ls-tree", "-z", revision, "--", path),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if tree.returncode != 0:
        raise ValueError(f"cannot inspect canonical base Git mode: {path}")
    entries = [entry for entry in tree.stdout.split(b"\0") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise ValueError(f"cannot resolve exact canonical base Git mode: {path}")
    metadata, separator, observed_path = entries[0].partition(b"\t")
    fields = metadata.split()
    if (
        separator != b"\t"
        or observed_path.decode("utf-8", errors="surrogateescape") != path
        or len(fields) != 3
        or fields[1] != b"blob"
    ):
        raise ValueError(f"unsupported canonical base Git entry: {path}")
    return fields[0].decode("ascii")


def _regular_file_git_mode(mode: int) -> str:
    return "100755" if stat.S_IMODE(mode) & 0o111 else "100644"


def _replace_file(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.change-delivery-",
        dir=path.parent,
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:  # silent-ok: os.replace consumed the temp on success.
            pass


def _restore_materialized_paths(
    repo: Path,
    originals: dict[str, tuple[bool, bytes, int]],
) -> None:
    for path, (existed, payload, mode) in originals.items():
        target = repo / path
        if existed:
            _replace_file(target, payload, mode)
        else:
            try:
                target.unlink()
            except FileNotFoundError:  # silent-ok: absent is the exact pre-materialization state being restored.
                pass


def _materialize_candidate_workspace(
    *,
    repo: Path,
    source: Path,
    expected_head: str | None,
    paths: list[str],
    expected_content_hashes: dict[str, str],
) -> dict[str, tuple[bool, bytes, int]]:
    """Copy one immutable candidate into main while the Git writer lease is held.

    Validation happens before the first destination write. Exact candidate
    residue left by a killed prior attempt is accepted, making the operation
    safely restartable; unrelated destination bytes fail closed.
    """
    if expected_head is None:
        raise ValueError("source-workspace materialization requires expected-head")
    if set(expected_content_hashes) != set(paths):
        raise ValueError(
            "source-workspace materialization requires a content hash for every path"
        )
    if not is_registered_linked_worktree(repo, source):
        raise ValueError(
            "source-workspace must be a registered non-main linked worktree"
        )
    source_head = subprocess.run(
        _git("rev-parse", "--verify", "HEAD^{commit}"),
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if source_head.returncode != 0 or source_head.stdout.strip() != expected_head:
        raise ValueError("source-workspace HEAD differs from expected-head")
    if _workspace_dirty_paths(source) != tuple(sorted(paths)):
        raise ValueError(
            "source-workspace dirty paths differ from the complete commit scope"
        )

    candidates: dict[str, tuple[bytes, int]] = {}
    originals: dict[str, tuple[bool, bytes, int]] = {}
    for path in paths:
        candidate = source / path
        if candidate.is_symlink():
            raise ValueError(f"source-workspace path may not be a symlink: {path}")
        try:
            candidate_stat = candidate.stat()
        except OSError as exc:
            raise ValueError(f"cannot inspect source-workspace path {path}: {exc}") from exc
        if not stat.S_ISREG(candidate_stat.st_mode):
            raise ValueError(f"source-workspace path is not a regular file: {path}")
        base_mode = _git_blob_mode(repo, expected_head, path)
        expected_mode = base_mode or "100644"
        if expected_mode not in {"100644", "100755"}:
            raise ValueError(f"unsupported base Git file mode for {path}")
        candidate_mode = _regular_file_git_mode(candidate_stat.st_mode)
        if candidate_mode != expected_mode:
            raise ValueError(
                "Git file mode changes are outside ChangeSet content identity: "
                f"{path}"
            )
        try:
            payload = candidate.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read source-workspace path {path}: {exc}") from exc
        observed_hash = hashlib.sha256(payload).hexdigest()
        if observed_hash != expected_content_hashes[path]:
            raise ValueError(
                f"source content hash drift for {path}: expected "
                f"{expected_content_hashes[path]}, observed {observed_hash}"
            )
        candidates[path] = (payload, stat.S_IMODE(candidate_stat.st_mode))

        target = repo / path
        if target.is_symlink():
            raise ValueError(f"canonical target may not be a symlink: {path}")
        if target.exists():
            try:
                target_stat = target.stat()
                current = target.read_bytes()
            except OSError as exc:
                raise ValueError(f"cannot inspect canonical target {path}: {exc}") from exc
            if not stat.S_ISREG(target_stat.st_mode):
                raise ValueError(f"canonical target is not a regular file: {path}")
            if _regular_file_git_mode(target_stat.st_mode) != expected_mode:
                raise ValueError(
                    f"canonical target has foreign Git file mode: {path}"
                )
            base = _git_blob(repo, expected_head, path)
            if current not in {payload, base}:
                raise ValueError(
                    f"canonical target has foreign working bytes: {path}"
                )
            originals[path] = (
                True,
                current,
                stat.S_IMODE(target_stat.st_mode),
            )
        else:
            if _git_blob(repo, expected_head, path) is not None:
                raise ValueError(
                    f"canonical target has an unowned deletion: {path}"
                )
            originals[path] = (False, b"", 0)

    # Catch source residue added while candidate files were being read.
    if _workspace_dirty_paths(source) != tuple(sorted(paths)):
        raise ValueError("source-workspace changed during materialization preflight")

    try:
        for path in paths:
            payload, mode = candidates[path]
            _replace_file(repo / path, payload, mode)
    except BaseException:
        _restore_materialized_paths(repo, originals)
        raise
    return originals


def _committed_scope(
    repo: Path,
    *,
    base_head: str,
    commit_head: str,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> tuple[str, ...] | None:
    """Return changed paths only when ``commit_head`` is one direct commit.

    ``git commit --only`` builds a temporary index for hooks. A hook can stage a
    foreign path into that temporary index even when the CLI named exact paths,
    so argv alone is not evidence of the resulting commit scope.
    """
    parent = subprocess.run(
        _git("rev-list", "--parents", "-n", "1", commit_head),
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if parent.returncode != 0:
        return None
    if parent.stdout.split() != [commit_head, base_head]:
        return None

    changed = subprocess.run(
        _git(
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            base_head,
            commit_head,
        ),
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if changed.returncode != 0:
        return None
    return tuple(
        path.decode("utf-8", errors="surrogateescape")
        for path in changed.stdout.split(b"\0")
        if path
    )


def _staged_blob_mode(
    repo: Path,
    *,
    path: str,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> str | None:
    entry = subprocess.run(
        _git("ls-files", "--stage", "-z", "--", path),
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if entry.returncode != 0:
        return None
    records = [record for record in entry.stdout.split(b"\0") if record]
    if len(records) != 1:
        return None
    metadata, separator, observed_path = records[0].partition(b"\t")
    fields = metadata.split()
    if (
        separator != b"\t"
        or observed_path.decode("utf-8", errors="surrogateescape") != path
        or len(fields) != 3
        or fields[2] != b"0"
    ):
        return None
    return fields[0].decode("ascii", errors="strict")


def _committed_blob_identity(
    repo: Path,
    *,
    commit_head: str,
    path: str,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> tuple[str, str] | None:
    entry = subprocess.run(
        _git("ls-tree", "-z", commit_head, "--", path),
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if entry.returncode != 0:
        return None
    records = [record for record in entry.stdout.split(b"\0") if record]
    if len(records) != 1:
        return None
    metadata, separator, observed_path = records[0].partition(b"\t")
    fields = metadata.split()
    if (
        separator != b"\t"
        or observed_path.decode("utf-8", errors="surrogateescape") != path
        or len(fields) != 3
        or fields[1] != b"blob"
    ):
        return None
    blob = subprocess.run(
        _git("cat-file", "blob", fields[2].decode("ascii", errors="strict")),
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if blob.returncode != 0:
        return None
    return (
        fields[0].decode("ascii", errors="strict"),
        hashlib.sha256(blob.stdout).hexdigest(),
    )


def _read_regular_working_identity(path: Path) -> tuple[bytes, int]:
    """Read one regular file without following a final-component symlink."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"cannot open runtime path without symlink: {path}") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"runtime path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read()
        return payload, stat.S_IMODE(file_stat.st_mode)
    finally:
        os.close(descriptor)


def _working_identities(
    repo: Path,
    paths: list[str],
) -> dict[str, tuple[bytes, int]]:
    identities: dict[str, tuple[bytes, int]] = {}
    for path in paths:
        target = repo / path
        if target.is_symlink():
            raise ValueError(f"runtime path may not be a symlink: {path}")
        identities[path] = _read_regular_working_identity(target)
    return identities


def _committed_ignore_source(
    repo: Path,
    *,
    revision: str,
    path: str,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> str | None:
    """Return the committed ignore file proving ``path`` is machine-local.

    ``git check-ignore`` normally suppresses tracked paths, so ``--no-index`` is
    required during the ownership migration.  The winning ignore source must
    itself be a repository file whose working bytes equal ``revision``; a local
    global exclude, ``.git/info/exclude``, or an uncommitted rule cannot
    authorize removing a canonical path from Git.
    """

    checked = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", "-z", "--stdin"],
        cwd=repo,
        input=(path + "\0").encode("utf-8", errors="surrogateescape"),
        capture_output=True,
        env=env,
        check=False,
        pass_fds=pass_fds,
    )
    if checked.returncode != 0:
        return None
    fields = checked.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) != 4:
        return None
    raw_source, raw_line, _raw_pattern, raw_path = fields
    if (
        not raw_source
        or not raw_line.isdigit()
        or raw_path.decode("utf-8", errors="surrogateescape") != path
    ):
        return None
    source = Path(raw_source.decode("utf-8", errors="surrogateescape"))
    candidate = source if source.is_absolute() else repo / source
    candidate = Path(os.path.abspath(os.path.normpath(candidate)))
    try:
        relative = candidate.relative_to(repo).as_posix()
    except ValueError:  # silent-ok: external ignore sources are rejected below.
        return None
    if relative == ".gitignore" or relative.endswith("/.gitignore"):
        try:
            current = _read_regular_working_identity(candidate)[0]
        except ValueError:  # silent-ok: unsafe ignore sources cannot authorize migration.
            return None
        committed = _git_blob(repo, revision, relative)
        if committed is not None and current == committed:
            return relative
    return None


def _restore_index_tree(
    repo: Path,
    tree: str,
    *,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> bool:
    restored = subprocess.run(
        _git("read-tree", tree),
        cwd=repo,
        env=env,
        text=True,
        check=False,
        pass_fds=pass_fds,
    )
    return restored.returncode == 0


def _rollback_head(
    repo: Path,
    *,
    original_head: str,
    current_head: str,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
) -> bool:
    rolled_back = subprocess.run(
        _git("update-ref", "HEAD", original_head, current_head),
        cwd=repo,
        env=env,
        text=True,
        check=False,
        pass_fds=pass_fds,
    )
    return rolled_back.returncode == 0


def cmd_run(args: argparse.Namespace) -> int:
    command = _strip_separator(args.command)
    if not command:
        print("[git-writer-lock] run requires a command after --", file=sys.stderr)
        return 2
    proc = run_locked(
        _repo(args.repo),
        command,
        actor=args.actor,
        timeout_s=args.timeout,
        command_timeout_s=args.command_timeout,
    )
    return int(proc.returncode)


def cmd_untrack_preserve(args: argparse.Namespace) -> int:
    """Commit exact tracked deletions while preserving live working files.

    A temporary index derived from HEAD keeps pre-existing staged work out of
    the commit.  Only after the resulting commit has been scope-verified do we
    remove the same exact entries from the caller's real index.  Runtime bytes
    and modes are read before and after the transaction but never written.
    """

    repo = _repo(args.repo)
    expected_head = _expected_head(args.expected_head)
    paths = _normalize_paths(repo, _strip_separator(args.paths))
    if not paths:
        print(
            "[git-writer-lock] untrack-preserve needs explicit file paths",
            file=sys.stderr,
        )
        return 2

    with git_writer_lock(repo, actor=args.actor, timeout_s=args.timeout) as lease:
        require_canonical_main_checkout(repo)
        paths = _normalize_paths(repo, paths)
        env = lease.child_env()
        pass_fds = lease.child_pass_fds()
        text_popen = {
            "env": env,
            "text": True,
            "pass_fds": pass_fds,
        }
        head = subprocess.run(
            _git("rev-parse", "--verify", "HEAD^{commit}"),
            cwd=repo,
            capture_output=True,
            check=False,
            **text_popen,
        )
        if head.returncode != 0:
            print(
                "[git-writer-lock] BLOCKED: cannot resolve current HEAD",
                file=sys.stderr,
            )
            return 2
        original_head = head.stdout.strip()
        if expected_head is not None and original_head != expected_head:
            print(
                "[git-writer-lock] BLOCKED: expected HEAD fence failed: "
                f"expected {expected_head}, observed {original_head}",
                file=sys.stderr,
            )
            return 2

        original_index = subprocess.run(
            _git("write-tree"),
            cwd=repo,
            capture_output=True,
            check=False,
            **text_popen,
        )
        if original_index.returncode != 0:
            print(
                "[git-writer-lock] BLOCKED: cannot snapshot current index",
                file=sys.stderr,
            )
            return int(original_index.returncode)
        original_index_tree = original_index.stdout.strip()

        snapshots = _working_identities(repo, paths)
        for path in paths:
            if _git_blob(repo, original_head, path) is None:
                raise ValueError(f"runtime path is not tracked at HEAD: {path}")
            ignore_source = _committed_ignore_source(
                repo,
                revision=original_head,
                path=path,
                env=env,
                pass_fds=pass_fds,
            )
            if ignore_source is None:
                raise ValueError(
                    "runtime path lacks a committed ignore rule: "
                    f"{path}"
                )

        common_dir = git_common_dir(repo)
        with tempfile.TemporaryDirectory(
            prefix="volpred-untrack-index-",
            dir=common_dir,
        ) as raw_temp_dir:
            alternate_env = env.copy()
            alternate_env["GIT_INDEX_FILE"] = str(
                Path(raw_temp_dir) / "index"
            )
            alternate_popen = {
                "env": alternate_env,
                "text": True,
                "pass_fds": pass_fds,
            }
            seeded = subprocess.run(
                _git("read-tree", original_head),
                cwd=repo,
                check=False,
                **alternate_popen,
            )
            if seeded.returncode != 0:
                return int(seeded.returncode)
            removed = subprocess.run(
                _git("update-index", "--force-remove", "--", *paths),
                cwd=repo,
                check=False,
                **alternate_popen,
            )
            if removed.returncode != 0:
                return int(removed.returncode)
            remaining = subprocess.run(
                _git("ls-files", "-z", "--", *paths),
                cwd=repo,
                capture_output=True,
                env=alternate_env,
                check=False,
                pass_fds=pass_fds,
            )
            if remaining.returncode != 0 or remaining.stdout:
                print(
                    "[git-writer-lock] BLOCKED: temporary index retained "
                    "an untrack target",
                    file=sys.stderr,
                )
                return 2

            commit_cmd = _git("commit")
            if args.message_file:
                commit_cmd += ["-F", args.message_file]
            else:
                commit_cmd += ["-m", args.message]
            commit = subprocess.run(
                commit_cmd,
                cwd=repo,
                check=False,
                **alternate_popen,
            )
            if commit.returncode != 0:
                return int(commit.returncode)

            committed_head = subprocess.run(
                _git("rev-parse", "--verify", "HEAD^{commit}"),
                cwd=repo,
                capture_output=True,
                check=False,
                **alternate_popen,
            )
            if committed_head.returncode != 0:
                print(
                    "[git-writer-lock] ERROR: commit succeeded but HEAD "
                    "cannot be resolved",
                    file=sys.stderr,
                )
                return 1
            new_head = committed_head.stdout.strip()
            scope = _committed_scope(
                repo,
                base_head=original_head,
                commit_head=new_head,
                env=alternate_env,
                pass_fds=pass_fds,
            )
            deleted = all(
                _git_blob(repo, new_head, path) is None for path in paths
            )
            current_snapshots = _working_identities(repo, paths)
            current_index = subprocess.run(
                _git("write-tree"),
                cwd=repo,
                capture_output=True,
                check=False,
                **text_popen,
            )
            real_index_unchanged = (
                current_index.returncode == 0
                and current_index.stdout.strip() == original_index_tree
            )
            if (
                scope is None
                or set(scope) != set(paths)
                or not deleted
                or current_snapshots != snapshots
                or not real_index_unchanged
            ):
                rolled_back = _rollback_head(
                    repo,
                    original_head=original_head,
                    current_head=new_head,
                    env=env,
                    pass_fds=pass_fds,
                )
                restored = _restore_index_tree(
                    repo,
                    original_index_tree,
                    env=env,
                    pass_fds=pass_fds,
                )
                if not rolled_back or not restored:
                    print(
                        "[git-writer-lock] ERROR: untrack verification failed "
                        "and rollback was incomplete",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    "[git-writer-lock] BLOCKED: untrack commit failed exact "
                    "scope, deletion, runtime identity, or index verification",
                    file=sys.stderr,
                )
                return 2

            real_remove = subprocess.run(
                _git("update-index", "--force-remove", "--", *paths),
                cwd=repo,
                check=False,
                **text_popen,
            )
            final_remaining = subprocess.run(
                _git("ls-files", "-z", "--", *paths),
                cwd=repo,
                capture_output=True,
                env=env,
                check=False,
                pass_fds=pass_fds,
            )
            final_snapshots = _working_identities(repo, paths)
            if (
                real_remove.returncode != 0
                or final_remaining.returncode != 0
                or final_remaining.stdout
                or final_snapshots != snapshots
            ):
                rolled_back = _rollback_head(
                    repo,
                    original_head=original_head,
                    current_head=new_head,
                    env=env,
                    pass_fds=pass_fds,
                )
                restored = _restore_index_tree(
                    repo,
                    original_index_tree,
                    env=env,
                    pass_fds=pass_fds,
                )
                if not rolled_back or not restored:
                    print(
                        "[git-writer-lock] ERROR: real-index finalization "
                        "failed and rollback was incomplete",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    "[git-writer-lock] BLOCKED: real-index or runtime "
                    "identity finalization failed",
                    file=sys.stderr,
                )
                return 2

            print(
                "[git-writer-lock] untracked and preserved: "
                + ", ".join(paths)
            )
            return 0


def cmd_commit(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    expected_head = _expected_head(args.expected_head)
    source_workspace = _source_workspace(args.source_workspace)
    paths = _normalize_paths(repo, _strip_separator(args.paths))
    expected_content_hashes = _expected_content_hashes(
        repo,
        args.expected_content_hash,
    )
    if not paths:
        print("[git-writer-lock] commit needs explicit file paths", file=sys.stderr)
        return 2
    if expected_content_hashes and set(expected_content_hashes) != set(paths):
        raise ValueError(
            "expected-content-hash paths must exactly match commit paths"
        )

    with git_writer_lock(repo, actor=args.actor, timeout_s=args.timeout) as lease:
        require_canonical_main_checkout(repo)
        paths = _normalize_paths(repo, paths)
        env = lease.child_env()
        popen = {"env": env, "text": True, "check": False,
                 "pass_fds": lease.child_pass_fds()}
        head = subprocess.run(
            _git("rev-parse", "--verify", "HEAD^{commit}"),
            cwd=repo,
            capture_output=True,
            **popen,
        )
        if head.returncode != 0:
            print(
                "[git-writer-lock] BLOCKED: cannot resolve current HEAD",
                file=sys.stderr,
            )
            return 2
        original_head = head.stdout.strip()
        if expected_head is not None and original_head != expected_head:
            print(
                "[git-writer-lock] BLOCKED: expected HEAD fence failed: "
                f"expected {expected_head}, observed {original_head}",
                file=sys.stderr,
            )
            return 2
        # Preserve the caller's complete index, including unrelated staged
        # changes, so a hook-injected foreign path can be rolled back without
        # taking another writer's staged ownership with it.
        index_tree = subprocess.run(
            _git("write-tree"),
            cwd=repo,
            capture_output=True,
            **popen,
        )
        if index_tree.returncode != 0:
            print(
                "[git-writer-lock] BLOCKED: cannot snapshot current index",
                file=sys.stderr,
            )
            return int(index_tree.returncode)
        original_index_tree = index_tree.stdout.strip()
        # 2026-07-19: an explicitly named but gitignored path (main_v5 era:
        # paper .pdf) made `git add -A` skip it with only an advice hint while
        # the transaction still reported success — the caller believed the file
        # was committed. Naming an ignored path is a caller error; fail loud.
        ignored = [
            p for p in paths
            # plain `git` here: check-ignore rejects --literal-pathspecs magic
            if subprocess.run(["git", "check-ignore", "-q", "--", p], cwd=repo, **popen).returncode == 0
        ]
        if ignored:
            print(
                "[git-writer-lock] BLOCKED: explicitly named path(s) are gitignored "
                f"and would be silently skipped: {ignored}. Drop them or un-ignore.",
                file=sys.stderr,
            )
            return 2
        preflight = subprocess.run(
            _git("diff", "--cached", "--quiet", "--", *paths), cwd=repo, **popen
        )
        if preflight.returncode == 1:
            print(
                "[git-writer-lock] BLOCKED: a target path was already staged; "
                "refusing ambiguous index ownership",
                file=sys.stderr,
            )
            return 2
        if preflight.returncode != 0:
            return int(preflight.returncode)

        index_touched = False
        index_restored = False
        committed = False
        materialized_originals: dict[str, tuple[bool, bytes, int]] | None = None
        try:
            if source_workspace is not None:
                materialized_originals = _materialize_candidate_workspace(
                    repo=repo,
                    source=source_workspace,
                    expected_head=expected_head,
                    paths=paths,
                    expected_content_hashes=expected_content_hashes,
                )
            index_touched = True
            add = subprocess.run(
                _git("add", "-A", "--", *paths), cwd=repo, **popen
            )
            if add.returncode != 0:
                return int(add.returncode)

            staged = subprocess.run(
                _git("diff", "--cached", "--quiet", "--", *paths),
                cwd=repo,
                **popen,
            )
            if staged.returncode == 0:
                print("[git-writer-lock] nothing to commit")
                return 0
            if staged.returncode != 1:
                return int(staged.returncode)

            expected_git_modes: dict[str, str] = {}
            for path, expected_sha256 in expected_content_hashes.items():
                staged_blob = subprocess.run(
                    _git("show", f":{path}"),
                    cwd=repo,
                    capture_output=True,
                    env=env,
                    check=False,
                    pass_fds=lease.child_pass_fds(),
                )
                if staged_blob.returncode != 0:
                    print(
                        "[git-writer-lock] BLOCKED: cannot read staged content "
                        f"for expected hash: {path}",
                        file=sys.stderr,
                    )
                    return 2
                observed_sha256 = hashlib.sha256(staged_blob.stdout).hexdigest()
                if observed_sha256 != expected_sha256:
                    print(
                        "[git-writer-lock] BLOCKED: expected content hash failed "
                        f"for {path}: expected {expected_sha256}, observed "
                        f"{observed_sha256}",
                        file=sys.stderr,
                    )
                    return 2
                staged_mode = _staged_blob_mode(
                    repo,
                    path=path,
                    env=env,
                    pass_fds=lease.child_pass_fds(),
                )
                if staged_mode is None:
                    print(
                        "[git-writer-lock] BLOCKED: cannot read staged Git "
                        f"mode for expected identity: {path}",
                        file=sys.stderr,
                    )
                    return 2
                expected_git_modes[path] = staged_mode

            commit_cmd = _git("commit", "--only")
            if args.message_file:
                commit_cmd += ["-F", args.message_file]
            else:
                commit_cmd += ["-m", args.message]
            commit_cmd += ["--", *paths]
            commit = subprocess.run(commit_cmd, cwd=repo, **popen)
            committed = commit.returncode == 0
            if committed:
                committed_head = subprocess.run(
                    _git("rev-parse", "--verify", "HEAD^{commit}"),
                    cwd=repo,
                    capture_output=True,
                    **popen,
                )
                committed_head_id = committed_head.stdout.strip()
                commit_scope = (
                    _committed_scope(
                        repo,
                        base_head=original_head,
                        commit_head=committed_head_id,
                        env=env,
                        pass_fds=lease.child_pass_fds(),
                    )
                    if committed_head.returncode == 0
                    else None
                )
                unexpected = (
                    sorted(set(commit_scope) - set(paths))
                    if commit_scope is not None
                    else []
                )
                content_mismatches: list[
                    tuple[str, str, str | None]
                ] = []
                mode_mismatches: list[
                    tuple[str, str, str | None]
                ] = []
                if commit_scope is not None:
                    for path, expected_sha256 in (
                        expected_content_hashes.items()
                    ):
                        identity = _committed_blob_identity(
                            repo,
                            commit_head=committed_head_id,
                            path=path,
                            env=env,
                            pass_fds=lease.child_pass_fds(),
                        )
                        observed_mode, observed_sha256 = (
                            identity if identity is not None else (None, None)
                        )
                        if observed_sha256 != expected_sha256:
                            content_mismatches.append(
                                (path, expected_sha256, observed_sha256)
                            )
                        expected_mode = expected_git_modes[path]
                        if observed_mode != expected_mode:
                            mode_mismatches.append(
                                (path, expected_mode, observed_mode)
                            )
                if (
                    commit_scope is None
                    or unexpected
                    or content_mismatches
                    or mode_mismatches
                ):
                    new_head = (
                        committed_head_id
                        if committed_head.returncode == 0
                        else ""
                    )
                    rollback = subprocess.run(
                        _git("update-ref", "HEAD", original_head, new_head),
                        cwd=repo,
                        **popen,
                    )
                    if rollback.returncode != 0:
                        print(
                            "[git-writer-lock] ERROR: commit scope drift detected "
                            "but HEAD CAS rollback failed",
                            file=sys.stderr,
                        )
                        return 1
                    committed = False
                    restore_index = subprocess.run(
                        _git("read-tree", original_index_tree),
                        cwd=repo,
                        **popen,
                    )
                    index_restored = restore_index.returncode == 0
                    if not index_restored:
                        print(
                            "[git-writer-lock] ERROR: commit scope drift was "
                            "rolled back but index restoration failed",
                            file=sys.stderr,
                        )
                        return 1
                    detail = (
                        f"unexpected paths {unexpected}"
                        if unexpected
                        else (
                            "committed content drift for "
                            + ", ".join(
                                f"{path} (expected {expected}, observed "
                                f"{observed or 'missing'})"
                                for path, expected, observed in (
                                    content_mismatches
                                )
                            )
                            if content_mismatches
                            else (
                                "committed mode drift for "
                                + ", ".join(
                                    f"{path} (expected {expected}, observed "
                                    f"{observed or 'missing'})"
                                    for path, expected, observed in (
                                        mode_mismatches
                                    )
                                )
                                if mode_mismatches
                                else "result was not one direct child commit"
                            )
                        )
                    )
                    print(
                        "[git-writer-lock] BLOCKED: commit scope drift after "
                        f"hooks: {detail}",
                        file=sys.stderr,
                    )
                    return 2
                try:
                    head = subprocess.run(
                        _git("rev-parse", "HEAD"),
                        cwd=repo,
                        env=env,
                        text=True,
                        capture_output=True,
                        check=False,
                        pass_fds=lease.child_pass_fds(),
                    )
                    if head.returncode == 0:
                        src = str(ROOT / "src")
                        if src not in sys.path:
                            sys.path.insert(0, src)
                        from volpred.ops.issue_tracker_sync import (
                            settle_completed_task_issues,
                        )
                        from volpred.ops.next_tasks import backfill_ci_repair_commit

                        commit_sha = head.stdout.strip()
                        backfill_ci_repair_commit(
                            path=repo / "storage" / "next_tasks.json",
                            claim_owners={args.actor},
                            commit_sha=commit_sha,
                        )
                        settle_completed_task_issues(
                            path=repo / "storage" / "next_tasks.json",
                            claim_owners={args.actor},
                            commit_sha=commit_sha,
                            commit_parent_sha=original_head,
                            completed_task_ids=set(args.task_id),
                            repo_root=repo,
                        )
                except Exception as exc:  # noqa: BLE001 — commit is durable; later PHASE-Z can retry receipt state
                    print(
                        f"[git-writer-lock] warning: post-commit task settlement failed: {exc}",
                        file=sys.stderr,
                    )
            return int(commit.returncode)
        finally:
            if index_touched and not committed and not index_restored:
                # Preflight proved these entries matched HEAD before we touched
                # them, so exact-path reset restores index ownership while
                # deliberately preserving working-tree bytes.
                subprocess.run(
                    _git("reset", "-q", "HEAD", "--", *paths),
                    cwd=repo,
                    **popen,
                )
            if materialized_originals is not None and not committed:
                _restore_materialized_paths(repo, materialized_originals)


def cmd_validate_inherited(args: argparse.Namespace) -> int:
    """Return success only for a child of the active holder.

    Shell wrappers use this before skipping their outer re-exec.  Merely setting
    an environment variable is insufficient: path and active metadata token
    must match the common-dir sentinel.
    """
    repo = _repo(args.repo)
    path = git_writer_lock_path(repo)
    return 0 if _inherited_lease(path, args.actor) is not None else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command_name", required=True)

    run = sub.add_parser("run", help="run one complete external transaction under the lock")
    run.add_argument("--repo", default=str(ROOT))
    run.add_argument("--actor", required=True)
    run.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    run.add_argument(
        "--command-timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT_S,
        help="maximum foreground command-tree runtime in seconds",
    )
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    commit = sub.add_parser("commit", help="stage and commit exact paths under one lease")
    commit.add_argument("--repo", default=str(ROOT))
    commit.add_argument("--actor", required=True)
    commit.add_argument(
        "--task-id",
        action="append",
        default=[],
        help=(
            "canonical completed task ID bound to this commit; repeat for "
            "multiple tasks"
        ),
    )
    commit.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    commit.add_argument(
        "--expected-head",
        help=(
            "full object ID observed by the caller; fail inside the writer "
            "lease before staging if canonical HEAD has advanced"
        ),
    )
    commit.add_argument(
        "--expected-content-hash",
        action="append",
        default=[],
        metavar="PATH=SHA256",
        help=(
            "optional staged-blob assertion; when present, one value is "
            "required for every exact commit path"
        ),
    )
    commit.add_argument(
        "--source-workspace",
        help=(
            "registered linked worktree whose exact candidate files are copied "
            "and committed inside the same canonical Git-writer lease"
        ),
    )
    message = commit.add_mutually_exclusive_group(required=True)
    message.add_argument("--message")
    message.add_argument("--message-file")
    commit.add_argument("paths", nargs=argparse.REMAINDER)
    commit.set_defaults(func=cmd_commit)

    untrack = sub.add_parser(
        "untrack-preserve",
        help="commit exact tracked deletions while preserving ignored runtime files",
    )
    untrack.add_argument("--repo", default=str(ROOT))
    untrack.add_argument("--actor", required=True)
    untrack.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    untrack.add_argument(
        "--expected-head",
        help=(
            "full object ID observed by the caller; fail inside the writer "
            "lease before building the deletion commit"
        ),
    )
    untrack_message = untrack.add_mutually_exclusive_group(required=True)
    untrack_message.add_argument("--message")
    untrack_message.add_argument("--message-file")
    untrack.add_argument("paths", nargs=argparse.REMAINDER)
    untrack.set_defaults(func=cmd_untrack_preserve)

    validate = sub.add_parser(
        "validate-inherited", help="validate an inherited outer transaction lease"
    )
    validate.add_argument("--repo", default=str(ROOT))
    validate.add_argument("--actor", default="lease-child")
    validate.set_defaults(func=cmd_validate_inherited)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except GitWriterLockTimeout as exc:
        print(f"[git-writer-lock] BUSY: {exc}", file=sys.stderr)
        return EX_TEMPFAIL
    except GitWriterLockError as exc:
        print(f"[git-writer-lock] BLOCKED: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[git-writer-lock] BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
