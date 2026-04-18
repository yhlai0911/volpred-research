#!/usr/bin/env python3
"""
K401: Stablecoin Dynamics — Does Stablecoin Stress Predict Crypto and Equity Vol?
====================================================================================
[提出: User, 執行: Claude]

跳躍式探索：穩定幣是加密貨幣生態的基礎設施，當 USDT/USDC 偏離錨定價格，
意味著系統性壓力。本實驗探索穩定幣壓力是否能預測加密貨幣和股市波動率。

Data source: yfinance (real market data)
Assets: USDT-USD, USDC-USD, BTC-USD, ETH-USD, SPY, ^VIX
Period: 2019-01-01 to 2026-03-24

Methodology:
1. Stablecoin stress metrics (depeg magnitude, daily vol, USDT-USDC spread)
2. Granger causality: stablecoin stress → crypto vol
3. Event study: depeg events → crypto/equity response
4. Partial correlation: stablecoin stress → SPY RV | VIX
5. UST collapse case study (May 2022)

Limitations:
- yfinance stablecoin data may have quality issues (stale quotes, gaps)
- USDT-USD is an OTC/exchange-aggregated price, not a single venue
- Daily frequency only — intraday dynamics are much richer
- Survivorship bias: we don't observe failed stablecoins' full history via yfinance
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 80)
print("K401: Stablecoin Dynamics — Stress → Crypto & Equity Vol?")
print("=" * 80)
print(f"\nExperiment run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("Data source: yfinance (real market data)")

tickers = {
    'USDT': 'USDT-USD',
    'USDC': 'USDC-USD',
    'BTC': 'BTC-USD',
    'ETH': 'ETH-USD',
    'SPY': 'SPY',
    'VIX': '^VIX',
}

start_date = '2019-01-01'
end_date = '2026-03-24'

print(f"\nDownloading data: {start_date} to {end_date}")
print(f"Tickers: {list(tickers.values())}")

data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 0:
            data[name] = df['Close'].copy()
            print(f"  {name} ({ticker}): {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name} ({ticker}): NO DATA")
    except Exception as e:
        print(f"  {name} ({ticker}): ERROR - {e}")

# Combine into DataFrame
prices = pd.DataFrame(data)
print(f"\nCombined dataset: {len(prices)} trading days")
print(f"Date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Data quality check for stablecoins
print("\n" + "=" * 80)
print("DATA QUALITY CHECK — Stablecoin Prices")
print("=" * 80)
for sc in ['USDT', 'USDC']:
    if sc in prices.columns:
        p = prices[sc].dropna()
        print(f"\n{sc}:")
        print(f"  Observations: {len(p)}")
        print(f"  Mean: {p.mean():.6f}")
        print(f"  Std:  {p.std():.6f}")
        print(f"  Min:  {p.min():.6f} ({p.idxmin().strftime('%Y-%m-%d')})")
        print(f"  Max:  {p.max():.6f} ({p.idxmax().strftime('%Y-%m-%d')})")
        print(f"  NaN count: {prices[sc].isna().sum()}")
        # Days with > 0.5% deviation from 1.00
        deviations = (p - 1.0).abs()
        big_deviations = deviations[deviations > 0.005]
        print(f"  Days with >0.5% depeg: {len(big_deviations)}")
        if len(big_deviations) > 0:
            print(f"  Largest depegs:")
            for date, dev in big_deviations.nlargest(5).items():
                print(f"    {date.strftime('%Y-%m-%d')}: price={p.loc[date]:.4f}, deviation={dev:.4f} ({dev*100:.2f}%)")

# ============================================================
# 2. STABLECOIN STRESS METRICS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 2: STABLECOIN STRESS METRICS")
print("=" * 80)

# Fill forward for alignment (crypto trades 7 days, equity 5 days)
# We'll work with the intersection of available dates
df = prices.copy()

# Calculate stress metrics
stress = pd.DataFrame(index=df.index)

# 2a. Absolute depeg from $1.00
if 'USDT' in df.columns:
    stress['usdt_depeg'] = (df['USDT'] - 1.0).abs()
    stress['usdt_signed_depeg'] = df['USDT'] - 1.0  # positive = premium, negative = discount
if 'USDC' in df.columns:
    stress['usdc_depeg'] = (df['USDC'] - 1.0).abs()

# 2b. Stablecoin daily returns volatility (rolling 5-day)
if 'USDT' in df.columns:
    usdt_ret = df['USDT'].pct_change()
    stress['usdt_daily_ret'] = usdt_ret
    stress['usdt_vol_5d'] = usdt_ret.rolling(5).std() * np.sqrt(365)  # annualized
    stress['usdt_vol_20d'] = usdt_ret.rolling(20).std() * np.sqrt(365)

if 'USDC' in df.columns:
    usdc_ret = df['USDC'].pct_change()
    stress['usdc_daily_ret'] = usdc_ret
    stress['usdc_vol_5d'] = usdc_ret.rolling(5).std() * np.sqrt(365)

# 2c. USDT-USDC spread
if 'USDT' in df.columns and 'USDC' in df.columns:
    stress['usdt_usdc_spread'] = (df['USDT'] - df['USDC']).abs()
    stress['usdt_usdc_spread_bps'] = stress['usdt_usdc_spread'] * 10000  # in basis points

# 2d. Combined stress index (simple average of z-scored components)
stress_components = []
for col in ['usdt_depeg', 'usdc_depeg', 'usdt_vol_5d']:
    if col in stress.columns:
        s = stress[col].dropna()
        if s.std() > 0:
            stress_components.append(col)

if len(stress_components) >= 2:
    # Z-score each component (using expanding window to avoid look-ahead)
    z_scores = pd.DataFrame(index=stress.index)
    for col in stress_components:
        expanding_mean = stress[col].expanding(min_periods=60).mean()
        expanding_std = stress[col].expanding(min_periods=60).std()
        z_scores[col] = (stress[col] - expanding_mean) / expanding_std
    stress['combined_stress_z'] = z_scores[stress_components].mean(axis=1)

# Print summary stats
print("\nStress metric summary (full sample):")
for col in ['usdt_depeg', 'usdc_depeg', 'usdt_vol_5d', 'usdt_usdc_spread_bps', 'combined_stress_z']:
    if col in stress.columns:
        s = stress[col].dropna()
        print(f"  {col}:")
        print(f"    mean={s.mean():.6f}, median={s.median():.6f}, p95={s.quantile(0.95):.6f}, p99={s.quantile(0.99):.6f}")

# ============================================================
# 3. CRYPTO VOLATILITY MEASURES
# ============================================================
print("\n" + "=" * 80)
print("SECTION 3: CRYPTO & EQUITY VOLATILITY")
print("=" * 80)

vol = pd.DataFrame(index=df.index)

for asset in ['BTC', 'ETH', 'SPY']:
    if asset in df.columns:
        ret = df[asset].pct_change()
        vol[f'{asset}_ret'] = ret
        vol[f'{asset}_rv5'] = ret.rolling(5).std() * np.sqrt(252)  # 5-day RV
        vol[f'{asset}_rv20'] = ret.rolling(20).std() * np.sqrt(252)  # 20-day RV
        vol[f'{asset}_abs_ret'] = ret.abs()  # daily absolute return as vol proxy

if 'VIX' in df.columns:
    vol['VIX'] = df['VIX']

print("\nVolatility summary (annualized 20-day RV):")
for asset in ['BTC', 'ETH', 'SPY']:
    col = f'{asset}_rv20'
    if col in vol.columns:
        s = vol[col].dropna()
        print(f"  {asset}: mean={s.mean():.1%}, median={s.median():.1%}, max={s.max():.1%}")

# ============================================================
# 4. GRANGER CAUSALITY: STABLECOIN STRESS → CRYPTO VOL
# ============================================================
print("\n" + "=" * 80)
print("SECTION 4: GRANGER CAUSALITY — Stablecoin Stress → Crypto Vol?")
print("=" * 80)

def granger_f_test(y, x, max_lag=5):
    """
    Manual Granger causality test.
    H0: x does NOT Granger-cause y (restricted model is as good).
    Returns dict with F-stat and p-value for each lag.
    """
    results = {}
    combined = pd.DataFrame({'y': y, 'x': x}).dropna()
    if len(combined) < max_lag * 3 + 10:
        return results

    for lag in range(1, max_lag + 1):
        # Create lagged variables
        df_test = combined.copy()
        for i in range(1, lag + 1):
            df_test[f'y_lag{i}'] = df_test['y'].shift(i)
            df_test[f'x_lag{i}'] = df_test['x'].shift(i)
        df_test = df_test.dropna()

        if len(df_test) < lag * 2 + 10:
            continue

        y_vals = df_test['y'].values

        # Restricted model: y ~ y_lags only
        X_r = np.column_stack([df_test[f'y_lag{i}'].values for i in range(1, lag + 1)])
        X_r = np.column_stack([np.ones(len(y_vals)), X_r])

        # Unrestricted model: y ~ y_lags + x_lags
        X_u = np.column_stack([X_r] + [df_test[f'x_lag{i}'].values for i in range(1, lag + 1)])

        try:
            # OLS
            beta_r = np.linalg.lstsq(X_r, y_vals, rcond=None)[0]
            resid_r = y_vals - X_r @ beta_r
            ssr_r = np.sum(resid_r ** 2)

            beta_u = np.linalg.lstsq(X_u, y_vals, rcond=None)[0]
            resid_u = y_vals - X_u @ beta_u
            ssr_u = np.sum(resid_u ** 2)

            n = len(y_vals)
            k_r = X_r.shape[1]
            k_u = X_u.shape[1]
            df_num = k_u - k_r  # = lag
            df_den = n - k_u

            if ssr_u > 0 and df_den > 0:
                F = ((ssr_r - ssr_u) / df_num) / (ssr_u / df_den)
                p_val = 1 - stats.f.cdf(F, df_num, df_den)
                results[lag] = {'F': F, 'p': p_val, 'n': n}
        except Exception:
            continue

    return results

# Test combinations
stress_vars = ['usdt_depeg', 'usdt_vol_5d', 'combined_stress_z']
vol_vars = ['BTC_abs_ret', 'ETH_abs_ret', 'BTC_rv5']

# Merge stress and vol data
merged = pd.concat([stress, vol], axis=1).dropna(subset=['BTC_ret'], how='all')

print(f"\nMerged dataset: {len(merged)} observations")

granger_results = []
for sv in stress_vars:
    if sv not in merged.columns:
        continue
    for vv in vol_vars:
        if vv not in merged.columns:
            continue
        res = granger_f_test(merged[vv].dropna(), merged[sv].dropna(), max_lag=5)
        if res:
            best_lag = min(res, key=lambda k: res[k]['p'])
            print(f"\n  {sv} → {vv}:")
            for lag in sorted(res.keys()):
                sig = "***" if res[lag]['p'] < 0.01 else "**" if res[lag]['p'] < 0.05 else "*" if res[lag]['p'] < 0.1 else ""
                print(f"    lag={lag}: F={res[lag]['F']:.3f}, p={res[lag]['p']:.4f} {sig}  (n={res[lag]['n']})")
            granger_results.append({
                'stress_var': sv,
                'vol_var': vv,
                'best_lag': best_lag,
                'best_F': res[best_lag]['F'],
                'best_p': res[best_lag]['p'],
                'n': res[best_lag]['n'],
            })

# Reverse causality check: does crypto vol → stablecoin stress?
print("\n--- Reverse Causality Check ---")
print("Does crypto vol Granger-cause stablecoin stress?")
for vv in ['BTC_abs_ret', 'BTC_rv5']:
    if vv not in merged.columns:
        continue
    for sv in ['usdt_depeg', 'usdt_vol_5d']:
        if sv not in merged.columns:
            continue
        res = granger_f_test(merged[sv].dropna(), merged[vv].dropna(), max_lag=5)
        if res:
            best_lag = min(res, key=lambda k: res[k]['p'])
            sig_flag = "***" if res[best_lag]['p'] < 0.01 else "**" if res[best_lag]['p'] < 0.05 else "*" if res[best_lag]['p'] < 0.1 else ""
            print(f"  {vv} → {sv}: best lag={best_lag}, F={res[best_lag]['F']:.3f}, p={res[best_lag]['p']:.4f} {sig_flag}")

# ============================================================
# 5. EVENT STUDY: DEPEG EVENTS → CRYPTO RESPONSE
# ============================================================
print("\n" + "=" * 80)
print("SECTION 5: EVENT STUDY — Depeg Events → Crypto & Equity Response")
print("=" * 80)

# Identify depeg events
if 'usdt_depeg' in stress.columns:
    depeg_threshold_pct = 0.3  # 0.3% deviation (more lenient than 0.5% to get more events)
    depeg_threshold = depeg_threshold_pct / 100

    usdt_depeg = stress['usdt_depeg'].dropna()
    depeg_days = usdt_depeg[usdt_depeg > depeg_threshold]

    # Cluster nearby events (within 3 days)
    if len(depeg_days) > 0:
        event_dates = []
        sorted_dates = depeg_days.index.sort_values()
        current_cluster = [sorted_dates[0]]
        for d in sorted_dates[1:]:
            if (d - current_cluster[-1]).days <= 3:
                current_cluster.append(d)
            else:
                # Pick the day with max depeg in cluster
                cluster_data = depeg_days.loc[current_cluster]
                event_dates.append(cluster_data.idxmax())
                current_cluster = [d]
        cluster_data = depeg_days.loc[current_cluster]
        event_dates.append(cluster_data.idxmax())

        print(f"\nUSDT depeg events (>{depeg_threshold_pct}% deviation from $1.00):")
        print(f"Total event clusters: {len(event_dates)}")

        # For each event, measure crypto and equity response over next 1, 3, 5, 10 days
        event_results = []
        for edate in event_dates:
            depeg_val = stress.loc[edate, 'usdt_depeg']
            signed_depeg = stress.loc[edate, 'usdt_signed_depeg'] if 'usdt_signed_depeg' in stress.columns else np.nan
            direction = "premium" if signed_depeg > 0 else "discount"

            row = {
                'date': edate.strftime('%Y-%m-%d'),
                'usdt_price': df.loc[edate, 'USDT'] if 'USDT' in df.columns else np.nan,
                'depeg_pct': depeg_val * 100,
                'direction': direction,
            }

            for asset in ['BTC', 'ETH', 'SPY']:
                ret_col = f'{asset}_ret'
                if ret_col not in vol.columns:
                    continue
                for window in [1, 3, 5, 10]:
                    try:
                        loc_idx = vol.index.get_loc(edate)
                        future_rets = vol[ret_col].iloc[loc_idx + 1: loc_idx + 1 + window]
                        cum_ret = (1 + future_rets).prod() - 1
                        row[f'{asset}_{window}d'] = cum_ret
                    except (KeyError, IndexError):
                        row[f'{asset}_{window}d'] = np.nan

            event_results.append(row)

        event_df = pd.DataFrame(event_results)
        print(f"\n{'Date':<12} {'USDT':<8} {'Depeg%':<8} {'Dir':<9} {'BTC 1d':<10} {'BTC 5d':<10} {'ETH 5d':<10} {'SPY 5d':<10}")
        print("-" * 95)
        for _, row in event_df.iterrows():
            btc1 = f"{row.get('BTC_1d', np.nan):.2%}" if pd.notna(row.get('BTC_1d')) else "N/A"
            btc5 = f"{row.get('BTC_5d', np.nan):.2%}" if pd.notna(row.get('BTC_5d')) else "N/A"
            eth5 = f"{row.get('ETH_5d', np.nan):.2%}" if pd.notna(row.get('ETH_5d')) else "N/A"
            spy5 = f"{row.get('SPY_5d', np.nan):.2%}" if pd.notna(row.get('SPY_5d')) else "N/A"
            print(f"{row['date']:<12} {row.get('usdt_price', np.nan):<8.4f} {row['depeg_pct']:<8.3f} {row['direction']:<9} {btc1:<10} {btc5:<10} {eth5:<10} {spy5:<10}")

        # Average post-event returns
        print("\nAverage post-depeg returns:")
        for asset in ['BTC', 'ETH', 'SPY']:
            for window in [1, 3, 5, 10]:
                col = f'{asset}_{window}d'
                if col in event_df.columns:
                    vals = event_df[col].dropna()
                    if len(vals) > 2:
                        mean_r = vals.mean()
                        t_stat, p_val = stats.ttest_1samp(vals, 0)
                        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
                        print(f"  {asset} {window}d: mean={mean_r:.3%}, t={t_stat:.2f}, p={p_val:.3f} {sig} (n={len(vals)})")

        # Compare to unconditional returns
        print("\nUnconditional (non-event) average returns for comparison:")
        for asset in ['BTC', 'ETH', 'SPY']:
            ret_col = f'{asset}_ret'
            if ret_col in vol.columns:
                unc_mean = vol[ret_col].dropna().mean()
                unc_5d = unc_mean * 5
                print(f"  {asset}: daily={unc_mean:.4%}, 5d≈{unc_5d:.4%}")
    else:
        print(f"  No USDT depeg events found > {depeg_threshold_pct}%")
else:
    print("  USDT depeg data not available")

# Also check with USDC
if 'usdc_depeg' in stress.columns:
    usdc_depeg_days = stress['usdc_depeg'].dropna()
    usdc_big = usdc_depeg_days[usdc_depeg_days > 0.003]
    print(f"\nUSDC depeg events (>0.3%): {len(usdc_big)}")
    if len(usdc_big) > 0:
        print("  Top 5 USDC depeg days:")
        for date, val in usdc_big.nlargest(5).items():
            usdc_price = df.loc[date, 'USDC'] if 'USDC' in df.columns else np.nan
            print(f"    {date.strftime('%Y-%m-%d')}: USDC={usdc_price:.4f}, depeg={val*100:.3f}%")

# ============================================================
# 6. PARTIAL CORRELATION: STABLECOIN STRESS → SPY RV | VIX
# ============================================================
print("\n" + "=" * 80)
print("SECTION 6: PARTIAL CORRELATION — Stablecoin Stress → SPY Vol | VIX")
print("=" * 80)

def partial_corr(x, y, z):
    """Partial correlation between x and y, controlling for z."""
    combined = pd.DataFrame({'x': x, 'y': y, 'z': z}).dropna()
    if len(combined) < 30:
        return np.nan, np.nan, len(combined)

    # Regress x on z, get residuals
    z_vals = combined['z'].values
    x_vals = combined['x'].values
    y_vals = combined['y'].values

    Z = np.column_stack([np.ones(len(z_vals)), z_vals])

    beta_xz = np.linalg.lstsq(Z, x_vals, rcond=None)[0]
    resid_x = x_vals - Z @ beta_xz

    beta_yz = np.linalg.lstsq(Z, y_vals, rcond=None)[0]
    resid_y = y_vals - Z @ beta_yz

    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p, len(combined)

print("\nPartial r(stablecoin_stress, SPY_vol | VIX):")
print("Tests whether stablecoin stress has information about SPY vol BEYOND what VIX captures\n")

for stress_var in ['usdt_depeg', 'usdt_vol_5d', 'combined_stress_z']:
    if stress_var not in merged.columns:
        continue
    for vol_var in ['SPY_rv5', 'SPY_abs_ret']:
        if vol_var not in merged.columns or 'VIX' not in merged.columns:
            continue
        r, p, n = partial_corr(merged[stress_var], merged[vol_var], merged['VIX'])
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
        print(f"  partial r({stress_var}, {vol_var} | VIX) = {r:.4f}, p={p:.4f} {sig}  (n={n})")

# Also test: stablecoin stress → crypto vol after controlling for VIX
print("\nPartial r(stablecoin_stress, crypto_vol | VIX):")
for stress_var in ['usdt_depeg', 'usdt_vol_5d']:
    if stress_var not in merged.columns:
        continue
    for vol_var in ['BTC_rv5', 'BTC_abs_ret', 'ETH_abs_ret']:
        if vol_var not in merged.columns or 'VIX' not in merged.columns:
            continue
        r, p, n = partial_corr(merged[stress_var], merged[vol_var], merged['VIX'])
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
        print(f"  partial r({stress_var}, {vol_var} | VIX) = {r:.4f}, p={p:.4f} {sig}  (n={n})")

# ============================================================
# 7. UST COLLAPSE CASE STUDY (MAY 2022)
# ============================================================
print("\n" + "=" * 80)
print("SECTION 7: UST COLLAPSE CASE STUDY — May 2022")
print("=" * 80)
print("\nContext: TerraUSD (UST) lost its peg in May 2022, triggering a massive")
print("crypto crash. USDT also briefly depegged. This examines the spillover.\n")

# Focus on April-June 2022
case_start = '2022-04-01'
case_end = '2022-07-01'

case_df = df.loc[case_start:case_end].copy()
case_stress = stress.loc[case_start:case_end].copy()
case_vol = vol.loc[case_start:case_end].copy()

if len(case_df) > 0:
    print(f"Case study period: {case_start} to {case_end} ({len(case_df)} obs)\n")

    # Timeline
    print("Key dates and stablecoin prices:")
    key_dates = pd.date_range('2022-05-05', '2022-05-20', freq='D')
    print(f"{'Date':<12} {'USDT':<10} {'USDC':<10} {'BTC':<12} {'ETH':<10} {'SPY':<10} {'VIX':<8}")
    print("-" * 72)
    for d in key_dates:
        if d in case_df.index:
            row_vals = []
            for col in ['USDT', 'USDC', 'BTC', 'ETH', 'SPY', 'VIX']:
                if col in case_df.columns and pd.notna(case_df.loc[d, col]):
                    if col in ['USDT', 'USDC']:
                        row_vals.append(f"{case_df.loc[d, col]:.4f}")
                    elif col == 'VIX':
                        row_vals.append(f"{case_df.loc[d, col]:.1f}")
                    else:
                        row_vals.append(f"{case_df.loc[d, col]:,.0f}")
                else:
                    row_vals.append("N/A")
            print(f"{d.strftime('%Y-%m-%d'):<12} {row_vals[0]:<10} {row_vals[1]:<10} {row_vals[2]:<12} {row_vals[3]:<10} {row_vals[4]:<10} {row_vals[5]:<8}")

    # Pre/post crisis comparison
    pre_crisis = '2022-04-01'
    crisis_start_d = '2022-05-05'
    crisis_peak = '2022-05-12'
    post_crisis = '2022-06-15'

    print("\nPerformance around UST collapse:")
    for asset in ['BTC', 'ETH', 'SPY']:
        if asset in case_df.columns:
            try:
                p_pre = case_df.loc[:crisis_start_d, asset].iloc[-1]
                p_trough = case_df.loc[crisis_start_d:post_crisis, asset].min()
                p_post = case_df.loc[:post_crisis, asset].iloc[-1]
                drawdown = (p_trough - p_pre) / p_pre
                print(f"  {asset}: pre-crisis={p_pre:,.0f}, trough={p_trough:,.0f}, drawdown={drawdown:.1%}")
            except (KeyError, IndexError):
                pass

    # VIX response
    if 'VIX' in case_df.columns:
        try:
            vix_pre = case_df.loc[:crisis_start_d, 'VIX'].iloc[-1]
            vix_peak = case_df.loc[crisis_start_d:'2022-05-20', 'VIX'].max()
            print(f"  VIX: pre={vix_pre:.1f}, peak={vix_peak:.1f}, change=+{vix_peak-vix_pre:.1f}")
        except (KeyError, IndexError):
            pass

    # USDT stress during crisis
    if 'usdt_depeg' in case_stress.columns:
        crisis_stress = case_stress.loc[crisis_start_d:'2022-05-20', 'usdt_depeg']
        print(f"\n  USDT depeg during crisis: max={crisis_stress.max()*100:.3f}%, mean={crisis_stress.mean()*100:.3f}%")
else:
    print("  Insufficient data for May 2022 case study")

# ============================================================
# 8. ROLLING CORRELATION: STABLECOIN STRESS × CRYPTO VOL
# ============================================================
print("\n" + "=" * 80)
print("SECTION 8: ROLLING CORRELATION — Time-Varying Relationship")
print("=" * 80)

if 'usdt_depeg' in merged.columns and 'BTC_abs_ret' in merged.columns:
    rolling_window = 90  # 90-day rolling

    combined_roll = merged[['usdt_depeg', 'BTC_abs_ret']].dropna()
    if len(combined_roll) > rolling_window:
        roll_corr = combined_roll['usdt_depeg'].rolling(rolling_window).corr(combined_roll['BTC_abs_ret'])

        # Yearly summary
        print(f"\nRolling {rolling_window}-day correlation: USDT depeg × BTC |return|")
        yearly = roll_corr.groupby(roll_corr.index.year)
        for year, data in yearly:
            d = data.dropna()
            if len(d) > 0:
                print(f"  {year}: mean={d.mean():.3f}, min={d.min():.3f}, max={d.max():.3f}")

        print(f"\n  Full sample correlation:")
        r_full, p_full = stats.pearsonr(combined_roll['usdt_depeg'], combined_roll['BTC_abs_ret'])
        print(f"    Pearson r = {r_full:.4f}, p = {p_full:.4f}")
        r_sp, p_sp = stats.spearmanr(combined_roll['usdt_depeg'], combined_roll['BTC_abs_ret'])
        print(f"    Spearman rho = {r_sp:.4f}, p = {p_sp:.4f}")

# ============================================================
# 9. PREDICTIVE REGRESSION: NEXT-DAY CRYPTO VOL
# ============================================================
print("\n" + "=" * 80)
print("SECTION 9: PREDICTIVE REGRESSION — Today's Stablecoin Stress → Tomorrow's Crypto Vol")
print("=" * 80)

for target_asset in ['BTC', 'ETH']:
    abs_ret_col = f'{target_asset}_abs_ret'
    if abs_ret_col not in merged.columns:
        continue

    print(f"\n--- {target_asset} ---")

    # y = tomorrow's |return|
    # x = today's stablecoin stress + controls
    reg_df = pd.DataFrame({
        'y': merged[abs_ret_col].shift(-1),  # next day
        'y_lag': merged[abs_ret_col],  # today's vol (AR(1) control)
    })

    for sv in ['usdt_depeg', 'usdt_vol_5d', 'combined_stress_z']:
        if sv in merged.columns:
            reg_df[sv] = merged[sv]

    if 'VIX' in merged.columns:
        reg_df['VIX'] = merged['VIX']

    reg_df = reg_df.dropna()

    if len(reg_df) < 100:
        print(f"  Insufficient data (n={len(reg_df)})")
        continue

    print(f"  Sample: n={len(reg_df)}")

    # Model 1: y ~ y_lag (baseline)
    # Model 2: y ~ y_lag + stress
    # Model 3: y ~ y_lag + VIX + stress

    y = reg_df['y'].values

    # Baseline: AR(1)
    X_base = np.column_stack([np.ones(len(y)), reg_df['y_lag'].values])
    beta_base = np.linalg.lstsq(X_base, y, rcond=None)[0]
    resid_base = y - X_base @ beta_base
    r2_base = 1 - np.sum(resid_base**2) / np.sum((y - y.mean())**2)

    print(f"  Baseline AR(1): R²={r2_base:.4f}")

    for sv in ['usdt_depeg', 'usdt_vol_5d', 'combined_stress_z']:
        if sv not in reg_df.columns:
            continue

        # Model with stress
        X_stress = np.column_stack([X_base, reg_df[sv].values])
        beta_s = np.linalg.lstsq(X_stress, y, rcond=None)[0]
        resid_s = y - X_stress @ beta_s
        r2_stress = 1 - np.sum(resid_s**2) / np.sum((y - y.mean())**2)

        # t-stat for stress coefficient
        n_obs = len(y)
        k = X_stress.shape[1]
        s2 = np.sum(resid_s**2) / (n_obs - k)
        try:
            cov_matrix = s2 * np.linalg.inv(X_stress.T @ X_stress)
            se_stress = np.sqrt(cov_matrix[-1, -1])
            t_stress = beta_s[-1] / se_stress
            p_stress = 2 * (1 - stats.t.cdf(abs(t_stress), n_obs - k))
        except np.linalg.LinAlgError:
            t_stress = np.nan
            p_stress = np.nan

        delta_r2 = r2_stress - r2_base
        sig = "***" if p_stress < 0.01 else "**" if p_stress < 0.05 else "*" if p_stress < 0.1 else ""
        print(f"  + {sv}: R²={r2_stress:.4f} (ΔR²={delta_r2:.5f}), coef={beta_s[-1]:.6f}, t={t_stress:.3f}, p={p_stress:.4f} {sig}")

    # With VIX control
    if 'VIX' in reg_df.columns:
        X_vix = np.column_stack([X_base, reg_df['VIX'].values])
        beta_v = np.linalg.lstsq(X_vix, y, rcond=None)[0]
        resid_v = y - X_vix @ beta_v
        r2_vix = 1 - np.sum(resid_v**2) / np.sum((y - y.mean())**2)
        print(f"  + VIX only: R²={r2_vix:.4f}")

        for sv in ['usdt_depeg', 'usdt_vol_5d']:
            if sv not in reg_df.columns:
                continue
            X_both = np.column_stack([X_vix, reg_df[sv].values])
            beta_b = np.linalg.lstsq(X_both, y, rcond=None)[0]
            resid_b = y - X_both @ beta_b
            r2_both = 1 - np.sum(resid_b**2) / np.sum((y - y.mean())**2)

            n_obs = len(y)
            k = X_both.shape[1]
            s2 = np.sum(resid_b**2) / (n_obs - k)
            try:
                cov_matrix = s2 * np.linalg.inv(X_both.T @ X_both)
                se_s = np.sqrt(cov_matrix[-1, -1])
                t_s = beta_b[-1] / se_s
                p_s = 2 * (1 - stats.t.cdf(abs(t_s), n_obs - k))
            except np.linalg.LinAlgError:
                t_s = np.nan
                p_s = np.nan

            delta = r2_both - r2_vix
            sig = "***" if p_s < 0.01 else "**" if p_s < 0.05 else "*" if p_s < 0.1 else ""
            print(f"  + VIX + {sv}: R²={r2_both:.4f} (ΔR² over VIX={delta:.5f}), t_stress={t_s:.3f}, p={p_s:.4f} {sig}")

# ============================================================
# 10. TAIL ANALYSIS: STABLECOIN STRESS IN HIGH-VOL REGIMES
# ============================================================
print("\n" + "=" * 80)
print("SECTION 10: TAIL ANALYSIS — Stablecoin Stress in High vs Low Vol Regimes")
print("=" * 80)

if 'usdt_depeg' in merged.columns and 'BTC_rv20' in merged.columns:
    rv_col = 'BTC_rv20'
    stress_col = 'usdt_depeg'

    tail_df = merged[[rv_col, stress_col]].dropna()

    # Define regimes
    rv_75 = tail_df[rv_col].quantile(0.75)
    rv_25 = tail_df[rv_col].quantile(0.25)

    high_vol = tail_df[tail_df[rv_col] > rv_75]
    low_vol = tail_df[tail_df[rv_col] <= rv_25]

    print(f"\nBTC RV20 quartiles: Q1={rv_25:.1%}, Q3={rv_75:.1%}")
    print(f"High-vol regime (>Q3): n={len(high_vol)}, mean USDT depeg={high_vol[stress_col].mean()*100:.4f}%")
    print(f"Low-vol regime (≤Q1):  n={len(low_vol)}, mean USDT depeg={low_vol[stress_col].mean()*100:.4f}%")

    # Mann-Whitney U test (non-parametric)
    u_stat, u_p = stats.mannwhitneyu(high_vol[stress_col], low_vol[stress_col], alternative='greater')
    sig = "***" if u_p < 0.01 else "**" if u_p < 0.05 else "*" if u_p < 0.1 else ""
    print(f"Mann-Whitney U test (high > low): U={u_stat:.0f}, p={u_p:.4f} {sig}")

    # Correlation in tails only
    r_high, p_high = stats.spearmanr(high_vol[rv_col], high_vol[stress_col])
    r_low, p_low = stats.spearmanr(low_vol[rv_col], low_vol[stress_col])
    print(f"Spearman rho in high-vol regime: {r_high:.4f} (p={p_high:.4f})")
    print(f"Spearman rho in low-vol regime:  {r_low:.4f} (p={p_low:.4f})")

# ============================================================
# 11. CRYPTO-EQUITY SPILLOVER CONDITIONED ON STABLECOIN STRESS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 11: CRYPTO→EQUITY SPILLOVER — Does Stablecoin Stress Amplify It?")
print("=" * 80)

if all(c in merged.columns for c in ['BTC_ret', 'SPY_ret', 'usdt_depeg']):
    # Split sample: high stress vs low stress
    spill_df = merged[['BTC_ret', 'SPY_ret', 'usdt_depeg']].dropna()

    stress_median = spill_df['usdt_depeg'].median()
    stress_p90 = spill_df['usdt_depeg'].quantile(0.90)

    low_stress_mask = spill_df['usdt_depeg'] <= stress_median
    high_stress_mask = spill_df['usdt_depeg'] > stress_p90

    # BTC-SPY correlation in different stress regimes
    r_low, p_low = stats.pearsonr(spill_df.loc[low_stress_mask, 'BTC_ret'],
                                    spill_df.loc[low_stress_mask, 'SPY_ret'])
    r_high, p_high = stats.pearsonr(spill_df.loc[high_stress_mask, 'BTC_ret'],
                                     spill_df.loc[high_stress_mask, 'SPY_ret'])

    print(f"\nBTC-SPY daily return correlation:")
    print(f"  Low stablecoin stress (≤ median):  r={r_low:.4f}, p={p_low:.4f} (n={low_stress_mask.sum()})")
    print(f"  High stablecoin stress (> p90):    r={r_high:.4f}, p={p_high:.4f} (n={high_stress_mask.sum()})")
    print(f"  Difference: {r_high - r_low:+.4f}")

    # Fisher z-test for difference in correlations
    def fisher_z_test(r1, n1, r2, n2):
        z1 = 0.5 * np.log((1 + r1) / (1 - r1))
        z2 = 0.5 * np.log((1 + r2) / (1 - r2))
        se = np.sqrt(1/(n1-3) + 1/(n2-3))
        z_diff = (z1 - z2) / se
        p = 2 * (1 - stats.norm.cdf(abs(z_diff)))
        return z_diff, p

    z_diff, z_p = fisher_z_test(r_high, high_stress_mask.sum(), r_low, low_stress_mask.sum())
    sig = "***" if z_p < 0.01 else "**" if z_p < 0.05 else "*" if z_p < 0.1 else ""
    print(f"  Fisher z-test for difference: z={z_diff:.3f}, p={z_p:.4f} {sig}")

# ============================================================
# 12. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 80)
print("SECTION 12: SUMMARY & CONCLUSIONS")
print("=" * 80)

print("""
K401 STABLECOIN DYNAMICS — SUMMARY
===================================

