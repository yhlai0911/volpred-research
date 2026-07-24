from __future__ import annotations

import pytest

from scripts import audit_publish_sync


def test_http_status_warns_on_transport_failure(monkeypatch, capsys) -> None:
    def fail_urlopen(*args, **kwargs):
        raise TimeoutError("network stalled")

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fail_urlopen)

    with pytest.raises(
        audit_publish_sync.RemoteObservationUnavailable,
        match="live_url_observation_unavailable",
    ):
        audit_publish_sync.http_status(
            "https://volpred.example/reports/mile_x"
        )

    captured = capsys.readouterr()
    assert "[publish-sync-audit] WARN live URL check failed" in captured.err
    assert "TimeoutError: network stalled" in captured.err
    assert "https://volpred.example/reports/mile_x" in captured.err


def test_fetch_supabase_slugs_warns_on_query_failure(monkeypatch, capsys) -> None:
    def fail_urlopen(*args, **kwargs):
        raise RuntimeError("postgrest unavailable")

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fail_urlopen)

    with pytest.raises(
        audit_publish_sync.RemoteObservationUnavailable,
        match="supabase_observation_unavailable",
    ):
        audit_publish_sync.fetch_supabase_slugs(
            {
                "SUPABASE_URL": "https://supabase.example",
                "SUPABASE_SERVICE_ROLE_KEY": "token",
            },
            "2026-07-22T02:00:00Z",
        )

    captured = capsys.readouterr()
    assert (
        "[publish-sync-audit] WARN supabase slug fetch failed "
        "window_start=2026-07-22T02:00:00Z"
    ) in captured.err
    assert "RuntimeError: postgrest unavailable" in captured.err


def test_fetch_supabase_slugs_queries_complete_published_window(
    monkeypatch,
) -> None:
    observed = {}

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'[{"slug":"mile_remote","status":"published"}]'

    def fake_urlopen(req, timeout):
        observed["url"] = req.full_url
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fake_urlopen)

    result = audit_publish_sync.fetch_supabase_slugs(
        {
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "token",
        },
        "2026-07-22T02:00:00Z",
    )

    assert result == {"mile_remote"}
    assert observed["timeout"] == 15
    assert "status=eq.published" in observed["url"]
    assert "published_at=gte.2026-07-22T02:00:00Z" in observed["url"]
    assert "slug=in." not in observed["url"]


def test_fetch_supabase_slugs_paginates_the_complete_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(audit_publish_sync, "SUPABASE_PAGE_SIZE", 2)
    observed_ranges = []
    pages = [
        (
            b'[{"slug":"mile_a","status":"published"},'
            b'{"slug":"mile_b","status":"published"}]',
            {"Content-Range": "0-1/3"},
        ),
        (
            b'[{"slug":"mile_c","status":"published"}]',
            {"Content-Range": "2-2/3"},
        ),
    ]

    class Response:
        def __init__(self, body, headers):
            self.body = body
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout):
        observed_ranges.append(req.headers["Range"])
        body, headers = pages.pop(0)
        return Response(body, headers)

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fake_urlopen)

    result = audit_publish_sync.fetch_supabase_slugs(
        {
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "token",
        },
        "2026-07-22T02:00:00Z",
    )

    assert result == {"mile_a", "mile_b", "mile_c"}
    assert observed_ranges == ["0-1", "2-3"]
    assert pages == []
