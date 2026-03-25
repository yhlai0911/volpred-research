#!/usr/bin/env python3
"""
K348: Credit Spread as Volatility Signal — Does Bond Market Stress Predict Equity Vol?
======================================================================================
跳躍式探索：信用市場 → 股市波動率

問題：債券市場的信用利差是否能預測股市波動率？
      信用利差變化是否領先 VIX / realized vol？

Data sources: yfinance (HYG, LQD, TLT, SPY, ^VIX)
Period: 2007-2024 (covers GFC, COVID, rate hikes)

Methodology:
1. Credit spread proxies:
   - TLT_ret - HYG_ret (when spread widens, credit risk rises)
   - HYG/LQD ratio (high yield vs investment grade relative)
2. Predictive analysis:
   - Partial corr(credit_spread_change, future_SPY_RV | VIX)
   - Lead-lag cross-correlation
   - Granger causality (VAR framework)
3. Credit spread regime analysis:
   - Wide spread (>80th pctl) → higher equity vol?
   - Spread narrowing (complacency) → future vol spike?
4. Credit spread vs VIX: which leads?
5. Portfolio implications: reduce equity when spreads widen?

[提出: 用戶 (跳躍式探索), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K348: Credit Spread as Volatility Signal")
print("Does Bond Market Stress Predict Equity Vol?")
print("=" * 70)

tickers = {
    'HYG': 'iShares High Yield Corporate Bond ETF',
    'LQD': 'iShares Investment Grade Corporate Bond ETF',
    'TLT': 'iShares 20+ Year Treasury Bond ETF',
    'SPY': 'S&P 500 ETF',
    '^VIX': 'CBOE VIX Index',
}

print("\n[1] Downloading data 2007-2024...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2007-01-01', end='2024-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Align all series to common dates
common_idx = data['HYG'].index
for k in data:
    common_idx = common_idx.intersection(data[k].index)
print(f"\n  Common trading days: {len(common_idx)}")
print(f"  Period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

prices = pd.DataFrame({k: data[k].reindex(common_idx) for k in data})
prices.columns = ['HYG', 'LQD', 'TLT', 'SPY', 'VIX']

# ============================================================
# 2. Construct Credit Spread Proxies
# ============================================================
print("\n" + "=" * 70)
print("[2] Constructing Credit Spread Proxies")
print("=" * 70)

# Returns
ret = prices[['HYG', 'LQD', 'TLT', 'SPY']].pct_change().dropna()
vix = prices['VIX'].reindex(ret.index)

# Proxy 1: Credit Spread via return differential
# When HYG underperforms TLT → credit stress rising
# spread_return = TLT_ret - HYG_ret  (positive = stress increasing)
ret['spread_ret'] = ret['TLT'] - ret['HYG']

# Proxy 2: Cumulative credit spread level (rolling 22-day sum of spread returns)
ret['spread_level_22d'] = ret['spread_ret'].rolling(22).sum()

# Proxy 3: HYG/LQD ratio (when HY underperforms IG → stress)
# Lower ratio = more stress
prices['HYG_LQD'] = prices['HYG'] / prices['LQD']
hyg_lqd_ret = prices['HYG_LQD'].pct_change().reindex(ret.index)
ret['hyg_lqd_ret'] = hyg_lqd_ret

# Proxy 4: HYG/TLT ratio change (direct credit risk premium)
prices['HYG_TLT'] = prices['HYG'] / prices['TLT']
hyg_tlt_ret = prices['HYG_TLT'].pct_change().reindex(ret.index)
ret['hyg_tlt_ret'] = hyg_tlt_ret

# SPY Realized Vol (22-day rolling)
ret['SPY_RV_22d'] = ret['SPY'].rolling(22).std() * np.sqrt(252) * 100  # annualized %
# Future realized vol (22-day forward)
ret['SPY_RV_22d_fwd'] = ret['SPY'].rolling(22).std().shift(-22) * np.sqrt(252) * 100

# VIX level
ret['VIX'] = vix

# Drop NaN
df = ret.dropna(subset=['SPY_RV_22d', 'SPY_RV_22d_fwd', 'spread_level_22d', 'VIX']).copy()
print(f"\n  Analysis sample: {len(df)} observations")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

print(f"\n  Credit spread proxy stats:")
print(f"    spread_ret (TLT-HYG daily):  mean={df['spread_ret'].mean()*100:.4f}%, "
      f"std={df['spread_ret'].std()*100:.4f}%")
print(f"    spread_level_22d:            mean={df['spread_level_22d'].mean()*100:.2f}%, "
      f"std={df['spread_level_22d'].std()*100:.2f}%")
print(f"    HYG/LQD daily return:        mean={df['hyg_lqd_ret'].mean()*100:.4f}%, "
      f"std={df['hyg_lqd_ret'].std()*100:.4f}%")

# ============================================================
# 3. Contemporaneous Relationships
# ============================================================
print("\n" + "=" * 70)
print("[3] Contemporaneous Relationships")
print("=" * 70)

# 3a. Correlation: credit spread vs current SPY RV
corr_spread_rv, p_spread_rv = stats.pearsonr(df['spread_level_22d'], df['SPY_RV_22d'])
print(f"\n  corr(22d_spread_level, SPY_RV_22d) = {corr_spread_rv:.4f} (p={p_spread_rv:.2e})")

# 3b. Correlation: VIX vs SPY RV
corr_vix_rv, p_vix_rv = stats.pearsonr(df['VIX'], df['SPY_RV_22d'])
print(f"  corr(VIX, SPY_RV_22d)               = {corr_vix_rv:.4f} (p={p_vix_rv:.2e})")

# 3c. Correlation: credit spread vs VIX
corr_spread_vix, p_spread_vix = stats.pearsonr(df['spread_level_22d'], df['VIX'])
print(f"  corr(22d_spread_level, VIX)          = {corr_spread_vix:.4f} (p={p_spread_vix:.2e})")

# 3d. Daily: spread_ret vs VIX change
df['VIX_change'] = df['VIX'].pct_change()
mask_vix = df['VIX_change'].notna()
corr_daily, p_daily = stats.pearsonr(df.loc[mask_vix, 'spread_ret'], df.loc[mask_vix, 'VIX_change'])
print(f"  corr(spread_ret_daily, VIX_change)   = {corr_daily:.4f} (p={p_daily:.2e})")

# ============================================================
# 4. Predictive Analysis: Does Credit Spread Predict Future Vol?
# ============================================================
print("\n" + "=" * 70)
print("[4] Predictive Analysis: Credit Spread → Future SPY Vol?")
print("=" * 70)

# 4a. Simple correlation: credit spread level → future RV
corr_pred, p_pred = stats.pearsonr(df['spread_level_22d'], df['SPY_RV_22d_fwd'])
print(f"\n  Simple corr(spread_level_22d, future_RV_22d) = {corr_pred:.4f} (p={p_pred:.2e})")

# 4b. Partial correlation controlling for VIX
# partial_r(X, Y | Z) = (r_XY - r_XZ * r_YZ) / sqrt((1-r_XZ^2)(1-r_YZ^2))
r_xy = corr_pred  # spread vs future_rv
r_xz, _ = stats.pearsonr(df['spread_level_22d'], df['VIX'])
r_yz, _ = stats.pearsonr(df['SPY_RV_22d_fwd'], df['VIX'])
partial_r = (r_xy - r_xz * r_yz) / np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
# t-test for partial correlation
n = len(df)
t_partial = partial_r * np.sqrt((n - 3) / (1 - partial_r**2))
p_partial = 2 * (1 - stats.t.cdf(abs(t_partial), n - 3))
print(f"  Partial corr(spread, future_RV | VIX)        = {partial_r:.4f} (t={t_partial:.2f}, p={p_partial:.2e})")

# 4c. Multiple horizons
print(f"\n  Lead-lag analysis (credit spread level → future SPY RV):")
print(f"  {'Horizon':>10s}  {'r':>8s}  {'partial_r|VIX':>14s}  {'t-stat':>8s}  {'p-value':>10s}")
print(f"  {'-'*55}")

horizons = [5, 10, 22, 44, 66]  # 1w, 2w, 1m, 2m, 3m
horizon_results = {}
for h in horizons:
    fwd_rv = ret['SPY'].rolling(h).std().shift(-h) * np.sqrt(252) * 100
    fwd_rv = fwd_rv.reindex(df.index)
    mask = fwd_rv.notna()

    if mask.sum() < 50:
        continue

    r_simple, _ = stats.pearsonr(df.loc[mask, 'spread_level_22d'], fwd_rv[mask])

    # Partial correlation
    r_xz2, _ = stats.pearsonr(df.loc[mask, 'spread_level_22d'], df.loc[mask, 'VIX'])
    r_yz2, _ = stats.pearsonr(fwd_rv[mask], df.loc[mask, 'VIX'])
    pr = (r_simple - r_xz2 * r_yz2) / np.sqrt((1 - r_xz2**2) * (1 - r_yz2**2))
    n2 = mask.sum()
    t2 = pr * np.sqrt((n2 - 3) / (1 - pr**2))
    p2 = 2 * (1 - stats.t.cdf(abs(t2), n2 - 3))

    horizon_results[h] = {'r': r_simple, 'partial_r': pr, 't': t2, 'p': p2, 'n': n2}
    sig = "***" if p2 < 0.001 else "**" if p2 < 0.01 else "*" if p2 < 0.05 else ""
    print(f"  {h:>5d}d     {r_simple:>+.4f}  {pr:>+.4f}         {t2:>+.2f}     {p2:>.2e} {sig}")

# 4d. HYG/LQD ratio as predictor
print(f"\n  HYG/LQD ratio change as predictor:")
# 22-day cumulative HYG/LQD underperformance
df['hyg_lqd_22d'] = df['hyg_lqd_ret'].rolling(22).sum()
mask2 = df['hyg_lqd_22d'].notna() & df['SPY_RV_22d_fwd'].notna()
if mask2.sum() > 50:
    r_hyglqd, p_hyglqd = stats.pearsonr(df.loc[mask2, 'hyg_lqd_22d'], df.loc[mask2, 'SPY_RV_22d_fwd'])
    print(f"  corr(HYG/LQD_22d_change, future_RV_22d) = {r_hyglqd:.4f} (p={p_hyglqd:.2e})")

# ============================================================
# 5. Granger Causality: Credit Spread ⇄ VIX
# ============================================================
print("\n" + "=" * 70)
print("[5] Granger Causality: Credit Spread ⇄ VIX / Equity Vol")
print("=" * 70)

# Manual Granger causality test using OLS
# H0: X does not Granger-cause Y
# Compare: Y_t = c + sum(a_i * Y_{t-i}) vs Y_t = c + sum(a_i * Y_{t-i}) + sum(b_i * X_{t-i})
# F-test on the additional X lags

def granger_test(y_series, x_series, maxlag=5):
    """Manual Granger causality test via F-test."""
    y = y_series.values
    x = x_series.values
    n = len(y)

    results = {}
    for lag in range(1, maxlag + 1):
        # Build matrices
        Y = y[lag:]
        n_obs = len(Y)

        # Restricted model: Y_t = c + Y_{t-1} + ... + Y_{t-lag}
        X_restricted = np.ones((n_obs, lag + 1))
        for i in range(lag):
            X_restricted[:, i + 1] = y[lag - 1 - i:n - 1 - i]

        # Unrestricted model: add X lags
        X_unrestricted = np.ones((n_obs, 2 * lag + 1))
        for i in range(lag):
            X_unrestricted[:, i + 1] = y[lag - 1 - i:n - 1 - i]
            X_unrestricted[:, lag + 1 + i] = x[lag - 1 - i:n - 1 - i]

        # OLS
        try:
            beta_r = np.linalg.lstsq(X_restricted, Y, rcond=None)[0]
            resid_r = Y - X_restricted @ beta_r
            ssr_r = np.sum(resid_r**2)

            beta_u = np.linalg.lstsq(X_unrestricted, Y, rcond=None)[0]
            resid_u = Y - X_unrestricted @ beta_u
            ssr_u = np.sum(resid_u**2)

            # F-test
            q = lag  # number of restrictions
            k = 2 * lag + 1  # params in unrestricted
            f_stat = ((ssr_r - ssr_u) / q) / (ssr_u / (n_obs - k))
            p_value = 1 - stats.f.cdf(f_stat, q, n_obs - k)

            results[lag] = {'F': f_stat, 'p': p_value, 'n': n_obs}
        except Exception:
            results[lag] = {'F': np.nan, 'p': np.nan, 'n': n_obs}

    return results

# Prepare weekly data to reduce noise (avoid overlapping daily issues)
weekly = df[['spread_ret', 'VIX']].resample('W-FRI').agg({
    'spread_ret': 'sum',
    'VIX': 'last'
}).dropna()
weekly['VIX_change'] = weekly['VIX'].pct_change()
weekly['spread_ret_std'] = df['spread_ret'].resample('W-FRI').std()
weekly = weekly.dropna()

# Also compute weekly SPY RV
weekly_spy_ret = ret['SPY'].resample('W-FRI').agg(lambda x: x.std() * np.sqrt(252) * 100)
weekly['SPY_RV'] = weekly_spy_ret.reindex(weekly.index)
weekly = weekly.dropna()

print(f"\n  Weekly sample: {len(weekly)} weeks")

# Test 1: Credit spread → VIX
print(f"\n  [5a] Credit Spread → VIX change (Granger causality):")
gc1 = granger_test(weekly['VIX_change'], weekly['spread_ret'], maxlag=4)
print(f"  {'Lag':>5s}  {'F-stat':>8s}  {'p-value':>10s}  {'Significant':>12s}")
for lag, res in gc1.items():
    sig = "YES ***" if res['p'] < 0.001 else "YES **" if res['p'] < 0.01 else "YES *" if res['p'] < 0.05 else "no"
    print(f"  {lag:>5d}  {res['F']:>8.2f}  {res['p']:>10.4f}  {sig:>12s}")

# Test 2: VIX → Credit spread
print(f"\n  [5b] VIX change → Credit Spread (Granger causality):")
gc2 = granger_test(weekly['spread_ret'], weekly['VIX_change'], maxlag=4)
print(f"  {'Lag':>5s}  {'F-stat':>8s}  {'p-value':>10s}  {'Significant':>12s}")
for lag, res in gc2.items():
    sig = "YES ***" if res['p'] < 0.001 else "YES **" if res['p'] < 0.01 else "YES *" if res['p'] < 0.05 else "no"
    print(f"  {lag:>5d}  {res['F']:>8.2f}  {res['p']:>10.4f}  {sig:>12s}")

# Test 3: Credit spread → SPY RV
print(f"\n  [5c] Credit Spread → SPY Weekly RV (Granger causality):")
gc3 = granger_test(weekly['SPY_RV'], weekly['spread_ret'], maxlag=4)
print(f"  {'Lag':>5s}  {'F-stat':>8s}  {'p-value':>10s}  {'Significant':>12s}")
for lag, res in gc3.items():
    sig = "YES ***" if res['p'] < 0.001 else "YES **" if res['p'] < 0.01 else "YES *" if res['p'] < 0.05 else "no"
    print(f"  {lag:>5d}  {res['F']:>8.2f}  {res['p']:>10.4f}  {sig:>12s}")

# ============================================================
# 6. Credit Spread Regime Analysis
# ============================================================
print("\n" + "=" * 70)
print("[6] Credit Spread Regime Analysis")
print("=" * 70)

# Define regimes based on spread level percentiles
pctls = [20, 50, 80]
thresholds = np.percentile(df['spread_level_22d'], pctls)

df['spread_regime'] = pd.cut(df['spread_level_22d'],
                              bins=[-np.inf, thresholds[0], thresholds[1], thresholds[2], np.inf],
                              labels=['Narrow(<20%)', 'Normal(20-50%)', 'Moderate(50-80%)', 'Wide(>80%)'])

print(f"\n  Spread Level Percentile Thresholds:")
for p, t in zip(pctls, thresholds):
    print(f"    {p}th percentile: {t*100:.2f}%")

print(f"\n  {'Regime':<20s}  {'N':>6s}  {'Mean RV':>8s}  {'Median RV':>10s}  {'Mean Fwd RV':>12s}  {'VIX':>6s}")
print(f"  {'-'*70}")
for regime in ['Narrow(<20%)', 'Normal(20-50%)', 'Moderate(50-80%)', 'Wide(>80%)']:
    mask = df['spread_regime'] == regime
    if mask.sum() == 0:
        continue
    rv_mean = df.loc[mask, 'SPY_RV_22d'].mean()
    rv_median = df.loc[mask, 'SPY_RV_22d'].median()
    fwd_mask = mask & df['SPY_RV_22d_fwd'].notna()
    fwd_rv = df.loc[fwd_mask, 'SPY_RV_22d_fwd'].mean() if fwd_mask.sum() > 0 else np.nan
    vix_mean = df.loc[mask, 'VIX'].mean()
    print(f"  {regime:<20s}  {mask.sum():>6d}  {rv_mean:>8.2f}%  {rv_median:>10.2f}%  {fwd_rv:>12.2f}%  {vix_mean:>6.1f}")

# Test: Wide spread → higher future vol vs Narrow
wide_mask = df['spread_regime'] == 'Wide(>80%)'
narrow_mask = df['spread_regime'] == 'Narrow(<20%)'
fwd_wide = df.loc[wide_mask & df['SPY_RV_22d_fwd'].notna(), 'SPY_RV_22d_fwd']
fwd_narrow = df.loc[narrow_mask & df['SPY_RV_22d_fwd'].notna(), 'SPY_RV_22d_fwd']

if len(fwd_wide) > 10 and len(fwd_narrow) > 10:
    t_regime, p_regime = stats.ttest_ind(fwd_wide, fwd_narrow)
    print(f"\n  t-test (Wide vs Narrow future RV): t={t_regime:.2f}, p={p_regime:.2e}")
    print(f"    Wide spread: mean future RV = {fwd_wide.mean():.2f}%, n={len(fwd_wide)}")
    print(f"    Narrow spread: mean future RV = {fwd_narrow.mean():.2f}%, n={len(fwd_narrow)}")

# 6b. Complacency detection: rapid narrowing → future spike
print(f"\n  [6b] Complacency Detection: Rapid Spread Narrowing → Future Vol Spike")
df['spread_change_5d'] = df['spread_level_22d'].diff(5)
# Rapid narrowing = large negative change in spread level
narrow_fast = df['spread_change_5d'] < df['spread_change_5d'].quantile(0.10)
not_narrowing = (df['spread_change_5d'] > df['spread_change_5d'].quantile(0.40)) & \
                (df['spread_change_5d'] < df['spread_change_5d'].quantile(0.60))

fwd_narrow_fast = df.loc[narrow_fast & df['SPY_RV_22d_fwd'].notna(), 'SPY_RV_22d_fwd']
fwd_normal = df.loc[not_narrowing & df['SPY_RV_22d_fwd'].notna(), 'SPY_RV_22d_fwd']

if len(fwd_narrow_fast) > 10 and len(fwd_normal) > 10:
    t_comp, p_comp = stats.ttest_ind(fwd_narrow_fast, fwd_normal)
    print(f"  Rapid narrowing (bottom 10%): mean future RV = {fwd_narrow_fast.mean():.2f}%, n={len(fwd_narrow_fast)}")
    print(f"  Normal change (40-60%):       mean future RV = {fwd_normal.mean():.2f}%, n={len(fwd_normal)}")
    print(f"  t-test: t={t_comp:.2f}, p={p_comp:.2e}")

# ============================================================
# 7. Credit Spread vs VIX: Which Leads?
# ============================================================
print("\n" + "=" * 70)
print("[7] Lead-Lag Analysis: Credit Spread vs VIX")
print("=" * 70)

# Cross-correlation using shift (clean approach)
print(f"  {'Lag k':>8s}  {'r(spread, VIX_chg)':>20s}  {'Meaning':>30s}")
print(f"  {'-'*62}")
cc_clean = {}
for k in range(-5, 6):
    shifted_vix = df['VIX_change'].shift(-k)
    mask_both = df['spread_ret'].notna() & shifted_vix.notna()
    if mask_both.sum() > 100:
        r_val, p_val = stats.pearsonr(df.loc[mask_both, 'spread_ret'], shifted_vix[mask_both])
        cc_clean[k] = {'r': r_val, 'p': p_val}

        if k < 0:
            meaning = f"VIX leads spread by {-k}d"
        elif k > 0:
            meaning = f"Spread leads VIX by {k}d"
        else:
            meaning = "Same day"

        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        print(f"  {k:>+8d}  {r_val:>+20.4f}  {meaning:>30s} {sig}")

# Find the peak
if cc_clean:
    peak_lag = max(cc_clean, key=lambda k: abs(cc_clean[k]['r']))
    print(f"\n  Peak cross-correlation at lag={peak_lag}: r={cc_clean[peak_lag]['r']:.4f}")
    if peak_lag < 0:
        print(f"  → VIX leads credit spread by {-peak_lag} day(s)")
    elif peak_lag > 0:
        print(f"  → Credit spread leads VIX by {peak_lag} day(s)")
    else:
        print(f"  → Contemporaneous (same day)")

# ============================================================
# 8. Incremental R²: Does Credit Spread Add to VIX?
# ============================================================
print("\n" + "=" * 70)
print("[8] Incremental R²: Credit Spread Beyond VIX?")
print("=" * 70)

# OLS regression: future_RV = a + b1*VIX + b2*spread_level
from numpy.linalg import lstsq

mask_reg = df['SPY_RV_22d_fwd'].notna() & df['spread_level_22d'].notna() & df['VIX'].notna()
Y = df.loc[mask_reg, 'SPY_RV_22d_fwd'].values
X_vix = np.column_stack([np.ones(mask_reg.sum()), df.loc[mask_reg, 'VIX'].values])
X_both = np.column_stack([np.ones(mask_reg.sum()),
                          df.loc[mask_reg, 'VIX'].values,
                          df.loc[mask_reg, 'spread_level_22d'].values])

# Model 1: VIX only
beta1 = lstsq(X_vix, Y, rcond=None)[0]
resid1 = Y - X_vix @ beta1
r2_vix = 1 - np.sum(resid1**2) / np.sum((Y - Y.mean())**2)

# Model 2: VIX + Credit Spread
beta2 = lstsq(X_both, Y, rcond=None)[0]
resid2 = Y - X_both @ beta2
r2_both = 1 - np.sum(resid2**2) / np.sum((Y - Y.mean())**2)

delta_r2 = r2_both - r2_vix

# F-test for incremental R²
n_reg = len(Y)
f_incr = (np.sum(resid1**2) - np.sum(resid2**2)) / (np.sum(resid2**2) / (n_reg - 3))
p_incr = 1 - stats.f.cdf(f_incr, 1, n_reg - 3)

# Also: credit spread coefficient significance
# Simple t-test on beta2[2]
X_both_mat = X_both
XtX_inv = np.linalg.inv(X_both_mat.T @ X_both_mat)
s2 = np.sum(resid2**2) / (n_reg - 3)
se_beta = np.sqrt(np.diag(XtX_inv) * s2)
t_spread = beta2[2] / se_beta[2]
p_spread = 2 * (1 - stats.t.cdf(abs(t_spread), n_reg - 3))

print(f"\n  Model 1 (VIX only):        R² = {r2_vix:.4f}")
print(f"  Model 2 (VIX + Spread):    R² = {r2_both:.4f}")
print(f"  Incremental R²:            ΔR² = {delta_r2:.4f}")
print(f"  F-test for ΔR²:            F = {f_incr:.2f}, p = {p_incr:.2e}")
print(f"\n  Coefficients in Model 2:")
print(f"    Intercept:     {beta2[0]:>+.4f}")
print(f"    VIX:           {beta2[1]:>+.4f} (SE={se_beta[1]:.4f})")
print(f"    Spread Level:  {beta2[2]:>+.4f} (SE={se_beta[2]:.4f}, t={t_spread:.2f}, p={p_spread:.2e})")

# Also add HYG/LQD
X_all = np.column_stack([np.ones(mask_reg.sum()),
                          df.loc[mask_reg, 'VIX'].values,
                          df.loc[mask_reg, 'spread_level_22d'].values,
                          df.loc[mask_reg, 'hyg_lqd_22d'].values])
mask_all = ~np.isnan(X_all).any(axis=1) & ~np.isnan(Y)
if mask_all.sum() > 100:
    beta3 = lstsq(X_all[mask_all], Y[mask_all], rcond=None)[0]
    resid3 = Y[mask_all] - X_all[mask_all] @ beta3
    r2_all = 1 - np.sum(resid3**2) / np.sum((Y[mask_all] - Y[mask_all].mean())**2)
    print(f"\n  Model 3 (VIX + Spread + HYG/LQD): R² = {r2_all:.4f} (ΔR² vs VIX = {r2_all - r2_vix:.4f})")

# ============================================================
# 9. Subperiod Analysis: GFC, Post-GFC, COVID, Rate Hikes
# ============================================================
print("\n" + "=" * 70)
print("[9] Subperiod Analysis")
print("=" * 70)

periods = {
    'GFC (2007-2009)': ('2007-01-01', '2009-12-31'),
    'Post-GFC (2010-2014)': ('2010-01-01', '2014-12-31'),
    'QE era (2015-2019)': ('2015-01-01', '2019-12-31'),
    'COVID+ (2020-2021)': ('2020-01-01', '2021-12-31'),
    'Rate Hikes (2022-2024)': ('2022-01-01', '2024-12-31'),
}

print(f"\n  {'Period':<25s}  {'N':>5s}  {'r(spread,futRV)':>16s}  {'partial_r|VIX':>14s}  {'t':>7s}  {'p':>10s}")
print(f"  {'-'*85}")

subperiod_results = {}
for name, (start, end) in periods.items():
    sub = df.loc[start:end].copy()
    mask_s = sub['SPY_RV_22d_fwd'].notna() & sub['spread_level_22d'].notna() & sub['VIX'].notna()

    if mask_s.sum() < 50:
        print(f"  {name:<25s}  {mask_s.sum():>5d}  insufficient data")
        continue

    r_s, _ = stats.pearsonr(sub.loc[mask_s, 'spread_level_22d'], sub.loc[mask_s, 'SPY_RV_22d_fwd'])

    # Partial correlation
    r_xz_s, _ = stats.pearsonr(sub.loc[mask_s, 'spread_level_22d'], sub.loc[mask_s, 'VIX'])
    r_yz_s, _ = stats.pearsonr(sub.loc[mask_s, 'SPY_RV_22d_fwd'], sub.loc[mask_s, 'VIX'])
    denom = np.sqrt((1 - r_xz_s**2) * (1 - r_yz_s**2))
    if denom > 0:
        pr_s = (r_s - r_xz_s * r_yz_s) / denom
    else:
        pr_s = 0
    n_s = mask_s.sum()
    t_s = pr_s * np.sqrt((n_s - 3) / (1 - pr_s**2)) if abs(pr_s) < 1 else 0
    p_s = 2 * (1 - stats.t.cdf(abs(t_s), n_s - 3))

    subperiod_results[name] = {'r': r_s, 'partial_r': pr_s, 't': t_s, 'p': p_s, 'n': n_s}
    sig = "***" if p_s < 0.001 else "**" if p_s < 0.01 else "*" if p_s < 0.05 else ""
    print(f"  {name:<25s}  {n_s:>5d}  {r_s:>+16.4f}  {pr_s:>+14.4f}  {t_s:>+7.2f}  {p_s:>10.2e} {sig}")

# ============================================================
# 10. Portfolio Strategy: Reduce Equity When Spreads Widen
# ============================================================
print("\n" + "=" * 70)
print("[10] Portfolio Strategy: Credit Spread-Based Allocation")
print("=" * 70)

# Strategy: 50/50 SPY/GLD baseline
# When credit spread widens (top 30%), reduce SPY allocation
# When narrow (bottom 30%), increase SPY allocation

spy_ret = ret['SPY'].reindex(df.index)
gld_data = yf.download('GLD', start='2007-01-01', end='2024-12-31', progress=False, auto_adjust=True)
gld_close = gld_data['Close']
if isinstance(gld_close, pd.DataFrame):
    gld_close = gld_close.iloc[:, 0]
gld_ret = gld_close.pct_change().reindex(df.index)

# Ensure alignment
valid_strat = spy_ret.notna() & gld_ret.notna() & df['spread_level_22d'].notna()
spy_r = spy_ret[valid_strat]
gld_r = gld_ret[valid_strat]
spread_signal = df.loc[valid_strat, 'spread_level_22d']

# Use LAGGED signal (yesterday's spread → today's allocation)
spread_lagged = spread_signal.shift(1)
valid_final = spy_r.notna() & gld_r.notna() & spread_lagged.notna()
spy_r = spy_r[valid_final]
gld_r = gld_r[valid_final]
spread_lagged = spread_lagged[valid_final]

print(f"\n  Strategy backtest: {len(spy_r)} trading days")
print(f"  Period: {spy_r.index[0].strftime('%Y-%m-%d')} to {spy_r.index[-1].strftime('%Y-%m-%d')}")

# Benchmark: static 50/50
bench_ret = 0.5 * spy_r + 0.5 * gld_r

# Strategy 1: Step function
#   Wide spread (>70th pctl): 30% SPY / 70% GLD
#   Normal (30-70th): 50/50
#   Narrow (<30th): 70% SPY / 30% GLD
p30 = spread_lagged.quantile(0.30)
p70 = spread_lagged.quantile(0.70)

spy_weight_step = pd.Series(0.5, index=spy_r.index)
spy_weight_step[spread_lagged > p70] = 0.30  # Wide spread → reduce equity
spy_weight_step[spread_lagged < p30] = 0.70  # Narrow spread → increase equity

strat1_ret = spy_weight_step * spy_r + (1 - spy_weight_step) * gld_r

# Strategy 2: Continuous (linear mapping)
spread_pctl = spread_lagged.rank(pct=True)
spy_weight_cont = 0.80 - 0.60 * spread_pctl  # Range: 0.20 to 0.80
spy_weight_cont = spy_weight_cont.clip(0.20, 0.80)
strat2_ret = spy_weight_cont * spy_r + (1 - spy_weight_cont) * gld_r

# Strategy 3: Binary VIX-augmented
# Reduce equity when BOTH spread is wide AND VIX is high
vix_lagged = df.loc[valid_final, 'VIX'].shift(1)
vix_lagged = vix_lagged.reindex(spy_r.index)
spy_weight_dual = pd.Series(0.5, index=spy_r.index)
# Both signals agree: reduce
spy_weight_dual[(spread_lagged > p70) & (vix_lagged > 20)] = 0.25
# Both calm: increase
spy_weight_dual[(spread_lagged < p30) & (vix_lagged < 15)] = 0.75
strat3_ret = spy_weight_dual * spy_r + (1 - spy_weight_dual) * gld_r

def calc_metrics(rets, name):
    """Calculate portfolio metrics."""
    ann_ret = rets.mean() * 252
    ann_vol = rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cumret = (1 + rets).cumprod()
    mdd = (cumret / cumret.cummax() - 1).min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sharpe SE
    n_years = len(rets) / 252
    sharpe_se = 1 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se

    return {
        'name': name,
        'ann_ret': ann_ret * 100,
        'ann_vol': ann_vol * 100,
        'sharpe': sharpe,
        'sharpe_t': sharpe_t,
        'mdd': mdd * 100,
        'calmar': calmar,
    }

strats = [
    calc_metrics(bench_ret, 'Static 50/50'),
    calc_metrics(strat1_ret, 'Step (30/50/70)'),
    calc_metrics(strat2_ret, 'Continuous (20-80)'),
    calc_metrics(strat3_ret, 'Dual (spread+VIX)'),
]

print(f"\n  {'Strategy':<22s}  {'Return':>8s}  {'Vol':>6s}  {'Sharpe':>7s}  {'t-stat':>7s}  {'MDD':>7s}  {'Calmar':>7s}")
print(f"  {'-'*75}")
for s in strats:
    print(f"  {s['name']:<22s}  {s['ann_ret']:>+7.2f}%  {s['ann_vol']:>5.2f}%  {s['sharpe']:>+7.3f}  {s['sharpe_t']:>7.2f}  {s['mdd']:>6.1f}%  {s['calmar']:>7.3f}")

# Difference test: strategy vs benchmark
for strat_name, strat_ret_series in [('Step', strat1_ret), ('Continuous', strat2_ret), ('Dual', strat3_ret)]:
    diff = strat_ret_series - bench_ret
    t_diff = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_diff = 2 * (1 - stats.t.cdf(abs(t_diff), len(diff) - 1))
    print(f"\n  {strat_name} vs Benchmark: mean diff = {diff.mean()*252*100:.2f}%/yr, t={t_diff:.2f}, p={p_diff:.4f}")

# Turnover
turnover_step = spy_weight_step.diff().abs().sum() / (len(spy_weight_step) / 252)
turnover_cont = spy_weight_cont.diff().abs().sum() / (len(spy_weight_cont) / 252)
turnover_dual = spy_weight_dual.diff().abs().sum() / (len(spy_weight_dual) / 252)
print(f"\n  Annual Turnover: Step={turnover_step:.1f}x, Continuous={turnover_cont:.1f}x, Dual={turnover_dual:.1f}x")

# ============================================================
# 11. Out-of-Sample Test (rolling)
# ============================================================
print("\n" + "=" * 70)
print("[11] Out-of-Sample: Rolling Predictive Regression")
print("=" * 70)

# Rolling: use 252-day window to estimate VIX+spread → future RV, then predict OOS
from numpy.linalg import lstsq as np_lstsq

window = 504  # 2 years
oos_start = window + 22  # need 22-day forward RV in training

# Prepare data
Y_full = df['SPY_RV_22d_fwd'].values
X_vix_only = np.column_stack([np.ones(len(df)), df['VIX'].values])
X_vix_spread = np.column_stack([np.ones(len(df)), df['VIX'].values, df['spread_level_22d'].values])

pred_vix = np.full(len(df), np.nan)
pred_both = np.full(len(df), np.nan)

for t in range(oos_start, len(df) - 22):
    # Training window
    train_idx = slice(t - window, t)
    y_train = Y_full[train_idx]

    if np.isnan(y_train).any():
        continue

    # VIX only
    X_train_v = X_vix_only[train_idx]
    if np.isnan(X_train_v).any():
        continue
    beta_v = np_lstsq(X_train_v, y_train, rcond=None)[0]
    pred_vix[t] = X_vix_only[t] @ beta_v

    # VIX + spread
    X_train_b = X_vix_spread[train_idx]
    if np.isnan(X_train_b).any():
        continue
    beta_b = np_lstsq(X_train_b, y_train, rcond=None)[0]
    pred_both[t] = X_vix_spread[t] @ beta_b

# Evaluate OOS
mask_oos = ~np.isnan(pred_vix) & ~np.isnan(pred_both) & ~np.isnan(Y_full)
actual = Y_full[mask_oos]
pv = pred_vix[mask_oos]
pb = pred_both[mask_oos]

qlike_vix = np.mean(np.log(pv**2) + actual**2 / pv**2)
qlike_both = np.mean(np.log(pb**2) + actual**2 / pb**2)
mse_vix = np.mean((actual - pv)**2)
mse_both = np.mean((actual - pb)**2)

# DM test
loss_vix = (actual - pv)**2
loss_both = (actual - pb)**2
d = loss_vix - loss_both
dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
dm_p = 2 * (1 - stats.t.cdf(abs(dm_stat), len(d) - 1))

print(f"\n  OOS evaluation ({mask_oos.sum()} predictions):")
print(f"  {'Model':<20s}  {'MSE':>10s}  {'QLIKE':>10s}")
print(f"  {'-'*45}")
print(f"  {'VIX only':<20s}  {mse_vix:>10.2f}  {qlike_vix:>10.4f}")
print(f"  {'VIX + Spread':<20s}  {mse_both:>10.2f}  {qlike_both:>10.4f}")
print(f"\n  DM test (VIX+Spread vs VIX): t={dm_stat:.3f}, p={dm_p:.4f}")
if dm_stat > 0:
    print(f"  → VIX+Spread has LOWER MSE (positive DM → VIX+Spread wins)")
else:
    print(f"  → VIX only has LOWER MSE (negative DM → VIX alone sufficient)")

# ============================================================
# 12. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[12] SUMMARY & CONCLUSIONS")
print("=" * 70)

# Compile results
results = {
    'experiment': 'K348',
    'title': 'Credit Spread as Volatility Signal',
    'data_source': 'yfinance (HYG, LQD, TLT, SPY, ^VIX, GLD)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df),
    'contemporaneous': {
        'corr_spread_rv': float(corr_spread_rv),
        'corr_vix_rv': float(corr_vix_rv),
        'corr_spread_vix': float(corr_spread_vix),
    },
    'predictive': {
        'simple_r': float(corr_pred),
        'partial_r_given_vix': float(partial_r),
        'partial_r_t': float(t_partial),
        'partial_r_p': float(p_partial),
        'incremental_r2': float(delta_r2),
        'f_test_p': float(p_incr),
    },
    'horizons': {str(h): {
        'r': float(v['r']),
        'partial_r': float(v['partial_r']),
        't': float(v['t']),
        'p': float(v['p']),
    } for h, v in horizon_results.items()},
    'granger_causality': {
        'spread_to_vix': {str(k): {'F': float(v['F']), 'p': float(v['p'])} for k, v in gc1.items()},
        'vix_to_spread': {str(k): {'F': float(v['F']), 'p': float(v['p'])} for k, v in gc2.items()},
        'spread_to_spy_rv': {str(k): {'F': float(v['F']), 'p': float(v['p'])} for k, v in gc3.items()},
    },
    'subperiods': {k: {
        'r': float(v['r']),
        'partial_r': float(v['partial_r']),
        't': float(v['t']),
        'p': float(v['p']),
        'n': int(v['n']),
    } for k, v in subperiod_results.items()},
    'portfolio': {s['name']: {
        'ann_ret': float(s['ann_ret']),
        'sharpe': float(s['sharpe']),
        'mdd': float(s['mdd']),
    } for s in strats},
    'oos': {
        'mse_vix': float(mse_vix),
        'mse_both': float(mse_both),
        'dm_stat': float(dm_stat),
        'dm_p': float(dm_p),
    },
}

# Print conclusions
print(f"""
  KEY FINDINGS:

  1. CONTEMPORANEOUS RELATIONSHIP:
     Credit spread highly correlated with SPY RV ({corr_spread_rv:.3f})
     and VIX ({corr_spread_vix:.3f}) — confirming credit and equity vol move together.

  2. PREDICTIVE POWER (beyond VIX):
     Partial r(spread, future_RV | VIX) = {partial_r:.4f} (t={t_partial:.2f}, p={p_partial:.2e})
     Incremental R² over VIX alone: {delta_r2:.4f} (F={f_incr:.2f}, p={p_incr:.2e})
     {'→ SIGNIFICANT: Credit spread adds information beyond VIX' if p_partial < 0.05 else '→ NOT significant: VIX subsumes credit spread information'}

  3. LEAD-LAG:
     Peak cross-correlation at lag={peak_lag}: r={cc_clean[peak_lag]['r']:.4f}
     {'→ Credit spread LEADS VIX' if peak_lag > 0 else '→ VIX leads credit spread' if peak_lag < 0 else '→ Contemporaneous'}

  4. REGIME EFFECT:
     Wide spread future RV: {fwd_wide.mean():.2f}% vs Narrow: {fwd_narrow.mean():.2f}%
     t={t_regime:.2f}, p={p_regime:.2e}
     {'→ SIGNIFICANT regime effect' if p_regime < 0.05 else '→ Regime effect not significant after VIX control'}

  5. PORTFOLIO IMPACT:
     Best strategy Sharpe: {max(s['sharpe'] for s in strats):.3f} vs Benchmark: {strats[0]['sharpe']:.3f}
     {'→ Credit spread overlay IMPROVES portfolio' if max(s['sharpe'] for s in strats) > strats[0]['sharpe'] + 0.05 else '→ Marginal/no improvement over static 50/50'}

  6. OOS PREDICTION:
     DM test (VIX+Spread vs VIX only): t={dm_stat:.3f}, p={dm_p:.4f}
     {'→ Credit spread IMPROVES OOS forecast' if dm_p < 0.05 and dm_stat > 0 else '→ No significant OOS improvement'}

  OVERALL VERDICT:
