"""BSD-only `stat -f` in shell scripts is a portability landmine — gate it.

2026-07-10 incident (docs/error_log.md「CI 從未跑過 pytest」entry): the hourly
dispatch wrapper read the claude binary's mtime with `stat -f %m`. That is BSD
syntax. GNU/Linux `stat` reads `-f` as `--file-system`, treats `%m` as a filename
(error, swallowed by `2>/dev/null`), and prints a MULTI-LINE filesystem report for
the real path — with exit status 0. The report landed in a shell arithmetic
expansion, bash raised a syntax error, and a non-interactive bash discards the
whole enclosing compound command on an arithmetic error. Control flow fell out of
the `if preflight failed` block entirely and into the next top-level statement,
which logged "preflight successful" and exited 0. The send-alert and the
Claude→Codex failover were both silently skipped. Two CI tests caught it only as
`assert 0 == 1`.

The exit status is the trap: `stat -f` SUCCEEDS on GNU. So the invariant a caller
must uphold is not "check the exit code" but "reject anything that is not a
digits-only value". Any script that reaches for `stat -f` must therefore also
carry the GNU spelling (`stat -c`) and a digits-only validation.

Population swept: every `*.sh` under scripts/ and .claude/hooks/. Three call
sites existed; all three now route through a `file_mtime_epoch` /
`file_size_bytes` helper.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHELL_DIRS = ("scripts", ".claude/hooks")

_BSD_STAT = re.compile(r"stat\s+-f")
_GNU_STAT = re.compile(r"stat\s+-c")
# `case "$value" in ""|*[!0-9]*)` — the digits-only rejection.
_DIGITS_GUARD = re.compile(r"\[!0-9\]")


def _shell_scripts() -> list[Path]:
    found: list[Path] = []
    for rel in SHELL_DIRS:
        directory = ROOT / rel
        if directory.is_dir():
            found.extend(sorted(directory.rglob("*.sh")))
    return found


def test_shell_script_population_is_non_empty() -> None:
    """A gate that scans nothing passes vacuously. Name the population."""
    assert len(_shell_scripts()) >= 5


@pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: p.name)
def test_bsd_stat_always_paired_with_gnu_fallback_and_digits_guard(script: Path) -> None:
    # errors="replace": file encoding is source-encoding.yml's concern, not this
    # gate's. A non-UTF-8 byte must not mask a portability bug (or vice versa).
    text = script.read_text(encoding="utf-8", errors="replace")
    if not _BSD_STAT.search(text):
        return

    assert _GNU_STAT.search(text), (
        f"{script.relative_to(ROOT)} uses BSD-only `stat -f` with no GNU `stat -c` "
        "fallback. On Linux `stat -f` prints a filesystem report and still exits 0."
    )
    assert _DIGITS_GUARD.search(text), (
        f"{script.relative_to(ROOT)} has both stat spellings but no digits-only "
        "validation (`*[!0-9]*`). GNU `stat -f` exits 0 on success, so checking the "
        "exit status cannot tell a real epoch from a filesystem report."
    )


_FUNC_START = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{")
_FUNC_END = re.compile(r"^\}")


def _strip_comment(line: str) -> str:
    """Drop a trailing `#` comment. The three portable helpers document the BSD
    spelling in prose right above themselves, so comments must not count as uses."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _bsd_stat_call_sites(text: str) -> list[tuple[int, str | None, list[str]]]:
    """Every non-comment `stat -f` line → (lineno, enclosing function, FULL body).

    Two passes on purpose. A single pass that accumulates the body as it goes only
    ever sees the lines ABOVE the call site — and in all three real helpers the
    `stat -c` fallback sits BELOW the `stat -f` it guards, so a one-pass scanner
    reports the correct code as a violation. (It did, on first run.)
    """
    lines = text.splitlines()

    ranges: list[tuple[str, int, int]] = []  # (name, start_idx, end_idx) 0-based, end exclusive
    open_name: str | None = None
    open_start = 0
    for idx, raw in enumerate(lines):
        start = _FUNC_START.match(raw)
        if start and open_name is None:
            open_name, open_start = start.group(1), idx
        elif open_name is not None and _FUNC_END.match(raw):
            ranges.append((open_name, open_start + 1, idx))
            open_name = None

    sites: list[tuple[int, str | None, list[str]]] = []
    for idx, raw in enumerate(lines):
        if not _BSD_STAT.search(_strip_comment(raw)):
            continue
        enclosing = next(
            ((name, s, e) for name, s, e in ranges if s <= idx < e), None
        )
        if enclosing is None:
            sites.append((idx + 1, None, []))
        else:
            name, s, e = enclosing
            sites.append((idx + 1, name, lines[s:e]))
    return sites


@pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: p.name)
def test_every_bsd_stat_call_site_is_inside_a_portable_helper(script: Path) -> None:
    """Per-CALL-SITE, not per-file.

    The file-level assertions above pass as soon as a script contains the portable
    helper ANYWHERE. So a new naked `stat -f` added to a file that already has one
    (e.g. `cron_hourly_dispatch.sh`, which now does) slips through green — the exact
    path by which this bug would return. Verified 2026-07-10: appending
    `_x=$(stat -f %m "$0")` to `cron_log_rotate.sh` left the gate at 66 passed.

    The real invariant: every `stat -f` must sit inside a function whose body also
    carries the GNU spelling and the digits-only rejection. Prose mentions of the
    BSD spelling in comments are not call sites.
    """
    text = script.read_text(encoding="utf-8", errors="replace")
    rel = script.relative_to(ROOT)
    for lineno, fn_name, fn_body in _bsd_stat_call_sites(text):
        assert fn_name is not None, (
            f"{rel}:{lineno} calls BSD-only `stat -f` at top level, outside any "
            "portable helper. Route it through `file_mtime_epoch` / `file_size_bytes` "
            "(GNU `stat -c` fallback + digits-only validation)."
        )
        body = "\n".join(fn_body)
        assert _GNU_STAT.search(body) and _DIGITS_GUARD.search(body), (
            f"{rel}:{lineno} calls `stat -f` inside `{fn_name}()`, whose body lacks "
            "the GNU `stat -c` fallback and/or the `*[!0-9]*` digits guard. On Linux "
            "`stat -f` exits 0 while printing a filesystem report."
        )


def test_call_site_scan_actually_finds_the_known_helpers() -> None:
    """Range self-check: an empty scan would make the gate above pass vacuously."""
    sites = [
        (script.name, fn)
        for script in _shell_scripts()
        for _, fn, _ in _bsd_stat_call_sites(script.read_text(encoding="utf-8", errors="replace"))
    ]
    assert sites, "no `stat -f` call sites found — the scanner or the population broke"
    assert {"file_mtime_epoch", "file_size_bytes"} <= {fn for _, fn in sites}, (
        f"expected both portable helpers among the call sites, got {sites}"
    )
