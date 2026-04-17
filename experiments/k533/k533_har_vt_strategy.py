#!/usr/bin/env python3
"""K533: HAR-Based Volatility Targeting Strategy
==================================================

Research question: Can K530's HAR breakthrough (DM=-15.45 vs GJR-GARCH)
translate to a better TRADING strategy?  Tests the "prediction ≠ application"
principle confirmed 4× (K440/K467/K470/K488) and the 12/VIX irreducible
kernel (6× confirmed: K440/K470/K488/K503/K504/K524).

Key insight:
  - 12/VIX uses FORWARD-LOOKING market-implied vol
  - HAR uses BACKWARD-LOOKING realized vol (|r_t| averages)
  - Better statistical prediction does NOT guarantee better economic outcomes

Strategies tested:
  1. Buy & Hold SPY (benchmark)
  2. Buy & Hold 50/50 SPY+GLD (benchmark)
  3. Standard 12/VIX VT (baseline strategy)
  4. HAR-ABS VT:  w = min(1, target_vol / σ_HAR_ABS)
  5. HAR-VIX VT:  w = min(1, target_vol / σ_HAR_VIX)  (HAR + VIX regressor)
  6. Hybrid 50/50: w = 0.5 * w_VIX + 0.5 * w_HAR

Evaluation (ECONOMIC, not just statistical):
  - Sharpe ratio (Harvey t>3.0 for significance)
  - MDD (maximum drawdown)
  - Calmar ratio (CAGR / MDD)
  - Net Sharpe after TX costs (0.1% per trade)
  - Turnover (rebalancing frequency impact)
  - Cross-OOS: 3 periods (2020-2021, 2021-2022, 2023-2024)

References:
  - Corsi (2009, JFE): Original HAR-RV model
  - Moreira & Muir (2017, JoF 72(4)): Volatility-Managed Portfolios
  - K530: HAR-ABS DM=-15.45 vs GJR, HAR-VIX best (QLIKE=0.463)
  - K470: HAR log-range VT — doesn't pass Harvey t>3.0
  - K440/K488/K503/K504/K524: 12/VIX irreducible kernel

Data: yfinance (SPY, GLD, ^VIX)
Asset: SPY (primary)
Author: [Proposed: User, Executed: Claude]

Usage:
    uv run python experiments/k533_har_vt_strategy.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants & Configuration
# ============================================================
TARGET_VOL = 0.12  # 12% annualized target volatility
TX_COST = 0.001    # 0.1% one-way transaction cost
HAR_WINDOW = 500   # HAR estimation window (rolling OLS)
ANNUALIZE = np.sqrt(252)
OOS_PERIODS = {
    "OOS1_2020_2021": ("2020-01-01", "2021-12-31"),
    "OOS2_2021_2022": ("2021-01-01", "2022-12-31"),
    "OOS3_2023_2024": ("2023-01-01", "2024-12-31"),
}

# ============================================================
#  Utility Functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def sharpe_ratio(returns: np.ndarray) -> float:
    """Annualized Sharpe ratio (excess return / vol)."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * ANNUALIZE)


