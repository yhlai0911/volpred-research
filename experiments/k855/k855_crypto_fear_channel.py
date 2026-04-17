"""
K855: Crypto Fear Channel — 2026 Tariff Crisis Update

UPDATE to K746b (bidirectional BTC↔VIX Granger, asymmetric: BTC→VIX stronger in high-vol).
Key question: Has the crypto fear channel STRENGTHENED post-BTC-ETF (2024+)?

Context:
- K746b: BTC↔VIX bidirectional Granger causality confirmed (2015-2026-03)
- K639: BTC→SPY Granger causality, inverse leverage, NOT crisis hedge
- K565: BTC 5% allocation Harvey PASS (t=3.07) but post-ETF correlation 0→0.35
- April 2-3 2026: Trump tariffs caused major turmoil, VIX spiked >30

Research Questions:
1. Has BTC-VIX Granger causality strengthened post-BTC-ETF (2024+) vs pre-ETF?
2. During April 2026 tariff crisis, did BTC lead VIX or follow it?
3. Is BTC still a diversifier (corr < 0.3) or has it become a risk-on asset?
4. Does BTC realized vol predict VIX direction change better than other assets?

Methodology:
- Rolling 60-day correlation (BTC-SPY, BTC-VIX)
- Granger causality per sub-period (pre-ETF, post-ETF, tariff crisis)
- Asymmetric Granger by VIX regime
- Lead-lag cross-correlation at lags -5 to +5
- VAR impulse response functions

Error Log rules: DM test from volpred.stats, Harvey |t|>3.0, no hard-coded values.

Data: BTC-USD, SPY, GLD, ^VIX, ^GSPC from yfinance (2020-01 to 2026-04-04)
References: K746b, K639, K565; Corbet et al. (2020) JBF; Bouri et al. (2017) Finance Research Letters

[提出: Claude (K746b extension), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
from statsmodels.tsa.api import VAR
from concurrent.futures import ProcessPoolExecutor
import os

warnings.filterwarnings('ignore')

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(os.path.dirname(OUTPUT_DIR), 'experiments', 'k855_charts')
os.makedirs(CHART_DIR, exist_ok=True)

# ============================================================
# DATA COLLECTION
# ============================================================
print("=" * 70)
print("K855: Crypto Fear Channel — 2026 Tariff Crisis Update")
print("=" * 70)

tickers = {
    'BTC': 'BTC-USD',
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX',
    'GSPC': '^GSPC',
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2020-01-01', end='2026-04-05', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].dropna()
    print(f"{name}: {len(data[name])} obs, {data[name].index[0].date()} to {data[name].index[-1].date()}")

# Align all series on common dates
df_all = pd.DataFrame(data).dropna()
print(f"\nAligned dataset: {len(df_all)} obs, {df_all.index[0].date()} to {df_all.index[-1].date()}")

# Log returns
returns = np.log(df_all[['BTC', 'SPY', 'GLD', 'GSPC']] / df_all[['BTC', 'SPY', 'GLD', 'GSPC']].shift(1)).dropna()
returns['VIX'] = df_all['VIX'].reindex(returns.index)
returns['VIX_chg'] = returns['VIX'].diff()  # VIX level change
returns['VIX_pct'] = returns['VIX'].pct_change()  # VIX percentage change

# Absolute returns as daily vol proxy (non-overlapping)
for asset in ['BTC', 'SPY', 'GLD']:
    returns[f'{asset}_absret'] = returns[asset].abs()

# Realized vol: 22-day rolling std of log returns, annualized
for asset in ['BTC', 'SPY', 'GLD']:
    returns[f'{asset}_RV22'] = returns[asset].rolling(22).std() * np.sqrt(252) * 100

returns = returns.dropna()
print(f"After RV22 dropna: {len(returns)} obs")

# ============================================================
# DEFINE SUB-PERIODS
# ============================================================
PERIODS = {
    'Full': ('2020-01-01', '2026-04-05'),
    'Pre-ETF': ('2020-01-01', '2023-12-31'),
    'Post-ETF': ('2024-01-01', '2026-04-05'),
    'Tariff Crisis (2026)': ('2026-03-01', '2026-04-05'),
}

period_data = {}
for pname, (start, end) in PERIODS.items():
    mask = (returns.index >= start) & (returns.index <= end)
    period_data[pname] = returns[mask].copy()
    print(f"Period '{pname}': {len(period_data[pname])} obs")

# ============================================================
# PART A: DESCRIPTIVE STATISTICS PER PERIOD
# ============================================================
print("\n" + "=" * 70)
print("PART A: Descriptive Statistics by Period")
print("=" * 70)

desc_results = {}
for pname, pdata in period_data.items():
    desc_results[pname] = {}
    print(f"\n--- {pname} ({len(pdata)} obs) ---")
    for asset in ['BTC', 'SPY', 'GLD']:
        r = pdata[asset]
        ann_vol = r.std() * np.sqrt(252) * 100
        ann_ret = r.mean() * 252 * 100  # log return annualized
        desc_results[pname][asset] = {
            'n_obs': int(len(r)),
            'ann_return_pct': round(float(ann_ret), 2),
            'ann_vol_pct': round(float(ann_vol), 2),
            'skewness': round(float(stats.skew(r)), 4),
            'kurtosis': round(float(stats.kurtosis(r)), 4),
            'min_daily_pct': round(float(r.min() * 100), 2),
            'max_daily_pct': round(float(r.max() * 100), 2),
        }
        print(f"  {asset}: AnnRet={ann_ret:.1f}%, AnnVol={ann_vol:.1f}%, Skew={stats.skew(r):.3f}, Kurt={stats.kurtosis(r):.1f}")

    # BTC-SPY correlation
    corr_btc_spy = pdata['BTC'].corr(pdata['SPY'])
    corr_btc_vix = pdata['BTC'].corr(pdata['VIX_chg'])
    desc_results[pname]['correlations'] = {
        'BTC_SPY_return': round(float(corr_btc_spy), 4),
        'BTC_VIX_change': round(float(corr_btc_vix), 4),
    }
    print(f"  Corr(BTC,SPY)={corr_btc_spy:.3f}, Corr(BTC,dVIX)={corr_btc_vix:.3f}")

# VIX stats per period
print("\n--- VIX Levels ---")
for pname, pdata in period_data.items():
    vix = pdata['VIX']
    print(f"  {pname}: mean={vix.mean():.1f}, median={vix.median():.1f}, max={vix.max():.1f}, "
          f"days>25={int((vix>25).sum())}, days>30={int((vix>30).sum())}")
    desc_results[pname]['VIX'] = {
        'mean': round(float(vix.mean()), 2),
        'median': round(float(vix.median()), 2),
        'max': round(float(vix.max()), 2),
        'days_above_25': int((vix > 25).sum()),
        'days_above_30': int((vix > 30).sum()),
    }

# ============================================================
# PART B: ROLLING 60-DAY CORRELATIONS
# ============================================================
print("\n" + "=" * 70)
print("PART B: Rolling 60-Day Correlations")
print("=" * 70)

window = 60
rolling_corr_btc_spy = returns['BTC'].rolling(window).corr(returns['SPY'])
rolling_corr_btc_vix_chg = returns['BTC'].rolling(window).corr(returns['VIX_chg'])
rolling_corr_btc_gld = returns['BTC'].rolling(window).corr(returns['GLD'])

# Summary stats for rolling correlations per period
rolling_corr_results = {}
for pname, (start, end) in PERIODS.items():
    mask = (rolling_corr_btc_spy.index >= start) & (rolling_corr_btc_spy.index <= end)
    rc_spy = rolling_corr_btc_spy[mask].dropna()
    rc_vix = rolling_corr_btc_vix_chg[mask].dropna()
    rc_gld = rolling_corr_btc_gld[mask].dropna()

    rolling_corr_results[pname] = {
        'BTC_SPY': {
            'mean': round(float(rc_spy.mean()), 4),
            'std': round(float(rc_spy.std()), 4),
            'min': round(float(rc_spy.min()), 4),
            'max': round(float(rc_spy.max()), 4),
        },
        'BTC_VIX_chg': {
            'mean': round(float(rc_vix.mean()), 4),
            'std': round(float(rc_vix.std()), 4),
            'min': round(float(rc_vix.min()), 4),
            'max': round(float(rc_vix.max()), 4),
        },
        'BTC_GLD': {
            'mean': round(float(rc_gld.mean()), 4),
            'std': round(float(rc_gld.std()), 4),
            'min': round(float(rc_gld.min()), 4),
            'max': round(float(rc_gld.max()), 4),
        },
    }
    print(f"\n{pname}:")
    print(f"  BTC-SPY: mean={rc_spy.mean():.3f} ± {rc_spy.std():.3f} [{rc_spy.min():.3f}, {rc_spy.max():.3f}]")
    print(f"  BTC-dVIX: mean={rc_vix.mean():.3f} ± {rc_vix.std():.3f} [{rc_vix.min():.3f}, {rc_vix.max():.3f}]")
    print(f"  BTC-GLD: mean={rc_gld.mean():.3f} ± {rc_gld.std():.3f} [{rc_gld.min():.3f}, {rc_gld.max():.3f}]")

# Fisher z-test: pre-ETF vs post-ETF correlation change
def fisher_z_test(r1, n1, r2, n2):
    """Test H0: rho1 = rho2 using Fisher z-transform."""
    z1 = np.arctanh(r1)
    z2 = np.arctanh(r2)
    se = np.sqrt(1/(n1-3) + 1/(n2-3))
    z_stat = (z1 - z2) / se
    p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    return float(z_stat), float(p_val)

# Test if BTC-SPY correlation increased post-ETF
pre_etf_corr = period_data['Pre-ETF']['BTC'].corr(period_data['Pre-ETF']['SPY'])
post_etf_corr = period_data['Post-ETF']['BTC'].corr(period_data['Post-ETF']['SPY'])
n_pre = len(period_data['Pre-ETF'])
n_post = len(period_data['Post-ETF'])
z_stat, p_val = fisher_z_test(pre_etf_corr, n_pre, post_etf_corr, n_post)
print(f"\nFisher z-test (BTC-SPY correlation change):")
print(f"  Pre-ETF: {pre_etf_corr:.4f} (n={n_pre})")
print(f"  Post-ETF: {post_etf_corr:.4f} (n={n_post})")
print(f"  z={z_stat:.3f}, p={p_val:.4f}")

fisher_z_result = {
    'BTC_SPY': {
        'pre_etf_corr': round(float(pre_etf_corr), 4),
        'post_etf_corr': round(float(post_etf_corr), 4),
        'z_stat': round(float(z_stat), 4),
        'p_val': round(float(p_val), 6),
        'significant_at_005': bool(p_val < 0.05),
    }
}

# Same for BTC-VIX change
pre_vix_corr = period_data['Pre-ETF']['BTC'].corr(period_data['Pre-ETF']['VIX_chg'])
post_vix_corr = period_data['Post-ETF']['BTC'].corr(period_data['Post-ETF']['VIX_chg'])
z2, p2 = fisher_z_test(pre_vix_corr, n_pre, post_vix_corr, n_post)
print(f"\nFisher z-test (BTC-dVIX correlation change):")
print(f"  Pre-ETF: {pre_vix_corr:.4f}, Post-ETF: {post_vix_corr:.4f}")
print(f"  z={z2:.3f}, p={p2:.4f}")

fisher_z_result['BTC_VIX_chg'] = {
    'pre_etf_corr': round(float(pre_vix_corr), 4),
    'post_etf_corr': round(float(post_vix_corr), 4),
    'z_stat': round(float(z2), 4),
    'p_val': round(float(p2), 6),
    'significant_at_005': bool(p2 < 0.05),
}

# ============================================================
# PART C: GRANGER CAUSALITY PER PERIOD
# ============================================================
print("\n" + "=" * 70)
print("PART C: Granger Causality Tests by Period")
print("=" * 70)

def run_granger_test(series_y, series_x, max_lag=5, label=""):
    """
    Test: does x Granger-cause y?
    Following K746b: use forward-looking target (next-day |r|).
    Uses AIC for lag selection (not min-p cherry-picking).
    Returns best lag, F-stat, p-value.
    """
    df_gc = pd.DataFrame({'y': series_y, 'x': series_x}).dropna()
    if len(df_gc) < max_lag * 3 + 10:
        return {'lag': None, 'f_stat': None, 'p_val': None, 'n_obs': len(df_gc), 'error': 'insufficient_data'}

    try:
        result = grangercausalitytests(df_gc[['y', 'x']], maxlag=max_lag, verbose=False)

        # Use AIC for lag selection
        best_lag = None
        best_aic = np.inf
        for lag in range(1, max_lag + 1):
            aic_val = result[lag][1][1].aic  # restricted model AIC
            if aic_val < best_aic:
                best_aic = aic_val
                best_lag = lag

        # Get F-stat and p-value at best lag
        f_stat = result[best_lag][0]['ssr_ftest'][0]
        p_val = result[best_lag][0]['ssr_ftest'][1]

        # Also get min-p across all lags for comparison
        min_p = min(result[lag][0]['ssr_ftest'][1] for lag in range(1, max_lag + 1))
        min_p_lag = min(range(1, max_lag + 1), key=lambda lag: result[lag][0]['ssr_ftest'][1])

        return {
            'aic_best_lag': int(best_lag),
            'aic_f_stat': round(float(f_stat), 4),
            'aic_p_val': round(float(p_val), 6),
            'min_p_lag': int(min_p_lag),
            'min_p_val': round(float(min_p), 6),
            'n_obs': int(len(df_gc)),
            'significant_aic': bool(p_val < 0.05),
        }
    except Exception as e:
        return {'error': str(e), 'n_obs': int(len(df_gc))}

granger_results = {}
for pname, pdata in period_data.items():
    granger_results[pname] = {}
    print(f"\n--- {pname} (n={len(pdata)}) ---")

    # Following K746b: use next-day absolute return (forward-looking, non-overlapping)
    # Test 1: BTC |r_t| → VIX change_{t+1} (does BTC vol predict VIX moves?)
    btc_absret = pdata['BTC_absret']
    vix_chg_next = pdata['VIX_chg'].shift(-1)  # next-day VIX change

    gc1 = run_granger_test(vix_chg_next, btc_absret, max_lag=5, label="BTC_absret→dVIX(t+1)")
    granger_results[pname]['BTC_absret_to_VIX_chg'] = gc1
    print(f"  BTC |r| → dVIX(t+1): lag={gc1.get('aic_best_lag')}, F={gc1.get('aic_f_stat')}, "
          f"p={gc1.get('aic_p_val')}, sig={gc1.get('significant_aic')}")

    # Test 2: VIX level → BTC |r_{t+1}| (does VIX predict BTC vol?)
    vix_level = pdata['VIX']
    btc_absret_next = pdata['BTC_absret'].shift(-1)

    gc2 = run_granger_test(btc_absret_next, vix_level, max_lag=5, label="VIX→BTC_absret(t+1)")
    granger_results[pname]['VIX_to_BTC_absret'] = gc2
    print(f"  VIX → BTC |r|(t+1): lag={gc2.get('aic_best_lag')}, F={gc2.get('aic_f_stat')}, "
          f"p={gc2.get('aic_p_val')}, sig={gc2.get('significant_aic')}")

    # Test 3: BTC RV22 → VIX (does BTC sustained vol predict VIX?)
    btc_rv = pdata['BTC_RV22']
    vix_next = pdata['VIX'].shift(-1)

    gc3 = run_granger_test(vix_next, btc_rv, max_lag=5, label="BTC_RV22→VIX(t+1)")
    granger_results[pname]['BTC_RV22_to_VIX'] = gc3
    print(f"  BTC RV22 → VIX(t+1): lag={gc3.get('aic_best_lag')}, F={gc3.get('aic_f_stat')}, "
          f"p={gc3.get('aic_p_val')}, sig={gc3.get('significant_aic')}")

    # Test 4: SPY |r_t| → dVIX(t+1) as benchmark
    spy_absret = pdata['SPY_absret']
    gc4 = run_granger_test(vix_chg_next, spy_absret, max_lag=5, label="SPY_absret→dVIX(t+1)")
    granger_results[pname]['SPY_absret_to_VIX_chg'] = gc4
    print(f"  SPY |r| → dVIX(t+1): lag={gc4.get('aic_best_lag')}, F={gc4.get('aic_f_stat')}, "
          f"p={gc4.get('aic_p_val')}, sig={gc4.get('significant_aic')}")

# ============================================================
# PART D: ASYMMETRIC GRANGER (by VIX regime)
# ============================================================
print("\n" + "=" * 70)
print("PART D: Asymmetric Granger Causality by VIX Regime")
print("=" * 70)

asymmetric_results = {}
for pname in ['Full', 'Pre-ETF', 'Post-ETF']:
    pdata = period_data[pname]
    vix_median = pdata['VIX'].median()

    high_vix_mask = pdata['VIX'] > vix_median
    low_vix_mask = pdata['VIX'] <= vix_median

    pdata_high = pdata[high_vix_mask]
    pdata_low = pdata[low_vix_mask]

    asymmetric_results[pname] = {'vix_median': round(float(vix_median), 2)}
    print(f"\n--- {pname} (VIX median={vix_median:.1f}) ---")

    for regime, rdata in [('High_VIX', pdata_high), ('Low_VIX', pdata_low)]:
        print(f"  {regime} (n={len(rdata)}):")

        btc_absret = rdata['BTC_absret']
        vix_chg_next = rdata['VIX_chg'].shift(-1)

        gc_btc_vix = run_granger_test(vix_chg_next, btc_absret, max_lag=3, label=f"{regime}: BTC→dVIX")

        vix_level = rdata['VIX']
        btc_absret_next = rdata['BTC_absret'].shift(-1)
        gc_vix_btc = run_granger_test(btc_absret_next, vix_level, max_lag=3, label=f"{regime}: VIX→BTC")

        asymmetric_results[pname][regime] = {
            'n_obs': int(len(rdata)),
            'BTC_to_VIX': gc_btc_vix,
            'VIX_to_BTC': gc_vix_btc,
        }

        print(f"    BTC→dVIX: p={gc_btc_vix.get('aic_p_val')}, sig={gc_btc_vix.get('significant_aic')}")
        print(f"    VIX→BTC: p={gc_vix_btc.get('aic_p_val')}, sig={gc_vix_btc.get('significant_aic')}")

# ============================================================
# PART E: LEAD-LAG CROSS-CORRELATION
# ============================================================
print("\n" + "=" * 70)
print("PART E: Lead-Lag Cross-Correlation (BTC return vs VIX change)")
print("=" * 70)

lead_lag_results = {}
for pname in ['Full', 'Pre-ETF', 'Post-ETF', 'Tariff Crisis (2026)']:
    pdata = period_data[pname]
    btc_ret = pdata['BTC']
    vix_chg = pdata['VIX_chg']

    lead_lag_results[pname] = {}
    print(f"\n--- {pname} ---")
    for lag in range(-5, 6):
        if lag < 0:
            # Negative lag: BTC leads (BTC at t, VIX at t+|lag|)
            shifted = vix_chg.shift(lag)  # shift VIX back = VIX future
        elif lag > 0:
            # Positive lag: VIX leads (VIX at t, BTC at t+lag)
            shifted = vix_chg.shift(lag)  # shift VIX forward = VIX past
        else:
            shifted = vix_chg

        valid = pd.DataFrame({'btc': btc_ret, 'vix': shifted}).dropna()
        if len(valid) > 10:
            corr = valid['btc'].corr(valid['vix'])
        else:
            corr = np.nan
        lead_lag_results[pname][f'lag_{lag}'] = round(float(corr), 4) if not np.isnan(corr) else None
        if abs(lag) <= 3:
            print(f"  lag={lag:+d}: corr={corr:.4f}" if not np.isnan(corr) else f"  lag={lag:+d}: N/A")

# ============================================================
# PART F: VAR IMPULSE RESPONSE (BTC shock → VIX)
# ============================================================
print("\n" + "=" * 70)
print("PART F: VAR Impulse Response Functions")
print("=" * 70)

irf_results = {}
for pname in ['Full', 'Pre-ETF', 'Post-ETF']:
    pdata = period_data[pname]

    # VAR with BTC absolute return and VIX change
    var_df = pd.DataFrame({
        'BTC_absret': pdata['BTC_absret'],
        'VIX_chg': pdata['VIX_chg'],
    }).dropna()

    if len(var_df) < 30:
        irf_results[pname] = {'error': 'insufficient_data'}
        continue

    try:
        # Select lag order by AIC
        model = VAR(var_df)
        lag_order = model.select_order(maxlags=5)
        best_lag = lag_order.aic
        if best_lag == 0:
            best_lag = 1

        var_result = model.fit(best_lag)
        irf = var_result.irf(periods=10)

        # BTC shock → VIX response (impulse=BTC_absret, response=VIX_chg)
        # IRF matrix: irf.irfs[horizon, response_var, impulse_var]
        btc_idx = var_df.columns.get_loc('BTC_absret')
        vix_idx = var_df.columns.get_loc('VIX_chg')

        btc_to_vix_irf = [round(float(irf.irfs[h, vix_idx, btc_idx]), 6) for h in range(11)]
        vix_to_btc_irf = [round(float(irf.irfs[h, btc_idx, vix_idx]), 6) for h in range(11)]

        # Cumulative IRF
        btc_to_vix_cum = [round(float(sum(btc_to_vix_irf[:h+1])), 6) for h in range(11)]
        vix_to_btc_cum = [round(float(sum(vix_to_btc_irf[:h+1])), 6) for h in range(11)]

        irf_results[pname] = {
            'var_lag': int(best_lag),
            'n_obs': int(len(var_df)),
            'BTC_shock_to_VIX': {
                'irf': btc_to_vix_irf,
                'cumulative': btc_to_vix_cum,
            },
            'VIX_shock_to_BTC': {
                'irf': vix_to_btc_irf,
                'cumulative': vix_to_btc_cum,
            },
        }

        print(f"\n--- {pname} (VAR lag={best_lag}, n={len(var_df)}) ---")
        print(f"  BTC shock → VIX (cumulative at day 5): {btc_to_vix_cum[5]:.4f}")
        print(f"  BTC shock → VIX (cumulative at day 10): {btc_to_vix_cum[10]:.4f}")
        print(f"  VIX shock → BTC (cumulative at day 5): {vix_to_btc_cum[5]:.4f}")
        print(f"  VIX shock → BTC (cumulative at day 10): {vix_to_btc_cum[10]:.4f}")

    except Exception as e:
        irf_results[pname] = {'error': str(e)}
        print(f"\n--- {pname}: VAR error: {e}")

# ============================================================
# PART G: TARIFF CRISIS DEEP DIVE
# ============================================================
print("\n" + "=" * 70)
print("PART G: April 2026 Tariff Crisis Deep Dive")
print("=" * 70)

crisis_data = period_data['Tariff Crisis (2026)']
if len(crisis_data) > 5:
    # Day-by-day comparison in crisis week (March 31 - April 4)
    crisis_week = crisis_data.loc['2026-03-28':'2026-04-04']
    print("\nCrisis week day-by-day:")
    print(f"{'Date':<12} {'BTC_ret%':>10} {'SPY_ret%':>10} {'VIX':>8} {'dVIX':>8}")
    for idx, row in crisis_week.iterrows():
        print(f"{idx.date()!s:<12} {row['BTC']*100:>10.2f} {row['SPY']*100:>10.2f} "
              f"{row['VIX']:>8.1f} {row['VIX_chg']:>8.2f}")

    # March 2026 correlations
    mar_data = crisis_data.loc['2026-03-01':'2026-03-31']
    apr_data = crisis_data.loc['2026-04-01':'2026-04-04']

    crisis_deep_dive = {
        'march_2026': {
            'n_days': int(len(mar_data)),
            'btc_cum_return_pct': round(float(mar_data['BTC'].sum() * 100), 2),
            'spy_cum_return_pct': round(float(mar_data['SPY'].sum() * 100), 2),
            'vix_start': round(float(mar_data['VIX'].iloc[0]), 2) if len(mar_data) > 0 else None,
            'vix_end': round(float(mar_data['VIX'].iloc[-1]), 2) if len(mar_data) > 0 else None,
            'btc_spy_corr': round(float(mar_data['BTC'].corr(mar_data['SPY'])), 4) if len(mar_data) > 5 else None,
        },
        'april_2026_start': {
            'n_days': int(len(apr_data)),
            'btc_cum_return_pct': round(float(apr_data['BTC'].sum() * 100), 2) if len(apr_data) > 0 else None,
            'spy_cum_return_pct': round(float(apr_data['SPY'].sum() * 100), 2) if len(apr_data) > 0 else None,
            'btc_spy_corr': round(float(apr_data['BTC'].corr(apr_data['SPY'])), 4) if len(apr_data) > 5 else None,
        },
    }

    # Did BTC or VIX move first?
    # Check: on tariff announcement days, which asset showed larger initial reaction?
    # Look at the crisis week: did BTC drop before VIX spiked or simultaneously?
    if len(crisis_week) > 2:
        btc_first_move = crisis_week['BTC'].iloc[0] * 100
        spy_first_move = crisis_week['SPY'].iloc[0] * 100
        vix_first_move = crisis_week['VIX_chg'].iloc[0]

        crisis_deep_dive['first_day_reaction'] = {
            'btc_return_pct': round(float(btc_first_move), 2),
            'spy_return_pct': round(float(spy_first_move), 2),
            'vix_change': round(float(vix_first_move), 2),
        }

        # Who moved more (standardized by own vol)?
        btc_z = float(crisis_week['BTC'].iloc[0] / period_data['Post-ETF']['BTC'].std())
        spy_z = float(crisis_week['SPY'].iloc[0] / period_data['Post-ETF']['SPY'].std())
        crisis_deep_dive['first_day_z_scores'] = {
            'btc_z': round(btc_z, 2),
            'spy_z': round(spy_z, 2),
            'btc_moved_more': bool(abs(btc_z) > abs(spy_z)),
        }

        print(f"\nFirst crisis day z-scores: BTC={btc_z:.2f}, SPY={spy_z:.2f}")
        print(f"BTC moved more (standardized): {abs(btc_z) > abs(spy_z)}")
else:
    crisis_deep_dive = {'error': 'insufficient_crisis_data'}
    print("Insufficient crisis data for deep dive")

# ============================================================
# PART H: BTC AS RISK-ON INDICATOR
# ============================================================
print("\n" + "=" * 70)
print("PART H: BTC as Risk-On Indicator (Correlation Regime Analysis)")
print("=" * 70)

# Question: Is BTC still a diversifier or has it become risk-on?
# Metric: what fraction of time does rolling 60d corr(BTC,SPY) exceed 0.3?
risk_on_results = {}
for pname, (start, end) in PERIODS.items():
    mask = (rolling_corr_btc_spy.index >= start) & (rolling_corr_btc_spy.index <= end)
    rc = rolling_corr_btc_spy[mask].dropna()

    if len(rc) > 0:
        pct_above_03 = float((rc > 0.3).mean() * 100)
        pct_above_05 = float((rc > 0.5).mean() * 100)
        pct_negative = float((rc < 0).mean() * 100)

        risk_on_results[pname] = {
            'pct_corr_above_0.3': round(pct_above_03, 1),
            'pct_corr_above_0.5': round(pct_above_05, 1),
            'pct_corr_negative': round(pct_negative, 1),
            'mean_corr': round(float(rc.mean()), 4),
        }
        print(f"  {pname}: mean={rc.mean():.3f}, >0.3={pct_above_03:.1f}%, >0.5={pct_above_05:.1f}%, <0={pct_negative:.1f}%")

# ============================================================
# CHARTS
# ============================================================
print("\n" + "=" * 70)
print("Generating Charts...")
print("=" * 70)

# Chart 1: Rolling 60-day correlations
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

ax1 = axes[0]
ax1.plot(rolling_corr_btc_spy.index, rolling_corr_btc_spy, 'b-', alpha=0.8, label='BTC-SPY')
ax1.plot(rolling_corr_btc_gld.index, rolling_corr_btc_gld, 'orange', alpha=0.7, label='BTC-GLD')
ax1.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
ax1.axhline(y=0.3, color='red', linestyle=':', alpha=0.5, label='Risk-on threshold (0.3)')
ax1.axvline(x=pd.Timestamp('2024-01-10'), color='green', linestyle='--', alpha=0.7, label='BTC ETF launch')
ax1.axvline(x=pd.Timestamp('2026-04-02'), color='red', linestyle='--', alpha=0.7, label='Tariff crisis')
ax1.set_ylabel('Rolling 60d Correlation')
ax1.set_title('K855: BTC Rolling Correlations — ETF Era vs Pre-ETF')
ax1.legend(loc='upper left', fontsize=8)
ax1.set_ylim(-0.6, 0.8)
ax1.grid(True, alpha=0.3)

ax2 = axes[1]
ax2.plot(rolling_corr_btc_vix_chg.index, rolling_corr_btc_vix_chg, 'r-', alpha=0.8, label='BTC-dVIX')
ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
ax2.axvline(x=pd.Timestamp('2024-01-10'), color='green', linestyle='--', alpha=0.7, label='BTC ETF launch')
ax2.axvline(x=pd.Timestamp('2026-04-02'), color='red', linestyle='--', alpha=0.7, label='Tariff crisis')
ax2.set_ylabel('Rolling 60d Correlation')
ax2.set_xlabel('Date')
ax2.legend(loc='upper left', fontsize=8)
ax2.set_ylim(-0.6, 0.4)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
chart1_path = os.path.join(CHART_DIR, 'k855_rolling_correlations.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart 1 saved: {chart1_path}")

# Chart 2: Lead-lag cross-correlations by period
fig, ax = plt.subplots(figsize=(10, 6))
lags = list(range(-5, 6))
for pname in ['Full', 'Pre-ETF', 'Post-ETF', 'Tariff Crisis (2026)']:
    corrs = [lead_lag_results[pname].get(f'lag_{lag}', None) for lag in lags]
    corrs = [c if c is not None else np.nan for c in corrs]
    style = '-o' if pname != 'Tariff Crisis (2026)' else '-s'
    lw = 2.5 if pname == 'Post-ETF' else (2.5 if pname == 'Tariff Crisis (2026)' else 1.5)
    ax.plot(lags, corrs, style, label=pname, linewidth=lw, markersize=5)

ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
ax.set_xlabel('Lag (negative = BTC leads, positive = VIX leads)')
ax.set_ylabel('Cross-Correlation')
ax.set_title('K855: BTC Return vs VIX Change — Lead-Lag Cross-Correlation')
ax.legend()
ax.grid(True, alpha=0.3)
ax.set_xticks(lags)

plt.tight_layout()
chart2_path = os.path.join(CHART_DIR, 'k855_lead_lag_xcorr.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart 2 saved: {chart2_path}")

# Chart 3: IRF comparison pre vs post ETF
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
horizons = list(range(11))

for i, (direction, ylabel) in enumerate([('BTC_shock_to_VIX', 'VIX response to BTC shock'),
                                          ('VIX_shock_to_BTC', 'BTC response to VIX shock')]):
    ax = axes[i]
    for pname in ['Pre-ETF', 'Post-ETF']:
        if pname in irf_results and 'error' not in irf_results[pname]:
            cum_irf = irf_results[pname][direction]['cumulative']
            ax.plot(horizons, cum_irf, '-o', label=pname, markersize=4, linewidth=2)

    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('Horizon (days)')
    ax.set_ylabel(ylabel)
    ax.set_title(f'Cumulative IRF: {direction.replace("_", " ")}')
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.suptitle('K855: VAR Impulse Response — Pre-ETF vs Post-ETF', fontsize=13, y=1.02)
plt.tight_layout()
chart3_path = os.path.join(CHART_DIR, 'k855_irf_comparison.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart 3 saved: {chart3_path}")

# Chart 4: BTC risk-on transition
fig, ax = plt.subplots(figsize=(14, 5))
rc_filled = rolling_corr_btc_spy.dropna()
ax.fill_between(rc_filled.index, 0.3, rc_filled.where(rc_filled > 0.3), alpha=0.3, color='red', label='Risk-on (corr > 0.3)')
ax.fill_between(rc_filled.index, rc_filled.where(rc_filled < 0), 0, alpha=0.3, color='green', label='Diversifier (corr < 0)')
ax.plot(rc_filled.index, rc_filled, 'k-', alpha=0.6, linewidth=0.8)
ax.axvline(x=pd.Timestamp('2024-01-10'), color='blue', linestyle='--', alpha=0.8, linewidth=2, label='BTC ETF (Jan 2024)')
ax.axvline(x=pd.Timestamp('2026-04-02'), color='red', linestyle='--', alpha=0.8, linewidth=2, label='Tariff crisis')
ax.set_ylabel('60d Rolling Corr(BTC, SPY)')
ax.set_title('K855: BTC-SPY Correlation — Risk-On vs Diversifier Regimes')
ax.legend(loc='upper left', fontsize=9)
ax.grid(True, alpha=0.3)
ax.set_ylim(-0.6, 0.8)

plt.tight_layout()
chart4_path = os.path.join(CHART_DIR, 'k855_risk_on_transition.png')
plt.savefig(chart4_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart 4 saved: {chart4_path}")

# ============================================================
# SYNTHESIS & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SYNTHESIS")
print("=" * 70)

# Key findings
pre_btc_spy_mean = rolling_corr_results.get('Pre-ETF', {}).get('BTC_SPY', {}).get('mean', None)
post_btc_spy_mean = rolling_corr_results.get('Post-ETF', {}).get('BTC_SPY', {}).get('mean', None)

pre_granger_p = granger_results.get('Pre-ETF', {}).get('BTC_absret_to_VIX_chg', {}).get('aic_p_val', None)
post_granger_p = granger_results.get('Post-ETF', {}).get('BTC_absret_to_VIX_chg', {}).get('aic_p_val', None)

pre_risk_on = risk_on_results.get('Pre-ETF', {}).get('pct_corr_above_0.3', None)
post_risk_on = risk_on_results.get('Post-ETF', {}).get('pct_corr_above_0.3', None)

conclusions = []
if pre_btc_spy_mean is not None and post_btc_spy_mean is not None:
    corr_change = post_btc_spy_mean - pre_btc_spy_mean
    if abs(corr_change) > 0.1:
        conclusions.append(f"BTC-SPY correlation shifted significantly: {pre_btc_spy_mean:.3f} → {post_btc_spy_mean:.3f} (Δ={corr_change:+.3f})")
    else:
        conclusions.append(f"BTC-SPY correlation change modest: {pre_btc_spy_mean:.3f} → {post_btc_spy_mean:.3f} (Δ={corr_change:+.3f})")

if pre_granger_p is not None and post_granger_p is not None:
    if post_granger_p < 0.05 and pre_granger_p >= 0.05:
        conclusions.append("Crypto fear channel ACTIVATED post-ETF: BTC→VIX Granger became significant")
    elif post_granger_p < 0.05 and pre_granger_p < 0.05:
        conclusions.append(f"Crypto fear channel persistent: BTC→VIX Granger significant in both periods (pre p={pre_granger_p:.4f}, post p={post_granger_p:.4f})")
    elif post_granger_p >= 0.05 and pre_granger_p < 0.05:
        conclusions.append("Crypto fear channel WEAKENED post-ETF: BTC→VIX Granger lost significance")
    else:
        conclusions.append(f"Crypto fear channel weak in both periods (pre p={pre_granger_p:.4f}, post p={post_granger_p:.4f})")

if pre_risk_on is not None and post_risk_on is not None:
    if post_risk_on > pre_risk_on + 15:
        conclusions.append(f"BTC has become more risk-on: time above 0.3 corr increased {pre_risk_on:.1f}% → {post_risk_on:.1f}%")
    else:
        conclusions.append(f"BTC risk-on status mixed: {pre_risk_on:.1f}% → {post_risk_on:.1f}% of time above 0.3 corr")

# Fisher z significance
if fisher_z_result['BTC_SPY']['significant_at_005']:
    conclusions.append(f"Fisher z-test CONFIRMS structural break in BTC-SPY correlation (z={fisher_z_result['BTC_SPY']['z_stat']:.3f}, p={fisher_z_result['BTC_SPY']['p_val']:.4f})")
else:
    conclusions.append(f"Fisher z-test: NO significant structural break in BTC-SPY correlation (z={fisher_z_result['BTC_SPY']['z_stat']:.3f}, p={fisher_z_result['BTC_SPY']['p_val']:.4f})")

for c in conclusions:
    print(f"  • {c}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K855',
    'title': 'Crypto Fear Channel — 2026 Tariff Crisis Update',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_period': '2020-01 to 2026-04-04',
    'methodology': {
        'periods': {k: {'start': v[0], 'end': v[1]} for k, v in PERIODS.items()},
        'rolling_window': 60,
        'rv_window': 22,
        'granger_max_lag': 5,
        'granger_lag_selection': 'AIC',
        'var_max_lag': 5,
    },
    'references': [
        'K746b: Bitcoin-VIX bidirectional Granger (2015-2026)',
        'K639: BTC→SPY Granger, inverse leverage',
        'K565: BTC 5% allocation Harvey PASS, post-ETF correlation 0→0.35',
        'Corbet et al. (2020) JBF: Cryptocurrency reaction to FOMC',
        'Bouri et al. (2017) FRL: Bitcoin as hedge/diversifier',
    ],
    'descriptive_stats': desc_results,
    'rolling_correlations': rolling_corr_results,
    'fisher_z_tests': fisher_z_result,
    'granger_causality': granger_results,
    'asymmetric_granger': asymmetric_results,
    'lead_lag_crosscorr': lead_lag_results,
    'var_irf': irf_results,
    'tariff_crisis_deep_dive': crisis_deep_dive,
    'risk_on_analysis': risk_on_results,
    'conclusions': conclusions,
    'charts': [
        'k855_charts/k855_rolling_correlations.png',
        'k855_charts/k855_lead_lag_xcorr.png',
        'k855_charts/k855_irf_comparison.png',
        'k855_charts/k855_risk_on_transition.png',
    ],
    'limitations': [
        'BTC trades 24/7 but VIX/SPY only during market hours — alignment uses close-to-close',
        'Tariff crisis period very short (25 trading days) — limited statistical power',
        'Granger causality ≠ true causality; confounders (global risk appetite) possible',
        'Post-ETF period includes 2024-2026 only — may reflect specific market conditions not just ETF effect',
        'Rolling correlations use 60-day window — smooths high-frequency dynamics',
    ],
}

results_path = os.path.join(OUTPUT_DIR, 'k855_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved: {results_path}")
print(f"\nK855 complete. Charts in: {CHART_DIR}")
