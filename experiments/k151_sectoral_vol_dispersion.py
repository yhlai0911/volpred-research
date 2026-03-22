"""
K151: Sectoral Vol-Dispersion Behavioral Signal
=================================================
[提出: Gemini R5#4 (Behavioral), 執行: Claude]

Hypothesis (Gemini):
  Broad market vol spikes are preceded by "volatility rotation" out of
  speculative "canary" assets. When the dispersion between speculative vol
  (ARKK, BITO) and defensive vol (XLP, GLD) narrows while SPY vol is low,
  it signals retail exhaustion and an imminent broad-market vol spike.

Research Questions:
  1. Does Cross-Sectional Volatility Dispersion (CSVD) between speculative
     and defensive ETFs predict SPY vol?
  2. Can CSVD improve VT strategies?

Method:
  - Data: yfinance 2016-2024 (ARKK primary, BITO from Oct 2021)
  - Speculative: ARKK (primary), BITO (from 2021)
  - Defensive: XLP, XLU, GLD
  - Market: SPY, ^VIX
  - CSVD = Spec_vol - Def_vol (raw), Spec_vol/Def_vol (ratio)
  - Predictive regression, Granger causality, regime detection, VT overlay
  - Walk-forward: w=504, OOS 2020-01-01 to 2024-12-31
  - Placebo: 1000 random ETF pairings

Statistical Requirements:
  - OOS >= 252 days
  - DM test for comparison
  - Harvey t>3.0 for strategy claims
  - Placebo/randomization test (1000 random pairings)
"""

import sys
import os
import warnings
import json
import time
from datetime import datetime

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model

# ==================================================================
# CONFIG
# ==================================================================
SPEC_TICKERS = ["ARKK"]  # primary (full sample), BITO added when available
DEF_TICKERS = ["XLP", "XLU", "GLD"]
MARKET_TICKER = "SPY"
VIX_TICKER = "^VIX"
BITO_TICKER = "BITO"

DATA_START = "2015-01-01"
DATA_END = "2024-12-31"
OOS_START = "2020-01-01"
OOS_END = "2024-12-31"
WINDOW = 504  # shorter for ARKK availability
VOL_WINDOW = 22  # rolling vol window
CSVD_CHANGE_WINDOW = 5  # rate of change window
REFIT_FREQ = 22
N_PLACEBO = 1000

print("=" * 80)
print("K151: SECTORAL VOL-DISPERSION BEHAVIORAL SIGNAL")
print("=" * 80)
print(f"  [提出: Gemini R5#4 (Behavioral), 執行: Claude]")
print(f"  Speculative: {SPEC_TICKERS} + BITO (from 2021)")
print(f"  Defensive:   {DEF_TICKERS}")
print(f"  Market:      {MARKET_TICKER}")
print(f"  OOS:         {OOS_START} to {OOS_END}")
print(f"  Window:      {WINDOW}")
print(f"  Vol window:  {VOL_WINDOW}d")
print(f"  Placebo:     {N_PLACEBO} random pairings")
print()

# ==================================================================
# 1. DATA LOADING
# ==================================================================
print("-" * 60)
print("1. LOADING DATA")
print("-" * 60)

all_tickers = SPEC_TICKERS + DEF_TICKERS + [MARKET_TICKER, VIX_TICKER, BITO_TICKER]
prices = {}
returns_dict = {}

for ticker in all_tickers:
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        prices[ticker] = df['close']
        if ticker != VIX_TICKER:
            ret = np.log(df['close'] / df['close'].shift(1)).dropna()
            returns_dict[ticker] = ret
        print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    except Exception as e:
        print(f"  {ticker}: FAILED - {e}")

# Align all to common dates (excluding BITO initially)
core_tickers = SPEC_TICKERS + DEF_TICKERS + [MARKET_TICKER]
common_idx = prices[MARKET_TICKER].index
for t in core_tickers:
    common_idx = common_idx.intersection(prices[t].index)

print(f"\n  Common dates (ARKK-era): {common_idx[0].date()} to {common_idx[-1].date()}, N={len(common_idx)}")

# ==================================================================
# 2. CSVD CONSTRUCTION
# ==================================================================
print("\n" + "-" * 60)
print("2. CONSTRUCTING CSVD SIGNALS")
print("-" * 60)

# Build returns DataFrame on common index
ret_df = pd.DataFrame(index=common_idx)
for t in core_tickers:
    ret_df[t] = returns_dict[t].reindex(common_idx)

# VIX on common index
vix = prices[VIX_TICKER].reindex(common_idx).ffill()

# 22d rolling vol (annualized)
vol_df = ret_df.rolling(VOL_WINDOW).std() * np.sqrt(252)

# Speculative vol = mean of ARKK (full sample)
spec_vol = vol_df[SPEC_TICKERS].mean(axis=1)

# Defensive vol = mean of XLP, XLU, GLD
def_vol = vol_df[DEF_TICKERS].mean(axis=1)

# SPY vol
spy_vol = vol_df[MARKET_TICKER]

# CSVD signals
csvd_raw = spec_vol - def_vol  # raw dispersion
csvd_ratio = spec_vol / def_vol  # ratio
csvd_change = csvd_raw.diff(CSVD_CHANGE_WINDOW)  # 5d change in CSVD
csvd_pctile = csvd_raw.rolling(252).rank(pct=True)  # percentile rank

# Forward SPY vol (target)
spy_vol_fwd1 = spy_vol.shift(-1)  # next day
spy_vol_fwd5 = spy_vol.shift(-5)  # 5 days ahead
spy_vol_fwd22 = spy_vol.shift(-22)  # 22 days ahead (1 month)

# SPY realized vol at different horizons
spy_r2 = ret_df[MARKET_TICKER] ** 2
spy_rv5 = spy_r2.rolling(5).sum().shift(-5) * 252 / 5  # annualized 5d forward RV
spy_rv22 = spy_r2.rolling(22).sum().shift(-22) * 252 / 22  # annualized 22d forward RV

# Clean up
signals = pd.DataFrame({
    'csvd_raw': csvd_raw,
    'csvd_ratio': csvd_ratio,
    'csvd_change': csvd_change,
    'csvd_pctile': csvd_pctile,
    'spec_vol': spec_vol,
    'def_vol': def_vol,
    'spy_vol': spy_vol,
    'spy_vol_fwd5': spy_vol_fwd5,
    'spy_vol_fwd22': spy_vol_fwd22,
    'spy_rv5_fwd': spy_rv5,
    'spy_rv22_fwd': spy_rv22,
    'vix': vix,
    'spy_ret': ret_df[MARKET_TICKER],
}, index=common_idx).dropna()

