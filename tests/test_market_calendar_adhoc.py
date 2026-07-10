"""
Regression: adhoc (unscheduled) closure override in market_calendar.

Incident (2026-07-10): 台股 closed for typhoon 巴威 but exchange_calendars (XTAI)
still reported 2026-07-10 as a trading session → site showed "台股正常開盤" and
published "本日持倉建議" for a closed day. The override layer must force is_open=
False for adhoc-closed days and skip them in prev/next trading-day math — WITHOUT
touching the real config file (inject a temp override).
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from volpred import market_calendar as mc


@pytest.fixture
def temp_override(tmp_path, monkeypatch):
    """Point market_calendar at a temp adhoc-closure file and reset its cache."""
    def _write(closures):
        path = tmp_path / "market_closures_adhoc.json"
        path.write_text(json.dumps({"closures": closures}, ensure_ascii=False))
        monkeypatch.setattr(mc, "_ADHOC_CLOSURES_PATH", path)
        mc._adhoc_cache = None
        mc._adhoc_cache_mtime = None
        return path
    yield _write
    mc._adhoc_cache = None
    mc._adhoc_cache_mtime = None


def test_typhoon_override_forces_closed(temp_override):
    temp_override([
        {"market": "tw", "date": "2026-07-10", "reason": "颱風休市（巴威）",
         "reason_en": "Typhoon Bawi closure", "source": "test"}
    ])
    s = mc.get_market_status(date(2026, 7, 10), "tw")
    assert s["is_open"] is False
    assert "颱風" in s["reason"]
    assert s.get("adhoc_closure") is True


def test_next_trading_day_skips_adhoc_closure(temp_override):
    # 2026-07-10 is a Friday session per exchange_calendars; override closes it.
    temp_override([
        {"market": "tw", "date": "2026-07-10", "reason": "颱風休市", "reason_en": "Typhoon"}
    ])
    # From Thursday 7/9, the next trading day must jump PAST the closed 7/10 to 7/13.
    thu = mc.get_market_status(date(2026, 7, 9), "tw")
    assert thu["is_open"] is True
    assert thu["next_trading_day"] == "2026-07-13"
    # The closed day itself points forward to 7/13 and back to 7/9.
    fri = mc.get_market_status(date(2026, 7, 10), "tw")
    assert fri["next_trading_day"] == "2026-07-13"
    assert fri["prev_trading_day"] == "2026-07-09"


def test_no_override_leaves_calendar_untouched(temp_override):
    temp_override([])  # empty override
    s = mc.get_market_status(date(2026, 7, 10), "tw")
    assert s["is_open"] is True  # ordinary Friday session
    assert "adhoc_closure" not in s


def test_override_scoped_by_market(temp_override):
    # A TW closure must NOT close the US market on the same date.
    temp_override([
        {"market": "tw", "date": "2026-07-10", "reason": "颱風休市", "reason_en": "Typhoon"}
    ])
    us = mc.get_market_status(date(2026, 7, 10), "us")
    assert us["is_open"] is True  # NYSE unaffected by a TW typhoon


def test_malformed_override_fails_open(temp_override, monkeypatch):
    # A broken override file must not crash the calendar (fail-open to scheduled).
    path = temp_override([])
    path.write_text("{ this is not valid json")
    mc._adhoc_cache = None
    mc._adhoc_cache_mtime = None
    s = mc.get_market_status(date(2026, 7, 10), "tw")
    assert s["is_open"] is True  # degrades to exchange_calendars-only
