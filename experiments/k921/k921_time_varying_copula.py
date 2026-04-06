#!/usr/bin/env python3
"""
K921: Time-Varying Copula -- Dynamic Tail Dependence as Crisis Early Warning

Question: Does the SPY-GLD tail dependence coefficient change *before*
crises begin, potentially serving as an early warning signal?

Method:
  1. GJR-GARCH(1,1) Student-t marginals for SPY and GLD (same as K920)
  2. PIT to uniform residuals
  3. Patton (2006) time-varying Student-t copula:
     rho_t = Lambda(omega + beta*rho_{t-1} + alpha*(1/M)*sum Phi^-1(u1)*Phi^-1(u2))
     Lambda(x) = (1-exp(-x))/(1+exp(-x)) keeps rho in (-1,1)
  4. Compute time-varying lambda_t from rho_t and fixed nu
  5. Crisis early warning analysis:
     - lambda_t behavior 60 days before GFC/COVID/Rate Hike
     - Granger causality lambda -> VIX
     - Lambda regime detection with rolling bands
  6. Compare time-varying vs static copula (AIC, VaR IS+OOS)

Data: SPY, GLD daily from yfinance, 2005-01-01 to 2026-04-04
IS: 2005-2019, OOS: 2019-2026

References:
  - Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER 47(2):527-556
  - Joe (1997): Multivariate Models and Dependence Concepts
  - K920: Copula-GARCH Tail Dependence (prior experiment)

Error log rules:
  - Fixed seed np.random.seed(42)
  - VaR/ES reported IS and OOS separately
  - signal.shift(1) for any strategy signals

Author: VolPred Research System
"""

import json
import os
import sys
import warnings
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats as sp_stats
from scipy.optimize import minimize
from scipy.special import gammaln

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'GLD']
START_DATE = '2005-01-01'
END_DATE = '2026-04-04'
OOS_START = '2019-01-01'
M_FORCING = 10  # Patton (2006) forcing variable window
N_SIM = 10000   # Monte Carlo draws for VaR
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Crisis periods (for analysis)
CRISES = {
    'GFC_2008': ('2008-09-15', '2009-03-09'),      # Lehman to market bottom
    'COVID_2020': ('2020-02-20', '2020-03-23'),      # COVID crash
    'Rate_Hike_2022': ('2022-01-03', '2022-10-12'),  # Rate hike drawdown
}

# Pre-crisis windows (60 trading days before crisis start)
PRE_CRISIS_DAYS = 60


# ============================================================
# Step 1: Data Collection
# ============================================================
def fetch_data():
    """Fetch daily prices for SPY, GLD, VIX from yfinance."""
    import yfinance as yf

    tickers = ASSETS + ['^VIX']
    data = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

    if isinstance(data.columns, pd.MultiIndex):
        prices = data['Close']
    else:
        prices = data[['Close']]

    if '^VIX' in prices.columns:
        prices = prices.rename(columns={'^VIX': 'VIX'})

    prices = prices.dropna()
    print(f"Data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices)} days")
    return prices


# ============================================================
# Step 2: GJR-GARCH Marginal Models (same as K920)
# ============================================================
def fit_gjr_garch(returns_series, asset_name):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
    r = returns_series * 100  # percentage

    am = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
    res = am.fit(disp='off', options={'maxiter': 5000})

    cond_vol = res.conditional_volatility / 100
    std_resid = res.std_resid

    nu = res.params.get('nu', 30.0)

    persistence = (res.params.get('alpha[1]', 0)
                   + res.params.get('gamma[1]', 0) / 2
                   + res.params.get('beta[1]', 0))

    print(f"\n{asset_name} GJR-GARCH(1,1):")
    print(f"  omega={res.params.get('omega', 0):.6f}, "
          f"alpha={res.params.get('alpha[1]', 0):.6f}, "
          f"gamma={res.params.get('gamma[1]', 0):.6f}, "
          f"beta={res.params.get('beta[1]', 0):.6f}")
    print(f"  nu (df)={nu:.2f}, persistence={persistence:.4f}")
    print(f"  Converged: {res.convergence_flag == 0}")

    return res, cond_vol, std_resid, nu


def probability_integral_transform(std_resid, nu):
    """Apply PIT using Student-t CDF to get uniform (0,1) variates."""
    u = sp_stats.t.cdf(std_resid, df=nu)
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return u


# ============================================================
# Step 3: Static Student-t Copula (baseline, same as K920)
# ============================================================
def student_t_copula_ll(params, u1, u2):
    """Student-t copula negative log-likelihood."""
    rho = np.tanh(params[0])
    nu = np.exp(params[1]) + 2.01  # df > 2

    x1 = sp_stats.t.ppf(u1, df=nu)
    x2 = sp_stats.t.ppf(u2, df=nu)
    n = len(u1)

    det = 1 - rho**2
    if det <= 0:
        return 1e10

    ll = n * (gammaln((nu + 2) / 2) - gammaln(nu / 2)
              - np.log(nu * np.pi) - 0.5 * np.log(det))

    ll -= n * 2 * (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                   - 0.5 * np.log(nu * np.pi))

    Q = (x1**2 + x2**2 - 2 * rho * x1 * x2) / det
    ll -= ((nu + 2) / 2) * np.sum(np.log(1 + Q / nu))

    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x1**2 / nu))
    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x2**2 / nu))

    return -ll


def fit_static_copula(u1, u2):
    """Fit static Student-t copula. Returns rho, nu, log-lik, AIC, BIC."""
    n = len(u1)
    res = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1, u2),
                   method='Nelder-Mead', options={'maxiter': 10000})
    rho = np.tanh(res.x[0])
    nu = np.exp(res.x[1]) + 2.01
    ll = -res.fun
    k = 2
    aic = -2 * ll + 2 * k
    bic = -2 * ll + k * np.log(n)

    # Tail dependence
    if nu < 100:
        lam = 2 * sp_stats.t.cdf(
            -np.sqrt((nu + 1) * (1 - rho) / (1 + rho)), df=nu + 1
        )
    else:
        lam = 0.0

    return {
        'rho': float(rho),
        'nu': float(nu),
        'log_likelihood': float(ll),
        'AIC': float(aic),
        'BIC': float(bic),
        'lambda': float(lam),
        'converged': res.success or res.fun < 1e9
    }


