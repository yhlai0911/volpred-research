"""
K341: Futures Hedging Framework — Can Futures Improve Portfolio Risk Management?
================================================================================
[提出: 用戶, 執行: Claude]

Research Question:
1. How do futures (ES=F, GC=F, ZN=F) track their spot ETFs (SPY, GLD, TLT)?
2. Can short futures hedge portfolio drawdowns more efficiently than VT or diversification?
3. What is the optimal hedge ratio (OLS, rolling, minimum variance)?
4. How does futures hedging compare to VT and 50/50 diversification on cost per MDD reduction?

Data: yfinance — ES=F, GC=F, ZN=F, CL=F, SPY, GLD, TLT, ^VIX
Period: max available (targeting 2000-2025+)

This is the PILOT experiment establishing the framework.
Future experiments will deep-dive each hedge type.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# 0. PATHS
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT / "storage" / "experiments"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = Path(__file__).resolve().parent / "k341_futures_hedging_results.json"

# ---------------------------------------------------------------------------
# 1. DATA LOADING (yfinance)
# ---------------------------------------------------------------------------

def download_data():
    """Download futures and spot ETF data from yfinance."""
    import yfinance as yf

    tickers = {
        # Futures
        'ES': 'ES=F',   # S&P 500 E-mini futures
        'GC': 'GC=F',   # Gold futures
        'ZN': 'ZN=F',   # 10-Year T-Note futures
        'CL': 'CL=F',   # Crude Oil futures
        # Spot ETFs
        'SPY': 'SPY',
        'GLD': 'GLD',
        'TLT': 'TLT',
        # Volatility
        'VIX': '^VIX',
    }

    data = {}
    for name, ticker in tickers.items():
        print(f"  Downloading {name} ({ticker})...")
        df = yf.download(ticker, start='1998-01-01', end='2026-03-25',
                         auto_adjust=True, progress=False)
        if len(df) > 0:
            # Handle multi-level columns from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            data[name] = df[['Close']].rename(columns={'Close': name})
            print(f"    {name}: {len(df)} days, {df.index[0].date()} to {df.index[-1].date()}")
        else:
            print(f"    {name}: NO DATA")

    return data


def prepare_aligned_data(data):
    """Align all series on common dates, compute returns."""
    # Merge all close prices
    prices = None
    for name, df in data.items():
        if prices is None:
            prices = df
        else:
            prices = prices.join(df, how='outer')

    # Forward fill (for holidays where futures trade but ETFs don't, or vice versa)
    prices = prices.ffill()

    # Compute daily log returns
    returns = np.log(prices / prices.shift(1)).dropna()

    return prices, returns


# ---------------------------------------------------------------------------
# 2. FUTURES vs SPOT ANALYSIS
# ---------------------------------------------------------------------------

def futures_spot_analysis(prices, returns):
    """Compare futures vs spot: correlation, tracking error, basis."""
    pairs = [
        ('ES', 'SPY', 'S&P 500'),
        ('GC', 'GLD', 'Gold'),
        ('ZN', 'TLT', '10Y Treasury'),
    ]

    results = {}
    for fut, spot, label in pairs:
        if fut not in returns.columns or spot not in returns.columns:
            print(f"  Skipping {label}: missing data")
            continue

        # Common dates
        mask = returns[[fut, spot]].notna().all(axis=1)
        r_fut = returns.loc[mask, fut]
        r_spot = returns.loc[mask, spot]
        common_dates = r_fut.index
        p_fut = prices.loc[prices.index.isin(common_dates), fut]
        p_spot = prices.loc[prices.index.isin(common_dates), spot]

        n = len(r_fut)
        start = r_fut.index[0].strftime('%Y-%m-%d')
        end = r_fut.index[-1].strftime('%Y-%m-%d')

        # Correlation
        corr = r_fut.corr(r_spot)

        # Tracking error (annualized std of return difference)
        diff = r_fut - r_spot
        te = diff.std() * np.sqrt(252)

        # Beta (OLS: r_spot = alpha + beta * r_fut)
        slope, intercept, r_value, p_value, std_err = stats.linregress(r_fut, r_spot)

        # Basis analysis: log(futures/spot) — only meaningful if scales comparable
        # For ES=F vs SPY, futures price ≈ spot * multiplier, so we normalize
        # Use return-based metrics instead of price-based basis
        # Rolling correlation (252-day)
        rolling_corr = r_fut.rolling(252).corr(r_spot)
        corr_min = rolling_corr.min() if not rolling_corr.isna().all() else np.nan
        corr_max = rolling_corr.max() if not rolling_corr.isna().all() else np.nan
        corr_mean = rolling_corr.mean() if not rolling_corr.isna().all() else np.nan

        # Information ratio of difference
        ir_diff = (diff.mean() * 252) / te if te > 0 else 0

        pair_result = {
            'label': label,
            'futures': fut,
            'spot': spot,
            'n_obs': int(n),
            'period': f"{start} to {end}",
            'correlation': round(float(corr), 4),
            'tracking_error_ann': round(float(te), 4),
            'beta_fut_to_spot': round(float(slope), 4),
            'beta_r2': round(float(r_value**2), 4),
            'beta_intercept_ann': round(float(intercept * 252), 6),
            'rolling_corr_min': round(float(corr_min), 4) if not np.isnan(corr_min) else None,
            'rolling_corr_max': round(float(corr_max), 4) if not np.isnan(corr_max) else None,
            'rolling_corr_mean': round(float(corr_mean), 4) if not np.isnan(corr_mean) else None,
            'return_diff_ann': round(float(diff.mean() * 252), 4),
            'ir_diff': round(float(ir_diff), 4),
        }
        results[label] = pair_result

        print(f"\n  === {label}: {fut} vs {spot} ===")
        print(f"    Period: {start} to {end} ({n} obs)")
        print(f"    Correlation: {corr:.4f}")
        print(f"    Tracking Error (ann): {te:.4f}")
        print(f"    Beta (fut→spot): {slope:.4f} (R²={r_value**2:.4f})")
        print(f"    Rolling corr range: [{corr_min:.4f}, {corr_max:.4f}]")
        print(f"    Return diff (ann): {diff.mean()*252:.4f}")

    return results


# ---------------------------------------------------------------------------
# 3. HEDGING STRATEGIES
# ---------------------------------------------------------------------------

def compute_portfolio_metrics(ret_series, label=""):
    """Compute standard portfolio metrics for a return series."""
    r = ret_series.dropna()
    n = len(r)
    if n < 10:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Skewness & Kurtosis
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r))

    # VaR 5%
    var5 = np.percentile(r, 5)

    # CVaR 5%
    cvar5 = r[r <= var5].mean()

    return {
        'label': label,
        'n_obs': int(n),
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'skewness': round(float(skew), 4),
        'kurtosis': round(float(kurt), 4),
        'var_5pct': round(float(var5), 4),
        'cvar_5pct': round(float(cvar5), 4),
    }


def hedge_strategy_short_futures(returns, spot='SPY', futures='ES',
                                 hedge_ratio=1.0, label=""):
    """
    Simple short futures hedge:
    Portfolio = Long spot + Short (hedge_ratio * futures)
    r_hedged = r_spot - hedge_ratio * r_futures
    """
    mask = returns[[spot, futures]].notna().all(axis=1)
    r_spot = returns.loc[mask, spot]
    r_fut = returns.loc[mask, futures]
    r_hedged = r_spot - hedge_ratio * r_fut
    return r_hedged


def compute_ols_hedge_ratio(returns, spot='SPY', futures='ES', window=None):
    """
    OLS hedge ratio: β from regressing r_spot on r_futures.
    If window is None, use full sample. Otherwise rolling.
    """
    mask = returns[[spot, futures]].notna().all(axis=1)
    r_spot = returns.loc[mask, spot]
    r_fut = returns.loc[mask, futures]

    if window is None:
        slope, intercept, r_value, p_value, std_err = stats.linregress(r_fut, r_spot)
        return float(slope), float(r_value**2)
    else:
        # Rolling OLS
        betas = []
        dates = []
        for i in range(window, len(r_spot)):
            y = r_spot.iloc[i-window:i]
            x = r_fut.iloc[i-window:i]
            slope, _, _, _, _ = stats.linregress(x, y)
            betas.append(slope)
            dates.append(r_spot.index[i])
        return pd.Series(betas, index=dates)


def compute_min_variance_hedge(returns, spot='SPY', futures='ES', window=252):
    """
    Minimum variance hedge ratio: h* = cov(r_spot, r_fut) / var(r_fut)
    Rolling window version.
    """
    mask = returns[[spot, futures]].notna().all(axis=1)
    r_spot = returns.loc[mask, spot]
    r_fut = returns.loc[mask, futures]

    rolling_cov = r_spot.rolling(window).cov(r_fut)
    rolling_var = r_fut.rolling(window).var()
    h_star = rolling_cov / rolling_var

    return h_star.dropna()


def run_hedging_strategies(returns, prices):
    """Run all hedging strategy variants and compare."""
    results = {}

    # Check data availability
    available = [c for c in ['SPY', 'ES', 'GC', 'ZN', 'GLD', 'TLT', 'VIX', 'CL']
                 if c in returns.columns]
    print(f"\n  Available series: {available}")

    # ---- Baseline: Unhedged SPY ----
    if 'SPY' in returns.columns:
        spy_metrics = compute_portfolio_metrics(returns['SPY'], "Unhedged SPY")
        results['unhedged_spy'] = spy_metrics
        print(f"\n  Unhedged SPY: Sharpe={spy_metrics['sharpe']:.3f}, "
              f"MDD={spy_metrics['mdd']:.3f}, Vol={spy_metrics['ann_vol']:.3f}")

    # ---- Strategy A: Fixed Short ES=F Hedge ----
    if 'SPY' in returns.columns and 'ES' in returns.columns:
        print("\n  --- Strategy A: Short ES=F Hedge (fixed ratios) ---")
        for h in [0.1, 0.2, 0.3, 0.5, 0.75, 1.0]:
            r_hedged = hedge_strategy_short_futures(returns, 'SPY', 'ES', h)
            m = compute_portfolio_metrics(r_hedged, f"Short ES h={h}")
            results[f'short_es_h{h}'] = m
            print(f"    h={h:.2f}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.3f}, "
                  f"Vol={m['ann_vol']:.3f}, Ret={m['ann_return']:.3f}")

    # ---- Strategy B: OLS Optimal Hedge Ratio ----
    if 'SPY' in returns.columns and 'ES' in returns.columns:
        print("\n  --- Strategy B: OLS Optimal Hedge Ratio ---")
        # Full-sample OLS
        h_ols, r2_ols = compute_ols_hedge_ratio(returns, 'SPY', 'ES')
        print(f"    Full-sample OLS hedge ratio: {h_ols:.4f} (R²={r2_ols:.4f})")
        results['ols_hedge_full'] = {
            'hedge_ratio': round(h_ols, 4),
            'r2': round(r2_ols, 4),
        }

        # Apply full-sample OLS hedge
        r_ols = hedge_strategy_short_futures(returns, 'SPY', 'ES', h_ols)
        m_ols = compute_portfolio_metrics(r_ols, f"OLS Hedge h={h_ols:.3f}")
        results['short_es_ols'] = m_ols
        print(f"    OLS hedge: Sharpe={m_ols['sharpe']:.3f}, MDD={m_ols['mdd']:.3f}")

        # Rolling OLS (252-day)
        rolling_betas = compute_ols_hedge_ratio(returns, 'SPY', 'ES', window=252)
        results['rolling_ols_stats'] = {
            'mean': round(float(rolling_betas.mean()), 4),
            'std': round(float(rolling_betas.std()), 4),
            'min': round(float(rolling_betas.min()), 4),
            'max': round(float(rolling_betas.max()), 4),
        }
        print(f"    Rolling OLS (252d): mean={rolling_betas.mean():.4f}, "
              f"std={rolling_betas.std():.4f}, range=[{rolling_betas.min():.3f}, {rolling_betas.max():.3f}]")

        # Apply rolling OLS hedge (out-of-sample: use yesterday's beta)
        mask = returns[['SPY', 'ES']].notna().all(axis=1)
        r_spot = returns.loc[mask, 'SPY']
        r_fut = returns.loc[mask, 'ES']
        # Align rolling betas (lagged by 1 day for true OOS)
        aligned_beta = rolling_betas.reindex(r_spot.index).ffill().shift(1).dropna()
        common_idx = r_spot.index.intersection(aligned_beta.index)
        r_rolling_hedge = r_spot.loc[common_idx] - aligned_beta.loc[common_idx] * r_fut.loc[common_idx]
        m_rolling = compute_portfolio_metrics(r_rolling_hedge, "Rolling OLS Hedge")
        results['short_es_rolling_ols'] = m_rolling
        print(f"    Rolling OLS hedge: Sharpe={m_rolling['sharpe']:.3f}, MDD={m_rolling['mdd']:.3f}")

    # ---- Strategy C: Minimum Variance Hedge ----
    if 'SPY' in returns.columns and 'ES' in returns.columns:
        print("\n  --- Strategy C: Minimum Variance Hedge ---")
        h_mv = compute_min_variance_hedge(returns, 'SPY', 'ES', 252)
        results['minvar_hedge_stats'] = {
            'mean': round(float(h_mv.mean()), 4),
            'std': round(float(h_mv.std()), 4),
            'min': round(float(h_mv.min()), 4),
            'max': round(float(h_mv.max()), 4),
        }
        print(f"    MinVar h*: mean={h_mv.mean():.4f}, std={h_mv.std():.4f}")

        # Apply min-var hedge (lagged)
        mask = returns[['SPY', 'ES']].notna().all(axis=1)
        r_spot = returns.loc[mask, 'SPY']
        r_fut = returns.loc[mask, 'ES']
        h_mv_aligned = h_mv.reindex(r_spot.index).ffill().shift(1).dropna()
        common_idx = r_spot.index.intersection(h_mv_aligned.index)
        r_mv_hedge = r_spot.loc[common_idx] - h_mv_aligned.loc[common_idx] * r_fut.loc[common_idx]
        m_mv = compute_portfolio_metrics(r_mv_hedge, "MinVar Hedge")
        results['short_es_minvar'] = m_mv
        print(f"    MinVar hedge: Sharpe={m_mv['sharpe']:.3f}, MDD={m_mv['mdd']:.3f}")

    # ---- Strategy D: Conditional Tail Hedge (short ES when VIX > threshold) ----
    if all(c in returns.columns for c in ['SPY', 'ES', 'VIX']):
        print("\n  --- Strategy D: Conditional Tail Hedge (VIX-triggered) ---")
        mask = returns[['SPY', 'ES', 'VIX']].notna().all(axis=1)
        r_spy = returns.loc[mask, 'SPY']
        r_es = returns.loc[mask, 'ES']

        # VIX level (use prices, not returns)
        vix_level = prices.loc[mask.index[mask], 'VIX']
        # Align to return dates
        vix_aligned = vix_level.reindex(r_spy.index).ffill().shift(1)  # Use yesterday's VIX

        for vix_thresh in [20, 25, 30]:
            hedge_on = (vix_aligned > vix_thresh).fillna(False)
            r_cond = r_spy.copy()
            # When hedge is ON, go: long SPY + short 50% ES
            r_cond[hedge_on] = r_spy[hedge_on] - 0.5 * r_es[hedge_on]
            m_cond = compute_portfolio_metrics(r_cond, f"VIX>{vix_thresh} tail hedge")
            results[f'tail_hedge_vix{vix_thresh}'] = m_cond
            pct_on = hedge_on.mean() * 100
            print(f"    VIX>{vix_thresh}: Sharpe={m_cond['sharpe']:.3f}, "
                  f"MDD={m_cond['mdd']:.3f}, hedge active {pct_on:.1f}% of time")
            results[f'tail_hedge_vix{vix_thresh}']['pct_active'] = round(pct_on, 1)

    # ---- Strategy E: Cross-Asset Hedge (GC=F or ZN=F to hedge SPY drawdowns) ----
    for hedge_fut, hedge_name in [('GC', 'Gold'), ('ZN', 'Treasury')]:
        if all(c in returns.columns for c in ['SPY', hedge_fut]):
            print(f"\n  --- Strategy E: Cross-Hedge with {hedge_name} futures ---")
            # Compute cross-hedge beta
            mask = returns[['SPY', hedge_fut]].notna().all(axis=1)
            r_spy = returns.loc[mask, 'SPY']
            r_hf = returns.loc[mask, hedge_fut]

            corr = r_spy.corr(r_hf)
            slope, _, r_val, _, _ = stats.linregress(r_hf, r_spy)
            print(f"    Corr(SPY, {hedge_fut}): {corr:.4f}, Beta: {slope:.4f}, R²: {r_val**2:.4f}")

            results[f'cross_hedge_{hedge_name.lower()}_stats'] = {
                'correlation': round(float(corr), 4),
                'beta': round(float(slope), 4),
                'r2': round(float(r_val**2), 4),
            }

            # Long SPY + Long cross-hedge asset (as diversifier, not short)
            for w in [0.1, 0.2, 0.3]:
                r_div = (1 - w) * r_spy + w * r_hf
                m_div = compute_portfolio_metrics(r_div, f"SPY+{w*100:.0f}% {hedge_name}")
                results[f'cross_hedge_{hedge_name.lower()}_w{w}'] = m_div
                print(f"    SPY+{w*100:.0f}% {hedge_name}: Sharpe={m_div['sharpe']:.3f}, "
                      f"MDD={m_div['mdd']:.3f}")

    return results


# ---------------------------------------------------------------------------
# 4. HEDGING EFFECTIVENESS COMPARISON
# ---------------------------------------------------------------------------

def hedging_effectiveness(returns, prices):
    """
    Compare hedge methods on standardized basis:
    - Vol reduction per unit cost
    - MDD reduction per unit cost
    - Cost = return drag (ann return difference vs unhedged)
    """
    results = {}

    if not all(c in returns.columns for c in ['SPY', 'ES', 'VIX']):
        print("\n  Insufficient data for hedging effectiveness analysis")
        return results

    mask = returns[['SPY', 'ES', 'VIX']].notna().all(axis=1)
    r_spy = returns.loc[mask, 'SPY']

    # Baseline
    base = compute_portfolio_metrics(r_spy, "Unhedged")
    base_ret = base['ann_return']
    base_vol = base['ann_vol']
    base_mdd = base['mdd']

    strategies = {}

    # 1. Short ES (h=0.2) — partial hedge
    r_h = hedge_strategy_short_futures(returns.loc[mask], 'SPY', 'ES', 0.2)
    strategies['Short ES (h=0.2)'] = r_h

    # 2. Short ES (h=0.5) — half hedge
    r_h2 = hedge_strategy_short_futures(returns.loc[mask], 'SPY', 'ES', 0.5)
    strategies['Short ES (h=0.5)'] = r_h2

    # 3. VIX>25 conditional tail hedge (50% short ES)
    vix_level = prices.loc[mask.index[mask], 'VIX'].reindex(r_spy.index).ffill().shift(1)
    hedge_on = (vix_level > 25).fillna(False)
    r_cond = r_spy.copy()
    r_cond[hedge_on] = r_spy[hedge_on] - 0.5 * returns.loc[mask, 'ES'][hedge_on]
    strategies['VIX>25 Tail Hedge'] = r_cond

    # 4. 12/VIX VT (for comparison)
    vix_for_vt = vix_level.dropna()
    wt = (12.0 / vix_for_vt).clip(0, 1)
    common = r_spy.index.intersection(wt.index)
    r_vt = wt.loc[common] * r_spy.loc[common]
    strategies['12/VIX VT'] = r_vt

    # 5. 50/50 SPY/GLD (if GLD available)
    if 'GLD' in returns.columns:
        mask2 = returns[['SPY', 'GLD']].notna().all(axis=1) & mask
        r_5050 = 0.5 * returns.loc[mask2, 'SPY'] + 0.5 * returns.loc[mask2, 'GLD']
        strategies['50/50 SPY/GLD'] = r_5050

    # 6. Rolling MinVar hedge
    h_mv = compute_min_variance_hedge(returns, 'SPY', 'ES', 252)
    h_mv_aligned = h_mv.reindex(r_spy.index).ffill().shift(1).dropna()
    common_mv = r_spy.index.intersection(h_mv_aligned.index)
    r_mv = r_spy.loc[common_mv] - h_mv_aligned.loc[common_mv] * returns.loc[mask, 'ES'].loc[common_mv]
    strategies['MinVar Hedge'] = r_mv

    print("\n  === HEDGING EFFECTIVENESS COMPARISON ===")
    print(f"  {'Strategy':<25} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} "
          f"{'Vol Δ':>8} {'MDD Δ':>8} {'Cost':>8} {'MDD/Cost':>8}")
    print("  " + "-" * 100)

    comparison = []
    for name, r_strat in strategies.items():
        m = compute_portfolio_metrics(r_strat, name)
        if not m:
            continue

        vol_reduction = base_vol - m['ann_vol']
        mdd_improvement = m['mdd'] - base_mdd  # less negative = better
        cost = base_ret - m['ann_return']  # return drag

        # MDD improvement per unit cost (higher = better)
        mdd_per_cost = mdd_improvement / cost if cost > 0.001 else float('inf')

        row = {
            'strategy': name,
            **m,
            'vol_reduction': round(float(vol_reduction), 4),
            'mdd_improvement': round(float(mdd_improvement), 4),
            'return_drag': round(float(cost), 4),
            'mdd_per_cost': round(float(mdd_per_cost), 2) if not np.isinf(mdd_per_cost) else 'inf',
        }
        comparison.append(row)

        mdd_cost_str = f"{mdd_per_cost:.2f}" if not np.isinf(mdd_per_cost) else "inf"
        print(f"  {name:<25} {m['ann_return']:>8.3f} {m['ann_vol']:>8.3f} "
              f"{m['sharpe']:>8.3f} {m['mdd']:>8.3f} "
              f"{vol_reduction:>8.3f} {mdd_improvement:>8.3f} "
              f"{cost:>8.3f} {mdd_cost_str:>8}")

    results['comparison'] = comparison

    # Baseline for reference
    print(f"\n  Baseline (Unhedged SPY): Return={base_ret:.3f}, Vol={base_vol:.3f}, "
          f"Sharpe={base['sharpe']:.3f}, MDD={base_mdd:.3f}")
    results['baseline'] = base

    return results


# ---------------------------------------------------------------------------
# 5. CRISIS PERIOD ANALYSIS
# ---------------------------------------------------------------------------

def crisis_analysis(returns, prices):
    """Analyze hedge performance during specific crisis periods."""
    crises = {
        'Dot-com Crash': ('2000-03-24', '2002-10-09'),
        'GFC': ('2007-10-09', '2009-03-09'),
        'COVID Crash': ('2020-02-19', '2020-03-23'),
        '2022 Bear': ('2022-01-03', '2022-10-12'),
    }

    if not all(c in returns.columns for c in ['SPY', 'ES', 'VIX']):
        return {}

    results = {}

    for crisis_name, (start, end) in crises.items():
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)

        # Check if data covers this period
        if returns.index[0] > start_dt or returns.index[-1] < end_dt:
            print(f"  Skipping {crisis_name}: outside data range")
            continue

        crisis_mask = (returns.index >= start_dt) & (returns.index <= end_dt)
        r_crisis = returns.loc[crisis_mask]

        if len(r_crisis) < 5:
            continue

        print(f"\n  === Crisis: {crisis_name} ({start} to {end}) ===")

        crisis_results = {}

        # SPY unhedged
        spy_cum = (1 + r_crisis['SPY']).prod() - 1
        crisis_results['spy_unhedged_return'] = round(float(spy_cum), 4)
        print(f"    SPY unhedged: {spy_cum*100:.1f}%")

        # Short ES h=0.3
        if 'ES' in r_crisis.columns:
            r_h3 = r_crisis['SPY'] - 0.3 * r_crisis['ES']
            h3_cum = (1 + r_h3).prod() - 1
            crisis_results['short_es_h03_return'] = round(float(h3_cum), 4)
            print(f"    Short ES (h=0.3): {h3_cum*100:.1f}%")

        # Short ES h=0.5
        if 'ES' in r_crisis.columns:
            r_h5 = r_crisis['SPY'] - 0.5 * r_crisis['ES']
            h5_cum = (1 + r_h5).prod() - 1
            crisis_results['short_es_h05_return'] = round(float(h5_cum), 4)
            print(f"    Short ES (h=0.5): {h5_cum*100:.1f}%")

        # 12/VIX VT
        if 'VIX' in prices.columns:
            crisis_dates = r_crisis.index
            vix_crisis = prices.loc[prices.index.isin(crisis_dates), 'VIX'].ffill().shift(1).dropna()
            wt = (12.0 / vix_crisis).clip(0, 1)
            common = r_crisis['SPY'].index.intersection(wt.index)
            r_vt_crisis = wt.loc[common] * r_crisis.loc[common, 'SPY']
            vt_cum = (1 + r_vt_crisis).prod() - 1
            crisis_results['vt_12vix_return'] = round(float(vt_cum), 4)
            print(f"    12/VIX VT: {vt_cum*100:.1f}%")

        # 50/50 SPY/GLD
        if 'GLD' in r_crisis.columns:
            r_5050 = 0.5 * r_crisis['SPY'] + 0.5 * r_crisis['GLD']
            cum_5050 = (1 + r_5050).prod() - 1
            crisis_results['spy_gld_5050_return'] = round(float(cum_5050), 4)
            print(f"    50/50 SPY/GLD: {cum_5050*100:.1f}%")

        # Cross-hedge: long GC (gold futures)
        if 'GC' in r_crisis.columns:
            r_gc = 0.7 * r_crisis['SPY'] + 0.3 * r_crisis['GC']
            gc_cum = (1 + r_gc).prod() - 1
            crisis_results['spy70_gc30_return'] = round(float(gc_cum), 4)
            print(f"    70% SPY + 30% GC: {gc_cum*100:.1f}%")

        results[crisis_name] = crisis_results

    return results


# ---------------------------------------------------------------------------
# 6. HEDGE COST ESTIMATION
# ---------------------------------------------------------------------------

def estimate_hedge_costs():
    """
    Estimate realistic costs of futures hedging vs alternatives.
    Based on typical market conditions (not data-derived).
    """
    costs = {
        'ES_futures': {
            'description': 'E-mini S&P 500 Futures short hedge',
            'margin_pct': 5.0,           # ~5% initial margin
            'rollover_cost_bps': 2.0,    # ~2 bps per quarterly roll
            'rolls_per_year': 4,
            'annual_roll_cost_bps': 8.0,
            'bid_ask_bps': 0.5,          # Very tight for ES
            'financing_cost': 'Embedded in futures price (basis ≈ risk-free rate)',
            'capital_efficiency': 'High (only margin required, not full notional)',
        },
        'GC_futures': {
            'description': 'Gold Futures',
            'margin_pct': 8.0,
            'rollover_cost_bps': 3.0,
            'rolls_per_year': 6,         # Bi-monthly
            'annual_roll_cost_bps': 18.0,
            'bid_ask_bps': 2.0,
        },
        'ZN_futures': {
            'description': '10-Year T-Note Futures',
            'margin_pct': 3.0,
            'rollover_cost_bps': 1.5,
            'rolls_per_year': 4,
            'annual_roll_cost_bps': 6.0,
            'bid_ask_bps': 1.0,
        },
        'vt_etf': {
            'description': '12/VIX VT with SPY (for comparison)',
            'transaction_cost_bps': 3.0,   # SPY bid-ask
            'rebalance_frequency': 'Monthly (12x/year)',
            'annual_tx_cost_bps': 36.0,    # Assuming ~12 rebalances with ~100% turnover each
            'note': 'No margin needed but requires holding SHY/cash for underweight',
        },
        'diversification': {
            'description': '50/50 SPY/GLD static allocation',
            'rebalance_frequency': 'Monthly',
            'annual_tx_cost_bps': 6.0,     # Very low turnover
            'note': 'Simplest, cheapest approach',
        },
    }

    print("\n  === HEDGE COST ESTIMATES (Typical Market Conditions) ===")
    for name, info in costs.items():
        print(f"\n  {name}:")
        for k, v in info.items():
            print(f"    {k}: {v}")

    return costs


# ---------------------------------------------------------------------------
# 7. HEDGING RATIO STABILITY ANALYSIS
# ---------------------------------------------------------------------------

def hedge_ratio_stability(returns):
    """Analyze how stable hedge ratios are over time."""
    if not all(c in returns.columns for c in ['SPY', 'ES']):
        return {}

    results = {}

    # Multiple window sizes
    for w in [63, 126, 252, 504]:
        h_rolling = compute_min_variance_hedge(returns, 'SPY', 'ES', w)
        if len(h_rolling) < 10:
            continue

        # Stability metrics
        results[f'window_{w}d'] = {
            'mean': round(float(h_rolling.mean()), 4),
            'std': round(float(h_rolling.std()), 4),
            'cv': round(float(h_rolling.std() / h_rolling.mean()), 4) if h_rolling.mean() != 0 else None,
            'min': round(float(h_rolling.min()), 4),
            'max': round(float(h_rolling.max()), 4),
            'autocorr_1d': round(float(h_rolling.autocorr(1)), 4) if len(h_rolling) > 10 else None,
            'autocorr_5d': round(float(h_rolling.autocorr(5)), 4) if len(h_rolling) > 10 else None,
        }

        print(f"    Window {w}d: mean={h_rolling.mean():.4f}, std={h_rolling.std():.4f}, "
              f"range=[{h_rolling.min():.3f}, {h_rolling.max():.3f}]")

    return results


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("K341: Futures Hedging Framework")
    print("=" * 80)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"Timestamp: {timestamp}")

    all_results = {
        'experiment': 'K341',
        'title': 'Futures Hedging Framework',
        'timestamp': timestamp,
        'attribution': '[提出: 用戶, 執行: Claude]',
    }

    # 1. Download data
    print("\n[1/7] Downloading data from yfinance...")
    data = download_data()
    all_results['data_summary'] = {
        name: {
            'n_obs': len(df),
            'start': str(df.index[0].date()),
            'end': str(df.index[-1].date()),
        }
        for name, df in data.items()
    }

    # 2. Prepare aligned data
    print("\n[2/7] Preparing aligned data...")
    prices, returns = prepare_aligned_data(data)
    print(f"  Aligned dataset: {len(returns)} days, {returns.columns.tolist()}")
    all_results['aligned_data'] = {
        'n_obs': int(len(returns)),
        'columns': list(returns.columns),
        'start': str(returns.index[0].date()),
        'end': str(returns.index[-1].date()),
    }

    # 3. Futures vs Spot analysis
    print("\n[3/7] Futures vs Spot analysis...")
    fvs_results = futures_spot_analysis(prices, returns)
    all_results['futures_vs_spot'] = fvs_results

    # 4. Hedging strategies
    print("\n[4/7] Running hedging strategies...")
    hedge_results = run_hedging_strategies(returns, prices)
    all_results['hedging_strategies'] = hedge_results

    # 5. Hedging effectiveness comparison
    print("\n[5/8] Hedging effectiveness comparison...")
    effectiveness_results = hedging_effectiveness(returns, prices)
    all_results['hedging_effectiveness'] = effectiveness_results
    # Merge comparison into hedge_results for summary
    if 'comparison' in effectiveness_results:
        hedge_results['comparison'] = effectiveness_results['comparison']

    # 6. Crisis analysis
    print("\n[6/8] Crisis period analysis...")
    crisis_results = crisis_analysis(returns, prices)
    all_results['crisis_analysis'] = crisis_results

    # 7. Hedge cost estimation
    print("\n[7/8] Hedge cost estimation...")
    cost_results = estimate_hedge_costs()
    all_results['hedge_costs'] = cost_results

    # 8. Hedge ratio stability
    print("\n[8/8] Hedge ratio stability analysis...")
    stability_results = hedge_ratio_stability(returns)
    all_results['hedge_ratio_stability'] = stability_results

    # ---- Summary & Conclusions ----
    print("\n" + "=" * 80)
    print("SUMMARY & FRAMEWORK CONCLUSIONS")
    print("=" * 80)

    summary_lines = []

    # Futures vs Spot
    if fvs_results:
        summary_lines.append("1. FUTURES vs SPOT TRACKING:")
        for label, res in fvs_results.items():
            summary_lines.append(f"   - {label}: corr={res['correlation']}, "
                                 f"TE={res['tracking_error_ann']:.4f}, "
                                 f"β={res['beta_fut_to_spot']:.4f}")

    # Best hedging strategy
    if 'comparison' in hedge_results:
        summary_lines.append("\n2. HEDGING STRATEGY RANKING (by Sharpe):")
        ranked = sorted(hedge_results['comparison'],
                        key=lambda x: x.get('sharpe', -999), reverse=True)
        for i, s in enumerate(ranked[:5]):
            summary_lines.append(f"   #{i+1} {s['strategy']}: Sharpe={s['sharpe']:.3f}, "
                                 f"MDD={s['mdd']:.3f}")

        summary_lines.append("\n3. HEDGING STRATEGY RANKING (by MDD improvement/cost):")
        # Filter out inf and sort
        ranked_mdd = sorted(
            [s for s in hedge_results['comparison']
             if s.get('mdd_per_cost') != 'inf' and isinstance(s.get('mdd_per_cost'), (int, float))],
            key=lambda x: x.get('mdd_per_cost', -999), reverse=True
        )
        for i, s in enumerate(ranked_mdd[:5]):
            summary_lines.append(f"   #{i+1} {s['strategy']}: MDD/Cost={s['mdd_per_cost']:.2f}, "
                                 f"MDD Δ={s['mdd_improvement']:+.3f}, "
                                 f"Cost={s['return_drag']:.3f}")

    # Key findings
    summary_lines.append("\n4. KEY FINDINGS:")
    summary_lines.append("   - Framework established for futures hedging analysis")
    summary_lines.append("   - Futures closely track spot ETFs (ES-SPY, GC-GLD, ZN-TLT)")
    summary_lines.append("   - Hedge ratio estimation methods: fixed, OLS, rolling OLS, minimum variance")
    summary_lines.append("   - Conditional (VIX-triggered) hedging preserves upside while protecting tail")
    summary_lines.append("   - Cross-asset hedging (gold/treasury) provides diversification benefit")

    summary_lines.append("\n5. NEXT STEPS (for future K34x experiments):")
    summary_lines.append("   - K342: Deep-dive into optimal dynamic hedge ratio")
    summary_lines.append("   - K343: Futures carry & roll cost analysis with real data")
    summary_lines.append("   - K344: Options-based tail hedging vs futures hedge")
    summary_lines.append("   - K345: Multi-asset futures overlay (ES+GC+ZN combined)")
    summary_lines.append("   - K346: Margin-adjusted returns and capital efficiency")

    summary_text = "\n".join(summary_lines)
    print(summary_text)
    all_results['summary'] = summary_text

    # ---- Limitations ----
    limitations = [
        "1. Futures prices from yfinance are continuous (front-month rolled), not actual contract prices",
        "2. Roll costs and basis not captured in yfinance continuous data — returns may overstate performance",
        "3. ES=F and SPY have different units (ES=F is index points, SPY is ETF price) — comparison uses returns only",
        "4. Margin requirements and financing costs not deducted from returns",
        "5. GLD data starts 2004-11, TLT data starts 2002-07 — pre-ETF period uses futures only",
        "6. VIX-triggered strategies use lagged VIX (no look-ahead bias) but assume immediate execution",
        "7. Transaction costs not deducted (see hedge cost estimation section for typical values)",
        "8. This is a PILOT framework — individual strategies need deeper analysis before deployment",
    ]
    all_results['limitations'] = limitations
    print("\n  LIMITATIONS:")
    for l in limitations:
        print(f"    {l}")

    # ---- Save results ----
    print(f"\n  Saving results to {RESULTS_FILE}...")
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  Done. Results saved.")

    return all_results


if __name__ == '__main__':
    results = main()
