"""Gate: `scripts/supabase_sync.py` must import without Supabase credentials.

Why this exists (2026-07-10): the module used to `raise RuntimeError` at import
when neither the env vars nor `.env.local` supplied credentials. `volpred.ops`
imports it transitively, so **pytest collection died in any environment without
`.env.local`** — a file that is gitignored and therefore never present in CI.
That single import-time side effect is why this repo's 1600+ tests had never run
in CI, and why two long-red tests sat unnoticed for days.

Credentials are a *request-time* requirement. The guard now lives on `HEADERS`
(a credential-guarded `Mapping`) and on `require_creds()`.

The isolation trick below matters: the module resolves `.env.local` relative to
its own `__file__`. Executing the source with a `__file__` under `tmp_path` means
the repo's real `.env.local` cannot leak in and make the test vacuously pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "scripts" / "supabase_sync.py"


def _exec_module_without_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run supabase_sync's module body with no env vars and no reachable .env.local."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.syspath_prepend(str(REPO))

    fake_dir = tmp_path / "scripts"
    fake_dir.mkdir()
    fake_file = fake_dir / "supabase_sync.py"
    assert not (tmp_path / ".env.local").exists(), "isolation broken: fixture dir has .env.local"

    namespace: dict = {"__name__": "supabase_sync_isolated", "__file__": str(fake_file)}
    code = compile(SOURCE.read_text(encoding="utf-8"), str(fake_file), "exec")
    exec(code, namespace)  # noqa: S102 — executing our own source under test
    return namespace


def test_imports_without_credentials(tmp_path, monkeypatch):
    """The whole point: no raise at import. This is what unblocks pytest in CI."""
    ns = _exec_module_without_creds(tmp_path, monkeypatch)
    assert ns["SUPABASE_URL"] is None
    assert ns["SUPABASE_KEY"] is None


def test_isolation_actually_hides_the_repo_env_file(tmp_path, monkeypatch):
    """Self-check: if `.env.local` leaked in, every test here would pass vacuously
    (creds present → no raise → looks import-safe even if the raise came back).

    Only meaningful on a checkout that HAS `.env.local` — skip otherwise rather
    than assert something trivially true.
    """
    if not (REPO / ".env.local").exists():
        pytest.skip("no .env.local on this checkout — nothing for the isolation to hide")
    ns = _exec_module_without_creds(tmp_path, monkeypatch)
    assert ns["SUPABASE_URL"] is None, (
        "the repo's .env.local leaked into the isolated namespace — this suite proves nothing"
    )


def test_headers_guard_fires_without_credentials(tmp_path, monkeypatch):
    """Fail-fast is preserved: touching HEADERS without creds still raises."""
    ns = _exec_module_without_creds(tmp_path, monkeypatch)
    headers = ns["HEADERS"]
    with pytest.raises(RuntimeError, match="Missing SUPABASE_URL"):
        headers["apikey"]


def test_headers_guard_survives_dict_unpacking(tmp_path, monkeypatch):
    """`{**HEADERS, ...}` is how five of the seven request helpers build headers.

    A `dict` subclass would NOT catch this: CPython's `{**d}` fast-path copies a
    dict subclass's internal storage directly, skipping any overridden
    `__getitem__`/`keys()`. `HEADERS` is a `Mapping` for exactly this reason —
    this test is what stops someone "simplifying" it back into a dict subclass.
    """
    ns = _exec_module_without_creds(tmp_path, monkeypatch)
    headers = ns["HEADERS"]
    with pytest.raises(RuntimeError, match="Missing SUPABASE_URL"):
        {**headers, "Prefer": "return=minimal"}


def test_dict_subclass_would_have_been_bypassed():
    """Pins the CPython behaviour the design depends on. If a future Python makes
    `{**d}` honour subclass overrides, this fails and the comment can be relaxed."""

    class GuardDict(dict):
        def __getitem__(self, key):  # pragma: no cover - must never be reached
            raise AssertionError("unreachable via {**d} on a dict subclass")

        def keys(self):  # pragma: no cover
            raise AssertionError("unreachable via {**d} on a dict subclass")

    assert {**GuardDict(a=1)} == {"a": 1}, (
        "CPython now honours dict-subclass overrides in {**d}; the Mapping "
        "workaround in supabase_sync.HEADERS may be simplified."
    )


def test_require_creds_raises_with_the_original_message(tmp_path, monkeypatch):
    ns = _exec_module_without_creds(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="Set env vars or create .env.local"):
        ns["require_creds"]()


def test_module_body_has_no_top_level_credential_raise():
    """Belt-and-braces against reintroduction by someone reading only the source."""
    import ast

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:  # top level only — nested raises inside functions are fine
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise) and isinstance(node, (ast.If, ast.Raise)):
                pytest.fail(
                    "top-level `raise` reintroduced in supabase_sync.py — this makes "
                    "the module un-importable without creds and breaks CI collection"
                )


def test_sys_modules_untouched_by_isolated_exec():
    """The isolated exec must not shadow the real module for other tests."""
    real = sys.modules.get("scripts.supabase_sync")
    assert real is None or real.__name__ == "scripts.supabase_sync"
    assert "supabase_sync_isolated" not in sys.modules
