#!/usr/bin/env python3
"""
K731: VIX Term Structure Trading Strategy
==========================================
[提出: Claude, 執行: Claude]

Tests whether the SHAPE of the VIX term structure (contango vs backwardation)
provides different information from VIX level alone, and whether it can
improve equity timing in a smooth-weight strategy.

Background:
  - K697: VIX predicts vol magnitude (corr 0.57) NOT direction (corr 0.04)
  - K702: 50/50 SPY/GLD is optimal static allocation
  - K704: 50/50 ≈ Risk Parity (SPY vol 19.3% ≈ GLD vol 18.3%)
  - K730: Cross-asset vol momentum detectable but not exploitable
  - P37: Backwardation preemptive (VIX×1.3) passed Harvey (t=4.31)
  - P41: Cross-asset backwardation confirmed on SPY+QQQ
  - Prior VIX TS enhancement for Hybrid VT: Sharpe -0.012 (null)
  - Smooth-weight strategies almost immune to lag — design principle

Hypothesis:
  VIX term structure shape (contango = complacent, backwardation = panic)
  provides DIFFERENT information from VIX level alone, and can improve
  equity timing when combined with 12/VIX smooth weighting.

Data:
  - ^VIX: CBOE VIX (spot implied vol)
  - ^VIX3M: CBOE 3-month VIX (via yfinance)
  - SPY, GLD prices
  - Period: 2010-2026

Signals:
  1. VIX/VIX3M ratio: <1 = contango (normal), >1 = backwardation (panic)
  2. Term structure slope: (VIX3M - VIX) / VIX
  3. Combined: VIX level × term structure interaction

Strategy variants:
  A. 12/VIX baseline (no term structure)
  B. Term-structure-adjusted 12/VIX: scale down when backwardation
  C. Term-structure regime switch: full 12/VIX in contango, half in backwardation
  D. Smooth TS overlay: weight = 12/VIX × (1 - max(0, ratio-1))

Statistical tests:
  - Granger causality: VIX/VIX3M ratio → next-day realized vol
  - Information content: does TS predict vol beyond VIX level?
  - DM test: strategy comparison
  - Cross-OOS: 5 non-overlapping 2-year periods
  - Harvey (2016) t>3.0 threshold for prediction claims

Requirements:
  - signal.shift(1) — MANDATORY for all strategies
  - TX cost 5 bps per weight change
  - OOS ≥ 252 days per period

References:
  - Chang (2016) — VIX backwardation predicts positive future S&P returns (monthly)
  - Wang & Yen (2017) — VIX term structure predictive power
  - Moreira & Muir (2017) — Volatility-Managed Portfolios, JoF
  - Johnson (2017) — VIX term structure for market timing
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from pathlib import Path
from scipy import stats as sp_stats

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────
VIX_TICKER = '^VIX'
VIX3M_TICKER = '^VIX3M'  # CBOE 3-month VIX
PRICE_TICKERS = ['SPY', 'GLD']
START_DATE = '2008-01-01'   # VIX3M available from ~2007
END_DATE = '2026-03-30'
TX_COST_BPS = 5            # 5 bps per weight change

# 5 non-overlapping 2-year OOS periods
OOS_PERIODS = [
    ('2012-01-01', '2013-12-31'),  # Post-GFC recovery
    ('2014-01-01', '2015-12-31'),  # Low vol era
    ('2016-01-01', '2017-12-31'),  # Trump election vol
    ('2018-01-01', '2019-12-31'),  # Volmageddon + trade war
    ('2020-01-01', '2021-12-31'),  # COVID
]
# Full OOS (most recent, not in 2-year windows above)
FULL_OOS_START = '2022-01-01'

# Strategy parameters
VIX_SCALE = 12.0  # base: 12/VIX
BACKWARDATION_THRESHOLD = 1.0   # ratio > 1.0 = backwardation
CONTANGO_THRESHOLD = 0.9        # ratio < 0.9 = deep contango


def download_data():
    """Download VIX, VIX3M, SPY, GLD data."""
    print("=" * 70)
    print("K731: VIX Term Structure Trading Strategy")
    print("=" * 70)
    print(f"\nDownloading data: {START_DATE} to {END_DATE}")

    tickers = PRICE_TICKERS + [VIX_TICKER, VIX3M_TICKER]
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw['Close'] if 'Close' in raw.columns.get_level_values(0) else raw['Adj Close']
    else:
        prices = raw

    # Rename columns
    prices.columns = [c.replace('^', '') for c in prices.columns]

    # Check VIX3M availability
    if 'VIX3M' not in prices.columns or prices['VIX3M'].dropna().empty:
        print("WARNING: VIX3M not available, trying VXV ticker...")
        vxv = yf.download('^VXV', start=START_DATE, end=END_DATE, progress=False)
        if isinstance(vxv.columns, pd.MultiIndex):
            vxv = vxv['Close'] if 'Close' in vxv.columns.get_level_values(0) else vxv['Adj Close']
        if isinstance(vxv, pd.DataFrame):
            vxv = vxv.iloc[:, 0]
        prices['VIX3M'] = vxv

    prices = prices.dropna(subset=['SPY', 'GLD', 'VIX'])

    print(f"  Raw rows: {len(prices)}")
    print(f"  VIX3M available: {prices['VIX3M'].notna().sum()} / {len(prices)}")
    print(f"  Date range: {prices.index[0].date()} to {prices.index[-1].date()}")

    return prices


def compute_signals(prices):
    """Compute VIX term structure signals."""
    df = prices.copy()

    # Returns
    df['spy_ret'] = df['SPY'].pct_change()
    df['gld_ret'] = df['GLD'].pct_change()

    # VIX term structure ratio
    df['vix_ratio'] = df['VIX'] / df['VIX3M']

    # Term structure slope (normalized)
    df['ts_slope'] = (df['VIX3M'] - df['VIX']) / df['VIX']

    # Regime classification
    df['is_backwardation'] = (df['vix_ratio'] > BACKWARDATION_THRESHOLD).astype(int)
    df['is_deep_contango'] = (df['vix_ratio'] < CONTANGO_THRESHOLD).astype(int)

    # Realized vol (annualized, 22-day rolling)
    df['rv_22d'] = df['spy_ret'].rolling(22).std() * np.sqrt(252) * 100

    # Forward realized vol (for prediction tests)
    df['fwd_rv_22d'] = df['spy_ret'].rolling(22).std().shift(-22) * np.sqrt(252) * 100

    # 5-day forward return (for timing tests)
    df['fwd_ret_5d'] = df['SPY'].pct_change(5).shift(-5)

    # Drop NaN rows from signals
    df = df.dropna(subset=['vix_ratio', 'spy_ret', 'gld_ret', 'rv_22d'])

    print(f"\n── Signal Statistics ──")
    print(f"  Observations with VIX3M: {df['vix_ratio'].notna().sum()}")
    print(f"  VIX/VIX3M ratio: mean={df['vix_ratio'].mean():.3f}, "
          f"std={df['vix_ratio'].std():.3f}, "
          f"min={df['vix_ratio'].min():.3f}, max={df['vix_ratio'].max():.3f}")
    print(f"  Backwardation days (ratio>1): {df['is_backwardation'].sum()} "
          f"({df['is_backwardation'].mean()*100:.1f}%)")
    print(f"  Deep contango days (ratio<0.9): {df['is_deep_contango'].sum()} "
          f"({df['is_deep_contango'].mean()*100:.1f}%)")
    print(f"  TS slope: mean={df['ts_slope'].mean():.4f}, std={df['ts_slope'].std():.4f}")

    return df


def test_information_content(df):
    """Test whether VIX/VIX3M ratio adds info beyond VIX level."""
    print("\n" + "=" * 70)
    print("PART 1: Information Content Tests")
    print("=" * 70)

    results = {}

    # 1. Correlation of ratio with forward realized vol
    mask = df['fwd_rv_22d'].notna() & df['vix_ratio'].notna()
    sub = df[mask]

    corr_ratio_fwd, p_ratio = sp_stats.pearsonr(sub['vix_ratio'], sub['fwd_rv_22d'])
    corr_vix_fwd, p_vix = sp_stats.pearsonr(sub['VIX'], sub['fwd_rv_22d'])

    print(f"\n1. Correlation with 22d forward realized vol:")
    print(f"   VIX level:     r = {corr_vix_fwd:.4f} (p = {p_vix:.2e})")
    print(f"   VIX/VIX3M:     r = {corr_ratio_fwd:.4f} (p = {p_ratio:.2e})")

    results['corr_vix_fwd_rv'] = float(corr_vix_fwd)
    results['corr_ratio_fwd_rv'] = float(corr_ratio_fwd)

    # 2. Granger causality: does ratio predict vol beyond VIX?
    # Using OLS regression: fwd_rv ~ VIX vs fwd_rv ~ VIX + ratio
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_squared_error

    X_vix = sub[['VIX']].values
    X_both = sub[['VIX', 'vix_ratio']].values
    y = sub['fwd_rv_22d'].values

    # In-sample R²
    lr_vix = LinearRegression().fit(X_vix, y)
    lr_both = LinearRegression().fit(X_both, y)

    r2_vix = lr_vix.score(X_vix, y)
    r2_both = lr_both.score(X_both, y)

    print(f"\n2. Regression: fwd_rv_22d ~ predictors (in-sample)")
    print(f"   VIX only:      R² = {r2_vix:.4f}")
    print(f"   VIX + ratio:   R² = {r2_both:.4f}")
    print(f"   Incremental:   ΔR² = {r2_both - r2_vix:.4f}")

    results['r2_vix_only'] = float(r2_vix)
    results['r2_vix_plus_ratio'] = float(r2_both)
    results['delta_r2'] = float(r2_both - r2_vix)

    # 3. F-test for incremental significance
    n = len(y)
    k_reduced = 1  # VIX only
    k_full = 2     # VIX + ratio
    ssr_reduced = np.sum((y - lr_vix.predict(X_vix)) ** 2)
    ssr_full = np.sum((y - lr_both.predict(X_both)) ** 2)

    f_stat = ((ssr_reduced - ssr_full) / (k_full - k_reduced)) / (ssr_full / (n - k_full - 1))
    f_pval = 1 - sp_stats.f.cdf(f_stat, k_full - k_reduced, n - k_full - 1)

    print(f"\n3. F-test for ratio incremental significance:")
    print(f"   F-statistic:   {f_stat:.2f}")
    print(f"   p-value:       {f_pval:.2e}")
    print(f"   Significant:   {'YES' if f_pval < 0.05 else 'NO'} (α=0.05)")

    results['f_stat_ratio'] = float(f_stat)
    results['f_pval_ratio'] = float(f_pval)

    # 4. Return by regime
    print(f"\n4. SPY returns by VIX term structure regime:")
    for regime, mask_col in [('Backwardation', 'is_backwardation'), ('Contango (all)', lambda x: 1 - x['is_backwardation'])]:
        if callable(mask_col):
            m = mask_col(df).astype(bool)
        else:
            m = df[mask_col].astype(bool)
        ret = df.loc[m, 'spy_ret']
        ann_ret = ret.mean() * 252 * 100
        ann_vol = ret.std() * np.sqrt(252) * 100
        sr = ann_ret / ann_vol if ann_vol > 0 else 0
        n_days = m.sum()
        print(f"   {regime:25s}: n={n_days:5d}, ann_ret={ann_ret:+6.1f}%, "
              f"ann_vol={ann_vol:5.1f}%, SR={sr:+.3f}")

    # Deep contango
    m = df['is_deep_contango'].astype(bool)
    ret = df.loc[m, 'spy_ret']
    ann_ret = ret.mean() * 252 * 100
    ann_vol = ret.std() * np.sqrt(252) * 100
    sr = ann_ret / ann_vol if ann_vol > 0 else 0
    print(f"   {'Deep contango (<0.9)':25s}: n={m.sum():5d}, ann_ret={ann_ret:+6.1f}%, "
          f"ann_vol={ann_vol:5.1f}%, SR={sr:+.3f}")

    results['regime_stats'] = {
        'backwardation_pct': float(df['is_backwardation'].mean()),
        'deep_contango_pct': float(df['is_deep_contango'].mean()),
    }

    # 5. Sorted portfolio analysis (quintiles by ratio, controlling for VIX)
    print(f"\n5. Sorted portfolios by VIX/VIX3M ratio (quintiles):")
    sub_valid = df[df['fwd_ret_5d'].notna()].copy()
    sub_valid['vix_q'] = pd.qcut(sub_valid['VIX'], 5, labels=False, duplicates='drop')
    sub_valid['ratio_q'] = pd.qcut(sub_valid['vix_ratio'], 5, labels=False, duplicates='drop')

    print(f"   Ratio quintile    Mean 5d fwd ret   Ann. ret   N")
    for q in sorted(sub_valid['ratio_q'].unique()):
        m = sub_valid['ratio_q'] == q
        ret_5d = sub_valid.loc[m, 'fwd_ret_5d']
        mean_5d = ret_5d.mean() * 100
        ann = mean_5d * (252/5)
        n = m.sum()
        print(f"   Q{int(q)+1}:              {mean_5d:+.3f}%         {ann:+.1f}%     {n}")

    # Monotonicity test (Q5 - Q1)
    q1_ret = sub_valid.loc[sub_valid['ratio_q'] == 0, 'fwd_ret_5d']
    q5_ret = sub_valid.loc[sub_valid['ratio_q'] == sub_valid['ratio_q'].max(), 'fwd_ret_5d']
    if len(q1_ret) > 0 and len(q5_ret) > 0:
        t_spread, p_spread = sp_stats.ttest_ind(q5_ret, q1_ret)
        print(f"   Q5-Q1 spread t-stat: {t_spread:.2f} (p={p_spread:.3f})")
        results['q5_q1_tstat'] = float(t_spread)
        results['q5_q1_pval'] = float(p_spread)

    # 6. Controlling for VIX level (double sort)
    print(f"\n6. Double sort: ratio effect WITHIN VIX quintiles:")
    print(f"   VIX Q  | Low ratio 5d ret | High ratio 5d ret | Spread   | N_lo | N_hi")
    spreads = []
    for vq in sorted(sub_valid['vix_q'].unique()):
        sub_vq = sub_valid[sub_valid['vix_q'] == vq]
        ratio_med = sub_vq['vix_ratio'].median()
        lo = sub_vq[sub_vq['vix_ratio'] <= ratio_med]['fwd_ret_5d']
        hi = sub_vq[sub_vq['vix_ratio'] > ratio_med]['fwd_ret_5d']
        if len(lo) > 10 and len(hi) > 10:
            spread = hi.mean() - lo.mean()
            spreads.append(spread)
            print(f"   Q{int(vq)+1}     | {lo.mean()*100:+.3f}%           | {hi.mean()*100:+.3f}%            | "
                  f"{spread*100:+.3f}% | {len(lo):4d} | {len(hi):4d}")

    if spreads:
        avg_spread = np.mean(spreads) * 100
        t_avg, p_avg = sp_stats.ttest_1samp(np.array(spreads), 0)
        print(f"   Average spread: {avg_spread:+.3f}% (t={t_avg:.2f}, p={p_avg:.3f})")
        results['double_sort_avg_spread'] = float(avg_spread)
        results['double_sort_tstat'] = float(t_avg)
        results['double_sort_pval'] = float(p_avg)

    return results


def compute_strategy_returns(df, strategy_name, spy_weight_func):
    """Compute strategy returns with proper lag and TX costs.

    CRITICAL: signal.shift(1) applied inside — weight from t-1 applied to return at t.

    Args:
        df: DataFrame with signals and returns
        strategy_name: name for display
        spy_weight_func: function(row) -> SPY weight [0, 1]
    """
    # Compute raw weights
    raw_weights = df.apply(spy_weight_func, axis=1)
    raw_weights = raw_weights.clip(0, 1)

    # MANDATORY: shift(1) — use yesterday's signal for today's trade
    weights = raw_weights.shift(1)

    # TX cost: proportional to weight change
    weight_change = weights.diff().abs()
    tx_cost = weight_change * TX_COST_BPS / 10000

    # Portfolio return: w*SPY + (1-w)*GLD - tx_cost
    port_ret = weights * df['spy_ret'] + (1 - weights) * df['gld_ret'] - tx_cost

    port_ret = port_ret.dropna()

    return port_ret, weights


def strategy_metrics(returns, name):
    """Compute standard performance metrics."""
    ann_ret = returns.mean() * 252 * 100
    ann_vol = returns.std() * np.sqrt(252) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min() * 100

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252) * 100
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        'name': name,
        'ann_return_pct': float(ann_ret),
        'ann_vol_pct': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd_pct': float(mdd),
        'calmar': float(calmar),
        'sortino': float(sortino),
        'n_days': int(len(returns)),
    }


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for comparing strategy returns.
    H0: equal expected loss. Uses squared return as loss proxy.
    Returns t-stat, p-value."""
    d = e1 ** 2 - e2 ** 2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return 0, 1
    mean_d = d.mean()
    # Newey-West with h-1 lags
    gamma0 = d.var()
    se = np.sqrt(gamma0 / n)
    if se == 0:
        return 0, 1
    t_stat = mean_d / se
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def run_strategies(df):
    """Run all strategy variants and compare."""
    print("\n" + "=" * 70)
    print("PART 2: Strategy Backtests")
    print("=" * 70)

    strategies = {}

    # A. 50/50 Buy & Hold (baseline)
    def bh_5050(row):
        return 0.5
    strategies['BH 50/50'] = bh_5050

    # B. 12/VIX (no term structure)
    def twelve_vix(row):
        return min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
    strategies['12/VIX'] = twelve_vix

    # C. TS-adjusted 12/VIX: scale down in backwardation
    def ts_adjusted(row):
        base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
        ratio = row['vix_ratio']
        if pd.isna(ratio):
            return base
        if ratio > BACKWARDATION_THRESHOLD:
            # Backwardation: scale down proportionally
            scale = max(0.3, 1.0 - (ratio - 1.0) * 2)
            return base * scale
        return base
    strategies['TS-Adj 12/VIX'] = ts_adjusted

    # D. Regime switch: full in contango, half in backwardation
    def regime_switch(row):
        base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
        ratio = row['vix_ratio']
        if pd.isna(ratio):
            return base
        if ratio > BACKWARDATION_THRESHOLD:
            return base * 0.5  # half equity in backwardation
        return base
    strategies['Regime Switch'] = regime_switch

    # E. Smooth TS overlay: weight = 12/VIX × min(1, 1/ratio)
    def smooth_ts(row):
        base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
        ratio = row['vix_ratio']
        if pd.isna(ratio) or ratio <= 0:
            return base
        adjustment = min(1.0, 1.0 / ratio)  # < 1 when backwardation
        return base * adjustment
    strategies['Smooth TS'] = smooth_ts

    # F. Deep contango boost: increase equity in deep contango
    def contango_boost(row):
        base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
        ratio = row['vix_ratio']
        if pd.isna(ratio):
            return base
        if ratio < CONTANGO_THRESHOLD:
            # Deep contango: boost by 20%
            return min(1.0, base * 1.2)
        elif ratio > BACKWARDATION_THRESHOLD:
            # Backwardation: reduce by 30%
            return base * 0.7
        return base
    strategies['Contango Boost'] = contango_boost

    # Compute all strategy returns
    results_all = {}
    returns_dict = {}

    for name, func in strategies.items():
        ret, wt = compute_strategy_returns(df, name, func)
        metrics = strategy_metrics(ret, name)
        results_all[name] = metrics
        returns_dict[name] = ret

    # Print full-sample results
    print(f"\n── Full Sample Results ({df.index[0].date()} to {df.index[-1].date()}) ──")
    print(f"{'Strategy':25s} {'Ann Ret%':>8s} {'Ann Vol%':>8s} {'Sharpe':>7s} {'MDD%':>7s} {'Calmar':>7s} {'N':>6s}")
    print("-" * 70)
    for name in strategies:
        m = results_all[name]
        print(f"{name:25s} {m['ann_return_pct']:+8.2f} {m['ann_vol_pct']:8.2f} {m['sharpe']:+7.3f} "
              f"{m['mdd_pct']:7.1f} {m['calmar']:7.3f} {m['n_days']:6d}")

    # DM tests vs 12/VIX baseline
    print(f"\n── DM Tests vs 12/VIX ──")
    baseline_ret = returns_dict['12/VIX']
    dm_results = {}
    for name, ret in returns_dict.items():
        if name == '12/VIX':
            continue
        # Align returns
        common = baseline_ret.index.intersection(ret.index)
        if len(common) < 100:
            continue
        t_stat, p_val = dm_test(baseline_ret[common], ret[common])
        harvey_pass = abs(t_stat) > 3.0
        dm_results[name] = {'t_stat': t_stat, 'p_val': p_val, 'harvey_pass': harvey_pass}
        print(f"  {name:25s}: t={t_stat:+6.3f}, p={p_val:.4f}, Harvey: {'PASS' if harvey_pass else 'fail'}")

    return results_all, returns_dict, dm_results


