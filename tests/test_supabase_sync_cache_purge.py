"""Regression: syncing an article must purge the frontend's unstable_cache tags.

Incident (2026-07-19, discovered while retracting mile_ebb5d6f5): after
sync_full() the Supabase row was `status=retracted` and invisible to the anon
key under RLS, yet https://volpred.zeabur.app/v3/reports/mile_ebb5d6f5 kept
returning HTTP 200 with the full body for >15 minutes -- far past the page's
`revalidate = 300` and unstable_cache's `revalidate: 60`. cache-control was
no-store, so no CDN was involved.

Two conditions had to stack:

  1. scripts/supabase_sync.py writes straight to Supabase REST, bypassing
     frontend-v2-fix/src/app/api/sync/[...path]/route.ts -- the only caller of
     revalidateTag('article') / revalidateTag(`article-<slug>`).
  2. data-server.ts getArticleInternal *throws* for a retracted row (status
     filter + RLS both miss -> .single() errors). unstable_cache's background
     stale-while-revalidate has no new value to write when the loader throws,
     so it keeps re-serving the last good value. Expiry is not eviction.

Owner of the fix is the projection provider (condition 1):
``sync_article_projection`` now POSTs
/api/sync/revalidate/article/<slug> after every successful write. These tests
pin that provider behaviour so the purge cannot be dropped again.

The live end-to-end check (retract -> sync -> curl -> 404) needs the real
deployment and is env-gated; CI never touches the network.
"""
from __future__ import annotations

import importlib.util
import json
import os
import urllib.error
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SYNC_PATH = _REPO_ROOT / "scripts" / "supabase_sync.py"


def _load_sync():
    """Fresh module instance per test (module-level _REVALIDATE_FAILURES)."""
    spec = importlib.util.spec_from_file_location("supabase_sync_purge_test", _SYNC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture
def sync(monkeypatch):
    module = _load_sync()
    # conftest sets VOLPRED_NO_REMOTE_WRITE=1, which short-circuits the purge.
    # These tests exercise the purge itself, so lift it and stub the network.
    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setenv("VOLPRED_REMOTE_URL", "https://volpred.example.test")
    monkeypatch.setenv("OPS_ADMIN_TOKEN", "test-ops-token")
    return module


class _FakeResponse:
    def __init__(self, status: int = 200, body=None):
        self.status = status
        self.body = (
            {
                "status": "revalidated",
                "slug": "mile_ebb5d6f5",
                "tags": ["article", "article-mile_ebb5d6f5"],
            }
            if body is None
            else body
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if isinstance(self.body, bytes):
            return self.body
        return json.dumps(self.body).encode("utf-8")


def _capture(monkeypatch, sync, response=None, raises=None):
    """Stub the purge's urlopen; return the list it records requests into."""
    calls: list = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if raises is not None:
            raise raises
        return response or _FakeResponse(200)

    monkeypatch.setattr(sync, "urlopen", fake_urlopen)
    return calls


def _stub_db(monkeypatch, sync, status="retracted"):
    """Make the Supabase write path succeed without touching the network."""
    monkeypatch.setattr(sync, "_post", lambda *a, **k: True)
    monkeypatch.setattr(sync, "_patch_where", lambda *a, **k: True)
    monkeypatch.setattr(sync, "_delete_where", lambda *a, **k: True)
    monkeypatch.setattr(sync, "_get_article_id", lambda slug: None)
    monkeypatch.setattr(
        sync,
        "_select_rows",
        lambda table, **kw: [
            {
                "slug": kw.get("slug"),
                "status": status,
                "published_at": None,
                "audience": "research",
            }
        ]
        if table == "articles"
        else [],
    )


def _retracted_item() -> dict:
    return {
        "id": "mile_ebb5d6f5",
        "title": "已撤稿測試文章",
        "content": "本文已撤稿。",
        "status": "retracted",
        "audience": "research",
        "category": "milestone",
        "published_at": None,
    }


# --- the core regression -----------------------------------------------------


def test_retraction_sync_purges_frontend_cache(monkeypatch, sync):
    """Retracting via sync_article must POST the tag purge for that slug.

    This is the exact mile_ebb5d6f5 path: feed.json flips status to
    'retracted', sync_full -> sync_article writes Supabase. Before the fix
    nothing purged `article-mile_ebb5d6f5`, so readers kept the old body.
    """
    _stub_db(monkeypatch, sync)
    calls = _capture(monkeypatch, sync)

    assert sync.sync_article_projection(_retracted_item()) is True

    assert len(calls) == 1, "retraction sync must issue exactly one purge"
    req = calls[0]
    assert req.full_url == (
        "https://volpred.example.test/api/sync/revalidate/article/mile_ebb5d6f5"
    )
    assert req.get_method() == "POST"
    # Auth header must be attached (2026-06-11: unauthenticated mirror writes
    # 401'd silently for a month).
    assert req.headers.get("X-ops-key") == "test-ops-token"
    assert sync._REVALIDATE_FAILURES == []


def test_formal_cache_ack_keeps_target_status_and_digest(monkeypatch, sync):
    _stub_db(monkeypatch, sync)
    _capture(monkeypatch, sync, response=_FakeResponse(204))

    result = sync.sync_article_projection_result(
        _retracted_item(),
        require_cache_ack=True,
    )

    assert result.succeeded is True
    acknowledgement = result.cache_acknowledgement
    assert acknowledgement is not None
    assert acknowledgement.acknowledged is True
    assert acknowledgement.status_code == 204
    assert acknowledgement.target_ref.endswith(
        "/api/sync/revalidate/article/mile_ebb5d6f5"
    )
    assert acknowledgement.evidence_ref.endswith("#status=204")
    assert len(acknowledgement.evidence_sha256) == 64


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        {
            "status": "noop",
            "slug": "mile_ebb5d6f5",
            "tags": ["article", "article-mile_ebb5d6f5"],
        },
        {
            "status": "revalidated",
            "slug": "mile_wrong",
            "tags": ["article", "article-mile_wrong"],
        },
        {
            "status": "revalidated",
            "slug": "mile_ebb5d6f5",
            "tags": ["article"],
        },
    ],
)
def test_http_2xx_without_exact_cache_ack_body_fails_closed(
    monkeypatch,
    sync,
    body,
):
    _capture(
        monkeypatch,
        sync,
        response=_FakeResponse(200, body=body),
    )

    acknowledgement = sync.revalidate_article_cache_with_evidence(
        "mile_ebb5d6f5"
    )

    assert acknowledgement.acknowledged is False
    assert acknowledgement.status_code == 200
    assert acknowledgement.evidence_ref.endswith("#status=200")
    assert len(acknowledgement.evidence_sha256) == 64
    assert sync._REVALIDATE_FAILURES == ["mile_ebb5d6f5"]


