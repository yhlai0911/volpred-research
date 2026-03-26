#!/usr/bin/env python3
"""
K490: GJR-GARCH-X(VIX9D) vs GJR-X(VIX) Comparison
====================================================
Background:
  K486: GJR-X(VIX) breaks impossible triangle (forecasting -4.6% QLIKE + VaR 5/5)
  K489: VIX9D R²=0.41 for 5d vol (best single predictor, beats VIX R²=0.34)
  Question: Does VIX9D work better than VIX as exogenous in GARCH-X variance eq?

Models:
  1. GJR-GARCH baseline (no exogenous)
  2. GJR-X(VIX) — K486 winner (h_t += δ·VIX²/252)
  3. GJR-X(VIX9D) — new (h_t += δ·VIX9D²/252)
  4. GJR-X(VIX+VIX9D) — both exogenous

VIX9D ^VIX9D available from ~2018 on yfinance, so shorter history.
3 OOS periods:
  1. 2019-2020 (COVID)
  2. 2021-2022 (rate hikes)
  3. 2023-2024

Evaluation:
  - QLIKE with r² proxy (Patton 2011)
  - DM test: VIX9D vs VIX (pairwise)
  - VaR Trinity at 1% and 5% (Kupiec + Christoffersen + DQ)
  - Delta coefficient stability across periods

Data: yfinance (SPY, ^VIX, ^VIX9D), 2018-2026
Efficiency: Custom log-likelihood, 3 periods × 4 models × ~15 refits = ~180 fits, target < 2 min

Refs:
  Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models
  Christoffersen (1998) Evaluating Interval Forecasts, International Economic Review
  Engle & Manganelli (2004) CAViaR: Conditional Autoregressive VaR, JBES
  Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE
  Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES
  K486, K489
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.special import gammaln
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K490: GJR-GARCH-X(VIX9D) vs GJR-X(VIX) Comparison")
print("  4 models × 3 periods × QLIKE + VaR(1%,5%) × Trinity(3 tests)")
print("  Core Q: VIX9D better than VIX in GARCH-X variance equation?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 500  # Shorter window due to limited VIX9D history (2018+); 500 to cover COVID OOS
REFIT_INTERVAL = 21  # refit every ~1 month

OOS_PERIODS = [
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
]

ALPHA_LEVELS = [0.01, 0.05]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start='2017-01-01', progress=False)
vix_raw = yf.download('^VIX', start='2017-01-01', progress=False)
vix9d_raw = yf.download('^VIX9D', start='2017-01-01', progress=False)

for df_name, df in [('SPY', spy_raw), ('VIX', vix_raw), ('VIX9D', vix9d_raw)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df_name == 'SPY':
        spy_raw = df
    elif df_name == 'VIX':
        vix_raw = df
    else:
        vix9d_raw = df

print(f"  SPY:   {spy_raw.index[0].date()} to {spy_raw.index[-1].date()} ({len(spy_raw)} obs)")
print(f"  VIX:   {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")
print(f"  VIX9D: {vix9d_raw.index[0].date()} to {vix9d_raw.index[-1].date()} ({len(vix9d_raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

spy_close = spy_raw['Close'].values.astype(float).ravel()
vix_close = vix_raw['Close'].values.astype(float).ravel()
vix9d_close = vix9d_raw['Close'].values.astype(float).ravel()

# Log returns in %
spy_ret_pct = np.log(spy_close[1:] / spy_close[:-1]) * 100
spy_idx = spy_raw.index[1:]

df_spy = pd.DataFrame({
    'return_pct': spy_ret_pct,
    'r2_proxy': (np.log(spy_close[1:] / spy_close[:-1]))**2,  # decimal²
}, index=spy_idx)

df_vix = pd.DataFrame({'VIX': vix_close}, index=vix_raw.index)
df_vix9d = pd.DataFrame({'VIX9D': vix9d_close}, index=vix9d_raw.index)

# Merge on date (inner join — only dates with all 3 available)
feat = df_spy.join(df_vix, how='inner').join(df_vix9d, how='inner')
feat = feat.dropna()

# VIX/VIX9D implied daily variance: X²/252 in %² units
# VIX=20 → 20²/252 = 1.587 %² daily, matches return_pct variance
feat['vix_daily_var'] = feat['VIX']**2 / 252
feat['vix9d_daily_var'] = feat['VIX9D']**2 / 252

print(f"  Combined: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")
print(f"  VIX:   mean={feat['VIX'].mean():.1f}, std={feat['VIX'].std():.1f}")
print(f"  VIX9D: mean={feat['VIX9D'].mean():.1f}, std={feat['VIX9D'].std():.1f}")
print(f"  VIX daily var:   mean={feat['vix_daily_var'].mean():.3f} %²")
print(f"  VIX9D daily var: mean={feat['vix9d_daily_var'].mean():.3f} %²")
print(f"  Corr(VIX, VIX9D): {feat['VIX'].corr(feat['VIX9D']):.4f}")
print(f"  Corr(VIX_var, VIX9D_var): {feat['vix_daily_var'].corr(feat['vix9d_daily_var']):.4f}")
print(f"  Return var: mean={feat['return_pct'].var():.3f} %²")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values

adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
arch_stat_val, arch_p, _, _ = het_arch(ret, nlags=10)
lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)

diagnostics = {
    'n_obs': len(feat),
    'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'return_mean_pct': float(np.mean(ret)),
    'return_std_pct': float(np.std(ret)),
    'return_skew': float(stats.skew(ret)),
    'return_kurt': float(stats.kurtosis(ret)),
    'vix_mean': float(feat['VIX'].mean()),
    'vix_std': float(feat['VIX'].std()),
    'vix9d_mean': float(feat['VIX9D'].mean()),
    'vix9d_std': float(feat['VIX9D'].std()),
    'corr_vix_vix9d': float(feat['VIX'].corr(feat['VIX9D'])),
    'corr_vix_var_vix9d_var': float(feat['vix_daily_var'].corr(feat['vix9d_daily_var'])),
    'vix_daily_var_mean': float(feat['vix_daily_var'].mean()),
    'vix9d_daily_var_mean': float(feat['vix9d_daily_var'].mean()),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat_val),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
    'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")
print(f"  Return: mean={np.mean(ret):.4f}%, std={np.std(ret):.4f}%, skew={stats.skew(ret):.3f}, kurt={stats.kurtosis(ret):.3f}")
print(f"  Corr(VIX, VIX9D) = {diagnostics['corr_vix_vix9d']:.4f}")

# ============================================================
# 4. MODEL ESTIMATION FUNCTIONS
# ============================================================

def fit_gjr_garch(returns_pct):
    """Standard GJR-GARCH(1,1) with Student-t via arch package."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        return res
    except Exception:
        return None