def cross_oos_validation(df, returns_dict):
    """Run cross-OOS validation on 5 non-overlapping 2-year periods."""
    print("\n" + "=" * 70)
    print("PART 3: Cross-OOS Validation (5 × 2-year periods)")
    print("=" * 70)

    strategy_names = list(returns_dict.keys())
    oos_results = {name: [] for name in strategy_names}

    for i, (start, end) in enumerate(OOS_PERIODS):
        print(f"\n  Period {i+1}: {start} to {end}")
        for name, ret in returns_dict.items():
            mask = (ret.index >= start) & (ret.index <= end)
            sub = ret[mask]
            if len(sub) < 100:
                oos_results[name].append(None)
                continue
            m = strategy_metrics(sub, name)
            oos_results[name].append(m)

    # Print OOS summary
    print(f"\n── Cross-OOS Sharpe Summary ──")
    print(f"{'Strategy':25s}", end="")
    for i in range(5):
        print(f" {'P'+str(i+1):>7s}", end="")
    print(f" {'Mean':>7s} {'Win/5':>5s}")
    print("-" * 80)

    baseline_name = 'BH 50/50'
    cross_oos_summary = {}

    for name in strategy_names:
        sharpes = []
        wins = 0
        print(f"{name:25s}", end="")
        for i in range(5):
            if oos_results[name][i] is not None:
                s = oos_results[name][i]['sharpe']
                sharpes.append(s)
                # Compare vs BH 50/50
                if oos_results[baseline_name][i] is not None:
                    if s > oos_results[baseline_name][i]['sharpe']:
                        wins += 1
                print(f" {s:+7.3f}", end="")
            else:
                print(f" {'N/A':>7s}", end="")
        mean_sr = np.mean(sharpes) if sharpes else 0
        print(f" {mean_sr:+7.3f} {wins:>3d}/5")

        cross_oos_summary[name] = {
            'mean_sharpe': float(mean_sr),
            'wins_vs_bh5050': int(wins),
            'period_sharpes': [float(s) if s is not None else None for s in sharpes],
        }

    return cross_oos_summary


