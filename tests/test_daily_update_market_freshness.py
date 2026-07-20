"""Regression tests for market_daily SPY/GLD source-date freshness."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from daily_update import reconcile_market_daily_sources  # noqa: E402
import supabase_sync  # noqa: E402


def _frame(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [r[1] for r in rows], "close": [r[2] for r in rows]},
        index=pd.to_datetime([r[0] for r in rows]),
    )


def test_reconcile_repairs_recovered_source_instead_of_copying_prior_close():
    market_daily = {
        "2026-07-14": {"spy_close": 749.17, "gld_close": 367.13},
        "2026-07-15": {"spy_close": 749.17, "gld_close": 367.13},
    }
    spy = _frame([
        ("2026-07-13", 752.47, 749.17),
        ("2026-07-14", 750.91, 751.83),
    ])
    gld = _frame([
        ("2026-07-13", 372.77, 367.13),
        ("2026-07-14", 374.53, 372.15),
    ])

    result = reconcile_market_daily_sources(market_daily, spy, gld)

    assert result == {"rows": 2, "stale_spy": 0, "stale_gld": 0}
    assert market_daily["2026-07-14"]["spy_data_date"] == "2026-07-13"
    assert market_daily["2026-07-15"]["spy_data_date"] == "2026-07-14"
    assert market_daily["2026-07-15"]["spy_close"] == 751.83
    assert market_daily["2026-07-15"]["gld_close"] == 372.15
    assert market_daily["2026-07-15"]["spy_stale"] is False
    assert market_daily["2026-07-15"]["gld_stale"] is False


def test_reconcile_marks_carry_forward_when_expected_session_is_missing():
    market_daily = {"2026-07-15": {}}
    spy = _frame([("2026-07-13", 752.47, 749.17)])
    gld = _frame([("2026-07-13", 372.77, 367.13)])

    result = reconcile_market_daily_sources(market_daily, spy, gld)

    assert result == {"rows": 1, "stale_spy": 1, "stale_gld": 1}
    assert market_daily["2026-07-15"] == {
        "spy_open": 752.47,
        "spy_close": 749.17,
        "spy_data_date": "2026-07-13",
        "spy_stale": True,
        "gld_open": 372.77,
        "gld_close": 367.13,
        "gld_data_date": "2026-07-13",
        "gld_stale": True,
    }


def test_reconcile_uses_friday_close_for_monday_run():
    market_daily = {"2026-07-20": {}}
    spy = _frame([("2026-07-17", 760.0, 761.0)])
    gld = _frame([("2026-07-17", 375.0, 376.0)])

    reconcile_market_daily_sources(market_daily, spy, gld)

    assert market_daily["2026-07-20"]["spy_data_date"] == "2026-07-17"
    assert market_daily["2026-07-20"]["spy_stale"] is False


def test_supabase_sync_preserves_source_dates_and_stale_flags(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "test-key")

    def fake_post(table, row):
        captured["table"] = table
        captured["row"] = row
        return True

    monkeypatch.setattr(supabase_sync, "_post", fake_post)
    market = {
        "spy_close": 751.83,
        "spy_data_date": "2026-07-14",
        "spy_stale": False,
        "gld_close": 372.15,
        "gld_data_date": "2026-07-14",
        "gld_stale": False,
        "gap_alert_level": None,
    }

    assert supabase_sync.sync_market_daily("2026-07-15", market) is True
    assert captured == {
        "table": "market_daily",
        "row": {
            "trade_date": "2026-07-15",
            "spy_close": 751.83,
            "spy_data_date": "2026-07-14",
            "spy_stale": False,
            "gld_close": 372.15,
            "gld_data_date": "2026-07-14",
            "gld_stale": False,
        },
    }


def test_adjudicated_local_only_keys_strip_without_daily_warn(monkeypatch, capsys):
    """2026-07-20 D5 adjudication: overnight_gap / gap_alert_level are
    canonical-local-only. They must be stripped from the market_daily row
    (table has no such columns) WITHOUT the daily schema-mismatch warning
    that spammed sync logs for 5 straight days."""
    captured = {}
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "test-key")
    monkeypatch.setattr(supabase_sync, "_post", lambda table, row: captured.update(row=row) or True)

    market = {
        "spy_close": 751.83,
        "overnight_gap": -0.011509,
        "gap_alert_level": "yellow",
    }
    assert supabase_sync.sync_market_daily("2026-07-20", market) is True
    assert captured["row"] == {"trade_date": "2026-07-20", "spy_close": 751.83}
    assert "schema-mismatch" not in capsys.readouterr().out


def test_genuinely_unknown_key_still_warns_loudly(monkeypatch, capsys):
    """The adjudication must not weaken the fail-open+warn design: a key that
    is neither whitelisted nor adjudicated local-only still strips AND warns
    (2026-04-17 silent-400 outage class stays observable)."""
    captured = {}
    monkeypatch.setattr(supabase_sync, "SUPABASE_KEY", "test-key")
    monkeypatch.setattr(supabase_sync, "_post", lambda table, row: captured.update(row=row) or True)

    market = {"spy_close": 751.83, "nk225_close": 39100.0}
    assert supabase_sync.sync_market_daily("2026-07-20", market) is True
    assert "nk225_close" not in captured["row"]
    out = capsys.readouterr().out
    assert "schema-mismatch warning" in out
    assert "nk225_close" in out