def gjr_garchx_loglik(params, returns, exog_lag, n_exog):
    """
    Custom log-likelihood for GJR-GARCH-X with 1 or 2 exogenous variables.

    h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + Σ δ_i·X_i_{t-1}

    params layout:
      [mu, omega, alpha, gamma, beta, delta_1, ..., delta_n, nu]

    exog_lag: (T, n_exog) array of lagged exogenous variables
    """
    mu = params[0]
    omega = params[1]
    alpha = params[2]
    gamma = params[3]
    beta = params[4]
    deltas = params[5:5+n_exog]
    nu = params[5+n_exog]

    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)

    # Initialize with unconditional variance
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0

    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 if eps[t-1] < 0 else 0.0
        exog_contrib = 0.0
        for i in range(n_exog):
            exog_contrib += deltas[i] * exog_lag[t, i]
        h[t] = omega + alpha * shock2 + gamma * asym + beta * h[t-1] + exog_contrib
        if h[t] <= 0:
            h[t] = 1e-6

    # Student-t log-likelihood
    ll = (
        gammaln((nu + 1) / 2) - gammaln(nu / 2)
        - 0.5 * np.log(np.pi * (nu - 2))
        - 0.5 * np.log(h)
        - (nu + 1) / 2 * np.log(1 + eps**2 / (h * (nu - 2)))
    )

    return -np.sum(ll)


