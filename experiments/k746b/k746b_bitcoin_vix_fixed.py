"""
K746b: Bitcoin Volatility and VIX — Crypto Fear Channel (Fixed Methodology)

Fixes from Codex K746 review (2 HIGH issues):
1. Granger tests now use FORWARD-LOOKING target: |r_{BTC,t+1}| (next-day absolute return)
   instead of backward-looking 22d rolling RV (overlapping, not truly forward)
   Also tests reverse: lagged BTC |r_t| → next-day VIX change
   Lag selection via AIC (not min-p cherry-picking)
2. Fisher z-test now compares VIX-BTC_RV correlation (not BTC-SPY return corr)
   Andrews (1993) unknown-breakpoint sup-Wald test instead of hardcoded 2021

Kept from K746:
- Same data (BTC-USD, SPY, GLD, VIX from yfinance 2015-2026)
- Descriptive statistics, tail dependence, regime analysis
- Portfolio implications (5% BTC, VIX-conditioned)

Data: BTC-USD, SPY, GLD, ^VIX from yfinance (2015-01 to 2026-03)
[提出: Codex (K746 review), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

warnings.filterwarnings('ignore')

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K746b: Bitcoin Volatility and VIX — Crypto Fear Channel (FIXED)")
print("=" * 70)

tickers = {
    'BTC': 'BTC-USD',
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX'
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2015-01-01', end='2026-03-30', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].dropna()
    print(f"{name}: {len(data[name])} obs, {data[name].index[0].date()} to {data[name].index[-1].date()}")

# Align all series
df_all = pd.DataFrame(data)
df_all = df_all.dropna()
print(f"\nAligned dataset: {len(df_all)} obs, {df_all.index[0].date()} to {df_all.index[-1].date()}")

# Simple returns
returns = df_all[['BTC', 'SPY', 'GLD']].pct_change().dropna()

# ============================================================
# PART A: DESCRIPTIVE STATISTICS (unchanged from K746)
# ============================================================
print("\n" + "=" * 70)
print("PART A: BTC Volatility Characteristics")
print("=" * 70)

desc_stats = {}
for asset in ['BTC', 'SPY', 'GLD']:
    r = returns[asset]
    ann_vol = r.std() * np.sqrt(252) * 100
    desc_stats[asset] = {
        'n_obs': len(r),
        'ann_return_pct': float((1 + r).prod() ** (252 / len(r)) - 1) * 100,
        'ann_vol_pct': float(ann_vol),
        'skewness': float(stats.skew(r)),
        'kurtosis': float(stats.kurtosis(r)),
        'min_daily_pct': float(r.min() * 100),
        'max_daily_pct': float(r.max() * 100),
        'adf_stat': float(adfuller(r, maxlag=10)[0]),
        'adf_pval': float(adfuller(r, maxlag=10)[1]),
    }
    print(f"\n--- {asset} ---")
    for k, v in desc_stats[asset].items():
        print(f"  {k}: {v:.4f}")

# Realized volatility (22-day rolling) — for correlations only, NOT for Granger
for asset in ['BTC', 'SPY', 'GLD']:
    returns[f'{asset}_RV22'] = returns[asset].rolling(22).std() * np.sqrt(252) * 100

# Absolute returns (non-overlapping daily vol proxy)
for asset in ['BTC', 'SPY']:
    returns[f'{asset}_absret'] = returns[asset].abs()

# VIX level (aligned to returns index)
returns['VIX'] = df_all['VIX'].reindex(returns.index)
returns = returns.dropna()

print(f"\nFinal dataset with RV: {len(returns)} obs")
print(f"BTC RV22 mean: {returns['BTC_RV22'].mean():.1f}%  median: {returns['BTC_RV22'].median():.1f}%")
print(f"SPY RV22 mean: {returns['SPY_RV22'].mean():.1f}%  median: {returns['SPY_RV22'].median():.1f}%")
print(f"VIX    mean: {returns['VIX'].mean():.1f}   median: {returns['VIX'].median():.1f}")

# ============================================================
# PART B: CROSS-ASSET VOLATILITY SPILLOVER (FIXED)
# ============================================================
print("\n" + "=" * 70)
print("PART B: Cross-Asset Volatility Spillover (FIXED METHODOLOGY)")
print("=" * 70)

# B1: Full-sample correlations (unchanged — these are fine)
corr_pairs = [
    ('VIX', 'BTC_RV22', 'VIX vs BTC RV'),
    ('VIX', 'SPY_RV22', 'VIX vs SPY RV'),
    ('BTC_RV22', 'SPY_RV22', 'BTC RV vs SPY RV'),
]

print("\n--- Full-sample Correlations ---")
correlation_results = {}
for x, y, label in corr_pairs:
    r_val, p_val = stats.pearsonr(returns[x], returns[y])
    sr, sp = stats.spearmanr(returns[x], returns[y])
    correlation_results[label] = {
        'pearson_r': float(r_val),
        'pearson_p': float(p_val),
        'spearman_r': float(sr),
        'spearman_p': float(sp)
    }
    print(f"  {label}: Pearson r={r_val:.3f} (p={p_val:.2e}), Spearman rho={sr:.3f} (p={sp:.2e})")

# B2: FIXED Granger Causality Tests
# FIX #1: Use FORWARD-LOOKING target
#   - Test: lagged VIX → NEXT-DAY |r_{BTC,t+1}| (non-overlapping)
#   - Also: lagged BTC |r_t| → NEXT-DAY VIX change
#   - Lag selection via AIC (not min-p)
print("\n--- FIXED Granger Causality Tests ---")
print("  Target: next-day BTC |return| (forward-looking, non-overlapping)")
print("  Lag selection: AIC-optimal (not min-p cherry-picking)")

granger_results = {}

# Prepare forward-looking targets
# BTC_absret_next = |r_{BTC,t+1}| — this is what we want to predict
# VIX_t = today's VIX level
# BTC_absret_t = |r_{BTC,t}| = today's BTC absolute return
gc_df = pd.DataFrame({
    'BTC_absret': returns['BTC_absret'],
    'VIX': returns['VIX'],
    'dVIX': returns['VIX'].diff(),
}).dropna()

# The forward-looking target: next-day absolute return
# In Granger framework: we test whether column 2 Granger-causes column 1
# statsmodels expects [y, x] format — y is the "caused" variable
# For "VIX → future BTC vol": y = BTC_absret, x = VIX
# statsmodels internally handles the lagging, so we use LEVELS not shifted

# Test 1: VIX → BTC |return| (does VIX predict next-day BTC volatility?)
print("\n  Test 1: H0: VIX does NOT Granger-cause BTC |return|")
try:
    gc1 = grangercausalitytests(gc_df[['BTC_absret', 'VIX']], maxlag=10, verbose=False)
    gc1_results = {}
    aic_values = {}
    for lag in range(1, 11):
        f_stat = gc1[lag][0]['ssr_ftest'][0]
        p_val = gc1[lag][0]['ssr_ftest'][1]
        # Get AIC from the restricted and unrestricted models
        ols_restricted = gc1[lag][1][0]  # restricted model (without x lags)
        ols_unrestricted = gc1[lag][1][1]  # unrestricted model (with x lags)
        aic_unr = float(ols_unrestricted.aic)
        aic_values[lag] = aic_unr
        gc1_results[lag] = {'F': float(f_stat), 'p': float(p_val), 'AIC': aic_unr}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f}, AIC={aic_unr:.1f} {sig}")

    # AIC-optimal lag
    best_lag_1 = min(aic_values, key=aic_values.get)
    best_p_1 = gc1_results[best_lag_1]['p']
    print(f"    AIC-optimal lag: {best_lag_1} (p={best_p_1:.4f})")
    gc1_results['aic_best_lag'] = best_lag_1
    gc1_results['aic_best_p'] = best_p_1
    granger_results['VIX_to_BTC_absret'] = gc1_results
except Exception as e:
    print(f"    Error: {e}")
    granger_results['VIX_to_BTC_absret'] = {'error': str(e)}

# Test 2: BTC |return| → VIX change (does BTC vol predict next-day VIX?)
print("\n  Test 2: H0: BTC |return| does NOT Granger-cause VIX change")
gc_df2 = pd.DataFrame({
    'dVIX': returns['VIX'].diff(),
    'BTC_absret': returns['BTC_absret'],
}).dropna()

try:
    gc2 = grangercausalitytests(gc_df2[['dVIX', 'BTC_absret']], maxlag=10, verbose=False)
    gc2_results = {}
    aic_values2 = {}
    for lag in range(1, 11):
        f_stat = gc2[lag][0]['ssr_ftest'][0]
        p_val = gc2[lag][0]['ssr_ftest'][1]
        ols_unrestricted = gc2[lag][1][1]
        aic_unr = float(ols_unrestricted.aic)
        aic_values2[lag] = aic_unr
        gc2_results[lag] = {'F': float(f_stat), 'p': float(p_val), 'AIC': aic_unr}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f}, AIC={aic_unr:.1f} {sig}")

    best_lag_2 = min(aic_values2, key=aic_values2.get)
    best_p_2 = gc2_results[best_lag_2]['p']
    print(f"    AIC-optimal lag: {best_lag_2} (p={best_p_2:.4f})")
    gc2_results['aic_best_lag'] = best_lag_2
    gc2_results['aic_best_p'] = best_p_2
    granger_results['BTC_absret_to_dVIX'] = gc2_results
except Exception as e:
    print(f"    Error: {e}")
    granger_results['BTC_absret_to_dVIX'] = {'error': str(e)}

# Test 3: VIX → SPY |return| (benchmark: VIX should predict SPY vol)
print("\n  Test 3 (benchmark): H0: VIX does NOT Granger-cause SPY |return|")
gc_df3 = pd.DataFrame({
    'SPY_absret': returns['SPY_absret'],
    'VIX': returns['VIX'],
}).dropna()

try:
    gc3 = grangercausalitytests(gc_df3[['SPY_absret', 'VIX']], maxlag=10, verbose=False)
    gc3_results = {}
    aic_values3 = {}
    for lag in range(1, 11):
        f_stat = gc3[lag][0]['ssr_ftest'][0]
        p_val = gc3[lag][0]['ssr_ftest'][1]
        ols_unrestricted = gc3[lag][1][1]
        aic_unr = float(ols_unrestricted.aic)
        aic_values3[lag] = aic_unr
        gc3_results[lag] = {'F': float(f_stat), 'p': float(p_val), 'AIC': aic_unr}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f}, AIC={aic_unr:.1f} {sig}")

    best_lag_3 = min(aic_values3, key=aic_values3.get)
    best_p_3 = gc3_results[best_lag_3]['p']
    print(f"    AIC-optimal lag: {best_lag_3} (p={best_p_3:.4f})")
    gc3_results['aic_best_lag'] = best_lag_3
    gc3_results['aic_best_p'] = best_p_3
    granger_results['VIX_to_SPY_absret_benchmark'] = gc3_results
except Exception as e:
    print(f"    Error: {e}")
    granger_results['VIX_to_SPY_absret_benchmark'] = {'error': str(e)}

# B3: Rolling correlation (VIX vs BTC_RV22, 252-day window) — unchanged
print("\n--- Rolling Correlation: VIX vs BTC RV (252-day) ---")
rolling_corr = returns['VIX'].rolling(252).corr(returns['BTC_RV22'])
rolling_corr_clean = rolling_corr.dropna()

periods = {
    'Pre-2018 (early crypto)': ('2016-01-01', '2017-12-31'),
    '2018 (crypto winter 1)': ('2018-01-01', '2018-12-31'),
    '2019 (recovery)': ('2019-01-01', '2019-12-31'),
    '2020 (COVID)': ('2020-01-01', '2020-12-31'),
    '2021 (bull run)': ('2021-01-01', '2021-12-31'),
    '2022 (crypto winter 2)': ('2022-01-01', '2022-12-31'),
    '2023 (recovery 2)': ('2023-01-01', '2023-12-31'),
    '2024-2026 (maturation)': ('2024-01-01', '2026-12-31'),
}

rolling_corr_by_period = {}
for label, (start, end) in periods.items():
    mask = (rolling_corr_clean.index >= start) & (rolling_corr_clean.index <= end)
    subset = rolling_corr_clean[mask]
    if len(subset) > 0:
        mean_corr = float(subset.mean())
        rolling_corr_by_period[label] = mean_corr
        print(f"  {label}: mean rolling corr = {mean_corr:.3f} (n={len(subset)})")

# Trend test
if len(rolling_corr_clean) > 100:
    x_numeric = np.arange(len(rolling_corr_clean))
    slope, intercept, r_val, p_val, se = stats.linregress(x_numeric, rolling_corr_clean.values)
    print(f"\n  Linear trend in rolling corr: slope={slope:.6f}/day, t={slope/se:.2f}, p={p_val:.4f}")
    print(f"  Interpretation: {'Correlation is INCREASING' if slope > 0 and p_val < 0.05 else 'No significant trend'}")
    trend_result = {
        'slope_per_day': float(slope),
        'slope_per_year': float(slope * 252),
        't_stat': float(slope / se),
        'p_value': float(p_val),
        'increasing': bool(slope > 0 and p_val < 0.05)
    }
else:
    trend_result = {'error': 'Insufficient data'}

# ============================================================
# PART C: REGIME ANALYSIS (unchanged from K746)
# ============================================================
print("\n" + "=" * 70)
print("PART C: Regime Analysis — VIX Spikes and BTC Behavior")
print("=" * 70)

returns['VIX_regime'] = pd.cut(returns['VIX'], bins=[0, 15, 20, 25, 35, 100],
                                labels=['Low(<15)', 'Normal(15-20)', 'Elevated(20-25)',
                                        'High(25-35)', 'Extreme(>35)'])

print("\n--- BTC Returns by VIX Regime ---")
regime_stats = {}
for regime in returns['VIX_regime'].cat.categories:
    mask = returns['VIX_regime'] == regime
    btc_r = returns.loc[mask, 'BTC']
    spy_r = returns.loc[mask, 'SPY']
    n = int(mask.sum())
    if n > 10:
        regime_stats[regime] = {
            'n_days': n,
            'btc_mean_daily_bps': float(btc_r.mean() * 10000),
            'btc_vol_ann_pct': float(btc_r.std() * np.sqrt(252) * 100),
            'spy_mean_daily_bps': float(spy_r.mean() * 10000),
            'btc_spy_corr': float(btc_r.corr(spy_r)),
        }
        print(f"  {regime}: n={n}, BTC mean={btc_r.mean()*10000:.1f}bps/day, "
              f"BTC vol={btc_r.std()*np.sqrt(252)*100:.1f}%, "
              f"BTC-SPY corr={btc_r.corr(spy_r):.3f}")

# Key events
print("\n--- Key Events: Coupled vs Decoupled ---")
events = {
    'COVID crash (2020-02-20 to 2020-03-23)': ('2020-02-20', '2020-03-23'),
    'Post-COVID rally (2020-04 to 2020-08)': ('2020-04-01', '2020-08-31'),
    'BTC bull peak (2021-10 to 2021-11)': ('2021-10-01', '2021-11-30'),
    'Crypto winter (2022-05 to 2022-07)': ('2022-05-01', '2022-07-31'),
    'FTX collapse (2022-11-01 to 2022-11-30)': ('2022-11-01', '2022-11-30'),
    'SVB crisis (2023-03-08 to 2023-03-15)': ('2023-03-08', '2023-03-15'),
    'BTC ETF approval rally (2024-01)': ('2024-01-01', '2024-01-31'),
}

event_results = {}
for label, (start, end) in events.items():
    mask = (returns.index >= start) & (returns.index <= end)
    sub = returns[mask]
    if len(sub) > 3:
        btc_cum = float((1 + sub['BTC']).prod() - 1) * 100
        spy_cum = float((1 + sub['SPY']).prod() - 1) * 100
        vix_mean = float(sub['VIX'].mean())
        btc_spy_corr = float(sub['BTC'].corr(sub['SPY']))

        coupled = "COUPLED" if btc_spy_corr > 0.3 else "DECOUPLED" if btc_spy_corr < -0.1 else "MIXED"
        event_results[label] = {
            'btc_return_pct': btc_cum,
            'spy_return_pct': spy_cum,
            'vix_mean': vix_mean,
            'btc_spy_corr': btc_spy_corr,
            'classification': coupled,
            'n_days': len(sub)
        }
        print(f"  {label}")
        print(f"    BTC: {btc_cum:+.1f}%, SPY: {spy_cum:+.1f}%, VIX avg: {vix_mean:.1f}, "
              f"BTC-SPY corr: {btc_spy_corr:.2f} -> {coupled}")

# ============================================================
# PART D: PORTFOLIO IMPLICATIONS (unchanged from K746)
# ============================================================
print("\n" + "=" * 70)
print("PART D: Portfolio Implications")
print("=" * 70)

common_start = '2015-02-01'
r = returns.loc[common_start:].copy()
print(f"Portfolio analysis period: {r.index[0].date()} to {r.index[-1].date()} ({len(r)} days)")

# D1: Static allocations
print("\n--- D1: Static BTC Allocations ---")
static_results = {}
for btc_pct in [0, 2, 5, 10, 15, 20]:
    spy_pct = (100 - btc_pct) / 2
    gld_pct = (100 - btc_pct) / 2
    port_r = (r['SPY'] * spy_pct/100 + r['GLD'] * gld_pct/100 + r['BTC'] * btc_pct/100)

    cum = (1 + port_r).cumprod()
    ann_ret = float((cum.iloc[-1]) ** (252 / len(cum)) - 1) * 100
    ann_vol = float(port_r.std() * np.sqrt(252)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    mdd = float((cum / cum.cummax() - 1).min()) * 100

    static_results[f'BTC_{btc_pct}pct'] = {
        'weights': f'SPY {spy_pct:.0f}% / GLD {gld_pct:.0f}% / BTC {btc_pct:.0f}%',
        'ann_return_pct': ann_ret,
        'ann_vol_pct': ann_vol,
        'sharpe': sharpe,
        'max_dd_pct': mdd,
    }
    print(f"  SPY {spy_pct:.0f}%/GLD {gld_pct:.0f}%/BTC {btc_pct:.0f}%: "
          f"Ret={ann_ret:.1f}%, Vol={ann_vol:.1f}%, Sharpe={sharpe:.3f}, MDD={mdd:.1f}%")

# D2: VIX-conditioned BTC allocation
print("\n--- D2: VIX-Conditioned BTC Allocation ---")
# signal.shift(1) — use YESTERDAY's VIX to decide TODAY's allocation
vix_signal = r['VIX'].shift(1)  # LAG = mandatory

vix_cond_results = {}
for btc_base in [5, 10]:
    spy_base = (100 - btc_base) / 2
    gld_base = (100 - btc_base) / 2

    high_vix = vix_signal > 25
    w_btc = pd.Series(btc_base / 100, index=r.index)
    w_btc[high_vix] = 0
    w_spy = (1 - w_btc) / 2
    w_gld = (1 - w_btc) / 2

    btc_turnover = w_btc.diff().abs()
    tx_cost = btc_turnover * 0.0020  # 20bps

    port_r_cond = r['SPY'] * w_spy + r['GLD'] * w_gld + r['BTC'] * w_btc - tx_cost
    port_r_cond = port_r_cond.dropna()

    cum = (1 + port_r_cond).cumprod()
    ann_ret = float((cum.iloc[-1]) ** (252 / len(cum)) - 1) * 100
    ann_vol = float(port_r_cond.std() * np.sqrt(252)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    mdd = float((cum / cum.cummax() - 1).min()) * 100

    n_reduce = int(high_vix.sum())
    total_tx = float(tx_cost.sum()) * 100

    vix_cond_results[f'BTC_{btc_base}pct_VIXcond'] = {
        'base_btc_pct': btc_base,
        'ann_return_pct': ann_ret,
        'ann_vol_pct': ann_vol,
        'sharpe': sharpe,
        'max_dd_pct': mdd,
        'n_days_btc_reduced': n_reduce,
        'total_tx_cost_pct': total_tx,
        'lag': 'signal.shift(1) — VIX from t-1 applied at t',
    }
    print(f"  BTC {btc_base}% (VIX>25->0%): Ret={ann_ret:.1f}%, Vol={ann_vol:.1f}%, "
          f"Sharpe={sharpe:.3f}, MDD={mdd:.1f}%, "
          f"BTC removed {n_reduce} days, TX={total_tx:.2f}%")

# D3: Baseline 50/50
port_5050 = r['SPY'] * 0.5 + r['GLD'] * 0.5
cum_5050 = (1 + port_5050).cumprod()
ann_ret_5050 = float((cum_5050.iloc[-1]) ** (252 / len(cum_5050)) - 1) * 100
ann_vol_5050 = float(port_5050.std() * np.sqrt(252)) * 100
sharpe_5050 = ann_ret_5050 / ann_vol_5050 if ann_vol_5050 > 0 else 0
mdd_5050 = float((cum_5050 / cum_5050.cummax() - 1).min()) * 100

print(f"\n  Baseline 50/50 SPY/GLD: Ret={ann_ret_5050:.1f}%, Vol={ann_vol_5050:.1f}%, "
      f"Sharpe={sharpe_5050:.3f}, MDD={mdd_5050:.1f}%")

baseline_5050 = {
    'ann_return_pct': ann_ret_5050,
    'ann_vol_pct': ann_vol_5050,
    'sharpe': sharpe_5050,
    'max_dd_pct': mdd_5050,
}

# ============================================================
# PART E: Tail Dependence (unchanged from K746)
# ============================================================
print("\n" + "=" * 70)
print("PART E: Tail Dependence Analysis")
print("=" * 70)

spy_crash = r['SPY'] < -0.02
btc_on_spy_crash = r.loc[spy_crash, 'BTC']
btc_on_normal = r.loc[~spy_crash, 'BTC']

print(f"\n--- BTC behavior on SPY crash days (SPY < -2%) ---")
print(f"  N crash days: {spy_crash.sum()}")
print(f"  BTC mean on crash days: {btc_on_spy_crash.mean()*100:.2f}%")
print(f"  BTC mean on normal days: {btc_on_normal.mean()*100:.2f}%")
print(f"  BTC also negative: {(btc_on_spy_crash < 0).mean()*100:.1f}% of crash days")

t_stat, t_pval = stats.ttest_ind(btc_on_spy_crash, btc_on_normal)
print(f"  T-test (crash vs normal): t={t_stat:.3f}, p={t_pval:.4f}")

tail_dep = {
    'n_spy_crash_days': int(spy_crash.sum()),
    'btc_mean_crash_days_pct': float(btc_on_spy_crash.mean() * 100),
    'btc_mean_normal_days_pct': float(btc_on_normal.mean() * 100),
    'btc_also_negative_pct': float((btc_on_spy_crash < 0).mean() * 100),
    't_stat': float(t_stat),
    'p_value': float(t_pval),
}

# VIX on BTC crash days
btc_crash = r['BTC'] < -0.05
vix_on_btc_crash = r.loc[btc_crash, 'VIX']
vix_on_normal = r.loc[~btc_crash, 'VIX']

print(f"\n--- VIX behavior on BTC crash days (BTC < -5%) ---")
print(f"  N BTC crash days: {btc_crash.sum()}")
print(f"  VIX mean on BTC crash days: {vix_on_btc_crash.mean():.1f}")
print(f"  VIX mean on normal days: {vix_on_normal.mean():.1f}")
t2, p2 = stats.ttest_ind(vix_on_btc_crash, vix_on_normal)
print(f"  T-test: t={t2:.3f}, p={p2:.4f}")

vix_on_btc_crash_result = {
    'n_btc_crash_days': int(btc_crash.sum()),
    'vix_mean_btc_crash': float(vix_on_btc_crash.mean()),
    'vix_mean_normal': float(vix_on_normal.mean()),
    't_stat': float(t2),
    'p_value': float(p2),
}

# ============================================================
# PART F: FIXED Structural Break Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART F: Structural Break — FIXED (VIX-BTC_RV correlation + Andrews test)")
print("=" * 70)

# FIX #2a: Fisher z-test on VIX-BTC_RV correlation (not BTC-SPY return corr)
split_date = '2021-01-01'
pre = r.loc[:split_date]
post = r.loc[split_date:]

structural_break = {}
for period_name, period_data in [('Pre-2021', pre), ('2021+', post)]:
    if len(period_data) < 50:
        continue
    btc_spy_corr = float(period_data['BTC'].corr(period_data['SPY']))
    btc_vol = float(period_data['BTC'].std() * np.sqrt(252) * 100)
    vix_btcrv_corr = float(period_data['VIX'].corr(period_data['BTC_RV22']))

    structural_break[period_name] = {
        'n_days': len(period_data),
        'btc_spy_daily_corr': btc_spy_corr,
        'btc_ann_vol_pct': btc_vol,
        'vix_btcrv_corr': vix_btcrv_corr,
    }
    print(f"  {period_name} (n={len(period_data)}): "
          f"BTC-SPY corr={btc_spy_corr:.3f}, BTC vol={btc_vol:.1f}%, "
          f"VIX-BTC_RV corr={vix_btcrv_corr:.3f}")

# FIX #2a: Fisher z-test on VIX-BTC_RV correlation (the CORRECT variable)
print("\n--- FIXED Fisher z-test: VIX-BTC_RV correlation change ---")
r1_corr = structural_break['Pre-2021']['vix_btcrv_corr']
r2_corr = structural_break['2021+']['vix_btcrv_corr']
n1 = structural_break['Pre-2021']['n_days']
n2 = structural_break['2021+']['n_days']

z1 = np.arctanh(r1_corr)
z2 = np.arctanh(r2_corr)
z_diff = (z1 - z2) / np.sqrt(1/(n1-3) + 1/(n2-3))
p_diff = 2 * (1 - stats.norm.cdf(abs(z_diff)))

print(f"  Pre-2021 VIX-BTC_RV corr: {r1_corr:.3f} (n={n1})")
print(f"  2021+    VIX-BTC_RV corr: {r2_corr:.3f} (n={n2})")
print(f"  Fisher z-test: z={z_diff:.3f}, p={p_diff:.4f}")
print(f"  {'Significant structural break in VIX-BTC_RV coupling!' if p_diff < 0.05 else 'No significant structural break.'}")

structural_break['fisher_z_test_vix_btcrv'] = {
    'variable': 'VIX vs BTC_RV22 correlation',
    'pre_2021_corr': float(r1_corr),
    'post_2021_corr': float(r2_corr),
    'z_stat': float(z_diff),
    'p_value': float(p_diff),
    'significant': bool(p_diff < 0.05),
    'note': 'FIXED: now tests VIX-BTC_RV corr (not BTC-SPY return corr as in K746)'
}

# Also provide BTC-SPY return corr Fisher z for reference
print("\n--- Reference: Fisher z-test on BTC-SPY return correlation ---")
r1_spy = structural_break['Pre-2021']['btc_spy_daily_corr']
r2_spy = structural_break['2021+']['btc_spy_daily_corr']
z1s = np.arctanh(r1_spy)
z2s = np.arctanh(r2_spy)
z_diff_spy = (z1s - z2s) / np.sqrt(1/(n1-3) + 1/(n2-3))
p_diff_spy = 2 * (1 - stats.norm.cdf(abs(z_diff_spy)))
print(f"  Pre-2021 BTC-SPY corr: {r1_spy:.3f}")
print(f"  2021+    BTC-SPY corr: {r2_spy:.3f}")
print(f"  Fisher z: z={z_diff_spy:.3f}, p={p_diff_spy:.4f}")

structural_break['fisher_z_test_btc_spy_ref'] = {
    'variable': 'BTC vs SPY daily return correlation (reference only)',
    'pre_2021_corr': float(r1_spy),
    'post_2021_corr': float(r2_spy),
    'z_stat': float(z_diff_spy),
    'p_value': float(p_diff_spy),
    'significant': bool(p_diff_spy < 0.05),
}

# FIX #2b: Andrews (1993) sup-Wald unknown-breakpoint test
# Test whether VIX-BTC_RV relationship has a structural break at unknown date
print("\n--- Andrews (1993) sup-Wald Test for Unknown Breakpoint ---")
print("  Testing: VIX-BTC_RV regression coefficient stability")

# Simple regression: BTC_RV22 = a + b*VIX + e
# Test for breakpoint in b across all candidate dates
y_full = r['BTC_RV22'].values
x_full = add_constant(r['VIX'].values)
n_full = len(y_full)

# Andrews recommends trimming 15% from each end
trim_pct = 0.15
start_idx = int(n_full * trim_pct)
end_idx = int(n_full * (1 - trim_pct))

# Full-sample OLS for restricted SSR
ols_full = OLS(y_full, x_full).fit()
ssr_full = ols_full.ssr
k = x_full.shape[1]  # number of regressors

# Compute Wald F-stat at each candidate breakpoint
wald_stats = []
candidate_dates = []

for t in range(start_idx, end_idx):
    # Sub-sample 1
    y1, x1 = y_full[:t], x_full[:t]
    # Sub-sample 2
    y2, x2 = y_full[t:], x_full[t:]

    if len(y1) < k + 2 or len(y2) < k + 2:
        continue

    ols1 = OLS(y1, x1).fit()
    ols2 = OLS(y2, x2).fit()

    ssr_unrestricted = ols1.ssr + ols2.ssr

    # Chow F-stat
    f_stat = ((ssr_full - ssr_unrestricted) / k) / (ssr_unrestricted / (n_full - 2*k))
    wald_stats.append(f_stat)
    candidate_dates.append(r.index[t])

if len(wald_stats) > 0:
    sup_wald = max(wald_stats)
    sup_idx = np.argmax(wald_stats)
    sup_date = candidate_dates[sup_idx]

    # Bootstrap p-value for sup-Wald (Hansen 1997 approximation)
    # For k=2 regressors and 15% trimming, critical values approx:
    # 10%: ~7.1, 5%: ~8.7, 1%: ~12.2 (from Andrews 1993 Table 1)
    andrews_cv_10 = 7.1
    andrews_cv_5 = 8.7
    andrews_cv_1 = 12.2

    print(f"  sup-Wald statistic: {sup_wald:.2f}")
    print(f"  Estimated break date: {sup_date.date()}")
    print(f"  Andrews (1993) critical values: 10%={andrews_cv_10}, 5%={andrews_cv_5}, 1%={andrews_cv_1}")

    if sup_wald > andrews_cv_1:
        sig_level = "p < 0.01 ***"
    elif sup_wald > andrews_cv_5:
        sig_level = "p < 0.05 **"
    elif sup_wald > andrews_cv_10:
        sig_level = "p < 0.10 *"
    else:
        sig_level = "p > 0.10 (not significant)"
    print(f"  Significance: {sig_level}")

    # Report sub-sample correlations at estimated break
    pre_break = r.loc[:sup_date]
    post_break = r.loc[sup_date:]
    pre_vix_btcrv = float(pre_break['VIX'].corr(pre_break['BTC_RV22']))
    post_vix_btcrv = float(post_break['VIX'].corr(post_break['BTC_RV22']))
    print(f"  VIX-BTC_RV corr pre-break: {pre_vix_btcrv:.3f} (n={len(pre_break)})")
    print(f"  VIX-BTC_RV corr post-break: {post_vix_btcrv:.3f} (n={len(post_break)})")

    structural_break['andrews_sup_wald'] = {
        'sup_wald_stat': float(sup_wald),
        'estimated_break_date': str(sup_date.date()),
        'trim_pct': trim_pct,
        'cv_10pct': andrews_cv_10,
        'cv_5pct': andrews_cv_5,
        'cv_1pct': andrews_cv_1,
        'significance': sig_level,
        'pre_break_vix_btcrv_corr': pre_vix_btcrv,
        'post_break_vix_btcrv_corr': post_vix_btcrv,
        'pre_break_n': len(pre_break),
        'post_break_n': len(post_break),
        'note': 'Andrews (1993) unknown-breakpoint test on VIX-BTC_RV regression'
    }
else:
    structural_break['andrews_sup_wald'] = {'error': 'Could not compute sup-Wald'}

# ============================================================
# COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY OF KEY FINDINGS (K746b — FIXED METHODOLOGY)")
print("=" * 70)

# Determine key findings with FIXED Granger
gc_vix_to_btc_sig = False
gc_btc_to_vix_sig = False
gc_vix_to_btc_aic_p = None
gc_btc_to_vix_aic_p = None

if 'error' not in granger_results.get('VIX_to_BTC_absret', {}):
    gc_vix_to_btc_aic_p = granger_results['VIX_to_BTC_absret'].get('aic_best_p')
    gc_vix_to_btc_sig = gc_vix_to_btc_aic_p is not None and gc_vix_to_btc_aic_p < 0.05

if 'error' not in granger_results.get('BTC_absret_to_dVIX', {}):
    gc_btc_to_vix_aic_p = granger_results['BTC_absret_to_dVIX'].get('aic_best_p')
    gc_btc_to_vix_sig = gc_btc_to_vix_aic_p is not None and gc_btc_to_vix_aic_p < 0.05

# Benchmark: VIX → SPY vol
gc_vix_to_spy_sig = False
gc_vix_to_spy_aic_p = None
if 'error' not in granger_results.get('VIX_to_SPY_absret_benchmark', {}):
    gc_vix_to_spy_aic_p = granger_results['VIX_to_SPY_absret_benchmark'].get('aic_best_p')
    gc_vix_to_spy_sig = gc_vix_to_spy_aic_p is not None and gc_vix_to_spy_aic_p < 0.05

best_alloc = max(static_results.items(), key=lambda x: x[1]['sharpe'])

# Andrews break significance
andrews_sig = structural_break.get('andrews_sup_wald', {}).get('significance', 'N/A')
andrews_date = structural_break.get('andrews_sup_wald', {}).get('estimated_break_date', 'N/A')

summary = {
    'methodology_fixes': {
        'fix1': 'Granger target changed from backward 22d RV to forward |r_{t+1}| (non-overlapping)',
        'fix2': 'Fisher z-test now on VIX-BTC_RV corr (not BTC-SPY return corr)',
        'fix3': 'Added Andrews (1993) sup-Wald unknown-breakpoint test',
        'fix4': 'Lag selection via AIC (not min-p cherry-picking)',
        'fix5': 'Added VIX→SPY benchmark Granger test for comparison',
    },
    'Q1_VIX_predicts_BTC_vol': gc_vix_to_btc_sig,
    'Q1_VIX_to_BTC_aic_p': gc_vix_to_btc_aic_p,
    'Q2_BTC_vol_predicts_VIX': gc_btc_to_vix_sig,
    'Q2_BTC_to_VIX_aic_p': gc_btc_to_vix_aic_p,
    'benchmark_VIX_predicts_SPY_vol': gc_vix_to_spy_sig,
    'benchmark_VIX_to_SPY_aic_p': gc_vix_to_spy_aic_p,
    'Q3_correlation_increasing': trend_result.get('increasing', False),
    'Q3_trend_slope_per_year': trend_result.get('slope_per_year', None),
    'Q4_best_static_BTC_allocation': best_alloc[0],
    'Q4_best_static_sharpe': best_alloc[1]['sharpe'],
    'full_sample_VIX_BTC_RV_corr': correlation_results['VIX vs BTC RV']['pearson_r'],
    'btc_also_crashes_on_spy_crash_pct': tail_dep['btc_also_negative_pct'],
    'structural_break_fisher_z_significant': structural_break['fisher_z_test_vix_btcrv']['significant'],
    'structural_break_andrews_significance': andrews_sig,
    'structural_break_andrews_date': andrews_date,
    'key_question': 'Does asymmetric Granger causality (BTC vol -> VIX) survive with forward-looking target?',
    'answer': f"VIX→BTC: {'YES' if gc_vix_to_btc_sig else 'NO'} (p={gc_vix_to_btc_aic_p}), "
              f"BTC→VIX: {'YES' if gc_btc_to_vix_sig else 'NO'} (p={gc_btc_to_vix_aic_p})",
}

print(f"\n  Q1 (VIX -> BTC vol, FIXED): {'YES' if gc_vix_to_btc_sig else 'NO'} "
      f"(AIC-opt p={gc_vix_to_btc_aic_p})")
print(f"  Q2 (BTC vol -> VIX, FIXED): {'YES' if gc_btc_to_vix_sig else 'NO'} "
      f"(AIC-opt p={gc_btc_to_vix_aic_p})")
print(f"  Benchmark (VIX -> SPY vol): {'YES' if gc_vix_to_spy_sig else 'NO'} "
      f"(AIC-opt p={gc_vix_to_spy_aic_p})")
print(f"  Q3 (Correlation increasing?): {'YES' if trend_result.get('increasing') else 'NO'}")
print(f"  Q4 (Best static BTC allocation): {best_alloc[0]} with Sharpe {best_alloc[1]['sharpe']:.3f}")
print(f"  Structural break (Fisher z on VIX-BTC_RV): "
      f"{'YES' if structural_break['fisher_z_test_vix_btcrv']['significant'] else 'NO'}")
print(f"  Structural break (Andrews sup-Wald): {andrews_sig}")
print(f"  Andrews estimated break date: {andrews_date}")

# Comparison with K746
print("\n--- Comparison with K746 (original, unfixed) ---")
print("  K746 Granger: backward 22d RV (overlapping) — INVALID")
print("  K746b Granger: next-day |return| (forward, non-overlapping) — CORRECT")
print("  K746 Fisher z: BTC-SPY return corr — WRONG VARIABLE")
print("  K746b Fisher z: VIX-BTC_RV corr — CORRECT VARIABLE")
print("  K746b adds: Andrews (1993) unknown-breakpoint test")
print("  K746b adds: VIX->SPY benchmark Granger test")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K746b',
    'title': 'Bitcoin Volatility and VIX — Crypto Fear Channel (Fixed Methodology)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (BTC-USD, SPY, GLD, ^VIX)',
    'data_period': f"{r.index[0].date()} to {r.index[-1].date()}",
    'n_obs': len(r),
    'flag': 'FIXED — corrects K746 Granger + structural break methodology',
    'proposer': 'Codex (K746 review)',
    'executor': 'Claude',
    'fixes_applied': {
        'fix1_granger_target': 'Changed from backward 22d RV to forward |r_{t+1}| (non-overlapping)',
        'fix2_fisher_z_variable': 'Changed from BTC-SPY return corr to VIX-BTC_RV corr',
        'fix3_andrews_test': 'Added Andrews (1993) sup-Wald unknown-breakpoint test (vs hardcoded 2021)',
        'fix4_lag_selection': 'AIC-optimal lag selection (not min-p cherry-picking)',
        'fix5_benchmark': 'Added VIX->SPY vol benchmark Granger test',
    },
    'part_a_descriptive': desc_stats,
    'part_b_correlations': correlation_results,
    'part_b_granger_fixed': granger_results,
    'part_b_rolling_corr_by_period': rolling_corr_by_period,
    'part_b_trend': trend_result,
    'part_c_regime_stats': {str(k): v for k, v in regime_stats.items()},
    'part_c_events': event_results,
    'part_d_static_allocations': static_results,
    'part_d_vix_conditioned': vix_cond_results,
    'part_d_baseline_5050': baseline_5050,
    'part_e_tail_dependence': tail_dep,
    'part_e_vix_on_btc_crash': vix_on_btc_crash_result,
    'part_f_structural_break_fixed': structural_break,
    'summary': summary,
    'references': [
        'K746: Original experiment (methodology issues identified by Codex)',
        'K66: 5% BTC improves portfolio Sharpe (prior VolPred result)',
        'K445: BTC inverse leverage effect (prior VolPred result)',
        'Andrews (1993) "Tests for Parameter Instability and Structural Change" Econometrica',
        'Hansen (1997) "Approximate Asymptotic P Values for Structural-Change Tests" JBES',
        'Baur & Dimpfl (2018) Economics Letters — BTC volatility',
        'Bouri et al. (2017) Finance Research Letters — BTC as hedge/safe haven',
        'Conlon & McGee (2020) Finance Research Letters — BTC during COVID',
    ],
}

with open('experiments/k746b_bitcoin_vix_fixed_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to experiments/k746b_bitcoin_vix_fixed_results.json")
print("Script saved as experiments/k746b_bitcoin_vix_fixed.py")
print("\nDone.")
