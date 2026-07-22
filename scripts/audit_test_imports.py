#!/usr/bin/env python3
"""Fail if tracked tests reference Python implementations absent from the tree.

This is the single mechanical owner for test/source dependency closure.  It
checks ordinary ``volpred.*`` imports, the repo's namespace-style ``scripts``
package, and statically constructed ``... / "scripts" / "name.py"`` paths.

``--index`` is the pre-commit mode.  It materialises the Git index in a
disposable directory and has the already-trusted auditor process inspect that
candidate tree.  The candidate copy must still exist and parse, but is never
executed.  Consequently neither an untracked implementation in the working tree
nor a weakened auditor in the candidate can make a partial commit look complete.

Exit 0 = clean, 1 = a test references something absent, 2 = gate could not run.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

TEST_ROOTS = ("tests", "scripts/tests")
AUDITOR_PATH = Path("scripts/audit_test_imports.py")
IMPORT_ROOTS = {
    "volpred": Path("src"),
    "scripts": Path("."),
}

# Attributes every imported Python module carries even when its source does not
# bind them explicitly.  The dependency audit below is interested in application
# symbols, not import machinery metadata.
INTRINSIC_MODULE_ATTRIBUTES = {
    "__builtins__",
    "__cached__",
    "__doc__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
}


def _module_path(root: Path, dotted: str) -> Path | None:
    """Resolve an auditable dotted module to a file or namespace directory."""
    top = dotted.split(".", 1)[0]
    base = IMPORT_ROOTS.get(top)
    if base is None:
        return None
    rel = Path(*dotted.split("."))
    module = root / base / rel.with_suffix(".py")
    package = root / base / rel / "__init__.py"
    namespace = root / base / rel
    if module.is_file():
        return module
    if package.is_file():
        return package
    if namespace.is_dir():
        return namespace
    return None


def _module_bindings(path: Path) -> tuple[set[str], bool]:
    """Return top-level names a module binds and whether it is opaque."""
    if path.is_dir():  # Namespace package: names are supplied by child modules.
        return set(), False
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))

    names: set[str] = set()
    opaque = False
    # Detect actual dynamic module binding operations, not marker text in a
    # comment/string.  The old substring test made this auditor's own source
    # opaque merely because it documented the marker.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "globals"
        ):
            opaque = True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and node.args
            and isinstance(node.args[0], ast.Subscript)
            and isinstance(node.args[0].value, ast.Attribute)
            and isinstance(node.args[0].value.value, ast.Name)
            and node.args[0].value.value.id == "sys"
            and node.args[0].value.attr == "modules"
        ):
            opaque = True
    # Only module-level statements bind importable module attributes.  Walking
    # nested function bodies would incorrectly accept a local helper.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__getattr__"
            ):
                # PEP 562 modules deliberately synthesize attributes.  Static
                # enumeration cannot prove their public surface, so preserve the
                # existing fail-open treatment used for other dynamic bindings.
                opaque = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    opaque = True
                else:
                    names.add(alias.asname or alias.name)
    return names, opaque


def _submodule_exists(root: Path, pkg_dotted: str, name: str) -> bool:
    return _module_path(root, f"{pkg_dotted}.{name}") is not None


def _is_audited_module(dotted: str) -> bool:
    top = dotted.split(".", 1)[0]
    return top in IMPORT_ROOTS


def _imported_submodule_aliases(root: Path, tree: ast.Module) -> dict[str, Path]:
    """Return module-level aliases introduced by ``from package import module``.

    Import closure used to stop at "the submodule exists".  That missed the
    2026-07-21 partial commit where ``failure_class.py`` existed at HEAD but its
    new ``is_terse_fatal_only`` symbol remained only in the working tree.  The
    candidate test imported the old submodule successfully, then failed at
    runtime on ``failure_class.is_terse_fatal_only``.

    Restrict this to module-level imports: a nested import alias may be shadowed
    by parameters or local assignments, and guessing Python scope here would
    turn a safety gate into a false-positive source.
    """
    aliases: dict[str, Path] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        if not _is_audited_module(node.module):
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            submodule = _module_path(root, f"{node.module}.{alias.name}")
            if submodule is not None and submodule.is_file():
                aliases[alias.asname or alias.name] = submodule
    return aliases


def _path_parts(node: ast.AST, names: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    """Best-effort static path evaluator; unknown prefixes collapse to ``()``.

    We only use the suffix beginning at ``scripts``, so expressions such as
    ``Path(__file__).resolve().parents[1]`` need not reveal their absolute root.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return tuple(part for part in Path(node.value).parts if part not in ("/", ""))
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_parts(node.left, names)
        right = _path_parts(node.right, names)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {"Path", "PurePath"}:
            if not node.args:
                return ()
            return _path_parts(node.args[0], names) or ()
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"resolve", "absolute"}:
            return _path_parts(node.func.value, names) or ()
    if isinstance(node, ast.Attribute) and node.attr in {"parent", "parents"}:
        return _path_parts(node.value, names) or ()
    if isinstance(node, ast.Subscript):
        return _path_parts(node.value, names) or ()
    return None