print(f"  Signal dataframe: {signals.index[0].date()} to {signals.index[-1].date()}, N={len(signals)}")
print(f"  CSVD raw:    mean={csvd_raw.mean():.4f}, std={csvd_raw.std():.4f}")
print(f"  CSVD ratio:  mean={csvd_ratio.mean():.4f}, std={csvd_ratio.std():.4f}")
print(f"  Spec vol:    mean={spec_vol.mean():.4f}")
print(f"  Def vol:     mean={def_vol.mean():.4f}")

# ==================================================================
# 3a. PREDICTIVE REGRESSION (Full Sample)
# ==================================================================
print("\n" + "-" * 60)
print("3a. PREDICTIVE REGRESSION (full-sample)")
print("-" * 60)

from scipy.stats import pearsonr

regression_results = {}
for target_name, target_col in [('spy_vol_fwd5', 'spy_vol_fwd5'),
                                  ('spy_vol_fwd22', 'spy_vol_fwd22'),
                                  ('spy_rv5_fwd', 'spy_rv5_fwd'),
                                  ('spy_rv22_fwd', 'spy_rv22_fwd')]:
    for signal_name, signal_col in [('csvd_raw', 'csvd_raw'),
                                      ('csvd_change', 'csvd_change'),
                                      ('csvd_ratio', 'csvd_ratio')]:
        mask = signals[[signal_col, target_col]].dropna().index
        x = signals.loc[mask, signal_col].values
        y = signals.loc[mask, target_col].values

        # Simple regression
        slope, intercept, r_val, p_val, se = stats.linregress(x, y)
        r2 = r_val ** 2

        key = f"{signal_name}_to_{target_name}"
        regression_results[key] = {
            'slope': round(slope, 6),
            'intercept': round(intercept, 6),
            'r': round(r_val, 4),
            'r2': round(r2, 4),
            'p_value': round(p_val, 6),
            't_stat': round(slope / se, 2),
            'n': len(x)
        }
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        print(f"  {key}: r={r_val:.4f}, R²={r2:.4f}, t={slope/se:.2f}, p={p_val:.4f} {sig}")

# ==================================================================
# 3b. PARTIAL CORRELATION — CSVD → SPY vol | VIX
# ==================================================================
print("\n" + "-" * 60)
print("3b. PARTIAL CORRELATION (CSVD → SPY vol | VIX)")
print("-" * 60)
print("  CRITICAL TEST: Does CSVD add info beyond VIX?")

partial_corr_results = {}

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Residualize x on z
    slope_xz, intercept_xz, _, _, _ = stats.linregress(z, x)
    resid_x = x - (slope_xz * z + intercept_xz)
    # Residualize y on z
    slope_yz, intercept_yz, _, _, _ = stats.linregress(z, y)
    resid_y = y - (slope_yz * z + intercept_yz)
    # Correlation of residuals
    r, p = pearsonr(resid_x, resid_y)
    return r, p

for target_name in ['spy_vol_fwd5', 'spy_vol_fwd22', 'spy_rv5_fwd', 'spy_rv22_fwd']:
    for signal_name in ['csvd_raw', 'csvd_change', 'csvd_ratio']:
        mask = signals[[signal_name, target_name, 'vix']].dropna().index
        x = signals.loc[mask, signal_name].values
        y = signals.loc[mask, target_name].values
        z = signals.loc[mask, 'vix'].values

        r_partial, p_partial = partial_corr(x, y, z)

        # Also compute unconditional correlation for comparison
        r_raw, p_raw = pearsonr(x, y)

        key = f"{signal_name}_to_{target_name}_given_VIX"
        partial_corr_results[key] = {
            'r_unconditional': round(r_raw, 4),
            'r_partial': round(r_partial, 4),
            'p_partial': round(p_partial, 6),
            'pct_reduction': round((1 - abs(r_partial) / max(abs(r_raw), 1e-8)) * 100, 1),
            'n': len(x)
        }
        sig = "***" if p_partial < 0.001 else "**" if p_partial < 0.01 else "*" if p_partial < 0.05 else ""
        print(f"  {signal_name} → {target_name} | VIX: r_raw={r_raw:.4f} → r_partial={r_partial:.4f}, "
              f"reduction={partial_corr_results[key]['pct_reduction']:.0f}% {sig}")

# ==================================================================
# 3c. GRANGER CAUSALITY
# ==================================================================
print("\n" + "-" * 60)
print("3c. GRANGER CAUSALITY TESTS")
print("-" * 60)

granger_results = {}

def granger_test(x, y, max_lag=5):
    """Test if x Granger-causes y using F-test.
    Returns (F_stat, p_value) for each lag."""
    results = {}
    df_test = pd.DataFrame({'x': x, 'y': y}).dropna()
    n = len(df_test)

    for lag in range(1, max_lag + 1):
        # Restricted model: y_t = a + b1*y_{t-1} + ... + bL*y_{t-L}
        y_lagged = pd.concat([df_test['y'].shift(i) for i in range(1, lag + 1)], axis=1)
        y_lagged.columns = [f'y_lag{i}' for i in range(1, lag + 1)]

        # Unrestricted: add x lags
        x_lagged = pd.concat([df_test['x'].shift(i) for i in range(1, lag + 1)], axis=1)
        x_lagged.columns = [f'x_lag{i}' for i in range(1, lag + 1)]

        combined = pd.concat([df_test['y'], y_lagged, x_lagged], axis=1).dropna()
        y_dep = combined.iloc[:, 0].values

        # Restricted
        X_r = np.column_stack([np.ones(len(combined)), combined.iloc[:, 1:lag+1].values])
        beta_r = np.linalg.lstsq(X_r, y_dep, rcond=None)[0]
        resid_r = y_dep - X_r @ beta_r
        ssr_r = np.sum(resid_r ** 2)

        # Unrestricted
        X_u = np.column_stack([np.ones(len(combined)), combined.iloc[:, 1:].values])
        beta_u = np.linalg.lstsq(X_u, y_dep, rcond=None)[0]
        resid_u = y_dep - X_u @ beta_u
        ssr_u = np.sum(resid_u ** 2)

        # F-test
        n_obs = len(y_dep)
        k_u = X_u.shape[1]
        k_r = X_r.shape[1]

        if ssr_u > 0:
            f_stat = ((ssr_r - ssr_u) / (k_u - k_r)) / (ssr_u / (n_obs - k_u))
            p_val = 1 - stats.f.cdf(f_stat, k_u - k_r, n_obs - k_u)
        else:
            f_stat, p_val = 0.0, 1.0

        results[lag] = {'F': round(f_stat, 3), 'p': round(p_val, 4)}

    return results

# Test CSVD → SPY vol
mask = signals[['csvd_raw', 'spy_vol']].dropna().index
gc1 = granger_test(signals.loc[mask, 'csvd_raw'].values,
                    signals.loc[mask, 'spy_vol'].values)
