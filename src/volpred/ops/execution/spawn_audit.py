"""Mechanical census for production AI CLI process boundaries.

The registry guard is useful only if a new ``claude``, ``codex`` or ``agy``
launcher cannot appear outside it.  This module discovers those launchers from
Python ASTs, classifies metadata-only probes separately, and verifies that a
business invocation is preceded by the canonical authorization call.

It deliberately reports uncertainty as ``unclassified``.  A source audit that
silently guesses is another bypass.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


AGENTIC_EXECUTABLES = frozenset({"agy", "claude", "codex"})
SUBPROCESS_SPAWNERS = frozenset(
    {"Popen", "call", "check_call", "check_output", "run"}
)
DIAGNOSTIC_SUBCOMMANDS = frozenset(
    {"--help", "--version", "-V", "-h", "help"}
)
SEARCH_DIRS = ("scripts", "src")


class SpawnKind(StrEnum):
    BUSINESS = "business"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class SpawnBoundary:
    path: str
    line: int
    executable: str
    kind: SpawnKind
    guarded: bool


@dataclass(frozen=True)
class SpawnAuditReport:
    boundaries: tuple[SpawnBoundary, ...]
    unclassified: tuple[str, ...]

    @property
    def unguarded(self) -> tuple[SpawnBoundary, ...]:
        return tuple(
            boundary
            for boundary in self.boundaries
            if boundary.kind is SpawnKind.BUSINESS and not boundary.guarded
        )

    def files(self, kind: SpawnKind) -> set[str]:
        """Return each launcher's dominant kind; business beats diagnostics."""
        business = {
            boundary.path
            for boundary in self.boundaries
            if boundary.kind is SpawnKind.BUSINESS
        }
        if kind is SpawnKind.BUSINESS:
            return business
        return {
            boundary.path
            for boundary in self.boundaries
            if boundary.kind is SpawnKind.DIAGNOSTIC
            and boundary.path not in business
        }

    def format_violations(self) -> str:
        rows = [
            f"{item.path}:{item.line}: {item.executable} business spawn "
            "has no preceding authorize_provider_spawn()"
            for item in self.unguarded
        ]
        rows.extend(f"unclassified: {item}" for item in self.unclassified)
        return "\n".join(rows)


@dataclass
class _Scope:
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef
    names: dict[str, set[str]]


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _strings(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _value_strings(node: ast.AST, names: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(names.get(node.id, ()))
    if isinstance(node, ast.Call):
        called = _call_name(node)
        return _strings(node) | set(names.get(called, ()))
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        return _value_strings(node.elts[0], names)
    return set()


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name)]


def _scope_names(
    node: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef,
    inherited: dict[str, set[str]],
) -> dict[str, set[str]]:
    names = {key: set(value) for key, value in inherited.items()}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        positional = [*node.args.posonlyargs, *node.args.args]
        default_offset = len(positional) - len(node.args.defaults)
        for index, default in enumerate(node.args.defaults, start=default_offset):
            values = _value_strings(default, names)
            if values:
                names[positional[index].arg] = values
    class _Assignments(ast.NodeVisitor):
        def __init__(self, root: ast.AST) -> None:
            self.root = root
            self.items: list[ast.Assign | ast.AnnAssign] = []

        def visit_Assign(self, child: ast.Assign) -> None:
            self.items.append(child)
            self.generic_visit(child)

        def visit_AnnAssign(self, child: ast.AnnAssign) -> None:
            self.items.append(child)
            self.generic_visit(child)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is self.root:
                self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is self.root:
                self.generic_visit(child)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            if child is self.root:
                self.generic_visit(child)

    visitor = _Assignments(node)
    visitor.visit(node)
    changed = True
    while changed:
        changed = False
        for child in visitor.items:
            value = child.value
            if value is None:
                continue
            values = _value_strings(value, names)
            if not values:
                continue
            for name in _assignment_names(child):
                combined = names.get(name, set()) | values
                if names.get(name) != combined:
                    names[name] = combined
                    changed = True
    return names