def recent_oos_test(df, returns_dict):
    """Test on most recent out-of-sample period (2022-2026)."""
    print("\n" + "=" * 70)
    print(f"PART 4: Recent OOS ({FULL_OOS_START} to present)")
    print("=" * 70)

    recent_results = {}
    print(f"\n{'Strategy':25s} {'Ann Ret%':>8s} {'Ann Vol%':>8s} {'Sharpe':>7s} {'MDD%':>7s} {'N':>6s}")
    print("-" * 65)

    for name, ret in returns_dict.items():
        mask = ret.index >= FULL_OOS_START
        sub = ret[mask]
        if len(sub) < 100:
            continue
        m = strategy_metrics(sub, name)
        recent_results[name] = m
        print(f"{name:25s} {m['ann_return_pct']:+8.2f} {m['ann_vol_pct']:8.2f} {m['sharpe']:+7.3f} "
              f"{m['mdd_pct']:7.1f} {m['n_days']:6d}")

    return recent_results


def sensitivity_analysis(df):
    """Test sensitivity to backwardation threshold parameter."""
    print("\n" + "=" * 70)
    print("PART 5: Sensitivity Analysis")
    print("=" * 70)

    thresholds = [0.95, 0.98, 1.00, 1.02, 1.05, 1.10]
    print(f"\n  Backwardation threshold sensitivity (TS-Adjusted 12/VIX):")
    print(f"  {'Threshold':>10s} {'Sharpe':>8s} {'MDD%':>8s} {'BW days%':>9s}")
    print("  " + "-" * 40)

    sensitivity = {}
    for thresh in thresholds:
        def ts_adj_param(row, t=thresh):
            base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
            ratio = row['vix_ratio']
            if pd.isna(ratio):
                return base
            if ratio > t:
                scale = max(0.3, 1.0 - (ratio - 1.0) * 2)
                return base * scale
            return base

        ret, wt = compute_strategy_returns(df, f'TS-Adj (thresh={thresh})', ts_adj_param)
        m = strategy_metrics(ret, f'thresh={thresh}')
        bw_pct = (df['vix_ratio'] > thresh).mean() * 100
        print(f"  {thresh:10.2f} {m['sharpe']:+8.3f} {m['mdd_pct']:8.1f} {bw_pct:8.1f}%")
        sensitivity[str(thresh)] = {
            'sharpe': m['sharpe'],
            'mdd_pct': m['mdd_pct'],
            'backwardation_pct': float(bw_pct),
        }

    # Scale factor sensitivity
    print(f"\n  Backwardation scale factor sensitivity (thresh=1.0):")
    print(f"  {'Scale':>10s} {'Sharpe':>8s} {'MDD%':>8s}")
    print("  " + "-" * 30)

    scales = [0.3, 0.5, 0.7, 0.8, 0.9, 1.0]
    for sc in scales:
        def ts_scale_param(row, s=sc):
            base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
            ratio = row['vix_ratio']
            if pd.isna(ratio):
                return base
            if ratio > 1.0:
                return base * s
            return base

        ret, wt = compute_strategy_returns(df, f'Scale={sc}', ts_scale_param)
        m = strategy_metrics(ret, f'scale={sc}')
        print(f"  {sc:10.1f} {m['sharpe']:+8.3f} {m['mdd_pct']:8.1f}")

    return sensitivity


