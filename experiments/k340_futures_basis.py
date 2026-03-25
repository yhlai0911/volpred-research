"""
K340: Futures Basis Structure — Can ES/NQ Futures Premium Predict Vol?
======================================================================
跳躍式探索：期貨基差（futures basis）是否包含波動率預測資訊？

Futures basis = daily log-return difference between futures and spot
  → captures the time-variation in carry (interest rate + dividend yield + risk premium)
  → backwardation signal = market stress

IMPORTANT: ES=F ≈ 10x SPY price (S&P 500 index points vs ETF shares)
  → We do NOT compute (ES=F/SPY - 1) as the level ratio is ~10x, not a basis
  → Instead we use: basis_return = log(F_t/F_{t-1}) - log(S_t/S_{t-1})
  → This captures the daily change in carry/basis regardless of price level
  → We also compute a "normalized basis level" = log(F/S) detrended

Methodology:
1. ES basis_return = r_ES - r_SPY (daily log-return difference)
2. NQ basis_return = r_NQ - r_QQQ
3. Normalized basis level = log(ES/SPY) detrended (HP filter or rolling mean)
4. Partial correlation with future 22d RV, controlling for VIX
5. Basis change speed: rapid narrowing = stress building?
6. Cross-asset: ES-NQ relative basis → relative vol?

Data: yfinance (ES=F, NQ=F, SPY, QQQ, ^VIX)
Limitations:
  - yfinance continuous futures have roll artifacts (quarterly rolls)
  - Roll artifacts create spurious jumps in basis_return on roll dates
  - Basis includes interest rate component (not pure risk premium)
  - ES=F vs SPY have different trading hours (futures trade ~23h/day)
  - We mitigate roll artifacts by winsorizing extreme basis_return values

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 30:
        return np.nan, np.nan, len(x)
    bx = np.polyfit(z, x, 1)
    by = np.polyfit(z, y, 1)
    rx = x - np.polyval(bx, z)
    ry = y - np.polyval(by, z)
    r, p = stats.pearsonr(rx, ry)
    return r, p, len(x)

def newey_west_t(X_mat, y, lags=22):
    """OLS with Newey-West t-stats. X_mat should include intercept column."""
    mask = np.all(np.isfinite(X_mat), axis=1) & np.isfinite(y)
    X = X_mat[mask]
    y = y[mask]
    n, k = X.shape
    if n < 50:
        return np.full(k, np.nan), np.full(k, np.nan), n
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    # Newey-West HAC
    S = np.zeros((k, k))
    for t in range(n):
        S += resid[t]**2 * np.outer(X[t], X[t])
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        for t in range(lag, n):
            S += w * resid[t] * resid[t-lag] * (np.outer(X[t], X[t-lag]) + np.outer(X[t-lag], X[t]))
    S /= n
    bread = np.linalg.inv(X.T @ X / n)
    V = bread @ S @ bread / n
    se = np.sqrt(np.diag(V))
    t_stats = beta / se
    return beta, t_stats, n

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K340: Futures Basis Structure — Vol Prediction")
print("=" * 70)

print("\n[1/8] Downloading data from yfinance...")

tickers = {
    'SPY': 'SPY',
    'QQQ': 'QQQ',
    'ES': 'ES=F',
    'NQ': 'NQ=F',
    'VIX': '^VIX',
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2010-01-01", end="2026-04-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    data[name] = df[col].copy()
    data[name].name = name
    print(f"  {name} ({ticker}): {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} obs)")

# Align all series
df_all = pd.DataFrame(data)
df_all = df_all.dropna()
print(f"\n  Aligned dataset: {df_all.index[0].strftime('%Y-%m-%d')} to {df_all.index[-1].strftime('%Y-%m-%d')} ({len(df_all)} obs)")

# Verify price scale
es_spy_ratio = (df_all['ES'] / df_all['SPY']).median()
nq_qqq_ratio = (df_all['NQ'] / df_all['QQQ']).median()
print(f"\n  Price scale check:")
print(f"    ES/SPY median ratio: {es_spy_ratio:.2f}x (ES=F is ~10x SPY)")
print(f"    NQ/QQQ median ratio: {nq_qqq_ratio:.2f}x (NQ=F is ~50x QQQ)")

# ============================================================
# 2. Compute futures basis measures
# ============================================================
print("\n[2/8] Computing futures basis measures...")

# Log returns
df_all['r_SPY'] = np.log(df_all['SPY'] / df_all['SPY'].shift(1))
df_all['r_QQQ'] = np.log(df_all['QQQ'] / df_all['QQQ'].shift(1))
df_all['r_ES'] = np.log(df_all['ES'] / df_all['ES'].shift(1))
df_all['r_NQ'] = np.log(df_all['NQ'] / df_all['NQ'].shift(1))

# Basis return = futures return - spot return
# This captures daily change in basis (carry cost variation)
df_all['ES_basis_ret'] = df_all['r_ES'] - df_all['r_SPY']
df_all['NQ_basis_ret'] = df_all['r_NQ'] - df_all['r_QQQ']

# Winsorize at 1st/99th percentile to remove roll artifacts
for col in ['ES_basis_ret', 'NQ_basis_ret']:
    p01 = df_all[col].quantile(0.01)
    p99 = df_all[col].quantile(0.99)
    n_clip = ((df_all[col] < p01) | (df_all[col] > p99)).sum()
    df_all[col] = df_all[col].clip(p01, p99)
    print(f"  {col}: winsorized {n_clip} obs at 1%/99%")

# Normalized basis level = log(F/S) - rolling 63-day mean
# This removes the structural level difference (ES≈10*SPY)
df_all['log_ES_SPY'] = np.log(df_all['ES'] / df_all['SPY'])
df_all['log_NQ_QQQ'] = np.log(df_all['NQ'] / df_all['QQQ'])
df_all['ES_basis_level'] = df_all['log_ES_SPY'] - df_all['log_ES_SPY'].rolling(63).mean()
df_all['NQ_basis_level'] = df_all['log_NQ_QQQ'] - df_all['log_NQ_QQQ'].rolling(63).mean()

# Cumulative basis return (rolling 22d sum of basis_ret)
df_all['ES_basis_cum22'] = df_all['ES_basis_ret'].rolling(22).sum()
df_all['NQ_basis_cum22'] = df_all['NQ_basis_ret'].rolling(22).sum()

# Basis return rolling 5d sum (short-term change)
df_all['ES_basis_cum5'] = df_all['ES_basis_ret'].rolling(5).sum()

# Basis spread (ES - NQ basis return)
df_all['basis_spread_ret'] = df_all['ES_basis_ret'] - df_all['NQ_basis_ret']

# Returns for RV computation
df_all['SPY_ret'] = df_all['SPY'].pct_change()
df_all['QQQ_ret'] = df_all['QQQ'].pct_change()

# Realized volatility (forward-looking 22d, annualized %)
df_all['RV22_fwd'] = df_all['SPY_ret'].rolling(22).std().shift(-22) * np.sqrt(252) * 100
df_all['RV22_fwd_QQQ'] = df_all['QQQ_ret'].rolling(22).std().shift(-22) * np.sqrt(252) * 100

# Current RV (backward-looking 22d)
df_all['RV22_cur'] = df_all['SPY_ret'].rolling(22).std() * np.sqrt(252) * 100

print(f"\n  ES basis return stats (daily, after winsorization):")
print(f"    Mean:   {df_all['ES_basis_ret'].mean()*10000:.2f} bps")
print(f"    Std:    {df_all['ES_basis_ret'].std()*10000:.2f} bps")
print(f"    Min:    {df_all['ES_basis_ret'].min()*10000:.2f} bps")
print(f"    Max:    {df_all['ES_basis_ret'].max()*10000:.2f} bps")
print(f"    Skew:   {df_all['ES_basis_ret'].skew():.2f}")
print(f"    Kurt:   {df_all['ES_basis_ret'].kurtosis():.2f}")

print(f"\n  NQ basis return stats (daily, after winsorization):")
print(f"    Mean:   {df_all['NQ_basis_ret'].mean()*10000:.2f} bps")
print(f"    Std:    {df_all['NQ_basis_ret'].std()*10000:.2f} bps")

print(f"\n  ES basis level (detrended) stats:")
print(f"    Mean:   {df_all['ES_basis_level'].mean()*100:.4f}%")
print(f"    Std:    {df_all['ES_basis_level'].std()*100:.4f}%")

# ============================================================
# 3. Correlation analysis: basis → future vol
# ============================================================
print("\n[3/8] Correlation analysis: basis measures → future 22d RV...")

df_clean = df_all.dropna(subset=['ES_basis_ret', 'NQ_basis_ret', 'ES_basis_level',
                                  'ES_basis_cum22', 'RV22_fwd', 'VIX']).copy()
print(f"  Clean sample: {len(df_clean)} obs")

# Table of correlations
print(f"\n  {'Predictor':<25} {'Raw r':<10} {'Raw p':<12} {'Partial r|VIX':<15} {'Partial p':<12}")
print(f"  {'-'*74}")

predictors = {
    'ES_basis_ret': 'ES basis return (1d)',
    'NQ_basis_ret': 'NQ basis return (1d)',
    'ES_basis_level': 'ES basis level (detr.)',
    'ES_basis_cum5': 'ES basis cum 5d',
    'ES_basis_cum22': 'ES basis cum 22d',
    'basis_spread_ret': 'ES-NQ spread return',
    'VIX': 'VIX (benchmark)',
}

corr_results = {}
for col, label in predictors.items():
    mask = np.isfinite(df_clean[col]) & np.isfinite(df_clean['RV22_fwd'])
    if mask.sum() < 50:
        continue
    r_raw, p_raw = stats.pearsonr(df_clean.loc[mask, col], df_clean.loc[mask, 'RV22_fwd'])
    pr, pp, n = partial_corr(df_clean[col].values, df_clean['RV22_fwd'].values, df_clean['VIX'].values)
    print(f"  {label:<25} {r_raw:>+.4f}    {p_raw:<12.2e} {pr:>+.4f}         {pp:<12.2e}")
    corr_results[col] = {'raw_r': r_raw, 'raw_p': p_raw, 'partial_r': pr, 'partial_p': pp}

# ============================================================
# 4. Newey-West regressions
# ============================================================
print(f"\n[4/8] Newey-West regressions...")

# Clean data
df_reg = df_clean.dropna(subset=['ES_basis_ret', 'ES_basis_level', 'ES_basis_cum22',
                                  'RV22_fwd', 'VIX', 'RV22_cur']).copy()
y = df_reg['RV22_fwd'].values
n_reg = len(df_reg)

print(f"  Regression sample: {n_reg} obs\n")

# Model 1: baseline: RV22_fwd ~ VIX
X1 = np.column_stack([np.ones(n_reg), df_reg['VIX'].values])
b1, t1, n1 = newey_west_t(X1, y)
print(f"  Model 1: RV22_fwd ~ VIX")
print(f"    VIX:  β={b1[1]:.4f}, NW_t={t1[1]:.2f}")

# Model 2: RV22_fwd ~ VIX + ES_basis_ret
X2 = np.column_stack([np.ones(n_reg), df_reg['VIX'].values, df_reg['ES_basis_ret'].values])
b2, t2, n2 = newey_west_t(X2, y)
print(f"\n  Model 2: RV22_fwd ~ VIX + ES_basis_ret")
print(f"    VIX:         β={b2[1]:.4f}, NW_t={t2[1]:.2f}")
print(f"    ES_basis_ret: β={b2[2]:.4f}, NW_t={t2[2]:.2f}")

# Model 3: RV22_fwd ~ VIX + ES_basis_level
X3 = np.column_stack([np.ones(n_reg), df_reg['VIX'].values, df_reg['ES_basis_level'].values])
b3, t3, n3 = newey_west_t(X3, y)
print(f"\n  Model 3: RV22_fwd ~ VIX + ES_basis_level")
print(f"    VIX:            β={b3[1]:.4f}, NW_t={t3[1]:.2f}")
print(f"    ES_basis_level: β={b3[2]:.4f}, NW_t={t3[2]:.2f}")

# Model 4: RV22_fwd ~ VIX + ES_basis_cum22
X4 = np.column_stack([np.ones(n_reg), df_reg['VIX'].values, df_reg['ES_basis_cum22'].values])
b4, t4, n4 = newey_west_t(X4, y)
print(f"\n  Model 4: RV22_fwd ~ VIX + ES_basis_cum22")
print(f"    VIX:            β={b4[1]:.4f}, NW_t={t4[1]:.2f}")
print(f"    ES_basis_cum22: β={b4[2]:.4f}, NW_t={t4[2]:.2f}")

# Model 5: Kitchen sink: VIX + basis_ret + basis_level + basis_cum22
X5 = np.column_stack([np.ones(n_reg), df_reg['VIX'].values,
                       df_reg['ES_basis_ret'].values,
                       df_reg['ES_basis_level'].values,
                       df_reg['ES_basis_cum22'].values])
b5, t5, n5 = newey_west_t(X5, y)
print(f"\n  Model 5 (kitchen sink): RV22_fwd ~ VIX + basis_ret + basis_level + basis_cum22")
print(f"    VIX:            β={b5[1]:.4f}, NW_t={t5[1]:.2f}")
print(f"    ES_basis_ret:   β={b5[2]:.4f}, NW_t={t5[2]:.2f}")
print(f"    ES_basis_level: β={b5[3]:.4f}, NW_t={t5[3]:.2f}")
print(f"    ES_basis_cum22: β={b5[4]:.4f}, NW_t={t5[4]:.2f}")

# ============================================================
# 5. Out-of-sample test
# ============================================================
print(f"\n[5/8] Out-of-sample test (expanding window, non-overlapping 22d)...")

df_oos = df_all.dropna(subset=['ES_basis_ret', 'ES_basis_level', 'ES_basis_cum22',
                                'RV22_fwd', 'VIX', 'RV22_cur']).copy()
df_oos = df_oos.sort_index()

oos_start = pd.Timestamp('2015-01-01')
train_min = 500

idx_start = df_oos.index.searchsorted(oos_start)
if idx_start < train_min:
    idx_start = train_min

errors_A = []  # VIX only
errors_B = []  # VIX + basis_ret
errors_C = []  # VIX + basis_level
errors_D = []  # VIX + basis_cum22
actuals = []
dates_oos = []

for i in range(idx_start, len(df_oos) - 22, 22):
    train = df_oos.iloc[:i]
    test_row = df_oos.iloc[i]

    y_t = train['RV22_fwd'].values
    vix_t = train['VIX'].values
    bret_t = train['ES_basis_ret'].values
    blevel_t = train['ES_basis_level'].values
    bcum22_t = train['ES_basis_cum22'].values

    valid = np.isfinite(y_t) & np.isfinite(vix_t) & np.isfinite(bret_t) & np.isfinite(blevel_t) & np.isfinite(bcum22_t)
    if valid.sum() < 100:
        continue

    actual = test_row['RV22_fwd']
    if not np.isfinite(actual):
        continue

    y_v = y_t[valid]
    vix_v = vix_t[valid]
    bret_v = bret_t[valid]
    blevel_v = blevel_t[valid]
    bcum22_v = bcum22_t[valid]
    n_t = len(y_v)

    # Model A: VIX only
    XA = np.column_stack([np.ones(n_t), vix_v])
    bA = np.linalg.lstsq(XA, y_v, rcond=None)[0]
    pred_A = bA[0] + bA[1] * test_row['VIX']

    # Model B: VIX + basis_ret
    XB = np.column_stack([np.ones(n_t), vix_v, bret_v])
    bB = np.linalg.lstsq(XB, y_v, rcond=None)[0]
    pred_B = bB[0] + bB[1] * test_row['VIX'] + bB[2] * test_row['ES_basis_ret']

    # Model C: VIX + basis_level
    XC = np.column_stack([np.ones(n_t), vix_v, blevel_v])
    bC = np.linalg.lstsq(XC, y_v, rcond=None)[0]
    pred_C = bC[0] + bC[1] * test_row['VIX'] + bC[2] * test_row['ES_basis_level']

    # Model D: VIX + basis_cum22
    XD = np.column_stack([np.ones(n_t), vix_v, bcum22_v])
    bD = np.linalg.lstsq(XD, y_v, rcond=None)[0]
    pred_D = bD[0] + bD[1] * test_row['VIX'] + bD[2] * test_row['ES_basis_cum22']

    errors_A.append((actual - pred_A)**2)
    errors_B.append((actual - pred_B)**2)
    errors_C.append((actual - pred_C)**2)
    errors_D.append((actual - pred_D)**2)
    actuals.append(actual)
    dates_oos.append(test_row.name)

errors_A = np.array(errors_A)
errors_B = np.array(errors_B)
errors_C = np.array(errors_C)
errors_D = np.array(errors_D)
actuals = np.array(actuals)

print(f"\n  OOS period: {dates_oos[0].strftime('%Y-%m-%d')} to {dates_oos[-1].strftime('%Y-%m-%d')}")
print(f"  OOS windows: {len(errors_A)} non-overlapping 22-day forecasts")

mse_A = errors_A.mean()
mse_B = errors_B.mean()
mse_C = errors_C.mean()
mse_D = errors_D.mean()
var_actual = actuals.var()

oos_r2_A = 1 - mse_A / var_actual
oos_r2_B = 1 - mse_B / var_actual
oos_r2_C = 1 - mse_C / var_actual
oos_r2_D = 1 - mse_D / var_actual

print(f"\n  {'Model':<40} {'MSE':<10} {'OOS R²':<10} {'ΔR² vs A':<10}")
print(f"  {'-'*70}")
print(f"  {'A: VIX only':<40} {mse_A:<10.4f} {oos_r2_A:<10.4f} {'—':<10}")
print(f"  {'B: VIX + basis_ret':<40} {mse_B:<10.4f} {oos_r2_B:<10.4f} {oos_r2_B - oos_r2_A:+.4f}")
print(f"  {'C: VIX + basis_level':<40} {mse_C:<10.4f} {oos_r2_C:<10.4f} {oos_r2_C - oos_r2_A:+.4f}")
print(f"  {'D: VIX + basis_cum22':<40} {mse_D:<10.4f} {oos_r2_D:<10.4f} {oos_r2_D - oos_r2_A:+.4f}")

# DM tests: each model vs A
def dm_test(e1, e2, lags=22):
    d = e1 - e2
    T = len(d)
    dm_mean = d.mean()
    gamma0 = np.var(d)
    dm_var = gamma0
    for lag in range(1, min(lags, T)):
        w = 1 - lag / (lags + 1)
        gamma_lag = np.cov(d[lag:], d[:-lag])[0, 1]
        dm_var += 2 * w * gamma_lag
    dm_t = dm_mean / np.sqrt(dm_var / T) if dm_var > 0 else 0
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))
    return dm_t, dm_p

print(f"\n  Diebold-Mariano tests (positive t = model improvement over VIX-only):")
for name, errs in [('B: basis_ret', errors_B), ('C: basis_level', errors_C), ('D: basis_cum22', errors_D)]:
    t_dm, p_dm = dm_test(errors_A, errs)
    sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else "n.s."
    print(f"    A vs {name}: DM_t={t_dm:+.3f}, p={p_dm:.4f} {sig}")

# ============================================================
# 6. Regime analysis
# ============================================================
print(f"\n[6/8] Regime analysis (basis level quintiles)...")

df_regime = df_clean.copy()
df_regime['ES_basis_level_q'] = pd.qcut(df_regime['ES_basis_level'], 5, labels=False, duplicates='drop')

print(f"\n  Quintile analysis (ES basis level, detrended → future 22d RV):")
print(f"  {'Q':<4} {'Mean Basis Lv':<16} {'Mean RV22':<12} {'Med RV22':<12} {'Mean VIX':<10} {'N':<6}")
print(f"  {'-'*60}")
for q in sorted(df_regime['ES_basis_level_q'].dropna().unique()):
    sub = df_regime[df_regime['ES_basis_level_q'] == q]
    rv_sub = sub['RV22_fwd'].dropna()
    if len(rv_sub) > 0:
        print(f"  Q{int(q):<3} {sub['ES_basis_level'].mean()*100:>+.4f}%       {rv_sub.mean():<12.2f} {rv_sub.median():<12.2f} {sub['VIX'].mean():<10.1f} {len(rv_sub):<6}")

# Basis return quintiles
df_regime['ES_basis_ret_q'] = pd.qcut(df_regime['ES_basis_ret'], 5, labels=False, duplicates='drop')
print(f"\n  Quintile analysis (ES basis return → future 22d RV):")
print(f"  {'Q':<4} {'Mean Basis Ret (bps)':<22} {'Mean RV22':<12} {'Med RV22':<12} {'N':<6}")
print(f"  {'-'*56}")
for q in sorted(df_regime['ES_basis_ret_q'].dropna().unique()):
    sub = df_regime[df_regime['ES_basis_ret_q'] == q]
    rv_sub = sub['RV22_fwd'].dropna()
    if len(rv_sub) > 0:
        print(f"  Q{int(q):<3} {sub['ES_basis_ret'].mean()*10000:>+.2f} bps             {rv_sub.mean():<12.2f} {rv_sub.median():<12.2f} {len(rv_sub):<6}")

# ============================================================
# 7. Cross-asset: ES-NQ basis → relative vol
# ============================================================
print(f"\n[7/8] Cross-asset: ES-NQ basis spread → relative vol...")

df_cross = df_all.dropna(subset=['basis_spread_ret', 'RV22_fwd', 'RV22_fwd_QQQ', 'VIX']).copy()
df_cross['rel_vol'] = df_cross['RV22_fwd'] / df_cross['RV22_fwd_QQQ']

# Rolling 22d cumulative spread
df_cross['spread_cum22'] = df_cross['basis_spread_ret'].rolling(22).sum()
df_cross = df_cross.dropna(subset=['spread_cum22'])

r_spread, p_spread = stats.pearsonr(df_cross['spread_cum22'], df_cross['rel_vol'])
pr_spread, pp_spread, n_spread = partial_corr(
    df_cross['spread_cum22'].values, df_cross['rel_vol'].values, df_cross['VIX'].values)

print(f"  Spread cum22 → relative vol (SPY/QQQ):")
print(f"    Raw:     r={r_spread:+.4f}, p={p_spread:.4e}, n={len(df_cross)}")
print(f"    |VIX:    r={pr_spread:+.4f}, p={pp_spread:.4e}")

# Also test: spread → QQQ vol (negative = QQQ basis more negative = QQQ stress)
r_spread_qqq, p_spread_qqq = stats.pearsonr(df_cross['spread_cum22'], df_cross['RV22_fwd_QQQ'])
print(f"  Spread cum22 → QQQ RV22:")
print(f"    Raw:     r={r_spread_qqq:+.4f}, p={p_spread_qqq:.4e}")

# ============================================================
# 8. Rolling correlation stability
# ============================================================
print(f"\n[8/8] Rolling correlation stability (252-day window)...")

for pred_col, label in [('ES_basis_ret', 'ES basis return'),
                         ('ES_basis_level', 'ES basis level'),
                         ('ES_basis_cum22', 'ES basis cum22')]:
    rc = df_all[pred_col].rolling(252).corr(df_all['RV22_fwd']).dropna()
    if len(rc) > 100:
        frac_neg = (rc < 0).mean()
        print(f"\n  {label}:")
        print(f"    Mean corr: {rc.mean():+.4f}, Std: {rc.std():.4f}")
        print(f"    Range: [{rc.min():+.4f}, {rc.max():+.4f}]")
        print(f"    Fraction negative: {frac_neg:.1%}")

# Year-by-year for basis_level (the most promising predictor based on partial corr)
print(f"\n  Year-by-year: ES basis level (detrended) → RV22_fwd:")
df_yearly = df_all.dropna(subset=['ES_basis_level', 'RV22_fwd'])
yearly_corrs = []
for year in range(2012, 2026):
    yr_data = df_yearly[df_yearly.index.year == year]
    if len(yr_data) > 50:
        r_yr, p_yr = stats.pearsonr(yr_data['ES_basis_level'], yr_data['RV22_fwd'])
        sig = "*" if p_yr < 0.05 else ""
        print(f"    {year}: r={r_yr:+.4f} (p={p_yr:.3f}) {sig}")
        yearly_corrs.append(r_yr)

if yearly_corrs:
    sign_consistency = sum(1 for r in yearly_corrs if r < 0) / len(yearly_corrs)
    print(f"    Sign consistency (negative): {sign_consistency:.0%}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K340 Futures Basis Structure")
print("=" * 70)

# Collect key results
raw_r_level = corr_results.get('ES_basis_level', {}).get('raw_r', np.nan)
raw_p_level = corr_results.get('ES_basis_level', {}).get('raw_p', np.nan)
partial_r_level = corr_results.get('ES_basis_level', {}).get('partial_r', np.nan)
partial_p_level = corr_results.get('ES_basis_level', {}).get('partial_p', np.nan)

raw_r_ret = corr_results.get('ES_basis_ret', {}).get('raw_r', np.nan)
partial_r_ret = corr_results.get('ES_basis_ret', {}).get('partial_r', np.nan)

raw_r_cum22 = corr_results.get('ES_basis_cum22', {}).get('raw_r', np.nan)
partial_r_cum22 = corr_results.get('ES_basis_cum22', {}).get('partial_r', np.nan)

dm_B_t, dm_B_p = dm_test(errors_A, errors_B)
dm_C_t, dm_C_p = dm_test(errors_A, errors_C)
dm_D_t, dm_D_p = dm_test(errors_A, errors_D)

# Determine conclusion
any_partial_sig = any(
    corr_results.get(k, {}).get('partial_p', 1.0) < 0.05
    for k in ['ES_basis_ret', 'ES_basis_level', 'ES_basis_cum22']
)
any_dm_sig = min(dm_B_p, dm_C_p, dm_D_p) < 0.05
any_nw_sig = any(abs(t) > 1.96 for t in [t2[2], t3[2], t4[2]] if not np.isnan(t))

if any_dm_sig and any_partial_sig:
    conclusion = "POSITIVE: Futures basis adds significant vol prediction beyond VIX"
elif any_partial_sig and not any_dm_sig:
    conclusion = "WEAK POSITIVE: Statistically significant in-sample partial correlation but OOS DM test not significant — likely overfitting or tiny effect"
elif not any_partial_sig:
    conclusion = "NULL: Futures basis does not add incremental vol prediction beyond VIX"
else:
    conclusion = "MIXED"

print(f"\n  Conclusion: {conclusion}")

print(f"\n  Key findings:")
print(f"    1. ES basis return (daily r_ES - r_SPY):")
print(f"       Raw r = {raw_r_ret:+.4f}, Partial r|VIX = {partial_r_ret:+.4f}")
print(f"    2. ES basis level (detrended log(ES/SPY)):")
print(f"       Raw r = {raw_r_level:+.4f}, Partial r|VIX = {partial_r_level:+.4f}")
print(f"    3. ES basis cum 22d:")
print(f"       Raw r = {raw_r_cum22:+.4f}, Partial r|VIX = {partial_r_cum22:+.4f}")
print(f"    4. OOS results:")
print(f"       VIX only R² = {oos_r2_A:.4f}")
print(f"       +basis_ret:   R² = {oos_r2_B:.4f} (ΔR²={oos_r2_B-oos_r2_A:+.4f}, DM p={dm_B_p:.4f})")
print(f"       +basis_level: R² = {oos_r2_C:.4f} (ΔR²={oos_r2_C-oos_r2_A:+.4f}, DM p={dm_C_p:.4f})")
print(f"       +basis_cum22: R² = {oos_r2_D:.4f} (ΔR²={oos_r2_D-oos_r2_A:+.4f}, DM p={dm_D_p:.4f})")

print(f"\n  Cross-asset (ES-NQ basis spread → SPY/QQQ relative vol):")
print(f"    r = {r_spread:+.4f}, partial r|VIX = {pr_spread:+.4f}")

print(f"\n  Limitations:")
print(f"    - yfinance continuous futures: quarterly roll artifacts (winsorized)")
print(f"    - Basis includes interest rate component, not pure risk premium")
print(f"    - ES=F trades ~23h/day vs SPY 6.5h → timing mismatch")
print(f"    - Forward RV uses close-to-close daily returns as proxy")
print(f"    - Overlapping 22d RV → autocorrelation (NW SE used)")

# Save results
results = {
    "experiment": "K340",
    "title": "Futures Basis Structure — Can ES/NQ Futures Premium Predict Vol?",
    "data_source": "yfinance (ES=F, NQ=F, SPY, QQQ, ^VIX)",
    "data_period": f"{df_all.index[0].strftime('%Y-%m-%d')} to {df_all.index[-1].strftime('%Y-%m-%d')}",
    "aligned_obs": int(len(df_all)),
    "price_scale": {"ES_SPY_ratio": round(float(es_spy_ratio), 2),
                     "NQ_QQQ_ratio": round(float(nq_qqq_ratio), 2)},
    "es_basis_ret_stats_bps": {
        "mean": round(float(df_all['ES_basis_ret'].mean()*10000), 2),
        "std": round(float(df_all['ES_basis_ret'].std()*10000), 2),
    },
    "correlation_table": {
        k: {"raw_r": round(v['raw_r'], 4), "partial_r_VIX": round(v['partial_r'], 4),
            "partial_p": round(v['partial_p'], 6)}
        for k, v in corr_results.items()
    },
    "newey_west_regressions": {
        "model2_VIX_basisret": {"beta_basis": round(float(b2[2]), 4), "NW_t": round(float(t2[2]), 2)},
        "model3_VIX_basislevel": {"beta_basis": round(float(b3[2]), 4), "NW_t": round(float(t3[2]), 2)},
        "model4_VIX_basiscum22": {"beta_basis": round(float(b4[2]), 4), "NW_t": round(float(t4[2]), 2)},
    },
    "oos_results": {
        "period": f"{dates_oos[0].strftime('%Y-%m-%d')} to {dates_oos[-1].strftime('%Y-%m-%d')}",
        "n_windows": len(errors_A),
        "VIX_only_R2": round(float(oos_r2_A), 4),
        "VIX_basisret_R2": round(float(oos_r2_B), 4),
        "VIX_basislevel_R2": round(float(oos_r2_C), 4),
        "VIX_basiscum22_R2": round(float(oos_r2_D), 4),
        "DM_B": {"t": round(float(dm_B_t), 3), "p": round(float(dm_B_p), 4)},
        "DM_C": {"t": round(float(dm_C_t), 3), "p": round(float(dm_C_p), 4)},
        "DM_D": {"t": round(float(dm_D_t), 3), "p": round(float(dm_D_p), 4)},
    },
    "cross_asset": {
        "ES_NQ_spread_to_relVol": {"r": round(float(r_spread), 4), "p": float(f"{p_spread:.4e}")},
        "partial_VIX": {"r": round(float(pr_spread), 4), "p": float(f"{pp_spread:.4e}")},
    },
    "conclusion": conclusion,
    "limitations": [
        "yfinance continuous futures have quarterly roll artifacts (winsorized at 1/99%)",
        "Basis includes interest rate component, not pure risk premium",
        "ES=F trades ~23h/day vs SPY 6.5h (trading hours mismatch)",
        "Forward RV uses close-to-close daily returns as proxy",
        "Overlapping 22d RV windows → autocorrelation (Newey-West SE used)",
    ],
    "timestamp": datetime.now().isoformat(),
}

output_path = "experiments/k340_futures_basis_results.json"
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K340 COMPLETE")
print("=" * 70)
