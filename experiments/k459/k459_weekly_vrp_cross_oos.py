"""
K459: Weekly VRP Cross-OOS Validation (5 OOS Periods)

Background:
  K457 found VRP is 100% significant at weekly frequency (every rolling window |t|>2).
  This is a strong finding, but only tested on one OOS period (2023-2025).
  Per research_program.md: "at least 5 OOS periods" required for robust conclusions (J9 lesson).

Design:
  5 OOS periods:
    1. 2015-2016 (low volatility)
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2025 (post-COVID recovery)

  For each OOS period:
    - IS: preceding 8 years (~400 weeks)
    - OOS: 2 years (~104 weeks)
    - Compare: Baseline (lagged RV) vs VIX-only vs VRP model (Ridge regression)
    - Metrics: QLIKE, MSE, DM test

  Models:
    1. Baseline: next_week_RV ~ const + RV_lag
    2. VIX-only: next_week_RV ~ const + VIX_weekly_var
    3. VRP model: next_week_RV ~ const + VRP + RV_lag

Data: yfinance (SPY, ^VIX), 2005-01-01 to present
Frequency: Weekly (Friday-to-Friday)
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
from sklearn.linear_model import Ridge

warnings.filterwarnings('ignore')

print("=" * 70)
print("K459: Weekly VRP Cross-OOS Validation (5 OOS Periods)")
print("  Publication-critical: Does VRP weekly hold across all regimes?")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start='2004-01-01', progress=False)
vix_raw = yf.download('^VIX', start='2004-01-01', progress=False)

# Handle MultiIndex columns
for df_raw in [spy_raw, vix_raw]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

spy_close = spy_raw['Close'].copy()
vix_close = vix_raw['Close'].copy()

print(f"  SPY daily: {spy_close.index[0].date()} to {spy_close.index[-1].date()} ({len(spy_close)} obs)")
print(f"  VIX daily: {vix_close.index[0].date()} to {vix_close.index[-1].date()} ({len(vix_close)} obs)")

# ============================================================
# 2. CONSTRUCT WEEKLY DATA
# ============================================================
print("\n[2] Constructing weekly data...")

# Daily returns
daily_ret = spy_close.pct_change().dropna()

# Weekly prices (Friday close)
weekly_close = spy_close.resample('W-FRI').last().dropna()
weekly_ret = weekly_close.pct_change().dropna()

# Weekly realized variance = sum of daily squared returns within each week
daily_ret_sq = daily_ret ** 2
weekly_rv = daily_ret_sq.resample('W-FRI').sum().reindex(weekly_ret.index)

# Weekly VIX (Friday close)
weekly_vix = vix_close.resample('W-FRI').last().reindex(weekly_ret.index)

# Weekly VRP: VIX - annualized realized vol (based on past 4 weeks of daily data)
# RV annualized = sqrt(rv_4week * 52/4) * 100
rv_4week = daily_ret_sq.rolling(20).sum()
rv_4week_weekly = rv_4week.resample('W-FRI').last().reindex(weekly_ret.index)
rv_ann = np.sqrt(rv_4week_weekly * 52 / 4) * 100
weekly_vrp = weekly_vix - rv_ann

# VIX-implied weekly variance: (VIX/100)^2 / 52
weekly_vix_var = (weekly_vix / 100)**2 / 52

# Align all series to common index
common_idx = weekly_ret.index.intersection(weekly_rv.index).intersection(weekly_vix.dropna().index)
common_idx = common_idx.intersection(weekly_vrp.dropna().index)
common_idx = common_idx[common_idx >= '2005-01-01']

weekly_ret = weekly_ret.reindex(common_idx)
weekly_rv = weekly_rv.reindex(common_idx)
weekly_vix = weekly_vix.reindex(common_idx)
weekly_vrp = weekly_vrp.reindex(common_idx)
weekly_vix_var = weekly_vix_var.reindex(common_idx)

# Drop any remaining NaN
valid_mask = ~(weekly_rv.isna() | weekly_vix.isna() | weekly_vrp.isna() | weekly_vix_var.isna())
common_idx = common_idx[valid_mask]
weekly_ret = weekly_ret.reindex(common_idx)
weekly_rv = weekly_rv.reindex(common_idx)
weekly_vix = weekly_vix.reindex(common_idx)
weekly_vrp = weekly_vrp.reindex(common_idx)
weekly_vix_var = weekly_vix_var.reindex(common_idx)

print(f"  Weekly obs: {len(common_idx)} ({common_idx[0].date()} to {common_idx[-1].date()})")
print(f"  Weekly ret: mean={weekly_ret.mean()*100:.3f}%, std={weekly_ret.std()*100:.3f}%")
print(f"  Weekly RV: mean={weekly_rv.mean()*1e4:.2f}bps², std={weekly_rv.std()*1e4:.2f}bps²")
print(f"  Weekly VRP: mean={weekly_vrp.mean():.2f}, std={weekly_vrp.std():.2f}")

# ============================================================
# 3. DATA DIAGNOSTICS (REQUIRED)
# ============================================================
print("\n[3] Data diagnostics on weekly returns...")
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

ret_vals = weekly_ret.values
print(f"  Mean:     {np.mean(ret_vals)*100:.4f}%")
print(f"  Std:      {np.std(ret_vals)*100:.4f}%")
print(f"  Skewness: {stats.skew(ret_vals):.4f}")
print(f"  Kurtosis: {stats.kurtosis(ret_vals):.4f} (excess)")

# ADF test
adf_stat, adf_p, _, _, _, _ = adfuller(ret_vals)
print(f"  ADF test: stat={adf_stat:.4f}, p={adf_p:.6f} {'(stationary)' if adf_p < 0.05 else '(NON-STATIONARY)'}")

# ARCH LM test
arch_lm = het_arch(ret_vals, nlags=5)
print(f"  ARCH LM(5): stat={arch_lm[0]:.4f}, p={arch_lm[1]:.6f} {'(ARCH effects)' if arch_lm[1] < 0.05 else '(no ARCH)'}")

# Ljung-Box on squared returns
lb_sq = acorr_ljungbox(ret_vals**2, lags=[5, 10], return_df=True)
print(f"  Ljung-Box(5) r²: stat={lb_sq.iloc[0, 0]:.4f}, p={lb_sq.iloc[0, 1]:.6f}")

# VRP diagnostics
vrp_vals = weekly_vrp.values
print(f"\n  VRP diagnostics:")
print(f"    Mean: {np.mean(vrp_vals):.4f}")
print(f"    Std:  {np.std(vrp_vals):.4f}")
print(f"    Skew: {stats.skew(vrp_vals):.4f}")
print(f"    Kurt: {stats.kurtosis(vrp_vals):.4f}")
print(f"    % positive: {(vrp_vals > 0).mean()*100:.1f}%")

# ============================================================
# 4. DEFINE 5 OOS PERIODS
# ============================================================
print("\n[4] Defining 5 OOS periods...")

oos_periods = [
    {"name": "2015-2016 (low vol)", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2025 (post-COVID)", "start": "2023-01-01", "end": "2025-12-31"},
]

window = 400  # weeks (~7.7 years)

for period in oos_periods:
    oos_mask = (common_idx >= period["start"]) & (common_idx <= period["end"])
    n_oos = oos_mask.sum()
    first_oos_pos = np.where(oos_mask)[0][0] if n_oos > 0 else None
    available_is = first_oos_pos if first_oos_pos is not None else 0
    print(f"  {period['name']}: {n_oos} weeks, IS available: {available_is} weeks")
    if available_is < window:
        print(f"    WARNING: IS shorter than {window} weeks, will use {available_is} weeks")


# ============================================================
# 5. HELPER: Diebold-Mariano Test
# ============================================================
def dm_test(e1, e2, h=1, loss='qlike'):
    """Diebold-Mariano test for forecast comparison.
    e1, e2: forecast errors or loss differentials.
    For QLIKE: loss = -log(sigma2_hat) - rv/sigma2_hat
    For MSE: loss = (rv - sigma2_hat)^2
    H0: equal predictive accuracy.
    Returns (t_stat, p_value).
    """
    d = e1 - e2  # loss differential
    n = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * (1 - k/h) * gamma_k

    if hac_var <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(hac_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return t_stat, p_value


def qlike_loss(rv_actual, rv_forecast):
    """QLIKE loss: log(forecast) + actual/forecast. Lower is better."""
    rv_forecast = np.maximum(rv_forecast, 1e-10)  # avoid log(0)
    return np.log(rv_forecast) + rv_actual / rv_forecast


def mse_loss(rv_actual, rv_forecast):
    """MSE loss: (actual - forecast)^2."""
    return (rv_actual - rv_forecast) ** 2


# ============================================================
# 6. CROSS-OOS EVALUATION
# ============================================================
print("\n[5] Running Cross-OOS evaluation for 5 periods...")

all_results = {}

for period_idx, period in enumerate(oos_periods):
    pname = period["name"]
    print(f"\n{'='*60}")
    print(f"  Period {period_idx+1}/5: {pname}")
    print(f"{'='*60}")

    oos_mask = (common_idx >= period["start"]) & (common_idx <= period["end"])
    oos_weeks = common_idx[oos_mask]
    n_oos = len(oos_weeks)

    if n_oos < 10:
        print(f"  SKIP: only {n_oos} OOS weeks")
        continue

    # Get positions in the common_idx
    all_dates = common_idx
    oos_positions = [i for i, d in enumerate(all_dates) if d in oos_weeks]

    print(f"  OOS weeks: {n_oos}")
    print(f"  OOS range: {oos_weeks[0].date()} to {oos_weeks[-1].date()}")

    # Storage for this period
    fc_baseline = []
    fc_vix = []
    fc_vrp = []
    actuals = []

    vrp_tstats_period = []
    vrp_coefs_period = []
    rv_lag_tstats_vrp = []
    vix_tstats_period = []
    baseline_r2s = []
    vrp_r2s = []

    for pos in oos_positions:
        # Training window
        start_pos = max(0, pos - window)
        actual_window = pos - start_pos

        # Training data
        train_rv = weekly_rv.iloc[start_pos:pos].values
        train_vix_var = weekly_vix_var.iloc[start_pos:pos].values
        train_vrp = weekly_vrp.iloc[start_pos:pos].values

        # Target: next week RV
        if pos + 1 >= len(all_dates):
            continue
        target_rv = weekly_rv.iloc[pos]
        if np.isnan(target_rv):
            continue

        actuals.append(target_rv)

        # Prepare regression data (predict RV_{t+1} from features at t)
        y_train = train_rv[1:]  # RV at t+1
        rv_lag = train_rv[:-1]  # RV at t
        vix_var_lag = train_vix_var[:-1]  # VIX-implied var at t
        vrp_lag = train_vrp[:-1]  # VRP at t

        valid = ~(np.isnan(y_train) | np.isnan(rv_lag) | np.isnan(vix_var_lag) | np.isnan(vrp_lag))

        if valid.sum() < 30:
            fc_baseline.append(np.nan)
            fc_vix.append(np.nan)
            fc_vrp.append(np.nan)
            continue

        y = y_train[valid]
        rv_l = rv_lag[valid]
        vix_v = vix_var_lag[valid]
        vrp_l = vrp_lag[valid]

        # ---- Model 1: Baseline (RV_lag only) ----
        X_base = sm.add_constant(rv_l)
        ols_base = sm.OLS(y, X_base).fit()
        X_fc_base = np.array([1.0, train_rv[-1]])
        pred_base = ols_base.predict(X_fc_base.reshape(1, -1))[0]
        fc_baseline.append(max(pred_base, 1e-10))
        baseline_r2s.append(ols_base.rsquared)

        # ---- Model 2: VIX-only ----
        X_vix = sm.add_constant(vix_v)
        ols_vix = sm.OLS(y, X_vix).fit()
        X_fc_vix = np.array([1.0, train_vix_var[-1]])
        pred_vix = ols_vix.predict(X_fc_vix.reshape(1, -1))[0]
        fc_vix.append(max(pred_vix, 1e-10))
        vix_tstats_period.append(ols_vix.tvalues[1])

        # ---- Model 3: VRP model (VRP + RV_lag) ----
        # Use Ridge to avoid multicollinearity issues
        X_vrp_raw = np.column_stack([vrp_l, rv_l])

        # Also run OLS for t-stats (Ridge doesn't give standard t-stats)
        X_vrp_ols = sm.add_constant(X_vrp_raw)
        ols_vrp = sm.OLS(y, X_vrp_ols).fit()
        vrp_tstats_period.append(ols_vrp.tvalues[1])  # VRP t-stat
        vrp_coefs_period.append(ols_vrp.params[1])    # VRP coefficient
        rv_lag_tstats_vrp.append(ols_vrp.tvalues[2])   # RV_lag t-stat in VRP model
        vrp_r2s.append(ols_vrp.rsquared)

        # Ridge regression for forecasting (more stable)
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_vrp_raw, y)
        X_fc_vrp = np.array([[train_vrp[-1], train_rv[-1]]])
        pred_vrp = ridge.predict(X_fc_vrp)[0]
        # Also add intercept correction: use mean of y to center
        fc_vrp.append(max(pred_vrp, 1e-10))

        vrp_r2s.append(ols_vrp.rsquared)

    # Convert to arrays
    actuals = np.array(actuals)
    fc_baseline = np.array(fc_baseline)
    fc_vix = np.array(fc_vix)
    fc_vrp = np.array(fc_vrp)

    # Remove NaN entries
    valid = ~(np.isnan(fc_baseline) | np.isnan(fc_vix) | np.isnan(fc_vrp) | np.isnan(actuals))
    actuals = actuals[valid]
    fc_baseline = fc_baseline[valid]
    fc_vix = fc_vix[valid]
    fc_vrp = fc_vrp[valid]

    n_valid = len(actuals)
    print(f"\n  Valid OOS forecasts: {n_valid}")

    if n_valid < 10:
        print(f"  SKIP: too few valid forecasts")
        continue

    # ---- Compute losses ----
    ql_baseline = qlike_loss(actuals, fc_baseline)
    ql_vix = qlike_loss(actuals, fc_vix)
    ql_vrp = qlike_loss(actuals, fc_vrp)

    mse_baseline_arr = mse_loss(actuals, fc_baseline)
    mse_vix_arr = mse_loss(actuals, fc_vix)
    mse_vrp_arr = mse_loss(actuals, fc_vrp)

    mean_ql = {
        "baseline": float(np.mean(ql_baseline)),
        "vix_only": float(np.mean(ql_vix)),
        "vrp_model": float(np.mean(ql_vrp)),
    }
    mean_mse = {
        "baseline": float(np.mean(mse_baseline_arr)),
        "vix_only": float(np.mean(mse_vix_arr)),
        "vrp_model": float(np.mean(mse_vrp_arr)),
    }

    print(f"\n  QLIKE (lower=better):")
    print(f"    Baseline (RV_lag): {mean_ql['baseline']:.6f}")
    print(f"    VIX-only:          {mean_ql['vix_only']:.6f}")
    print(f"    VRP model:         {mean_ql['vrp_model']:.6f}")

    print(f"\n  MSE:")
    print(f"    Baseline (RV_lag): {mean_mse['baseline']:.4e}")
    print(f"    VIX-only:          {mean_mse['vix_only']:.4e}")
    print(f"    VRP model:         {mean_mse['vrp_model']:.4e}")

    # ---- DM Tests ----
    # VRP vs Baseline (QLIKE)
    dm_vrp_vs_base_ql = dm_test(ql_vrp, ql_baseline, h=1)
    # VRP vs VIX-only (QLIKE)
    dm_vrp_vs_vix_ql = dm_test(ql_vrp, ql_vix, h=1)
    # VRP vs Baseline (MSE)
    dm_vrp_vs_base_mse = dm_test(mse_vrp_arr, mse_baseline_arr, h=1)
    # VRP vs VIX-only (MSE)
    dm_vrp_vs_vix_mse = dm_test(mse_vrp_arr, mse_vix_arr, h=1)

    print(f"\n  DM tests (negative t = VRP better):")
    print(f"    VRP vs Baseline (QLIKE): t={dm_vrp_vs_base_ql[0]:.3f}, p={dm_vrp_vs_base_ql[1]:.4f}")
    print(f"    VRP vs VIX-only (QLIKE): t={dm_vrp_vs_vix_ql[0]:.3f}, p={dm_vrp_vs_vix_ql[1]:.4f}")
    print(f"    VRP vs Baseline (MSE):   t={dm_vrp_vs_base_mse[0]:.3f}, p={dm_vrp_vs_base_mse[1]:.4f}")
    print(f"    VRP vs VIX-only (MSE):   t={dm_vrp_vs_vix_mse[0]:.3f}, p={dm_vrp_vs_vix_mse[1]:.4f}")

    # ---- VRP significance in this period ----
    vrp_tstats_arr = np.array(vrp_tstats_period)
    vrp_pct_sig = float((np.abs(vrp_tstats_arr) > 2.0).mean() * 100)
    vrp_pct_sig_3 = float((np.abs(vrp_tstats_arr) > 3.0).mean() * 100)

    print(f"\n  VRP coefficient in rolling windows:")
    print(f"    Mean t-stat:    {np.mean(vrp_tstats_arr):.3f}")
    print(f"    Median t-stat:  {np.median(vrp_tstats_arr):.3f}")
    print(f"    % |t|>2:        {vrp_pct_sig:.1f}%")
    print(f"    % |t|>3:        {vrp_pct_sig_3:.1f}%")
    print(f"    Mean coef:      {np.mean(vrp_coefs_period):.6e}")
    print(f"    Coef sign:      {(np.array(vrp_coefs_period) > 0).mean()*100:.1f}% positive")

    # ---- Mincer-Zarnowitz for each model ----
    mz_results = {}
    for model_name, preds in [("baseline", fc_baseline), ("vix_only", fc_vix), ("vrp_model", fc_vrp)]:
        X_mz = sm.add_constant(preds)
        mz_ols = sm.OLS(actuals, X_mz).fit()
        mz_results[model_name] = {
            "intercept": float(mz_ols.params[0]),
            "slope": float(mz_ols.params[1]),
            "R2": float(mz_ols.rsquared),
            "t_b1_eq_1": float((mz_ols.params[1] - 1) / mz_ols.bse[1]),
        }

    print(f"\n  Mincer-Zarnowitz R²:")
    for m, r in mz_results.items():
        print(f"    {m:12s}: slope={r['slope']:.4f}, R²={r['R2']:.4f}")

    # Store results for this period
    period_result = {
        "name": pname,
        "oos_start": period["start"],
        "oos_end": period["end"],
        "n_oos_weeks": n_valid,
        "qlike": mean_ql,
        "mse": mean_mse,
        "qlike_ranking": sorted(mean_ql.items(), key=lambda x: x[1]),
        "mse_ranking": sorted(mean_mse.items(), key=lambda x: x[1]),
        "dm_tests": {
            "vrp_vs_baseline_qlike": {"t_stat": float(dm_vrp_vs_base_ql[0]), "p_value": float(dm_vrp_vs_base_ql[1])},
            "vrp_vs_vix_qlike": {"t_stat": float(dm_vrp_vs_vix_ql[0]), "p_value": float(dm_vrp_vs_vix_ql[1])},
            "vrp_vs_baseline_mse": {"t_stat": float(dm_vrp_vs_base_mse[0]), "p_value": float(dm_vrp_vs_base_mse[1])},
            "vrp_vs_vix_mse": {"t_stat": float(dm_vrp_vs_vix_mse[0]), "p_value": float(dm_vrp_vs_vix_mse[1])},
        },
        "vrp_significance": {
            "mean_tstat": float(np.mean(vrp_tstats_arr)),
            "median_tstat": float(np.median(vrp_tstats_arr)),
            "std_tstat": float(np.std(vrp_tstats_arr)),
            "pct_abs_t_gt_2": vrp_pct_sig,
            "pct_abs_t_gt_3": vrp_pct_sig_3,
            "mean_coef": float(np.mean(vrp_coefs_period)),
            "pct_positive_coef": float((np.array(vrp_coefs_period) > 0).mean() * 100),
            "n_windows": len(vrp_tstats_period),
        },
        "vix_significance": {
            "mean_tstat": float(np.mean(vix_tstats_period)),
            "pct_abs_t_gt_2": float((np.abs(np.array(vix_tstats_period)) > 2.0).mean() * 100),
        },
        "mincer_zarnowitz": mz_results,
        "in_sample_r2": {
            "baseline_mean": float(np.mean(baseline_r2s)),
            "vrp_mean": float(np.mean(vrp_r2s)),
            "r2_improvement": float(np.mean(vrp_r2s) - np.mean(baseline_r2s)),
        },
    }

    all_results[f"period_{period_idx+1}"] = period_result

# ============================================================
# 7. CROSS-PERIOD SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("  CROSS-OOS SUMMARY")
print("=" * 70)

n_periods = len(all_results)
n_vrp_wins_qlike = 0
n_vrp_wins_mse = 0
n_vrp_sig = 0
n_vrp_sig_harvey = 0
all_vrp_tstats = []
all_dm_tstats_qlike = []
all_dm_tstats_mse = []

print(f"\n{'Period':<30} {'QLIKE best':>12} {'MSE best':>12} {'VRP %|t|>2':>12} {'DM(QL)':>10} {'DM(MSE)':>10}")
print("-" * 90)

for key, res in all_results.items():
    ql_rank = res["qlike_ranking"]
    mse_rank = res["mse_ranking"]
    qlike_best = ql_rank[0][0]
    mse_best = mse_rank[0][0]

    vrp_sig_pct = res["vrp_significance"]["pct_abs_t_gt_2"]
    dm_ql_t = res["dm_tests"]["vrp_vs_baseline_qlike"]["t_stat"]
    dm_mse_t = res["dm_tests"]["vrp_vs_baseline_mse"]["t_stat"]

    if qlike_best == "vrp_model":
        n_vrp_wins_qlike += 1
    if mse_best == "vrp_model":
        n_vrp_wins_mse += 1
    if vrp_sig_pct >= 50:
        n_vrp_sig += 1
    if res["vrp_significance"]["pct_abs_t_gt_3"] >= 50:
        n_vrp_sig_harvey += 1

    all_vrp_tstats.append(res["vrp_significance"]["mean_tstat"])
    all_dm_tstats_qlike.append(dm_ql_t)
    all_dm_tstats_mse.append(dm_mse_t)

    print(f"  {res['name']:<28} {qlike_best:>12} {mse_best:>12} {vrp_sig_pct:>10.1f}% {dm_ql_t:>10.3f} {dm_mse_t:>10.3f}")

print("-" * 90)

# Overall assessment
print(f"\n  VRP wins QLIKE: {n_vrp_wins_qlike}/{n_periods}")
print(f"  VRP wins MSE:   {n_vrp_wins_mse}/{n_periods}")
print(f"  VRP >50% |t|>2: {n_vrp_sig}/{n_periods}")
print(f"  VRP >50% |t|>3 (Harvey): {n_vrp_sig_harvey}/{n_periods}")
print(f"  Mean VRP t-stat across periods: {np.mean(all_vrp_tstats):.3f}")

# Robustness verdict
if n_vrp_sig == n_periods:
    verdict = "ROBUST: VRP significant in ALL periods"
elif n_vrp_sig >= 4:
    verdict = "MOSTLY ROBUST: VRP significant in 4/5 periods"
elif n_vrp_sig >= 3:
    verdict = "PARTIAL: VRP significant in 3/5 periods (regime-dependent)"
else:
    verdict = "WEAK: VRP significance is period-specific, NOT robust"

print(f"\n  VERDICT: {verdict}")

# ============================================================
# 8. POOLED DM TEST (across all periods)
# ============================================================
print("\n[6] Pooled analysis across all periods...")

# Collect all VRP t-stats across all windows in all periods
all_window_tstats = []
for key, res in all_results.items():
    # We stored n_windows and mean_tstat; reconstruct approximate stats
    pass  # We'll use the summary stats

# Meta-analysis: combine DM test statistics
if len(all_dm_tstats_qlike) > 1:
    combined_dm_ql = np.mean(all_dm_tstats_qlike) / (np.std(all_dm_tstats_qlike) / np.sqrt(len(all_dm_tstats_qlike)))
    combined_dm_mse = np.mean(all_dm_tstats_mse) / (np.std(all_dm_tstats_mse) / np.sqrt(len(all_dm_tstats_mse)))
    print(f"  Combined DM (QLIKE): z={combined_dm_ql:.3f} (avg t / SE across periods)")
    print(f"  Combined DM (MSE):   z={combined_dm_mse:.3f}")
else:
    combined_dm_ql = all_dm_tstats_qlike[0] if all_dm_tstats_qlike else 0
    combined_dm_mse = all_dm_tstats_mse[0] if all_dm_tstats_mse else 0

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print("\n[7] Saving results...")

final_results = {
    "experiment_id": "K459",
    "title": "Weekly VRP Cross-OOS Validation (5 Periods)",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX)",
    "data_period": f"2005-01-01 to {common_idx[-1].date()}",
    "frequency": "weekly (Friday-to-Friday)",
    "rolling_window": window,
    "n_weekly_obs_total": len(common_idx),
    "models": {
        "baseline": "OLS: next_week_RV ~ const + RV_lag",
        "vix_only": "OLS: next_week_RV ~ const + VIX_weekly_var",
        "vrp_model": "Ridge(alpha=1): next_week_RV ~ VRP + RV_lag (OLS for t-stats)",
    },
    "diagnostics": {
        "adf_stat": float(adf_stat),
        "adf_p": float(adf_p),
        "arch_lm_stat": float(arch_lm[0]),
        "arch_lm_p": float(arch_lm[1]),
        "has_arch_effects": bool(arch_lm[1] < 0.05),
        "vrp_mean": float(np.mean(vrp_vals)),
        "vrp_std": float(np.std(vrp_vals)),
        "vrp_pct_positive": float((vrp_vals > 0).mean() * 100),
    },
    "period_results": {},
    "cross_oos_summary": {
        "n_periods": n_periods,
        "vrp_wins_qlike": n_vrp_wins_qlike,
        "vrp_wins_mse": n_vrp_wins_mse,
        "vrp_sig_50pct_t2": n_vrp_sig,
        "vrp_sig_50pct_t3_harvey": n_vrp_sig_harvey,
        "mean_vrp_tstat_across_periods": float(np.mean(all_vrp_tstats)),
        "dm_tstats_qlike_per_period": [float(x) for x in all_dm_tstats_qlike],
        "dm_tstats_mse_per_period": [float(x) for x in all_dm_tstats_mse],
        "combined_dm_qlike": float(combined_dm_ql),
        "combined_dm_mse": float(combined_dm_mse),
        "verdict": verdict,
    },
}

# Add per-period results (convert tuples to lists for JSON)
for key, res in all_results.items():
    res_clean = dict(res)
    res_clean["qlike_ranking"] = [[k, v] for k, v in res["qlike_ranking"]]
    res_clean["mse_ranking"] = [[k, v] for k, v in res["mse_ranking"]]
    final_results["period_results"][key] = res_clean

# Notes
final_results["notes"] = {
    "methodology": "Rolling window OLS/Ridge regression. Each OOS week: re-estimate on prior 400 weeks, forecast next week RV.",
    "vrp_definition": "VRP = VIX - annualized 4-week realized vol. Positive VRP = implied > realized (normal).",
    "ridge_rationale": "Ridge(alpha=1) for forecasting stability; OLS for significance testing (t-stats).",
    "qlike_interpretation": "QLIKE is scale-invariant and preferred for variance forecasting (Patton 2011). Negative t in DM = VRP model better.",
    "limitations": [
        "Only SPY tested (single asset)",
        "VRP proxy uses 4-week rolling RV (not intraday estimator)",
        "Ridge alpha=1 not optimized per period",
        "Weekly frequency limits sample size per OOS period",
    ],
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a8d05275/experiments/k459_weekly_vrp_cross_oos_results.json'
with open(output_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"  Saved to: {output_path}")
print(f"\n  VERDICT: {verdict}")
print("\nDone.")