def lag_robustness(df):
    """Test lag robustness (should be robust for smooth-weight strategies)."""
    print("\n" + "=" * 70)
    print("PART 6: Lag Robustness")
    print("=" * 70)

    print(f"\n  TS-Adjusted 12/VIX with different lags:")
    print(f"  {'Lag':>5s} {'Sharpe':>8s} {'MDD%':>8s} {'Delta SR':>9s}")
    print("  " + "-" * 35)

    lag_results = {}
    baseline_sr = None

    for lag in [0, 1, 2, 3, 5]:
        # Compute raw weights
        def ts_adj_raw(row):
            base = min(1.0, VIX_SCALE / row['VIX']) if row['VIX'] > 0 else 0.5
            ratio = row['vix_ratio']
            if pd.isna(ratio):
                return base
            if ratio > 1.0:
                scale = max(0.3, 1.0 - (ratio - 1.0) * 2)
                return base * scale
            return base

        raw_weights = df.apply(ts_adj_raw, axis=1).clip(0, 1)
        weights = raw_weights.shift(lag) if lag > 0 else raw_weights
        weight_change = weights.diff().abs()
        tx_cost = weight_change * TX_COST_BPS / 10000
        port_ret = weights * df['spy_ret'] + (1 - weights) * df['gld_ret'] - tx_cost
        port_ret = port_ret.dropna()

        m = strategy_metrics(port_ret, f'lag={lag}')
        if lag == 0:
            lag0_sr = m['sharpe']
        if lag == 1:
            baseline_sr = m['sharpe']
        delta = m['sharpe'] - (baseline_sr if baseline_sr else m['sharpe'])
        label = "★ lookahead" if lag == 0 else ("← correct" if lag == 1 else "")
        print(f"  {lag:5d} {m['sharpe']:+8.3f} {m['mdd_pct']:8.1f} {delta:+9.3f}  {label}")
        lag_results[str(lag)] = m['sharpe']

    if baseline_sr is not None and lag_results.get('0'):
        lag_decay = lag_results['0'] - baseline_sr
        print(f"\n  Lag-0 vs Lag-1 decay: {lag_decay:+.4f}")
        print(f"  Smooth-weight lag robustness: {'CONFIRMED' if abs(lag_decay) < 0.05 else 'WEAK'}")
        return lag_results, float(lag_decay)

    return lag_results, 0.0