def max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown from cumulative returns."""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(np.min(dd))


def cagr(returns: np.ndarray) -> float:
    """Compound annual growth rate."""
    n_years = len(returns) / 252
    if n_years <= 0:
        return 0.0
    total = np.prod(1 + returns)
    if total <= 0:
        return -1.0
    return float(total ** (1 / n_years) - 1)


def calmar_ratio(returns: np.ndarray) -> float:
    """Calmar ratio = CAGR / |MDD|."""
    mdd = max_drawdown(returns)
    c = cagr(returns)
    if abs(mdd) < 1e-10:
        return 0.0
    return float(c / abs(mdd))


def sortino_ratio(returns: np.ndarray) -> float:
    """Annualized Sortino ratio."""
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0
    downside_std = np.std(downside)
    if downside_std == 0:
        return 0.0
    return float(np.mean(returns) / downside_std * ANNUALIZE)


def turnover(weights: np.ndarray) -> float:
    """Average daily turnover = mean(|Δw|)."""
    dw = np.diff(weights)
    return float(np.mean(np.abs(dw)))


def net_sharpe_after_tx(returns: np.ndarray, weights: np.ndarray, tx_cost: float) -> float:
    """Sharpe after deducting transaction costs from turnover."""
    dw = np.abs(np.diff(weights))
    # costs apply to each weight change (both buy and sell)
    tx_drag = dw * tx_cost  # daily TX cost
    # Align: returns[1:] corresponds to dw
    net_ret = returns[1:] - tx_drag
    return sharpe_ratio(net_ret)


def dm_test_sharpe(returns1: np.ndarray, returns2: np.ndarray) -> tuple:
    """Diebold-Mariano style test on utility/return differences.
    Tests H0: E[r1 - r2] = 0.  Positive DM → model1 better.
    """
    d = returns1 - returns2
    T = len(d)
    if T < 10:
        return (0.0, 1.0)
    d_bar = np.mean(d)
    se = np.std(d, ddof=1) / np.sqrt(T)
    if se == 0:
        return (0.0, 1.0)
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=T - 1))
    return (float(t_stat), float(p_val))


# ============================================================
#  HAR Feature Construction (from K530)
# ============================================================

def build_har_features(log_returns: np.ndarray, vix_daily: np.ndarray = None):
    """Build HAR features: RV1, RV5, RV22 (absolute return proxies).

    Returns dict with arrays of same length as log_returns.
    """
    abs_r = np.abs(log_returns)
    n = len(abs_r)

    rv1 = abs_r.copy()
    rv5 = pd.Series(abs_r).rolling(5).mean().values
    rv22 = pd.Series(abs_r).rolling(22).mean().values

    result = {
        "rv1": rv1,
        "rv5": rv5,
        "rv22": rv22,
    }

    if vix_daily is not None:
        result["vix_daily"] = vix_daily / 100.0 / ANNUALIZE  # annualized → daily scale

    return result


def ols_fit(X: np.ndarray, y: np.ndarray):
    """OLS with intercept. Returns coefficients [intercept, β1, β2, ...]."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def ols_predict(X_new: np.ndarray, beta: np.ndarray) -> float:
    """Predict with OLS coefficients."""
    x_aug = np.concatenate([[1.0], X_new])
    return max(float(np.dot(x_aug, beta)), 1e-10)


# ============================================================
#  Strategy Weight Computation
# ============================================================

def compute_vix_weights(vix_close: np.ndarray) -> np.ndarray:
    """Standard 12/VIX position sizing.

    w = min(1, 12 / VIX_t)
    This is the forward-looking benchmark.
    """
    weights = np.minimum(1.0, 12.0 / vix_close)
    weights = np.clip(weights, 0.0, 1.0)
    return weights


def compute_har_abs_weights(log_returns: np.ndarray, window: int = 500) -> np.ndarray:
    """HAR-ABS based VT: rolling OLS, annualize forecast, compute weight.

    σ_hat = HAR forecast (daily) × √252  → annualized
    w = min(1, target_vol / σ_hat)
    """
    n = len(log_returns)
    features = build_har_features(log_returns)
    rv1, rv5, rv22 = features["rv1"], features["rv5"], features["rv22"]

    weights = np.full(n, 1.0)  # default fully invested

    for t in range(window, n):
        # Training window
        start = t - window

        # Build training data (skip NaN from rolling)
        train_X = []
        train_y = []
        for i in range(start, t):
            if np.isnan(rv5[i]) or np.isnan(rv22[i]):
                continue
            if i + 1 >= n:
                continue
            train_X.append([rv1[i], rv5[i], rv22[i]])
            train_y.append(np.abs(log_returns[i + 1]))  # next-day target

        if len(train_X) < 50:
            continue

        train_X = np.array(train_X)
        train_y = np.array(train_y)

        # Fit OLS
        beta = ols_fit(train_X, train_y)

        # Predict next-day |r|
        x_new = np.array([rv1[t], rv5[t], rv22[t]])
        if np.any(np.isnan(x_new)):
            continue
        pred_abs = ols_predict(x_new, beta)

        # Annualize: daily |r| → annualized σ
        # E[|r|] ≈ σ_daily × √(2/π), so σ_daily ≈ E[|r|] × √(π/2)
        sigma_daily = pred_abs * np.sqrt(np.pi / 2)
        sigma_annual = sigma_daily * ANNUALIZE

        if sigma_annual > 0.01:  # sanity floor
            weights[t] = min(1.0, TARGET_VOL / sigma_annual)

    return np.clip(weights, 0.0, 1.0)


