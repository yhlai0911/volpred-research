"""CLAUDE.md and AGENTS.md must never drift from the shared governance source.

Both files are copies of `config/governance_shared.md` for every rule both
agents must obey, because each agent auto-loads only its own file and a pointer
to the other one is not reliably followed. Copies without a gate rot: before
this suite existed, all eleven shared sections had drifted, including the
project's highest-priority rule (research honesty stood at 6 condensed items in
one file and 13 expanded ones in the other).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_governance.py"
CANONICAL = ROOT / "config" / "governance_shared.md"
TARGETS = (ROOT / "CLAUDE.md", ROOT / "AGENTS.md")

_spec = importlib.util.spec_from_file_location("sync_governance", SCRIPT)
sync_governance = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sync_governance)


def _check() -> int:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT, capture_output=True, text=True,
    ).returncode


def test_both_files_match_the_canonical_source() -> None:
    assert _check() == 0, (
        "CLAUDE.md / AGENTS.md drifted from config/governance_shared.md. "
        "Edit the canonical file, then run: "
        "uv run python scripts/sync_governance.py --apply"
    )


def test_check_fails_when_a_shared_region_is_edited(tmp_path) -> None:
    """Guard the guard: a gate that cannot fail is not a gate."""
    sections = sync_governance.load_canonical()
    name = next(iter(sections))
    target = TARGETS[0]
    original = target.read_text(encoding="utf-8")
    begin = f"<!-- shared:{name}:begin -->"
    assert begin in original, f"{target.name} lost its {name} marker"
    try:
        target.write_text(
            original.replace(begin, begin + "\nDRIFT INJECTED BY TEST", 1),
            encoding="utf-8",
        )
        assert _check() == 1, "edited shared region did not fail --check"
    finally:
        target.write_text(original, encoding="utf-8")
    assert _check() == 0, "restore failed; working tree left dirty"


@pytest.mark.parametrize("target", TARGETS, ids=lambda p: p.name)
def test_every_shared_section_is_present_in_both_files(target: Path) -> None:
    text = target.read_text(encoding="utf-8")
    missing = [
        name for name in sync_governance.load_canonical()
        if f"<!-- shared:{name}:begin -->" not in text
    ]
    assert not missing, f"{target.name} is missing marker(s): {missing}"


def test_rules_that_only_one_file_used_to_carry_now_reach_both() -> None:
    """The concrete regressions that motivated the merge, pinned per file.

    graphify lived only in AGENTS.md, so the Claude main thread navigated by
    grep for a whole session; the experiment artifact gate and the global skill
    surface were likewise single-sided.
    """
    required = (
        "scripts/graphify_integration.py",
        "check_experiment_artifacts.py",
        "$HOME/.agents/skills/",
        ".codex/worktrees/",
        ".claude/worktrees/",
    )
    for target in TARGETS:
        text = target.read_text(encoding="utf-8")
        for token in required:
            assert token in text, f"{target.name} does not carry {token!r}"
