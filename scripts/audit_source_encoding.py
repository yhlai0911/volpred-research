#!/usr/bin/env python3
"""CI sweep: every .py under src/ tests/ scripts/ must be (1) strict-UTF-8
decodable, (2) free of U+FFFD replacement chars, (3) py_compile clean.

Zero tolerance — no baseline. A corrupted test file is a silently-vanished
gate (same failure class as no-silent-fallback): tests/test_prepublish_audit.py
mojibake broke pytest collection and 19 image-URL regression tests stopped
running unnoticed (docs/error_log.md 2026-07-02 14:11); the first run of this
script immediately caught a second live case in tests/test_alerts.py.

Usage:
    python scripts/audit_source_encoding.py [--roots src tests scripts]

Exit codes:
    0 = OK (all files decode, no U+FFFD, all compile)
    1 = FAIL (at least one file corrupted; each printed with byte/line position)
    2 = environment error (a root directory missing)

Escape hatch: a line that legitimately needs a literal U+FFFD (e.g. an
encoding-handling test) must carry an inline `# fffd-ok: <reason>` marker on
the SAME line; unmarked U+FFFD fails. Decode/compile failures have no escape.

Stdlib-only so CI can run it on a bare python without uv sync.
"""
from __future__ import annotations

import argparse
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = ("src", "tests", "scripts")
SKIP_PARTS = {".venv", "node_modules", "__pycache__", ".git", "_legacy"}

FFFD = "�"  # fffd-ok: the detector's own needle
FFFD_OK_MARKER = "# fffd-ok:"


def iter_py_files(roots: list[str], repo_root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        base = repo_root / root
        candidates = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for p in candidates:
            if p.suffix != ".py" or SKIP_PARTS.intersection(p.parts):
                continue
            files.append(p)
    return files


def check_file(path: Path) -> list[str]:
    """Return list of problem descriptions for one file (empty = clean)."""
    problems: list[str] = []
    raw = path.read_bytes()

    # 1) strict utf-8 decode — report every bad byte offset, not just the first
    text: str | None = None
    pos = 0
    remaining = raw
    while True:
        try:
            remaining.decode("utf-8")
            break
        except UnicodeDecodeError as e:
            off = pos + e.start
            line_no = raw[:off].count(b"\n") + 1
            problems.append(
                f"utf-8 decode fail at byte {off} (line {line_no}): "
                f"{raw[off:off + 8]!r}"
            )
            pos = off + 1
            remaining = raw[pos:]
            if len(problems) >= 20:  # enough to locate the damage
                problems.append("... (more decode errors truncated)")
                break
    if not problems:
        text = raw.decode("utf-8")

    # 2) U+FFFD replacement char — mojibake symptom even when decode succeeds
    if text is not None:
        for i, line in enumerate(text.split("\n"), 1):
            if FFFD in line and FFFD_OK_MARKER not in line:
                problems.append(
                    f"U+FFFD replacement char at line {i} "
                    f"(add '{FFFD_OK_MARKER} <reason>' only if intentional)"
                )

    # 3) py_compile — catches syntax-level corruption decode checks miss
    if not problems:
        try:
            py_compile.compile(str(path), doraise=True, quiet=1)
        except py_compile.PyCompileError as e:
            problems.append(f"py_compile fail: {e.msg.strip().splitlines()[-1]}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--roots",
        nargs="+",
        default=list(DEFAULT_ROOTS),
        help=(
            "directories or individual .py files under repo root to sweep "
            f"(default: {' '.join(DEFAULT_ROOTS)})"
        ),
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help=(
            "repo root the --roots are resolved against (default: this script's own repo). "
            "The pre-commit hook runs a copy of this script extracted from a trusted ref into "
            "a temp dir, so its __file__ says nothing about which tree is being audited."
        ),
    )
    args = ap.parse_args()
    repo_root = args.root.resolve()

    missing = [r for r in args.roots if not (repo_root / r).exists()]
    if missing:
        print(f"[audit-encoding] FAIL: root path(s) not found: {missing}", file=sys.stderr)
        return 2

    files = iter_py_files(args.roots, repo_root)
    if not files:
        # The roots exist (checked above) but nothing was collected, so the
        # filter is broken -- and every check below is a universal quantifier
        # over `files`. With none, `bad` stays empty and this prints
        # "0 files checked -> all clean -> OK": a gate that verified nothing
        # reporting success. That is the shape this whole script exists to
        # prevent, one level up (docs/error_log.md 2026-08-04, all([]) is True).
        print(
            f"[audit-encoding] FAIL: collected 0 files from {args.roots} under "
            f"{repo_root}. The roots exist, so the collector is broken; a sweep "
            "that sees nothing must not report clean.",
            file=sys.stderr,
        )
        return 2

    bad: dict[Path, list[str]] = {}
    for path in files:
        problems = check_file(path)
        if problems:
            bad[path] = problems

    if bad:
        for path, problems in bad.items():
            rel = path.relative_to(repo_root)
            for prob in problems:
                print(f"BAD {rel}: {prob}", file=sys.stderr)
        print(
            f"[audit-encoding] {len(files)} files checked -> "
            f"{len(bad)} corrupted  -> FAIL",
            file=sys.stderr,
        )
        print(
            "[audit-encoding] A corrupted .py silently kills its gate "
            "(pytest collection / import). Rebuild the damaged lines from git "
            "history or semantics — do NOT delete the file to pass the sweep. "
            "Background: docs/error_log.md 2026-07-02 14:11.",
            file=sys.stderr,
        )
        return 1

    print(f"[audit-encoding] {len(files)} files checked -> all clean  -> OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