# ============================================================
# Step 4: Patton (2006) Time-Varying Student-t Copula
# ============================================================
def modified_logistic(x):
    """
    Lambda(x) = (1 - exp(-x)) / (1 + exp(-x))
    Maps R -> (-1, 1). This is tanh(x/2) essentially.
    For numerical stability, use np.tanh.
    """
    # Lambda(x) = tanh(x/2) exactly
    return np.tanh(x / 2)


def tv_copula_filter(omega, beta, alpha, nu, u1, u2, M=10):
    """
    Filter time-varying rho_t using Patton (2006) evolution equation:
      rho_t = Lambda(omega + beta * rho_{t-1} + alpha * (1/M) * sum_{j=1}^{M} z1_{t-j} * z2_{t-j})
    where z_i = Phi^{-1}(u_i) (standard normal quantile)

    Returns: rho_t array, total log-likelihood
    """
    T = len(u1)
    z1 = sp_stats.norm.ppf(u1)
    z2 = sp_stats.norm.ppf(u2)

    # Pre-compute t-quantiles for copula density
    x1 = sp_stats.t.ppf(u1, df=nu)
    x2 = sp_stats.t.ppf(u2, df=nu)

    rho_t = np.zeros(T)
    ll_t = np.zeros(T)

    # Initialize rho_0 using unconditional (sample correlation of z's)
    rho_t[0] = modified_logistic(omega)

    # Pre-compute rolling forcing variable: (1/M) * sum_{j=1}^{M} z1_{t-j} * z2_{t-j}
    z_product = z1 * z2

    # Constants for Student-t copula density
    const1 = gammaln((nu + 2) / 2) - gammaln(nu / 2) - np.log(nu * np.pi)
    const2 = 2 * (gammaln((nu + 1) / 2) - gammaln(nu / 2) - 0.5 * np.log(nu * np.pi))

    for t in range(T):
        rho = rho_t[t]
        det = 1 - rho**2

        if det <= 1e-10:
            ll_t[t] = -1e5
        else:
            # Student-t copula log-density at time t
            Q = (x1[t]**2 + x2[t]**2 - 2 * rho * x1[t] * x2[t]) / det
            ll_t[t] = (const1 - 0.5 * np.log(det)
                       - const2
                       - ((nu + 2) / 2) * np.log(1 + Q / nu)
                       + ((nu + 1) / 2) * np.log(1 + x1[t]**2 / nu)
                       + ((nu + 1) / 2) * np.log(1 + x2[t]**2 / nu))

        # Update rho for next period
        if t < T - 1:
            # Forcing variable: average of last M products
            if t >= M:
                forcing = np.mean(z_product[t - M:t])
            elif t > 0:
                forcing = np.mean(z_product[:t])
            else:
                forcing = 0.0

            rho_t[t + 1] = modified_logistic(omega + beta * rho_t[t] + alpha * forcing)

    total_ll = np.sum(ll_t[M:])  # skip first M obs for forcing variable warmup
    return rho_t, total_ll, ll_t


def tv_copula_nll(params, u1, u2, nu, M=10):
    """Negative log-likelihood for time-varying copula optimization."""
    omega, beta, alpha = params

    # Stability check
    if abs(beta) > 50 or abs(omega) > 50 or abs(alpha) > 50:
        return 1e10

    try:
        _, total_ll, _ = tv_copula_filter(omega, beta, alpha, nu, u1, u2, M)
    except Exception:
        return 1e10

    if not np.isfinite(total_ll):
        return 1e10

    return -total_ll


def fit_tv_copula(u1, u2, nu_fixed, M=10):
    """
    Fit Patton (2006) time-varying Student-t copula.
    Fix nu from static copula, estimate omega, beta, alpha.
    """
    print("\n  Fitting time-varying Student-t copula (Patton 2006)...")

    # Try multiple starting points
    best_result = None
    best_nll = np.inf

    starts = [
        [0.0, 0.9, 0.05],     # high persistence
        [0.0, 0.5, 0.1],      # moderate
        [0.1, 0.95, 0.01],    # very persistent
        [-0.1, 0.8, 0.1],     # negative intercept
        [0.0, 0.0, 0.0],      # no dynamics (check)
    ]

    for x0 in starts:
        try:
            res = minimize(tv_copula_nll, x0=x0, args=(u1, u2, nu_fixed, M),
                           method='Nelder-Mead',
                           options={'maxiter': 20000, 'xatol': 1e-8, 'fatol': 1e-8})
            if res.fun < best_nll:
                best_nll = res.fun
                best_result = res
        except Exception:
            continue

    if best_result is None:
        raise ValueError("Time-varying copula optimization failed for all starts")

    omega, beta, alpha = best_result.x
    rho_t, total_ll, ll_t = tv_copula_filter(omega, beta, alpha, nu_fixed, u1, u2, M)

    n_eff = len(u1) - M  # effective sample size
    k = 3  # omega, beta, alpha (nu fixed from static)
    aic = -2 * total_ll + 2 * k
    bic = -2 * total_ll + k * np.log(n_eff)

    print(f"  omega={omega:.4f}, beta={beta:.4f}, alpha={alpha:.4f}")
    print(f"  nu (fixed)={nu_fixed:.2f}")
    print(f"  Log-lik={total_ll:.2f}, AIC={aic:.2f}, BIC={bic:.2f}")
    print(f"  rho_t: mean={np.mean(rho_t):.4f}, std={np.std(rho_t):.4f}, "
          f"min={np.min(rho_t):.4f}, max={np.max(rho_t):.4f}")

    return {
        'omega': float(omega),
        'beta': float(beta),
        'alpha': float(alpha),
        'nu': float(nu_fixed),
        'log_likelihood': float(total_ll),
        'AIC': float(aic),
        'BIC': float(bic),
        'converged': best_result.success or best_nll < 1e9,
        'rho_t': rho_t,
        'll_t': ll_t
    }


