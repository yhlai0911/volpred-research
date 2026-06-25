"""Audit Python exception handlers that fail open without diagnostics.

The 2026-06-22/23 error-log sweep repeatedly found the same bug family:
JSON/date/read failures were caught and converted to a default value, but the
caller received no warning. This script makes that pattern measurable.

Usage:
  uv run python scripts/audit_silent_fallbacks.py
  uv run python scripts/audit_silent_fallbacks.py --json
  uv run python scripts/audit_silent_fallbacks.py --strict
  uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json
  uv run python scripts/audit_silent_fallbacks.py --write-baseline storage/qa/silent_fallback_baseline.json

The audit is intentionally heuristic. It reports suspect exception handlers in
`scripts/` and `src/` that contain `pass`, `continue`, or default-ish `return`
statements without a nearby print/log/warn/error call. Report mode exits 0;
`--strict` exits 1 when any finding remains unless a baseline is supplied. With
`--baseline`, strict mode fails only for findings not already present in the
baseline.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (ROOT / "scripts", ROOT / "src" / "volpred", ROOT / ".claude" / "hooks")
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

    def key(self) -> tuple[str, int, str, str]:
        return (self.path, self.line, self.exception, self.action)


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


def _has_silent_ok_comment(source_lines: list[str], stmt: ast.stmt) -> bool:
    start = getattr(stmt, "lineno", None)
    end = getattr(stmt, "end_lineno", start)
    if start is None or end is None:
        return False
    for line_no in range(start, end + 1):
        if 1 <= line_no <= len(source_lines) and "silent-ok:" in source_lines[line_no - 1]:
            return True
    return False


def audit_file(path: Path, *, root: Path = ROOT) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
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
            if _has_silent_ok_comment(source_lines, stmt):
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


def _finding_from_raw(raw: dict[str, Any], *, baseline_path: Path) -> Finding:
    try:
        return Finding(
            path=str(raw["path"]),
            line=int(raw["line"]),
            exception=str(raw["exception"]),
            action=str(raw["action"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid baseline finding in {baseline_path}: {raw!r}") from exc


def load_baseline(path: Path) -> list[Finding]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"baseline read failed: {path} ({type(exc).__name__}: {exc})") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"baseline JSON parse failed: {path} ({exc})") from exc

    if isinstance(raw, dict):
        raw_findings = raw.get("findings")
    else:
        raw_findings = raw
    if not isinstance(raw_findings, list):
        raise ValueError(f"baseline must be a list or object with findings list: {path}")
    return sorted(
        (_finding_from_raw(item, baseline_path=path) for item in raw_findings),
        key=lambda item: item.key(),
    )


def diff_against_baseline(
    findings: list[Finding],
    baseline: list[Finding],
) -> tuple[list[Finding], list[Finding]]:
    current_by_key = {item.key(): item for item in findings}
    baseline_by_key = {item.key(): item for item in baseline}
    new_findings = [current_by_key[key] for key in sorted(current_by_key.keys() - baseline_by_key.keys())]
    resolved_findings = [
        baseline_by_key[key] for key in sorted(baseline_by_key.keys() - current_by_key.keys())
    ]
    return new_findings, resolved_findings


def write_baseline(path: Path, findings: list[Finding]) -> None:
    payload = {
        "schema": "silent_fallback_baseline.v1",
        "description": (
            "Known silent-fallback audit findings. CI strict mode fails only when "
            "current findings introduce keys absent from this baseline."
        ),
        "count": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _human_report(findings: list[Finding], *, limit: int | None) -> None:
    print(f"[silent-fallback-audit] findings={len(findings)}")
    if findings:
        by_action = Counter(item.action for item in findings)
        by_root = Counter(item.path.split("/", 1)[0] for item in findings)
        by_path = Counter(item.path for item in findings)
        action_summary = ", ".join(f"{action}={count}" for action, count in by_action.most_common())
        root_summary = ", ".join(f"{root}={count}" for root, count in by_root.most_common())
        path_summary = ", ".join(f"{path}={count}" for path, count in by_path.most_common(8))
        print(f"[silent-fallback-audit] by_action: {action_summary}")
        print(f"[silent-fallback-audit] by_root: {root_summary}")
        print(f"[silent-fallback-audit] top_paths: {path_summary}")
    rows = findings if limit is None else findings[:limit]
    for item in rows:
        print(f"{item.path}:{item.line} except {item.exception}: {item.action}")
    if limit is not None and len(findings) > limit:
        print(f"... {len(findings) - limit} more (rerun with --limit 0 for all)")


def _baseline_report(
    *,
    baseline_path: Path,
    current_count: int,
    baseline: list[Finding],
    new_findings: list[Finding],
    resolved_findings: list[Finding],
    limit: int | None,
) -> None:
    print(
        "[silent-fallback-audit] "
        f"findings={current_count} baseline={baseline_path} baseline_findings={len(baseline)} "
        f"new={len(new_findings)} resolved={len(resolved_findings)}"
    )
    rows = new_findings if limit is None else new_findings[:limit]
    for item in rows:
        print(f"NEW {item.path}:{item.line} except {item.exception}: {item.action}")
    if limit is not None and len(new_findings) > limit:
        print(f"... {len(new_findings) - limit} more new findings (rerun with --limit 0 for all)")
    if resolved_findings:
        print(
            "[silent-fallback-audit] "
            f"note: {len(resolved_findings)} baseline finding(s) no longer present; "
            "reduce the baseline in a separate cleanup commit."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=list(DEFAULT_TARGETS))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="JSON baseline file; with --strict, fail only for findings absent from this baseline",
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help="write the current findings to this baseline file and exit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=80,
        help="maximum human rows to print; 0 means no limit",
    )
    args = parser.parse_args()

    findings = audit_paths(args.paths)
    if args.write_baseline:
        write_baseline(args.write_baseline, findings)
        print(f"[silent-fallback-audit] wrote baseline={args.write_baseline} findings={len(findings)}")
        return 0

    baseline: list[Finding] | None = None
    new_findings: list[Finding] = []
    resolved_findings: list[Finding] = []
    if args.baseline:
        try:
            baseline = load_baseline(args.baseline)
        except ValueError as exc:
            print(f"[silent-fallback-audit] ERROR {exc}", file=sys.stderr)
            return 2
        new_findings, resolved_findings = diff_against_baseline(findings, baseline)

    if args.json and baseline is not None:
        print(
            json.dumps(
                {
                    "findings": [asdict(item) for item in findings],
                    "baseline": str(args.baseline),
                    "baseline_count": len(baseline),
                    "new_findings": [asdict(item) for item in new_findings],
                    "resolved_findings": [asdict(item) for item in resolved_findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        if baseline is None:
            _human_report(findings, limit=None if args.limit == 0 else args.limit)
        else:
            _baseline_report(
                baseline_path=args.baseline,
                current_count=len(findings),
                baseline=baseline,
                new_findings=new_findings,
                resolved_findings=resolved_findings,
                limit=None if args.limit == 0 else args.limit,
            )

    if args.strict and baseline is not None:
        return 1 if new_findings else 0
    return 1 if args.strict and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
