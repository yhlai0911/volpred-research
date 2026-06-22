"""Regression: daily_digest 必須豁免 publisher 的 dup gates（2026-06-23 incident）。

每日精選導讀是 meta-curation，本來就會引用同主題的多篇舊文，必然與被策展文章共享
experiment_refs / 標題主題 / narrative arc / entities。2026-06-23 第一篇正確格式的
MOVE-VIX 專題導讀被它自己 curate 的來源文章（mile_671d4c75）判為 narrative-arc dup
而擋下（publisher.py BLOCKED narrative-arc duplicate）。若不豁免，daily routine 產的
digest 會天天被擋。本測試鎖定契約：

- content_type='daily_digest' → 即使與既有文章是 arc-dup 也必須照常發佈。
- 同樣內容但非 daily_digest → 仍被 arc-dup gate 擋下（證明 dup 確實會被偵測）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from volpred.publisher.publisher import Publisher

# 與 seed 高度同主題（MOVE/VIX/FOMC + 共振/相關 = systemic_crowding arc），
# 用來觸發 arc-dup gate。
_SEED_ID = "mile_seeddup1"
_SEED_TITLE = "債市和股市同時在怕，但怕的不是同一件事"
_SEED_DESC = (
    "MOVE 是債市的恐慌指數，VIX 是股市的恐慌指數。兩者 60 日滾動相關係數爬到 0.50，"
    "近 90 日平均 0.60，逼近 2022 升息循環水準，顯示 FOMC 與 CPI 訊息下債市股市同步共振。"
    "但 MOVE/VIX 絕對水位比值 3.99 仍落在歷史 P38，動作同步、水位分歧。"
)
_NEW_TITLE_OVERLAP = "MOVE 與 VIX 的跨資產波動率分裂：債市恐懼 vs 股市平靜"
_NEW_DESC_OVERLAP = (
    "把過去一個月談 MOVE 與 VIX 的研究串起來：FOMC 前後債市選擇權與股市恐慌指數的分裂、"
    "60 日滾動相關 0.50、近 90 日 0.60、比值 3.99 落在 P38，債市股市同步共振但絕對水位分歧。"
)


def _seed_storage(tmp_path: Path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    feed = [
        {
            "id": _SEED_ID,
            "title": _SEED_TITLE,
            "description": _SEED_DESC,
            "status": "published",
            "audience": "general",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "details": {"content_type": "general_article"},
            "tags": ["一般讀者", "MOVE", "VIX"],
        }
    ]
    (reports / "feed.json").write_text(json.dumps(feed, ensure_ascii=False))
    return reports


def _stub_network(monkeypatch) -> None:
    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_notify_article_published", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda *a, **k: None, raising=False)
    import supabase_sync  # noqa: project script on path
    monkeypatch.setattr(supabase_sync, "sync_article", lambda *a, **k: True, raising=False)


def _feed_ids(reports: Path) -> list[str]:
    return [a.get("id") for a in json.loads((reports / "feed.json").read_text())]


def test_non_digest_arc_dup_is_blocked(tmp_path: Path, monkeypatch) -> None:
    """Sanity: 同主題的非 digest 文章會被 arc-dup gate 擋（證明 dup 確實偵測得到）。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title=_NEW_TITLE_OVERLAP,
        description=_NEW_DESC_OVERLAP,
        phase="test",
        details={"content_type": "general_article"},
        tags=["一般讀者", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 被擋 → 回傳既有 dup 的 id，feed 不新增
    assert ret == _SEED_ID
    assert _feed_ids(reports) == [_SEED_ID]


def test_daily_digest_bypasses_arc_dup(tmp_path: Path, monkeypatch) -> None:
    """契約：daily_digest 即使是 arc-dup 也照常發佈（curation 本就會重疊主題）。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title="每日精選導讀｜" + _NEW_TITLE_OVERLAP,
        description=_NEW_DESC_OVERLAP,
        phase="test",
        details={"content_type": "daily_digest", "digest_articles": [_SEED_ID]},
        tags=["一般讀者", "精選導讀", "daily_digest", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 未被擋 → 回傳新 id（非 seed dup），feed 新增一篇
    assert ret != _SEED_ID
    ids = _feed_ids(reports)
    assert _SEED_ID in ids and ret in ids and len(ids) == 2
