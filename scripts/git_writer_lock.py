#!/usr/bin/env python3
"""CLI for the single Git-writer transaction lock.

Examples:
  uv run python scripts/git_writer_lock.py run --actor merge-worktree -- \
      bash scripts/merge_worktree.sh agent-name
  uv run python scripts/git_writer_lock.py commit --actor codex-vscode \
      --message '[codex] describe change' -- path/to/a.py path/to/test.py
  uv run python scripts/git_writer_lock.py commit --actor change-delivery \
      --expected-head <full-object-id> --message 'land proposal' -- owned.py
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
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


def cmd_commit(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    expected_head = _expected_head(args.expected_head)
    paths = _normalize_paths(repo, _strip_separator(args.paths))
    if not paths:
        print("[git-writer-lock] commit needs explicit file paths", file=sys.stderr)
        return 2

    with git_writer_lock(repo, actor=args.actor, timeout_s=args.timeout) as lease:
        require_canonical_main_checkout(repo)
        paths = _normalize_paths(repo, paths)
        env = lease.child_env()
        popen = {"env": env, "text": True, "check": False,
                 "pass_fds": lease.child_pass_fds()}
        if expected_head is not None:
            head = subprocess.run(
                _git("rev-parse", "--verify", "HEAD^{commit}"),
                cwd=repo,
                capture_output=True,
                **popen,
            )
            if head.returncode != 0:
                print(
                    "[git-writer-lock] BLOCKED: cannot resolve current HEAD for "
                    "expected HEAD fence",
                    file=sys.stderr,
                )
                return 2
            observed_head = head.stdout.strip()
            if observed_head != expected_head:
                print(
                    "[git-writer-lock] BLOCKED: expected HEAD fence failed: "
                    f"expected {expected_head}, observed {observed_head}",
                    file=sys.stderr,
                )
                return 2
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
        committed = False
        try:
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

            commit_cmd = _git("commit", "--only")
            if args.message_file:
                commit_cmd += ["-F", args.message_file]
            else:
                commit_cmd += ["-m", args.message]
            commit_cmd += ["--", *paths]
            commit = subprocess.run(commit_cmd, cwd=repo, **popen)
            committed = commit.returncode == 0
            if committed:
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
                        from volpred.ops.next_tasks import backfill_ci_repair_commit

                        backfill_ci_repair_commit(
                            path=repo / "storage" / "next_tasks.json",
                            claim_owners={args.actor},
                            commit_sha=head.stdout.strip(),
                        )
                except Exception as exc:  # noqa: BLE001 — commit is durable; later PHASE-Z can retry receipt state
                    print(
                        f"[git-writer-lock] warning: CI repair receipt backfill failed: {exc}",
                        file=sys.stderr,
                    )
            return int(commit.returncode)
        finally:
            if index_touched and not committed:
                # Preflight proved these entries matched HEAD before we touched
                # them, so exact-path reset restores index ownership while
                # deliberately preserving working-tree bytes.
                subprocess.run(
                    _git("reset", "-q", "HEAD", "--", *paths),
                    cwd=repo,
                    **popen,
                )


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
    commit.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    commit.add_argument(
        "--expected-head",
        help=(
            "full object ID observed by the caller; fail inside the writer "
            "lease before staging if canonical HEAD has advanced"
        ),
    )
    message = commit.add_mutually_exclusive_group(required=True)
    message.add_argument("--message")
    message.add_argument("--message-file")
    commit.add_argument("paths", nargs=argparse.REMAINDER)
    commit.set_defaults(func=cmd_commit)

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
