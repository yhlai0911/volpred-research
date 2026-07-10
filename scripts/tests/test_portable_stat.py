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
