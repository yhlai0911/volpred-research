"""Gate: no monitor may probe a LaunchAgent label the 7/4 cutover retired.

The 2026-07-04 cutover replaced the `com.volpred.hourly-dispatch` LaunchAgent
(+ its shell wrapper) with the `com.volpred.dispatch-supervisor` daemon. The
old plist still sits in ~/Library/LaunchAgents but is UNLOADED, so any
`launchctl list` probe for it returns False forever — a healthy, dispatching
loop reported as dead.

Three monitors made this exact mistake, and each was fixed in isolation because
nobody swept the full population of readers:
  - ops_dashboard.py      fixed 2026-07-05
  - cron_review.py        fixed 2026-07-08 (false 🔴 "miss 80h" in the boss report)
  - work_dashboard_server fixed 2026-07-10 (this test) — silently wrong for 6 days

Prose in an error-log entry did not stop the third recurrence. This is the
mechanical gate: a retired label may appear in a comment explaining the history,
never inside a live probe call.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

RETIRED_LABELS = ("com.volpred.hourly-dispatch",)
LIVE_LABEL = "com.volpred.dispatch-supervisor"

# Monitors that probe launchd for daemon liveness.
MONITOR_SOURCES = (
    "scripts/work_dashboard_server.py",
    "scripts/cron_review.py",
    "scripts/ops_dashboard.py",
)


def _string_literals(path: Path) -> list[str]:
    """Every string literal in the module — comments and docstrings excluded.

    A retired label is fine in a `#` comment (history) but never in a value the
    code actually passes to `launchctl`. Module/function docstrings are the one
    string-literal form that is documentation, so they are stripped too.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


@pytest.mark.parametrize("rel", MONITOR_SOURCES)
def test_monitor_does_not_probe_a_retired_label(rel: str) -> None:
    path = REPO / rel
    if not path.exists():  # a monitor may legitimately be deleted later
        pytest.skip(f"{rel} not present")

    offenders = [
        lit
        for lit in _string_literals(path)
        for dead in RETIRED_LABELS
        if dead in lit
    ]

    assert not offenders, (
        f"{rel} still references a retired LaunchAgent label in live code: {offenders}. "
        f"The cutover made it permanently unloaded, so any launchctl probe reports the "
        f"healthy daemon as dead. Use {LIVE_LABEL!r}, and keep the history in a # comment."
    )


def test_work_dashboard_probes_the_live_daemon() -> None:
    """Positive assertion — the tile must actually watch something real."""
    src = (REPO / "scripts" / "work_dashboard_server.py").read_text(encoding="utf-8")
    m = re.search(r'"hourly_dispatch":\s*_daemon_alive\(\s*"([^"]+)"', src)

    assert m, "hourly_dispatch daemon tile not found — did the key or helper get renamed?"
    assert m.group(1) == LIVE_LABEL