def fit_gjr_garchx(returns_pct, exog_vars, exog_names=None):
    """
    Fit GJR-GARCH-X with 1 or 2 exogenous variables via custom MLE.

    returns_pct: array of returns in %
    exog_vars: list of arrays, each VIX²/252 or VIX9D²/252 in %² (same length)
    exog_names: list of strings for labeling

    Returns dict with params, h_forecast, or None on failure.
    """
    n_exog = len(exog_vars)
    T = len(returns_pct)
    ret = returns_pct.copy()

    # Build lagged exogenous matrix (T, n_exog)
    exog_lag = np.zeros((T, n_exog))
    for i, xv in enumerate(exog_vars):
        exog_lag[1:, i] = xv[:-1]
        exog_lag[0, i] = xv[0]

    # Initial guess
    mu0 = np.mean(ret)
    x0 = [mu0, 0.01, 0.05, 0.05, 0.90] + [0.01]*n_exog + [6.0]

    # Bounds
    bounds = [
        (-1.0, 1.0),        # mu
        (1e-6, 10.0),       # omega
        (1e-6, 0.5),        # alpha
        (0.0, 0.5),         # gamma
        (0.3, 0.999),       # beta
    ]
    for _ in range(n_exog):
        bounds.append((0.0, 1.0))  # delta_i
    bounds.append((2.1, 50.0))     # nu

    try:
        result = optimize.minimize(
            gjr_garchx_loglik, x0, args=(ret, exog_lag, n_exog),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )

        if not result.success and result.fun > 1e10:
            return None

        mu = result.x[0]
        omega = result.x[1]
        alpha_val = result.x[2]
        gamma_val = result.x[3]
        beta_val = result.x[4]
        deltas = result.x[5:5+n_exog]
        nu = result.x[5+n_exog]

        # Reconstruct h series
        eps = ret - mu
        h = np.zeros(T)
        h[0] = np.var(eps)
        if h[0] <= 0:
            h[0] = 1.0
        for t in range(1, T):
            shock2 = eps[t-1]**2
            asym = shock2 if eps[t-1] < 0 else 0.0
            exog_c = sum(deltas[i] * exog_lag[t, i] for i in range(n_exog))
            h[t] = omega + alpha_val * shock2 + gamma_val * asym + beta_val * h[t-1] + exog_c
            if h[t] <= 0:
                h[t] = 1e-6

        # 1-step ahead forecast
        shock2_last = eps[-1]**2
        asym_last = shock2_last if eps[-1] < 0 else 0.0
        exog_last = sum(deltas[i] * exog_vars[i][-1] for i in range(n_exog))
        h_forecast = omega + alpha_val * shock2_last + gamma_val * asym_last + beta_val * h[-1] + exog_last
        if h_forecast <= 0:
            h_forecast = 1e-6

        persistence = alpha_val + gamma_val / 2 + beta_val

        param_dict = {
            'mu': float(mu),
            'omega': float(omega),
            'alpha': float(alpha_val),
            'gamma': float(gamma_val),
            'beta': float(beta_val),
            'nu': float(nu),
            'persistence': float(persistence),
        }
        for i in range(n_exog):
            name = exog_names[i] if exog_names else f'delta_{i}'
            param_dict[f'delta_{name}'] = float(deltas[i])

        return {
            'params': param_dict,
            'persistence': float(persistence),
            'h_forecast': float(h_forecast),
            'h_series': h,
            'loglik': float(-result.fun),
            'converged': result.success,
        }
    except Exception:
        return None


# ============================================================
# 5. VaR TEST FUNCTIONS (Trinity: Kupiec + Christoffersen + DQ)
# ============================================================

def kupiec_test(violations, n_total, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_total if n_total > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0
    lr = -2 * (n_viol * np.log(alpha / p_hat) +
               (n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)))
    pval = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(pval)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test."""
    n = len(violations)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i-1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i-1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i-1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n
    if p == 0 or p == 1 or p01 == 0 or p01 == 1:
        return 0.0, 1.0
    if p11 == 0 or p11 == 1:
        return 0.0, 1.0
    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(pval)


def dq_test(violations, var_forecasts, n_lags=4):
    """Engle & Manganelli (2004) Dynamic Quantile test."""
    alpha = np.mean(violations)
    if alpha <= 0 or alpha >= 1:
        return 0.0, 1.0
    hit = violations.astype(float) - alpha
    T = len(hit)
    if T <= n_lags + 2:
        return 0.0, 1.0
    y = hit[n_lags:]
    X_cols = [np.ones(T - n_lags)]
    for lag in range(1, n_lags + 1):
        X_cols.append(hit[n_lags - lag:T - lag])
    X_cols.append(var_forecasts[n_lags:])
    X = np.column_stack(X_cols)
    try:
        XtX = X.T @ X
        Xty = X.T @ y
        try:
            XtX_inv = np.linalg.inv(XtX)
        except np.linalg.LinAlgError:
            return 0.0, 1.0
        k = X.shape[1]
        dq_stat = float(Xty.T @ XtX_inv @ Xty / (alpha * (1 - alpha)))
        dq_pval = 1 - stats.chi2.cdf(dq_stat, df=k)
        return float(dq_stat), float(dq_pval)
    except Exception:
        return 0.0, 1.0


def run_var_trinity(violations, var_forecasts, n_total, alpha_level):
    """Run all 3 VaR tests."""
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n_total if n_total > 0 else 0
    kup_stat, kup_p = kupiec_test(violations, n_total, alpha_level)
    chr_stat, chr_p = christoffersen_test(violations)
    dq_stat, dq_p = dq_test(violations, var_forecasts)
    kupiec_pass = bool(kup_p > 0.05)
    chris_pass = bool(chr_p > 0.05)
    dq_pass = bool(dq_p > 0.05)
    n_pass = int(kupiec_pass) + int(chris_pass) + int(dq_pass)
    return {
        'n_obs': n_total,
        'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4),
        'expected_rate': alpha_level,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4), 'pass': kupiec_pass},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(chr_p, 4), 'pass': chris_pass},
        'dq': {'stat': round(dq_stat, 4), 'p_value': round(dq_p, 4), 'pass': dq_pass},
        'trinity_pass': n_pass == 3,
        'tests_passed': f"{n_pass}/3",
    }


# ============================================================
# 6. DM TEST
# ============================================================

def diebold_mariano_test(loss1, loss2, h=1):
    """DM test. Positive stat → model 2 better (loss1 > loss2)."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    V = gamma_0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        V += 2 * (1 - k / h) * gamma_k
    if V <= 0:
        return 0.0, 1.0
    dm_stat = d_bar / np.sqrt(V / T)
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_pval)