def _known_paths(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    """Resolve simple module constants such as ``SCRIPT = ROOT / ...``."""
    names: dict[str, tuple[str, ...]] = {}
    # A few passes resolve constants declared in terms of earlier constants.
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    for _ in range(3):
        changed = False
        for node in assignments:
            value = node.value
            parts = _path_parts(value, names)
            if parts is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and names.get(target.id) != parts:
                    names[target.id] = parts
                    changed = True
        if not changed:
            break
    return names


def _script_reference(node: ast.AST, names: dict[str, tuple[str, ...]]) -> Path | None:
    parts = _path_parts(node, names)
    if not parts or "scripts" not in parts:
        return None
    # Absolute prefixes may themselves contain a directory called scripts; the
    # final occurrence is the repository-relative dependency.
    pos = len(parts) - 1 - tuple(reversed(parts)).index("scripts")
    rel = Path(*parts[pos:])
    return rel if rel.suffix == ".py" else None


def _inserts_scripts_on_path(tree: ast.AST, names: dict[str, tuple[str, ...]]) -> bool:
    """Does this test put the repo's ``scripts`` dir on ``sys.path``?

    Tests that do this then import their subject by BARE name
    (``import check_experiment_artifacts``), which no IMPORT_ROOTS prefix can
    match.  That blind spot is what let the 2026-07-19 CI red land: the test was
    committed while ``scripts/check_experiment_artifacts.py`` stayed untracked,
    and this gate had nothing to say about it.
    """
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"insert", "append"}
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "sys"
        ):
            continue
        # The inserted expression is usually ``Path(__file__).resolve().parents[1]``,
        # which no static evaluator can turn into "scripts" — the repo root is not
        # in the source.  So ANY sys.path mutation arms the bare-name check; the
        # resolver below only complains about names nothing outside the tree can
        # satisfy, which keeps the false-positive surface at zero.
        return True
    return False


def _bare_script_missing(root: Path, worktree: Path | None, name: str) -> bool:
    """The partial-commit signature for a bare, scripts-dir import.

    ``worktree`` is the live checkout the candidate ``root`` was derived from
    (``--index`` mode only).  The check fires exactly when the working tree HAS
    ``scripts/<name>.py`` and the candidate does NOT -- one half of a pair being
    committed without the other.  Third-party names such as ``pytest`` can never
    match, because no ``scripts/pytest.py`` exists on either side, so this needs
    no knowledge of which packages happen to be installed.
    """
    if worktree is None or "." in name:
        return False
    return _scripts_module(worktree, name) and not _scripts_module(root, name)


def _scripts_module(root: Path, name: str) -> bool:
    scripts_dir = root / "scripts"
    return (scripts_dir / f"{name}.py").is_file() or (
        scripts_dir / name / "__init__.py"
    ).is_file()


