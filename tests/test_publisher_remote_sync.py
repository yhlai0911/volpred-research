from __future__ import annotations

import gzip
import json
import random
import sys
import types
import urllib.request
from pathlib import Path

from volpred.publisher.email_notifier import EmailNotifier
from volpred.publisher.publisher import Publisher


def test_sync_feed_to_remote_gzips_large_compressible_feed(
    tmp_path: Path,
    monkeypatch,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    feed_path = reports_dir / "feed.json"
    original = b"[" + (b" " * (9 * 1024 * 1024)) + b"]"
    feed_path.write_bytes(original)

    captured: dict[str, object] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["encoding"] = req.get_header("Content-encoding")
        captured["content_type"] = req.get_header("Content-type")
        captured["timeout"] = timeout
        return object()

    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr("volpred.mirror_auth.ops_admin_headers", lambda: {"x-test-token": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    Publisher(storage_dir=str(tmp_path))._sync_feed_to_remote()

    assert captured["url"] == "https://mirror.example/api/sync/feed.json"
    assert captured["encoding"] == "gzip"
    assert captured["content_type"] == "application/json"
    payload = captured["data"]
    assert isinstance(payload, bytes)
    assert len(payload) < 8 * 1024 * 1024
    assert gzip.decompress(payload) == original


def test_sync_feed_to_remote_skips_large_incompressible_feed(
    tmp_path: Path,
    monkeypatch,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    # Deterministic, high-entropy enough to stay above the 8MB mirror ceiling
    # after gzip. The sync path does not parse the JSON before deciding whether
    # the whole-file mirror PUT is feasible.
    feed_path = reports_dir / "feed.json"
    feed_path.write_bytes(random.Random(42).randbytes(9 * 1024 * 1024))

    calls: list[object] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        calls.append(req)
        return object()

    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr("volpred.mirror_auth.ops_admin_headers", lambda: {"x-test-token": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    Publisher(storage_dir=str(tmp_path))._sync_feed_to_remote()

    assert calls == []


def test_article_notification_failure_warns_without_blocking(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    def fail_notify(self, *args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(EmailNotifier, "notify_article_published", fail_notify)
    pub = Publisher(storage_dir=str(tmp_path))

    result = pub._notify_article_published(
        {"id": "mile_notify_fail", "title": "Notification failure"},
        reason="publish_milestone",
    )

    captured = capsys.readouterr()
    assert result is None
    assert "[email_notify] article notification failed" in captured.out
    assert "mile_notify_fail" in captured.out
    assert "smtp down" in captured.out


def test_unpublish_supabase_sync_failure_is_queued(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_unpublish_fail",
                    "title": "Unpublish failure",
                    "status": "published",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_sync_article(*args, **kwargs):
        raise RuntimeError("postgrest down")

    fake_supabase_sync = types.SimpleNamespace(sync_article=fail_sync_article)
    monkeypatch.setitem(sys.modules, "supabase_sync", fake_supabase_sync)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None)

    assert Publisher(storage_dir=str(tmp_path)).unpublish("mile_unpublish_fail") is True

    queue = json.loads((tmp_path / ".failed_supabase_syncs.json").read_text(encoding="utf-8"))
    feed = json.loads((reports_dir / "feed.json").read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert queue == ["mile_unpublish_fail"]
    assert feed[0]["status"] == "unpublished"
    assert "Supabase unpublish sync exception for mile_unpublish_fail" in captured.out
    assert "recorded to .failed_supabase_syncs.json" in captured.out


def test_publish_milestone_bad_existing_timestamp_keeps_exact_title_gate(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_bad_timestamp",
                    "title": "Same Title",
                    "status": "published",
                    "published_at": "not-a-date",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    result = Publisher(storage_dir=str(tmp_path)).publish_milestone(
        title="Same Title",
        description="新的文章不應穿過 exact-title duplicate gate。",
        phase="research",
        status="draft",
    )

    captured = capsys.readouterr()
    assert result == "mile_bad_timestamp"
    assert "Duplicate title timestamp parse failed" in captured.out
