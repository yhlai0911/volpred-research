"""Gate: a network blip must not be reported as a real failure.

2026-07-16: one timed-out socket exited `paper_sync_all` non-zero, which raised a
critical `host_cron_fail` for a condition that had already cured itself, and the
same flake failed the publish read-back of an article that had actually synced
(mile_f9c70bd0). Retrying lives at `_urlopen`, the single egress chokepoint, so a
newly added request helper cannot forget it — the same reasoning as the read gate.

The dangerous half of retrying is replay: re-sending a bare POST whose insert the
server had already committed duplicates the row. These tests pin both halves —
transient failures are absorbed, and only for requests whose replay converges.
"""
from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_supabase_sync():
    spec = importlib.util.spec_from_file_location(
        "supabase_sync", ROOT / "scripts" / "supabase_sync.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod(monkeypatch):
    m = _load_supabase_sync()
    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "0")
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)  # no real backoff in tests
    return m


def _timeout_error():
    return URLError(socket.timeout("timed out"))


def test_transient_timeout_is_absorbed(mod, monkeypatch):
    """The exact 2026-07-16 failure: first call times out, retry succeeds."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        if len(calls) == 1:
            raise _timeout_error()
        return "response"

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request("https://x.supabase.co/rest/v1/papers?select=id", method="GET")

    assert mod._urlopen(req) == "response"
    assert len(calls) == 2


def test_persistent_timeout_still_raises(mod, monkeypatch):
    """Retrying must not turn a genuinely dead endpoint into silence."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        raise _timeout_error()

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request("https://x.supabase.co/rest/v1/papers?select=id", method="GET")

    with pytest.raises(URLError):
        mod._urlopen(req)
    assert len(calls) == mod._RETRY_MAX_ATTEMPTS


def test_bare_post_is_never_replayed(mod, monkeypatch):
    """A POST without on_conflict may have committed before the timeout."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        raise _timeout_error()

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request("https://x.supabase.co/rest/v1/articles", data=b"[]", method="POST")

    with pytest.raises(URLError):
        mod._urlopen(req)
    assert len(calls) == 1, "bare POST retried — this duplicates rows"


def test_upsert_post_is_replay_safe(mod, monkeypatch):
    """POST carrying on_conflict is an upsert, so replay converges."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        if len(calls) == 1:
            raise _timeout_error()
        return "response"

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request(
        "https://x.supabase.co/rest/v1/articles?on_conflict=slug", data=b"[]", method="POST"
    )

    assert mod._urlopen(req) == "response"
    assert len(calls) == 2


def test_client_error_is_not_retried(mod, monkeypatch):
    """A 400 is the request being wrong; re-sending it wastes time and hides it."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        raise HTTPError(req.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request("https://x.supabase.co/rest/v1/papers?select=id", method="GET")

    with pytest.raises(HTTPError):
        mod._urlopen(req)
    assert len(calls) == 1


def test_server_error_is_retried(mod, monkeypatch):
    """5xx/429 are the server asking to be asked again."""
    calls = []

    def fake_urlopen(req, timeout=15):
        calls.append(req)
        if len(calls) == 1:
            raise HTTPError(req.full_url, 503, "Service Unavailable", {}, None)
        return "response"

    monkeypatch.setattr(mod, "urlopen", fake_urlopen)
    req = Request("https://x.supabase.co/rest/v1/papers?select=id", method="GET")

    assert mod._urlopen(req) == "response"
    assert len(calls) == 2


def test_read_gate_still_wins_over_retry(mod, monkeypatch):
    """The test-isolation gate must fire before any retry loop can reach the network."""
    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "1")
    calls = []
    monkeypatch.setattr(mod, "urlopen", lambda req, timeout=15: calls.append(req))
    req = Request("https://x.supabase.co/rest/v1/papers?select=id", method="GET")

    with pytest.raises(RuntimeError, match="Blocked live Supabase read"):
        mod._urlopen(req)
    assert calls == []
