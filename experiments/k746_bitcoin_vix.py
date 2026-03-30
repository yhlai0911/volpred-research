"""
K746: Bitcoin Volatility and VIX — Is There a Crypto Fear Channel?

Research Questions:
1. Does VIX predict Bitcoin realized volatility? (TradFi → Crypto spillover)
2. Does BTC realized volatility predict VIX? (Crypto → TradFi reverse spillover)
3. Has the VIX-BTC vol relationship strengthened over time? (institutional adoption)
4. Can VIX-conditioned BTC allocation improve portfolio performance?

Prior work:
- K66: 5% BTC improves portfolio Sharpe (p=0.014) but tail risk (coskewness -0.50)
- K445: BTC has NO clear leverage effect (GJR gamma p=0.12); EGARCH best in-sample, GARCH-SkewT best OOS
- K205: BTC weekend vol is distinct microstructure feature
- K132: BTC vol 80%+ uncaptured by standard GARCH QLIKE decomposition

Data: BTC-USD, SPY, GLD, ^VIX from yfinance (2015-01 to 2026-03)
Method: Granger causality, rolling correlations, regime analysis, portfolio construction
[提出: Claude, 執行: Claude]
FLAG: EXPLORATORY — crypto data quality varies
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K746: Bitcoin Volatility and VIX — Crypto Fear Channel")
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
# PART A: DESCRIPTIVE STATISTICS
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

# Realized volatility (22-day rolling)
for asset in ['BTC', 'SPY', 'GLD']:
    returns[f'{asset}_RV22'] = returns[asset].rolling(22).std() * np.sqrt(252) * 100

# VIX level (aligned to returns index)
returns['VIX'] = df_all['VIX'].reindex(returns.index)
returns = returns.dropna()

print(f"\nFinal dataset with RV: {len(returns)} obs")

# Compare BTC RV to VIX
print(f"\nBTC RV22 mean: {returns['BTC_RV22'].mean():.1f}%  median: {returns['BTC_RV22'].median():.1f}%")
print(f"SPY RV22 mean: {returns['SPY_RV22'].mean():.1f}%  median: {returns['SPY_RV22'].median():.1f}%")
print(f"VIX    mean: {returns['VIX'].mean():.1f}   median: {returns['VIX'].median():.1f}")

# ============================================================
# PART B: CROSS-ASSET VOLATILITY SPILLOVER
# ============================================================
print("\n" + "=" * 70)
print("PART B: Cross-Asset Volatility Spillover")
print("=" * 70)

# B1: Full-sample correlations
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
    print(f"  {label}: Pearson r={r_val:.3f} (p={p_val:.2e}), Spearman ρ={sr:.3f} (p={sp:.2e})")

# B2: Granger Causality Tests
print("\n--- Granger Causality Tests (maxlag=10) ---")
granger_results = {}

# Prepare daily changes for Granger (stationarity)
dVIX = returns['VIX'].diff().dropna()
dBTC_RV = returns['BTC_RV22'].diff().dropna()

# Align
gc_df = pd.DataFrame({'dVIX': dVIX, 'dBTC_RV': dBTC_RV}).dropna()

# Test 1: VIX → BTC_RV (does VIX Granger-cause BTC vol?)
print("\n  H0: VIX does NOT Granger-cause BTC_RV")
try:
    gc1 = grangercausalitytests(gc_df[['dBTC_RV', 'dVIX']], maxlag=10, verbose=False)
    gc1_results = {}
    for lag in range(1, 11):
        f_stat = gc1[lag][0]['ssr_ftest'][0]
        p_val = gc1[lag][0]['ssr_ftest'][1]
        gc1_results[lag] = {'F': float(f_stat), 'p': float(p_val)}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {sig}")
    granger_results['VIX_to_BTC_RV'] = gc1_results
except Exception as e:
    print(f"    Error: {e}")
    granger_results['VIX_to_BTC_RV'] = {'error': str(e)}

# Test 2: BTC_RV → VIX (does BTC vol Granger-cause VIX?)
print("\n  H0: BTC_RV does NOT Granger-cause VIX")
try:
    gc2 = grangercausalitytests(gc_df[['dVIX', 'dBTC_RV']], maxlag=10, verbose=False)
    gc2_results = {}
    for lag in range(1, 11):
        f_stat = gc2[lag][0]['ssr_ftest'][0]
        p_val = gc2[lag][0]['ssr_ftest'][1]
        gc2_results[lag] = {'F': float(f_stat), 'p': float(p_val)}
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
        if lag <= 5:
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {sig}")
    granger_results['BTC_RV_to_VIX'] = gc2_results
except Exception as e:
    print(f"    Error: {e}")
    granger_results['BTC_RV_to_VIX'] = {'error': str(e)}

# B3: Rolling correlation (VIX vs BTC_RV22, 252-day window)
print("\n--- Rolling Correlation: VIX vs BTC RV (252-day) ---")
rolling_corr = returns['VIX'].rolling(252).corr(returns['BTC_RV22'])
rolling_corr_clean = rolling_corr.dropna()

# Split into periods
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

# Trend test: is correlation increasing?
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
# PART C: REGIME ANALYSIS — Coupled vs Decoupled
# ============================================================
print("\n" + "=" * 70)
print("PART C: Regime Analysis — VIX Spikes and BTC Behavior")
print("=" * 70)

# Define VIX regimes
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
              f"BTC-SPY corr: {btc_spy_corr:.2f} → {coupled}")

# ============================================================
# PART D: PORTFOLIO IMPLICATIONS
# ============================================================
print("\n" + "=" * 70)
print("PART D: Portfolio Implications")
print("=" * 70)

# Common start for comparison
common_start = '2015-02-01'  # after RV warmup
r = returns.loc[common_start:].copy()
print(f"Portfolio analysis period: {r.index[0].date()} to {r.index[-1].date()} ({len(r)} days)")

# D1: Static allocations
print("\n--- D1: Static BTC Allocations (no lag needed for static) ---")
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
# Rule: when VIX > 25, reduce BTC to 0 (shift signal by 1 day!)
print("\n--- D2: VIX-Conditioned BTC Allocation ---")
# signal.shift(1) — use YESTERDAY's VIX to decide TODAY's allocation
vix_signal = r['VIX'].shift(1)  # LAG = mandatory

vix_cond_results = {}
for btc_base in [5, 10]:
    # Static baseline
    spy_base = (100 - btc_base) / 2
    gld_base = (100 - btc_base) / 2

    # VIX-conditioned: when VIX > 25 yesterday, no BTC today
    high_vix = vix_signal > 25
    w_btc = pd.Series(btc_base / 100, index=r.index)
    w_btc[high_vix] = 0
    w_spy = (1 - w_btc) / 2
    w_gld = (1 - w_btc) / 2

    # Transaction costs: 20bps for BTC position changes
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
    print(f"  BTC {btc_base}% (VIX>25→0%): Ret={ann_ret:.1f}%, Vol={ann_vol:.1f}%, "
          f"Sharpe={sharpe:.3f}, MDD={mdd:.1f}%, "
          f"BTC removed {n_reduce} days, TX={total_tx:.2f}%")

# D3: Compare to pure 50/50 SPY/GLD baseline
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
# PART E: Tail Dependence & Conditional Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART E: Tail Dependence Analysis")
print("=" * 70)

# When SPY has extreme down days (< -2%), what happens to BTC?
spy_crash = r['SPY'] < -0.02
btc_on_spy_crash = r.loc[spy_crash, 'BTC']
btc_on_normal = r.loc[~spy_crash, 'BTC']

print(f"\n--- BTC behavior on SPY crash days (SPY < -2%) ---")
print(f"  N crash days: {spy_crash.sum()}")
print(f"  BTC mean on crash days: {btc_on_spy_crash.mean()*100:.2f}%")
print(f"  BTC mean on normal days: {btc_on_normal.mean()*100:.2f}%")
print(f"  BTC also negative: {(btc_on_spy_crash < 0).mean()*100:.1f}% of crash days")

# T-test
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

# When BTC crashes (< -5%), what happens to VIX?
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
# PART F: Sub-period Structural Break Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART F: Structural Break — Pre vs Post Institutional Adoption")
print("=" * 70)

# Split: pre-2021 (retail-dominated) vs 2021+ (institutional era)
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

# Fisher z-test for correlation difference
r1 = structural_break['Pre-2021']['btc_spy_daily_corr']
r2 = structural_break['2021+']['btc_spy_daily_corr']
n1 = structural_break['Pre-2021']['n_days']
n2 = structural_break['2021+']['n_days']

z1 = np.arctanh(r1)
z2 = np.arctanh(r2)
z_diff = (z1 - z2) / np.sqrt(1/(n1-3) + 1/(n2-3))
p_diff = 2 * (1 - stats.norm.cdf(abs(z_diff)))

print(f"\n  Fisher z-test for BTC-SPY corr change: z={z_diff:.3f}, p={p_diff:.4f}")
print(f"  {'Significant structural break!' if p_diff < 0.05 else 'No significant structural break.'}")

structural_break['fisher_z_test'] = {
    'z_stat': float(z_diff),
    'p_value': float(p_diff),
    'significant': bool(p_diff < 0.05)
}

# ============================================================
# COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY OF KEY FINDINGS")
print("=" * 70)

# Determine key findings
gc_vix_to_btc_sig = any(
    granger_results.get('VIX_to_BTC_RV', {}).get(lag, {}).get('p', 1) < 0.05
    for lag in range(1, 6)
)
gc_btc_to_vix_sig = any(
    granger_results.get('BTC_RV_to_VIX', {}).get(lag, {}).get('p', 1) < 0.05
    for lag in range(1, 6)
)

# Find best BTC allocation
best_alloc = max(static_results.items(), key=lambda x: x[1]['sharpe'])

summary = {
    'Q1_VIX_predicts_BTC_vol': gc_vix_to_btc_sig,
    'Q2_BTC_vol_predicts_VIX': gc_btc_to_vix_sig,
    'Q3_correlation_increasing': trend_result.get('increasing', False),
    'Q3_trend_slope_per_year': trend_result.get('slope_per_year', None),
    'Q4_best_static_BTC_allocation': best_alloc[0],
    'Q4_best_static_sharpe': best_alloc[1]['sharpe'],
    'full_sample_VIX_BTC_RV_corr': correlation_results['VIX vs BTC RV']['pearson_r'],
    'btc_also_crashes_on_spy_crash_pct': tail_dep['btc_also_negative_pct'],
    'structural_break_significant': structural_break['fisher_z_test']['significant'],
}

print(f"\n  Q1 (VIX → BTC vol): {'YES — significant Granger causality' if gc_vix_to_btc_sig else 'NO — not significant'}")
print(f"  Q2 (BTC vol → VIX): {'YES — significant Granger causality' if gc_btc_to_vix_sig else 'NO — not significant'}")
print(f"  Q3 (Correlation increasing?): {'YES — significant positive trend' if trend_result.get('increasing') else 'NO — no significant trend'}")
print(f"  Q4 (Best static BTC allocation): {best_alloc[0]} with Sharpe {best_alloc[1]['sharpe']:.3f}")
print(f"  Full-sample VIX vs BTC RV correlation: {correlation_results['VIX vs BTC RV']['pearson_r']:.3f}")
print(f"  BTC crashes when SPY crashes: {tail_dep['btc_also_negative_pct']:.0f}% of the time")
print(f"  Structural break (pre/post 2021): {'YES' if structural_break['fisher_z_test']['significant'] else 'NO'}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K746',
    'title': 'Bitcoin Volatility and VIX — Is There a Crypto Fear Channel?',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (BTC-USD, SPY, GLD, ^VIX)',
    'data_period': f"{r.index[0].date()} to {r.index[-1].date()}",
    'n_obs': len(r),
    'flag': 'EXPLORATORY — crypto data quality varies',
    'proposer': 'Claude',
    'executor': 'Claude',
    'part_a_descriptive': desc_stats,
    'part_b_correlations': correlation_results,
    'part_b_granger': granger_results,
    'part_b_rolling_corr_by_period': rolling_corr_by_period,
    'part_b_trend': trend_result,
    'part_c_regime_stats': {str(k): v for k, v in regime_stats.items()},
    'part_c_events': event_results,
    'part_d_static_allocations': static_results,
    'part_d_vix_conditioned': vix_cond_results,
    'part_d_baseline_5050': baseline_5050,
    'part_e_tail_dependence': tail_dep,
    'part_e_vix_on_btc_crash': vix_on_btc_crash_result,
    'part_f_structural_break': structural_break,
    'summary': summary,
    'references': [
        'K66: 5% BTC improves portfolio Sharpe (prior VolPred result)',
        'K445: BTC inverse leverage effect (prior VolPred result)',
        'Baur & Dimpfl (2018) Economics Letters — BTC volatility',
        'Bouri et al. (2017) Finance Research Letters — BTC as hedge/safe haven',
        'Conlon & McGee (2020) Finance Research Letters — BTC during COVID',
    ],
}

with open('experiments/k746_bitcoin_vix_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to experiments/k746_bitcoin_vix_results.json")
print("Script saved as experiments/k746_bitcoin_vix.py")
print("\nDone.")
