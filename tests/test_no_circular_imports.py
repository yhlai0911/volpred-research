"""Import-time cycles in `volpred` are a latent, order-dependent crash. Ban them.

2026-07-11: `token_report_daily` died every morning on

    volpred.publisher.email_notifier  (top-level: from volpred.ops.canonical_write ...)
      -> volpred.ops.__init__         (importing ANY submodule runs the package __init__)
        -> volpred.ops.alerts         (eagerly re-exported there)
          -> volpred.publisher.email_notifier   # still half-initialised -> ImportError

The cycle had existed for a while and was invisible: whether it raises depends
entirely on which module the process imports FIRST. Anything that reached
`volpred.ops` first was fine; the cron script that reached `email_notifier` first
was not. So the runtime never told us the graph was broken — only one entry point
did, once a day, in a log nobody reads.

This gate reads the graph instead of the crash. It walks every module under
`src/volpred/`, records the imports that execute at import time (module level,
NOT the ones deferred inside functions — deferring is precisely the fix), adds the
implicit edge to each ancestor package, and fails on any cycle.

Whitelisting a cycle here is almost never right: the fix is to move the import
inside the function that uses it, which is what email_notifier now does.
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
PKG = "volpred"


def _ancestors(mod: str) -> list[str]:
    """`import a.b.c` executes a/__init__.py then a/b/__init__.py. Those are edges."""
    parts = mod.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _import_time_edges(path: Path, mod: str, known: set[str]) -> set[str]:
    """Targets this module imports AT IMPORT TIME (module-level statements only).

    Imports nested in a function/method body are deferred to call time and cannot
    close an import-time cycle, so they are not edges — that is the whole point of
    the lazy-import convention this codebase uses to break cycles.

    Edges to a package the importer already lives in are skipped: when
    `volpred.ops.alerts` imports `volpred.ops.boss_facing`, `volpred/ops/__init__.py`
    is already running (it is what pulled `alerts` in) and is NOT re-executed, so
    that is not a cycle — every submodule would trivially "cycle" with its parent.
    The edge that matters is the one INTO a package from outside it, which is what
    forces that package's `__init__` to run: `volpred.publisher.email_notifier`
    importing `volpred.ops.canonical_write` is what ran `volpred/ops/__init__.py`
    and closed the loop back onto the half-initialised email_notifier.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    edges: set[str] = set()

    def _outside(target: str) -> bool:
        return not mod.startswith(target + ".")

    def resolve(target: str) -> None:
        # `from volpred.ops.canonical_write import guard` may name a module OR an
        # attribute of one; either way the deepest existing module prefix is what
        # gets executed. The packages above it run first — unless we are already
        # inside them.
        for cand in [target, *reversed(_ancestors(target))]:
            if cand in known:
                if _outside(cand):
                    edges.add(cand)
                edges.update(a for a in _ancestors(cand) if a in known and _outside(a))
                return

    for node in tree.body:  # module level only — no ast.walk
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolve(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: `from .alerts import x` inside volpred.ops
                base = mod if path.name == "__init__.py" else mod.rsplit(".", 1)[0]
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else base
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if not target.startswith(PKG):
                continue
            resolve(target)
            for alias in node.names:  # `from volpred.ops import alerts`
                resolve(f"{target}.{alias.name}")

    edges.discard(mod)
    return edges


def _mod_from(src: Path, path: Path) -> str:
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _build_graph(src: Path = SRC) -> dict[str, set[str]]:
    paths = sorted(src.glob(f"{PKG}/**/*.py"))
    known = {_mod_from(src, p) for p in paths}
    return {_mod_from(src, p): _import_time_edges(p, _mod_from(src, p), known) for p in paths}


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    seen: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def visit(mod: str) -> None:
        if mod in on_stack:
            cycles.append(stack[stack.index(mod):] + [mod])
            return
        if mod in seen:
            return
        seen.add(mod)
        stack.append(mod)
        on_stack.add(mod)
        for dep in sorted(graph.get(mod, ())):
            visit(dep)
        stack.pop()
        on_stack.discard(mod)

    for mod in sorted(graph):
        visit(mod)
    return cycles


def test_no_import_time_cycles_in_volpred() -> None:
    cycles = _find_cycles(_build_graph())
    assert not cycles, (
        "import-time cycle(s) in volpred — this crashes whichever entry point happens "
        "to import the cycle's modules in the wrong order (2026-07-11: token_report_daily).\n"
        "Fix: move the import inside the function that uses it.\n"
        + "\n".join("  " + " -> ".join(c) for c in cycles[:10])
    )


def test_gate_catches_the_cycle_it_was_built_for(tmp_path: Path) -> None:
    """Re-introduce the 2026-07-11 cycle in a throwaway copy of the tree.

    A gate that passes on both the broken and the fixed tree is not a gate. This
    restores the exact line that was removed (`email_notifier` importing
    `volpred.ops.canonical_write` at module level) and asserts the detector bites.
    """
    shutil.copytree(SRC / PKG, tmp_path / PKG)
    victim = tmp_path / PKG / "publisher" / "email_notifier.py"
    victim.write_text(
        "from volpred.ops.canonical_write import guard_canonical_write\n"
        + victim.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    cycles = _find_cycles(_build_graph(tmp_path))
    assert any(
        "volpred.publisher.email_notifier" in c and "volpred.ops" in c for c in cycles
    ), f"detector missed the regression it exists to catch; found: {cycles[:5]}"