# ============================================================
# Step 5: Compute Time-Varying Tail Dependence
# ============================================================
def compute_lambda_t(rho_t, nu):
    """
    Compute time-varying symmetric tail dependence from rho_t and nu:
    lambda_t = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho_t)/(1+rho_t)))
    """
    lambda_t = np.zeros_like(rho_t)
    for i in range(len(rho_t)):
        rho = rho_t[i]
        if abs(rho) >= 1.0:
            rho = np.sign(rho) * 0.9999
        arg = -np.sqrt((nu + 1) * (1 - rho) / (1 + rho))
        lambda_t[i] = 2 * sp_stats.t.cdf(arg, df=nu + 1)
    return lambda_t


# ============================================================
# Step 6: Granger Causality Test
# ============================================================
def granger_causality_test(x, y, max_lag=5):
    """
    Test if x Granger-causes y.
    Returns F-stat and p-value for best lag.

    Uses OLS regression:
    Restricted: y_t = c + sum(b_j * y_{t-j})
    Unrestricted: y_t = c + sum(b_j * y_{t-j}) + sum(g_j * x_{t-j})
    """
    from numpy.linalg import lstsq

    results = []
    for lag in range(1, max_lag + 1):
        T = len(y) - lag
        Y = y[lag:]

        # Restricted model: only lags of y
        X_r = np.column_stack([np.ones(T)] + [y[lag - j:lag - j + T] for j in range(1, lag + 1)])
        beta_r, res_r, _, _ = lstsq(X_r, Y, rcond=None)
        sse_r = np.sum((Y - X_r @ beta_r)**2)

        # Unrestricted model: lags of y + lags of x
        X_u = np.column_stack([X_r] + [x[lag - j:lag - j + T] for j in range(1, lag + 1)])
        beta_u, res_u, _, _ = lstsq(X_u, Y, rcond=None)
        sse_u = np.sum((Y - X_u @ beta_u)**2)

        # F-test
        q = lag  # number of restrictions
        k_u = X_u.shape[1]
        F_stat = ((sse_r - sse_u) / q) / (sse_u / (T - k_u))
        p_value = 1 - sp_stats.f.cdf(F_stat, q, T - k_u)

        results.append({
            'lag': lag,
            'F_stat': float(F_stat),
            'p_value': float(p_value),
            'sse_restricted': float(sse_r),
            'sse_unrestricted': float(sse_u)
        })

    # Best lag by lowest p-value
    best = min(results, key=lambda x: x['p_value'])
    return results, best


# ============================================================
# Step 7: VaR/ES Computation and Backtesting
# ============================================================
def compute_portfolio_var_es(cond_vol_spy, cond_vol_gld, rho_t, nu,
                              weights=(0.5, 0.5), alpha_levels=(0.01, 0.05),
                              n_sim=10000):
    """
    Compute portfolio VaR and ES using time-varying copula parameters.
    For each day, simulate from Student-t copula with rho_t[t] and fixed nu.
    """
    T = len(rho_t)
    var_results = {f'VaR_{int(a*100)}pct': np.zeros(T) for a in alpha_levels}
    es_results = {f'ES_{int(a*100)}pct': np.zeros(T) for a in alpha_levels}

    w1, w2 = weights

    for t in range(T):
        rho = rho_t[t]
        sig1 = cond_vol_spy.iloc[t] if hasattr(cond_vol_spy, 'iloc') else cond_vol_spy[t]
        sig2 = cond_vol_gld.iloc[t] if hasattr(cond_vol_gld, 'iloc') else cond_vol_gld[t]

        # Simulate from bivariate Student-t with correlation rho
        # Method: Cholesky of [[1, rho], [rho, 1]] on standard normal, then scale by chi2
        L = np.array([[1, 0], [rho, np.sqrt(max(1 - rho**2, 1e-10))]])
        Z = np.random.randn(n_sim, 2)
        chi2 = np.random.chisquare(nu, size=n_sim)
        T_draws = Z @ L.T * np.sqrt(nu / chi2)[:, None]

        # Scale to returns
        r1_sim = T_draws[:, 0] * sig1
        r2_sim = T_draws[:, 1] * sig2
        port_sim = w1 * r1_sim + w2 * r2_sim

        for a in alpha_levels:
            key_var = f'VaR_{int(a*100)}pct'
            key_es = f'ES_{int(a*100)}pct'
            var_val = np.percentile(port_sim, a * 100)
            var_results[key_var][t] = var_val
            es_results[key_es][t] = np.mean(port_sim[port_sim <= var_val])

    return var_results, es_results


def kupiec_test(violations, n, alpha):
    """Kupiec (1995) POF test."""
    v = np.sum(violations)
    if v == 0 or v == n:
        return {'stat': 0, 'p_value': 1.0, 'n_violations': int(v), 'violation_rate': float(v / n)}
    pi_hat = v / n
    lr = 2 * (v * np.log(pi_hat / alpha) + (n - v) * np.log((1 - pi_hat) / (1 - alpha)))
    p_value = 1 - sp_stats.chi2.cdf(lr, 1)
    return {
        'stat': round(float(lr), 4),
        'p_value': round(float(p_value), 4),
        'n_violations': int(v),
        'violation_rate': round(float(pi_hat), 4)
    }


def christoffersen_test(violations):
    """Christoffersen (1998) independence test."""
    n = len(violations)
    v = violations.astype(int)

    # Transition counts
    n00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    n01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    n10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    n11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

    n0 = n00 + n01
    n1 = n10 + n11

    if n0 == 0 or n1 == 0 or (n01 + n11) == 0:
        return {'stat': 0.0, 'p_value': 1.0}

    pi01 = n01 / n0 if n0 > 0 else 0
    pi11 = n11 / n1 if n1 > 0 else 0
    pi = (n01 + n11) / (n0 + n1)

    if pi == 0 or pi == 1 or pi01 == 0 or pi11 == 0:
        return {'stat': 0.0, 'p_value': 1.0}
    if pi01 == 1 or pi11 == 1:
        return {'stat': 0.0, 'p_value': 1.0}

    try:
        lr = 2 * (n00 * np.log((1 - pi01) / (1 - pi))
                  + n01 * np.log(pi01 / pi)
                  + n10 * np.log((1 - pi11) / (1 - pi))
                  + n11 * np.log(pi11 / pi))
        p_value = 1 - sp_stats.chi2.cdf(lr, 1)
    except (ValueError, FloatingPointError):
        return {'stat': 0.0, 'p_value': 1.0}

    return {'stat': round(float(lr), 4), 'p_value': round(float(p_value), 4)}


