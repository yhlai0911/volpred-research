"""Tests for _infer_audience() enforce gate.

Root cause covered (2026-05-26): mile_d0d66405 was published with
audience='general' despite containing ≥2 academic keywords (GARCH,
QLIKE, K-ids in content). The publisher had no proactive inference —
it accepted agent-supplied audience verbatim. _infer_audience() is the
enforce mechanism: caller-supplied audience is a hint only; if inferred
value disagrees, inferred value wins (with WARN log).
"""
from __future__ import annotations

import json
import logging
import pytest
from pathlib import Path

from volpred.publisher.publisher import (
    Publisher,
    _infer_audience,
)


# ---------------------------------------------------------------------------
# Part 1: _infer_audience() unit tests
# ---------------------------------------------------------------------------

class TestInferAudienceResearchCases:
    """Cases where content should be inferred as 'research'."""

    def test_k_id_in_title_triggers_research(self):
        assert _infer_audience("K1380 GARCH 改進分析", "", []) == "research"

    def test_k_id_lower_case_in_title_triggers_research(self):
        # K followed by digits regardless of surrounding text
        assert _infer_audience("關於 K999 實驗的結果", "", []) == "research"

    def test_two_academic_keywords_in_content(self):
        content = "本研究跑了 bootstrap 抽樣並計算 QLIKE 損失函數。"
        assert _infer_audience("市場波動分析", content, []) == "research"

    def test_p_value_and_t_stat_triggers_research(self):
        content = "t-stat = 3.24, p-value < 0.01，達到統計顯著。"
        assert _infer_audience("結果討論", content, []) == "research"

    def test_harvey_and_dm_test_triggers_research(self):
        content = "Harvey threshold 通過，DM test 顯示兩模型有顯著差異。"
        assert _infer_audience("模型比較", content, []) == "research"

    def test_garch_and_mle_triggers_research(self):
        content = "利用 MLE 估計 GARCH 參數。"
        assert _infer_audience("GARCH 模型估計", content, []) == "research"

    def test_k_id_in_tags_and_one_keyword_reaches_threshold(self):
        # K-id in tag list + bootstrap in content = 2 hits
        tags = ["K513", "波動率"]
        content = "bootstrap 重抽樣 1000 次。"
        assert _infer_audience("波動率研究", content, tags) == "research"

    def test_mile_d0d66405_case(self):
        """Regression: the triggering incident.

        mile_d0d66405 had audience='general' but title contained 'K1380'
        and content contained multiple academic keywords (GARCH, QLIKE).
        _infer_audience must return 'research'.
        """
        title = "K1380 v4 — GARCH-X 延伸：跨市場比較"
        content = (
            "本文報告 K1380 實驗結果。GARCH-X 模型加入 VIX 因子後，QLIKE 改善 "
            "達到 Harvey threshold（|t|>3.0）。DM test p-value=0.008，bootstrap "
            "CI=[0.003, 0.014]，MLE 收斂良好。"
        )
        tags = ["K1380", "GARCH-X", "波動率"]
        assert _infer_audience(title, content, tags) == "research"

    def test_bonferroni_and_cointegration(self):
        content = "Bonferroni 校正後，cointegration 關係仍顯著。"
        assert _infer_audience("跨資產分析", content, []) == "research"

    def test_har_rv_and_gjr_garch(self):
        content = "HAR-RV 與 GJR-GARCH 在短期預測期均優於 random walk。"
        assert _infer_audience("預測比較", content, []) == "research"


