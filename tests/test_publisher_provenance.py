"""Tests for publisher feed lock + provenance (Phase B.3)."""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path
from types import ModuleType
from contextlib import contextmanager

import pytest

from volpred.publisher import publisher as publisher_module
from volpred.publisher.publisher import Publisher


@contextmanager
def _fake_shared_state_lock(name, *, storage_dir="storage", **kwargs):
    lock_path = Path(storage_dir) / "ops" / "locks" / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()
    yield


def _install_test_stubs(monkeypatch):
    """Stub imports that drag in non-hermetic runtime dependencies."""
    ops_pkg = ModuleType("volpred.ops")
    shared_lock_mod = ModuleType("volpred.ops.shared_lock")
    writer_log_mod = ModuleType("volpred.ops.writer_log")
    shared_lock_mod.shared_state_lock = _fake_shared_state_lock
    def _append_writer_log(subsystem, target, record_id=None, *, result="ok", actor=None, storage_dir="storage"):
        path = Path(storage_dir) / "ops" / "writer_log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "actor": actor or "codex",
            "subsystem": subsystem,
            "target": target,
            "record_id": record_id,
            "result": result,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    writer_log_mod.append_writer_log = _append_writer_log
    ops_pkg.shared_lock = shared_lock_mod
    ops_pkg.writer_log = writer_log_mod
    monkeypatch.setitem(sys.modules, "volpred.ops", ops_pkg)
    monkeypatch.setitem(sys.modules, "volpred.ops.shared_lock", shared_lock_mod)
    monkeypatch.setitem(sys.modules, "volpred.ops.writer_log", writer_log_mod)

    supabase_sync_mod = ModuleType("supabase_sync")
    supabase_sync_mod.sync_article = lambda item, storage_dir=None: True
    monkeypatch.setitem(sys.modules, "supabase_sync", supabase_sync_mod)

    live_verify_mod = ModuleType("volpred.publisher.live_verify")
    live_verify_mod.verify_article_live = lambda pub_id: True
    live_verify_mod.stamp_verified = lambda item, verified=True: item.update({"live_verified": verified})
    live_verify_mod.emit_verify_alert = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "volpred.publisher.live_verify", live_verify_mod)

    # Publishing imports EmailNotifier lazily after the feed write.  Stub the
    # module itself so hermetic tests never probe the developer machine's
    # untracked .env/.env.local files (which clean CI does not have).
    email_notifier_mod = ModuleType("volpred.publisher.email_notifier")

    class _EmailNotifier:
        def __init__(self, *args, **kwargs):
            pass

        def notify_article_published(self, *args, **kwargs):
            return None

    email_notifier_mod.EmailNotifier = _EmailNotifier
    monkeypatch.setitem(sys.modules, "volpred.publisher.email_notifier", email_notifier_mod)


def test_append_to_feed_writes_provenance_entry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "codex")
    _install_test_stubs(monkeypatch)

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
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))
    pub._append_to_feed({"id": "pub_lockcheck", "title": "t"})

    lock_file = tmp_path / "ops" / "locks" / "publisher_feed.lock"
    assert lock_file.exists(), "publisher_feed.lock should be created under storage/ops/locks"


def test_identityless_event_append_fails_open_without_durable_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(
        publisher_module,
        "_log_dedup_decision",
        lambda *_args, **_kwargs: False,
    )

    item = {
        "id": "mile_identity_receipt_failure",
        "title": "FOMC event",
        "content": "Event body.",
        "audience": "event",
        "category": "event_article",
        "status": "draft",
        "details": {"content_type": "event_article"},
    }

    assert Publisher(storage_dir=str(tmp_path))._append_to_feed(item) == item["id"]
    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    assert [row["id"] for row in feed] == [item["id"]]


