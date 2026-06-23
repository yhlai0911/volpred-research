"""Audit Python exception handlers that fail open without diagnostics.

The 2026-06-22/23 error-log sweep repeatedly found the same bug family:
JSON/date/read failures were caught and converted to a default value, but the
caller received no warning. This script makes that pattern measurable.

Usage:
  uv run python scripts/audit_silent_fallbacks.py
  uv run python scripts/audit_silent_fallbacks.py --json
  uv run python scripts/audit_silent_fallbacks.py --strict

The audit is intentionally heuristic. It reports suspect exception handlers in
`scripts/` and `src/` that contain `pass`, `continue`, or default-ish `return`
statements without a nearby print/log/warn/error call. Report mode exits 0;
`--strict` exits 1 when any finding remains.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (ROOT / "scripts", ROOT / "src")
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "tests"}

OBSERVABLE_CALL_NAMES = {
    "critical",
    "debug",
    "error",
    "exception",
    "info",
    "notify",
    "print",
    "send_alert",
    "warn",
    "warning",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    exception: str
    action: str


def _relative(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def iter_python_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else ROOT / raw_path
        if path.is_file() and path.suffix == ".py":
            files.append(path)
            continue
        if not path.exists():
            continue
        for candidate in path.rglob("*.py"):
            if any(part in SKIP_DIRS for part in candidate.parts):
                continue
            files.append(candidate)
    return sorted(set(files))


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _has_observable_diagnostic(node: ast.ExceptHandler) -> bool:
    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue
        name = _call_name(subnode)
        if name in OBSERVABLE_CALL_NAMES or name.startswith("_warn"):
            return True
    return False


def _reraises(node: ast.ExceptHandler) -> bool:
    return any(isinstance(subnode, ast.Raise) for subnode in ast.walk(node))


def _exception_name(node: ast.ExceptHandler) -> str:
    exc = node.type
    if exc is None:
        return "bare"
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    if isinstance(exc, ast.Tuple):
        names: list[str] = []
        for elt in exc.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(elt.attr)
        return "|".join(names) if names else ast.unparse(exc)
    return ast.unparse(exc)


def _return_action(stmt: ast.Return) -> str | None:
    value = stmt.value
    if value is None:
        return "return None"
    if isinstance(value, ast.Constant):
        if value.value in (None, False, True, 0, -1, ""):
            return f"return {value.value!r}"
        return None
    if isinstance(value, ast.List) and not value.elts:
        return "return []"
    if isinstance(value, ast.Tuple) and not value.elts:
        return "return ()"
    if isinstance(value, ast.Set) and not value.elts:
        return "return set()"
    if isinstance(value, ast.Dict) and not value.keys:
        return "return {}"
    return None


def _silent_action(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, ast.Pass):
        return "pass"
    if isinstance(stmt, ast.Continue):
        return "continue"
    if isinstance(stmt, ast.Return):
        return _return_action(stmt)
    return None


def audit_file(path: Path, *, root: Path = ROOT) -> list[Finding]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _has_observable_diagnostic(node) or _reraises(node):
            continue
        for stmt in node.body:
            action = _silent_action(stmt)
            if action is None:
                continue
            findings.append(
                Finding(
                    path=_relative(path, root),
                    line=node.lineno,
                    exception=_exception_name(node),
                    action=action,
                )
            )
            break
    return sorted(findings, key=lambda item: (item.line, item.action))


def audit_paths(paths: Iterable[Path], *, root: Path = ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_python_files(paths):
        try:
            findings.extend(audit_file(path, root=root))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(
                f"[silent-fallback-audit] WARN scan failed path={_relative(path, root)} "
                f"error={type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    return sorted(findings, key=lambda item: (item.path, item.line, item.action))


def _human_report(findings: list[Finding], *, limit: int | None) -> None:
    print(f"[silent-fallback-audit] findings={len(findings)}")
    rows = findings if limit is None else findings[:limit]
    for item in rows:
        print(f"{item.path}:{item.line} except {item.exception}: {item.action}")
    if limit is not None and len(findings) > limit:
        print(f"... {len(findings) - limit} more (rerun with --limit 0 for all)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=list(DEFAULT_TARGETS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=80,
        help="maximum human rows to print; 0 means no limit",
    )
    args = parser.parse_args()

    findings = audit_paths(args.paths)
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        _human_report(findings, limit=None if args.limit == 0 else args.limit)

    return 1 if args.strict and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