""")

# Determine overall verdict
sig_count = sum([
    1 if p_partial < 0.05 else 0,
    1 if p_incr < 0.05 else 0,
    1 if p_regime < 0.05 else 0,
    1 if dm_p < 0.05 else 0,
])

if sig_count >= 3:
    verdict = "POSITIVE: Credit spread is a meaningful vol signal beyond VIX"
elif sig_count >= 1:
    verdict = "MIXED: Some evidence but VIX largely subsumes credit spread information"
else:
    verdict = "NULL: Credit spread does not add predictive value beyond VIX"

print(f"  {verdict}")
print(f"  Significant tests: {sig_count}/4")

results['verdict'] = verdict
results['significant_count'] = sig_count

# Save results
output_path = 'experiments/k348_credit_spread_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

# Limitations
print(f"""
  LIMITATIONS:
  1. Credit spread is proxied by ETF return differentials, not actual bond spreads
     (e.g., ICE BofA High Yield OAS would be more precise)
  2. HYG/LQD/TLT have different durations → return differential mixes credit + duration
  3. 22-day rolling windows create overlapping observations → autocorrelation in tests
  4. yfinance data only; institutional-grade spread data (Bloomberg/FRED) would be better
  5. Sample includes extreme events (GFC, COVID) that dominate correlations
  6. Portfolio backtest uses daily rebalancing — monthly would be more realistic
""")

print("=" * 70)
print("K348 COMPLETE")
print("=" * 70)
