"""Tests for narrative-arc duplicate detection (2026-06-10 K1449/K1091 incident).

Regression contract: every case below reproduces a real shipped duplicate (or a
real non-duplicate that must NOT be blocked). If any of these fail, the arc gate
has regressed to the title-similarity blind spot.
"""

from datetime import datetime, timedelta, timezone

import pytest

from volpred.publisher.arc_dedup import (
    arc_signature,
    classify_conclusion,
    classify_mechanisms,
    classify_time_horizon,
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


class TestArcAxes:
    def test_mechanism_and_horizon_signature(self):
        sig = arc_signature(
            "K1499 BDC private-credit shadow stress multi-horizon lead-lag",
            "BIZD NAV-discount proxy tests HYG forward RV across horizons t+1..t+21.",
        )
        assert "private_credit_stress" in sig["mechanisms"]
        assert sig["time_horizon"] == "multi_horizon"
        assert classify_time_horizon("盤中 5-min intraday event window") == "intraday"
        assert classify_time_horizon("完整重跑要多等好幾個小時") == "unspecified"
        assert classify_mechanisms("GJR-GARCH forecast model QLIKE") == {"model_forecast"}

    def test_retail_interaction_path_not_coherence_decay(self):
        """A generic 'interaction' token in an artifact path must not turn a
        retail-flow article into the theme-coherence mechanism."""
        sig = arc_signature(
            "散戶越熱，0050 明天就越震？數字給的答案很保守",
            (
                "0050 散戶 proxy、融資融券活動、近期下跌，樣本外測試自 2022 起。"
                "script: experiments/k1530_tw_retail_interaction_rv/"
                "k1530_tw_retail_interaction_rv.py"
            ),
        )
        assert "retail_flow" in sig["mechanisms"]
        assert "coherence_decay" not in sig["mechanisms"]
        assert sig["time_horizon"] == "daily"

    def test_hln_correction_factor_not_factor_causality(self):
        """The word 'factor' in an HLN correction formula is not a factor model."""
        sig = arc_signature(
            "K1416 HLN small-sample correction for TW0050-N225",
            (
                "The HLN correction factor = sqrt((n-1)/n). "
                "TW0050-N225 cross-market copula result is stable across five OOS starts."
            ),
        )
        assert "factor_causality" not in sig["mechanisms"]
        assert "cross_asset_spillover" in sig["mechanisms"]

    def test_same_asset_different_mechanism_not_blocked(self):
        """Same entity+conclusion can be publishable when the mechanism differs."""
        existing = {
            "id": "mile_copper_model",
            "title": "銅與 VIX 的 GARCH 預測模型沒用",
            "description": "CPER、VIX、SPY 的 GARCH forecast model QLIKE 無增量資訊。",
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        title = "銅礦罷工跳空事件研究：VIX 也吃不到"
        content = "CPER 和 VIX 的 event study / event window 顯示 jump clustering 不顯著，無增量資訊。"
        dups = find_arc_duplicates(title, content, [existing])
        assert dups == []

    def test_same_asset_different_horizon_not_blocked(self):
        existing = {
            "id": "mile_copper_intraday",
            "title": "銅與 VIX 的日內 GARCH 預測沒用",
            "description": "CPER、VIX、SPY 的 intraday 5-min GARCH forecast model 無增量資訊。",
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        title = "銅與 VIX 的下月 GARCH 預測也不成立"
        content = "CPER、VIX、SPY 的 monthly GARCH forecast model 對 next-month volatility 無增量資訊。"
        dups = find_arc_duplicates(title, content, [existing])
        assert dups == []


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

    def test_broad_survey_does_not_absorb_narrow_study(self):
        """2026-06-17 incident: a single cross-asset survey article
        (mile_bf13d810 '14 個跨市場資產的 GJR-GARCH persistence ~0.98') was
        absorbing every subsequent single-asset NULL study as an arc-dup,
        because the survey extracts 8+ distinctive entities (BITCOIN, GOLD,
        OIL, COPPER, US_EQUITY, US_SMALLCAP, HIGH_YIELD, LONG_BOND, MOMENTUM,
        ...) and any narrow study sharing 1-2 of them was blocked. Refill
        pool drained to zero. Fix: when one side is broad (>=6 distinctive
        entities) and the other is narrow (<=2), require >=3 distinctive
        overlap entities, not 1. Different research grains."""
        broad_survey = {
            "id": "mile_bf13d810",
            "title": "14 個跨市場資產的波動率慣性幾乎一樣高：GJR-GARCH persistence 均值 0.9802",
            "description": (
                "GJR-GARCH persistence 均值 0.9802，跨 14 個資產差異很小。"
                "BITCOIN、GOLD、OIL、COPPER、SILVER、LONG_BOND、HIGH_YIELD、"
                "US_SMALLCAP、CARBON、URANIUM、JPY、EUR、TLT、HYG。"
                "無增量資訊，預測力歸零。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        narrow_title = "比特幣波動率對加密期權微結構的反應"
        narrow_content = (
            "BTC realized vol 與 perpetual funding rate，週期效應接近於零，"
            "增量資訊幾乎沒有。"
        )
        dups = find_arc_duplicates(narrow_title, narrow_content, [broad_survey])
        assert dups == [], (
            "broad cross-asset survey should NOT absorb narrow single-asset "
            "study as arc-dup — different research grains"
        )

    def test_two_narrow_same_asset_still_blocked(self):
        """Regression guard: the broad-vs-narrow rule must NOT loosen the
        original copper×VIX case. Both K1449 and K1091 are narrow → still dup."""
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [K1091_ARTICLE])
        assert dups, "narrow vs narrow same-arc must still trigger"

    def test_core_plus_single_broad_market_entity_not_enough(self):
        """2026-06-17 refill dry regression: K1341 Russell/S&P reconstitution
        extracted {US_EQUITY, US_SMALLCAP} and was blocked by generic
        US_SMALLCAP/NASDAQ NULL articles. A core entity plus one broad-market
        distinctive entity is not a narrative arc unless the VIX mechanism or
        exact same narrow entity set is shared."""
        generic_smallcap = {
            "id": "mile_generic_smallcap",
            "title": "把 SPY 波動拆成平常和跳一下，IWM 版本也沒有改善",
            "description": "SPY、IWM 和 QQQ 的波動分解結果不顯著，預測力歸零。",
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        title = "K1341 NULL/REVERSED: Russell/S&P reconstitution day intraday dislocate then mean-revert hypothesis NOT supported"
        content = "Russell and S&P index reconstitution day effect at daily ETF frequency. IWM versus SPY event window is not significant."
        assert "INDEX_RECONSTITUTION" in extract_entities(title + "\n" + content)
        dups = find_arc_duplicates(title, content, [generic_smallcap])
        assert dups == [], "core US_EQUITY + one US_SMALLCAP overlap should not block K1341"

    def test_two_broad_surveys_still_blocked(self):
        """Two broad cross-asset NULL surveys ARE the same arc. Not loosened."""
        broad_a = {
            "id": "mile_aa",
            "title": "14 個跨市場資產 GJR persistence",
            "description": (
                "BITCOIN、GOLD、OIL、COPPER、SILVER、LONG_BOND、HIGH_YIELD、"
                "US_SMALLCAP、CARBON、URANIUM、JPY、EUR persistence 均值 0.98。無增量資訊。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        broad_b_title = "12 個跨市場資產的 EGARCH 持續性"
        broad_b_content = (
            "BITCOIN、GOLD、OIL、COPPER、SILVER、LONG_BOND、HIGH_YIELD、"
            "US_SMALLCAP、CARBON、URANIUM、JPY、EUR EGARCH 持續性 0.97 接近於零差異。無增量資訊。"
        )
        dups = find_arc_duplicates(broad_b_title, broad_b_content, [broad_a])
        assert dups, "two broad surveys on same conclusion class should still be dup"


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

    def test_publish_milestone_persists_arc_signature(self, tmp_path):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title="K999 BDC tax friction multi-horizon RV test",
            description=(
                "BDC private credit tax friction tests HYG forward RV across "
                "horizons t+1..t+21. Result is mixed."
            ),
            phase="Phase_X",
            tags=["K999"],
            audience="research",
            status="draft",
            audit_strict=False,
        )

        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert feed[0]["id"] == returned
        sig = feed[0]["details"]["arc_signature"]
        assert sig["schema_version"] == "arc_dedup_v2"
        assert "private_credit_stress" in sig["mechanisms"]
        assert sig["time_horizon"] == "multi_horizon"


class TestK1054GhostRecycle:
    """2026-06-19 incident: mile_bb520db8 (06-19) byte-for-byte re-published
    mile_c481c8cf (06-07). Both K1054, both classified 'descriptive' (their
    model-robustness conclusion wording isn't in _CONCLUSION_KEYWORDS), titles
    only slightly reworded. THREE gates missed it:
      (1) arc_dedup returned [] for any 'descriptive' article (SpaceX false-pos fix);
      (2) no same-experiment_refs gate independent of arc class;
      (3) title-sim near-dup gate fell below threshold on the reworded title.
    """

    # The 06-07 original (retitled/unpublished now, reconstructed here as published).
    C481_ARTICLE = {
        "id": "mile_c481c8cf",
        "status": "published",
        "published_at": _ts(days_ago=12),
        "title": "同一個模型，換一把尺子量還是贏，這才叫真的贏",
        "content": (
            "波動率模型比較：把 realized-vol proxy 換一把尺子重估，SPY 和 VIX 的"
            "模型在 proxy-robust 檢驗下還是贏。短期動能與反轉的關係沒有改變。"
        ),
        "details": {"experiment_refs": ["K1054"]},
        "audience": "general",
    }
    # The 06-19 recycle.
    BB520_TITLE = "波動率模型換一把尺子量還是贏，這才叫真的贏"
    BB520_CONTENT = (
        "波動率模型比較：把 realized-vol proxy 換一把尺子重估，SPY 和 VIX 的"
        "模型在 proxy-robust 檢驗下還是贏。短期動能與反轉的關係沒有改變。"
    )

    def test_descriptive_same_k_recycle_blocked(self):
        """The exact incident: same K, near-identical title, both descriptive."""
        dups = find_arc_duplicates(
            self.BB520_TITLE, self.BB520_CONTENT, [self.C481_ARTICLE],
            days=90, new_refs=["K1054"],
        )
        assert dups, "K1054 ghost recycle not detected — incident regression"
        assert dups[0]["id"] == "mile_c481c8cf"
        assert "K1054" in dups[0]["shared_experiment_refs"]
        assert dups[0]["match_reason"] == "descriptive_strict"

    def test_descriptive_same_k_recycle_blocked_without_explicit_refs(self):
        """Even if the publisher forgot to pass new_refs, the K-id is harvested
        from feed-item details + title. Here the new side has no explicit ref
        and no K-id in its title — it must still block on near-identical title
        + entity overlap (path B)."""
        dups = find_arc_duplicates(
            self.BB520_TITLE, self.BB520_CONTENT, [self.C481_ARTICLE], days=90,
        )
        assert dups, "recycle must block on near-title even without explicit refs"
        assert dups[0]["id"] == "mile_c481c8cf"

    def test_descriptive_same_k_different_angle_allowed(self):
        """Guard against over-blocking: the SAME K but a genuinely different
        descriptive article (different assets AND different title) is allowed.
        This is what distinguishes a recycle from a legitimate companion."""
        existing = dict(
            self.C481_ARTICLE,
            title="銅價這一年到底在反應什麼總經訊號",
            content="銅價 CPER 與全球製造業 PMI 的關係，純敘述性的總經背景說明。",
        )
        new_title = "比特幣這一輪上漲的資金面拆解"
        new_content = "BTC 這一輪上漲，從穩定幣供給與 ETF 淨流入的純敘述觀察。"
        dups = find_arc_duplicates(
            new_title, new_content, [existing], days=90, new_refs=["K1054"],
        )
        assert dups == [], "same K but different assets+title should not block"

    def test_spacex_still_not_blocked_with_refs_threaded(self):
        """Re-assert the SpaceX false-positive stays fixed under the new
        descriptive path (no shared ref, low title overlap, distinct entities)."""
        big_tech_vol = {
            "id": "mile_312204b2",
            "title": "砍人和燒錢同時進行：為什麼大型科技股的波動率是 SPY 的兩倍半",
            "description": (
                "大型科技股這一年一邊裁員一邊燒錢，美股七雄的波動率大約是 SPY 的 2.5 倍。"
                "用美元計價的市值與成交量觀察整體市場。"
            ),
            "details": {},
            "status": "published",
            "published_at": _ts(days_ago=2),
        }
        spacex_title = "人類史上最大 IPO：SpaceX 招股書裡，最該看的不是那兩兆估值"
        spacex_content = (
            "SpaceX 以接近兩兆美元估值在美股掛牌，募資 750 億美元只釋出 4.2% 股權。"
            "Starlink 在賺錢，xAI 在燒錢，馬斯克透過 B 類股掌握投票權。"
        )
        dups = find_arc_duplicates(spacex_title, spacex_content, [big_tech_vol], days=90)
        assert dups == [], "SpaceX must remain unblocked under descriptive-strict path"

    def test_publish_milestone_blocks_same_ref_recycle(self, tmp_path):
        """End-to-end vuln-2 gate: publish_milestone refuses a same-K,
        same-audience republish even when the arc class is descriptive."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([self.C481_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=self.BB520_TITLE,
            description=self.BB520_CONTENT,
            phase="Phase_X",
            status="published",
            audience="general",
            details={"experiment_refs": ["K1054"]},
            audit_strict=False,
        )
        assert returned == "mile_c481c8cf", "same-ref recycle was not blocked"
        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert len(feed) == 1, "blocked publish must not append a new article"

    def test_publish_milestone_allows_different_audience_companion(self, tmp_path):
        """A research companion to an existing general article on the same K is
        a legitimate dual-audience piece, not a recycle. Must be allowed."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([self.C481_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title="K1054 proxy-robustness 模型比較：研究版完整檢定",
            description=(
                "K1054 在 QLIKE、Diebold-Mariano test、Harvey threshold 下的"
                "完整 proxy-robust 檢定報告，t-stat 與 bootstrap p 值齊備。"
            ),
            phase="Phase_X",
            status="draft",
            audience="research",
            details={"experiment_refs": ["K1054"]},
            audit_strict=False,
        )
        assert returned != "mile_c481c8cf", "research companion must not be blocked"


def test_vt_crowding_arc_caught():
    """2026-06-14 regression: VT crowding arc must dedupe across K/audience.

    The production miss was two same-day articles telling the same reader story:
    volatility-targeting/crowded risk-control rules can amplify market stress.
    """
    from volpred.publisher.arc_dedup import find_arc_duplicates, extract_entities, classify_conclusion
    existing = [{
        "id": "mile_1a6d9369", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "當大家都用波動率目標策略，市場會更不安全",
        "content": "波動率目標策略的群聚風險會造成同步賣壓，1000 agents 模擬顯示系統性風險與閃崩機率上升。",
    }]
    new_title = "自動風控變成集體陷阱：波動率目標如何放大市場波動"
    new_content = "投資人都使用波動率目標策略時，群聚與同步賣壓會放大波動，代理人模擬顯示系統性風險增加。"
    assert "VOL_TARGETING" in extract_entities(new_title + "\n" + new_content)
    assert classify_conclusion(new_title + "\n" + new_content) == "systemic_crowding"
    dups = find_arc_duplicates(new_title, new_content, existing, days=3650)
    assert any(d["id"] == "mile_1a6d9369" for d in dups), "VT-crowding arc should be blocked"


def test_vt_different_conclusion_not_blocked():
    """Same VT entity with different conclusion class should not be deduped."""
    from volpred.publisher.arc_dedup import find_arc_duplicates
    existing = [{
        "id": "mile_vtpos", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "波動率目標策略顯著改善跨市場實驗",
        "content": "波動率目標策略降低 MDD 並顯著改善風險調整報酬，結果穩健成立。",
    }]
    dups = find_arc_duplicates(
        "波動率目標策略的群聚風險可能放大系統性風險",
        "波動率目標策略若被太多人採用，群聚與同步賣壓可能造成閃崩。",
        existing, days=3650,
    )
    assert not dups, "different VT conclusion classes should not be deduped"
