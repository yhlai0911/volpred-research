"""Tests for publisher feed lock + provenance (Phase B.3)."""
from __future__ import annotations

import json
from pathlib import Path

from volpred.publisher.publisher import Publisher


def test_append_to_feed_writes_provenance_entry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "codex")

    # Neutralize remote syncs so test is hermetic
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))
    pub._append_to_feed({
        "id": "pub_test_1",
        "title": "Test",
        "description": "desc",
        "tags": [],
    })

    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    assert len(feed) == 1
    assert feed[0]["id"] == "pub_test_1"

    log_path = tmp_path / "ops" / "writer_log.jsonl"
    assert log_path.exists(), "writer_log.jsonl should exist after publish"
    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["subsystem"] == "publisher"
    assert entry["target"] == "reports/feed.json"
    assert entry["record_id"] == "pub_test_1"
    assert entry["actor"] == "codex"
    assert entry["result"] == "ok"


def test_append_to_feed_lock_file_created(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))
    pub._append_to_feed({"id": "pub_lockcheck", "title": "t"})

    lock_file = tmp_path / "ops" / "locks" / "publisher_feed.lock"
    assert lock_file.exists(), "publisher_feed.lock should be created under storage/ops/locks"
