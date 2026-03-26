"""
K457: Weekly Frequency Volatility Prediction — Different Frequency Challenges

Background:
  Our 1000+ experiments are almost entirely at daily frequency. But investors care
  more about weekly/monthly vol. This experiment systematically evaluates vol
  prediction models at weekly frequency.

Research Questions:
  1. Does the daily QLIKE ceiling (GJR unbeatable) persist at weekly frequency?
  2. Is GJR gamma still significant at weekly frequency?
  3. Do exogenous variables (VIX, VRP) have stronger predictive power at weekly?
     (lower noise hypothesis)
  4. Does semivariance decomposition work better at weekly frequency?

Literature:
  - Andersen et al. (2003): Realized volatility at different frequencies
  - Corsi (2009) HAR: Multi-scale RV components
  - Ghysels et al. (2006) MIDAS: Mixed-frequency regression

Data: yfinance (SPY, ^VIX), 2005-01-01 to present
Frequency: Weekly (Friday-to-Friday)
OOS: 2023-01-01 to 2025-12-31 (~104 weeks)
Window: 400 weeks (~8 years)
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch

warnings.filterwarnings('ignore')

print("=" * 70)
print("K457: Weekly Frequency Volatility Prediction")
print("  Does the daily QLIKE ceiling persist at weekly frequency?")
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

# Count trading days per week (for annualization)
daily_count_per_week = daily_ret.resample('W-FRI').count().reindex(weekly_ret.index)

# Weekly VIX (Friday close)
weekly_vix = vix_close.resample('W-FRI').last().reindex(weekly_ret.index)

# Weekly VRP: VIX - annualized realized vol (based on past 4 weeks of daily data)
# RV annualized = sqrt(rv_4week * 52/4) * 100
rv_4week = daily_ret_sq.rolling(20).sum()
rv_4week_weekly = rv_4week.resample('W-FRI').last().reindex(weekly_ret.index)
rv_ann = np.sqrt(rv_4week_weekly * 52 / 4) * 100
weekly_vrp = weekly_vix - rv_ann

# Weekly semivariance: sum of squared negative daily returns within week
daily_neg_ret_sq = daily_ret.apply(lambda x: x**2 if x < 0 else 0)
daily_pos_ret_sq = daily_ret.apply(lambda x: x**2 if x >= 0 else 0)
weekly_rs_neg = daily_neg_ret_sq.resample('W-FRI').sum().reindex(weekly_ret.index)
weekly_rs_pos = daily_pos_ret_sq.resample('W-FRI').sum().reindex(weekly_ret.index)

# HAR-like daily RV components aggregated to weekly
# 1-day RV (last day of week), 5-day RV, 22-day RV
rv_1d = daily_ret_sq.copy()
rv_5d = daily_ret_sq.rolling(5).mean()
rv_22d = daily_ret_sq.rolling(22).mean()

# Sample at end of each week
weekly_rv_1d = rv_1d.resample('W-FRI').last().reindex(weekly_ret.index)
weekly_rv_5d = rv_5d.resample('W-FRI').last().reindex(weekly_ret.index)
weekly_rv_22d = rv_22d.resample('W-FRI').last().reindex(weekly_ret.index)

# Align all series to common index
common_idx = weekly_ret.index.intersection(weekly_rv.index).intersection(weekly_vix.dropna().index)
common_idx = common_idx[common_idx >= '2005-01-01']

weekly_ret = weekly_ret.reindex(common_idx)
weekly_rv = weekly_rv.reindex(common_idx)
weekly_vix = weekly_vix.reindex(common_idx)
weekly_vrp = weekly_vrp.reindex(common_idx)
weekly_rs_neg = weekly_rs_neg.reindex(common_idx)
weekly_rs_pos = weekly_rs_pos.reindex(common_idx)
weekly_rv_1d = weekly_rv_1d.reindex(common_idx)
weekly_rv_5d = weekly_rv_5d.reindex(common_idx)
weekly_rv_22d = weekly_rv_22d.reindex(common_idx)

print(f"  Weekly obs: {len(common_idx)} ({common_idx[0].date()} to {common_idx[-1].date()})")
print(f"  Weekly ret: mean={weekly_ret.mean()*100:.3f}%, std={weekly_ret.std()*100:.3f}%")
print(f"  Weekly RV: mean={weekly_rv.mean()*1e4:.2f}bps², std={weekly_rv.std()*1e4:.2f}bps²")

# ============================================================
# 3. DATA DIAGNOSTICS (REQUIRED)
# ============================================================
print("\n[3] Data diagnostics on weekly returns...")

# Descriptive statistics
ret_vals = weekly_ret.values
print(f"  Mean:     {np.mean(ret_vals)*100:.4f}%")
print(f"  Std:      {np.std(ret_vals)*100:.4f}%")
print(f"  Skewness: {stats.skew(ret_vals):.4f}")
print(f"  Kurtosis: {stats.kurtosis(ret_vals):.4f} (excess)")
print(f"  Min:      {np.min(ret_vals)*100:.2f}%")
print(f"  Max:      {np.max(ret_vals)*100:.2f}%")

# ADF test on weekly returns
adf_stat, adf_p, _, _, _, _ = adfuller(ret_vals)
print(f"\n  ADF test: stat={adf_stat:.4f}, p={adf_p:.6f} {'(stationary)' if adf_p < 0.05 else '(NON-STATIONARY)'}")

# ARCH LM test
arch_lm = het_arch(ret_vals, nlags=5)
print(f"  ARCH LM(5): stat={arch_lm[0]:.4f}, p={arch_lm[1]:.6f} {'(ARCH effects)' if arch_lm[1] < 0.05 else '(no ARCH)'}")

# Ljung-Box on returns
lb_ret = acorr_ljungbox(ret_vals, lags=[5, 10], return_df=True)
print(f"  Ljung-Box(5) returns: stat={lb_ret.iloc[0, 0]:.4f}, p={lb_ret.iloc[0, 1]:.4f}")
print(f"  Ljung-Box(10) returns: stat={lb_ret.iloc[1, 0]:.4f}, p={lb_ret.iloc[1, 1]:.4f}")

# Ljung-Box on squared returns (vol clustering)
lb_sq = acorr_ljungbox(ret_vals**2, lags=[5, 10], return_df=True)
print(f"  Ljung-Box(5) r²: stat={lb_sq.iloc[0, 0]:.4f}, p={lb_sq.iloc[0, 1]:.6f}")
print(f"  Ljung-Box(10) r²: stat={lb_sq.iloc[1, 0]:.4f}, p={lb_sq.iloc[1, 1]:.6f}")

# Diagnostics on weekly RV
rv_vals = weekly_rv.dropna().values
print(f"\n  Weekly RV diagnostics:")
print(f"    Mean: {np.mean(rv_vals)*1e4:.4f} bps²")
print(f"    Std:  {np.std(rv_vals)*1e4:.4f} bps²")
print(f"    Skew: {stats.skew(rv_vals):.4f}")
print(f"    Kurt: {stats.kurtosis(rv_vals):.4f}")

# ============================================================
# 4. DEFINE OOS PERIOD
# ============================================================
oos_start = '2023-01-01'
oos_end = '2025-12-31'
window = 400  # weeks

oos_mask = (common_idx >= oos_start) & (common_idx <= oos_end)
oos_weeks = common_idx[oos_mask]
n_oos = len(oos_weeks)
print(f"\n[4] OOS period: {oos_start} to {oos_end}")
print(f"    OOS weeks: {n_oos}")
print(f"    Rolling window: {window} weeks (~{window/52:.1f} years)")

if n_oos < 104:
    print(f"  WARNING: OOS weeks ({n_oos}) < 104 minimum!")

# ============================================================
# 5. MODEL DEFINITIONS AND ROLLING OOS EVALUATION
# ============================================================
print("\n[5] Running rolling OOS forecasts for 8 models...")

# Proxy for realized variance: weekly squared return (r²_t+1)
# This is the standard proxy — see Patton (2011)
# Target: weekly_rv (sum of daily squared returns) is a better proxy
# We use weekly_rv_{t+1} as the target

# Store forecasts
forecasts = {
    'GARCH11': [],
    'GJR_GARCH': [],
    'EWMA_094': [],
    'Rolling_4w': [],
    'VIX_scaled': [],
    'VRP_model': [],
    'Semivar': [],
    'HAR_like': [],
}

# Store model diagnostics
gjr_gammas = []
gjr_gamma_pvals = []
garch_convergences = []
gjr_convergences = []

# Store VRP and semivar regression stats
vrp_tstats = []
semivar_tstats = []

# Convert to arrays for speed
ret_series = weekly_ret.copy()
rv_series = weekly_rv.copy()
vix_series = weekly_vix.copy()
vrp_series = weekly_vrp.copy()
rsneg_series = weekly_rs_neg.copy()
rv1d_series = weekly_rv_1d.copy()
rv5d_series = weekly_rv_5d.copy()
rv22d_series = weekly_rv_22d.copy()

# Get positions
all_dates = common_idx
oos_positions = [i for i, d in enumerate(all_dates) if d in oos_weeks]

print(f"    First OOS position: {oos_positions[0]} (date: {all_dates[oos_positions[0]].date()})")
print(f"    Last OOS position: {oos_positions[-1]} (date: {all_dates[oos_positions[-1]].date()})")

n_done = 0
for pos in oos_positions:
    # Training data: [pos-window : pos]
    start_pos = pos - window
    if start_pos < 0:
        start_pos = 0

    train_ret = ret_series.iloc[start_pos:pos].values * 100  # in percent
    train_rv = rv_series.iloc[start_pos:pos].values
    train_vix = vix_series.iloc[start_pos:pos].values
    train_vrp = vrp_series.iloc[start_pos:pos].values
    train_rsneg = rsneg_series.iloc[start_pos:pos].values
    train_rv1d = rv1d_series.iloc[start_pos:pos].values
    train_rv5d = rv5d_series.iloc[start_pos:pos].values
    train_rv22d = rv22d_series.iloc[start_pos:pos].values

    # ---- Model 1: GARCH(1,1) on weekly returns ----
    try:
        am = arch_model(train_ret, vol='Garch', p=1, q=1, mean='Constant',
                       dist='normal', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        garch_var = fc.variance.values[-1, 0] / 1e4  # back to decimal
        forecasts['GARCH11'].append(garch_var)
        garch_convergences.append(res.convergence_flag == 0)
    except Exception:
        forecasts['GARCH11'].append(np.nan)
        garch_convergences.append(False)

    # ---- Model 2: GJR-GARCH(1,1) on weekly returns ----
    try:
        am = arch_model(train_ret, vol='Garch', p=1, o=1, q=1, mean='Constant',
                       dist='normal', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        gjr_var = fc.variance.values[-1, 0] / 1e4  # back to decimal
        forecasts['GJR_GARCH'].append(gjr_var)

        # Extract gamma
        param_names = list(res.params.index)
        gamma_idx = [i for i, n in enumerate(param_names) if 'gamma' in n.lower()]
        if gamma_idx:
            gamma_val = res.params.iloc[gamma_idx[0]]
            gamma_pval = res.pvalues.iloc[gamma_idx[0]]
            gjr_gammas.append(gamma_val)
            gjr_gamma_pvals.append(gamma_pval)

        gjr_convergences.append(res.convergence_flag == 0)
    except Exception:
        forecasts['GJR_GARCH'].append(np.nan)
        gjr_convergences.append(False)

    # ---- Model 3: EWMA(lambda=0.94) ----
    lam = 0.94
    train_ret_dec = train_ret / 100  # back to decimal
    ewma_var = np.var(train_ret_dec[:20])  # initialize with first 20 obs
    for r in train_ret_dec:
        ewma_var = lam * ewma_var + (1 - lam) * r**2
    forecasts['EWMA_094'].append(ewma_var)

    # ---- Model 4: Rolling 4-week std ----
    if len(train_ret_dec) >= 4:
        roll_std = np.std(train_ret_dec[-4:])
        forecasts['Rolling_4w'].append(roll_std**2)
    else:
        forecasts['Rolling_4w'].append(np.nan)

    # ---- Model 5: VIX-based (scaled to weekly) ----
    # VIX = annualized vol in %. Weekly var = (VIX/100)^2 / 52
    last_vix = train_vix[-1]
    if not np.isnan(last_vix):
        vix_weekly_var = (last_vix / 100)**2 / 52
        forecasts['VIX_scaled'].append(vix_weekly_var)
    else:
        forecasts['VIX_scaled'].append(np.nan)

    # ---- Model 6: VRP model (OLS: next week RV ~ VRP + RV_lag) ----
    try:
        y_train = train_rv[1:]  # next week RV
        x_vrp = train_vrp[:-1]
        x_rv_lag = train_rv[:-1]
        valid = ~(np.isnan(y_train) | np.isnan(x_vrp) | np.isnan(x_rv_lag))
        if valid.sum() > 30:
            X = sm.add_constant(np.column_stack([x_vrp[valid], x_rv_lag[valid]]))
            y = y_train[valid]
            ols = sm.OLS(y, X).fit()
            # Forecast: use last obs
            X_fc = np.array([1, train_vrp[-1], train_rv[-1]])
            fc_vrp = ols.predict(X_fc.reshape(1, -1))[0]
            forecasts['VRP_model'].append(max(fc_vrp, 1e-8))
            # t-stat for VRP coefficient
            vrp_tstats.append(ols.tvalues[1])
        else:
            forecasts['VRP_model'].append(np.nan)
    except Exception:
        forecasts['VRP_model'].append(np.nan)

    # ---- Model 7: Semivariance model (OLS: next week RV ~ RS_neg + RS_pos) ----
    try:
        y_train = train_rv[1:]
        x_rsneg = train_rsneg[:-1]
        x_rspos = rsneg_series.iloc[start_pos:pos].values[:-1]  # re-get for pos
        # Actually let's use the neg semivariance from the proper series
        x_rsneg = train_rsneg[:-1]
        x_rv_lag = train_rv[:-1]
        valid = ~(np.isnan(y_train) | np.isnan(x_rsneg) | np.isnan(x_rv_lag))
        if valid.sum() > 30:
            X = sm.add_constant(np.column_stack([x_rsneg[valid], x_rv_lag[valid]]))
            y = y_train[valid]
            ols = sm.OLS(y, X).fit()
            X_fc = np.array([1, train_rsneg[-1], train_rv[-1]])
            fc_semi = ols.predict(X_fc.reshape(1, -1))[0]
            forecasts['Semivar'].append(max(fc_semi, 1e-8))
            semivar_tstats.append(ols.tvalues[1])
        else:
            forecasts['Semivar'].append(np.nan)
    except Exception:
        forecasts['Semivar'].append(np.nan)

    # ---- Model 8: HAR-like (OLS: next week RV ~ RV_1d + RV_5d + RV_22d) ----
    try:
        y_train = train_rv[1:]
        x1 = train_rv1d[:-1]
        x5 = train_rv5d[:-1]
        x22 = train_rv22d[:-1]
        valid = ~(np.isnan(y_train) | np.isnan(x1) | np.isnan(x5) | np.isnan(x22))
        if valid.sum() > 30:
            X = sm.add_constant(np.column_stack([x1[valid], x5[valid], x22[valid]]))
            y = y_train[valid]
            ols = sm.OLS(y, X).fit()
            X_fc = np.array([1, train_rv1d[-1], train_rv5d[-1], train_rv22d[-1]])
            fc_har = ols.predict(X_fc.reshape(1, -1))[0]
            forecasts['HAR_like'].append(max(fc_har, 1e-8))
        else:
            forecasts['HAR_like'].append(np.nan)
    except Exception:
        forecasts['HAR_like'].append(np.nan)

    n_done += 1
    if n_done % 25 == 0:
        print(f"    Progress: {n_done}/{n_oos} weeks done")

print(f"    Completed: {n_done}/{n_oos} weeks")

# ============================================================
# 6. EVALUATE FORECASTS
# ============================================================
print("\n[6] Evaluating forecasts...")

# Realized target: weekly_rv at t+1
# For each OOS position i, the target is the NEXT week's realized variance
targets = []
for i, pos in enumerate(oos_positions):
    if pos + 1 < len(rv_series):
        targets.append(rv_series.iloc[pos + 1])
    else:
        targets.append(np.nan)
targets = np.array(targets)

# Loss functions
def qlike(sigma2, rv):
    """QLIKE loss: log(sigma2) + rv/sigma2"""
    valid = ~(np.isnan(sigma2) | np.isnan(rv) | (sigma2 <= 0))
    if valid.sum() == 0:
        return np.nan
    return np.mean(np.log(sigma2[valid]) + rv[valid] / sigma2[valid])

def mse_loss(sigma2, rv):
    """MSE loss: (sigma2 - rv)^2"""
    valid = ~(np.isnan(sigma2) | np.isnan(rv))
    return np.mean((sigma2[valid] - rv[valid])**2)

def mae_loss(sigma2, rv):
    """MAE loss: |sigma2 - rv|"""
    valid = ~(np.isnan(sigma2) | np.isnan(rv))
    return np.mean(np.abs(sigma2[valid] - rv[valid]))

# Diebold-Mariano test
def dm_test(loss1, loss2, h=1):
    """DM test: H0: E[d_t]=0, H1: E[d_t]<0 (model 1 better)"""
    d = loss1 - loss2
    valid = ~np.isnan(d)
    d = d[valid]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=0)
    hac_var = gamma0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * (1 - k/h) * gamma_k
    se = np.sqrt(hac_var / n)
    if se < 1e-12:
        return np.nan, np.nan
    t_stat = d_mean / se
    p_val = stats.t.cdf(t_stat, df=n-1)  # one-sided: model 1 better
    return t_stat, p_val

results_table = {}
print(f"\n  {'Model':<15} {'QLIKE':>10} {'MSE(×1e8)':>12} {'MAE(×1e4)':>12} {'N_valid':>8}")
print("  " + "-" * 60)

for model_name, fc_list in forecasts.items():
    fc_arr = np.array(fc_list)
    valid = ~(np.isnan(fc_arr) | np.isnan(targets) | (fc_arr <= 0))
    n_valid = valid.sum()

    if n_valid < 50:
        print(f"  {model_name:<15} {'INSUFFICIENT':>10}")
        continue

    q = qlike(fc_arr[valid], targets[valid])
    m = mse_loss(fc_arr[valid], targets[valid])
    a = mae_loss(fc_arr[valid], targets[valid])

    results_table[model_name] = {
        'QLIKE': float(q),
        'MSE': float(m),
        'MAE': float(a),
        'N_valid': int(n_valid),
        'forecasts': fc_arr,
    }

    print(f"  {model_name:<15} {q:>10.4f} {m*1e8:>12.4f} {a*1e4:>12.4f} {n_valid:>8}")

# ============================================================
# 7. DM TESTS (PAIRWISE vs GJR baseline)
# ============================================================
print("\n[7] Diebold-Mariano tests (vs GJR-GARCH baseline)...")

baseline = 'GJR_GARCH'
if baseline not in results_table:
    print("  ERROR: GJR baseline missing!")
else:
    base_fc = results_table[baseline]['forecasts']
    base_qlike_losses = np.log(base_fc) + targets / base_fc

    print(f"\n  {'Model':<15} {'DM t-stat':>10} {'p-value':>10} {'Sig?':>6}")
    print("  " + "-" * 45)

    dm_results = {}
    for model_name, info in results_table.items():
        if model_name == baseline:
            continue
        fc = info['forecasts']
        model_qlike_losses = np.log(fc) + targets / fc

        # Both valid
        valid = ~(np.isnan(base_qlike_losses) | np.isnan(model_qlike_losses))
        t_stat, p_val = dm_test(model_qlike_losses[valid], base_qlike_losses[valid])

        sig = ''
        if not np.isnan(p_val):
            if p_val < 0.01:
                sig = '***'
            elif p_val < 0.05:
                sig = '**'
            elif p_val < 0.10:
                sig = '*'

        dm_results[model_name] = {'t_stat': float(t_stat) if not np.isnan(t_stat) else None,
                                   'p_value': float(p_val) if not np.isnan(p_val) else None}
        print(f"  {model_name:<15} {t_stat:>10.4f} {p_val:>10.4f} {sig:>6}")

# ============================================================
# 8. GJR GAMMA ANALYSIS AT WEEKLY FREQUENCY
# ============================================================
print("\n[8] GJR gamma analysis at weekly frequency...")

if gjr_gammas:
    gammas = np.array(gjr_gammas)
    gamma_pvals = np.array(gjr_gamma_pvals)

    print(f"  Mean gamma:    {np.mean(gammas):.6f}")
    print(f"  Median gamma:  {np.median(gammas):.6f}")
    print(f"  Std gamma:     {np.std(gammas):.6f}")
    print(f"  Min gamma:     {np.min(gammas):.6f}")
    print(f"  Max gamma:     {np.max(gammas):.6f}")
    print(f"  % positive:    {(gammas > 0).mean()*100:.1f}%")
    print(f"  % significant (p<0.05): {(gamma_pvals < 0.05).mean()*100:.1f}%")
    print(f"  % significant (p<0.01): {(gamma_pvals < 0.01).mean()*100:.1f}%")

    # Compare with daily: at daily, gamma ~ 0.10-0.15 for SPY
    print(f"\n  [Daily reference: gamma ~ 0.10-0.15 for SPY at daily frequency]")
    print(f"  Weekly gamma is {'LARGER' if np.mean(gammas) > 0.15 else 'COMPARABLE' if np.mean(gammas) > 0.05 else 'SMALLER'} than daily")

# ============================================================
# 9. VRP AND SEMIVARIANCE T-STATS AT WEEKLY
# ============================================================
print("\n[9] Exogenous variable t-stats at weekly frequency...")

if vrp_tstats:
    vt = np.array(vrp_tstats)
    print(f"  VRP t-stat: mean={np.mean(vt):.3f}, median={np.median(vt):.3f}, "
          f"std={np.std(vt):.3f}, % sig (|t|>2)={((np.abs(vt)>2).mean()*100):.1f}%")

if semivar_tstats:
    st = np.array(semivar_tstats)
    print(f"  Semivar t-stat: mean={np.mean(st):.3f}, median={np.median(st):.3f}, "
          f"std={np.std(st):.3f}, % sig (|t|>2)={((np.abs(st)>2).mean()*100):.1f}%")

# ============================================================
# 10. CONVERGENCE AND PERSISTENCE CHECK
# ============================================================
print("\n[10] Convergence diagnostics...")
print(f"  GARCH(1,1) convergence rate: {np.mean(garch_convergences)*100:.1f}%")
print(f"  GJR-GARCH convergence rate:  {np.mean(gjr_convergences)*100:.1f}%")

# Fit full-sample GJR for persistence check
print("\n  Full-sample GJR-GARCH on weekly returns:")
try:
    am_full = arch_model(ret_series.values * 100, vol='Garch', p=1, o=1, q=1,
                        mean='Constant', dist='normal', rescale=False)
    res_full = am_full.fit(disp='off', show_warning=False)
    print(f"    Parameters:")
    for p_name, p_val in res_full.params.items():
        pval = res_full.pvalues[p_name]
        sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.10 else ''
        print(f"      {p_name}: {p_val:.6f} (p={pval:.4f}) {sig}")

    # Persistence
    param_names = list(res_full.params.index)
    alpha_idx = [i for i, n in enumerate(param_names) if n.startswith('alpha')]
    beta_idx = [i for i, n in enumerate(param_names) if n.startswith('beta')]
    gamma_idx = [i for i, n in enumerate(param_names) if 'gamma' in n.lower()]
    persistence = 0
    if alpha_idx:
        persistence += res_full.params.iloc[alpha_idx[0]]
    if beta_idx:
        persistence += res_full.params.iloc[beta_idx[0]]
    if gamma_idx:
        persistence += 0.5 * res_full.params.iloc[gamma_idx[0]]
    print(f"    Persistence (α + β + 0.5γ): {persistence:.6f}")
    if persistence >= 1.0:
        print("    WARNING: persistence >= 1, IGARCH-like behavior")

    # Standardized residuals check
    std_resids = res_full.std_resid
    arch_test_resid = het_arch(std_resids.dropna(), nlags=5)
    lb_resid = acorr_ljungbox(std_resids.dropna()**2, lags=[5, 10], return_df=True)
    print(f"    Residual ARCH LM(5): stat={arch_test_resid[0]:.4f}, p={arch_test_resid[1]:.4f}")
    print(f"    Residual Ljung-Box(5) r²: stat={lb_resid.iloc[0, 0]:.4f}, p={lb_resid.iloc[0, 1]:.4f}")

except Exception as e:
    print(f"    ERROR: {e}")

# ============================================================
# 11. CROSS-FREQUENCY COMPARISON: DAILY vs WEEKLY QLIKE
# ============================================================
print("\n[11] Cross-frequency comparison...")

# Run daily GJR on same OOS for comparison
print("  Running daily GJR-GARCH for comparison (2023-2025 OOS)...")
daily_ret_pct = daily_ret * 100
daily_rv_series = daily_ret ** 2  # daily squared return proxy
daily_dates = daily_ret.index
daily_oos_mask = (daily_dates >= oos_start) & (daily_dates <= oos_end)
daily_oos_dates = daily_dates[daily_oos_mask]
daily_window = 2000

daily_gjr_forecasts = []
daily_targets = []
daily_gjr_gammas = []

n_daily_done = 0
# Sub-sample: every 5th day for speed
daily_oos_subset = daily_oos_dates[::5]
for d in daily_oos_subset:
    pos = daily_dates.get_loc(d)
    if isinstance(pos, slice):
        pos = pos.start
    start_pos = max(0, pos - daily_window)
    train = daily_ret_pct.iloc[start_pos:pos].values

    try:
        am = arch_model(train, vol='Garch', p=1, o=1, q=1, mean='Constant',
                       dist='normal', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        gjr_var = fc.variance.values[-1, 0] / 1e4

        if pos + 1 < len(daily_ret):
            target = daily_ret.iloc[pos + 1] ** 2
            daily_gjr_forecasts.append(gjr_var)
            daily_targets.append(target)

            param_names = list(res.params.index)
            gi = [i for i, n in enumerate(param_names) if 'gamma' in n.lower()]
            if gi:
                daily_gjr_gammas.append(res.params.iloc[gi[0]])
    except Exception:
        pass

    n_daily_done += 1
    if n_daily_done % 30 == 0:
        print(f"    Daily progress: {n_daily_done}/{len(daily_oos_subset)}")

daily_gjr_fc = np.array(daily_gjr_forecasts)
daily_tgt = np.array(daily_targets)
valid_d = ~(np.isnan(daily_gjr_fc) | np.isnan(daily_tgt) | (daily_gjr_fc <= 0))

if valid_d.sum() > 50:
    daily_qlike = qlike(daily_gjr_fc[valid_d], daily_tgt[valid_d])
    print(f"\n  Daily GJR QLIKE:  {daily_qlike:.4f} (N={valid_d.sum()})")

    # Weekly GJR QLIKE
    wk_gjr_fc = results_table.get('GJR_GARCH', {})
    if wk_gjr_fc:
        print(f"  Weekly GJR QLIKE: {wk_gjr_fc['QLIKE']:.4f} (N={wk_gjr_fc['N_valid']})")
        print(f"  Difference: {wk_gjr_fc['QLIKE'] - daily_qlike:.4f}")

    if daily_gjr_gammas:
        dg = np.array(daily_gjr_gammas)
        print(f"\n  Daily gamma:  mean={np.mean(dg):.6f}, median={np.median(dg):.6f}")
        if gjr_gammas:
            wg = np.array(gjr_gammas)
            print(f"  Weekly gamma: mean={np.mean(wg):.6f}, median={np.median(wg):.6f}")
            print(f"  Ratio (weekly/daily): {np.mean(wg)/np.mean(dg):.2f}x")

# ============================================================
# 12. MINCER-ZARNOWITZ REGRESSION
# ============================================================
print("\n[12] Mincer-Zarnowitz calibration regressions...")

print(f"  {'Model':<15} {'a':>8} {'b':>8} {'R²':>8} {'b=1 t':>8}")
print("  " + "-" * 48)

mz_results = {}
for model_name, info in results_table.items():
    fc = info['forecasts']
    valid = ~(np.isnan(fc) | np.isnan(targets) | (fc <= 0))
    if valid.sum() < 30:
        continue

    X = sm.add_constant(fc[valid])
    y = targets[valid]
    ols = sm.OLS(y, X).fit()

    a = ols.params[0]
    b = ols.params[1]
    r2 = ols.rsquared
    # t-test for b=1
    t_b1 = (b - 1) / ols.bse[1]

    mz_results[model_name] = {
        'intercept': float(a),
        'slope': float(b),
        'R2': float(r2),
        't_b1': float(t_b1),
    }
    print(f"  {model_name:<15} {a:>8.6f} {b:>8.4f} {r2:>8.4f} {t_b1:>8.3f}")

# ============================================================
# 13. COMPILE RESULTS
# ============================================================
print("\n[13] Compiling results...")

# Rank by QLIKE
ranked = sorted(results_table.items(), key=lambda x: x[1]['QLIKE'])
print(f"\n  RANKING by QLIKE (lower is better):")
for i, (name, info) in enumerate(ranked):
    print(f"    {i+1}. {name:<15} QLIKE={info['QLIKE']:.4f}")

best_model = ranked[0][0]
print(f"\n  BEST model at weekly frequency: {best_model}")

# Summary statistics
results_summary = {
    'experiment_id': 'K457',
    'title': 'Weekly Frequency Volatility Prediction',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"2005-01-01 to {common_idx[-1].date()}",
    'frequency': 'weekly (Friday-to-Friday)',
    'oos_period': f"{oos_start} to {oos_end}",
    'oos_weeks': n_oos,
    'rolling_window': window,
    'n_weekly_obs_total': len(common_idx),
    'weekly_return_stats': {
        'mean_pct': float(np.mean(ret_vals) * 100),
        'std_pct': float(np.std(ret_vals) * 100),
        'skewness': float(stats.skew(ret_vals)),
        'kurtosis': float(stats.kurtosis(ret_vals)),
    },
    'diagnostics': {
        'adf_stat': float(adf_stat),
        'adf_p': float(adf_p),
        'arch_lm_stat': float(arch_lm[0]),
        'arch_lm_p': float(arch_lm[1]),
        'has_arch_effects': bool(arch_lm[1] < 0.05),
    },
    'model_results': {},
    'ranking_by_qlike': [{'rank': i+1, 'model': name, 'QLIKE': info['QLIKE']}
                          for i, (name, info) in enumerate(ranked)],
    'best_model': best_model,
    'dm_tests_vs_gjr': dm_results if baseline in results_table else {},
    'gjr_gamma_weekly': {
        'mean': float(np.mean(gjr_gammas)) if gjr_gammas else None,
        'median': float(np.median(gjr_gammas)) if gjr_gammas else None,
        'std': float(np.std(gjr_gammas)) if gjr_gammas else None,
        'pct_positive': float((np.array(gjr_gammas) > 0).mean() * 100) if gjr_gammas else None,
        'pct_significant_005': float((np.array(gjr_gamma_pvals) < 0.05).mean() * 100) if gjr_gamma_pvals else None,
        'pct_significant_001': float((np.array(gjr_gamma_pvals) < 0.01).mean() * 100) if gjr_gamma_pvals else None,
    },
    'convergence': {
        'garch11': float(np.mean(garch_convergences) * 100),
        'gjr_garch': float(np.mean(gjr_convergences) * 100),
    },
    'vrp_t_stats': {
        'mean': float(np.mean(vrp_tstats)) if vrp_tstats else None,
        'median': float(np.median(vrp_tstats)) if vrp_tstats else None,
        'pct_significant': float((np.abs(np.array(vrp_tstats)) > 2).mean() * 100) if vrp_tstats else None,
    },
    'semivar_t_stats': {
        'mean': float(np.mean(semivar_tstats)) if semivar_tstats else None,
        'median': float(np.median(semivar_tstats)) if semivar_tstats else None,
        'pct_significant': float((np.abs(np.array(semivar_tstats)) > 2).mean() * 100) if semivar_tstats else None,
    },
    'mincer_zarnowitz': mz_results,
}

# Add per-model results (without raw forecasts)
for model_name, info in results_table.items():
    results_summary['model_results'][model_name] = {
        'QLIKE': info['QLIKE'],
        'MSE': info['MSE'],
        'MAE': info['MAE'],
        'N_valid': info['N_valid'],
    }

# Cross-frequency comparison
if valid_d.sum() > 50 and 'GJR_GARCH' in results_table:
    results_summary['cross_frequency'] = {
        'daily_gjr_qlike': float(daily_qlike),
        'weekly_gjr_qlike': float(results_table['GJR_GARCH']['QLIKE']),
        'daily_gamma_mean': float(np.mean(daily_gjr_gammas)) if daily_gjr_gammas else None,
        'weekly_gamma_mean': float(np.mean(gjr_gammas)) if gjr_gammas else None,
        'gamma_ratio_weekly_over_daily': float(np.mean(gjr_gammas) / np.mean(daily_gjr_gammas)) if gjr_gammas and daily_gjr_gammas else None,
    }

# Save
output_path = 'experiments/k457_weekly_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(results_summary, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

# ============================================================
# 14. KEY FINDINGS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

print(f"\n1. QLIKE Ceiling at Weekly:")
print(f"   Best model: {best_model} (QLIKE={results_table[best_model]['QLIKE']:.4f})")
if 'GJR_GARCH' in results_table and 'GARCH11' in results_table:
    diff = results_table['GARCH11']['QLIKE'] - results_table['GJR_GARCH']['QLIKE']
    print(f"   GJR vs GARCH difference: {diff:.4f} ({'GJR better' if diff > 0 else 'GARCH better'})")

print(f"\n2. Weekly GJR Gamma:")
if gjr_gammas:
    print(f"   Mean={np.mean(gjr_gammas):.6f}, {(np.array(gjr_gamma_pvals)<0.05).mean()*100:.0f}% significant")
    print(f"   Leverage effect {'persists' if np.mean(gjr_gammas) > 0 and (np.array(gjr_gamma_pvals)<0.05).mean() > 0.5 else 'weakens'} at weekly frequency")

print(f"\n3. Exogenous Variables:")
if vrp_tstats:
    print(f"   VRP: mean t={np.mean(vrp_tstats):.3f}, {(np.abs(np.array(vrp_tstats))>2).mean()*100:.0f}% significant")
if semivar_tstats:
    print(f"   Semivar: mean t={np.mean(semivar_tstats):.3f}, {(np.abs(np.array(semivar_tstats))>2).mean()*100:.0f}% significant")

print(f"\n4. Cross-Frequency:")
if 'cross_frequency' in results_summary:
    cf = results_summary['cross_frequency']
    print(f"   Daily QLIKE:  {cf['daily_gjr_qlike']:.4f}")
    print(f"   Weekly QLIKE: {cf['weekly_gjr_qlike']:.4f}")
    if cf.get('gamma_ratio_weekly_over_daily'):
        print(f"   Gamma ratio (weekly/daily): {cf['gamma_ratio_weekly_over_daily']:.2f}x")

print(f"\n5. Model Convergence:")
print(f"   GARCH: {np.mean(garch_convergences)*100:.0f}%, GJR: {np.mean(gjr_convergences)*100:.0f}%")

print("\n" + "=" * 70)
print("K457 COMPLETED")
print("=" * 70)