def compute_har_vix_weights(log_returns: np.ndarray, vix_close: np.ndarray,
                             window: int = 500) -> np.ndarray:
    """HAR-VIX based VT: HAR-ABS + VIX as additional regressor.

    Combines backward-looking HAR features with forward-looking VIX.
    """
    n = len(log_returns)
    features = build_har_features(log_returns, vix_daily=vix_close)
    rv1, rv5, rv22 = features["rv1"], features["rv5"], features["rv22"]
    vix_d = features["vix_daily"]

    weights = np.full(n, 1.0)

    for t in range(window, n):
        start = t - window

        train_X = []
        train_y = []
        for i in range(start, t):
            if np.isnan(rv5[i]) or np.isnan(rv22[i]) or np.isnan(vix_d[i]):
                continue
            if i + 1 >= n:
                continue
            train_X.append([rv1[i], rv5[i], rv22[i], vix_d[i]])
            train_y.append(np.abs(log_returns[i + 1]))

        if len(train_X) < 50:
            continue

        train_X = np.array(train_X)
        train_y = np.array(train_y)

        beta = ols_fit(train_X, train_y)

        x_new = np.array([rv1[t], rv5[t], rv22[t], vix_d[t]])
        if np.any(np.isnan(x_new)):
            continue
        pred_abs = ols_predict(x_new, beta)

        sigma_daily = pred_abs * np.sqrt(np.pi / 2)
        sigma_annual = sigma_daily * ANNUALIZE

        if sigma_annual > 0.01:
            weights[t] = min(1.0, TARGET_VOL / sigma_annual)

    return np.clip(weights, 0.0, 1.0)


def compute_hybrid_weights(vix_weights: np.ndarray, har_weights: np.ndarray) -> np.ndarray:
    """50/50 blend of VIX and HAR weights."""
    return np.clip(0.5 * vix_weights + 0.5 * har_weights, 0.0, 1.0)


# ============================================================
#  Strategy Backtester
# ============================================================

def backtest_strategy(spy_returns: np.ndarray, gld_returns: np.ndarray,
                      weights: np.ndarray, name: str,
                      spy_allocation: float = 0.5,
                      cash_rate: float = 0.0) -> dict:
    """Backtest a VT strategy on 50/50 SPY+GLD portfolio.

    portfolio_return = w * (spy_alloc * spy_r + gld_alloc * gld_r) + (1-w) * cash_rate
    """
    gld_alloc = 1.0 - spy_allocation
    risky_return = spy_allocation * spy_returns + gld_alloc * gld_returns
    strat_return = weights * risky_return + (1 - weights) * cash_rate / 252

    sr = sharpe_ratio(strat_return)
    mdd = max_drawdown(strat_return)
    cal = calmar_ratio(strat_return)
    sort = sortino_ratio(strat_return)
    to = turnover(weights)
    net_sr = net_sharpe_after_tx(strat_return, weights, TX_COST)
    c = cagr(strat_return)
    ann_vol = float(np.std(strat_return) * ANNUALIZE)
    avg_weight = float(np.mean(weights))

    return {
        "name": name,
        "sharpe": round(sr, 4),
        "net_sharpe": round(net_sr, 4),
        "cagr": round(c, 4),
        "ann_vol": round(ann_vol, 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 4),
        "sortino": round(sort, 4),
        "turnover": round(to, 6),
        "avg_weight": round(avg_weight, 4),
        "n_obs": len(strat_return),
        "returns": strat_return,
        "weights": weights,
    }


