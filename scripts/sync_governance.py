"""Inject the shared governance region into CLAUDE.md and AGENTS.md.

`config/governance_shared.md` is the single source of truth for every section
both agents must obey. This script is its only writer into the two governance
files; `tests/test_governance_sync.py` fails the build when they drift.

Why copy instead of pointing at the canonical file: each agent auto-loads only
its own governance file, so a pointer depends on the other one choosing to
follow it. That dependency has already failed in practice -- a session handed an
explicit instruction to read AGENTS.md checked only its line count, and so never
saw the graphify rule that lives nowhere else. Copying keeps both files
self-sufficient; the gate keeps the copies honest.

Each shared section is injected between its own marker pair, so the two files
keep their existing order and their unique sections stay put:

    <!-- shared:Agent skills:begin -->
    ...generated, do not edit here...
    <!-- shared:Agent skills:end -->

Usage:
    uv run python scripts/sync_governance.py --check   # verify, write nothing
    uv run python scripts/sync_governance.py --apply   # rewrite both files
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "config" / "governance_shared.md"
TARGETS = (ROOT / "CLAUDE.md", ROOT / "AGENTS.md")

_SECTION_RE = re.compile(r"^<!-- section:(?P<name>.+?) -->$", re.M)
_BANNER = (
    "<!-- 本區由 scripts/sync_governance.py 從 config/governance_shared.md 生成。"
    "請改 canonical 來源，不要直接改這裡。 -->"
)


def load_canonical() -> dict[str, str]:
    """Return {section name: body} from the canonical file, in file order."""
    text = CANONICAL.read_text(encoding="utf-8")
    marks = list(_SECTION_RE.finditer(text))
    if not marks:
        raise SystemExit(f"no <!-- section:... --> markers in {CANONICAL}")
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        name = m.group("name").strip()
        if name in out:
            raise SystemExit(f"duplicate canonical section: {name}")
        out[name] = text[m.end():end].strip("\n")
    return out


def _markers(name: str) -> tuple[str, str]:
    return f"<!-- shared:{name}:begin -->", f"<!-- shared:{name}:end -->"


def render(name: str, body: str) -> str:
    begin, end = _markers(name)
    return f"{begin}\n{_BANNER}\n{body}\n{end}"


def inject(text: str, sections: dict[str, str]) -> tuple[str, list[str]]:
    """Replace every marked region present in `text`. Returns (new_text, injected)."""
    injected: list[str] = []
    for name, body in sections.items():
        begin, end = _markers(name)
        if begin not in text:
            continue
        pattern = re.compile(
            re.escape(begin) + r".*?" + re.escape(end), re.S
        )
        if not pattern.search(text):
            raise SystemExit(f"unbalanced markers for {name!r}")
        text = pattern.sub(lambda _m: render(name, body), text, count=1)
        injected.append(name)
    return text, injected


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sections = load_canonical()
    drifted: list[str] = []
    for target in TARGETS:
        current = target.read_text(encoding="utf-8")
        updated, injected = inject(current, sections)
        missing = [n for n in sections if _markers(n)[0] not in current]
        if missing:
            print(
                f"{target.name}: no marker for {len(missing)} section(s): "
                + ", ".join(missing)
            )
        if updated != current:
            drifted.append(target.name)
            if args.apply:
                target.write_text(updated, encoding="utf-8")
                print(f"{target.name}: synced {len(injected)} section(s)")
        elif args.apply:
            print(f"{target.name}: already in sync ({len(injected)} section(s))")

    if args.check:
        if drifted:
            print("governance sync: DRIFT in " + ", ".join(drifted))
            return 1
        print(f"governance sync: OK ({len(sections)} shared section(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
