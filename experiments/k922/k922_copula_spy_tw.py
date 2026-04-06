#!/usr/bin/env python3
"""
K922: Copula-GARCH SPY-0050.TW — Cross-Market Tail Dependence for Taiwan Investors

Question: How does the SPY-0050.TW copula structure compare to SPY-GLD (K920)?
Is cross-market tail dependence stronger or weaker? How large is the tail risk
for Taiwan investors holding US equities?

Method:
  1. GJR-GARCH(1,1) Student-t marginals for SPY and 0050.TW
  2. PIT to uniform residuals
  3. Five copulas: Gaussian, Student-t, Clayton, Gumbel, Frank
  4. AIC/BIC model selection
  5. Tail dependence coefficients (lambda_L, lambda_U)
  6. Rolling 500-day copula for time-varying tail dependence
  7. Crisis period analysis (GFC, COVID, Rate Hike)
  8. Copula-based portfolio VaR/ES comparison: SPY/GLD vs SPY/0050.TW
  9. VaR backtesting: Kupiec + Christoffersen + Basel (IS and OOS)

Data: SPY, 0050.TW daily from yfinance, 2006-01-01 to 2026-04-04
IS: 2006-2019, OOS: 2019-2026

Prior work:
  - K920: SPY-GLD Student-t copula, rho=0.094, lambda=0.14, crisis decoupling
  - K919: SPY->Taiwan gap channel 99.7% (R^2=0.355)
  - K907: 0050.TW net receiver (-18.4%)
  - K918: SPY-GLD no cross-spillover (BEKK)

References:
  - Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER
  - Joe (1997): Multivariate Models and Dependence Concepts
  - Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives
  - Christoffersen (1998): Evaluating Interval Forecasts, IER
  - Cherubini, Luciano & Vecchiato (2004): Copula Methods in Finance

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
ASSETS = ['SPY', '0050.TW']
START_DATE = '2006-01-01'
END_DATE = '2026-04-04'
OOS_START = '2019-01-01'
ROLLING_WINDOW = 500  # for time-varying copula
N_SIM = 10000  # Monte Carlo draws for VaR
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# K920 SPY-GLD reference results
K920_REFERENCE = {
    'best_copula': 'Student-t',
    'rho': 0.094,
    'nu': 3.05,
    'lambda_L': 0.1399,
    'lambda_U': 0.1399,
    'pearson_corr': 0.0583,
    'spearman_corr': 0.0613,
    'crisis': {
        'GFC_2008': {'lambda_sym_t': 0.112, 'rho_t': 0.0795},
        'COVID_2020': {'lambda_sym_t': 0.0682, 'rho_t': -0.1474},
        'Rate_Hike_2022': {'lambda_sym_t': 0.0489, 'rho_t': 0.1943},
    },
    'copula_var': {
        'VaR_1pct': -0.019735,
        'ES_1pct': -0.023767,
        'VaR_5pct': -0.012098,
        'ES_5pct': -0.016822,
    }
}


# ============================================================
# Step 1: Data Collection
# ============================================================
def fetch_data():
    """Fetch daily prices for SPY and 0050.TW from yfinance."""
    import yfinance as yf

    # Add volpred to path for clean_tw50_data
    project_root = os.path.abspath(os.path.join(OUTPUT_DIR, '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, os.path.join(project_root, 'src'))

    from volpred.utils import clean_tw50_data

    # Download SPY
    spy_data = yf.download('SPY', start=START_DATE, end=END_DATE, auto_adjust=True)
    if isinstance(spy_data.columns, pd.MultiIndex):
        spy_prices = spy_data['Close']['SPY'] if 'SPY' in spy_data['Close'].columns else spy_data['Close'].iloc[:, 0]
    else:
        spy_prices = spy_data['Close']
    spy_prices = spy_prices.squeeze()

    # Download 0050.TW
    tw_data = yf.download('0050.TW', start=START_DATE, end=END_DATE, auto_adjust=True)
    if isinstance(tw_data.columns, pd.MultiIndex):
        tw_prices = tw_data['Close']['0050.TW'] if '0050.TW' in tw_data['Close'].columns else tw_data['Close'].iloc[:, 0]
    else:
        tw_prices = tw_data['Close']
    tw_prices = tw_prices.squeeze()

    # Clean 0050.TW data (split adjustment)
    tw_prices_clean, _ = clean_tw50_data(tw_prices)

    # Compute returns
    spy_ret = spy_prices.pct_change().dropna()
    tw_ret = tw_prices_clean.pct_change().dropna()

    # Align on common trading days
    # Use intersection of dates where both have returns
    common_dates = spy_ret.index.intersection(tw_ret.index)
    spy_ret = spy_ret.loc[common_dates]
    tw_ret = tw_ret.loc[common_dates]
    spy_prices_aligned = spy_prices.loc[common_dates]
    tw_prices_aligned = tw_prices_clean.loc[common_dates]

    print(f"SPY raw: {len(spy_prices)} days")
    print(f"0050.TW raw: {len(tw_prices)} days -> {len(tw_prices_clean)} after clean")
    print(f"Common trading days: {len(common_dates)}")
    print(f"Period: {common_dates[0].date()} to {common_dates[-1].date()}")

    return spy_ret, tw_ret, spy_prices_aligned, tw_prices_aligned, common_dates


# ============================================================
# Step 2: Descriptive Statistics
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
# Step 3: GJR-GARCH Marginal Models
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
    # Clip to avoid exact 0 or 1
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return u


# ============================================================
# Step 4: Copula Log-Likelihoods
# ============================================================
def gaussian_copula_ll(params, u1, u2):
    """Gaussian copula negative log-likelihood."""
    rho = np.tanh(params[0])
    x1 = sp_stats.norm.ppf(u1)
    x2 = sp_stats.norm.ppf(u2)
    n = len(u1)

    det = 1 - rho**2
    if det <= 0:
        return 1e10

    ll = -0.5 * n * np.log(det) - 0.5 / det * np.sum(
        rho**2 * (x1**2 + x2**2) - 2 * rho * x1 * x2
    )
    return -ll


def student_t_copula_ll(params, u1, u2):
    """Student-t copula negative log-likelihood."""
    rho = np.tanh(params[0])
    nu = np.exp(params[1]) + 2.01

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


def clayton_copula_ll(params, u1, u2):
    """Clayton copula negative log-likelihood."""
    theta = np.exp(params[0]) + 1e-6
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
    theta = np.exp(params[0]) + 1.0

    try:
        t1 = (-np.log(u1))**theta
        t2 = (-np.log(u2))**theta
        S = t1 + t2
        A = S**(1.0 / theta)
        C = np.exp(-A)

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
    """Frank copula negative log-likelihood."""
    theta = params[0]
    if abs(theta) < 1e-6:
        return 1e10

    try:
        eta = np.exp(-theta) - 1.0
        log_num = np.log(np.abs(-theta * eta)) + (-theta * (u1 + u2))
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
# Step 5: Fit All Copulas
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

    results.sort(key=lambda x: x['AIC'] if np.isfinite(x['AIC']) else 1e20)
    return results


# ============================================================
# Step 6: Rolling Window Copula (Time-Varying Tail Dependence)
# ============================================================
def rolling_copula(u1_full, u2_full, dates, window=500):
    """
    Compute rolling-window tail dependence using Student-t and Clayton copulas.
    """
    n = len(u1_full)
    results = []

    for i in range(window, n):
        u1_win = u1_full[i - window:i]
        u2_win = u2_full[i - window:i]

        # Student-t copula
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

        # Clayton copula
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

        if (i - window) % 200 == 0:
            print(f"  Rolling window {i - window + 1}/{n - window}...")

    return pd.DataFrame(results)


# ============================================================
# Step 7: Crisis Period Analysis
# ============================================================
def analyze_crisis_periods(u1, u2, dates):
    """Analyze copula during specific crisis periods."""
    crisis_periods = {
        'GFC_2008': ('2008-09-01', '2009-03-31'),
        'COVID_2020': ('2020-02-01', '2020-04-30'),
        'Rate_Hike_2022': ('2022-01-01', '2022-10-31'),
    }

    crisis_results = {}
    for crisis_name, (start, end) in crisis_periods.items():
        mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
        if mask.sum() < 20:
            print(f"  {crisis_name}: too few observations ({mask.sum()}), skipping")
            crisis_results[crisis_name] = None
            continue

        u1_cr = u1[mask]
        u2_cr = u2[mask]

        # Student-t copula
        try:
            res_t = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1_cr, u2_cr),
                             method='Nelder-Mead', options={'maxiter': 5000})
            rho_cr = np.tanh(res_t.x[0])
            nu_cr = np.exp(res_t.x[1]) + 2.01
            if nu_cr < 100:
                lambda_sym_cr = 2 * sp_stats.t.cdf(
                    -np.sqrt((nu_cr + 1) * (1 - rho_cr) / (1 + rho_cr)), df=nu_cr + 1
                )
            else:
                lambda_sym_cr = 0.0
        except Exception:
            rho_cr, nu_cr, lambda_sym_cr = np.nan, np.nan, np.nan

        # Clayton copula
        try:
            res_c = minimize(clayton_copula_ll, x0=[0.0], args=(u1_cr, u2_cr),
                             method='Nelder-Mead', options={'maxiter': 5000})
            theta_cr = np.exp(res_c.x[0]) + 1e-6
            lambda_L_cr = 2**(-1 / theta_cr) if theta_cr > 0 else 0.0
        except Exception:
            lambda_L_cr = np.nan

        crisis_results[crisis_name] = {
            'lambda_L_clayton': round(float(lambda_L_cr), 4) if not np.isnan(lambda_L_cr) else None,
            'lambda_sym_t': round(float(lambda_sym_cr), 4) if not np.isnan(lambda_sym_cr) else None,
            'rho_t': round(float(rho_cr), 4) if not np.isnan(rho_cr) else None,
            'n_days': int(mask.sum()),
        }
        print(f"  {crisis_name}: rho={rho_cr:.4f}, lambda_sym={lambda_sym_cr:.4f}, n={mask.sum()}")

    return crisis_results


# ============================================================
# Step 8: Copula VaR/ES Simulation
# ============================================================
def copula_portfolio_var(best_copula_result, sigma1, sigma2, mu1, mu2,
                         weight1=0.5, weight2=0.5,
                         n_sim=10000, alpha_levels=[0.01, 0.05]):
    """Compute portfolio VaR and ES using copula simulation."""
    rng = np.random.default_rng(42)

    name = best_copula_result['name']
    params = best_copula_result['params']

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
        z = rng.multivariate_normal([0, 0], cov, size=n_sim)
        chi2 = rng.chisquare(nu, size=n_sim)
        t_samples = z * np.sqrt(nu / chi2)[:, None]
        u_sim1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
        u_sim2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

    elif name == 'Clayton':
        theta = params['theta']
        v1 = rng.uniform(size=n_sim)
        v2 = rng.uniform(size=n_sim)
        u_sim1 = v1
        u_sim2 = (v1**(-theta) * (v2**(-theta / (1 + theta)) - 1) + 1)**(-1 / theta)
        u_sim2 = np.clip(u_sim2, 1e-6, 1 - 1e-6)

    elif name == 'Gumbel':
        theta = params['theta']
        alpha_stable = 1.0 / theta
        V = rng.uniform(0, np.pi, size=n_sim)
        E = rng.exponential(1.0, size=n_sim)
        W = np.sin(alpha_stable * V) / (np.cos(V)**(1.0/alpha_stable))
        W *= (np.cos(V * (1 - alpha_stable)) / E)**((1 - alpha_stable) / alpha_stable)
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

    # Invert to returns
    avg_sigma1 = np.mean(sigma1)
    avg_sigma2 = np.mean(sigma2)
    avg_mu1 = np.mean(mu1)
    avg_mu2 = np.mean(mu2)

    r_sim1 = sp_stats.norm.ppf(u_sim1) * avg_sigma1 + avg_mu1
    r_sim2 = sp_stats.norm.ppf(u_sim2) * avg_sigma2 + avg_mu2

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


# ============================================================
# Step 9: VaR Backtesting
# ============================================================
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
# Step 10: Day-by-Day Copula VaR
# ============================================================
def compute_daily_copula_var(u1, u2, sigma1, sigma2, mu1, mu2,
                             dates, oos_start, copula_type='Student-t',
                             window=500, alpha_levels=[0.01, 0.05]):
    """Compute day-by-day copula VaR using rolling window estimation."""
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

        try:
            res_t = minimize(student_t_copula_ll, x0=[0.0, 1.0], args=(u1_win, u2_win),
                             method='Nelder-Mead', options={'maxiter': 2000})
            rho = np.tanh(res_t.x[0])
            nu = np.exp(res_t.x[1]) + 2.01
        except Exception:
            rho, nu = 0.0, 30.0

        # Simulate
        cov = np.array([[1, rho], [rho, 1]])
        z = rng.multivariate_normal([0, 0], cov, size=1000)
        chi2 = rng.chisquare(nu, size=1000)
        t_samples = z * np.sqrt(nu / chi2)[:, None]
        u_s1 = sp_stats.t.cdf(t_samples[:, 0], df=nu)
        u_s2 = sp_stats.t.cdf(t_samples[:, 1], df=nu)

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
# Step 11: Plotting
# ============================================================
def plot_copula_comparison(copula_results_tw, output_dir):
    """Plot AIC/BIC comparison for SPY/0050.TW copulas."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    names = [r['name'] for r in copula_results_tw]
    aics = [r['AIC'] for r in copula_results_tw]
    bics = [r['BIC'] for r in copula_results_tw]

    colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(names))]

    ax1.barh(names, aics, color=colors, edgecolor='black', linewidth=0.5)
    ax1.set_xlabel('AIC', fontsize=12)
    ax1.set_title('SPY-0050.TW Copula Selection (AIC)', fontsize=14, fontweight='bold')
    ax1.invert_yaxis()
    for i, v in enumerate(aics):
        ax1.text(v + 1 if v < 0 else v - abs(v)*0.1, i, f'{v:.1f}', va='center', fontsize=10)

    ax2.barh(names, bics, color=colors, edgecolor='black', linewidth=0.5)
    ax2.set_xlabel('BIC', fontsize=12)
    ax2.set_title('SPY-0050.TW Copula Selection (BIC)', fontsize=14, fontweight='bold')
    ax2.invert_yaxis()
    for i, v in enumerate(bics):
        ax2.text(v + 1 if v < 0 else v - abs(v)*0.1, i, f'{v:.1f}', va='center', fontsize=10)

    info_text = "Tail Dependence:\n"
    for r in copula_results_tw:
        info_text += f"  {r['name']}: lambda_L={r['lambda_L']:.4f}, lambda_U={r['lambda_U']:.4f}\n"

    fig.text(0.5, -0.05, info_text, ha='center', fontsize=9, style='italic',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k922_copula_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_tail_dependence(rolling_df, output_dir):
    """Plot time-varying tail dependence coefficients."""
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

    dates = pd.to_datetime(rolling_df['date'])

    # Panel 1: Clayton lower tail
    ax1 = axes[0]
    ax1.plot(dates, rolling_df['lambda_L_clayton'], color='#e74c3c', linewidth=0.8, alpha=0.8)
    ax1.fill_between(dates, 0, rolling_df['lambda_L_clayton'], alpha=0.2, color='#e74c3c')
    ax1.set_ylabel('$\\lambda_L$ (Clayton)', fontsize=12)
    ax1.set_title('SPY-0050.TW Lower Tail Dependence (Clayton)', fontsize=14, fontweight='bold')
    ax1.axhline(y=0, color='grey', linestyle='--', alpha=0.5)

    crisis_periods = [
        ('2008-09', '2009-03', 'GFC'),
        ('2011-07', '2011-10', 'Debt'),
        ('2015-08', '2015-09', 'China'),
        ('2018-12', '2019-01', 'Xmas'),
        ('2020-02', '2020-04', 'COVID'),
        ('2022-01', '2022-10', 'Rates'),
    ]
    for start, end, label in crisis_periods:
        for ax in axes:
            try:
                ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.15, color='grey')
            except Exception:
                pass

    # Panel 2: Student-t symmetric tail
    ax2 = axes[1]
    ax2.plot(dates, rolling_df['lambda_sym_t'], color='#2980b9', linewidth=0.8, alpha=0.8)
    ax2.fill_between(dates, 0, rolling_df['lambda_sym_t'], alpha=0.2, color='#2980b9')
    ax2.set_ylabel('$\\lambda$ (Student-t)', fontsize=12)
    ax2.set_title('SPY-0050.TW Symmetric Tail Dependence (Student-t)', fontsize=14, fontweight='bold')
    ax2.axhline(y=0, color='grey', linestyle='--', alpha=0.5)

    # Panel 3: rho and nu
    ax3 = axes[2]
    ax3.plot(dates, rolling_df['rho_t'], color='#8e44ad', linewidth=0.8, alpha=0.8, label='$\\rho_t$')
    ax3.set_ylabel('$\\rho_t$', fontsize=12, color='#8e44ad')
    ax3.set_title('SPY-0050.TW Student-t Copula Parameters', fontsize=14, fontweight='bold')
    ax3.axhline(y=0, color='grey', linestyle='--', alpha=0.5)
    ax3.legend(loc='upper left')

    ax3_twin = ax3.twinx()
    ax3_twin.plot(dates, rolling_df['nu_t'], color='#e67e22', linewidth=0.8, alpha=0.6, label='$\\nu_t$')
    ax3_twin.set_ylabel('$\\nu_t$ (df)', fontsize=12, color='#e67e22')
    ax3_twin.legend(loc='upper right')

    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax3.xaxis.set_major_locator(mdates.YearLocator(2))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k922_tail_dependence.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_crisis_comparison(crisis_tw, crisis_gld, output_dir):
    """Plot crisis-period tail dependence comparison: SPY/TW vs SPY/GLD."""
    crises = ['GFC_2008', 'COVID_2020', 'Rate_Hike_2022']
    labels = ['GFC 2008', 'COVID 2020', 'Rate Hike 2022']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    x = np.arange(len(crises))
    width = 0.35

    # Panel 1: lambda_sym_t
    tw_vals = []
    gld_vals = []
    for c in crises:
        tw_val = crisis_tw.get(c, {})
        gld_val = crisis_gld.get(c, {})
        tw_vals.append(tw_val.get('lambda_sym_t', 0) if tw_val else 0)
        gld_vals.append(gld_val.get('lambda_sym_t', 0) if gld_val else 0)

    bars1 = ax1.bar(x - width/2, tw_vals, width, label='SPY-0050.TW', color='#e74c3c', alpha=0.8)
    bars2 = ax1.bar(x + width/2, gld_vals, width, label='SPY-GLD (K920)', color='#2ecc71', alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel('$\\lambda$ (Student-t)', fontsize=12)
    ax1.set_title('Crisis Tail Dependence Comparison', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)

    for bar in bars1:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
                 f'{bar.get_height():.3f}', ha='center', fontsize=9)
    for bar in bars2:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
                 f'{bar.get_height():.3f}', ha='center', fontsize=9)

    # Panel 2: rho_t
    tw_rho = []
    gld_rho = []
    for c in crises:
        tw_val = crisis_tw.get(c, {})
        gld_val = crisis_gld.get(c, {})
        tw_rho.append(tw_val.get('rho_t', 0) if tw_val else 0)
        gld_rho.append(gld_val.get('rho_t', 0) if gld_val else 0)

    bars3 = ax2.bar(x - width/2, tw_rho, width, label='SPY-0050.TW', color='#e74c3c', alpha=0.8)
    bars4 = ax2.bar(x + width/2, gld_rho, width, label='SPY-GLD (K920)', color='#2ecc71', alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel('$\\rho_t$ (Student-t)', fontsize=12)
    ax2.set_title('Crisis Copula Correlation Comparison', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(axis='y', alpha=0.3)
    ax2.axhline(y=0, color='black', linestyle='--', linewidth=0.5)

    for bar in bars3:
        val = bar.get_height()
        y_pos = val + 0.005 if val >= 0 else val - 0.02
        ax2.text(bar.get_x() + bar.get_width()/2, y_pos,
                 f'{val:.3f}', ha='center', fontsize=9)
    for bar in bars4:
        val = bar.get_height()
        y_pos = val + 0.005 if val >= 0 else val - 0.02
        ax2.text(bar.get_x() + bar.get_width()/2, y_pos,
                 f'{val:.3f}', ha='center', fontsize=9)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k922_crisis_analysis.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_copula_var(var_df, returns_port, dates, output_dir):
    """Plot copula VaR vs actual returns for SPY/0050.TW portfolio."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

    var_dates = pd.to_datetime(var_df['date'])

    # Panel 1: 1% VaR
    ax1.plot(dates, returns_port, color='grey', alpha=0.3, linewidth=0.5, label='Portfolio Returns')
    ax1.plot(var_dates, var_df['var_1pct'], color='#e74c3c', linewidth=1.0, label='Copula VaR 1%')

    var_aligned = var_df.set_index('date')['var_1pct']
    port_aligned = pd.Series(returns_port.values, index=dates)
    common_idx = var_aligned.index.intersection(port_aligned.index)
    violations = port_aligned[common_idx] < var_aligned[common_idx]
    viol_dates = common_idx[violations]
    ax1.scatter(viol_dates, port_aligned[viol_dates],
                color='red', s=15, zorder=5, label=f'Violations ({len(viol_dates)})')

    ax1.axvline(x=pd.Timestamp(OOS_START), color='black', linestyle='--', linewidth=1.5, label='OOS Start')
    ax1.set_ylabel('Return', fontsize=12)
    ax1.set_title('Copula-GARCH VaR 1% Backtest (50/50 SPY/0050.TW)', fontsize=14, fontweight='bold')
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
    ax2.set_title('Copula-GARCH VaR 5% Backtest (50/50 SPY/0050.TW)', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=9, loc='lower left')

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))

    plt.tight_layout()
    path = os.path.join(output_dir, 'k922_copula_var.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("K922: Copula-GARCH SPY-0050.TW Cross-Market Tail Dependence")
    print("=" * 70)

    # ---- Step 1: Data ----
    print("\n--- Step 1: Data Collection ---")
    spy_ret, tw_ret, spy_prices, tw_prices, dates = fetch_data()

    # ---- Step 2: Descriptive Statistics ----
    print("\n--- Step 2: Descriptive Statistics ---")
    desc_spy = compute_descriptive_stats(spy_ret, 'SPY')
    desc_tw = compute_descriptive_stats(tw_ret, '0050.TW')

    for name, desc in [('SPY', desc_spy), ('0050.TW', desc_tw)]:
        print(f"\n{name}:")
        print(f"  N={desc['n_obs']}, mean={desc['mean']:.6f}, std={desc['std']:.6f}")
        print(f"  skew={desc['skew']:.4f}, kurtosis={desc['kurtosis']:.4f}")
        print(f"  ADF={desc['adf_stat']:.4f} (p={desc['adf_pval']:.6f})")
        print(f"  ARCH LM={desc['arch_lm_stat']}, JB={desc['jb_stat']}")

    # Correlation
    pearson_corr = float(np.corrcoef(spy_ret.values, tw_ret.values)[0, 1])
    spearman_rho, spearman_p = sp_stats.spearmanr(spy_ret.values, tw_ret.values)
    print(f"\nPearson correlation: {pearson_corr:.4f}")
    print(f"Spearman correlation: {spearman_rho:.4f} (p={spearman_p:.6f})")

    # ---- Step 3: GJR-GARCH Marginals ----
    print("\n--- Step 3: GJR-GARCH Marginals ---")
    res_spy, sigma_spy, std_resid_spy, nu_spy = fit_gjr_garch(spy_ret, 'SPY')
    res_tw, sigma_tw, std_resid_tw, nu_tw = fit_gjr_garch(tw_ret, '0050.TW')

    # PIT
    u_spy = probability_integral_transform(std_resid_spy.values, nu_spy)
    u_tw = probability_integral_transform(std_resid_tw.values, nu_tw)

    # KS test for uniformity
    ks_spy = sp_stats.kstest(u_spy, 'uniform')
    ks_tw = sp_stats.kstest(u_tw, 'uniform')
    print(f"\nKS test for PIT uniformity:")
    print(f"  SPY: stat={ks_spy.statistic:.4f}, p={ks_spy.pvalue:.4f}")
    print(f"  0050.TW: stat={ks_tw.statistic:.4f}, p={ks_tw.pvalue:.4f}")

    # ---- Step 4: Split IS/OOS ----
    dates_arr = dates.values if hasattr(dates, 'values') else np.array(dates)
    oos_mask = dates >= pd.Timestamp(OOS_START)
    is_mask = ~oos_mask

    n_is = int(is_mask.sum())
    n_oos = int(oos_mask.sum())
    print(f"\nIS: {n_is} days, OOS: {n_oos} days")

    # ---- Step 5: Copula Estimation (Full, IS, OOS) ----
    print("\n--- Step 5a: Full-Sample Copula Estimation ---")
    copula_full = fit_all_copulas(u_spy, u_tw)

    print("\n--- Step 5b: In-Sample Copula Estimation ---")
    copula_is = fit_all_copulas(u_spy[is_mask], u_tw[is_mask])

    print("\n--- Step 5c: Out-of-Sample Copula Estimation ---")
    copula_oos = fit_all_copulas(u_spy[oos_mask], u_tw[oos_mask])

    best_full = copula_full[0]
    best_is = copula_is[0]
    best_oos = copula_oos[0]

    print(f"\n*** Best Full-Sample: {best_full['name']} ***")
    print(f"    params={best_full['params']}")
    print(f"    lambda_L={best_full['lambda_L']:.4f}, lambda_U={best_full['lambda_U']:.4f}")
    print(f"    AIC={best_full['AIC']:.2f}")

    # ---- Step 6: Rolling Copula ----
    print("\n--- Step 6: Rolling Window Copula ---")
    rolling_df = rolling_copula(u_spy, u_tw, dates, window=ROLLING_WINDOW)

    rolling_stats = {
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

    print(f"\nRolling tail dependence statistics:")
    print(f"  Clayton lambda_L: mean={rolling_stats['lambda_L_clayton']['mean']:.4f}, "
          f"std={rolling_stats['lambda_L_clayton']['std']:.4f}")
    print(f"  Student-t lambda: mean={rolling_stats['lambda_sym_student_t']['mean']:.4f}, "
          f"std={rolling_stats['lambda_sym_student_t']['std']:.4f}")
    print(f"  Student-t rho: mean={rolling_stats['rho_student_t']['mean']:.4f}")

    # ---- Step 7: Crisis Analysis ----
    print("\n--- Step 7: Crisis Period Analysis ---")
    crisis_results = analyze_crisis_periods(u_spy, u_tw, dates)

    # ---- Step 8: Portfolio VaR ----
    print("\n--- Step 8: Portfolio VaR/ES ---")
    # 50/50 SPY/0050.TW portfolio
    returns_port = 0.5 * spy_ret.values + 0.5 * tw_ret.values

    # Historical VaR (IS, OOS)
    hist_var_is = historical_var(returns_port[is_mask])
    hist_var_oos = historical_var(returns_port[oos_mask])
    print(f"\nHistorical VaR (IS): {hist_var_is}")
    print(f"Historical VaR (OOS): {hist_var_oos}")

    # Copula VaR
    mu_spy = spy_ret.values
    mu_tw = tw_ret.values

    copula_var_result = copula_portfolio_var(
        best_full, sigma_spy.values, sigma_tw.values,
        mu_spy, mu_tw, weight1=0.5, weight2=0.5, n_sim=N_SIM
    )
    print(f"Copula VaR (simulation): {copula_var_result}")

    # ---- Step 9: Daily Copula VaR + Backtest ----
    print("\n--- Step 9: Daily Copula VaR Backtest ---")
    var_df = compute_daily_copula_var(
        u_spy, u_tw, sigma_spy.values, sigma_tw.values,
        mu_spy, mu_tw, dates, OOS_START, window=ROLLING_WINDOW
    )

    # Backtest
    var_backtest_results = {}
    for period_name, period_mask_name in [('IS', 'IS'), ('OOS', 'OOS')]:
        var_period = var_df[var_df['period'] == period_mask_name]
        if len(var_period) == 0:
            continue

        var_dates_period = pd.DatetimeIndex(var_period['date'].values)
        port_period = pd.Series(returns_port, index=dates)
        common = var_dates_period.intersection(port_period.index)

        if len(common) < 10:
            continue

        port_vals = port_period[common].values
        var_1_vals = var_period.set_index('date').loc[common, 'var_1pct'].values
        var_5_vals = var_period.set_index('date').loc[common, 'var_5pct'].values

        bt_1 = run_var_backtest(port_vals, var_1_vals, 0.01)
        bt_5 = run_var_backtest(port_vals, var_5_vals, 0.05)

        var_backtest_results[period_name] = {
            'VaR_1pct': bt_1,
            'VaR_5pct': bt_5,
            'n_days': len(common)
        }

        print(f"\n{period_name} VaR Backtest (n={len(common)}):")
        print(f"  1%: violations={bt_1['kupiec']['n_violations']}, "
              f"rate={bt_1['violation_rate']:.4f}, Basel={bt_1['basel_traffic_light']}")
        print(f"  5%: violations={bt_5['kupiec']['n_violations']}, "
              f"rate={bt_5['violation_rate']:.4f}, Basel={bt_5['basel_traffic_light']}")

    # ---- Step 10: K920 Comparison Table ----
    print("\n--- Step 10: Comparison with K920 (SPY-GLD) ---")
    comparison = {
        'metric': {},
        'SPY_GLD_K920': K920_REFERENCE,
        'SPY_0050TW_K922': {
            'best_copula': best_full['name'],
            'rho': best_full['params'].get('rho', None),
            'nu': best_full['params'].get('nu', None),
            'lambda_L': best_full['lambda_L'],
            'lambda_U': best_full['lambda_U'],
            'pearson_corr': round(pearson_corr, 4),
            'spearman_corr': round(float(spearman_rho), 4),
        }
    }

    print(f"\n{'Metric':<25} {'SPY-GLD (K920)':<20} {'SPY-0050.TW (K922)':<20}")
    print("-" * 65)
    print(f"{'Best Copula':<25} {K920_REFERENCE['best_copula']:<20} {best_full['name']:<20}")
    print(f"{'rho':<25} {K920_REFERENCE['rho']:<20.4f} {best_full['params'].get('rho', 0):<20.4f}")
    rho_tw = best_full['params'].get('rho', 0)
    rho_gld = K920_REFERENCE['rho']
    print(f"{'lambda_L':<25} {K920_REFERENCE['lambda_L']:<20.4f} {best_full['lambda_L']:<20.4f}")
    print(f"{'lambda_U':<25} {K920_REFERENCE['lambda_U']:<20.4f} {best_full['lambda_U']:<20.4f}")
    print(f"{'Pearson corr':<25} {K920_REFERENCE['pearson_corr']:<20.4f} {pearson_corr:<20.4f}")
    print(f"{'Spearman corr':<25} {K920_REFERENCE['spearman_corr']:<20.4f} {spearman_rho:<20.4f}")
    print(f"{'Copula VaR 1%':<25} {K920_REFERENCE['copula_var']['VaR_1pct']:<20.6f} {copula_var_result['VaR_1pct']:<20.6f}")
    print(f"{'Copula ES 1%':<25} {K920_REFERENCE['copula_var']['ES_1pct']:<20.6f} {copula_var_result['ES_1pct']:<20.6f}")

    # ---- Step 11: Plots ----
    print("\n--- Step 11: Generating Plots ---")
    plot_copula_comparison(copula_full, OUTPUT_DIR)
    plot_tail_dependence(rolling_df, OUTPUT_DIR)
    plot_crisis_comparison(crisis_results, K920_REFERENCE['crisis'], OUTPUT_DIR)
    plot_copula_var(var_df, pd.Series(returns_port, index=dates), dates, OUTPUT_DIR)

    # ---- Step 12: GARCH params for results ----
    garch_params = {}
    for name, res_obj in [('SPY', res_spy), ('0050.TW', res_tw)]:
        garch_params[name] = {
            'omega': round(float(res_obj.params.get('omega', 0)), 6),
            'alpha': round(float(res_obj.params.get('alpha[1]', 0)), 6),
            'gamma': round(float(res_obj.params.get('gamma[1]', 0)), 6),
            'beta': round(float(res_obj.params.get('beta[1]', 0)), 6),
            'nu': round(float(res_obj.params.get('nu', 30)), 2),
            'persistence': round(float(
                res_obj.params.get('alpha[1]', 0)
                + res_obj.params.get('gamma[1]', 0) / 2
                + res_obj.params.get('beta[1]', 0)
            ), 4),
            'converged': bool(res_obj.convergence_flag == 0)
        }

    # ---- Step 13: Save Results ----
    print("\n--- Step 13: Saving Results ---")

    # Determine key finding text
    finding_parts = []
    finding_parts.append(
        f"SPY-0050.TW copula analysis (2006-2026, {len(spy_ret)} common trading days): "
        f"Best copula = {best_full['name']} (AIC={best_full['AIC']:.1f}). "
    )
    if best_full['name'] == 'Student-t':
        finding_parts.append(
            f"Student-t copula: rho={best_full['params']['rho']:.4f} "
            f"(vs SPY-GLD {K920_REFERENCE['rho']:.4f}), "
            f"nu={best_full['params']['nu']:.2f} "
            f"(vs SPY-GLD {K920_REFERENCE.get('nu', 3.05):.2f}), "
            f"lambda={best_full['lambda_L']:.4f} "
            f"(vs SPY-GLD {K920_REFERENCE['lambda_L']:.4f}). "
        )
    else:
        finding_parts.append(
            f"Best copula params: {best_full['params']}. "
            f"lambda_L={best_full['lambda_L']:.4f}, lambda_U={best_full['lambda_U']:.4f} "
            f"(vs SPY-GLD lambda={K920_REFERENCE['lambda_L']:.4f}). "
        )
    finding_parts.append(
        f"Pearson corr={pearson_corr:.4f} (vs SPY-GLD {K920_REFERENCE['pearson_corr']:.4f}). "
    )
    finding_parts.append(
        f"Rolling Student-t lambda mean={rolling_stats['lambda_sym_student_t']['mean']:.4f}. "
    )
    # Crisis findings
    for crisis_name in ['GFC_2008', 'COVID_2020', 'Rate_Hike_2022']:
        tw_cr = crisis_results.get(crisis_name)
        gld_cr = K920_REFERENCE['crisis'].get(crisis_name)
        if tw_cr and gld_cr:
            finding_parts.append(
                f"{crisis_name}: SPY-TW lambda={tw_cr.get('lambda_sym_t', 'N/A')}, "
                f"rho={tw_cr.get('rho_t', 'N/A')} "
                f"(vs SPY-GLD lambda={gld_cr['lambda_sym_t']}, rho={gld_cr['rho_t']}). "
            )
    finding_parts.append(
        f"Copula VaR 1% (50/50 SPY/TW): {copula_var_result['VaR_1pct']:.6f} "
        f"(vs SPY/GLD: {K920_REFERENCE['copula_var']['VaR_1pct']:.6f})."
    )

    key_findings = ''.join(finding_parts)

    results = {
        'experiment_id': 'K922',
        'title': 'Copula-GARCH SPY-0050.TW Cross-Market Tail Dependence',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance',
        'data_period': f'{dates[0].strftime("%Y-%m-%d")} to {dates[-1].strftime("%Y-%m-%d")}',
        'oos_start': OOS_START,
        'n_obs': len(spy_ret),
        'n_is': n_is,
        'n_oos': n_oos,
        'descriptive_stats': {
            'SPY': desc_spy,
            '0050.TW': desc_tw,
        },
        'pearson_correlation': round(pearson_corr, 4),
        'spearman_correlation': {
            'rho': round(float(spearman_rho), 4),
            'p_value': round(float(spearman_p), 6),
        },
        'pit_uniformity': {
            'SPY': {'ks_stat': round(float(ks_spy.statistic), 4),
                     'ks_pval': round(float(ks_spy.pvalue), 4)},
            '0050.TW': {'ks_stat': round(float(ks_tw.statistic), 4),
                         'ks_pval': round(float(ks_tw.pvalue), 4)},
        },
        'garch_marginals': garch_params,
        'copula_full_sample': copula_full,
        'copula_is': copula_is,
        'copula_oos': copula_oos,
        'best_copula_full': best_full,
        'best_copula_is': best_is,
        'best_copula_oos': best_oos,
        'rolling_tail_dependence': rolling_stats,
        'crisis_tail_dependence': crisis_results,
        'var_backtest': var_backtest_results,
        'historical_var': {
            'IS': hist_var_is,
            'OOS': hist_var_oos,
        },
        'copula_var_simulation': copula_var_result,
        'comparison_with_k920': comparison,
        'references': [
            'Patton (2006): Modelling Asymmetric Exchange Rate Dependence, IER',
            'Joe (1997): Multivariate Models and Dependence Concepts',
            'Kupiec (1995): Techniques for Verifying VaR, Journal of Derivatives',
            'Christoffersen (1998): Evaluating Interval Forecasts, IER',
            'Cherubini, Luciano & Vecchiato (2004): Copula Methods in Finance',
        ],
        'key_findings': key_findings,
        'plots': [
            'k922_copula_comparison.png',
            'k922_tail_dependence.png',
            'k922_crisis_analysis.png',
            'k922_copula_var.png',
        ]
    }

    results_path = os.path.join(OUTPUT_DIR, 'k922_copula_spy_tw_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    print("\n" + "=" * 70)
    print("K922 COMPLETE")
    print("=" * 70)
    print(f"\nKey Finding Summary:")
    print(key_findings)

    return results


if __name__ == '__main__':
    main()
