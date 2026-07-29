"""Single-source-of-truth gate for the agent skill surface.

Replaces `tests/test_agent_spec.py`, which guarded a render pipeline
(`agent-specs/` -> `.claude/` + `.agents/`) that was retired on 2026-04-18
(commit e64a19072) but whose machinery was left behind. The leftovers caused
real failures: `ops session-bootstrap` blew up on the missing
`agent-specs/guide.md`, `.agents/skills/` kept living on as a gitignored,
unreadable-by-anyone copy that drifted from `.claude/skills/` in 18 of 26
shared skills, and `ops agent-spec render` was a loaded gun that rmtree's
`.claude/skills/` before rendering from a canonical tree that no longer exists.

The invariant this file enforces:

    `.claude/` is the ONE canonical agent surface. There is no render step,
    therefore there is nothing to drift.

Why `.agents/skills/` is dead and not merely stale (verified 2026-07-14):
  * Codex CLI 0.144.1 discovers skills only through plugin marketplaces
    (`<home>/.agents/plugins/marketplace.json` -> `plugins/<name>/skills/`).
    The shipped binary contains zero occurrences of the string
    `agents/skills`, and this repo ships no `.agents/plugins/marketplace.json`.
  * Claude Code reads `.claude/skills/`.
  * `scripts/check_skills_complete.sh` already treats any `.agents/` path
    inside a SKILL.md as a legacy typo and rewrites it to `.claude/`.

So the fix is elimination, not a second render + a third watchdog
(CLAUDE.md anti-stacking). This test is the enforcement owner: it fails if a
second skill surface is resurrected, or if the retired canonical tree comes
back. It is run by CI (`.github/workflows/pytest.yml`) and by the pre-push
hook, which both execute the whole `tests/` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_SKILLS = REPO_ROOT / ".claude" / "skills"

# Surfaces that were retired with the agent-specs render pipeline. If any of
# these reappears we are back to multi-way drift, which is the bug this gate
# exists to prevent.
RETIRED_SURFACES = (
    Path(".agents") / "skills",
    Path("agent-specs"),
)

STALE_RENDER_HEADER = "AUTO-GENERATED FROM agent-specs/"

CANONICAL_AGENT_DIRS = (
    "agents",
    "commands",
    "hooks",
    "rules",
    "skills",
)


def _iter_agent_surface_files() -> list[Path]:
    """Every `.md` in THIS checkout's active `.claude/` surface.

    Enumerate active roots directly instead of recursively walking `.claude/`
    and filtering afterward. Post-filtering still traverses local-only
    `.claude/worktrees/`, `.claude/backups/`, and `.claude/projects/`, so the
    test reads paths absent from a clean CI checkout and trips the CI-parity
    ratchet even when every assertion passes.
    """
    root = REPO_ROOT / ".claude"
    files = list(root.glob("*.md"))
    for dirname in CANONICAL_AGENT_DIRS:
        active_root = root / dirname
        if active_root.is_dir():
            files.extend(active_root.rglob("*.md"))
    assert files, f"scanned zero files under {root} — the check is not actually running"
    return files


def test_canonical_skill_surface_exists() -> None:
    """`.claude/skills/` is the single source of truth and must be populated."""
    assert CANONICAL_SKILLS.is_dir(), f"missing canonical skill surface: {CANONICAL_SKILLS}"
    skills = [d for d in CANONICAL_SKILLS.iterdir() if d.is_dir()]
    assert skills, "canonical skill surface is empty"
    missing_manifest = sorted(d.name for d in skills if not (d / "SKILL.md").is_file())
    assert not missing_manifest, f"skills without SKILL.md: {missing_manifest}"


@pytest.mark.parametrize("retired", RETIRED_SURFACES, ids=lambda p: str(p))
def test_retired_agent_surface_does_not_come_back(retired: Path) -> None:
    """A second skill/spec surface must not be resurrected.

    Deliberately checks the filesystem rather than git: `.agents/skills/` was
    *gitignored*, which is exactly how it managed to drift invisibly for three
    months. An ignored copy is still a copy an agent can read and edit.
    """
    path = REPO_ROOT / retired
    assert not path.exists(), (
        f"{retired} exists again. `.claude/` is the only canonical agent surface "
        "(the agent-specs render pipeline was retired in e64a19072). Do not "
        "recreate a second copy — put the content in .claude/ instead."
    )


def test_no_stale_render_headers_in_canonical_surface() -> None:
    """No `.claude/` file may claim it is generated from the retired canonical.

    These headers actively mislead: they tell the next agent to 'edit canonical
    sources instead' and point at a directory that has not existed since
    2026-04-18, so edits either go nowhere or get made twice.
    """
    offenders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in _iter_agent_surface_files()
        if STALE_RENDER_HEADER in p.read_text(encoding="utf-8", errors="replace")
    )
    assert not offenders, (
        "files still carry the retired agent-specs render header "
        f"({STALE_RENDER_HEADER!r}); they are canonical now, drop the header: {offenders}"
    )


def test_gitignore_does_not_hide_a_second_skill_surface() -> None:
    """`.gitignore` must not silently re-hide a resurrected `.agents/skills/`.

    The original entry is what let the drift stay invisible: the copy was
    untracked, so no clone/worktree ever had it and no diff ever showed it.
    """
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    live_rules = [
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(
        rule.rstrip("/").endswith(".agents/skills") or rule.rstrip("/") == ".agents"
        for rule in live_rules
    ), (
        ".gitignore still ignores a second skill surface. The surface is retired; "
        "an ignore rule would let it come back invisibly."
    )