def _make_png(path: Path) -> Path:
    """Write a minimal valid 1x1 PNG to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    raw = b"\x00\x00"
    idat = zlib.compress(raw)
    path.write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    return path


def test_publish_milestone_auto_uploads_markdown_and_details_charts(tmp_path: Path, monkeypatch):
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_find_similar_articles", lambda self, *a, **kw: [], raising=False)

    monkeypatch.setattr(
        "volpred.publisher.publisher.cluster_gate_status",
        lambda cluster: {"count": 0, "cap": 999, "ratio": 0.0, "blocked": False},
    )
    monkeypatch.setattr(
        "volpred.publisher.publisher.classify_topic_cluster",
        lambda title, tags, description: "test_cluster",
    )

    chart_a = _make_png(tmp_path / "experiments" / "k001" / "chart_a.png")
    chart_b = _make_png(tmp_path / "experiments" / "k001" / "chart_b.png")

    calls: list[str] = []

    def fake_upload_chart(local_path: str, bucket: str = "article-images") -> str:
        calls.append(local_path)
        return f"https://supabase.test/{Path(local_path).name}"

    monkeypatch.setattr("volpred.charts.upload_chart", fake_upload_chart)

    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="一般讀者測試文章",
        description="![圖一](experiments/k001/chart_a.png)\n\n內容段落。",
        phase="test_phase",
        details={"charts": ["experiments/k001/chart_b.png"]},
        tags=["一般讀者", "測試"],
        audience="general",
        audit_strict=False,
    )

    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(x for x in feed if x["id"] == pub_id)

    assert "https://supabase.test/chart_a.png" in item["content"]
    assert "experiments/k001/chart_a.png" not in item["content"]
    assert item["details"]["charts"] == ["https://supabase.test/chart_b.png"]
    assert item["details"]["image_urls"] == [
        "https://supabase.test/chart_a.png",
        "https://supabase.test/chart_b.png",
    ]
    assert item["details"]["supabase_storage_urls"] == [
        "https://supabase.test/chart_a.png",
        "https://supabase.test/chart_b.png",
    ]
    assert calls == [str(chart_a), str(chart_b)]


def test_publish_milestone_stamps_event_metadata_top_level(tmp_path: Path, monkeypatch):
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_find_similar_articles", lambda self, *a, **kw: [], raising=False)
    monkeypatch.setattr(
        "volpred.publisher.publisher.cluster_gate_status",
        lambda cluster: {"count": 0, "cap": 999, "ratio": 0.0, "blocked": False},
    )
    monkeypatch.setattr(
        "volpred.publisher.publisher.classify_topic_cluster",
        lambda title, tags, description: None,
    )

    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="NFP reaction article",
        description="event-driven analysis",
        phase="event_article",
        details={
            "content_type": "event_article",
            "event_key": "NFP_US_2026_07_03",
            "event_type": "NFP_US",
            "event_date": "2026-07-03",
            "event_series_slot": "T+0",
        },
        tags=["event_article", "NFP"],
        audience="event",
        category="event_article",
        audit_strict=False,
    )

    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(x for x in feed if x["id"] == pub_id)

    assert item["event_key"] == "NFP_US_2026_07_03"
    assert item["event_type"] == "NFP_US"
    assert item["event_date"] == "2026-07-03"
    assert item["event_series_slot"] == "T+0"
    assert item["details"]["event_key"] == "NFP_US_2026_07_03"


def test_live_event_publish_requires_complete_canonical_metadata(tmp_path: Path, monkeypatch):
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(Publisher, "_find_similar_articles", lambda self, *a, **kw: [], raising=False)
    monkeypatch.setattr(
        "volpred.publisher.publisher.cluster_gate_status",
        lambda cluster: {"count": 0, "cap": 999, "ratio": 0.0, "blocked": False},
    )
    monkeypatch.setattr(
        "volpred.publisher.publisher.classify_topic_cluster",
        lambda title, tags, description: None,
    )

    with pytest.raises(ValueError, match="event article is missing canonical metadata"):
        Publisher(storage_dir=str(tmp_path)).publish_milestone(
            title="CPI reaction article",
            description="event-driven analysis",
            phase="event_article",
            details={"content_type": "event_article", "event_type": "CPI_US"},
            tags=["event_article", "CPI"],
            audience="event",
            category="event_article",
            audit_strict=True,
        )

    with pytest.raises(ValueError, match="event article is missing canonical metadata"):
        Publisher(storage_dir=str(tmp_path)).publish_milestone(
            title="CPI reaction article migration bypass attempt",
            description="event-driven analysis",
            phase="event_article",
            details={"content_type": "event_article", "event_type": "CPI_US"},
            tags=["event_article", "CPI"],
            audience="event",
            category="event_article",
            status="published",
            audit_strict=False,
        )

    with pytest.raises(ValueError, match="event article is missing canonical metadata"):
        Publisher(storage_dir=str(tmp_path)).publish_milestone(
            title="CPI identity-less draft bypass attempt",
            description="event-driven draft",
            phase="event_article",
            details={"content_type": "event_article", "event_type": "CPI_US"},
            tags=["event_article", "CPI"],
            audience="event",
            category="event_article",
            status="draft",
            audit_strict=False,
        )

    assert not (tmp_path / "reports" / "feed.json").exists()


def test_event_metadata_block_fails_open_without_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_test_stubs(monkeypatch)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(
        publisher_module,
        "_log_dedup_decision",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        Publisher,
        "_append_to_feed",
        lambda self, item: item["id"],
    )

    pub_id = Publisher(storage_dir=str(tmp_path)).publish_milestone(
        title="CPI identity receipt outage",
        description="event-driven analysis",
        phase="event_article",
        details={"content_type": "event_article", "event_type": "CPI_US"},
        tags=["event_article", "CPI"],
        audience="event",
        category="event_article",
        status="published",
        audit_strict=True,
    )

    assert pub_id.startswith("mile_")