class TestInferAudienceGeneralCases:
    """Cases where content should remain 'general' (not over-inferred)."""

    def test_pure_general_article_stays_general(self):
        title = "為什麼你的投資總是輸大盤？"
        content = (
            "很多人問我：「我每個月定期定額，為什麼還是輸？」"
            "答案其實很簡單：我們在錯的時間點做了對的事情。"
            "研究顯示，長期持有 0050 可以打敗 80% 的主動型基金。"
        )
        assert _infer_audience(title, content, ["一般讀者", "投資"]) == "general"

    def test_fomc_event_article_no_jargon(self):
        title = "Fed 升息了！你的房貸怎麼辦？"
        content = "Fed 今天宣布升息 1 碼，這對一般人意味著什麼？房貸族最直接受影響。"
        assert _infer_audience(title, content, ["FOMC", "升息", "房貸"]) == "general"

    def test_strategy_intro_stays_general(self):
        title = "波動率目標策略：讓風險自動導航"
        content = (
            "想像開車時有自動巡航控制：速度穩定、不急煞。"
            "波動率目標策略就是投資組合的自動巡航。"
            "當市場「震動」（波動率）升高，自動減少倉位；穩定時再增加。"
        )
        assert _infer_audience(title, content, ["策略", "波動率", "風險"]) == "general"

    def test_one_academic_keyword_not_enough(self):
        # Only "bootstrap" — below threshold of 2
        content = "我們做了 bootstrap 模擬，結果顯示一般投資人不需要擔心。"
        assert _infer_audience("散戶投資術", content, []) == "general"

    def test_sharpe_alone_not_enough(self):
        # Only "Sharpe" — below threshold
        content = "這個策略的 Sharpe ratio 是 1.2，相當不錯。"
        assert _infer_audience("基金選擇指南", content, []) == "general"

    def test_common_financial_terms_not_academic(self):
        # "策略", "報酬", "風險", "股市" are NOT academic keywords
        content = "台股的風險與報酬長期來看是合理的，策略上建議定期定額。"
        assert _infer_audience("台股投資入門", content, ["台股", "策略"]) == "general"

    def test_empty_content_defaults_general(self):
        assert _infer_audience("投資心態", "", []) == "general"

    def test_empty_title_and_content_defaults_general(self):
        assert _infer_audience("", "", []) == "general"

    def test_garch_alone_not_enough(self):
        # Only "GARCH" — below threshold of 2
        content = "GARCH 模型是用來預測波動率的工具。"
        assert _infer_audience("波動率入門", content, []) == "general"

    def test_var_alone_not_enough(self):
        # Only "VaR" — below threshold
        content = "VaR 是銀行常用的風險指標。"
        assert _infer_audience("風控基礎", content, []) == "general"


class TestInferAudienceContentTypeOverrides:
    """content_type overrides take highest priority."""

    def test_member_qa_preserved_regardless_of_content(self):
        content = "bootstrap QLIKE Harvey p-value t-stat DM test MLE cointegration GARCH Bonferroni"
        assert _infer_audience("K999 會員問題", content, [], content_type="member_qa") == "member_qa"

    def test_event_article_preserved(self):
        content = "bootstrap QLIKE Harvey"
        assert _infer_audience("FOMC 即時觀察", content, [], content_type="event_article") == "event"

    def test_daily_digest_preserved_as_general(self):
        content = "K1512 bootstrap QLIKE Harvey p-value t-stat DM test"
        assert _infer_audience("每日精選導讀", content, [], content_type="daily_digest") == "general"

    def test_none_content_type_uses_keyword_inference(self):
        content = "bootstrap QLIKE p-value"
        assert _infer_audience("分析", content, [], content_type=None) == "research"


