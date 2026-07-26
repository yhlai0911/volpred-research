#!/usr/bin/env python3
"""Audit the global Matt Pocock Agent Skills installation.

The project-level ``.claude/skills`` tree and the user-level
``$HOME/.agents/skills`` tree are different surfaces. This checker verifies
the latter so an agent does not incorrectly report the Matt workflow missing
after inspecting only Claude Code's home directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


REQUIRED_MATT_SKILLS = (
    "ask-matt",
    "grill-with-docs",
    "to-spec",
    "to-tickets",
    "implement",
    "tdd",
    "code-review",
    "writing-great-skills",
    "setup-matt-pocock-skills",
)


def _frontmatter_name(manifest: Path) -> str | None:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return None

    declared_names = [
        line.split(":", maxsplit=1)[1].strip()
        for line in lines[1:closing_index]
        if line.split(":", maxsplit=1)[0].strip() == "name" and ":" in line
    ]
    if len(declared_names) != 1:
        return None
    return declared_names[0].strip("'\"")


def audit(skill_root: Path) -> dict[str, object]:
    """Return a deterministic audit result for the Matt skill suite."""
    root = skill_root.expanduser().resolve()
    missing: list[str] = []
    invalid_manifests: list[dict[str, str | None]] = []
    installed: list[str] = []

    for skill in REQUIRED_MATT_SKILLS:
        manifest = root / skill / "SKILL.md"
        if not manifest.is_file():
            missing.append(skill)
            continue

        declared_name = _frontmatter_name(manifest)
        if declared_name != skill:
            invalid_manifests.append(
                {
                    "skill": skill,
                    "declared_name": declared_name,
                    "reason": "frontmatter_name_mismatch",
                }
            )
            continue
        installed.append(skill)

    return {
        "ok": not missing and not invalid_manifests,
        "skill_root": str(root),
        "required": list(REQUIRED_MATT_SKILLS),
        "installed": installed,
        "missing": missing,
        "invalid_manifests": invalid_manifests,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the global Matt Pocock Agent Skills installation."
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="Agent Skills root (default: $HOME/.agents/skills).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full machine-readable audit result.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = audit(args.skill_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result["ok"]:
        print(
            "Matt skills verified: "
            f"{len(result['installed'])}/{len(result['required'])} "
            f"under {result['skill_root']}"
        )
    else:
        print(
            "Matt skills audit failed: "
            f"missing={result['missing']}, "
            f"invalid_manifests={result['invalid_manifests']}"
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