# ============================================================
# 7. MAIN CROSS-OOS LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Cross-OOS QLIKE + VaR Backtesting")
print("=" * 70)

MODEL_NAMES = ['GJR', 'GJR-X(VIX)', 'GJR-X(VIX9D)', 'GJR-X(VIX+VIX9D)']

t_start = time.time()
all_period_results = {}
delta_tracker = {m: [] for m in MODEL_NAMES}

for p_idx, period in enumerate(OOS_PERIODS):
    p_name = period['name']
    print(f"\n{'─'*60}")
    print(f"  Period {p_idx+1}/3: {p_name}")
    print(f"{'─'*60}")

    oos_mask = (feat.index >= period['start']) & (feat.index <= period['end'])
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data")
        continue

    first_oos_loc = feat.index.get_loc(oos_dates[0])
    if first_oos_loc < IS_WINDOW:
        print(f"  SKIP: insufficient IS data ({first_oos_loc} < {IS_WINDOW})")
        continue

    n_oos = len(oos_dates)
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")

    # Storage for 4 models
    model_forecasts = {m: np.zeros(n_oos) for m in MODEL_NAMES}
    model_var_1pct = {m: np.zeros(n_oos) for m in MODEL_NAMES}
    model_var_5pct = {m: np.zeros(n_oos) for m in MODEL_NAMES}
    model_deltas = {m: [] for m in MODEL_NAMES}
    model_params_last = {m: {} for m in MODEL_NAMES}

    actual_ret_pct = np.zeros(n_oos)
    actual_r2 = np.zeros(n_oos)

    n_refits = 0
    last_results = {m: None for m in MODEL_NAMES}

    for i in range(n_oos):
        oos_loc = first_oos_loc + i

        # Refit check
        need_refit = (i == 0) or (i % REFIT_INTERVAL == 0)

        if need_refit:
            n_refits += 1
            is_start = oos_loc - IS_WINDOW
            is_end = oos_loc  # exclusive

            is_ret = feat['return_pct'].values[is_start:is_end]
            is_vix_var = feat['vix_daily_var'].values[is_start:is_end]
            is_vix9d_var = feat['vix9d_daily_var'].values[is_start:is_end]

            # Model 1: GJR baseline
            res_gjr = fit_gjr_garch(is_ret)
            if res_gjr is not None:
                last_results['GJR'] = res_gjr

            # Model 2: GJR-X(VIX)
            res_vix = fit_gjr_garchx(is_ret, [is_vix_var], exog_names=['VIX'])
            if res_vix is not None:
                last_results['GJR-X(VIX)'] = res_vix
                model_deltas['GJR-X(VIX)'].append(res_vix['params']['delta_VIX'])

            # Model 3: GJR-X(VIX9D)
            res_v9d = fit_gjr_garchx(is_ret, [is_vix9d_var], exog_names=['VIX9D'])
            if res_v9d is not None:
                last_results['GJR-X(VIX9D)'] = res_v9d
                model_deltas['GJR-X(VIX9D)'].append(res_v9d['params']['delta_VIX9D'])

            # Model 4: GJR-X(VIX+VIX9D)
            res_both = fit_gjr_garchx(is_ret, [is_vix_var, is_vix9d_var], exog_names=['VIX', 'VIX9D'])
            if res_both is not None:
                last_results['GJR-X(VIX+VIX9D)'] = res_both
                model_deltas['GJR-X(VIX+VIX9D)'].append(
                    (res_both['params']['delta_VIX'], res_both['params']['delta_VIX9D'])
                )

        # Record actual
        actual_ret_pct[i] = feat['return_pct'].values[oos_loc]
        actual_r2[i] = feat['r2_proxy'].values[oos_loc]

        # Get current exogenous values (for 1-step forecast)
        current_vix_var = feat['vix_daily_var'].values[oos_loc]
        current_vix9d_var = feat['vix9d_daily_var'].values[oos_loc]

        # Forecast from each model
        for m_name in MODEL_NAMES:
            lr = last_results[m_name]
            if lr is None:
                # Fallback: use sample variance
                model_forecasts[m_name][i] = np.var(feat['return_pct'].values[:oos_loc]) / 10000
                sigma = np.sqrt(model_forecasts[m_name][i]) * 100
                model_var_1pct[m_name][i] = -sigma * stats.t.ppf(0.01, df=5)
                model_var_5pct[m_name][i] = -sigma * stats.t.ppf(0.05, df=5)
                continue

            if m_name == 'GJR':
                # Standard GJR from arch package — use forecast
                try:
                    fcast = lr.forecast(horizon=1, reindex=False)
                    h_fcast = fcast.variance.values[-1, 0]
                    # h_fcast is in %² (since returns are in %)
                    sigma_pct = np.sqrt(h_fcast)
                    nu = lr.params.get('nu', 5.0)
                    model_forecasts[m_name][i] = h_fcast / 10000  # decimal²
                    model_var_1pct[m_name][i] = sigma_pct / 100 * (-stats.t.ppf(0.01, df=nu))
                    model_var_5pct[m_name][i] = sigma_pct / 100 * (-stats.t.ppf(0.05, df=nu))
                    model_params_last[m_name] = dict(lr.params)
                except Exception:
                    model_forecasts[m_name][i] = np.var(feat['return_pct'].values[:oos_loc]) / 10000
                    sigma = np.sqrt(model_forecasts[m_name][i]) * 100
                    model_var_1pct[m_name][i] = -sigma / 100 * stats.t.ppf(0.01, df=5)
                    model_var_5pct[m_name][i] = -sigma / 100 * stats.t.ppf(0.05, df=5)
            else:
                # Custom GJR-X models
                p = lr['params']
                mu = p['mu']
                omega = p['omega']
                alpha_v = p['alpha']
                gamma_v = p['gamma']
                beta_v = p['beta']
                nu = p['nu']

                # Previous residual and h come from in-sample last values
                # We use the model's last h and last eps to do 1-step forecast
                h_last = lr['h_series'][-1]
                is_ret_last = feat['return_pct'].values[oos_loc - 1]
                eps_last = is_ret_last - mu
                shock2 = eps_last**2
                asym = shock2 if eps_last < 0 else 0.0

                if m_name == 'GJR-X(VIX)':
                    delta_vix = p['delta_VIX']
                    h_fcast = omega + alpha_v * shock2 + gamma_v * asym + beta_v * h_last + delta_vix * current_vix_var
                elif m_name == 'GJR-X(VIX9D)':
                    delta_v9d = p['delta_VIX9D']
                    h_fcast = omega + alpha_v * shock2 + gamma_v * asym + beta_v * h_last + delta_v9d * current_vix9d_var
                else:  # VIX+VIX9D
                    delta_vix = p['delta_VIX']
                    delta_v9d = p['delta_VIX9D']
                    h_fcast = omega + alpha_v * shock2 + gamma_v * asym + beta_v * h_last + delta_vix * current_vix_var + delta_v9d * current_vix9d_var

                if h_fcast <= 0:
                    h_fcast = 1e-6

                sigma_pct = np.sqrt(h_fcast)
                model_forecasts[m_name][i] = h_fcast / 10000  # decimal²
                model_var_1pct[m_name][i] = sigma_pct / 100 * (-stats.t.ppf(0.01, df=nu))
                model_var_5pct[m_name][i] = sigma_pct / 100 * (-stats.t.ppf(0.05, df=nu))
                model_params_last[m_name] = p

                # Update h_series for next iteration (rolling forward)
                lr['h_series'] = np.append(lr['h_series'], h_fcast)

    print(f"  Refits: {n_refits}")

    # ── Compute QLIKE for each model ──
    period_results = {'name': p_name, 'n_oos': n_oos, 'n_refits': n_refits, 'models': {}}

    for m_name in MODEL_NAMES:
        sigma2_forecast = model_forecasts[m_name]  # in decimal²
        # QLIKE = mean(r²/σ² + log(σ²)) with r² proxy (decimal²)
        r2_decimal = actual_r2  # already decimal²

        # Avoid division by zero
        valid = sigma2_forecast > 0
        if valid.sum() < 10:
            print(f"  {m_name}: TOO FEW VALID FORECASTS ({valid.sum()})")
            continue

        qlike_arr = r2_decimal[valid] / sigma2_forecast[valid] + np.log(sigma2_forecast[valid])
        qlike = float(np.mean(qlike_arr))

        # VaR violations
        actual_decimal = actual_ret_pct / 100  # decimal returns
        violations_1pct = (actual_decimal < -model_var_1pct[m_name]).astype(int)
        violations_5pct = (actual_decimal < -model_var_5pct[m_name]).astype(int)

        var_results_1 = run_var_trinity(violations_1pct, model_var_1pct[m_name], n_oos, 0.01)
        var_results_5 = run_var_trinity(violations_5pct, model_var_5pct[m_name], n_oos, 0.05)

        trinity_1_pass = var_results_1['trinity_pass']
        trinity_5_pass = var_results_5['trinity_pass']

        period_results['models'][m_name] = {
            'qlike': qlike,
            'qlike_array': qlike_arr.tolist(),
            'var_1pct': var_results_1,
            'var_5pct': var_results_5,
            'params_last': {k: float(v) if isinstance(v, (float, np.floating)) else v
                           for k, v in model_params_last[m_name].items()} if model_params_last[m_name] else {},
        }

        vr1 = var_results_1['violation_rate']
        vr5 = var_results_5['violation_rate']
        print(f"  {m_name:25s}: QLIKE={qlike:.6f}  VaR1%={vr1:.3f}({var_results_1['tests_passed']})  VaR5%={vr5:.3f}({var_results_5['tests_passed']})")

    # ── DM tests (pairwise vs GJR baseline) ──
    dm_results = {}
    if 'GJR' in period_results['models']:
        gjr_qlike_arr = np.array(period_results['models']['GJR']['qlike_array'])
        for m_name in MODEL_NAMES[1:]:
            if m_name in period_results['models']:
                m_qlike_arr = np.array(period_results['models'][m_name]['qlike_array'])
                # Ensure same length
                min_len = min(len(gjr_qlike_arr), len(m_qlike_arr))
                dm_stat, dm_p = diebold_mariano_test(gjr_qlike_arr[:min_len], m_qlike_arr[:min_len])
                delta_pct = (period_results['models'][m_name]['qlike'] / period_results['models']['GJR']['qlike'] - 1) * 100
                dm_results[f'GJR_vs_{m_name}'] = {
                    'dm_stat': round(dm_stat, 4),
                    'dm_p': round(dm_p, 4),
                    'delta_qlike_pct': round(delta_pct, 4),
                    'significant_5pct': bool(dm_p < 0.05),
                }
                print(f"  DM(GJR vs {m_name}): t={dm_stat:+.3f}, p={dm_p:.4f}, ΔQLIKE={delta_pct:+.2f}%")

    # Also DM: VIX vs VIX9D directly
    if 'GJR-X(VIX)' in period_results['models'] and 'GJR-X(VIX9D)' in period_results['models']:
        vix_arr = np.array(period_results['models']['GJR-X(VIX)']['qlike_array'])
        v9d_arr = np.array(period_results['models']['GJR-X(VIX9D)']['qlike_array'])
        min_len = min(len(vix_arr), len(v9d_arr))
        dm_stat, dm_p = diebold_mariano_test(vix_arr[:min_len], v9d_arr[:min_len])
        delta_pct = (period_results['models']['GJR-X(VIX9D)']['qlike'] / period_results['models']['GJR-X(VIX)']['qlike'] - 1) * 100
        dm_results['VIX_vs_VIX9D'] = {
            'dm_stat': round(dm_stat, 4),
            'dm_p': round(dm_p, 4),
            'delta_qlike_pct': round(delta_pct, 4),
            'significant_5pct': bool(dm_p < 0.05),
        }
        print(f"  DM(VIX vs VIX9D): t={dm_stat:+.3f}, p={dm_p:.4f}, ΔQLIKE={delta_pct:+.2f}%")

    period_results['dm_tests'] = dm_results
    all_period_results[p_name] = period_results

