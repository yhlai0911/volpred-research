#!/usr/bin/env python3
"""
K64 Follow-up: Deep Dive into Small BTC Allocation
=====================================================
47/47/5 SPY/GLD/BTC was found to beat 50/50 SPY/GLD (p=0.027).
This script investigates robustness, optimal allocation, VT overlays, and tail risk.

Author: VolPred Research System
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# 0. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K64 Follow-up: BTC Allocation Deep Dive")
print("=" * 70)

START = "2015-01-01"
END = "2026-03-21"

print("\n[0] Downloading data...")
spy = yf.download("SPY", start=START, end=END, progress=False)["Close"].squeeze()
gld = yf.download("GLD", start=START, end=END, progress=False)["Close"].squeeze()
btc = yf.download("BTC-USD", start=START, end=END, progress=False)["Close"].squeeze()
vix = yf.download("^VIX", start=START, end=END, progress=False)["Close"].squeeze()

# Align all series to common dates
common = spy.index.intersection(gld.index).intersection(btc.index).intersection(vix.index)
spy, gld, btc, vix = spy.loc[common], gld.loc[common], btc.loc[common], vix.loc[common]

ret_spy = spy.pct_change().dropna()
ret_gld = gld.pct_change().dropna()
ret_btc = btc.pct_change().dropna()

# Align returns
common_ret = ret_spy.index.intersection(ret_gld.index).intersection(ret_btc.index)
ret_spy = ret_spy.loc[common_ret]
ret_gld = ret_gld.loc[common_ret]
ret_btc = ret_btc.loc[common_ret]
vix_aligned = vix.reindex(common_ret, method="ffill")

print(f"  Data range: {common_ret[0].strftime('%Y-%m-%d')} to {common_ret[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(common_ret)}")


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def monthly_rebalance_portfolio(weights_dict, ret_dict, tc_dict, vt_weights=None):
    """
    Monthly rebalance with lagged weights and transaction costs.

    weights_dict: {asset: weight}  (static target weights)
    ret_dict: {asset: pd.Series of daily returns}
    tc_dict: {asset: one-way TC in decimal}
    vt_weights: pd.Series of VT weights (0-1), applied to equity portion

    Returns: pd.Series of daily portfolio returns (net of TC)
    """
    assets = list(weights_dict.keys())
    target_w = np.array([weights_dict[a] for a in assets])
    ret_df = pd.DataFrame({a: ret_dict[a] for a in assets})
    tc = np.array([tc_dict.get(a, 0.0005) for a in assets])

    dates = ret_df.index
    port_ret = pd.Series(0.0, index=dates)

    # Monthly rebalance dates (first trading day of each month)
    monthly = ret_df.resample("MS").first().index
    rebal_dates = set()
    for m in monthly:
        # Find next available trading day
        mask = dates >= m
        if mask.any():
            rebal_dates.add(dates[mask][0])

    current_w = target_w.copy()

    for i, date in enumerate(dates):
        if date in rebal_dates and i > 0:
            # Apply VT scaling if provided
            tw = target_w.copy()
            if vt_weights is not None and date in vt_weights.index:
                # Find the lagged VT weight (use previous month's end VIX)
                prev_dates = vt_weights.index[vt_weights.index < date]
                if len(prev_dates) > 0:
                    vt_w = vt_weights.loc[prev_dates[-1]]
                    # Scale all risky assets by VT weight
                    tw = tw * vt_w

            # Transaction cost
            turnover = np.abs(tw - current_w)
            tc_cost = np.sum(turnover * tc)

            current_w = tw.copy()
            port_ret.iloc[i] = np.sum(current_w * ret_df.iloc[i].values) - tc_cost
        else:
            port_ret.iloc[i] = np.sum(current_w * ret_df.iloc[i].values)

        # Drift weights
        if i < len(dates) - 1:
            current_w = current_w * (1 + ret_df.iloc[i].values)
            w_sum = current_w.sum()
            if w_sum > 0:
                current_w = current_w / w_sum


def portfolio_metrics(ret_series, name=""):
    """Calculate comprehensive portfolio metrics."""
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + ret_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = ret_series[ret_series < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Skewness, Kurtosis
    skew = ret_series.skew()
    kurt = ret_series.kurtosis()

    # Max daily loss
    max_loss = ret_series.min()

    # Harvey t-stat
    n_years = len(ret_series) / 252
    t_stat = sharpe * np.sqrt(n_years)

    return {
        "name": name,
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd * 100, 2),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "skewness": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "max_daily_loss": round(max_loss * 100, 2),
        "t_stat": round(t_stat, 2),
        "n_years": round(n_years, 1),
    }


def simple_monthly_rebalance(weights, ret_df, tc_rates, vt_series=None):
    """
    Simpler monthly rebalance implementation.
    weights: dict {col_name: target_weight}
    ret_df: DataFrame with columns matching weights keys
    tc_rates: dict {col_name: one-way TC rate}
    vt_series: optional Series of VT multipliers (0-1), indexed by date
    """
    cols = list(weights.keys())
    target = np.array([weights[c] for c in cols])
    tc = np.array([tc_rates.get(c, 0.0005) for c in cols])

    dates = ret_df.index
    port_rets = []

    # Identify month boundaries
    months = pd.Series(dates).dt.to_period("M")
    month_starts = []
    prev_m = None
    for i, m in enumerate(months):
        if m != prev_m:
            month_starts.append(i)
            prev_m = m
    month_start_set = set(month_starts)

    curr_w = target.copy()

    for i in range(len(dates)):
        day_ret = ret_df.iloc[i].values

        if i in month_start_set and i > 0:
            new_target = target.copy()

            # Apply VT if provided
            if vt_series is not None:
                # Lagged: use last available VT weight before this date
                prior = vt_series.index[vt_series.index < dates[i]]
                if len(prior) > 0:
                    vt_mult = vt_series.loc[prior[-1]]
                    new_target = new_target * vt_mult

            turnover = np.abs(new_target - curr_w)
            tc_cost = np.sum(turnover * tc)

            curr_w = new_target.copy()
            pr = np.sum(curr_w * day_ret) - tc_cost
        else:
            pr = np.sum(curr_w * day_ret)

        port_rets.append(pr)

        # Drift weights
        curr_w = curr_w * (1 + day_ret)
        wsum = curr_w.sum()
        if wsum > 0:
            curr_w = curr_w / wsum

    return pd.Series(port_rets, index=dates)


def bootstrap_sharpe_diff(ret_a, ret_b, n_boot=10000, block_size=21):
    """Block bootstrap test for Sharpe ratio difference."""
    diff_actual = (ret_a.mean() / ret_a.std() - ret_b.mean() / ret_b.std()) * np.sqrt(252)

    n = len(ret_a)
    n_blocks = n // block_size + 1

    diffs = []
    rng = np.random.RandomState(42)
    for _ in range(n_boot):
        idx = []
        for _ in range(n_blocks):
            start = rng.randint(0, n - block_size)
            idx.extend(range(start, start + block_size))
        idx = idx[:n]

        a_boot = ret_a.iloc[idx].values
        b_boot = ret_b.iloc[idx].values

        s_a = a_boot.mean() / a_boot.std() * np.sqrt(252)
        s_b = b_boot.mean() / b_boot.std() * np.sqrt(252)
        diffs.append(s_a - s_b)

    diffs = np.array(diffs)
    p_value = np.mean(diffs <= 0)  # p-value that A is not better than B

    return {
        "sharpe_diff": round(diff_actual, 4),
        "p_value": round(p_value, 4),
        "ci_95": [round(np.percentile(diffs, 2.5), 4), round(np.percentile(diffs, 97.5), 4)],
    }


# Build return DataFrame
ret_df = pd.DataFrame({"SPY": ret_spy, "GLD": ret_gld, "BTC": ret_btc})
tc_rates = {"SPY": 0.0005, "GLD": 0.0005, "BTC": 0.0010}

# VIX-based VT weights (12/VIX, monthly, lagged)
vt_weights_12vix = (12.0 / vix_aligned).clip(0, 1)

print(f"\n  BTC stats: mean={ret_btc.mean()*252*100:.1f}%/yr, vol={ret_btc.std()*np.sqrt(252)*100:.1f}%/yr")
print(f"  SPY stats: mean={ret_spy.mean()*252*100:.1f}%/yr, vol={ret_spy.std()*np.sqrt(252)*100:.1f}%/yr")
print(f"  GLD stats: mean={ret_gld.mean()*252*100:.1f}%/yr, vol={ret_gld.std()*np.sqrt(252)*100:.1f}%/yr")

results = {}

# ============================================================
# 1. SUB-PERIOD ROBUSTNESS
# ============================================================
print("\n" + "=" * 70)
print("[1] Sub-period Robustness Analysis")
print("=" * 70)

periods = {
    "Pre-2020 (2015-2019)": ("2015-01-01", "2019-12-31"),
    "COVID+Crypto Winter (2020-2022)": ("2020-01-01", "2022-12-31"),
    "Recovery+Bull (2023-2026)": ("2023-01-01", "2026-12-31"),
    "Full Period": (START, END),
}

sub_period_results = {}

for period_name, (ps, pe) in periods.items():
    mask = (ret_df.index >= ps) & (ret_df.index <= pe)
    sub_ret = ret_df.loc[mask]

    if len(sub_ret) < 60:
        continue

    # 50/50 SPY/GLD baseline
    p5050 = simple_monthly_rebalance(
        {"SPY": 0.50, "GLD": 0.50, "BTC": 0.0},
        sub_ret, tc_rates
    )

    # 47/47/5 SPY/GLD/BTC
    p47475 = simple_monthly_rebalance(
        {"SPY": 0.4725, "GLD": 0.4725, "BTC": 0.055},
        sub_ret, tc_rates
    )
    # Actually use 47.5/47.5/5 as described
    p47475 = simple_monthly_rebalance(
        {"SPY": 0.475, "GLD": 0.475, "BTC": 0.05},
        sub_ret, tc_rates
    )

    m_base = portfolio_metrics(p5050, "50/50 SPY/GLD")
    m_btc = portfolio_metrics(p47475, "47.5/47.5/5 SPY/GLD/BTC")

    boot = bootstrap_sharpe_diff(p47475, p5050, n_boot=5000)

    sub_period_results[period_name] = {
        "baseline": m_base,
        "btc_5pct": m_btc,
        "sharpe_diff_test": boot,
        "n_days": len(sub_ret),
    }

    print(f"\n  {period_name} ({len(sub_ret)} days)")
    print(f"    50/50:        Sharpe={m_base['sharpe']:.3f}  MDD={m_base['mdd']:.1f}%  Return={m_base['ann_return']:.1f}%")
    print(f"    47.5/47.5/5:  Sharpe={m_btc['sharpe']:.3f}  MDD={m_btc['mdd']:.1f}%  Return={m_btc['ann_return']:.1f}%")
    print(f"    Sharpe diff={boot['sharpe_diff']:.4f}  p={boot['p_value']:.3f}")

results["sub_period_robustness"] = sub_period_results

# ============================================================
# 2. OPTIMAL BTC ALLOCATION SWEEP
# ============================================================
print("\n" + "=" * 70)
print("[2] Optimal BTC Allocation Sweep")
print("=" * 70)

btc_allocs = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]

sweep_results = {}

# Strategy A: Replace from SPY only
print("\n  [2a] Replace from SPY only:")
strategy_a = {}
for btc_w in btc_allocs:
    spy_w = 0.50 - btc_w
    gld_w = 0.50
    if spy_w < 0:
        continue

    p = simple_monthly_rebalance(
        {"SPY": spy_w, "GLD": gld_w, "BTC": btc_w},
        ret_df, tc_rates
    )
    m = portfolio_metrics(p, f"{spy_w*100:.0f}/{gld_w*100:.0f}/{btc_w*100:.0f}")
    strategy_a[f"BTC_{btc_w*100:.0f}pct"] = m
    print(f"    SPY={spy_w*100:.0f}%  GLD={gld_w*100:.0f}%  BTC={btc_w*100:.0f}%  →  Sharpe={m['sharpe']:.3f}  MDD={m['mdd']:.1f}%  Return={m['ann_return']:.1f}%")

sweep_results["replace_from_SPY"] = strategy_a

# Strategy B: Replace from GLD only
print("\n  [2b] Replace from GLD only:")
strategy_b = {}
for btc_w in btc_allocs:
    spy_w = 0.50
    gld_w = 0.50 - btc_w
    if gld_w < 0:
        continue

    p = simple_monthly_rebalance(
        {"SPY": spy_w, "GLD": gld_w, "BTC": btc_w},
        ret_df, tc_rates
    )
    m = portfolio_metrics(p, f"{spy_w*100:.0f}/{gld_w*100:.0f}/{btc_w*100:.0f}")
    strategy_b[f"BTC_{btc_w*100:.0f}pct"] = m
    print(f"    SPY={spy_w*100:.0f}%  GLD={gld_w*100:.0f}%  BTC={btc_w*100:.0f}%  →  Sharpe={m['sharpe']:.3f}  MDD={m['mdd']:.1f}%  Return={m['ann_return']:.1f}%")

sweep_results["replace_from_GLD"] = strategy_b

# Strategy C: Replace equally from both
print("\n  [2c] Replace equally from both:")
strategy_c = {}
for btc_w in btc_allocs:
    spy_w = 0.50 - btc_w / 2
    gld_w = 0.50 - btc_w / 2
    if spy_w < 0 or gld_w < 0:
        continue

    p = simple_monthly_rebalance(
        {"SPY": spy_w, "GLD": gld_w, "BTC": btc_w},
        ret_df, tc_rates
    )
    m = portfolio_metrics(p, f"{spy_w*100:.1f}/{gld_w*100:.1f}/{btc_w*100:.0f}")
    strategy_c[f"BTC_{btc_w*100:.0f}pct"] = m
    print(f"    SPY={spy_w*100:.1f}%  GLD={gld_w*100:.1f}%  BTC={btc_w*100:.0f}%  →  Sharpe={m['sharpe']:.3f}  MDD={m['mdd']:.1f}%  Return={m['ann_return']:.1f}%")

sweep_results["replace_equally"] = strategy_c

# Find optimal
print("\n  [2d] Optimal allocation (max Sharpe, MDD > -20%):")
best_sharpe = -999
best_config = None
for strategy_name, strategy_data in sweep_results.items():
    for alloc_name, m in strategy_data.items():
        if m["mdd"] > -20 and m["sharpe"] > best_sharpe:
            best_sharpe = m["sharpe"]
            best_config = f"{strategy_name}/{alloc_name}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.1f}%"

print(f"    Best: {best_config}")

# Statistical test: best BTC allocation vs 50/50
p_baseline = simple_monthly_rebalance(
    {"SPY": 0.50, "GLD": 0.50, "BTC": 0.0},
    ret_df, tc_rates
)

# Test each allocation against baseline
print("\n  [2e] Bootstrap tests vs 50/50 baseline:")
test_configs = [
    ("2% equal", {"SPY": 0.49, "GLD": 0.49, "BTC": 0.02}),
    ("3% equal", {"SPY": 0.485, "GLD": 0.485, "BTC": 0.03}),
    ("5% equal", {"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}),
    ("7% equal", {"SPY": 0.465, "GLD": 0.465, "BTC": 0.07}),
    ("10% equal", {"SPY": 0.45, "GLD": 0.45, "BTC": 0.10}),
]

bootstrap_tests = {}
for name, weights in test_configs:
    p_test = simple_monthly_rebalance(weights, ret_df, tc_rates)
    boot = bootstrap_sharpe_diff(p_test, p_baseline, n_boot=10000)
    bootstrap_tests[name] = boot
    sig = "***" if boot["p_value"] < 0.01 else "**" if boot["p_value"] < 0.05 else "*" if boot["p_value"] < 0.10 else ""
    print(f"    {name}: ΔSharpe={boot['sharpe_diff']:.4f}  p={boot['p_value']:.3f} {sig}  CI={boot['ci_95']}")

sweep_results["bootstrap_vs_baseline"] = bootstrap_tests

results["allocation_sweep"] = sweep_results

# ============================================================
# 3. BTC WITH VT OVERLAY
# ============================================================
print("\n" + "=" * 70)
print("[3] BTC with VT Overlay")
print("=" * 70)

# 3a: 12/VIX VT applied to entire portfolio
print("\n  [3a] 12/VIX VT on entire portfolio:")
vt_configs = [
    ("50/50 no VT", {"SPY": 0.50, "GLD": 0.50, "BTC": 0.0}, None),
    ("50/50 + 12/VIX", {"SPY": 0.50, "GLD": 0.50, "BTC": 0.0}, vt_weights_12vix),
    ("47.5/47.5/5 no VT", {"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}, None),
    ("47.5/47.5/5 + 12/VIX (all)", {"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}, vt_weights_12vix),
]

vt_results = {}
for name, weights, vt in vt_configs:
    p = simple_monthly_rebalance(weights, ret_df, tc_rates, vt_series=vt)
    m = portfolio_metrics(p, name)
    vt_results[name] = m
    print(f"    {name}: Sharpe={m['sharpe']:.3f}  MDD={m['mdd']:.1f}%  Return={m['ann_return']:.1f}%")

# 3b: VT only on equity portion, BTC stays static
print("\n  [3b] VT on SPY/GLD only, BTC static:")

def mixed_vt_portfolio(spy_w, gld_w, btc_w, ret_df, tc_rates, vt_series):
    """Apply VT only to SPY+GLD, keep BTC static."""
    dates = ret_df.index
    port_rets = []

    months = pd.Series(dates).dt.to_period("M")
    month_starts = []
    prev_m = None
    for i, m in enumerate(months):
        if m != prev_m:
            month_starts.append(i)
            prev_m = m
    month_start_set = set(month_starts)

    # Current weights: [SPY, GLD, BTC]
    target = np.array([spy_w, gld_w, btc_w])
    curr_w = target.copy()
    tc = np.array([tc_rates.get("SPY", 0.0005), tc_rates.get("GLD", 0.0005), tc_rates.get("BTC", 0.001)])

    for i in range(len(dates)):
        day_ret = ret_df.iloc[i].values  # SPY, GLD, BTC

        if i in month_start_set and i > 0:
            # Get lagged VT weight
            prior = vt_series.index[vt_series.index < dates[i]]
            if len(prior) > 0:
                vt_mult = float(vt_series.loc[prior[-1]])
            else:
                vt_mult = 1.0

            # Scale SPY and GLD by VT, keep BTC static
            new_target = np.array([spy_w * vt_mult, gld_w * vt_mult, btc_w])

            turnover = np.abs(new_target - curr_w)
            tc_cost = np.sum(turnover * tc)

            curr_w = new_target.copy()
            pr = np.sum(curr_w * day_ret) - tc_cost
        else:
            pr = np.sum(curr_w * day_ret)

        port_rets.append(pr)

        curr_w = curr_w * (1 + day_ret)
        wsum = curr_w.sum()
        if wsum > 0:
            curr_w = curr_w / wsum

    return pd.Series(port_rets, index=dates)


p_mixed = mixed_vt_portfolio(0.475, 0.475, 0.05, ret_df, tc_rates, vt_weights_12vix)
m_mixed = portfolio_metrics(p_mixed, "47.5/47.5/5 VT(SPY+GLD only)")
vt_results["VT_equity_only_BTC_static"] = m_mixed
print(f"    VT on SPY+GLD, BTC static: Sharpe={m_mixed['sharpe']:.3f}  MDD={m_mixed['mdd']:.1f}%  Return={m_mixed['ann_return']:.1f}%")

# 3c: BTC with its own RV-based VT
print("\n  [3c] BTC RV-VT (using BTC's own 22d realized vol, target=15%):")

# Calculate BTC realized vol (22-day)
btc_rv = ret_btc.rolling(22).std() * np.sqrt(252)
btc_vt_target = 0.15  # 15% target vol
btc_vt_weights = (btc_vt_target / btc_rv).clip(0, 1)

def btc_rv_vt_portfolio(spy_w, gld_w, btc_w, ret_df, tc_rates, vix_vt, btc_vt):
    """Apply VIX VT to SPY/GLD and RV VT to BTC."""
    dates = ret_df.index
    port_rets = []

    months = pd.Series(dates).dt.to_period("M")
    month_starts = []
    prev_m = None
    for i, m in enumerate(months):
        if m != prev_m:
            month_starts.append(i)
            prev_m = m
    month_start_set = set(month_starts)

    target = np.array([spy_w, gld_w, btc_w])
    curr_w = target.copy()
    tc = np.array([tc_rates.get("SPY", 0.0005), tc_rates.get("GLD", 0.0005), tc_rates.get("BTC", 0.001)])

    for i in range(len(dates)):
        day_ret = ret_df.iloc[i].values

        if i in month_start_set and i > 0:
            # Lagged VIX VT for SPY/GLD
            prior_vix = vix_vt.index[vix_vt.index < dates[i]]
            vt_eq = float(vix_vt.loc[prior_vix[-1]]) if len(prior_vix) > 0 else 1.0

            # Lagged BTC RV VT
            prior_btc = btc_vt.index[btc_vt.index < dates[i]]
            vt_btc = float(btc_vt.loc[prior_btc[-1]]) if len(prior_btc) > 0 else 1.0

            new_target = np.array([spy_w * vt_eq, gld_w * vt_eq, btc_w * vt_btc])

            turnover = np.abs(new_target - curr_w)
            tc_cost = np.sum(turnover * tc)

            curr_w = new_target.copy()
            pr = np.sum(curr_w * day_ret) - tc_cost
        else:
            pr = np.sum(curr_w * day_ret)

        port_rets.append(pr)

        curr_w = curr_w * (1 + day_ret)
        wsum = curr_w.sum()
        if wsum > 0:
            curr_w = curr_w / wsum

    return pd.Series(port_rets, index=dates)


p_btc_rv = btc_rv_vt_portfolio(0.475, 0.475, 0.05, ret_df, tc_rates, vt_weights_12vix, btc_vt_weights)
m_btc_rv = portfolio_metrics(p_btc_rv, "47.5/47.5/5 VIX-VT(eq) + RV-VT(BTC)")
vt_results["VIX_VT_eq_plus_BTC_RV_VT"] = m_btc_rv
print(f"    VIX VT(eq) + BTC RV-VT: Sharpe={m_btc_rv['sharpe']:.3f}  MDD={m_btc_rv['mdd']:.1f}%  Return={m_btc_rv['ann_return']:.1f}%")

results["vt_overlay"] = vt_results

# ============================================================
# 4. TAIL RISK ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[4] Tail Risk Analysis")
print("=" * 70)

# 4a: Coskewness
print("\n  [4a] Coskewness analysis:")

# BTC coskewness with SPY
spy_dm = ret_spy - ret_spy.mean()
gld_dm = ret_gld - ret_gld.mean()
btc_dm = ret_btc - ret_btc.mean()

coskew_btc_spy = (btc_dm * spy_dm**2).mean() / (btc_dm.std() * spy_dm.std()**2)
coskew_btc_gld = (btc_dm * gld_dm**2).mean() / (btc_dm.std() * gld_dm.std()**2)
coskew_spy_btc = (spy_dm * btc_dm**2).mean() / (spy_dm.std() * btc_dm.std()**2)
coskew_gld_btc = (gld_dm * btc_dm**2).mean() / (gld_dm.std() * btc_dm.std()**2)

# Portfolio coskewness: how does adding BTC affect portfolio skewness?
p5050_ret = simple_monthly_rebalance({"SPY": 0.50, "GLD": 0.50, "BTC": 0.0}, ret_df, tc_rates)
p_btc5 = simple_monthly_rebalance({"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}, ret_df, tc_rates)

tail_results = {
    "coskewness": {
        "BTC_with_SPY_sq": round(coskew_btc_spy, 4),
        "BTC_with_GLD_sq": round(coskew_btc_gld, 4),
        "SPY_with_BTC_sq": round(coskew_spy_btc, 4),
        "GLD_with_BTC_sq": round(coskew_gld_btc, 4),
        "portfolio_skewness_5050": round(p5050_ret.skew(), 4),
        "portfolio_skewness_47_47_5": round(p_btc5.skew(), 4),
    }
}

print(f"    Coskew(BTC, SPY²) = {coskew_btc_spy:.4f}  (BTC crashes when SPY is volatile)")
print(f"    Coskew(BTC, GLD²) = {coskew_btc_gld:.4f}")
print(f"    Coskew(SPY, BTC²) = {coskew_spy_btc:.4f}  (SPY behavior when BTC is volatile)")
print(f"    Portfolio skewness: 50/50={p5050_ret.skew():.4f} → 47.5/47.5/5={p_btc5.skew():.4f}")

# 4b: Conditional drawdowns
print("\n  [4b] Conditional behavior during SPY crashes (>10% drawdown):")

# Find SPY drawdown episodes
cum_spy = (1 + ret_spy).cumprod()
peak_spy = cum_spy.cummax()
dd_spy = (cum_spy - peak_spy) / peak_spy

# Episodes where SPY DD > 10%
crash_mask = dd_spy < -0.10
crash_dates = dd_spy[crash_mask].index

if len(crash_dates) > 0:
    btc_during_crash = ret_btc.loc[crash_dates]
    gld_during_crash = ret_gld.loc[crash_dates]

    # BTC cumulative return during each crash episode
    crash_episodes = []
    in_episode = False
    ep_start = None

    for i in range(len(dd_spy)):
        if dd_spy.iloc[i] < -0.10 and not in_episode:
            in_episode = True
            ep_start = dd_spy.index[i]
        elif dd_spy.iloc[i] >= -0.05 and in_episode:
            in_episode = False
            crash_episodes.append((ep_start, dd_spy.index[i-1]))
    if in_episode:
        crash_episodes.append((ep_start, dd_spy.index[-1]))

    episode_analysis = []
    for ep_s, ep_e in crash_episodes:
        mask = (ret_df.index >= ep_s) & (ret_df.index <= ep_e)
        ep_ret_spy = (1 + ret_spy.loc[mask]).prod() - 1
        ep_ret_gld = (1 + ret_gld.loc[mask]).prod() - 1
        ep_ret_btc = (1 + ret_btc.loc[mask]).prod() - 1

        episode_analysis.append({
            "start": ep_s.strftime("%Y-%m-%d"),
            "end": ep_e.strftime("%Y-%m-%d"),
            "SPY_return": round(ep_ret_spy * 100, 1),
            "GLD_return": round(ep_ret_gld * 100, 1),
            "BTC_return": round(ep_ret_btc * 100, 1),
            "days": mask.sum(),
        })
        print(f"    {ep_s.strftime('%Y-%m')} to {ep_e.strftime('%Y-%m')}: SPY={ep_ret_spy*100:+.1f}%  GLD={ep_ret_gld*100:+.1f}%  BTC={ep_ret_btc*100:+.1f}%  ({mask.sum()}d)")

    tail_results["crash_episodes"] = episode_analysis

    # Correlation during crashes vs normal
    corr_normal = ret_btc[~crash_mask].corr(ret_spy[~crash_mask])
    corr_crash = ret_btc[crash_mask].corr(ret_spy[crash_mask]) if crash_mask.sum() > 10 else np.nan

    tail_results["conditional_correlation"] = {
        "BTC_SPY_normal": round(corr_normal, 4),
        "BTC_SPY_crash": round(corr_crash, 4) if not np.isnan(corr_crash) else "N/A",
        "BTC_GLD_full": round(ret_btc.corr(ret_gld), 4),
    }
    print(f"\n    Correlation BTC-SPY: normal={corr_normal:.3f}  during crashes={corr_crash:.3f}")
    print(f"    Correlation BTC-GLD: {ret_btc.corr(ret_gld):.3f}")

# 4c: Maximum drawdown comparison
print("\n  [4c] Maximum drawdown analysis:")

# Compare MDDs across different allocations
mdd_comparison = {}
for btc_pct in [0, 2, 5, 7, 10, 15, 20]:
    btc_w = btc_pct / 100
    remaining = 1.0 - btc_w
    w = {"SPY": remaining / 2, "GLD": remaining / 2, "BTC": btc_w}
    p = simple_monthly_rebalance(w, ret_df, tc_rates)
    cum = (1 + p).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Worst drawdown date
    worst_date = dd.idxmin()

    mdd_comparison[f"BTC_{btc_pct}pct"] = {
        "mdd": round(mdd * 100, 2),
        "worst_date": worst_date.strftime("%Y-%m-%d"),
    }
    print(f"    BTC={btc_pct}%: MDD={mdd*100:.1f}%  (worst: {worst_date.strftime('%Y-%m-%d')})")

tail_results["mdd_comparison"] = mdd_comparison

# 4d: Tail risk metrics
print("\n  [4d] Tail risk metrics (5th percentile, CVaR):")
for name, ret in [("SPY", ret_spy), ("GLD", ret_gld), ("BTC", ret_btc), ("50/50", p5050_ret), ("47.5/47.5/5", p_btc5)]:
    var_5 = ret.quantile(0.05)
    cvar_5 = ret[ret <= var_5].mean()
    print(f"    {name}: VaR(5%)={var_5*100:.2f}%  CVaR(5%)={cvar_5*100:.2f}%")

    tail_results[f"tail_{name}"] = {
        "VaR_5pct": round(var_5 * 100, 4),
        "CVaR_5pct": round(cvar_5 * 100, 4),
    }

results["tail_risk"] = tail_results

# ============================================================
# 5. ROLLING CORRELATION & REGIME ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[5] Rolling Correlation & Regime Analysis")
print("=" * 70)

# Rolling 252-day correlation
rolling_corr_btc_spy = ret_btc.rolling(252).corr(ret_spy)
rolling_corr_btc_gld = ret_btc.rolling(252).corr(ret_gld)

# Time-varying regime analysis
print("\n  [5a] Rolling 1-year correlation BTC-SPY:")
for year in range(2016, 2027):
    mask = (ret_btc.index >= f"{year}-01-01") & (ret_btc.index < f"{year+1}-01-01")
    if mask.sum() > 60:
        c = ret_btc.loc[mask].corr(ret_spy.loc[mask])
        print(f"    {year}: corr(BTC,SPY) = {c:.3f}")

# Is BTC a genuine diversifier?
print("\n  [5b] Diversification benefit test:")
# Full-period correlations
corr_matrix = ret_df.corr()
print(f"    Full-period correlations:")
print(f"    SPY-GLD: {corr_matrix.loc['SPY','GLD']:.3f}")
print(f"    SPY-BTC: {corr_matrix.loc['SPY','BTC']:.3f}")
print(f"    GLD-BTC: {corr_matrix.loc['GLD','BTC']:.3f}")

# Average correlation over time (non-stationarity check)
regime_data = {
    "full_period_correlations": {
        "SPY_GLD": round(corr_matrix.loc["SPY", "GLD"], 4),
        "SPY_BTC": round(corr_matrix.loc["SPY", "BTC"], 4),
        "GLD_BTC": round(corr_matrix.loc["GLD", "BTC"], 4),
    },
    "yearly_corr_BTC_SPY": {},
}

for year in range(2016, 2027):
    mask = (ret_btc.index >= f"{year}-01-01") & (ret_btc.index < f"{year+1}-01-01")
    if mask.sum() > 60:
        regime_data["yearly_corr_BTC_SPY"][str(year)] = round(
            ret_btc.loc[mask].corr(ret_spy.loc[mask]), 4
        )

results["regime_analysis"] = regime_data

# ============================================================
# 6. RECENCY BIAS TEST
# ============================================================
print("\n" + "=" * 70)
print("[6] Recency Bias Test")
print("=" * 70)

# Rolling 3-year Sharpe comparison
print("\n  Rolling 3-year Sharpe (47.5/47.5/5 vs 50/50):")
window = 756  # ~3 years
rolling_sharpe_diff = []

for i in range(window, len(ret_df), 63):  # Check every quarter
    sub = ret_df.iloc[i-window:i]
    p1 = simple_monthly_rebalance({"SPY": 0.50, "GLD": 0.50, "BTC": 0.0}, sub, tc_rates)
    p2 = simple_monthly_rebalance({"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}, sub, tc_rates)

    s1 = p1.mean() / p1.std() * np.sqrt(252)
    s2 = p2.mean() / p2.std() * np.sqrt(252)

    end_date = sub.index[-1].strftime("%Y-%m-%d")
    rolling_sharpe_diff.append({
        "end_date": end_date,
        "sharpe_5050": round(s1, 3),
        "sharpe_47_47_5": round(s2, 3),
        "diff": round(s2 - s1, 3),
        "btc_wins": s2 > s1,
    })

n_btc_wins = sum(1 for r in rolling_sharpe_diff if r["btc_wins"])
n_total = len(rolling_sharpe_diff)
print(f"    BTC allocation wins in {n_btc_wins}/{n_total} rolling 3-year windows ({n_btc_wins/n_total*100:.0f}%)")

# Show a few key windows
for r in rolling_sharpe_diff[-8:]:
    w_l = "✓" if r["btc_wins"] else "✗"
    print(f"    ending {r['end_date']}: 50/50={r['sharpe_5050']:.3f}  47.5/47.5/5={r['sharpe_47_47_5']:.3f}  diff={r['diff']:+.3f} {w_l}")

recency_results = {
    "rolling_3yr_btc_win_rate": f"{n_btc_wins}/{n_total} ({n_btc_wins/n_total*100:.0f}%)",
    "rolling_windows": rolling_sharpe_diff,
}
results["recency_bias"] = recency_results

# ============================================================
# 7. FINAL VERDICT
# ============================================================
print("\n" + "=" * 70)
print("[7] FINAL VERDICT")
print("=" * 70)

# Comprehensive summary
full_5050 = simple_monthly_rebalance({"SPY": 0.50, "GLD": 0.50, "BTC": 0.0}, ret_df, tc_rates)
full_47475 = simple_monthly_rebalance({"SPY": 0.475, "GLD": 0.475, "BTC": 0.05}, ret_df, tc_rates)

m_full_base = portfolio_metrics(full_5050, "50/50 Baseline")
m_full_btc = portfolio_metrics(full_47475, "47.5/47.5/5 BTC")

final_boot = bootstrap_sharpe_diff(full_47475, full_5050, n_boot=10000)

print(f"\n  Baseline (50/50 SPY/GLD):")
print(f"    Sharpe={m_full_base['sharpe']:.3f}  Return={m_full_base['ann_return']:.1f}%  Vol={m_full_base['ann_vol']:.1f}%  MDD={m_full_base['mdd']:.1f}%")
print(f"    t-stat={m_full_base['t_stat']:.2f}")

print(f"\n  BTC 5% (47.5/47.5/5):")
print(f"    Sharpe={m_full_btc['sharpe']:.3f}  Return={m_full_btc['ann_return']:.1f}%  Vol={m_full_btc['ann_vol']:.1f}%  MDD={m_full_btc['mdd']:.1f}%")
print(f"    t-stat={m_full_btc['t_stat']:.2f}")

print(f"\n  Bootstrap Sharpe diff test:")
print(f"    ΔSharpe = {final_boot['sharpe_diff']:.4f}")
print(f"    p-value = {final_boot['p_value']:.4f}")
print(f"    95% CI = {final_boot['ci_95']}")

# Verdict logic
sub_wins = sum(1 for k, v in sub_period_results.items()
               if v["btc_5pct"]["sharpe"] > v["baseline"]["sharpe"])
sub_total = len(sub_period_results)

verdict_points = []
if final_boot["p_value"] < 0.05:
    verdict_points.append("Full-period Sharpe difference IS statistically significant")
else:
    verdict_points.append("Full-period Sharpe difference is NOT statistically significant")

verdict_points.append(f"BTC allocation wins in {sub_wins}/{sub_total} sub-periods")
verdict_points.append(f"BTC allocation wins in {n_btc_wins}/{n_total} rolling 3-year windows")

# Check if recent-only
pre2020 = sub_period_results.get("Pre-2020 (2015-2019)", {})
if pre2020:
    if pre2020["btc_5pct"]["sharpe"] > pre2020["baseline"]["sharpe"]:
        verdict_points.append("Pre-2020: BTC helps (not just recent bull run)")
    else:
        verdict_points.append("Pre-2020: BTC HURTS (possibly driven by recent bull run)")

# Tail risk
skew_diff = p_btc5.skew() - p5050_ret.skew()
verdict_points.append(f"Portfolio skewness change: {skew_diff:+.4f} (negative = worse tail risk)")

# Correlation concern
corr_btc_spy_full = ret_btc.corr(ret_spy)
if corr_btc_spy_full > 0.3:
    verdict_points.append(f"WARNING: BTC-SPY correlation {corr_btc_spy_full:.2f} is high (rising since 2020)")

is_genuine = (
    sub_wins >= sub_total * 0.6  # Wins in most sub-periods
    and n_btc_wins / n_total >= 0.5  # Wins in most rolling windows
    and final_boot["p_value"] < 0.10  # At least marginally significant
)

if is_genuine:
    verdict = "5% BTC 是合理的分散投資，但效果主要來自報酬增強而非風險降低"
else:
    verdict = "5% BTC 的統計優勢不夠穩健，可能受近期牛市驅動"

print(f"\n  Verdict Points:")
for v in verdict_points:
    print(f"    • {v}")

print(f"\n  FINAL VERDICT: {verdict}")

results["verdict"] = {
    "conclusion": verdict,
    "points": verdict_points,
    "is_genuine_diversifier": is_genuine,
    "full_period_baseline": m_full_base,
    "full_period_btc5": m_full_btc,
    "bootstrap_test": final_boot,
}

# ============================================================
# 8. SAVE RESULTS
# ============================================================
output_path = Path("/Users/yhlai0911/Dropbox/自我研究波動預測模型/storage/experiments/btc_allocation_deep_dive.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

# Clean up non-serializable items
def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(i) for i in obj]
    elif isinstance(obj, (np.floating, np.integer)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    return obj

results_clean = clean_for_json(results)
results_clean["metadata"] = {
    "experiment_id": "K64_followup_btc_deep_dive",
    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "data_range": f"{common_ret[0].strftime('%Y-%m-%d')} to {common_ret[-1].strftime('%Y-%m-%d')}",
    "n_days": len(common_ret),
    "tc_rates": {"SPY": "0.05%", "GLD": "0.05%", "BTC": "0.10%"},
    "rebalance": "monthly",
    "weights": "lagged",
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results_clean, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to: {output_path}")
print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
