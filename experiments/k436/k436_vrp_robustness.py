"""
K436: VRP Predictability Robustness Test (Non-overlapping + Bootstrap)

Background:
  K430 found VRP (VIX - RV21) IS t=4.38 (passes Harvey t>3.0) but OOS DM test p=0.163.
  Root cause hypothesis: overlapping 21-day windows inflate serial correlation,
  reducing effective sample size and DM test power.

Robustness Tests:
  Test 1: Non-overlapping monthly vol (every 21 trading days → one observation)
  Test 2: Daily frequency — predict next-day |return|, completely avoids overlap
  Test 3: Block bootstrap (block=21, 10000 reps) on QLIKE loss differential
  Test 4: HAC-robust DM test with proper Newey-West lag selection

Literature:
  - Bollerslev, Tauchen, Zhou (2009) RFS — VRP predicts excess returns
  - Bekaert & Hoerova (2014) JoE — VRP decomposition, VP predicts returns

Data: yfinance (SPY, ^VIX), 2005-01-01 to present
OOS: 2023-01-01 to 2025-12-31
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

warnings.filterwarnings('ignore')

print("=" * 70)
print("K436: VRP Predictability Robustness Test")
print("  Non-overlapping windows + Block Bootstrap + Daily frequency")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2005-01-01', progress=False)
vix = yf.download('^VIX', start='2005-01-01', progress=False)

# Handle MultiIndex columns if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")

# ============================================================
# 2. DAILY FEATURE CONSTRUCTION
# ============================================================
print("\n[2] Constructing daily features...")

ret = spy['Close'].pct_change()
rv_21 = ret.rolling(21).std() * np.sqrt(252) * 100  # annualized %
rv_21_future = ret.rolling(21).std().shift(-21) * np.sqrt(252) * 100

df = pd.DataFrame({
    'ret': ret,
    'abs_ret': ret.abs() * 100,  # absolute return in %
    'vix': vix['Close'].reindex(spy.index),
    'rv_21': rv_21,
    'rv_21_future': rv_21_future,
}, index=spy.index)

df['vrp'] = df['vix'] - df['rv_21']
# Next-day absolute return (daily target, no overlap)
df['abs_ret_next'] = df['abs_ret'].shift(-1)
# Next-day squared return (alternative daily target)
df['sq_ret_next'] = (ret.shift(-1) ** 2) * 10000  # in bp²

df_daily = df.dropna()
print(f"  Daily sample: {df_daily.index[0].date()} to {df_daily.index[-1].date()} ({len(df_daily)} obs)")

# ============================================================
# 3. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n[3] Descriptive Statistics & Diagnostics...")

desc_vars = ['vix', 'rv_21', 'vrp', 'abs_ret_next']
desc_stats = {}
for v in desc_vars:
    s = df_daily[v]
    desc_stats[v] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'median': float(s.median()),
        'max': float(s.max()),
        'N': int(s.count()),
    }
    print(f"  {v}: Mean={s.mean():.3f}, Std={s.std():.3f}, Skew={s.skew():.3f}, Kurt={s.kurtosis():.3f}")

# ADF on VRP
adf_result = adfuller(df_daily['vrp'].values, maxlag=21, autolag='AIC')
print(f"\n  ADF test on VRP: stat={adf_result[0]:.4f}, p={adf_result[1]:.6f} → {'stationary' if adf_result[1] < 0.05 else 'non-stationary'}")

# Ljung-Box on VRP
lb_result = acorr_ljungbox(df_daily['vrp'].values, lags=[10, 21], return_df=True)
for lag in [10, 21]:
    row = lb_result.loc[lag]
    print(f"  Ljung-Box VRP lag {lag}: Q={row['lb_stat']:.2f}, p={row['lb_pvalue']:.6f}")

# ============================================================
# 4. NON-OVERLAPPING MONTHLY CONSTRUCTION
# ============================================================
print("\n[4] Constructing non-overlapping monthly data...")

# Build non-overlapping 21-day blocks
# Start from first available date with sufficient data
start_idx = 21  # need at least 21 days for first RV
block_size = 21

# Identify non-overlapping block end dates
all_dates = df.index.tolist()
block_end_dates = []
i = start_idx
while i < len(all_dates):
    block_end_dates.append(all_dates[i])
    i += block_size

print(f"  Total non-overlapping blocks: {len(block_end_dates)}")

# For each block end, compute:
# - RV of the block (realized vol of 21 days ending at this date)
# - VIX at block end
# - RV of NEXT block (target)
monthly_data = []
for j in range(len(block_end_dates) - 1):
    curr_date = block_end_dates[j]
    next_date = block_end_dates[j + 1]

    # Current block RV
    loc_curr = all_dates.index(curr_date)
    block_start = max(0, loc_curr - block_size + 1)
    block_rets = ret.iloc[block_start:loc_curr + 1].dropna()
    if len(block_rets) < 15:
        continue
    rv_curr = float(block_rets.std() * np.sqrt(252) * 100)

    # Next block RV (target)
    loc_next = all_dates.index(next_date)
    next_start = loc_curr + 1
    if next_start >= len(all_dates) or loc_next >= len(all_dates):
        continue
    next_rets = ret.iloc[next_start:loc_next + 1].dropna()
    if len(next_rets) < 15:
        continue
    rv_next = float(next_rets.std() * np.sqrt(252) * 100)

    # VIX at current block end
    if curr_date in df.index:
        vix_curr = float(df.loc[curr_date, 'vix'])
    else:
        continue

    if np.isnan(rv_curr) or np.isnan(rv_next) or np.isnan(vix_curr):
        continue

    vrp_curr = vix_curr - rv_curr

    monthly_data.append({
        'date': curr_date,
        'rv_curr': rv_curr,
        'rv_next': rv_next,
        'vix': vix_curr,
        'vrp': vrp_curr,
    })

df_monthly = pd.DataFrame(monthly_data).set_index('date')
print(f"  Monthly non-overlapping: {df_monthly.index[0].date()} to {df_monthly.index[-1].date()} ({len(df_monthly)} obs)")

# ============================================================
# 5. IS/OOS SPLIT
# ============================================================
print("\n[5] IS/OOS Split...")

oos_start = '2023-01-01'

# Daily split
is_daily = df_daily[df_daily.index < oos_start].copy()
oos_daily = df_daily[df_daily.index >= oos_start].copy()
print(f"  Daily IS: {is_daily.index[0].date()} to {is_daily.index[-1].date()} ({len(is_daily)} obs)")
print(f"  Daily OOS: {oos_daily.index[0].date()} to {oos_daily.index[-1].date()} ({len(oos_daily)} obs)")

# Monthly split
is_monthly = df_monthly[df_monthly.index < oos_start].copy()
oos_monthly = df_monthly[df_monthly.index >= oos_start].copy()
print(f"  Monthly IS: {is_monthly.index[0].date()} to {is_monthly.index[-1].date()} ({len(is_monthly)} obs)")
print(f"  Monthly OOS: {oos_monthly.index[0].date()} to {oos_monthly.index[-1].date()} ({len(oos_monthly)} obs)")


# ============================================================
# Helper functions
# ============================================================
def qlike(actual, predicted):
    """QLIKE loss: mean(actual/predicted + ln(predicted) - 1 - ln(actual))"""
    pred_safe = np.maximum(predicted, 0.01)
    act_safe = np.maximum(actual, 0.01)
    return float(np.mean(act_safe / pred_safe + np.log(pred_safe) - 1 - np.log(act_safe)))


def mse_loss(actual, predicted):
    return float(np.mean((actual - predicted) ** 2))


def ols_fit_predict(X_is, y_is, X_oos):
    """OLS with intercept, returns OOS predictions and IS betas"""
    X_aug = np.column_stack([np.ones(len(X_is)), X_is])
    X_oos_aug = np.column_stack([np.ones(len(X_oos)), X_oos])
    beta, _, _, _ = np.linalg.lstsq(X_aug, y_is, rcond=None)
    return X_oos_aug @ beta, beta


def dm_test_hac(loss1, loss2, max_lag=None):
    """Diebold-Mariano test with Newey-West HAC standard errors.
    loss1 = baseline loss, loss2 = alternative loss.
    Positive DM stat means alternative is better (lower loss)."""
    d = loss1 - loss2  # positive = baseline worse
    n = len(d)
    d_mean = d.mean()

    if max_lag is None:
        max_lag = int(np.floor(4 * (n / 100) ** (2 / 9)))  # Andrews (1991) rule
    max_lag = max(max_lag, 1)

    # HAC variance (Bartlett kernel)
    gamma_0 = np.mean((d - d_mean) ** 2)
    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * w * gamma_k

    hac_var = max(hac_var, 1e-12)  # safety floor
    dm_stat = d_mean / np.sqrt(hac_var / n)
    dm_pvalue = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(dm_pvalue), float(d_mean)


def block_bootstrap_dm(loss1, loss2, block_size=21, n_boot=10000, seed=42):
    """Block bootstrap for DM test.
    Returns bootstrap distribution of DM stats and p-value."""
    rng = np.random.RandomState(seed)
    d = loss1 - loss2
    T = len(d)
    n_blocks = T // block_size + 1

    dm_boot = np.zeros(n_boot)
    d_mean_obs = d.mean()

    for b in range(n_boot):
        # Draw random block starting points
        idx = rng.randint(0, T - block_size + 1, n_blocks)
        sample = np.concatenate([d[i:i + block_size] for i in idx])[:T]
        # Center the bootstrap sample (null hypothesis: mean diff = 0)
        sample_centered = sample - sample.mean() + 0  # center at 0
        se = sample.std() / np.sqrt(T)
        if se > 1e-12:
            dm_boot[b] = sample_centered.mean() / se
        else:
            dm_boot[b] = 0.0

    # Bootstrap p-value: fraction of bootstrap DM stats more extreme than observed
    obs_dm = d_mean_obs / (d.std() / np.sqrt(T))
    p_value = float(np.mean(np.abs(dm_boot) >= abs(obs_dm)))

    # Also compute percentile CI for the mean loss difference
    d_mean_boot = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, T - block_size + 1, n_blocks)
        sample = np.concatenate([d[i:i + block_size] for i in idx])[:T]
        d_mean_boot[b] = sample.mean()

    ci_lower = float(np.percentile(d_mean_boot, 2.5))
    ci_upper = float(np.percentile(d_mean_boot, 97.5))

    return {
        'obs_dm_stat': float(obs_dm),
        'bootstrap_p_value': p_value,
        'ci_95_lower': ci_lower,
        'ci_95_upper': ci_upper,
        'mean_loss_diff': float(d_mean_obs),
        'boot_mean_dm': float(np.mean(dm_boot)),
        'boot_std_dm': float(np.std(dm_boot)),
        'n_boot': n_boot,
        'block_size': block_size,
    }


# ============================================================
# 6. TEST 1: NON-OVERLAPPING MONTHLY VOL PREDICTION
# ============================================================
print("\n" + "=" * 70)
print("TEST 1: Non-overlapping Monthly Vol Prediction")
print("=" * 70)

# IS regression diagnostics first
X_m_is = is_monthly[['rv_curr', 'vrp']].values
y_m_is = is_monthly['rv_next'].values

X_m_is_diag = sm.add_constant(is_monthly[['rv_curr', 'vrp']])
ols_monthly_is = sm.OLS(y_m_is, X_m_is_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 3})
print("\n  IS Monthly Regression (non-overlapping, HAC lag=3):")
print(ols_monthly_is.summary().tables[1])
print(f"\n  IS R² = {ols_monthly_is.rsquared:.4f}, Adj R² = {ols_monthly_is.rsquared_adj:.4f}")

# Also test VRP-only IS regression
X_m_vrp_is = sm.add_constant(is_monthly[['vrp']])
ols_vrp_only_is = sm.OLS(y_m_is, X_m_vrp_is).fit(cov_type='HAC', cov_kwds={'maxlags': 3})
print(f"\n  VRP-only IS: coef={ols_vrp_only_is.params['vrp']:.4f}, t={ols_vrp_only_is.tvalues['vrp']:.3f}, p={ols_vrp_only_is.pvalues['vrp']:.6f}")

# Baseline IS regression (RV only)
X_m_rv_is = sm.add_constant(is_monthly[['rv_curr']])
ols_rv_only_is = sm.OLS(y_m_is, X_m_rv_is).fit(cov_type='HAC', cov_kwds={'maxlags': 3})
print(f"  RV-only IS: coef={ols_rv_only_is.params['rv_curr']:.4f}, t={ols_rv_only_is.tvalues['rv_curr']:.3f}")

# Residual diagnostics
resid_monthly = ols_monthly_is.resid
lb_resid = acorr_ljungbox(resid_monthly, lags=[3, 5], return_df=True)
print(f"\n  Residual Ljung-Box lag 3: Q={lb_resid.loc[3, 'lb_stat']:.2f}, p={lb_resid.loc[3, 'lb_pvalue']:.4f}")
print(f"  Residual Ljung-Box lag 5: Q={lb_resid.loc[5, 'lb_stat']:.2f}, p={lb_resid.loc[5, 'lb_pvalue']:.4f}")

# Check residual ARCH effects
if len(resid_monthly) > 10:
    arch_test_m = het_arch(resid_monthly, nlags=3)
    print(f"  Residual ARCH LM (3 lags): stat={arch_test_m[0]:.2f}, p={arch_test_m[1]:.4f}")

# OOS prediction
y_m_oos = oos_monthly['rv_next'].values

# Model 1: Baseline (lagged RV only)
X_m_rv_oos = oos_monthly[['rv_curr']].values
pred_m1, _ = ols_fit_predict(is_monthly[['rv_curr']].values, y_m_is, X_m_rv_oos)

# Model 2: RV + VRP
X_m_oos = oos_monthly[['rv_curr', 'vrp']].values
pred_m2, _ = ols_fit_predict(X_m_is, y_m_is, X_m_oos)

# Model 3: VRP only
X_m_vrp_oos = oos_monthly[['vrp']].values
pred_m3, _ = ols_fit_predict(is_monthly[['vrp']].values, y_m_is, X_m_vrp_oos)

# Evaluate
qlike_m1 = qlike(y_m_oos, pred_m1)
qlike_m2 = qlike(y_m_oos, pred_m2)
qlike_m3 = qlike(y_m_oos, pred_m3)
mse_m1 = mse_loss(y_m_oos, pred_m1)
mse_m2 = mse_loss(y_m_oos, pred_m2)
mse_m3 = mse_loss(y_m_oos, pred_m3)
corr_m1 = float(np.corrcoef(y_m_oos, pred_m1)[0, 1])
corr_m2 = float(np.corrcoef(y_m_oos, pred_m2)[0, 1])
corr_m3 = float(np.corrcoef(y_m_oos, pred_m3)[0, 1])

print(f"\n  OOS Non-overlapping Monthly Performance:")
print(f"  {'Model':<25s} {'QLIKE':>8s} {'MSE':>10s} {'Corr':>8s}")
print(f"  {'-' * 55}")
print(f"  {'M1: RV baseline':<25s} {qlike_m1:8.4f} {mse_m1:10.2f} {corr_m1:8.4f}")
print(f"  {'M2: RV + VRP':<25s} {qlike_m2:8.4f} {mse_m2:10.2f} {corr_m2:8.4f}")
print(f"  {'M3: VRP only':<25s} {qlike_m3:8.4f} {mse_m3:10.2f} {corr_m3:8.4f}")

qlike_improv_m = (1 - qlike_m2 / qlike_m1) * 100 if qlike_m1 > 0 else 0.0
mse_improv_m = (1 - mse_m2 / mse_m1) * 100 if mse_m1 > 0 else 0.0
print(f"\n  VRP incremental improvement: QLIKE {qlike_improv_m:+.2f}%, MSE {mse_improv_m:+.2f}%")

# DM test on non-overlapping monthly (NO overlap → standard DM is valid)
# But we still use HAC with lag=3 for safety (monthly RV has some persistence)
loss_m1 = (y_m_oos - pred_m1) ** 2
loss_m2 = (y_m_oos - pred_m2) ** 2
dm_m_stat, dm_m_pval, dm_m_diff = dm_test_hac(loss_m1, loss_m2, max_lag=3)
print(f"\n  DM test (M2 vs M1, HAC lag=3): stat={dm_m_stat:.3f}, p={dm_m_pval:.4f}")

# Also standard DM (no HAC, valid for non-overlapping)
d_m = loss_m1 - loss_m2
d_m_mean = d_m.mean()
d_m_se = d_m.std() / np.sqrt(len(d_m))
dm_m_simple_stat = d_m_mean / d_m_se if d_m_se > 1e-12 else 0.0
dm_m_simple_pval = 2 * (1 - stats.norm.cdf(abs(dm_m_simple_stat)))
print(f"  DM test (standard, no HAC): stat={dm_m_simple_stat:.3f}, p={dm_m_simple_pval:.4f}")

# N for monthly
n_monthly_oos = len(y_m_oos)
print(f"  (N = {n_monthly_oos} non-overlapping monthly obs)")

monthly_results = {
    'n_is': int(len(is_monthly)),
    'n_oos': int(n_monthly_oos),
    'is_regression': {
        'rv_plus_vrp': {
            'r_squared': float(ols_monthly_is.rsquared),
            'adj_r_squared': float(ols_monthly_is.rsquared_adj),
            'vrp_coef': float(ols_monthly_is.params['vrp']),
            'vrp_t_stat': float(ols_monthly_is.tvalues['vrp']),
            'vrp_p_value': float(ols_monthly_is.pvalues['vrp']),
            'rv_coef': float(ols_monthly_is.params['rv_curr']),
            'rv_t_stat': float(ols_monthly_is.tvalues['rv_curr']),
        },
        'vrp_only': {
            'vrp_coef': float(ols_vrp_only_is.params['vrp']),
            'vrp_t_stat': float(ols_vrp_only_is.tvalues['vrp']),
            'vrp_p_value': float(ols_vrp_only_is.pvalues['vrp']),
            'r_squared': float(ols_vrp_only_is.rsquared),
        },
    },
    'oos_performance': {
        'M1_RV_baseline': {'qlike': qlike_m1, 'mse': mse_m1, 'corr': corr_m1},
        'M2_RV_plus_VRP': {'qlike': qlike_m2, 'mse': mse_m2, 'corr': corr_m2},
        'M3_VRP_only': {'qlike': qlike_m3, 'mse': mse_m3, 'corr': corr_m3},
    },
    'qlike_improvement_pct': float(qlike_improv_m),
    'mse_improvement_pct': float(mse_improv_m),
    'dm_test_hac': {'stat': dm_m_stat, 'p_value': dm_m_pval, 'mean_loss_diff': dm_m_diff},
    'dm_test_standard': {'stat': float(dm_m_simple_stat), 'p_value': float(dm_m_simple_pval)},
}

# ============================================================
# 7. TEST 2: DAILY FREQUENCY — PREDICT NEXT-DAY |RETURN|
# ============================================================
print("\n" + "=" * 70)
print("TEST 2: Daily Frequency — Predict next-day |return|")
print("  (Completely avoids overlap problem)")
print("=" * 70)

# Features: VRP, RV21, VIX
# Target: abs_ret_next (next-day absolute return %)

y_d_is = is_daily['abs_ret_next'].values
y_d_oos = oos_daily['abs_ret_next'].values

# IS diagnostics
X_d_diag = sm.add_constant(is_daily[['rv_21', 'vrp']])
ols_daily_is = sm.OLS(y_d_is, X_d_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print("\n  IS Daily Regression (HAC lag=10):")
print(ols_daily_is.summary().tables[1])
print(f"\n  IS R² = {ols_daily_is.rsquared:.6f}, Adj R² = {ols_daily_is.rsquared_adj:.6f}")

# VRP-only daily
X_d_vrp_diag = sm.add_constant(is_daily[['vrp']])
ols_daily_vrp_is = sm.OLS(y_d_is, X_d_vrp_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"\n  VRP-only daily IS: coef={ols_daily_vrp_is.params['vrp']:.6f}, t={ols_daily_vrp_is.tvalues['vrp']:.3f}, p={ols_daily_vrp_is.pvalues['vrp']:.6f}")

# RV-only daily
X_d_rv_diag = sm.add_constant(is_daily[['rv_21']])
ols_daily_rv_is = sm.OLS(y_d_is, X_d_rv_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 10})
print(f"  RV-only daily IS: coef={ols_daily_rv_is.params['rv_21']:.6f}, t={ols_daily_rv_is.tvalues['rv_21']:.3f}")

# OOS prediction
# M1: RV baseline
pred_d1, _ = ols_fit_predict(is_daily[['rv_21']].values, y_d_is, oos_daily[['rv_21']].values)
# M2: RV + VRP
pred_d2, _ = ols_fit_predict(is_daily[['rv_21', 'vrp']].values, y_d_is, oos_daily[['rv_21', 'vrp']].values)
# M3: VRP only
pred_d3, _ = ols_fit_predict(is_daily[['vrp']].values, y_d_is, oos_daily[['vrp']].values)
# M4: VIX only
pred_d4, _ = ols_fit_predict(is_daily[['vix']].values, y_d_is, oos_daily[['vix']].values)

# For QLIKE on daily abs returns, need to be careful (can't take log of 0)
# Use squared returns instead for QLIKE
y_d_sq_is = is_daily['sq_ret_next'].values
y_d_sq_oos = oos_daily['sq_ret_next'].values

pred_d1_sq, _ = ols_fit_predict(is_daily[['rv_21']].values, y_d_sq_is, oos_daily[['rv_21']].values)
pred_d2_sq, _ = ols_fit_predict(is_daily[['rv_21', 'vrp']].values, y_d_sq_is, oos_daily[['rv_21', 'vrp']].values)

# MSE for daily abs return
mse_d1 = mse_loss(y_d_oos, pred_d1)
mse_d2 = mse_loss(y_d_oos, pred_d2)
mse_d3 = mse_loss(y_d_oos, pred_d3)
mse_d4 = mse_loss(y_d_oos, pred_d4)
corr_d1 = float(np.corrcoef(y_d_oos, pred_d1)[0, 1])
corr_d2 = float(np.corrcoef(y_d_oos, pred_d2)[0, 1])
corr_d3 = float(np.corrcoef(y_d_oos, pred_d3)[0, 1])
corr_d4 = float(np.corrcoef(y_d_oos, pred_d4)[0, 1])

# QLIKE on squared returns
qlike_d1 = qlike(y_d_sq_oos, np.maximum(pred_d1_sq, 0.01))
qlike_d2 = qlike(y_d_sq_oos, np.maximum(pred_d2_sq, 0.01))

print(f"\n  OOS Daily Performance (predict next-day |return|):")
print(f"  {'Model':<25s} {'MSE':>10s} {'Corr':>8s}")
print(f"  {'-' * 47}")
print(f"  {'M1: RV baseline':<25s} {mse_d1:10.4f} {corr_d1:8.4f}")
print(f"  {'M2: RV + VRP':<25s} {mse_d2:10.4f} {corr_d2:8.4f}")
print(f"  {'M3: VRP only':<25s} {mse_d3:10.4f} {corr_d3:8.4f}")
print(f"  {'M4: VIX only':<25s} {mse_d4:10.4f} {corr_d4:8.4f}")

mse_improv_d = (1 - mse_d2 / mse_d1) * 100 if mse_d1 > 0 else 0.0
qlike_improv_d = (1 - qlike_d2 / qlike_d1) * 100 if qlike_d1 > 0 else 0.0
print(f"\n  VRP incremental improvement (daily): MSE {mse_improv_d:+.4f}%, QLIKE(sq) {qlike_improv_d:+.4f}%")

# DM test for daily (no overlap → standard DM valid, but use HAC lag=5 for safety)
loss_d1 = (y_d_oos - pred_d1) ** 2
loss_d2 = (y_d_oos - pred_d2) ** 2

dm_d_stat, dm_d_pval, dm_d_diff = dm_test_hac(loss_d1, loss_d2, max_lag=5)
print(f"\n  DM test daily (M2 vs M1, HAC lag=5): stat={dm_d_stat:.3f}, p={dm_d_pval:.4f}")

# Standard DM (no HAC)
d_d = loss_d1 - loss_d2
d_d_mean = d_d.mean()
d_d_se = d_d.std() / np.sqrt(len(d_d))
dm_d_simple_stat = d_d_mean / d_d_se if d_d_se > 1e-12 else 0.0
dm_d_simple_pval = 2 * (1 - stats.norm.cdf(abs(dm_d_simple_stat)))
print(f"  DM test daily (standard, no HAC): stat={dm_d_simple_stat:.3f}, p={dm_d_simple_pval:.4f}")

# Also test VRP-only vs RV-only
loss_d3 = (y_d_oos - pred_d3) ** 2
dm_d3_stat, dm_d3_pval, _ = dm_test_hac(loss_d1, loss_d3, max_lag=5)
print(f"  DM test daily (VRP-only vs RV, HAC lag=5): stat={dm_d3_stat:.3f}, p={dm_d3_pval:.4f}")

daily_results = {
    'n_is': int(len(is_daily)),
    'n_oos': int(len(oos_daily)),
    'is_regression': {
        'rv_plus_vrp': {
            'r_squared': float(ols_daily_is.rsquared),
            'vrp_coef': float(ols_daily_is.params['vrp']),
            'vrp_t_stat': float(ols_daily_is.tvalues['vrp']),
            'vrp_p_value': float(ols_daily_is.pvalues['vrp']),
            'rv_coef': float(ols_daily_is.params['rv_21']),
            'rv_t_stat': float(ols_daily_is.tvalues['rv_21']),
        },
        'vrp_only': {
            'vrp_coef': float(ols_daily_vrp_is.params['vrp']),
            'vrp_t_stat': float(ols_daily_vrp_is.tvalues['vrp']),
            'vrp_p_value': float(ols_daily_vrp_is.pvalues['vrp']),
            'r_squared': float(ols_daily_vrp_is.rsquared),
        },
    },
    'oos_performance': {
        'M1_RV_baseline': {'mse': mse_d1, 'corr': corr_d1},
        'M2_RV_plus_VRP': {'mse': mse_d2, 'corr': corr_d2},
        'M3_VRP_only': {'mse': mse_d3, 'corr': corr_d3},
        'M4_VIX_only': {'mse': mse_d4, 'corr': corr_d4},
    },
    'mse_improvement_pct': float(mse_improv_d),
    'qlike_sq_improvement_pct': float(qlike_improv_d),
    'dm_test_hac': {'stat': dm_d_stat, 'p_value': dm_d_pval},
    'dm_test_standard': {'stat': float(dm_d_simple_stat), 'p_value': float(dm_d_simple_pval)},
    'dm_test_vrp_only_vs_rv': {'stat': float(dm_d3_stat), 'p_value': float(dm_d3_pval)},
}

# ============================================================
# 8. TEST 3: BLOCK BOOTSTRAP ON OVERLAPPING DAILY DATA
# ============================================================
print("\n" + "=" * 70)
print("TEST 3: Block Bootstrap on Original Overlapping 21-day Data")
print("  (Re-doing K430 with proper bootstrap inference)")
print("=" * 70)

# Re-construct overlapping daily data for 21-day RV prediction
df_overlap = df.dropna(subset=['vrp', 'rv_21', 'rv_21_future']).copy()
is_overlap = df_overlap[df_overlap.index < oos_start]
oos_overlap = df_overlap[df_overlap.index >= oos_start]

y_o_is = is_overlap['rv_21_future'].values
y_o_oos = oos_overlap['rv_21_future'].values

# M1: Baseline (RV only)
pred_o1, _ = ols_fit_predict(is_overlap[['rv_21']].values, y_o_is, oos_overlap[['rv_21']].values)
# M2: RV + VRP
pred_o2, _ = ols_fit_predict(is_overlap[['rv_21', 'vrp']].values, y_o_is, oos_overlap[['rv_21', 'vrp']].values)

loss_o1 = (y_o_oos - pred_o1) ** 2
loss_o2 = (y_o_oos - pred_o2) ** 2

qlike_o1 = qlike(y_o_oos, pred_o1)
qlike_o2 = qlike(y_o_oos, pred_o2)
qlike_improv_o = (1 - qlike_o2 / qlike_o1) * 100

# QLIKE loss arrays for bootstrap
qlike_loss_o1 = y_o_oos / np.maximum(pred_o1, 0.01) + np.log(np.maximum(pred_o1, 0.01)) - 1 - np.log(np.maximum(y_o_oos, 0.01))
qlike_loss_o2 = y_o_oos / np.maximum(pred_o2, 0.01) + np.log(np.maximum(pred_o2, 0.01)) - 1 - np.log(np.maximum(y_o_oos, 0.01))

print(f"\n  OOS overlapping: N={len(y_o_oos)}")
print(f"  QLIKE baseline: {qlike_o1:.4f}, QLIKE VRP+: {qlike_o2:.4f}, improvement: {qlike_improv_o:.2f}%")

# Block bootstrap on MSE loss
print("\n  Running block bootstrap (block=21, 10000 reps) on MSE loss...")
boot_mse = block_bootstrap_dm(loss_o1, loss_o2, block_size=21, n_boot=10000, seed=42)
print(f"    MSE loss: obs DM={boot_mse['obs_dm_stat']:.3f}")
print(f"    Bootstrap p-value: {boot_mse['bootstrap_p_value']:.4f}")
print(f"    95% CI for mean MSE diff: [{boot_mse['ci_95_lower']:.4f}, {boot_mse['ci_95_upper']:.4f}]")
print(f"    Mean loss diff: {boot_mse['mean_loss_diff']:.4f} ({'VRP+ better' if boot_mse['mean_loss_diff'] > 0 else 'baseline better'})")

# Block bootstrap on QLIKE loss
print("\n  Running block bootstrap (block=21, 10000 reps) on QLIKE loss...")
boot_qlike = block_bootstrap_dm(qlike_loss_o1, qlike_loss_o2, block_size=21, n_boot=10000, seed=42)
print(f"    QLIKE loss: obs DM={boot_qlike['obs_dm_stat']:.3f}")
print(f"    Bootstrap p-value: {boot_qlike['bootstrap_p_value']:.4f}")
print(f"    95% CI for mean QLIKE diff: [{boot_qlike['ci_95_lower']:.6f}, {boot_qlike['ci_95_upper']:.6f}]")

# Also try different block sizes for sensitivity
print("\n  Block size sensitivity analysis:")
for bsize in [10, 15, 21, 42, 63]:
    boot_s = block_bootstrap_dm(loss_o1, loss_o2, block_size=bsize, n_boot=10000, seed=42)
    print(f"    Block={bsize:2d}: bootstrap p={boot_s['bootstrap_p_value']:.4f}, CI=[{boot_s['ci_95_lower']:.2f}, {boot_s['ci_95_upper']:.2f}]")

# HAC DM with different lags
print("\n  HAC DM lag sensitivity:")
for lag in [5, 10, 15, 21, 42]:
    dm_s, dm_p, _ = dm_test_hac(loss_o1, loss_o2, max_lag=lag)
    print(f"    HAC lag={lag:2d}: DM stat={dm_s:.3f}, p={dm_p:.4f}")

bootstrap_results = {
    'n_oos': int(len(y_o_oos)),
    'qlike_baseline': qlike_o1,
    'qlike_vrp_augmented': qlike_o2,
    'qlike_improvement_pct': float(qlike_improv_o),
    'bootstrap_mse': boot_mse,
    'bootstrap_qlike': boot_qlike,
    'block_sensitivity': {},
    'hac_lag_sensitivity': {},
}

for bsize in [10, 15, 21, 42, 63]:
    boot_s = block_bootstrap_dm(loss_o1, loss_o2, block_size=bsize, n_boot=10000, seed=42)
    bootstrap_results['block_sensitivity'][f'block_{bsize}'] = {
        'p_value': boot_s['bootstrap_p_value'],
        'ci_lower': boot_s['ci_95_lower'],
        'ci_upper': boot_s['ci_95_upper'],
    }

for lag in [5, 10, 15, 21, 42]:
    dm_s, dm_p, _ = dm_test_hac(loss_o1, loss_o2, max_lag=lag)
    bootstrap_results['hac_lag_sensitivity'][f'lag_{lag}'] = {
        'dm_stat': dm_s,
        'p_value': dm_p,
    }

# ============================================================
# 9. NON-OVERLAPPING QUINTILE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("TEST 4: Non-overlapping VRP Quintile Analysis")
print("=" * 70)

# Use monthly non-overlapping data
vrp_breaks = is_monthly['vrp'].quantile([0.2, 0.4, 0.6, 0.8]).values
oos_monthly_q = oos_monthly.copy()
oos_monthly_q['vrp_quintile'] = pd.cut(
    oos_monthly_q['vrp'],
    bins=[-np.inf] + list(vrp_breaks) + [np.inf],
    labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']
)
oos_monthly_q['pred_baseline'] = pred_m1
oos_monthly_q['pred_vrp_aug'] = pred_m2

quintile_results_nonoverlap = {}
print(f"\n  {'Quintile':<12s} {'N':>5s} {'Mean_VRP':>10s} {'Mean_NextRV':>12s} {'MSE_Base':>10s} {'MSE_VRP+':>10s} {'Improv%':>8s}")
print(f"  {'-' * 70}")

for q_name in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    mask = oos_monthly_q['vrp_quintile'] == q_name
    if mask.sum() < 3:
        print(f"  {q_name:<12s}: insufficient obs ({mask.sum()})")
        quintile_results_nonoverlap[q_name] = {'n': int(mask.sum()), 'insufficient': True}
        continue

    sub = oos_monthly_q[mask]
    n_q = len(sub)
    mean_vrp = float(sub['vrp'].mean())
    mean_rv_next = float(sub['rv_next'].mean())
    mse_base = float(mse_loss(sub['rv_next'].values, sub['pred_baseline'].values))
    mse_vrp = float(mse_loss(sub['rv_next'].values, sub['pred_vrp_aug'].values))
    improv = (1 - mse_vrp / mse_base) * 100 if mse_base > 0 else 0.0

    print(f"  {q_name:<12s} {n_q:>5d} {mean_vrp:>10.2f} {mean_rv_next:>12.2f} {mse_base:>10.2f} {mse_vrp:>10.2f} {improv:>7.1f}%")

    quintile_results_nonoverlap[q_name] = {
        'n': n_q,
        'mean_vrp': mean_vrp,
        'mean_next_rv': mean_rv_next,
        'mse_baseline': mse_base,
        'mse_vrp_augmented': mse_vrp,
        'improvement_pct': float(improv),
    }

# ============================================================
# 10. ENCOMPASSING TEST (Forecast combination)
# ============================================================
print("\n" + "=" * 70)
print("TEST 5: Forecast Encompassing Test")
print("=" * 70)

# If M1 encompasses M2, then combining forecasts shouldn't help
# Test: rv_actual = a * pred_M1 + (1-a) * pred_M2 + error
# If a=1, M1 encompasses M2 (VRP adds nothing)
# Use non-overlapping monthly for clean inference

pred_diff_m = pred_m2 - pred_m1  # M2 - M1 prediction difference
X_encomp = sm.add_constant(np.column_stack([pred_m1, pred_diff_m]))
encomp_model = sm.OLS(y_m_oos, X_encomp).fit(cov_type='HAC', cov_kwds={'maxlags': 3})

print(f"\n  Encompassing test (non-overlapping monthly):")
print(f"  rv_next = a * pred_RV + b * (pred_VRP+ - pred_RV) + c")
print(f"  b = {encomp_model.params[2]:.4f}, t = {encomp_model.tvalues[2]:.3f}, p = {encomp_model.pvalues[2]:.4f}")
print(f"  → If b significant, VRP adds information beyond RV baseline")

encompassing_result = {
    'combination_weight': float(encomp_model.params[2]),
    't_stat': float(encomp_model.tvalues[2]),
    'p_value': float(encomp_model.pvalues[2]),
    'significant_5pct': bool(encomp_model.pvalues[2] < 0.05),
    'significant_10pct': bool(encomp_model.pvalues[2] < 0.10),
    'interpretation': 'VRP adds information' if encomp_model.pvalues[2] < 0.10 else 'M1 (RV) encompasses VRP',
}

# ============================================================
# 11. ROLLING OOS ANALYSIS (time-varying predictability)
# ============================================================
print("\n" + "=" * 70)
print("TEST 6: Rolling OOS Analysis (time-varying VRP predictability)")
print("=" * 70)

# 1-year rolling window on monthly non-overlapping data
window = 12  # 12 months ≈ 1 year
rolling_dm_stats = []

if len(oos_monthly) >= window + 5:
    for i in range(window, len(oos_monthly)):
        start = max(0, i - window)
        sub_loss1 = loss_m1[start:i]
        sub_loss2 = loss_m2[start:i]
        if len(sub_loss1) < window:
            continue
        d_roll = sub_loss1 - sub_loss2
        d_mean = d_roll.mean()
        d_se = d_roll.std() / np.sqrt(len(d_roll))
        dm_roll = d_mean / d_se if d_se > 1e-12 else 0.0
        rolling_dm_stats.append({
            'date': str(oos_monthly.index[i].date()),
            'dm_stat': float(dm_roll),
            'mean_loss_diff': float(d_mean),
        })

    if rolling_dm_stats:
        dm_stats_array = [r['dm_stat'] for r in rolling_dm_stats]
        print(f"\n  Rolling 1-year DM stats (N={len(rolling_dm_stats)} windows):")
        print(f"    Mean DM: {np.mean(dm_stats_array):.3f}")
        print(f"    Min DM: {np.min(dm_stats_array):.3f}, Max DM: {np.max(dm_stats_array):.3f}")
        print(f"    Fraction DM > 0 (VRP+ better): {np.mean(np.array(dm_stats_array) > 0):.2%}")
        print(f"    Fraction DM > 1.96 (significant): {np.mean(np.array(dm_stats_array) > 1.96):.2%}")
else:
    print(f"  Insufficient OOS data for rolling analysis (need {window + 5}, have {len(oos_monthly)})")
    rolling_dm_stats = []

# ============================================================
# 12. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("COMPREHENSIVE SUMMARY")
print("=" * 70)

print("\n  Reference: K430 original results")
print(f"    IS VRP t-stat: 4.38 (passes Harvey t>3.0)")
print(f"    OOS DM test: p=0.163 (not significant)")
print(f"    OOS QLIKE improvement: 16.7%")

print("\n  K436 Robustness findings:")

# Test 1 summary
print(f"\n  Test 1 — Non-overlapping monthly:")
print(f"    IS VRP t-stat: {ols_monthly_is.tvalues['vrp']:.3f}")
passes_harvey_monthly = abs(ols_monthly_is.tvalues['vrp']) > 3.0
print(f"    Harvey t>3.0: {'PASSES' if passes_harvey_monthly else 'FAILS'}")
print(f"    OOS QLIKE improvement: {qlike_improv_m:+.2f}%")
print(f"    DM test (HAC): stat={dm_m_stat:.3f}, p={dm_m_pval:.4f}")
print(f"    DM test (standard): stat={dm_m_simple_stat:.3f}, p={dm_m_simple_pval:.4f}")
print(f"    N (OOS): {n_monthly_oos}")

# Test 2 summary
print(f"\n  Test 2 — Daily frequency (no overlap):")
print(f"    IS VRP t-stat: {ols_daily_is.tvalues['vrp']:.3f}")
passes_harvey_daily = abs(ols_daily_is.tvalues['vrp']) > 3.0
print(f"    Harvey t>3.0: {'PASSES' if passes_harvey_daily else 'FAILS'}")
print(f"    OOS MSE improvement: {mse_improv_d:+.4f}%")
print(f"    DM test (HAC): stat={dm_d_stat:.3f}, p={dm_d_pval:.4f}")

# Test 3 summary
print(f"\n  Test 3 — Block bootstrap (overlapping data):")
print(f"    Bootstrap p-value (MSE): {boot_mse['bootstrap_p_value']:.4f}")
print(f"    Bootstrap p-value (QLIKE): {boot_qlike['bootstrap_p_value']:.4f}")
print(f"    95% CI MSE diff: [{boot_mse['ci_95_lower']:.4f}, {boot_mse['ci_95_upper']:.4f}]")
ci_excludes_zero = (boot_mse['ci_95_lower'] > 0) or (boot_mse['ci_95_upper'] < 0)
print(f"    CI excludes zero: {'YES' if ci_excludes_zero else 'NO'}")

# Test 5 summary
print(f"\n  Test 5 — Forecast encompassing:")
print(f"    VRP combination weight: {encompassing_result['combination_weight']:.4f}")
print(f"    t-stat: {encompassing_result['t_stat']:.3f}, p={encompassing_result['p_value']:.4f}")

# Overall conclusion
conclusions = []

# Non-overlapping monthly
if dm_m_pval < 0.05:
    conclusions.append(f"Non-overlapping monthly: VRP SIGNIFICANTLY improves vol prediction (DM p={dm_m_pval:.4f})")
elif dm_m_pval < 0.10:
    conclusions.append(f"Non-overlapping monthly: VRP marginally improves vol prediction (DM p={dm_m_pval:.4f})")
else:
    conclusions.append(f"Non-overlapping monthly: VRP improvement NOT significant (DM p={dm_m_pval:.4f}), low power with only {n_monthly_oos} obs")

# Daily
if dm_d_pval < 0.05:
    conclusions.append(f"Daily frequency: VRP SIGNIFICANTLY improves next-day |return| prediction (DM p={dm_d_pval:.4f})")
elif dm_d_pval < 0.10:
    conclusions.append(f"Daily frequency: VRP marginally improves next-day |return| prediction (DM p={dm_d_pval:.4f})")
else:
    conclusions.append(f"Daily frequency: VRP does NOT significantly improve next-day |return| prediction (DM p={dm_d_pval:.4f})")

# Bootstrap
if boot_mse['bootstrap_p_value'] < 0.05:
    conclusions.append(f"Block bootstrap: VRP improvement IS significant under proper inference (p={boot_mse['bootstrap_p_value']:.4f})")
elif boot_mse['bootstrap_p_value'] < 0.10:
    conclusions.append(f"Block bootstrap: VRP improvement marginally significant (p={boot_mse['bootstrap_p_value']:.4f})")
else:
    conclusions.append(f"Block bootstrap: VRP improvement NOT significant even with proper inference (p={boot_mse['bootstrap_p_value']:.4f})")

# Encompassing
if encompassing_result['significant_5pct']:
    conclusions.append(f"Encompassing test: VRP adds significant information beyond RV baseline (p={encompassing_result['p_value']:.4f})")
elif encompassing_result['significant_10pct']:
    conclusions.append(f"Encompassing test: VRP marginally adds information (p={encompassing_result['p_value']:.4f})")
else:
    conclusions.append(f"Encompassing test: RV baseline encompasses VRP (p={encompassing_result['p_value']:.4f})")

# Overall verdict
monthly_sig = dm_m_pval < 0.10
daily_sig = dm_d_pval < 0.10
boot_sig = boot_mse['bootstrap_p_value'] < 0.10
encomp_sig = encompassing_result['significant_10pct']
n_sig = sum([monthly_sig, daily_sig, boot_sig, encomp_sig])

if n_sig >= 3:
    verdict = "UPGRADE: VRP has genuine predictive power (multiple robustness tests pass)"
elif n_sig >= 2:
    verdict = "MIXED: VRP shows some predictive signal but not fully robust"
elif n_sig == 1:
    verdict = "WEAK: VRP predictability appears fragile, likely sample-specific"
else:
    verdict = "REJECT: VRP predictability does NOT survive robustness tests (K430 likely overfitted)"

conclusions.append(f"\nOverall verdict: {verdict}")
conclusions.append(f"  Tests passing at 10%: {n_sig}/4 (monthly, daily, bootstrap, encompassing)")

# Harvey threshold
conclusions.append(f"\nHarvey (2016) t>3.0 check:")
conclusions.append(f"  Monthly non-overlapping VRP t: {ols_monthly_is.tvalues['vrp']:.3f} → {'PASSES' if passes_harvey_monthly else 'FAILS'}")
conclusions.append(f"  Daily VRP t: {ols_daily_is.tvalues['vrp']:.3f} → {'PASSES' if passes_harvey_daily else 'FAILS'}")

# Literature comparison
conclusions.append(f"\nLiterature comparison:")
conclusions.append(f"  Bollerslev et al. (2009): VRP predicts equity premium (our focus: vol, not returns)")
conclusions.append(f"  Bekaert & Hoerova (2014): VP (not full VIX) predicts returns; E[RV] predicts vol")
conclusions.append(f"  Our finding: VRP (VIX - RV) for vol prediction — {'consistent' if n_sig >= 2 else 'weaker than'} the literature")

print(f"\n  Conclusions:")
for i, c in enumerate(conclusions, 1):
    print(f"    {i}. {c}")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'k436',
    'title': 'VRP Predictability Robustness Test (Non-overlapping + Bootstrap)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df_daily.index[0].date()} to {df_daily.index[-1].date()}",
    'oos_start': oos_start,
    'reference_experiment': 'K430 (VRP Predictability, IS t=4.38, OOS DM p=0.163)',
    'literature': [
        'Bollerslev, Tauchen, Zhou (2009) RFS 22(11):4463-4492 — VRP predicts excess returns',
        'Bekaert & Hoerova (2014) JoE 183(2):181-192 — VRP decomposition: VP→returns, E[RV]→vol',
    ],
    'descriptive_statistics': desc_stats,
    'adf_test_vrp': {
        'statistic': float(adf_result[0]),
        'p_value': float(adf_result[1]),
        'stationary': bool(adf_result[1] < 0.05),
    },
    'test1_non_overlapping_monthly': monthly_results,
    'test2_daily_frequency': daily_results,
    'test3_block_bootstrap': bootstrap_results,
    'test4_quintile_non_overlapping': quintile_results_nonoverlap,
    'test5_forecast_encompassing': encompassing_result,
    'test6_rolling_oos': {
        'window_months': 12,
        'n_windows': len(rolling_dm_stats),
        'stats': rolling_dm_stats[-5:] if rolling_dm_stats else [],
        'summary': {
            'mean_dm': float(np.mean([r['dm_stat'] for r in rolling_dm_stats])) if rolling_dm_stats else None,
            'frac_positive': float(np.mean([r['dm_stat'] > 0 for r in rolling_dm_stats])) if rolling_dm_stats else None,
            'frac_significant': float(np.mean([r['dm_stat'] > 1.96 for r in rolling_dm_stats])) if rolling_dm_stats else None,
        },
    },
    'overall_verdict': verdict,
    'n_tests_passing_10pct': n_sig,
    'harvey_threshold': {
        'monthly_vrp_t': float(ols_monthly_is.tvalues['vrp']),
        'daily_vrp_t': float(ols_daily_is.tvalues['vrp']),
        'monthly_passes': passes_harvey_monthly,
        'daily_passes': passes_harvey_daily,
    },
    'conclusions': conclusions,
    'limitations': [
        'Non-overlapping monthly reduces sample to ~36 OOS observations (low power)',
        'Daily abs_ret is noisy; VRP is a slow-moving predictor for daily variation',
        'Block bootstrap assumes stationary blocks; if regime shifts occur within OOS, blocks may not capture this',
        'VRP proxy uses VIX (30d implied) vs 21d realized — maturity mismatch (per K430)',
        'OOS period (2023-2025) is relatively calm, limiting test of VRP in crisis periods',
    ],
    'prior_knowledge': [
        'K430: VRP IS t=4.38 passes Harvey, OOS DM p=0.163 not significant',
        'K430: VRP provides 16.7% QLIKE improvement over RV baseline',
        'K430: VRP more predictive in extreme quintiles (Q1, Q5)',
        'K-series: VRP is NOT a return predictor for SPY',
    ],
}

output_path = 'experiments/k436_vrp_robustness_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Saved to {output_path}")
print("\n  DONE.")