elapsed = time.time() - t_start
print(f"\n  Total time: {elapsed:.1f}s")

# ============================================================
# 8. AGGREGATE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("[5] Aggregate Results Summary")
print("=" * 70)

# Build summary table
summary = {}
for m_name in MODEL_NAMES:
    qlikes = []
    var1_pass = 0
    var5_pass = 0
    n_periods = 0
    for pname, pres in all_period_results.items():
        if m_name in pres['models']:
            qlikes.append(pres['models'][m_name]['qlike'])
            if pres['models'][m_name]['var_1pct']['trinity_pass']:
                var1_pass += 1
            if pres['models'][m_name]['var_5pct']['trinity_pass']:
                var5_pass += 1
            n_periods += 1

    if n_periods == 0:
        continue

    mean_qlike = np.mean(qlikes)
    summary[m_name] = {
        'mean_qlike': float(mean_qlike),
        'qlikes_by_period': {pname: pres['models'][m_name]['qlike']
                            for pname, pres in all_period_results.items()
                            if m_name in pres['models']},
        'var1_trinity_pass': f"{var1_pass}/{n_periods}",
        'var5_trinity_pass': f"{var5_pass}/{n_periods}",
        'n_periods': n_periods,
    }

# Print summary
print(f"\n{'Model':25s} {'Mean QLIKE':>12s} {'VaR1% Pass':>12s} {'VaR5% Pass':>12s}")
print("─" * 65)
for m_name in MODEL_NAMES:
    if m_name in summary:
        s = summary[m_name]
        print(f"{m_name:25s} {s['mean_qlike']:12.6f} {s['var1_trinity_pass']:>12s} {s['var5_trinity_pass']:>12s}")

