"""Tests for narrative-arc duplicate detection (2026-06-10 K1449/K1091 incident).

Regression contract: every case below reproduces a real shipped duplicate (or a
real non-duplicate that must NOT be blocked). If any of these fail, the arc gate
has regressed to the title-similarity blind spot.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
import sys
import types

import pytest

from volpred.publisher.arc_dedup import (
    arc_signature,
    classify_narrative_axis,
    classify_conclusion,
    classify_mechanisms,
    classify_time_horizon,
    extract_entities,
    find_arc_duplicates,
    _same_series_different_episode,
)


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _install_publisher_runtime_stubs(monkeypatch) -> None:
    """Keep publisher integration tests independent of developer-only env."""
    original_exists = Path.exists

    def clean_checkout_exists(path: Path) -> bool:
        if path.name in {".env", ".env.local"}:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", clean_checkout_exists)

    sync_stub = types.ModuleType("supabase_sync")
    sync_stub.sync_article = lambda *_args, **_kwargs: True
    monkeypatch.setitem(sys.modules, "supabase_sync", sync_stub)

    live_stub = types.ModuleType("volpred.publisher.live_verify")
    live_stub.verify_article_live = lambda *_args, **_kwargs: True
    live_stub.stamp_verified = lambda *_args, **_kwargs: None
    live_stub.emit_verify_alert = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "volpred.publisher.live_verify", live_stub)

    email_stub = types.ModuleType("volpred.publisher.email_notifier")

    class _EmailNotifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def notify_article_published(self, *_args, **_kwargs):
            return None

    email_stub.EmailNotifier = _EmailNotifier
    monkeypatch.setitem(
        sys.modules,
        "volpred.publisher.email_notifier",
        email_stub,
    )


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

    def test_narrative_axis_separates_methodology_from_product_myth(self):
        paper_text = (
            "K1417: Stationary Bootstrap 驗證 Paper 三 MDD Retention CI 穩健性。"
            "Paper reviewer H2 不成立，SPY、VIX、TSMOM momentum 的 canonical K1192 "
            "baseline 與 Table 6 provenance 已修正。"
        )
        product_text = (
            "CTA ETF 比 SPY 更耐跌嗎？DBMF、KMLM、CTA 的免費 ETF proxy 顯示 "
            "trend-following crisis alpha 在 stress regime 不穩健。"
        )
        assert classify_narrative_axis(paper_text) == "methodology_robustness"
        assert classify_narrative_axis(product_text) == "product_myth"
        paper_sig = arc_signature("K1417 Paper 三 bootstrap robustness", paper_text)
        product_sig = arc_signature("CTA ETF crisis alpha myth", product_text)
        assert paper_sig["entity_groups"]["paper_methodology"]
        assert paper_sig["entity_groups"]["reader_narrative"] == []
        assert product_sig["entity_groups"]["reader_narrative"]
        assert product_sig["entity_groups"]["paper_methodology"] == []

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

    def test_unparseable_timestamp_warns_and_keeps_candidate(self, caplog):
        bad_ts = dict(K1091_ARTICLE, published_at="not-a-date")

        with caplog.at_level("WARNING"):
            dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [bad_ts], days=90)

        assert dups, "invalid timestamp must keep candidate conservatively"
        assert "arc_dedup keeping item with invalid timestamp" in caplog.text
        assert "mile_232ce5d4" in caplog.text
        assert "not-a-date" in caplog.text

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

    def test_k1547_cta_product_myth_not_blocked_by_k1417_paper_methodology(self):
        """2026-06-24 incident: K1547 CTA crisis-alpha product-myth was rejected
        against K1417 Paper 3 stationary-bootstrap methodology robustness because
        both shared SPY/VIX/momentum/null-ish words. Different narrative_axis
        must prevent that over-match."""
        k1417_article = {
            "id": "mile_2849a7b5",
            "title": (
                "K1417: Stationary Bootstrap 驗證 Paper 三 MDD Retention CI 穩健性 "
                "— H2 不成立，但基線需改用 canonical"
            ),
            "description": (
                "Paper 三 v4 reviewer H2 質疑 K1192 固定 252-day block bootstrap 會切碎 "
                "SPY/VIX/TSMOM drawdown path。K1417 用 stationary bootstrap、MDD retention、"
                "canonical baseline 重算，H2 不成立，provenance caveat 已修正。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=1),
        }
        k1547_title = "CTA ETF 比 SPY 更耐跌嗎？KMLM、DBMF 給的是一半答案"
        k1547_content = (
            "免費 ETF proxy 下 CTA / managed-futures / trend-following 在 lagged VIX stress "
            "regime 沒有 robust crisis alpha。CTA_EW 與 252d momentum timing overlay "
            "相對 SPY 的壓力期 excess return 不顯著，bootstrap CI crosses zero。"
        )
        assert classify_narrative_axis(k1417_article["title"] + "\n" + k1417_article["description"]) == "methodology_robustness"
        assert classify_narrative_axis(k1547_title + "\n" + k1547_content) == "product_myth"
        dups = find_arc_duplicates(k1547_title, k1547_content, [k1417_article])
        assert dups == [], "product-myth article must not be absorbed by paper-methodology robustness"

    def test_same_cta_product_myth_still_blocked(self):
        existing = {
            "id": "mile_cta_old",
            "title": "CTA ETF 的 crisis alpha 沒有想像中穩",
            "description": (
                "DBMF、KMLM、CTA managed-futures ETF proxy 在 VIX stress regime "
                "相對 SPY 不顯著，trend-following momentum timing 沒有穩健改善。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=1),
        }
        new_title = "免費 CTA ETF 真有避險 alpha 嗎？"
        new_content = (
            "DBMF、KMLM、CTA 的 managed-futures ETF proxy 和 252d trend-following "
            "momentum overlay 對 SPY 壓力期 excess return 不顯著，沒有 robust crisis alpha。"
        )
        dups = find_arc_duplicates(new_title, new_content, [existing])
        assert dups and dups[0]["id"] == "mile_cta_old"
        assert dups[0]["narrative_axis"] == "product_myth"

    def test_different_axis_keeps_raw_entity_overlap_five_backstop(self):
        """Task guard: v3 must not become 'different narrative_axis always allow'.
        If two pieces share >=5 raw entities and still match on conclusion,
        mechanism, and horizon, keep the duplicate backstop."""
        existing = {
            "id": "mile_method_broad",
            "title": "K1999 Paper 三 commodity GARCH robustness",
            "description": (
                "Paper 三 robustness check：BTC、GOLD、OIL、COPPER、SILVER、SPY 的 "
                "GARCH forecast model 比較，無增量資訊，bootstrap CI 穩健性驗證。"
            ),
            "status": "published",
            "published_at": _ts(days_ago=1),
        }
        new_title = "CTA ETF 大宗商品籃子真的有 crisis alpha 嗎？"
        new_content = (
            "CTA managed-futures ETF proxy 同時看 BTC、GOLD、OIL、COPPER、SILVER、SPY，"
            "GARCH forecast model 顯示無增量資訊，沒有 robust crisis alpha。"
        )
        assert classify_narrative_axis(existing["title"] + "\n" + existing["description"]) == "methodology_robustness"
        assert classify_narrative_axis(new_title + "\n" + new_content) == "product_myth"
        dups = find_arc_duplicates(new_title, new_content, [existing])
        assert dups and dups[0]["id"] == "mile_method_broad"
        assert len(dups[0]["shared_entities"]) >= 5


class TestPublisherGateWiring:
    def test_event_cross_stage_same_title_publishes_but_same_stage_is_idempotent(
        self, tmp_path, monkeypatch
    ):
        import json as _json
        import sys as _sys
        from pathlib import Path as _Path
        from types import ModuleType as _ModuleType

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        existing = {
            "id": "mile_fomc_preview",
            "title": "事件溫度計｜FOMC 利率決議",
            "content": "決議前情境與市場預期。",
            "status": "published",
            "audience": "event",
            "category": "event_article",
            "published_at": _ts(),
            "event_key": "FOMC_2026_07_29",
            "event_type": "FOMC",
            "event_date": "2026-07-29",
            "event_series_slot": "T-2",
            "details": {
                "content_type": "event_article",
                "event_key": "FOMC_2026_07_29",
                "event_type": "FOMC",
                "event_date": "2026-07-29",
                "event_series_slot": "T-2",
                "experiment_refs": ["K2000"],
            },
        }
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([existing], ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        supabase_sync = _ModuleType("supabase_sync")
        supabase_sync.sync_article = lambda *_a, **_k: True
        monkeypatch.setitem(_sys.modules, "supabase_sync", supabase_sync)
        original_exists = _Path.exists

        def _clean_checkout_exists(path):
            if path.name in {".env", ".env.local"}:
                return False
            return original_exists(path)

        monkeypatch.setattr(_Path, "exists", _clean_checkout_exists)
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        reaction_details = {
            "event_key": "FOMC_2026_07_29",
            "event_type": "FOMC",
            "event_date": "2026-07-29",
            "event_series_slot": "T+0",
            "experiment_refs": ["K2000"],
        }
        reaction_id = pub.publish_milestone(
            title=existing["title"],
            description="決議後官方結果與第一段市場反應。",
            phase="event",
            details=reaction_details,
            category="event_article",
            audience="event",
            status="draft",
            audit_strict=False,
        )
        assert reaction_id != existing["id"]

        retry_id = pub.publish_milestone(
            title="事件溫度計｜FOMC 決議後更新",
            description="同一階段的重試，不應建立第二篇。",
            phase="event",
            details=reaction_details,
            category="event_article",
            audience="event",
            status="draft",
            audit_strict=False,
        )
        assert retry_id == reaction_id
        feed = _json.loads(
            (storage / "reports" / "feed.json").read_text(encoding="utf-8")
        )
        assert len(feed) == 2
        decisions = [
            _json.loads(line)
            for line in (storage / "logs" / "dedup_decisions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        exact_blocks = [
            row
            for row in decisions
            if row.get("action") == "block_event_stage_coverage"
        ]
        assert exact_blocks[-1]["candidate_id"] == "fomc_2026_07_29:T+0"

    def test_atomic_append_serializes_same_event_stage_writers(
        self, tmp_path, monkeypatch
    ):
        import json as _json

        from volpred.publisher.publisher import Publisher

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(
            Publisher, "_mirror_article", lambda self, *_a, **_k: True
        )
        pub = Publisher(storage_dir=str(storage))
        start = Barrier(2)

        def event_item(item_id: str) -> dict:
            identity = {
                "event_key": "FOMC_2026_07_29",
                "event_type": "FOMC",
                "event_date": "2026-07-29",
                "event_series_slot": "T+0",
            }
            return {
                "id": item_id,
                "title": "FOMC 決議後即時反應",
                "description": "官方決議與第一段市場反應。",
                "content": "官方決議與第一段市場反應。",
                "status": "draft",
                "audience": "event",
                "category": "event_article",
                "details": {"content_type": "event_article", **identity},
                **identity,
            }

        def append(item: dict) -> str:
            # Both callers bypass the non-atomic publish_milestone precheck.
            # Only the feed lock + fresh exact-stage read can keep one row.
            start.wait()
            return pub._append_to_feed(item)

        items = [event_item("mile_race_a"), event_item("mile_race_b")]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(append, items))

        feed = _json.loads(
            (storage / "reports" / "feed.json").read_text(encoding="utf-8")
        )
        assert len(feed) == 1
        assert set(results) == {feed[0]["id"]}
        assert feed[0]["event_series_slot"] == "T+0"

    def test_atomic_append_rejects_identityless_event_direct_caller(
        self, tmp_path, monkeypatch
    ):
        import json as _json

        from volpred.publisher.publisher import Publisher

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(
            Publisher, "_mirror_article", lambda self, *_a, **_k: True
        )

        with pytest.raises(
            ValueError, match="event article is missing canonical metadata"
        ):
            Publisher(storage_dir=str(storage))._append_to_feed(
                {
                    "id": "mile_missing_identity",
                    "title": "FOMC event",
                    "content": "Event body.",
                    "audience": "event",
                    "category": "event_article",
                    "status": "draft",
                    "details": {"content_type": "event_article"},
                }
            )

        assert _json.loads(
            (storage / "reports" / "feed.json").read_text(encoding="utf-8")
        ) == []

    def test_publish_milestone_warns_but_publishes_arc_dup(self, tmp_path, monkeypatch):
        """End-to-end: 2026-06-23 (boss「沒發文比重複發文嚴重」) the narrative-arc gate
        is downgraded from HARD BLOCK to warn-only. A different-K, same-arc article
        (K1449 vs K1091) now PUBLISHES, but the decision is logged to
        dedup_decisions.jsonl so the (rare) reader-facing dup is auditable and
        cheaply retractable — the lesser evil vs a silent missed publish."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        _install_publisher_runtime_stubs(monkeypatch)
        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=K1449_TITLE,
            description=K1449_CONTENT,
            phase="Phase_X",
            status="draft",
            audit_strict=False,
        )
        # Warn-only → publishes a NEW article (not the existing dup id)
        assert returned != "mile_232ce5d4"
        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert len(feed) == 2
        # The arc-dup was not silent: a warn_arc_dup record was logged.
        log_path = storage / "logs" / "dedup_decisions.jsonl"
        assert log_path.exists(), "arc-dup warn must be logged (never silent)"
        # Filter to arc_dedup records — the shared log also carries other
        # gates' decisions (e.g. publish_throttle since 2026-06-30), which use a
        # `decision`/`gate` schema rather than `action`.
        actions = [
            rec.get("action")
            for rec in (_json.loads(line) for line in log_path.read_text().splitlines() if line.strip())
            if rec.get("action") is not None
        ]
        assert "warn_arc_dup" in actions

    def test_dup_waiver_overrides(self, tmp_path, monkeypatch):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        _install_publisher_runtime_stubs(monkeypatch)
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
        assert sig["schema_version"] == "arc_dedup_v4"
        assert "narrative_axis" in sig
        assert "entity_groups" in sig
        assert "private_credit_stress" in sig["mechanisms"]
        assert sig["time_horizon"] == "multi_horizon"

    def test_publish_milestone_recomputes_stale_v3_signature(self, tmp_path):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
        from volpred.publisher.publisher import Publisher

        stale = {
            "schema_version": "arc_dedup_v3",
            "entities": [],
            "entity_groups": {"reader_narrative": [], "paper_methodology": []},
            "conclusion_class": "descriptive",
            "narrative_axis": "unspecified",
            "mechanisms": [],
            "time_horizon": "unspecified",
        }
        Publisher(storage_dir=str(storage)).publish_milestone(
            title="USDC 脫鉤時 DeFi 流動性如何傳染",
            description="USDC stablecoin 與 DeFi pool 的流動性傳染。",
            phase="Phase_X",
            audience="research",
            status="draft",
            details={"arc_signature": stale},
            audit_strict=False,
        )

        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        sig = feed[0]["details"]["arc_signature"]
        assert sig["schema_version"] == "arc_dedup_v4"
        assert {"STABLECOIN", "DEFI"} <= set(sig["entities"])

    def test_publish_milestone_signature_uses_final_tags_surface(self, tmp_path):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text("[]", encoding="utf-8")
        from volpred.publisher.publisher import Publisher

        Publisher(storage_dir=str(storage)).publish_milestone(
            title="流動性觀察",
            description="市場結構追蹤。",
            phase="Phase_X",
            audience="research",
            status="draft",
            tags=["USDC", "DeFi"],
            audit_strict=False,
        )

        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        sig = feed[0]["details"]["arc_signature"]
        assert sig["schema_version"] == "arc_dedup_v4"
        assert {"STABLECOIN", "DEFI"} <= set(sig["entities"])


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

    def test_publish_milestone_warns_same_ref_recycle(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Heuristic same-K similarity is auditable but cannot own a lock."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([self.C481_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher
        from volpred.publisher import publisher as publisher_module

        pub = Publisher(storage_dir=str(storage))
        monkeypatch.setattr(
            Publisher,
            "_sync_to_remote",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            Publisher,
            "_notify_article_published",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            publisher_module,
            "_semantic_dup_warn",
            lambda *_args, **_kwargs: None,
        )
        sync_stub = types.ModuleType("supabase_sync")
        sync_stub.sync_article = lambda *_args, **_kwargs: True
        monkeypatch.setitem(sys.modules, "supabase_sync", sync_stub)
        returned = pub.publish_milestone(
            title=self.BB520_TITLE,
            description=self.BB520_CONTENT,
            phase="Phase_X",
            status="published",
            audience="general",
            details={"experiment_refs": ["K1054"]},
            audit_strict=False,
        )
        assert returned != "mile_c481c8cf"
        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert len(feed) == 2
        decisions = [
            _json.loads(line)
            for line in (
                storage / "logs" / "dedup_decisions.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        assert any(
            row.get("action") == "warn_same_ref_similarity"
            and row.get("matched_id") == "mile_c481c8cf"
            for row in decisions
        )

    def test_publish_milestone_allows_different_audience_companion(
        self,
        tmp_path,
        monkeypatch,
    ):
        """A research companion to an existing general article on the same K is
        a legitimate dual-audience piece, not a recycle. Must be allowed."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([self.C481_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        _install_publisher_runtime_stubs(monkeypatch)
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

    def test_append_choke_blocks_near_identical_same_ref(self):
        """Unit: the append choke (_find_same_ref_feed_duplicate) still blocks a
        TRUE byte-level recycle — same experiment_ref + same audience + a
        near-identical BODY (the K1054 ghost pattern, body_sim ≈ 1.0)."""
        from volpred.publisher.publisher import _find_same_ref_feed_duplicate

        existing = dict(self.C481_ARTICLE, audience="research")
        recycle = {
            "title": self.BB520_TITLE,
            "content": self.BB520_CONTENT,  # byte-identical to C481 content
            "audience": "research",
            "details": {"experiment_refs": ["K1054"]},
        }
        dup = _find_same_ref_feed_duplicate([existing], recycle)
        assert dup is not None and dup["id"] == "mile_c481c8cf"

    def test_append_choke_allows_legacy_different_body_same_ref(
        self, tmp_path, monkeypatch
    ):
        """2026-06-23 (boss「沒發文比重複發文嚴重」): a same-K legacy publish whose
        BODY is genuinely different (the templated publish_experiment render vs the
        stored prose) is a companion piece, not a recycle, and now PUBLISHES. Only
        a near-identical body recycle is blocked (see the unit test above)."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        existing = dict(self.C481_ARTICLE, audience="research")
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([existing], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        _install_publisher_runtime_stubs(monkeypatch)
        monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None)
        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_experiment(
            "K1054",
            title="K1054 proxy robustness recycle",
            summary="Same K1054 model robustness result through the legacy path.",
            metrics={},
        )

        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert returned != "mile_c481c8cf"
        assert len(feed) == 2, "different-body same-K legacy publish should append"


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


def test_vol_target_noun_not_vol_targeting_strategy():
    """2026-07-01 (K1590): the noun phrase 'vol target' (a target variable for
    vol research) must NOT extract VOL_TARGETING, but the strategy gerund must.
    """
    assert "VOL_TARGETING" not in extract_entities(
        "MNA is a usable portfolio-level vol target for volatility research."
    )
    assert "VOL_TARGETING" not in extract_entities(
        "We treat MNA realized vol as the target; a portfolio-level volatility target."
    )
    assert "VOL_TARGETING" in extract_entities("A vol targeting strategy scaling to a vol budget.")
    assert "VOL_TARGETING" in extract_entities("volatility-targeting overlay on the portfolio")
    # Chinese strategy detection unchanged.
    assert "VOL_TARGETING" in extract_entities("波動率目標策略的槓桿調整")


def test_merger_arb_entity_extracted():
    """2026-07-01 (K1590): merger arbitrage is a distinctive registered entity."""
    assert "MERGER_ARB" in extract_entities("IQ Merger Arbitrage ETF (MNA) deal-spread vol")
    assert "MERGER_ARB" in extract_entities("併購套利的價差波動率診斷")
    assert "MERGER_ARB" in extract_entities("risk arbitrage deal-break probability")
    # Word boundary: 'mna' must not fire inside unrelated words.
    assert "MERGER_ARB" not in extract_entities("Kilimanjaro amnale spelled oddly")


def test_k1590_merger_arb_not_blocked_by_vt_event_study():
    """2026-07-01 regression: K1590 merger-arb diagnostic was falsely arc-blocked
    against unrelated 台股 VT event-study descriptive articles. Root cause: the
    diagnostic's only extracted entities were comparison proxies (SPY/HYG/IWM/VIX)
    plus a spurious VOL_TARGETING from the phrase 'portfolio-level vol target';
    both sides shared the generic event_study mechanism → descriptive_strict block.
    After registering MERGER_ARB and tightening the vol-target noun, the shared
    entities collapse to core VIX only → no significant overlap → not blocked.
    """
    existing = [
        {
            "id": "mile_c11a2ced", "status": "published",
            "published_at": "2026-06-20T04:00:00+00:00",
            "title": "把兩個工具換著用，反而更差？台股波動率策略的一場假設破功",
            "content": (
                "台股波動率目標策略在事件窗的公告後表現，與 VIX 訊號的搭配一場假設破功。"
            ),
        },
        {
            # Broad-market-proxy false positive: shares only US_EQUITY+US_SMALLCAP+VIX
            # (all core/broad proxies) with the merger-arb diagnostic.
            "id": "mile_4901f7bc", "status": "published",
            "published_at": "2026-06-25T04:00:00+00:00",
            "title": "AI 一季燒五百億，該擔心嗎？別看 VIX，看波動率市場真正在怕的三件事",
            "content": (
                "SPY 與 IWM 的隱含波動率結構在公告後的事件窗透露，VIX 沒說出來的三件事。"
            ),
        },
    ]
    k1590_title = "併購套利的價差波動率：MNA 能不能當波動率研究的目標"
    k1590_content = (
        "IQ Merger Arbitrage ETF (MNA) 是併購套利的 portfolio-level 代理。"
        "we test whether MNA is a usable portfolio-level vol target versus SPY / IWM / HYG "
        "and VIX proxies. post-announcement deal-spread widens with deal-break risk. "
        "N=1629 交易日 2020-2026。"
    )
    ents = extract_entities(k1590_title + "\n" + k1590_content)
    assert "MERGER_ARB" in ents
    assert "VOL_TARGETING" not in ents, "the 'vol target' noun must not extract the strategy"
    dups = find_arc_duplicates(k1590_title, k1590_content, existing, days=3650)
    assert not dups, "merger-arb deal-spread arc must not be blocked by a 台股 VT event-study piece"


def test_legacy_none_arc_signature_title_entity_fuzzy_blocks_nfp_reaction():
    """2026-07-03 NFP stale-duplicate incident: a legacy article with
    details.arc_signature=None and only title-level metadata must still be
    visible to check_arc_dedup's title/entity fallback.
    """
    existing = {
        "id": "mile_legacy_nfp",
        "status": "published",
        "published_at": "2026-07-01T17:24:08+00:00",
        "title": "6 月非農爆冷 5.7 萬，SPY 卻只動 0.13%：讓市場抖動的從來不是「就業數字」本身",
        "details": {"arc_signature": None},
    }
    new_title = "非農正式公布後，SPY 為什麼沒有抖？"
    new_content = (
        "NFP 2026-07-03 T+0 反應文：新增就業爆冷，但 SPY 波動不顯著，"
        "VIX 體制才是主因。k528 事件研究顯示 NFP 無增量資訊。"
    )

    dups = find_arc_duplicates(new_title, new_content, [existing], days=90)

    assert dups, "legacy arc_signature=None NFP coverage must not be invisible"
    assert dups[0]["id"] == "mile_legacy_nfp"
    assert dups[0]["match_reason"] == "legacy_title_entity_fuzzy"
    assert "US_EQUITY" in dups[0]["shared_entities"]
    assert dups[0]["shared_legacy_event_topics"] == ["NFP"]


def test_legacy_none_arc_signature_fuzzy_does_not_block_core_market_only():
    """The legacy fallback must require a specific event/topic entity, not only
    ubiquitous SPY/VIX-style market overlap.
    """
    existing = {
        "id": "mile_legacy_spy",
        "status": "published",
        "published_at": "2026-07-01T17:24:08+00:00",
        "title": "SPY 只動 0.13%，市場沒有抖",
        "details": {"arc_signature": None},
    }
    new_title = "非農正式公布後，SPY 為什麼沒有抖？"
    new_content = "NFP 公布後 SPY 波動不顯著，VIX 體制才是主因，無增量資訊。"

    dups = find_arc_duplicates(new_title, new_content, [existing], days=90)

    assert dups == []


# --- audience scoping (2026-07-11 release-pool freeze, 2nd occurrence) --------
# Publishing a research write-up and a general-reader write-up of the same K is
# the product design (74 K-ids carry both audiences live). Judging the general
# twin against its research sibling is a false positive — and a PERMANENT one,
# since the sibling stays published forever. That mis-scoping froze the release
# pool for 30+ consecutive fires and skipped general candidates at task refill.

_TWIN_TITLE = "K1574 避險比例再檢驗"
_TWIN_BODY = (
    "gld slv copper wti fxy ung 的 hedge ratio 與 asset allocation 檢驗。"
    "結果顯著改善且通過檢定。"
)


def _factor_etf_twin(audience: str | None) -> dict:
    item = {
        "id": f"mile_prior_{audience or 'untagged'}",
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "title": "避險比例再檢驗",
        "content": (
            "gld slv copper wti fxy ung 的 hedge ratio 與 asset allocation 檢驗。"
            "結果顯著改善且通過檢定。"
        ),
        "details": {"experiment_refs": ["K1574"]},
    }
    if audience is not None:
        item["audience"] = audience
    return item


def test_general_twin_not_blocked_by_research_sibling_of_same_k():
    dups = find_arc_duplicates(
        _TWIN_TITLE, _TWIN_BODY, [_factor_etf_twin("research")], days=90,
        new_refs=["K1574"], audience="general",
    )
    assert dups == []


def test_general_twin_still_blocked_by_general_sibling_of_same_k():
    dups = find_arc_duplicates(
        _TWIN_TITLE, _TWIN_BODY, [_factor_etf_twin("general")], days=90,
        new_refs=["K1574"], audience="general",
    )
    assert dups, "same-audience rehash must still block — that is the anti-rehash gate"


def test_untagged_legacy_article_stays_in_corpus():
    """'Unknown audience' is not evidence of a DIFFERENT audience. 75 published
    articles carry audience=null; dropping them from the corpus would quietly
    weaken the gate."""
    dups = find_arc_duplicates(
        _TWIN_TITLE, _TWIN_BODY, [_factor_etf_twin(None)], days=90,
        new_refs=["K1574"], audience="general",
    )
    assert dups, "untagged legacy articles must still be deduped against"


def test_audience_omitted_keeps_cross_audience_behaviour():
    """Callers that genuinely span audiences (the publish-time warn) pass no
    audience and must keep seeing the old, wider corpus."""
    dups = find_arc_duplicates(
        _TWIN_TITLE, _TWIN_BODY, [_factor_etf_twin("research")], days=90,
        new_refs=["K1574"],
    )
    assert dups, "audience=None must not silently narrow the corpus"


# --- Registered-series episode exemption (boss Telegram msg 662, 2026-07-13) ---
# A multi-part series published inside one week is by design a sequence of
# chapters over one entity family with one conclusion family — the exact shape
# the arc gate is built to catch. Blocking a series is a false positive.

def _series_episode(title: str, published_at: str = "2026-07-13T02:00:00+00:00") -> dict:
    return {
        "id": "mile_series_" + str(abs(hash(title)) % 10**6),
        "title": title,
        "summary": "台灣無人機供應鏈與大盤的報酬與波動比較，無人機題材沒有帶來超額報酬。",
        "published_at": published_at,
        "status": "published",
        "audience": "general",
    }


def test_same_series_different_episode_not_blocked():
    existing = [
        _series_episode("🛩️ 無人載具｜EP1：上游 87% 的營收集中在三家晶片廠"),
        _series_episode("🛩️ 無人載具｜EP2：八家都能碰到機體、電池或馬達，零家拆出無人機營收"),
    ]
    dups = find_arc_duplicates(
        "🛩️ 無人載具｜EP5：下游整機廠訂單能見度只有兩家撐得住",
        "台灣無人機下游整機廠的訂單與量產進度，與大盤比較報酬與波動。",
        existing, days=14,
    )
    assert not dups, "registered-series episodes must not dedup against each other"


def test_same_series_same_episode_still_blocked():
    """The exemption is per-episode, not a blanket hole: republishing the same
    episode (near-identical title) must still be caught."""
    title = "🛩️ 無人載具｜EP2：八家都能碰到機體、電池或馬達，零家拆出無人機營收"
    existing = [_series_episode(title)]
    assert _same_series_different_episode(title, title, set()) is False


def test_series_exemption_off_when_experiment_refs_shared():
    a = "🧪 迷思實驗室｜VIX 破 30 抄底，勝率其實沒比較高"
    b = "🧪 迷思實驗室｜恐慌指數衝高就進場？十年資料說不行"
    assert _same_series_different_episode(a, b, set()) is True
    assert _same_series_different_episode(a, b, {"K1633"}) is False


# --- 2026-07-16 trending refill: the mega-cap AI-capex vocabulary hole -------
# Three P1 trending topics shipped in one fire, all three narrative-arc repeats
# of live general articles inside 30 days. Root cause (measured, not inferred):
# `_ENTITY_SURFACE` carried NO mega-cap / AI-capex surface at all, so the
# entity-anchored gate could not see the cluster. 「科技巨頭AI變現期延遲？」
# extracted entities=[] -> the matcher declined to look; 「雲端四巨頭年燒六千億」
# extracted only [USD] from 「六千億美元」 -- an anchor on the CURRENCY, which
# dragged in unrelated dollar articles while the real story stayed invisible.
#
# Same shape as VOL_TARGETING (2026-06-14) and MERGER_ARB (2026-07-01), and the
# third strike of the AI-capex family specifically (07-13, 07-14, 07-16).
# `theme_saturation` was the 2026-07-14 answer and it scored these 2/3/4 against
# a threshold of 5 -- a counter cannot substitute for missing vocabulary.

AI_CAPEX_TOPIC_TITLE = "科技巨頭AI變現期延遲？期權市場定價的雙向尾部風險"
AI_CAPEX_TOPIC_TEXT = (
    "針對微軟與 Google 等巨頭的 AI 研發回報率進行評估，結合 CapEx 與營收增速。"
    "可量化：IV skew 與科技股遠期波動率之期限結構，評估市場對 AI 泡沫破裂或加速爆發的溢價定價。"
)

CLOUD_CAPEX_TOPIC_TITLE = "雲端四巨頭年燒六千億，AI波動率偏斜如何避險？"
CLOUD_CAPEX_TOPIC_TEXT = (
    "從四大科技巨頭2026年資本支出飆升至6000億美元切入，分析市場對ROI疑慮引發的科技股波動率偏斜。"
    "可量化分析：科技股隱含波動率Skew與CapEx支出指引修正的相關性。"
)

# The two live general articles these repeated (abridged real feed text).
MILE_F5F4CB43 = {
    "id": "mile_f5f4cb43",
    "title": "科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點",
    "description": (
        "四家公司累計砸進超過 4500 億美元的 AI 資本支出。Microsoft FY2025 的 CapEx 是 646 億美元，"
        "成長 45%，同期營收增速約 15%。Meta 的變現缺口高達近 65 個百分點。"
        "選擇權市場的隱含波動率期限結構怎麼定價這個落差。"
    ),
    "status": "published",
    "audience": "general",
    "published_at": _ts(days_ago=17),
}

MILE_0FA841ED = {
    "id": "mile_0fa841ed",
    "title": "燒最多錢的科技巨頭，選擇權市場現在沒有多收「下跌保費」",
    "description": (
        "Meta、微軟、Google、亞馬遜四家公司最近一年的資本支出加起來超過四千五百億美元。"
        "把 Mag 7 七檔的選擇權鏈用同一個到期日比對，資本支出佔營收比重最高的三家，"
        "下檔偏斜反而是七檔裡最便宜的。CapEx 強度與 IV skew 的關係跟直覺相反。"
    ),
    "status": "published",
    "audience": "general",
    "published_at": _ts(days_ago=12),
}


def test_ai_capex_topic_extracts_the_cluster():
    """entities=[] was the bug: the gate could not see mega-cap AI capex at all."""
    sig = arc_signature(AI_CAPEX_TOPIC_TITLE, AI_CAPEX_TOPIC_TEXT)
    assert "BIG_TECH" in sig["entities"]
    assert "CAPEX_CYCLE" in sig["entities"]


def test_cloud_capex_topic_no_longer_anchors_on_the_currency_alone():
    """「六千億美元」 used to yield entities=[USD] — an anchor on the unit."""
    sig = arc_signature(CLOUD_CAPEX_TOPIC_TITLE, CLOUD_CAPEX_TOPIC_TEXT)
    assert "BIG_TECH" in sig["entities"]
    assert set(sig["entities"]) - {"USD"} != set()


def test_ai_capex_topic_matches_the_live_article_it_repeats():
    """Behaviour, not vocabulary bookkeeping: it must reach mile_f5f4cb43."""
    matches = find_arc_duplicates(
        AI_CAPEX_TOPIC_TITLE, AI_CAPEX_TOPIC_TEXT,
        [MILE_F5F4CB43, MILE_0FA841ED], days=30,
        audience="general", include_fuzzy=True,
    )
    hits = {m["id"]: m for m in matches}
    assert "mile_f5f4cb43" in hits, "the arc gate must at least SEE the piece it repeats"
    assert "BIG_TECH" in hits["mile_f5f4cb43"]["shared_entities"]


def test_cloud_capex_topic_matches_the_live_article_it_repeats():
    matches = find_arc_duplicates(
        CLOUD_CAPEX_TOPIC_TITLE, CLOUD_CAPEX_TOPIC_TEXT,
        [MILE_F5F4CB43, MILE_0FA841ED], days=30,
        audience="general", include_fuzzy=True,
    )
    hits = {m["id"]: m for m in matches}
    assert "mile_0fa841ed" in hits
    shared = hits["mile_0fa841ed"]["shared_entities"]
    assert "BIG_TECH" in shared and "CAPEX_CYCLE" in shared


def test_bare_tech_stock_is_not_the_big_tech_cluster():
    """寧可窄而準: 「科技股」 is a comparison BENCHMARK in 79/844 live articles.

    Mapping it to BIG_TECH would repeat the bare-「銀」→SILVER bug and the
    SPY/HYG-proxy false block that hit K1590 merger-arb.
    """
    assert "BIG_TECH" not in extract_entities(
        "台股修正時，科技股的波動率比金融股高多少？以科技股為對照組。"
    )


def test_bare_giant_is_not_the_big_tech_cluster():
    """「巨頭」 alone spans 石油巨頭 / 銀行巨頭 — only 科技/雲端/七 qualify."""
    assert "BIG_TECH" not in extract_entities("石油巨頭減產，原油波動率怎麼走")


def test_capex_cycle_alone_does_not_link_unrelated_industries():
    """CAPEX_CYCLE is a mechanism entity: it sharpens, it never anchors alone."""
    fab = arc_signature("台積電資本支出上修", "台積電 CapEx 與晶圓廠的波動率。")
    assert "CAPEX_CYCLE" in fab["entities"]
    matches = find_arc_duplicates(
        "台積電資本支出上修", "台積電 CapEx 與晶圓廠 SEMIS 的波動率。",
        [MILE_F5F4CB43], days=30, audience="general", include_fuzzy=True,
    )
    assert not matches, "a fab-capex piece must not arc-match the mega-cap AI story"
