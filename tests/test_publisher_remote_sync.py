from __future__ import annotations

import gzip
import random
import urllib.request
from pathlib import Path

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
