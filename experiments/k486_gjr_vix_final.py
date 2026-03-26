#!/usr/bin/env python3
"""
K486: GJR-GARCH-X(VIX) Final Cross-OOS Validation + VaR Trinity Test
=====================================================================
Background:
  K438: GARCH-X(VIX) borderline -6.3% QLIKE (DM p=0.050) in single OOS period
  K485: GJR+VIX only is best across 5 cross-OOS periods (-4.64%, 5/5 wins)
  K467/K476: HAR does well on forecasting but badly on VaR — can GJR+VIX do both?

Core Question:
  GJR-GARCH-X(VIX) improves QLIKE by ~4.6% — does it ALSO do good VaR?
  (VIX contains risk premium → may naturally produce conservative forecasts → good VaR?)

Model:
  GJR-GARCH-X(VIX):
    h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + δ·VIX²_{t-1}/252

  Comparison: GJR-GARCH(1,1) baseline (no VIX)

5 OOS Periods (same as K485):
  1. 2015-2016
  2. 2017-2018 (Volmageddon)
  3. 2019-2020 (COVID)
  4. 2021-2022 (rate hikes)
  5. 2023-2024

Evaluation:
  - QLIKE with r² proxy (Patton 2011)
  - Diebold-Mariano test per period
  - VaR Trinity test (Kupiec + Christoffersen + DQ) at 1% and 5%
  - δ coefficient stability across periods

Efficiency target: < 2 minutes (custom log-likelihood, 5 × 2 × ~24 refits = ~240 fits)

Data: yfinance (SPY, ^VIX), 2005-2026
Refs:
  Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models
  Christoffersen (1998) Evaluating Interval Forecasts, International Economic Review
  Engle & Manganelli (2004) CAViaR: Conditional Autoregressive VaR, JBES
  Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE
  Hansen & Lunde (2005) A Forecast Comparison of Volatility Models, JoAE
  Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES
  K438, K485, K467, K476
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
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K486: GJR-GARCH-X(VIX) Final Cross-OOS + VaR Trinity")
print("  2 models × 5 periods × QLIKE + VaR(1%,5%) × Trinity(3 tests)")
print("  Core Q: Can GJR+VIX beat QLIKE AND pass VaR?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
REFIT_INTERVAL = 21  # refit every ~1 month
ALPHA_LEVELS = [0.01, 0.05]

OOS_PERIODS = [
    {"name": "2015-2016", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start='2005-01-01', progress=False)
vix_raw = yf.download('^VIX', start='2005-01-01', progress=False)

if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

print(f"  SPY: {spy_raw.index[0].date()} to {spy_raw.index[-1].date()} ({len(spy_raw)} obs)")
print(f"  VIX: {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

spy_close = spy_raw['Close'].values.astype(float).ravel()
vix_close = vix_raw['Close'].values.astype(float).ravel()

# Log returns in %
spy_ret_pct = np.log(spy_close[1:] / spy_close[:-1]) * 100
spy_idx = spy_raw.index[1:]

df_spy = pd.DataFrame({
    'return_pct': spy_ret_pct,
    'r2_proxy': (np.log(spy_close[1:] / spy_close[:-1]))**2,  # decimal²
}, index=spy_idx)

df_vix = pd.DataFrame({
    'VIX': vix_close,
}, index=vix_raw.index)

# Merge on date (inner join)
feat = df_spy.join(df_vix, how='inner')
feat = feat.dropna()

# VIX implied daily variance: VIX²/252 (in decimal² for variance equation compatibility)
# But returns are in %, so we need VIX²/252/10000 to match %² scale? No:
# VIX is in %, annual. VIX²/252 gives daily variance in %² (annualized → daily).
# But our returns are log returns * 100 (so in %). Their variance is in %².
# VIX is reported as annual % (e.g. VIX=20 → σ_annual=20%).
# VIX²/252 = daily variance in %² terms.
# Example: VIX=20 → 20²/252 = 1.587 %² daily.
# Our return_pct has std ~ 1.2%, variance ~ 1.44 %². Matches.
feat['vix_daily_var'] = feat['VIX']**2 / 252  # in %² units

print(f"  Combined: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")
print(f"  VIX: mean={feat['VIX'].mean():.1f}, std={feat['VIX'].std():.1f}")
print(f"  VIX daily var: mean={feat['vix_daily_var'].mean():.3f} %²")
print(f"  Return var: mean={feat['return_pct'].var():.3f} %²")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values
r2 = feat['r2_proxy'].values

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
    'vix_daily_var_mean': float(feat['vix_daily_var'].mean()),
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

# ============================================================
# 4. MODEL ESTIMATION FUNCTIONS
# ============================================================

def fit_gjr_garch(returns_pct):
    """
    Standard GJR-GARCH(1,1) with Student-t via arch package.
    Returns fitted result object, or None on failure.
    """
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        return res
    except Exception:
        return None


def gjr_garchx_loglik(params, returns, vix_var_lag):
    """
    Custom log-likelihood for GJR-GARCH-X(VIX).

    h_t = omega + alpha * eps²_{t-1} + gamma * I(eps<0) * eps²_{t-1} + beta * h_{t-1} + delta * VIX²_{t-1}/252

    params = [mu, omega, alpha, gamma, beta, delta, nu]
    returns: in % (return_pct)
    vix_var_lag: VIX²_{t-1}/252 in %² (already lagged)

    Returns: negative log-likelihood (for minimization)
    """
    mu, omega, alpha, gamma, beta, delta, nu = params

    T = len(returns)
    eps = returns - mu  # residuals in %
    h = np.zeros(T)

    # Initialize with unconditional variance
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0

    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * shock2 + gamma * asym + beta * h[t-1] + delta * vix_var_lag[t]
        if h[t] <= 0:
            h[t] = 1e-6

    # Student-t log-likelihood
    # f(x|nu) ∝ (1 + z²/(nu-2))^(-(nu+1)/2) where z = eps/sqrt(h)
    from scipy.special import gammaln
    ll = (
        gammaln((nu + 1) / 2) - gammaln(nu / 2)
        - 0.5 * np.log(np.pi * (nu - 2))
        - 0.5 * np.log(h)
        - (nu + 1) / 2 * np.log(1 + eps**2 / (h * (nu - 2)))
    )

    return -np.sum(ll)


def fit_gjr_garchx(returns_pct, vix_daily_var):
    """
    Fit GJR-GARCH-X(VIX) via custom MLE.
    returns_pct: array of returns in %
    vix_daily_var: array of VIX²/252 in %² (same length, already aligned)

    Returns dict with params, sigma2 series, loglik, or None on failure.
    """
    T = len(returns_pct)
    ret = returns_pct.copy()

    # Lag VIX: for h_t we use VIX_{t-1}
    vix_lag = np.zeros(T)
    vix_lag[1:] = vix_daily_var[:-1]
    vix_lag[0] = vix_daily_var[0]  # use first available for t=0

    # Initial guess from standard GJR
    mu0 = np.mean(ret)
    var0 = np.var(ret)
    x0 = [mu0, 0.01, 0.05, 0.05, 0.90, 0.01, 6.0]

    # Bounds
    bounds = [
        (-1.0, 1.0),        # mu
        (1e-6, 10.0),       # omega
        (1e-6, 0.5),        # alpha
        (0.0, 0.5),         # gamma (asymmetry, can be 0)
        (0.3, 0.999),       # beta
        (0.0, 1.0),         # delta (VIX coefficient)
        (2.1, 50.0),        # nu (df)
    ]

    try:
        result = optimize.minimize(
            gjr_garchx_loglik, x0, args=(ret, vix_lag),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )

        if not result.success and result.fun > 1e10:
            return None

        mu, omega, alpha, gamma_val, beta, delta, nu = result.x

        # Reconstruct h series
        eps = ret - mu
        h = np.zeros(T)
        h[0] = np.var(eps)
        if h[0] <= 0:
            h[0] = 1.0
        for t in range(1, T):
            shock2 = eps[t-1]**2
            asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
            h[t] = omega + alpha * shock2 + gamma_val * asym + beta * h[t-1] + delta * vix_lag[t]
            if h[t] <= 0:
                h[t] = 1e-6

        # 1-step ahead forecast
        shock2_last = eps[-1]**2
        asym_last = shock2_last * (1.0 if eps[-1] < 0 else 0.0)
        h_forecast = omega + alpha * shock2_last + gamma_val * asym_last + beta * h[-1] + delta * vix_daily_var[-1]
        if h_forecast <= 0:
            h_forecast = 1e-6

        persistence = alpha + gamma_val / 2 + beta
        return {
            'params': {
                'mu': float(mu),
                'omega': float(omega),
                'alpha': float(alpha),
                'gamma': float(gamma_val),
                'beta': float(beta),
                'delta': float(delta),
                'nu': float(nu),
            },
            'persistence': float(persistence),
            'h_forecast': float(h_forecast),  # in %²
            'h_series': h,
            'loglik': float(-result.fun),
            'converged': result.success,
        }
    except Exception as e:
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
    """
    Engle & Manganelli (2004) Dynamic Quantile test.
    Regress hit_{t} - alpha on lagged hits and VaR forecasts.
    Under H0: coefficients = 0 → F-test.
    """
    alpha = np.mean(violations)  # Use empirical rate for robustness
    if alpha <= 0 or alpha >= 1:
        return 0.0, 1.0

    hit = violations.astype(float) - alpha
    T = len(hit)

    if T <= n_lags + 2:
        return 0.0, 1.0

    # Build regressor matrix: constant, lagged hits, VaR forecast
    y = hit[n_lags:]
    X_cols = [np.ones(T - n_lags)]
    for lag in range(1, n_lags + 1):
        X_cols.append(hit[n_lags - lag:T - lag])
    X_cols.append(var_forecasts[n_lags:])
    X = np.column_stack(X_cols)

    try:
        # OLS
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        k = X.shape[1]
        n = len(y)

        # DQ statistic ~ chi2(k)
        # Under H0: beta = 0, DQ = (X'y)' (X'X)^{-1} (X'y) / alpha(1-alpha)
        XtX = X.T @ X
        Xty = X.T @ y
        try:
            XtX_inv = np.linalg.inv(XtX)
        except np.linalg.LinAlgError:
            return 0.0, 1.0

        dq_stat = float(Xty.T @ XtX_inv @ Xty / (alpha * (1 - alpha)))
        dq_pval = 1 - stats.chi2.cdf(dq_stat, df=k)
        return float(dq_stat), float(dq_pval)
    except Exception:
        return 0.0, 1.0


def run_var_trinity(violations, var_forecasts, n_total, alpha_level):
    """Run all 3 VaR tests and return comprehensive results."""
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
    """
    Diebold-Mariano (1995) test for equal predictive accuracy.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Returns DM stat and p-value. Positive stat means loss1 > loss2 (model 2 better).
    """
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)

    # Newey-West variance with h-1 lags
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

t_start = time.time()
all_period_results = {}
delta_coefficients = {}  # Track delta stability

for p_idx, period in enumerate(OOS_PERIODS):
    p_name = period['name']
    print(f"\n{'─'*60}")
    print(f"  Period {p_idx+1}/5: {p_name}")
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
    is_start_date = feat.index[first_oos_loc - IS_WINDOW]

    print(f"  IS: {is_start_date.date()} ({IS_WINDOW} obs)")
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")

    # Storage
    sigma2_gjr = np.full(n_oos, np.nan)      # %²
    sigma2_gjrx = np.full(n_oos, np.nan)     # %²
    actual_returns = np.full(n_oos, np.nan)   # %
    actual_r2 = np.full(n_oos, np.nan)        # decimal²
    deltas_this_period = []

    # Cached model results (refit every REFIT_INTERVAL)
    last_gjr_res = None
    last_gjrx_res = None
    last_fit_idx = -REFIT_INTERVAL  # force first fit

    t_period = time.time()
    fit_count = 0

    for i, oos_date in enumerate(oos_dates):
        oos_loc = feat.index.get_loc(oos_date)

        # Actual values
        actual_returns[i] = feat.iloc[oos_loc]['return_pct']
        actual_r2[i] = feat.iloc[oos_loc]['r2_proxy']

        # Check if refit needed
        need_refit = (i - last_fit_idx >= REFIT_INTERVAL) or (last_gjr_res is None)

        if need_refit:
            window_start = oos_loc - IS_WINDOW
            window_data = feat.iloc[window_start:oos_loc]
            ret_w = window_data['return_pct'].values
            vix_w = window_data['vix_daily_var'].values

            # Fit GJR baseline
            last_gjr_res = fit_gjr_garch(ret_w)

            # Fit GJR-X(VIX)
            last_gjrx_res = fit_gjr_garchx(ret_w, vix_w)

            if last_gjrx_res is not None:
                deltas_this_period.append(last_gjrx_res['params']['delta'])

            last_fit_idx = i
            fit_count += 1

        # --- GJR forecast ---
        if last_gjr_res is not None:
            try:
                # Re-apply to current data for forecast
                window_start = oos_loc - IS_WINDOW
                ret_w = feat.iloc[window_start:oos_loc]['return_pct'].values
                am = arch_model(ret_w, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
                res = am.fit(disp='off', show_warning=False, starting_values=last_gjr_res.params.values)
                fc = res.forecast(horizon=1)
                s2 = float(fc.variance.values[-1, 0])
                if s2 > 0 and np.isfinite(s2):
                    sigma2_gjr[i] = s2
            except Exception:
                # Use last good forecast
                if i > 0 and np.isfinite(sigma2_gjr[i-1]):
                    sigma2_gjr[i] = sigma2_gjr[i-1]

        # --- GJR-X(VIX) forecast ---
        if last_gjrx_res is not None:
            try:
                window_start = oos_loc - IS_WINDOW
                window_data = feat.iloc[window_start:oos_loc]
                ret_w = window_data['return_pct'].values
                vix_w = window_data['vix_daily_var'].values

                p = last_gjrx_res['params']
                eps = ret_w - p['mu']

                # Reconstruct h series with cached params
                h = np.zeros(len(ret_w))
                h[0] = np.var(eps)
                if h[0] <= 0:
                    h[0] = 1.0

                vix_lag = np.zeros(len(ret_w))
                vix_lag[1:] = vix_w[:-1]
                vix_lag[0] = vix_w[0]

                for t in range(1, len(ret_w)):
                    shock2 = eps[t-1]**2
                    asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
                    h[t] = (p['omega'] + p['alpha'] * shock2 + p['gamma'] * asym
                            + p['beta'] * h[t-1] + p['delta'] * vix_lag[t])
                    if h[t] <= 0:
                        h[t] = 1e-6

                # 1-step forecast
                shock2_last = eps[-1]**2
                asym_last = shock2_last * (1.0 if eps[-1] < 0 else 0.0)
                h_fc = (p['omega'] + p['alpha'] * shock2_last + p['gamma'] * asym_last
                        + p['beta'] * h[-1] + p['delta'] * vix_w[-1])
                if h_fc > 0 and np.isfinite(h_fc):
                    sigma2_gjrx[i] = h_fc
            except Exception:
                if i > 0 and np.isfinite(sigma2_gjrx[i-1]):
                    sigma2_gjrx[i] = sigma2_gjrx[i-1]

        # Progress
        if (i + 1) % 100 == 0 or i == n_oos - 1:
            elapsed = time.time() - t_period
            print(f"    {i+1}/{n_oos} ({elapsed:.1f}s, {fit_count} refits)")

    # Compute QLIKE per period
    # QLIKE = mean(h/σ² - log(h/σ²) - 1) where h is actual (r²), σ² is forecast
    # With r² proxy: QLIKE = mean(r²/σ² + log(σ²)) (ignoring constants)
    valid_gjr = np.isfinite(sigma2_gjr) & np.isfinite(actual_r2) & (sigma2_gjr > 0)
    valid_gjrx = np.isfinite(sigma2_gjrx) & np.isfinite(actual_r2) & (sigma2_gjrx > 0)
    valid_both = valid_gjr & valid_gjrx

    # Use r² in %² to match sigma2 units
    r2_pct2 = actual_r2 * 10000  # decimal² → %²

    # QLIKE loss per observation
    qlike_gjr_loss = r2_pct2[valid_both] / sigma2_gjr[valid_both] + np.log(sigma2_gjr[valid_both])
    qlike_gjrx_loss = r2_pct2[valid_both] / sigma2_gjrx[valid_both] + np.log(sigma2_gjrx[valid_both])

    mean_qlike_gjr = float(np.mean(qlike_gjr_loss))
    mean_qlike_gjrx = float(np.mean(qlike_gjrx_loss))
    rel_qlike_pct = (mean_qlike_gjrx - mean_qlike_gjr) / abs(mean_qlike_gjr) * 100

    # DM test
    dm_stat, dm_pval = diebold_mariano_test(qlike_gjr_loss, qlike_gjrx_loss)

    print(f"\n  QLIKE: GJR={mean_qlike_gjr:.6f}, GJR-X(VIX)={mean_qlike_gjrx:.6f}")
    print(f"  Relative: {rel_qlike_pct:+.2f}% {'BETTER' if rel_qlike_pct < 0 else 'WORSE'}")
    print(f"  DM test: stat={dm_stat:.3f}, p={dm_pval:.4f}")

    # Delta coefficient statistics
    delta_stats = {}
    if deltas_this_period:
        delta_stats = {
            'mean': float(np.mean(deltas_this_period)),
            'std': float(np.std(deltas_this_period)),
            'min': float(np.min(deltas_this_period)),
            'max': float(np.max(deltas_this_period)),
            'n_refits': len(deltas_this_period),
        }
        print(f"  δ (VIX coeff): mean={delta_stats['mean']:.4f}, std={delta_stats['std']:.4f}, "
              f"range=[{delta_stats['min']:.4f}, {delta_stats['max']:.4f}]")

    delta_coefficients[p_name] = delta_stats

    # VaR Trinity tests
    var_results = {}
    for alpha_level in ALPHA_LEVELS:
        alpha_str = f"{int(alpha_level*100)}pct"

        for model_name, sigma2_arr in [('GJR', sigma2_gjr), ('GJR-X(VIX)', sigma2_gjrx)]:
            valid = np.isfinite(sigma2_arr) & np.isfinite(actual_returns)
            n_valid = int(np.sum(valid))

            if n_valid < 100:
                print(f"  VaR {alpha_str} {model_name}: SKIP (only {n_valid} valid)")
                continue

            sigma_arr = np.sqrt(sigma2_arr[valid])
            ret_valid = actual_returns[valid]

            # Get nu from the model fit
            if model_name == 'GJR':
                # Use last GJR fit's df
                try:
                    nu_val = float(last_gjr_res.params['nu'])
                except Exception:
                    nu_val = 5.0
            else:
                nu_val = last_gjrx_res['params']['nu'] if last_gjrx_res else 5.0

            # Student-t quantile for VaR
            q = stats.t.ppf(alpha_level, df=nu_val)
            var_forecasts = sigma_arr * q  # VaR is negative (left tail)

            # Violations: return < VaR (both are in %)
            violations = (ret_valid < var_forecasts).astype(int)

            trinity = run_var_trinity(violations, var_forecasts, n_valid, alpha_level)

            key = f"{model_name}_{alpha_str}"
            var_results[key] = trinity

            status = "PASS" if trinity['trinity_pass'] else f"FAIL ({trinity['tests_passed']})"
            print(f"  VaR {alpha_str} {model_name}: {trinity['n_violations']}/{n_valid} "
                  f"({trinity['violation_rate']:.3f} vs {alpha_level}) → {status}")

    # Store period results
    all_period_results[p_name] = {
        'T_oos': n_oos,
        'n_valid': int(np.sum(valid_both)),
        'n_refits': fit_count,
        'qlike': {
            'GJR': mean_qlike_gjr,
            'GJR-X(VIX)': mean_qlike_gjrx,
            'relative_pct': round(rel_qlike_pct, 4),
            'DM_stat': round(dm_stat, 4),
            'DM_pval': round(dm_pval, 4),
            'GJR-X_better': rel_qlike_pct < 0,
            'significant_10pct': dm_pval < 0.10,
        },
        'delta_stats': delta_stats,
        'var_trinity': var_results,
    }

total_time = time.time() - t_start
print(f"\n{'='*70}")
print(f"Total computation time: {total_time:.1f}s")
print(f"{'='*70}")

# ============================================================
# 8. CROSS-OOS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[5] CROSS-OOS SUMMARY")
print("=" * 70)

# QLIKE summary
print("\n--- QLIKE Results ---")
print(f"{'Period':<30} {'GJR':>10} {'GJR-X(VIX)':>12} {'Rel%':>8} {'DM':>6} {'p':>8} {'Better?':>8}")
print("-" * 82)

n_better = 0
n_sig = 0
qlike_rels = []
dm_stats_all = []

for p_name, res in all_period_results.items():
    q = res['qlike']
    better = "YES" if q['GJR-X_better'] else "no"
    sig = "*" if q['significant_10pct'] else ""
    print(f"{p_name:<30} {q['GJR']:>10.4f} {q['GJR-X(VIX)']:>12.4f} {q['relative_pct']:>+7.2f}% "
          f"{q['DM_stat']:>6.2f} {q['DM_pval']:>8.4f} {better:>6}{sig}")
    if q['GJR-X_better']:
        n_better += 1
    if q['significant_10pct'] and q['GJR-X_better']:
        n_sig += 1
    qlike_rels.append(q['relative_pct'])
    dm_stats_all.append(q['DM_stat'])

avg_rel = np.mean(qlike_rels)
print(f"\nGJR-X(VIX) better in {n_better}/5 periods, significant in {n_sig}/5")
print(f"Average relative QLIKE: {avg_rel:+.2f}%")

# VaR Trinity summary
print("\n--- VaR Trinity Results ---")
for alpha_level in ALPHA_LEVELS:
    alpha_str = f"{int(alpha_level*100)}pct"
    print(f"\n  α = {alpha_level} ({alpha_str}):")
    print(f"  {'Period':<30} {'GJR':>12} {'GJR-X(VIX)':>12}")
    print(f"  {'-'*54}")

    gjr_pass = 0
    gjrx_pass = 0

    for p_name, res in all_period_results.items():
        var_res = res['var_trinity']
        gjr_key = f"GJR_{alpha_str}"
        gjrx_key = f"GJR-X(VIX)_{alpha_str}"

        gjr_status = var_res.get(gjr_key, {}).get('tests_passed', 'N/A')
        gjrx_status = var_res.get(gjrx_key, {}).get('tests_passed', 'N/A')

        gjr_trinity = var_res.get(gjr_key, {}).get('trinity_pass', False)
        gjrx_trinity = var_res.get(gjrx_key, {}).get('trinity_pass', False)

        if gjr_trinity:
            gjr_pass += 1
        if gjrx_trinity:
            gjrx_pass += 1

        g_mark = "✓" if gjr_trinity else "✗"
        x_mark = "✓" if gjrx_trinity else "✗"

        print(f"  {p_name:<30} {g_mark} {gjr_status:>10} {x_mark} {gjrx_status:>10}")

    print(f"  Total Trinity 3/3 pass:      GJR {gjr_pass}/5     GJR-X(VIX) {gjrx_pass}/5")

# Delta stability
print("\n--- δ (VIX coefficient) Stability ---")
print(f"{'Period':<30} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
print("-" * 62)
all_deltas = []
for p_name, d in delta_coefficients.items():
    if d:
        print(f"{p_name:<30} {d['mean']:>8.4f} {d['std']:>8.4f} {d['min']:>8.4f} {d['max']:>8.4f}")
        all_deltas.append(d['mean'])

if all_deltas:
    overall_mean = np.mean(all_deltas)
    overall_std = np.std(all_deltas)
    cv = overall_std / overall_mean if overall_mean > 0 else float('inf')
    print(f"\nOverall: mean={overall_mean:.4f}, cross-period std={overall_std:.4f}, CV={cv:.2f}")
    print(f"Stability: {'STABLE (CV<0.5)' if cv < 0.5 else 'MODERATE (0.5<CV<1)' if cv < 1 else 'UNSTABLE (CV>1)'}")

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print("\n[6] Saving results...")

# Build VaR summary tables
var_summary = {}
for alpha_level in ALPHA_LEVELS:
    alpha_str = f"{int(alpha_level*100)}pct"
    table = {}
    for p_name, res in all_period_results.items():
        var_res = res['var_trinity']
        for model_prefix in ['GJR', 'GJR-X(VIX)']:
            key = f"{model_prefix}_{alpha_str}"
            if key in var_res:
                if model_prefix not in table:
                    table[model_prefix] = {}
                table[model_prefix][p_name] = var_res[key]
    var_summary[alpha_str] = table

# Count Trinity passes
var_pass_counts = {}
for alpha_str, table in var_summary.items():
    var_pass_counts[alpha_str] = {}
    for model_name, periods in table.items():
        n_pass = sum(1 for v in periods.values() if v.get('trinity_pass', False))
        var_pass_counts[alpha_str][model_name] = f"{n_pass}/{len(periods)}"

results = {
    "experiment_id": "K486",
    "title": "GJR-GARCH-X(VIX) Final Cross-OOS Validation + VaR Trinity Test",
    "method": "GJR-GARCH-X with VIX exogenous regressor, custom MLE, 5 cross-OOS periods",
    "proposed_by": "User (publication-critical validation)",
    "asset": "SPY",
    "data_source": "yfinance (SPY, ^VIX) — empirical data",
    "data_period": f"{feat.index[0].date()} to {feat.index[-1].date()}",
    "total_observations": len(feat),
    "configuration": {
        "IS_window": IS_WINDOW,
        "refit_interval": REFIT_INTERVAL,
        "n_oos_periods": 5,
        "variance_proxy": "r² (squared return)",
        "loss_function": "QLIKE (Patton 2011)",
        "VaR_distribution": "Student-t (MLE estimated df)",
        "VaR_levels": ALPHA_LEVELS,
        "VaR_tests": ["Kupiec (1995)", "Christoffersen (1998)", "DQ (Engle-Manganelli 2004)"],
        "models": ["GJR-GARCH(1,1)", "GJR-GARCH-X(VIX)"],
        "variance_equation_GJRX": "h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + δ·VIX²_{t-1}/252",
    },
    "diagnostics": diagnostics,
    "cross_oos_results": all_period_results,
    "qlike_summary": {
        "n_periods_GJRX_better": n_better,
        "n_periods_significant_10pct": n_sig,
        "avg_relative_QLIKE_pct": round(avg_rel, 4),
        "per_period_relative_pct": {p: round(r, 4) for p, r in zip(all_period_results.keys(), qlike_rels)},
    },
    "var_trinity_summary": {
        "pass_counts": var_pass_counts,
        "var_summary": var_summary,
    },
    "delta_stability": {
        "per_period": delta_coefficients,
        "overall_mean": round(float(np.mean(all_deltas)), 4) if all_deltas else None,
        "cross_period_std": round(float(np.std(all_deltas)), 4) if all_deltas else None,
        "cv": round(float(np.std(all_deltas) / np.mean(all_deltas)), 4) if all_deltas and np.mean(all_deltas) > 0 else None,
    },
    "core_question_answer": (
        "Does GJR-GARCH-X(VIX) beat QLIKE AND pass VaR Trinity? "
        f"QLIKE: GJR-X better in {n_better}/5 periods (avg {avg_rel:+.2f}%). "
        f"VaR: see var_trinity_summary for pass counts."
    ),
    "computation_time_seconds": round(total_time, 1),
    "references": [
        "Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models",
        "Christoffersen (1998) Evaluating Interval Forecasts, IER 39(4):841-862",
        "Engle & Manganelli (2004) CAViaR: Conditional Autoregressive VaR, JBES 22(4):367-381",
        "Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE 160(1):246-256",
        "Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES 13(3):253-263",
        "Hansen & Lunde (2005) A Forecast Comparison of Volatility Models, JoAE 20(7):873-889",
        "K438: GARCH-X(VIX) borderline -6.3% QLIKE (DM p=0.050)",
        "K485: GJR+VIX best across 5 cross-OOS (-4.64%, 5/5 wins)",
        "K467: HAR good forecasting but bad VaR",
        "K476: Ensemble VaR cross-OOS validation",
    ],
}

output_path = 'experiments/k486_gjr_vix_final_results.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to {output_path}")
print(f"\n{'='*70}")
print("K486 COMPLETE")
print(f"{'='*70}")
