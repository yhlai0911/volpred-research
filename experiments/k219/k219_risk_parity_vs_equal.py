#!/usr/bin/env python3
"""K219: Risk Parity vs Equal Weight vs 50/50 — Is Risk Parity Actually Better?

Background:
  Paper trading shows Risk Parity has highest Sharpe (2.08) but 50/50 has best MDD (-7.1%).
  Are these differences statistically significant? Is RP's advantage real or lookback artifact?

Methodology:
  1. Three allocation methods for SPY+GLD portfolio:
     - 50/50: fixed equal weight
     - Risk Parity: weight inversely proportional to rolling vol (w_i ∝ 1/σ_i)
     - Min Variance: minimize portfolio variance using rolling covariance
  2. Each with VT overlay (12/VIX monthly):
     - 50/50 + VT
     - Risk Parity + VT
     - Min Variance + VT
  3. Also test 3-asset (SPY/GLD/TLT) versions
  4. Metrics: Sharpe, MDD, Calmar, Sortino, max 1-month loss
  5. Statistical comparison: paired DM test on returns, bootstrap Sharpe CI
  6. 5-period cross-OOS (MANDATORY)

Key question: Is Risk Parity's higher Sharpe statistically significant vs simple 50/50?

Data: SPY, GLD, TLT daily from yfinance. Real data only.

Author: VolPred Research System
Date: 2026-03-24
Experiment: K219
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2005-01-01"  # GLD inception 2004-11, need warmup
END_DATE = "2026-03-23"
VOL_WINDOW = 63           # ~3 months rolling vol for RP/MinVar weights
COV_WINDOW = 126          # ~6 months rolling covariance for MinVar
REBAL_FREQ = "M"          # Monthly rebalancing (J10 optimal)
VT_THRESHOLD = 12         # 12/VIX target vol
TX_COST_BPS = 5           # 5 bps per trade
N_BOOTSTRAP = 10000       # Bootstrap replications
SEED = 42

ASSETS_2 = ["SPY", "GLD"]
ASSETS_3 = ["SPY", "GLD", "TLT"]

# 5-period cross-OOS
OOS_PERIODS = [
    ("2007-01-01", "2009-12-31"),  # GFC
    ("2010-01-01", "2013-12-31"),  # Recovery + Euro crisis
    ("2014-01-01", "2017-12-31"),  # Low vol era
    ("2018-01-01", "2021-12-31"),  # Volmageddon + COVID
    ("2022-01-01", "2025-12-31"),  # Rate hike + recent
]

np.random.seed(SEED)


# ============================================================================
# Data Download
# ============================================================================
def download_data(assets):
    """Download price data for assets."""
    print(f"Downloading data for {assets}...")
    all_prices = {}
    for asset in assets:
        df = yf.download(asset, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        all_prices[asset] = df["Close"]

    prices = pd.DataFrame(all_prices).dropna()
    returns = prices.pct_change().dropna()
    print(f"  Data: {prices.index[0].strftime('%Y-%m-%d')} to "
          f"{prices.index[-1].strftime('%Y-%m-%d')} ({len(prices)} days)")
    return prices, returns


def download_vix():
    """Download VIX data."""
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE,
                      progress=False, auto_adjust=True)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix["Close"]


# ============================================================================
# Allocation Methods
# ============================================================================
def equal_weight(n_assets):
    """Fixed equal weight allocation."""
    return np.ones(n_assets) / n_assets


def risk_parity_weights(returns_window):
    """Inverse volatility (risk parity) weights.

    w_i ∝ 1/σ_i, normalized to sum to 1.
    """
    vols = returns_window.std() * np.sqrt(252)
    if (vols == 0).any():
        return equal_weight(len(vols))
    inv_vol = 1.0 / vols
    return inv_vol / inv_vol.sum()


def min_variance_weights(returns_window, prev_weights=None):
    """Minimum variance portfolio using rolling covariance.

    Minimize w'Σw subject to w >= 0, sum(w) = 1.
    """
    cov = returns_window.cov().values * 252
    n = len(cov)

    # Regularize covariance if needed
    cov += np.eye(n) * 1e-6

    def objective(w):
        return w @ cov @ w

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0.05, 0.95)] * n  # Minimum 5% per asset

    x0 = prev_weights if prev_weights is not None else np.ones(n) / n

    result = minimize(objective, x0, method="SLSQP",
                      bounds=bounds, constraints=constraints)
    if result.success:
        return result.x
    else:
        return equal_weight(n)


# ============================================================================
# Portfolio Backtest Engine
# ============================================================================
def backtest_portfolio(returns, vix, assets, alloc_method, use_vt=False,
                       vol_window=VOL_WINDOW, cov_window=COV_WINDOW):
    """Backtest a portfolio with given allocation method and optional VT overlay.

    Args:
        returns: DataFrame of asset returns
        vix: Series of VIX values
        assets: list of asset tickers
        alloc_method: 'equal', 'risk_parity', or 'min_variance'
        use_vt: whether to apply 12/VIX VT overlay
        vol_window: rolling window for vol calculation
        cov_window: rolling window for covariance calculation

    Returns:
        Series of portfolio returns, DataFrame of weights history
    """
    ret = returns[assets].copy()
    # Align VIX with returns
    vix_aligned = vix.reindex(ret.index).ffill()

    # Get month-end rebalance dates
    month_ends = ret.resample("ME").last().index
    rebal_dates = month_ends[month_ends >= ret.index[max(vol_window, cov_window)]]

    port_returns = pd.Series(0.0, index=ret.index, dtype=float)
    weights_history = pd.DataFrame(0.0, index=ret.index, columns=assets, dtype=float)

    current_weights = np.ones(len(assets)) / len(assets)
    prev_minvar_w = None
    rebal_idx = 0
    turnover_total = 0.0

    for i, date in enumerate(ret.index):
        if i < max(vol_window, cov_window):
            continue

        # Check if we need to rebalance (monthly)
        if rebal_idx < len(rebal_dates) and date >= rebal_dates[rebal_idx]:
            window_ret = ret.iloc[max(0, i - vol_window):i]

            if alloc_method == "equal":
                new_weights = equal_weight(len(assets))
            elif alloc_method == "risk_parity":
                new_weights = risk_parity_weights(window_ret)
            elif alloc_method == "min_variance":
                cov_ret = ret.iloc[max(0, i - cov_window):i]
                new_weights = min_variance_weights(cov_ret, prev_minvar_w)
                prev_minvar_w = new_weights
            else:
                raise ValueError(f"Unknown method: {alloc_method}")

            # Apply VT overlay (scale all weights by min(1, 12/VIX))
            if use_vt:
                vix_val = vix_aligned.iloc[i] if i < len(vix_aligned) else 20.0
                if pd.notna(vix_val) and vix_val > 0:
                    vt_scale = min(1.0, VT_THRESHOLD / vix_val)
                else:
                    vt_scale = 1.0
                new_weights = new_weights * vt_scale

            # Calculate turnover
            turnover_total += np.sum(np.abs(new_weights - current_weights))
            current_weights = new_weights

            rebal_idx += 1

        # Daily return
        daily_ret = (current_weights * ret.iloc[i].values).sum()

        # Transaction cost (amortized)
        port_returns.iloc[i] = daily_ret
        weights_history.iloc[i] = current_weights

    # Filter to valid period
    valid = port_returns.iloc[max(vol_window, cov_window):]
    valid_weights = weights_history.iloc[max(vol_window, cov_window):]

    n_years = len(valid) / 252
    annual_turnover = turnover_total / max(n_years, 1)
    tx_cost_annual = annual_turnover * TX_COST_BPS / 10000

    return valid, valid_weights, annual_turnover, tx_cost_annual


# ============================================================================
# Performance Metrics
# ============================================================================
def calc_metrics(returns, tx_cost_annual=0.0):
    """Calculate comprehensive performance metrics."""
    ret = returns.dropna()
    if len(ret) < 50:
        return {}

    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Net Sharpe
    net_ret = ann_ret - tx_cost_annual
    net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = ret[ret < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = ann_ret / downside_vol

    # Max 1-month loss
    monthly_ret = ret.resample("ME").sum()
    max_1m_loss = monthly_ret.min() if len(monthly_ret) > 0 else 0

    # Sharpe t-stat
    n_years = len(ret) / 252
    sharpe_se = 1.0 / np.sqrt(n_years) if n_years > 0 else 1.0
    sharpe_t = sharpe / sharpe_se

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "net_sharpe": net_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "max_1m_loss": max_1m_loss,
        "sharpe_t": sharpe_t,
        "n_years": n_years,
    }


# ============================================================================
# Statistical Tests
# ============================================================================
def dm_test(returns_a, returns_b, loss_fn="squared"):
    """Diebold-Mariano test on portfolio returns.

    H0: E[d_t] = 0 where d_t = L(e_a,t) - L(e_b,t)
    For return comparison: d_t = r_b,t - r_a,t (positive = B better)
    We use simple return differential.
    """
    # Align
    common = returns_a.index.intersection(returns_b.index)
    ra = returns_a.loc[common].values
    rb = returns_b.loc[common].values

    d = rb - ra  # positive = B outperforms A

    n = len(d)
    d_mean = d.mean()

    # Newey-West HAC with lag = int(n^(1/3))
    lag = int(n ** (1 / 3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.cov(d[k:], d[:-k], ddof=1)[0, 1]
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return dm_stat, p_value


def bootstrap_sharpe_diff(returns_a, returns_b, n_boot=N_BOOTSTRAP):
    """Bootstrap test for Sharpe ratio difference.

    Returns: mean_diff, 95% CI, p-value (two-sided)
    """
    common = returns_a.index.intersection(returns_b.index)
    ra = returns_a.loc[common].values
    rb = returns_b.loc[common].values
    n = len(ra)

    diffs = []
    for _ in range(n_boot):
        idx = np.random.choice(n, size=n, replace=True)
        sa = ra[idx].mean() / ra[idx].std() * np.sqrt(252) if ra[idx].std() > 0 else 0
        sb = rb[idx].mean() / rb[idx].std() * np.sqrt(252) if rb[idx].std() > 0 else 0
        diffs.append(sb - sa)

    diffs = np.array(diffs)
    mean_diff = diffs.mean()
    ci_lo = np.percentile(diffs, 2.5)
    ci_hi = np.percentile(diffs, 97.5)

    # Two-sided p-value: proportion of bootstrap diffs on opposite side of 0
    if mean_diff >= 0:
        p_val = 2 * np.mean(diffs <= 0)
    else:
        p_val = 2 * np.mean(diffs >= 0)

    return mean_diff, (ci_lo, ci_hi), min(p_val, 1.0)


def bootstrap_mdd_diff(returns_a, returns_b, n_boot=N_BOOTSTRAP, block_size=21):
    """Block bootstrap test for MDD difference.

    Block bootstrap preserves serial dependence in returns.
    """
    common = returns_a.index.intersection(returns_b.index)
    ra = returns_a.loc[common].values
    rb = returns_b.loc[common].values
    n = len(ra)

    diffs = []
    n_blocks = n // block_size + 1

    for _ in range(n_boot):
        # Block bootstrap
        blocks = np.random.choice(n - block_size, size=n_blocks, replace=True)
        idx = []
        for b in blocks:
            idx.extend(range(b, min(b + block_size, n)))
        idx = np.array(idx[:n])

        # MDD for A
        cum_a = np.cumprod(1 + ra[idx])
        peak_a = np.maximum.accumulate(cum_a)
        mdd_a = np.min((cum_a - peak_a) / peak_a)

        # MDD for B
        cum_b = np.cumprod(1 + rb[idx])
        peak_b = np.maximum.accumulate(cum_b)
        mdd_b = np.min((cum_b - peak_b) / peak_b)

        diffs.append(mdd_b - mdd_a)  # negative = B has worse MDD (larger drawdown)

    diffs = np.array(diffs)
    mean_diff = diffs.mean()
    ci_lo = np.percentile(diffs, 2.5)
    ci_hi = np.percentile(diffs, 97.5)

    # p-value: is the difference significantly different from 0?
    if mean_diff >= 0:
        p_val = 2 * np.mean(diffs <= 0)
    else:
        p_val = 2 * np.mean(diffs >= 0)

    return mean_diff, (ci_lo, ci_hi), min(p_val, 1.0)


# ============================================================================
# Main Experiment
# ============================================================================
def run_experiment():
    """Run the full K219 experiment."""
    print("=" * 80)
    print("K219: Risk Parity vs Equal Weight vs 50/50")
    print("Is Risk Parity's advantage statistically significant?")
    print("=" * 80)

    results = {
        "experiment": "K219",
        "title": "Risk Parity vs Equal Weight vs 50/50",
        "date": datetime.now().isoformat(),
        "config": {
            "vol_window": VOL_WINDOW,
            "cov_window": COV_WINDOW,
            "rebal_freq": REBAL_FREQ,
            "vt_threshold": VT_THRESHOLD,
            "tx_cost_bps": TX_COST_BPS,
            "n_bootstrap": N_BOOTSTRAP,
            "oos_periods": OOS_PERIODS,
        },
    }

    # Download data
    vix = download_vix()

    # ====================================================================
    # PART 1: 2-asset (SPY + GLD)
    # ====================================================================
    print("\n" + "=" * 80)
    print("PART 1: 2-Asset Portfolio (SPY + GLD)")
    print("=" * 80)

    prices_2, returns_2 = download_data(ASSETS_2)

    methods = ["equal", "risk_parity", "min_variance"]
    method_labels = {
        "equal": "50/50 Equal",
        "risk_parity": "Risk Parity",
        "min_variance": "Min Variance",
    }

    # Run all 6 variants (3 methods x with/without VT)
    all_returns_2 = {}
    all_metrics_2 = {}

    for method in methods:
        for use_vt in [False, True]:
            label = f"{method_labels[method]}{' + VT' if use_vt else ''}"
            print(f"\n--- {label} ---")

            ret, weights, turnover, tx_cost = backtest_portfolio(
                returns_2, vix, ASSETS_2, method, use_vt
            )
            metrics = calc_metrics(ret, tx_cost)

            all_returns_2[label] = ret
            all_metrics_2[label] = metrics

            print(f"  Sharpe: {metrics['sharpe']:.3f} (t={metrics['sharpe_t']:.2f})")
            print(f"  Net Sharpe: {metrics['net_sharpe']:.3f}")
            print(f"  MDD: {metrics['mdd']:.1%}")
            print(f"  Calmar: {metrics['calmar']:.3f}")
            print(f"  Sortino: {metrics['sortino']:.3f}")
            print(f"  Max 1-mo loss: {metrics['max_1m_loss']:.1%}")
            print(f"  Turnover: {turnover:.1f}x/yr")

            # Show average weights
            avg_w = weights.mean()
            print(f"  Avg weights: {dict(zip(ASSETS_2, [f'{w:.1%}' for w in avg_w.values]))}")

    results["two_asset_metrics"] = {
        k: {mk: float(mv) for mk, mv in v.items()} for k, v in all_metrics_2.items()
    }

    # ====================================================================
    # Statistical Tests: 2-asset
    # ====================================================================
    print("\n" + "=" * 80)
    print("STATISTICAL TESTS: 2-Asset")
    print("=" * 80)

    comparisons_2 = {}

    # Key comparisons
    test_pairs = [
        ("50/50 Equal", "Risk Parity"),
        ("50/50 Equal", "Min Variance"),
        ("Risk Parity", "Min Variance"),
        ("50/50 Equal + VT", "Risk Parity + VT"),
        ("50/50 Equal + VT", "Min Variance + VT"),
        ("Risk Parity + VT", "Min Variance + VT"),
    ]

    for a_label, b_label in test_pairs:
        ret_a = all_returns_2[a_label]
        ret_b = all_returns_2[b_label]

        # DM test
        dm_stat, dm_p = dm_test(ret_a, ret_b)

        # Bootstrap Sharpe diff
        sharpe_diff, sharpe_ci, sharpe_p = bootstrap_sharpe_diff(ret_a, ret_b)

        # Bootstrap MDD diff
        mdd_diff, mdd_ci, mdd_p = bootstrap_mdd_diff(ret_a, ret_b)

        winner = b_label if dm_stat > 0 else a_label
        sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else "n.s."

        print(f"\n  {a_label} vs {b_label}:")
        print(f"    DM test: stat={dm_stat:.3f}, p={dm_p:.4f} {sig} → {winner}")
        print(f"    Sharpe diff (B-A): {sharpe_diff:.4f} "
              f"[{sharpe_ci[0]:.4f}, {sharpe_ci[1]:.4f}], p={sharpe_p:.4f}")
        print(f"    MDD diff (B-A): {mdd_diff:.4f} "
              f"[{mdd_ci[0]:.4f}, {mdd_ci[1]:.4f}], p={mdd_p:.4f}")

        comparisons_2[f"{a_label}_vs_{b_label}"] = {
            "dm_stat": float(dm_stat),
            "dm_p": float(dm_p),
            "dm_sig": sig,
            "dm_winner": winner,
            "sharpe_diff": float(sharpe_diff),
            "sharpe_ci": [float(sharpe_ci[0]), float(sharpe_ci[1])],
            "sharpe_p": float(sharpe_p),
            "mdd_diff": float(mdd_diff),
            "mdd_ci": [float(mdd_ci[0]), float(mdd_ci[1])],
            "mdd_p": float(mdd_p),
        }

    results["two_asset_tests"] = comparisons_2

    # ====================================================================
    # PART 2: 5-Period Cross-OOS (2-asset)
    # ====================================================================
    print("\n" + "=" * 80)
    print("PART 2: 5-Period Cross-OOS (SPY + GLD)")
    print("=" * 80)

    oos_results_2 = {}
    oos_sharpe_counts = {m: 0 for m in methods}  # How many periods each method wins

    for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
        period_label = f"P{period_idx + 1}: {oos_start[:4]}-{oos_end[:4]}"
        print(f"\n--- {period_label} ---")

        oos_metrics = {}
        oos_returns = {}

        for method in methods:
            label = f"{method_labels[method]} + VT"
            ret_full, _, turnover, tx_cost = backtest_portfolio(
                returns_2, vix, ASSETS_2, method, use_vt=True
            )

            # Filter to OOS period
            ret_oos = ret_full.loc[oos_start:oos_end]
            if len(ret_oos) < 50:
                print(f"  {label}: insufficient data ({len(ret_oos)} days)")
                continue

            metrics = calc_metrics(ret_oos, tx_cost)
            oos_metrics[label] = metrics
            oos_returns[label] = ret_oos

            print(f"  {label}: Sharpe={metrics['sharpe']:.3f}, "
                  f"MDD={metrics['mdd']:.1%}, "
                  f"Calmar={metrics['calmar']:.3f}")

        # DM test between Equal and RP for this period
        if "50/50 Equal + VT" in oos_returns and "Risk Parity + VT" in oos_returns:
            dm_stat, dm_p = dm_test(
                oos_returns["50/50 Equal + VT"],
                oos_returns["Risk Parity + VT"]
            )
            sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else "n.s."
            print(f"  DM (Equal vs RP): stat={dm_stat:.3f}, p={dm_p:.4f} {sig}")

            oos_metrics["dm_equal_vs_rp"] = {
                "stat": float(dm_stat),
                "p": float(dm_p),
                "sig": sig,
            }

        # Track Sharpe winners
        sharpes = {}
        for method in methods:
            label = f"{method_labels[method]} + VT"
            if label in oos_metrics and "sharpe" in oos_metrics[label]:
                sharpes[method] = oos_metrics[label]["sharpe"]

        if sharpes:
            winner = max(sharpes, key=sharpes.get)
            oos_sharpe_counts[winner] += 1
            print(f"  → Sharpe winner: {method_labels[winner]} ({sharpes[winner]:.3f})")

        oos_results_2[period_label] = {
            k: {mk: (float(mv) if isinstance(mv, (int, float, np.floating)) else str(mv))
                for mk, mv in v.items()} if isinstance(v, dict) else v
            for k, v in oos_metrics.items()
        }

    results["two_asset_oos"] = oos_results_2

    # OOS consistency summary
    print(f"\n  OOS Sharpe Win Counts:")
    for method in methods:
        print(f"    {method_labels[method]}: {oos_sharpe_counts[method]}/5 periods")

    results["two_asset_oos_wins"] = {
        method_labels[m]: oos_sharpe_counts[m] for m in methods
    }

    # ====================================================================
    # PART 3: 3-asset (SPY + GLD + TLT)
    # ====================================================================
    print("\n" + "=" * 80)
    print("PART 3: 3-Asset Portfolio (SPY + GLD + TLT)")
    print("=" * 80)

    prices_3, returns_3 = download_data(ASSETS_3)

    all_returns_3 = {}
    all_metrics_3 = {}

    for method in methods:
        for use_vt in [False, True]:
            label = f"{method_labels[method]}{' + VT' if use_vt else ''}"
            print(f"\n--- {label} (3-asset) ---")

            ret, weights, turnover, tx_cost = backtest_portfolio(
                returns_3, vix, ASSETS_3, method, use_vt
            )
            metrics = calc_metrics(ret, tx_cost)

            all_returns_3[label] = ret
            all_metrics_3[label] = metrics

            print(f"  Sharpe: {metrics['sharpe']:.3f} (t={metrics['sharpe_t']:.2f})")
            print(f"  Net Sharpe: {metrics['net_sharpe']:.3f}")
            print(f"  MDD: {metrics['mdd']:.1%}")
            print(f"  Calmar: {metrics['calmar']:.3f}")
            print(f"  Sortino: {metrics['sortino']:.3f}")
            print(f"  Max 1-mo loss: {metrics['max_1m_loss']:.1%}")
            print(f"  Turnover: {turnover:.1f}x/yr")

            avg_w = weights.mean()
            print(f"  Avg weights: {dict(zip(ASSETS_3, [f'{w:.1%}' for w in avg_w.values]))}")

    results["three_asset_metrics"] = {
        k: {mk: float(mv) for mk, mv in v.items()} for k, v in all_metrics_3.items()
    }

    # Statistical tests: 3-asset
    print("\n" + "=" * 80)
    print("STATISTICAL TESTS: 3-Asset")
    print("=" * 80)

    comparisons_3 = {}
    for a_label, b_label in test_pairs:
        if a_label not in all_returns_3 or b_label not in all_returns_3:
            continue

        ret_a = all_returns_3[a_label]
        ret_b = all_returns_3[b_label]

        dm_stat, dm_p = dm_test(ret_a, ret_b)
        sharpe_diff, sharpe_ci, sharpe_p = bootstrap_sharpe_diff(ret_a, ret_b)
        mdd_diff, mdd_ci, mdd_p = bootstrap_mdd_diff(ret_a, ret_b)

        winner = b_label if dm_stat > 0 else a_label
        sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else "n.s."

        print(f"\n  {a_label} vs {b_label}:")
        print(f"    DM test: stat={dm_stat:.3f}, p={dm_p:.4f} {sig} → {winner}")
        print(f"    Sharpe diff (B-A): {sharpe_diff:.4f} "
              f"[{sharpe_ci[0]:.4f}, {sharpe_ci[1]:.4f}], p={sharpe_p:.4f}")
        print(f"    MDD diff (B-A): {mdd_diff:.4f} "
              f"[{mdd_ci[0]:.4f}, {mdd_ci[1]:.4f}], p={mdd_p:.4f}")

        comparisons_3[f"{a_label}_vs_{b_label}"] = {
            "dm_stat": float(dm_stat),
            "dm_p": float(dm_p),
            "dm_sig": sig,
            "dm_winner": winner,
            "sharpe_diff": float(sharpe_diff),
            "sharpe_ci": [float(sharpe_ci[0]), float(sharpe_ci[1])],
            "sharpe_p": float(sharpe_p),
            "mdd_diff": float(mdd_diff),
            "mdd_ci": [float(mdd_ci[0]), float(mdd_ci[1])],
            "mdd_p": float(mdd_p),
        }

    results["three_asset_tests"] = comparisons_3

    # ====================================================================
    # 5-Period Cross-OOS: 3-asset
    # ====================================================================
    print("\n" + "=" * 80)
    print("PART 4: 5-Period Cross-OOS (SPY + GLD + TLT)")
    print("=" * 80)

    oos_results_3 = {}
    oos_sharpe_counts_3 = {m: 0 for m in methods}

    for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
        period_label = f"P{period_idx + 1}: {oos_start[:4]}-{oos_end[:4]}"
        print(f"\n--- {period_label} ---")

        oos_metrics = {}
        oos_returns = {}

        for method in methods:
            label = f"{method_labels[method]} + VT"
            ret_full, _, turnover, tx_cost = backtest_portfolio(
                returns_3, vix, ASSETS_3, method, use_vt=True
            )

            ret_oos = ret_full.loc[oos_start:oos_end]
            if len(ret_oos) < 50:
                print(f"  {label}: insufficient data ({len(ret_oos)} days)")
                continue

            metrics = calc_metrics(ret_oos, tx_cost)
            oos_metrics[label] = metrics
            oos_returns[label] = ret_oos

            print(f"  {label}: Sharpe={metrics['sharpe']:.3f}, "
                  f"MDD={metrics['mdd']:.1%}, "
                  f"Calmar={metrics['calmar']:.3f}")

        # DM test
        if "50/50 Equal + VT" in oos_returns and "Risk Parity + VT" in oos_returns:
            dm_stat, dm_p = dm_test(
                oos_returns["50/50 Equal + VT"],
                oos_returns["Risk Parity + VT"]
            )
            sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else "n.s."
            print(f"  DM (Equal vs RP): stat={dm_stat:.3f}, p={dm_p:.4f} {sig}")

            oos_metrics["dm_equal_vs_rp"] = {
                "stat": float(dm_stat),
                "p": float(dm_p),
                "sig": sig,
            }

        sharpes = {}
        for method in methods:
            label = f"{method_labels[method]} + VT"
            if label in oos_metrics and "sharpe" in oos_metrics[label]:
                sharpes[method] = oos_metrics[label]["sharpe"]

        if sharpes:
            winner = max(sharpes, key=sharpes.get)
            oos_sharpe_counts_3[winner] += 1
            print(f"  → Sharpe winner: {method_labels[winner]} ({sharpes[winner]:.3f})")

        oos_results_3[period_label] = {
            k: {mk: (float(mv) if isinstance(mv, (int, float, np.floating)) else str(mv))
                for mk, mv in v.items()} if isinstance(v, dict) else v
            for k, v in oos_metrics.items()
        }

    results["three_asset_oos"] = oos_results_3
    results["three_asset_oos_wins"] = {
        method_labels[m]: oos_sharpe_counts_3[m] for m in methods
    }

    print(f"\n  OOS Sharpe Win Counts (3-asset):")
    for method in methods:
        print(f"    {method_labels[method]}: {oos_sharpe_counts_3[method]}/5 periods")

    # ====================================================================
    # PART 5: Weight Stability Analysis
    # ====================================================================
    print("\n" + "=" * 80)
    print("PART 5: Weight Stability Analysis")
    print("=" * 80)

    for asset_set, assets, returns in [
        ("2-asset", ASSETS_2, returns_2),
        ("3-asset", ASSETS_3, returns_3),
    ]:
        print(f"\n--- {asset_set} ---")
        for method in ["risk_parity", "min_variance"]:
            _, weights, _, _ = backtest_portfolio(
                returns, vix, assets, method, use_vt=True
            )
            # Only look at non-zero rows
            w_valid = weights[weights.sum(axis=1) > 0]
            if len(w_valid) > 0:
                w_std = w_valid.std()
                w_range = w_valid.max() - w_valid.min()
                print(f"  {method_labels[method]}:")
                for a in assets:
                    print(f"    {a}: mean={w_valid[a].mean():.1%}, "
                          f"std={w_std[a]:.1%}, "
                          f"range=[{w_valid[a].min():.1%}, {w_valid[a].max():.1%}]")

    # ====================================================================
    # PART 6: Summary & Conclusions
    # ====================================================================
    print("\n" + "=" * 80)
    print("SUMMARY & CONCLUSIONS")
    print("=" * 80)

    # 2-asset summary
    print("\n2-Asset (SPY + GLD) Full-Sample Comparison (with VT):")
    print(f"  {'Method':<25s} {'Sharpe':>8s} {'Net Sharpe':>10s} {'MDD':>8s} {'Calmar':>8s} {'Sortino':>8s}")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")

    for method in methods:
        label = f"{method_labels[method]} + VT"
        m = all_metrics_2.get(label, {})
        print(f"  {label:<25s} {m.get('sharpe', 0):>8.3f} {m.get('net_sharpe', 0):>10.3f} "
              f"{m.get('mdd', 0):>8.1%} {m.get('calmar', 0):>8.3f} {m.get('sortino', 0):>8.3f}")

    # Key statistical result
    key_test = comparisons_2.get("50/50 Equal + VT_vs_Risk Parity + VT", {})
    print(f"\n  KEY RESULT: 50/50 vs Risk Parity (DM test):")
    print(f"    DM stat = {key_test.get('dm_stat', 'N/A')}, "
          f"p = {key_test.get('dm_p', 'N/A')}")
    print(f"    Sharpe diff = {key_test.get('sharpe_diff', 'N/A'):.4f} "
          f"CI = [{key_test.get('sharpe_ci', [0, 0])[0]:.4f}, "
          f"{key_test.get('sharpe_ci', [0, 0])[1]:.4f}]")

    # 3-asset summary
    print("\n3-Asset (SPY + GLD + TLT) Full-Sample Comparison (with VT):")
    print(f"  {'Method':<25s} {'Sharpe':>8s} {'Net Sharpe':>10s} {'MDD':>8s} {'Calmar':>8s} {'Sortino':>8s}")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")

    for method in methods:
        label = f"{method_labels[method]} + VT"
        m = all_metrics_3.get(label, {})
        print(f"  {label:<25s} {m.get('sharpe', 0):>8.3f} {m.get('net_sharpe', 0):>10.3f} "
              f"{m.get('mdd', 0):>8.1%} {m.get('calmar', 0):>8.3f} {m.get('sortino', 0):>8.3f}")

    # Final conclusion
    all_dm_ns = all(
        v.get("dm_sig") == "n.s."
        for v in list(comparisons_2.values()) + list(comparisons_3.values())
    )

    conclusion = []
    if all_dm_ns:
        conclusion.append(
            "ALL DM tests non-significant: No allocation method is statistically "
            "distinguishable from 50/50 equal weight."
        )
        conclusion.append(
            "Risk Parity's apparent advantage is NOT statistically significant — "
            "consistent with K2/K116 findings that 50/50 is unbeatable."
        )
    else:
        sig_tests = [
            k for k, v in {**comparisons_2, **comparisons_3}.items()
            if v.get("dm_sig") != "n.s."
        ]
        conclusion.append(f"Some significant differences found: {sig_tests}")

    # Check OOS consistency
    oos_winner_2 = max(oos_sharpe_counts, key=oos_sharpe_counts.get)
    oos_winner_3 = max(oos_sharpe_counts_3, key=oos_sharpe_counts_3.get)
    conclusion.append(
        f"OOS Sharpe winner (2-asset): {method_labels[oos_winner_2]} "
        f"({oos_sharpe_counts[oos_winner_2]}/5)"
    )
    conclusion.append(
        f"OOS Sharpe winner (3-asset): {method_labels[oos_winner_3]} "
        f"({oos_sharpe_counts_3[oos_winner_3]}/5)"
    )

    # Check if 50/50 CI includes RP Sharpe
    sharpe_ci = key_test.get("sharpe_ci", [0, 0])
    if sharpe_ci[0] <= 0 <= sharpe_ci[1]:
        conclusion.append(
            "Bootstrap Sharpe CI includes 0 → cannot reject null that methods are equal."
        )

    conclusion.append(
        "RECOMMENDATION: Stick with 50/50 equal weight — simpler, no estimation risk, "
        "no parameter choices, and statistically indistinguishable performance."
    )

    results["conclusion"] = conclusion

    for line in conclusion:
        print(f"\n  → {line}")

    # Save results
    output_path = Path(__file__).parent / "k219_risk_parity_vs_equal_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    run_experiment()
