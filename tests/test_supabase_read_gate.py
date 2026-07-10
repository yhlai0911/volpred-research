"""Gate: tests must not read production Supabase.

`VOLPRED_NO_REMOTE_WRITE` (2026-06-23) stops a test corrupting prod. It does nothing
about reads. A test whose stub is incomplete then queries LIVE production and its
verdict tracks today's prod data instead of its fixtures — the symptom is "the same
code is green today and red tomorrow", which reads as flakiness and gets re-run rather
than diagnosed. Measured 2026-07-10: four tests in tests/test_feed_sync.py were doing
exactly this, and two of them flipped pass->fail across two full runs 40 minutes apart
with no code change on that path.

The switch lives at `supabase_sync._urlopen`, the single egress chokepoint, so a newly
added read cannot forget it.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_supabase_sync():
    """Import directly — no credential skip.

    supabase_sync is import-safe (credentials are a request-time requirement, enforced
    by `require_creds()` behind the HEADERS guard and pinned by
    tests/test_supabase_sync_import_safety.py). A `pytest.skip` on import failure here
    would silently disable this whole file the day someone reintroduces an import-time
    raise — the exact silent-guard failure mode the gate exists to prevent.
    """
    spec = importlib.util.spec_from_file_location(
        "supabase_sync", ROOT / "scripts" / "supabase_sync.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_conftest_arms_the_read_switch():
    """The switch is worthless unless conftest turns it on for every test run."""
    assert os.environ.get("VOLPRED_NO_REMOTE_READ") == "1"


def test_get_is_blocked_when_switch_is_on(monkeypatch):
    supabase_sync = _load_supabase_sync()
    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "1")
    req = Request("https://example.supabase.co/rest/v1/articles?select=id", method="GET")

    with pytest.raises(RuntimeError, match="Blocked live Supabase read"):
        supabase_sync._urlopen(req)


def test_get_is_allowed_when_switch_is_off(monkeypatch):
    """The gate must key off the env var, not be hardcoded on — prod reads must work."""
    supabase_sync = _load_supabase_sync()
    monkeypatch.delenv("VOLPRED_NO_REMOTE_READ", raising=False)
    monkeypatch.setattr(supabase_sync, "urlopen", lambda r, timeout=15: "response")
    req = Request("https://example.supabase.co/rest/v1/articles?select=id", method="GET")

    assert supabase_sync._urlopen(req) == "response"


def test_read_gate_does_not_swallow_writes(monkeypatch):
    """Writes have their own switch. If the read gate also blocked POST, a run with
    reads disabled would silently skip every write assertion."""
    supabase_sync = _load_supabase_sync()
    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "1")
    monkeypatch.setattr(supabase_sync, "urlopen", lambda r, timeout=15: "posted")
    req = Request("https://example.supabase.co/rest/v1/articles", data=b"[]", method="POST")

    assert supabase_sync._urlopen(req) == "posted"


def test_every_request_helper_routes_through_the_chokepoint():
    """A helper calling bare `urlopen` would bypass the gate. Only `_urlopen` itself may.

    Checked with AST rather than a text match: a new helper written as
    `urlopen(req, timeout=timeout)` would slip past any keyword-based grep.
    """
    import ast

    tree = ast.parse((ROOT / "scripts" / "supabase_sync.py").read_text(encoding="utf-8"))

    offenders: list[str] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name == "_urlopen":  # the chokepoint's own body is the sanctioned caller
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "urlopen":
                    offenders.append(f"{func.name}() at line {node.lineno}")

    assert offenders == [], f"request helpers bypassing _urlopen: {offenders}"

    # Negative control: the detector must actually be able to see a bare call.
    bad = ast.parse("def helper():\n    urlopen(req, timeout=timeout)\n")
    found = [
        n
        for f in ast.walk(bad)
        if isinstance(f, ast.FunctionDef) and f.name != "_urlopen"
        for n in ast.walk(f)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "urlopen"
    ]
    assert found, "detector cannot see a bare urlopen call; gate is dead"
