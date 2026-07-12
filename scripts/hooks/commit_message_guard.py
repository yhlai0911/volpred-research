#!/usr/bin/env python3
"""Classify inline ``git commit`` message arguments without executing shell code.

Predicate exit contract for ``pretooluse-bash-optimizer.sh``:

* 0: deny (an inline message/trailer contains non-ASCII)
* 10: allow (every detected inline message/trailer is ASCII, or none is present)
* 20: indeterminate (the early UX parser cannot classify this shell syntax)

The command arrives on stdin.  This helper never expands, evaluates, or executes it.
Heredoc bodies are masked before tokenization so source text such as
``git commit -m '中文範例'`` is not mistaken for a command being executed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
import re
import shlex
import sys
from typing import Iterable, Iterator, Sequence


DENY = 0
ALLOW = 10
INDETERMINATE = 20


class ParseIndeterminate(ValueError):
    """The shell text cannot be classified safely without executing it."""


@dataclass(frozen=True)
class Heredoc:
    delimiter: str
    strip_tabs: bool


def _parse_heredoc_word(line: str, start: int) -> tuple[str, int]:
    """Apply shell quote removal to one heredoc delimiter word."""
    chars: list[str] = []
    i = start
    saw_input = False
    while i < len(line):
        char = line[i]
        if char.isspace() or char in ";&|()<>":
            break
        saw_input = True
        if char == "'":
            end = line.find("'", i + 1)
            if end < 0:
                raise ParseIndeterminate("unterminated single quote in heredoc delimiter")
            chars.append(line[i + 1 : end])
            i = end + 1
        elif char == '"':
            i += 1
            while i < len(line) and line[i] != '"':
                if line[i] == "\\" and i + 1 < len(line):
                    i += 1
                chars.append(line[i])
                i += 1
            if i >= len(line):
                raise ParseIndeterminate("unterminated double quote in heredoc delimiter")
            i += 1
        elif char == "\\":
            if i + 1 >= len(line):
                raise ParseIndeterminate("dangling escape in heredoc delimiter")
            chars.append(line[i + 1])
            i += 2
        else:
            chars.append(char)
            i += 1
    if not saw_input or not chars:
        raise ParseIndeterminate("missing heredoc delimiter")
    return "".join(chars), i


def _heredocs_on_header(
    line: str, quote: str | None
) -> tuple[list[Heredoc], str | None]:
    """Find heredocs while carrying quote state across physical lines."""
    found: list[Heredoc] = []
    i = 0
    while i < len(line):
        char = line[i]
        if quote is not None:
            if quote == '"' and char == "\\" and i + 1 < len(line):
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char == "\\":
            i += 2
            continue
        if char in {"'", '"'}:
            quote = char
            i += 1
            continue
        if char == "#" and (i == 0 or line[i - 1].isspace() or line[i - 1] in ";&|("):
            break
        # Here-strings are not heredocs.  Skip simple arithmetic shifts too;
        # treating ``$((1 << 2))`` as a heredoc would make a safe command
        # indeterminate and recreate the false-positive class.
        if line.startswith("<<<", i):
            i += 3
            continue
        if line.startswith("$((", i):
            end = line.find("))", i + 3)
            if end < 0:
                raise ParseIndeterminate("unterminated arithmetic expansion")
            i = end + 2
            continue
        if line.startswith("((", i):
            end = line.find("))", i + 2)
            if end < 0:
                raise ParseIndeterminate("unterminated arithmetic command")
            i = end + 2
            continue
        if line.startswith("<<", i):
            i += 2
            strip_tabs = i < len(line) and line[i] == "-"
            if strip_tabs:
                i += 1
            while i < len(line) and line[i] in " \t":
                i += 1
            delimiter, i = _parse_heredoc_word(line, i)
            found.append(Heredoc(delimiter=delimiter, strip_tabs=strip_tabs))
            continue
        i += 1
    return found, quote


def _mask_heredoc_bodies(command: str) -> str:
    """Replace heredoc bodies/delimiters with blank lines, preserving headers."""
    pending: deque[Heredoc] = deque()
    active: Heredoc | None = None
    quote: str | None = None
    masked: list[str] = []

    for line in command.splitlines(keepends=True):
        if active is not None:
            candidate = line.rstrip("\r\n")
            if active.strip_tabs:
                candidate = candidate.lstrip("\t")
            masked.append("\n" if line.endswith(("\n", "\r")) else "")
            if candidate == active.delimiter:
                active = pending.popleft() if pending else None
            continue

        masked.append(line)
        header = line.rstrip("\r\n")
        found, quote = _heredocs_on_header(header, quote)
        pending.extend(found)
        # A physical newline inside a quote is part of the header, not the
        # point at which the shell starts consuming pending heredoc bodies.
        if quote is None and pending:
            active = pending.popleft()

    if active is not None or pending:
        raise ParseIndeterminate("unterminated heredoc")
    return "".join(masked)


def _remove_line_continuations(command: str) -> str:
    """Apply shell's backslash-newline removal outside single quotes."""
    output: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    while i < len(command):
        char = command[i]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            output.append(char)
            i += 1
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            output.append(char)
            i += 1
            continue
        if char == "\\" and not in_single_quote:
            if command.startswith("\r\n", i + 1):
                i += 3
                continue
            if i + 1 < len(command) and command[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < len(command):
                # The escaped character cannot open/close a shell quote.
                output.extend((char, command[i + 1]))
                i += 2
                continue
        output.append(char)
        i += 1
    return "".join(output)


def _strip_shell_comments(command: str) -> str:
    """Remove real shell comments while preserving ``#`` inside an argv word."""
    output: list[str] = []
    in_single_quote = False
    in_double_quote = False
    at_word_start = True
    i = 0
    while i < len(command):
        char = command[i]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            at_word_start = False
            output.append(char)
            i += 1
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            at_word_start = False
            output.append(char)
            i += 1
            continue
        if char == "\\" and not in_single_quote and i + 1 < len(command):
            output.extend((char, command[i + 1]))
            at_word_start = False
            i += 2
            continue
        if char == "#" and not in_single_quote and not in_double_quote and at_word_start:
            newline = command.find("\n", i)
            if newline < 0:
                break
            output.append("\n")
            at_word_start = True
            i = newline + 1
            continue
        output.append(char)
        if not in_single_quote and not in_double_quote:
            at_word_start = char.isspace() or char in ";&|()<>"
        i += 1
    return "".join(output)


_SEPARATOR_CHARS = frozenset(";&|()\n")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\+)?=")
_REDIRECTIONS = {"<", ">", "<<", ">>", "<<<", "<>", ">&", "<&", ">|", "&>", "&>>"}
_CONTROL_PREFIXES = {"!", "{", "do", "elif", "else", "if", "then", "until", "while"}


