"""Smoke tests for daily_update.py 持倉比率 milestone TW staleness disclosure.

Background (2026-05-08 follow-up to 5/8 05:16 UTC fix):
- The original 2026-05-08 fix added 0050.TW staleness disclosure to
  generate_daily_article() (rich VIX article path, lines 161-178).
- mile_08abe5b7 audit revealed the publish_milestone() 持倉比率 path (the
  short article variant in daily_update.py main()) was NOT covered:
  no TW close line, no staleness banner.
- Reader of 持倉比率 articles sees TW-asset weights (3/11 active strategies
  = 27%) without knowing TW data is T-1 from referenced SPY close.
- Per CLAUDE.md "永遠修流程，不修資料": fix the article generation, not patch
  feed.json after the fact.

Fix:
- Extracted build_milestone_description() helper that mirrors the rich
  article TW staleness logic (same warning text for consistency).
- main() now calls the helper; both daily-article variants now disclose
  0050.TW data freshness symmetrically.

These tests verify the milestone description rendering branches without
exercising main()'s yfinance / Publisher / FS side-effects.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _import_build_milestone_description():
    from daily_update import build_milestone_description  # type: ignore
    return build_milestone_description


# Minimal strat_list compatible with STRATEGY_REGISTRY lookup; the helper
# uses .get(sid, (sid, True, 99)) so unknown ids degrade gracefully.
_STRAT_LIST = [("slow_vt", {"SPY": 0.6})]


def test_milestone_tw50_no_data_omits_tw_line() -> None:
    """When tw50_close is None (yfinance hard fail), no TW snapshot bullet
    appears in the milestone desc and no staleness warning is emitted."""
    build_milestone_description = _import_build_milestone_description()
    desc = build_milestone_description(
        strat_list=_STRAT_LIST,
        sigma_gjr_ann=12.0,
        vix_level=18.0,
        spy_date="2026-05-07",
        tw50_close=None,
        tw50_date=None,
    )
    assert "**0050.TW**" not in desc
    assert "資料延遲提醒" not in desc
    # Strategy table should still render
    assert "| 策略 | 配置 | 現金 |" in desc


def test_milestone_tw50_fresh_no_staleness_warning() -> None:
    """When tw50_date == spy_date (typical fresh case), TW bullet is stamped
    with date but no staleness warning is rendered."""
    build_milestone_description = _import_build_milestone_description()
    desc = build_milestone_description(
        strat_list=_STRAT_LIST,
        sigma_gjr_ann=12.0,
        vix_level=18.0,
        spy_date="2026-05-06",
        tw50_close=95.75,
        tw50_date="2026-05-06",
    )
    assert "0050.TW" in desc
    assert "NT$95.75" in desc
    assert "（2026-05-06 收盤）" in desc
    assert "資料延遲提醒" not in desc


def test_milestone_tw50_stale_renders_warning() -> None:
    """When tw50_date < spy_date (yfinance TW EOD lag), the milestone desc
    must include the same staleness warning the rich article emits.

    This is the case mile_08abe5b7 audit (2026-05-08) flagged."""
    build_milestone_description = _import_build_milestone_description()
    desc = build_milestone_description(
        strat_list=_STRAT_LIST,
        sigma_gjr_ann=12.0,
        vix_level=17.39,
        spy_date="2026-05-06",
        tw50_close=94.6,
        tw50_date="2026-05-05",
    )
    assert "NT$94.6" in desc
    assert "（2026-05-05 收盤）" in desc
    assert "資料延遲提醒" in desc
    # Both dates surface in the warning for contrast
    assert "2026-05-05" in desc
    assert "2026-05-06" in desc
    # Same warning text as rich article (consistency check)
    assert "daily_update cron 於台北時間 08:03 執行" in desc
    assert "TWSE" in desc


def test_milestone_tw50_close_without_date_graceful() -> None:
    """When tw50_close is set but tw50_date is missing (older feed entries
    or partial fetch), render TW bullet without date stamp and no warning.
    Should NOT raise."""
    build_milestone_description = _import_build_milestone_description()
    desc = build_milestone_description(
        strat_list=_STRAT_LIST,
        sigma_gjr_ann=12.0,
        vix_level=18.0,
        spy_date="2026-05-07",
        tw50_close=94.6,
        tw50_date=None,
    )
    assert "**0050.TW**: NT$94.6" in desc
    assert "（" not in desc.split("**0050.TW**")[1].split("\n")[0]  # no date suffix
    assert "資料延遲提醒" not in desc


def test_milestone_warning_format_matches_rich_article() -> None:
    """The staleness warning text in the milestone desc must be byte-for-byte
    identical to the rich article version (single source-of-truth template).
    Drift between the two would create reader confusion."""
    build_milestone_description = _import_build_milestone_description()
    desc = build_milestone_description(
        strat_list=_STRAT_LIST,
        sigma_gjr_ann=12.0,
        vix_level=18.0,
        spy_date="2026-05-06",
        tw50_close=94.6,
        tw50_date="2026-05-05",
    )
    expected_warning = (
        "> ⚠️ **0050.TW 資料延遲提醒**：本文所引用的 0050.TW 收盤為 "
        "2026-05-05，較美股 2026-05-06 收盤晚一個交易日以上。"
        "原因：daily_update cron 於台北時間 08:03 執行，早於台股當日開盤"
        "（09:00），TW 資料天然落後一個交易日；偶有 yfinance 同步延遲。"
        "今日台股實際收盤後請以官方 TWSE 數據為準。"
    )
    assert expected_warning in desc