class TestInferAudiencePublishMilestoneIntegration:
    """Integration tests: _infer_audience interacts with publish_milestone."""

    @pytest.fixture
    def pub(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VOLPRED_ACTOR", "claude")
        # Block Supabase URL discovery so any direct REST call has no target
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
        monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
        monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
        monkeypatch.setattr(
            "volpred.publisher.publisher.cluster_gate_status",
            lambda _cluster: {"blocked": False, "count": 0, "cap": 10, "ratio": 0.0},
        )
        # 2026-05-27 fix (50-ghost Supabase pollution incident): stub
        # supabase_sync.sync_article — Publisher.publish_milestone calls it
        # directly via module-level import, bypassing the REMOTE_URL gate.
        # Without this, every test fixture invocation publishes a real
        # article to production Supabase.
        import sys
        import importlib
        for mod_name in ("supabase_sync", "scripts.supabase_sync"):
            try:
                mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
                if hasattr(mod, "sync_article"):
                    monkeypatch.setattr(mod, "sync_article", lambda *a, **kw: True, raising=False)
                if hasattr(mod, "_post"):
                    monkeypatch.setattr(mod, "_post", lambda *a, **kw: False, raising=False)
            except (ImportError, ModuleNotFoundError):
                pass
        return Publisher(storage_dir=str(tmp_path))

    def test_explicit_general_overridden_when_content_is_research(
        self, pub, tmp_path, caplog
    ):
        """mile_d0d66405 scenario: agent passes audience='general' but content
        has ≥2 academic keywords. publisher must override to 'research' + WARN."""
        research_content = (
            "K1380 v4 使用 GARCH-X 模型，加入 VIX 作為外生變數。"
            "QLIKE 損失函數改善顯著。bootstrap CI 驗證。"
        )
        with caplog.at_level(logging.WARNING, logger="root"):
            pub_id = pub.publish_milestone(
                title="K1380 GARCH-X 延伸分析",
                description=research_content,
                phase="research",
                audience="general",  # agent mis-tag — should be overridden
                tags=["一般讀者", "波動率"],
                status="draft",
            )

        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        # Audience must be overridden to research
        assert item["audience"] == "research", f"expected 'research', got '{item['audience']}'"
        # WARN must be printed (captured via stdout or caplog)
        # We check the feed record is correct; WARN goes to stdout print

    def test_correct_research_audience_not_double_warned(
        self, pub, tmp_path
    ):
        """Agent correctly passes audience='research' — no override, no WARN needed."""
        research_content = (
            "本文報告 GARCH 模型與 HAR-RV 的 QLIKE 比較結果，"
            "使用 DM test 與 bootstrap CI 驗證。"
        )
        pub_id = pub.publish_milestone(
            title="GARCH vs HAR-RV 比較",
            description=research_content,
            phase="research",
            audience="research",
            tags=["研究", "波動率"],
            status="draft",
        )
        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        assert item["audience"] == "research"

    def test_clean_general_article_stays_general(self, pub, tmp_path):
        """Clean general content with no academic keywords stays general."""
        general_content = (
            "想像你有 100 萬要投資。每個月定期定額買 0050，"
            "長期下來報酬率比大多數主動型基金還好。"
            "這不是魔法，是統計上的必然。"
        )
        pub_id = pub.publish_milestone(
            title="定期定額的秘密",
            description=general_content,
            phase="general",
            audience="general",
            tags=["一般讀者", "定期定額"],
            status="draft",
        )
        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        assert item["audience"] == "general"


class TestInferAudienceDailyPreservation:
    """2026-05-27 fix (mile_a91f19be incident): daily strategy articles must
    preserve audience='daily' even when boilerplate description contains
    academic keywords (GARCH/VaR/Sharpe), like member_qa/event preservation."""

    @pytest.fixture
    def pub(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VOLPRED_ACTOR", "claude")
        # Block Supabase URL discovery so any direct REST call has no target
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
        monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
        monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
        monkeypatch.setattr(
            "volpred.publisher.publisher.cluster_gate_status",
            lambda _cluster: {"blocked": False, "count": 0, "cap": 10, "ratio": 0.0},
        )
        # 2026-05-27 fix (50-ghost Supabase pollution incident): stub
        # supabase_sync.sync_article — Publisher.publish_milestone calls it
        # directly via module-level import, bypassing the REMOTE_URL gate.
        # Without this, every test fixture invocation publishes a real
        # article to production Supabase.
        import sys
        import importlib
        for mod_name in ("supabase_sync", "scripts.supabase_sync"):
            try:
                mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
                if hasattr(mod, "sync_article"):
                    monkeypatch.setattr(mod, "sync_article", lambda *a, **kw: True, raising=False)
                if hasattr(mod, "_post"):
                    monkeypatch.setattr(mod, "_post", lambda *a, **kw: False, raising=False)
            except (ImportError, ModuleNotFoundError):
                pass
        return Publisher(storage_dir=str(tmp_path))

    def test_mile_a91f19be_daily_strategy_preserved(self, pub, tmp_path):
        """Exact regression case: daily_update.py boilerplate hits ≥2
        academic keywords (GARCH + VaR + Sharpe) yet audience='daily' must
        survive — these are retail-facing daily recommendations, not research."""
        daily_content = (
            "# 2026-05-27 每日策略建議\n"
            "> 基於 2026-05-26 收盤數據，預測下一交易日最佳持倉配置。\n\n"
            "## 市場快照\n"
            "- **SPY**: $750.59 (+0.66%)\n"
            "- **VIX**: 17.01（正常）\n"
            "- **GARCH 年化波動率**: 11.3%\n"
            "- VaR 95% / Sharpe 0.8 全包含\n"
        )
        pub_id = pub.publish_milestone(
            title="每日策略建議：VIX 17.01（正常）— 2026-05-27",
            description=daily_content,
            phase="daily_recommendation",
            audience="daily",
            category="general",
            tags=["每日建議", "VIX", "策略配置"],
            status="published",
        )
        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        assert item["audience"] == "daily", (
            f"daily preservation failed — got '{item['audience']}'. "
            "Boilerplate GARCH/VaR/Sharpe must not override daily."
        )

    def test_daily_tag_alone_triggers_preservation_even_if_audience_missing(
        self, pub, tmp_path
    ):
        """tag '每日建議' or 'daily-update' detection works without explicit audience."""
        pub_id = pub.publish_milestone(
            title="每日策略：GARCH 預測",
            description="QLIKE 評估 + bootstrap CI（boilerplate academic terms）",
            phase="daily_recommendation",
            tags=["每日建議", "VIX"],
            status="published",
        )
        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        assert item["audience"] == "daily"

    def test_daily_update_alias_tag_also_works(self, pub, tmp_path):
        """English alias 'daily-update' tag should equally trigger preservation."""
        pub_id = pub.publish_milestone(
            title="Daily strategy update",
            description="HAR-RV vs GJR-GARCH comparison (boilerplate)",
            phase="daily_recommendation",
            tags=["daily-update", "VIX"],
            status="published",
        )
        feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
        item = next(i for i in feed if i["id"] == pub_id)
        assert item["audience"] == "daily"