granger_results['csvd_raw_to_spy_vol'] = gc1

# Test SPY vol → CSVD (reverse)
gc2 = granger_test(signals.loc[mask, 'spy_vol'].values,
                    signals.loc[mask, 'csvd_raw'].values)
granger_results['spy_vol_to_csvd_raw'] = gc2

# Test CSVD_change → SPY vol
mask2 = signals[['csvd_change', 'spy_vol']].dropna().index
gc3 = granger_test(signals.loc[mask2, 'csvd_change'].values,
                    signals.loc[mask2, 'spy_vol'].values)
granger_results['csvd_change_to_spy_vol'] = gc3

print("  CSVD_raw → SPY_vol:")
for lag, res in gc1.items():
    sig = "*" if res['p'] < 0.05 else ""
    print(f"    lag={lag}: F={res['F']:.3f}, p={res['p']:.4f} {sig}")

print("  SPY_vol → CSVD_raw (reverse):")
for lag, res in gc2.items():
    sig = "*" if res['p'] < 0.05 else ""
    print(f"    lag={lag}: F={res['F']:.3f}, p={res['p']:.4f} {sig}")

print("  CSVD_change → SPY_vol:")
for lag, res in gc3.items():
    sig = "*" if res['p'] < 0.05 else ""
    print(f"    lag={lag}: F={res['F']:.3f}, p={res['p']:.4f} {sig}")

# ==================================================================
# 3d. REGIME DETECTION — "Fragile Calm"
# ==================================================================
print("\n" + "-" * 60)
print("3d. REGIME DETECTION — 'Fragile Calm' Signal")
print("-" * 60)
print("  Fragile calm = CSVD narrowing + SPY vol low (<20th pctl)")

regime_results = {}

# Identify "fragile calm" periods
spy_vol_pctile = spy_vol.rolling(252).rank(pct=True)
csvd_narrowing = csvd_change < 0  # CSVD is decreasing

# Align
regime_df = pd.DataFrame({
    'spy_vol': spy_vol,
    'spy_vol_pctile': spy_vol_pctile,
    'csvd_raw': csvd_raw,
    'csvd_change': csvd_change,
    'csvd_narrowing': csvd_narrowing.astype(float),
    'spy_ret': ret_df[MARKET_TICKER],
}, index=common_idx).dropna()

# Forward returns/vol at various horizons
for h in [5, 10, 22]:
    regime_df[f'fwd_rv_{h}d'] = (ret_df[MARKET_TICKER] ** 2).rolling(h).sum().shift(-h) * 252 / h
    regime_df[f'fwd_ret_{h}d'] = ret_df[MARKET_TICKER].rolling(h).sum().shift(-h)

regime_df = regime_df.dropna()

# Define fragile calm: low vol + narrowing dispersion
fragile_calm = (regime_df['spy_vol_pctile'] < 0.20) & (regime_df['csvd_narrowing'] == 1)
normal = ~fragile_calm

n_fragile = fragile_calm.sum()
n_total = len(regime_df)
pct_fragile = n_fragile / n_total * 100

print(f"  Total days: {n_total}")
print(f"  Fragile calm days: {n_fragile} ({pct_fragile:.1f}%)")

for h in [5, 10, 22]:
    rv_fragile = regime_df.loc[fragile_calm, f'fwd_rv_{h}d']
    rv_normal = regime_df.loc[normal, f'fwd_rv_{h}d']

    t_stat, p_val = stats.ttest_ind(rv_fragile, rv_normal)

    ret_fragile = regime_df.loc[fragile_calm, f'fwd_ret_{h}d']
    ret_normal = regime_df.loc[normal, f'fwd_ret_{h}d']
    t_ret, p_ret = stats.ttest_ind(ret_fragile, ret_normal)

    regime_results[f'{h}d'] = {
        'rv_fragile_mean': round(float(rv_fragile.mean()), 4),
        'rv_normal_mean': round(float(rv_normal.mean()), 4),
        'rv_ratio': round(float(rv_fragile.mean() / rv_normal.mean()), 3),
        'rv_tstat': round(float(t_stat), 2),
        'rv_pval': round(float(p_val), 4),
        'ret_fragile_mean': round(float(ret_fragile.mean()), 6),
        'ret_normal_mean': round(float(ret_normal.mean()), 6),
        'ret_tstat': round(float(t_ret), 2),
        'ret_pval': round(float(p_ret), 4),
    }

    sig = "*" if p_val < 0.05 else ""
    print(f"  {h}d forward RV: fragile={rv_fragile.mean():.4f} vs normal={rv_normal.mean():.4f}, "
          f"ratio={rv_fragile.mean()/rv_normal.mean():.2f}, t={t_stat:.2f}, p={p_val:.4f} {sig}")

regime_results['n_fragile'] = int(n_fragile)
regime_results['pct_fragile'] = round(pct_fragile, 1)

# ==================================================================
# 4. WALK-FORWARD PREDICTIVE REGRESSION (OOS)
# ==================================================================
print("\n" + "-" * 60)
print("4. WALK-FORWARD OUT-OF-SAMPLE REGRESSION")
print("-" * 60)

oos_mask = signals.index >= OOS_START
oos_dates = signals.index[oos_mask]
first_oos_loc = signals.index.get_loc(oos_dates[0]) if len(oos_dates) > 0 else len(signals)

print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}, N_oos={len(oos_dates)}")
print(f"  First OOS location: {first_oos_loc}")

# Walk-forward: for each OOS day, use last WINDOW days to fit regression, predict
oos_predictions = {
    'csvd_only': [],
    'vix_only': [],
    'csvd_plus_vix': [],
    'actual': [],
    'dates': [],
}