def main():
    """Main execution."""
    start_time = datetime.now(timezone.utc)
    results = {
        'experiment_id': 'K731',
        'title': 'VIX Term Structure Trading Strategy',
        'proposer': 'Claude',
        'executor': 'Claude',
        'timestamp': start_time.isoformat(),
        'data_source': 'yfinance (^VIX, ^VIX3M, SPY, GLD)',
        'period': f'{START_DATE} to {END_DATE}',
    }

    # Download data
    prices = download_data()

    # Compute signals
    df = compute_signals(prices)
    results['n_observations'] = int(len(df))
    results['vix3m_coverage'] = float(df['vix_ratio'].notna().mean())

    # Part 1: Information content
    info_results = test_information_content(df)
    results['information_content'] = info_results

    # Part 2: Strategy backtests
    strat_results, returns_dict, dm_results = run_strategies(df)
    results['full_sample_strategies'] = strat_results
    results['dm_tests_vs_12vix'] = dm_results

    # Part 3: Cross-OOS
    cross_oos = cross_oos_validation(df, returns_dict)
    results['cross_oos'] = cross_oos

    # Part 4: Recent OOS
    recent_oos = recent_oos_test(df, returns_dict)
    results['recent_oos'] = recent_oos

    # Part 5: Sensitivity
    sensitivity = sensitivity_analysis(df)
    results['sensitivity'] = sensitivity

    # Part 6: Lag robustness
    lag_results, lag_decay = lag_robustness(df)
    results['lag_robustness'] = lag_results
    results['lag_decay'] = lag_decay

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY: K731 VIX Term Structure Trading Strategy")
    print("=" * 70)

    # Key findings
    best_strat = max(strat_results.items(), key=lambda x: x[1]['sharpe'] if x[0] != 'BH 50/50' else -999)
    baseline_sr = strat_results['12/VIX']['sharpe']
    best_name = best_strat[0]
    best_sr = best_strat[1]['sharpe']
    bh_sr = strat_results['BH 50/50']['sharpe']

    print(f"\n1. Information content:")
    print(f"   VIX→fwd vol corr:     {info_results['corr_vix_fwd_rv']:.4f}")
    print(f"   Ratio→fwd vol corr:   {info_results['corr_ratio_fwd_rv']:.4f}")
    print(f"   Incremental ΔR²:      {info_results['delta_r2']:.4f}")
    print(f"   F-test p-value:       {info_results['f_pval_ratio']:.4f}")

    print(f"\n2. Strategy comparison (full sample):")
    print(f"   BH 50/50 Sharpe:      {bh_sr:+.3f}")
    print(f"   12/VIX Sharpe:        {baseline_sr:+.3f}")
    print(f"   Best TS variant:      {best_name} Sharpe = {best_sr:+.3f}")
    print(f"   TS improvement:       {best_sr - baseline_sr:+.4f}")

    improvement_meaningful = abs(best_sr - baseline_sr) > 0.02

    print(f"\n3. Cross-OOS wins vs BH 50/50:")
    for name, oos in cross_oos.items():
        if name != 'BH 50/50':
            print(f"   {name:25s}: {oos['wins_vs_bh5050']}/5")

    print(f"\n4. Lag robustness:")
    print(f"   Lag-0 to Lag-1 decay: {lag_decay:+.4f}")
    print(f"   Smooth-weight:        {'YES' if abs(lag_decay) < 0.05 else 'NO'}")

    # Verdict
    print(f"\n5. VERDICT:")
    if improvement_meaningful:
        print(f"   VIX term structure ADDS meaningful information to 12/VIX.")
        print(f"   Best variant: {best_name} ({best_sr:+.3f} vs 12/VIX {baseline_sr:+.3f})")
        results['verdict'] = f'POSITIVE: {best_name} improves on 12/VIX by {best_sr - baseline_sr:+.4f} Sharpe'
    else:
        print(f"   VIX term structure does NOT meaningfully improve 12/VIX.")
        print(f"   This confirms VIX level sufficiency (consistent with K697, K702).")
        print(f"   Term structure info is largely absorbed by VIX level in smooth-weight context.")
        results['verdict'] = 'NULL: VIX term structure does not improve 12/VIX in smooth-weight trading'

    results['conclusion'] = {
        'bh_5050_sharpe': float(bh_sr),
        'twelve_vix_sharpe': float(baseline_sr),
        'best_ts_sharpe': float(best_sr),
        'best_ts_name': best_name,
        'improvement': float(best_sr - baseline_sr),
        'improvement_meaningful': bool(improvement_meaningful),
        'lag_robust': bool(abs(lag_decay) < 0.05),
    }

    # Save results
    results_path = Path(__file__).parent / 'k731_vix_term_structure_results.json'
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"Total runtime: {elapsed:.1f}s")

    return results


if __name__ == '__main__':
    results = main()
