#!/usr/bin/env python3
"""
K733: Regime-Dependent Rebalancing Frequency
=============================================
Hypothesis: Adaptive rebalancing (daily in high-vol, monthly in low-vol)
            improves risk-adjusted returns vs fixed monthly rebalancing.

Prior work:
  K48/K65/K75: Monthly rebalancing optimal for VT (fixed frequency)
  K697: VIX predicts vol magnitude not direction
  K499: TX cost matters for frequent rebalancing
  12/VIX smooth-weight is lag-robust (design principle)

Data: SPY, GLD, ^VIX from yfinance, 2006-01-01 to 2026-01-01 (20 years)
Signal: 12/VIX weight → signal.shift(1) for lag
TX cost: 5 bps per unit of total turnover (sum of |Δw| across all assets)
Returns: simple (pct_change), NOT log returns

Strategies compared:
  1. Fixed Daily rebalance (12/VIX weight)
  2. Fixed Weekly rebalance (12/VIX weight)
  3. Fixed Monthly rebalance (12/VIX weight) — BASELINE
  4. Fixed Quarterly rebalance (12/VIX weight)
  5. Adaptive v1: Daily if VIX>25, Weekly if 15<VIX≤25, Monthly if VIX≤15
  6. Adaptive v2: Daily if VIX>30, Monthly otherwise
  7. BH 50/50 (buy-and-hold with natural drift, no rebalancing)

References:
  - Fleming, Kirby, Ostdiek (2001): "The Economic Value of Volatility Timing"
  - Moreira & Muir (2017): "Volatility-Managed Portfolios"

[提出: Claude, 執行: Claude]
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── Configuration ────────────────────────────────────────────────────
TX_COST_BPS = 5  # 5 bps per unit of total turnover
START = "2006-01-01"
END = "2026-01-01"

# Cross-OOS periods (5 non-overlapping 4-year periods)
OOS_PERIODS = [
    ("2006-01-01", "2009-12-31"),
    ("2010-01-01", "2013-12-31"),
    ("2014-01-01", "2017-12-31"),
    ("2018-01-01", "2021-12-31"),
    ("2022-01-01", "2025-12-31"),
]


def download_data():
    """Download SPY, GLD, VIX from yfinance."""
    print("Downloading data...")
    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df["Close"].squeeze()
        print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    # Align all series
    df_all = pd.DataFrame(data).dropna()
    print(f"  Aligned: {len(df_all)} rows")
    return df_all


def compute_returns(prices):
    """Compute simple returns (pct_change)."""
    return prices.pct_change().dropna()


def compute_12vix_weight(vix_series):
    """Compute 12/VIX weight for SPY, capped at [0, 1.5].

    CRITICAL: signal.shift(1) — use YESTERDAY's VIX for TODAY's weight.
    """
    raw_weight = 12.0 / vix_series
    weight = raw_weight.clip(0, 1.5)
    # LAG: shift(1) to avoid lookahead bias
    weight = weight.shift(1)
    return weight


def should_rebalance_fixed(dates, freq):
    """Generate boolean mask for fixed rebalancing frequency."""
    if freq == "daily":
        return pd.Series(True, index=dates)
    elif freq == "weekly":
        # Rebalance on Monday (or first trading day of week)
        return dates.to_series().dt.dayofweek == 0
    elif freq == "monthly":
        # Rebalance on first trading day of month
        months = dates.to_series().dt.to_period("M")
        return ~months.duplicated(keep="first")
    elif freq == "quarterly":
        # Rebalance on first trading day of quarter
        quarters = dates.to_series().dt.to_period("Q")
        return ~quarters.duplicated(keep="first")
    else:
        raise ValueError(f"Unknown frequency: {freq}")


def should_rebalance_adaptive_v1(dates, vix_lagged):
    """Adaptive v1: Daily if VIX>25, Weekly if 15<VIX≤25, Monthly if VIX≤15.

    Uses LAGGED VIX (same shift(1) as weight calculation).
    """
    rebal = pd.Series(False, index=dates)

    for i, date in enumerate(dates):
        vix_val = vix_lagged.iloc[i] if not pd.isna(vix_lagged.iloc[i]) else 20.0

        if vix_val > 25:
            # High vol: rebalance daily
            rebal.iloc[i] = True
        elif vix_val > 15:
            # Medium vol: rebalance weekly (Monday)
            if date.dayofweek == 0:
                rebal.iloc[i] = True
        else:
            # Low vol: rebalance monthly (first trading day)
            if i == 0:
                rebal.iloc[i] = True
            else:
                if date.month != dates[i - 1].month:
                    rebal.iloc[i] = True

    return rebal


def should_rebalance_adaptive_v2(dates, vix_lagged):
    """Adaptive v2: Daily if VIX>30, Monthly otherwise.

    Uses LAGGED VIX (same shift(1) as weight calculation).
    """
    rebal = pd.Series(False, index=dates)

    months_first = ~dates.to_series().dt.to_period("M").duplicated(keep="first")

    for i, date in enumerate(dates):
        vix_val = vix_lagged.iloc[i] if not pd.isna(vix_lagged.iloc[i]) else 20.0

        if vix_val > 30:
            # Crisis: rebalance daily
            rebal.iloc[i] = True
        else:
            # Normal: rebalance monthly
            if months_first.iloc[i]:
                rebal.iloc[i] = True

    return rebal


def simulate_strategy(ret_spy, ret_gld, target_weight_spy, rebal_mask, tx_cost_bps=TX_COST_BPS):
    """Simulate a 2-asset portfolio with rebalancing on specified days.

    Args:
        ret_spy: Simple returns for SPY
        ret_gld: Simple returns for GLD
        target_weight_spy: Target weight for SPY (GLD = 1 - w_spy)
        rebal_mask: Boolean Series — True on days to rebalance
        tx_cost_bps: Transaction cost in basis points per unit turnover

    Returns:
        portfolio_returns: Series of net portfolio returns
        turnovers: Series of daily turnover
        actual_weights: Series of actual SPY weight before rebalancing
    """
    n = len(ret_spy)
    port_ret = np.zeros(n)
    turnover = np.zeros(n)
    actual_w_spy = np.zeros(n)

    # Initial weight: 50/50
    w_spy = 0.5
    w_gld = 0.5

    for i in range(n):
        # Record actual weight before any rebalancing
        actual_w_spy[i] = w_spy

        # Check if we should rebalance TODAY
        if rebal_mask.iloc[i]:
            target = target_weight_spy.iloc[i]
            if not np.isnan(target):
                # Turnover = sum of |Δw| across BOTH assets
                delta_spy = abs(target - w_spy)
                delta_gld = abs((1 - target) - w_gld)
                day_turnover = delta_spy + delta_gld  # Both legs
                turnover[i] = day_turnover

                # Update weights to target
                w_spy = target
                w_gld = 1 - target

        # Portfolio return with current weights
        r_spy = ret_spy.iloc[i]
        r_gld = ret_gld.iloc[i]
        gross_ret = w_spy * r_spy + w_gld * r_gld

        # TX cost deducted on rebalancing days
        tx = turnover[i] * tx_cost_bps / 10000
        port_ret[i] = gross_ret - tx

        # Drift weights for next day (mark-to-market)
        total_val = w_spy * (1 + r_spy) + w_gld * (1 + r_gld)
        if total_val > 0:
            w_spy = w_spy * (1 + r_spy) / total_val
            w_gld = w_gld * (1 + r_gld) / total_val

    return (
        pd.Series(port_ret, index=ret_spy.index),
        pd.Series(turnover, index=ret_spy.index),
        pd.Series(actual_w_spy, index=ret_spy.index),
    )


def simulate_bh(ret_spy, ret_gld):
    """Buy-and-hold 50/50 with NO rebalancing (natural drift)."""
    n = len(ret_spy)
    port_ret = np.zeros(n)

    w_spy = 0.5
    w_gld = 0.5

    for i in range(n):
        r_spy = ret_spy.iloc[i]
        r_gld = ret_gld.iloc[i]

        port_ret[i] = w_spy * r_spy + w_gld * r_gld

        # Drift
        total_val = w_spy * (1 + r_spy) + w_gld * (1 + r_gld)
        if total_val > 0:
            w_spy = w_spy * (1 + r_spy) / total_val
            w_gld = w_gld * (1 + r_gld) / total_val

    return pd.Series(port_ret, index=ret_spy.index)


def compute_metrics(returns, name=""):
    """Compute performance metrics from daily returns."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # CAGR
    cum = (1 + returns).cumprod()
    n_years = len(returns) / 252
    cagr = cum.iloc[-1] ** (1 / n_years) - 1 if n_years > 0 else 0

    # MDD
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        "name": name,
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
    }


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided) for forecast comparison.

    e1, e2: loss differentials (squared returns work as proxy).
    Returns t-stat and p-value.
    """
    d = e1 - e2
    n = len(d)
    d_bar = d.mean()

    # Newey-West variance with h-1 lags
    gamma0 = np.sum((d - d_bar) ** 2) / n
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / n
        gamma_sum += 2 * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0, 1.0

    from scipy import stats
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return round(t_stat, 4), round(p_val, 4)


def run_full_analysis(df_all):
    """Run all strategies on full sample and cross-OOS."""
    print("\n" + "=" * 70)
    print("K733: Regime-Dependent Rebalancing Frequency")
    print("=" * 70)

    # Compute returns (simple)
    ret = compute_returns(df_all[["SPY", "GLD"]])
    vix = df_all["VIX"].reindex(ret.index)

    # Compute 12/VIX target weight (with shift(1) lag)
    target_w = compute_12vix_weight(vix)

    # Align everything
    mask = target_w.notna()
    ret = ret[mask]
    vix = vix[mask]
    target_w = target_w[mask]

    # VIX lagged for adaptive decisions (same shift already applied in target_w)
    vix_lagged = vix.shift(1)  # Use yesterday's VIX for today's regime decision

    print(f"\nData: {ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(ret)}")
    print(f"VIX stats: mean={vix.mean():.1f}, median={vix.median():.1f}, "
          f"min={vix.min():.1f}, max={vix.max():.1f}")

    # VIX regime distribution
    vix_high = (vix > 25).sum()
    vix_med = ((vix > 15) & (vix <= 25)).sum()
    vix_low = (vix <= 15).sum()
    total = len(vix)
    print(f"\nVIX Regime Distribution:")
    print(f"  High (>25): {vix_high} days ({vix_high/total*100:.1f}%)")
    print(f"  Medium (15-25): {vix_med} days ({vix_med/total*100:.1f}%)")
    print(f"  Low (≤15): {vix_low} days ({vix_low/total*100:.1f}%)")

    # ─── Define strategies ────────────────────────────────────────
    strategies = {}

    # Fixed frequencies
    for freq in ["daily", "weekly", "monthly", "quarterly"]:
        rebal = should_rebalance_fixed(ret.index, freq)
        strategies[f"fixed_{freq}"] = {
            "label": f"Fixed {freq.capitalize()}",
            "rebal_mask": rebal,
        }

    # Adaptive v1
    rebal_v1 = should_rebalance_adaptive_v1(ret.index, vix_lagged)
    strategies["adaptive_v1"] = {
        "label": "Adaptive v1 (D>25/W>15/M≤15)",
        "rebal_mask": rebal_v1,
    }

    # Adaptive v2
    rebal_v2 = should_rebalance_adaptive_v2(ret.index, vix_lagged)
    strategies["adaptive_v2"] = {
        "label": "Adaptive v2 (D>30/M else)",
        "rebal_mask": rebal_v2,
    }

    # ─── Run full-sample simulation ────────────────────────────────
    print("\n" + "-" * 70)
    print("FULL SAMPLE RESULTS (with 5 bps TX cost)")
    print("-" * 70)

    results = {}
    for key, strat in strategies.items():
        port_ret, turnover, weights = simulate_strategy(
            ret["SPY"], ret["GLD"], target_w, strat["rebal_mask"]
        )
        metrics = compute_metrics(port_ret, strat["label"])

        # Turnover stats
        n_rebal = strat["rebal_mask"].sum()
        avg_daily_turnover = turnover.mean()
        ann_turnover = avg_daily_turnover * 252
        tx_drag = ann_turnover * TX_COST_BPS / 10000

        metrics["n_rebal_days"] = int(n_rebal)
        metrics["rebal_pct"] = round(n_rebal / len(ret) * 100, 1)
        metrics["ann_turnover_pct"] = round(ann_turnover * 100, 2)
        metrics["tx_drag_bps"] = round(tx_drag * 10000, 1)

        results[key] = {
            "metrics": metrics,
            "returns": port_ret,
            "turnover": turnover,
        }

    # BH 50/50
    bh_ret = simulate_bh(ret["SPY"], ret["GLD"])
    bh_metrics = compute_metrics(bh_ret, "BH 50/50")
    bh_metrics["n_rebal_days"] = 0
    bh_metrics["rebal_pct"] = 0.0
    bh_metrics["ann_turnover_pct"] = 0.0
    bh_metrics["tx_drag_bps"] = 0.0
    results["bh_5050"] = {
        "metrics": bh_metrics,
        "returns": bh_ret,
        "turnover": pd.Series(0, index=ret.index),
    }

    # Print results table
    print(f"\n{'Strategy':<35} {'Sharpe':>7} {'CAGR%':>7} {'MDD%':>7} "
          f"{'Calmar':>7} {'Sortino':>8} {'Rebal#':>7} {'TO%/yr':>8} {'TX bps':>7}")
    print("-" * 100)

    for key in ["fixed_daily", "fixed_weekly", "fixed_monthly", "fixed_quarterly",
                 "adaptive_v1", "adaptive_v2", "bh_5050"]:
        m = results[key]["metrics"]
        print(f"{m['name']:<35} {m['sharpe']:>7.4f} {m['cagr']:>7.2f} {m['mdd']:>7.2f} "
              f"{m['calmar']:>7.4f} {m['sortino']:>8.4f} {m['n_rebal_days']:>7d} "
              f"{m['ann_turnover_pct']:>8.2f} {m['tx_drag_bps']:>7.1f}")

    # ─── Gross Sharpe (no TX) ─────────────────────────────────────
    print("\n\nGROSS SHARPE (no TX cost):")
    print("-" * 70)
    gross_results = {}
    for key, strat in strategies.items():
        port_ret_gross, _, _ = simulate_strategy(
            ret["SPY"], ret["GLD"], target_w, strat["rebal_mask"], tx_cost_bps=0
        )
        gross_m = compute_metrics(port_ret_gross, strat["label"])
        gross_results[key] = gross_m
        print(f"  {strat['label']:<35} Gross Sharpe: {gross_m['sharpe']:.4f}  "
              f"Net Sharpe: {results[key]['metrics']['sharpe']:.4f}  "
              f"Diff: {gross_m['sharpe'] - results[key]['metrics']['sharpe']:.4f}")

    # ─── DM Tests vs Monthly baseline ────────────────────────────
    print("\n\nDIEBOLD-MARIANO TESTS vs Fixed Monthly:")
    print("-" * 70)
    baseline_ret = results["fixed_monthly"]["returns"]
    baseline_loss = baseline_ret ** 2  # Use squared returns as loss proxy

    dm_results = {}
    for key in ["fixed_daily", "fixed_weekly", "fixed_quarterly",
                 "adaptive_v1", "adaptive_v2", "bh_5050"]:
        strat_ret = results[key]["returns"]
        strat_loss = strat_ret ** 2
        t_stat, p_val = dm_test(strat_loss, baseline_loss)
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
        dm_results[key] = {"t_stat": t_stat, "p_val": p_val}
        print(f"  {results[key]['metrics']['name']:<35} t={t_stat:>7.3f}  p={p_val:.4f} {sig}")

    # ─── Cross-OOS analysis ────────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("CROSS-OOS ANALYSIS (5 non-overlapping 4-year periods)")
    print("=" * 70)

    oos_all = {}
    for period_idx, (p_start, p_end) in enumerate(OOS_PERIODS):
        period_mask = (ret.index >= p_start) & (ret.index <= p_end)
        period_ret = ret[period_mask]
        period_vix = vix[period_mask]
        period_tw = target_w[period_mask]
        period_vix_lag = vix_lagged[period_mask]

        print(f"\nPeriod {period_idx+1}: {p_start} to {p_end} ({period_mask.sum()} days)")

        period_results = {}
        for key, strat in strategies.items():
            period_rebal = strat["rebal_mask"][period_mask]
            port_r, to, _ = simulate_strategy(
                period_ret["SPY"], period_ret["GLD"], period_tw, period_rebal
            )
            m = compute_metrics(port_r, strat["label"])
            period_results[key] = m

        # BH for this period
        bh_r = simulate_bh(period_ret["SPY"], period_ret["GLD"])
        period_results["bh_5050"] = compute_metrics(bh_r, "BH 50/50")

        oos_all[f"period_{period_idx+1}"] = period_results

        print(f"  {'Strategy':<35} {'Sharpe':>7} {'MDD%':>7}")
        for key in ["fixed_daily", "fixed_weekly", "fixed_monthly", "fixed_quarterly",
                     "adaptive_v1", "adaptive_v2", "bh_5050"]:
            m = period_results[key]
            print(f"  {m['name']:<35} {m['sharpe']:>7.4f} {m['mdd']:>7.2f}")

    # ─── Win rate vs Monthly across OOS periods ──────────────────
    print("\n\nWIN RATE vs Fixed Monthly (Sharpe):")
    print("-" * 70)

    win_rates = {}
    for key in ["fixed_daily", "fixed_weekly", "fixed_quarterly",
                 "adaptive_v1", "adaptive_v2", "bh_5050"]:
        wins = 0
        for p in range(1, 6):
            if oos_all[f"period_{p}"][key]["sharpe"] > oos_all[f"period_{p}"]["fixed_monthly"]["sharpe"]:
                wins += 1
        win_rates[key] = wins
        label = results[key]["metrics"]["name"]
        print(f"  {label:<35} {wins}/5 periods")

    # ─── Regime-conditional analysis ──────────────────────────────
    print("\n\n" + "=" * 70)
    print("REGIME-CONDITIONAL PERFORMANCE")
    print("=" * 70)

    for regime_name, regime_mask_fn in [
        ("High Vol (VIX>25)", lambda v: v > 25),
        ("Medium Vol (15<VIX≤25)", lambda v: (v > 15) & (v <= 25)),
        ("Low Vol (VIX≤15)", lambda v: v <= 15),
    ]:
        regime_mask = regime_mask_fn(vix)
        regime_days = regime_mask.sum()
        print(f"\n{regime_name}: {regime_days} days")

        for key in ["fixed_daily", "fixed_monthly", "adaptive_v1", "adaptive_v2", "bh_5050"]:
            regime_ret = results[key]["returns"][regime_mask]
            if len(regime_ret) > 20:
                ann_ret = regime_ret.mean() * 252
                ann_vol = regime_ret.std() * np.sqrt(252)
                sr = ann_ret / ann_vol if ann_vol > 0 else 0
                print(f"  {results[key]['metrics']['name']:<35} "
                      f"Ann.Ret={ann_ret*100:>7.2f}%  Vol={ann_vol*100:>7.2f}%  Sharpe={sr:>7.4f}")

    # ─── Compile results for JSON ─────────────────────────────────
    output = {
        "experiment_id": "K733",
        "title": "Regime-Dependent Rebalancing Frequency",
        "hypothesis": "Adaptive rebalancing (daily in high-vol, monthly in low-vol) improves risk-adjusted returns vs fixed monthly rebalancing",
        "data_source": "yfinance",
        "assets": ["SPY", "GLD", "^VIX"],
        "period": f"{ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')}",
        "n_trading_days": len(ret),
        "tx_cost_bps": TX_COST_BPS,
        "signal": "12/VIX with shift(1) lag",
        "vix_regime_distribution": {
            "high_gt25": {"days": int(vix_high), "pct": round(vix_high/total*100, 1)},
            "medium_15_25": {"days": int(vix_med), "pct": round(vix_med/total*100, 1)},
            "low_le15": {"days": int(vix_low), "pct": round(vix_low/total*100, 1)},
        },
        "full_sample_results": {},
        "gross_sharpe_comparison": {},
        "dm_tests_vs_monthly": dm_results,
        "cross_oos": {},
        "win_rate_vs_monthly": win_rates,
        "conclusion": "",
        "references": [
            "K48/K65/K75: Monthly rebalancing optimal (fixed frequency)",
            "K697: VIX predicts vol magnitude not direction",
            "K499: TX cost matters for frequent rebalancing",
            "Fleming, Kirby, Ostdiek (2001): Economic Value of Volatility Timing",
            "Moreira & Muir (2017): Volatility-Managed Portfolios",
        ],
    }

    # Full sample
    for key in ["fixed_daily", "fixed_weekly", "fixed_monthly", "fixed_quarterly",
                 "adaptive_v1", "adaptive_v2", "bh_5050"]:
        output["full_sample_results"][key] = results[key]["metrics"]

    # Gross Sharpe
    for key in ["fixed_daily", "fixed_weekly", "fixed_monthly", "fixed_quarterly",
                 "adaptive_v1", "adaptive_v2"]:
        output["gross_sharpe_comparison"][key] = {
            "gross_sharpe": gross_results[key]["sharpe"],
            "net_sharpe": results[key]["metrics"]["sharpe"],
            "diff": round(gross_results[key]["sharpe"] - results[key]["metrics"]["sharpe"], 4),
        }

    # Cross-OOS
    for period_key, period_data in oos_all.items():
        output["cross_oos"][period_key] = {}
        for strat_key, strat_data in period_data.items():
            output["cross_oos"][period_key][strat_key] = strat_data

    # ─── Conclusion ───────────────────────────────────────────────
    monthly_sharpe = results["fixed_monthly"]["metrics"]["sharpe"]
    best_key = max(
        ["fixed_daily", "fixed_weekly", "fixed_quarterly", "adaptive_v1", "adaptive_v2"],
        key=lambda k: results[k]["metrics"]["sharpe"]
    )
    best_sharpe = results[best_key]["metrics"]["sharpe"]
    best_name = results[best_key]["metrics"]["name"]

    adaptive_v1_sharpe = results["adaptive_v1"]["metrics"]["sharpe"]
    adaptive_v2_sharpe = results["adaptive_v2"]["metrics"]["sharpe"]

    conclusion_parts = []
    conclusion_parts.append(f"Monthly baseline Sharpe: {monthly_sharpe:.4f}")
    conclusion_parts.append(f"Best strategy: {best_name} (Sharpe {best_sharpe:.4f})")
    conclusion_parts.append(f"Adaptive v1 Sharpe: {adaptive_v1_sharpe:.4f} (vs Monthly diff: {adaptive_v1_sharpe - monthly_sharpe:+.4f})")
    conclusion_parts.append(f"Adaptive v2 Sharpe: {adaptive_v2_sharpe:.4f} (vs Monthly diff: {adaptive_v2_sharpe - monthly_sharpe:+.4f})")

    # Check if adaptive beats monthly
    adaptive_beats = (adaptive_v1_sharpe > monthly_sharpe) or (adaptive_v2_sharpe > monthly_sharpe)
    if adaptive_beats:
        conclusion_parts.append("RESULT: Adaptive rebalancing DOES improve over fixed monthly.")
    else:
        conclusion_parts.append("NULL RESULT: Adaptive rebalancing does NOT improve over fixed monthly. Monthly is robust regardless of regime.")

    # Check DM significance
    any_sig = any(dm_results[k]["p_val"] < 0.05 for k in dm_results)
    if not any_sig:
        conclusion_parts.append("No strategy is statistically different from monthly (all DM p>0.05).")

    conclusion = " | ".join(conclusion_parts)
    output["conclusion"] = conclusion

    print("\n\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    for part in conclusion_parts:
        print(f"  {part}")

    return output


def main():
    df_all = download_data()
    output = run_full_analysis(df_all)

    # Save results
    out_path = Path(__file__).parent / "k733_regime_rebalancing_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return output


if __name__ == "__main__":
    main()