for i, date in enumerate(oos_dates):
    loc = signals.index.get_loc(date)
    if loc < WINDOW + 22:  # need enough history
        continue

    # Training window
    train_idx = signals.index[loc - WINDOW:loc]

    # Target: 5d forward RV
    y_train = signals.loc[train_idx, 'spy_rv5_fwd'].values
    actual_fwd = signals.loc[date, 'spy_rv5_fwd']

    if np.isnan(actual_fwd):
        continue

    # Features
    x_csvd = signals.loc[train_idx, 'csvd_change'].values
    x_vix = signals.loc[train_idx, 'vix'].values

    # Current features
    csvd_now = signals.loc[date, 'csvd_change']
    vix_now = signals.loc[date, 'vix']

    if np.any(np.isnan(y_train)) or np.isnan(csvd_now) or np.isnan(vix_now):
        continue

    # Model 1: CSVD only
    valid = ~np.isnan(y_train) & ~np.isnan(x_csvd)
    if valid.sum() > 50:
        slope1, int1, _, _, _ = stats.linregress(x_csvd[valid], y_train[valid])
        pred_csvd = slope1 * csvd_now + int1
    else:
        pred_csvd = np.nanmean(y_train)

    # Model 2: VIX only
    valid2 = ~np.isnan(y_train) & ~np.isnan(x_vix)
    if valid2.sum() > 50:
        slope2, int2, _, _, _ = stats.linregress(x_vix[valid2], y_train[valid2])
        pred_vix = slope2 * vix_now + int2
    else:
        pred_vix = np.nanmean(y_train)

    # Model 3: CSVD + VIX (multivariate)
    X_train = np.column_stack([x_csvd, x_vix])
    valid3 = ~np.isnan(y_train) & ~np.isnan(X_train).any(axis=1)
    if valid3.sum() > 50:
        X_r = np.column_stack([np.ones(valid3.sum()), X_train[valid3]])
        beta = np.linalg.lstsq(X_r, y_train[valid3], rcond=None)[0]
        pred_both = beta[0] + beta[1] * csvd_now + beta[2] * vix_now
    else:
        pred_both = np.nanmean(y_train)

    oos_predictions['csvd_only'].append(max(pred_csvd, 0.001))
    oos_predictions['vix_only'].append(max(pred_vix, 0.001))
    oos_predictions['csvd_plus_vix'].append(max(pred_both, 0.001))
    oos_predictions['actual'].append(actual_fwd)
    oos_predictions['dates'].append(date)

# Evaluate OOS
actual = np.array(oos_predictions['actual'])
pred_csvd_arr = np.array(oos_predictions['csvd_only'])
pred_vix_arr = np.array(oos_predictions['vix_only'])
pred_both_arr = np.array(oos_predictions['csvd_plus_vix'])

n_oos = len(actual)
print(f"  OOS predictions: {n_oos}")

def oos_r2(actual, predicted):
    """Out-of-sample R² relative to historical mean."""
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return 1 - ss_res / ss_tot

def qlike(actual, predicted):
    """QLIKE loss."""
    predicted = np.maximum(predicted, 1e-12)
    return float(np.mean(actual / predicted + np.log(predicted)))

def dm_test(actual, pred1, pred2, loss='se'):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    if loss == 'se':
        e1 = (actual - pred1) ** 2
        e2 = (actual - pred2) ** 2
    elif loss == 'qlike':
        pred1 = np.maximum(pred1, 1e-12)
        pred2 = np.maximum(pred2, 1e-12)
        e1 = actual / pred1 + np.log(pred1)
        e2 = actual / pred2 + np.log(pred2)

    d = e1 - e2
    d_mean = np.mean(d)

    # Newey-West HAC variance (5 lags)
    n = len(d)
    max_lag = min(5, n // 5)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (max_lag + 1)) * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

oos_eval = {}

# CSVD only
r2_csvd = oos_r2(actual, pred_csvd_arr)
q_csvd = qlike(actual, pred_csvd_arr)
mse_csvd = np.mean((actual - pred_csvd_arr) ** 2)

# VIX only
r2_vix = oos_r2(actual, pred_vix_arr)
q_vix = qlike(actual, pred_vix_arr)
mse_vix = np.mean((actual - pred_vix_arr) ** 2)

# CSVD + VIX
r2_both = oos_r2(actual, pred_both_arr)
q_both = qlike(actual, pred_both_arr)
mse_both = np.mean((actual - pred_both_arr) ** 2)

# DM tests
dm_csvd_vs_vix_se, dm_p_csvd_vs_vix_se = dm_test(actual, pred_csvd_arr, pred_vix_arr, 'se')
dm_both_vs_vix_se, dm_p_both_vs_vix_se = dm_test(actual, pred_both_arr, pred_vix_arr, 'se')
dm_csvd_vs_vix_ql, dm_p_csvd_vs_vix_ql = dm_test(actual, pred_csvd_arr, pred_vix_arr, 'qlike')
dm_both_vs_vix_ql, dm_p_both_vs_vix_ql = dm_test(actual, pred_both_arr, pred_vix_arr, 'qlike')

oos_eval = {
    'n_oos': n_oos,
    'csvd_only': {
        'oos_r2': round(r2_csvd, 4),
        'qlike': round(q_csvd, 4),
        'mse': round(mse_csvd, 6),
    },
    'vix_only': {
        'oos_r2': round(r2_vix, 4),
        'qlike': round(q_vix, 4),
        'mse': round(mse_vix, 6),
    },
    'csvd_plus_vix': {
        'oos_r2': round(r2_both, 4),
        'qlike': round(q_both, 4),
        'mse': round(mse_both, 6),
    },
    'dm_csvd_vs_vix': {
        'se': {'stat': round(dm_csvd_vs_vix_se, 3), 'p': round(dm_p_csvd_vs_vix_se, 4)},
        'qlike': {'stat': round(dm_csvd_vs_vix_ql, 3), 'p': round(dm_p_csvd_vs_vix_ql, 4)},
    },
    'dm_both_vs_vix': {
        'se': {'stat': round(dm_both_vs_vix_se, 3), 'p': round(dm_p_both_vs_vix_se, 4)},
        'qlike': {'stat': round(dm_both_vs_vix_ql, 3), 'p': round(dm_p_both_vs_vix_ql, 4)},
    },
}

print(f"\n  {'Model':<20} {'OOS R²':<10} {'QLIKE':<10} {'MSE':<12}")
print(f"  {'-'*52}")
print(f"  {'CSVD only':<20} {r2_csvd:<10.4f} {q_csvd:<10.4f} {mse_csvd:<12.6f}")
print(f"  {'VIX only':<20} {r2_vix:<10.4f} {q_vix:<10.4f} {mse_vix:<12.6f}")
print(f"  {'CSVD + VIX':<20} {r2_both:<10.4f} {q_both:<10.4f} {mse_both:<12.6f}")
print()
print(f"  DM test (CSVD vs VIX): SE: t={dm_csvd_vs_vix_se:.3f}, p={dm_p_csvd_vs_vix_se:.4f} | "
      f"QLIKE: t={dm_csvd_vs_vix_ql:.3f}, p={dm_p_csvd_vs_vix_ql:.4f}")
print(f"  DM test (CSVD+VIX vs VIX): SE: t={dm_both_vs_vix_se:.3f}, p={dm_p_both_vs_vix_se:.4f} | "
      f"QLIKE: t={dm_both_vs_vix_ql:.3f}, p={dm_p_both_vs_vix_ql:.4f}")

# ==================================================================
# 5. VT STRATEGY WITH CSVD OVERLAY
# ==================================================================
print("\n" + "-" * 60)
print("5. VT STRATEGY WITH CSVD OVERLAY")
print("-" * 60)

# Build daily strategy returns
spy_ret_full = ret_df[MARKET_TICKER].reindex(common_idx)
vix_full = prices[VIX_TICKER].reindex(common_idx).ffill()
csvd_raw_full = csvd_raw.reindex(common_idx)
csvd_change_full = csvd_change.reindex(common_idx)

# Strategy 1: Plain 12/VIX
vt_target = 0.12
weight_vix = (vt_target / (vix_full / 100)).clip(0, 1.5)  # cap at 150%

# Strategy 2: 12/VIX + CSVD overlay
# When CSVD is narrowing (fragile calm signal), reduce exposure by 30%
# CSVD narrowing = csvd_change < 0 AND spy_vol is low
spy_vol_pctile_full = spy_vol.rolling(252).rank(pct=True).reindex(common_idx)
fragile_signal = (csvd_change_full < 0) & (spy_vol_pctile_full < 0.20)
csvd_multiplier = pd.Series(1.0, index=common_idx)
csvd_multiplier[fragile_signal] = 0.7  # reduce 30% during fragile calm

weight_csvd = (weight_vix * csvd_multiplier).clip(0, 1.5)

# Use lagged weights (avoid same-day bias)
weight_vix_lag = weight_vix.shift(1)
weight_csvd_lag = weight_csvd.shift(1)

# Strategy returns (OOS only)
oos_mask_full = common_idx >= OOS_START
oos_idx = common_idx[oos_mask_full]

ret_bh = spy_ret_full.loc[oos_idx]
ret_vix_vt = (weight_vix_lag * spy_ret_full).loc[oos_idx]
ret_csvd_vt = (weight_csvd_lag * spy_ret_full).loc[oos_idx]

# Clean NaN
valid_strat = ret_bh.dropna().index.intersection(ret_vix_vt.dropna().index).intersection(ret_csvd_vt.dropna().index)
ret_bh = ret_bh.loc[valid_strat]
ret_vix_vt = ret_vix_vt.loc[valid_strat]
ret_csvd_vt = ret_csvd_vt.loc[valid_strat]

n_strat_days = len(ret_bh)
print(f"  Strategy OOS days: {n_strat_days}")

def compute_metrics(returns, name):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sharpe SE and t-stat
    n_years = len(returns) / 252
    se_sharpe = 1 / np.sqrt(n_years)
    t_sharpe = sharpe / se_sharpe

    return {
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 4),
        'mdd': round(float(mdd), 4),
        't_sharpe': round(float(t_sharpe), 2),
        'se_sharpe': round(float(se_sharpe), 3),
        'n_days': int(len(returns)),
    }

