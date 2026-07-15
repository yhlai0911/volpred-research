from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def k1410_module():
    path = ROOT / "experiments/k1410/k1410.py"
    spec = importlib.util.spec_from_file_location("k1410_partial_month_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prices(dates: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)


def test_historical_one_day_tail_stays_excluded_after_calendar_rollover(k1410_module):
    dates = pd.DatetimeIndex([pd.Timestamp("2020-04-30")])
    dates = dates.append(pd.bdate_range("2020-05-01", "2020-05-29"))
    dates = dates.append(pd.DatetimeIndex([pd.Timestamp("2020-06-01")]))

    result = k1410_module.monthly_returns(
        _prices(dates), as_of=pd.Timestamp("2020-07-15")
    )

    assert list(result.index) == [pd.Timestamp("2020-05-31")]


def test_completed_historical_month_is_kept(k1410_module):
    dates = pd.DatetimeIndex([pd.Timestamp("2020-04-30")])
    dates = dates.append(pd.bdate_range("2020-05-01", "2020-05-29"))

    result = k1410_module.monthly_returns(
        _prices(dates), as_of=pd.Timestamp("2020-07-15")
    )

    assert list(result.index) == [pd.Timestamp("2020-05-31")]


def test_current_calendar_month_is_conservatively_excluded(k1410_module):
    dates = pd.DatetimeIndex([pd.Timestamp("2020-04-30")])
    dates = dates.append(pd.bdate_range("2020-05-01", "2020-05-29"))
    dates = dates.append(pd.bdate_range("2020-06-01", "2020-06-30"))

    result = k1410_module.monthly_returns(
        _prices(dates), as_of=pd.Timestamp("2020-06-30")
    )

    assert list(result.index) == [pd.Timestamp("2020-05-31")]


def test_well_covered_historical_tail_near_month_end_is_kept(k1410_module):
    dates = pd.DatetimeIndex([pd.Timestamp("2020-04-30")])
    dates = dates.append(pd.bdate_range("2020-05-01", "2020-05-29"))
    dates = dates.append(pd.bdate_range("2020-06-01", "2020-06-30"))

    result = k1410_module.monthly_returns(
        _prices(dates), as_of=pd.Timestamp("2020-07-15")
    )

    assert list(result.index) == [
        pd.Timestamp("2020-05-31"),
        pd.Timestamp("2020-06-30"),
    ]
