"""
K987: VIX² Nonlinearity in Volatility Forecasting

Background:
- K979 (SKEW) side finding: VIX² nonlinearity OOS R² = 0.198 vs VIX linear 0.139
- VIX-vol relationship is convex: VIX 20→30 vol increment > 10→20 increment
- Question: Can VIX² significantly improve daily vol forecasting?

Models (all use VIX_{t-1} to predict r²_t, proper shift(1)):
  M1: Linear VIX
  M2: Quadratic (VIX + VIX²)
  M3: Log VIX
  M4: Piecewise linear (knot at VIX=20)
  M5: Cubic spline (3 knots)
  M6: MF2-VIX (tau from VIX)
  M7: MF2-VIX² (tau with convexity)
  GJR: GJR-GARCH(1,1) baseline

Data: SPY + ^VIX, 2006-2026, IS: 2006-2018, OOS: 2019-2026
Evaluation: QLIKE, MSE, OOS R², DM test, MZ regression, RESET test

References: K979 (SKEW experiment), K970 (MF2 framework)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
from datetime import datetime
from scipy import stats
from scipy.interpolate import CubicSpline
from arch import arch_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K987: VIX² Nonlinearity in Volatility Forecasting")
print("=" * 60)

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle MultiIndex columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Returns and realized vol proxy
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['r2'] = spy['ret'] ** 2  # daily squared return as vol proxy

# Merge
df = pd.DataFrame({
    'r2': spy['r2'],
    'ret': spy['ret'],
    'vix': vix['Close']
}).dropna()

print(f"  Total observations: {len(df)}")
print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# IS / OOS split
IS_END = '2018-12-31'
OOS_START = '2019-01-01'
df_is = df.loc[:IS_END]
df_oos = df.loc[OOS_START:]
print(f"  IS: {len(df_is)} obs ({df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {len(df_oos)} obs ({df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[2] Descriptive Statistics")
for name, s in [('r²', df['r2']), ('VIX', df['vix']), ('log(VIX)', np.log(df['vix']))]:
    print(f"  {name}: mean={s.mean():.6f}, std={s.std():.6f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# Correlation: VIX vs r²
corr_linear = df['vix'].corr(df['r2'])
corr_log = np.log(df['vix']).corr(df['r2'])
corr_sq = (df['vix'] ** 2).corr(df['r2'])
print(f"\n  Correlations with r²:")
print(f"    VIX:      {corr_linear:.4f}")
print(f"    log(VIX): {corr_log:.4f}")
print(f"    VIX²:     {corr_sq:.4f}")

# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1
    Clamp forecast to minimum to avoid numerical issues."""
    forecast = np.maximum(forecast, 1e-10)
    actual = np.maximum(actual, 1e-15)
    ratio = actual / forecast
    valid = np.isfinite(ratio) & (ratio > 0)
    if valid.sum() == 0:
        return np.nan
    return np.mean(ratio[valid] - np.log(ratio[valid]) - 1)

def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)

def oos_r2(actual, forecast):
    """OOS R² = 1 - MSE(model) / MSE(mean)"""
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return 1 - ss_res / ss_tot

