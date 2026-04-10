"""
K1031: Bayesian SSVS for ARX-GARCH (Joint Variable Selection)
============================================================
Based on So, Chen, Liu (2006) "Best Subset Selection of Autoregressive Models
with Exogenous Variables and Generalized Autoregressive Conditional
Heteroscedasticity Errors." JRSS-C, 55(2), 201-224.

Method: Joint MCMC over binary inclusion indicators δ^m (mean eq) and δ^v (variance eq)
       simultaneously. Spike-and-slab priors for coefficients.

Data: SPY 2005-2026, yfinance
  In-sample: 2005-2018 (~3500 obs)
  OOS: 2019-2026

Candidate variables:
  Mean: VIX_change, VIX_level, TLT_return, CREDIT_spread (HYG)
  Variance: VIX², VIX9D², RV_22d, VIX_change²

Evaluation target: r² (squared daily return) per preamble rule for GARCH-type models
QLIKE = mean(r²/σ² - log(r²/σ²) - 1), proxy-robust (Patton 2011)

Prior knowledge:
  K433: Mean eq SSVS → NULL (all PIP < 0.5)
  K484: Variance eq SSVS → 4/5 internal PIP=1.0, QLIKE +7.43%
  K1013: Two-stage SSVS for GJR residual → NULL
  K821: Variance eq external → 0/8 PIP > 0.5

References:
  So, Chen, Liu (2006) JRSS-C 55(2) 201-224
  Patton (2011) "Volatility Forecast Comparison" JFE
  George & McCulloch (1993) JASA - original SSVS
  Harvey (2016) - DM test threshold t>3.0

seed = 42
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import os
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTDIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K1031: Bayesian SSVS ARX-GARCH (So, Chen, Liu 2006)")
print("=" * 60)

print("\n[1/6] Downloading data...")
tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX9D': '^VIX9D',
    'TLT': 'TLT',
    'HYG': 'HYG'
}

data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2004-06-01', end='2026-04-10', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df
        print(f"  {name}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {name}: FAILED - {e}")

# Build aligned DataFrame
spy = data['SPY'][['Close']].rename(columns={'Close': 'SPY_close'})
vix = data['VIX'][['Close']].rename(columns={'Close': 'VIX'})
tlt = data['TLT'][['Close']].rename(columns={'Close': 'TLT_close'})
hyg = data['HYG'][['Close']].rename(columns={'Close': 'HYG_close'})

df = spy.join(vix, how='inner').join(tlt, how='inner').join(hyg, how='inner')

# VIX9D has shorter history - join separately
if 'VIX9D' in data and len(data['VIX9D']) > 100:
    vix9d = data['VIX9D'][['Close']].rename(columns={'Close': 'VIX9D'})
    df = df.join(vix9d, how='left')
    # Forward fill VIX9D for missing dates, then drop remaining NaN
    df['VIX9D'] = df['VIX9D'].ffill()
else:
    print("  WARNING: VIX9D data insufficient, using VIX as proxy")
    df['VIX9D'] = df['VIX']

# Compute returns and variables
df['r'] = np.log(df['SPY_close'] / df['SPY_close'].shift(1))
df['r_sq'] = df['r'] ** 2  # evaluation target

# Mean equation candidates (lagged by 1)
df['VIX_change'] = np.log(df['VIX'] / df['VIX'].shift(1))  # Δln(VIX)
df['VIX_level'] = np.log(df['VIX'])  # ln(VIX)
df['TLT_return'] = np.log(df['TLT_close'] / df['TLT_close'].shift(1))
df['CREDIT_spread'] = np.log(df['HYG_close'] / df['HYG_close'].shift(1))  # HYG return as proxy

# Variance equation candidates (lagged by 1)
df['VIX_sq'] = (df['VIX'] / 100) ** 2  # VIX² scaled
df['VIX9D_sq'] = (df['VIX9D'] / 100) ** 2  # VIX9D²
# RV_22d: 22-day realized variance from daily returns
df['RV_22d'] = df['r'].rolling(22).var() * 252  # annualized
df['VIX_change_sq'] = df['VIX_change'] ** 2

# Drop NaN
df = df.dropna()
print(f"\n  Total aligned obs: {len(df)}, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Split
is_mask = df.index < '2019-01-01'
oos_mask = df.index >= '2019-01-01'
df_is = df[is_mask].copy()
df_oos = df[oos_mask].copy()
print(f"  In-sample: {len(df_is)} obs ({df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {len(df_oos)} obs ({df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. GJR-GARCH BASELINE (for comparison)
# ============================================================
print("\n[2/6] Fitting GJR-GARCH baseline...")

from arch import arch_model

# In-sample fit
am = arch_model(df_is['r'] * 100, vol='GARCH', p=1, o=1, q=1, dist='t', mean='ARX')
res_gjr = am.fit(disp='off')
print(f"  GJR-t converged: {res_gjr.convergence_flag == 0}")
print(f"  Params: omega={res_gjr.params.get('omega', 'N/A'):.6f}, "
      f"alpha={res_gjr.params.get('alpha[1]', 'N/A'):.6f}, "
      f"gamma={res_gjr.params.get('gamma[1]', 'N/A'):.6f}, "
      f"beta={res_gjr.params.get('beta[1]', 'N/A'):.6f}")

persistence = (res_gjr.params.get('alpha[1]', 0) +
               res_gjr.params.get('gamma[1]', 0) / 2 +
               res_gjr.params.get('beta[1]', 0))
print(f"  Persistence: {persistence:.4f}")

# OOS forecast: recursive 1-step
def gjr_oos_forecast(returns_is, returns_oos, params, dist_params=None):
    """Recursive 1-step GJR-GARCH OOS forecast."""
    omega = params.get('omega', 0)
    alpha = params.get('alpha[1]', 0)
    gamma = params.get('gamma[1]', 0)
    beta = params.get('beta[1]', 0)
    mu = params.get('mu', 0)

    # Initialize with IS final variance
    r_all = np.concatenate([returns_is.values, returns_oos.values])
    n_is = len(returns_is)
    n_total = len(r_all)

    sigma2 = np.zeros(n_total)
    # Warm up with IS data
    sigma2[0] = np.var(returns_is.values[:100])
    for t in range(1, n_total):
        eps = r_all[t-1] - mu
        leverage = 1.0 if eps < 0 else 0.0
        sigma2[t] = omega + alpha * eps**2 + gamma * leverage * eps**2 + beta * sigma2[t-1]
        sigma2[t] = max(sigma2[t], 1e-8)

    # Return OOS part, convert from (return*100)² back to return²
    return sigma2[n_is:] / 10000.0

gjr_oos_var = gjr_oos_forecast(
    df_is['r'] * 100, df_oos['r'] * 100,
    res_gjr.params.to_dict()
)

# QLIKE
def qlike(actual_r_sq, predicted_var):
    """QLIKE loss: mean(r²/σ² - log(r²/σ²) - 1), proxy-robust."""
    # Replace zeros in actual with small number
    actual = np.maximum(actual_r_sq, 1e-12)
    pred = np.maximum(predicted_var, 1e-12)
    ratio = actual / pred
    loss = ratio - np.log(ratio) - 1
    return np.mean(loss)

gjr_qlike_oos = qlike(df_oos['r_sq'].values, gjr_oos_var)
print(f"  GJR-t OOS QLIKE: {gjr_qlike_oos:.6f}")

# ============================================================
# 3. BAYESIAN SSVS MCMC (Joint Mean + Variance Selection)
# ============================================================
print("\n[3/6] Running Bayesian SSVS MCMC (joint selection)...")

# Prepare data matrices
mean_vars = ['VIX_change', 'VIX_level', 'TLT_return', 'CREDIT_spread']
var_vars = ['VIX_sq', 'VIX9D_sq', 'RV_22d', 'VIX_change_sq']
all_var_names = mean_vars + var_vars

# In-sample data (lagged predictors: X_{t-1} predicts r_t)
y = df_is['r'].values[1:]  # returns from t=1 onwards
y_sq = y ** 2  # target for evaluation

# Mean eq predictors (lagged by 1)
X_mean = df_is[mean_vars].values[:-1]  # t-1 values
# Variance eq predictors (lagged by 1)
X_var = df_is[var_vars].values[:-1]  # t-1 values

n_obs = len(y)
n_mean = len(mean_vars)
n_var = len(var_vars)
n_total_vars = n_mean + n_var

print(f"  Observations: {n_obs}")
print(f"  Mean eq candidates: {n_mean} ({mean_vars})")
print(f"  Variance eq candidates: {n_var} ({var_vars})")

# Standardize predictors for numerical stability
X_mean_std = (X_mean - X_mean.mean(axis=0)) / (X_mean.std(axis=0) + 1e-10)
X_var_std = (X_var - X_var.mean(axis=0)) / (X_var.std(axis=0) + 1e-10)

# ---- MCMC Setup ----
n_iter = 10000
n_burnin = 2000
n_thin = 5
n_keep = (n_iter - n_burnin) // n_thin

# Spike-and-slab parameters
tau_sq = 0.01   # spike variance (near zero when excluded)
c_sq = 100.0    # slab variance (wide when included)
prior_incl = 0.5  # prior inclusion probability

# GJR internal parameters (initialized from arch fit)
omega_init = res_gjr.params.get('omega', 0.01) / 10000.0  # convert from *100 scale
alpha_init = res_gjr.params.get('alpha[1]', 0.05)
gamma_init = res_gjr.params.get('gamma[1]', 0.05)
beta_init = res_gjr.params.get('beta[1]', 0.90)

# Storage
delta_m_samples = np.zeros((n_keep, n_mean), dtype=int)  # mean indicators
delta_v_samples = np.zeros((n_keep, n_var), dtype=int)    # variance indicators
beta_m_samples = np.zeros((n_keep, n_mean))               # mean coefficients
theta_v_samples = np.zeros((n_keep, n_var))                # variance coefficients
mu_samples = np.zeros(n_keep)
omega_samples = np.zeros(n_keep)
alpha_samples = np.zeros(n_keep)
gamma_samples = np.zeros(n_keep)
beta_g_samples = np.zeros(n_keep)  # GARCH beta
loglik_samples = np.zeros(n_keep)

# Current state
delta_m = np.zeros(n_mean, dtype=int)
delta_v = np.zeros(n_var, dtype=int)
beta_m = np.zeros(n_mean)
theta_v = np.zeros(n_var)
mu = 0.0
omega = max(omega_init, 1e-8)
alpha = max(alpha_init, 0.01)
gamma_g = max(gamma_init, 0.01)
beta_g = min(max(beta_init, 0.5), 0.98)

rng = np.random.default_rng(42)

def compute_conditional_variance(y, mu_val, beta_m_vec, delta_m_vec, X_m,
                                  omega_val, alpha_val, gamma_val, beta_garch,
                                  theta_v_vec, delta_v_vec, X_v):
    """Compute GJR-GARCH(1,1) conditional variance with exogenous variables."""
    n = len(y)
    sigma2 = np.zeros(n)

    # Mean equation residuals
    mean_x = X_m @ (beta_m_vec * delta_m_vec)
    eps = y - mu_val - mean_x

    # Variance equation
    sigma2[0] = np.var(y[:min(100, n)])
    for t in range(1, n):
        leverage = 1.0 if eps[t-1] < 0 else 0.0
        exog_var = np.dot(X_v[t-1], theta_v_vec * delta_v_vec)
        sigma2[t] = (omega_val + alpha_val * eps[t-1]**2
                     + gamma_val * leverage * eps[t-1]**2
                     + beta_garch * sigma2[t-1]
                     + max(exog_var, 0))  # ensure non-negative contribution
        sigma2[t] = max(sigma2[t], 1e-10)

    return sigma2, eps

def log_likelihood_normal(y, sigma2, eps):
    """Log-likelihood for normal errors given residuals and variance."""
    n = len(y)
    ll = -0.5 * n * np.log(2 * np.pi) - 0.5 * np.sum(np.log(sigma2) + eps**2 / sigma2)
    return ll

print("  Running MCMC...")
accept_count = 0
total_mh = 0

for iteration in range(n_iter):
    # ---- Step 1: Sample delta_m (mean inclusion indicators) ----
    # Gibbs step: for each j, compute P(delta_m_j=1 | rest)
    for j in range(n_mean):
        # Current variance
        sigma2_curr, eps_curr = compute_conditional_variance(
            y, mu, beta_m, delta_m, X_mean_std,
            omega, alpha, gamma_g, beta_g,
            theta_v, delta_v, X_var_std
        )
        ll_curr = log_likelihood_normal(y, sigma2_curr, eps_curr)

        # Try flipping delta_m[j]
        delta_m_prop = delta_m.copy()
        delta_m_prop[j] = 1 - delta_m[j]

        # If turning on, draw a coefficient from prior
        beta_m_prop = beta_m.copy()
        if delta_m_prop[j] == 1 and delta_m[j] == 0:
            beta_m_prop[j] = rng.normal(0, np.sqrt(c_sq) * np.std(y))
        elif delta_m_prop[j] == 0:
            beta_m_prop[j] = 0.0

        sigma2_prop, eps_prop = compute_conditional_variance(
            y, mu, beta_m_prop, delta_m_prop, X_mean_std,
            omega, alpha, gamma_g, beta_g,
            theta_v, delta_v, X_var_std
        )
        ll_prop = log_likelihood_normal(y, sigma2_prop, eps_prop)

        # Log prior odds for inclusion
        log_prior_ratio = 0.0  # symmetric prior (0.5/0.5)

        # Spike-slab prior on coefficient
        if delta_m_prop[j] == 1:
            log_spike_slab = stats.norm.logpdf(beta_m_prop[j], 0, np.sqrt(c_sq) * np.std(y))
        else:
            log_spike_slab = 0.0
        if delta_m[j] == 1:
            log_spike_slab -= stats.norm.logpdf(beta_m[j], 0, np.sqrt(c_sq) * np.std(y))

        log_accept = ll_prop - ll_curr + log_prior_ratio + log_spike_slab

        if np.log(rng.uniform()) < min(log_accept, 0):
            delta_m[j] = delta_m_prop[j]
            beta_m[j] = beta_m_prop[j]

    # ---- Step 2: Sample beta_m (mean coefficients) given delta_m ----
    sigma2_curr, eps_curr = compute_conditional_variance(
        y, mu, beta_m, delta_m, X_mean_std,
        omega, alpha, gamma_g, beta_g,
        theta_v, delta_v, X_var_std
    )

    for j in range(n_mean):
        if delta_m[j] == 1:
            # Full conditional for beta_m[j]: Normal posterior
            x_j = X_mean_std[:, j]
            # Posterior precision
            prior_prec = 1.0 / (c_sq * np.var(y))
            data_prec = np.sum(x_j**2 / sigma2_curr)
            post_prec = prior_prec + data_prec

            # Residual without j-th variable
            resid_no_j = eps_curr + beta_m[j] * x_j * delta_m[j]
            post_mean = np.sum(x_j * resid_no_j / sigma2_curr) / post_prec

            beta_m[j] = rng.normal(post_mean, 1.0 / np.sqrt(post_prec))
        else:
            beta_m[j] = rng.normal(0, np.sqrt(tau_sq) * np.std(y))  # spike

    # ---- Step 3: Sample delta_v (variance inclusion indicators) ----
    for j in range(n_var):
        sigma2_curr, eps_curr = compute_conditional_variance(
            y, mu, beta_m, delta_m, X_mean_std,
            omega, alpha, gamma_g, beta_g,
            theta_v, delta_v, X_var_std
        )
        ll_curr = log_likelihood_normal(y, sigma2_curr, eps_curr)

        delta_v_prop = delta_v.copy()
        delta_v_prop[j] = 1 - delta_v[j]

        theta_v_prop = theta_v.copy()
        if delta_v_prop[j] == 1 and delta_v[j] == 0:
            theta_v_prop[j] = abs(rng.normal(0, np.sqrt(c_sq) * np.var(y)))
        elif delta_v_prop[j] == 0:
            theta_v_prop[j] = 0.0

        sigma2_prop, eps_prop = compute_conditional_variance(
            y, mu, beta_m, delta_m, X_mean_std,
            omega, alpha, gamma_g, beta_g,
            theta_v_prop, delta_v_prop, X_var_std
        )
        ll_prop = log_likelihood_normal(y, sigma2_prop, eps_prop)

        log_accept = ll_prop - ll_curr

        if np.log(rng.uniform()) < min(log_accept, 0):
            delta_v[j] = delta_v_prop[j]
            theta_v[j] = theta_v_prop[j]

    # ---- Step 4: Sample theta_v (variance coefficients) given delta_v ----
    for j in range(n_var):
        if delta_v[j] == 1:
            # MH step for variance eq coefficient (no closed form)
            theta_curr = theta_v[j]
            theta_prop = abs(theta_curr + rng.normal(0, 0.1 * np.var(y)))

            theta_v_test = theta_v.copy()
            theta_v_test[j] = theta_prop

            sigma2_curr_j, eps_curr_j = compute_conditional_variance(
                y, mu, beta_m, delta_m, X_mean_std,
                omega, alpha, gamma_g, beta_g,
                theta_v, delta_v, X_var_std
            )
            sigma2_prop_j, eps_prop_j = compute_conditional_variance(
                y, mu, beta_m, delta_m, X_mean_std,
                omega, alpha, gamma_g, beta_g,
                theta_v_test, delta_v, X_var_std
            )

            ll_c = log_likelihood_normal(y, sigma2_curr_j, eps_curr_j)
            ll_p = log_likelihood_normal(y, sigma2_prop_j, eps_prop_j)

            if np.log(rng.uniform()) < (ll_p - ll_c):
                theta_v[j] = theta_prop
                accept_count += 1
            total_mh += 1
        else:
            theta_v[j] = abs(rng.normal(0, np.sqrt(tau_sq) * np.var(y)))

    # ---- Step 5: Sample mu (intercept) ----
    sigma2_curr, eps_curr = compute_conditional_variance(
        y, mu, beta_m, delta_m, X_mean_std,
        omega, alpha, gamma_g, beta_g,
        theta_v, delta_v, X_var_std
    )
    mu_prop = mu + rng.normal(0, 0.0001)
    sigma2_prop, eps_prop = compute_conditional_variance(
        y, mu_prop, beta_m, delta_m, X_mean_std,
        omega, alpha, gamma_g, beta_g,
        theta_v, delta_v, X_var_std
    )
    ll_c = log_likelihood_normal(y, sigma2_curr, eps_curr)
    ll_p = log_likelihood_normal(y, sigma2_prop, eps_prop)
    if np.log(rng.uniform()) < (ll_p - ll_c):
        mu = mu_prop

    # ---- Step 6: Sample GARCH parameters via MH ----
    # Joint proposal for (omega, alpha, gamma, beta_g)
    garch_params = np.array([omega, alpha, gamma_g, beta_g])
    proposal_scale = np.array([omega * 0.05, 0.01, 0.01, 0.01])
    garch_prop = garch_params + rng.normal(0, 1, 4) * proposal_scale

    # Enforce constraints
    garch_prop[0] = max(garch_prop[0], 1e-10)  # omega > 0
    garch_prop[1] = max(min(garch_prop[1], 0.5), 0.001)  # 0 < alpha < 0.5
    garch_prop[2] = max(min(garch_prop[2], 0.5), 0.001)  # 0 < gamma < 0.5
    garch_prop[3] = max(min(garch_prop[3], 0.999), 0.3)   # 0.3 < beta < 1

    # Check persistence < 1
    pers_prop = garch_prop[1] + garch_prop[2] / 2 + garch_prop[3]
    if pers_prop < 1.0:
        sigma2_curr_g, eps_curr_g = compute_conditional_variance(
            y, mu, beta_m, delta_m, X_mean_std,
            omega, alpha, gamma_g, beta_g,
            theta_v, delta_v, X_var_std
        )
        sigma2_prop_g, eps_prop_g = compute_conditional_variance(
            y, mu, beta_m, delta_m, X_mean_std,
            garch_prop[0], garch_prop[1], garch_prop[2], garch_prop[3],
            theta_v, delta_v, X_var_std
        )
        ll_c = log_likelihood_normal(y, sigma2_curr_g, eps_curr_g)
        ll_p = log_likelihood_normal(y, sigma2_prop_g, eps_prop_g)

        if np.log(rng.uniform()) < (ll_p - ll_c):
            omega, alpha, gamma_g, beta_g = garch_prop

    # ---- Store samples (after burn-in, with thinning) ----
    if iteration >= n_burnin and (iteration - n_burnin) % n_thin == 0:
        idx = (iteration - n_burnin) // n_thin
        if idx < n_keep:
            delta_m_samples[idx] = delta_m
            delta_v_samples[idx] = delta_v
            beta_m_samples[idx] = beta_m
            theta_v_samples[idx] = theta_v
            mu_samples[idx] = mu
            omega_samples[idx] = omega
            alpha_samples[idx] = alpha
            gamma_samples[idx] = gamma_g
            beta_g_samples[idx] = beta_g

            sigma2_final, eps_final = compute_conditional_variance(
                y, mu, beta_m, delta_m, X_mean_std,
                omega, alpha, gamma_g, beta_g,
                theta_v, delta_v, X_var_std
            )
            loglik_samples[idx] = log_likelihood_normal(y, sigma2_final, eps_final)

    if (iteration + 1) % 2000 == 0:
        print(f"    Iteration {iteration + 1}/{n_iter}, "
              f"delta_m={delta_m.tolist()}, delta_v={delta_v.tolist()}, "
              f"pers={alpha + gamma_g/2 + beta_g:.4f}")

# ============================================================
# 4. MCMC DIAGNOSTICS & PIP COMPUTATION
# ============================================================
print("\n[4/6] MCMC Diagnostics & PIP...")

# Posterior Inclusion Probabilities
pip_mean = delta_m_samples.mean(axis=0)
pip_var = delta_v_samples.mean(axis=0)

print("\n  === Posterior Inclusion Probabilities ===")
print("  MEAN EQUATION:")
for i, name in enumerate(mean_vars):
    status = "★ INCLUDED" if pip_mean[i] >= 0.5 else ""
    print(f"    {name:20s}: PIP = {pip_mean[i]:.4f} {status}")

print("  VARIANCE EQUATION:")
for i, name in enumerate(var_vars):
    status = "★ INCLUDED" if pip_var[i] >= 0.5 else ""
    print(f"    {name:20s}: PIP = {pip_var[i]:.4f} {status}")

# Best model (highest posterior probability)
# Combine delta_m and delta_v into a single model indicator
model_strings = []
for k in range(n_keep):
    model_key = tuple(delta_m_samples[k].tolist() + delta_v_samples[k].tolist())
    model_strings.append(model_key)

from collections import Counter
model_counts = Counter(model_strings)
best_model, best_count = model_counts.most_common(1)[0]
best_model_prob = best_count / n_keep

print(f"\n  Best model (posterior probability {best_model_prob:.4f}):")
print(f"    Mean indicators:     {list(best_model[:n_mean])}")
print(f"    Variance indicators: {list(best_model[n_mean:])}")

best_mean_vars = [mean_vars[i] for i in range(n_mean) if best_model[i] == 1]
best_var_vars = [var_vars[i] for i in range(n_var) if best_model[n_mean + i] == 1]
print(f"    Mean variables:     {best_mean_vars if best_mean_vars else 'NONE'}")
print(f"    Variance variables: {best_var_vars if best_var_vars else 'NONE'}")

# Top 5 models
print(f"\n  Top 5 models:")
for model_key, count in model_counts.most_common(5):
    prob = count / n_keep
    m_vars = [mean_vars[i] for i in range(n_mean) if model_key[i] == 1]
    v_vars_sel = [var_vars[i] for i in range(n_var) if model_key[n_mean + i] == 1]
    print(f"    P={prob:.4f}: mean={m_vars}, var={v_vars_sel}")

# MH acceptance rate for theta_v
if total_mh > 0:
    accept_rate = accept_count / total_mh
    print(f"\n  MH acceptance rate (theta_v): {accept_rate:.4f}")

# Effective sample size (simple estimate via autocorrelation)
def effective_sample_size(chain):
    """Estimate ESS using initial positive sequence estimator."""
    n = len(chain)
    if np.std(chain) < 1e-15:
        return 1.0
    chain_centered = chain - np.mean(chain)
    # First few autocorrelations
    max_lag = min(100, n // 3)
    autocorr = np.correlate(chain_centered, chain_centered, 'full')[n-1:n-1+max_lag]
    autocorr = autocorr / autocorr[0]
    # Sum pairs
    rho_sum = 0
    for k in range(1, max_lag, 2):
        pair_sum = autocorr[k] + (autocorr[k+1] if k+1 < max_lag else 0)
        if pair_sum < 0:
            break
        rho_sum += pair_sum
    tau = 1 + 2 * rho_sum
    return n / max(tau, 1)

ess_omega = effective_sample_size(omega_samples)
ess_alpha = effective_sample_size(alpha_samples)
ess_beta = effective_sample_size(beta_g_samples)
ess_loglik = effective_sample_size(loglik_samples)

print(f"\n  Effective Sample Size:")
print(f"    omega:  {ess_omega:.0f}")
print(f"    alpha:  {ess_alpha:.0f}")
print(f"    beta:   {ess_beta:.0f}")
print(f"    loglik: {ess_loglik:.0f}")

# Posterior means of GARCH parameters
print(f"\n  Posterior means (GARCH):")
print(f"    omega:  {omega_samples.mean():.8f} (±{omega_samples.std():.8f})")
print(f"    alpha:  {alpha_samples.mean():.4f} (±{alpha_samples.std():.4f})")
print(f"    gamma:  {gamma_samples.mean():.4f} (±{gamma_samples.std():.4f})")
print(f"    beta:   {beta_g_samples.mean():.4f} (±{beta_g_samples.std():.4f})")
pers_post = alpha_samples.mean() + gamma_samples.mean() / 2 + beta_g_samples.mean()
print(f"    persistence: {pers_post:.4f}")

# ============================================================
# 5. OOS EVALUATION (Best SSVS Model vs GJR-t)
# ============================================================
print("\n[5/6] OOS Evaluation...")

# Use posterior mean parameters for OOS forecast
best_delta_m = (pip_mean >= 0.5).astype(int)
best_delta_v = (pip_var >= 0.5).astype(int)

# Posterior mean coefficients (only for included variables)
post_beta_m = np.zeros(n_mean)
post_theta_v = np.zeros(n_var)
for j in range(n_mean):
    if best_delta_m[j] == 1:
        # Mean of coefficient when included
        included_mask = delta_m_samples[:, j] == 1
        if included_mask.sum() > 0:
            post_beta_m[j] = beta_m_samples[included_mask, j].mean()

for j in range(n_var):
    if best_delta_v[j] == 1:
        included_mask = delta_v_samples[:, j] == 1
        if included_mask.sum() > 0:
            post_theta_v[j] = theta_v_samples[included_mask, j].mean()

post_mu = mu_samples.mean()
post_omega = omega_samples.mean()
post_alpha = alpha_samples.mean()
post_gamma = gamma_samples.mean()
post_beta_g = beta_g_samples.mean()

print(f"  Best model (PIP >= 0.5):")
print(f"    Mean delta: {best_delta_m.tolist()} -> {[mean_vars[i] for i in range(n_mean) if best_delta_m[i]]}")
print(f"    Var delta:  {best_delta_v.tolist()} -> {[var_vars[i] for i in range(n_var) if best_delta_v[i]]}")
print(f"    Mean coefs: {post_beta_m}")
print(f"    Var coefs:  {post_theta_v}")

# OOS recursive forecast with SSVS model
# Need standardization parameters from IS
X_mean_mean = df_is[mean_vars].values[:-1].mean(axis=0)
X_mean_std_scale = df_is[mean_vars].values[:-1].std(axis=0) + 1e-10
X_var_mean = df_is[var_vars].values[:-1].mean(axis=0)
X_var_std_scale = df_is[var_vars].values[:-1].std(axis=0) + 1e-10

# Concatenate IS and OOS for recursive forecast
r_all = np.concatenate([df_is['r'].values[1:], df_oos['r'].values])
X_m_all = np.concatenate([
    df_is[mean_vars].values[:-1],
    df_oos[mean_vars].values
])
X_v_all = np.concatenate([
    df_is[var_vars].values[:-1],
    df_oos[var_vars].values
])

# Standardize using IS parameters
X_m_all_std = (X_m_all - X_mean_mean) / X_mean_std_scale
X_v_all_std = (X_v_all - X_var_mean) / X_var_std_scale

n_is_obs = len(df_is['r'].values[1:])
n_all = len(r_all)

# Lag the predictors by 1 for OOS (at time t, use X_{t-1})
# The data is already aligned: X[t] corresponds to predictors for return at t+1
# So for return r_all[t], we use X[t-1] predictors
sigma2_all = np.zeros(n_all)
eps_all = np.zeros(n_all)

# Mean prediction
mean_pred = post_mu + X_m_all_std @ (post_beta_m * best_delta_m)
eps_all = r_all - mean_pred

# Variance
sigma2_all[0] = np.var(r_all[:100])
for t in range(1, n_all):
    leverage = 1.0 if eps_all[t-1] < 0 else 0.0
    exog_var = np.dot(X_v_all_std[t-1] if t > 0 else np.zeros(n_var),
                      post_theta_v * best_delta_v)
    sigma2_all[t] = (post_omega + post_alpha * eps_all[t-1]**2
                     + post_gamma * leverage * eps_all[t-1]**2
                     + post_beta_g * sigma2_all[t-1]
                     + max(exog_var, 0))
    sigma2_all[t] = max(sigma2_all[t], 1e-10)

ssvs_oos_var = sigma2_all[n_is_obs:]
ssvs_oos_target = df_oos['r_sq'].values

# Also compute the "null model" (no exogenous variables) OOS
null_delta_m = np.zeros(n_mean, dtype=int)
null_delta_v = np.zeros(n_var, dtype=int)
null_beta_m = np.zeros(n_mean)
null_theta_v = np.zeros(n_var)

sigma2_null = np.zeros(n_all)
eps_null = r_all - post_mu  # just intercept
sigma2_null[0] = np.var(r_all[:100])
for t in range(1, n_all):
    leverage = 1.0 if eps_null[t-1] < 0 else 0.0
    sigma2_null[t] = (post_omega + post_alpha * eps_null[t-1]**2
                      + post_gamma * leverage * eps_null[t-1]**2
                      + post_beta_g * sigma2_null[t-1])
    sigma2_null[t] = max(sigma2_null[t], 1e-10)
null_oos_var = sigma2_null[n_is_obs:]

# QLIKE comparisons
ssvs_qlike = qlike(ssvs_oos_target, ssvs_oos_var)
null_qlike = qlike(ssvs_oos_target, null_oos_var)

print(f"\n  === OOS QLIKE Comparison ===")
print(f"  GJR-t baseline:      {gjr_qlike_oos:.6f}")
print(f"  SSVS null (no exog): {null_qlike:.6f}")
print(f"  SSVS best model:     {ssvs_qlike:.6f}")

# Improvement
if gjr_qlike_oos > 0:
    ssvs_vs_gjr = (gjr_qlike_oos - ssvs_qlike) / gjr_qlike_oos * 100
    print(f"  SSVS vs GJR-t:       {ssvs_vs_gjr:+.2f}% (positive = SSVS better)")
    null_vs_gjr = (gjr_qlike_oos - null_qlike) / gjr_qlike_oos * 100
    print(f"  Null vs GJR-t:       {null_vs_gjr:+.2f}%")

# DM test (Harvey threshold t > 3.0)
def dm_test(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with bandwidth = int(n^(1/3)))
    bw = int(n ** (1.0 / 3))
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, bw + 1):
        weight = 1 - k / (bw + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * weight * gamma_k
    var_d = gamma_0 + gamma_sum
    var_d = max(var_d, 1e-20)
    t_stat = d_bar / np.sqrt(var_d / n)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return t_stat, p_value

# Individual QLIKE losses for DM test
r_sq_oos = df_oos['r_sq'].values
eps_small = 1e-12

gjr_loss = r_sq_oos / np.maximum(gjr_oos_var, eps_small) - np.log(r_sq_oos / np.maximum(gjr_oos_var, eps_small) + eps_small) - 1
ssvs_loss = r_sq_oos / np.maximum(ssvs_oos_var, eps_small) - np.log(r_sq_oos / np.maximum(ssvs_oos_var, eps_small) + eps_small) - 1

# Clip extreme values
gjr_loss = np.clip(gjr_loss, -100, 100)
ssvs_loss = np.clip(ssvs_loss, -100, 100)

dm_stat, dm_pval = dm_test(gjr_loss, ssvs_loss)  # positive = SSVS better
print(f"\n  DM test (GJR vs SSVS): t = {dm_stat:.4f}, p = {dm_pval:.4f}")
print(f"  Harvey (2016) threshold: |t| > 3.0 → {'SIGNIFICANT' if abs(dm_stat) > 3.0 else 'NOT significant'}")

# ============================================================
# 6. FIGURES
# ============================================================
print("\n[6/6] Generating figures...")

# Figure 1: PIP Bar Chart
fig, ax = plt.subplots(figsize=(10, 6))
all_pips = np.concatenate([pip_mean, pip_var])
all_names = mean_vars + var_vars
colors = ['#2196F3'] * n_mean + ['#FF9800'] * n_var

bars = ax.barh(range(len(all_names)), all_pips, color=colors, edgecolor='white', height=0.6)
ax.axvline(x=0.5, color='red', linestyle='--', linewidth=1.5, label='PIP = 0.5 threshold')
ax.set_yticks(range(len(all_names)))
ax.set_yticklabels(all_names, fontsize=11)
ax.set_xlabel('Posterior Inclusion Probability (PIP)', fontsize=12)
ax.set_title('K1031: Joint SSVS Variable Selection (So, Chen, Liu 2006)\nBlue = Mean Eq, Orange = Variance Eq', fontsize=13)
ax.set_xlim(0, 1)
ax.legend(fontsize=10)

# Add value labels
for bar, pip_val in zip(bars, all_pips):
    ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height()/2,
            f'{pip_val:.3f}', va='center', fontsize=10)

plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, 'k1031_pip_chart.png'), dpi=150)
plt.close()
print("  Saved: k1031_pip_chart.png")

# Figure 2: MCMC Trace Plot (log-likelihood)
fig, axes = plt.subplots(2, 2, figsize=(12, 8))

axes[0, 0].plot(loglik_samples, linewidth=0.5, color='#333')
axes[0, 0].set_title('Log-Likelihood Trace', fontsize=11)
axes[0, 0].set_xlabel('Iteration (post burn-in, thinned)')

axes[0, 1].plot(alpha_samples, linewidth=0.5, color='#2196F3')
axes[0, 1].set_title('Alpha (ARCH) Trace', fontsize=11)
axes[0, 1].set_xlabel('Iteration')

axes[1, 0].plot(beta_g_samples, linewidth=0.5, color='#FF9800')
axes[1, 0].set_title('Beta (GARCH) Trace', fontsize=11)
axes[1, 0].set_xlabel('Iteration')

# PIP evolution (cumulative)
pip_evolution_m = np.cumsum(delta_m_samples, axis=0) / (np.arange(n_keep)[:, None] + 1)
pip_evolution_v = np.cumsum(delta_v_samples, axis=0) / (np.arange(n_keep)[:, None] + 1)

for i, name in enumerate(mean_vars):
    axes[1, 1].plot(pip_evolution_m[:, i], label=f'M:{name}', linewidth=1)
for i, name in enumerate(var_vars):
    axes[1, 1].plot(pip_evolution_v[:, i], label=f'V:{name}', linewidth=1, linestyle='--')
axes[1, 1].axhline(y=0.5, color='red', linestyle=':', linewidth=1)
axes[1, 1].set_title('PIP Evolution (Cumulative)', fontsize=11)
axes[1, 1].set_xlabel('Iteration')
axes[1, 1].set_ylabel('PIP')
axes[1, 1].legend(fontsize=7, ncol=2)

plt.suptitle('K1031: MCMC Diagnostics', fontsize=13, y=1.01)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, 'k1031_mcmc_trace.png'), dpi=150)
plt.close()
print("  Saved: k1031_mcmc_trace.png")

# Figure 3: QLIKE Comparison Bar Chart
fig, ax = plt.subplots(figsize=(8, 5))
models = ['GJR-t\n(baseline)', 'SSVS\n(null/no exog)', 'SSVS\n(best model)']
qlikes = [gjr_qlike_oos, null_qlike, ssvs_qlike]
colors = ['#9E9E9E', '#FF9800', '#4CAF50']

bars = ax.bar(models, qlikes, color=colors, edgecolor='white', width=0.5)
for bar, q in zip(bars, qlikes):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
            f'{q:.4f}', ha='center', fontsize=11, fontweight='bold')

ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
ax.set_title('K1031: OOS QLIKE Comparison (2019-2026)', fontsize=13)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, 'k1031_qlike_comparison.png'), dpi=150)
plt.close()
print("  Saved: k1031_qlike_comparison.png")

# ============================================================
# 7. RESULTS JSON
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Count variables with PIP >= 0.5
n_mean_selected = int(np.sum(pip_mean >= 0.5))
n_var_selected = int(np.sum(pip_var >= 0.5))

conclusion = ""
if n_mean_selected == 0 and n_var_selected == 0:
    conclusion = "NULL RESULT: Joint SSVS selects no exogenous variables (all PIP < 0.5). Confirms K433/K821/K1013: GJR internal dynamics are self-sufficient for SPY vol prediction."
elif n_mean_selected > 0 or n_var_selected > 0:
    selected = []
    for i, name in enumerate(mean_vars):
        if pip_mean[i] >= 0.5:
            selected.append(f"mean:{name}")
    for i, name in enumerate(var_vars):
        if pip_var[i] >= 0.5:
            selected.append(f"var:{name}")
    conclusion = f"Joint SSVS selects {n_mean_selected + n_var_selected} variable(s): {selected}. OOS QLIKE vs GJR: {ssvs_vs_gjr:+.2f}%."
    if abs(dm_stat) < 3.0:
        conclusion += " But DM test NOT significant (Harvey t<3.0). Marginal improvement at best."

print(conclusion)

results = {
    "experiment_id": "K1031",
    "title": "Bayesian SSVS for ARX-GARCH (Joint Variable Selection, So Chen Liu 2006)",
    "method": "Joint MCMC with binary inclusion indicators for mean and variance equations simultaneously",
    "reference": "So, Chen, Liu (2006) JRSS-C 55(2) 201-224; George & McCulloch (1993) JASA",
    "data": {
        "asset": "SPY",
        "source": "yfinance",
        "in_sample": f"{df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')} ({len(df_is)} obs)",
        "oos": f"{df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')} ({len(df_oos)} obs)"
    },
    "mcmc": {
        "iterations": n_iter,
        "burn_in": n_burnin,
        "thinning": n_thin,
        "kept_samples": n_keep,
        "seed": 42,
        "spike_variance_tau_sq": tau_sq,
        "slab_variance_c_sq": c_sq,
        "prior_inclusion": prior_incl,
        "mh_acceptance_rate": float(accept_count / max(total_mh, 1)),
        "ess": {
            "omega": float(ess_omega),
            "alpha": float(ess_alpha),
            "beta": float(ess_beta),
            "loglik": float(ess_loglik)
        }
    },
    "pip": {
        "mean_equation": {name: float(pip_mean[i]) for i, name in enumerate(mean_vars)},
        "variance_equation": {name: float(pip_var[i]) for i, name in enumerate(var_vars)},
        "pip_threshold": 0.5
    },
    "best_model": {
        "mean_indicators": best_delta_m.tolist(),
        "variance_indicators": best_delta_v.tolist(),
        "mean_variables_selected": [mean_vars[i] for i in range(n_mean) if best_delta_m[i]],
        "variance_variables_selected": [var_vars[i] for i in range(n_var) if best_delta_v[i]],
        "posterior_probability": float(best_model_prob)
    },
    "top5_models": [
        {
            "mean_vars": [mean_vars[i] for i in range(n_mean) if model_key[i] == 1],
            "var_vars": [var_vars[i] for i in range(n_var) if model_key[n_mean + i] == 1],
            "posterior_probability": float(count / n_keep)
        }
        for model_key, count in model_counts.most_common(5)
    ],
    "posterior_garch_params": {
        "omega": float(omega_samples.mean()),
        "omega_std": float(omega_samples.std()),
        "alpha": float(alpha_samples.mean()),
        "alpha_std": float(alpha_samples.std()),
        "gamma": float(gamma_samples.mean()),
        "gamma_std": float(gamma_samples.std()),
        "beta": float(beta_g_samples.mean()),
        "beta_std": float(beta_g_samples.std()),
        "persistence": float(pers_post)
    },
    "oos_evaluation": {
        "target": "r² (squared daily return, proxy-robust per Patton 2011)",
        "qlike": {
            "gjr_t_baseline": float(gjr_qlike_oos),
            "ssvs_null_no_exog": float(null_qlike),
            "ssvs_best_model": float(ssvs_qlike),
            "ssvs_vs_gjr_pct": float(ssvs_vs_gjr) if gjr_qlike_oos > 0 else None
        },
        "dm_test": {
            "t_statistic": float(dm_stat),
            "p_value": float(dm_pval),
            "harvey_threshold": 3.0,
            "significant": bool(abs(dm_stat) > 3.0)
        }
    },
    "conclusion": conclusion,
    "prior_knowledge_confirmed": {
        "K433": "Mean eq SSVS NULL confirmed" if n_mean_selected == 0 else "Mean eq: some selected",
        "K484": "Variance eq: internal components dominate (GARCH structure sufficient)",
        "K821": "External variance predictors NULL confirmed" if n_var_selected == 0 else "Some variance externals selected",
        "K1013": "Two-stage NULL confirmed by joint approach" if (n_mean_selected == 0 and n_var_selected == 0) else "Joint approach reveals cross-effects"
    },
    "interpretation": (
        "Joint SSVS (So, Chen, Liu 2006) simultaneously searches mean and variance equation "
        "variable subsets. This addresses the concern that sequential selection (K433 then K484) "
        "might miss cross-equation interactions. The joint posterior sampling can detect cases where "
        "a variable is unimportant in one equation but becomes important when another equation includes "
        "a related variable."
    ),
    "figures": [
        "k1031_pip_chart.png",
        "k1031_mcmc_trace.png",
        "k1031_qlike_comparison.png"
    ],
    "timestamp": datetime.now().isoformat()
}

with open(os.path.join(OUTDIR, 'k1031_results.json'), 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\nSaved: k1031_results.json")

print("\n" + "=" * 60)
print("K1031 COMPLETE")
print("=" * 60)
