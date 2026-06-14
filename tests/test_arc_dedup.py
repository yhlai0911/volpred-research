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

    def test_low_vol_factor_requires_factor_etf_context(self):
        # Generic market-regime wording should not collide with USMV/factor ETF
        # articles in arc dedup.
        assert "LOW_VOL_FACTOR" not in extract_entities("近期低波動環境讓 VIX 降到 14")
        assert "LOW_VOL_FACTOR" in extract_entities("USMV 是低波動 ETF")
        assert "LOW_VOL_FACTOR" in extract_entities("低波動因子和品質因子比較")


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

    def test_descriptive_both_not_blocked(self):
        """2026-06-14 false positive: SpaceX IPO 資本結構文 (mile_6159728d) was
        blocked against big-tech-vol 文 (mile_312204b2) — both unclassifiable
        ('descriptive'), shared only USD + US_EQUITY incidentally. 'descriptive'
        means 'no conclusion arc', so it must NOT count as a matching arc."""
        big_tech_vol = {
            "id": "mile_312204b2",
            "title": "砍人和燒錢同時進行：為什麼大型科技股的波動率是 SPY 的兩倍半",
            "description": (
                "大型科技股這一年一邊裁員一邊燒錢，美股七雄的波動率大約是 SPY 的 2.5 倍。"
                "用美元計價的市值與成交量觀察整體市場。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        spacex_title = "人類史上最大 IPO：SpaceX 招股書裡，最該看的不是那兩兆估值"
        spacex_content = (
            "SpaceX 以接近兩兆美元估值在美股掛牌，募資 750 億美元只釋出 4.2% 股權。"
            "Starlink 在賺錢，xAI 在燒錢，馬斯克透過 B 類股掌握投票權。"
        )
        dups = find_arc_duplicates(spacex_title, spacex_content, [big_tech_vol])
        assert dups == [], "both-descriptive incidental-entity overlap falsely blocked"

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


def test_vt_crowding_arc_caught():
    """2026-06-14 regression: ��������VT crowding ��� ��場���������������� arc ����� K/audience
    ��mile_ec28b1cc K1047 ���������� + mile_1a6d9369 K864 ��究������������������������
    修���� VOL_TARGETING 實�� + systemic_crowding conclusion class ������������"""
    from volpred.publisher.arc_dedup import find_arc_duplicates, extract_entities, classify_conclusion
    existing = [{
        "id": "mile_1a6d9369", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "���������������������場��波�������������������������",
        "content": "波�����������������群���使�����1000 agents 代���人模���顯示��������������系統���風���������崩���大波������風���平������������",
    }]
    new_title = "���������������人����������������������������場����������������"
    new_content = "����������人����������波�����������������������場�����������������������������模�����究顯示群������大波������"
    assert "VOL_TARGETING" in extract_entities(new_title + "\n" + new_content)
    assert classify_conclusion(new_title + "\n" + new_content) == "systemic_crowding"
    dups = find_arc_duplicates(new_title, new_content, existing, days=3650)
    assert any(d["id"] == "mile_1a6d9369" for d in dups), "VT-crowding arc ���被������"


def test_vt_different_conclusion_not_blocked():
    """��誤��������樣 VT 實���������������crowding vs ������������� dedup���"""
    from volpred.publisher.arc_dedup import find_arc_duplicates
    existing = [{
        "id": "mile_vtpos", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "波�����������顯����������������跨�����實���",
        "content": "波���������������������������� MDD�������� DM 檢��顯�����������穩�����������",
    }]
    dups = find_arc_duplicates(
        "波���������������������������群������大系統���風���",
        "波�����������群���使����������������������系統���風���������崩���",
        existing, days=3650,
    )
    assert not dups, "������������ VT ���章�����被誤���"