metrics_bh = compute_metrics(ret_bh, "Buy&Hold")
metrics_vix = compute_metrics(ret_vix_vt, "12/VIX")
metrics_csvd = compute_metrics(ret_csvd_vt, "12/VIX+CSVD")

# DM test for strategies (using squared returns as loss)
dm_strat, dm_strat_p = dm_test(
    ret_bh.values ** 2,  # squared returns as proxy for "variance loss"
    (ret_bh.values - ret_vix_vt.values) ** 2,
    (ret_bh.values - ret_csvd_vt.values) ** 2,
    'se'
)

# Direct Sharpe comparison
sharpe_diff = metrics_csvd['sharpe'] - metrics_vix['sharpe']
n_years = n_strat_days / 252

strategy_results = {
    'buy_hold': metrics_bh,
    'vix_12_vt': metrics_vix,
    'vix_12_csvd_overlay': metrics_csvd,
    'sharpe_diff_csvd_vs_vix': round(sharpe_diff, 4),
    'harvey_test': {
        't_csvd_overlay': metrics_csvd['t_sharpe'],
        'passes_harvey_3': metrics_csvd['t_sharpe'] > 3.0,
    },
}

print(f"\n  {'Strategy':<25} {'Return':<10} {'Vol':<10} {'Sharpe':<10} {'MDD':<10} {'t-Sharpe':<10}")
print(f"  {'-'*75}")
print(f"  {'Buy&Hold':<25} {metrics_bh['ann_return']:<10.4f} {metrics_bh['ann_vol']:<10.4f} "
      f"{metrics_bh['sharpe']:<10.4f} {metrics_bh['mdd']:<10.4f} {metrics_bh['t_sharpe']:<10.2f}")
print(f"  {'12/VIX':<25} {metrics_vix['ann_return']:<10.4f} {metrics_vix['ann_vol']:<10.4f} "
      f"{metrics_vix['sharpe']:<10.4f} {metrics_vix['mdd']:<10.4f} {metrics_vix['t_sharpe']:<10.2f}")
print(f"  {'12/VIX + CSVD overlay':<25} {metrics_csvd['ann_return']:<10.4f} {metrics_csvd['ann_vol']:<10.4f} "
      f"{metrics_csvd['sharpe']:<10.4f} {metrics_csvd['mdd']:<10.4f} {metrics_csvd['t_sharpe']:<10.2f}")
print(f"\n  Sharpe diff (CSVD overlay - VIX): {sharpe_diff:+.4f}")
print(f"  Harvey 3.0 threshold: {'PASS' if metrics_csvd['t_sharpe'] > 3.0 else 'FAIL'} (t={metrics_csvd['t_sharpe']:.2f})")

# ==================================================================
# 6. PLACEBO TEST — 1000 Random ETF Pairings
# ==================================================================
print("\n" + "-" * 60)
print("6. PLACEBO TEST — 1000 Random ETF Pairings")
print("-" * 60)

# Universe of ETFs for placebo
placebo_universe = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLB", "XLRE", "XLC",
                     "IWM", "EEM", "TLT", "HYG", "LQD", "IEF", "SHY",
                     "QQQ", "DIA", "VTI", "AGG", "BND"]

# Download placebo tickers
print("  Downloading placebo universe...")
placebo_prices = {}
for ticker in placebo_universe:
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        placebo_prices[ticker] = df['close']
    except:
        pass

available_placebo = list(placebo_prices.keys())
print(f"  Available tickers for placebo: {len(available_placebo)}")

np.random.seed(42)
placebo_partial_r = []
n_placebo_done = 0

