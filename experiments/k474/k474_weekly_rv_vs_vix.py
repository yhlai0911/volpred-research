#!/usr/bin/env python3
"""
K474: Weekly Lagged RV vs VIX — 5-Period Cross-OOS Validation

Background:
  K473 found: weekly lagged RV (HAR-style) QLIKE=0.382 significantly beats
  VIX+RV 0.511 (DM p=0.044) in 2023-2025 OOS. This challenges VIX sufficiency
  (confirmed 27+ times at daily frequency but possibly not at weekly).

  This experiment validates across 5 additional OOS periods to determine
  if the finding is robust or period-specific.

5 OOS periods:
  1. 2013-2014 (post-GFC recovery)
  2. 2015-2016 (low volatility)
  3. 2017-2018 (Volmageddon)
  4. 2019-2020 (COVID)
  5. 2021-2022 (rate hikes)
  (+K473's 2023-2025 as period 6, already known)

Models:
  M1: Lagged RV only — log(RV_1w), log(RV_5w), log(RV_21w) → log(next-week RV) (log-HAR)
  M2: VIX only — log(VIX_var_weekly) → log(next-week RV)
  M3: VIX + Lagged RV — all features → log(next-week RV)

  All models use log-level regression (Corsi 2009 log-HAR variant) to ensure
  positive forecasts. Forecasts are exp(predicted log) with Jensen's inequality
  correction: exp(log_pred + 0.5 * sigma_resid^2).

Data: SPY weekly (Friday-to-Friday), 2005-2026
  Weekly RV = sum of daily squared returns within week
  Weekly VIX = Friday close

For each OOS period:
  Expanding window OLS (all data up to t-1 → predict t)
  Evaluation: QLIKE, MSE, R², DM test (M1 vs M2, M1 vs M3)

Decision rule:
  M1 wins ≥4/6 periods → VIX sufficiency rejected at weekly frequency
  M1 wins ≤2/6 periods → K473 is period-specific

References:
  - Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility" JFE
  - Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies" JoE
  - Diebold & Mariano (1995) "Comparing Predictive Accuracy" JBES
  - K473 (this project): weekly attention vol, lagged RV finding
  - K129: VIX sufficiency boundary map
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
ASSET = 'SPY'
DATA_START = '2005-01-01'
DATA_END = '2026-03-26'

OOS_PERIODS = {
    'P1_2013_2014': ('2013-01-01', '2014-12-31', 'Post-GFC recovery'),
    'P2_2015_2016': ('2015-01-01', '2016-12-31', 'Low volatility'),
    'P3_2017_2018': ('2017-01-01', '2018-12-31', 'Volmageddon'),
    'P4_2019_2020': ('2019-01-01', '2020-12-31', 'COVID'),
    'P5_2021_2022': ('2021-01-01', '2022-12-31', 'Rate hikes'),
    'P6_2023_2025': ('2023-01-01', '2025-12-31', 'Post-hike / K473 period'),
}

MIN_TRAIN = 104  # ~2 years of weekly data

# ============================================================
# Helper functions
# ============================================================

def qlike_loss_vec(realized, forecast):
    """Per-observation QLIKE losses: rv/f - log(rv/f) - 1"""
    valid = (realized > 0) & (forecast > 0) & np.isfinite(realized) & np.isfinite(forecast)
    losses = np.full_like(realized, np.nan, dtype=float)
    r = realized[valid]
    f = forecast[valid]
    ratio = r / f
    losses[valid] = ratio - np.log(ratio) - 1
    return losses


def qlike_mean(realized, forecast):
    """Mean QLIKE loss"""
    losses = qlike_loss_vec(realized, forecast)
    valid = np.isfinite(losses)
    if valid.sum() == 0:
        return np.nan, 0
    return np.nanmean(losses), int(valid.sum())


def dm_test(losses1, losses2, h=1):
    """Diebold-Mariano test (two-sided).
    Positive t-stat → model 1 has higher loss (model 2 is better).
    Negative t-stat → model 1 has lower loss (model 1 is better).
    """
    # Align valid observations
    valid = np.isfinite(losses1) & np.isfinite(losses2)
    d = losses1[valid] - losses2[valid]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with ceil(n^(1/3)) lags)
    max_lag = max(1, int(np.ceil(n ** (1/3))))
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max_lag + 1):
        if k >= n:
            break
        weight = 1 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * weight * gamma_k
    hac_var = max(hac_var, 1e-20)
    dm_stat = d_mean / np.sqrt(hac_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value


# ============================================================
# Data Download & Weekly Aggregation
# ============================================================
print("=" * 70)
print("K474: Weekly Lagged RV vs VIX — Cross-OOS Validation")
print("=" * 70)

t0 = time.time()

print(f"\nDownloading {ASSET} data {DATA_START} to {DATA_END}...")
spy = yf.download(ASSET, start=DATA_START, end=DATA_END, auto_adjust=True)
print(f"  Daily observations: {len(spy)}")

print("Downloading ^VIX...")
vix = yf.download('^VIX', start=DATA_START, end=DATA_END, auto_adjust=True)
print(f"  VIX observations: {len(vix)}")

# Flatten MultiIndex columns if needed
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
    vix.columns = vix.columns.get_level_values(0)

# Daily log returns and squared returns
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['ret_sq'] = spy['ret'] ** 2

# Merge VIX
spy = spy.join(vix[['Close']].rename(columns={'Close': 'VIX'}), how='left')
spy['VIX'] = spy['VIX'].ffill()

# Weekly aggregation (Friday-to-Friday)
spy['week'] = spy.index.to_period('W-FRI')
weekly = spy.groupby('week').agg(
    rv_weekly=('ret_sq', 'sum'),       # Weekly RV = sum of daily r²
    vix_friday=('VIX', 'last'),        # Friday close VIX
    n_days=('ret_sq', 'count'),        # Trading days in week
    close_friday=('Close', 'last'),    # Friday close price
).dropna()

# Convert VIX to weekly variance scale: (VIX/100)^2 / 52
weekly['vix_var_weekly'] = (weekly['vix_friday'] / 100) ** 2 / 52

# Filter: need at least 3 trading days in the week
weekly = weekly[weekly['n_days'] >= 3].copy()
weekly.index = weekly.index.to_timestamp()

print(f"\nWeekly observations: {len(weekly)}")
print(f"Period: {weekly.index[0].strftime('%Y-%m-%d')} to {weekly.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# Descriptive statistics
# ============================================================
rv = weekly['rv_weekly']
print(f"\n--- Descriptive Statistics (Weekly RV) ---")
print(f"  Mean:   {rv.mean():.6f}  ({rv.mean()*10000:.2f} bps²)")
print(f"  Median: {rv.median():.6f}")
print(f"  Std:    {rv.std():.6f}")
print(f"  Skew:   {rv.skew():.2f}")
print(f"  Kurt:   {rv.kurtosis():.2f}")
print(f"  Min:    {rv.min():.8f}")
print(f"  Max:    {rv.max():.6f}")

vv = weekly['vix_var_weekly']
print(f"\n--- VIX Weekly Variance ---")
print(f"  Mean:   {vv.mean():.6f}")
print(f"  Median: {vv.median():.6f}")
print(f"  Corr(RV, VIX_var): {rv.corr(vv):.4f}")
print(f"  Corr(log RV, log VIX_var): {np.log(rv).corr(np.log(vv)):.4f}")

# ============================================================
# Construct features (all lagged by 1 week)
# ============================================================
# Use log-level for all features and target (log-HAR specification)
weekly['log_rv'] = np.log(weekly['rv_weekly'])
weekly['log_rv_1w'] = weekly['log_rv'].shift(1)                            # Last week
weekly['log_rv_5w'] = weekly['log_rv'].rolling(5).mean().shift(1)          # 5-week avg (monthly)
weekly['log_rv_21w'] = weekly['log_rv'].rolling(21).mean().shift(1)        # 21-week avg (~5 months)
weekly['log_vix_var'] = np.log(weekly['vix_var_weekly']).shift(1)           # Last week VIX var

# Target
weekly['target_log'] = weekly['log_rv']  # log(next-week RV)
weekly['target'] = weekly['rv_weekly']    # next-week RV (for QLIKE evaluation)

# Drop NAs from rolling
weekly = weekly.dropna(subset=['log_rv_1w', 'log_rv_5w', 'log_rv_21w', 'log_vix_var', 'target'])
print(f"\n  Usable weekly obs (after lags): {len(weekly)}")

# ============================================================
# Cross-OOS Validation
# ============================================================
results = {}
all_period_forecasts = {}  # For pooled analysis

for period_id, (oos_start, oos_end, description) in OOS_PERIODS.items():
    print(f"\n{'='*60}")
    print(f"  {period_id}: {description} ({oos_start} to {oos_end})")
    print(f"{'='*60}")

    # Define OOS mask
    oos_mask = (weekly.index >= oos_start) & (weekly.index <= oos_end)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    if n_oos < 20:
        print(f"  SKIP: only {n_oos} OOS observations")
        continue

    # How much IS data before OOS start
    first_oos = oos_indices[0]
    n_is = first_oos  # All data before OOS start
    print(f"  IS: {n_is} weeks (before {oos_start})")
    print(f"  OOS: {n_oos} weeks")

    if n_is < MIN_TRAIN:
        print(f"  SKIP: only {n_is} IS weeks (need {MIN_TRAIN})")
        continue

    # Feature arrays (full series)
    log_rv_1w = weekly['log_rv_1w'].values
    log_rv_5w = weekly['log_rv_5w'].values
    log_rv_21w = weekly['log_rv_21w'].values
    log_vix_var = weekly['log_vix_var'].values
    target_log = weekly['target_log'].values
    target = weekly['target'].values

    # Model feature matrices
    # M1: Lagged RV only (log-HAR)
    # M2: VIX only
    # M3: VIX + Lagged RV

    forecasts = {
        'M1': np.full(n_oos, np.nan),
        'M2': np.full(n_oos, np.nan),
        'M3': np.full(n_oos, np.nan),
    }

    for i, oos_loc in enumerate(oos_indices):
        # Expanding window: use all data up to oos_loc (exclusive)
        train_end = oos_loc
        if train_end < MIN_TRAIN:
            continue

        y_train = target_log[:train_end]
        valid_train = np.isfinite(y_train)

        # --- Model 1: log-HAR (Lagged RV only) ---
        X1_all = np.column_stack([log_rv_1w, log_rv_5w, log_rv_21w])
        X1_train = X1_all[:train_end]
        v1 = valid_train & np.all(np.isfinite(X1_train), axis=1)
        if v1.sum() >= MIN_TRAIN:
            X1_v = np.column_stack([np.ones(v1.sum()), X1_train[v1]])
            y1_v = y_train[v1]
            beta1, _, _, _ = np.linalg.lstsq(X1_v, y1_v, rcond=None)
            resid1 = y1_v - X1_v @ beta1
            sigma2_1 = np.var(resid1)
            # Predict in log space, then exponentiate with Jensen's correction
            x_new = np.array([1.0, log_rv_1w[oos_loc], log_rv_5w[oos_loc], log_rv_21w[oos_loc]])
            if np.all(np.isfinite(x_new)):
                log_pred = x_new @ beta1
                forecasts['M1'][i] = np.exp(log_pred + 0.5 * sigma2_1)

        # --- Model 2: VIX only ---
        X2_all = log_vix_var.reshape(-1, 1)
        X2_train = X2_all[:train_end]
        v2 = valid_train & np.isfinite(X2_train.ravel())
        if v2.sum() >= MIN_TRAIN:
            X2_v = np.column_stack([np.ones(v2.sum()), X2_train[v2]])
            y2_v = y_train[v2]
            beta2, _, _, _ = np.linalg.lstsq(X2_v, y2_v, rcond=None)
            resid2 = y2_v - X2_v @ beta2
            sigma2_2 = np.var(resid2)
            x_new = np.array([1.0, log_vix_var[oos_loc]])
            if np.all(np.isfinite(x_new)):
                log_pred = x_new @ beta2
                forecasts['M2'][i] = np.exp(log_pred + 0.5 * sigma2_2)

        # --- Model 3: VIX + Lagged RV ---
        X3_all = np.column_stack([log_rv_1w, log_rv_5w, log_rv_21w, log_vix_var])
        X3_train = X3_all[:train_end]
        v3 = valid_train & np.all(np.isfinite(X3_train), axis=1)
        if v3.sum() >= MIN_TRAIN:
            X3_v = np.column_stack([np.ones(v3.sum()), X3_train[v3]])
            y3_v = y_train[v3]
            beta3, _, _, _ = np.linalg.lstsq(X3_v, y3_v, rcond=None)
            resid3 = y3_v - X3_v @ beta3
            sigma2_3 = np.var(resid3)
            x_new = np.array([1.0, log_rv_1w[oos_loc], log_rv_5w[oos_loc],
                             log_rv_21w[oos_loc], log_vix_var[oos_loc]])
            if np.all(np.isfinite(x_new)):
                log_pred = x_new @ beta3
                forecasts['M3'][i] = np.exp(log_pred + 0.5 * sigma2_3)

    # Realized values for OOS
    realized_oos = target[oos_mask]

    # Store for pooled analysis
    all_period_forecasts[period_id] = {
        'realized': realized_oos.copy(),
        'M1': forecasts['M1'].copy(),
        'M2': forecasts['M2'].copy(),
        'M3': forecasts['M3'].copy(),
    }

    # Compute QLIKE for each model
    period_results = {
        'description': description,
        'oos_start': oos_start,
        'oos_end': oos_end,
        'n_is': int(n_is),
        'n_oos': int(n_oos),
    }

    for model_name, fcast in forecasts.items():
        ql, n_valid = qlike_mean(realized_oos, fcast)
        # Also compute R² (Mincer-Zarnowitz)
        valid_mz = np.isfinite(fcast) & np.isfinite(realized_oos) & (realized_oos > 0) & (fcast > 0)
        if valid_mz.sum() > 10:
            r_val = realized_oos[valid_mz]
            f_val = fcast[valid_mz]
            corr = np.corrcoef(r_val, f_val)[0, 1]
            r2 = corr ** 2
        else:
            r2 = np.nan

        period_results[f'{model_name}_qlike'] = round(float(ql), 6)
        period_results[f'{model_name}_n_valid'] = int(n_valid)
        period_results[f'{model_name}_r2'] = round(float(r2), 4)
        print(f"  {model_name}: QLIKE={ql:.4f}, R²={r2:.4f} (n={n_valid})")

    # DM tests: M1 vs M2
    l1 = qlike_loss_vec(realized_oos, forecasts['M1'])
    l2 = qlike_loss_vec(realized_oos, forecasts['M2'])
    l3 = qlike_loss_vec(realized_oos, forecasts['M3'])

    dm_12, p_12 = dm_test(l1, l2, h=1)
    period_results['DM_M1vsM2_stat'] = round(float(dm_12), 4) if not np.isnan(dm_12) else None
    period_results['DM_M1vsM2_pval'] = round(float(p_12), 4) if not np.isnan(p_12) else None
    m1_beats_m2 = dm_12 < 0 if not np.isnan(dm_12) else None
    m1_beats_m2_sig = (p_12 < 0.10 and dm_12 < 0) if not np.isnan(dm_12) else None
    period_results['M1_beats_M2'] = m1_beats_m2
    period_results['M1_beats_M2_sig'] = m1_beats_m2_sig
    if not np.isnan(dm_12):
        winner_12 = 'M1' if dm_12 < 0 else 'M2'
        sig_12 = '*' if p_12 < 0.10 else ''
        print(f"  DM M1 vs M2: t={dm_12:.3f}, p={p_12:.4f} ← {winner_12} wins{sig_12}")

    # DM tests: M1 vs M3
    dm_13, p_13 = dm_test(l1, l3, h=1)
    period_results['DM_M1vsM3_stat'] = round(float(dm_13), 4) if not np.isnan(dm_13) else None
    period_results['DM_M1vsM3_pval'] = round(float(p_13), 4) if not np.isnan(p_13) else None
    m1_beats_m3 = dm_13 < 0 if not np.isnan(dm_13) else None
    m1_beats_m3_sig = (p_13 < 0.10 and dm_13 < 0) if not np.isnan(dm_13) else None
    period_results['M1_beats_M3'] = m1_beats_m3
    period_results['M1_beats_M3_sig'] = m1_beats_m3_sig
    if not np.isnan(dm_13):
        winner_13 = 'M1' if dm_13 < 0 else 'M3'
        sig_13 = '*' if p_13 < 0.10 else ''
        print(f"  DM M1 vs M3: t={dm_13:.3f}, p={p_13:.4f} ← {winner_13} wins{sig_13}")

    # DM tests: M2 vs M3 (secondary)
    dm_23, p_23 = dm_test(l2, l3, h=1)
    period_results['DM_M2vsM3_stat'] = round(float(dm_23), 4) if not np.isnan(dm_23) else None
    period_results['DM_M2vsM3_pval'] = round(float(p_23), 4) if not np.isnan(p_23) else None

    # QLIKE-based winner
    ql_m1 = period_results['M1_qlike']
    ql_m2 = period_results['M2_qlike']
    ql_m3 = period_results['M3_qlike']
    best = min([(ql_m1, 'M1'), (ql_m2, 'M2'), (ql_m3, 'M3')])[1]
    period_results['qlike_winner'] = best
    print(f"  QLIKE winner: {best}")

    results[period_id] = period_results

# ============================================================
# Summary across all periods
# ============================================================
print(f"\n{'='*70}")
print("CROSS-OOS SUMMARY")
print(f"{'='*70}")

header = f"{'Period':<20} {'M1(RV)':<10} {'M2(VIX)':<10} {'M3(V+R)':<10} {'R²_M1':<8} {'R²_M2':<8} {'DM M1vM2':<15} {'DM M1vM3':<15} {'Best'}"
print(f"\n{header}")
print("-" * len(header))

m1_wins_vs_m2_ql = 0  # M1 lower QLIKE than M2
m1_wins_vs_m3_ql = 0  # M1 lower QLIKE than M3
m1_wins_vs_m2_sig = 0  # Significant DM
m1_wins_vs_m3_sig = 0
qlike_winners = {'M1': 0, 'M2': 0, 'M3': 0}
total_periods = 0

for pid, pr in results.items():
    total_periods += 1
    m1q = pr['M1_qlike']
    m2q = pr['M2_qlike']
    m3q = pr['M3_qlike']
    r2_m1 = pr.get('M1_r2', np.nan)
    r2_m2 = pr.get('M2_r2', np.nan)

    dm12_str = ""
    dm13_str = ""
    if pr.get('DM_M1vsM2_stat') is not None:
        dm12_str = f"t={pr['DM_M1vsM2_stat']:.2f} p={pr['DM_M1vsM2_pval']:.3f}"
    if pr.get('DM_M1vsM3_stat') is not None:
        dm13_str = f"t={pr['DM_M1vsM3_stat']:.2f} p={pr['DM_M1vsM3_pval']:.3f}"

    best = pr.get('qlike_winner', '?')
    qlike_winners[best] = qlike_winners.get(best, 0) + 1

    if pr.get('M1_beats_M2'):
        m1_wins_vs_m2_ql += 1
    if pr.get('M1_beats_M3'):
        m1_wins_vs_m3_ql += 1
    if pr.get('M1_beats_M2_sig'):
        m1_wins_vs_m2_sig += 1
    if pr.get('M1_beats_M3_sig'):
        m1_wins_vs_m3_sig += 1

    print(f"{pid:<20} {m1q:<10.4f} {m2q:<10.4f} {m3q:<10.4f} {r2_m1:<8.4f} {r2_m2:<8.4f} {dm12_str:<15} {dm13_str:<15} {best}")

print(f"\n--- Win Counts ({total_periods} periods) ---")
print(f"M1 beats M2 (QLIKE): {m1_wins_vs_m2_ql}/{total_periods}")
print(f"M1 beats M2 (DM sig p<0.10): {m1_wins_vs_m2_sig}/{total_periods}")
print(f"M1 beats M3 (QLIKE): {m1_wins_vs_m3_ql}/{total_periods}")
print(f"M1 beats M3 (DM sig p<0.10): {m1_wins_vs_m3_sig}/{total_periods}")
print(f"QLIKE best overall: M1={qlike_winners.get('M1',0)}, M2={qlike_winners.get('M2',0)}, M3={qlike_winners.get('M3',0)}")

# ============================================================
# Pooled QLIKE (concatenated OOS)
# ============================================================
print(f"\n--- Pooled QLIKE (all OOS periods concatenated) ---")
all_realized = np.concatenate([v['realized'] for v in all_period_forecasts.values()])
all_m1 = np.concatenate([v['M1'] for v in all_period_forecasts.values()])
all_m2 = np.concatenate([v['M2'] for v in all_period_forecasts.values()])
all_m3 = np.concatenate([v['M3'] for v in all_period_forecasts.values()])

pool_m1, pool_n1 = qlike_mean(all_realized, all_m1)
pool_m2, pool_n2 = qlike_mean(all_realized, all_m2)
pool_m3, pool_n3 = qlike_mean(all_realized, all_m3)

print(f"  M1 (Lagged RV):  QLIKE={pool_m1:.4f} (n={pool_n1})")
print(f"  M2 (VIX only):   QLIKE={pool_m2:.4f} (n={pool_n2})")
print(f"  M3 (VIX + RV):   QLIKE={pool_m3:.4f} (n={pool_n3})")

# Pooled DM tests
pool_l1 = qlike_loss_vec(all_realized, all_m1)
pool_l2 = qlike_loss_vec(all_realized, all_m2)
pool_l3 = qlike_loss_vec(all_realized, all_m3)

pool_dm12, pool_p12 = dm_test(pool_l1, pool_l2, h=1)
pool_dm13, pool_p13 = dm_test(pool_l1, pool_l3, h=1)
pool_dm23, pool_p23 = dm_test(pool_l2, pool_l3, h=1)

print(f"\n  Pooled DM M1 vs M2: t={pool_dm12:.3f}, p={pool_p12:.4f}")
print(f"  Pooled DM M1 vs M3: t={pool_dm13:.3f}, p={pool_p13:.4f}")
print(f"  Pooled DM M2 vs M3: t={pool_dm23:.3f}, p={pool_p23:.4f}")

# ============================================================
# Decision
# ============================================================
print(f"\n{'='*70}")
print("DECISION")
print(f"{'='*70}")

# Count M1 QLIKE wins across all periods
m1_qlike_best = qlike_winners.get('M1', 0)

if m1_wins_vs_m3_ql >= 4:
    verdict = f"VIX sufficiency CHALLENGED at weekly frequency — lagged RV wins {m1_wins_vs_m3_ql}/{total_periods} periods"
    robust = True
elif m1_wins_vs_m3_ql <= 2:
    verdict = f"K473 is PERIOD-SPECIFIC — VIX sufficiency holds at weekly frequency ({m1_wins_vs_m3_ql}/{total_periods})"
    robust = False
else:
    verdict = f"AMBIGUOUS — M1 wins {m1_wins_vs_m3_ql}/{total_periods}, need more evidence"
    robust = None

print(f"\n  M1 vs M3: {verdict}")

if m1_wins_vs_m2_ql >= 4:
    verdict_m2 = f"Lagged RV dominates VIX-only at weekly frequency ({m1_wins_vs_m2_ql}/{total_periods})"
elif m1_wins_vs_m2_ql <= 2:
    verdict_m2 = f"VIX-only is competitive or better at weekly frequency ({m1_wins_vs_m2_ql}/{total_periods})"
else:
    verdict_m2 = f"Mixed: {m1_wins_vs_m2_ql}/{total_periods}"
print(f"  M1 vs M2: {verdict_m2}")

# Implication
if robust:
    implication = (
        "At weekly frequency, lagged RV (log-HAR) dominates VIX for QLIKE forecasting. "
        "This suggests VIX sufficiency, confirmed 27+ times at daily frequency, does NOT "
        "extend to weekly horizon. The HAR long-memory structure captures weekly vol persistence "
        "that VIX (a 30-day forward measure) cannot provide at this specific aggregation level. "
        "Consistent with Corsi (2009) HAR-RV literature."
    )
elif robust is False:
    implication = (
        "K473's finding is period-specific. VIX sufficiency likely holds "
        "at weekly frequency as well, consistent with the 27+ daily confirmations. "
        "The 2023-2025 result was driven by specific market conditions."
    )
else:
    implication = "Evidence is mixed. Neither model consistently dominates across all periods."

print(f"\n  Implication: {implication}")

elapsed = time.time() - t0
print(f"\nElapsed: {elapsed:.1f} seconds")

# ============================================================
# Save results
# ============================================================
output = {
    "experiment_id": "K474",
    "title": "Weekly Lagged RV vs VIX — 6-Period Cross-OOS Validation",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data": {
        "asset": ASSET,
        "data_start": DATA_START,
        "data_end": DATA_END,
        "source": "yfinance (SPY + ^VIX)",
        "weekly_obs_total": int(len(weekly)),
        "method": "Log-level OLS (log-HAR), expanding window, Jensen correction for exp()"
    },
    "descriptive_stats": {
        "weekly_rv_mean": float(rv.mean()),
        "weekly_rv_median": float(rv.median()),
        "weekly_rv_std": float(rv.std()),
        "weekly_rv_skew": float(rv.skew()),
        "weekly_rv_kurt": float(rv.kurtosis()),
        "corr_rv_vix_level": float(rv.corr(vv)),
        "corr_log_rv_log_vix": float(np.log(rv).corr(np.log(vv))),
    },
    "models": {
        "M1": "Log-HAR (Lagged RV only): log(RV_1w), log(RV_5w), log(RV_21w) -> log(next-week RV)",
        "M2": "VIX only: log(VIX_var_weekly) -> log(next-week RV)",
        "M3": "VIX + Log-HAR: log(RV_1w), log(RV_5w), log(RV_21w), log(VIX_var) -> log(next-week RV)",
    },
    "oos_periods": {k: v for k, v in results.items()},
    "pooled_analysis": {
        "M1_qlike": round(float(pool_m1), 6),
        "M2_qlike": round(float(pool_m2), 6),
        "M3_qlike": round(float(pool_m3), 6),
        "DM_M1vsM2": {"t_stat": round(float(pool_dm12), 4), "p_value": round(float(pool_p12), 4)},
        "DM_M1vsM3": {"t_stat": round(float(pool_dm13), 4), "p_value": round(float(pool_p13), 4)},
        "DM_M2vsM3": {"t_stat": round(float(pool_dm23), 4), "p_value": round(float(pool_p23), 4)},
        "total_oos_weeks": int(pool_n1),
    },
    "summary": {
        "total_periods": total_periods,
        "M1_wins_vs_M2_qlike": m1_wins_vs_m2_ql,
        "M1_wins_vs_M2_sig": m1_wins_vs_m2_sig,
        "M1_wins_vs_M3_qlike": m1_wins_vs_m3_ql,
        "M1_wins_vs_M3_sig": m1_wins_vs_m3_sig,
        "qlike_best_counts": qlike_winners,
        "verdict_vs_M3": verdict,
        "verdict_vs_M2": verdict_m2,
        "robust": robust,
    },
    "conclusion": {
        "main_finding": verdict,
        "implication": implication,
        "vix_sufficiency_status": (
            "REJECTED at weekly frequency" if robust else
            "MAINTAINED at weekly frequency" if robust is False else
            "INCONCLUSIVE at weekly frequency"
        ),
    },
    "references": [
        "Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility' JFE",
        "Patton (2011) 'Volatility Forecast Comparison Using Imperfect Volatility Proxies' JoE",
        "Diebold & Mariano (1995) 'Comparing Predictive Accuracy' JBES",
        "K473: Weekly attention vol experiment (lagged RV finding)",
        "K129: VIX sufficiency boundary map",
    ],
    "elapsed_seconds": round(elapsed, 1),
}

out_path = 'experiments/k474_weekly_rv_vs_vix_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")