# Delta stability
print(f"\n{'─'*60}")
print("Delta Coefficient Stability:")
for m_name in ['GJR-X(VIX)', 'GJR-X(VIX9D)', 'GJR-X(VIX+VIX9D)']:
    deltas = model_deltas[m_name]
    if len(deltas) > 0:
        if m_name == 'GJR-X(VIX+VIX9D)':
            vix_deltas = [d[0] for d in deltas]
            v9d_deltas = [d[1] for d in deltas]
            print(f"  {m_name} δ_VIX:   mean={np.mean(vix_deltas):.4f}, std={np.std(vix_deltas):.4f}, range=[{np.min(vix_deltas):.4f}, {np.max(vix_deltas):.4f}]")
            print(f"  {m_name} δ_VIX9D: mean={np.mean(v9d_deltas):.4f}, std={np.std(v9d_deltas):.4f}, range=[{np.min(v9d_deltas):.4f}, {np.max(v9d_deltas):.4f}]")
        else:
            print(f"  {m_name}: mean={np.mean(deltas):.4f}, std={np.std(deltas):.4f}, range=[{np.min(deltas):.4f}, {np.max(deltas):.4f}], CV={np.std(deltas)/np.mean(deltas):.2f}" if np.mean(deltas) > 0 else f"  {m_name}: all zero")

