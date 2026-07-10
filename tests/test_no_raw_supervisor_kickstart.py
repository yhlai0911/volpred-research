"""Gate: nothing may instruct a raw `launchctl kickstart` of the supervisor.

2026-07-10 restart-noise incident. Five deliberate deploy restarts in 80 minutes
each emailed the owner an indistinguishable "supervisor restart" alert; he could
not tell a deploy from a crash and asked for a thorough fix. The fix
(`cfe13589a`) is a planned-restart marker: `scripts/reload_dispatch_supervisor.sh`
writes it, the supervisor consumes it at boot, and `send_supervisor_restart()`
stays silent when it is present — so only an UNEXPECTED KeepAlive respawn pages
the owner.

That fix is only as good as the path people actually take. A raw
`launchctl kickstart -k gui/<uid>/com.volpred.dispatch-supervisor` writes no
marker, so a routine deploy still reads as a crash. Within hours of landing the
marker, three places in this repo — two of them alert-remediation bodies written
the same day — were still telling the operator to run exactly that command.

Prose could not hold this. The command may appear in the wrapper, and in `#`
comments explaining the history; never in a string the operator is told to run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LABEL = "com.volpred.dispatch-supervisor"
WRAPPER = "scripts/reload_dispatch_supervisor.sh"

# The wrapper IS the sanctioned path; this gate names the command to forbid it.
_ALLOWLIST = {WRAPPER, "tests/test_no_raw_supervisor_kickstart.py"}

_SEARCH_ROOTS = ("scripts", "src", "docs", ".claude")
_SUFFIXES = (".py", ".sh", ".md")


def _candidate_files() -> list[Path]:
    out: list[Path] = []
    for root in _SEARCH_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in _SUFFIXES or "__pycache__" in path.parts:
                continue
            if str(path.relative_to(REPO)) in _ALLOWLIST:
                continue
            out.append(path)
    return out


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") or stripped.startswith("//")


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    """A line offends when it names BOTH `kickstart` and the supervisor label —
    i.e. it is a runnable command, not a passing mention of `kickstart -k`.

    Multi-line string concatenation splits the command across lines, so join a
    line with its successor before matching (the 2026-07-10 ops_dashboard.py
    case put `kickstart -k ` and the label on adjacent lines).
    """
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if _is_comment(line):
            continue
        window = line + (lines[i + 1] if i + 1 < len(lines) else "")
        if "kickstart" in window and LABEL in window:
            hits.append((i + 1, line.strip()))
    return hits


def test_wrapper_exists_or_this_gate_is_dead() -> None:
    assert (REPO / WRAPPER).exists(), (
        f"{WRAPPER} is gone — either it was renamed (update this gate) or the "
        "planned-restart marker path was abandoned, in which case this gate "
        "protects nothing and must not silently pass."
    )


def test_gate_detects_a_raw_kickstart() -> None:
    """Self-check: the matcher must actually fire on the forbidden command,
    including the split-across-lines form that slipped past a manual review."""
    sample = REPO / "tests" / "test_no_raw_supervisor_kickstart.py"
    lines = [
        '            "check supervisor: launchctl kickstart -k "',
        f'            "gui/501/{LABEL} + uv run ..."',
    ]
    joined = lines[0] + lines[1]
    assert "kickstart" in joined and LABEL in joined
    assert not _is_comment(lines[0])
    assert sample.exists()


@pytest.mark.parametrize("path", _candidate_files(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_raw_kickstart_instruction(path: Path) -> None:
    offenders = _offending_lines(path)
    rel = path.relative_to(REPO)
    assert not offenders, (
        f"{rel} tells the operator to run a raw `launchctl kickstart` against "
        f"{LABEL}: {offenders}. That writes no planned-restart marker, so a routine "
        f"deploy pages the owner as an unexpected crash. Use `bash {WRAPPER} "
        f"--reason <why>` (it writes the marker and refuses while a worker is in "
        f"flight), or move the mention into a `#` comment if it is history."
    )
