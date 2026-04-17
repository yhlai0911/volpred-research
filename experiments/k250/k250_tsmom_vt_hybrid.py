#!/usr/bin/env python3
"""
K250: TSMOM+VT Hybrid — The Best of Both Worlds?
==================================================
[提出: 用戶, 執行: Claude]

Background:
  - TSMOM 6_1 has good Sharpe (~0.79) but bad MDD (~-21.8%)
  - 50/50+VT has lower Sharpe but great MDD (~-10.8%)
  - Can we combine TSMOM's alpha with VT's risk management?

Data: SPY, GLD, TLT, VIX daily from yfinance. 2005-2024.

Methodology:
  1. Base: TSMOM 6_1 on SPY/GLD/TLT (multi-asset time-series momentum)
  2. VT overlay variants:
     a. Simple VT: multiply TSMOM weights by min(1, 12/VIX)
     b. Risk budget: TSMOM decides WHAT, VT decides HOW MUCH
     c. Conditional: TSMOM when VIX<20, switch to 50/50+VT when VIX>=20
     d. Blended: 60% TSMOM + 40% 50/50+VT (static blend)
  3. For each variant: Sharpe, MDD, Calmar, Sortino, DM test, Harvey threshold
  4. 5-period cross-OOS MANDATORY
  5. TX cost at 10bps

Output: Full results JSON + console summary.
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

# ════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════
ASSETS = ["SPY", "GLD", "TLT"]
START_DATE = "2004-01-01"  # extra history for TSMOM lookback
END_DATE = "2024-12-31"
TSMOM_LOOKBACK = 126  # 6 months (~126 trading days)
TSMOM_HOLD = 21       # 1 month hold period
VIX_THRESHOLD = 12.0  # for 12/VIX scaling
VIX_REGIME_THRESHOLD = 20.0  # for conditional switching
TX_COST = 0.0010  # 10 bps per trade
RF_ANNUAL = 0.04
N_BOOTSTRAP = 10000

# Cross-OOS periods (5 non-overlapping)
OOS_PERIODS = {
    "OOS1_2005_2008": ("2005-01-01", "2008-12-31"),
    "OOS2_2009_2012": ("2009-01-01", "2012-12-31"),
    "OOS3_2013_2016": ("2013-01-01", "2016-12-31"),
    "OOS4_2017_2020": ("2017-01-01", "2020-12-31"),
    "OOS5_2021_2024": ("2021-01-01", "2024-12-31"),
}

OUTPUT_PATH = Path(__file__).parent.parent / "storage" / "experiments" / "k250_tsmom_vt_hybrid.json"


def download_data():
    """Download all needed data from yfinance."""
    print("=" * 70)
    print("K250: TSMOM+VT Hybrid — Downloading Data")
    print("=" * 70)

    prices = {}
    for ticker in ASSETS + ["^VIX"]:
        label = ticker.replace("^", "")
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[label] = df["Close"].dropna()
        print(f"  {label}: {len(prices[label])} days, "
              f"{prices[label].index[0].strftime('%Y-%m-%d')} to "
              f"{prices[label].index[-1].strftime('%Y-%m-%d')}")

    # SHY for cash returns
    df = yf.download("SHY", start=START_DATE, end=END_DATE, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prices["SHY"] = df["Close"].dropna()
    print(f"  SHY: {len(prices['SHY'])} days")

    return prices


def align_data(prices):
    """Align all price series to common dates."""
    common_idx = prices["SPY"].index
    for key in prices:
        common_idx = common_idx.intersection(prices[key].index)
    common_idx = common_idx.sort_values()

    aligned = {}
    for key in prices:
        aligned[key] = prices[key].reindex(common_idx).ffill()

    returns = {}
    for asset in ASSETS:
        returns[asset] = aligned[asset].pct_change().dropna()

    returns["SHY"] = aligned["SHY"].pct_change().dropna()

    # Align everything to common return dates
    ret_idx = returns["SPY"].index
    for key in returns:
        ret_idx = ret_idx.intersection(returns[key].index)
    ret_idx = ret_idx.sort_values()

    for key in returns:
        returns[key] = returns[key].reindex(ret_idx)

    vix = aligned["VIX"].reindex(ret_idx).ffill()

    print(f"\n  Aligned data: {ret_idx[0].strftime('%Y-%m-%d')} to "
          f"{ret_idx[-1].strftime('%Y-%m-%d')}, {len(ret_idx)} days")

    return returns, vix, ret_idx


# ════════════════════════════════════════════════════════════════
# Strategy Implementations
# ════════════════════════════════════════════════════════════════

def compute_tsmom_signals(returns, lookback=126):
    """
    Compute TSMOM 6_1 signals for each asset.
    Signal = sign of past `lookback` day cumulative return.
    +1 = long, -1 = short (we use 0 = flat for long-only version).
    """
    signals = {}
    for asset in ASSETS:
        cum_ret = returns[asset].rolling(lookback).sum()
        # Long-only TSMOM: +1 if positive momentum, 0 if negative
        sig = (cum_ret > 0).astype(float)
        signals[asset] = sig
    return signals


def monthly_rebalance_dates(dates):
    """Return indices of month-end rebalance dates."""
    months = pd.Series(dates).dt.to_period("M")
    mask = months != months.shift(-1)
    mask.iloc[-1] = True
    mask.index = dates
    return mask


def strategy_buyhold_equal(returns, vix, dates):
    """Benchmark: Equal-weight buy-and-hold SPY/GLD/TLT, no VT."""
    n = len(ASSETS)
    w = 1.0 / n
    port_ret = sum(w * returns[a] for a in ASSETS)
    return port_ret, f"Buy&Hold Equal 1/{n}"


def strategy_5050_vt(returns, vix, dates):
    """50/50 SPY/GLD with 12/VIX VT scaling + SHY cash. Monthly rebalance."""
    rebal = monthly_rebalance_dates(dates)
    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None

    current_w_spy = 0.5
    current_w_gld = 0.5
    current_vt = 1.0

    for i, date in enumerate(dates):
        if i == 0:
            continue

        # Update VT weight on rebalance
        if rebal.iloc[i - 1]:
            vix_val = vix.iloc[i - 1]
            current_vt = min(1.0, VIX_THRESHOLD / vix_val) if vix_val > 0 else 1.0

        w_spy = 0.5 * current_vt
        w_gld = 0.5 * current_vt
        w_cash = 1.0 - w_spy - w_gld

        new_weights = np.array([w_spy, w_gld, w_cash])

        # Transaction costs
        tc = 0.0
        if prev_weights is not None and rebal.iloc[i - 1]:
            tc = TX_COST * np.sum(np.abs(new_weights - prev_weights))

        port_ret.iloc[i] = (w_spy * returns["SPY"].iloc[i]
                            + w_gld * returns["GLD"].iloc[i]
                            + w_cash * returns["SHY"].iloc[i]
                            - tc)
        prev_weights = new_weights

    return port_ret, "50/50 SPY/GLD + VT"


def strategy_tsmom(returns, vix, dates):
    """TSMOM 6_1: Equal-weight across assets with positive 6m momentum. Monthly rebalance."""
    signals = compute_tsmom_signals(returns, TSMOM_LOOKBACK)
    rebal = monthly_rebalance_dates(dates)
    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None

    current_asset_weights = {a: 1.0 / len(ASSETS) for a in ASSETS}  # default equal
    current_signals = {a: 1.0 for a in ASSETS}

    for i, date in enumerate(dates):
        if i == 0:
            continue

        # Update signals on rebalance
        if rebal.iloc[i - 1]:
            active_count = 0
            for a in ASSETS:
                sig = signals[a].iloc[i - 1] if not np.isnan(signals[a].iloc[i - 1]) else 0.0
                current_signals[a] = sig
                active_count += sig

            # Equal weight among active assets
            if active_count > 0:
                for a in ASSETS:
                    current_asset_weights[a] = current_signals[a] / active_count
            else:
                # All negative momentum → go to cash
                for a in ASSETS:
                    current_asset_weights[a] = 0.0

        weights_arr = np.array([current_asset_weights[a] for a in ASSETS])
        w_cash = max(0.0, 1.0 - weights_arr.sum())
        full_weights = np.append(weights_arr, w_cash)

        # Transaction costs
        tc = 0.0
        if prev_weights is not None and rebal.iloc[i - 1]:
            tc = TX_COST * np.sum(np.abs(full_weights - prev_weights))

        daily_ret = sum(current_asset_weights[a] * returns[a].iloc[i] for a in ASSETS)
        daily_ret += w_cash * returns["SHY"].iloc[i]
        port_ret.iloc[i] = daily_ret - tc

        prev_weights = full_weights.copy()

    return port_ret, "TSMOM 6_1"


def strategy_tsmom_simple_vt(returns, vix, dates):
    """
    Variant A: Simple VT overlay on TSMOM.
    TSMOM decides WHAT to hold, VT scales ALL positions by min(1, 12/VIX).
    Remainder goes to SHY.
    """
    signals = compute_tsmom_signals(returns, TSMOM_LOOKBACK)
    rebal = monthly_rebalance_dates(dates)
    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None

    current_asset_weights = {a: 0.0 for a in ASSETS}
    current_vt = 1.0

    for i, date in enumerate(dates):
        if i == 0:
            continue

        if rebal.iloc[i - 1]:
            # TSMOM signals
            active_count = 0
            sigs = {}
            for a in ASSETS:
                sig = signals[a].iloc[i - 1] if not np.isnan(signals[a].iloc[i - 1]) else 0.0
                sigs[a] = sig
                active_count += sig

            # VT scaling
            vix_val = vix.iloc[i - 1]
            current_vt = min(1.0, VIX_THRESHOLD / vix_val) if vix_val > 0 else 1.0

            if active_count > 0:
                for a in ASSETS:
                    current_asset_weights[a] = (sigs[a] / active_count) * current_vt
            else:
                for a in ASSETS:
                    current_asset_weights[a] = 0.0

        weights_arr = np.array([current_asset_weights[a] for a in ASSETS])
        w_cash = max(0.0, 1.0 - weights_arr.sum())
        full_weights = np.append(weights_arr, w_cash)

        tc = 0.0
        if prev_weights is not None and rebal.iloc[i - 1]:
            tc = TX_COST * np.sum(np.abs(full_weights - prev_weights))

        daily_ret = sum(current_asset_weights[a] * returns[a].iloc[i] for a in ASSETS)
        daily_ret += w_cash * returns["SHY"].iloc[i]
        port_ret.iloc[i] = daily_ret - tc

        prev_weights = full_weights.copy()

    return port_ret, "TSMOM + Simple VT"


def strategy_tsmom_risk_budget(returns, vix, dates):
    """
    Variant B: Risk Budget.
    TSMOM decides WHAT to hold (asset selection).
    VT decides HOW MUCH total equity exposure: equity_pct = min(1, 12/VIX).
    Active assets get equal share of the equity budget.
    """
    signals = compute_tsmom_signals(returns, TSMOM_LOOKBACK)
    rebal = monthly_rebalance_dates(dates)
    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None

    current_asset_weights = {a: 0.0 for a in ASSETS}

    for i, date in enumerate(dates):
        if i == 0:
            continue

        if rebal.iloc[i - 1]:
            active_count = 0
            sigs = {}
            for a in ASSETS:
                sig = signals[a].iloc[i - 1] if not np.isnan(signals[a].iloc[i - 1]) else 0.0
                sigs[a] = sig
                active_count += sig

            vix_val = vix.iloc[i - 1]
            equity_budget = min(1.0, VIX_THRESHOLD / vix_val) if vix_val > 0 else 1.0

            if active_count > 0:
                for a in ASSETS:
                    current_asset_weights[a] = (sigs[a] / active_count) * equity_budget
            else:
                for a in ASSETS:
                    current_asset_weights[a] = 0.0

        weights_arr = np.array([current_asset_weights[a] for a in ASSETS])
        w_cash = max(0.0, 1.0 - weights_arr.sum())
        full_weights = np.append(weights_arr, w_cash)

        tc = 0.0
        if prev_weights is not None and rebal.iloc[i - 1]:
            tc = TX_COST * np.sum(np.abs(full_weights - prev_weights))

        daily_ret = sum(current_asset_weights[a] * returns[a].iloc[i] for a in ASSETS)
        daily_ret += w_cash * returns["SHY"].iloc[i]
        port_ret.iloc[i] = daily_ret - tc

        prev_weights = full_weights.copy()

    return port_ret, "TSMOM + Risk Budget VT"


def strategy_conditional_switch(returns, vix, dates):
    """
    Variant C: Conditional switching.
    When VIX < 20: use TSMOM (momentum-driven allocation).
    When VIX >= 20: switch to 50/50 SPY/GLD + VT (defensive).
    """
    signals = compute_tsmom_signals(returns, TSMOM_LOOKBACK)
    rebal = monthly_rebalance_dates(dates)
    port_ret = pd.Series(0.0, index=dates)
    prev_weights = None

    current_asset_weights = {a: 0.0 for a in ASSETS}
    w_cash_current = 1.0

    for i, date in enumerate(dates):
        if i == 0:
            continue

        if rebal.iloc[i - 1]:
            vix_val = vix.iloc[i - 1]

            if vix_val < VIX_REGIME_THRESHOLD:
                # Low VIX regime: use TSMOM
                active_count = 0
                sigs = {}
                for a in ASSETS:
                    sig = signals[a].iloc[i - 1] if not np.isnan(signals[a].iloc[i - 1]) else 0.0
                    sigs[a] = sig
                    active_count += sig

                if active_count > 0:
                    for a in ASSETS:
                        current_asset_weights[a] = sigs[a] / active_count
                else:
                    for a in ASSETS:
                        current_asset_weights[a] = 0.0
            else:
                # High VIX regime: switch to 50/50 SPY/GLD + VT
                vt_scale = min(1.0, VIX_THRESHOLD / vix_val) if vix_val > 0 else 1.0
                current_asset_weights["SPY"] = 0.5 * vt_scale
                current_asset_weights["GLD"] = 0.5 * vt_scale
                current_asset_weights["TLT"] = 0.0

        weights_arr = np.array([current_asset_weights[a] for a in ASSETS])
        w_cash = max(0.0, 1.0 - weights_arr.sum())
        full_weights = np.append(weights_arr, w_cash)

        tc = 0.0
        if prev_weights is not None and rebal.iloc[i - 1]:
            tc = TX_COST * np.sum(np.abs(full_weights - prev_weights))

        daily_ret = sum(current_asset_weights[a] * returns[a].iloc[i] for a in ASSETS)
        daily_ret += w_cash * returns["SHY"].iloc[i]
        port_ret.iloc[i] = daily_ret - tc

        prev_weights = full_weights.copy()

    return port_ret, "Conditional TSMOM/VT Switch"


def strategy_blended(returns, vix, dates):
    """
    Variant D: 60% TSMOM + 40% 50/50+VT (static blend).
    Each component computed independently, then blended.
    """
    # Get individual strategy returns
    tsmom_ret, _ = strategy_tsmom(returns, vix, dates)
    vt5050_ret, _ = strategy_5050_vt(returns, vix, dates)

    port_ret = 0.6 * tsmom_ret + 0.4 * vt5050_ret
    return port_ret, "60% TSMOM + 40% 50/50 VT"


# ════════════════════════════════════════════════════════════════
# Evaluation Functions
# ════════════════════════════════════════════════════════════════

def compute_metrics(returns_series, rf_daily=None):
    """Compute Sharpe, MDD, Calmar, Sortino for a return series."""
    if rf_daily is None:
        rf_daily = RF_ANNUAL / 252

    r = returns_series.dropna()
    if len(r) < 50:
        return {"sharpe": np.nan, "mdd": np.nan, "calmar": np.nan,
                "sortino": np.nan, "ann_return": np.nan, "ann_vol": np.nan,
                "n_days": len(r)}

    excess = r - rf_daily
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = excess.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0.0

    # Sortino
    downside = r[r < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 0.001
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Sharpe t-stat (for Harvey threshold)
    n_years = len(r) / 252
    sharpe_se = 1.0 / np.sqrt(n_years) if n_years > 0 else np.inf
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0.0

    # Turnover (approximate from weight changes encoded in TC)
    # We count TC impact instead
    total_tc = 0  # already embedded in returns

    return {
        "sharpe": round(sharpe, 4),
        "sharpe_t": round(sharpe_t, 2),
        "harvey_pass": sharpe_t > 3.0,
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "n_days": len(r),
        "n_years": round(n_years, 1),
    }


def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test comparing two return series.
    H0: strategies have equal expected return.
    We test: d_t = r1_t - r2_t, is mean(d) significantly different from 0?
    Returns t-stat and p-value (two-sided).
    """
    d = e1 - e2
    d = d.dropna()
    if len(d) < 30:
        return np.nan, np.nan

    mean_d = d.mean()
    # Newey-West HAC standard error (lag = h-1 for h-step ahead)
    n = len(d)
    gamma_0 = np.var(d, ddof=1)

    # Simple HAC with bandwidth = h
    bandwidth = max(1, int(np.ceil(n ** (1/3))))
    var_d = gamma_0
    for k in range(1, bandwidth + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        weight = 1 - k / (bandwidth + 1)
        var_d += 2 * weight * gamma_k

    se = np.sqrt(var_d / n)
    if se < 1e-12:
        return 0.0, 1.0

    t_stat = mean_d / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return round(t_stat, 3), round(p_val, 4)


def bootstrap_mdd_test(ret1, ret2, n_boot=N_BOOTSTRAP):
    """
    Bootstrap test: is MDD difference significant?
    H0: MDD(strategy1) = MDD(strategy2).
    Returns p-value for H_a: MDD(strategy1) > MDD(strategy2) (i.e., strategy1 has LESS drawdown).
    """
    r1 = ret1.dropna().values
    r2 = ret2.dropna().values
    n = min(len(r1), len(r2))
    r1, r2 = r1[:n], r2[:n]

    def mdd(r):
        cum = np.cumprod(1 + r)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        return dd.min()

    obs_diff = mdd(r1) - mdd(r2)  # positive = strategy1 has LESS drawdown (better)

    boot_diffs = np.zeros(n_boot)
    rng = np.random.default_rng(42)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot_diffs[b] = mdd(r1[idx]) - mdd(r2[idx])

    # p-value: proportion of bootstrap samples where diff <= 0 (strategy1 NOT better)
    p_val = np.mean(boot_diffs <= 0)
    return round(obs_diff, 4), round(p_val, 4)


# ════════════════════════════════════════════════════════════════
# Main Execution
# ════════════════════════════════════════════════════════════════

def run_experiment():
    """Run the full K250 experiment."""
    prices = download_data()
    returns, vix, dates = align_data(prices)

    # Define all strategies
    strategies = {
        "buyhold_equal": strategy_buyhold_equal,
        "5050_vt": strategy_5050_vt,
        "tsmom_6_1": strategy_tsmom,
        "A_tsmom_simple_vt": strategy_tsmom_simple_vt,
        "B_tsmom_risk_budget": strategy_tsmom_risk_budget,
        "C_conditional_switch": strategy_conditional_switch,
        "D_blended_60_40": strategy_blended,
    }

    # ── Full Sample Results ──
    print("\n" + "=" * 70)
    print("FULL SAMPLE RESULTS")
    print("=" * 70)

    full_results = {}
    full_returns = {}

    for key, fn in strategies.items():
        ret, name = fn(returns, vix, dates)
        metrics = compute_metrics(ret)
        full_results[key] = {"name": name, "metrics": metrics}
        full_returns[key] = ret
        print(f"\n  {name}:")
        print(f"    Sharpe={metrics['sharpe']:.3f}  (t={metrics['sharpe_t']:.1f}, "
              f"Harvey={'PASS' if metrics['harvey_pass'] else 'FAIL'})")
        print(f"    MDD={metrics['mdd']:.1%}  Calmar={metrics['calmar']:.3f}  "
              f"Sortino={metrics['sortino']:.3f}")
        print(f"    Ann Return={metrics['ann_return']:.1%}  "
              f"Ann Vol={metrics['ann_vol']:.1%}  N={metrics['n_days']}")

    # ── DM Tests vs TSMOM and vs 50/50+VT ──
    print("\n" + "=" * 70)
    print("DM TESTS (return difference significance)")
    print("=" * 70)

    dm_results = {}
    hybrid_keys = ["A_tsmom_simple_vt", "B_tsmom_risk_budget",
                   "C_conditional_switch", "D_blended_60_40"]

    for key in hybrid_keys:
        name = full_results[key]["name"]

        # vs TSMOM
        t1, p1 = dm_test(full_returns[key], full_returns["tsmom_6_1"])
        # vs 50/50+VT
        t2, p2 = dm_test(full_returns[key], full_returns["5050_vt"])

        dm_results[key] = {
            "vs_tsmom": {"t_stat": t1, "p_value": p1},
            "vs_5050_vt": {"t_stat": t2, "p_value": p2},
        }

        print(f"\n  {name}:")
        print(f"    vs TSMOM:    t={t1:+.3f}, p={p1:.4f} {'*' if p1 < 0.05 else ''}")
        print(f"    vs 50/50+VT: t={t2:+.3f}, p={p2:.4f} {'*' if p2 < 0.05 else ''}")

    # ── Bootstrap MDD Tests ──
    print("\n" + "=" * 70)
    print("BOOTSTRAP MDD TESTS (drawdown improvement)")
    print("=" * 70)

    mdd_results = {}
    for key in hybrid_keys:
        name = full_results[key]["name"]

        # Compare hybrid's MDD vs TSMOM (positive diff = hybrid better)
        diff_tsmom, p_tsmom = bootstrap_mdd_test(
            full_returns[key], full_returns["tsmom_6_1"])
        # Compare hybrid's MDD vs 50/50+VT
        diff_5050, p_5050 = bootstrap_mdd_test(
            full_returns[key], full_returns["5050_vt"])

        mdd_results[key] = {
            "vs_tsmom": {"mdd_diff": diff_tsmom, "p_value": p_tsmom},
            "vs_5050_vt": {"mdd_diff": diff_5050, "p_value": p_5050},
        }

        print(f"\n  {name}:")
        print(f"    vs TSMOM MDD:    diff={diff_tsmom:+.1%}, p={p_tsmom:.4f} "
              f"{'*' if p_tsmom < 0.05 else ''}")
        print(f"    vs 50/50+VT MDD: diff={diff_5050:+.1%}, p={p_5050:.4f} "
              f"{'*' if p_5050 < 0.05 else ''}")

    # ── 5-Period Cross-OOS Validation ──
    print("\n" + "=" * 70)
    print("5-PERIOD CROSS-OOS VALIDATION")
    print("=" * 70)

    oos_results = {}
    for period_name, (start, end) in OOS_PERIODS.items():
        print(f"\n  --- {period_name} ({start} to {end}) ---")
        oos_mask = (dates >= start) & (dates <= end)
        if oos_mask.sum() < 50:
            print(f"    Insufficient data ({oos_mask.sum()} days), skipping")
            continue

        oos_results[period_name] = {}
        for key, fn in strategies.items():
            # We need to recompute returns for the OOS period
            # But signals are computed over full history, so we just slice
            ret_full = full_returns[key]
            ret_oos = ret_full[oos_mask]
            metrics = compute_metrics(ret_oos)
            oos_results[period_name][key] = {
                "name": full_results[key]["name"],
                "metrics": metrics,
            }

        # Print OOS comparison table
        print(f"    {'Strategy':<32} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
        print(f"    {'-'*32} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
        for key in strategies:
            m = oos_results[period_name][key]["metrics"]
            name = oos_results[period_name][key]["name"][:32]
            print(f"    {name:<32} {m['sharpe']:>8.3f} {m['mdd']:>7.1%} "
                  f"{m['calmar']:>8.3f} {m['sortino']:>8.3f}")

    # ── Cross-OOS Summary: Win Rate ──
    print("\n" + "=" * 70)
    print("CROSS-OOS WIN RATE SUMMARY")
    print("=" * 70)

    win_counts_sharpe = {k: 0 for k in hybrid_keys}
    win_counts_mdd = {k: 0 for k in hybrid_keys}
    n_periods = len(oos_results)

    for period_name in oos_results:
        for key in hybrid_keys:
            hybrid_m = oos_results[period_name][key]["metrics"]
            tsmom_m = oos_results[period_name]["tsmom_6_1"]["metrics"]
            vt5050_m = oos_results[period_name]["5050_vt"]["metrics"]

            # Better Sharpe than TSMOM?
            if hybrid_m["sharpe"] > tsmom_m["sharpe"]:
                win_counts_sharpe[key] += 0.5
            # Better Sharpe than 50/50+VT?
            if hybrid_m["sharpe"] > vt5050_m["sharpe"]:
                win_counts_sharpe[key] += 0.5

            # Better MDD than TSMOM?
            if hybrid_m["mdd"] > tsmom_m["mdd"]:  # less negative = better
                win_counts_mdd[key] += 0.5
            # Better MDD than 50/50+VT?
            if hybrid_m["mdd"] > vt5050_m["mdd"]:
                win_counts_mdd[key] += 0.5

    for key in hybrid_keys:
        name = full_results[key]["name"]
        print(f"  {name}:")
        print(f"    Sharpe win rate vs (TSMOM + 50/50+VT): "
              f"{win_counts_sharpe[key]}/{n_periods} = {win_counts_sharpe[key]/n_periods:.0%}")
        print(f"    MDD win rate vs (TSMOM + 50/50+VT):    "
              f"{win_counts_mdd[key]}/{n_periods} = {win_counts_mdd[key]/n_periods:.0%}")

    # ── Key Question Assessment ──
    print("\n" + "=" * 70)
    print("KEY QUESTION: Can we get TSMOM Sharpe with 50/50+VT MDD protection?")
    print("=" * 70)

    tsmom_sharpe = full_results["tsmom_6_1"]["metrics"]["sharpe"]
    vt_mdd = full_results["5050_vt"]["metrics"]["mdd"]

    for key in hybrid_keys:
        name = full_results[key]["name"]
        m = full_results[key]["metrics"]
        sharpe_pct = m["sharpe"] / tsmom_sharpe * 100 if tsmom_sharpe != 0 else 0
        mdd_vs_vt = m["mdd"] / vt_mdd * 100 if vt_mdd != 0 else 0

        achieves_sharpe = m["sharpe"] >= tsmom_sharpe * 0.9  # within 90% of TSMOM
        achieves_mdd = m["mdd"] >= vt_mdd * 1.1  # within 110% of 50/50+VT (less negative)

        verdict = "YES!" if (achieves_sharpe and achieves_mdd) else "NO"

        print(f"\n  {name}:")
        print(f"    Sharpe: {m['sharpe']:.3f} ({sharpe_pct:.0f}% of TSMOM's {tsmom_sharpe:.3f})")
        print(f"    MDD:    {m['mdd']:.1%} ({mdd_vs_vt:.0f}% of 50/50+VT's {vt_mdd:.1%})")
        print(f"    Verdict: {verdict} {'(Sharpe OK)' if achieves_sharpe else '(Sharpe too low)'} "
              f"{'(MDD OK)' if achieves_mdd else '(MDD too high)'}")

    # ── Save Results ──
    results_json = {
        "experiment": "K250",
        "title": "TSMOM+VT Hybrid — The Best of Both Worlds?",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, TLT, VIX, SHY)",
        "data_period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        "n_days": len(dates),
        "parameters": {
            "tsmom_lookback": TSMOM_LOOKBACK,
            "tsmom_hold": TSMOM_HOLD,
            "vix_threshold": VIX_THRESHOLD,
            "vix_regime_threshold": VIX_REGIME_THRESHOLD,
            "tx_cost_bps": TX_COST * 10000,
            "rf_annual": RF_ANNUAL,
            "n_bootstrap": N_BOOTSTRAP,
            "assets": ASSETS,
        },
        "full_sample": {k: v for k, v in full_results.items()},
        "dm_tests": dm_results,
        "mdd_bootstrap": mdd_results,
        "cross_oos": oos_results,
        "cross_oos_win_rates": {
            key: {
                "sharpe_wins": win_counts_sharpe[key],
                "mdd_wins": win_counts_mdd[key],
                "n_periods": n_periods,
            }
            for key in hybrid_keys
        },
        "conclusion": {},  # filled below
    }

    # Determine best hybrid
    best_key = None
    best_score = -999
    for key in hybrid_keys:
        m = full_results[key]["metrics"]
        # Score: normalized Sharpe + normalized MDD improvement
        sharpe_norm = m["sharpe"] / max(tsmom_sharpe, 0.001)
        mdd_norm = m["mdd"] / min(vt_mdd, -0.001)  # closer to 1 = closer to 50/50+VT MDD
        score = sharpe_norm * 0.5 + (1 / max(mdd_norm, 0.001)) * 0.5
        if score > best_score:
            best_score = score
            best_key = key

    best_m = full_results[best_key]["metrics"]
    best_name = full_results[best_key]["name"]

    results_json["conclusion"] = {
        "best_hybrid": best_key,
        "best_hybrid_name": best_name,
        "best_sharpe": best_m["sharpe"],
        "best_mdd": best_m["mdd"],
        "best_calmar": best_m["calmar"],
        "tsmom_sharpe": tsmom_sharpe,
        "tsmom_mdd": full_results["tsmom_6_1"]["metrics"]["mdd"],
        "vt5050_sharpe": full_results["5050_vt"]["metrics"]["sharpe"],
        "vt5050_mdd": vt_mdd,
        "achieves_goal": (best_m["sharpe"] >= tsmom_sharpe * 0.9 and
                          best_m["mdd"] >= vt_mdd * 1.1),
        "harvey_pass": best_m.get("harvey_pass", False),
        "dm_vs_tsmom": dm_results.get(best_key, {}).get("vs_tsmom", {}),
        "dm_vs_5050vt": dm_results.get(best_key, {}).get("vs_5050_vt", {}),
    }

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {OUTPUT_PATH}")

    # ── Final Summary ──
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"\n  Best hybrid strategy: {best_name}")
    print(f"  Sharpe:  {best_m['sharpe']:.3f} (TSMOM: {tsmom_sharpe:.3f}, "
          f"50/50+VT: {full_results['5050_vt']['metrics']['sharpe']:.3f})")
    print(f"  MDD:     {best_m['mdd']:.1%} (TSMOM: {full_results['tsmom_6_1']['metrics']['mdd']:.1%}, "
          f"50/50+VT: {vt_mdd:.1%})")
    print(f"  Calmar:  {best_m['calmar']:.3f}")
    print(f"  Sortino: {best_m['sortino']:.3f}")
    print(f"  Harvey:  {'PASS' if best_m.get('harvey_pass') else 'FAIL'} "
          f"(t={best_m.get('sharpe_t', 0):.1f})")

    goal = results_json["conclusion"]["achieves_goal"]
    print(f"\n  Goal achieved (TSMOM Sharpe + VT MDD): {'YES' if goal else 'NO'}")
    if goal:
        print("  >>> CANDIDATE FOR NEW STRATEGY LAUNCH <<<")
    else:
        print("  >>> Hybrid does NOT achieve both targets simultaneously <<<")

    print("\n" + "=" * 70)
    return results_json


if __name__ == "__main__":
    results = run_experiment()
