"""Regression gates for the release-settings audit circular import."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "scripts" / "supabase_sync.py"


def _fresh_import(statement: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def test_supabase_sync_imports_first_without_ops_cycle() -> None:
    proc = _fresh_import(
        "from scripts.supabase_sync import _select_rows; print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_release_settings_audit_imports_in_fresh_interpreter() -> None:
    proc = _fresh_import(
        "from scripts.audit_release_settings import _load_remote; print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_legacy_projection_contract_exports_all_public_symbols() -> None:
    proc = _fresh_import(
        "from volpred.ops.public_article_projection_contract import ("
        "PublicArticleProjectionContractError,"
        "audit_frontend_public_article_projection_contract,"
        "load_public_article_projection_contract,"
        "public_projection_contract_evidence_matches"
        "); print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_supabase_sync_has_no_top_level_ops_dependency() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for module in modules:
            assert not module.startswith("volpred.ops"), (
                f"top-level import {module!r} recreates the supabase_sync ↔ "
                "volpred.ops circular dependency"
            )
