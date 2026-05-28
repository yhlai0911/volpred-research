from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backfill_audience.py"
SPEC = importlib.util.spec_from_file_location("backfill_audience", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_normalize_tags_rewrites_audience_aliases():
    tags = ["一般讀者", "K123", "audience=general", "研究", "量化"]
    assert MODULE.normalize_tags(tags, audience="research") == ["研究", "K123", "量化"]


def test_patch_article_payload_sets_research_and_backfill_metadata():
    payload = {
        "id": "mile_x",
        "audience": "general",
        "tags": ["一般讀者", "K123"],
        "details": {"experiment_refs": ["K123"]},
    }

    changed = MODULE.patch_article_payload(payload, article_id="mile_x", run_at="2026-05-27T00:00:00+00:00")

    assert changed is True
    assert payload["audience"] == "research"
    assert payload["tags"][0] == "研究"
    assert payload["details"]["audience"] == "research"
    assert payload["details"]["audience_backfill"]["reason"] == "validator_371_historical_backfill"


def test_apply_backfill_updates_feed_and_existing_report(tmp_path, monkeypatch):
    feed_path = tmp_path / "storage" / "reports" / "feed.json"
    report_path = tmp_path / "storage" / "reports" / "mile_a.json"
    archive_dir = tmp_path / "storage" / "reports" / "_archive_mile_files"
    archive_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    feed = [
        {
            "id": "mile_a",
            "title": "K123 Sharpe 測試",
            "description": "K123 與 Sharpe",
            "audience": "general",
            "status": "published",
            "tags": ["一般讀者", "K123"],
            "details": {},
        }
    ]
    feed_path.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(json.dumps(feed[0], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    monkeypatch.setattr(MODULE, "OPS_DIR", tmp_path / "storage" / "ops")
    monkeypatch.setattr(MODULE, "REPORTS_DIR", tmp_path / "storage" / "reports")
    monkeypatch.setattr(MODULE, "ARCHIVE_DIR", archive_dir)

    plan = {
        "generated_at": "2026-05-27T00:00:00+00:00",
        "violations": [{"id": "mile_a", "title": "K123 Sharpe 測試", "status": "published", "keywords": ["K-id", "Sharpe"], "report_paths": []}],
        "count": 1,
    }

    result = MODULE.apply_backfill(feed, plan)

    assert result["patched_feed_entries"] == 1
    updated_feed = json.loads(feed_path.read_text(encoding="utf-8"))
    updated_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert updated_feed[0]["audience"] == "research"
    assert updated_report["audience"] == "research"