def basel_traffic_light(violation_rate, alpha):
    """Basel traffic light classification."""
    if alpha == 0.01:
        if violation_rate <= 0.015:
            return "Green"
        elif violation_rate <= 0.02:
            return "Yellow"
        else:
            return "Red"
    elif alpha == 0.05:
        if violation_rate <= 0.065:
            return "Green"
        elif violation_rate <= 0.075:
            return "Yellow"
        else:
            return "Red"
    return "Unknown"


def backtest_var(portfolio_returns, var_series, alpha):
    """Full VaR backtest: Kupiec + Christoffersen + Basel."""
    violations = (portfolio_returns < var_series).astype(int)
    n = len(portfolio_returns)

    kup = kupiec_test(violations, n, alpha)
    cc = christoffersen_test(violations)
    btl = basel_traffic_light(kup['violation_rate'], alpha)

    return {
        'alpha': alpha,
        'n_obs': n,
        'kupiec': kup,
        'christoffersen': cc,
        'basel_traffic_light': btl,
        'violation_rate': kup['violation_rate'],
        'expected_rate': alpha
    }


# ============================================================
# Step 8: Descriptive Statistics
# ============================================================
def descriptive_stats(returns, name):
    """Compute descriptive statistics for a return series."""
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch

    r = returns.dropna()
    n = len(r)
    adf = adfuller(r, maxlag=20)
    arch_lm = het_arch(r, nlags=10)

    return {
        'name': name,
        'n_obs': int(n),
        'mean': round(float(r.mean()), 6),
        'std': round(float(r.std()), 6),
        'skew': round(float(r.skew()), 4),
        'kurtosis': round(float(r.kurtosis()), 4),
        'min': round(float(r.min()), 6),
        'max': round(float(r.max()), 6),
        'adf_stat': round(float(adf[0]), 4),
        'adf_pval': round(float(adf[1]), 4),
        'arch_lm_stat': round(float(arch_lm[0]), 4),
        'arch_lm_pval': round(float(arch_lm[1]), 6),
    }


# ============================================================
# Step 9: Plotting
# ============================================================
def plot_dynamic_lambda(dates, lambda_t, rho_t, crises_dict, output_path):
    """Plot time-varying lambda_t with crisis markers."""
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

    # Panel 1: Time-varying rho_t
    ax1 = axes[0]
    ax1.plot(dates, rho_t, color='steelblue', linewidth=0.5, alpha=0.7)
    # Rolling mean
    rho_rolling = pd.Series(rho_t, index=dates).rolling(60).mean()
    ax1.plot(dates, rho_rolling, color='navy', linewidth=1.5, label='60-day MA')
    ax1.axhline(y=np.mean(rho_t), color='gray', linestyle='--', alpha=0.5,
                label=f'Mean={np.mean(rho_t):.3f}')
    ax1.set_ylabel('Copula Correlation (rho_t)')
    ax1.set_title('K921: Patton (2006) Time-Varying Student-t Copula -- SPY/GLD')
    ax1.legend(loc='upper right')

    # Crisis shading
    for name, (start, end) in crises_dict.items():
        for ax in axes:
            ax.axvspan(pd.Timestamp(start), pd.Timestamp(end),
                       alpha=0.15, color='red', label=name if ax == axes[0] else None)

    # Panel 2: Time-varying lambda_t
    ax2 = axes[1]
    ax2.plot(dates, lambda_t, color='darkred', linewidth=0.5, alpha=0.7)
    lambda_rolling = pd.Series(lambda_t, index=dates).rolling(60).mean()
    ax2.plot(dates, lambda_rolling, color='red', linewidth=1.5, label='60-day MA')
    ax2.axhline(y=np.mean(lambda_t), color='gray', linestyle='--', alpha=0.5,
                label=f'Mean={np.mean(lambda_t):.4f}')

    # Add 2-sigma bands
    lam_mean = pd.Series(lambda_t, index=dates).rolling(252).mean()
    lam_std = pd.Series(lambda_t, index=dates).rolling(252).std()
    ax2.fill_between(dates, lam_mean - 2 * lam_std, lam_mean + 2 * lam_std,
                     alpha=0.1, color='orange', label='2-sigma band')
    ax2.set_ylabel('Tail Dependence (lambda_t)')
    ax2.legend(loc='upper right')

    # Panel 3: VIX overlay
    ax3 = axes[2]
    ax3.plot(dates, lambda_t, color='darkred', linewidth=0.5, alpha=0.5, label='lambda_t')
    ax3.set_ylabel('lambda_t', color='darkred')
    ax3.tick_params(axis='y', labelcolor='darkred')

    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax3.xaxis.set_major_locator(mdates.YearLocator(2))
    ax3.set_xlabel('Date')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