def test_status_downgrade_purges_frontend_cache(monkeypatch, sync):
    """sync_article_status('unpublished') is the other visibility downgrade."""
    _stub_db(monkeypatch, sync)
    calls = _capture(monkeypatch, sync)

    assert sync.sync_article_status("mile_ebb5d6f5", "unpublished") is True

    assert [r.full_url for r in calls] == [
        "https://volpred.example.test/api/sync/revalidate/article/mile_ebb5d6f5"
    ]


def test_hard_delete_purges_frontend_cache(monkeypatch, sync):
    _stub_db(monkeypatch, sync)
    calls = _capture(monkeypatch, sync)

    assert sync.delete_article("mile_ebb5d6f5") is True

    assert [r.full_url for r in calls] == [
        "https://volpred.example.test/api/sync/revalidate/article/mile_ebb5d6f5"
    ]


# --- loud failure ------------------------------------------------------------


def test_missing_ops_token_fails_loudly(monkeypatch, sync, capsys):
    """No OPS_ADMIN_TOKEN must not degrade into a silent skip."""
    monkeypatch.delenv("OPS_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(sync, "_mirror_base_url", lambda: "https://volpred.example.test")
    # mirror_auth falls back to .env.local on disk; neutralise that too so the
    # test asserts the no-token branch regardless of the developer's machine.
    import volpred.mirror_auth as mirror_auth

    monkeypatch.setattr(mirror_auth, "ops_admin_token", lambda: None)
    calls = _capture(monkeypatch, sync)

    assert sync.revalidate_article_cache("mile_ebb5d6f5") is False
    assert calls == [], "must not attempt an unauthenticated purge"
    assert "CACHE PURGE FAILED" in capsys.readouterr().out
    assert sync._REVALIDATE_FAILURES == ["mile_ebb5d6f5"]


def test_401_fails_loudly_and_is_recorded(monkeypatch, sync, capsys):
    """A rejected token must be shouted about, not swallowed."""
    _capture(
        monkeypatch,
        sync,
        raises=urllib.error.HTTPError(
            "https://volpred.example.test", 401, "Unauthorized", {}, None  # type: ignore[arg-type]
        ),
    )

    assert sync.revalidate_article_cache("mile_ebb5d6f5") is False
    out = capsys.readouterr().out
    assert "CACHE PURGE FAILED" in out
    assert "UNAUTHORIZED" in out
    assert sync._REVALIDATE_FAILURES == ["mile_ebb5d6f5"]


def test_purge_failure_does_not_mask_successful_db_write(monkeypatch, sync):
    """The projection contract is the DB write; the purge reports separately."""
    _stub_db(monkeypatch, sync)
    _capture(monkeypatch, sync, raises=urllib.error.URLError("dns"))

    assert sync.sync_article_projection(_retracted_item()) is True
    assert sync._REVALIDATE_FAILURES == ["mile_ebb5d6f5"]


def test_cli_exits_non_zero_when_purge_failed(sync):
    """A green 'Done.' must not hide a broken purge."""
    assert sync._report_counts({"articles": 3}) == 0
    assert sync._report_counts({"articles": 3, "cache_purge_failed": ["mile_x"]}) == 1


def test_remote_write_kill_switch_skips_purge(monkeypatch, sync):
    """VOLPRED_NO_REMOTE_WRITE=1 (conftest) must block the outbound purge too."""
    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")
    calls = _capture(monkeypatch, sync)

    assert sync.revalidate_article_cache("mile_ebb5d6f5") is True
    assert calls == []


# --- live end-to-end (manual / integration; never runs in CI) ----------------


@pytest.mark.skipif(
    not os.environ.get("VOLPRED_LIVE_INTEGRATION"),
    reason="hits the live deployment; set VOLPRED_LIVE_INTEGRATION=1 to run",
)
def test_live_retracted_article_returns_404():
    """Retracted articles must 404 on the live site.

    Run manually after a retraction:
        VOLPRED_LIVE_INTEGRATION=1 pytest tests/test_supabase_sync_cache_purge.py -k live

    Override the slug with VOLPRED_LIVE_RETRACTED_SLUG.
    """
    import urllib.request

    slug = os.environ.get("VOLPRED_LIVE_RETRACTED_SLUG", "mile_ebb5d6f5")
    base = os.environ.get("VOLPRED_REMOTE_URL", "https://volpred.zeabur.app")
    for path in (f"/v3/reports/{slug}", f"/reports/{slug}"):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=20) as resp:
                pytest.fail(f"{path} returned HTTP {resp.status}; expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404, f"{path} returned HTTP {exc.code}; expected 404"
