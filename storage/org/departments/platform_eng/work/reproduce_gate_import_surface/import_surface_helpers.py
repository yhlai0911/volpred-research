"""Helpers to paste into ``scripts/reproduce_check.py`` after ``_git_file_sha256``.

Validated 2026-08-05 against the real repository: waives the k1699/K1710 false
positive, and fails closed on every mutation that actually reaches the imported
symbols (see ../reproduce_gate_import_surface/diagnosis_and_patch.md section 4).

Not importable on its own -- it relies on ``ast``, ``hashlib``, ``json``,
``subprocess``, ``Path``, ``Any``, ``Iterable`` and ``_sha256`` from the host
module.  It is stored here only so the landing agent pastes verified code
instead of re-deriving it.
"""


def _module_name_for_path(relative_path: str) -> str | None:
    """``src/volpred/stats/model_evaluation.py`` -> ``volpred.stats.model_evaluation``."""
    if not relative_path.endswith(".py"):
        return None
    parts = Path(relative_path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts) or None


def _imported_symbols(module: str, sources: Iterable[Path]) -> set[str] | None:
    """Names these sources import FROM ``module``.

    ``None`` means the whole module is in play (``import module``,
    ``from module import *``, or a source that would not parse).  That is the
    conservative answer and sends the caller back to whole-file comparison.
    """
    symbols: set[str] = set()
    for path in sources:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level or node.module != module:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        return None
                    symbols.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == module or module.startswith(alias.name + "."):
                        return None
    return symbols


def _module_symbol_digests(source: str, symbols: set[str]) -> dict[str, str] | None:
    """Digest ``symbols`` plus every module-level name they transitively reach.

    Hashing only the imported function would be a lie: it can call a helper or
    read a constant defined beside it, so its behaviour changes while its own
    bytes stay identical.  The unit compared is therefore the transitive closure
    of module-level names reachable from the entry symbols.

    ``None`` means the comparison is not sound and the caller must fall back to
    the whole file: the module has a top-level statement other than a
    definition, import or assignment (import-time side effect), the source does
    not parse, or a requested symbol is not defined at module level.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    defs: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        defs[sub.id] = node
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                defs[node.target.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defs[(alias.asname or alias.name).split(".")[0]] = node
        elif isinstance(node, (ast.Expr, ast.Pass)):
            continue  # docstrings and no-ops carry no behaviour
        else:
            return None  # top-level side effect: a partial comparison is unsound
    if any(name not in defs for name in symbols):
        return None
    digests: dict[str, str] = {}
    queue = sorted(symbols)
    while queue:
        name = queue.pop()
        if name in digests or name not in defs:
            continue
        digests[name] = hashlib.sha256(
            ast.dump(defs[name], annotate_fields=True).encode("utf-8")
        ).hexdigest()
        for sub in ast.walk(defs[name]):
            if isinstance(sub, ast.Name) and sub.id in defs and sub.id not in digests:
                queue.append(sub.id)
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                if sub.value.id in defs and sub.value.id not in digests:
                    queue.append(sub.value.id)
    return digests


def _historic_blob(root: Path, relative_path: str, sha256: str) -> tuple[str, str] | None:
    """Find the committed version of ``relative_path`` whose content is ``sha256``.

    This is what makes the whole change spec-compatible: a spec records only a
    whole-file hash, but the version behind that hash can be recovered from
    history, so no spec migration and no reader change is needed.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "--", relative_path],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if log.returncode != 0:
        return None
    for commit in log.stdout.split():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=root, capture_output=True, check=False,
        )
        if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == sha256:
            return commit, blob.stdout.decode("utf-8", "replace")
    return None


def _import_surface_waiver(
    root: Path,
    relative_path: str,
    recorded_sha: str,
    sources: list[Path],
) -> dict[str, Any] | None:
    """Receipt fragment when a changed input cannot affect this experiment.

    ``None`` means no waiver -- the caller keeps failing closed.  A waiver is
    only issued when every symbol the experiment imports, and everything those
    symbols reach at module level, is byte-identical to the recorded version.
    """
    module = _module_name_for_path(relative_path)
    if module is None:
        return None
    symbols = _imported_symbols(module, sources)
    if not symbols:
        return None  # whole module in play, or nothing imported from it at all
    historic = _historic_blob(root, relative_path, recorded_sha)
    if historic is None:
        return None  # the recorded version is not in history; no basis to compare
    commit, old_source = historic
    new_source = (root / relative_path).read_text(encoding="utf-8")
    old_digests = _module_symbol_digests(old_source, symbols)
    new_digests = _module_symbol_digests(new_source, symbols)
    if old_digests is None or new_digests is None or old_digests != new_digests:
        return None
    return {
        "path": relative_path,
        "recorded_sha256": recorded_sha,
        "current_sha256": _sha256(root / relative_path),
        "recorded_version_commit": commit,
        "imported_symbols": sorted(symbols),
        "compared_symbol_closure": sorted(old_digests),
        "closure_digest": hashlib.sha256(
            json.dumps(old_digests, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "basis": "import_surface",
    }
