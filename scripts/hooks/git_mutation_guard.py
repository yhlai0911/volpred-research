#!/usr/bin/env python3
"""Classify Bash text that could mutate the canonical shared Git checkout.

Exit contract for the Claude PreToolUse hook:

* 0: deny (a Git mutation targets the canonical checkout/common dir)
* 10: allow (no such mutation was found)
* 20: indeterminate candidate (fail closed and ask for an explicit target)

The helper only lexes text and runs read-only ``git rev-parse`` probes.  It
never evaluates shell expansions or executes the submitted command.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Sequence

from commit_message_guard import (
    ParseIndeterminate,
    _command_argv,
    _mask_heredoc_bodies,
    _remove_line_continuations,
    _segments,
    _strip_shell_comments,
)


DENY = 0
ALLOW = 10
INDETERMINATE = 20
GIT = "/usr/bin/git"
DIRECT_MUTATORS = {
    "add", "am", "apply", "checkout", "checkout-index", "cherry-pick",
    "clean", "commit", "init", "merge", "mv", "pull", "read-tree",
    "rebase", "reset", "restore", "revert", "rm", "stage", "stash", "switch",
    "update-index", "update-ref", "mergetool",
}
WORKTREE_MUTATORS = {"add", "lock", "move", "prune", "remove", "repair", "unlock"}
SPECIAL_MUTATORS = {"bisect", "branch", "config", "notes", "replace", "sparse-checkout", "submodule", "symbolic-ref", "tag", "worktree"}
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
_RAW_CANDIDATE = re.compile(
    r"\bgit\b[\s\S]*\b(?:" + "|".join(sorted(DIRECT_MUTATORS | SPECIAL_MUTATORS)) + r")\b"
)


def _dynamic(value: str) -> bool:
    return any(mark in value for mark in ("$", "`"))


def _resolve(base: Path, value: str) -> Path | None:
    if not value or _dynamic(value):
        return None
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _probe(args: Sequence[str], cwd: Path) -> tuple[Path | None, Path | None]:
    def run(kind: str) -> Path | None:
        try:
            proc = subprocess.run(
                [GIT, *args, "rev-parse", "--path-format=absolute", kind],
                cwd=str(cwd), capture_output=True, text=True, timeout=5, check=False,
            )
        except OSError:  # silent-ok: an unavailable read-only identity probe yields unknown identity; callers retain fail-closed handling.
            return None
        value = (proc.stdout or "").strip()
        return Path(value).resolve() if proc.returncode == 0 and value else None

    return run("--show-toplevel"), run("--git-common-dir")


def _git_builtin(subcommand: str) -> bool | None:
    """Return whether Git owns the command; aliases cannot shadow builtins."""
    try:
        proc = subprocess.run(
            [GIT, "--list-cmds=builtins"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # silent-ok: inability to enumerate builtins is an indeterminate, fail-closed classification.
        return None
    if proc.returncode != 0:
        return None
    return subcommand in (proc.stdout or "").split()


def _inline_alias_assignment(value: str) -> tuple[str, str] | None:
    key, separator, body = value.partition("=")
    if not separator or not key.casefold().startswith("alias."):
        return None
    name = key[6:].casefold()
    return (name, body) if name else None


def _effective_alias(
    subcommand: str,
    *,
    probe_args: Sequence[str],
    cwd: Path,
    inline_aliases: dict[str, str],
    dynamic_aliases: set[str],
) -> tuple[bool, str | None]:
    """Return (defined, body); body=None means lookup is indeterminate."""
    name = subcommand.casefold()
    if name in dynamic_aliases:
        return True, None
    if name in inline_aliases:
        return True, inline_aliases[name]
    try:
        proc = subprocess.run(
            [GIT, *probe_args, "config", "--get", f"alias.{subcommand}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):  # silent-ok: alias lookup failure is represented as defined-but-unknown and denied by the caller.
        return True, None
    if proc.returncode == 1:
        return False, None
    if proc.returncode != 0:
        return True, None
    return True, (proc.stdout or "").rstrip("\n")


def _config_mutates(args: Sequence[str]) -> bool:
    positional = [token for token in args if not token.startswith("-")]
    protected_key = any(
        token.lower() in {"core.hookspath", "core.repositoryformatversion"}
        for token in positional
    )
    if protected_key and (
        len(positional) >= 2
        or any(token in {"--add", "--replace-all", "--unset", "--unset-all"} for token in args)
    ):
        return True
    if any(token in {"--global", "--system"} for token in args):
        return False
    if any(token in {"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section"} for token in args):
        return True
    return len(positional) >= 2


def _protected_config_mutates(args: Sequence[str]) -> bool:
    positional = [token for token in args if not token.startswith("-")]
    return any(
        token.lower() in {"core.hookspath", "core.repositoryformatversion"}
        for token in positional
    ) and (
        len(positional) >= 2
        or any(token in {"--add", "--replace-all", "--unset", "--unset-all"} for token in args)
    )


def _branch_mutates(args: Sequence[str]) -> bool:
    if any(token in {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "--edit-description", "--set-upstream-to", "--unset-upstream"} for token in args):
        return True
    positional = [token for token in args if not token.startswith("-")]
    return bool(positional) and "--list" not in args and "--show-current" not in args


def _tag_mutates(args: Sequence[str]) -> bool:
    if any(token in {"-d", "--delete", "-f", "--force"} for token in args):
        return True
    positional = [token for token in args if not token.startswith("-")]
    return bool(positional) and "--list" not in args


def _is_mutation(subcommand: str, args: Sequence[str]) -> tuple[bool, bool]:
    """Return (mutates, common-dir-wide)."""
    if subcommand in DIRECT_MUTATORS:
        return True, False
    if subcommand == "worktree":
        action = next((token for token in args if not token.startswith("-")), "")
        return action in WORKTREE_MUTATORS, True
    if subcommand == "config":
        return _config_mutates(args), True
    if subcommand == "branch":
        return _branch_mutates(args), True
    if subcommand == "tag":
        return _tag_mutates(args), True
    if subcommand == "symbolic-ref":
        positional = [token for token in args if not token.startswith("-")]
        return ("--delete" in args or len(positional) >= 2), True
    action = next((token for token in args if not token.startswith("-")), "")
    if subcommand == "sparse-checkout":
        return action in {"add", "disable", "init", "reapply", "set"}, False
    if subcommand == "bisect":
        return action not in {"", "log", "visualize", "view"}, False
    if subcommand == "notes":
        return action in {"add", "append", "copy", "edit", "merge", "prune", "remove"}, True
    if subcommand == "replace":
        return bool(args) and "--list" not in args, True
    if subcommand == "submodule":
        return action not in {"", "status", "summary"}, False
    return False, False


def _command_mutation(
    subcommand: str,
    args: Sequence[str],
    *,
    probe_args: Sequence[str],
    cwd: Path,
    inline_aliases: dict[str, str],
    dynamic_aliases: set[str],
    seen: frozenset[str] = frozenset(),
) -> tuple[bool, bool, bool]:
    """Return (mutates, common-dir-wide, indeterminate), expanding aliases."""
    mutates, common_wide = _is_mutation(subcommand, args)
    if mutates:
        return True, common_wide, False

    builtin = _git_builtin(subcommand)
    if builtin is None:
        return False, False, True
    if builtin:
        return False, False, False

    name = subcommand.casefold()
    if name in seen or len(seen) >= 8:
        return False, False, True
    defined, body = _effective_alias(
        subcommand,
        probe_args=probe_args,
        cwd=cwd,
        inline_aliases=inline_aliases,
        dynamic_aliases=dynamic_aliases,
    )
    if not defined:
        # Preserve the existing treatment of external `git-foo` commands.  The
        # alias-specific ratchet only claims commands whose alias is observable.
        return False, False, False
    if body is None or not body.strip() or _dynamic(body):
        return False, False, True
    if body.lstrip().startswith("!"):
        # Shell aliases can contain pipelines, nested Git commands, and their
        # own path selection.  Do not attempt partial shell interpretation.
        return False, False, True
    try:
        expanded = shlex.split(body, posix=True)
    except ValueError:  # silent-ok: malformed alias text is explicitly indeterminate and denied by the hook.
        return False, False, True
    if not expanded or expanded[0].startswith("-"):
        return False, False, True
    return _command_mutation(
        expanded[0],
        [*expanded[1:], *args],
        probe_args=probe_args,
        cwd=cwd,
        inline_aliases=inline_aliases,
        dynamic_aliases=dynamic_aliases,
        seen=seen | {name},
    )


def _env_context(segment: Sequence[str], git_index: int, cwd: Path) -> tuple[Path | None, dict[str, str]]:
    target_cwd: Path | None = cwd
    values: dict[str, str] = {}
    i = 0
    while i < git_index:
        token = segment[i]
        match = _ASSIGNMENT.match(token)
        if match and match.group(1) in {"GIT_DIR", "GIT_WORK_TREE"}:
            values[match.group(1)] = match.group(2)
            i += 1
            continue
        if os.path.basename(token) == "env":
            i += 1
            while i < git_index:
                token = segment[i]
                if token in {"-C", "--chdir"}:
                    if i + 1 >= git_index:
                        raise ParseIndeterminate("env chdir is missing its value")
                    target_cwd = _resolve(target_cwd or cwd, segment[i + 1])
                    i += 2
                    continue
                if token.startswith("--chdir="):
                    target_cwd = _resolve(target_cwd or cwd, token.split("=", 1)[1])
                    i += 1
                    continue
                match = _ASSIGNMENT.match(token)
                if match and match.group(1) in {"GIT_DIR", "GIT_WORK_TREE"}:
                    values[match.group(1)] = match.group(2)
                i += 1
            break
        i += 1
    return target_cwd, values


def _classify_git(
    argv: Sequence[str], segment: Sequence[str], shell_cwd: Path | None,
    root: Path, root_common: Path,
) -> int:
    if shell_cwd is None:
        return INDETERMINATE
    git_index = next(
        (i for i, token in enumerate(segment) if os.path.basename(token) == "git"),
        -1,
    )
    if git_index < 0:
        return ALLOW
    target_cwd, env_values = _env_context(segment, git_index, shell_cwd)
    if target_cwd is None:
        return INDETERMINATE

    probe_args: list[str] = []
    inline_aliases: dict[str, str] = {}
    dynamic_aliases: set[str] = set()
    git_dir = env_values.get("GIT_DIR")
    work_tree = env_values.get("GIT_WORK_TREE")
    subcommand = ""
    command_args: Sequence[str] = ()
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "-C":
            if i + 1 >= len(argv):
                return INDETERMINATE
            target_cwd = _resolve(target_cwd, argv[i + 1])
            if target_cwd is None:
                return INDETERMINATE
            i += 2
            continue
        if token.startswith("-C") and token != "-C":
            target_cwd = _resolve(target_cwd, token[2:])
            if target_cwd is None:
                return INDETERMINATE
            i += 1
            continue
        if token in {"--git-dir", "--work-tree"}:
            if i + 1 >= len(argv):
                return INDETERMINATE
            if token == "--git-dir":
                git_dir = argv[i + 1]
            else:
                work_tree = argv[i + 1]
            i += 2
            continue
        if token.startswith("--git-dir="):
            git_dir = token.split("=", 1)[1]
            i += 1
            continue
        if token.startswith("--work-tree="):
            work_tree = token.split("=", 1)[1]
            i += 1
            continue
        if token in {"-c", "--config-env", "--exec-path", "--namespace", "--super-prefix"}:
            if i + 1 >= len(argv):
                return INDETERMINATE
            value = argv[i + 1]
            probe_args.extend((token, value))
            if token == "-c":
                assignment = _inline_alias_assignment(value)
                if assignment is not None:
                    inline_aliases[assignment[0]] = assignment[1]
            elif token == "--config-env":
                key, separator, _environment_name = value.partition("=")
                if separator and key.casefold().startswith("alias.") and key[6:]:
                    dynamic_aliases.add(key[6:].casefold())
            i += 2
            continue
        if token.startswith("-c") and token != "-c":
            probe_args.append(token)
            assignment = _inline_alias_assignment(token[2:])
            if assignment is not None:
                inline_aliases[assignment[0]] = assignment[1]
            i += 1
            continue
        if token.startswith("--config-env="):
            probe_args.append(token)
            value = token.removeprefix("--config-env=")
            key, separator, _environment_name = value.partition("=")
            if separator and key.casefold().startswith("alias.") and key[6:]:
                dynamic_aliases.add(key[6:].casefold())
            i += 1
            continue
        if token.startswith("-"):
            probe_args.append(token)
            i += 1
            continue
        subcommand = token
        command_args = argv[i + 1 :]
        break
    else:
        return ALLOW

    if git_dir:
        resolved = _resolve(target_cwd, git_dir)
        if resolved is None:
            return INDETERMINATE
        probe_args.extend(("--git-dir", str(resolved)))
    if work_tree:
        resolved = _resolve(target_cwd, work_tree)
        if resolved is None:
            return INDETERMINATE
        probe_args.extend(("--work-tree", str(resolved)))

    mutates, common_wide, indeterminate = _command_mutation(
        subcommand,
        command_args,
        probe_args=probe_args,
        cwd=target_cwd,
        inline_aliases=inline_aliases,
        dynamic_aliases=dynamic_aliases,
    )
    if indeterminate:
        return INDETERMINATE
    if not mutates:
        return ALLOW
    if subcommand == "config" and _protected_config_mutates(command_args):
        # A global hooksPath write disables the installed reference gate for
        # every repo, so it is unsafe even from the external scratch cwd.
        return DENY

    top, common = _probe(probe_args, target_cwd)
    if top is None and common is None:
        # An explicit path under the canonical checkout is still unsafe even if
        # Git would later reject another malformed option.
        if target_cwd == root or root in target_cwd.parents:
            return DENY
        return ALLOW
    if common_wide:
        return DENY if common == root_common else ALLOW
    return DENY if top == root else ALLOW


def classify(command: str, *, cwd: Path, root: Path) -> int:
    root = root.resolve()
    cwd = cwd.resolve()
    root_common_proc = subprocess.run(
        [GIT, "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if root_common_proc.returncode != 0 or not root_common_proc.stdout.strip():
        return INDETERMINATE
    root_common = Path(root_common_proc.stdout.strip()).resolve()
    shell_cwd: Path | None = cwd
    prepared = _strip_shell_comments(
        _mask_heredoc_bodies(_remove_line_continuations(command))
    )
    for segment in _segments(prepared):
        argv = list(_command_argv(segment))
        if argv and argv[0] == "builtin":
            argv = argv[1:]
        if not argv:
            continue
        navigation = os.path.basename(argv[0])
        if navigation in {"cd", "pushd"}:
            values = [token for token in argv[1:] if token not in {"-L", "-P", "--"}]
            if navigation == "pushd":
                values = [token for token in values if token not in {">", ">>", "2>", "/dev/null"}]
            if values:
                next_cwd = _resolve(shell_cwd or cwd, values[0])
            elif navigation == "cd":
                assigned_home = next(
                    (
                        match.group(2)
                        for token in segment
                        if (match := _ASSIGNMENT.match(token))
                        and match.group(1) == "HOME"
                    ),
                    None,
                )
                next_cwd = (
                    _resolve(shell_cwd or cwd, assigned_home)
                    if assigned_home is not None
                    else Path.home()
                )
            else:
                next_cwd = None
            # With `cd missing; git add`, Bash keeps the old cwd and still runs
            # Git.  Separator-aware execution would distinguish `&&`, but this
            # static guard deliberately fails closed for both forms.
            shell_cwd = next_cwd if next_cwd is not None and next_cwd.is_dir() else None
            continue
        if navigation == "popd":
            shell_cwd = None
            continue
        if os.path.basename(argv[0]) != "git":
            continue
        outcome = _classify_git(argv, segment, shell_cwd, root, root_common)
        if outcome != ALLOW:
            return outcome
    return ALLOW


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cwd", required=True)
    args = parser.parse_args()
    command = sys.stdin.read()
    try:
        return classify(command, cwd=Path(args.cwd), root=Path(args.root))
    except (OSError, ValueError, subprocess.TimeoutExpired, ParseIndeterminate):
        # Invalid shell cannot execute, so it cannot mutate Git.  For valid but
        # unsupported syntax, fail closed only when the current repo shares the
        # canonical common dir (including linked worktrees); an unrelated cwd
        # cannot accidentally target canonical without an explicit path, which
        # the normal parser handles before reaching this fallback.
        syntax = subprocess.run(
            ["/bin/bash", "-n"], input=command, text=True,
            capture_output=True, check=False,
        )
        if syntax.returncode != 0 or not _RAW_CANDIDATE.search(command):
            return ALLOW
        try:
            root_common = subprocess.run(
                [GIT, "-C", str(Path(args.root).resolve()), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            cwd_common = subprocess.run(
                [GIT, "-C", str(Path(args.cwd).resolve()), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if (
                root_common.returncode == 0
                and cwd_common.returncode == 0
                and Path(root_common.stdout.strip()).resolve()
                == Path(cwd_common.stdout.strip()).resolve()
            ):
                return INDETERMINATE
        except (OSError, ValueError, subprocess.TimeoutExpired):  # silent-ok: fallback identity failure is explicitly indeterminate and denied by the hook.
            return INDETERMINATE
        return ALLOW


if __name__ == "__main__":
    raise SystemExit(main())
