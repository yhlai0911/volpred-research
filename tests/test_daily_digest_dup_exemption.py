"""Dedup policy（2026-06-23 boss directive「沒發文比重複發文嚴重」）+ daily_digest 豁免。

預設從「default block, 逐類豁免」反轉成「default publish, 只 hard-block 真正的
byte-level recycle」。三條契約：

1. 同 experiment_ref + 同 audience + 內文**近乎逐字相同**（K1054 ghost 那種）→ 仍被擋
   （唯一保留的 hard block，擋它零成本）。
2. 同 experiment_ref 但**不同角度/不同寫法**（body_sim < _RECYCLE_SIM）→ 現在照常發佈，
   不再被靜默吞掉（這是 boss directive 的核心）。
3. content_type='daily_digest' → 即使內文與被策展來源近乎相同也照常發佈（curation 本就
   會大量重疊）。

每日精選導讀是 meta-curation，本來就會引用同主題的多篇舊文，必然與被策展文章共享
experiment_refs / 標題主題 / narrative arc / entities。2026-06-23 第一篇正確格式的
MOVE-VIX 專題導讀被它自己 curate 的來源文章（mile_671d4c75）判為 narrative-arc dup
而擋下。narrative-arc / 純標題相似 gate 已降級為 warn-only（見 publisher.py），digest
另有 content_type 豁免做雙重保險。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from volpred.publisher.publisher import Publisher

# Deterministic dup trigger: seed and the new article share experiment_ref
# 'K9999' (+ same general audience).
_SHARED_REF = "K9999"
_SEED_ID = "mile_seeddup1"
_SEED_TITLE = "債市和股市同時在怕，但怕的不是同一件事"
_SEED_DESC = (
    "MOVE 是債市的恐慌指數，VIX 是股市的恐慌指數。兩者 60 日滾動相關係數爬到 0.50，"
    "近 90 日平均 0.60，逼近 2022 升息循環水準，顯示 FOMC 與 CPI 訊息下債市股市同步共振。"
    "但 MOVE/VIX 絕對水位比值 3.99 仍落在歷史 P38，動作同步、水位分歧。"
)

# (A) TRUE RECYCLE: byte-for-byte body, title only slightly reworded (the K1054
# ghost pattern). body_sim ≈ 0.95 ≥ _RECYCLE_SIM → must be blocked.
_RECYCLE_TITLE = "債市和股市同時在怕，但怕的不是同一件事（更新版）"
_RECYCLE_DESC = _SEED_DESC

# (B) SAME-K DIFFERENT ANGLE: shares the topic + experiment_ref but is a
# genuinely different writeup. body_sim ≈ 0.19 < _RECYCLE_SIM → must publish
# (boss directive: a missed publish is worse than a duplicate).
_DIFF_TITLE = "MOVE 與 VIX 的跨資產波動率分裂：債市恐懼 vs 股市平靜"
_DIFF_DESC = (
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
            "content": _SEED_DESC,
            "status": "published",
            "audience": "general",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "details": {"content_type": "general_article", "experiment_refs": [_SHARED_REF]},
            "tags": ["一般讀者", "MOVE", "VIX"],
        }
    ]
    (reports / "feed.json").write_text(json.dumps(feed, ensure_ascii=False))
    return reports


def _stub_network(monkeypatch, tmp_path: Path) -> None:
    """Hermetic isolation: make it IMPOSSIBLE for this test to touch production.

    2026-06-23 incident: a prior version only stubbed Publisher methods and a
    single supabase_sync reference, AND left SUPABASE_URL/KEY in the env. When
    the `import supabase_sync` stub failed (wrong module path), publish_milestone
    synced the test's MOVE-VIX digest fixture to PRODUCTION Supabase — two stub
    daily_digest rows leaked live and had to be retracted. Defense-in-depth now:
    clear creds, blank REMOTE_URL, stub every sync/notify/verify path, and stub
    sync_article + _post on BOTH module names.
    """
    for var in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_notify_article_published", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda *a, **k: None, raising=False)

    try:
        from volpred.publisher import live_verify  # type: ignore
        for fn, ret in (("verify_article_live", True), ("stamp_verified", None), ("emit_verify_alert", None)):
            monkeypatch.setattr(live_verify, fn, (lambda *a, **k: ret), raising=False)
    except Exception:
        pass

    import importlib
    for mod_name in ("supabase_sync", "scripts.supabase_sync"):
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        monkeypatch.setattr(mod, "sync_article", lambda *a, **k: True, raising=False)
        monkeypatch.setattr(mod, "_post", lambda *a, **k: False, raising=False)

    # Isolate the topic-cluster cooldown gate to the tmp feed (otherwise it reads
    # the REAL feed.json and may raise topic_cluster_cooldown_blocked first).
    import volpred.topic_clusters as tc
    monkeypatch.setattr(tc, "FEED_PATH", tmp_path / "reports" / "feed.json", raising=False)


def _feed_ids(reports: Path) -> list[str]:
    return [a.get("id") for a in json.loads((reports / "feed.json").read_text())]


def test_non_digest_recycle_is_blocked(tmp_path: Path, monkeypatch) -> None:
    """契約 1：同 ref + 同 audience + 內文近乎逐字相同 → 被擋（K1054 ghost 防線仍在）。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title=_RECYCLE_TITLE,
        description=_RECYCLE_DESC,
        phase="test",
        details={
            "content_type": "general_article",
            "experiment_refs": [_SHARED_REF],
            "cluster_waiver": "test_dup_isolation",
        },
        tags=["一般讀者", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 被擋 → 回傳既有 dup 的 id，feed 不新增
    assert ret == _SEED_ID
    assert _feed_ids(reports) == [_SEED_ID]


def test_same_ref_different_angle_publishes(tmp_path: Path, monkeypatch) -> None:
    """契約 2（boss directive 核心）：同 ref 但不同角度/不同寫法 → 照常發佈，不被靜默吞掉。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title=_DIFF_TITLE,
        description=_DIFF_DESC,
        phase="test",
        details={
            "content_type": "general_article",
            "experiment_refs": [_SHARED_REF],
            "cluster_waiver": "test_dup_isolation",
        },
        tags=["一般讀者", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 未被擋 → 回傳新 id，feed 新增一篇
    assert ret != _SEED_ID
    ids = _feed_ids(reports)
    assert _SEED_ID in ids and ret in ids and len(ids) == 2


def test_daily_digest_bypasses_recycle(tmp_path: Path, monkeypatch) -> None:
    """契約 3：daily_digest 即使內文與來源近乎相同也照常發佈（curation 本就會重疊）。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title="每日精選導讀｜" + _SEED_TITLE,
        description=_RECYCLE_DESC,  # near-identical to seed — would block a non-digest
        phase="test",
        details={"content_type": "daily_digest", "digest_articles": [_SEED_ID], "experiment_refs": [_SHARED_REF]},
        tags=["一般讀者", "精選導讀", "daily_digest", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 未被擋 → 回傳新 id（非 seed dup），feed 新增一篇
    assert ret != _SEED_ID
    ids = _feed_ids(reports)
    assert _SEED_ID in ids and ret in ids and len(ids) == 2
