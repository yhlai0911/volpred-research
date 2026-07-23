"""Regression test: every agent-job brief carries the headless runtime contract.

2026-07-20 incident (hourly-slot-2, job agent-brief_k1698_rev3-4dffab): the
agent fixed the K1698 generator correctly, launched the full rerun in the
background, and ended its turn with "背景重跑完成時我會被叫醒". Nothing wakes a
`claude -p` process. The tree was torn down, the rerun died at 800/2192 files,
the result artifact never appeared, and a whole 20-minute job was collected as
a failure — with the actual work salvageable only by hand.

The agent's plan was correct for an interactive session. It was never told it
wasn't in one. That is a property of the runner, not of any one brief, so the
runner prepends it to every brief rather than each dispatcher remembering to.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_agent_job import BRIEF_PREAMBLE, _compose_brief  # noqa: E402


def test_preamble_precedes_the_task_brief() -> None:
    composed = _compose_brief("Do the K1698 rerun and write the artifact.\n")
    assert composed.startswith(BRIEF_PREAMBLE)
    assert composed.endswith("Do the K1698 rerun and write the artifact.\n")


def test_preamble_names_both_failure_modes() -> None:
    """The two things the agent must plan around, in the words it will read."""
    # Nothing wakes it up — the K1698 failure.
    assert "background" in BRIEF_PREAMBLE
    assert "Nothing wakes you up" in BRIEF_PREAMBLE
    # Prose is not a result — the artifact is.
    assert "unresolved" in BRIEF_PREAMBLE
    assert "result artifact" in BRIEF_PREAMBLE


def test_empty_brief_still_gets_the_contract() -> None:
    assert _compose_brief("") == BRIEF_PREAMBLE
