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
statements without a nearby print/log/warn/error call or a conservatively proven
returned diagnostic collector. Report mode exits 0;
`--strict` exits 1 when any finding remains unless a baseline is supplied. With
`--baseline`, strict mode fails only for findings not already present in the
baseline.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import Counter, defaultdict, deque
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
    signature: str | None = None

    def key(self) -> tuple[str, int, str, str]:
        return (self.path, self.line, self.exception, self.action)

    def stable_key(self) -> tuple[str, str, str, str] | None:
        if not self.signature:
            return None
        return (self.path, self.exception, self.action, self.signature)


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


def _walk_lexical_scope(scope: ast.AST) -> Iterable[ast.AST]:
    """Walk one function without borrowing evidence from nested definitions."""

    stack = list(reversed(list(ast.iter_child_nodes(scope))))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _nearest_function(
    node: ast.AST,
    parent_map: dict[ast.AST, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = parent_map.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parent_map.get(current)
    return None


def _target_binds_name(target: ast.AST, name: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_binds_name(item, name) for item in target.elts)
    return False


def _target_mutates_name(target: ast.AST, name: str) -> bool:
    """True for rebinding or item/slice assignment on the collector."""

    if _target_binds_name(target, name):
        return True
    return bool(
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id == name
    )


def _empty_list_initializer(value: ast.AST | None) -> bool:
    return bool(
        isinstance(value, ast.List)
        and not value.elts
        or isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "list"
        and not value.args
        and not value.keywords
    )


def _collector_initializer_line(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
    before_line: int,
) -> int | None:
    args = [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]
    if any(arg.arg == name for arg in args):
        return None

    bindings: list[tuple[ast.AST | None, int]] = []
    for node in _walk_lexical_scope(function):
        if getattr(node, "lineno", before_line) >= before_line:
            continue
        if isinstance(node, ast.Assign) and any(
            _target_binds_name(target, name) for target in node.targets
        ):
            bindings.append((node.value, node.lineno))
        elif isinstance(node, ast.AnnAssign) and _target_binds_name(node.target, name):
            bindings.append((node.value, node.lineno))
        elif isinstance(node, (ast.For, ast.AsyncFor)) and _target_binds_name(node.target, name):
            bindings.append((None, node.lineno))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            if any(
                item.optional_vars is not None
                and _target_binds_name(item.optional_vars, name)
                for item in node.items
            ):
                bindings.append((None, node.lineno))
    if len(bindings) != 1 or not _empty_list_initializer(bindings[0][0]):
        return None
    return bindings[0][1]


def _direct_exception_collectors(node: ast.ExceptHandler) -> set[str]:
    """Collectors directly appended before a continue/pass with exception detail."""

    exception_name = node.name if isinstance(node.name, str) else None
    if not exception_name:
        return set()
    collectors: set[str] = set()
    for stmt in node.body:
        action = _silent_action(stmt)
        if action is not None:
            # A default return makes the later function-level return unreachable.
            if isinstance(stmt, ast.Return):
                return set()
            break
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        call = stmt.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Name)
        ):
            continue
        def preserves_exception_detail(payload: ast.AST) -> bool:
            if isinstance(payload, ast.Name):
                return payload.id == exception_name
            if isinstance(payload, ast.Attribute):
                return preserves_exception_detail(payload.value)
            if isinstance(payload, ast.FormattedValue):
                return preserves_exception_detail(payload.value)
            if isinstance(payload, ast.JoinedStr):
                return any(
                    preserves_exception_detail(value)
                    for value in payload.values
                    if isinstance(value, ast.FormattedValue)
                )
            if isinstance(payload, ast.Call):
                return bool(
                    isinstance(payload.func, ast.Name)
                    and payload.func.id in {"repr", "str"}
                    and len(payload.args) == 1
                    and not payload.keywords
                    and preserves_exception_detail(payload.args[0])
                )
            if isinstance(payload, (ast.Tuple, ast.List, ast.Set)):
                return any(preserves_exception_detail(item) for item in payload.elts)
            if isinstance(payload, ast.Dict):
                return any(
                    item is not None and preserves_exception_detail(item)
                    for item in payload.values
                )
            if isinstance(payload, ast.BinOp) and isinstance(payload.op, ast.Add):
                return preserves_exception_detail(payload.left) or preserves_exception_detail(
                    payload.right
                )
            return False

        payload_nodes = [*call.args, *(kw.value for kw in call.keywords)]
        if any(preserves_exception_detail(payload) for payload in payload_nodes):
            collectors.add(call.func.value.id)
    return collectors