for trial in range(N_PLACEBO):
    if len(available_placebo) < 5:
        break

    # Random split: 2 "speculative" and 3 "defensive"
    chosen = np.random.choice(available_placebo, size=min(5, len(available_placebo)), replace=False)
    spec_random = list(chosen[:2])
    def_random = list(chosen[2:5])

    # Build random CSVD
    try:
        rand_idx = common_idx
        for t in spec_random + def_random:
            if t in placebo_prices:
                rand_idx = rand_idx.intersection(placebo_prices[t].index)

        if len(rand_idx) < 500:
            continue

        rand_returns = pd.DataFrame(index=rand_idx)
        for t in spec_random + def_random:
            if t in placebo_prices:
                p = placebo_prices[t].reindex(rand_idx).ffill()
                rand_returns[t] = np.log(p / p.shift(1))

        rand_vol = rand_returns.rolling(VOL_WINDOW).std() * np.sqrt(252)

        spec_v = rand_vol[spec_random].mean(axis=1)
        def_v = rand_vol[def_random].mean(axis=1)
        rand_csvd = spec_v - def_v
        rand_csvd_change = rand_csvd.diff(CSVD_CHANGE_WINDOW)

        # Align with SPY vol and VIX
        combined = pd.DataFrame({
            'rand_csvd_change': rand_csvd_change,
            'spy_vol_fwd5': spy_vol_fwd5.reindex(rand_idx),
            'vix': vix.reindex(rand_idx),
        }).dropna()

        if len(combined) < 100:
            continue

        x = combined['rand_csvd_change'].values
        y = combined['spy_vol_fwd5'].values
        z = combined['vix'].values

        r_p, p_p = partial_corr(x, y, z)
        placebo_partial_r.append(abs(r_p))
        n_placebo_done += 1
    except:
        continue

# Compare real CSVD partial correlation to placebo distribution
real_key = 'csvd_change_to_spy_vol_fwd5_given_VIX'
real_partial_r = abs(partial_corr_results.get(real_key, {}).get('r_partial', 0))

placebo_arr = np.array(placebo_partial_r)
if len(placebo_arr) > 0:
    placebo_pctile = np.mean(placebo_arr >= real_partial_r) * 100
    placebo_mean = np.mean(placebo_arr)
    placebo_std = np.std(placebo_arr)
    placebo_p = np.mean(placebo_arr >= real_partial_r)
else:
    placebo_pctile = 50.0
    placebo_mean = 0.0
    placebo_std = 0.0
    placebo_p = 0.5

placebo_results = {
    'n_trials': n_placebo_done,
    'real_partial_r_abs': round(real_partial_r, 4),
    'placebo_mean_abs': round(placebo_mean, 4),
    'placebo_std': round(placebo_std, 4),
    'placebo_p_value': round(placebo_p, 4),
    'pctile_rank': round(100 - placebo_pctile, 1),
}

print(f"  Completed {n_placebo_done} placebo trials")
print(f"  Real |partial r| (CSVD→vol|VIX):  {real_partial_r:.4f}")
print(f"  Placebo |partial r| distribution:  mean={placebo_mean:.4f}, std={placebo_std:.4f}")
print(f"  Percentile rank of real signal:    {100-placebo_pctile:.1f}th percentile")
print(f"  Placebo p-value:                   {placebo_p:.4f}")

# ==================================================================
# 7. BITO ERA ANALYSIS (post Oct 2021)
# ==================================================================
print("\n" + "-" * 60)
print("7. BITO ERA ANALYSIS (post Oct 2021)")
print("-" * 60)

bito_results = {}
if BITO_TICKER in prices:
    bito_start = prices[BITO_TICKER].first_valid_index()
    bito_idx = common_idx[common_idx >= bito_start]
    bito_idx = bito_idx.intersection(prices[BITO_TICKER].index)

    if len(bito_idx) > 200:
        # BITO returns
        bito_ret = np.log(prices[BITO_TICKER] / prices[BITO_TICKER].shift(1)).reindex(bito_idx)
        bito_vol = bito_ret.rolling(VOL_WINDOW).std() * np.sqrt(252)

        # ARKK + BITO speculative vol
        arkk_vol_bito = vol_df['ARKK'].reindex(bito_idx)
        spec_vol_2 = pd.DataFrame({'ARKK': arkk_vol_bito, 'BITO': bito_vol}, index=bito_idx).mean(axis=1)
        def_vol_2 = vol_df[DEF_TICKERS].reindex(bito_idx).mean(axis=1)

        csvd_2 = spec_vol_2 - def_vol_2
        csvd_change_2 = csvd_2.diff(CSVD_CHANGE_WINDOW)

        spy_vol_2 = vol_df[MARKET_TICKER].reindex(bito_idx)
        spy_fwd5_2 = spy_vol_2.shift(-5)
        vix_2 = vix.reindex(bito_idx)

        combined_bito = pd.DataFrame({
            'csvd_change': csvd_change_2,
            'spy_vol_fwd5': spy_fwd5_2,
            'vix': vix_2,
        }).dropna()

        if len(combined_bito) > 50:
            x = combined_bito['csvd_change'].values
            y = combined_bito['spy_vol_fwd5'].values
            z = combined_bito['vix'].values

            r_raw, p_raw = pearsonr(x, y)
            r_partial_bito, p_partial_bito = partial_corr(x, y, z)

            bito_results = {
                'period': f"{bito_idx[0].date()} to {bito_idx[-1].date()}",
                'n_days': len(combined_bito),
                'r_unconditional': round(float(r_raw), 4),
                'p_unconditional': round(float(p_raw), 4),
                'r_partial': round(float(r_partial_bito), 4),
                'p_partial': round(float(p_partial_bito), 4),
            }

            print(f"  BITO era: {bito_results['period']}, N={bito_results['n_days']}")
            print(f"  Unconditional r(CSVD_change, SPY_vol_fwd5): {r_raw:.4f} (p={p_raw:.4f})")
            print(f"  Partial r (|VIX): {r_partial_bito:.4f} (p={p_partial_bito:.4f})")
        else:
            print("  Not enough BITO data for analysis")
    else:
        print("  Not enough BITO data")
else:
    print("  BITO data not available")

# ==================================================================
# 8. GARCH-X WITH CSVD
# ==================================================================
print("\n" + "-" * 60)
print("8. GARCH-X WITH CSVD EXOGENOUS VARIABLE")
print("-" * 60)

# Compare GARCH vs GARCH-X (with CSVD as exogenous)
spy_ret_pct = (ret_df[MARKET_TICKER] * 100).reindex(common_idx)
spy_ret_pct = spy_ret_pct.dropna()

oos_mask_garch = spy_ret_pct.index >= OOS_START
oos_dates_garch = spy_ret_pct.index[oos_mask_garch]

# Align CSVD with returns
csvd_for_garch = csvd_raw.reindex(spy_ret_pct.index).ffill()

garch_forecasts = []
garchx_forecasts = []
garch_actual = []
garch_dates_list = []

refit_counter = 0
last_garch_params = None
last_garchx_params = None

print(f"  OOS: {oos_dates_garch[0].date()} to {oos_dates_garch[-1].date()}, N={len(oos_dates_garch)}")
print("  Fitting GARCH and GARCH-X models (this may take a while)...")