# Aggregate DM: pool all OOS periods
print(f"\n{'─'*60}")
print("Pooled DM Tests (all periods combined):")
for pair in ['GJR_vs_GJR-X(VIX)', 'GJR_vs_GJR-X(VIX9D)', 'GJR_vs_GJR-X(VIX+VIX9D)', 'VIX_vs_VIX9D']:
    gjr_key = pair.split('_vs_')[0]
    other_key = pair.split('_vs_')[1]

    all_loss1 = []
    all_loss2 = []
    for pname, pres in all_period_results.items():
        if pair.startswith('VIX_vs'):
            k1, k2 = 'GJR-X(VIX)', 'GJR-X(VIX9D)'
        else:
            k1, k2 = 'GJR', other_key
        if k1 in pres['models'] and k2 in pres['models']:
            arr1 = np.array(pres['models'][k1]['qlike_array'])
            arr2 = np.array(pres['models'][k2]['qlike_array'])
            min_len = min(len(arr1), len(arr2))
            all_loss1.append(arr1[:min_len])
            all_loss2.append(arr2[:min_len])

    if len(all_loss1) > 0:
        pooled1 = np.concatenate(all_loss1)
        pooled2 = np.concatenate(all_loss2)
        dm_stat, dm_p = diebold_mariano_test(pooled1, pooled2)
        delta = (np.mean(pooled2) / np.mean(pooled1) - 1) * 100
        print(f"  {pair:40s}: DM t={dm_stat:+.3f}, p={dm_p:.4f}, ΔQLIKE={delta:+.3f}%")
        summary[f'pooled_dm_{pair}'] = {
            'dm_stat': round(dm_stat, 4),
            'dm_p': round(dm_p, 4),
            'delta_qlike_pct': round(delta, 4),
        }

# ============================================================
# 9. ANOMALY CHECK
# ============================================================
print(f"\n{'─'*60}")
print("Anomaly checks:")
# Check: is VIX9D delta on boundary?
for m_name in ['GJR-X(VIX9D)', 'GJR-X(VIX+VIX9D)']:
    for pname, pres in all_period_results.items():
        if m_name in pres['models']:
            params = pres['models'][m_name].get('params_last', {})
            for k, v in params.items():
                if 'delta' in str(k).lower() or 'Delta' in str(k):
                    if isinstance(v, (int, float)):
                        if v <= 1e-5:
                            print(f"  ⚠️ {m_name} {pname}: {k}={v:.6f} ON BOUNDARY (=0)")
                        elif v >= 0.999:
                            print(f"  ⚠️ {m_name} {pname}: {k}={v:.6f} ON BOUNDARY (=1)")

# Check persistence
for pname, pres in all_period_results.items():
    for m_name, mres in pres['models'].items():
        params = mres.get('params_last', {})
        pers = params.get('persistence', None)
        if pers is not None and pers >= 1.0:
            print(f"  ⚠️ {m_name} {pname}: persistence={pers:.4f} ≥ 1.0!")

print("\n  Anomaly check complete.")

# ============================================================
# 10. VERDICT
# ============================================================
print(f"\n{'='*70}")
print("[6] VERDICT")
print(f"{'='*70}")