def _argv_node(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg in {"args", "argv", "cmd", "command"}:
            return keyword.value
    return None


def _head_and_tail(
    argv: ast.AST,
    names: dict[str, set[str]],
) -> tuple[set[str], set[str]]:
    resolved = argv
    if isinstance(argv, ast.Name):
        # The name may represent argv[0] itself or a complete argv assignment.
        heads = set(names.get(argv.id, ()))
        return heads, set()
    if not isinstance(resolved, (ast.List, ast.Tuple)) or not resolved.elts:
        return _value_strings(resolved, names), set()
    return (
        _value_strings(resolved.elts[0], names),
        {
            value
            for element in resolved.elts[1:]
            for value in _value_strings(element, names)
        },
    )


def _executable(candidates: set[str]) -> str | None:
    matches = {
        Path(candidate).name.lower()
        for candidate in candidates
        if Path(candidate).name.lower() in AGENTIC_EXECUTABLES
    }
    if len(matches) == 1:
        return matches.pop()
    return None


def _uses_authorized_executable(
    argv: ast.AST,
    scope: ast.AST,
) -> bool:
    if any(
        isinstance(node, ast.Attribute) and node.attr == "resolved_executable"
        for node in ast.walk(argv)
    ):
        return True
    if not isinstance(argv, ast.Name):
        return False
    for node in ast.walk(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if argv.id not in _assignment_names(node):
            continue
        value = node.value
        if value is not None and any(
            isinstance(child, ast.Attribute)
            and child.attr == "resolved_executable"
            for child in ast.walk(value)
        ):
            return True
    return False


def _likely_binary_values(names: dict[str, set[str]]) -> set[str]:
    return {
        value
        for name, values in names.items()
        if (
            any(token in name.lower() for token in ("bin", "executable"))
            or name.lower() in AGENTIC_EXECUTABLES
        )
        for value in values
        if Path(value).name.lower() in AGENTIC_EXECUTABLES
    }


def _single_executable(values: set[str]) -> str | None:
    executables = {
        Path(value).name.lower()
        for value in values
        if Path(value).name.lower() in AGENTIC_EXECUTABLES
    }
    return next(iter(executables)) if len(executables) == 1 else None


def _enclosing_function(
    call: ast.Call,
    parents: dict[ast.AST, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current: ast.AST = call
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _has_preceding_guard(
    scope: ast.AST,
    *,
    line: int,
    guard_names: frozenset[str],
) -> bool:
    return any(
        isinstance(node, ast.Call)
        and _call_name(node) in guard_names
        and node.lineno < line
        for node in ast.walk(scope)
    )


def _wrapper_names(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    wrappers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(child, ast.Call)
            and _call_name(child) in SUBPROCESS_SPAWNERS
            for child in ast.walk(node)
        ):
            wrappers[node.name] = node
    return wrappers


def _guard_names(tree: ast.Module) -> frozenset[str]:
    """Canonical guard plus local helpers that only deepen that interface."""
    names = {"authorize_provider_spawn"}
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in names:
                continue
            if any(
                isinstance(child, ast.Call) and _call_name(child) in names
                for child in ast.walk(node)
            ):
                names.add(node.name)
                changed = True
    return frozenset(names)


def _iter_sources(root: Path) -> list[Path]:
    sources: list[Path] = []
    for directory in SEARCH_DIRS:
        for path in sorted((root / directory).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in rel or rel.startswith("scripts/_legacy/"):
                continue
            sources.append(path)
    return sources


def _audit_file(root: Path, path: Path) -> tuple[list[SpawnBoundary], list[str]]:
    rel = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    resolver_names = {
        node.name: _strings(node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module_names = _scope_names(tree, resolver_names)
    scopes: dict[ast.AST, _Scope] = {tree: _Scope(tree, module_names)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes[node] = _Scope(node, _scope_names(node, module_names))
    wrappers = _wrapper_names(tree)
    guard_names = _guard_names(tree)
    likely_binary_names = set().union(
        *(_likely_binary_values(scope.names) for scope in scopes.values())
    )
    boundaries: list[SpawnBoundary] = []
    uncertain: list[str] = []
    seen: set[tuple[int, str]] = set()

    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        called = _call_name(call)
        wrapper = wrappers.get(called)
        if called not in SUBPROCESS_SPAWNERS and wrapper is None:
            continue
        argv = _argv_node(call)
        if argv is None:
            continue
        owner = _enclosing_function(call, parents)
        scope = scopes.get(owner or tree, scopes[tree])
        scope_binaries = _likely_binary_values(scope.names)
        heads, tail = _head_and_tail(argv, scope.names)
        executable = _executable(heads)
        if (
            executable is None
            and _single_executable(scope_binaries) is not None
            and _uses_authorized_executable(argv, scope.node)
        ):
            executable = _single_executable(scope_binaries)
        if executable is None:
            continue
        key = (call.lineno, executable)
        if key in seen:
            continue
        seen.add(key)
        kind = (
            SpawnKind.DIAGNOSTIC
            if tail & DIAGNOSTIC_SUBCOMMANDS
            else SpawnKind.BUSINESS
        )
        guard_scope: ast.AST = owner or tree
        guard_line = call.lineno
        if wrapper is not None:
            # A deep wrapper may own authorization immediately before Popen.
            direct_spawn_lines = [
                child.lineno
                for child in ast.walk(wrapper)
                if isinstance(child, ast.Call)
                and _call_name(child) in SUBPROCESS_SPAWNERS
            ]
            if _has_preceding_guard(
                wrapper,
                line=min(direct_spawn_lines, default=10**9),
                guard_names=guard_names,
            ):
                guarded = True
            else:
                guarded = _has_preceding_guard(
                    guard_scope,
                    line=guard_line,
                    guard_names=guard_names,
                )
        else:
            guarded = _has_preceding_guard(
                guard_scope,
                line=guard_line,
                guard_names=guard_names,
            )
        boundaries.append(
            SpawnBoundary(
                path=rel,
                line=call.lineno,
                executable=executable,
                kind=kind,
                guarded=guarded or kind is SpawnKind.DIAGNOSTIC,
            )
        )

    # A file that contains a direct subprocess call and an exact executable
    # literal, but yielded no boundary, is data-flow the analyser could not
    # resolve.  Fail closed rather than silently dropping it from the census.
    has_subprocess = any(
        isinstance(node, ast.Call) and _call_name(node) in SUBPROCESS_SPAWNERS
        for node in ast.walk(tree)
    )
    if not boundaries and _single_executable(likely_binary_names) is not None:
        executable = _single_executable(likely_binary_names)
        assert executable is not None
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if _call_name(call) not in wrappers:
                continue
            owner = _enclosing_function(call, parents)
            if owner is None or not _has_preceding_guard(
                owner,
                line=call.lineno,
                guard_names=guard_names,
            ):
                continue
            boundaries.append(
                SpawnBoundary(
                    path=rel,
                    line=call.lineno,
                    executable=executable,
                    kind=SpawnKind.BUSINESS,
                    guarded=True,
                )
            )
            break
    if likely_binary_names and has_subprocess and not boundaries:
        uncertain.append(
            f"{rel}: subprocess + {sorted(likely_binary_names)} could not be resolved"
        )
    return boundaries, uncertain


def audit_provider_spawns(root: Path) -> SpawnAuditReport:
    """Audit every production Python source below ``scripts`` and ``src``."""
    boundaries: list[SpawnBoundary] = []
    unclassified: list[str] = []
    for path in _iter_sources(root):
        found, uncertain = _audit_file(root, path)
        boundaries.extend(found)
        unclassified.extend(uncertain)
    return SpawnAuditReport(
        boundaries=tuple(boundaries),
        unclassified=tuple(unclassified),
    )
