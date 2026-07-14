#!/usr/bin/env python3
"""Fail if a test module imports a `volpred.*` name the source tree does not define.

The failure this exists for: a test file lands on main while the source change it
depends on stays behind (a partial commit, a worktree auto-commit, a bad merge).
pytest then dies at *collection* — `ImportError: cannot import name X from ...` —
and the entire suite goes red before a single test runs. CI catches it, but only
after the push. This runs pre-push, on the tree being pushed.

Concretely: 0fef6fa3b put tests/test_arc_dedup_calibration.py on main without
`arc_dedup.ARC_SIGNATURE_SCHEMA_VERSION`, and every run of the Test Suite was red
until the source commit followed (docs/error_log.md 2026-07-14).

Why AST and not `pytest --collect-only`: collection needs config/ + storage/ +
installed deps, so it cannot run against the ~7 MB source-only tree the pre-push
hook extracts (measured: 121 collection errors from missing project dirs alone).
Import resolution needs nothing but the source, so that is what we check.

Exit 0 = clean, 1 = a test imports something that is not there, 2 = could not run.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

TEST_ROOTS = ("tests", "scripts/tests")
PKG_ROOT = "src"
PKG = "volpred"

# A module doing either of these binds names we cannot see statically; checking it
# would produce false BADs, so we report it as skipped rather than guess.
OPAQUE_MARKERS = ("globals()[", "setattr(sys.modules")


def _module_path(root: Path, dotted: str) -> Path | None:
    """Resolve `volpred.publisher.arc_dedup` to its .py file (or package __init__)."""
    rel = Path(*dotted.split("."))
    for cand in (root / PKG_ROOT / rel.with_suffix(".py"), root / PKG_ROOT / rel / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def _module_bindings(path: Path) -> tuple[set[str], bool]:
    """Top-level names a module binds, plus whether it is opaque to static reading.

    Raises SyntaxError if the source does not parse — a source module that cannot be
    parsed cannot be imported either, so the caller reports it rather than waving it
    through as "opaque".
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    if any(m in src for m in OPAQUE_MARKERS):
        return set(), True
    tree = ast.parse(src, filename=str(path))

    names: set[str] = set()
    opaque = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    opaque = True  # re-exports we cannot enumerate
                else:
                    names.add(alias.asname or alias.name)
    return names, opaque


def _submodule_exists(root: Path, pkg_dotted: str, name: str) -> bool:
    """`from volpred.publisher import arc_dedup` — the name is a submodule, not a binding."""
    return _module_path(root, f"{pkg_dotted}.{name}") is not None


def audit(root: Path) -> tuple[list[str], int, int]:
    bad: list[str] = []
    checked = 0
    files = 0

    test_files = [
        p
        for test_root in TEST_ROOTS
        if (root / test_root).is_dir()
        for p in sorted((root / test_root).rglob("test_*.py"))
    ]

    for tf in test_files:
        files += 1
        try:
            tree = ast.parse(tf.read_text(encoding="utf-8", errors="replace"), filename=str(tf))
        except SyntaxError as exc:  # silent-ok: recorded as a BAD finding below, which fails the gate
            bad.append(f"BAD {tf.relative_to(root)}:{exc.lineno} — test module does not parse: {exc.msg}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level:
                continue
            mod = node.module or ""
            if mod != PKG and not mod.startswith(f"{PKG}."):
                continue

            mod_file = _module_path(root, mod)
            if mod_file is None:
                rel = tf.relative_to(root)
                bad.append(f"BAD {rel}:{node.lineno} — imports from '{mod}', which does not exist in {PKG_ROOT}/")
                continue

            try:
                bindings, opaque = _module_bindings(mod_file)
            except SyntaxError as exc:  # silent-ok: recorded as a BAD finding below, which fails the gate
                rel_src = mod_file.relative_to(root)
                bad.append(f"BAD {rel_src}:{exc.lineno} — source module does not parse: {exc.msg}")
                continue
            if opaque:
                continue

            for alias in node.names:
                if alias.name == "*":
                    continue
                checked += 1
                if alias.name in bindings:
                    continue
                if _submodule_exists(root, mod, alias.name):
                    continue
                rel = tf.relative_to(root)
                bad.append(
                    f"BAD {rel}:{node.lineno} — '{alias.name}' is imported from '{mod}' "
                    f"but {mod_file.relative_to(root)} does not define it"
                )

    return bad, checked, files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="tree to audit (default: cwd)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not (root / PKG_ROOT / PKG).is_dir():
        print(f"[audit-test-imports] cannot audit: {root}/{PKG_ROOT}/{PKG} is not a directory", file=sys.stderr)
        return 2

    bad, checked, files = audit(root)
    for line in bad:
        print(line)
    print(f"[audit-test-imports] {files} test files checked, {checked} volpred imports resolved, {len(bad)} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
