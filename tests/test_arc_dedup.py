"""Tests for narrative-arc duplicate detection (2026-06-10 K1449/K1091 incident).

Regression contract: every case below reproduces a real shipped duplicate (or a
real non-duplicate that must NOT be blocked). If any of these fail, the arc gate
has regressed to the title-similarity blind spot.
"""

from datetime import datetime, timedelta, timezone

import pytest

from volpred.publisher.arc_dedup import (
    classify_conclusion,
    extract_entities,
    find_arc_duplicates,
)


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# --- The actual K1091 article (2026-05-16) that K1449 duplicated -------------
K1091_ARTICLE = {
    "id": "mile_232ce5d4",
    "title": "為什麼同樣是『商品 ETF』，銅銀就是吃不到 VIX 紅利？—— 給散戶與資產配置者的一張資產相容性地圖",
    "description": (
        "拿 VIX（S&P 500 的恐慌指數）去推全球股票 ETF（VGK 歐股、EWJ 日股）的波動率是有效的；"
        "拿同一個 VIX 去推沒有自己 IV 指數的商品 ETF（CPER 銅、SLV 銀），幾乎沒用，跟一般 GARCH 模型沒差別。"
    ),
    "status": "published",
    "published_at": _ts(days_ago=25),
}

# --- The K1449 piece that slipped through every gate on 2026-06-10 -----------
K1449_TITLE = "銅博士的波動率版本：13 年數據說了什麼"
K1449_CONTENT = (
    "銅的波動程度，能不能預測股市未來的波動程度？這個分析追蹤 CPER 和 SPY 的 21 日實現波動率。"
    "相關係數 0.057，接近於零。加入 VIX 後，銅波動的增量資訊幾乎歸零。"
)


class TestEntityExtraction:
    def test_copper_from_chinese_and_ticker(self):
        ents = extract_entities("銅博士的波動率版本 CPER vs SPY")
        assert "COPPER" in ents
        assert "US_EQUITY" in ents

    def test_ticker_word_boundary(self):
        # 'tip' must not match inside other words
        assert "TIPS" not in extract_entities("multiple tips for traders")
        assert "TIPS" in extract_entities("TIP 抗通膨債 ETF")

    def test_no_entities_returns_empty(self):
        assert extract_entities("一篇關於方法論的文章") == set()


class TestConclusionClassification:
    def test_null_class(self):
        assert classify_conclusion("增量資訊幾乎歸零，接近於零") == "null_no_info"
        assert classify_conclusion("吃不到 VIX 紅利，幾乎沒用") == "null_no_info"

    def test_descriptive_fallback(self):
        assert classify_conclusion("本文介紹三種模型的建構方式") == "descriptive"


class TestArcDuplicates:
    def test_k1449_vs_k1091_regression(self):
        """The 2026-06-10 incident: ~0 title overlap, different K refs,
        same story (copper × VIX/equity-vol → no info). MUST be caught."""
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [K1091_ARTICLE])
        assert dups, "K1449 arc-duplicate of K1091 was not detected — incident regression"
        assert dups[0]["id"] == "mile_232ce5d4"
        assert "COPPER" in dups[0]["shared_entities"]

    def test_direction_agnostic(self):
        """A→B null vs B→A null is the same arc to the reader."""
        reversed_article = {
            "id": "mile_x",
            "title": "VIX 推不動銅價波動",
            "description": "VIX 對 CPER 波動率幾乎沒有預測力，無增量資訊。",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [reversed_article])
        assert dups and dups[0]["id"] == "mile_x"

    def test_core_only_overlap_not_blocked(self):
        """Two articles that only share SPY/VIX (ubiquitous) are NOT dups."""
        other = {
            "id": "mile_y",
            "title": "黃金波動率在升息循環的表現",
            "description": "GLD 與 SPY 的波動率比較，黃金避險效果不成立。",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        new_title = "日圓避險屬性檢驗"
        new_content = "FXY 與 SPY 波動率，risk-off 時日圓避險不成立，無增量資訊。"
        dups = find_arc_duplicates(new_title, new_content, [other])
        assert dups == []  # share only US_EQUITY (core) — different assets

    def test_different_conclusion_class_not_blocked(self):
        """Same assets but opposite conclusion = genuinely new finding, allow."""
        positive_copper = {
            "id": "mile_z",
            "title": "銅波動的領先訊號",
            "description": "CPER 波動率顯著領先 SPY，預測力顯著，通過檢定。",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [positive_copper])
        assert dups == []

    def test_old_article_outside_window(self):
        old = dict(K1091_ARTICLE, published_at=_ts(days_ago=120))
        assert find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [old], days=90) == []

    def test_unpublished_ignored(self):
        unpub = dict(K1091_ARTICLE, status="unpublished")
        assert find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [unpub]) == []


class TestPublisherGateWiring:
    def test_publish_milestone_blocks_arc_dup(self, tmp_path, monkeypatch):
        """End-to-end: publish_milestone must refuse the K1449 article when the
        K1091 article is in the feed."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=K1449_TITLE,
            description=K1449_CONTENT,
            phase="Phase_X",
            status="draft",
            audit_strict=False,
        )
        # Blocked → returns the existing dup id, and no new article in feed
        assert returned == "mile_232ce5d4"
        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert len(feed) == 1

    def test_dup_waiver_overrides(self, tmp_path):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=K1449_TITLE,
            description=K1449_CONTENT,
            phase="Phase_X",
            status="draft",
            details={"dup_waiver": "deliberate follow-up with new angle"},
            audit_strict=False,
        )
        assert returned != "mile_232ce5d4"
