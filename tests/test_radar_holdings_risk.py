"""
Tests for VolPred Radar Phase A — 持倉風險體檢計算引擎 (scripts/radar_holdings_risk.py).

Verifies the risk math is correct against an independent numpy reference:
  - portfolio annualized vol = sqrt(w' Σ w) * sqrt(252)
  - 5% / 2.5% historical VaR (percentile of portfolio daily returns)
  - 5% / 2.5% parametric VaR (z*σ - μ)
  - per-position risk contribution sums to 100% and identifies the top source
  - single-asset vol equals that asset's own annualized vol
  - data-honesty: unknown tickers are reported in `skipped`, never fabricated
  - empty holdings / all-no-data return no fabricated numbers

Prices are mock real-shaped series injected via the `fetch` hook (no network).
Deterministic: a fixed RNG seed builds the synthetic price paths.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = REPO_ROOT / "scripts" / "radar_holdings_risk.py"

TRADING_DAYS = 252
Z95 = 1.6448536269514722
Z975 = 1.959963984540054


def _load_engine():
    spec = importlib.util.spec_from_file_location("radar_holdings_risk", ENGINE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eng = _load_engine()


# ─────────────────────────────────────────────────────────────────────────────
# Mock price builder
# ─────────────────────────────────────────────────────────────────────────────
def _make_prices(returns: list[float], start_price: float = 100.0) -> eng.PriceSeries:
    """Build a PriceSeries whose simple daily returns equal `returns`."""
    closes = [start_price]
    for r in returns:
        closes.append(closes[-1] * (1.0 + r))
    dates = [f"2024-01-{i + 1:02d}" if i < 28 else f"2024-02-{i - 27:02d}" for i in range(len(closes))]
    # ensure monotonic ISO dates well past lengths used here
    dates = _isodates(len(closes))
    return eng.PriceSeries(ticker="MOCK", dates=dates, closes=closes)


def _isodates(n: int) -> list[str]:
    import datetime as dt

    base = dt.date(2023, 1, 2)
    out = []
    d = base
    while len(out) < n:
        if d.weekday() < 5:  # weekdays only, looks like trading days
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def _fetch_factory(returns_by_ticker: dict[str, list[float]]):
    """Returns a fetch(ticker, lookback) compatible with the engine.
    Aligns all tickers on a shared date axis (same length) so the inner-join keeps all."""
    n = max(len(v) for v in returns_by_ticker.values())
    dates = _isodates(n + 1)

    def fetch(ticker: str, lookback_days: int):
        rets = returns_by_ticker.get(ticker.upper())
        if rets is None:
            return None
        closes = [100.0]
        for r in rets:
            closes.append(closes[-1] * (1.0 + r))
        return eng.PriceSeries(ticker=ticker.upper(), dates=dates[: len(closes)], closes=closes)

    return fetch


# ─────────────────────────────────────────────────────────────────────────────
# Reference (numpy) computations
# ─────────────────────────────────────────────────────────────────────────────
def _ref_portfolio(returns_by_ticker, weights_frac):
    tickers = list(weights_frac.keys())
    R = np.array([returns_by_ticker[t] for t in tickers])  # (k, n)
    w = np.array([weights_frac[t] for t in tickers])
    cov = np.cov(R, ddof=1)  # (k, k)
    if cov.ndim == 0:
        cov = cov.reshape(1, 1)
    port_var = float(w @ cov @ w)
    annual_vol = math.sqrt(port_var) * math.sqrt(TRADING_DAYS)
    port_daily = (w[:, None] * R).sum(axis=0)
    return annual_vol, port_daily, cov, w


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
def test_two_asset_portfolio_vol_matches_numpy():
    rng = np.random.default_rng(42)
    n = 260
    rA = list(rng.normal(0.0004, 0.012, n))
    rB = list(rng.normal(0.0002, 0.008, n))
    returns = {"SPY": rA, "TLT": rB}
    fetch = _fetch_factory(returns)

    holdings = eng.parse_holdings([
        {"ticker": "SPY", "weight_pct": 60},
        {"ticker": "TLT", "weight_pct": 40},
    ])
    res = eng.compute_holdings_risk(holdings, lookback_days=n, fetch=fetch)

    annual_vol_ref, _, _, _ = _ref_portfolio(returns, {"SPY": 0.6, "TLT": 0.4})
    assert res.portfolio_annual_vol_pct == pytest.approx(annual_vol_ref * 100, rel=1e-6)


def test_historical_and_parametric_var_match_reference():
    rng = np.random.default_rng(7)
    n = 300
    rA = list(rng.normal(0.0003, 0.015, n))
    rB = list(rng.normal(0.0001, 0.010, n))
    returns = {"QQQ": rA, "GLD": rB}
    fetch = _fetch_factory(returns)

    holdings = eng.parse_holdings([
        {"ticker": "QQQ", "weight_pct": 70},
        {"ticker": "GLD", "weight_pct": 30},
    ])
    res = eng.compute_holdings_risk(holdings, lookback_days=n, fetch=fetch)

    _, port_daily, _, _ = _ref_portfolio(returns, {"QQQ": 0.7, "GLD": 0.3})
    # historical VaR = -percentile(returns, q) * 100
    var95_ref = -float(np.percentile(port_daily, 5.0)) * 100
    var975_ref = -float(np.percentile(port_daily, 2.5)) * 100
    assert res.var_95_hist_pct == pytest.approx(var95_ref, rel=1e-6)
    assert res.var_975_hist_pct == pytest.approx(var975_ref, rel=1e-6)

    # parametric VaR = (z*sd - mean) * 100, sd ddof=1
    mu = float(np.mean(port_daily))
    sd = float(np.std(port_daily, ddof=1))
    assert res.var_95_param_pct == pytest.approx((Z95 * sd - mu) * 100, rel=1e-6)
    assert res.var_975_param_pct == pytest.approx((Z975 * sd - mu) * 100, rel=1e-6)


def test_risk_contributions_sum_to_100_and_top_is_riskiest():
    rng = np.random.default_rng(11)
    n = 260
    # high-vol asset gets large weight -> should dominate risk contribution
    rHigh = list(rng.normal(0.0, 0.030, n))
    rLow = list(rng.normal(0.0, 0.004, n))
    returns = {"LEV": rHigh, "BND": rLow}
    fetch = _fetch_factory(returns)

    holdings = eng.parse_holdings([
        {"ticker": "LEV", "weight_pct": 50},
        {"ticker": "BND", "weight_pct": 50},
    ])
    res = eng.compute_holdings_risk(holdings, lookback_days=n, fetch=fetch)

    total_contrib = sum(p.risk_contribution_pct for p in res.positions)
    assert total_contrib == pytest.approx(100.0, abs=1e-6)
    assert res.top_risk_ticker == "LEV"
    # top contribution clearly above 50% given much higher vol
    assert res.top_risk_contribution_pct > 80.0


def test_single_asset_vol_equals_own_annual_vol():
    rng = np.random.default_rng(99)
    n = 252
    r = list(rng.normal(0.0005, 0.02, n))
    returns = {"SPY": r}
    fetch = _fetch_factory(returns)

    holdings = eng.parse_holdings([{"ticker": "SPY", "weight_pct": 100}])
    res = eng.compute_holdings_risk(holdings, lookback_days=n, fetch=fetch)

    own_sd = float(np.std(r, ddof=1))
    own_annual = own_sd * math.sqrt(TRADING_DAYS) * 100
    assert res.portfolio_annual_vol_pct == pytest.approx(own_annual, rel=1e-6)
    assert res.positions[0].annual_vol_pct == pytest.approx(own_annual, rel=1e-6)
    assert res.top_risk_contribution_pct == pytest.approx(100.0, abs=1e-6)


def test_unknown_ticker_is_skipped_not_fabricated():
    rng = np.random.default_rng(3)
    n = 60
    returns = {"SPY": list(rng.normal(0, 0.01, n))}
    fetch = _fetch_factory(returns)  # only SPY resolvable

    holdings = eng.parse_holdings([
        {"ticker": "SPY", "weight_pct": 50},
        {"ticker": "NOTREAL", "weight_pct": 50},
    ])
    res = eng.compute_holdings_risk(holdings, lookback_days=n, fetch=fetch)

    assert [s["ticker"] for s in res.skipped] == ["NOTREAL"]
    # only SPY priced -> single-asset portfolio, no fabricated value for NOTREAL
    assert all(p.ticker != "NOTREAL" for p in res.positions)
    assert res.portfolio_annual_vol_pct is not None


def test_empty_holdings_returns_no_numbers():
    res = eng.compute_holdings_risk([], lookback_days=252, fetch=_fetch_factory({}))
    assert res.portfolio_annual_vol_pct is None
    assert res.var_95_hist_pct is None
    assert res.top_risk_ticker is None
    assert res.notes


def test_all_no_data_returns_no_numbers():
    fetch = _fetch_factory({})  # nothing resolves

    holdings = eng.parse_holdings([{"ticker": "FAKE1", "weight_pct": 100}])
    res = eng.compute_holdings_risk(holdings, lookback_days=252, fetch=fetch)
    assert res.portfolio_annual_vol_pct is None
    assert len(res.skipped) == 1
    assert any("假值" in n or "資料" in n for n in res.notes)


def test_cash_reduces_portfolio_vol():
    rng = np.random.default_rng(21)
    n = 252
    r = list(rng.normal(0.0, 0.02, n))
    returns = {"SPY": r}
    fetch = _fetch_factory(returns)

    full = eng.compute_holdings_risk(
        eng.parse_holdings([{"ticker": "SPY", "weight_pct": 100}]), lookback_days=n, fetch=fetch
    )
    half = eng.compute_holdings_risk(
        eng.parse_holdings([{"ticker": "SPY", "weight_pct": 50}]), lookback_days=n, fetch=fetch
    )
    # 50% cash -> portfolio vol should be ~half of fully-invested
    assert half.cash_pct == pytest.approx(50.0)
    assert half.portfolio_annual_vol_pct == pytest.approx(full.portfolio_annual_vol_pct * 0.5, rel=1e-6)


def test_parse_holdings_accepts_dict_and_dedups():
    parsed = eng.parse_holdings({"spy": 30, "tlt": 20})
    assert {h.ticker for h in parsed} == {"SPY", "TLT"}

    deduped = eng.parse_holdings([
        {"ticker": "SPY", "weight_pct": 30},
        {"ticker": "spy", "weight_pct": 20},
    ])
    assert len(deduped) == 1
    assert deduped[0].weight_pct == pytest.approx(50.0)


def test_week_change_present_with_enough_sample():
    rng = np.random.default_rng(5)
    n = 120
    returns = {"SPY": list(rng.normal(0, 0.01, n)), "TLT": list(rng.normal(0, 0.008, n))}
    fetch = _fetch_factory(returns)
    res = eng.compute_holdings_risk(
        eng.parse_holdings([{"ticker": "SPY", "weight_pct": 60}, {"ticker": "TLT", "weight_pct": 40}]),
        lookback_days=n,
        fetch=fetch,
    )
    assert res.week_change is not None
    assert "delta_pct" in res.week_change
    assert "current_annual_vol_pct" in res.week_change