# ============================================================
#  Main Experiment
# ============================================================

def main():
    t_start = time.time()

    print_section("K533: HAR-Based Volatility Targeting Strategy")
    print("  Q: Can K530's HAR prediction breakthrough → better VT strategy?")
    print("  Key: prediction ≠ application (confirmed 4×)")
    print("  Benchmark: 12/VIX irreducible kernel (confirmed 6×)")

    # --------------------------------------------------------
    # 1. DATA COLLECTION
    # --------------------------------------------------------
    print_section("1. Data Collection", "-")

    spy = yf.download("SPY", start="2005-01-01", progress=False)
    gld = yf.download("GLD", start="2005-01-01", progress=False)
    vix = yf.download("^VIX", start="2005-01-01", progress=False)

    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Align
    common_idx = spy.index.intersection(gld.index).intersection(vix.index)
    spy = spy.loc[common_idx]
    gld = gld.loc[common_idx]
    vix = vix.loc[common_idx]

    print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
    print(f"  GLD: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} obs)")
    print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")

    # Compute returns
    spy_ret = np.log(spy["Close"] / spy["Close"].shift(1)).values.flatten()
    gld_ret = np.log(gld["Close"] / gld["Close"].shift(1)).values.flatten()
    vix_close = vix["Close"].values.flatten()
    dates = spy.index

    # Replace NaN at index 0
    spy_ret[0] = 0.0
    gld_ret[0] = 0.0

    n = len(spy_ret)
    print(f"  Total observations: {n}")

    # --------------------------------------------------------
    # 2. DESCRIPTIVE STATISTICS (Research Integrity Rule #5)
    # --------------------------------------------------------
    print_section("2. Descriptive Statistics", "-")

    for name, ret in [("SPY", spy_ret), ("GLD", gld_ret)]:
        valid = ret[~np.isnan(ret)]
        print(f"  {name}:")
        print(f"    Mean daily return: {np.mean(valid):.6f}")
        print(f"    Std:               {np.std(valid):.6f}")
        print(f"    Skewness:          {stats.skew(valid):.4f}")
        print(f"    Kurtosis:          {stats.kurtosis(valid):.4f}")
        print(f"    Min/Max:           {np.min(valid):.4f} / {np.max(valid):.4f}")

    print(f"  VIX:")
    print(f"    Mean:   {np.nanmean(vix_close):.2f}")
    print(f"    Median: {np.nanmedian(vix_close):.2f}")
    print(f"    Min/Max: {np.nanmin(vix_close):.2f} / {np.nanmax(vix_close):.2f}")

    # --------------------------------------------------------
    # 3. COMPUTE ALL STRATEGY WEIGHTS
    # --------------------------------------------------------
    print_section("3. Computing Strategy Weights", "-")

    # 3a. VIX-based weights (benchmark)
    print("  Computing 12/VIX weights...")
    w_vix = compute_vix_weights(vix_close)

    # 3b. HAR-ABS weights
    print("  Computing HAR-ABS weights (rolling OLS, window=500)...")
    w_har_abs = compute_har_abs_weights(spy_ret, window=HAR_WINDOW)

    # 3c. HAR-VIX weights
    print("  Computing HAR-VIX weights (rolling OLS + VIX regressor)...")
    w_har_vix = compute_har_vix_weights(spy_ret, vix_close, window=HAR_WINDOW)

    # 3d. Hybrid weights
    print("  Computing Hybrid 50/50 weights...")
    w_hybrid = compute_hybrid_weights(w_vix, w_har_abs)

    # Report weight statistics
    for name, w in [("12/VIX", w_vix), ("HAR-ABS", w_har_abs),
                     ("HAR-VIX", w_har_vix), ("Hybrid", w_hybrid)]:
        valid_w = w[~np.isnan(w)]
        print(f"  {name:12s}: mean={np.mean(valid_w):.4f}, "
              f"std={np.std(valid_w):.4f}, "
              f"min={np.min(valid_w):.4f}, max={np.max(valid_w):.4f}")

    # --------------------------------------------------------
    # 4. CROSS-OOS EVALUATION
    # --------------------------------------------------------
    print_section("4. Cross-OOS Evaluation (3 periods)", "-")

    all_results = {}

    for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
        print(f"\n  --- {period_name}: {oos_start} to {oos_end} ---")

        # Find OOS indices
        mask = (dates >= oos_start) & (dates <= oos_end)
        if mask.sum() == 0:
            print(f"    SKIP: no data in this period")
            continue

        oos_idx = np.where(mask)[0]
        oos_spy = spy_ret[oos_idx]
        oos_gld = gld_ret[oos_idx]

        # Buy & Hold SPY
        bh_spy = backtest_strategy(
            oos_spy, oos_gld, np.ones(len(oos_idx)), "B&H SPY",
            spy_allocation=1.0
        )

        # Buy & Hold 50/50
        bh_5050 = backtest_strategy(
            oos_spy, oos_gld, np.ones(len(oos_idx)), "B&H 50/50",
            spy_allocation=0.5
        )

        # 12/VIX VT
        vix_vt = backtest_strategy(
            oos_spy, oos_gld, w_vix[oos_idx], "12/VIX VT",
            spy_allocation=0.5
        )

        # HAR-ABS VT
        har_abs_vt = backtest_strategy(
            oos_spy, oos_gld, w_har_abs[oos_idx], "HAR-ABS VT",
            spy_allocation=0.5
        )

        # HAR-VIX VT
        har_vix_vt = backtest_strategy(
            oos_spy, oos_gld, w_har_vix[oos_idx], "HAR-VIX VT",
            spy_allocation=0.5
        )

        # Hybrid VT
        hybrid_vt = backtest_strategy(
            oos_spy, oos_gld, w_hybrid[oos_idx], "Hybrid VT",
            spy_allocation=0.5
        )

        strategies = [bh_spy, bh_5050, vix_vt, har_abs_vt, har_vix_vt, hybrid_vt]

        # Print results table
        print(f"\n  {'Strategy':15s} {'Sharpe':>8s} {'NetSR':>8s} {'CAGR':>8s} "
              f"{'MDD':>8s} {'Calmar':>8s} {'Turnover':>10s} {'AvgW':>6s}")
        print(f"  {'-'*75}")
        for s in strategies:
            print(f"  {s['name']:15s} {s['sharpe']:8.4f} {s['net_sharpe']:8.4f} "
                  f"{s['cagr']:8.4f} {s['mdd']:8.4f} {s['calmar']:8.4f} "
                  f"{s['turnover']:10.6f} {s['avg_weight']:6.4f}")

        # DM-style tests: HAR strategies vs 12/VIX
        print(f"\n  DM-style tests (return differences) vs 12/VIX:")
        vix_returns = vix_vt["returns"]
        for s in [har_abs_vt, har_vix_vt, hybrid_vt]:
            t_stat, p_val = dm_test_sharpe(s["returns"], vix_returns)
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else "NS"
            print(f"    {s['name']:15s} vs 12/VIX: t={t_stat:+.4f}, p={p_val:.4f} [{sig}]")

        # Store results (without returns/weights arrays for JSON)
        period_results = {}
        for s in strategies:
            period_results[s["name"]] = {k: v for k, v in s.items()
                                          if k not in ("returns", "weights")}

        # Add DM tests
        dm_tests = {}
        for s in [har_abs_vt, har_vix_vt, hybrid_vt]:
            t_stat, p_val = dm_test_sharpe(s["returns"], vix_returns)
            dm_tests[f"{s['name']}_vs_VIX"] = {
                "t_stat": round(t_stat, 4),
                "p_value": round(p_val, 4),
                "significant_at_5pct": p_val < 0.05,
                "better_model": s["name"] if t_stat > 0 else "12/VIX VT",
            }
        period_results["dm_tests"] = dm_tests

        all_results[period_name] = period_results

    # --------------------------------------------------------
    # 5. WEIGHT CORRELATION ANALYSIS
    # --------------------------------------------------------
    print_section("5. Weight Correlation Analysis", "-")

    # Use OOS3 period for correlation
    mask_oos3 = (dates >= "2023-01-01") & (dates <= "2024-12-31")
    oos3_idx = np.where(mask_oos3)[0]

    corr_data = {
        "12/VIX": w_vix[oos3_idx],
        "HAR-ABS": w_har_abs[oos3_idx],
        "HAR-VIX": w_har_vix[oos3_idx],
        "Hybrid": w_hybrid[oos3_idx],
    }

    print(f"\n  Weight correlations (OOS3: 2023-2024):")
    print(f"  {'':12s}", end="")
    for name in corr_data:
        print(f"  {name:10s}", end="")
    print()

    weight_corr = {}
    for n1, w1 in corr_data.items():
        print(f"  {n1:12s}", end="")
        for n2, w2 in corr_data.items():
            c = np.corrcoef(w1, w2)[0, 1]
            print(f"  {c:10.4f}", end="")
            weight_corr[f"{n1}_vs_{n2}"] = round(c, 4)
        print()

    # --------------------------------------------------------
    # 6. TURNOVER ANALYSIS
    # --------------------------------------------------------
    print_section("6. Turnover & Transaction Cost Analysis", "-")

    for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
        mask = (dates >= oos_start) & (dates <= oos_end)
        oos_idx = np.where(mask)[0]
        if len(oos_idx) == 0:
            continue

        print(f"\n  {period_name}:")
        for name, w in [("12/VIX", w_vix), ("HAR-ABS", w_har_abs),
                         ("HAR-VIX", w_har_vix), ("Hybrid", w_hybrid)]:
            w_oos = w[oos_idx]
            to = np.mean(np.abs(np.diff(w_oos)))
            daily_tx = to * TX_COST
            annual_tx = daily_tx * 252
            print(f"    {name:12s}: turnover={to:.6f}/day, "
                  f"annual TX drag={annual_tx:.4f} ({annual_tx*100:.2f}%)")

    # --------------------------------------------------------
    # 7. CROSS-OOS SUMMARY
    # --------------------------------------------------------
    print_section("7. Cross-OOS Summary", "-")

    # Aggregate Sharpe across periods
    strat_names = ["B&H SPY", "B&H 50/50", "12/VIX VT", "HAR-ABS VT", "HAR-VIX VT", "Hybrid VT"]

    cross_oos_summary = {}
    print(f"\n  {'Strategy':15s}", end="")
    for p in OOS_PERIODS:
        print(f"  {p[:10]:>12s}", end="")
    print(f"  {'Mean':>8s}  {'Std':>8s}  {'Wins':>5s}")
    print(f"  {'-'*80}")

    for sname in strat_names:
        sharpes = []
        print(f"  {sname:15s}", end="")
        for p in OOS_PERIODS:
            if p in all_results and sname in all_results[p]:
                sr = all_results[p][sname]["sharpe"]
                sharpes.append(sr)
                print(f"  {sr:12.4f}", end="")
            else:
                print(f"  {'N/A':>12s}", end="")

        if sharpes:
            mean_sr = np.mean(sharpes)
            std_sr = np.std(sharpes)
            cross_oos_summary[sname] = {
                "sharpes": [round(s, 4) for s in sharpes],
                "mean_sharpe": round(mean_sr, 4),
                "std_sharpe": round(std_sr, 4),
            }
            print(f"  {mean_sr:8.4f}  {std_sr:8.4f}", end="")

            # Count wins vs VIX
            if sname != "12/VIX VT" and "12/VIX VT" in cross_oos_summary:
                vix_sharpes = cross_oos_summary["12/VIX VT"]["sharpes"]
                wins = sum(1 for s, v in zip(sharpes, vix_sharpes) if s > v)
                print(f"  {wins}/{len(sharpes)}", end="")
                cross_oos_summary[sname]["wins_vs_vix"] = f"{wins}/{len(sharpes)}"
        print()

    # --------------------------------------------------------
    # 8. HARVEY (2016) SIGNIFICANCE TEST
    # --------------------------------------------------------
    print_section("8. Harvey (2016) Significance: t > 3.0?", "-")

    # For each period, test if any HAR strategy beats VIX significantly
    harvey_results = {}
    any_passes = False

    for period_name in OOS_PERIODS:
        if period_name not in all_results:
            continue
        dm = all_results[period_name].get("dm_tests", {})
        for test_name, test_result in dm.items():
            t_abs = abs(test_result["t_stat"])
            passes_harvey = t_abs > 3.0
            if passes_harvey:
                any_passes = True
            harvey_results[f"{period_name}_{test_name}"] = {
                "t_stat": test_result["t_stat"],
                "passes_harvey_3_0": passes_harvey,
            }
            status = "PASS ✓" if passes_harvey else "FAIL ✗"
            print(f"  {period_name} {test_name}: |t|={t_abs:.4f} → {status}")

    if not any_passes:
        print("\n  ⚠ NO HAR strategy passes Harvey t>3.0 threshold in ANY OOS period")
        print("    → Confirms: 12/VIX remains the irreducible kernel (#7)")

    # --------------------------------------------------------
    # 9. PREDICTION ≠ APPLICATION ANALYSIS
    # --------------------------------------------------------
    print_section("9. Prediction ≠ Application Analysis", "-")

    print("\n  K530 vol prediction ranking (QLIKE):")
    print("    1. HAR-VIX:   0.463  (best predictor)")
    print("    2. HAR-ABS:   0.490")
    print("    5. GJR-GARCH: 1.507")
    print("    → HAR-ABS DM=-15.45 vs GJR: statistically massive improvement")

    print("\n  K533 VT strategy ranking (mean Sharpe across 3 OOS):")
    ranked = sorted(cross_oos_summary.items(),
                    key=lambda x: x[1]["mean_sharpe"], reverse=True)
    for rank, (name, data) in enumerate(ranked, 1):
        better = ""
        if name in ["HAR-ABS VT", "HAR-VIX VT", "Hybrid VT"]:
            vix_mean = cross_oos_summary.get("12/VIX VT", {}).get("mean_sharpe", 0)
            diff = data["mean_sharpe"] - vix_mean
            better = f" (Δ vs VIX: {diff:+.4f})"
        print(f"    {rank}. {name}: mean Sharpe = {data['mean_sharpe']:.4f}{better}")

    # --------------------------------------------------------
    # 10. CONCLUSION
    # --------------------------------------------------------
    print_section("10. Conclusion", "-")

    vix_mean_sr = cross_oos_summary.get("12/VIX VT", {}).get("mean_sharpe", 0)
    har_abs_mean = cross_oos_summary.get("HAR-ABS VT", {}).get("mean_sharpe", 0)
    har_vix_mean = cross_oos_summary.get("HAR-VIX VT", {}).get("mean_sharpe", 0)
    hybrid_mean = cross_oos_summary.get("Hybrid VT", {}).get("mean_sharpe", 0)

    conclusion_lines = []
    if har_abs_mean > vix_mean_sr:
        conclusion_lines.append(f"HAR-ABS VT beats 12/VIX by {har_abs_mean - vix_mean_sr:.4f} Sharpe (mean)")
    else:
        conclusion_lines.append(f"HAR-ABS VT LOSES to 12/VIX by {vix_mean_sr - har_abs_mean:.4f} Sharpe (mean)")

    if har_vix_mean > vix_mean_sr:
        conclusion_lines.append(f"HAR-VIX VT beats 12/VIX by {har_vix_mean - vix_mean_sr:.4f} Sharpe (mean)")
    else:
        conclusion_lines.append(f"HAR-VIX VT LOSES to 12/VIX by {vix_mean_sr - har_vix_mean:.4f} Sharpe (mean)")

    conclusion_lines.append(f"Harvey t>3.0: {'SOME pass' if any_passes else 'NONE pass'}")
    conclusion_lines.append(f"Prediction ≠ Application: {'CONFIRMED again (#5)' if not any_passes or har_abs_mean <= vix_mean_sr else 'CHALLENGED'}")
    conclusion_lines.append(f"12/VIX irreducible kernel: {'CONFIRMED (#7)' if not any_passes else 'CHALLENGED'}")

    for line in conclusion_lines:
        print(f"  • {line}")

    # --------------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------------
    elapsed = time.time() - t_start
    print(f"\n  Elapsed: {elapsed:.1f}s")

    results = {
        "experiment_id": "K533",
        "title": "HAR-Based Volatility Targeting Strategy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "data_source": "yfinance (SPY, GLD, ^VIX) — empirical data",
        "data_period": f"{spy.index[0].date()} to {spy.index[-1].date()}",
        "references": [
            "Corsi (2009, JFE): Original HAR-RV model",
            "Moreira & Muir (2017, JoF 72(4)): Volatility-Managed Portfolios",
            "K530: HAR-ABS DM=-15.45 vs GJR-GARCH",
            "K470: HAR log-range VT — doesn't pass Harvey t>3.0",
            "K440/K488/K503/K504/K524: 12/VIX irreducible kernel"
        ],
        "method": {
            "strategies": {
                "B&H_SPY": "Buy & Hold 100% SPY",
                "B&H_5050": "Buy & Hold 50% SPY + 50% GLD",
                "12/VIX_VT": "w = min(1, 12/VIX) — forward-looking baseline",
                "HAR-ABS_VT": "w = min(1, target_vol / σ_HAR_ABS) — backward-looking HAR",
                "HAR-VIX_VT": "w = min(1, target_vol / σ_HAR_VIX) — HAR + VIX regressor",
                "Hybrid_VT": "w = 0.5 * w_VIX + 0.5 * w_HAR_ABS"
            },
            "target_vol": TARGET_VOL,
            "tx_cost": TX_COST,
            "har_window": HAR_WINDOW,
            "portfolio": "50% SPY + 50% GLD (for VT strategies)",
            "oos_periods": {k: list(v) for k, v in OOS_PERIODS.items()},
            "annualization": "σ_daily ≈ E[|r|] × √(π/2), σ_annual = σ_daily × √252",
        },
        "results_by_period": {},
        "cross_oos_summary": cross_oos_summary,
        "weight_correlations": weight_corr,
        "harvey_significance": harvey_results,
        "any_passes_harvey": any_passes,
        "conclusions": conclusion_lines,
    }

    # Clean results for JSON serialization
    for period_name in all_results:
        clean = {}
        for sname, sdata in all_results[period_name].items():
            if isinstance(sdata, dict):
                clean[sname] = {k: v for k, v in sdata.items()
                               if k not in ("returns", "weights")}
            else:
                clean[sname] = sdata
        results["results_by_period"][period_name] = clean

    out_path = Path(__file__).with_name("k533_har_vt_strategy_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