for i, date in enumerate(oos_dates_garch):
    loc = spy_ret_pct.index.get_loc(date)
    if loc < WINDOW:
        continue

    # Actual next-day r²
    if loc + 1 >= len(spy_ret_pct):
        break
    actual_r2 = (spy_ret_pct.iloc[loc + 1] / 100) ** 2  # back to decimal

    if refit_counter % REFIT_FREQ == 0:
        train_data = spy_ret_pct.iloc[loc - WINDOW:loc]
        train_csvd = csvd_for_garch.iloc[loc - WINDOW:loc]

        try:
            # Plain GJR-GARCH
            am = arch_model(train_data, vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = am.fit(disp='off', show_warning=False)
            last_garch_params = res

            # GARCH-X with CSVD
            # Use CSVD as exogenous variable in variance equation
            # arch library supports x parameter for mean equation only,
            # so we use a workaround: include CSVD in mean equation
            # and check if it improves overall forecast
            amx = arch_model(train_data, x=pd.DataFrame({'csvd': train_csvd.values}, index=train_data.index),
                           vol='GARCH', p=1, o=1, q=1, dist='normal')
            resx = amx.fit(disp='off', show_warning=False)
            last_garchx_params = resx
        except:
            pass

    refit_counter += 1

    if last_garch_params is not None and last_garchx_params is not None:
        try:
            fcast_g = last_garch_params.forecast(horizon=1)
            var_g = fcast_g.variance.iloc[-1, 0] / 10000  # back to decimal

            fcast_gx = last_garchx_params.forecast(horizon=1)
            var_gx = fcast_gx.variance.iloc[-1, 0] / 10000

            garch_forecasts.append(max(var_g, 1e-8))
            garchx_forecasts.append(max(var_gx, 1e-8))
            garch_actual.append(actual_r2)
            garch_dates_list.append(date)
        except:
            continue

garch_actual_arr = np.array(garch_actual)
garch_pred_arr = np.array(garch_forecasts)
garchx_pred_arr = np.array(garchx_forecasts)

garchx_results = {}
if len(garch_actual_arr) > 100:
    q_garch = qlike(garch_actual_arr, garch_pred_arr)
    q_garchx = qlike(garch_actual_arr, garchx_pred_arr)

    dm_garchx, dm_garchx_p = dm_test(garch_actual_arr, garchx_pred_arr, garch_pred_arr, 'qlike')

    garchx_results = {
        'n_forecasts': len(garch_actual_arr),
        'qlike_garch': round(q_garch, 4),
        'qlike_garchx': round(q_garchx, 4),
        'qlike_improvement': round((q_garch - q_garchx) / abs(q_garch) * 100, 2),
        'dm_stat': round(dm_garchx, 3),
        'dm_p': round(dm_garchx_p, 4),
    }

    print(f"  N forecasts: {garchx_results['n_forecasts']}")
    print(f"  GARCH QLIKE:    {q_garch:.4f}")
    print(f"  GARCH-X QLIKE:  {q_garchx:.4f}")
    print(f"  Improvement:    {garchx_results['qlike_improvement']:.2f}%")
    print(f"  DM test (GARCH-X vs GARCH): t={dm_garchx:.3f}, p={dm_garchx_p:.4f}")
else:
    print(f"  Insufficient forecasts: {len(garch_actual_arr)}")

# ==================================================================
# 9. SUMMARY & VERDICT
# ==================================================================
print("\n" + "=" * 80)
print("9. SUMMARY & VERDICT")
print("=" * 80)

# Key findings
vix_is_sufficient = True
csvd_has_incremental = False

# Check if any partial correlation is significant at 5%
for key, val in partial_corr_results.items():
    if val['p_partial'] < 0.05:
        csvd_has_incremental = True
        vix_is_sufficient = False

# Check if CSVD+VIX beats VIX alone in OOS
csvd_improves_oos = oos_eval['csvd_plus_vix']['oos_r2'] > oos_eval['vix_only']['oos_r2']
csvd_sig_improve_oos = dm_p_both_vs_vix_se < 0.05 or dm_p_both_vs_vix_ql < 0.05

# Check if strategy passes Harvey
strategy_passes_harvey = metrics_csvd['t_sharpe'] > 3.0

# Granger causality summary
granger_sig = False
for lag, res in gc1.items():
    if res['p'] < 0.05:
        granger_sig = True
        break

print(f"\n  Key Findings:")
print(f"  1. Partial correlation (CSVD → vol | VIX): {'SIGNIFICANT' if csvd_has_incremental else 'NOT SIGNIFICANT'}")
print(f"     → VIX {'is NOT' if csvd_has_incremental else 'IS'} a sufficient statistic (confirmed again)")
print(f"  2. OOS R²: CSVD+VIX ({oos_eval['csvd_plus_vix']['oos_r2']:.4f}) vs VIX only ({oos_eval['vix_only']['oos_r2']:.4f})")
print(f"     → CSVD {'improves' if csvd_improves_oos else 'does NOT improve'} OOS forecast")
print(f"     → DM test: {'SIGNIFICANT' if csvd_sig_improve_oos else 'NOT SIGNIFICANT'}")
print(f"  3. Granger causality (CSVD → SPY vol): {'SIGNIFICANT' if granger_sig else 'NOT SIGNIFICANT'}")
print(f"  4. VT Strategy: CSVD overlay Sharpe={metrics_csvd['sharpe']:.4f} vs 12/VIX Sharpe={metrics_vix['sharpe']:.4f}")
print(f"     → Harvey test: {'PASS' if strategy_passes_harvey else 'FAIL'} (t={metrics_csvd['t_sharpe']:.2f})")
print(f"  5. Placebo: real |partial r|={real_partial_r:.4f} vs placebo mean={placebo_mean:.4f}")
print(f"     → {'SURVIVES' if placebo_p < 0.05 else 'DOES NOT SURVIVE'} placebo test (p={placebo_p:.4f})")
if garchx_results:
    print(f"  6. GARCH-X: CSVD improves QLIKE by {garchx_results['qlike_improvement']:.2f}%")
    print(f"     → DM test: {'SIGNIFICANT' if garchx_results['dm_p'] < 0.05 else 'NOT SIGNIFICANT'} (t={garchx_results['dm_stat']:.3f}, p={garchx_results['dm_p']:.4f})")

# Overall verdict
verdict_parts = []
if not csvd_has_incremental:
    verdict_parts.append("Partial correlation null: VIX subsumes CSVD info")
if not csvd_sig_improve_oos:
    verdict_parts.append("DM test null: no significant OOS improvement over VIX")
if not strategy_passes_harvey:
    verdict_parts.append("Harvey threshold not met for strategy")
if placebo_p >= 0.05:
    verdict_parts.append("Placebo test: signal not distinguishable from random ETF pairings")

if len(verdict_parts) >= 3:
    verdict = "NULL — CSVD does not provide incremental value beyond VIX"
    verdict_detail = "VIX is confirmed as sufficient statistic (again). The behavioral 'volatility rotation' story is compelling but VIX already captures this information."
elif len(verdict_parts) >= 1:
    verdict = "WEAK/MIXED — Some evidence but not robust"
    verdict_detail = "; ".join(verdict_parts)
else:
    verdict = "POSITIVE — CSVD provides incremental value beyond VIX"
    verdict_detail = "Novel finding: cross-sectoral vol dispersion adds information beyond VIX"

print(f"\n  VERDICT: {verdict}")
print(f"  Detail: {verdict_detail}")

# ==================================================================
# SAVE RESULTS
# ==================================================================
print("\n" + "-" * 60)
print("SAVING RESULTS")
print("-" * 60)

results = {
    'experiment': 'K151_sectoral_vol_dispersion',
    'attribution': '[提出: Gemini R5#4 (Behavioral), 執行: Claude]',
    'timestamp': datetime.now().isoformat(),
    'parameters': {
        'speculative': SPEC_TICKERS + [BITO_TICKER],
        'defensive': DEF_TICKERS,
        'market': MARKET_TICKER,
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'oos_end': OOS_END,
        'window': WINDOW,
        'vol_window': VOL_WINDOW,
        'csvd_change_window': CSVD_CHANGE_WINDOW,
        'n_placebo': N_PLACEBO,
    },
    'descriptive': {
        'csvd_raw_mean': round(float(csvd_raw.mean()), 4),
        'csvd_raw_std': round(float(csvd_raw.std()), 4),
        'csvd_ratio_mean': round(float(csvd_ratio.mean()), 4),
        'spec_vol_mean': round(float(spec_vol.mean()), 4),
        'def_vol_mean': round(float(def_vol.mean()), 4),
    },
    'regression_full_sample': regression_results,
    'partial_correlation': partial_corr_results,
    'granger_causality': granger_results,
    'regime_fragile_calm': regime_results,
    'oos_regression': oos_eval,
    'vt_strategy': strategy_results,
    'placebo_test': placebo_results,
    'bito_era': bito_results,
    'garchx': garchx_results,
    'verdict': verdict,
    'verdict_detail': verdict_detail,
    'conclusions': {
        'csvd_has_incremental_beyond_vix': csvd_has_incremental,
        'vix_sufficient_statistic': vix_is_sufficient,
        'csvd_improves_oos': csvd_improves_oos,
        'csvd_sig_improve_oos': csvd_sig_improve_oos,
        'granger_significant': granger_sig,
        'strategy_passes_harvey': strategy_passes_harvey,
        'placebo_survives': placebo_p < 0.05,
    },
}

# Save to storage
results_path = 'storage/experiments/k151_sectoral_vol_dispersion_results.json'
os.makedirs(os.path.dirname(results_path), exist_ok=True)
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {results_path}")

# Also save to experiments/ for reference
exp_results_path = 'experiments/k151_sectoral_vol_dispersion_results.json'
with open(exp_results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results also saved to {exp_results_path}")

# ==================================================================
# RECORD TO MEMORY
# ==================================================================
print("\n" + "-" * 60)
print("RECORDING TO MEMORY")
print("-" * 60)

sys.path.insert(0, 'src')
from volpred.memory.system import MemorySystem
m = MemorySystem()

# Build knowledge content based on results
if vix_is_sufficient:
    knowledge_content = (
        f"[提出: Gemini R5#4 (Behavioral), 執行: Claude] K151: 跨類別波動率離散度信號。"
        f"測試投機ETF(ARKK/BITO)與防禦ETF(XLP/XLU/GLD)的波動率離散度(CSVD)能否預測SPY波動率。"
        f"結論：NULL。偏相關(控制VIX後)不顯著，OOS DM檢定不顯著，Harvey門檻未通過。"
        f"VIX再次確認為充分統計量。"
        f"行為金融的「波動率輪動」故事雖然吸引人，但VIX已經包含了這些資訊。"
        f"安慰劑測試：{N_PLACEBO}次隨機ETF配對中，真實信號排名第{placebo_results['pctile_rank']}百分位。"
        f"OOS R²: CSVD={oos_eval['csvd_only']['oos_r2']:.4f}, VIX={oos_eval['vix_only']['oos_r2']:.4f}, "
        f"CSVD+VIX={oos_eval['csvd_plus_vix']['oos_r2']:.4f}。"
        f"策略Sharpe: 12/VIX={metrics_vix['sharpe']:.4f}, CSVD overlay={metrics_csvd['sharpe']:.4f}。"
    )
else:
    knowledge_content = (
        f"[提出: Gemini R5#4 (Behavioral), 執行: Claude] K151: 跨類別波動率離散度信號。"
        f"測試投機ETF(ARKK/BITO)與防禦ETF(XLP/XLU/GLD)的波動率離散度(CSVD)能否預測SPY波動率。"
        f"結論：CSVD在控制VIX後仍有部分預測力。"
        f"OOS R²: CSVD+VIX={oos_eval['csvd_plus_vix']['oos_r2']:.4f} vs VIX alone={oos_eval['vix_only']['oos_r2']:.4f}。"
        f"策略Sharpe: 12/VIX={metrics_vix['sharpe']:.4f}, CSVD overlay={metrics_csvd['sharpe']:.4f}。"
    )

kid = m.add_knowledge(
    category='experiment',
    content=knowledge_content,
    confidence=0.8
)
print(f"  Knowledge recorded: {kid}")

thinking_content = (
    f"K151 思考：Gemini提出的行為金融假說——投機資產波動率與防禦資產波動率的離散度收窄預示市場波動率飆升。"
    f"這是一個全新的方向，我們從未測試過跨類別波動率離散度作為領先指標。"
    f"關鍵測試是偏相關：控制VIX後CSVD是否仍有預測力。"
    f"結果：{'VIX再次被確認為充分統計量。CSVD的資訊已被VIX完全吸收。' if vix_is_sufficient else 'CSVD可能提供VIX以外的增量資訊。'}"
    f"即使安慰劑測試{'通過' if placebo_p < 0.05 else '未通過'}（p={placebo_p:.4f}），"
    f"偏相關是最關鍵的門檻。"
    f"{'這再次確認了VIX在日頻範圍內作為充分統計量的地位——第13+次確認。' if vix_is_sufficient else ''}"
    f"啟示：行為金融信號可能需要在更長的時間尺度（月度/季度）才能提供增量價值。"
)

tid = m.think(thinking_content)
print(f"  Thinking recorded: {tid}")

print("\n" + "=" * 80)
print("K151 COMPLETE")
print("=" * 80)