def _collector_return_line(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
    after_line: int,
) -> int | None:
    # Only an unconditional top-level return is accepted.  A nested/conditional
    # return is not proof that every swallowed exception reaches an observer.
    def directly_returns_collector(value: ast.AST) -> bool:
        if isinstance(value, ast.Name):
            return value.id == name
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            return any(directly_returns_collector(item) for item in value.elts)
        if isinstance(value, ast.Dict):
            return any(
                item is not None and directly_returns_collector(item)
                for item in value.values
            )
        return False

    for stmt in function.body:
        if not isinstance(stmt, ast.Return) or stmt.lineno <= after_line or stmt.value is None:
            continue
        if directly_returns_collector(stmt.value):
            return stmt.lineno
    return None


def _collector_survives_to_return(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    name: str,
    initializer_line: int,
    return_line: int,
) -> bool:
    scope_nodes = list(_walk_lexical_scope(function))
    parent_map = {
        child: parent
        for parent in [function, *scope_nodes]
        for child in ast.iter_child_nodes(parent)
    }

    for node in scope_nodes:
        line = getattr(node, "lineno", -1)
        if not initializer_line < line < return_line:
            continue
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            parent = parent_map.get(node)
            call = parent_map.get(parent) if parent is not None else None
            # This deliberately tiny proof accepts exactly a direct list.append
            # receiver.  Any other read can leak an alias before or after the
            # handler (`identity(bad)`, `[bad]`, attributes, subscripts, etc.),
            # so it is not evidence that the diagnostic reaches the caller.
            if not (
                isinstance(parent, ast.Attribute)
                and parent.value is node
                and parent.attr == "append"
                and isinstance(call, ast.Call)
                and call.func is parent
            ):
                return False
        if isinstance(node, ast.Return):
            # Any earlier conditional/default return is a path on which the
            # collector never reaches the accepted top-level return.
            return False
        if isinstance(node, (ast.Raise, ast.Yield, ast.YieldFrom)):
            return False
        if (
            isinstance(node, ast.While)
            and isinstance(node.test, ast.Constant)
            and node.test.value is True
        ):
            return False
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return False
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            return False
        if isinstance(node, ast.Assign) and any(
            _target_mutates_name(target, name) for target in node.targets
        ):
            return False
        if isinstance(node, ast.AnnAssign) and _target_mutates_name(node.target, name):
            return False
        if isinstance(node, ast.AugAssign) and _target_mutates_name(node.target, name):
            return False
        if isinstance(node, ast.Delete) and any(
            _target_mutates_name(target, name) for target in node.targets
        ):
            return False
    return True


def _has_returned_diagnostic_collector(
    node: ast.ExceptHandler,
    parent_map: dict[ast.AST, ast.AST],
) -> bool:
    function = _nearest_function(node, parent_map)
    if function is None:
        return False
    for name in _direct_exception_collectors(node):
        initializer_line = _collector_initializer_line(
            function,
            name=name,
            before_line=node.lineno,
        )
        if initializer_line is None:
            continue
        return_line = _collector_return_line(
            function,
            name=name,
            after_line=node.lineno,
        )
        if return_line is not None and _collector_survives_to_return(
            function,
            name=name,
            initializer_line=initializer_line,
            return_line=return_line,
        ):
            return True
    return False


def _has_observable_diagnostic(
    node: ast.ExceptHandler,
    parent_map: dict[ast.AST, ast.AST],
) -> bool:
    for subnode in ast.walk(node):
        if not isinstance(subnode, ast.Call):
            continue
        name = _call_name(subnode)
        if name in OBSERVABLE_CALL_NAMES or name.startswith("_warn"):
            return True
    return _has_returned_diagnostic_collector(node, parent_map)


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


def _line_has_silent_ok(source_lines: list[str], line_no: int | None) -> bool:
    """Accept the marker on the `except ...:` header line, not just the body."""
    if line_no is None or not 1 <= line_no <= len(source_lines):
        return False
    return "silent-ok:" in source_lines[line_no - 1]