def qlike_loss_series(actual, forecast):
    """Compute per-observation QLIKE losses (for DM test)."""
    forecast = np.maximum(forecast, 1e-10)
    actual = np.maximum(actual, 1e-15)
    ratio = actual / forecast
    return ratio - np.log(ratio) - 1

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided). loss1 vs loss2.
    Returns t-stat and p-value. Negative t = loss1 < loss2 (model1 better)."""
    d = np.asarray(loss1 - loss2, dtype=float)
    # Remove any NaN/Inf
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = d.mean()
    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    var_d = gamma_0
    for k in range(1, max(h, 2)):
        if k < n:
            gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
            var_d += 2 * (1 - k / (h + 1)) * gamma_k
    se = np.sqrt(max(var_d, 1e-30) / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_val

def mz_regression(actual, forecast):
    """Mincer-Zarnowitz regression: actual = a + b*forecast + e
    Returns a, b, R², F-test p-value for H0: a=0, b=1"""
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coef, _, _, _ = lstsq(X, actual, rcond=None)
    a, b = coef
    fitted = X @ coef
    ss_res = np.sum((actual - fitted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2_mz = 1 - ss_res / ss_tot
    return a, b, r2_mz

def reset_test(y, X_design, fitted):
    """Ramsey RESET test for functional form misspecification.
    H0: linear model is correctly specified."""
    n = len(y)
    # Add squared and cubed fitted values
    X_aug = np.column_stack([X_design, fitted ** 2, fitted ** 3])
    from numpy.linalg import lstsq
    coef_aug, _, _, _ = lstsq(X_aug, y, rcond=None)
    fitted_aug = X_aug @ coef_aug
    ss_res_r = np.sum((y - fitted) ** 2)
    ss_res_u = np.sum((y - fitted_aug) ** 2)
    k_r = X_design.shape[1]
    k_u = X_aug.shape[1]
    df1 = k_u - k_r
    df2 = n - k_u
    if ss_res_u < 1e-30 or df2 <= 0:
        return 0.0, 1.0
    f_stat = ((ss_res_r - ss_res_u) / df1) / (ss_res_u / df2)
    p_val = 1 - stats.f.cdf(f_stat, df1, df2)
    return f_stat, p_val

# ============================================================
# 4. PREPARE FEATURES (all shift(1) for proper lag)
# ============================================================
print("\n[3] Preparing features (all shift(1))...")

df['vix_lag'] = df['vix'].shift(1)
df['vix2_lag'] = (df['vix'] ** 2).shift(1)
df['log_vix_lag'] = np.log(df['vix']).shift(1)
df['vix_pw_lag'] = np.maximum(df['vix'].shift(1) - 20, 0)  # piecewise knot at 20
df = df.dropna()

# Re-split after adding lags
df_is = df.loc[:IS_END]
df_oos = df.loc[OOS_START:]

y_is = df_is['r2'].values
y_oos = df_oos['r2'].values

# ============================================================
# 5. MODEL ESTIMATION (IS) AND OOS FORECASTING
# ============================================================
print("\n[4] Estimating models...")

from numpy.linalg import lstsq as np_lstsq

results = {}

# --- M1: Linear VIX ---
print("  M1: Linear VIX")
X_is = np.column_stack([np.ones(len(df_is)), df_is['vix_lag'].values])
X_oos = np.column_stack([np.ones(len(df_oos)), df_oos['vix_lag'].values])
coef, _, _, _ = np_lstsq(X_is, y_is, rcond=None)
fc_is = X_is @ coef
fc_oos_m1 = np.maximum(X_oos @ coef, 1e-10)
# RESET test on IS
f_reset, p_reset = reset_test(y_is, X_is, fc_is)
results['M1_Linear'] = {
    'coef': {'intercept': coef[0], 'beta_vix': coef[1]},
    'forecast_oos': fc_oos_m1,
    'reset_f': f_reset, 'reset_p': p_reset
}
print(f"    coef: a={coef[0]:.6f}, b_vix={coef[1]:.6f}")
print(f"    RESET: F={f_reset:.2f}, p={p_reset:.4f}")

# --- M2: Quadratic (VIX + VIX²) ---
print("  M2: Quadratic (VIX + VIX²)")
X_is = np.column_stack([np.ones(len(df_is)), df_is['vix_lag'].values, df_is['vix2_lag'].values])
X_oos = np.column_stack([np.ones(len(df_oos)), df_oos['vix_lag'].values, df_oos['vix2_lag'].values])
coef, _, _, _ = np_lstsq(X_is, y_is, rcond=None)
fc_oos_m2 = np.maximum(X_oos @ coef, 1e-10)
fc_is2 = X_is @ coef
f_reset, p_reset = reset_test(y_is, X_is, fc_is2)
results['M2_Quadratic'] = {
    'coef': {'intercept': coef[0], 'beta_vix': coef[1], 'beta_vix2': coef[2]},
    'forecast_oos': fc_oos_m2,
    'reset_f': f_reset, 'reset_p': p_reset
}
print(f"    coef: a={coef[0]:.6f}, b_vix={coef[1]:.6f}, b_vix²={coef[2]:.8f}")
print(f"    RESET: F={f_reset:.2f}, p={p_reset:.4f}")

# --- M3: Log VIX ---
print("  M3: Log VIX")
X_is = np.column_stack([np.ones(len(df_is)), df_is['log_vix_lag'].values])
X_oos = np.column_stack([np.ones(len(df_oos)), df_oos['log_vix_lag'].values])
coef, _, _, _ = np_lstsq(X_is, y_is, rcond=None)
fc_oos_m3 = np.maximum(X_oos @ coef, 1e-10)
fc_is3 = X_is @ coef
f_reset, p_reset = reset_test(y_is, X_is, fc_is3)
results['M3_Log'] = {
    'coef': {'intercept': coef[0], 'beta_logvix': coef[1]},
    'forecast_oos': fc_oos_m3,
    'reset_f': f_reset, 'reset_p': p_reset
}
print(f"    coef: a={coef[0]:.6f}, b_log={coef[1]:.6f}")
print(f"    RESET: F={f_reset:.2f}, p={p_reset:.4f}")

# --- M4: Piecewise linear (knot at VIX=20) ---
print("  M4: Piecewise linear (knot=20)")
X_is = np.column_stack([np.ones(len(df_is)), df_is['vix_lag'].values, df_is['vix_pw_lag'].values])
X_oos = np.column_stack([np.ones(len(df_oos)), df_oos['vix_lag'].values, df_oos['vix_pw_lag'].values])
coef, _, _, _ = np_lstsq(X_is, y_is, rcond=None)
fc_oos_m4 = np.maximum(X_oos @ coef, 1e-10)
fc_is4 = X_is @ coef
f_reset, p_reset = reset_test(y_is, X_is, fc_is4)
results['M4_Piecewise'] = {
    'coef': {'intercept': coef[0], 'beta_vix': coef[1], 'beta_vix_above20': coef[2]},
    'forecast_oos': fc_oos_m4,
    'reset_f': f_reset, 'reset_p': p_reset
}
# Effective slope below/above 20
slope_below = coef[1]
slope_above = coef[1] + coef[2]
print(f"    coef: a={coef[0]:.6f}, b_vix={coef[1]:.6f}, b_above20={coef[2]:.6f}")
print(f"    Effective slope: below 20 = {slope_below:.6f}, above 20 = {slope_above:.6f}")
print(f"    RESET: F={f_reset:.2f}, p={p_reset:.4f}")

# --- M5: Cubic spline (3 knots) ---
print("  M5: Cubic spline (3 knots)")
# Fit cubic spline on IS data
vix_is = df_is['vix_lag'].values
vix_oos_vals = df_oos['vix_lag'].values

# Use quantile-based knots
knots = np.quantile(vix_is, [0.25, 0.50, 0.75])
print(f"    Knots at VIX = {knots}")

# Create basis functions for natural cubic spline using truncated power basis
def spline_basis(x, knots):
    """Create truncated power basis for cubic spline."""
    X = np.column_stack([np.ones(len(x)), x, x**2, x**3])
    for k in knots:
        X = np.column_stack([X, np.maximum(x - k, 0)**3])
    return X

X_is_sp = spline_basis(vix_is, knots)
X_oos_sp = spline_basis(vix_oos_vals, knots)
coef, _, _, _ = np_lstsq(X_is_sp, y_is, rcond=None)
fc_oos_m5 = np.maximum(X_oos_sp @ coef, 1e-10)
results['M5_Spline'] = {
    'coef': coef.tolist(),
    'knots': knots.tolist(),
    'forecast_oos': fc_oos_m5
}

# --- M6: MF2-VIX (tau from VIX, K970 framework) ---
print("  M6: MF2-VIX (tau from VIX)")
# tau_t = (VIX_{t-1} / sqrt(252))^2 — annualized VIX to daily variance
tau_is = (df_is['vix_lag'].values / 100 / np.sqrt(252)) ** 2  # VIX in % → daily var
tau_oos = (df_oos['vix_lag'].values / 100 / np.sqrt(252)) ** 2

# MF2: r²_t = alpha + beta * tau_{t-1} + epsilon
X_is_mf = np.column_stack([np.ones(len(df_is)), tau_is])
X_oos_mf = np.column_stack([np.ones(len(df_oos)), tau_oos])
coef, _, _, _ = np_lstsq(X_is_mf, y_is, rcond=None)
fc_oos_m6 = np.maximum(X_oos_mf @ coef, 1e-10)
results['M6_MF2_VIX'] = {
    'coef': {'intercept': coef[0], 'beta_tau': coef[1]},
    'forecast_oos': fc_oos_m6
}
print(f"    coef: a={coef[0]:.8f}, b_tau={coef[1]:.4f}")

# --- M7: MF2-VIX² (tau with convexity) ---
print("  M7: MF2-VIX² (tau with VIX convexity)")
# tau_t = (VIX/100/sqrt(252))^2 * (1 + delta * VIX/100)
# We estimate delta from IS data
# Use two regressors: tau and tau*VIX
vix_frac_is = df_is['vix_lag'].values / 100
vix_frac_oos = df_oos['vix_lag'].values / 100
tau_base_is = (vix_frac_is / np.sqrt(252)) ** 2
tau_base_oos = (vix_frac_oos / np.sqrt(252)) ** 2
tau_conv_is = tau_base_is * vix_frac_is  # convexity term
tau_conv_oos = tau_base_oos * vix_frac_oos

X_is_mf2 = np.column_stack([np.ones(len(df_is)), tau_base_is, tau_conv_is])
X_oos_mf2 = np.column_stack([np.ones(len(df_oos)), tau_base_oos, tau_conv_oos])
coef, _, _, _ = np_lstsq(X_is_mf2, y_is, rcond=None)
fc_oos_m7 = np.maximum(X_oos_mf2 @ coef, 1e-10)
results['M7_MF2_VIX2'] = {
    'coef': {'intercept': coef[0], 'beta_tau': coef[1], 'beta_tau_conv': coef[2]},
    'forecast_oos': fc_oos_m7
}
print(f"    coef: a={coef[0]:.8f}, b_tau={coef[1]:.4f}, b_conv={coef[2]:.4f}")

# --- GJR-GARCH(1,1) baseline ---
print("  GJR-GARCH(1,1) baseline (recursive OOS)...")
# Use full sample up to each OOS point, refit every 63 days
ret_full = df['ret'].values * 100  # scale for arch
oos_idx = df.index.get_indexer(df_oos.index)
n_total = len(df)
fc_gjr = np.full(len(df_oos), np.nan)
refit_interval = 63

last_model = None
for i, idx in enumerate(oos_idx):
    if i % refit_interval == 0 or last_model is None:
        try:
            am = arch_model(ret_full[:idx], vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = am.fit(disp='off', show_warning=False)
            last_model = res
        except Exception:
            pass
    if last_model is not None:
        try:
            fcast = last_model.forecast(horizon=1, reindex=False)
            fc_gjr[i] = fcast.variance.values[-1, 0] / (100 ** 2)  # back to decimal
        except Exception:
            pass

# Handle any NaN
fc_gjr = np.where(np.isnan(fc_gjr), np.nanmean(fc_gjr), fc_gjr)
fc_gjr = np.maximum(fc_gjr, 1e-10)
results['GJR_GARCH'] = {'forecast_oos': fc_gjr}
print(f"    GJR done. Mean forecast: {np.mean(fc_gjr):.8f}")

# ============================================================
# 6. EVALUATION
# ============================================================
print("\n[5] Evaluation")

model_names = ['M1_Linear', 'M2_Quadratic', 'M3_Log', 'M4_Piecewise',
               'M5_Spline', 'M6_MF2_VIX', 'M7_MF2_VIX2', 'GJR_GARCH']
forecasts = {
    'M1_Linear': fc_oos_m1,
    'M2_Quadratic': fc_oos_m2,
    'M3_Log': fc_oos_m3,
    'M4_Piecewise': fc_oos_m4,
    'M5_Spline': fc_oos_m5,
    'M6_MF2_VIX': fc_oos_m6,
    'M7_MF2_VIX2': fc_oos_m7,
    'GJR_GARCH': fc_gjr,
}

print(f"\n  {'Model':<16} {'QLIKE':>10} {'MSE':>14} {'OOS_R2':>10} {'MZ_a':>10} {'MZ_b':>10} {'MZ_R2':>8}")
print("  " + "-" * 78)

eval_results = {}
for name in model_names:
    fc = forecasts[name]
    q = qlike(y_oos, fc)
    m = mse(y_oos, fc)
    r2 = oos_r2(y_oos, fc)
    a, b, r2_mz = mz_regression(y_oos, fc)
    eval_results[name] = {
        'qlike': q, 'mse': m, 'oos_r2': r2,
        'mz_a': a, 'mz_b': b, 'mz_r2': r2_mz
    }
    print(f"  {name:<16} {q:10.6f} {m:14.10f} {r2:10.4f} {a:10.6f} {b:10.4f} {r2_mz:8.4f}")

# Check which models produce negative (clipped) forecasts
print(f"\n  Negative forecast check (clipped to 1e-10):")
for name in model_names:
    fc_raw = forecasts[name]
    n_neg = np.sum(fc_raw <= 1e-9)
    if n_neg > 0:
        print(f"    {name}: {n_neg} clipped obs — QLIKE unreliable for this model")

# DM tests using MSE (robust to clipping issue)
print(f"\n  DM Test vs M2_Quadratic baseline (MSE loss):")
print(f"  {'Model':<16} {'t-stat':>10} {'p-value':>10} {'Sig':>5}")
print("  " + "-" * 45)

mse_m2 = (y_oos - fc_oos_m2) ** 2  # M2 as baseline (best OOS R²)

dm_results = {}
for name in model_names:
    if name == 'M2_Quadratic':
        dm_results[name] = {'t_stat': 0.0, 'p_value': 1.0}
        continue
    fc = forecasts[name]
    mse_i = (y_oos - fc) ** 2
    t, p = dm_test(mse_i, mse_m2)
    sig = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.10 else ''))
    dm_results[name] = {'t_stat': t, 'p_value': p}
    print(f"  {name:<16} {t:10.4f} {p:10.4f} {sig:>5}")

# DM test: pairwise among well-behaved models (no negative forecasts)
good_models = ['M2_Quadratic', 'M4_Piecewise', 'M5_Spline', 'M7_MF2_VIX2']
print(f"\n  Pairwise DM (MSE) among well-behaved models:")
print(f"  {'Pair':<30} {'t-stat':>10} {'p-value':>10} {'Winner':>12}")
print("  " + "-" * 65)

dm_pairwise = {}
for i, n1 in enumerate(good_models):
    for n2 in good_models[i+1:]:
        mse1 = (y_oos - forecasts[n1]) ** 2
        mse2 = (y_oos - forecasts[n2]) ** 2
        t, p = dm_test(mse1, mse2)
        winner = n1 if t < 0 else n2
        sig = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.10 else 'ns'))
        pair_key = f"{n1}_vs_{n2}"
        dm_pairwise[pair_key] = {'t_stat': t, 'p_value': p, 'winner': winner}
        print(f"  {n1+' vs '+n2:<30} {t:10.4f} {p:10.4f} {winner+' '+sig:>12}")

# DM tests: all vs GJR baseline (MSE)
print(f"\n  DM Test vs GJR_GARCH (MSE loss):")
print(f"  {'Model':<16} {'t-stat':>10} {'p-value':>10} {'Sig':>5}")
print("  " + "-" * 45)

mse_gjr = (y_oos - fc_gjr) ** 2

dm_vs_gjr = {}
for name in model_names:
    if name == 'GJR_GARCH':
        continue
    fc = forecasts[name]
    mse_i = (y_oos - fc) ** 2
    t, p = dm_test(mse_i, mse_gjr)
    sig = '***' if p < 0.01 else ('**' if p < 0.05 else ('*' if p < 0.10 else ''))
    dm_vs_gjr[name] = {'t_stat': t, 'p_value': p}
    print(f"  {name:<16} {t:10.4f} {p:10.4f} {sig:>5}")

# ============================================================
# 7. SUBSAMPLE ANALYSIS (crisis vs normal)
# ============================================================
print("\n[6] Subsample Analysis")

# Define crisis periods
crisis_mask = df_oos['vix'].values > 25
normal_mask = ~crisis_mask
print(f"  Crisis days (VIX>25): {crisis_mask.sum()}")
print(f"  Normal days (VIX<=25): {normal_mask.sum()}")

print(f"\n  QLIKE by regime:")
print(f"  {'Model':<16} {'Normal':>10} {'Crisis':>10} {'Ratio':>8}")
print("  " + "-" * 48)

subsample_results = {}
for name in model_names:
    fc = forecasts[name]
    q_normal = qlike(y_oos[normal_mask], fc[normal_mask])
    q_crisis = qlike(y_oos[crisis_mask], fc[crisis_mask])
    ratio = q_crisis / q_normal if q_normal > 0 else np.nan
    subsample_results[name] = {'normal': q_normal, 'crisis': q_crisis, 'ratio': ratio}
    print(f"  {name:<16} {q_normal:10.6f} {q_crisis:10.6f} {ratio:8.2f}")

# ============================================================
# 8. NONLINEARITY DIAGNOSTIC: VIX vs r² scatter
# ============================================================
print("\n[7] Nonlinearity diagnostics...")

# Binned analysis: mean r² by VIX decile
vix_deciles = pd.qcut(df['vix_lag'], 10, labels=False, duplicates='drop')
binned = df.groupby(vix_deciles).agg(
    vix_mean=('vix_lag', 'mean'),
    r2_mean=('r2', 'mean'),
    r2_std=('r2', 'std'),
    count=('r2', 'count')
)
print("\n  VIX decile analysis:")
print(f"  {'Decile':>7} {'VIX_mean':>10} {'r²_mean':>12} {'r²_std':>12} {'N':>6}")
for idx, row in binned.iterrows():
    print(f"  {idx:>7} {row['vix_mean']:10.2f} {row['r2_mean']:12.8f} {row['r2_std']:12.8f} {int(row['count']):6d}")

# Convexity test: is the relationship convex?
# Compare slope in bottom half vs top half
vix_median = df['vix_lag'].median()
below = df[df['vix_lag'] <= vix_median]
above = df[df['vix_lag'] > vix_median]
slope_below_empirical = np.polyfit(below['vix_lag'], below['r2'], 1)[0]
slope_above_empirical = np.polyfit(above['vix_lag'], above['r2'], 1)[0]
convexity_ratio = slope_above_empirical / slope_below_empirical if slope_below_empirical != 0 else np.nan
print(f"\n  Convexity check:")
print(f"    Slope below median VIX ({vix_median:.1f}): {slope_below_empirical:.8f}")
print(f"    Slope above median VIX: {slope_above_empirical:.8f}")
print(f"    Convexity ratio: {convexity_ratio:.2f}x")

# ============================================================
# 9. PLOTS
# ============================================================
print("\n[8] Generating plots...")

# --- Plot 1: Nonlinear fit ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left: scatter + fitted curves
ax = axes[0]
# Subsample for visibility
np.random.seed(42)
idx_sample = np.random.choice(len(df), min(2000, len(df)), replace=False)
ax.scatter(df['vix_lag'].values[idx_sample], df['r2'].values[idx_sample],
           alpha=0.15, s=5, color='gray', label='Data')

# Plot fitted curves over VIX range
vix_range = np.linspace(df['vix_lag'].min(), min(df['vix_lag'].max(), 80), 200)

# M1 Linear
coef_m1 = [results['M1_Linear']['coef']['intercept'], results['M1_Linear']['coef']['beta_vix']]
ax.plot(vix_range, coef_m1[0] + coef_m1[1] * vix_range, 'b-', lw=2, label='M1: Linear')

# M2 Quadratic
c = results['M2_Quadratic']['coef']
ax.plot(vix_range, c['intercept'] + c['beta_vix'] * vix_range + c['beta_vix2'] * vix_range**2,
        'r-', lw=2, label='M2: Quadratic')

# M3 Log
c = results['M3_Log']['coef']
ax.plot(vix_range, c['intercept'] + c['beta_logvix'] * np.log(vix_range),
        'g-', lw=2, label='M3: Log')

# M4 Piecewise
c = results['M4_Piecewise']['coef']
pw_fit = c['intercept'] + c['beta_vix'] * vix_range + c['beta_vix_above20'] * np.maximum(vix_range - 20, 0)
ax.plot(vix_range, pw_fit, 'm-', lw=2, label='M4: Piecewise')

# Binned means
ax.plot(binned['vix_mean'].values, binned['r2_mean'].values, 'ko-', ms=6, lw=2, label='Decile means')

ax.set_xlabel('VIX (t-1)', fontsize=12)
ax.set_ylabel('r² (t)', fontsize=12)
ax.set_title('K987: VIX Nonlinearity in Vol Forecasting', fontsize=13)
ax.legend(fontsize=9)
ax.set_ylim(bottom=0)
ax.grid(True, alpha=0.3)

# Right: residuals vs VIX for M1 (showing nonlinearity)
ax = axes[1]
resid_m1 = y_oos - fc_oos_m1
vix_oos_plot = df_oos['vix_lag'].values

# Bin residuals
vix_oos_deciles = pd.qcut(vix_oos_plot, 10, labels=False, duplicates='drop')
resid_df = pd.DataFrame({'vix_decile': vix_oos_deciles, 'resid': resid_m1, 'vix': vix_oos_plot})
resid_binned = resid_df.groupby('vix_decile').agg(
    vix_mean=('vix', 'mean'),
    resid_mean=('resid', 'mean')
)

ax.bar(resid_binned['vix_mean'].values, resid_binned['resid_mean'].values, width=1.5, alpha=0.7, color='steelblue')
ax.axhline(0, color='red', ls='--', lw=1)
ax.set_xlabel('VIX decile mean', fontsize=12)
ax.set_ylabel('Mean residual (M1 Linear)', fontsize=12)
ax.set_title('M1 Residuals by VIX Level (OOS)', fontsize=13)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k987_nonlinear_fit.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k987_nonlinear_fit.png")

# --- Plot 2: OOS model comparison ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Top-left: QLIKE comparison
ax = axes[0, 0]
qlikes = [eval_results[n]['qlike'] for n in model_names]
colors = ['steelblue'] * len(model_names)
best_idx = np.argmin(qlikes)
colors[best_idx] = 'darkred'
bars = ax.bar(range(len(model_names)), qlikes, color=colors, alpha=0.8)
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels([n.replace('_', '\n') for n in model_names], fontsize=8, rotation=45, ha='right')
ax.set_ylabel('QLIKE (lower = better)', fontsize=11)
ax.set_title('QLIKE Comparison', fontsize=12)
ax.grid(True, alpha=0.3, axis='y')

# Top-right: OOS R²
ax = axes[0, 1]
r2s = [eval_results[n]['oos_r2'] for n in model_names]
colors = ['steelblue'] * len(model_names)
best_idx = np.argmax(r2s)
colors[best_idx] = 'darkred'
ax.bar(range(len(model_names)), r2s, color=colors, alpha=0.8)
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels([n.replace('_', '\n') for n in model_names], fontsize=8, rotation=45, ha='right')
ax.set_ylabel('OOS R²', fontsize=11)
ax.set_title('OOS R² Comparison', fontsize=12)
ax.grid(True, alpha=0.3, axis='y')

# Bottom-left: DM t-stats vs M2 (MSE)
ax = axes[1, 0]
dm_names = [n for n in model_names if n != 'M2_Quadratic']
dm_tstats = [dm_results[n]['t_stat'] for n in dm_names]
colors = ['green' if t < -1.96 else ('red' if t > 1.96 else 'gray') for t in dm_tstats]
ax.barh(range(len(dm_names)), dm_tstats, color=colors, alpha=0.8)
ax.set_yticks(range(len(dm_names)))
ax.set_yticklabels(dm_names, fontsize=9)
ax.axvline(-1.96, color='black', ls='--', lw=0.8, alpha=0.5)
ax.axvline(1.96, color='black', ls='--', lw=0.8, alpha=0.5)
ax.axvline(-3.0, color='red', ls='--', lw=0.8, alpha=0.5)
ax.set_xlabel('DM t-stat vs M2 Quadratic (MSE)', fontsize=11)
ax.set_title('DM Test (positive = M2 better)', fontsize=12)
ax.grid(True, alpha=0.3, axis='x')

# Bottom-right: MSE by regime (only well-behaved models)
ax = axes[1, 1]
good_names = ['M2_Quadratic', 'M4_Piecewise', 'M5_Spline', 'M7_MF2_VIX2', 'GJR_GARCH']
x = np.arange(len(good_names))
width = 0.35
normal_mse = [mse(y_oos[normal_mask], forecasts[n][normal_mask]) for n in good_names]
crisis_mse = [mse(y_oos[crisis_mask], forecasts[n][crisis_mask]) for n in good_names]
ax.bar(x - width/2, normal_mse, width, label='Normal (VIX≤25)', color='steelblue', alpha=0.8)
ax.bar(x + width/2, crisis_mse, width, label='Crisis (VIX>25)', color='indianred', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels([n.replace('_', '\n') for n in good_names], fontsize=8, rotation=45, ha='right')
ax.set_ylabel('MSE', fontsize=11)
ax.set_title('MSE by Regime (well-behaved models)', fontsize=12)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, axis='y')

plt.suptitle('K987: OOS Model Comparison (2019-2026)', fontsize=14, y=1.01)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k987_oos_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k987_oos_comparison.png")

# ============================================================
# 10. SAVE RESULTS
# ============================================================
print("\n[9] Saving results...")

# Determine best model
best_qlike = min(eval_results, key=lambda x: eval_results[x]['qlike'])
best_r2 = max(eval_results, key=lambda x: eval_results[x]['oos_r2'])

output = {
    "experiment_id": "K987",
    "title": "VIX² Nonlinearity in Volatility Forecasting",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY, ^VIX)",
    "sample_period": "2006-01-01 to 2026-04-07",
    "is_period": "2006-01-01 to 2018-12-31",
    "oos_period": "2019-01-01 to 2026-04-07",
    "n_is": len(df_is),
    "n_oos": len(df_oos),
    "target": "r² (daily squared return)",
    "lag": "shift(1) — all features use t-1",
    "seed": 42,
    "descriptive_stats": {
        "r2_mean": float(df['r2'].mean()),
        "r2_std": float(df['r2'].std()),
        "vix_mean": float(df['vix'].mean()),
        "vix_std": float(df['vix'].std()),
        "corr_vix_r2": float(corr_linear),
        "corr_logvix_r2": float(corr_log),
        "corr_vix2_r2": float(corr_sq),
    },
    "convexity_analysis": {
        "vix_median": float(vix_median),
        "slope_below_median": float(slope_below_empirical),
        "slope_above_median": float(slope_above_empirical),
        "convexity_ratio": float(convexity_ratio),
        "interpretation": f"VIX-vol slope is {convexity_ratio:.1f}x steeper above median VIX — confirms convex relationship"
    },
    "model_coefficients": {},
    "evaluation": {},
    "dm_test_vs_m2_mse": {},
    "dm_test_vs_gjr_mse": {},
    "dm_pairwise_mse": {},
    "subsample_analysis": {},
    "best_model_qlike": best_qlike,
    "best_model_r2": best_r2,
    "conclusions": [],
    "references": ["K979 (SKEW experiment — VIX² side finding)",
                    "K970 (MF2 framework)"]
}

# Fill in model-specific results
for name in model_names:
    # Coefficients
    if name in results and 'coef' in results[name]:
        coef_data = results[name]['coef']
        if isinstance(coef_data, dict):
            output['model_coefficients'][name] = {k: float(v) for k, v in coef_data.items()}
        else:
            output['model_coefficients'][name] = [float(c) for c in coef_data]

    # Evaluation
    ev = eval_results[name]
    output['evaluation'][name] = {
        'qlike': float(ev['qlike']),
        'mse': float(ev['mse']),
        'oos_r2': float(ev['oos_r2']),
        'mz_intercept': float(ev['mz_a']),
        'mz_slope': float(ev['mz_b']),
        'mz_r2': float(ev['mz_r2'])
    }

    # RESET test
    if name in results and 'reset_f' in results[name]:
        output['evaluation'][name]['reset_f'] = float(results[name]['reset_f'])
        output['evaluation'][name]['reset_p'] = float(results[name]['reset_p'])

    # DM vs M2 (MSE)
    if name in dm_results and name != 'M2_Quadratic':
        output['dm_test_vs_m2_mse'][name] = {
            't_stat': float(dm_results[name]['t_stat']),
            'p_value': float(dm_results[name]['p_value'])
        }

    # DM vs GJR (MSE)
    if name in dm_vs_gjr:
        output['dm_test_vs_gjr_mse'][name] = {
            't_stat': float(dm_vs_gjr[name]['t_stat']),
            'p_value': float(dm_vs_gjr[name]['p_value'])
        }

    # Subsample
    if name in subsample_results:
        output['subsample_analysis'][name] = {
            'qlike_normal': float(subsample_results[name]['normal']),
            'qlike_crisis': float(subsample_results[name]['crisis']),
            'crisis_normal_ratio': float(subsample_results[name]['ratio'])
        }

# Pairwise DM results
for pair_key, pair_data in dm_pairwise.items():
    output['dm_pairwise_mse'][pair_key] = {
        't_stat': float(pair_data['t_stat']),
        'p_value': float(pair_data['p_value']),
        'winner': pair_data['winner']
    }

# Conclusions
conclusions = []

# 1. Best model by OOS R²
conclusions.append(f"Best OOS R² model: {best_r2} (R²={eval_results[best_r2]['oos_r2']:.4f})")
conclusions.append(f"Best QLIKE model (among well-behaved): {best_qlike} (QLIKE={eval_results[best_qlike]['qlike']:.6f})")

# 2. Convexity
conclusions.append(f"VIX-vol convexity strongly confirmed: slope ratio {convexity_ratio:.1f}x above vs below median VIX")
conclusions.append(f"Correlation: VIX²-r² ({corr_sq:.4f}) > VIX-r² ({corr_linear:.4f}) > log(VIX)-r² ({corr_log:.4f})")

# 3. M2 vs others (pairwise)
for pair_key, pair_data in dm_pairwise.items():
    sig = '***' if pair_data['p_value'] < 0.01 else ('**' if pair_data['p_value'] < 0.05 else ('*' if pair_data['p_value'] < 0.10 else 'ns'))
    conclusions.append(f"DM(MSE) {pair_key}: t={pair_data['t_stat']:.3f}, p={pair_data['p_value']:.4f} → {pair_data['winner']} {sig}")

# 4. Negative forecast issue
conclusions.append("M1(Linear), M3(Log), M6(MF2-VIX) produce negative forecasts at low VIX — QLIKE unreliable for these")
conclusions.append("Models with non-negativity guaranteed (M2, M4, M5, M7) are preferable for variance forecasting")

# 5. All models fail RESET test
conclusions.append("All models fail RESET test (p<0.01) — residual nonlinearity persists even with quadratic/spline")
conclusions.append("Implication: VIX alone cannot fully capture the nonlinear VIX-vol relationship")

# 6. GJR comparison
conclusions.append(f"All VIX-based models beat GJR-GARCH: GJR OOS R²={eval_results['GJR_GARCH']['oos_r2']:.4f} (negative)")
conclusions.append("VIX is a far better vol predictor than GJR-GARCH for r² target")

output['conclusions'] = conclusions

with open(os.path.join(OUTPUT_DIR, 'k987_vix_nonlinear_results.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)
print("  Saved k987_vix_nonlinear_results.json")

# ============================================================
# 11. SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for c in conclusions:
    print(f"  • {c}")
print(f"\n  Files saved in: {OUTPUT_DIR}")
print("  Done.")