def _segments(command: str) -> Iterator[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n<>")
    # Keep newlines as shell command boundaries; shlex otherwise treats them as
    # ordinary whitespace and can join argv from two different commands.
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    # Comments were stripped with shell's word-boundary rule.  shlex's native
    # commenter handling wrongly treats ``fix#中文`` as ``fix``.
    lexer.commenters = ""

    current: list[str] = []
    for token in lexer:
        if token and set(token) <= _SEPARATOR_CHARS:
            if current:
                yield current
                current = []
        else:
            current.append(token)
    if current:
        yield current


def _command_argv(segment: Sequence[str]) -> Sequence[str]:
    """Drop safe leading assignments/wrappers; never search inside echo data."""
    i = 0
    while i < len(segment):
        token = segment[i]
        if _ASSIGNMENT.match(token) or token in _CONTROL_PREFIXES:
            i += 1
            continue
        if token.isdigit() and i + 1 < len(segment) and segment[i + 1] in _REDIRECTIONS:
            if i + 2 >= len(segment):
                raise ParseIndeterminate("prefix redirection is missing its target")
            i += 3
            continue
        if token in _REDIRECTIONS:
            if i + 1 >= len(segment):
                raise ParseIndeterminate("prefix redirection is missing its target")
            i += 2
            continue
        if token == "command":
            i += 1
            query_only = False
            while i < len(segment):
                option = segment[i]
                if option == "--":
                    i += 1
                    break
                if option.startswith("-") and set(option[1:]) <= {"p", "v", "V"}:
                    query_only = query_only or "v" in option or "V" in option
                    i += 1
                    continue
                break
            if query_only:
                # `command -v/-V` inspects names; it does not execute argv.
                return ()
            if i < len(segment) and segment[i] == "--":
                i += 1
            continue
        if token in {"exec", "nohup", "time"}:
            i += 1
            while i < len(segment) and segment[i].startswith("-"):
                if segment[i] == "-a":
                    if i + 1 >= len(segment):
                        raise ParseIndeterminate("exec -a is missing argv[0]")
                    i += 2
                else:
                    i += 1
            continue
        if os.path.basename(token) == "env":
            i += 1
            while i < len(segment):
                env_token = segment[i]
                if env_token == "--":
                    i += 1
                    break
                if env_token in {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"}:
                    if i + 1 >= len(segment):
                        raise ParseIndeterminate(f"env {env_token} is missing its value")
                    i += 2
                    continue
                if env_token.startswith("-") or _ASSIGNMENT.match(env_token):
                    i += 1
                    continue
                break
            continue
        break
    return segment[i:]


_GLOBAL_VALUE_OPTIONS = {
    "-C",
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}


def _commit_args(argv: Sequence[str]) -> Sequence[str] | None:
    if not argv or os.path.basename(argv[0]) != "git":
        return None
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "commit":
            return argv[i + 1 :]
        if token == "--":
            return None
        if token in _GLOBAL_VALUE_OPTIONS:
            if i + 1 >= len(argv):
                raise ParseIndeterminate(f"missing value for git global option {token}")
            i += 2
            continue
        if token.startswith("-C") and token != "-C":
            i += 1
            continue
        if token.startswith("-c") and token != "-c":
            i += 1
            continue
        if any(token.startswith(f"{option}=") for option in _GLOBAL_VALUE_OPTIONS if option.startswith("--")):
            i += 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        return None
    return None


def _long_option_value(
    args: Sequence[str], index: int, canonical: str, minimum_prefix: int
) -> tuple[str, int] | None:
    token = args[index]
    option, equals, attached = token.partition("=")
    if len(option) < minimum_prefix or not canonical.startswith(option):
        return None
    if equals:
        return attached, index + 1
    if index + 1 >= len(args):
        raise ParseIndeterminate(f"missing value for {option}")
    return args[index + 1], index + 2


_NO_VALUE_SHORTS_BEFORE_M = frozenset("aeinopqsvz")


_EXPANSION_SENTINEL = "\ue000"
_EXPANSION_STARTS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_({?#!$*-@'\"")


def _mark_shell_expansions(command: str) -> str:
    """Mark expansions outside single quotes so inline ``-m`` fails closed."""
    output: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    while i < len(command):
        char = command[i]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            output.append(char)
            i += 1
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            output.append(char)
            i += 1
            continue
        if char == "\\" and not in_single_quote and i + 1 < len(command):
            output.extend((char, command[i + 1]))
            i += 2
            continue
        if not in_single_quote and char == "`":
            output.append(_EXPANSION_SENTINEL)
            i += 1
            continue
        if (
            not in_single_quote
            and char == "$"
            and i + 1 < len(command)
            and command[i + 1] in _EXPANSION_STARTS
        ):
            output.append(_EXPANSION_SENTINEL)
            i += 1
            continue
        output.append(char)
        i += 1
    return "".join(output)


def _inline_message_values(args: Sequence[str]) -> Iterable[str]:
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            return

        long_message = _long_option_value(args, i, "--message", len("--m"))
        if long_message is not None:
            value, i = long_message
            yield value
            continue

        # ``--trailer`` contributes directly to the final commit body, unlike
        # --author/pathspec.  Preserve the old safety invariant while removing
        # unrelated-Unicode false positives.
        long_trailer = _long_option_value(args, i, "--trailer", len("--tr"))
        if long_trailer is not None:
            value, i = long_trailer
            yield value
            continue

        if token.startswith("-") and not token.startswith("--"):
            cluster = token[1:]
            message_index = cluster.find("m")
            if message_index >= 0 and set(cluster[:message_index]) <= _NO_VALUE_SHORTS_BEFORE_M:
                attached = cluster[message_index + 1 :]
                if attached:
                    yield attached
                    i += 1
                else:
                    if i + 1 >= len(args):
                        raise ParseIndeterminate("missing value for -m")
                    yield args[i + 1]
                    i += 2
                continue
        i += 1


def has_non_ascii_inline_message(command: str) -> bool:
    # Shell removes backslash-newline before recognizing heredoc headers.  The
    # order is observable when `<<EOF \\` continues onto a line containing the
    # real git command; masking first would incorrectly hide that command.
    continued = _remove_line_continuations(command)
    masked = _mask_heredoc_bodies(continued)
    prepared = _mark_shell_expansions(_strip_shell_comments(masked))
    for segment in _segments(prepared):
        args = _commit_args(_command_argv(segment))
        if args is None:
            continue
        for value in _inline_message_values(args):
            if _EXPANSION_SENTINEL in value:
                raise ParseIndeterminate("inline commit message uses shell expansion")
            if not value.isascii():
                return True
    return False


def main() -> int:
    try:
        command = sys.stdin.read()
        return DENY if has_non_ascii_inline_message(command) else ALLOW
    except (OSError, UnicodeError, ParseIndeterminate, ValueError):
        return INDETERMINATE


if __name__ == "__main__":
    raise SystemExit(main())
