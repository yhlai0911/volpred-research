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

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LABEL = "com.volpred.dispatch-supervisor"
WRAPPER = "scripts/reload_dispatch_supervisor.sh"

# The wrapper IS the sanctioned path; this gate names the command to forbid it.
_ALLOWLIST = {WRAPPER, "tests/test_no_raw_supervisor_kickstart.py"}

# `.claude/worktrees/**` holds full checkouts of this repo — scanning them
# re-scans every file once per worktree (first run of this gate: 113,926 tests,
# 2 minutes) and reports stale copies of code already fixed on main.
_SKIP_PARTS = {"__pycache__", "worktrees", ".git", "node_modules"}

_SEARCH_ROOTS = ("scripts", "src", "docs", ".claude/rules", ".claude/skills")
_SUFFIXES = (".py", ".sh", ".md")


def _candidate_files() -> list[Path]:
    out: list[Path] = []
    for root in _SEARCH_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in _SUFFIXES:
                continue
            if _SKIP_PARTS & set(path.parts):
                continue
            if str(path.relative_to(REPO)) in _ALLOWLIST:
                continue
            out.append(path)
    return out


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") or stripped.startswith("//")


def _offends(window: str) -> bool:
    """True only for the RUNNABLE form: `launchctl kickstart … gui/<uid>/<label>`.

    Requiring the `gui/` domain target is what separates a command the operator
    can paste from prose that merely names `kickstart -k`. Without it this gate
    flags its own ban — `.claude/rules/control-plane.md` says 「禁止手動裸
    `kickstart -k`」 next to the label — and the historical cutover plan in
    `docs/refactor_plan_hourly_dispatch.md`. Both are documentation, neither is
    a paste-able command. (Both were false positives on this gate's first run.)
    """
    return "kickstart" in window and "gui/" in window and LABEL in window


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    """Multi-line string concatenation splits the command across source lines, so
    join each line with its successor before matching — the 2026-07-10
    `ops_dashboard.py` case put `kickstart -k ` and `gui/501/<label>` on adjacent
    lines and would slip past a single-line matcher.
    """
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if _is_comment(line):
            continue
        window = line + (lines[i + 1] if i + 1 < len(lines) else "")
        if _offends(window):
            hits.append((i + 1, line.strip()))
    return hits


def test_wrapper_exists_or_this_gate_is_dead() -> None:
    assert (REPO / WRAPPER).exists(), (
        f"{WRAPPER} is gone — either it was renamed (update this gate) or the "
        "planned-restart marker path was abandoned, in which case this gate "
        "protects nothing and must not silently pass."
    )


def test_gate_detects_a_raw_kickstart() -> None:
    """Break-then-verify, without touching the production checkout: feed the
    matcher the exact forms that existed at 2026-07-10 17:20."""
    # alert-remediation body (src/volpred/ops/alerts.py, single line)
    assert _offends(f"   launchctl kickstart -k gui/$(id -u)/{LABEL}")
    # ops_dashboard.py — command split across concatenated string literals
    split = '"check supervisor: launchctl kickstart -k "' + f'"gui/501/{LABEL} + uv run ..."'
    assert _offends(split)


def test_gate_does_not_flag_documentation() -> None:
    """The ban itself, and historical plans, name the command without `gui/`.
    A gate that flags its own rule text gets disabled by the next person."""
    assert not _offends(f"**禁止手動裸 `kickstart -k`**（漏寫 marker）… {LABEL} …")
    assert not _offends(f"把 `{LABEL}` 從 --dry-run 切成 real-run（→ `launchctl kickstart -k`）")
    assert _is_comment("        # NOT raw `launchctl kickstart` — bypasses the marker")


def test_no_raw_kickstart_instruction() -> None:
    files = _candidate_files()
    assert files, "no files scanned — search roots or suffixes changed; gate is dead"

    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in files:
        hits = _offending_lines(path)
        if hits:
            offenders[str(path.relative_to(REPO))] = hits

    assert not offenders, (
        f"These tell the operator to run a raw `launchctl kickstart` against {LABEL}: "
        f"{offenders}. That writes no planned-restart marker, so a routine deploy pages "
        f"the owner as an unexpected crash. Use `bash {WRAPPER} --reason <why>` (it writes "
        f"the marker and refuses while a worker is in flight), or move the mention into a "
        f"`#` comment if it is history."
    )
