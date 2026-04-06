#!/usr/bin/env python3
"""
K920: Copula-GARCH Tail Dependence -- SPY/GLD Non-Linear Dependence Structure

Question: Do SPY and GLD exhibit non-linear tail dependence that linear
correlation models (DCC, BEKK) miss? Does diversification break down
during extreme events?

Method:
  1. GJR-GARCH(1,1) Student-t marginals for SPY and GLD
  2. PIT to uniform residuals
  3. Five copulas: Gaussian, Student-t, Clayton, Gumbel, Frank
  4. AIC/BIC model selection
  5. Tail dependence coefficients (lambda_L, lambda_U)
  6. Rolling 500-day copula for time-varying tail dependence
  7. Copula-based portfolio VaR/ES (50/50 SPY/GLD)
  8. VaR backtesting: Kupiec + Christoffersen + Basel (IS and OOS)

Data: SPY, GLD daily from yfinance, 2005-01-01 to 2026-04-04
IS: 2005-2019, OOS: 2019-2026

References:
  - Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER
  - Joe (1997): Multivariate Models and Dependence Concepts
  - Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives
  - Christoffersen (1998): Evaluating Interval Forecasts, IER

Prior work:
  - K915: DCC-GARCH (linear dynamic correlation)
  - K918: BEKK (no cross-asset spillover)
  - K846: 50/50 three moats
  - K443: Earlier copula (SPY-GLD lambda_L ~ 0, SPY-QQQ lambda_L = 0.82)

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
from scipy.optimize import minimize, minimize_scalar
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
ROLLING_WINDOW = 500  # for time-varying copula
N_SIM = 10000  # Monte Carlo draws for VaR
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 1: Data Collection
# ============================================================
def fetch_data():
    """Fetch daily prices for SPY, GLD from yfinance."""
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
# Step 2: GJR-GARCH Marginal Models
# ============================================================
def fit_gjr_garch(returns_series, asset_name):
    """
    Fit GJR-GARCH(1,1) with Student-t innovations.
    Returns: model result, conditional volatility, standardized residuals, df.
    """
    r = returns_series * 100  # percentage

    am = arch_model(r, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
    res = am.fit(disp='off', options={'maxiter': 5000})

    cond_vol = res.conditional_volatility / 100
    std_resid = res.std_resid

    # Extract Student-t df
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
    """
    Apply PIT using Student-t CDF to get uniform (0,1) variates.
    """
    u = sp_stats.t.cdf(std_resid, df=nu)
    # Clip to avoid exact 0 or 1 (causes issues with copula)
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return u


# ============================================================
# Step 3: Copula Log-Likelihoods
# ============================================================
def gaussian_copula_ll(params, u1, u2):
    """Gaussian copula negative log-likelihood."""
    rho = np.tanh(params[0])  # transform to (-1, 1)
    x1 = sp_stats.norm.ppf(u1)
    x2 = sp_stats.norm.ppf(u2)
    n = len(u1)

    det = 1 - rho**2
    if det <= 0:
        return 1e10

    ll = -0.5 * n * np.log(det) - 0.5 / det * np.sum(
        rho**2 * (x1**2 + x2**2) - 2 * rho * x1 * x2
    )
    return -ll  # negative for minimization


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

    # Student-t copula density
    ll = n * (gammaln((nu + 2) / 2) - gammaln(nu / 2)
              - np.log(nu * np.pi) - 0.5 * np.log(det))

    # Marginal t contributions (cancel out in copula density)
    ll -= n * 2 * (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                   - 0.5 * np.log(nu * np.pi))

    # Quadratic form
    Q = (x1**2 + x2**2 - 2 * rho * x1 * x2) / det
    ll -= ((nu + 2) / 2) * np.sum(np.log(1 + Q / nu))

    # Marginal t log-densities (add back)
    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x1**2 / nu))
    ll += ((nu + 1) / 2) * np.sum(np.log(1 + x2**2 / nu))

    return -ll


def clayton_copula_ll(params, u1, u2):
    """Clayton copula negative log-likelihood."""
    theta = np.exp(params[0]) + 1e-6  # theta > 0
    n = len(u1)

    try:
        term1 = n * np.log(1 + theta)
        term2 = -(1 + theta) * np.sum(np.log(u1) + np.log(u2))
        S = u1**(-theta) + u2**(-theta) - 1
        S = np.maximum(S, 1e-10)
        term3 = -(2 + 1 / theta) * np.sum(np.log(S))
        ll = term1 + term2 + term3
    except (FloatingPointError, ValueError):
        return 1e10

    if not np.isfinite(ll):
        return 1e10
    return -ll


def gumbel_copula_ll(params, u1, u2):
    """Gumbel copula negative log-likelihood (bivariate)."""
    theta = np.exp(params[0]) + 1.0  # theta >= 1

    try:
        t1 = (-np.log(u1))**theta
        t2 = (-np.log(u2))**theta
        S = t1 + t2
        A = S**(1.0 / theta)
        C = np.exp(-A)

        # Bivariate Gumbel copula density:
        # c(u1,u2) = C(u1,u2) / (u1*u2) * (t1*t2)^(theta-1) * S^(1/theta - 2)
        #            * (A + theta - 1)
        pdf = (C / (u1 * u2)) * (t1 * t2)**(theta - 1) * S**(1.0/theta - 2)
        pdf *= (A + theta - 1)
        pdf = np.maximum(pdf, 1e-300)

        ll = np.sum(np.log(pdf))
    except (FloatingPointError, ValueError, RuntimeWarning):
        return 1e10

    if not np.isfinite(ll):
        return 1e10
    return -ll


def frank_copula_ll(params, u1, u2):
    """Frank copula negative log-likelihood.

    Frank copula density:
    c(u1,u2) = -theta*(exp(-theta)-1)*exp(-theta*(u1+u2)) /
               [(exp(-theta)-1) + (exp(-theta*u1)-1)*(exp(-theta*u2)-1)]^2

    For numerical stability with large |theta|, we work in log space.
    """
    theta = params[0]
    if abs(theta) < 1e-6:
        return 1e10  # independence, degenerate

    n = len(u1)
    try:
        # Work in log space for numerical stability
        # log(numerator) = log(|theta|) + log(|exp(-theta)-1|) - theta*(u1+u2)
        # But need to handle signs carefully

        # Use the log-sum-exp trick for large theta
        # For theta > 0: exp(-theta) - 1 < 0, so |exp(-theta)-1| = 1 - exp(-theta)
        # For theta < 0: exp(-theta) - 1 > 0

        eta = np.exp(-theta) - 1.0  # could be negative

        # Numerator: -theta * eta * exp(-theta*(u1+u2))
        # For theta > 0: -theta < 0, eta < 0, so -theta * eta > 0 (good, density positive)
        log_num = np.log(np.abs(-theta * eta)) + (-theta * (u1 + u2))

        # Denominator: [eta + (exp(-theta*u1)-1)*(exp(-theta*u2)-1)]^2
        inner = eta + (np.exp(-theta * u1) - 1) * (np.exp(-theta * u2) - 1)
        log_denom = 2.0 * np.log(np.abs(inner))

        log_pdf = log_num - log_denom
        ll = np.sum(log_pdf)
    except (FloatingPointError, ValueError):
        return 1e10

    if not np.isfinite(ll):
        return 1e10
    return -ll


# ============================================================
# Step 4: Fit All Copulas
# ============================================================
def fit_copula(name, u1, u2):
    """Fit a single copula and return params, LL, AIC, BIC, tail deps."""
    n = len(u1)

    if name == 'Gaussian':
        res = minimize(gaussian_copula_ll, x0=[0.0], args=(u1, u2),
                       method='Nelder-Mead', options={'maxiter': 5000})
        rho = np.tanh(res.x[0])
        ll = -res.fun
        k = 1
        lambda_L = 0.0
        lambda_U = 0.0
        params_dict = {'rho': round(float(rho), 4)}

    elif name == 'Student-t':
        res = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1, u2),
                       method='Nelder-Mead', options={'maxiter': 10000})
        rho = np.tanh(res.x[0])
        nu = np.exp(res.x[1]) + 2.01
        ll = -res.fun
        k = 2
        # Symmetric tail dependence for Student-t copula
        if nu < 100:
            lambda_tail = 2 * sp_stats.t.cdf(
                -np.sqrt((nu + 1) * (1 - rho) / (1 + rho)), df=nu + 1
            )
        else:
            lambda_tail = 0.0
        lambda_L = lambda_tail
        lambda_U = lambda_tail
        params_dict = {'rho': round(float(rho), 4), 'nu': round(float(nu), 2)}

    elif name == 'Clayton':
        res = minimize(clayton_copula_ll, x0=[0.0], args=(u1, u2),
                       method='Nelder-Mead', options={'maxiter': 5000})
        theta = np.exp(res.x[0]) + 1e-6
        ll = -res.fun
        k = 1
        lambda_L = 2**(-1 / theta) if theta > 0 else 0.0
        lambda_U = 0.0
        params_dict = {'theta': round(float(theta), 4)}

    elif name == 'Gumbel':
        res = minimize(gumbel_copula_ll, x0=[0.1], args=(u1, u2),
                       method='Nelder-Mead', options={'maxiter': 5000})
        theta = np.exp(res.x[0]) + 1.0
        ll = -res.fun
        k = 1
        lambda_L = 0.0
        lambda_U = 2 - 2**(1 / theta) if theta > 1 else 0.0
        params_dict = {'theta': round(float(theta), 4)}

    elif name == 'Frank':
        res = minimize(frank_copula_ll, x0=[1.0], args=(u1, u2),
                       method='Nelder-Mead', options={'maxiter': 5000})
        theta = res.x[0]
        ll = -res.fun
        k = 1
        lambda_L = 0.0
        lambda_U = 0.0
        params_dict = {'theta': round(float(theta), 4)}

    else:
        raise ValueError(f"Unknown copula: {name}")

    aic = -2 * ll + 2 * k
    bic = -2 * ll + k * np.log(n)

    return {
        'name': name,
        'params': params_dict,
        'log_likelihood': round(float(ll), 2),
        'k': k,
        'AIC': round(float(aic), 2),
        'BIC': round(float(bic), 2),
        'lambda_L': round(float(lambda_L), 4),
        'lambda_U': round(float(lambda_U), 4),
        'converged': res.success
    }


def fit_all_copulas(u1, u2):
    """Fit all 5 copulas and return sorted results."""
    copula_names = ['Gaussian', 'Student-t', 'Clayton', 'Gumbel', 'Frank']
    results = []

    for name in copula_names:
        print(f"\nFitting {name} copula...")
        try:
            res = fit_copula(name, u1, u2)
            results.append(res)
            print(f"  {name}: LL={res['log_likelihood']:.2f}, "
                  f"AIC={res['AIC']:.2f}, BIC={res['BIC']:.2f}, "
                  f"lambda_L={res['lambda_L']:.4f}, lambda_U={res['lambda_U']:.4f}")
        except Exception as e:
            print(f"  {name} failed: {e}")
            results.append({
                'name': name,
                'params': {},
                'log_likelihood': float('nan'),
                'k': 0,
                'AIC': float('inf'),
                'BIC': float('inf'),
                'lambda_L': float('nan'),
                'lambda_U': float('nan'),
                'converged': False
            })

    # Sort by AIC
    results.sort(key=lambda x: x['AIC'] if np.isfinite(x['AIC']) else 1e20)
    return results


# ============================================================
# Step 5: Rolling Window Copula (Time-Varying Tail Dependence)
# ============================================================
def rolling_copula(u1_full, u2_full, dates, window=500):
    """
    Compute rolling-window tail dependence using Student-t and Clayton copulas.
    Returns DataFrame with dates, lambda_L (Clayton), lambda_L (Student-t), lambda_U (Student-t).
    """
    n = len(u1_full)
    results = []

    for i in range(window, n):
        u1_win = u1_full[i - window:i]
        u2_win = u2_full[i - window:i]

        # Student-t copula for symmetric tail dep
        try:
            res_t = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1_win, u2_win),
                             method='Nelder-Mead', options={'maxiter': 3000})
            rho_t = np.tanh(res_t.x[0])
            nu_t = np.exp(res_t.x[1]) + 2.01
            if nu_t < 100:
                lambda_sym = 2 * sp_stats.t.cdf(
                    -np.sqrt((nu_t + 1) * (1 - rho_t) / (1 + rho_t)), df=nu_t + 1
                )
            else:
                lambda_sym = 0.0
        except Exception:
            rho_t, nu_t, lambda_sym = np.nan, np.nan, np.nan

        # Clayton copula for lower tail dep
        try:
            res_c = minimize(clayton_copula_ll, x0=[0.0], args=(u1_win, u2_win),
                             method='Nelder-Mead', options={'maxiter': 3000})
            theta_c = np.exp(res_c.x[0]) + 1e-6
            lambda_L_clay = 2**(-1 / theta_c) if theta_c > 0 else 0.0
        except Exception:
            theta_c, lambda_L_clay = np.nan, np.nan

        results.append({
            'date': dates[i],
            'lambda_L_clayton': lambda_L_clay,
            'lambda_sym_t': lambda_sym,
            'rho_t': rho_t,
            'nu_t': nu_t,
            'theta_clayton': theta_c
        })

    return pd.DataFrame(results)


# ============================================================
# Step 6: Copula-Based VaR/ES
# ============================================================
def copula_portfolio_var(u1, u2, sigma1, sigma2, mu1, mu2,
                         best_copula_result, weight1=0.5, weight2=0.5,
                         n_sim=10000, alpha_levels=[0.01, 0.05]):
    """
    Compute portfolio VaR and ES using copula simulation.

    Steps:
    1. Generate correlated uniform draws from the best copula
    2. Invert to returns using marginal distributions
    3. Compute portfolio returns
    4. Extract VaR and ES quantiles
    """
    rng = np.random.default_rng(42)

    name = best_copula_result['name']
    params = best_copula_result['params']

    # Generate copula samples
    if name == 'Gaussian':
        rho = params['rho']
        cov = np.array([[1, rho], [rho, 1]])
        z = rng.multivariate_normal([0, 0], cov, size=n_sim)
        u_sim1 = sp_stats.norm.cdf(z[:, 0])
        u_sim2 = sp_stats.norm.cdf(z[:, 1])

    elif name == 'Student-t':
        rho = params['rho']
        nu = params['nu']
        cov = np.array([[1, rho], [rho, 1]])
        # Generate from multivariate t
        z = rng.multivariate_normal([0, 0], cov, size=n_sim)
        chi2 = rng.chisquare(nu, size=n_sim)
        t_samples = z * np.sqrt(nu / chi2)[:, None]
        u_sim1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
        u_sim2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

    elif name == 'Clayton':
        theta = params['theta']
        # Clayton sampling via conditional method
        v1 = rng.uniform(size=n_sim)
        v2 = rng.uniform(size=n_sim)
        u_sim1 = v1
        u_sim2 = (v1**(-theta) * (v2**(-theta / (1 + theta)) - 1) + 1)**(-1 / theta)
        u_sim2 = np.clip(u_sim2, 1e-6, 1 - 1e-6)

    elif name == 'Gumbel':
        theta = params['theta']
        # Gumbel sampling via Marshall-Olkin method (stable distribution)
        # Use a simpler approach: generate from Gumbel via algorithm
        alpha_stable = 1.0 / theta
        # Generate stable(alpha) random variable
        V = rng.uniform(0, np.pi, size=n_sim)
        E = rng.exponential(1.0, size=n_sim)
        W = np.sin(alpha_stable * V) / (np.cos(V)**(1.0/alpha_stable))
        W *= (np.cos(V * (1 - alpha_stable)) / E)**((1 - alpha_stable) / alpha_stable)
        # Conditional on W, generate independent exponentials
        E1 = rng.exponential(1.0, size=n_sim)
        E2 = rng.exponential(1.0, size=n_sim)
        u_sim1 = np.exp(-(E1 / W)**(1.0/theta))
        u_sim2 = np.exp(-(E2 / W)**(1.0/theta))
        u_sim1 = np.clip(u_sim1, 1e-6, 1 - 1e-6)
        u_sim2 = np.clip(u_sim2, 1e-6, 1 - 1e-6)

    elif name == 'Frank':
        theta = params['theta']
        v1 = rng.uniform(size=n_sim)
        v2 = rng.uniform(size=n_sim)
        u_sim1 = v1
        u_sim2 = -np.log(1 + v2 * (np.exp(-theta) - 1) /
                         (v2 * (np.exp(-theta * v1) - 1) - np.exp(-theta * v1))) / theta
        u_sim2 = np.clip(u_sim2, 1e-6, 1 - 1e-6)

    # Invert to returns (using normal quantiles scaled by sigma)
    # Use average sigma and mu for the simulation period
    avg_sigma1 = np.mean(sigma1)
    avg_sigma2 = np.mean(sigma2)
    avg_mu1 = np.mean(mu1)
    avg_mu2 = np.mean(mu2)

    r_sim1 = sp_stats.norm.ppf(u_sim1) * avg_sigma1 + avg_mu1
    r_sim2 = sp_stats.norm.ppf(u_sim2) * avg_sigma2 + avg_mu2

    # Portfolio returns
    r_port = weight1 * r_sim1 + weight2 * r_sim2

    var_results = {}
    for alpha in alpha_levels:
        var_val = np.percentile(r_port, alpha * 100)
        es_val = np.mean(r_port[r_port <= var_val])
        var_results[f'VaR_{int(alpha*100)}pct'] = round(float(var_val), 6)
        var_results[f'ES_{int(alpha*100)}pct'] = round(float(es_val), 6)

    return var_results


def historical_var(returns, alpha_levels=[0.01, 0.05]):
    """Compute historical simulation VaR and ES."""
    results = {}
    for alpha in alpha_levels:
        var_val = np.percentile(returns, alpha * 100)
        es_val = np.mean(returns[returns <= var_val])
        results[f'VaR_{int(alpha*100)}pct'] = round(float(var_val), 6)
        results[f'ES_{int(alpha*100)}pct'] = round(float(es_val), 6)
    return results


def kupiec_test(violations, n_obs, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_obs if n_obs > 0 else 0

    if n_viol == 0 or n_viol == n_obs:
        return {'stat': 0.0, 'p_value': 1.0, 'n_violations': n_viol,
                'violation_rate': round(p_hat, 4)}

    lr = 2 * (n_viol * np.log(p_hat / alpha) +
              (n_obs - n_viol) * np.log((1 - p_hat) / (1 - alpha)))

    p_value = 1 - sp_stats.chi2.cdf(lr, df=1)

    return {'stat': round(float(lr), 4), 'p_value': round(float(p_value), 4),
            'n_violations': n_viol, 'violation_rate': round(p_hat, 4)}


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

    p01 = n01 / n0 if n0 > 0 else 0
    p11 = n11 / n1 if n1 > 0 else 0
    p_hat = (n01 + n11) / (n - 1)

    if p_hat == 0 or p_hat == 1 or p01 == 0 or p11 == 0:
        return {'stat': 0.0, 'p_value': 1.0}
    if p01 == 1 or p11 == 1:
        return {'stat': 0.0, 'p_value': 1.0}

    try:
        ll_0 = (n00 + n10) * np.log(1 - p_hat) + (n01 + n11) * np.log(p_hat)
        ll_1 = 0
        if n00 > 0: ll_1 += n00 * np.log(1 - p01)
        if n01 > 0: ll_1 += n01 * np.log(p01)
        if n10 > 0: ll_1 += n10 * np.log(1 - p11)
        if n11 > 0: ll_1 += n11 * np.log(p11)

        lr = 2 * (ll_1 - ll_0)
        p_value = 1 - sp_stats.chi2.cdf(lr, df=1)
    except (ValueError, FloatingPointError):
        lr, p_value = 0.0, 1.0

    return {'stat': round(float(lr), 4), 'p_value': round(float(p_value), 4)}


def basel_traffic_light(violation_rate, alpha):
    """Basel traffic light system."""
    ratio = violation_rate / alpha if alpha > 0 else 0
    if ratio <= 1.0:
        return 'Green'
    elif ratio <= 1.5:
        return 'Yellow'
    else:
        return 'Red'


def run_var_backtest(returns_port, var_series, alpha):
    """Run full VaR backtest: Kupiec + Christoffersen + Basel."""
    violations = (returns_port < var_series).astype(int)
    n_obs = len(returns_port)

    kupiec = kupiec_test(violations, n_obs, alpha)
    cc = christoffersen_test(violations)
    violation_rate = kupiec['violation_rate']
    traffic = basel_traffic_light(violation_rate, alpha)

    return {
        'alpha': alpha,
        'n_obs': n_obs,
        'kupiec': kupiec,
        'christoffersen': cc,
        'basel_traffic_light': traffic,
        'violation_rate': violation_rate,
        'expected_rate': alpha
    }


# ============================================================
# Step 7: Time-Varying Copula VaR (Day-by-Day)
# ============================================================
def compute_daily_copula_var(u1, u2, sigma1, sigma2, mu1, mu2,
                             dates, oos_start, copula_type='Student-t',
                             window=500, alpha_levels=[0.01, 0.05]):
    """
    Compute day-by-day copula VaR using rolling window estimation.
    Returns DataFrame with date, VaR_1pct, VaR_5pct for IS and OOS.
    """
    n = len(u1)
    results = []
    rng = np.random.default_rng(42)

    oos_idx = None
    for i, d in enumerate(dates):
        if d >= pd.Timestamp(oos_start):
            oos_idx = i
            break

    for i in range(window, n):
        u1_win = u1[i - window:i]
        u2_win = u2[i - window:i]

        # Fit Student-t copula on window
        try:
            res_t = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1_win, u2_win),
                             method='Nelder-Mead', options={'maxiter': 2000})
            rho = np.tanh(res_t.x[0])
            nu = np.exp(res_t.x[1]) + 2.01
        except Exception:
            rho, nu = 0.0, 30.0

        # Simulate from Student-t copula
        cov = np.array([[1, rho], [rho, 1]])
        z = rng.multivariate_normal([0, 0], cov, size=1000)
        chi2 = rng.chisquare(nu, size=1000)
        t_samples = z * np.sqrt(nu / chi2)[:, None]
        u_s1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
        u_s2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

        # Invert to returns using today's sigma
        r_s1 = sp_stats.norm.ppf(np.clip(u_s1, 1e-6, 1-1e-6)) * sigma1[i] + mu1[i]
        r_s2 = sp_stats.norm.ppf(np.clip(u_s2, 1e-6, 1-1e-6)) * sigma2[i] + mu2[i]
        r_port = 0.5 * r_s1 + 0.5 * r_s2

        var_1 = np.percentile(r_port, 1)
        var_5 = np.percentile(r_port, 5)
        es_1 = np.mean(r_port[r_port <= var_1])
        es_5 = np.mean(r_port[r_port <= var_5])

        period = 'OOS' if (oos_idx is not None and i >= oos_idx) else 'IS'

        results.append({
            'date': dates[i],
            'var_1pct': var_1,
            'var_5pct': var_5,
            'es_1pct': es_1,
            'es_5pct': es_5,
            'period': period
        })

    return pd.DataFrame(results)


# ============================================================
# Step 8: Descriptive Statistics
# ============================================================
def compute_descriptive_stats(returns, name):
    """Compute descriptive statistics for a return series."""
    from scipy.stats import jarque_bera, kurtosis, skew
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch

    r = returns.dropna()
    desc = {
        'name': name,
        'n_obs': len(r),
        'mean': round(float(r.mean()), 6),
        'std': round(float(r.std()), 6),
        'skew': round(float(skew(r)), 4),
        'kurtosis': round(float(kurtosis(r, fisher=True)), 4),
        'min': round(float(r.min()), 6),
        'max': round(float(r.max()), 6),
    }

    # ADF test
    adf_stat, adf_pval = adfuller(r, maxlag=20)[:2]
    desc['adf_stat'] = round(float(adf_stat), 4)
    desc['adf_pval'] = round(float(adf_pval), 6)

    # ARCH LM test
    try:
        arch_stat, arch_pval, _, _ = het_arch(r, nlags=10)
        desc['arch_lm_stat'] = round(float(arch_stat), 4)
        desc['arch_lm_pval'] = round(float(arch_pval), 6)
    except Exception:
        desc['arch_lm_stat'] = None
        desc['arch_lm_pval'] = None

    # JB test
    jb_stat, jb_pval = jarque_bera(r)
    desc['jb_stat'] = round(float(jb_stat), 2)
    desc['jb_pval'] = round(float(jb_pval), 6)

    return desc


# ============================================================
# Step 9: Plotting
# ============================================================
def plot_copula_comparison(copula_results, output_dir):
    """Plot AIC/BIC comparison for all copulas."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    names = [r['name'] for r in copula_results]
    aics = [r['AIC'] for r in copula_results]
    bics = [r['BIC'] for r in copula_results]

    colors = ['#2ecc71' if i == 0 else '#3498db' for i in range(len(names))]

    ax1.barh(names, aics, color=colors, edgecolor='black', linewidth=0.5)
    ax1.set_xlabel('AIC', fontsize=12)
    ax1.set_title('Copula Model Selection (AIC)', fontsize=14, fontweight='bold')
    ax1.invert_yaxis()
    for i, v in enumerate(aics):
        ax1.text(v + 1, i, f'{v:.1f}', va='center', fontsize=10)

    ax2.barh(names, bics, color=colors, edgecolor='black', linewidth=0.5)
    ax2.set_xlabel('BIC', fontsize=12)
    ax2.set_title('Copula Model Selection (BIC)', fontsize=14, fontweight='bold')
    ax2.invert_yaxis()
    for i, v in enumerate(bics):
        ax2.text(v + 1, i, f'{v:.1f}', va='center', fontsize=10)

    # Add tail dependence info
    info_text = "Tail Dependence:\n"
    for r in copula_results:
        info_text += f"  {r['name']}: lambda_L={r['lambda_L']:.4f}, lambda_U={r['lambda_U']:.4f}\n"

    fig.text(0.5, -0.05, info_text, ha='center', fontsize=9, style='italic',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k920_copula_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_tail_dependence(rolling_df, output_dir):
    """Plot time-varying tail dependence coefficients."""
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

    dates = pd.to_datetime(rolling_df['date'])

    # Panel 1: Clayton lower tail dependence
    ax1 = axes[0]
    ax1.plot(dates, rolling_df['lambda_L_clayton'], color='#e74c3c', linewidth=0.8, alpha=0.8)
    ax1.fill_between(dates, 0, rolling_df['lambda_L_clayton'], alpha=0.2, color='#e74c3c')
    ax1.set_ylabel('$\\lambda_L$ (Clayton)', fontsize=12)
    ax1.set_title('Lower Tail Dependence (Clayton Copula)', fontsize=14, fontweight='bold')
    ax1.axhline(y=0, color='grey', linestyle='--', alpha=0.5)

    # Crisis annotations
    crisis_periods = [
        ('2008-09', '2009-03', 'GFC'),
        ('2011-07', '2011-10', 'Debt'),
        ('2015-08', '2015-09', 'China'),
        ('2018-12', '2019-01', 'Xmas'),
        ('2020-02', '2020-04', 'COVID'),
        ('2022-01', '2022-10', 'Rates'),
    ]
    for start, end, label in crisis_periods:
        try:
            ax1.axvspan(pd.Timestamp(start), pd.Timestamp(end),
                        alpha=0.15, color='grey')
        except Exception:
            pass

    # Panel 2: Student-t symmetric tail dependence
    ax2 = axes[1]
    ax2.plot(dates, rolling_df['lambda_sym_t'], color='#2980b9', linewidth=0.8, alpha=0.8)
    ax2.fill_between(dates, 0, rolling_df['lambda_sym_t'], alpha=0.2, color='#2980b9')
    ax2.set_ylabel('$\\lambda$ (Student-t)', fontsize=12)
    ax2.set_title('Symmetric Tail Dependence (Student-t Copula)', fontsize=14, fontweight='bold')
    ax2.axhline(y=0, color='grey', linestyle='--', alpha=0.5)

    # Panel 3: Student-t rho and nu
    ax3 = axes[2]
    ax3.plot(dates, rolling_df['rho_t'], color='#8e44ad', linewidth=0.8, alpha=0.8, label='$\\rho_t$')
    ax3.set_ylabel('$\\rho_t$ (Student-t)', fontsize=12, color='#8e44ad')
    ax3.set_title('Student-t Copula Parameters', fontsize=14, fontweight='bold')
    ax3.axhline(y=0, color='grey', linestyle='--', alpha=0.5)
    ax3.legend(loc='upper left')

    ax3_twin = ax3.twinx()
    ax3_twin.plot(dates, rolling_df['nu_t'], color='#e67e22', linewidth=0.8, alpha=0.6, label='$\\nu_t$')
    ax3_twin.set_ylabel('$\\nu_t$ (df)', fontsize=12, color='#e67e22')
    ax3_twin.legend(loc='upper right')

    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax3.xaxis.set_major_locator(mdates.YearLocator(2))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k920_tail_dependence.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_copula_var(var_df, returns_port, dates, output_dir):
    """Plot copula VaR vs actual returns."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    # Align dates
    var_dates = pd.to_datetime(var_df['date'])

    # Panel 1: 1% VaR
    ax1.plot(dates, returns_port, color='grey', alpha=0.3, linewidth=0.5, label='Portfolio Returns')
    ax1.plot(var_dates, var_df['var_1pct'], color='#e74c3c', linewidth=1.0, label='Copula VaR 1%')

    # Mark violations
    var_aligned = var_df.set_index('date')['var_1pct']
    port_aligned = pd.Series(returns_port, index=dates)
    common_idx = var_aligned.index.intersection(port_aligned.index)
    violations = port_aligned[common_idx] < var_aligned[common_idx]
    viol_dates = common_idx[violations]
    ax1.scatter(viol_dates, port_aligned[viol_dates],
                color='red', s=15, zorder=5, label=f'Violations ({len(viol_dates)})')

    # OOS boundary
    ax1.axvline(x=pd.Timestamp(OOS_START), color='black', linestyle='--', linewidth=1.5, label='OOS Start')

    ax1.set_ylabel('Return', fontsize=12)
    ax1.set_title('Copula-GARCH VaR 1% Backtest (50/50 SPY/GLD)', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=9, loc='lower left')

    # Panel 2: 5% VaR
    ax2.plot(dates, returns_port, color='grey', alpha=0.3, linewidth=0.5, label='Portfolio Returns')
    ax2.plot(var_dates, var_df['var_5pct'], color='#2980b9', linewidth=1.0, label='Copula VaR 5%')

    var_5_aligned = var_df.set_index('date')['var_5pct']
    violations_5 = port_aligned[common_idx] < var_5_aligned[common_idx]
    viol_dates_5 = common_idx[violations_5]
    ax2.scatter(viol_dates_5, port_aligned[viol_dates_5],
                color='blue', s=10, zorder=5, label=f'Violations ({len(viol_dates_5)})')

    ax2.axvline(x=pd.Timestamp(OOS_START), color='black', linestyle='--', linewidth=1.5, label='OOS Start')

    ax2.set_ylabel('Return', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.set_title('Copula-GARCH VaR 5% Backtest (50/50 SPY/GLD)', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=9, loc='lower left')

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k920_copula_var.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("K920: Copula-GARCH Tail Dependence -- SPY/GLD")
    print("=" * 70)

    # ---- Fetch Data ----
    prices = fetch_data()
    returns = prices[ASSETS].pct_change().dropna()
    vix = prices['VIX'].reindex(returns.index)

    # ---- Descriptive Statistics ----
    print("\n" + "=" * 50)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 50)
    desc_stats = {}
    for asset in ASSETS:
        desc = compute_descriptive_stats(returns[asset], asset)
        desc_stats[asset] = desc
        print(f"\n{asset}:")
        for k, v in desc.items():
            if k != 'name':
                print(f"  {k}: {v}")

    # Linear correlation
    corr_full = returns[ASSETS].corr().iloc[0, 1]
    print(f"\nFull-sample Pearson correlation (SPY, GLD): {corr_full:.4f}")

    # Spearman rank correlation
    spearman_rho, spearman_p = sp_stats.spearmanr(returns['SPY'], returns['GLD'])
    print(f"Spearman rank correlation: {spearman_rho:.4f} (p={spearman_p:.4e})")

    # ---- Fit GJR-GARCH Marginals ----
    print("\n" + "=" * 50)
    print("MARGINAL MODELS (GJR-GARCH)")
    print("=" * 50)

    garch_results = {}
    std_resids = {}
    cond_vols = {}
    nus = {}

    for asset in ASSETS:
        res, cv, sr, nu = fit_gjr_garch(returns[asset], asset)
        garch_results[asset] = res
        cond_vols[asset] = cv
        std_resids[asset] = sr
        nus[asset] = nu

    # ---- PIT to Uniform ----
    print("\n" + "=" * 50)
    print("PROBABILITY INTEGRAL TRANSFORM")
    print("=" * 50)

    u = {}
    for asset in ASSETS:
        u[asset] = probability_integral_transform(std_resids[asset].values, nus[asset])
        # KS test for uniformity
        ks_stat, ks_pval = sp_stats.kstest(u[asset], 'uniform')
        print(f"{asset}: KS test for U(0,1): stat={ks_stat:.4f}, p={ks_pval:.4f}")

    u1 = u['SPY']
    u2 = u['GLD']
    dates = returns.index

    # ---- Fit All Copulas (Full Sample) ----
    print("\n" + "=" * 50)
    print("COPULA ESTIMATION (FULL SAMPLE)")
    print("=" * 50)

    copula_results = fit_all_copulas(u1, u2)

    print("\n\nCopula Ranking (by AIC):")
    print(f"{'Copula':<12} {'LL':>10} {'AIC':>10} {'BIC':>10} {'lambda_L':>10} {'lambda_U':>10}")
    print("-" * 64)
    for r in copula_results:
        print(f"{r['name']:<12} {r['log_likelihood']:>10.2f} {r['AIC']:>10.2f} "
              f"{r['BIC']:>10.2f} {r['lambda_L']:>10.4f} {r['lambda_U']:>10.4f}")

    best_copula = copula_results[0]
    print(f"\nBest copula (AIC): {best_copula['name']}")
    print(f"  Parameters: {best_copula['params']}")
    print(f"  Lower tail dep (lambda_L): {best_copula['lambda_L']:.4f}")
    print(f"  Upper tail dep (lambda_U): {best_copula['lambda_U']:.4f}")

    # ---- IS and OOS Copula Estimation ----
    print("\n" + "=" * 50)
    print("COPULA ESTIMATION (IS vs OOS)")
    print("=" * 50)

    oos_mask = dates >= pd.Timestamp(OOS_START)
    is_mask = ~oos_mask

    u1_is, u2_is = u1[is_mask], u2[is_mask]
    u1_oos, u2_oos = u1[oos_mask], u2[oos_mask]

    print(f"\nIS sample: {is_mask.sum()} days, OOS sample: {oos_mask.sum()} days")

    copula_is = fit_all_copulas(u1_is, u2_is)
    copula_oos = fit_all_copulas(u1_oos, u2_oos)

    print("\nIS Best copula:", copula_is[0]['name'], copula_is[0]['params'])
    print("OOS Best copula:", copula_oos[0]['name'], copula_oos[0]['params'])

    # ---- Rolling Copula (Time-Varying Tail Dependence) ----
    print("\n" + "=" * 50)
    print("ROLLING COPULA (TIME-VARYING TAIL DEPENDENCE)")
    print("=" * 50)

    rolling_df = rolling_copula(u1, u2, dates.tolist(), window=ROLLING_WINDOW)
    print(f"\nRolling window: {ROLLING_WINDOW} days, {len(rolling_df)} observations")

    # Summary stats of rolling tail dependence
    print(f"\nRolling lambda_L (Clayton):")
    print(f"  Mean: {rolling_df['lambda_L_clayton'].mean():.4f}")
    print(f"  Std:  {rolling_df['lambda_L_clayton'].std():.4f}")
    print(f"  Min:  {rolling_df['lambda_L_clayton'].min():.4f}")
    print(f"  Max:  {rolling_df['lambda_L_clayton'].max():.4f}")

    print(f"\nRolling lambda (Student-t, symmetric):")
    print(f"  Mean: {rolling_df['lambda_sym_t'].mean():.4f}")
    print(f"  Std:  {rolling_df['lambda_sym_t'].std():.4f}")
    print(f"  Min:  {rolling_df['lambda_sym_t'].min():.4f}")
    print(f"  Max:  {rolling_df['lambda_sym_t'].max():.4f}")

    print(f"\nRolling rho (Student-t):")
    print(f"  Mean: {rolling_df['rho_t'].mean():.4f}")
    print(f"  Std:  {rolling_df['rho_t'].std():.4f}")

    # Crisis-period tail dependence
    crisis_periods = {
        'GFC_2008': ('2008-09-01', '2009-03-31'),
        'COVID_2020': ('2020-02-01', '2020-04-30'),
        'Rate_Hike_2022': ('2022-01-01', '2022-10-31'),
    }

    crisis_tail = {}
    for name, (start, end) in crisis_periods.items():
        mask = (pd.to_datetime(rolling_df['date']) >= start) & \
               (pd.to_datetime(rolling_df['date']) <= end)
        if mask.sum() > 0:
            crisis_tail[name] = {
                'lambda_L_clayton': round(float(rolling_df.loc[mask, 'lambda_L_clayton'].mean()), 4),
                'lambda_sym_t': round(float(rolling_df.loc[mask, 'lambda_sym_t'].mean()), 4),
                'rho_t': round(float(rolling_df.loc[mask, 'rho_t'].mean()), 4),
                'n_days': int(mask.sum())
            }
            print(f"\n{name}: lambda_L={crisis_tail[name]['lambda_L_clayton']:.4f}, "
                  f"lambda_sym={crisis_tail[name]['lambda_sym_t']:.4f}, "
                  f"rho={crisis_tail[name]['rho_t']:.4f}")

    # ---- Copula VaR/ES (Day-by-Day) ----
    print("\n" + "=" * 50)
    print("COPULA-BASED VaR/ES (DAY-BY-DAY)")
    print("=" * 50)

    # Get daily mu and sigma for each asset
    sigma1_arr = cond_vols['SPY'].values
    sigma2_arr = cond_vols['GLD'].values
    mu1_arr = np.full(len(returns), float(returns['SPY'].mean()))
    mu2_arr = np.full(len(returns), float(returns['GLD'].mean()))

    # Compute daily copula VaR
    var_df = compute_daily_copula_var(
        u1, u2, sigma1_arr, sigma2_arr, mu1_arr, mu2_arr,
        dates.tolist(), OOS_START, copula_type='Student-t',
        window=ROLLING_WINDOW
    )

    # Portfolio returns (50/50)
    returns_port = 0.5 * returns['SPY'].values + 0.5 * returns['GLD'].values
    port_series = pd.Series(returns_port, index=dates)

    # Align and run backtest
    var_df_indexed = var_df.set_index('date')
    common_dates = port_series.index.intersection(var_df_indexed.index)

    port_common = port_series[common_dates].values
    var_1_common = var_df_indexed.loc[common_dates, 'var_1pct'].values
    var_5_common = var_df_indexed.loc[common_dates, 'var_5pct'].values

    # Split IS/OOS
    is_dates = common_dates[common_dates < pd.Timestamp(OOS_START)]
    oos_dates = common_dates[common_dates >= pd.Timestamp(OOS_START)]

    backtest_results = {}
    for period_name, period_dates in [('IS', is_dates), ('OOS', oos_dates)]:
        port_p = port_series[period_dates].values
        var_1_p = var_df_indexed.loc[period_dates, 'var_1pct'].values
        var_5_p = var_df_indexed.loc[period_dates, 'var_5pct'].values

        bt_1 = run_var_backtest(port_p, var_1_p, 0.01)
        bt_5 = run_var_backtest(port_p, var_5_p, 0.05)

        backtest_results[period_name] = {
            'VaR_1pct': bt_1,
            'VaR_5pct': bt_5,
            'n_days': len(period_dates)
        }

        print(f"\n{period_name} ({len(period_dates)} days):")
        print(f"  VaR 1%: violations={bt_1['violation_rate']:.4f} (expected 0.01), "
              f"Kupiec p={bt_1['kupiec']['p_value']:.4f}, "
              f"CC p={bt_1['christoffersen']['p_value']:.4f}, "
              f"Basel={bt_1['basel_traffic_light']}")
        print(f"  VaR 5%: violations={bt_5['violation_rate']:.4f} (expected 0.05), "
              f"Kupiec p={bt_5['kupiec']['p_value']:.4f}, "
              f"CC p={bt_5['christoffersen']['p_value']:.4f}, "
              f"Basel={bt_5['basel_traffic_light']}")

    # ---- Historical VaR for comparison ----
    print("\n\nHistorical Simulation VaR (for comparison):")
    hist_var_is = historical_var(port_series[is_dates].values)
    hist_var_oos = historical_var(port_series[oos_dates].values)
    print(f"  IS: VaR_1%={hist_var_is['VaR_1pct']:.6f}, ES_1%={hist_var_is['ES_1pct']:.6f}")
    print(f"  OOS: VaR_1%={hist_var_oos['VaR_1pct']:.6f}, ES_1%={hist_var_oos['ES_1pct']:.6f}")

    # ---- Copula VaR Summary ----
    copula_var_summary = copula_portfolio_var(
        u1_is, u2_is,
        sigma1_arr[is_mask], sigma2_arr[is_mask],
        mu1_arr[is_mask], mu2_arr[is_mask],
        copula_is[0]  # best IS copula
    )
    print(f"\nCopula VaR (from IS best copula simulation):")
    for k, v in copula_var_summary.items():
        print(f"  {k}: {v:.6f}")

    # ---- Generate Plots ----
    print("\n" + "=" * 50)
    print("GENERATING PLOTS")
    print("=" * 50)

    plot_copula_comparison(copula_results, OUTPUT_DIR)
    plot_tail_dependence(rolling_df, OUTPUT_DIR)
    plot_copula_var(var_df, returns_port, dates, OUTPUT_DIR)

    # ---- Compile Results ----
    print("\n" + "=" * 50)
    print("COMPILING RESULTS")
    print("=" * 50)

    # Rolling tail dep summary
    rolling_summary = {
        'lambda_L_clayton': {
            'mean': round(float(rolling_df['lambda_L_clayton'].mean()), 4),
            'std': round(float(rolling_df['lambda_L_clayton'].std()), 4),
            'min': round(float(rolling_df['lambda_L_clayton'].min()), 4),
            'max': round(float(rolling_df['lambda_L_clayton'].max()), 4),
        },
        'lambda_sym_student_t': {
            'mean': round(float(rolling_df['lambda_sym_t'].mean()), 4),
            'std': round(float(rolling_df['lambda_sym_t'].std()), 4),
            'min': round(float(rolling_df['lambda_sym_t'].min()), 4),
            'max': round(float(rolling_df['lambda_sym_t'].max()), 4),
        },
        'rho_student_t': {
            'mean': round(float(rolling_df['rho_t'].mean()), 4),
            'std': round(float(rolling_df['rho_t'].std()), 4),
        }
    }

    # GARCH params
    garch_params = {}
    for asset in ASSETS:
        res = garch_results[asset]
        garch_params[asset] = {
            'omega': round(float(res.params.get('omega', 0)), 6),
            'alpha': round(float(res.params.get('alpha[1]', 0)), 6),
            'gamma': round(float(res.params.get('gamma[1]', 0)), 6),
            'beta': round(float(res.params.get('beta[1]', 0)), 6),
            'nu': round(float(nus[asset]), 2),
            'persistence': round(float(
                res.params.get('alpha[1]', 0) +
                res.params.get('gamma[1]', 0) / 2 +
                res.params.get('beta[1]', 0)
            ), 4),
            'converged': bool(res.convergence_flag == 0)
        }

    results = {
        'experiment_id': 'K920',
        'title': 'Copula-GARCH Tail Dependence -- SPY/GLD Non-Linear Dependence Structure',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance',
        'data_period': f'{START_DATE} to {END_DATE}',
        'oos_start': OOS_START,
        'n_obs': len(returns),
        'n_is': int(is_mask.sum()),
        'n_oos': int(oos_mask.sum()),

        'descriptive_stats': desc_stats,
        'pearson_correlation': round(float(corr_full), 4),
        'spearman_correlation': {
            'rho': round(float(spearman_rho), 4),
            'p_value': round(float(spearman_p), 6)
        },

        'garch_marginals': garch_params,

        'copula_full_sample': [r for r in copula_results],
        'copula_is': [r for r in copula_is],
        'copula_oos': [r for r in copula_oos],
        'best_copula_full': copula_results[0],
        'best_copula_is': copula_is[0],
        'best_copula_oos': copula_oos[0],

        'rolling_tail_dependence': rolling_summary,
        'crisis_tail_dependence': crisis_tail,

        'var_backtest': backtest_results,
        'historical_var': {
            'IS': hist_var_is,
            'OOS': hist_var_oos
        },
        'copula_var_simulation': copula_var_summary,

        'references': [
            'Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER',
            'Joe (1997): Multivariate Models and Dependence Concepts',
            'Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives',
            'Christoffersen (1998): Evaluating Interval Forecasts, IER',
            'Cherubini, Luciano & Vecchiato (2004): Copula Methods in Finance',
        ],

        'key_findings': (
            "SPY-GLD tail dependence analysis (2005-2026): "
            "Copula-GARCH reveals the non-linear dependence structure. "
            "Full-sample best copula selected by AIC/BIC. "
            "Rolling 500-day window shows time-varying tail dependence. "
            "Crisis periods (GFC, COVID, 2022 rate hikes) analyzed separately. "
            "Copula VaR backtested with Kupiec + Christoffersen + Basel trinity "
            "for both IS and OOS periods. "
            "Key question: does lower tail dependence exist (diversification breakdown) "
            "or is it near zero (50/50 moat intact)?"
        ),

        'plots': [
            'k920_copula_comparison.png',
            'k920_tail_dependence.png',
            'k920_copula_var.png'
        ]
    }

    # Save results
    results_path = os.path.join(OUTPUT_DIR, 'k920_copula_garch_tail_dependence_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {results_path}")

    # ---- Key Findings ----
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)
    print(f"Best copula (full sample): {best_copula['name']}")
    print(f"  lambda_L (lower tail): {best_copula['lambda_L']:.4f}")
    print(f"  lambda_U (upper tail): {best_copula['lambda_U']:.4f}")
    print(f"\nBest copula (IS): {copula_is[0]['name']} - {copula_is[0]['params']}")
    print(f"Best copula (OOS): {copula_oos[0]['name']} - {copula_oos[0]['params']}")

    if best_copula['lambda_L'] < 0.05:
        print("\n=> SPY-GLD has NEGLIGIBLE lower tail dependence.")
        print("   Diversification holds even in extreme downturns.")
        print("   50/50 moat is structurally intact.")
    else:
        print(f"\n=> SPY-GLD has MEANINGFUL lower tail dependence ({best_copula['lambda_L']:.4f}).")
        print("   Diversification partially breaks down in extreme events.")

    print(f"\nPearson corr: {corr_full:.4f}, Spearman corr: {spearman_rho:.4f}")
    print("=" * 70)

    return results


if __name__ == '__main__':
    results = main()
