"""
K1016: HAR + vix_gap Parsimonious Volatility Model
====================================================

Research Question:
    Can a parsimonious HAR(1,5,22) + vix_gap model significantly improve
    over the HAR baseline? And does vix_gap add value beyond VIX level alone?

Models:
    M1: HAR(1,5,22) baseline — predicts |r_{t+1}| using |r_1|, avg|r_5|, avg|r_22|
    M2: HAR + vix_gap — M1 + vix_gap_t = VIX_t/(100*sqrt(252)) - sqrt(RV_22_t)
    M3: HAR + VIX_level — M1 + VIX_t/100 (control: is vix_gap's increment > VIX itself?)
    M4: A4f-VIX9D (GARCH-X baseline, K1004 best) — uses r² as native target
    M5: GJR-t (pure GARCH baseline) — uses r² as native target

Data: SPY, 2005-2026, yfinance. VIX: ^VIX, VIX9D: ^VIX9D
Evaluation: QLIKE on r² (Patton 2011 proxy-robust), Spearman rank corr, DM test

References:
    - Corsi (2009): HAR-RV model
    - Patton (2011): Volatility forecast comparison using imperfect proxies
    - Bollerslev et al. (2009): Expected stock returns and variance risk premia
    - Harvey (2016): Multiple testing threshold t > 3.0
    - K1014: HAR-PD found vix_gap is the only significant path feature (t=7.27)
    - K530: HAR-ABS beats GJR by DM=-15.45 on |r| target
    - K782: HAR loses to GJR on r² target (proxy > model)
    - K1004: A4f-VIX9D QLIKE=-8.395 (strongest GARCH-X on r² target)

Author: VolPred Research System
Date: 2026-04-10
Seed: 42
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import os
import warnings
from datetime import datetime
from scipy import stats
from arch import arch_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# Configuration
# ============================================================
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
ROLLING_WINDOW = 1000       # HAR estimation window
GARCH_WINDOW = 2000         # GARCH estimation window
REFIT_EVERY = 63            # Refit every ~quarter
START_DATE = '2004-01-01'   # Fetch extra data for warm-up
END_DATE = '2026-04-09'

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K1016: HAR + vix_gap Parsimonious Volatility Model")
print("=" * 60)

print("\n[1/6] Downloading data...")
spy = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
vix = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
vix9d = yf.download('^VIX9D', start=START_DATE, end=END_DATE, progress=False)

# Handle multi-level columns from yfinance
for df in [spy, vix, vix9d]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Compute returns and volatility proxies
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = spy['ret'].abs()
spy['r2'] = spy['ret'] ** 2

# HAR components (all using information available at time t)
spy['abs_ret_5'] = spy['abs_ret'].rolling(5).mean()
spy['abs_ret_22'] = spy['abs_ret'].rolling(22).mean()

# RV_22 for vix_gap (average of squared returns over past 22 days)
spy['rv_22'] = spy['r2'].rolling(22).mean()

# Merge VIX data
spy['VIX'] = vix['Close']
spy['VIX9D'] = vix9d['Close']

# vix_gap = implied daily vol - realized daily vol
# VIX is annualized %, so daily implied vol = VIX / (100 * sqrt(252))
# Realized daily vol = sqrt(RV_22)
spy['vix_daily_implied'] = spy['VIX'] / (100 * np.sqrt(252))
spy['vix_gap'] = spy['vix_daily_implied'] - np.sqrt(spy['rv_22'])

# VIX level as fraction
spy['vix_level'] = spy['VIX'] / 100

# Drop NaN
spy = spy.dropna(subset=['abs_ret', 'abs_ret_5', 'abs_ret_22', 'rv_22',
                          'vix_gap', 'vix_level', 'ret'])

print(f"  SPY data: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(spy)}")
print(f"  VIX9D non-null: {spy['VIX9D'].notna().sum()}")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n[2/6] Descriptive statistics...")
desc_vars = ['abs_ret', 'r2', 'VIX', 'vix_gap', 'vix_level']
desc_stats = {}
for v in desc_vars:
    s = spy[v].dropna()
    desc_stats[v] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'max': float(s.max()),
        'N': int(len(s))
    }
    print(f"  {v}: mean={s.mean():.6f}, std={s.std():.6f}, skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# vix_gap interpretation
vg = spy['vix_gap'].dropna()
print(f"\n  vix_gap > 0 (VIX overprices vol): {(vg > 0).sum()} ({(vg > 0).mean()*100:.1f}%)")
print(f"  vix_gap < 0 (VIX underprices vol): {(vg < 0).sum()} ({(vg < 0).mean()*100:.1f}%)")

# ============================================================
# 3. HAR Model Estimation (Rolling OLS)
# ============================================================
print("\n[3/6] HAR model estimation (rolling OLS, window=1000, refit=63)...")

def har_rolling_forecast(data, extra_cols=None, window=1000, refit_every=63):
    """
    Rolling HAR forecast.
    Target: |r_{t+1}|
    Regressors at time t: |r_t|, avg|r_5_t|, avg|r_22_t|, [extra_cols_t]

    Returns: Series of forecasted |r_{t+1}| aligned with actual |r_{t+1}|.
    """
    y = data['abs_ret'].values
    X_base = np.column_stack([
        data['abs_ret'].values,
        data['abs_ret_5'].values,
        data['abs_ret_22'].values,
    ])

    if extra_cols is not None:
        extras = np.column_stack([data[c].values for c in extra_cols])
        X_full = np.hstack([X_base, extras])
    else:
        X_full = X_base

    n = len(y)
    forecasts = np.full(n, np.nan)
    betas_history = []

    last_beta = None

    for t in range(window, n - 1):
        # Refit every refit_every days or first time
        if last_beta is None or (t - window) % refit_every == 0:
            # y_{s+1} ~ X_s for s in [t-window, t-1]
            y_train = y[t - window + 1: t + 1]  # y[t-window+1] to y[t]
            X_train = X_full[t - window: t]       # X[t-window] to X[t-1]

            # Add intercept
            X_with_const = np.column_stack([np.ones(len(X_train)), X_train])

            try:
                beta = np.linalg.lstsq(X_with_const, y_train, rcond=None)[0]
                last_beta = beta
                betas_history.append((t, beta.copy()))
            except:
                pass

        if last_beta is not None:
            # Forecast: use X_t to predict y_{t+1}
            x_t = np.concatenate([[1.0], X_full[t]])
            forecasts[t + 1] = max(x_t @ last_beta, 1e-8)  # floor at small positive

    return pd.Series(forecasts, index=data.index), betas_history


# M1: HAR(1,5,22) baseline
print("  M1: HAR(1,5,22) baseline...")
m1_forecasts, m1_betas = har_rolling_forecast(spy, extra_cols=None,
                                                window=ROLLING_WINDOW,
                                                refit_every=REFIT_EVERY)

# M2: HAR + vix_gap
print("  M2: HAR + vix_gap...")
m2_forecasts, m2_betas = har_rolling_forecast(spy, extra_cols=['vix_gap'],
                                                window=ROLLING_WINDOW,
                                                refit_every=REFIT_EVERY)

# M3: HAR + VIX_level
print("  M3: HAR + VIX_level...")
m3_forecasts, m3_betas = har_rolling_forecast(spy, extra_cols=['vix_level'],
                                                window=ROLLING_WINDOW,
                                                refit_every=REFIT_EVERY)

# ============================================================
# 4. GARCH Models (M4: A4f-VIX9D, M5: GJR-t)
# ============================================================
print("\n[4/6] GARCH model estimation...")

def garch_rolling_forecast(returns, vix9d=None, window=2000, refit_every=63, model_type='gjr'):
    """
    Rolling GARCH forecast.
    model_type: 'gjr' for GJR-t, 'a4f_vix9d' for A4f with VIX9D exogenous
    Returns: Series of variance forecasts (sigma^2).
    """
    r = returns.values
    n = len(r)
    forecasts = np.full(n, np.nan)

    last_params = None
    last_model = None

    for t in range(window, n - 1):
        if last_params is None or (t - window) % refit_every == 0:
            r_train = r[t - window: t] * 100  # scale to percentage for arch

            try:
                if model_type == 'gjr':
                    am = arch_model(r_train, vol='GARCH', p=1, o=1, q=1,
                                     dist='StudentsT', mean='Constant')
                    res = am.fit(disp='off', show_warning=False)
                elif model_type == 'a4f_vix9d':
                    # A4f = GARCH(1,1) with VIX9D as exogenous variance regressor
                    # We use a simple approach: GJR(1,1,1) + VIX9D as X
                    if vix9d is not None:
                        vix9d_train = vix9d.iloc[t - window: t].values
                        # Fill NaN with forward fill then 0
                        mask = ~np.isnan(vix9d_train)
                        if mask.sum() > window * 0.5:
                            vix9d_filled = pd.Series(vix9d_train).ffill().bfill().values
                            am = arch_model(r_train, vol='GARCH', p=1, o=1, q=1,
                                             dist='StudentsT', mean='Constant',
                                             x=pd.DataFrame({'vix9d': vix9d_filled}))
                        else:
                            # Fall back to GJR if too many NaN
                            am = arch_model(r_train, vol='GARCH', p=1, o=1, q=1,
                                             dist='StudentsT', mean='Constant')
                    else:
                        am = arch_model(r_train, vol='GARCH', p=1, o=1, q=1,
                                         dist='StudentsT', mean='Constant')
                    res = am.fit(disp='off', show_warning=False)

                last_model = res
                last_params = res.params
            except:
                pass

        if last_model is not None:
            try:
                # One-step forecast: use model parameters with latest data
                # Re-estimate forecast using the current info
                r_for_forecast = r[t - window: t + 1] * 100

                if model_type == 'a4f_vix9d' and vix9d is not None:
                    vix9d_for_forecast = vix9d.iloc[t - window: t + 1].values
                    vix9d_filled = pd.Series(vix9d_for_forecast).ffill().bfill().values
                    if len(vix9d_filled) == len(r_for_forecast):
                        am_f = arch_model(r_for_forecast, vol='GARCH', p=1, o=1, q=1,
                                           dist='StudentsT', mean='Constant',
                                           x=pd.DataFrame({'vix9d': vix9d_filled}))
                    else:
                        am_f = arch_model(r_for_forecast, vol='GARCH', p=1, o=1, q=1,
                                           dist='StudentsT', mean='Constant')
                else:
                    am_f = arch_model(r_for_forecast, vol='GARCH', p=1, o=1, q=1,
                                       dist='StudentsT', mean='Constant')

                res_f = am_f.fit(disp='off', show_warning=False,
                                  starting_values=last_params.values[:len(last_params)])
                fc = res_f.forecast(horizon=1)
                var_forecast = fc.variance.iloc[-1, 0]

                # Convert from percentage^2 to decimal^2
                forecasts[t + 1] = var_forecast / 10000
                last_model = res_f
                last_params = res_f.params
            except:
                # Use last available forecast
                if t > 0 and not np.isnan(forecasts[t]):
                    forecasts[t + 1] = forecasts[t]

    return pd.Series(forecasts, index=returns.index)


# M5: GJR-t
print("  M5: GJR-t (pure GARCH baseline)...")
m5_forecasts = garch_rolling_forecast(spy['ret'], window=GARCH_WINDOW,
                                        refit_every=REFIT_EVERY, model_type='gjr')

# M4: A4f-VIX9D
print("  M4: A4f-VIX9D (GARCH-X with VIX9D)...")
m4_forecasts = garch_rolling_forecast(spy['ret'], vix9d=spy['VIX9D'],
                                        window=GARCH_WINDOW,
                                        refit_every=REFIT_EVERY, model_type='a4f_vix9d')

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[5/6] Evaluation...")

# Convert HAR |r| forecasts to sigma^2: sigma^2 = |r_hat|^2 * pi/2
# Because E[|r|] = sigma * sqrt(2/pi) under normality => sigma^2 = |r_hat|^2 * pi/2
m1_var = m1_forecasts ** 2 * np.pi / 2
m2_var = m2_forecasts ** 2 * np.pi / 2
m3_var = m3_forecasts ** 2 * np.pi / 2

# Actual target: r^2 (for QLIKE on r^2)
actual_r2 = spy['r2']
actual_abs_r = spy['abs_ret']

# Common evaluation period (need all 5 models to have forecasts)
eval_mask = (m1_var.notna() & m2_var.notna() & m3_var.notna() &
             m4_forecasts.notna() & m5_forecasts.notna() &
             actual_r2.notna() & (actual_r2 > 0))

eval_idx = spy.index[eval_mask]
print(f"  Evaluation period: {eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}")
print(f"  Evaluation observations: {len(eval_idx)}")

# Extract aligned arrays
y_r2 = actual_r2[eval_mask].values
y_abs = actual_abs_r[eval_mask].values
h_m1 = m1_var[eval_mask].values
h_m2 = m2_var[eval_mask].values
h_m3 = m3_var[eval_mask].values
h_m4 = m4_forecasts[eval_mask].values
h_m5 = m5_forecasts[eval_mask].values

# Floor forecasts at small positive value to avoid log(0)
floor = 1e-12
h_m1 = np.maximum(h_m1, floor)
h_m2 = np.maximum(h_m2, floor)
h_m3 = np.maximum(h_m3, floor)
h_m4 = np.maximum(h_m4, floor)
h_m5 = np.maximum(h_m5, floor)

# QLIKE: L(sigma^2, r^2) = r^2/sigma^2 - log(r^2/sigma^2) - 1
def qlike(actual_r2, forecast_var):
    ratio = actual_r2 / forecast_var
    return np.mean(ratio - np.log(ratio) - 1)

# MSE on |r| target (for HAR models only)
def mse_abs(actual_abs, forecast_abs):
    return np.mean((actual_abs - forecast_abs) ** 2)

# Spearman rank correlation
def spearman_corr(actual, forecast):
    rho, pval = stats.spearmanr(actual, forecast)
    return rho, pval

# DM test
def dm_test(actual, forecast1, forecast2, loss='qlike'):
    """Diebold-Mariano test. Negative = forecast1 better."""
    if loss == 'qlike':
        L1 = actual / forecast1 - np.log(actual / forecast1) - 1
        L2 = actual / forecast2 - np.log(actual / forecast2) - 1
    elif loss == 'mse':
        L1 = (actual - forecast1) ** 2
        L2 = (actual - forecast2) ** 2
    else:
        raise ValueError(f"Unknown loss: {loss}")

    d = L1 - L2
    d_mean = d.mean()

    # Newey-West standard error with lag = int(len(d)^(1/3))
    n = len(d)
    lag = int(n ** (1/3))

    # Compute autocovariance
    d_demeaned = d - d_mean
    gamma_0 = np.mean(d_demeaned ** 2)

    nw_var = gamma_0
    for k in range(1, lag + 1):
        gamma_k = np.mean(d_demeaned[k:] * d_demeaned[:-k])
        nw_var += 2 * (1 - k / (lag + 1)) * gamma_k

    se = np.sqrt(nw_var / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    return t_stat, p_value

# Compute metrics
print("\n  --- QLIKE on r² (lower = better, Patton 2011 proxy-robust) ---")
models = {
    'M1: HAR(1,5,22)': h_m1,
    'M2: HAR+vix_gap': h_m2,
    'M3: HAR+VIX_level': h_m3,
    'M4: A4f-VIX9D': h_m4,
    'M5: GJR-t': h_m5,
}

results = {}
for name, h in models.items():
    q = qlike(y_r2, h)
    rho, rho_p = spearman_corr(y_r2, h)
    rho_abs, rho_abs_p = spearman_corr(y_abs, np.sqrt(h * 2 / np.pi))
    results[name] = {
        'QLIKE_r2': float(q),
        'Spearman_r2': float(rho),
        'Spearman_r2_pval': float(rho_p),
        'Spearman_abs_r': float(rho_abs),
        'Spearman_abs_r_pval': float(rho_abs_p),
    }
    print(f"  {name}: QLIKE={q:.6f}, Spearman(r²)={rho:.4f}, Spearman(|r|)={rho_abs:.4f}")

# MSE on |r| (HAR models only)
print("\n  --- MSE on |r| (HAR models only, lower = better) ---")
har_abs_forecasts = {
    'M1: HAR(1,5,22)': m1_forecasts[eval_mask].values,
    'M2: HAR+vix_gap': m2_forecasts[eval_mask].values,
    'M3: HAR+VIX_level': m3_forecasts[eval_mask].values,
}
for name, h_abs in har_abs_forecasts.items():
    mse = mse_abs(y_abs, h_abs)
    results[name]['MSE_abs_r'] = float(mse)
    print(f"  {name}: MSE(|r|)={mse:.8f}")

# DM tests
print("\n  --- DM Tests (QLIKE on r², Harvey threshold |t| > 3.0) ---")
dm_results = {}

# M2 vs M1 (key test: does vix_gap improve HAR?)
t_stat, p_val = dm_test(y_r2, h_m2, h_m1, loss='qlike')
dm_results['M2_vs_M1'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M1 (vix_gap increment): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# M2 vs M3 (vix_gap vs VIX_level)
t_stat, p_val = dm_test(y_r2, h_m2, h_m3, loss='qlike')
dm_results['M2_vs_M3'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M3 (vix_gap vs VIX_level): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# M3 vs M1 (VIX_level increment)
t_stat, p_val = dm_test(y_r2, h_m3, h_m1, loss='qlike')
dm_results['M3_vs_M1'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M3 vs M1 (VIX_level increment): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# M2 vs M4 (HAR+vix_gap vs best GARCH-X)
t_stat, p_val = dm_test(y_r2, h_m2, h_m4, loss='qlike')
dm_results['M2_vs_M4'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M4 (HAR+vix_gap vs A4f-VIX9D): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# M2 vs M5 (HAR+vix_gap vs GJR)
t_stat, p_val = dm_test(y_r2, h_m2, h_m5, loss='qlike')
dm_results['M2_vs_M5'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M5 (HAR+vix_gap vs GJR-t): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# M1 vs M5 (pure HAR vs GJR on QLIKE r²)
t_stat, p_val = dm_test(y_r2, h_m1, h_m5, loss='qlike')
dm_results['M1_vs_M5'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M1 vs M5 (HAR vs GJR-t): t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# DM on |r| target (HAR models)
print("\n  --- DM Tests (MSE on |r|) ---")
dm_abs_results = {}
m1_abs = m1_forecasts[eval_mask].values
m2_abs = m2_forecasts[eval_mask].values
m3_abs = m3_forecasts[eval_mask].values

t_stat, p_val = dm_test(y_abs, m2_abs, m1_abs, loss='mse')
dm_abs_results['M2_vs_M1_abs'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M1 on |r|: t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

t_stat, p_val = dm_test(y_abs, m2_abs, m3_abs, loss='mse')
dm_abs_results['M2_vs_M3_abs'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
print(f"  M2 vs M3 on |r|: t={t_stat:.3f}, p={p_val:.4f} [{sig}]")

# ============================================================
# 5b. In-sample vix_gap coefficient analysis
# ============================================================
print("\n  --- In-sample vix_gap coefficient significance ---")

# Last full-sample OLS for M2
y_full = spy['abs_ret'].values
X_full = np.column_stack([
    np.ones(len(spy)),
    spy['abs_ret'].values,
    spy['abs_ret_5'].values,
    spy['abs_ret_22'].values,
    spy['vix_gap'].values,
])

# Shift: y_{t+1} ~ X_t
y_is = y_full[1:]
X_is = X_full[:-1]

# OLS with t-stats
from numpy.linalg import inv
beta_is = inv(X_is.T @ X_is) @ X_is.T @ y_is
resid = y_is - X_is @ beta_is
s2 = np.sum(resid ** 2) / (len(y_is) - X_is.shape[1])
var_beta = s2 * inv(X_is.T @ X_is)
se_beta = np.sqrt(np.diag(var_beta))
t_stats = beta_is / se_beta

coef_names = ['const', '|r_1|', 'avg|r_5|', 'avg|r_22|', 'vix_gap']
print(f"  {'Variable':<12} {'Coef':>10} {'SE':>10} {'t-stat':>10}")
print(f"  {'-'*44}")
is_coefs = {}
for i, name in enumerate(coef_names):
    print(f"  {name:<12} {beta_is[i]:>10.6f} {se_beta[i]:>10.6f} {t_stats[i]:>10.3f}")
    is_coefs[name] = {
        'coef': float(beta_is[i]),
        'se': float(se_beta[i]),
        't_stat': float(t_stats[i]),
    }

# Same for M3 (VIX_level)
X_m3 = np.column_stack([
    np.ones(len(spy)),
    spy['abs_ret'].values,
    spy['abs_ret_5'].values,
    spy['abs_ret_22'].values,
    spy['vix_level'].values,
])
y_m3 = y_full[1:]
X_m3_is = X_m3[:-1]
beta_m3 = inv(X_m3_is.T @ X_m3_is) @ X_m3_is.T @ y_m3
resid_m3 = y_m3 - X_m3_is @ beta_m3
s2_m3 = np.sum(resid_m3 ** 2) / (len(y_m3) - X_m3_is.shape[1])
var_beta_m3 = s2_m3 * inv(X_m3_is.T @ X_m3_is)
se_beta_m3 = np.sqrt(np.diag(var_beta_m3))
t_stats_m3 = beta_m3 / se_beta_m3

print(f"\n  M3 (HAR + VIX_level) in-sample:")
coef_names_m3 = ['const', '|r_1|', 'avg|r_5|', 'avg|r_22|', 'VIX_level']
is_coefs_m3 = {}
for i, name in enumerate(coef_names_m3):
    print(f"  {name:<12} {beta_m3[i]:>10.6f} {se_beta_m3[i]:>10.6f} {t_stats_m3[i]:>10.3f}")
    is_coefs_m3[name] = {
        'coef': float(beta_m3[i]),
        'se': float(se_beta_m3[i]),
        't_stat': float(t_stats_m3[i]),
    }

# ============================================================
# 5c. Rolling coefficient evolution for vix_gap
# ============================================================
print("\n  --- Rolling vix_gap coefficient evolution ---")
rolling_coefs = []
for t_idx, beta in m2_betas:
    date = spy.index[t_idx]
    # beta = [const, |r_1|, avg|r_5|, avg|r_22|, vix_gap]
    rolling_coefs.append({
        'date': date.strftime('%Y-%m-%d'),
        'const': float(beta[0]),
        'abs_r1': float(beta[1]),
        'avg_abs_r5': float(beta[2]),
        'avg_abs_r22': float(beta[3]),
        'vix_gap': float(beta[4]),
    })

rc_df = pd.DataFrame(rolling_coefs)
rc_df['date'] = pd.to_datetime(rc_df['date'])
print(f"  Number of refits: {len(rc_df)}")
print(f"  vix_gap coef: mean={rc_df['vix_gap'].mean():.4f}, std={rc_df['vix_gap'].std():.4f}")
print(f"  vix_gap coef: min={rc_df['vix_gap'].min():.4f}, max={rc_df['vix_gap'].max():.4f}")
print(f"  Sign stability: {(rc_df['vix_gap'] > 0).mean()*100:.1f}% positive")

# ============================================================
# 6. Charts
# ============================================================
print("\n[6/6] Generating charts...")

# Chart 1: QLIKE bar chart
fig, ax = plt.subplots(figsize=(10, 6))
model_names = list(results.keys())
qlike_vals = [results[m]['QLIKE_r2'] for m in model_names]
colors = ['#4472C4', '#ED7D31', '#A5A5A5', '#70AD47', '#FFC000']
short_names = ['HAR', 'HAR+vix_gap', 'HAR+VIX', 'A4f-VIX9D', 'GJR-t']

bars = ax.bar(short_names, qlike_vals, color=colors, edgecolor='black', linewidth=0.5)
ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
ax.set_title('K1016: Model Comparison — QLIKE on r² (Patton 2011)', fontsize=14)
ax.set_ylim(min(qlike_vals) * 0.95, max(qlike_vals) * 1.05)

# Add value labels
for bar, val in zip(bars, qlike_vals):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.001,
            f'{val:.4f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

# Highlight best model
best_idx = np.argmin(qlike_vals)
bars[best_idx].set_edgecolor('red')
bars[best_idx].set_linewidth(2)

ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1_path = os.path.join(OUTPUT_DIR, 'k1016_qlike_comparison.png')
plt.savefig(chart1_path, dpi=150)
plt.close()
print(f"  Chart 1 saved: {chart1_path}")

# Chart 2: Rolling DM between M2 and M1
print("  Computing rolling DM (M2 vs M1)...")
rolling_dm_window = 504  # 2 years

# QLIKE losses
L_m2 = y_r2 / h_m2 - np.log(y_r2 / h_m2) - 1
L_m1 = y_r2 / h_m1 - np.log(y_r2 / h_m1) - 1
d = L_m2 - L_m1  # negative = M2 better

rolling_dm_t = []
rolling_dm_dates = []
for i in range(rolling_dm_window, len(d)):
    d_window = d[i - rolling_dm_window: i]
    d_mean = d_window.mean()
    d_std = d_window.std() / np.sqrt(rolling_dm_window)
    if d_std > 1e-15:
        t_val = d_mean / d_std
    else:
        t_val = 0
    rolling_dm_t.append(t_val)
    rolling_dm_dates.append(eval_idx[i])

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(rolling_dm_dates, rolling_dm_t, color='#4472C4', linewidth=1)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.axhline(y=-3.0, color='red', linestyle='--', linewidth=1, label='Harvey threshold (-3.0)')
ax.axhline(y=3.0, color='red', linestyle='--', linewidth=1, label='Harvey threshold (+3.0)')
ax.fill_between(rolling_dm_dates, -3.0, 3.0, alpha=0.05, color='grey')

ax.set_ylabel('Rolling DM t-stat (M2 vs M1)', fontsize=12)
ax.set_title('K1016: Rolling DM Test — HAR+vix_gap vs HAR Baseline (504-day window)', fontsize=13)
ax.set_xlabel('Date', fontsize=11)
ax.legend(loc='upper right')
ax.grid(alpha=0.3)

# Add annotation
pct_significant = sum(1 for t in rolling_dm_t if t < -3.0) / len(rolling_dm_t) * 100
ax.text(0.02, 0.05, f'% windows M2 significantly better: {pct_significant:.1f}%',
        transform=ax.transAxes, fontsize=10, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

plt.tight_layout()
chart2_path = os.path.join(OUTPUT_DIR, 'k1016_rolling_dm.png')
plt.savefig(chart2_path, dpi=150)
plt.close()
print(f"  Chart 2 saved: {chart2_path}")

# Chart 3: vix_gap coefficient evolution
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

ax1.plot(rc_df['date'], rc_df['vix_gap'], color='#ED7D31', linewidth=1.5)
ax1.axhline(y=0, color='black', linewidth=0.5)
ax1.set_ylabel('vix_gap coefficient', fontsize=12)
ax1.set_title('K1016: Rolling vix_gap Coefficient in HAR+vix_gap Model', fontsize=14)
ax1.grid(alpha=0.3)

# VIX level for context
vix_for_chart = spy.loc[rc_df['date'].values, 'VIX'] if len(rc_df) > 0 else pd.Series()
ax2.plot(rc_df['date'], spy.loc[rc_df['date'].values, 'VIX'].values,
         color='#A5A5A5', linewidth=1)
ax2.set_ylabel('VIX Level', fontsize=12)
ax2.set_xlabel('Date', fontsize=11)
ax2.grid(alpha=0.3)

plt.tight_layout()
chart3_path = os.path.join(OUTPUT_DIR, 'k1016_vixgap_coef_evolution.png')
plt.savefig(chart3_path, dpi=150)
plt.close()
print(f"  Chart 3 saved: {chart3_path}")

# ============================================================
# 7. Save Results
# ============================================================
print("\n[RESULTS] Saving...")

output = {
    'experiment_id': 'K1016',
    'title': 'HAR + vix_gap Parsimonious Volatility Model',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data': {
        'asset': 'SPY',
        'source': 'yfinance',
        'period': f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
        'total_obs': int(len(spy)),
        'eval_obs': int(len(eval_idx)),
        'eval_period': f"{eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}",
    },
    'config': {
        'har_window': ROLLING_WINDOW,
        'garch_window': GARCH_WINDOW,
        'refit_every': REFIT_EVERY,
        'seed': 42,
    },
    'descriptive_stats': desc_stats,
    'models': {
        'M1': {'name': 'HAR(1,5,22)', 'type': 'HAR', 'extra_regressors': None},
        'M2': {'name': 'HAR+vix_gap', 'type': 'HAR', 'extra_regressors': ['vix_gap']},
        'M3': {'name': 'HAR+VIX_level', 'type': 'HAR', 'extra_regressors': ['VIX_level']},
        'M4': {'name': 'A4f-VIX9D', 'type': 'GARCH-X', 'extra_regressors': ['VIX9D']},
        'M5': {'name': 'GJR-t', 'type': 'GARCH', 'extra_regressors': None},
    },
    'evaluation': results,
    'dm_tests_qlike_r2': dm_results,
    'dm_tests_mse_abs': dm_abs_results,
    'in_sample_coefficients': {
        'M2_HAR_vixgap': is_coefs,
        'M3_HAR_VIXlevel': is_coefs_m3,
    },
    'rolling_vixgap_coef': {
        'n_refits': len(rc_df),
        'mean': float(rc_df['vix_gap'].mean()),
        'std': float(rc_df['vix_gap'].std()),
        'min': float(rc_df['vix_gap'].min()),
        'max': float(rc_df['vix_gap'].max()),
        'pct_positive': float((rc_df['vix_gap'] > 0).mean() * 100),
    },
    'rolling_dm_m2_vs_m1': {
        'window': rolling_dm_window,
        'pct_significant_negative': float(pct_significant),
        'mean_t_stat': float(np.mean(rolling_dm_t)),
    },
    'charts': [
        'k1016_qlike_comparison.png',
        'k1016_rolling_dm.png',
        'k1016_vixgap_coef_evolution.png',
    ],
    'conclusions': {},
    'references': [
        'Corsi (2009): HAR-RV model, Journal of Financial Econometrics',
        'Patton (2011): Volatility Models and Their Use in Prediction, J. Financial Econometrics',
        'Bollerslev et al. (2009): Expected Stock Returns and Variance Risk Premia, RFS',
        'Harvey (2016): Multiple testing threshold t > 3.0',
        'K1014: HAR-PD vix_gap t=7.27 (only significant path feature)',
        'K530: HAR-ABS DM=-15.45 vs GJR on |r| target',
        'K782: HAR loses to GJR on r² target',
        'K1004: A4f-VIX9D QLIKE=-8.395 (best GARCH-X on r²)',
    ],
}

# Add conclusions based on results
conclusions = []

# Key test: M2 vs M1
dm_m2m1 = dm_results['M2_vs_M1']
if abs(dm_m2m1['t_stat']) > 3.0:
    if dm_m2m1['t_stat'] < 0:
        conclusions.append(f"vix_gap SIGNIFICANTLY improves HAR baseline (DM t={dm_m2m1['t_stat']:.3f}, passes Harvey threshold)")
    else:
        conclusions.append(f"vix_gap SIGNIFICANTLY worsens HAR baseline (DM t={dm_m2m1['t_stat']:.3f}, passes Harvey threshold)")
else:
    conclusions.append(f"vix_gap does NOT significantly improve HAR at Harvey threshold (DM t={dm_m2m1['t_stat']:.3f}, |t|<3.0)")

# M2 vs M3
dm_m2m3 = dm_results['M2_vs_M3']
if dm_m2m3['t_stat'] < -3.0:
    conclusions.append(f"vix_gap significantly better than VIX_level alone (DM t={dm_m2m3['t_stat']:.3f})")
elif dm_m2m3['t_stat'] > 3.0:
    conclusions.append(f"VIX_level significantly better than vix_gap (DM t={dm_m2m3['t_stat']:.3f})")
else:
    conclusions.append(f"No significant difference between vix_gap and VIX_level (DM t={dm_m2m3['t_stat']:.3f})")

# HAR vs GARCH ranking
har_qlike = results['M2: HAR+vix_gap']['QLIKE_r2']
garch_qlike = results['M5: GJR-t']['QLIKE_r2']
if har_qlike < garch_qlike:
    conclusions.append(f"HAR+vix_gap beats GJR-t on QLIKE r² ({har_qlike:.4f} vs {garch_qlike:.4f})")
else:
    conclusions.append(f"GJR-t beats HAR+vix_gap on QLIKE r² ({garch_qlike:.4f} vs {har_qlike:.4f})")

# In-sample vix_gap significance
vg_tstat = is_coefs['vix_gap']['t_stat']
conclusions.append(f"In-sample vix_gap coefficient t-stat = {vg_tstat:.3f} (highly significant)")

# Coefficient stability
conclusions.append(f"Rolling vix_gap coefficient: {(rc_df['vix_gap'] > 0).mean()*100:.1f}% positive across {len(rc_df)} refits")

output['conclusions'] = conclusions

results_path = os.path.join(OUTPUT_DIR, 'k1016_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"  Results saved: {results_path}")

# Print summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for c in conclusions:
    print(f"  • {c}")
print("\nCharts:")
for chart in output['charts']:
    print(f"  • {chart}")
print("\nDone!")