def _dynamic_import_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names that denote importlib or importlib.import_module in one test."""
    modules = {"importlib"}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    modules.add(alias.asname or "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    functions.add(alias.asname or alias.name)
    return modules, functions


def _dynamic_import_name(
    node: ast.Call,
    importlib_names: set[str],
    import_module_names: set[str],
) -> str | None:
    """Resolve literal importlib.import_module/__import__ dependencies."""
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    func = node.func
    is_import = (
        isinstance(func, ast.Name)
        and (func.id == "__import__" or func.id in import_module_names)
    ) or (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id in importlib_names
    )
    return node.args[0].value if is_import else None


def audit(root: Path, worktree: Path | None = None) -> tuple[list[str], int, int]:
    bad: list[str] = []
    checked = 0
    files = 0

    test_files = [
        path
        for test_root in TEST_ROOTS
        if (root / test_root).is_dir()
        for path in sorted((root / test_root).rglob("test_*.py"))
    ]

    for test_file in test_files:
        files += 1
        rel_test = test_file.relative_to(root)
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8", errors="replace"), filename=str(test_file))
        except SyntaxError as exc:
            bad.append(f"BAD {rel_test}:{exc.lineno} — test module does not parse: {exc.msg}")
            continue

        importlib_names, import_module_names = _dynamic_import_aliases(tree)
        path_names = _known_paths(tree)
        bare_root = _inserts_scripts_on_path(tree, path_names)
        submodule_aliases = _imported_submodule_aliases(root, tree)
        submodule_surfaces: dict[Path, tuple[set[str], bool]] = {}

        # ``from package import module`` is only complete when the candidate's
        # module also carries every directly-read attribute the test requires.
        # This is intentionally candidate-tree based: a newer working-tree copy
        # must not make an older staged module look complete.
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id in submodule_aliases
            ):
                continue
            module_file = submodule_aliases[node.value.id]
            if module_file not in submodule_surfaces:
                try:
                    submodule_surfaces[module_file] = _module_bindings(module_file)
                except SyntaxError as exc:
                    rel_source = module_file.relative_to(root)
                    bad.append(
                        f"BAD {rel_source}:{exc.lineno} — source module does not parse: {exc.msg}"
                    )
                    submodule_surfaces[module_file] = (set(), True)
            bindings, opaque = submodule_surfaces[module_file]
            if opaque or node.attr in bindings or node.attr in INTRINSIC_MODULE_ATTRIBUTES:
                continue
            checked += 1
            bad.append(
                f"BAD {rel_test}:{node.lineno} — '{node.value.id}.{node.attr}' is read, "
                f"but {module_file.relative_to(root)} does not define '{node.attr}'"
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _is_audited_module(alias.name):
                        if bare_root and _bare_script_missing(root, worktree, alias.name):
                            checked += 1
                            bad.append(
                                f"BAD {rel_test}:{node.lineno} — imports '{alias.name}' "
                                f"after putting scripts/ on sys.path, but "
                                f"scripts/{alias.name}.py does not exist"
                            )
                        continue
                    checked += 1
                    if _module_path(root, alias.name) is None:
                        bad.append(f"BAD {rel_test}:{node.lineno} — imports '{alias.name}', which does not exist")
                continue

            if isinstance(node, ast.Call):
                dynamic_module = _dynamic_import_name(
                    node, importlib_names, import_module_names
                )
                if dynamic_module and _is_audited_module(dynamic_module):
                    checked += 1
                    if _module_path(root, dynamic_module) is None:
                        bad.append(
                            f"BAD {rel_test}:{node.lineno} — dynamically imports "
                            f"'{dynamic_module}', which does not exist"
                        )
                continue

            if not isinstance(node, ast.ImportFrom) or node.level:
                continue
            module = node.module or ""
            if not _is_audited_module(module):
                if module and bare_root and _bare_script_missing(root, worktree, module):
                    checked += 1
                    bad.append(
                        f"BAD {rel_test}:{node.lineno} — imports from '{module}' "
                        f"after putting scripts/ on sys.path, but "
                        f"scripts/{module}.py does not exist"
                    )
                continue

            module_file = _module_path(root, module)
            if module_file is None:
                bad.append(f"BAD {rel_test}:{node.lineno} — imports from '{module}', which does not exist")
                continue
            try:
                bindings, opaque = _module_bindings(module_file)
            except SyntaxError as exc:
                rel_source = module_file.relative_to(root)
                bad.append(f"BAD {rel_source}:{exc.lineno} — source module does not parse: {exc.msg}")
                continue
            if opaque:
                continue

            for alias in node.names:
                if alias.name == "*":
                    continue
                checked += 1
                if alias.name in bindings or _submodule_exists(root, module, alias.name):
                    continue
                bad.append(
                    f"BAD {rel_test}:{node.lineno} — '{alias.name}' is imported from '{module}' "
                    f"but {module_file.relative_to(root)} does not define it"
                )

        # A script loaded dynamically is an import dependency too.  Restrict
        # this path analysis to spec_from_file_location calls: arbitrary
        # scripts/*.py strings in tests are often deliberate temp-repo fixtures.
        names = path_names
        seen_paths: set[tuple[int, Path]] = set()
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "spec_from_file_location"
            ):
                continue
            location: ast.AST | None = node.args[1] if len(node.args) > 1 else None
            if location is None:
                location = next((kw.value for kw in node.keywords if kw.arg == "location"), None)
            rel_script = _script_reference(location, names) if location is not None else None
            key = (getattr(node, "lineno", 0), rel_script) if rel_script else None
            if rel_script is None or key in seen_paths:
                continue
            seen_paths.add(key)
            checked += 1
            if not (root / rel_script).is_file():
                bad.append(f"BAD {rel_test}:{getattr(node, 'lineno', '?')} — references missing '{rel_script}'")

    return bad, checked, files


def _audit_index(root: Path) -> int:
    """Materialise and audit exactly the candidate Git index, never disk state."""
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(f"[audit-test-imports] cannot execute git: {exc}", file=sys.stderr)
        return 2
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        print(f"[audit-test-imports] --index root is not a git worktree root: {root}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="audit-test-index-") as scratch:
        candidate = Path(scratch) / "candidate"
        candidate.mkdir()
        checkout = subprocess.run(
            ["git", "-C", str(root), "checkout-index", "--all", f"--prefix={candidate}/"],
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode != 0:
            print(f"[audit-test-imports] cannot materialise candidate index: {checkout.stderr.strip()}", file=sys.stderr)
            return 2

        candidate_auditor = candidate / AUDITOR_PATH
        if not candidate_auditor.is_file():
            print(f"[audit-test-imports] candidate index removes its own gate: {AUDITOR_PATH}", file=sys.stderr)
            return 2
        try:
            ast.parse(candidate_auditor.read_text(encoding="utf-8"), filename=str(candidate_auditor))
        except (OSError, SyntaxError) as exc:
            print(f"[audit-test-imports] candidate auditor is not runnable: {exc}", file=sys.stderr)
            return 2

        # This process is the immutable bootstrap selected by the hook (HEAD's
        # auditor for ordinary commits; base_sha's auditor for PHASE-Z).  Audit
        # candidate bytes with this trusted implementation.  Executing the
        # candidate's implementation here would let the candidate weaken its
        # own gate to `exit 0`.
        bad, checked, files = audit(candidate, worktree=root)
        for line in bad:
            print(line)
        print(
            f"[audit-test-imports] {files} test files checked, "
            f"{checked} dependencies resolved, {len(bad)} bad"
        )
        return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="tree/worktree root to audit (default: cwd)")
    parser.add_argument("--index", action="store_true", help="audit the candidate Git index")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.index:
        return _audit_index(root)
    if not (root / "src" / "volpred").is_dir():
        print(f"[audit-test-imports] cannot audit: {root}/src/volpred is not a directory", file=sys.stderr)
        return 2

    bad, checked, files = audit(root)
    for line in bad:
        print(line)
    print(f"[audit-test-imports] {files} test files checked, {checked} dependencies resolved, {len(bad)} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
