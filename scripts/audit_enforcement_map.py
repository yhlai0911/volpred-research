#!/usr/bin/env python3
"""Audit: Enforcement Layer Map claims vs. what is actually on disk.

Why this exists (2026-07-20, WS-F1)
-----------------------------------
`loop-health-and-dreaming.md` holds the Enforcement Layer Map — the authoritative
index every new constraint is supposed to consult before opening a new hook /
cron / workflow ("不要疊床架屋"). On 2026-07-20 the map was audited by hand and
found to be missing 3 registered Claude Code hooks, 4 PreToolUse deny rules,
1 whole CI workflow + 1 CI step, and all 5 git-hook files. A stale authoritative
index is worse than no index: an agent reads it, concludes a concern has no
owner, and stacks a new layer on top of the one that already existed.

Prose cannot keep an index fresh. This gate does: the map carries four
machine-readable inventory tables, and this script rebuilds each inventory from
disk and diffs them. Add a hook without touching the map -> CI red.

Inventories checked
-------------------
  HOOKS      .claude/settings.json (+ settings.local.json if present) `hooks`
             -> (event, matcher, owner script path)
  DENY       .claude/hooks/pretooluse-bash-optimizer.sh DENY_REASON branches
             + PreToolUse hooks that are themselves deny-only owners
  CI         .github/workflows/*.yml -> (workflow file, job id)
  GITHOOKS   scripts/git_hooks/ (canonical, in-repo; .git/hooks is not tracked
             so CI can only see this copy) + deploy parity with .git/hooks
             when running on a machine that has them installed

Exit 0 = map matches disk. Exit 1 = drift (or the map's tables are unparseable).

Anti-stacking note: this is not a new enforcement layer. It is one more step in
the existing `audit` job of .github/workflows/knowledge-provenance.yml (Data
Baseline Gates), which already owns "a canonical file claims X, verify X".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MAP_PATH = REPO / ".claude/skills/platform-ops-manager/references/loop-health-and-dreaming.md"
SETTINGS = REPO / ".claude/settings.json"
SETTINGS_LOCAL = REPO / ".claude/settings.local.json"
BASH_DENY_OWNER = REPO / ".claude/hooks/pretooluse-bash-optimizer.sh"
WORKFLOW_DIR = REPO / ".github/workflows"
GIT_HOOKS_SRC = REPO / "scripts/git_hooks"
GIT_HOOKS_LIVE = REPO / ".git/hooks"

# PreToolUse hooks whose entire job is to deny. They are deny rules in their own
# right, not just hook registrations, so they appear in BOTH inventories.
DENY_ONLY_HOOKS = {"scripts/hooks/deny_wakeup_interactive.py"}

# A deny rule's identity = the headline clause of its user-visible reason, i.e.
# everything before the first "（" (the why/incident parenthetical) or "。". The
# reason bodies are long incident write-ups that get edited often; the headline
# is the part that actually names what is being blocked.
DENY_KEY_LEN = 40
DENY_KEY_STOPS = "（。"


# --------------------------------------------------------------------------
# Map parsing
# --------------------------------------------------------------------------

def _parse_map_table(text: str, marker: str) -> list[tuple[str, ...]]:
    """Return the data rows of the Markdown table tagged `<!-- AUDIT:<marker> -->`.

    Each row is a tuple of its cells, backticks stripped, whitespace collapsed.
    """
    tag = f"<!-- AUDIT:{marker} -->"
    idx = text.find(tag)
    if idx < 0:
        raise SystemExit(
            f"[audit_enforcement_map] map is missing the `{tag}` inventory table "
            f"({MAP_PATH.relative_to(REPO)}). The audit cannot verify an inventory "
            "that does not declare itself."
        )
    rows: list[tuple[str, ...]] = []
    seen_header = False
    for line in text[idx + len(tag):].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows or seen_header:
                break
            continue
        cells = [c.strip().strip("`").strip() for c in stripped.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue
        if all(set(c) <= {"-", ":", ""} for c in cells):
            continue
        rows.append(tuple(cells))
    if not rows:
        raise SystemExit(f"[audit_enforcement_map] `{tag}` table has no data rows.")
    return rows


# --------------------------------------------------------------------------
# Disk inventories
# --------------------------------------------------------------------------

def _script_path_from_command(command: str) -> str:
    """Pull the owner script out of a hook `command` string, repo-relative."""
    for token in re.findall(r"[\w./~-]+\.(?:py|sh)", command):
        token = token.replace(str(REPO) + "/", "")
        token = token.removeprefix("./")
        if token.startswith("scripts/") or token.startswith(".claude/"):
            return token
    return f"<unparsed: {command[:60]}>"


def disk_hooks() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for settings_file in (SETTINGS, SETTINGS_LOCAL):
        if not settings_file.exists():
            continue
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        for event, matchers in (data.get("hooks") or {}).items():
            for matcher_block in matchers:
                matcher = matcher_block.get("matcher") or "*"
                for hook in matcher_block.get("hooks") or []:
                    command = hook.get("command", "")
                    found.add((event, matcher, _script_path_from_command(command)))
    return found


def disk_deny() -> set[str]:
    """Deny-rule keys: the leading slice of each user-visible deny reason."""
    keys: set[str] = set()
    text = BASH_DENY_OWNER.read_text(encoding="utf-8")
    for reason in re.findall(r'DENY_REASON="🚫\s*(.+?)"', text, re.S):
        headline = re.sub(r"\s+", " ", reason).strip()
        for stop in DENY_KEY_STOPS:
            headline = headline.split(stop, 1)[0]
        keys.add(headline.strip()[:DENY_KEY_LEN])
    for _event, _matcher, script in disk_hooks():
        if script in DENY_ONLY_HOOKS:
            keys.add(f"hook:{script}")
    return keys


def disk_ci() -> set[tuple[str, str]]:
    jobs: set[tuple[str, str]] = set()
    for wf in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        text = wf.read_text(encoding="utf-8")
        in_jobs = False
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if in_jobs:
                if re.match(r"^\S", line):  # dedented out of the jobs: block
                    in_jobs = False
                    continue
                match = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", line)
                if match:
                    jobs.add((wf.name, match.group(1)))
    return jobs


def disk_git_hooks() -> set[str]:
    return {
        p.name
        for p in GIT_HOOKS_SRC.iterdir()
        if p.is_file() and not p.name.endswith(".sample") and p.name != "install.sh"
    }


def deploy_parity_problems() -> list[str]:
    """Compare the in-repo canonical git hooks against the installed .git/hooks.

    Skipped entirely when .git/hooks is absent (CI checkouts, exported trees).
    """
    if not GIT_HOOKS_LIVE.is_dir():
        return []
    problems: list[str] = []
    for name in sorted(disk_git_hooks()):
        live = GIT_HOOKS_LIVE / name
        if not live.exists():
            problems.append(f"git hook `{name}` exists in scripts/git_hooks/ but is NOT installed in .git/hooks/")
        elif live.read_bytes() != (GIT_HOOKS_SRC / name).read_bytes():
            problems.append(f"git hook `{name}` installed in .git/hooks/ DIFFERS from scripts/git_hooks/ (run scripts/git_hooks/install.sh)")
    return problems


# --------------------------------------------------------------------------
# Diff + report
# --------------------------------------------------------------------------

def _diff(label: str, claimed: set, actual: set, render) -> list[str]:
    problems = []
    for missing in sorted(actual - claimed, key=str):
        problems.append(f"{label}: on disk but NOT in the map -> {render(missing)}")
    for stale in sorted(claimed - actual, key=str):
        problems.append(f"{label}: claimed by the map but NOT on disk -> {render(stale)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print the reconstructed disk inventories")
    args = parser.parse_args()

    text = MAP_PATH.read_text(encoding="utf-8")

    claimed_hooks = {tuple(r[:3]) for r in _parse_map_table(text, "HOOKS")}
    claimed_deny = {r[0] for r in _parse_map_table(text, "DENY")}
    claimed_ci = {tuple(r[:2]) for r in _parse_map_table(text, "CI")}
    claimed_git = {r[0] for r in _parse_map_table(text, "GITHOOKS")}

    actual_hooks = disk_hooks()
    actual_deny = disk_deny()
    actual_ci = disk_ci()
    actual_git = disk_git_hooks()

    if args.verbose:
        for name, inv in (
            ("HOOKS", actual_hooks),
            ("DENY", actual_deny),
            ("CI", actual_ci),
            ("GITHOOKS", actual_git),
        ):
            print(f"--- disk {name} (n={len(inv)}) ---")
            for item in sorted(inv, key=str):
                print(f"  {item}")

    problems: list[str] = []
    problems += _diff("HOOKS", claimed_hooks, actual_hooks, lambda x: f"{x[0]} / matcher={x[1]} / {x[2]}")
    problems += _diff("DENY", claimed_deny, actual_deny, lambda x: f'"{x}"')
    problems += _diff("CI", claimed_ci, actual_ci, lambda x: f"{x[0]} :: job `{x[1]}`")
    problems += _diff("GITHOOKS", claimed_git, actual_git, lambda x: x)
    problems += deploy_parity_problems()

    if problems:
        print("[audit_enforcement_map] Enforcement Layer Map is OUT OF DATE:\n")
        for problem in problems:
            print(f"  - {problem}")
        print(
            f"\nFix: update the AUDIT:* inventory tables in "
            f"{MAP_PATH.relative_to(REPO)} so they match disk (or revert the "
            "enforcement change). A stale index makes agents stack a new layer "
            "on top of an owner that already exists."
        )
        return 1

    print(
        "[audit_enforcement_map] OK — map matches disk: "
        f"{len(actual_hooks)} hooks / {len(actual_deny)} deny rules / "
        f"{len(actual_ci)} CI jobs / {len(actual_git)} git hook files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