def _has_silent_ok_comment(source_lines: list[str], stmt: ast.stmt) -> bool:
    start = getattr(stmt, "lineno", None)
    end = getattr(stmt, "end_lineno", start)
    if start is None or end is None:
        return False
    for line_no in range(start, end + 1):
        if 1 <= line_no <= len(source_lines) and "silent-ok:" in source_lines[line_no - 1]:
            return True
    return False


def _scope_name(node: ast.ExceptHandler, parent_map: dict[ast.AST, ast.AST]) -> str:
    scopes: list[str] = []
    current: ast.AST | None = node
    while current is not None:
        parent = parent_map.get(current)
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scopes.append(parent.name)
        current = parent
    return ".".join(reversed(scopes)) if scopes else "<module>"


def _normalized_stmt(stmt: ast.stmt) -> str:
    return ast.dump(stmt, annotate_fields=True, include_attributes=False)


def _finding_signature(
    node: ast.ExceptHandler,
    *,
    exception: str,
    action: str,
    parent_map: dict[ast.AST, ast.AST],
) -> str:
    """Return a line-insensitive signature for one silent fallback finding.

    The signature intentionally excludes absolute line numbers. It uses the
    enclosing scope plus the normalized handler body, and baseline diffing treats
    the key as a multiset so adding a second identical fallback in the same scope
    still produces a new finding.
    """

    payload = {
        "schema": "silent-fallback-signature.v1",
        "scope": _scope_name(node, parent_map),
        "exception": exception,
        "action": action,
        "handler_body": [_normalized_stmt(stmt) for stmt in node.body],
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"v1:{digest}"


def audit_file(path: Path, *, root: Path = ROOT) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    parent_map = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _has_observable_diagnostic(node, parent_map) or _reraises(node):
            continue
        for stmt in node.body:
            action = _silent_action(stmt)
            if action is None:
                continue
            if _has_silent_ok_comment(source_lines, stmt) or _line_has_silent_ok(
                source_lines, node.lineno
            ):
                continue
            exception = _exception_name(node)
            findings.append(
                Finding(
                    path=_relative(path, root),
                    line=node.lineno,
                    exception=exception,
                    action=action,
                    signature=_finding_signature(
                        node,
                        exception=exception,
                        action=action,
                        parent_map=parent_map,
                    ),
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
            signature=str(raw["signature"]) if raw.get("signature") else None,
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
    current_unmatched = set(range(len(findings)))
    baseline_unmatched = set(range(len(baseline)))

    def match_by_key(key_fn: Any) -> None:
        baseline_by_key: dict[Any, deque[int]] = defaultdict(deque)
        for idx in sorted(baseline_unmatched):
            key = key_fn(baseline[idx])
            if key is not None:
                baseline_by_key[key].append(idx)
        for idx in sorted(list(current_unmatched)):
            key = key_fn(findings[idx])
            if key is None:
                continue
            candidates = baseline_by_key.get(key)
            if not candidates:
                continue
            baseline_idx = candidates.popleft()
            current_unmatched.remove(idx)
            baseline_unmatched.remove(baseline_idx)

    # Prefer line-insensitive signatures. Fall back to legacy exact keys so old
    # test fixtures and hand-written baselines remain readable.
    match_by_key(lambda item: item.stable_key())
    if any(item.signature is None for item in findings) or any(
        item.signature is None for item in baseline
    ):
        match_by_key(lambda item: ("legacy", *item.key()))

    new_findings = sorted((findings[idx] for idx in current_unmatched), key=lambda item: item.key())
    resolved_findings = sorted(
        (baseline[idx] for idx in baseline_unmatched),
        key=lambda item: item.key(),
    )
    return new_findings, resolved_findings


def _finding_to_raw(item: Finding) -> dict[str, Any]:
    raw = asdict(item)
    if raw.get("signature") is None:
        raw.pop("signature", None)
    return raw


def write_baseline(path: Path, findings: list[Finding]) -> None:
    payload = {
        "schema": "silent_fallback_baseline.v2",
        "description": (
            "Known silent-fallback audit findings. CI strict mode fails only when "
            "current findings introduce line-insensitive signatures absent from "
            "this baseline."
        ),
        "count": len(findings),
        "findings": [_finding_to_raw(item) for item in findings],
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
