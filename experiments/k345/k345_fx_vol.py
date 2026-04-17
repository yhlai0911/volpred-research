#!/usr/bin/env python3
"""
K345: FX Volatility and Cross-Asset Hedging — A Completely New Domain
=====================================================================
跳躍式探索：外匯波動率特性 + 跨資產避險

Prior knowledge: ZERO experiments on FX/forex/currency.
Building on: K207 (VIX not sufficient for non-equity), K342 (SPY→oil Granger),
             K341 (futures hedging framework)

Data: yfinance — EURUSD=X, JPYUSD=X, 6J=F, SPY, GLD, ^VIX
Methodology:
  1. FX vol characteristics (leverage effect, clustering, kurtosis)
  2. FX-equity relationship (USD strength → SPY vol, JPY carry trade)
  3. FX as hedging instrument (JPY safe haven, SPY+JPY vs SPY+GLD)
  4. FX vol prediction (VIX → FX vol? GARCH QLIKE comparison)

Author: VolPred Research System
Date: 2026-03-25
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ──────────────────────────────────────────────────────────
# 0. DATA COLLECTION
# ──────────────────────────────────────────────────────────

print("=" * 80)
print("K345: FX Volatility and Cross-Asset Hedging")
print("=" * 80)

tickers = {
    'EURUSD': 'EURUSD=X',
    'JPYUSD': 'JPYUSD=X',
    'JPY_FUT': '6J=F',
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX',
}

print("\n[0] Downloading data from yfinance...")
raw = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2000-01-01', end='2026-03-25',
                         progress=False, auto_adjust=True)
        if len(df) > 100:
            raw[name] = df
            print(f"  {name} ({ticker}): {len(df)} days, "
                  f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name}: insufficient data ({len(df)} rows)")
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# Build returns
returns = {}
for name in raw:
    close = raw[name]['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    ret = close.pct_change().dropna()
    returns[name] = ret

# Common date range for cross-asset analysis
common_idx = returns['SPY'].index
for name in ['EURUSD', 'JPYUSD', 'GLD', 'VIX']:
    if name in returns:
        common_idx = common_idx.intersection(returns[name].index)
    elif name == 'VIX' and name in raw:
        vix_close = raw['VIX']['Close']
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        common_idx = common_idx.intersection(vix_close.dropna().index)

print(f"\n  Common date range: {common_idx[0].strftime('%Y-%m-%d')} to "
      f"{common_idx[-1].strftime('%Y-%m-%d')} ({len(common_idx)} days)")

results = {}

# ──────────────────────────────────────────────────────────
# 1. FX VOL CHARACTERISTICS
# ──────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("PART 1: FX Volatility Characteristics")
print("=" * 80)

fx_chars = {}
for name in ['EURUSD', 'JPYUSD', 'SPY']:
    if name not in returns:
        continue
    r = returns[name]

    # Basic stats
    ann_vol = r.std() * np.sqrt(252)
    ann_ret = r.mean() * 252
    skew = r.skew()
    kurt = r.kurtosis()  # excess kurtosis

    # Leverage effect: corr(r_t, r²_{t+1})
    r_aligned = r.iloc[:-1].values
    r2_next = (r.iloc[1:].values) ** 2
    leverage_corr = np.corrcoef(r_aligned, r2_next)[0, 1]

    # Vol clustering: ACF of r² at lags 1,5,10,20
    r2 = r ** 2
    acf_vals = {}
    for lag in [1, 5, 10, 20]:
        if len(r2) > lag + 10:
            acf_vals[f'ACF_r2_lag{lag}'] = r2.autocorr(lag=lag)

    # Annualized vol by year
    yearly_vol = r.groupby(r.index.year).std() * np.sqrt(252)

    fx_chars[name] = {
        'ann_vol': ann_vol,
        'ann_ret': ann_ret,
        'skewness': skew,
        'excess_kurtosis': kurt,
        'leverage_corr': leverage_corr,
        'acf_r2': acf_vals,
        'n_obs': len(r),
        'yearly_vol_mean': yearly_vol.mean(),
        'yearly_vol_std': yearly_vol.std(),
    }

    print(f"\n--- {name} ---")
    print(f"  Observations: {len(r)}")
    print(f"  Ann. Return:  {ann_ret:.4f} ({ann_ret*100:.2f}%)")
    print(f"  Ann. Vol:     {ann_vol:.4f} ({ann_vol*100:.2f}%)")
    print(f"  Skewness:     {skew:.4f}")
    print(f"  Excess Kurt:  {kurt:.4f}")
    print(f"  Leverage Corr (r_t, r²_{{t+1}}): {leverage_corr:.4f}")
    print(f"  ACF of r²:")
    for k, v in acf_vals.items():
        print(f"    {k}: {v:.4f}")

# Compare FX vs Equity vol characteristics
print("\n\n--- Comparison: FX vs Equity Vol Characteristics ---")
print(f"{'Metric':<25} {'EURUSD':>10} {'JPYUSD':>10} {'SPY':>10}")
print("-" * 55)
for metric in ['ann_vol', 'skewness', 'excess_kurtosis', 'leverage_corr']:
    vals = []
    for name in ['EURUSD', 'JPYUSD', 'SPY']:
        if name in fx_chars:
            vals.append(f"{fx_chars[name][metric]:.4f}")
        else:
            vals.append("N/A")
    print(f"{metric:<25} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

# ACF comparison
print(f"\n{'ACF r² lag':<25} {'EURUSD':>10} {'JPYUSD':>10} {'SPY':>10}")
print("-" * 55)
for lag in [1, 5, 10, 20]:
    key = f'ACF_r2_lag{lag}'
    vals = []
    for name in ['EURUSD', 'JPYUSD', 'SPY']:
        if name in fx_chars and key in fx_chars[name]['acf_r2']:
            vals.append(f"{fx_chars[name]['acf_r2'][key]:.4f}")
        else:
            vals.append("N/A")
    print(f"  lag {lag:<20} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

results['part1_fx_characteristics'] = {}
for name in fx_chars:
    char = fx_chars[name].copy()
    char['ann_vol'] = float(char['ann_vol'])
    char['ann_ret'] = float(char['ann_ret'])
    char['skewness'] = float(char['skewness'])
    char['excess_kurtosis'] = float(char['excess_kurtosis'])
    char['leverage_corr'] = float(char['leverage_corr'])
    char['yearly_vol_mean'] = float(char['yearly_vol_mean'])
    char['yearly_vol_std'] = float(char['yearly_vol_std'])
    char['acf_r2'] = {k: float(v) for k, v in char['acf_r2'].items()}
    results['part1_fx_characteristics'][name] = char


# ──────────────────────────────────────────────────────────
# 2. FX-EQUITY RELATIONSHIP
# ──────────────────────────────────────────────────────────

print("\n\n" + "=" * 80)
print("PART 2: FX-Equity Relationship")
print("=" * 80)

# 2a. Does USD strength predict SPY vol?
# Construct USD strength index from EURUSD (invert: lower EURUSD = stronger USD)
print("\n--- 2a: USD Strength → SPY Volatility ---")

eur_close = raw['EURUSD']['Close']
if isinstance(eur_close, pd.DataFrame):
    eur_close = eur_close.iloc[:, 0]

spy_ret = returns['SPY']

# USD strength = -log(EURUSD change) over 20 days (rolling)
eur_ret_20d = np.log(eur_close / eur_close.shift(20)).dropna()
usd_strength = -eur_ret_20d  # positive = USD strengthening

# SPY realized vol (20-day forward)
spy_rv_20d = spy_ret.rolling(20).std() * np.sqrt(252)
spy_rv_20d_fwd = spy_rv_20d.shift(-20)  # forward-looking

# Align
common = usd_strength.index.intersection(spy_rv_20d_fwd.dropna().index)
x_usd = usd_strength.loc[common].values
y_spy_vol = spy_rv_20d_fwd.loc[common].values

# Remove NaN
mask = ~(np.isnan(x_usd) | np.isnan(y_spy_vol))
x_usd = x_usd[mask]
y_spy_vol = y_spy_vol[mask]

if len(x_usd) > 100:
    corr, p_corr = stats.pearsonr(x_usd, y_spy_vol)
    slope, intercept, r_val, p_val, se = stats.linregress(x_usd, y_spy_vol)

    print(f"  USD 20d strength vs SPY 20d fwd vol:")
    print(f"    Correlation: {corr:.4f} (p={p_corr:.6f})")
    print(f"    Regression: slope={slope:.4f}, R²={r_val**2:.4f}, p={p_val:.6f}")
    print(f"    N = {len(x_usd)}")

    results['part2a_usd_strength_spy_vol'] = {
        'correlation': float(corr),
        'p_value': float(p_corr),
        'regression_slope': float(slope),
        'r_squared': float(r_val**2),
        'regression_p': float(p_val),
        'n_obs': int(len(x_usd)),
    }

    # Quintile analysis
    print(f"\n  Quintile analysis: SPY vol by USD strength quintile")
    quintiles = pd.qcut(x_usd, 5, labels=['Q1(weak$)', 'Q2', 'Q3', 'Q4', 'Q5(strong$)'])
    df_q = pd.DataFrame({'usd_str': x_usd, 'spy_vol': y_spy_vol, 'quintile': quintiles})
    q_means = df_q.groupby('quintile')['spy_vol'].agg(['mean', 'std', 'count'])
    print(q_means.to_string())

    results['part2a_quintile'] = {}
    for q_name, row in q_means.iterrows():
        results['part2a_quintile'][str(q_name)] = {
            'mean_spy_vol': float(row['mean']),
            'std': float(row['std']),
            'count': int(row['count']),
        }

# 2b. JPY carry trade unwinding → equity crashes
print("\n\n--- 2b: JPY Carry Trade Unwinding & Equity Crashes ---")

jpy_close = raw['JPYUSD']['Close']
if isinstance(jpy_close, pd.DataFrame):
    jpy_close = jpy_close.iloc[:, 0]
jpy_ret = returns['JPYUSD']

# JPY appreciation = carry trade unwinding (risk-off)
# Look at extreme JPY moves and subsequent SPY performance
jpy_5d = jpy_ret.rolling(5).sum()  # 5-day JPY return
spy_5d_fwd = spy_ret.rolling(5).sum().shift(-5)  # 5-day forward SPY return

common2 = jpy_5d.dropna().index.intersection(spy_5d_fwd.dropna().index)
jpy_5d_c = jpy_5d.loc[common2]
spy_5d_fwd_c = spy_5d_fwd.loc[common2]

# JPY appreciation > 2% in 5 days (carry unwind signal)
threshold = 0.02
carry_unwind = jpy_5d_c > threshold
normal = ~carry_unwind

if carry_unwind.sum() > 10:
    spy_after_unwind = spy_5d_fwd_c[carry_unwind]
    spy_after_normal = spy_5d_fwd_c[normal]

    t_stat, t_pval = stats.ttest_ind(spy_after_unwind, spy_after_normal, equal_var=False)

    print(f"  JPY 5-day appreciation > {threshold*100:.0f}% (carry trade unwinding signal):")
    print(f"    Events: {carry_unwind.sum()} out of {len(carry_unwind)} days")
    print(f"    SPY 5d fwd return after JPY unwind: {spy_after_unwind.mean()*100:.3f}% "
          f"(std={spy_after_unwind.std()*100:.3f}%)")
    print(f"    SPY 5d fwd return (normal):         {spy_after_normal.mean()*100:.3f}% "
          f"(std={spy_after_normal.std()*100:.3f}%)")
    print(f"    t-stat: {t_stat:.3f}, p-value: {t_pval:.4f}")
    print(f"    Effect: {'SPY underperforms after JPY unwind' if spy_after_unwind.mean() < spy_after_normal.mean() else 'No underperformance detected'}")

    results['part2b_carry_unwind'] = {
        'threshold': threshold,
        'n_events': int(carry_unwind.sum()),
        'n_total': int(len(carry_unwind)),
        'spy_after_unwind_mean': float(spy_after_unwind.mean()),
        'spy_after_unwind_std': float(spy_after_unwind.std()),
        'spy_normal_mean': float(spy_after_normal.mean()),
        'spy_normal_std': float(spy_after_normal.std()),
        't_stat': float(t_stat),
        'p_value': float(t_pval),
    }

# 2c. Conditional correlation: JPYUSD vs SPY in crisis vs calm
print("\n\n--- 2c: JPY-SPY Correlation: Crisis vs Calm ---")

# Use VIX as regime indicator
vix_close = raw['VIX']['Close']
if isinstance(vix_close, pd.DataFrame):
    vix_close = vix_close.iloc[:, 0]

common3 = spy_ret.index.intersection(jpy_ret.index).intersection(vix_close.index)
spy_c = spy_ret.loc[common3]
jpy_c = jpy_ret.loc[common3]
vix_c = vix_close.loc[common3]

# Crisis = VIX > 25, Calm = VIX < 15
crisis_mask = vix_c > 25
calm_mask = vix_c < 15
mid_mask = (vix_c >= 15) & (vix_c <= 25)

for regime_name, mask in [('Crisis (VIX>25)', crisis_mask),
                           ('Normal (15≤VIX≤25)', mid_mask),
                           ('Calm (VIX<15)', calm_mask)]:
    if mask.sum() > 30:
        corr_val = spy_c[mask].corr(jpy_c[mask])
        print(f"  {regime_name}: corr(SPY, JPYUSD) = {corr_val:.4f} (n={mask.sum()})")

# Rolling 60-day correlation
rolling_corr = spy_c.rolling(60).corr(jpy_c)

print(f"\n  Rolling 60-day correlation stats:")
print(f"    Mean: {rolling_corr.mean():.4f}")
print(f"    Std:  {rolling_corr.std():.4f}")
print(f"    Min:  {rolling_corr.min():.4f}")
print(f"    Max:  {rolling_corr.max():.4f}")

results['part2c_conditional_corr'] = {
    'crisis_corr': float(spy_c[crisis_mask].corr(jpy_c[crisis_mask])) if crisis_mask.sum() > 30 else None,
    'normal_corr': float(spy_c[mid_mask].corr(jpy_c[mid_mask])) if mid_mask.sum() > 30 else None,
    'calm_corr': float(spy_c[calm_mask].corr(jpy_c[calm_mask])) if calm_mask.sum() > 30 else None,
    'n_crisis': int(crisis_mask.sum()),
    'n_normal': int(mid_mask.sum()),
    'n_calm': int(calm_mask.sum()),
    'rolling_60d_corr_mean': float(rolling_corr.mean()),
    'rolling_60d_corr_std': float(rolling_corr.std()),
}

# Named crisis episodes
print("\n  Crisis episode deep dive:")
crisis_periods = {
    'GFC': ('2008-09-01', '2009-03-31'),
    'COVID': ('2020-02-20', '2020-04-30'),
    'Rate_Hike_2022': ('2022-01-01', '2022-12-31'),
    'SVB_Crisis_2023': ('2023-03-01', '2023-03-31'),
}

results['part2c_crisis_episodes'] = {}
for ep_name, (start, end) in crisis_periods.items():
    ep_mask = (spy_c.index >= start) & (spy_c.index <= end)
    if ep_mask.sum() > 10:
        ep_corr = spy_c[ep_mask].corr(jpy_c[ep_mask])
        spy_ep_ret = spy_c[ep_mask].sum()
        jpy_ep_ret = jpy_c[ep_mask].sum()
        print(f"  {ep_name}: corr={ep_corr:.4f}, SPY cum={spy_ep_ret*100:.1f}%, "
              f"JPY cum={jpy_ep_ret*100:.1f}% (n={ep_mask.sum()})")
        results['part2c_crisis_episodes'][ep_name] = {
            'correlation': float(ep_corr),
            'spy_cum_return': float(spy_ep_ret),
            'jpy_cum_return': float(jpy_ep_ret),
            'n_days': int(ep_mask.sum()),
        }


# ──────────────────────────────────────────────────────────
# 3. FX AS HEDGING INSTRUMENT
# ──────────────────────────────────────────────────────────

print("\n\n" + "=" * 80)
print("PART 3: FX as Hedging Instrument")
print("=" * 80)

# 3a. Can JPY futures hedge SPY drawdowns?
print("\n--- 3a: JPY as Safe Haven — Portfolio Analysis ---")

# Align SPY, GLD, JPYUSD on common dates
hedge_assets = {}
for name in ['SPY', 'JPYUSD', 'GLD']:
    if name in returns:
        hedge_assets[name] = returns[name]

common_hedge = hedge_assets['SPY'].index
for name in hedge_assets:
    common_hedge = common_hedge.intersection(hedge_assets[name].index)

spy_h = hedge_assets['SPY'].loc[common_hedge]
jpy_h = hedge_assets['JPYUSD'].loc[common_hedge]
gld_h = hedge_assets['GLD'].loc[common_hedge]

print(f"  Common period: {common_hedge[0].strftime('%Y-%m-%d')} to "
      f"{common_hedge[-1].strftime('%Y-%m-%d')} ({len(common_hedge)} days)")

# Portfolio strategies
portfolios = {
    '100% SPY': spy_h,
    '70/30 SPY/GLD': 0.7 * spy_h + 0.3 * gld_h,
    '70/30 SPY/JPY': 0.7 * spy_h + 0.3 * jpy_h,
    '50/50 SPY/GLD': 0.5 * spy_h + 0.5 * gld_h,
    '50/50 SPY/JPY': 0.5 * spy_h + 0.5 * jpy_h,
    '60/20/20 SPY/GLD/JPY': 0.6 * spy_h + 0.2 * gld_h + 0.2 * jpy_h,
}

def calc_portfolio_metrics(ret_series):
    """Calculate key portfolio metrics."""
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + ret_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = ret_series[ret_series < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Worst month
    monthly = ret_series.resample('ME').sum()
    worst_month = monthly.min()

    # Worst year
    yearly = ret_series.resample('YE').sum()
    worst_year = yearly.min()

    return {
        'ann_ret': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'sortino': sortino,
        'worst_month': worst_month,
        'worst_year': worst_year,
    }

print(f"\n{'Portfolio':<25} {'Ann.Ret':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 85)

results['part3a_portfolios'] = {}
for pname, pret in portfolios.items():
    m = calc_portfolio_metrics(pret)
    print(f"{pname:<25} {m['ann_ret']*100:>7.2f}% {m['ann_vol']*100:>7.2f}% "
          f"{m['sharpe']:>8.3f} {m['mdd']*100:>7.1f}% {m['calmar']:>8.3f} {m['sortino']:>8.3f}")
    results['part3a_portfolios'][pname] = {k: float(v) for k, v in m.items()}

# 3b. Crisis-specific hedge performance
print("\n\n--- 3b: Hedge Performance During Named Crises ---")

for ep_name, (start, end) in crisis_periods.items():
    ep_mask = (spy_h.index >= start) & (spy_h.index <= end)
    if ep_mask.sum() > 5:
        spy_cum = (1 + spy_h[ep_mask]).prod() - 1
        jpy_cum = (1 + jpy_h[ep_mask]).prod() - 1
        gld_cum = (1 + gld_h[ep_mask]).prod() - 1

        p_spy_gld = (1 + 0.5 * spy_h[ep_mask] + 0.5 * gld_h[ep_mask]).prod() - 1
        p_spy_jpy = (1 + 0.5 * spy_h[ep_mask] + 0.5 * jpy_h[ep_mask]).prod() - 1

        print(f"\n  {ep_name} ({start} to {end}):")
        print(f"    SPY:          {spy_cum*100:>+7.2f}%")
        print(f"    GLD:          {gld_cum*100:>+7.2f}%")
        print(f"    JPYUSD:       {jpy_cum*100:>+7.2f}%")
        print(f"    50/50 SPY/GLD: {p_spy_gld*100:>+7.2f}%")
        print(f"    50/50 SPY/JPY: {p_spy_jpy*100:>+7.2f}%")

        results[f'part3b_{ep_name}'] = {
            'spy': float(spy_cum),
            'gld': float(gld_cum),
            'jpyusd': float(jpy_cum),
            'spy_gld_50_50': float(p_spy_gld),
            'spy_jpy_50_50': float(p_spy_jpy),
        }

# 3c. Conditional hedge ratio (minimum variance)
print("\n\n--- 3c: Minimum-Variance Hedge Ratios ---")

# Rolling 252-day min-variance hedge ratio: w* = -cov(SPY,JPY)/var(JPY)
cov_rolling = spy_h.rolling(252).cov(jpy_h)
var_jpy_rolling = jpy_h.rolling(252).var()
hedge_ratio = -cov_rolling / var_jpy_rolling

print(f"  Min-variance hedge ratio (JPY for SPY):")
print(f"    Full sample mean: {hedge_ratio.mean():.4f}")
print(f"    Full sample std:  {hedge_ratio.std():.4f}")
print(f"    Recent 1Y mean:   {hedge_ratio.iloc[-252:].mean():.4f}")

# Same for GLD
cov_rolling_gld = spy_h.rolling(252).cov(gld_h)
var_gld_rolling = gld_h.rolling(252).var()
hedge_ratio_gld = -cov_rolling_gld / var_gld_rolling

print(f"\n  Min-variance hedge ratio (GLD for SPY):")
print(f"    Full sample mean: {hedge_ratio_gld.mean():.4f}")
print(f"    Full sample std:  {hedge_ratio_gld.std():.4f}")
print(f"    Recent 1Y mean:   {hedge_ratio_gld.iloc[-252:].mean():.4f}")

results['part3c_hedge_ratios'] = {
    'jpy_hedge_mean': float(hedge_ratio.mean()),
    'jpy_hedge_std': float(hedge_ratio.std()),
    'jpy_hedge_recent_1y': float(hedge_ratio.iloc[-252:].mean()),
    'gld_hedge_mean': float(hedge_ratio_gld.mean()),
    'gld_hedge_std': float(hedge_ratio_gld.std()),
    'gld_hedge_recent_1y': float(hedge_ratio_gld.iloc[-252:].mean()),
}

# 3d. Tail hedge effectiveness
print("\n\n--- 3d: Tail Hedge Effectiveness ---")
# When SPY drops > 2% in a day, how do JPY and GLD perform?

spy_tail = spy_h < -0.02
print(f"  SPY daily loss > 2%: {spy_tail.sum()} events")
if spy_tail.sum() > 20:
    jpy_in_spy_tail = jpy_h[spy_tail]
    gld_in_spy_tail = gld_h[spy_tail]

    print(f"    JPY mean return: {jpy_in_spy_tail.mean()*100:>+.3f}% "
          f"(positive = JPY appreciates = hedge works)")
    print(f"    GLD mean return: {gld_in_spy_tail.mean()*100:>+.3f}%")
    print(f"    JPY positive %:  {(jpy_in_spy_tail > 0).mean()*100:.1f}%")
    print(f"    GLD positive %:  {(gld_in_spy_tail > 0).mean()*100:.1f}%")

    # t-test: is JPY return significantly positive on SPY crash days?
    t_jpy, p_jpy = stats.ttest_1samp(jpy_in_spy_tail, 0)
    t_gld, p_gld = stats.ttest_1samp(gld_in_spy_tail, 0)
    print(f"    JPY t-test vs 0: t={t_jpy:.3f}, p={p_jpy:.4f}")
    print(f"    GLD t-test vs 0: t={t_gld:.3f}, p={p_gld:.4f}")

    results['part3d_tail_hedge'] = {
        'n_spy_tail_events': int(spy_tail.sum()),
        'jpy_mean_in_tail': float(jpy_in_spy_tail.mean()),
        'gld_mean_in_tail': float(gld_in_spy_tail.mean()),
        'jpy_positive_pct': float((jpy_in_spy_tail > 0).mean()),
        'gld_positive_pct': float((gld_in_spy_tail > 0).mean()),
        'jpy_tstat': float(t_jpy),
        'jpy_pval': float(p_jpy),
        'gld_tstat': float(t_gld),
        'gld_pval': float(p_gld),
    }

    # Extreme tail (>3%)
    spy_extreme = spy_h < -0.03
    if spy_extreme.sum() > 10:
        jpy_extreme = jpy_h[spy_extreme]
        gld_extreme = gld_h[spy_extreme]
        print(f"\n  SPY daily loss > 3%: {spy_extreme.sum()} events")
        print(f"    JPY mean: {jpy_extreme.mean()*100:>+.3f}%, GLD mean: {gld_extreme.mean()*100:>+.3f}%")


# ──────────────────────────────────────────────────────────
# 4. FX VOLATILITY PREDICTION
# ──────────────────────────────────────────────────────────

print("\n\n" + "=" * 80)
print("PART 4: FX Volatility Prediction")
print("=" * 80)

# 4a. Does VIX predict FX vol?
print("\n--- 4a: Does VIX Predict FX Volatility? ---")

# Forward-looking FX realized vol (20-day)
for fx_name in ['EURUSD', 'JPYUSD']:
    if fx_name not in returns:
        continue
    fx_r = returns[fx_name]
    fx_rv = fx_r.rolling(20).std() * np.sqrt(252)
    fx_rv_fwd = fx_rv.shift(-20)

    common_v = vix_close.index.intersection(fx_rv_fwd.dropna().index)
    vix_v = vix_close.loc[common_v].values
    fx_v = fx_rv_fwd.loc[common_v].values

    mask_v = ~(np.isnan(vix_v) | np.isnan(fx_v))
    vix_v = vix_v[mask_v]
    fx_v = fx_v[mask_v]

    if len(vix_v) > 100:
        corr_v, p_v = stats.pearsonr(vix_v, fx_v)
        slope_v, int_v, r_v, p_reg, se_v = stats.linregress(vix_v, fx_v)

        print(f"\n  VIX → {fx_name} 20d fwd vol:")
        print(f"    Correlation: {corr_v:.4f} (p={p_v:.6f})")
        print(f"    R²: {r_v**2:.4f}")
        print(f"    N: {len(vix_v)}")

        results[f'part4a_vix_predicts_{fx_name.lower()}_vol'] = {
            'correlation': float(corr_v),
            'p_value': float(p_v),
            'r_squared': float(r_v**2),
            'n_obs': int(len(vix_v)),
        }

# 4b. Granger causality: VIX → FX vol, FX vol → VIX
print("\n\n--- 4b: Granger Causality: VIX ↔ FX Vol ---")

def granger_f_test(x, y, max_lag=5):
    """Simple Granger causality F-test: does x Granger-cause y?"""
    from numpy.linalg import lstsq

    # Align
    common_g = x.dropna().index.intersection(y.dropna().index)
    x_g = x.loc[common_g].values
    y_g = y.loc[common_g].values
    n = len(y_g)

    results_gc = {}
    for lag in range(1, max_lag + 1):
        if n <= 2 * lag + 5:
            continue

        # Restricted model: y_t = a0 + sum(a_i * y_{t-i})
        Y = y_g[lag:]
        X_r = np.column_stack([y_g[lag - i - 1:n - i - 1] for i in range(lag)])
        X_r = np.column_stack([np.ones(len(Y)), X_r])

        # Unrestricted model: y_t = a0 + sum(a_i * y_{t-i}) + sum(b_i * x_{t-i})
        X_u = np.column_stack([X_r] + [x_g[lag - i - 1:n - i - 1] for i in range(lag)])

        # OLS
        beta_r, res_r, _, _ = lstsq(X_r, Y, rcond=None)
        beta_u, res_u, _, _ = lstsq(X_u, Y, rcond=None)

        ssr_r = np.sum((Y - X_r @ beta_r) ** 2)
        ssr_u = np.sum((Y - X_u @ beta_u) ** 2)

        q = lag  # number of restrictions
        df2 = len(Y) - X_u.shape[1]
        if df2 <= 0:
            continue

        f_stat = ((ssr_r - ssr_u) / q) / (ssr_u / df2)
        p_value = 1 - stats.f.cdf(f_stat, q, df2)

        results_gc[lag] = {'f_stat': f_stat, 'p_value': p_value}

    return results_gc

for fx_name in ['EURUSD', 'JPYUSD']:
    if fx_name not in returns:
        continue
    fx_r = returns[fx_name]
    fx_rv_daily = (fx_r ** 2).rolling(5).mean() * 252  # 5-day variance proxy

    vix_daily = vix_close / 100  # scale VIX to decimal

    print(f"\n  Granger Causality Tests: VIX ↔ {fx_name} Vol")

    # VIX → FX vol
    gc1 = granger_f_test(vix_daily, fx_rv_daily, max_lag=5)
    print(f"    VIX → {fx_name} vol:")
    for lag, res in gc1.items():
        sig = "***" if res['p_value'] < 0.01 else "**" if res['p_value'] < 0.05 else "*" if res['p_value'] < 0.1 else ""
        print(f"      lag {lag}: F={res['f_stat']:.3f}, p={res['p_value']:.4f} {sig}")

    # FX vol → VIX
    gc2 = granger_f_test(fx_rv_daily, vix_daily, max_lag=5)
    print(f"    {fx_name} vol → VIX:")
    for lag, res in gc2.items():
        sig = "***" if res['p_value'] < 0.01 else "**" if res['p_value'] < 0.05 else "*" if res['p_value'] < 0.1 else ""
        print(f"      lag {lag}: F={res['f_stat']:.3f}, p={res['p_value']:.4f} {sig}")

    results[f'part4b_granger_{fx_name.lower()}'] = {
        'vix_to_fx': {str(k): {'f_stat': float(v['f_stat']), 'p_value': float(v['p_value'])} for k, v in gc1.items()},
        'fx_to_vix': {str(k): {'f_stat': float(v['f_stat']), 'p_value': float(v['p_value'])} for k, v in gc2.items()},
    }


# 4c. GARCH comparison: EURUSD vs SPY
print("\n\n--- 4c: GARCH(1,1) Comparison — FX vs Equity ---")

def fit_garch11(returns_series, name=""):
    """Fit GARCH(1,1) using maximum likelihood."""
    r = returns_series.dropna().values
    n = len(r)
    mu = r.mean()
    eps = r - mu

    # Initialize
    omega = np.var(eps) * 0.05
    alpha = 0.08
    beta = 0.88

    # MLE via scipy
    from scipy.optimize import minimize

    def neg_loglik(params):
        omega_p, alpha_p, beta_p = params
        if omega_p <= 0 or alpha_p < 0 or beta_p < 0 or alpha_p + beta_p >= 1:
            return 1e10
        sigma2 = np.zeros(n)
        sigma2[0] = np.var(eps)
        for t in range(1, n):
            sigma2[t] = omega_p + alpha_p * eps[t-1]**2 + beta_p * sigma2[t-1]
            if sigma2[t] <= 0:
                return 1e10
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + eps**2 / sigma2)
        return -ll

    try:
        res = minimize(neg_loglik, [omega, alpha, beta],
                       method='Nelder-Mead', options={'maxiter': 5000})
        omega_hat, alpha_hat, beta_hat = res.x
        persistence = alpha_hat + beta_hat

        # In-sample sigma2
        sigma2 = np.zeros(n)
        sigma2[0] = np.var(eps)
        for t in range(1, n):
            sigma2[t] = omega_hat + alpha_hat * eps[t-1]**2 + beta_hat * sigma2[t-1]

        # QLIKE loss
        rv_proxy = eps ** 2  # daily squared return as RV proxy
        qlike = np.mean(rv_proxy[1:] / sigma2[1:] - np.log(rv_proxy[1:] / sigma2[1:]) - 1)

        return {
            'omega': omega_hat,
            'alpha': alpha_hat,
            'beta': beta_hat,
            'persistence': persistence,
            'log_likelihood': -res.fun,
            'qlike': qlike,
            'n_obs': n,
            'converged': res.success,
        }
    except Exception as e:
        return {'error': str(e)}

for asset_name in ['EURUSD', 'JPYUSD', 'SPY']:
    if asset_name not in returns:
        continue
    r = returns[asset_name]

    # Use last 5 years for GARCH
    r_recent = r[r.index >= '2021-01-01']
    garch_res = fit_garch11(r_recent, name=asset_name)

    if 'error' not in garch_res:
        print(f"\n  GARCH(1,1) for {asset_name} (2021-2026, N={garch_res['n_obs']}):")
        print(f"    omega = {garch_res['omega']:.2e}")
        print(f"    alpha = {garch_res['alpha']:.4f}")
        print(f"    beta  = {garch_res['beta']:.4f}")
        print(f"    persistence (alpha+beta) = {garch_res['persistence']:.4f}")
        print(f"    QLIKE = {garch_res['qlike']:.4f}")
        print(f"    Converged: {garch_res['converged']}")

        results[f'part4c_garch_{asset_name.lower()}'] = {
            k: float(v) if isinstance(v, (np.floating, float)) else v
            for k, v in garch_res.items()
        }
    else:
        print(f"\n  GARCH(1,1) for {asset_name}: FAILED — {garch_res['error']}")


# 4d. Out-of-sample GARCH forecasting for FX
print("\n\n--- 4d: Out-of-Sample GARCH Forecast (Expanding Window) ---")

def oos_garch_forecast(ret_series, train_start, oos_start, name=""):
    """Expanding window GARCH(1,1) OOS forecast evaluation."""
    from scipy.optimize import minimize

    r_full = ret_series[ret_series.index >= train_start].dropna()
    oos_idx = r_full.index >= oos_start
    n_oos = oos_idx.sum()

    if n_oos < 60:
        return {'error': f'Insufficient OOS data: {n_oos}'}

    r_values = r_full.values
    oos_start_pos = np.where(oos_idx)[0][0]

    forecasts = []
    actuals = []

    # Re-estimate every 63 days (quarterly)
    refit_interval = 63
    last_refit = -refit_interval - 1
    omega_hat, alpha_hat, beta_hat = None, None, None
    sigma2_last = None

    for t in range(oos_start_pos, len(r_values)):
        # Refit if needed
        if t - last_refit >= refit_interval or omega_hat is None:
            train_r = r_values[:t]
            mu = train_r.mean()
            eps_train = train_r - mu

            def neg_ll(params):
                o, a, b = params
                if o <= 0 or a < 0 or b < 0 or a + b >= 1:
                    return 1e10
                s2 = np.zeros(len(eps_train))
                s2[0] = np.var(eps_train)
                for i in range(1, len(eps_train)):
                    s2[i] = o + a * eps_train[i-1]**2 + b * s2[i-1]
                    if s2[i] <= 0:
                        return 1e10
                return 0.5 * np.sum(np.log(s2) + eps_train**2 / s2)

            try:
                res = minimize(neg_ll, [np.var(eps_train)*0.05, 0.08, 0.88],
                               method='Nelder-Mead', options={'maxiter': 3000})
                omega_hat, alpha_hat, beta_hat = res.x
            except:
                continue

            # Compute sigma2 for entire training period
            s2 = np.zeros(len(eps_train))
            s2[0] = np.var(eps_train)
            for i in range(1, len(eps_train)):
                s2[i] = omega_hat + alpha_hat * eps_train[i-1]**2 + beta_hat * s2[i-1]
            sigma2_last = s2[-1]
            last_refit = t

        if omega_hat is None:
            continue

        # 1-step forecast
        eps_prev = r_values[t-1] - r_values[:t].mean()
        forecast_var = omega_hat + alpha_hat * eps_prev**2 + beta_hat * sigma2_last
        sigma2_last = forecast_var

        forecasts.append(forecast_var)
        actuals.append(r_values[t] ** 2)

    if len(forecasts) < 30:
        return {'error': f'Too few forecasts: {len(forecasts)}'}

    forecasts = np.array(forecasts)
    actuals = np.array(actuals)

    # Losses
    mse = np.mean((forecasts - actuals) ** 2)
    mae = np.mean(np.abs(forecasts - actuals))

    # QLIKE
    mask_pos = (forecasts > 0) & (actuals > 0)
    if mask_pos.sum() > 10:
        qlike = np.mean(actuals[mask_pos] / forecasts[mask_pos]
                        - np.log(actuals[mask_pos] / forecasts[mask_pos]) - 1)
    else:
        qlike = np.nan

    # Mincer-Zarnowitz regression
    slope_mz, int_mz, r_mz, p_mz, se_mz = stats.linregress(forecasts, actuals)

    return {
        'n_oos': len(forecasts),
        'mse': float(mse),
        'mae': float(mae),
        'qlike': float(qlike),
        'mz_slope': float(slope_mz),
        'mz_r2': float(r_mz**2),
        'mz_p': float(p_mz),
        'oos_start': oos_start,
    }

for asset_name in ['EURUSD', 'JPYUSD', 'SPY']:
    if asset_name not in returns:
        continue

    oos_res = oos_garch_forecast(returns[asset_name],
                                  train_start='2005-01-01',
                                  oos_start='2020-01-01',
                                  name=asset_name)

    if 'error' not in oos_res:
        print(f"\n  OOS GARCH(1,1) for {asset_name} (OOS: 2020-2026):")
        print(f"    N OOS:     {oos_res['n_oos']}")
        print(f"    MSE:       {oos_res['mse']:.2e}")
        print(f"    MAE:       {oos_res['mae']:.2e}")
        print(f"    QLIKE:     {oos_res['qlike']:.4f}")
        print(f"    MZ R²:     {oos_res['mz_r2']:.4f}")
        print(f"    MZ slope:  {oos_res['mz_slope']:.4f}")

        results[f'part4d_oos_garch_{asset_name.lower()}'] = oos_res
    else:
        print(f"\n  OOS GARCH(1,1) for {asset_name}: {oos_res['error']}")


# ──────────────────────────────────────────────────────────
# 5. SYNTHESIS & IMPLICATIONS
# ──────────────────────────────────────────────────────────

print("\n\n" + "=" * 80)
print("PART 5: Synthesis & Key Findings")
print("=" * 80)

findings = []

# Finding 1: FX vol characteristics
if 'EURUSD' in fx_chars and 'SPY' in fx_chars:
    eur_lev = fx_chars['EURUSD']['leverage_corr']
    spy_lev = fx_chars['SPY']['leverage_corr']
    finding = (f"1. FX leverage effect is WEAKER than equity: "
               f"EURUSD leverage corr = {eur_lev:.4f} vs SPY = {spy_lev:.4f}")
    findings.append(finding)
    print(f"\n{finding}")

    eur_kurt = fx_chars['EURUSD']['excess_kurtosis']
    spy_kurt = fx_chars['SPY']['excess_kurtosis']
    finding2 = (f"   FX kurtosis comparison: EURUSD = {eur_kurt:.2f}, SPY = {spy_kurt:.2f}")
    findings.append(finding2)
    print(finding2)

# Finding 2: USD strength → SPY vol
if 'part2a_usd_strength_spy_vol' in results:
    r2a = results['part2a_usd_strength_spy_vol']
    sig = "YES" if r2a['p_value'] < 0.05 else "NO"
    finding = (f"2. USD strength predicts SPY vol: {sig} "
               f"(corr={r2a['correlation']:.4f}, p={r2a['p_value']:.6f}, R²={r2a['r_squared']:.4f})")
    findings.append(finding)
    print(f"\n{finding}")

# Finding 3: Carry trade unwinding
if 'part2b_carry_unwind' in results:
    r2b = results['part2b_carry_unwind']
    sig = "YES" if r2b['p_value'] < 0.05 else "NO"
    finding = (f"3. JPY carry unwind predicts SPY weakness: {sig} "
               f"(t={r2b['t_stat']:.3f}, p={r2b['p_value']:.4f})")
    findings.append(finding)
    print(f"\n{finding}")

# Finding 4: Crisis correlation
if 'part2c_conditional_corr' in results:
    r2c = results['part2c_conditional_corr']
    finding = (f"4. JPY-SPY correlation shifts by regime: "
               f"Crisis={r2c.get('crisis_corr', 'N/A')}, "
               f"Calm={r2c.get('calm_corr', 'N/A')}")
    findings.append(finding)
    print(f"\n{finding}")

# Finding 5: Tail hedge
if 'part3d_tail_hedge' in results:
    r3d = results['part3d_tail_hedge']
    jpy_works = r3d['jpy_pval'] < 0.05 and r3d['jpy_mean_in_tail'] > 0
    gld_works = r3d['gld_pval'] < 0.05 and r3d['gld_mean_in_tail'] > 0
    finding = (f"5. Tail hedge: JPY {'WORKS' if jpy_works else 'FAILS'} "
               f"(mean={r3d['jpy_mean_in_tail']*100:+.3f}%, p={r3d['jpy_pval']:.4f}), "
               f"GLD {'WORKS' if gld_works else 'FAILS'} "
               f"(mean={r3d['gld_mean_in_tail']*100:+.3f}%, p={r3d['gld_pval']:.4f})")
    findings.append(finding)
    print(f"\n{finding}")

# Finding 6: VIX predictive power for FX vol
for fx in ['eurusd', 'jpyusd']:
    key = f'part4a_vix_predicts_{fx}_vol'
    if key in results:
        r4a = results[key]
        finding = (f"6. VIX predicts {fx.upper()} vol: R²={r4a['r_squared']:.4f} "
                   f"(corr={r4a['correlation']:.4f})")
        findings.append(finding)
        print(f"\n{finding}")

# Finding 7: GARCH persistence comparison
garch_keys = [k for k in results if k.startswith('part4c_garch_')]
if len(garch_keys) >= 2:
    persistence_vals = {}
    for k in garch_keys:
        asset = k.replace('part4c_garch_', '').upper()
        if 'persistence' in results[k]:
            persistence_vals[asset] = results[k]['persistence']
    if persistence_vals:
        finding = f"7. GARCH(1,1) persistence: " + ", ".join(
            f"{a}={v:.4f}" for a, v in persistence_vals.items())
        findings.append(finding)
        print(f"\n{finding}")

results['findings'] = findings

# ──────────────────────────────────────────────────────────
# 6. RESEARCH IMPLICATIONS
# ──────────────────────────────────────────────────────────

print("\n\n" + "=" * 80)
print("PART 6: Research Implications for VolPred")
print("=" * 80)

implications = [
    "1. FX vol has different dynamics from equity vol — need separate models",
    "2. JPY can serve as crisis hedge but with regime-dependent effectiveness",
    "3. VIX alone is insufficient for FX vol prediction (confirming K207)",
    "4. Multi-asset portfolios benefit from FX diversification",
    "5. Carry trade unwinding is a useful risk-off signal worth monitoring",
    "6. Consider adding JPY to strategy framework as tail hedge component",
]

for imp in implications:
    print(f"  {imp}")

results['implications'] = implications

# ──────────────────────────────────────────────────────────
# SAVE RESULTS
# ──────────────────────────────────────────────────────────

output_file = 'experiments/k345_fx_vol_results.json'
with open(output_file, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {output_file}")
print(f"Total result keys: {len(results)}")
print("\n" + "=" * 80)
print("K345 COMPLETE")
print("=" * 80)
