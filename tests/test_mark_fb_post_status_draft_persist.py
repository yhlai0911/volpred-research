"""Regression tests for the 2026-07-07 FB canonical-draft persistence invariant.

Root cause (docs/error_log.md 2026-07-07): FB 稿寫手 marked
awaiting_interactive_session but never persisted the finished post to the
canonical location storage/drafts/fb_<mile_id>.md, so an interactive session
had no reference copy → post got lost. Fix makes mark_fb_post_status the
enforcement owner and audit_fb_pipeline the backstop.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module(name: str, rel_path: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


mark_fb = _load_module("mark_fb_post_status", "scripts/mark_fb_post_status.py")
audit_fb = _load_module("audit_fb_pipeline", "scripts/audit_fb_pipeline.py")


@pytest.fixture()
def fb_paths(tmp_path, monkeypatch):
    """Point mark_fb_post_status at isolated feed/log/drafts under tmp."""
    feed = tmp_path / "feed.json"
    log = tmp_path / "trending_repost_log.json"
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    feed.write_text(json.dumps([{"id": "mile_abc123", "fb_post_status": "pending"}]), encoding="utf-8")
    log.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(mark_fb, "FEED_PATH", feed)
    monkeypatch.setattr(mark_fb, "TRENDING_LOG_PATH", log)
    monkeypatch.setattr(mark_fb, "DRAFTS_DIR", drafts)
    return {"feed": feed, "log": log, "drafts": drafts}


def test_canonical_path_prefixes_fb_and_keeps_mile_id():
    p = mark_fb.canonical_fb_draft_path("mile_08fefa59")
    assert p.name == "fb_mile_08fefa59.md"
    # bare suffix without mile_ prefix normalizes too
    assert mark_fb.canonical_fb_draft_path("08fefa59").name == "fb_mile_08fefa59.md"


def test_awaiting_with_draft_file_persists_canonical(fb_paths):
    body = "## 主貼文\n測試完稿\n\n## 第一則留言\nhttps://volpred.zeabur.app/v3/reports/mile_abc123"
    result = mark_fb.update_fb_status(
        "mile_abc123", status="awaiting_interactive_session", draft_text=body
    )
    canonical = fb_paths["drafts"] / "fb_mile_abc123.md"
    assert canonical.exists()
    assert "測試完稿" in canonical.read_text(encoding="utf-8")
    assert canonical.read_text(encoding="utf-8").endswith("\n")
    assert result["draft_path"] == str(canonical)
    assert result["updated_feed"] == 1


def test_awaiting_without_draft_and_no_existing_refuses(fb_paths):
    with pytest.raises(mark_fb.DraftRequiredError):
        mark_fb.update_fb_status("mile_abc123", status="awaiting_interactive_session")
    # feed status must NOT have been mutated (fail-closed BEFORE write)
    feed = json.loads(fb_paths["feed"].read_text(encoding="utf-8"))
    assert feed[0]["fb_post_status"] == "pending"


def test_awaiting_without_draft_but_existing_canonical_ok(fb_paths):
    (fb_paths["drafts"] / "fb_mile_abc123.md").write_text("既有稿\n", encoding="utf-8")
    result = mark_fb.update_fb_status("mile_abc123", status="awaiting_interactive_session")
    assert result["updated_feed"] == 1
    assert result["draft_path"].endswith("fb_mile_abc123.md")


def test_nonhandoff_status_does_not_require_draft(fb_paths):
    # success / expired_skip / wont_fix never require a persisted draft
    result = mark_fb.update_fb_status("mile_abc123", status="success")
    assert "draft_path" not in result
    assert result["updated_feed"] == 1
    assert not (fb_paths["drafts"] / "fb_mile_abc123.md").exists()


def test_success_writes_permalink_and_posted_at(fb_paths):
    # 發文成功時把抓到的 permalink + posted_at 一併寫進 canonical
    url = "https://www.facebook.com/yihao.lai/posts/pfbid0TEST"
    ts = "2026-07-08T00:21:01+00:00"
    result = mark_fb.update_fb_status(
        "mile_abc123", status="success", post_url=url, posted_at=ts
    )
    assert result["fb_post_url"] == url
    assert result["fb_posted_at"] == ts
    feed = json.loads(fb_paths["feed"].read_text(encoding="utf-8"))
    assert feed[0]["fb_post_url"] == url
    assert feed[0]["fb_posted_at"] == ts


def test_success_without_permalink_does_not_null_existing(fb_paths):
    # permalink 抓不到（None）時，不可把既有非空 fb_post_url 覆蓋成 None
    url = "https://www.facebook.com/yihao.lai/posts/pfbidPREEXIST"
    feed_data = [{"id": "mile_abc123", "fb_post_status": "success", "fb_post_url": url}]
    fb_paths["feed"].write_text(json.dumps(feed_data), encoding="utf-8")
    result = mark_fb.update_fb_status("mile_abc123", status="success")  # 無 post_url
    assert "fb_post_url" not in result  # None 不進 result
    feed = json.loads(fb_paths["feed"].read_text(encoding="utf-8"))
    assert feed[0]["fb_post_url"] == url  # 既有值保留


def test_clear_fields_nulls_wrong_capture(fb_paths):
    # 撤回誤抓的 permalink：clear_fields 把欄位設回 None（修正錯誤 capture 的正式途徑）
    feed_data = [{"id": "mile_abc123", "fb_post_status": "success",
                  "fb_post_url": "https://fb.com/wrong/pfbidWRONG",
                  "fb_posted_at": "2026-07-08T00:21:01+00:00"}]
    fb_paths["feed"].write_text(json.dumps(feed_data), encoding="utf-8")
    mark_fb.update_fb_status("mile_abc123", status="success", clear_fields=["fb_post_url"])
    feed = json.loads(fb_paths["feed"].read_text(encoding="utf-8"))
    assert feed[0]["fb_post_url"] is None       # 撤回
    assert feed[0]["fb_posted_at"] == "2026-07-08T00:21:01+00:00"  # 不動其他欄位


def test_audit_flags_missing_draft(tmp_path, monkeypatch):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    monkeypatch.setattr(audit_fb, "DRAFTS_DIR", drafts)
    data = [
        {"mile_id": "mile_missing", "fb_post_status": "awaiting_interactive_session", "date": "2026-07-08T00:00:00"},
        {"mile_id": "mile_pending", "fb_post_status": "pending", "date": "2026-07-08T00:00:00"},
        {"mile_id": "mile_present", "fb_post_status": "awaiting_interactive_session", "date": "2026-07-08T00:00:00"},
        {"mile_id": "mile_done", "fb_post_status": "success", "date": "2026-07-08T00:00:00"},
    ]
    (drafts / "fb_mile_present.md").write_text("有稿\n", encoding="utf-8")
    missing = audit_fb._scan_missing_drafts(data)
    ids = {m["mile_id"] for m in missing}
    assert ids == {"mile_missing", "mile_pending"}  # all non-terminal missing copies surface
    assert missing[0]["expected_draft"].endswith("fb_mile_missing.md")