if 'GJR-X(VIX)' in summary and 'GJR-X(VIX9D)' in summary:
    vix_qlike = summary['GJR-X(VIX)']['mean_qlike']
    v9d_qlike = summary['GJR-X(VIX9D)']['mean_qlike']
    # QLIKE is negative; more negative = better. Improvement = (vix - v9d) / |vix| * 100
    # If v9d_qlike < vix_qlike (more negative), VIX9D is better
    improvement_pct = (vix_qlike - v9d_qlike) / abs(vix_qlike) * 100

    if improvement_pct > 0.1:
        verdict = "VIX9D BETTER"
        detail = f"VIX9D mean QLIKE improvement +{improvement_pct:.3f}% vs VIX (lower QLIKE = better)"
    elif improvement_pct < -0.1:
        verdict = "VIX BETTER"
        detail = f"VIX mean QLIKE improvement +{-improvement_pct:.3f}% vs VIX9D (lower QLIKE = better)"
    else:
        verdict = "INDISTINGUISHABLE"
        detail = f"Difference {improvement_pct:+.3f}% within noise"

    # Check pooled DM significance
    pooled_key = 'pooled_dm_VIX_vs_VIX9D'
    if pooled_key in summary:
        dm_p = summary[pooled_key]['dm_p']
        if dm_p < 0.05:
            verdict += " (SIGNIFICANT)"
        else:
            verdict += " (NOT significant)"

    print(f"\n  VIX9D vs VIX: {verdict}")
    print(f"  Detail: {detail}")
    print(f"  VIX  mean QLIKE: {vix_qlike:.6f}")
    print(f"  VIX9D mean QLIKE: {v9d_qlike:.6f}")
    print(f"  Improvement: {improvement_pct:+.3f}%")

    # Best model overall (lowest QLIKE = best)
    best_model = min(summary.items(), key=lambda x: x[1]['mean_qlike'] if isinstance(x[1], dict) and 'mean_qlike' in x[1] else float('inf'))
    print(f"  Best model: {best_model[0]} (mean QLIKE={best_model[1]['mean_qlike']:.6f})")
else:
    verdict = "INCOMPLETE"
    detail = "Missing model results"
    print(f"  VERDICT: {verdict} — {detail}")

# ============================================================
# 11. SAVE RESULTS
# ============================================================
print(f"\n[7] Saving results...")

# Clean results for JSON serialization
def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    else:
        return obj

# Trim qlike_array from period results to save space
period_results_clean = {}
for pname, pres in all_period_results.items():
    pr = dict(pres)
    pr['models'] = {}
    for m_name, mres in pres['models'].items():
        mr = dict(mres)
        # Keep only summary stats, remove per-obs arrays
        mr.pop('qlike_array', None)
        pr['models'][m_name] = mr
    period_results_clean[pname] = pr

results = {
    'experiment_id': 'K490',
    'title': 'GJR-GARCH-X(VIX9D) vs GJR-X(VIX) Comparison',
    'hypothesis': 'VIX9D (9-day implied vol) may outperform VIX (30-day) as exogenous regressor in GARCH-X variance equation, since VIX9D has higher R² for 5d realized vol',
    'builds_on': 'K486 (GJR-X(VIX) breaks impossible triangle), K489 (VIX9D R²=0.41 for 5d vol)',
    'data_source': 'yfinance: SPY, ^VIX, ^VIX9D',
    'data_period': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'n_total': len(feat),
    'is_window': IS_WINDOW,
    'refit_interval': REFIT_INTERVAL,
    'methodology': {
        'models': MODEL_NAMES,
        'variance_equation': 'h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + δ·X²_{t-1}/252',
        'distribution': 'Student-t (MLE estimated df)',
        'estimation': 'Custom MLE via scipy L-BFGS-B (arch package for baseline GJR)',
        'evaluation': 'QLIKE (Patton 2011), DM test (HAC), VaR Trinity (Kupiec + Christoffersen + DQ)',
        'oos_periods': OOS_PERIODS,
    },
    'references': [
        'Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models',
        'Christoffersen (1998) Evaluating Interval Forecasts, International Economic Review',
        'Engle & Manganelli (2004) CAViaR: Conditional Autoregressive VaR, JBES',
        'Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE',
        'Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES',
        'K486: GJR-X(VIX) breaks impossible triangle',
        'K489: VIX term structure — VIX9D R²=0.41 for 5d vol',
    ],
    'diagnostics': diagnostics,
    'period_results': clean_for_json(period_results_clean),
    'summary': clean_for_json(summary),
    'delta_stability': {
        m: {
            'values': [float(x) if not isinstance(x, tuple) else [float(y) for y in x] for x in model_deltas[m]],
            'mean': float(np.mean([x if not isinstance(x, tuple) else x[0] for x in model_deltas[m]])) if model_deltas[m] else None,
            'std': float(np.std([x if not isinstance(x, tuple) else x[0] for x in model_deltas[m]])) if model_deltas[m] else None,
        }
        for m in ['GJR-X(VIX)', 'GJR-X(VIX9D)', 'GJR-X(VIX+VIX9D)']
    },
    'verdict': verdict if 'verdict' in dir() else 'INCOMPLETE',
    'detail': detail if 'detail' in dir() else '',
    'execution_time_seconds': round(elapsed, 1),
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

out_path = 'experiments/k490_gjrx_vix9d_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Saved to {out_path}")
print(f"\n  Done in {elapsed:.1f}s")
print(f"  VERDICT: {results['verdict']}")