This experiment examined whether stablecoin stress (USDT/USDC depeg, volatility,
and spread) can predict crypto and equity market volatility.

KEY FINDINGS:
""")

# Collect key results
print("1. DATA QUALITY:")
if 'USDT' in prices.columns:
    usdt = prices['USDT'].dropna()
    print(f"   - USDT-USD: {len(usdt)} obs, mean={usdt.mean():.4f}, std={usdt.std():.4f}")
    print(f"   - USDT data from yfinance has known limitations (stale quotes, gaps)")

print("\n2. GRANGER CAUSALITY:")
if granger_results:
    for gr in granger_results:
        sig = "***" if gr['best_p'] < 0.01 else "**" if gr['best_p'] < 0.05 else "*" if gr['best_p'] < 0.1 else ""
        print(f"   - {gr['stress_var']} → {gr['vol_var']}: F={gr['best_F']:.2f}, p={gr['best_p']:.4f} {sig}")
else:
    print("   - No Granger results available")

print("\n3. PREDICTIVE POWER:")
print("   - See Section 9 for ΔR² values (incremental R² over AR(1) and VIX)")

print("\n4. LIMITATIONS:")
print("   - yfinance stablecoin data may miss intraday depegs (daily close only)")
print("   - USDT/USDC on yfinance aggregates across exchanges (no single-venue precision)")
print("   - Crypto trades 24/7 but SPY only 5 days/week → date alignment issues")
print("   - Sample period includes only one major depeg event (UST May 2022)")
print("   - Cannot observe UST (TerraUSD) directly as it no longer trades normally")
print("   - Harvey (2016) t>3.0 threshold should be applied for novel factor claims")
print("   - Daily frequency misses important intraday stress dynamics")

# Save results
results = {
    'experiment': 'K401',
    'title': 'Stablecoin Dynamics — Stress → Crypto & Equity Vol',
    'run_date': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'period': f'{start_date} to {end_date}',
    'granger_results': granger_results,
}

results_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a23ccdeb/experiments/k401_stablecoin_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to: {results_path}")
print("\n" + "=" * 80)
print("K401 EXPERIMENT COMPLETE")
print("=" * 80)
