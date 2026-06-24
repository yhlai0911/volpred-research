from __future__ import annotations

from scripts import audit_publish_sync


def test_http_status_warns_on_transport_failure(monkeypatch, capsys) -> None:
    def fail_urlopen(*args, **kwargs):
        raise TimeoutError("network stalled")

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fail_urlopen)

    status = audit_publish_sync.http_status("https://volpred.example/reports/mile_x")

    captured = capsys.readouterr()
    assert status == 0
    assert "[publish-sync-audit] WARN live URL check failed; returning status 0" in captured.err
    assert "TimeoutError: network stalled" in captured.err
    assert "https://volpred.example/reports/mile_x" in captured.err


def test_fetch_supabase_slugs_warns_on_query_failure(monkeypatch, capsys) -> None:
    def fail_urlopen(*args, **kwargs):
        raise RuntimeError("postgrest unavailable")

    monkeypatch.setattr(audit_publish_sync.request, "urlopen", fail_urlopen)

    slugs = audit_publish_sync.fetch_supabase_slugs(
        {
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "token",
        },
        ["mile_a", "mile_b"],
    )

    captured = capsys.readouterr()
    assert slugs == set()
    assert (
        "[publish-sync-audit] WARN supabase slug fetch failed; "
        "treating remote slug set as empty"
    ) in captured.err
    assert "article_count=2" in captured.err
    assert "RuntimeError: postgrest unavailable" in captured.err