def plot_crisis_leadlag(dates, lambda_t, crises_dict, pre_days, output_path):
    """Plot lambda behavior 60 days before each crisis."""
    lambda_series = pd.Series(lambda_t, index=dates)

    n_crises = len(crises_dict)
    fig, axes = plt.subplots(1, n_crises, figsize=(5 * n_crises, 5))
    if n_crises == 1:
        axes = [axes]

    for idx, (name, (start, end)) in enumerate(crises_dict.items()):
        ax = axes[idx]
        crisis_start = pd.Timestamp(start)

        # Find the position in data
        pos = dates.searchsorted(crisis_start)
        if pos == 0:
            continue

        # Pre-crisis window: 60 trading days before
        pre_start = max(0, pos - pre_days)
        # During crisis
        crisis_end = pd.Timestamp(end)
        post_pos = min(len(dates) - 1, dates.searchsorted(crisis_end))

        # Get lambda values
        pre_lambda = lambda_series.iloc[pre_start:pos]
        during_lambda = lambda_series.iloc[pos:post_pos + 1]

        # Plot
        days_before = np.arange(-len(pre_lambda), 0)
        days_during = np.arange(0, len(during_lambda))

        ax.plot(days_before, pre_lambda.values, color='steelblue', linewidth=1.5,
                label='Pre-crisis')
        ax.plot(days_during, during_lambda.values, color='red', linewidth=1.5,
                label='During crisis')
        ax.axvline(x=0, color='black', linestyle='--', alpha=0.5, label='Crisis start')

        # Add trend line for pre-crisis
        if len(pre_lambda) > 5:
            z = np.polyfit(days_before, pre_lambda.values, 1)
            trend = np.polyval(z, days_before)
            ax.plot(days_before, trend, color='orange', linestyle='--',
                    label=f'Pre-trend: {z[0]:.5f}/day')

        ax.set_title(f'{name}\n(start: {start})')
        ax.set_xlabel('Trading Days (0 = crisis start)')
        ax.set_ylabel('Tail Dependence (lambda_t)')
        ax.legend(fontsize=8)

    plt.suptitle('K921: Lambda Behavior Before and During Crises', fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("K921: Time-Varying Copula -- Dynamic Tail Dependence as Crisis Early Warning")
    print("=" * 70)

    # ---- Step 1: Fetch data ----
    print("\n[Step 1] Fetching data...")
    prices = fetch_data()

    returns = prices[ASSETS].pct_change().dropna()
    dates = returns.index

    # VIX
    vix = prices['VIX'].reindex(dates).ffill()

    # IS/OOS split
    oos_mask = dates >= OOS_START
    is_mask = ~oos_mask

    # ---- Step 2: Descriptive Statistics ----
    print("\n[Step 2] Descriptive statistics...")
    desc_stats = {}
    for asset in ASSETS:
        desc_stats[asset] = descriptive_stats(returns[asset], asset)
        print(f"  {asset}: mean={desc_stats[asset]['mean']:.6f}, std={desc_stats[asset]['std']:.6f}, "
              f"skew={desc_stats[asset]['skew']:.4f}, kurt={desc_stats[asset]['kurtosis']:.4f}")

    # ---- Step 3: GJR-GARCH Marginals ----
    print("\n[Step 3] Fitting GJR-GARCH marginals...")
    garch_results = {}
    cond_vols = {}
    std_resids = {}
    nus = {}

    for asset in ASSETS:
        res, cv, sr, nu = fit_gjr_garch(returns[asset], asset)
        garch_results[asset] = {
            'omega': round(float(res.params.get('omega', 0)), 6),
            'alpha': round(float(res.params.get('alpha[1]', 0)), 6),
            'gamma': round(float(res.params.get('gamma[1]', 0)), 6),
            'beta': round(float(res.params.get('beta[1]', 0)), 6),
            'nu': round(float(nu), 2),
            'persistence': round(float(res.params.get('alpha[1]', 0) +
                                       res.params.get('gamma[1]', 0) / 2 +
                                       res.params.get('beta[1]', 0)), 4),
            'converged': res.convergence_flag == 0
        }
        cond_vols[asset] = cv
        std_resids[asset] = sr
        nus[asset] = nu

    # ---- Step 4: PIT ----
    print("\n[Step 4] Probability Integral Transform...")
    u = {}
    for asset in ASSETS:
        u[asset] = probability_integral_transform(std_resids[asset].values, nus[asset])
        # KS test for uniformity
        ks_stat, ks_pval = sp_stats.kstest(u[asset], 'uniform')
        print(f"  {asset} PIT: KS stat={ks_stat:.4f}, p={ks_pval:.4f} "
              f"({'OK' if ks_pval > 0.05 else 'REJECT uniformity'})")

    u1 = u['SPY']
    u2 = u['GLD']

    # ---- Step 5: Static Student-t Copula (baseline) ----
    print("\n[Step 5] Fitting static Student-t copula (baseline)...")

    # Full sample
    static_full = fit_static_copula(u1, u2)
    print(f"  Full sample: rho={static_full['rho']:.4f}, nu={static_full['nu']:.2f}, "
          f"lambda={static_full['lambda']:.4f}, AIC={static_full['AIC']:.2f}")

    # IS only
    static_is = fit_static_copula(u1[is_mask], u2[is_mask])
    print(f"  IS: rho={static_is['rho']:.4f}, nu={static_is['nu']:.2f}, "
          f"lambda={static_is['lambda']:.4f}")

    # OOS only
    static_oos = fit_static_copula(u1[oos_mask], u2[oos_mask])
    print(f"  OOS: rho={static_oos['rho']:.4f}, nu={static_oos['nu']:.2f}, "
          f"lambda={static_oos['lambda']:.4f}")

    # ---- Step 6: Time-Varying Copula ----
    print("\n[Step 6] Fitting time-varying Student-t copula...")

    # Use static full-sample nu as fixed df
    nu_fixed = static_full['nu']

    tv_result = fit_tv_copula(u1, u2, nu_fixed, M=M_FORCING)
    rho_t = tv_result['rho_t']

    # ---- Step 7: Compute time-varying lambda_t ----
    print("\n[Step 7] Computing time-varying tail dependence lambda_t...")
    lambda_t = compute_lambda_t(rho_t, nu_fixed)

    print(f"  lambda_t: mean={np.mean(lambda_t):.4f}, std={np.std(lambda_t):.4f}, "
          f"min={np.min(lambda_t):.4f}, max={np.max(lambda_t):.4f}")

    lambda_stats = {
        'mean': round(float(np.mean(lambda_t)), 4),
        'std': round(float(np.std(lambda_t)), 4),
        'min': round(float(np.min(lambda_t)), 4),
        'max': round(float(np.max(lambda_t)), 4),
        'q25': round(float(np.percentile(lambda_t, 25)), 4),
        'q75': round(float(np.percentile(lambda_t, 75)), 4),
    }

    rho_t_stats = {
        'mean': round(float(np.mean(rho_t)), 4),
        'std': round(float(np.std(rho_t)), 4),
        'min': round(float(np.min(rho_t)), 4),
        'max': round(float(np.max(rho_t)), 4),
    }

    # ---- Step 8: Crisis Analysis ----
    print("\n[Step 8] Crisis early warning analysis...")

    lambda_series = pd.Series(lambda_t, index=dates)
    rho_series = pd.Series(rho_t, index=dates)

    crisis_analysis = {}
    for name, (start, end) in CRISES.items():
        crisis_start = pd.Timestamp(start)
        crisis_end = pd.Timestamp(end)

        pos = dates.searchsorted(crisis_start)
        pre_start = max(0, pos - PRE_CRISIS_DAYS)
        post_pos = min(len(dates) - 1, dates.searchsorted(crisis_end))

        # Pre-crisis lambda
        pre_lambda = lambda_series.iloc[pre_start:pos]
        during_lambda = lambda_series.iloc[pos:post_pos + 1]

        # Pre-crisis rho
        pre_rho = rho_series.iloc[pre_start:pos]
        during_rho = rho_series.iloc[pos:post_pos + 1]

        # Trend analysis (linear regression on pre-crisis lambda)
        if len(pre_lambda) > 5:
            days = np.arange(len(pre_lambda))
            slope, intercept, r_value, p_value, std_err = sp_stats.linregress(days, pre_lambda.values)
        else:
            slope, intercept, r_value, p_value, std_err = 0, 0, 0, 1, 0

        crisis_analysis[name] = {
            'pre_crisis_lambda': {
                'mean': round(float(pre_lambda.mean()), 4),
                'start_val': round(float(pre_lambda.iloc[0]), 4) if len(pre_lambda) > 0 else None,
                'end_val': round(float(pre_lambda.iloc[-1]), 4) if len(pre_lambda) > 0 else None,
                'trend_slope': round(float(slope), 6),
                'trend_r2': round(float(r_value**2), 4),
                'trend_pval': round(float(p_value), 4),
                'n_days': int(len(pre_lambda))
            },
            'during_crisis_lambda': {
                'mean': round(float(during_lambda.mean()), 4),
                'min': round(float(during_lambda.min()), 4),
                'max': round(float(during_lambda.max()), 4),
                'n_days': int(len(during_lambda))
            },
            'pre_crisis_rho': {
                'mean': round(float(pre_rho.mean()), 4),
                'start_val': round(float(pre_rho.iloc[0]), 4) if len(pre_rho) > 0 else None,
                'end_val': round(float(pre_rho.iloc[-1]), 4) if len(pre_rho) > 0 else None,
            },
            'during_crisis_rho': {
                'mean': round(float(during_rho.mean()), 4),
            },
            'lambda_drop': round(float(pre_lambda.mean() - during_lambda.mean()), 4),
            'signal': 'DECLINING' if slope < -1e-4 and p_value < 0.05 else 'NO SIGNAL'
        }

        print(f"\n  {name}:")
        print(f"    Pre-crisis lambda: mean={pre_lambda.mean():.4f}, "
              f"trend={slope:.6f}/day, R²={r_value**2:.4f}, p={p_value:.4f}")
        print(f"    During crisis lambda: mean={during_lambda.mean():.4f}")
        print(f"    Lambda drop: {pre_lambda.mean() - during_lambda.mean():.4f}")
        print(f"    Signal: {crisis_analysis[name]['signal']}")

    # ---- Step 9: Granger Causality ----
    print("\n[Step 9] Granger causality tests...")

    # Test: lambda -> VIX (does lambda lead VIX?)
    # Align lambda and VIX
    vix_aligned = vix.reindex(dates).ffill().dropna()
    common_idx = lambda_series.index.intersection(vix_aligned.index)
    lam_gc = lambda_series.reindex(common_idx).dropna()
    vix_gc = vix_aligned.reindex(lam_gc.index)

    # Need common non-NaN
    valid = ~(np.isnan(lam_gc.values) | np.isnan(vix_gc.values))
    lam_arr = lam_gc.values[valid]
    vix_arr = vix_gc.values[valid]

    print("\n  Lambda -> VIX (does tail dependence lead volatility?):")
    gc_lam_to_vix, gc_lam_to_vix_best = granger_causality_test(lam_arr, vix_arr, max_lag=5)
    print(f"    Best lag={gc_lam_to_vix_best['lag']}, F={gc_lam_to_vix_best['F_stat']:.4f}, "
          f"p={gc_lam_to_vix_best['p_value']:.4f}")

    print("\n  VIX -> Lambda (does volatility lead tail dependence?):")
    gc_vix_to_lam, gc_vix_to_lam_best = granger_causality_test(vix_arr, lam_arr, max_lag=5)
    print(f"    Best lag={gc_vix_to_lam_best['lag']}, F={gc_vix_to_lam_best['F_stat']:.4f}, "
          f"p={gc_vix_to_lam_best['p_value']:.4f}")

    # Also test lambda(t) vs VIX(t+22) correlation
    lam_shift = pd.Series(lam_arr[:-22])
    vix_future = pd.Series(vix_arr[22:])
    corr_lam_vix22, corr_pval = sp_stats.pearsonr(lam_shift, vix_future)
    spearman_corr, spearman_pval = sp_stats.spearmanr(lam_shift, vix_future)
    print(f"\n  Lambda(t) vs VIX(t+22):")
    print(f"    Pearson r={corr_lam_vix22:.4f}, p={corr_pval:.4f}")
    print(f"    Spearman rho={spearman_corr:.4f}, p={spearman_pval:.4f}")

    granger_results = {
        'lambda_to_VIX': {
            'all_lags': gc_lam_to_vix,
            'best': gc_lam_to_vix_best,
        },
        'VIX_to_lambda': {
            'all_lags': gc_vix_to_lam,
            'best': gc_vix_to_lam_best,
        },
        'lambda_vs_VIX_22d': {
            'pearson_r': round(float(corr_lam_vix22), 4),
            'pearson_pval': round(float(corr_pval), 4),
            'spearman_rho': round(float(spearman_corr), 4),
            'spearman_pval': round(float(spearman_pval), 4),
        }
    }

    # ---- Step 10: VaR Backtesting (IS + OOS) ----
    print("\n[Step 10] VaR backtesting (time-varying vs static copula)...")

    portfolio_returns = 0.5 * returns['SPY'] + 0.5 * returns['GLD']

    # -- Time-Varying Copula VaR --
    print("  Computing time-varying copula VaR (Monte Carlo)...")
    np.random.seed(42)  # reset seed for reproducibility
    tv_var, tv_es = compute_portfolio_var_es(
        cond_vols['SPY'], cond_vols['GLD'], rho_t, nu_fixed,
        weights=(0.5, 0.5), alpha_levels=(0.01, 0.05), n_sim=N_SIM
    )

    # -- Static Copula VaR (use static rho throughout) --
    print("  Computing static copula VaR (Monte Carlo)...")
    rho_static = np.full(len(rho_t), static_full['rho'])
    np.random.seed(42)
    st_var, st_es = compute_portfolio_var_es(
        cond_vols['SPY'], cond_vols['GLD'], rho_static, nu_fixed,
        weights=(0.5, 0.5), alpha_levels=(0.01, 0.05), n_sim=N_SIM
    )

    # Backtest both
    var_backtest_results = {'time_varying': {}, 'static': {}}

    for sample_name, mask in [('IS', is_mask), ('OOS', oos_mask)]:
        port_r = portfolio_returns[mask].values
        n_sample = len(port_r)

        var_backtest_results['time_varying'][sample_name] = {}
        var_backtest_results['static'][sample_name] = {}

        for alpha_level in [0.01, 0.05]:
            key = f'VaR_{int(alpha_level*100)}pct'

            # Time-varying
            tv_v = tv_var[key][mask]
            bt_tv = backtest_var(port_r, tv_v, alpha_level)
            var_backtest_results['time_varying'][sample_name][key] = bt_tv

            # Static
            st_v = st_var[key][mask]
            bt_st = backtest_var(port_r, st_v, alpha_level)
            var_backtest_results['static'][sample_name][key] = bt_st

            print(f"  {sample_name} {key}:")
            print(f"    TV: violations={bt_tv['kupiec']['n_violations']}/{n_sample} "
                  f"({bt_tv['violation_rate']:.4f}), Kupiec p={bt_tv['kupiec']['p_value']:.4f}, "
                  f"Basel={bt_tv['basel_traffic_light']}")
            print(f"    Static: violations={bt_st['kupiec']['n_violations']}/{n_sample} "
                  f"({bt_st['violation_rate']:.4f}), Kupiec p={bt_st['kupiec']['p_value']:.4f}, "
                  f"Basel={bt_st['basel_traffic_light']}")

    # ---- Step 11: Model Comparison ----
    print("\n[Step 11] Model comparison (time-varying vs static)...")

    # AIC/BIC comparison
    # For static copula on full sample, compute LL over same effective range
    # Re-fit static on full sample for fair comparison
    # Static: 2 params (rho, nu), TV: 3 params (omega, beta, alpha) + 1 fixed nu = 4 effective
    # But we fix nu, so TV has 3 params

    n_eff_full = len(u1) - M_FORCING
    static_ll_full = static_full['log_likelihood']
    static_aic = -2 * static_ll_full + 2 * 2  # 2 params
    static_bic = -2 * static_ll_full + 2 * np.log(len(u1))

    tv_ll = tv_result['log_likelihood']
    tv_aic = tv_result['AIC']
    tv_bic = tv_result['BIC']

    model_comparison = {
        'static': {
            'log_likelihood': round(float(static_ll_full), 2),
            'AIC': round(float(static_aic), 2),
            'BIC': round(float(static_bic), 2),
            'n_params': 2,
        },
        'time_varying': {
            'log_likelihood': round(float(tv_ll), 2),
            'AIC': round(float(tv_aic), 2),
            'BIC': round(float(tv_bic), 2),
            'n_params': 3,  # omega, beta, alpha (nu fixed)
        },
        'delta_AIC': round(float(tv_aic - static_aic), 2),
        'delta_BIC': round(float(tv_bic - static_bic), 2),
        'tv_preferred_by_AIC': tv_aic < static_aic,
        'tv_preferred_by_BIC': tv_bic < static_bic,
        'LR_test': {
            'stat': round(float(2 * (tv_ll - static_ll_full)), 2),
            'df': 1,  # 3 vs 2 params
            'p_value': round(float(1 - sp_stats.chi2.cdf(
                2 * (tv_ll - static_ll_full), 1)), 4) if tv_ll > static_ll_full else 1.0
        }
    }

    print(f"  Static:  LL={static_ll_full:.2f}, AIC={static_aic:.2f}, BIC={static_bic:.2f}")
    print(f"  TV:      LL={tv_ll:.2f}, AIC={tv_aic:.2f}, BIC={tv_bic:.2f}")
    print(f"  Delta AIC={tv_aic - static_aic:.2f} ({'TV better' if tv_aic < static_aic else 'Static better'})")
    print(f"  Delta BIC={tv_bic - static_bic:.2f} ({'TV better' if tv_bic < static_bic else 'Static better'})")
    print(f"  LR stat={model_comparison['LR_test']['stat']:.2f}, "
          f"p={model_comparison['LR_test']['p_value']:.4f}")

    # ---- Step 12: Regime Detection ----
    print("\n[Step 12] Lambda regime detection...")

    # Rolling bands
    lam_pd = pd.Series(lambda_t, index=dates)
    rolling_mean = lam_pd.rolling(252).mean()
    rolling_std = lam_pd.rolling(252).std()
    upper_band = rolling_mean + 2 * rolling_std
    lower_band = rolling_mean - 2 * rolling_std

    # Identify regime breaks (lambda below lower band)
    below_lower = lam_pd < lower_band
    above_upper = lam_pd > upper_band

    # Find contiguous blocks of below_lower
    regime_breaks = []
    in_break = False
    break_start = None
    for i, (d, b) in enumerate(zip(dates, below_lower)):
        if pd.isna(b):
            continue
        if b and not in_break:
            in_break = True
            break_start = d
        elif not b and in_break:
            in_break = False
            regime_breaks.append({
                'start': str(break_start.date()),
                'end': str(dates[i - 1].date()),
                'duration_days': (dates[i - 1] - break_start).days,
                'min_lambda': round(float(lam_pd.loc[break_start:dates[i - 1]].min()), 4)
            })

    # Close any open break
    if in_break:
        regime_breaks.append({
            'start': str(break_start.date()),
            'end': str(dates[-1].date()),
            'duration_days': (dates[-1] - break_start).days,
            'min_lambda': round(float(lam_pd.loc[break_start:].min()), 4)
        })

    # Filter significant breaks (duration > 5 days)
    significant_breaks = [b for b in regime_breaks if b['duration_days'] > 5]
    print(f"  Total regime breaks (lambda < lower band): {len(regime_breaks)}")
    print(f"  Significant breaks (>5 days): {len(significant_breaks)}")
    for b in significant_breaks[:10]:
        print(f"    {b['start']} to {b['end']} ({b['duration_days']} days, min lambda={b['min_lambda']})")

    regime_detection = {
        'n_total_breaks': len(regime_breaks),
        'n_significant_breaks': len(significant_breaks),
        'significant_breaks': significant_breaks[:20],  # cap at 20
    }

    # ---- Step 13: Plots ----
    print("\n[Step 13] Generating plots...")

    plot_dynamic_lambda(
        dates, lambda_t, rho_t, CRISES,
        os.path.join(OUTPUT_DIR, 'k921_dynamic_lambda.png')
    )

    plot_crisis_leadlag(
        dates, lambda_t, CRISES, PRE_CRISIS_DAYS,
        os.path.join(OUTPUT_DIR, 'k921_crisis_leadlag.png')
    )

    # ---- Step 14: Compile Results ----
    print("\n[Step 14] Compiling results...")

    # Build key findings
    # Determine early warning signal quality
    n_signaling = sum(1 for c in crisis_analysis.values() if c['signal'] == 'DECLINING')
    n_crises_total = len(crisis_analysis)

    gc_lambda_leads = gc_lam_to_vix_best['p_value'] < 0.05
    gc_vix_leads = gc_vix_to_lam_best['p_value'] < 0.05

    # rho_t mean vs static rho
    rho_t_mean = np.mean(rho_t)
    rho_static_val = static_full['rho']

    key_findings = (
        f"K921 Time-Varying Copula: Patton (2006) dynamic Student-t copula on SPY-GLD (2005-2026). "
        f"Parameters: omega={tv_result['omega']:.4f}, beta={tv_result['beta']:.4f}, "
        f"alpha={tv_result['alpha']:.4f}, nu(fixed)={nu_fixed:.2f}. "
        f"Dynamic rho_t: mean={rho_t_mean:.4f} (vs static {rho_static_val:.4f}), "
        f"std={np.std(rho_t):.4f}, range [{np.min(rho_t):.4f}, {np.max(rho_t):.4f}]. "
        f"Dynamic lambda_t: mean={np.mean(lambda_t):.4f}, std={np.std(lambda_t):.4f}. "
        f"Crisis early warning: {n_signaling}/{n_crises_total} crises showed declining pre-crisis lambda. "
        f"Granger causality: lambda->VIX {'significant' if gc_lambda_leads else 'NOT significant'} "
        f"(F={gc_lam_to_vix_best['F_stat']:.2f}, p={gc_lam_to_vix_best['p_value']:.4f}); "
        f"VIX->lambda {'significant' if gc_vix_leads else 'NOT significant'} "
        f"(F={gc_vix_to_lam_best['F_stat']:.2f}, p={gc_vix_to_lam_best['p_value']:.4f}). "
        f"Lambda(t) vs VIX(t+22): Pearson r={corr_lam_vix22:.4f}, Spearman={spearman_corr:.4f}. "
        f"Model comparison: TV {'preferred' if tv_aic < static_aic else 'NOT preferred'} by AIC "
        f"(delta={tv_aic - static_aic:.1f}), "
        f"{'preferred' if tv_bic < static_bic else 'NOT preferred'} by BIC "
        f"(delta={tv_bic - static_bic:.1f}). "
        f"VaR improvement: see backtest results."
    )

    results = {
        'experiment_id': 'K921',
        'title': 'Time-Varying Copula -- Dynamic Tail Dependence as Crisis Early Warning',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance',
        'data_period': f'{START_DATE} to {END_DATE}',
        'oos_start': OOS_START,
        'n_obs': int(len(returns)),
        'n_is': int(is_mask.sum()),
        'n_oos': int(oos_mask.sum()),
        'descriptive_stats': desc_stats,
        'pearson_correlation': round(float(returns['SPY'].corr(returns['GLD'])), 4),
        'garch_marginals': garch_results,
        'patton_tv_copula': {
            'omega': round(float(tv_result['omega']), 4),
            'beta': round(float(tv_result['beta']), 4),
            'alpha': round(float(tv_result['alpha']), 4),
            'nu_fixed': round(float(nu_fixed), 2),
            'M_forcing': M_FORCING,
            'log_likelihood': round(float(tv_result['log_likelihood']), 2),
            'AIC': round(float(tv_result['AIC']), 2),
            'BIC': round(float(tv_result['BIC']), 2),
            'converged': tv_result['converged'],
        },
        'rho_t_stats': rho_t_stats,
        'lambda_t_stats': lambda_stats,
        'static_copula': {
            'full': {k: round(v, 4) if isinstance(v, float) else v
                     for k, v in static_full.items()},
            'IS': {k: round(v, 4) if isinstance(v, float) else v
                   for k, v in static_is.items()},
            'OOS': {k: round(v, 4) if isinstance(v, float) else v
                    for k, v in static_oos.items()},
        },
        'crisis_analysis': crisis_analysis,
        'granger_causality': granger_results,
        'model_comparison': model_comparison,
        'var_backtest': var_backtest_results,
        'regime_detection': regime_detection,
        'references': [
            'Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER 47(2):527-556',
            'Joe (1997): Multivariate Models and Dependence Concepts',
            'K920: Copula-GARCH Tail Dependence (prior experiment)',
            'Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives',
            'Christoffersen (1998): Evaluating Interval Forecasts, IER',
        ],
        'key_findings': key_findings,
        'plots': [
            'k921_dynamic_lambda.png',
            'k921_crisis_leadlag.png',
        ]
    }

    # Save results
    results_path = os.path.join(OUTPUT_DIR, 'k921_time_varying_copula_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    print("\n" + "=" * 70)
    print("K921 COMPLETE")
    print("=" * 70)
    print(f"\nKey findings summary:")
    print(f"  1. Dynamic rho_t mean={rho_t_mean:.4f} vs static rho={rho_static_val:.4f}")
    print(f"  2. Dynamic lambda_t: mean={np.mean(lambda_t):.4f}, range [{np.min(lambda_t):.4f}, {np.max(lambda_t):.4f}]")
    print(f"  3. Crisis early warning signal: {n_signaling}/{n_crises_total} crises")
    print(f"  4. Granger lambda->VIX: {'YES' if gc_lambda_leads else 'NO'}")
    print(f"  5. Model: TV {'better' if tv_aic < static_aic else 'worse'} by AIC (delta={tv_aic - static_aic:.1f})")

    return results


if __name__ == '__main__':
    results = main()
