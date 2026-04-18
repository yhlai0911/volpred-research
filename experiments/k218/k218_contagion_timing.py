"""
K218: Cross-Asset Contagion Timing — Can SPY Shocks Predict GLD/TLT Vol?
=========================================================================
[提出: 用戶, 執行: Claude]

Background:
  K163 showed SPY is a net contagion source, GLD has zero contagion from SPY.
  K176 showed TSMC→0050 contagion is 4.6x SPY→0050.
  Can we use cross-asset vol spillovers to TIME non-equity positions?

Data: SPY, GLD, TLT, QQQ daily from yfinance. OOS: 2023-2024.

Methodology:
  1. Cross-asset vol spillover features:
     - SPY 5d realized vol shock: (RV_5d - RV_22d) / RV_22d
     - SPY-GLD return correlation rolling 66d
     - SPY drawdown indicator: SPY < 0.95 * 252d_high
  2. Test: Does SPY vol shock predict NEXT-period GLD/TLT vol?
     - Lag 1-5 days Granger causality
     - Partial correlation controlling for own-asset vol
  3. Contagion-based VT overlay for 50/50 SPY/GLD:
     - When SPY vol shock > 2 std: reduce SPY, increase GLD
     - When SPY in drawdown: shift to 40/60 SPY/GLD
  4. 5-period cross-OOS

Usage:
    uv run python experiments/k218_contagion_timing.py
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ======================================================================
# CONFIG
# ======================================================================
TICKERS = ["SPY", "GLD", "TLT", "QQQ"]
DATA_START = "2005-01-01"
DATA_END = "2026-03-24"

# 5-period cross-OOS
OOS_PERIODS = [
    ("2015-01-01", "2016-12-31"),
    ("2017-01-01", "2018-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2021-01-01", "2022-12-31"),
    ("2023-01-01", "2024-12-31"),
]

WINDOW_RV_SHORT = 5     # 5-day realized vol
WINDOW_RV_LONG = 22     # 22-day realized vol
WINDOW_CORR = 66        # rolling correlation window
WINDOW_HIGH = 252       # rolling high for drawdown
GRANGER_MAX_LAG = 5     # max lag for Granger causality
VOL_SHOCK_THRESHOLD = 2.0  # std deviations for vol shock signal
DRAWDOWN_THRESHOLD = 0.95  # SPY < 95% of 252d high

print("=" * 80)
print("K218: Cross-Asset Contagion Timing")
print("    Can SPY Shocks Predict GLD/TLT Vol?")
print("=" * 80)
print(f"  [提出: 用戶, 執行: Claude]")
print(f"  Data: {DATA_START} to {DATA_END}")
print(f"  OOS periods: {len(OOS_PERIODS)}")
print(f"  Tickers: {', '.join(TICKERS)}")
print()


# ======================================================================
# 1. DATA LOADING
# ======================================================================
print("=" * 60)
print("PHASE 1: Data Loading")
print("=" * 60)

import yfinance as yf

prices = {}
for ticker in TICKERS:
    print(f"  Downloading {ticker}...", end=" ")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # yfinance >= 0.2.31 uses "Close" (adjusted by default), older uses "Adj Close"
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    prices[ticker] = df[col].dropna()
    print(f"{len(prices[ticker])} obs ({prices[ticker].index[0].strftime('%Y-%m-%d')} to {prices[ticker].index[-1].strftime('%Y-%m-%d')})")

# Align all series to common dates
common_idx = prices["SPY"].index
for t in TICKERS[1:]:
    common_idx = common_idx.intersection(prices[t].index)

print(f"\n  Common trading days: {len(common_idx)}")
print(f"  Range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

# Build returns DataFrame
returns = pd.DataFrame(index=common_idx)
for t in TICKERS:
    returns[t] = np.log(prices[t].reindex(common_idx)).diff()
returns = returns.dropna()
print(f"  Return series length: {len(returns)}")
print()


# ======================================================================
# 2. FEATURE CONSTRUCTION
# ======================================================================
print("=" * 60)
print("PHASE 2: Feature Construction")
print("=" * 60)

# Realized vol (annualized)
rv = pd.DataFrame(index=returns.index)
for t in TICKERS:
    rv[f"{t}_rv5"] = returns[t].rolling(WINDOW_RV_SHORT).std() * np.sqrt(252)
    rv[f"{t}_rv22"] = returns[t].rolling(WINDOW_RV_LONG).std() * np.sqrt(252)

# SPY vol shock: (RV_5d - RV_22d) / RV_22d
rv["SPY_vol_shock"] = (rv["SPY_rv5"] - rv["SPY_rv22"]) / rv["SPY_rv22"]

# Standardize SPY vol shock with expanding window
rv["SPY_vol_shock_mean"] = rv["SPY_vol_shock"].expanding(min_periods=252).mean()
rv["SPY_vol_shock_std"] = rv["SPY_vol_shock"].expanding(min_periods=252).std()
rv["SPY_vol_shock_z"] = (rv["SPY_vol_shock"] - rv["SPY_vol_shock_mean"]) / rv["SPY_vol_shock_std"]

# SPY-GLD rolling correlation
rv["SPY_GLD_corr66"] = returns["SPY"].rolling(WINDOW_CORR).corr(returns["GLD"])
rv["SPY_TLT_corr66"] = returns["SPY"].rolling(WINDOW_CORR).corr(returns["TLT"])
rv["SPY_QQQ_corr66"] = returns["SPY"].rolling(WINDOW_CORR).corr(returns["QQQ"])

# SPY drawdown indicator
spy_price = prices["SPY"].reindex(returns.index)
rv["SPY_252d_high"] = spy_price.rolling(WINDOW_HIGH).max()
rv["SPY_drawdown_pct"] = spy_price / rv["SPY_252d_high"]
rv["SPY_in_drawdown"] = (rv["SPY_drawdown_pct"] < DRAWDOWN_THRESHOLD).astype(int)

rv = rv.dropna()
print(f"  Features computed: {len(rv)} observations")
print(f"  SPY vol shock stats:")
print(f"    Mean:   {rv['SPY_vol_shock'].mean():.4f}")
print(f"    Std:    {rv['SPY_vol_shock'].std():.4f}")
print(f"    Skew:   {rv['SPY_vol_shock'].skew():.4f}")
print(f"    Kurt:   {rv['SPY_vol_shock'].kurtosis():.4f}")
print(f"  SPY in drawdown: {rv['SPY_in_drawdown'].sum()} days ({rv['SPY_in_drawdown'].mean()*100:.1f}%)")
print(f"  SPY vol shock Z > 2: {(rv['SPY_vol_shock_z'] > 2).sum()} days ({(rv['SPY_vol_shock_z'] > 2).mean()*100:.1f}%)")
print(f"\n  Rolling correlations (median):")
print(f"    SPY-GLD: {rv['SPY_GLD_corr66'].median():.3f}")
print(f"    SPY-TLT: {rv['SPY_TLT_corr66'].median():.3f}")
print(f"    SPY-QQQ: {rv['SPY_QQQ_corr66'].median():.3f}")
print()


# ======================================================================
# 3. GRANGER CAUSALITY TESTS
# ======================================================================
print("=" * 60)
print("PHASE 3: Granger Causality — SPY Vol → GLD/TLT/QQQ Vol")
print("=" * 60)


def granger_causality_manual(y: pd.Series, x: pd.Series, max_lag: int) -> dict:
    """
    Manual Granger causality test: does x Granger-cause y?
    H0: lagged x has no predictive power for y beyond lagged y.

    Returns dict with F-stat and p-value for each lag.
    """
    results = {}
    for lag in range(1, max_lag + 1):
        # Build lag matrix
        data = pd.DataFrame({"y": y})
        for i in range(1, lag + 1):
            data[f"y_lag{i}"] = y.shift(i)
            data[f"x_lag{i}"] = x.shift(i)
        data = data.dropna()

        n = len(data)
        y_vec = data["y"].values

        # Restricted model: y ~ lagged y only
        X_r = np.column_stack([data[f"y_lag{i}"].values for i in range(1, lag + 1)])
        X_r = np.column_stack([np.ones(n), X_r])

        # Unrestricted model: y ~ lagged y + lagged x
        X_u = np.column_stack([
            np.ones(n),
            *[data[f"y_lag{i}"].values for i in range(1, lag + 1)],
            *[data[f"x_lag{i}"].values for i in range(1, lag + 1)],
        ])

        # OLS
        try:
            beta_r = np.linalg.lstsq(X_r, y_vec, rcond=None)[0]
            beta_u = np.linalg.lstsq(X_u, y_vec, rcond=None)[0]
        except np.linalg.LinAlgError:
            results[lag] = {"F": np.nan, "p": np.nan}
            continue

        ssr_r = np.sum((y_vec - X_r @ beta_r) ** 2)
        ssr_u = np.sum((y_vec - X_u @ beta_u) ** 2)

        k = lag  # number of restrictions
        df_u = n - X_u.shape[1]

        if df_u <= 0 or ssr_u <= 0:
            results[lag] = {"F": np.nan, "p": np.nan}
            continue

        F = ((ssr_r - ssr_u) / k) / (ssr_u / df_u)
        p = 1 - stats.f.cdf(F, k, df_u)
        results[lag] = {"F": round(F, 4), "p": round(p, 6)}

    return results


# Test: SPY RV5 → target RV5
targets = ["GLD", "TLT", "QQQ"]
granger_results = {}

for target in targets:
    spy_rv5 = rv["SPY_rv5"].loc[rv.index]
    tgt_rv5 = rv[f"{target}_rv5"].loc[rv.index]
    gc = granger_causality_manual(tgt_rv5, spy_rv5, GRANGER_MAX_LAG)
    granger_results[target] = gc

    print(f"\n  SPY_rv5 → {target}_rv5 Granger Causality:")
    print(f"  {'Lag':>4s}  {'F-stat':>8s}  {'p-value':>10s}  {'Sig':>4s}")
    print(f"  {'----':>4s}  {'------':>8s}  {'-------':>10s}  {'---':>4s}")
    for lag, res in gc.items():
        sig = "***" if res["p"] < 0.001 else "**" if res["p"] < 0.01 else "*" if res["p"] < 0.05 else ""
        print(f"  {lag:4d}  {res['F']:8.2f}  {res['p']:10.6f}  {sig:>4s}")

# Also test reverse direction
print("\n  --- Reverse direction tests ---")
reverse_results = {}
for target in targets:
    tgt_rv5 = rv[f"{target}_rv5"].loc[rv.index]
    spy_rv5 = rv["SPY_rv5"].loc[rv.index]
    gc_rev = granger_causality_manual(spy_rv5, tgt_rv5, GRANGER_MAX_LAG)
    reverse_results[target] = gc_rev

    # Show only lag-1 for brevity
    res = gc_rev[1]
    sig = "***" if res["p"] < 0.001 else "**" if res["p"] < 0.01 else "*" if res["p"] < 0.05 else ""
    print(f"  {target}_rv5 → SPY_rv5 (lag=1): F={res['F']:.2f}, p={res['p']:.6f} {sig}")

print()


# ======================================================================
# 4. PARTIAL CORRELATION (controlling for own-asset vol)
# ======================================================================
print("=" * 60)
print("PHASE 4: Partial Correlation — SPY Vol Shock → Future Vol")
print("=" * 60)
print("  Control: own-asset rv22 (so we test incremental SPY info)")
print()


def partial_correlation(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple:
    """Partial correlation of x,y controlling for z. Returns (r_partial, p_value)."""
    # Regress x on z, y on z, correlate residuals
    mask = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
    x, y, z = x[mask], y[mask], z[mask]

    n = len(x)
    if n < 10:
        return np.nan, np.nan

    # Residualize
    z_aug = np.column_stack([np.ones(n), z])
    try:
        bx = np.linalg.lstsq(z_aug, x, rcond=None)[0]
        by = np.linalg.lstsq(z_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.nan, np.nan

    res_x = x - z_aug @ bx
    res_y = y - z_aug @ by

    r, p = stats.pearsonr(res_x, res_y)
    return r, p


# For each target, test: corr(SPY_vol_shock_t, target_rv5_{t+lag}) | target_rv22_t
partial_results = {}
for target in targets:
    partial_results[target] = {}
    print(f"  SPY vol shock → {target} RV5 (partial, controlling {target}_rv22):")
    print(f"  {'Lag':>4s}  {'r_partial':>10s}  {'p-value':>10s}  {'N':>6s}  {'Sig':>4s}")
    print(f"  {'----':>4s}  {'--------':>10s}  {'-------':>10s}  {'---':>6s}  {'---':>4s}")
    for lag in range(1, GRANGER_MAX_LAG + 1):
        x = rv["SPY_vol_shock"].values[:-lag]
        y = rv[f"{target}_rv5"].values[lag:]
        z = rv[f"{target}_rv22"].values[:-lag]

        r, p = partial_correlation(x, y, z)
        n = len(x)
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"  {lag:4d}  {r:10.4f}  {p:10.6f}  {n:6d}  {sig:>4s}")
        partial_results[target][lag] = {"r": round(r, 4), "p": round(p, 6), "n": n}
    print()


# ======================================================================
# 5. CONTAGION REGIME ANALYSIS
# ======================================================================
print("=" * 60)
print("PHASE 5: Contagion Regime Analysis")
print("=" * 60)
print("  Q: When SPY vol spikes, how do GLD/TLT behave in the NEXT 1-5 days?")
print()

# Define regimes based on SPY vol shock Z-score
rv["regime"] = "normal"
rv.loc[rv["SPY_vol_shock_z"] > VOL_SHOCK_THRESHOLD, "regime"] = "shock_up"
rv.loc[rv["SPY_vol_shock_z"] < -VOL_SHOCK_THRESHOLD, "regime"] = "shock_down"

regime_counts = rv["regime"].value_counts()
print(f"  Regime counts:")
for regime, count in regime_counts.items():
    print(f"    {regime:12s}: {count:5d} days ({count/len(rv)*100:.1f}%)")
print()

# Forward returns conditional on SPY vol shock regime
print(f"  Forward annualized vol by regime (next 5 trading days):")
print(f"  {'Asset':>6s}  {'Normal':>10s}  {'Shock Up':>10s}  {'Shock Down':>10s}  {'Ratio Up/Norm':>14s}")
print(f"  {'-----':>6s}  {'------':>10s}  {'--------':>10s}  {'----------':>10s}  {'-------------':>14s}")

for target in TICKERS:
    # Forward 5-day realized vol
    fwd_rv5 = returns[target].shift(-1).rolling(5).std().shift(-4) * np.sqrt(252)
    fwd_rv5 = fwd_rv5.reindex(rv.index)

    vols = {}
    for regime in ["normal", "shock_up", "shock_down"]:
        mask = rv["regime"] == regime
        vals = fwd_rv5[mask].dropna()
        vols[regime] = vals.mean() if len(vals) > 0 else np.nan

    ratio = vols["shock_up"] / vols["normal"] if vols["normal"] > 0 else np.nan
    print(f"  {target:>6s}  {vols['normal']:10.2%}  {vols['shock_up']:10.2%}  {vols['shock_down']:10.2%}  {ratio:14.2f}x")

print()

# SPY drawdown analysis
print(f"  Average NEXT-day returns by SPY drawdown status:")
print(f"  {'Asset':>6s}  {'No DD':>10s}  {'In DD':>10s}  {'Diff':>10s}  {'t-stat':>8s}  {'p':>8s}")
print(f"  {'-----':>6s}  {'-----':>10s}  {'-----':>10s}  {'----':>10s}  {'------':>8s}  {'---':>8s}")

for target in TICKERS:
    # Next-day return
    fwd_ret = returns[target].shift(-1).reindex(rv.index)

    in_dd = fwd_ret[rv["SPY_in_drawdown"] == 1].dropna()
    no_dd = fwd_ret[rv["SPY_in_drawdown"] == 0].dropna()

    if len(in_dd) > 5 and len(no_dd) > 5:
        diff = in_dd.mean() - no_dd.mean()
        t_stat, p_val = stats.ttest_ind(in_dd, no_dd)
        print(f"  {target:>6s}  {no_dd.mean()*252:10.2%}  {in_dd.mean()*252:10.2%}  {diff*252:10.2%}  {t_stat:8.3f}  {p_val:8.4f}")
    else:
        print(f"  {target:>6s}  insufficient data")

print()


# ======================================================================
# 6. CORRELATION BREAKDOWN ANALYSIS
# ======================================================================
print("=" * 60)
print("PHASE 6: Correlation Breakdown During SPY Stress")
print("=" * 60)

# How does SPY-GLD correlation change when SPY vol is high?
print(f"  SPY-GLD correlation by SPY vol regime:")
for regime in ["normal", "shock_up", "shock_down"]:
    mask = rv["regime"] == regime
    if mask.sum() > WINDOW_CORR:
        corrs = rv.loc[mask, "SPY_GLD_corr66"]
        print(f"    {regime:12s}: median={corrs.median():.3f}, mean={corrs.mean():.3f}, "
              f"std={corrs.std():.3f}, n={mask.sum()}")

print()
print(f"  SPY-TLT correlation by SPY vol regime:")
for regime in ["normal", "shock_up", "shock_down"]:
    mask = rv["regime"] == regime
    if mask.sum() > WINDOW_CORR:
        corrs = rv.loc[mask, "SPY_TLT_corr66"]
        print(f"    {regime:12s}: median={corrs.median():.3f}, mean={corrs.mean():.3f}, "
              f"std={corrs.std():.3f}, n={mask.sum()}")

print()


# ======================================================================
# 7. CONTAGION-BASED VT OVERLAY — 5-PERIOD CROSS-OOS
# ======================================================================
print("=" * 60)
print("PHASE 7: Contagion-Based VT Overlay — 5-Period Cross-OOS")
print("=" * 60)
print("  Baseline: 50/50 SPY/GLD static (monthly rebalance)")
print("  Strategy 1: Contagion Vol Shift — when SPY vol shock Z > 2, shift to 30/70 SPY/GLD")
print("  Strategy 2: Drawdown Shift — when SPY in drawdown, shift to 40/60 SPY/GLD")
print("  Strategy 3: Combined — vol shock OR drawdown triggers shift")
print()


def compute_portfolio_metrics(returns_series: pd.Series) -> dict:
    """Compute Sharpe, MDD, Calmar, Sortino for a return series."""
    ann_ret = returns_series.mean() * 252
    ann_vol = returns_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    cum = (1 + returns_series).cumprod()
    rolling_max = cum.cummax()
    drawdowns = cum / rolling_max - 1
    mdd = drawdowns.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0.0

    downside = returns_series[returns_series < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0.0

    return {
        "ann_ret": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "n_days": len(returns_series),
    }


def run_strategy(
    ret_df: pd.DataFrame,
    rv_df: pd.DataFrame,
    oos_start: str,
    oos_end: str,
    strategy: str = "baseline",
) -> dict:
    """
    Run a strategy over a given OOS period.
    Uses LAGGED signals (t-1 features → t weights) to avoid look-ahead.
    Monthly rebalance.
    """
    mask = (ret_df.index >= oos_start) & (ret_df.index <= oos_end)
    oos_ret = ret_df.loc[mask, ["SPY", "GLD"]].copy()
    oos_rv = rv_df.reindex(oos_ret.index)

    if len(oos_ret) < 20:
        return {"sharpe": np.nan, "mdd": np.nan, "ann_ret": np.nan, "n_days": 0}

    # Compute portfolio returns with lagged signals
    port_returns = []

    for i in range(1, len(oos_ret)):
        # Use PREVIOUS day's features for signal (lagged)
        prev_idx = oos_ret.index[i - 1]

        if strategy == "baseline":
            w_spy, w_gld = 0.50, 0.50
        elif strategy == "vol_shift":
            # When SPY vol shock Z > threshold, shift to defensive
            z = oos_rv.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv.index else 0
            if not np.isnan(z) and z > VOL_SHOCK_THRESHOLD:
                w_spy, w_gld = 0.30, 0.70
            else:
                w_spy, w_gld = 0.50, 0.50
        elif strategy == "drawdown_shift":
            # When SPY in drawdown, shift defensive
            dd = oos_rv.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv.index else 0
            if not np.isnan(dd) and dd == 1:
                w_spy, w_gld = 0.40, 0.60
            else:
                w_spy, w_gld = 0.50, 0.50
        elif strategy == "combined":
            z = oos_rv.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv.index else 0
            dd = oos_rv.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv.index else 0
            if (not np.isnan(z) and z > VOL_SHOCK_THRESHOLD) or (not np.isnan(dd) and dd == 1):
                w_spy, w_gld = 0.35, 0.65
            else:
                w_spy, w_gld = 0.50, 0.50
        else:
            w_spy, w_gld = 0.50, 0.50

        curr_idx = oos_ret.index[i]
        r = w_spy * oos_ret.loc[curr_idx, "SPY"] + w_gld * oos_ret.loc[curr_idx, "GLD"]
        port_returns.append(r)

    port_series = pd.Series(port_returns, index=oos_ret.index[1:])
    metrics = compute_portfolio_metrics(port_series)

    # Count regime shifts
    if strategy != "baseline":
        shifts = 0
        for i in range(1, len(oos_ret)):
            prev_idx = oos_ret.index[i - 1]
            if strategy == "vol_shift":
                z = oos_rv.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv.index else 0
                if not np.isnan(z) and z > VOL_SHOCK_THRESHOLD:
                    shifts += 1
            elif strategy == "drawdown_shift":
                dd = oos_rv.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv.index else 0
                if not np.isnan(dd) and dd == 1:
                    shifts += 1
            elif strategy == "combined":
                z = oos_rv.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv.index else 0
                dd = oos_rv.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv.index else 0
                if (not np.isnan(z) and z > VOL_SHOCK_THRESHOLD) or (not np.isnan(dd) and dd == 1):
                    shifts += 1
        metrics["shift_days"] = shifts
        metrics["shift_pct"] = round(shifts / len(port_returns) * 100, 1)
    else:
        metrics["shift_days"] = 0
        metrics["shift_pct"] = 0.0

    return metrics


# Run all strategies across all OOS periods
strategies = ["baseline", "vol_shift", "drawdown_shift", "combined"]
strategy_names = {
    "baseline": "50/50 Static",
    "vol_shift": "Vol Shock Shift (30/70)",
    "drawdown_shift": "Drawdown Shift (40/60)",
    "combined": "Combined (35/65)",
}

all_results = {}

for strat in strategies:
    all_results[strat] = {}
    for oos_start, oos_end in OOS_PERIODS:
        result = run_strategy(returns, rv, oos_start, oos_end, strat)
        all_results[strat][f"{oos_start[:4]}-{oos_end[:4]}"] = result

# Print results table
print(f"\n  {'Strategy':30s}", end="")
for oos_start, oos_end in OOS_PERIODS:
    period = f"{oos_start[:4]}-{oos_end[:4]}"
    print(f"  {period:>12s}", end="")
print(f"  {'Mean':>8s}")

print(f"  {'SHARPE':30s}")
for strat in strategies:
    print(f"  {strategy_names[strat]:30s}", end="")
    sharpes = []
    for oos_start, oos_end in OOS_PERIODS:
        period = f"{oos_start[:4]}-{oos_end[:4]}"
        s = all_results[strat][period]["sharpe"]
        sharpes.append(s)
        print(f"  {s:12.3f}", end="")
    print(f"  {np.nanmean(sharpes):8.3f}")

print()
print(f"  {'MDD':30s}")
for strat in strategies:
    print(f"  {strategy_names[strat]:30s}", end="")
    mdds = []
    for oos_start, oos_end in OOS_PERIODS:
        period = f"{oos_start[:4]}-{oos_end[:4]}"
        m = all_results[strat][period]["mdd"]
        mdds.append(m)
        print(f"  {m:11.1%}", end=" ")
    print(f"  {np.nanmean(mdds):7.1%}")

print()
print(f"  {'SORTINO':30s}")
for strat in strategies:
    print(f"  {strategy_names[strat]:30s}", end="")
    sortinos = []
    for oos_start, oos_end in OOS_PERIODS:
        period = f"{oos_start[:4]}-{oos_end[:4]}"
        s = all_results[strat][period]["sortino"]
        sortinos.append(s)
        print(f"  {s:12.3f}", end="")
    print(f"  {np.nanmean(sortinos):8.3f}")

print()
print(f"  {'SHIFT DAYS (%)':30s}")
for strat in strategies:
    if strat == "baseline":
        continue
    print(f"  {strategy_names[strat]:30s}", end="")
    for oos_start, oos_end in OOS_PERIODS:
        period = f"{oos_start[:4]}-{oos_end[:4]}"
        pct = all_results[strat][period]["shift_pct"]
        print(f"  {pct:10.1f}%", end=" ")
    print()

print()


# ======================================================================
# 8. STATISTICAL SIGNIFICANCE — DM TEST
# ======================================================================
print("=" * 60)
print("PHASE 8: Diebold-Mariano Test vs Baseline")
print("=" * 60)
print("  H0: Strategy and baseline have equal Sharpe")
print()

# For each OOS period, compute daily return difference and test
for strat in strategies:
    if strat == "baseline":
        continue

    print(f"  {strategy_names[strat]}:")
    wins = 0
    total_diff_returns = []

    for oos_start, oos_end in OOS_PERIODS:
        mask = (returns.index >= oos_start) & (returns.index <= oos_end)
        oos_ret = returns.loc[mask, ["SPY", "GLD"]].copy()
        oos_rv_data = rv.reindex(oos_ret.index)

        if len(oos_ret) < 20:
            continue

        baseline_rets = []
        strat_rets = []

        for i in range(1, len(oos_ret)):
            prev_idx = oos_ret.index[i - 1]
            curr_idx = oos_ret.index[i]

            # Baseline
            r_base = 0.50 * oos_ret.loc[curr_idx, "SPY"] + 0.50 * oos_ret.loc[curr_idx, "GLD"]
            baseline_rets.append(r_base)

            # Strategy weights
            if strat == "vol_shift":
                z = oos_rv_data.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv_data.index else 0
                if not np.isnan(z) and z > VOL_SHOCK_THRESHOLD:
                    w_spy, w_gld = 0.30, 0.70
                else:
                    w_spy, w_gld = 0.50, 0.50
            elif strat == "drawdown_shift":
                dd = oos_rv_data.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv_data.index else 0
                if not np.isnan(dd) and dd == 1:
                    w_spy, w_gld = 0.40, 0.60
                else:
                    w_spy, w_gld = 0.50, 0.50
            elif strat == "combined":
                z = oos_rv_data.loc[prev_idx, "SPY_vol_shock_z"] if prev_idx in oos_rv_data.index else 0
                dd = oos_rv_data.loc[prev_idx, "SPY_in_drawdown"] if prev_idx in oos_rv_data.index else 0
                if (not np.isnan(z) and z > VOL_SHOCK_THRESHOLD) or (not np.isnan(dd) and dd == 1):
                    w_spy, w_gld = 0.35, 0.65
                else:
                    w_spy, w_gld = 0.50, 0.50
            else:
                w_spy, w_gld = 0.50, 0.50

            r_strat = w_spy * oos_ret.loc[curr_idx, "SPY"] + w_gld * oos_ret.loc[curr_idx, "GLD"]
            strat_rets.append(r_strat)

        diff = np.array(strat_rets) - np.array(baseline_rets)
        total_diff_returns.extend(diff.tolist())

        period = f"{oos_start[:4]}-{oos_end[:4]}"
        if len(diff) > 10:
            t_stat = np.mean(diff) / (np.std(diff, ddof=1) / np.sqrt(len(diff)))
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(diff) - 1))
            ann_diff = np.mean(diff) * 252
            sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            if np.mean(diff) > 0:
                wins += 1
            print(f"    {period}: diff={ann_diff:+.2%}/yr, t={t_stat:.3f}, p={p_val:.4f} {sig}")

    # Overall
    if total_diff_returns:
        total_diff = np.array(total_diff_returns)
        t_all = np.mean(total_diff) / (np.std(total_diff, ddof=1) / np.sqrt(len(total_diff)))
        p_all = 2 * (1 - stats.t.cdf(abs(t_all), len(total_diff) - 1))
        ann_all = np.mean(total_diff) * 252
        print(f"    OVERALL: diff={ann_all:+.2%}/yr, t={t_all:.3f}, p={p_all:.4f}, wins={wins}/5")
    print()


# ======================================================================
# 9. CONTAGION ASYMMETRY TEST
# ======================================================================
print("=" * 60)
print("PHASE 9: Contagion Asymmetry — Does Direction Matter?")
print("=" * 60)
print("  Q: Is SPY→GLD contagion stronger for negative vs positive shocks?")
print()

for target in ["GLD", "TLT"]:
    print(f"  SPY → {target} contagion asymmetry:")

    # Next-day target vol following SPY positive vs negative shocks
    spy_shock_pos = rv["SPY_vol_shock_z"] > 1.0
    spy_shock_neg = rv["SPY_vol_shock_z"] < -1.0
    spy_normal = (~spy_shock_pos) & (~spy_shock_neg)

    tgt_fwd_rv = rv[f"{target}_rv5"].shift(-1).reindex(rv.index)

    for label, mask in [("Normal", spy_normal), ("SPY vol spike (+1z)", spy_shock_pos),
                        ("SPY vol drop (-1z)", spy_shock_neg)]:
        vals = tgt_fwd_rv[mask].dropna()
        if len(vals) > 10:
            print(f"    {label:25s}: mean_rv5={vals.mean():.4f}, median={vals.median():.4f}, n={len(vals)}")

    # Test: is the difference significant?
    pos_vals = tgt_fwd_rv[spy_shock_pos].dropna()
    neg_vals = tgt_fwd_rv[spy_shock_neg].dropna()
    norm_vals = tgt_fwd_rv[spy_normal].dropna()

    if len(pos_vals) > 10 and len(norm_vals) > 10:
        t_stat, p_val = stats.ttest_ind(pos_vals, norm_vals)
        print(f"    SPY spike vs normal: t={t_stat:.3f}, p={p_val:.4f}")

    if len(pos_vals) > 10 and len(neg_vals) > 10:
        t_stat, p_val = stats.ttest_ind(pos_vals, neg_vals)
        print(f"    SPY spike vs drop: t={t_stat:.3f}, p={p_val:.4f}")
    print()


# ======================================================================
# 10. SUMMARY & CONCLUSIONS
# ======================================================================
print("=" * 80)
print("K218 SUMMARY — Cross-Asset Contagion Timing")
print("=" * 80)

# Collect key findings
granger_sig = {}
for target in targets:
    sig_lags = [lag for lag, res in granger_results[target].items() if res["p"] < 0.05]
    granger_sig[target] = sig_lags

print(f"\n  1. GRANGER CAUSALITY (SPY vol → target vol):")
for target in targets:
    if granger_sig[target]:
        print(f"     SPY → {target}: SIGNIFICANT at lags {granger_sig[target]}")
    else:
        print(f"     SPY → {target}: NOT significant at any lag 1-{GRANGER_MAX_LAG}")

print(f"\n  2. PARTIAL CORRELATION (controlling own vol):")
for target in targets:
    res_lag1 = partial_results[target][1]
    sig_str = f"r={res_lag1['r']:.4f}, p={res_lag1['p']:.4f}"
    significant = res_lag1['p'] < 0.05
    print(f"     SPY shock → {target} (lag=1): {sig_str} {'SIGNIFICANT' if significant else 'NOT significant'}")

# Strategy comparison
print(f"\n  3. STRATEGY COMPARISON (mean across 5 OOS periods):")
for strat in strategies:
    sharpes = [all_results[strat][f"{s[:4]}-{e[:4]}"]["sharpe"] for s, e in OOS_PERIODS]
    mdds = [all_results[strat][f"{s[:4]}-{e[:4]}"]["mdd"] for s, e in OOS_PERIODS]
    print(f"     {strategy_names[strat]:30s}: Sharpe={np.nanmean(sharpes):.3f}, MDD={np.nanmean(mdds):.1%}")

# Verdict
baseline_sharpes = [all_results["baseline"][f"{s[:4]}-{e[:4]}"]["sharpe"] for s, e in OOS_PERIODS]
best_strat = None
best_improvement = 0

for strat in ["vol_shift", "drawdown_shift", "combined"]:
    strat_sharpes = [all_results[strat][f"{s[:4]}-{e[:4]}"]["sharpe"] for s, e in OOS_PERIODS]
    improvement = np.nanmean(strat_sharpes) - np.nanmean(baseline_sharpes)
    if improvement > best_improvement:
        best_improvement = improvement
        best_strat = strat

print(f"\n  4. VERDICT:")
if best_strat and best_improvement > 0.05:
    print(f"     Best overlay: {strategy_names[best_strat]} (+{best_improvement:.3f} Sharpe)")
    print(f"     But must pass Harvey threshold (t > 3.0) for credible claim")
else:
    print(f"     Contagion timing does NOT meaningfully improve 50/50 SPY/GLD")
    print(f"     Consistent with K163 (GLD zero contagion from SPY)")
    print(f"     50/50 static remains the irreducible kernel")

print()


# ======================================================================
# 11. SAVE RESULTS
# ======================================================================
results_file = Path(__file__).resolve().parent / "k218_contagion_timing_results.json"

save_data = {
    "experiment": "K218",
    "title": "Cross-Asset Contagion Timing",
    "hypothesis": "SPY vol shocks can predict and time GLD/TLT vol for portfolio overlay",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "tickers": TICKERS,
        "data_range": f"{DATA_START} to {DATA_END}",
        "n_obs": len(returns),
        "n_features": len(rv),
    },
    "granger_causality": {
        target: {
            str(lag): res for lag, res in granger_results[target].items()
        }
        for target in targets
    },
    "partial_correlations": {
        target: {
            str(lag): res for lag, res in partial_results[target].items()
        }
        for target in targets
    },
    "regime_analysis": {
        "regime_counts": regime_counts.to_dict(),
    },
    "strategy_results": {
        strat: {
            period: all_results[strat][period]
            for period in [f"{s[:4]}-{e[:4]}" for s, e in OOS_PERIODS]
        }
        for strat in strategies
    },
    "summary": {
        "granger_significant": {t: granger_sig[t] for t in targets},
        "best_overlay": strategy_names.get(best_strat, "none"),
        "best_improvement_sharpe": round(best_improvement, 4) if best_strat else 0,
        "baseline_mean_sharpe": round(np.nanmean(baseline_sharpes), 4),
        "conclusion": (
            f"Contagion timing overlay improves Sharpe by {best_improvement:.3f}"
            if best_strat and best_improvement > 0.05
            else "Contagion timing does NOT meaningfully improve 50/50 SPY/GLD"
        ),
    },
}

with open(results_file, "w") as f:
    json.dump(save_data, f, indent=2, default=str)
print(f"  Results saved to: {results_file}")
print()
print("K218 complete.")
