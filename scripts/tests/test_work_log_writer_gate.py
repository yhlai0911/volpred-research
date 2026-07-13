"""Mechanical gate: every writer of storage/work_log.json goes through the lock.

2026-07-13 (hourly-02): a fire appended two entries to `storage/work_log.json`,
staged the file, and by commit time the file had reverted to a previous writer's
snapshot. Both entries were gone, silently. Root cause: the log had a dozen
call sites doing an unlocked read-modify-write of the whole array, so two
overlapping writers always dropped the loser's work. Under load the failure gets
worse than lost entries — a reader can catch the file mid-write and get a
truncated array (`JSONDecodeError`), which is exactly what
`.claude/rules/control-plane.md` forbids for canonical JSON.

`scripts/append_work_log.py` is the fix: flock + full pre-serialisation +
`os.replace`. This gate is what keeps it the *only* way in. Prose in a rulebook
does not survive the next person who needs to append one entry in a hurry.

Per anti-stacking, this is the SINGLE enforcement owner for this concern. Do not
add a second watchdog or a pre-commit hook for it — extend this test.

Run::
    uv run --extra dev python -m pytest scripts/tests/test_work_log_writer_gate.py -v
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("scripts", "src", "experiments")

# The helper itself is the lock. It is the one file allowed to touch the bytes.
ALLOWED_WRITERS = {
    "scripts/append_work_log.py",
}

# Frozen pre-existing violations (RATCHET — this set may only shrink).
#
# These are archived one-shot experiment scripts: each was run once, by hand, to
# stamp a single knowledge/work_log entry for its K, and none is on a scheduled
# or daemon path. Rewriting them now would edit the record of what was actually
# executed for those experiments (research-honesty: experiment artifacts are
# evidence, not live code), and their concurrency exposure is a human running one
# script once. What matters is that the class cannot GROW: a NEW experiment
# writer that appends to the work log unlocked fails this gate.
BASELINE = {
    "experiments/K1387/write_knowledge.py",
    "experiments/K1655/write_knowledge.py",
    "experiments/K1655/write_encompassing_knowledge.py",
}

# Call names that mean "this expression's bytes are being replaced".
WRITE_CALL = re.compile(r"(write|dump|save|replace|unlink)", re.IGNORECASE)
# Path/file methods that mutate the target.
WRITE_METHOD = {"write_text", "write_bytes", "open"}
MUTATING_MODES = ("w", "a", "+", "x")


class _Scanner(ast.NodeVisitor):
    """Flag any expression that writes the work log without going through the lock.

    Resolution is name-based on purpose. A module names its log path once
    (``WORK_LOG = ROOT / "storage" / "work_log.json"``) and then passes that name
    around, so binding the name and following it catches both the direct
    ``WORK_LOG.write_text(...)`` and the indirect ``_atomic_write_json(WORK_LOG, x)``
    — the two shapes that actually existed in the tree. A writer that assembles
    the path inline from fragments would slip through; that is a real blind spot,
    accepted because no such call site exists and the honest alternative
    (taint-tracking) is not worth its false positives here.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.log_names: set[str] = set()
        self.violations: list[tuple[int, str]] = []

    # -- name binding -------------------------------------------------------
    def _binds_work_log(self, node: ast.AST) -> bool:
        seg = ast.get_source_segment(self.source, node) or ""
        return "work_log.json" in seg

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._binds_work_log(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.log_names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and self._binds_work_log(node.value):
            if isinstance(node.target, ast.Name):
                self.log_names.add(node.target.id)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # `from append_work_log import WORK_LOG` re-exports the path without the
        # literal ever appearing here. Track the bound name or the gate has a hole
        # exactly where the migration put one.
        for alias in node.names:
            if "work_log" in alias.name.lower() and alias.name.isupper():
                self.log_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    # -- write detection ----------------------------------------------------
    def _is_log_expr(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in self.log_names:
            return True
        return self._binds_work_log(node)

    def _mode_is_mutating(self, node: ast.Call) -> bool:
        args = list(node.args) + [kw.value for kw in node.keywords if kw.arg == "mode"]
        for arg in args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(ch in arg.value for ch in MUTATING_MODES):
                    return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        # X.write_text(...) / X.open("w") where X is the log
        if isinstance(func, ast.Attribute) and func.attr in WRITE_METHOD:
            if self._is_log_expr(func.value):
                if func.attr != "open" or self._mode_is_mutating(node):
                    self.violations.append((node.lineno, f".{func.attr}() on the work log"))

        # open(X, "w") — builtin
        if isinstance(func, ast.Name) and func.id == "open":
            if node.args and self._is_log_expr(node.args[0]) and self._mode_is_mutating(node):
                self.violations.append((node.lineno, "open(work_log, 'w')"))

        # _atomic_write_json(X, ...) / json.dump(..., X) / save_json(X, ...)
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name and WRITE_CALL.search(name) and name not in WRITE_METHOD:
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if self._is_log_expr(arg):
                    self.violations.append((node.lineno, f"{name}(..., work_log, ...)"))
                    break

        self.generic_visit(node)


def _scan(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    # Broader than the literal: a module that imports WORK_LOG never spells the
    # filename, and that is precisely the shape the gate must not miss.
    if "work_log" not in source.lower():
        return []
    # A file that mentions the work log but does not parse is a file this gate
    # cannot vet. Swallowing the SyntaxError would silently exempt it — the exact
    # hole the gate exists to close — so let it fail the test loudly instead.
    tree = ast.parse(source)
    scanner = _Scanner(source)
    scanner.visit(tree)
    return scanner.violations


def _population() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return files


@pytest.fixture(scope="module")
def offenders() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for path in _population():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_WRITERS:
            continue
        hits = _scan(path)
        if hits:
            found[rel] = hits
    return found


def test_no_unlocked_work_log_writers(offenders: dict[str, list[tuple[int, str]]]) -> None:
    """No file outside the helper may write work_log.json directly."""
    new = {rel: hits for rel, hits in offenders.items() if rel not in BASELINE}
    assert not new, (
        "Unlocked writer(s) of storage/work_log.json:\n"
        + "\n".join(
            f"  {rel}:{ln}  {what}" for rel, hits in sorted(new.items()) for ln, what in hits
        )
        + "\n\nRoute the append through scripts/append_work_log.py:\n"
        "    from append_work_log import append_entry, append_entries\n"
        "    append_entry({'task_id': ..., 'actor': ..., 'summary': ...})\n"
        "It takes fcntl.LOCK_EX, pre-serialises, and os.replace()s. An unlocked\n"
        "read-modify-write silently drops concurrent entries (2026-07-13 incident)."
    )


def test_baseline_only_shrinks(offenders: dict[str, list[tuple[int, str]]]) -> None:
    """A baselined file that got fixed can never regress back into the baseline."""
    stale = BASELINE - set(offenders)
    assert not stale, (
        "These files no longer write the work log unlocked — remove them from "
        f"BASELINE in {Path(__file__).name} so the ratchet cannot slip back: {sorted(stale)}"
    )


def test_scanner_detects_each_write_shape() -> None:
    """The gate is only worth its runtime if it actually catches the shapes."""
    cases = {
        "write_text": 'P = ROOT / "storage" / "work_log.json"\nP.write_text("[]")\n',
        "open_w": 'P = ROOT / "storage" / "work_log.json"\nwith open(P, "w") as f:\n    f.write("[]")\n',
        "helper_call": 'P = ROOT / "storage" / "work_log.json"\n_atomic_write_json(P, [])\n',
        "json_dump_path": 'import json\nP = ROOT / "storage" / "work_log.json"\njson.dump([], P.open("w"))\n',
        "inline_literal": 'Path("storage/work_log.json").write_text("[]")\n',
        "imported_name": 'from append_work_log import WORK_LOG\nWORK_LOG.write_text("[]")\n',
    }
    for label, src in cases.items():
        scanner = _Scanner(src)
        scanner.visit(ast.parse(src))
        assert scanner.violations, f"scanner missed shape: {label}"


def test_scanner_does_not_flag_readers() -> None:
    """Readers vastly outnumber writers; a gate that flags them would be turned off."""
    src = (
        'WORK_LOG = ROOT / "storage" / "work_log.json"\n'
        "data = json.loads(WORK_LOG.read_text())\n"
        "with open(WORK_LOG) as f:\n"
        "    rows = json.load(f)\n"
        "count = len(rows)\n"
    )
    scanner = _Scanner(src)
    scanner.visit(ast.parse(src))
    assert scanner.violations == []
