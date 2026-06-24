"""Smoke tests for daily_update.py 0050.TW staleness disclosure.

Background (2026-05-08 systemic fix):
- daily_update cron runs at 08:03 Asia/Taipei (canonical: config/runtime_schedules.json)
- TW market opens 09:00, closes 13:30 — at cron time, the latest TW close is
  ALWAYS T-1 (yesterday's session); occasionally yfinance lags T-2 or T-3.
- Reviewer audits (mile_146dc06e / f7584521 / 688f15e9) flagged article body
  showed 0050.TW close without date stamp, making T-1 close look current.
- Per CLAUDE.md "永遠修流程，不修資料": fix article generation, not patch JSONs.

Fix:
- generate_daily_article() now stamps tw50_date next to NT$ price.
- When tw50_date < spy_date, an explicit staleness warning block is rendered.

These tests verify the rendering branches without writing to feed.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class _CapturingPublisher:
    """Stand-in for volpred.publisher.publisher.Publisher.

    Captures the description passed to publish_milestone so tests can assert
    on the rendered article body without touching feed.json or supabase.
    """

    def __init__(self) -> None:
        self.last_title: str | None = None
        self.last_description: str | None = None
        self.last_details: dict | None = None

    def publish_milestone(self, *, title, tags, description, phase,
                          status=None, audience=None, category=None, details=None):
        self.last_title = title
        self.last_description = description
        self.last_details = details or {}
        return "mile_test_capture"


def _import_generate_daily_article():
    # daily_update imports volpred.* at module-load; the conftest already adds
    # src to sys.path, so this works in CI.
    from daily_update import generate_daily_article  # type: ignore
    return generate_daily_article


def _import_check_vix_term_structure():
    from daily_update import _check_vix_term_structure  # type: ignore
    return _check_vix_term_structure


def _import_load_vix_level():
    from daily_update import _load_vix_level  # type: ignore
    return _load_vix_level


def _import_load_json_retry():
    from daily_update import _load_json_retry  # type: ignore
    return _load_json_retry


class _FailingDataManager:
    def get_model_data(self, *args, **kwargs):
        raise RuntimeError("vix3m down")


class _EmptyDataManager:
    def get_model_data(self, *args, **kwargs):
        return []


def test_load_vix_level_warns_on_fetch_failure(capsys) -> None:
    load_vix_level = _import_load_vix_level()
    vix_level, vix_data = load_vix_level(_FailingDataManager())
    output = capsys.readouterr().out

    assert vix_level is None
    assert vix_data is None
    assert "^VIX fetch failed" in output
    assert "VIX-based strategies will fall back to GARCH" in output
    assert "vix3m down" in output


def test_load_json_retry_warns_with_exception_type_after_retries(tmp_path, capsys) -> None:
    load_json_retry = _import_load_json_retry()
    bad_json = tmp_path / "feed.json"
    bad_json.write_text("{bad json", encoding="utf-8")

    result = load_json_retry(bad_json, {"fallback": True}, retries=1, delay=0)

    output = capsys.readouterr().out
    assert result == {"fallback": True}
    assert "unreadable after 1 tries" in output
    assert "JSONDecodeError" in output
    assert str(bad_json) in output


def test_load_vix_level_warns_on_empty_data(capsys) -> None:
    load_vix_level = _import_load_vix_level()
    vix_level, vix_data = load_vix_level(_EmptyDataManager())
    output = capsys.readouterr().out

    assert vix_level is None
    assert vix_data is None
    assert "^VIX returned no rows" in output
    assert "VIX-based strategies will fall back to GARCH" in output


def test_vix_term_structure_warns_on_fetch_failure(capsys) -> None:
    check_vix_term_structure = _import_check_vix_term_structure()
    result = check_vix_term_structure(_FailingDataManager(), 18.0)
    output = capsys.readouterr().out

    assert result is None
    assert "VIX term structure check failed" in output
    assert "vix3m down" in output


def test_vix_term_structure_skips_when_vix_unavailable(capsys) -> None:
    check_vix_term_structure = _import_check_vix_term_structure()
    result = check_vix_term_structure(_FailingDataManager(), None)
    output = capsys.readouterr().out

    assert result is None
    assert "VIX term structure check skipped: VIX unavailable" in output


def test_tw50_no_data_omits_tw_line() -> None:
    """When tw50_close is None (e.g. yfinance hard fail), no 0050.TW line and
    no staleness warning should be emitted."""
    generate_daily_article = _import_generate_daily_article()
    pub = _CapturingPublisher()
    generate_daily_article(
        pub=pub,
        strat_list=[("slow_vt", {"SPY": 0.6})],
        vix_level=18.0,
        sigma_gjr_ann=12.0,
        spy_close=731.58,
        gld_close=431.68,
        spy_date="2026-05-07",
        today="2026-05-08",
        tw50_close=None,
        tw50_date=None,
        spy_ret=0.0,
        gld_ret=0.0,
    )
    body = pub.last_description or ""
    # The disclaimer footer mentions yfinance(...0050.TW) regardless; check the
    # snapshot bullet form is absent and no staleness warning is emitted.
    assert "**0050.TW**" not in body
    assert "資料延遲提醒" not in body


def test_tw50_fresh_no_staleness_warning() -> None:
    """When tw50_date == spy_date (typical TW data fresh case), price line is
    stamped with date but no staleness warning is rendered."""
    generate_daily_article = _import_generate_daily_article()
    pub = _CapturingPublisher()
    generate_daily_article(
        pub=pub,
        strat_list=[("slow_vt", {"SPY": 0.6})],
        vix_level=18.0,
        sigma_gjr_ann=12.0,
        spy_close=731.58,
        gld_close=431.68,
        spy_date="2026-05-06",
        today="2026-05-07",
        tw50_close=95.75,
        tw50_date="2026-05-06",
        spy_ret=0.0,
        gld_ret=0.0,
    )
    body = pub.last_description or ""
    assert "0050.TW" in body
    assert "NT$95.75" in body
    assert "（2026-05-06 收盤）" in body
    assert "資料延遲提醒" not in body  # tw50_date == spy_date → no warning


def test_tw50_stale_renders_warning() -> None:
    """When tw50_date < spy_date (yfinance TW EOD lag), an explicit staleness
    warning is appended to the snapshot. This is the case the 2026-05-07
    audit (mile_688f15e9) was flagging."""
    generate_daily_article = _import_generate_daily_article()
    pub = _CapturingPublisher()
    generate_daily_article(
        pub=pub,
        strat_list=[("slow_vt", {"SPY": 0.6})],
        vix_level=17.39,
        sigma_gjr_ann=12.0,
        spy_close=731.58,
        gld_close=431.68,
        spy_date="2026-05-06",
        today="2026-05-07",
        tw50_close=94.6,        # actual stale value from mile_688f15e9
        tw50_date="2026-05-05",  # 1 trading day older than spy_date
        spy_ret=0.0,
        gld_ret=0.0,
    )
    body = pub.last_description or ""
    assert "NT$94.6" in body
    assert "（2026-05-05 收盤）" in body
    assert "資料延遲提醒" in body
    assert "2026-05-05" in body  # the stale date surfaces in the warning
    assert "2026-05-06" in body  # the spy_date is referenced for contrast


def test_tw50_date_persisted_in_details() -> None:
    """tw50_date must reach feed.json details so audits can verify
    byte-for-byte traceability (P5 / strict-audit rule)."""
    generate_daily_article = _import_generate_daily_article()
    pub = _CapturingPublisher()
    generate_daily_article(
        pub=pub,
        strat_list=[("slow_vt", {"SPY": 0.6})],
        vix_level=18.0,
        sigma_gjr_ann=12.0,
        spy_close=731.58,
        gld_close=431.68,
        spy_date="2026-05-06",
        today="2026-05-07",
        tw50_close=94.6,
        tw50_date="2026-05-05",
        spy_ret=0.0,
        gld_ret=0.0,
    )
    details = pub.last_details or {}
    assert details.get("tw50_close") == 94.6
    assert details.get("tw50_date") == "2026-05-05"
    assert details.get("spy_date") == "2026-05-06"
