"""
K392: The Retail Trader Revolution — Has Zero-Commission Trading Changed Volatility?
===================================================================================

跳躍式探索：2020年後零佣金交易（Robinhood 等）帶來大量散戶湧入市場。
GameStop 事件（2021-01）是分水嶺。散戶的湧入是否改變了波動率動態？

Related: K228 gamma doubling 25yr, K391 phase transitions declining post-GFC,
         K364 Monday effect dead, K297 intraday J-shape

Data: SPY, VIX, IWM daily from yfinance (REAL data only)
Periods: Pre-retail (2005-2019) vs Post-retail (2020-2025)

Tests:
1. Structural break in VIX level, clustering (ACF), leverage effect (gamma)
2. Volume patterns: total volume, asymmetry (down vs up days)
3. 0DTE era analysis (2022+): VIX floor, vol compression
4. Small-cap (IWM) vs large-cap (SPY) vol divergence
5. VT (12/VIX) regime stability across eras
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.tsa.stattools import acf
from arch import arch_model
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 80)
print("K392: Retail Trader Revolution — Has Zero-Commission Trading Changed Volatility?")
print("=" * 80)

# ============================================================================
# 1. DATA COLLECTION
# ============================================================================
print("\n[1] Downloading data from yfinance...")

tickers = {
    'SPY': yf.download('SPY', start='2005-01-01', end='2026-03-25', progress=False),
    'VIX': yf.download('^VIX', start='2005-01-01', end='2026-03-25', progress=False),
    'IWM': yf.download('IWM', start='2005-01-01', end='2026-03-25', progress=False),
}

# Flatten multi-level columns if needed
for k in tickers:
    if isinstance(tickers[k].columns, pd.MultiIndex):
        tickers[k].columns = tickers[k].columns.get_level_values(0)

spy = tickers['SPY'].copy()
vix = tickers['VIX'].copy()
iwm = tickers['IWM'].copy()

spy['Return'] = spy['Close'].pct_change()
spy['AbsReturn'] = spy['Return'].abs()
spy['LogReturn'] = np.log(spy['Close'] / spy['Close'].shift(1))
iwm['Return'] = iwm['Close'].pct_change()
iwm['AbsReturn'] = iwm['Return'].abs()

print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()}, {len(spy)} days")
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()}, {len(vix)} days")
print(f"  IWM: {iwm.index[0].date()} to {iwm.index[-1].date()}, {len(iwm)} days")

# ============================================================================
# 2. DEFINE ERAS
# ============================================================================
# Pre-retail: 2005-2019 (before zero-commission revolution)
# Post-retail: 2020-2025 (after Robinhood, zero-commission brokers)
# Sub-eras:
#   - COVID volatility: 2020-01 to 2020-06
#   - Post-COVID retail: 2020-07 to 2021-12
#   - 0DTE era: 2022-01 to present (CBOE launched 0DTE SPX options)

BREAKPOINT = '2020-01-01'
COVID_END = '2020-06-30'
ZERO_DTE_START = '2022-01-01'

eras = {
    'Pre-retail (2005-2019)': ('2005-01-01', '2019-12-31'),
    'Post-retail (2020-2025)': ('2020-01-01', '2026-03-25'),
    'Post-COVID retail (2020H2-2021)': ('2020-07-01', '2021-12-31'),
    '0DTE era (2022+)': ('2022-01-01', '2026-03-25'),
    'Pre-GFC (2005-2007)': ('2005-01-01', '2007-12-31'),
    'Post-GFC (2010-2019)': ('2010-01-01', '2019-12-31'),
}

def slice_era(df, era_name):
    start, end = eras[era_name]
    return df.loc[start:end].dropna(subset=['Return'] if 'Return' in df.columns else ['Close'])

results = {}

# ============================================================================
# 3. VIX LEVEL ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("[3] VIX Level Analysis Across Eras")
print("=" * 80)

vix_stats = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-COVID retail (2020H2-2021)', '0DTE era (2022+)',
                  'Pre-GFC (2005-2007)', 'Post-GFC (2010-2019)']:
    v = slice_era(vix, era_name)
    vix_stats[era_name] = {
        'mean': float(v['Close'].mean()),
        'median': float(v['Close'].median()),
        'std': float(v['Close'].std()),
        'min': float(v['Close'].min()),
        'max': float(v['Close'].max()),
        'pct_below_15': float((v['Close'] < 15).mean() * 100),
        'pct_below_12': float((v['Close'] < 12).mean() * 100),
        'n_days': len(v),
    }

print(f"\n{'Era':<35} {'Mean':>7} {'Median':>7} {'Std':>7} {'Min':>6} {'Max':>6} {'%<15':>6} {'%<12':>6} {'N':>6}")
print("-" * 100)
for era, s in vix_stats.items():
    print(f"{era:<35} {s['mean']:7.2f} {s['median']:7.2f} {s['std']:7.2f} {s['min']:6.2f} {s['max']:6.2f} {s['pct_below_15']:5.1f}% {s['pct_below_12']:5.1f}% {s['n_days']:6d}")

# Welch's t-test: Pre vs Post VIX mean
pre_vix = slice_era(vix, 'Pre-retail (2005-2019)')['Close'].values
post_vix = slice_era(vix, 'Post-retail (2020-2025)')['Close'].values
t_vix, p_vix = stats.ttest_ind(pre_vix, post_vix, equal_var=False)
print(f"\nWelch t-test (Pre vs Post VIX mean): t={t_vix:.3f}, p={p_vix:.6f}")

# More meaningful: Post-GFC vs 0DTE era (both exclude crisis periods)
postgfc_vix = slice_era(vix, 'Post-GFC (2010-2019)')['Close'].values
zdteera_vix = slice_era(vix, '0DTE era (2022+)')['Close'].values
t_vix2, p_vix2 = stats.ttest_ind(postgfc_vix, zdteera_vix, equal_var=False)
print(f"Welch t-test (Post-GFC vs 0DTE era): t={t_vix2:.3f}, p={p_vix2:.6f}")

# VIX floor analysis
print(f"\n--- VIX Floor Analysis ---")
print(f"Post-GFC (2010-2019): VIX 5th pct = {np.percentile(postgfc_vix, 5):.2f}, 10th pct = {np.percentile(postgfc_vix, 10):.2f}")
print(f"0DTE era (2022+):     VIX 5th pct = {np.percentile(zdteera_vix, 5):.2f}, 10th pct = {np.percentile(zdteera_vix, 10):.2f}")

results['vix_levels'] = vix_stats
results['vix_ttest_pre_post'] = {'t': float(t_vix), 'p': float(p_vix)}
results['vix_ttest_postgfc_0dte'] = {'t': float(t_vix2), 'p': float(p_vix2)}
results['vix_floor'] = {
    'postgfc_5th': float(np.percentile(postgfc_vix, 5)),
    'postgfc_10th': float(np.percentile(postgfc_vix, 10)),
    '0dte_5th': float(np.percentile(zdteera_vix, 5)),
    '0dte_10th': float(np.percentile(zdteera_vix, 10)),
}

# ============================================================================
# 4. VOLATILITY CLUSTERING (ACF of |returns|)
# ============================================================================
print("\n" + "=" * 80)
print("[4] Volatility Clustering Analysis (ACF of |returns|)")
print("=" * 80)

acf_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    abs_ret = s['AbsReturn'].dropna().values
    acf_vals = acf(abs_ret, nlags=20, fft=True)
    acf_results[era_name] = {
        'acf_1': float(acf_vals[1]),
        'acf_5': float(acf_vals[5]),
        'acf_10': float(acf_vals[10]),
        'acf_20': float(acf_vals[20]),
        'sum_acf_1_10': float(np.sum(acf_vals[1:11])),
    }

print(f"\n{'Era':<35} {'ACF(1)':>8} {'ACF(5)':>8} {'ACF(10)':>8} {'ACF(20)':>8} {'Sum(1-10)':>10}")
print("-" * 85)
for era, a in acf_results.items():
    print(f"{era:<35} {a['acf_1']:8.4f} {a['acf_5']:8.4f} {a['acf_10']:8.4f} {a['acf_20']:8.4f} {a['sum_acf_1_10']:10.4f}")

results['acf_clustering'] = acf_results

# ============================================================================
# 5. LEVERAGE EFFECT (GAMMA) via GJR-GARCH
# ============================================================================
print("\n" + "=" * 80)
print("[5] Leverage Effect (GJR-GARCH gamma) Across Eras")
print("=" * 80)

gamma_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    ret = s['Return'].dropna().values * 100  # percent returns
    try:
        gjr = arch_model(ret, vol='GARCH', p=1, o=1, q=1, dist='normal')
        res = gjr.fit(disp='off')
        gamma_results[era_name] = {
            'omega': float(res.params.get('omega', np.nan)),
            'alpha': float(res.params.get('alpha[1]', np.nan)),
            'gamma': float(res.params.get('gamma[1]', np.nan)),
            'beta': float(res.params.get('beta[1]', np.nan)),
            'gamma_pvalue': float(res.pvalues.get('gamma[1]', np.nan)),
            'persistence': float(res.params.get('alpha[1]', 0) + res.params.get('beta[1]', 0) + 0.5 * res.params.get('gamma[1]', 0)),
        }
    except Exception as e:
        gamma_results[era_name] = {'error': str(e)}

print(f"\n{'Era':<35} {'alpha':>8} {'gamma':>8} {'beta':>8} {'persist':>8} {'gamma_p':>8}")
print("-" * 83)
for era, g in gamma_results.items():
    if 'error' not in g:
        sig = '***' if g['gamma_pvalue'] < 0.01 else ('**' if g['gamma_pvalue'] < 0.05 else ('*' if g['gamma_pvalue'] < 0.1 else ''))
        print(f"{era:<35} {g['alpha']:8.4f} {g['gamma']:8.4f} {g['beta']:8.4f} {g['persistence']:8.4f} {g['gamma_pvalue']:8.4f} {sig}")
    else:
        print(f"{era:<35} ERROR: {g['error']}")

results['gjr_gamma'] = gamma_results

# ============================================================================
# 6. VOLUME ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("[6] Volume Analysis — Did Retail Trading Increase Volume?")
print("=" * 80)

volume_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Pre-GFC (2005-2007)', 'Post-GFC (2010-2019)',
                  'Post-COVID retail (2020H2-2021)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    vol = s['Volume'].values
    ret = s['Return'].dropna().values

    # Volume on up vs down days
    up_mask = s['Return'] > 0
    down_mask = s['Return'] < 0
    vol_up = s.loc[up_mask, 'Volume'].values
    vol_down = s.loc[down_mask, 'Volume'].values

    volume_results[era_name] = {
        'mean_volume_M': float(np.mean(vol) / 1e6),
        'median_volume_M': float(np.median(vol) / 1e6),
        'vol_up_mean_M': float(np.mean(vol_up) / 1e6) if len(vol_up) > 0 else np.nan,
        'vol_down_mean_M': float(np.mean(vol_down) / 1e6) if len(vol_down) > 0 else np.nan,
        'down_up_ratio': float(np.mean(vol_down) / np.mean(vol_up)) if len(vol_up) > 0 and len(vol_down) > 0 else np.nan,
        'n_days': len(s),
    }

print(f"\n{'Era':<35} {'Mean Vol(M)':>12} {'Med Vol(M)':>12} {'Up Vol(M)':>12} {'Dn Vol(M)':>12} {'Dn/Up':>7}")
print("-" * 95)
for era, v in volume_results.items():
    print(f"{era:<35} {v['mean_volume_M']:12.1f} {v['median_volume_M']:12.1f} {v['vol_up_mean_M']:12.1f} {v['vol_down_mean_M']:12.1f} {v['down_up_ratio']:7.3f}")

results['volume'] = volume_results

# ============================================================================
# 7. VOLUME-VOLATILITY RELATIONSHIP CHANGE
# ============================================================================
print("\n" + "=" * 80)
print("[7] Volume-Volatility Relationship")
print("=" * 80)

vol_vol_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name).dropna(subset=['Return'])
    corr_vol_absret = float(np.corrcoef(s['Volume'].values, s['AbsReturn'].values)[0, 1])

    # Rank correlation (more robust)
    rho, p_rho = stats.spearmanr(s['Volume'].values, s['AbsReturn'].values)

    vol_vol_results[era_name] = {
        'pearson_vol_absret': corr_vol_absret,
        'spearman_vol_absret': float(rho),
        'spearman_pvalue': float(p_rho),
    }

print(f"\n{'Era':<35} {'Pearson':>10} {'Spearman':>10} {'p-value':>10}")
print("-" * 70)
for era, v in vol_vol_results.items():
    print(f"{era:<35} {v['pearson_vol_absret']:10.4f} {v['spearman_vol_absret']:10.4f} {v['spearman_pvalue']:10.6f}")

results['volume_volatility'] = vol_vol_results

# ============================================================================
# 8. REALIZED VOLATILITY DISTRIBUTION SHIFT
# ============================================================================
print("\n" + "=" * 80)
print("[8] Realized Volatility Distribution — Has the Shape Changed?")
print("=" * 80)

rv_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    # 21-day realized vol (annualized)
    rv21 = s['Return'].rolling(21).std() * np.sqrt(252) * 100
    rv21 = rv21.dropna()

    rv_results[era_name] = {
        'mean_rv': float(rv21.mean()),
        'median_rv': float(rv21.median()),
        'std_rv': float(rv21.std()),
        'skew_rv': float(rv21.skew()),
        'kurt_rv': float(rv21.kurtosis()),
        'pct_below_10': float((rv21 < 10).mean() * 100),
        'pct_above_25': float((rv21 > 25).mean() * 100),
        'pct_above_40': float((rv21 > 40).mean() * 100),
    }

print(f"\n{'Era':<35} {'Mean RV':>8} {'Med RV':>8} {'Std':>7} {'Skew':>7} {'Kurt':>7} {'%<10':>6} {'%>25':>6} {'%>40':>6}")
print("-" * 100)
for era, r in rv_results.items():
    print(f"{era:<35} {r['mean_rv']:8.2f} {r['median_rv']:8.2f} {r['std_rv']:7.2f} {r['skew_rv']:7.2f} {r['kurt_rv']:7.2f} {r['pct_below_10']:5.1f}% {r['pct_above_25']:5.1f}% {r['pct_above_40']:5.1f}%")

# KS test: distribution shift
pre_rv = slice_era(spy, 'Post-GFC (2010-2019)')['Return'].rolling(21).std().dropna() * np.sqrt(252) * 100
post_rv = slice_era(spy, '0DTE era (2022+)')['Return'].rolling(21).std().dropna() * np.sqrt(252) * 100
ks_stat, ks_p = stats.ks_2samp(pre_rv.values, post_rv.values)
print(f"\nKS test (Post-GFC RV dist vs 0DTE era RV dist): KS={ks_stat:.4f}, p={ks_p:.6f}")

results['realized_vol'] = rv_results
results['rv_ks_test'] = {'ks_stat': float(ks_stat), 'p': float(ks_p)}

# ============================================================================
# 9. SMALL-CAP (IWM) VS LARGE-CAP (SPY) VOLATILITY DIVERGENCE
# ============================================================================
print("\n" + "=" * 80)
print("[9] Small-Cap (IWM) vs Large-Cap (SPY) Volatility Divergence")
print("=" * 80)

divergence_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)',
                  'Post-COVID retail (2020H2-2021)']:
    s_spy = slice_era(spy, era_name)
    s_iwm = slice_era(iwm, era_name)

    spy_vol = s_spy['Return'].std() * np.sqrt(252) * 100
    iwm_vol = s_iwm['Return'].std() * np.sqrt(252) * 100

    # Correlation between SPY and IWM
    common_idx = s_spy.index.intersection(s_iwm.index)
    spy_r = s_spy.loc[common_idx, 'Return'].dropna()
    iwm_r = s_iwm.loc[common_idx, 'Return'].dropna()
    common_idx2 = spy_r.index.intersection(iwm_r.index)
    corr = float(np.corrcoef(spy_r.loc[common_idx2].values, iwm_r.loc[common_idx2].values)[0, 1])

    divergence_results[era_name] = {
        'spy_annvol': float(spy_vol),
        'iwm_annvol': float(iwm_vol),
        'iwm_spy_ratio': float(iwm_vol / spy_vol),
        'correlation': corr,
    }

print(f"\n{'Era':<35} {'SPY Vol%':>9} {'IWM Vol%':>9} {'IWM/SPY':>8} {'Corr':>7}")
print("-" * 73)
for era, d in divergence_results.items():
    print(f"{era:<35} {d['spy_annvol']:9.2f} {d['iwm_annvol']:9.2f} {d['iwm_spy_ratio']:8.3f} {d['correlation']:7.4f}")

results['small_vs_large_cap'] = divergence_results

# ============================================================================
# 10. RETURN DISTRIBUTION CHANGES (tail risk)
# ============================================================================
print("\n" + "=" * 80)
print("[10] Return Distribution — Tail Risk Changes")
print("=" * 80)

tail_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    ret = s['Return'].dropna().values

    tail_results[era_name] = {
        'mean_ret_bps': float(np.mean(ret) * 10000),
        'std_ret_bps': float(np.std(ret) * 10000),
        'skewness': float(stats.skew(ret)),
        'kurtosis': float(stats.kurtosis(ret)),
        'pct_days_gt_2pct': float((np.abs(ret) > 0.02).mean() * 100),
        'pct_days_gt_3pct': float((np.abs(ret) > 0.03).mean() * 100),
        'max_drawdown_1d': float(np.min(ret) * 100),
        'max_gain_1d': float(np.max(ret) * 100),
        'var_1pct': float(np.percentile(ret, 1) * 100),
        'cvar_1pct': float(np.mean(ret[ret <= np.percentile(ret, 1)]) * 100),
    }

print(f"\n{'Era':<35} {'Skew':>7} {'Kurt':>7} {'%>2%':>6} {'%>3%':>6} {'VaR1%':>7} {'CVaR1%':>8} {'MaxLoss':>8}")
print("-" * 95)
for era, t in tail_results.items():
    print(f"{era:<35} {t['skewness']:7.3f} {t['kurtosis']:7.2f} {t['pct_days_gt_2pct']:5.1f}% {t['pct_days_gt_3pct']:5.1f}% {t['var_1pct']:7.2f}% {t['cvar_1pct']:8.2f}% {t['max_drawdown_1d']:7.2f}%")

results['tail_risk'] = tail_results

# ============================================================================
# 11. VIX-VOLUME INTERACTION (0DTE proxy)
# ============================================================================
print("\n" + "=" * 80)
print("[11] VIX-Volume Interaction — 0DTE Impact Proxy")
print("=" * 80)

# Since we can't directly get 0DTE volume, we use SPY volume as a proxy
# and check if the VIX-Volume relationship changed

vix_vol_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s_spy = slice_era(spy, era_name)
    s_vix = slice_era(vix, era_name)

    common_idx = s_spy.index.intersection(s_vix.index)
    spy_vol_data = s_spy.loc[common_idx, 'Volume']
    vix_close = s_vix.loc[common_idx, 'Close']

    # Correlation between VIX level and SPY volume
    valid = spy_vol_data.notna() & vix_close.notna()
    rho, p = stats.spearmanr(vix_close[valid].values, spy_vol_data[valid].values)

    # Volume when VIX < 15 vs VIX > 25
    low_vix = vix_close < 15
    high_vix = vix_close > 25

    vix_vol_results[era_name] = {
        'spearman_vix_volume': float(rho),
        'spearman_p': float(p),
        'mean_vol_lowvix_M': float(spy_vol_data[low_vix].mean() / 1e6) if low_vix.sum() > 0 else np.nan,
        'mean_vol_highvix_M': float(spy_vol_data[high_vix].mean() / 1e6) if high_vix.sum() > 0 else np.nan,
        'n_lowvix_days': int(low_vix.sum()),
        'n_highvix_days': int(high_vix.sum()),
    }

print(f"\n{'Era':<35} {'Spearman':>10} {'p':>10} {'Vol@VIX<15(M)':>14} {'Vol@VIX>25(M)':>14}")
print("-" * 88)
for era, v in vix_vol_results.items():
    lv = f"{v['mean_vol_lowvix_M']:14.1f}" if not np.isnan(v['mean_vol_lowvix_M']) else "           N/A"
    hv = f"{v['mean_vol_highvix_M']:14.1f}" if not np.isnan(v['mean_vol_highvix_M']) else "           N/A"
    print(f"{era:<35} {v['spearman_vix_volume']:10.4f} {v['spearman_p']:10.6f} {lv} {hv}")

results['vix_volume_interaction'] = vix_vol_results

# ============================================================================
# 12. DAY-OF-WEEK VOLATILITY PATTERNS (retail impact on specific days?)
# ============================================================================
print("\n" + "=" * 80)
print("[12] Day-of-Week Volatility Patterns — Has Retail Changed Weekly Patterns?")
print("=" * 80)

dow_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    s_ret = s.copy()
    s_ret['DOW'] = s_ret.index.dayofweek  # 0=Mon, 4=Fri

    dow_vol = {}
    dow_names = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri'}
    for d in range(5):
        daily = s_ret[s_ret['DOW'] == d]['AbsReturn'].dropna()
        dow_vol[dow_names[d]] = float(daily.mean() * 10000)  # in bps

    # Friday/Monday ratio (retail traders close before weekend?)
    fri_mon_ratio = dow_vol['Fri'] / dow_vol['Mon'] if dow_vol['Mon'] > 0 else np.nan

    dow_results[era_name] = {
        'dow_absret_bps': dow_vol,
        'fri_mon_ratio': float(fri_mon_ratio),
    }

for era, d in dow_results.items():
    print(f"\n{era}:")
    for day, val in d['dow_absret_bps'].items():
        bar = '#' * int(val / 5)
        print(f"  {day}: {val:6.1f} bps {bar}")
    print(f"  Fri/Mon ratio: {d['fri_mon_ratio']:.3f}")

results['dow_patterns'] = dow_results

# ============================================================================
# 13. VT (12/VIX) PERFORMANCE STABILITY
# ============================================================================
print("\n" + "=" * 80)
print("[13] VT = 12/VIX Strategy Performance Stability")
print("=" * 80)

vt_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s_spy = slice_era(spy, era_name)
    s_vix = slice_era(vix, era_name)

    common = s_spy.index.intersection(s_vix.index)
    spy_r = s_spy.loc[common, 'Return'].copy()
    vix_c = s_vix.loc[common, 'Close'].copy()

    valid = spy_r.notna() & vix_c.notna()
    spy_r = spy_r[valid]
    vix_c = vix_c[valid]

    # VT signal: fraction invested = min(12/VIX, 1)
    vt_weight = np.minimum(12.0 / vix_c.values, 1.0)

    # VT portfolio return
    vt_return = vt_weight * spy_r.values

    # Buy & hold return
    bh_return = spy_r.values

    # Performance metrics
    ann_factor = 252
    vt_sharpe = float(np.mean(vt_return) / np.std(vt_return) * np.sqrt(ann_factor)) if np.std(vt_return) > 0 else np.nan
    bh_sharpe = float(np.mean(bh_return) / np.std(bh_return) * np.sqrt(ann_factor)) if np.std(bh_return) > 0 else np.nan

    # VT cumulative
    vt_cum = np.cumprod(1 + vt_return)
    bh_cum = np.cumprod(1 + bh_return)

    # Max drawdown
    def max_drawdown(cum):
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        return float(np.min(dd) * 100)

    vt_mdd = max_drawdown(vt_cum)
    bh_mdd = max_drawdown(bh_cum)

    # Average VT weight
    avg_weight = float(np.mean(vt_weight))

    vt_results[era_name] = {
        'vt_sharpe': vt_sharpe,
        'bh_sharpe': bh_sharpe,
        'sharpe_improvement': float(vt_sharpe - bh_sharpe),
        'vt_ann_ret': float(np.mean(vt_return) * ann_factor * 100),
        'bh_ann_ret': float(np.mean(bh_return) * ann_factor * 100),
        'vt_mdd': vt_mdd,
        'bh_mdd': bh_mdd,
        'avg_vt_weight': avg_weight,
        'vt_ann_vol': float(np.std(vt_return) * np.sqrt(ann_factor) * 100),
        'bh_ann_vol': float(np.std(bh_return) * np.sqrt(ann_factor) * 100),
    }

print(f"\n{'Era':<35} {'VT Sharpe':>10} {'BH Sharpe':>10} {'Improve':>8} {'VT MDD':>8} {'BH MDD':>8} {'AvgWt':>7}")
print("-" * 93)
for era, v in vt_results.items():
    print(f"{era:<35} {v['vt_sharpe']:10.3f} {v['bh_sharpe']:10.3f} {v['sharpe_improvement']:8.3f} {v['vt_mdd']:7.1f}% {v['bh_mdd']:7.1f}% {v['avg_vt_weight']:7.2f}")

results['vt_performance'] = vt_results

# ============================================================================
# 14. VIX MEAN REVERSION SPEED — Has it Changed?
# ============================================================================
print("\n" + "=" * 80)
print("[14] VIX Mean Reversion Speed")
print("=" * 80)

mr_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    v = slice_era(vix, era_name)
    vix_vals = v['Close'].values

    # AR(1): VIX_t = a + b * VIX_{t-1} + e
    # Mean reversion speed = 1 - b (higher = faster reversion)
    y = vix_vals[1:]
    x = vix_vals[:-1]
    valid = ~(np.isnan(y) | np.isnan(x))
    y, x = y[valid], x[valid]

    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    half_life = -np.log(2) / np.log(abs(slope)) if abs(slope) < 1 and slope > 0 else np.nan

    mr_results[era_name] = {
        'ar1_coef': float(slope),
        'mean_reversion_speed': float(1 - slope),
        'half_life_days': float(half_life),
        'r_squared': float(r_value ** 2),
        'implied_mean': float(intercept / (1 - slope)) if slope < 1 else np.nan,
    }

print(f"\n{'Era':<35} {'AR(1)':>7} {'MR Speed':>9} {'Half-Life':>10} {'R2':>7} {'Implied Mean':>13}")
print("-" * 85)
for era, m in mr_results.items():
    hl = f"{m['half_life_days']:10.1f}" if not np.isnan(m['half_life_days']) else "       N/A"
    im = f"{m['implied_mean']:13.2f}" if not np.isnan(m['implied_mean']) else "          N/A"
    print(f"{era:<35} {m['ar1_coef']:7.4f} {m['mean_reversion_speed']:9.4f} {hl} {m['r_squared']:7.4f} {im}")

results['vix_mean_reversion'] = mr_results

# ============================================================================
# 15. OVERNIGHT VS INTRADAY RETURN DECOMPOSITION
# ============================================================================
print("\n" + "=" * 80)
print("[15] Overnight vs Intraday Return — Retail Overnight Risk")
print("=" * 80)

oi_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)

    # Overnight return = Open_t / Close_{t-1} - 1
    # Intraday return = Close_t / Open_t - 1
    overnight = s['Open'] / s['Close'].shift(1) - 1
    intraday = s['Close'] / s['Open'] - 1

    overnight = overnight.dropna()
    intraday = intraday.dropna()

    common = overnight.index.intersection(intraday.index)
    overnight = overnight.loc[common]
    intraday = intraday.loc[common]

    oi_results[era_name] = {
        'overnight_mean_bps': float(overnight.mean() * 10000),
        'intraday_mean_bps': float(intraday.mean() * 10000),
        'overnight_std_bps': float(overnight.std() * 10000),
        'intraday_std_bps': float(intraday.std() * 10000),
        'overnight_sharpe': float(overnight.mean() / overnight.std() * np.sqrt(252)) if overnight.std() > 0 else np.nan,
        'intraday_sharpe': float(intraday.mean() / intraday.std() * np.sqrt(252)) if intraday.std() > 0 else np.nan,
        'overnight_fraction_of_total_return': float(overnight.sum() / (overnight.sum() + intraday.sum()) * 100) if (overnight.sum() + intraday.sum()) != 0 else np.nan,
    }

print(f"\n{'Era':<35} {'ON Mean':>8} {'ID Mean':>8} {'ON Std':>8} {'ID Std':>8} {'ON Sharpe':>10} {'ID Sharpe':>10} {'ON%Ret':>7}")
print("-" * 100)
for era, o in oi_results.items():
    print(f"{era:<35} {o['overnight_mean_bps']:8.2f} {o['intraday_mean_bps']:8.2f} {o['overnight_std_bps']:8.1f} {o['intraday_std_bps']:8.1f} {o['overnight_sharpe']:10.3f} {o['intraday_sharpe']:10.3f} {o['overnight_fraction_of_total_return']:6.1f}%")

results['overnight_intraday'] = oi_results

# ============================================================================
# 16. VIX TERM STRUCTURE PROXY — VIX vs 21-day RV spread
# ============================================================================
print("\n" + "=" * 80)
print("[16] VIX vs Realized Vol Spread (Variance Risk Premium Proxy)")
print("=" * 80)

vrp_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s_spy = slice_era(spy, era_name)
    s_vix = slice_era(vix, era_name)

    rv21 = s_spy['Return'].rolling(21).std() * np.sqrt(252) * 100

    common = rv21.dropna().index.intersection(s_vix.index)
    rv = rv21.loc[common]
    vi = s_vix.loc[common, 'Close']

    spread = vi - rv  # VIX - RV = Variance Risk Premium proxy

    vrp_results[era_name] = {
        'mean_vrp': float(spread.mean()),
        'median_vrp': float(spread.median()),
        'std_vrp': float(spread.std()),
        'pct_positive': float((spread > 0).mean() * 100),
        'mean_vix': float(vi.mean()),
        'mean_rv': float(rv.mean()),
    }

print(f"\n{'Era':<35} {'Mean VRP':>9} {'Med VRP':>9} {'Std VRP':>9} {'%Pos':>6} {'Mean VIX':>9} {'Mean RV':>8}")
print("-" * 90)
for era, v in vrp_results.items():
    print(f"{era:<35} {v['mean_vrp']:9.2f} {v['median_vrp']:9.2f} {v['std_vrp']:9.2f} {v['pct_positive']:5.1f}% {v['mean_vix']:9.2f} {v['mean_rv']:8.2f}")

# Welch t-test on VRP
pre_vrp_data = (slice_era(vix, 'Post-GFC (2010-2019)')['Close'] -
                slice_era(spy, 'Post-GFC (2010-2019)')['Return'].rolling(21).std() * np.sqrt(252) * 100)
post_vrp_data = (slice_era(vix, '0DTE era (2022+)')['Close'] -
                 slice_era(spy, '0DTE era (2022+)')['Return'].rolling(21).std() * np.sqrt(252) * 100)
pre_vrp_data = pre_vrp_data.dropna()
post_vrp_data = post_vrp_data.dropna()
t_vrp, p_vrp = stats.ttest_ind(pre_vrp_data.values, post_vrp_data.values, equal_var=False)
print(f"\nWelch t-test VRP (Post-GFC vs 0DTE): t={t_vrp:.3f}, p={p_vrp:.6f}")

results['variance_risk_premium'] = vrp_results
results['vrp_ttest'] = {'t': float(t_vrp), 'p': float(p_vrp)}

# ============================================================================
# 17. YEAR-BY-YEAR VIX AND VOLATILITY TREND
# ============================================================================
print("\n" + "=" * 80)
print("[17] Year-by-Year VIX & Realized Vol Trend")
print("=" * 80)

yearly = {}
for year in range(2005, 2026):
    yr_str = str(year)
    spy_yr = spy.loc[yr_str].dropna(subset=['Return']) if yr_str in spy.index.year.astype(str).values else pd.DataFrame()
    vix_yr = vix.loc[yr_str] if yr_str in vix.index.year.astype(str).values else pd.DataFrame()

    if len(spy_yr) > 50 and len(vix_yr) > 50:
        rv = spy_yr['Return'].std() * np.sqrt(252) * 100
        yearly[year] = {
            'mean_vix': float(vix_yr['Close'].mean()),
            'rv_ann': float(rv),
            'vrp': float(vix_yr['Close'].mean() - rv),
            'mean_volume_M': float(spy_yr['Volume'].mean() / 1e6),
            'n_days_gt_2pct': int((spy_yr['Return'].abs() > 0.02).sum()),
        }

print(f"\n{'Year':>6} {'Mean VIX':>9} {'RV Ann%':>8} {'VRP':>7} {'Vol(M)':>8} {'Days>2%':>8}")
print("-" * 50)
for year, y in yearly.items():
    marker = ' <-- retail era' if year >= 2020 else ''
    print(f"{year:6d} {y['mean_vix']:9.2f} {y['rv_ann']:8.2f} {y['vrp']:7.2f} {y['mean_volume_M']:8.1f} {y['n_days_gt_2pct']:8d}{marker}")

results['yearly_trends'] = yearly

# ============================================================================
# 18. STRUCTURAL BREAK TEST (Chow-like via rolling regression)
# ============================================================================
print("\n" + "=" * 80)
print("[18] Structural Break Detection — Rolling GJR-GARCH gamma")
print("=" * 80)

# Estimate GJR-GARCH gamma on rolling 2-year windows
print("Estimating GJR-GARCH gamma on rolling 2-year windows...")

spy_full = spy.dropna(subset=['Return']).copy()
ret_full = spy_full['Return'].values * 100

window = 504  # ~2 years
step = 63  # ~quarterly
gamma_ts = []

for i in range(0, len(ret_full) - window, step):
    chunk = ret_full[i:i+window]
    center_date = spy_full.index[i + window // 2]
    try:
        gjr = arch_model(chunk, vol='GARCH', p=1, o=1, q=1, dist='normal')
        res = gjr.fit(disp='off')
        g = float(res.params.get('gamma[1]', np.nan))
        a = float(res.params.get('alpha[1]', np.nan))
        b = float(res.params.get('beta[1]', np.nan))
        gamma_ts.append({
            'date': str(center_date.date()),
            'gamma': g,
            'alpha': a,
            'beta': b,
            'persistence': a + b + 0.5 * g,
        })
    except:
        pass

print(f"\n  Estimated {len(gamma_ts)} rolling windows")
print(f"\n{'Date':>12} {'Gamma':>8} {'Alpha':>8} {'Beta':>8} {'Persist':>8}")
print("-" * 48)
for gt in gamma_ts[-15:]:  # show last 15
    marker = ' **' if gt['date'] >= '2020' else ''
    print(f"{gt['date']:>12} {gt['gamma']:8.4f} {gt['alpha']:8.4f} {gt['beta']:8.4f} {gt['persistence']:8.4f}{marker}")

# Pre vs post gamma comparison
pre_gammas = [g['gamma'] for g in gamma_ts if g['date'] < '2020-01-01']
post_gammas = [g['gamma'] for g in gamma_ts if g['date'] >= '2020-01-01']
if pre_gammas and post_gammas:
    t_gamma, p_gamma = stats.ttest_ind(pre_gammas, post_gammas, equal_var=False)
    print(f"\nGamma: Pre-retail mean={np.mean(pre_gammas):.4f}, Post-retail mean={np.mean(post_gammas):.4f}")
    print(f"Welch t-test: t={t_gamma:.3f}, p={p_gamma:.6f}")
    results['rolling_gamma'] = {
        'pre_mean': float(np.mean(pre_gammas)),
        'post_mean': float(np.mean(post_gammas)),
        't_stat': float(t_gamma),
        'p_value': float(p_gamma),
    }

results['gamma_timeseries'] = gamma_ts

# ============================================================================
# 19. INTRADAY RANGE ANALYSIS (High-Low as % of Close)
# ============================================================================
print("\n" + "=" * 80)
print("[19] Intraday Range (High-Low)/Close — Has Daily Range Changed?")
print("=" * 80)

range_results = {}
for era_name in ['Pre-retail (2005-2019)', 'Post-retail (2020-2025)',
                  'Post-GFC (2010-2019)', '0DTE era (2022+)']:
    s = slice_era(spy, era_name)
    daily_range = (s['High'] - s['Low']) / s['Close'] * 100

    range_results[era_name] = {
        'mean_range_pct': float(daily_range.mean()),
        'median_range_pct': float(daily_range.median()),
        'std_range_pct': float(daily_range.std()),
        'pct_gt_2pct': float((daily_range > 2).mean() * 100),
    }

print(f"\n{'Era':<35} {'Mean Range%':>12} {'Med Range%':>12} {'Std':>8} {'%>2%':>7}")
print("-" * 78)
for era, r in range_results.items():
    print(f"{era:<35} {r['mean_range_pct']:12.4f} {r['median_range_pct']:12.4f} {r['std_range_pct']:8.4f} {r['pct_gt_2pct']:6.1f}%")

results['intraday_range'] = range_results

# ============================================================================
# 20. SUMMARY & CONCLUSIONS
# ============================================================================
print("\n" + "=" * 80)
print("SUMMARY: K392 — Retail Trader Revolution Impact on Volatility")
print("=" * 80)

print("""
KEY FINDINGS:
""")

# VIX level
pre_vix_mean = vix_stats['Pre-retail (2005-2019)']['mean']
post_vix_mean = vix_stats['Post-retail (2020-2025)']['mean']
postgfc_mean = vix_stats['Post-GFC (2010-2019)']['mean']
dte0_mean = vix_stats['0DTE era (2022+)']['mean']
print(f"1. VIX LEVEL:")
print(f"   Pre-retail mean: {pre_vix_mean:.2f}, Post-retail: {post_vix_mean:.2f}")
print(f"   Post-GFC (2010-19): {postgfc_mean:.2f}, 0DTE era (2022+): {dte0_mean:.2f}")
print(f"   Post-GFC vs 0DTE t-test: t={t_vix2:.3f}, p={p_vix2:.6f}")

# Gamma
if 'rolling_gamma' in results:
    rg = results['rolling_gamma']
    print(f"\n2. LEVERAGE EFFECT (GAMMA):")
    print(f"   Pre-retail mean gamma: {rg['pre_mean']:.4f}")
    print(f"   Post-retail mean gamma: {rg['post_mean']:.4f}")
    print(f"   t-test: t={rg['t_stat']:.3f}, p={rg['p_value']:.6f}")

# Volume
print(f"\n3. VOLUME:")
print(f"   Post-GFC mean: {volume_results['Post-GFC (2010-2019)']['mean_volume_M']:.1f}M")
print(f"   0DTE era mean: {volume_results['0DTE era (2022+)']['mean_volume_M']:.1f}M")
print(f"   Down/Up ratio Pre: {volume_results['Post-GFC (2010-2019)']['down_up_ratio']:.3f}")
print(f"   Down/Up ratio 0DTE: {volume_results['0DTE era (2022+)']['down_up_ratio']:.3f}")

# VT performance
print(f"\n4. VT (12/VIX) STRATEGY STABILITY:")
for era in ['Post-GFC (2010-2019)', '0DTE era (2022+)']:
    v = vt_results[era]
    print(f"   {era}: VT Sharpe={v['vt_sharpe']:.3f}, BH Sharpe={v['bh_sharpe']:.3f}, Improvement={v['sharpe_improvement']:.3f}")

# VRP
print(f"\n5. VARIANCE RISK PREMIUM:")
print(f"   Post-GFC: {vrp_results['Post-GFC (2010-2019)']['mean_vrp']:.2f}")
print(f"   0DTE era: {vrp_results['0DTE era (2022+)']['mean_vrp']:.2f}")
print(f"   VRP t-test: t={t_vrp:.3f}, p={p_vrp:.6f}")

# Overnight
print(f"\n6. OVERNIGHT VS INTRADAY:")
print(f"   Post-GFC overnight return fraction: {oi_results['Post-GFC (2010-2019)']['overnight_fraction_of_total_return']:.1f}%")
print(f"   0DTE era overnight return fraction: {oi_results['0DTE era (2022+)']['overnight_fraction_of_total_return']:.1f}%")

# Small cap divergence
print(f"\n7. SMALL-CAP vs LARGE-CAP:")
print(f"   Post-GFC IWM/SPY vol ratio: {divergence_results['Post-GFC (2010-2019)']['iwm_spy_ratio']:.3f}")
print(f"   0DTE era IWM/SPY vol ratio: {divergence_results['0DTE era (2022+)']['iwm_spy_ratio']:.3f}")
print(f"   Post-COVID retail IWM/SPY vol ratio: {divergence_results['Post-COVID retail (2020H2-2021)']['iwm_spy_ratio']:.3f}")

print(f"\n8. MEAN REVERSION SPEED:")
print(f"   Post-GFC half-life: {mr_results['Post-GFC (2010-2019)']['half_life_days']:.1f} days")
print(f"   0DTE era half-life: {mr_results['0DTE era (2022+)']['half_life_days']:.1f} days")

# ============================================================================
# SAVE RESULTS
# ============================================================================
output_file = 'experiments/k392_retail_revolution_results.json'

# Convert any remaining numpy types
def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(i) for i in obj]
    return obj

results_clean = convert_numpy(results)

with open(output_file, 'w') as f:
    json.dump(results_clean, f, indent=2, default=str)

print(f"\nResults saved to {output_file}")
print("\n" + "=" * 80)
print("K392 EXPERIMENT COMPLETE")
print("=" * 80)
