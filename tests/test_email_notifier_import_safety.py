"""Gate: `volpred.publisher.email_notifier` must import without triggering a
circular import through `volpred.ops`.

Why this exists (2026-07-11): `email_notifier.py` used to import an eager
`volpred.ops` submodule at module scope. Importing any
`volpred.ops.*` submodule eagerly runs `volpred/ops/__init__.py`, which imports
`.alerts`, which imports `EmailNotifier` back from this module while it is still
partially initialized → `ImportError: cannot import name 'EmailNotifier' ...
(most likely due to a circular import)`.

`email_notifier` sits *below* `volpred.ops` in the dependency order (ops depends
on it, not the other way round). The daily `token_report_daily` cron imports
`EmailNotifier` first and hit this cycle every run (exit=1) — see the
`host_cron_fail` critical alert. The guard now lives below `volpred.ops`, so this
suite pins the dependency direction and rejects any new top-level ops edge.

The subprocess is load-bearing: within a running pytest process `volpred.ops`
is usually already fully imported, so an in-process `import` would pass
vacuously. A fresh interpreter reproduces the exact failing order.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "src" / "volpred" / "publisher" / "email_notifier.py"


def _fresh_import(statement: str) -> subprocess.CompletedProcess:
    """Run `statement` in a brand-new interpreter with no volpred module cached."""
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_email_notifier_imports_first_without_cycle():
    """The exact failing order: import email_notifier before volpred.ops."""
    proc = _fresh_import(
        "from volpred.publisher.email_notifier import EmailNotifier; print('OK')"
    )
    assert proc.returncode == 0, (
        "email_notifier failed to import standalone — circular import regressed.\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_ops_first_still_imports():
    """The reverse order must keep working too (ops → email_notifier)."""
    proc = _fresh_import(
        "import volpred.ops; "
        "from volpred.publisher.email_notifier import EmailNotifier; print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_no_top_level_ops_import_in_email_notifier():
    """AST guard: no module-level `import volpred.ops...` may be reintroduced.

    Imports nested inside functions/methods (the deferred pattern the fix uses)
    are fine — only top-level statements create the initialization-time cycle.
    """
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:  # top level only
        mods: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        for mod in mods:
            assert not mod.startswith("volpred.ops"), (
                f"top-level `import {mod}` reintroduced in email_notifier.py — this "
                "recreates the circular import that broke token_report_daily. Import "
                "it lazily inside the method that uses it instead."
            )
