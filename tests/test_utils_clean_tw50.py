"""Tests for clean_tw50_data().

Why this file exists (2026-07-21): the function is called from ~130 files and
had no test at all. Its extreme-return branch used to zero any |return| > 50%
and rebuild the entire price series by cumprod, silently. This pins both the
split repair it is actually for and the fact that extreme returns are now
reported rather than erased.
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from volpred.utils import (
    _TW50_SPLIT_DATE,
    _TW50_SPLIT_RATIO,
    EXTREME_RETURN_INCIDENTS,
    clean_tw50_data,
)


@pytest.fixture(autouse=True)
def _clear_incidents():
    EXTREME_RETURN_INCIDENTS.clear()
    yield
    EXTREME_RETURN_INCIDENTS.clear()


def _series(values, start="2013-12-26"):
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _with_split_break(n_pre=5, n_post=5):
    """Prices with the Yahoo artifact: pre-2014-01-02 quoted 4x too high."""
    post = np.linspace(50.0, 52.0, n_post)
    pre = np.linspace(48.0, 50.0, n_pre) * _TW50_SPLIT_RATIO
    idx = pd.bdate_range(end=pd.Timestamp(_TW50_SPLIT_DATE), periods=n_pre + 1)[:-1]
    idx = idx.append(pd.bdate_range(start=_TW50_SPLIT_DATE, periods=n_post))
    return pd.Series(np.concatenate([pre, post]), index=idx)


def test_split_artifact_is_repaired():
    prices = _with_split_break()
    clean_prices, clean_returns = clean_tw50_data(prices)

    split_ret = clean_returns.loc[pd.Timestamp(_TW50_SPLIT_DATE)]
    assert abs(split_ret) < 0.10, f"split break survived: {split_ret:+.2%}"
    # Pre-split prices divided down, post-split untouched.
    assert clean_prices.iloc[0] == pytest.approx(48.0)
    assert clean_prices.iloc[-1] == pytest.approx(52.0)


def test_series_without_break_is_unchanged():
    prices = _series([10.0, 10.1, 10.2, 10.15, 10.3])
    clean_prices, clean_returns = clean_tw50_data(prices)

    pd.testing.assert_series_equal(clean_prices, prices)
    pd.testing.assert_series_equal(clean_returns, prices.pct_change())


def test_extreme_return_is_preserved_not_zeroed():
    """The regression this file was written for."""
    prices = _series([10.0, 10.1, 30.0, 30.2, 30.1])  # +197% on day 3

    with pytest.warns(RuntimeWarning, match="PRESERVED, not zeroed"):
        clean_prices, clean_returns = clean_tw50_data(prices)

    spike = clean_returns.iloc[2]
    assert spike > 1.5, f"extreme return was erased: {spike:+.2%}"
    # Prices must not be rebuilt from a doctored return path.
    pd.testing.assert_series_equal(clean_prices, prices)


def test_extreme_return_is_recorded_for_audit():
    prices = _series([10.0, 10.1, 30.0, 30.2, 30.1])

    with pytest.warns(RuntimeWarning):
        clean_tw50_data(prices)

    assert len(EXTREME_RETURN_INCIDENTS) == 1
    incident = EXTREME_RETURN_INCIDENTS[0]
    assert incident["n_days"] == 1
    assert incident["returns"][0] > 1.5
    assert str(prices.index[2]) in incident["dates"]


def test_clean_series_records_nothing_and_warns_nothing():
    prices = _series([10.0, 10.1, 10.2, 10.15, 10.3])

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        clean_tw50_data(prices)

    assert EXTREME_RETURN_INCIDENTS == []


def test_returns_argument_is_ignored_and_recomputed():
    """Second arg is documented as optional/recomputed — pin that."""
    prices = _series([10.0, 10.1, 10.2, 10.15, 10.3])
    bogus = pd.Series(99.0, index=prices.index)

    _, clean_returns = clean_tw50_data(prices, bogus)

    pd.testing.assert_series_equal(clean_returns, prices.pct_change())
