"""
K484: SSVS for Variance Equation Component Selection
=====================================================
Method: Stochastic Search Variable Selection applied to GARCH variance equation
       (Extension of So, Chen, Liu 2006 JRSS-C from mean equation to variance equation)
Asset: SPY
Data: yfinance (empirical), 2015-2025
OOS: 2023-2024

Core innovation (user-proposed):
  K433 applied SSVS to the mean equation (which external regressors predict returns?)
  → Result: null model wins (no exogenous variable helps predict SPY returns).

  K484 applies SSVS to the VARIANCE equation:
  Instead of "which external variable to add?", we ask
  "which GARCH extensions are worth keeping?"

  h_t = ω + α·ε²_{t-1} + β·h_{t-1}
        + δ₁ · γ · I(ε<0)·ε²_{t-1}    [GJR asymmetry]
        + δ₂ · λ₁ · VIX²_{t-1}/252     [GARCH-X VIX implied var]
        + δ₃ · λ₂ · Parkinson²_{t-1}    [Range-based info]
        + δ₄ · λ₃ · RS⁻_{t-1}           [Negative semivariance]
        + δ₅ · λ₄ · |ε_{t-1}|           [Absolute shock TGARCH-style]

  δ_i ∈ {0,1} with P(δ_i=1) = 0.5

MCMC: 8000 iterations (3000 burn-in + 5000 sample), component-wise MH.
Ref: So, Chen, Liu (2006) JRSS-C; K433 component-wise MH fix.

Data sources: yfinance (SPY daily OHLCV, ^VIX daily Close)
"""

import numpy as np
from scipy import stats
from scipy.optimize import minimize
import yfinance as yf
import json
import time
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ============================================================
# 1. DATA DOWNLOAD AND PREPARATION
# ============================================================
print("=" * 70)
print("K484: SSVS for Variance Equation Component Selection")
print("Extension of So, Chen, Liu (2006) from mean eq → variance eq")
print("=" * 70)

start_time = time.time()

print("\n[1] Downloading data from yfinance...")
spy = yf.download('SPY', start='2015-01-01', end='2025-12-31',
                   progress=False, auto_adjust=True)
vix = yf.download('^VIX', start='2015-01-01', end='2025-12-31',
                   progress=False, auto_adjust=True)

# Align dates
common_idx = spy.index.intersection(vix.index)
spy = spy.loc[common_idx]
vix = vix.loc[common_idx]

spy_close = spy['Close'].values.flatten()
spy_high = spy['High'].values.flatten()
spy_low = spy['Low'].values.flatten()
vix_close = vix['Close'].values.flatten()

print(f"  SPY: {len(spy)} obs, {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"  VIX: {len(vix)} obs")

# Compute returns (percent log returns)
log_ret = np.diff(np.log(spy_close)) * 100
T_full = len(log_ret)

# ============================================================
# 2. PRE-COMPUTE VARIANCE EQUATION COMPONENTS
# ============================================================
print("\n[2] Pre-computing variance equation components...")

# All components use lagged values (t-1) for predicting h_t.
# We need index alignment: returns[t] → components use data up to t-1.
# returns[0] = log(close[1]/close[0]), so for returns[t], close/high/low at index t+1 is "today".
# Lagged component for returns[t] uses data at index t (which is yesterday's close for returns[t]).

# Component 1: GJR leverage indicator × squared return
# I(ε_{t-1} < 0) · ε²_{t-1} — needs ε_{t-1}, available from t≥1
leverage_term = np.where(log_ret < 0, log_ret**2, 0.0)  # I(ε<0)·ε²
# For variance at t, we use leverage_term[t-1]

# Component 2: VIX implied daily variance
# VIX²/252 — transforms annualized VIX to daily implied variance
# vix_close[i] corresponds to trading day i (aligned with close[i])
# For returns[t] (close[t+1]/close[t]), VIX at t is lagged
vix_daily_var = (vix_close**2) / 252.0  # length = len(common_idx)
# For return[t], the lagged VIX var is vix_daily_var[t] (same day as numerator close)
# Actually: return[t] = log(close[t+1]/close[t]). VIX[t] is known at close of day t.
# So VIX[t] is "lagged" relative to return[t] — it's available before we see return[t].

# Component 3: Parkinson range-based variance estimator
# Parkinson = (ln(H/L))² / (4·ln(2))
# Uses high[i] and low[i] for day i
parkinson = (np.log(spy_high / spy_low))**2 / (4 * np.log(2))  # length = len(common_idx)
# For return[t], lagged Parkinson uses day t's range = parkinson[t]

# Component 4: Negative semivariance (realized)
# RS⁻ = ε² if ε < 0, else 0  (same as leverage_term actually, which is I(ε<0)·ε²)
# Wait — the user spec says RS⁻_{t-1}, which is the same as leverage_term.
# Let's distinguish: RS⁻ is specifically the contribution of negative returns to realized variance.
# For daily data, RS⁻_t = r²_t · I(r_t < 0). This equals leverage_term[t].
# To make it different from GJR, we use a ROLLING measure: sum of squared negative returns over 5 days.
# This captures "recent downside risk" vs. GJR's "single-day asymmetry".
semi_neg_raw = np.where(log_ret < 0, log_ret**2, 0.0)
# 5-day rolling negative semivariance
window_semi = 5
semi_neg_rolling = np.zeros(T_full)
for t in range(window_semi, T_full):
    semi_neg_rolling[t] = np.mean(semi_neg_raw[t-window_semi:t])
# For the first few obs, use expanding window
for t in range(1, window_semi):
    semi_neg_rolling[t] = np.mean(semi_neg_raw[:t])

# Component 5: Absolute shock |ε_{t-1}| (TGARCH / AVGARCH style)
abs_shock = np.abs(log_ret)  # |ε_t|
# For variance at t, we use abs_shock[t-1]

# ============================================================
# 3. CONSTRUCT ALIGNED SAMPLE
# ============================================================
print("\n[3] Constructing aligned sample...")

# We need: y[t] = returns, and for variance equation we need components at t-1.
# Start from index 2 to have t-1 and t-2 available.
START_IDX = 5  # Safe buffer for rolling semivariance

y = log_ret[START_IDX:]
T = len(y)

# Lagged components for each time step t in y:
# y[t] corresponds to log_ret[START_IDX + t]
# Lagged squared return: log_ret[START_IDX + t - 1]² = ε²_{t-1}
eps2_lag1 = log_ret[START_IDX-1:START_IDX-1+T]**2  # ε²_{t-1}

# Component vectors (all lagged by 1 relative to y)
# C1: GJR leverage = I(ε_{t-1}<0) · ε²_{t-1}
C1_gjr = leverage_term[START_IDX-1:START_IDX-1+T]

# C2: VIX daily variance at t-1
# VIX[t] is known at close of day t. For return[t] = log(close[t+1]/close[t]),
# VIX at index t (in vix_daily_var) is lagged.
# return[i] corresponds to close[i+1]/close[i].
# For return at START_IDX+t, VIX lagged = vix_daily_var[START_IDX+t]
C2_vix = vix_daily_var[START_IDX:START_IDX+T]

# C3: Parkinson range at t-1 (same-day range)
# parkinson[i] uses high[i]/low[i]. For return[t]=log(close[t+1]/close[t]),
# lagged Parkinson = parkinson[t] (known at end of day t).
C3_range = parkinson[START_IDX:START_IDX+T]

# C4: Rolling negative semivariance at t-1
C4_semi = semi_neg_rolling[START_IDX-1:START_IDX-1+T]

# C5: Absolute shock |ε_{t-1}|
C5_abs = abs_shock[START_IDX-1:START_IDX-1+T]

# Stack all components
component_names = [
    'GJR_asymmetry',      # δ₁: I(ε<0)·ε²
    'VIX_implied_var',     # δ₂: VIX²/252
    'Parkinson_range',     # δ₃: Parkinson range
    'Neg_semivariance',    # δ₄: Rolling RS⁻
    'Abs_shock_TGARCH',    # δ₅: |ε|
]
n_components = len(component_names)
C_matrix = np.column_stack([C1_gjr, C2_vix, C3_range, C4_semi, C5_abs])

print(f"  Total sample T = {T} ({T/252:.1f} years)")
print(f"  Variance equation components: {n_components}")
for i, name in enumerate(component_names):
    vals = C_matrix[:, i]
    print(f"    [{i}] {name:25s}: mean={vals.mean():.4f}, std={vals.std():.4f}, "
          f"min={vals.min():.4f}, max={vals.max():.4f}")

# ============================================================
# 4. DESCRIPTIVE STATISTICS AND DIAGNOSTICS
# ============================================================
print("\n[4] Descriptive statistics and diagnostics...")
print(f"  Returns: mean={y.mean():.4f}, std={y.std():.4f}, "
      f"skew={stats.skew(y):.3f}, kurt={stats.kurtosis(y):.3f}")

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_pval, *_ = adfuller(y, maxlag=10)
print(f"  ADF test: stat={adf_stat:.4f}, p={adf_pval:.4f} → {'Stationary' if adf_pval < 0.05 else 'Non-stationary'}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_stat, arch_pval, *_ = het_arch(y, nlags=5)
print(f"  ARCH LM test (5 lags): stat={arch_stat:.2f}, p={arch_pval:.6f} → {'ARCH effects' if arch_pval < 0.05 else 'No ARCH'}")

# Ljung-Box on squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_result = acorr_ljungbox(y**2, lags=[10], return_df=True)
lb_stat = lb_result['lb_stat'].values[0]
lb_pval = lb_result['lb_pvalue'].values[0]
print(f"  Ljung-Box on ε² (10 lags): stat={lb_stat:.2f}, p={lb_pval:.6f}")

# Correlations between components
print("\n  Component correlations:")
for i in range(n_components):
    for j in range(i+1, n_components):
        corr = np.corrcoef(C_matrix[:, i], C_matrix[:, j])[0, 1]
        print(f"    {component_names[i]:25s} × {component_names[j]:25s}: r={corr:.4f}")

# OOS split
oos_start_date = '2023-01-01'
# Find index in dates
dates_arr = common_idx[START_IDX+1:]  # dates corresponding to y
oos_mask = dates_arr >= oos_start_date
T_train = int((~oos_mask).sum())
T_test = int(oos_mask.sum())
print(f"\n  Train: {T_train} obs | OOS: {T_test} obs (from {oos_start_date})")

# ============================================================
# 5. MLE ESTIMATES FOR INITIALIZATION
# ============================================================
print("\n[5] MLE initialization...")

y_train = y[:T_train]
y_test = y[T_train:]
C_train = C_matrix[:T_train]
C_test = C_matrix[T_train:]

# Standard GARCH(1,1) MLE on training data
def garch11_negloglik(params, returns):
    """Negative log-likelihood for GARCH(1,1)."""
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return 1e10
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return -(-0.5 * np.sum(np.log(h) + returns**2 / h))

var_y = np.var(y_train)
x0 = [var_y * 0.05, 0.08, 0.88]
bounds = [(1e-6, var_y * 5), (1e-6, 0.5), (0.3, 0.9999)]
res_garch = minimize(garch11_negloglik, x0, args=(y_train,),
                     method='L-BFGS-B', bounds=bounds)
omega_mle, alpha_mle, beta_mle = res_garch.x
print(f"  Base GARCH(1,1): ω={omega_mle:.6f}, α={alpha_mle:.4f}, β={beta_mle:.4f}, "
      f"persist={alpha_mle+beta_mle:.4f}")

# Augmented GARCH with all components (kitchen sink) for initial lambda estimates
def augmented_garch_negloglik(params, returns, components):
    """Negative log-likelihood for augmented GARCH with all components."""
    omega = params[0]
    alpha = params[1]
    beta = params[2]
    lambdas = params[3:]  # one per component

    n_comp = components.shape[1]
    if omega <= 0 or alpha < 0 or beta < 0:
        return 1e10

    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        for k in range(n_comp):
            h[t] += lambdas[k] * components[t, k]
        if h[t] < 1e-10:
            h[t] = 1e-10

    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll

x0_aug = [omega_mle, alpha_mle, beta_mle] + [0.01] * n_components
bounds_aug = [(1e-6, var_y*5), (1e-6, 0.5), (0.01, 0.9999)] + \
             [(-1.0, 2.0)] * n_components

res_aug = minimize(augmented_garch_negloglik, x0_aug, args=(y_train, C_train),
                   method='L-BFGS-B', bounds=bounds_aug)
params_aug_mle = res_aug.x
print(f"  Augmented GARCH MLE:")
print(f"    ω={params_aug_mle[0]:.6f}, α={params_aug_mle[1]:.4f}, β={params_aug_mle[2]:.4f}")
for i, name in enumerate(component_names):
    print(f"    λ_{name}: {params_aug_mle[3+i]:.6f}")
print(f"    Converged: {res_aug.success}")

# Estimate standard errors via numerical Hessian (for τ calibration)
from scipy.optimize import approx_fprime
eps_hess = 1e-5
n_params = len(params_aug_mle)

# Simple finite-difference Hessian
def neg_ll_wrapper(params):
    return augmented_garch_negloglik(params, y_train, C_train)

hessian = np.zeros((n_params, n_params))
f0 = neg_ll_wrapper(params_aug_mle)
for i in range(n_params):
    for j in range(i, n_params):
        ei = np.zeros(n_params)
        ej = np.zeros(n_params)
        ei[i] = eps_hess
        ej[j] = eps_hess
        fpp = neg_ll_wrapper(params_aug_mle + ei + ej)
        fpm = neg_ll_wrapper(params_aug_mle + ei - ej)
        fmp = neg_ll_wrapper(params_aug_mle - ei + ej)
        fmm = neg_ll_wrapper(params_aug_mle - ei - ej)
        hessian[i, j] = (fpp - fpm - fmp + fmm) / (4 * eps_hess**2)
        hessian[j, i] = hessian[i, j]

try:
    inv_hess = np.linalg.inv(hessian)
    se_mle = np.sqrt(np.abs(np.diag(inv_hess)))
except np.linalg.LinAlgError:
    se_mle = np.abs(params_aug_mle) * 0.1 + 0.01
    print("  WARNING: Hessian singular, using approximate SE")

# τ for lambda parameters (indices 3..3+n_components-1)
tau_lambda = se_mle[3:3+n_components]
tau_lambda[tau_lambda < 1e-4] = 0.01
print(f"\n  τ (SE-based) for SSVS prior:")
for i, name in enumerate(component_names):
    print(f"    τ_{name}: {tau_lambda[i]:.6f}")

# ============================================================
# 6. SSVS-MCMC FOR VARIANCE EQUATION
# ============================================================
print("\n[6] Running SSVS-MCMC for variance equation...")

# SSVS settings
c_val = 10.0          # So et al. (2006): c=10
P_prior = 0.5         # Uninformative inclusion prior
c_vec = np.full(n_components, c_val)
P_vec = np.full(n_components, P_prior)

# MCMC settings
n_total = 8000
n_burn = 3000
n_sample = n_total - n_burn

# Storage
lambda_samples = np.zeros((n_sample, n_components))
delta_samples = np.zeros((n_sample, n_components), dtype=int)
garch_samples = np.zeros((n_sample, 3))  # omega, alpha, beta

# Initialize from MLE
omega_curr = params_aug_mle[0]
alpha_curr = params_aug_mle[1]
beta_curr = params_aug_mle[2]
lambda_curr = params_aug_mle[3:3+n_components].copy()
delta_curr = np.ones(n_components, dtype=int)  # Start all included

# Proposal standard deviations
omega_prop_sd = se_mle[0] * 0.3
alpha_prop_sd = se_mle[1] * 0.3
beta_prop_sd = se_mle[2] * 0.3
lambda_prop_sd = tau_lambda * 0.5  # Start with 0.5× SE

# Acceptance counters
garch_accept = np.zeros(3)
garch_total = np.zeros(3)
lambda_accept = np.zeros(n_components)
lambda_total = np.zeros(n_components)

print(f"    Total: {n_total} | Burn-in: {n_burn} | Sample: {n_sample}")
print(f"    Components: {n_components} | c = {c_val} | P(δ=1) = {P_prior}")
print(f"    Component-wise MH (K433 lesson: joint MH → all-reject)")

def compute_augmented_h(returns, omega, alpha, beta, lambdas, deltas, components):
    """Compute augmented GARCH conditional variance series.

    h_t = ω + α·ε²_{t-1} + β·h_{t-1} + Σ δ_k·λ_k·C_k(t)

    Parameters are applied only when δ_k=1.
    """
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    n_comp = len(lambdas)

    for t in range(1, T):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        for k in range(n_comp):
            if deltas[k] == 1:
                h[t] += lambdas[k] * components[t, k]
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def log_likelihood(returns, h):
    """Gaussian log-likelihood."""
    return -0.5 * np.sum(np.log(h) + returns**2 / h)

def log_prior_garch(omega, alpha, beta):
    """Weakly informative prior for base GARCH parameters."""
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return -np.inf
    # Weak log-normal prior on omega to keep it positive
    if omega > var_y * 10:
        return -np.inf
    return 0.0

# Pre-compute current state
h_curr = compute_augmented_h(y_train, omega_curr, alpha_curr, beta_curr,
                              lambda_curr, delta_curr, C_train)
ll_curr = log_likelihood(y_train, h_curr)

mcmc_start = time.time()

# Adaptive tuning
tune_interval = 200
target_accept_low = 0.20
target_accept_high = 0.50

garch_prop_sds = np.array([omega_prop_sd, alpha_prop_sd, beta_prop_sd])

print("    Starting MCMC iterations...")

for iteration in range(n_total):
    # === (a) Draw base GARCH parameters COMPONENT-WISE ===
    garch_curr = np.array([omega_curr, alpha_curr, beta_curr])

    for g in range(3):  # omega, alpha, beta
        garch_prop = garch_curr.copy()
        garch_prop[g] += np.random.normal(0, garch_prop_sds[g])

        lp_prop = log_prior_garch(garch_prop[0], garch_prop[1], garch_prop[2])
        garch_total[g] += 1

        if lp_prop > -np.inf:
            h_prop = compute_augmented_h(y_train, garch_prop[0], garch_prop[1], garch_prop[2],
                                          lambda_curr, delta_curr, C_train)
            ll_prop = log_likelihood(y_train, h_prop)

            log_ratio = (ll_prop + lp_prop) - (ll_curr + log_prior_garch(garch_curr[0], garch_curr[1], garch_curr[2]))

            if np.log(np.random.uniform()) < log_ratio:
                garch_curr = garch_prop
                h_curr = h_prop
                ll_curr = ll_prop
                garch_accept[g] += 1

    omega_curr, alpha_curr, beta_curr = garch_curr

    # === (b) Draw lambda parameters COMPONENT-WISE ===
    for k in range(n_components):
        lambda_prop = lambda_curr.copy()
        lambda_prop[k] += np.random.normal(0, lambda_prop_sd[k])

        lambda_total[k] += 1

        # Compute h with proposed lambda
        h_prop = compute_augmented_h(y_train, omega_curr, alpha_curr, beta_curr,
                                      lambda_prop, delta_curr, C_train)
        ll_prop = log_likelihood(y_train, h_prop)

        # SSVS prior for lambda_k
        if delta_curr[k] == 1:
            sd_k = c_vec[k] * tau_lambda[k]
        else:
            sd_k = tau_lambda[k]
        sd_k = max(sd_k, 1e-10)

        lp_prop_k = stats.norm.logpdf(lambda_prop[k], 0, sd_k)
        lp_curr_k = stats.norm.logpdf(lambda_curr[k], 0, sd_k)

        log_ratio = (ll_prop + lp_prop_k) - (ll_curr + lp_curr_k)

        if np.isfinite(log_ratio) and np.log(np.random.uniform()) < log_ratio:
            lambda_curr = lambda_prop
            h_curr = h_prop
            ll_curr = ll_prop
            lambda_accept[k] += 1

    # === (c) Draw δ_i from Bernoulli conditional posterior ===
    for k in range(n_components):
        sd_incl = c_vec[k] * tau_lambda[k]
        sd_excl = tau_lambda[k]
        sd_incl = max(sd_incl, 1e-10)
        sd_excl = max(sd_excl, 1e-10)

        log_A = stats.norm.logpdf(lambda_curr[k], 0, sd_incl) + np.log(P_vec[k])
        log_B = stats.norm.logpdf(lambda_curr[k], 0, sd_excl) + np.log(1 - P_vec[k])

        # Numerically stable sigmoid
        log_max = max(log_A, log_B)
        p_incl = np.exp(log_A - log_max) / (np.exp(log_A - log_max) + np.exp(log_B - log_max))

        # But we also need to check if including/excluding changes the likelihood
        # For pure SSVS on variance eq, δ affects h_t directly.
        # Full conditional: P(δ_k=1|rest) ∝ p(y|δ_k=1,...) · p(λ_k|δ_k=1) · P(δ_k=1)

        # Compute likelihood under both δ_k states
        delta_incl = delta_curr.copy()
        delta_excl = delta_curr.copy()
        delta_incl[k] = 1
        delta_excl[k] = 0

        h_incl = compute_augmented_h(y_train, omega_curr, alpha_curr, beta_curr,
                                      lambda_curr, delta_incl, C_train)
        h_excl = compute_augmented_h(y_train, omega_curr, alpha_curr, beta_curr,
                                      lambda_curr, delta_excl, C_train)

        ll_incl = log_likelihood(y_train, h_incl)
        ll_excl = log_likelihood(y_train, h_excl)

        # Full conditional posterior for δ_k
        log_A_full = ll_incl + stats.norm.logpdf(lambda_curr[k], 0, sd_incl) + np.log(P_vec[k])
        log_B_full = ll_excl + stats.norm.logpdf(lambda_curr[k], 0, sd_excl) + np.log(1 - P_vec[k])

        log_max_full = max(log_A_full, log_B_full)
        p_incl_full = np.exp(log_A_full - log_max_full) / \
                      (np.exp(log_A_full - log_max_full) + np.exp(log_B_full - log_max_full))

        if not np.isfinite(p_incl_full):
            p_incl_full = 0.5

        delta_curr[k] = np.random.binomial(1, p_incl_full)

    # Update h_curr after delta changes
    h_curr = compute_augmented_h(y_train, omega_curr, alpha_curr, beta_curr,
                                  lambda_curr, delta_curr, C_train)
    ll_curr = log_likelihood(y_train, h_curr)

    # === Adaptive tuning during burn-in ===
    if iteration < n_burn and iteration > 0 and iteration % tune_interval == 0:
        for g in range(3):
            if garch_total[g] > 0:
                rate = garch_accept[g] / garch_total[g]
                if rate < target_accept_low:
                    garch_prop_sds[g] *= 0.7
                elif rate > target_accept_high:
                    garch_prop_sds[g] *= 1.3

        for k in range(n_components):
            if lambda_total[k] > 0:
                rate = lambda_accept[k] / lambda_total[k]
                if rate < target_accept_low:
                    lambda_prop_sd[k] *= 0.7
                elif rate > target_accept_high:
                    lambda_prop_sd[k] *= 1.3

        if iteration % 1000 == 0:
            g_rates = garch_accept / np.maximum(garch_total, 1)
            l_rates = lambda_accept / np.maximum(lambda_total, 1)
            elapsed = time.time() - mcmc_start
            print(f"      Iter {iteration:5d} | GARCH accept: {g_rates.mean():.3f} | "
                  f"λ accept: {l_rates.mean():.3f} | "
                  f"δ: {delta_curr} | elapsed: {elapsed:.1f}s")

        # Reset counters after tuning
        garch_accept[:] = 0
        garch_total[:] = 0
        lambda_accept[:] = 0
        lambda_total[:] = 0

    # === Store post-burn-in samples ===
    if iteration >= n_burn:
        idx = iteration - n_burn
        lambda_samples[idx] = lambda_curr
        delta_samples[idx] = delta_curr
        garch_samples[idx] = [omega_curr, alpha_curr, beta_curr]

    # Progress
    if iteration > 0 and iteration % 2000 == 0:
        elapsed = time.time() - mcmc_start
        rate = iteration / elapsed
        eta = (n_total - iteration) / rate
        print(f"      Iter {iteration:5d}/{n_total} | "
              f"Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s | "
              f"LL: {ll_curr:.1f}")

mcmc_elapsed = time.time() - mcmc_start
print(f"\n    MCMC completed in {mcmc_elapsed:.1f}s ({n_total/mcmc_elapsed:.0f} iter/s)")

# Final acceptance rates
final_g_rates = garch_accept / np.maximum(garch_total, 1)
final_l_rates = lambda_accept / np.maximum(lambda_total, 1)
print(f"    Final GARCH accept: ω={final_g_rates[0]:.3f}, α={final_g_rates[1]:.3f}, β={final_g_rates[2]:.3f}")
print(f"    Final λ accept: {[f'{r:.3f}' for r in final_l_rates]}")

# ============================================================
# 7. POSTERIOR ANALYSIS
# ============================================================
print("\n[7] Posterior Analysis...")

# 7a. Posterior Inclusion Probabilities
pip = delta_samples.mean(axis=0)
print("\n  Posterior Inclusion Probabilities P(δ_k=1|data):")
print("  " + "-" * 60)
for k in range(n_components):
    indicator = "***" if pip[k] > 0.5 else ("**" if pip[k] > 0.3 else "")
    print(f"    [{k}] {component_names[k]:25s}: PIP = {pip[k]:.4f} {indicator}")
print("  " + "-" * 60)
print("  *** = PIP > 0.5 (strong evidence) | ** = PIP > 0.3 (moderate)")

# 7b. Lambda posterior estimates
print("\n  Posterior parameter estimates:")
lambda_mean = lambda_samples.mean(axis=0)
lambda_std = lambda_samples.std(axis=0)
lambda_p025 = np.percentile(lambda_samples, 2.5, axis=0)
lambda_p975 = np.percentile(lambda_samples, 97.5, axis=0)

for k in range(n_components):
    sig = "*" if (lambda_p025[k] > 0 and lambda_p975[k] > 0) or \
                 (lambda_p025[k] < 0 and lambda_p975[k] < 0) else " "
    print(f"    {component_names[k]:25s}: λ={lambda_mean[k]:9.6f} ± {lambda_std[k]:.6f}  "
          f"[{lambda_p025[k]:9.6f}, {lambda_p975[k]:9.6f}] PIP={pip[k]:.4f} {sig}")

# 7c. GARCH base parameters
garch_mean = garch_samples.mean(axis=0)
garch_std = garch_samples.std(axis=0)
print(f"\n  Base GARCH parameters (posterior):")
print(f"    ω: {garch_mean[0]:.6f} ± {garch_std[0]:.6f}")
print(f"    α: {garch_mean[1]:.4f} ± {garch_std[1]:.4f}")
print(f"    β: {garch_mean[2]:.4f} ± {garch_std[2]:.4f}")
print(f"    persistence: {garch_mean[1] + garch_mean[2]:.4f}")

# 7d. Top subset models
print("\n  Top 10 most visited variance equation models:")
from collections import Counter
delta_tuples = [tuple(row) for row in delta_samples]
model_counts = Counter(delta_tuples)
top_models = model_counts.most_common(10)

for rank, (model, count) in enumerate(top_models):
    prob = count / n_sample
    n_comp_sel = sum(model)
    selected = [component_names[i] for i in range(n_components) if model[i] == 1]
    sel_str = ", ".join(selected) if selected else "(base GARCH only)"
    print(f"    #{rank+1}: P={prob:.4f} | k={n_comp_sel} | {sel_str}")

# Best model
best_model = top_models[0][0]
best_prob = top_models[0][1] / n_sample
best_components = [component_names[i] for i in range(n_components) if best_model[i] == 1]

# 7e. MCMC diagnostics - ESS
def effective_sample_size(chain):
    """Estimate ESS using initial positive sequence estimator."""
    n = len(chain)
    if np.std(chain) < 1e-10:
        return float(n)
    mean_c = np.mean(chain)
    var_c = np.var(chain)
    if var_c < 1e-20:
        return float(n)
    max_lag = min(n // 2, 500)
    chain_centered = chain - mean_c
    autocorr = np.zeros(max_lag)
    for lag in range(max_lag):
        autocorr[lag] = np.mean(chain_centered[:n-lag] * chain_centered[lag:]) / var_c
    tau = 1.0
    for k_lag in range(1, max_lag - 1, 2):
        pair_sum = autocorr[k_lag] + autocorr[k_lag+1]
        if pair_sum < 0:
            break
        tau += 2 * pair_sum
    ess = n / tau
    return max(ess, 1.0)

print("\n  Effective Sample Sizes:")
for k in range(n_components):
    ess_l = effective_sample_size(lambda_samples[:, k])
    ess_d = effective_sample_size(delta_samples[:, k].astype(float))
    print(f"    {component_names[k]:25s}: ESS(λ)={ess_l:7.0f}, ESS(δ)={ess_d:7.0f}")
for g, name in enumerate(['omega', 'alpha', 'beta']):
    ess_g = effective_sample_size(garch_samples[:, g])
    print(f"    GARCH {name:5s}              : ESS={ess_g:7.0f}")

# ============================================================
# 8. OUT-OF-SAMPLE EVALUATION
# ============================================================
print("\n[8] Out-of-Sample Evaluation (2023-2024)...")

# Realized variance proxy (squared returns)
rv_test = y_test**2

# Model 1: Base GARCH(1,1) — use posterior mean params
print("\n  --- Model 1: Base GARCH(1,1) ---")
garch_base_params = garch_mean.copy()
# Use MLE for fair comparison (posterior mean might be biased by augmented model)
garch_base_params_mle = np.array([omega_mle, alpha_mle, beta_mle])
# Actually re-fit on training data only
res_base_train = minimize(garch11_negloglik, [var_y*0.05, 0.08, 0.88],
                          args=(y_train,), method='L-BFGS-B', bounds=bounds)
garch_base_mle = res_base_train.x
print(f"  Params: ω={garch_base_mle[0]:.6f}, α={garch_base_mle[1]:.4f}, β={garch_base_mle[2]:.4f}")

h_base_oos = np.zeros(T_test)
h_last = np.var(y_train)
e_last = y_train[-1]
for t in range(T_test):
    h_pred = garch_base_mle[0] + garch_base_mle[1] * e_last**2 + garch_base_mle[2] * h_last
    h_pred = max(h_pred, 1e-8)
    h_base_oos[t] = h_pred
    e_last = y_test[t]
    h_last = h_pred

# Model 2: SSVS Median Model (components with PIP > 0.5)
print("\n  --- Model 2: SSVS Median Model ---")
median_mask = pip > 0.5
n_sel_median = median_mask.sum()
print(f"  Selected components ({n_sel_median}):")
for k in range(n_components):
    if median_mask[k]:
        print(f"    - {component_names[k]} (PIP={pip[k]:.4f})")
if n_sel_median == 0:
    print(f"    (none — SSVS prefers base GARCH)")

# Use posterior mean of lambda (conditional on delta=1)
lambda_median_model = np.zeros(n_components)
for k in range(n_components):
    if median_mask[k]:
        # Mean of lambda when delta=1
        mask_k_incl = delta_samples[:, k] == 1
        if mask_k_incl.sum() > 10:
            lambda_median_model[k] = lambda_samples[mask_k_incl, k].mean()
        else:
            lambda_median_model[k] = lambda_mean[k]

h_median_oos = np.zeros(T_test)
h_last = np.var(y_train)
e_last = y_train[-1]
for t in range(T_test):
    h_pred = garch_mean[0] + garch_mean[1] * e_last**2 + garch_mean[2] * h_last
    for k in range(n_components):
        if median_mask[k]:
            h_pred += lambda_median_model[k] * C_test[t, k]
    h_pred = max(h_pred, 1e-8)
    h_median_oos[t] = h_pred
    e_last = y_test[t]
    h_last = h_pred

# Model 3: SSVS Best Model (most visited configuration)
print(f"\n  --- Model 3: SSVS Best Model ---")
best_delta = np.array(best_model)
n_sel_best = best_delta.sum()
print(f"  Components ({n_sel_best}):")
for k in range(n_components):
    if best_delta[k] == 1:
        print(f"    - {component_names[k]}")
if n_sel_best == 0:
    print(f"    (none — base GARCH)")

lambda_best_model = np.zeros(n_components)
for k in range(n_components):
    if best_delta[k] == 1:
        mask_k_incl = delta_samples[:, k] == 1
        if mask_k_incl.sum() > 10:
            lambda_best_model[k] = lambda_samples[mask_k_incl, k].mean()
        else:
            lambda_best_model[k] = lambda_mean[k]

h_best_oos = np.zeros(T_test)
h_last = np.var(y_train)
e_last = y_train[-1]
for t in range(T_test):
    h_pred = garch_mean[0] + garch_mean[1] * e_last**2 + garch_mean[2] * h_last
    for k in range(n_components):
        if best_delta[k] == 1:
            h_pred += lambda_best_model[k] * C_test[t, k]
    h_pred = max(h_pred, 1e-8)
    h_best_oos[t] = h_pred
    e_last = y_test[t]
    h_last = h_pred

# Model 4: Kitchen Sink (all components included, MLE)
print(f"\n  --- Model 4: Kitchen Sink (all components, MLE) ---")
# Re-fit augmented GARCH on training data
res_ks = minimize(augmented_garch_negloglik, x0_aug, args=(y_train, C_train),
                  method='L-BFGS-B', bounds=bounds_aug)
ks_params = res_ks.x
print(f"  Params: ω={ks_params[0]:.6f}, α={ks_params[1]:.4f}, β={ks_params[2]:.4f}")
for k, name in enumerate(component_names):
    print(f"    λ_{name}: {ks_params[3+k]:.6f}")

h_ks_oos = np.zeros(T_test)
h_last = np.var(y_train)
e_last = y_train[-1]
for t in range(T_test):
    h_pred = ks_params[0] + ks_params[1] * e_last**2 + ks_params[2] * h_last
    for k in range(n_components):
        h_pred += ks_params[3+k] * C_test[t, k]
    h_pred = max(h_pred, 1e-8)
    h_ks_oos[t] = h_pred
    e_last = y_test[t]
    h_last = h_pred

# Model 5: GJR-GARCH only (MLE, for comparison)
print(f"\n  --- Model 5: GJR-GARCH only (MLE) ---")
def gjr_garch_negloglik(params, returns):
    omega, alpha, beta, gamma = params
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5*gamma >= 0.9999:
        return 1e10
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1] + gamma * indicator * returns[t-1]**2
        if h[t] < 1e-10:
            h[t] = 1e-10
    return -(-0.5 * np.sum(np.log(h) + returns**2 / h))

x0_gjr = [var_y*0.05, 0.05, 0.88, 0.05]
bounds_gjr = [(1e-6, var_y*5), (1e-6, 0.4), (0.3, 0.9999), (1e-6, 0.4)]
res_gjr = minimize(gjr_garch_negloglik, x0_gjr, args=(y_train,),
                   method='L-BFGS-B', bounds=bounds_gjr)
gjr_params = res_gjr.x
print(f"  Params: ω={gjr_params[0]:.6f}, α={gjr_params[1]:.4f}, β={gjr_params[2]:.4f}, γ={gjr_params[3]:.4f}")

h_gjr_oos = np.zeros(T_test)
h_last = np.var(y_train)
e_last = y_train[-1]
for t in range(T_test):
    indicator = 1.0 if e_last < 0 else 0.0
    h_pred = gjr_params[0] + gjr_params[1] * e_last**2 + gjr_params[2] * h_last + gjr_params[3] * indicator * e_last**2
    h_pred = max(h_pred, 1e-8)
    h_gjr_oos[t] = h_pred
    e_last = y_test[t]
    h_last = h_pred

# ============================================================
# 9. EVALUATION METRICS
# ============================================================
print("\n[9] Computing evaluation metrics...")

def compute_qlike(rv, h_forecast):
    """QLIKE loss: E[RV/h - log(RV/h) - 1]."""
    ratio = rv / h_forecast
    return np.mean(ratio - np.log(ratio) - 1)

def compute_mse(rv, h_forecast):
    """MSE loss."""
    return np.mean((rv - h_forecast)**2)

# Use |RV| to avoid issues with zero realized variance
rv_proxy = rv_test.copy()
rv_proxy[rv_proxy < 1e-10] = 1e-10

models = {
    'Base GARCH(1,1)': h_base_oos,
    'SSVS Median Model': h_median_oos,
    'SSVS Best Model': h_best_oos,
    'Kitchen Sink (all)': h_ks_oos,
    'GJR-GARCH (MLE)': h_gjr_oos,
}

results_oos = {}
print(f"\n  OOS Results (T_test={T_test}):")
print(f"  {'Model':<25s} {'QLIKE':>10s} {'MSE':>12s} {'ΔQLIKE%':>10s}")
print("  " + "-" * 60)

baseline_qlike = compute_qlike(rv_proxy, h_base_oos)
baseline_mse = compute_mse(rv_proxy, h_base_oos)

for name, h_oos in models.items():
    qlike = compute_qlike(rv_proxy, h_oos)
    mse = compute_mse(rv_proxy, h_oos)
    delta_qlike = (qlike - baseline_qlike) / baseline_qlike * 100
    print(f"  {name:<25s} {qlike:10.4f} {mse:12.4f} {delta_qlike:+10.4f}%")
    results_oos[name] = {
        'QLIKE': float(qlike),
        'MSE': float(mse),
        'relative_QLIKE_pct': float(delta_qlike),
    }

# ============================================================
# 10. DIEBOLD-MARIANO TESTS
# ============================================================
print("\n[10] Diebold-Mariano tests vs. Base GARCH(1,1)...")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Negative DM stat → model2 better (lower loss)."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k/h) * gamma_k
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

base_loss = np.log(h_base_oos) + rv_proxy / h_base_oos  # QLIKE loss series: log(h) + rv/h

dm_results = {}
print(f"\n  {'Model':<25s} {'DM stat':>10s} {'p-value':>10s} {'Interpretation':>20s}")
print("  " + "-" * 68)

for name, h_oos in models.items():
    if name == 'Base GARCH(1,1)':
        continue
    model_loss = np.log(h_oos) + rv_proxy / h_oos  # QLIKE loss: log(h) + rv/h
    dm_stat, dm_p = dm_test(base_loss, model_loss)

    # d = base_loss - model_loss. If d > 0, baseline has higher loss → model is better.
    if np.isnan(dm_stat):
        interp = "inconclusive"
    elif dm_stat > 0 and dm_p < 0.05:
        interp = "model BETTER*"
    elif dm_stat < 0 and dm_p < 0.05:
        interp = "baseline BETTER*"
    else:
        interp = "no sig. difference"

    print(f"  {name:<25s} {dm_stat:10.4f} {dm_p:10.4f} {interp:>20s}")
    dm_results[name] = {
        'dm_stat': dm_stat,
        'p_value': dm_p,
        'interpretation': interp,
    }

# ============================================================
# 11. BIC COMPARISON (in-sample)
# ============================================================
print("\n[11] BIC comparison (in-sample)...")

def compute_bic(neg_ll, n_params, T):
    return 2 * neg_ll + n_params * np.log(T)

bic_base = compute_bic(garch11_negloglik(garch_base_mle, y_train), 3, T_train)
bic_gjr = compute_bic(gjr_garch_negloglik(gjr_params, y_train), 4, T_train)
bic_ks = compute_bic(augmented_garch_negloglik(ks_params, y_train, C_train), 3+n_components, T_train)

# SSVS median model BIC (if any selected)
if n_sel_median > 0:
    # Fit median model via MLE for fair BIC
    sel_idx = [k for k in range(n_components) if median_mask[k]]
    C_sel = C_train[:, sel_idx]

    def median_model_nll(params, returns, components):
        omega, alpha, beta = params[:3]
        lambdas = params[3:]
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        T = len(returns)
        h = np.zeros(T)
        h[0] = np.var(returns)
        for t in range(1, T):
            h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
            for j in range(len(lambdas)):
                h[t] += lambdas[j] * components[t, j]
            if h[t] < 1e-8:
                h[t] = 1e-8
        return -(-0.5 * np.sum(np.log(h) + returns**2 / h))

    x0_med = list(garch_base_mle) + [0.01] * len(sel_idx)
    bounds_med = list(bounds) + [(-1.0, 2.0)] * len(sel_idx)
    res_med = minimize(median_model_nll, x0_med, args=(y_train, C_sel),
                       method='L-BFGS-B', bounds=bounds_med)
    bic_median = compute_bic(res_med.fun, 3 + len(sel_idx), T_train)
else:
    bic_median = bic_base

print(f"  Base GARCH(1,1):      BIC = {bic_base:.2f} (3 params)")
print(f"  GJR-GARCH:            BIC = {bic_gjr:.2f} (4 params)")
print(f"  SSVS Median:          BIC = {bic_median:.2f} ({3+n_sel_median} params)")
print(f"  Kitchen Sink:         BIC = {bic_ks:.2f} ({3+n_components} params)")

best_bic_model = min(
    [('Base GARCH(1,1)', bic_base), ('GJR-GARCH', bic_gjr),
     ('SSVS Median', bic_median), ('Kitchen Sink', bic_ks)],
    key=lambda x: x[1]
)
print(f"\n  Best BIC: {best_bic_model[0]} ({best_bic_model[1]:.2f})")

# ============================================================
# 12. RESIDUAL DIAGNOSTICS
# ============================================================
print("\n[12] Residual diagnostics (base GARCH on training)...")
h_train_base = np.zeros(T_train)
h_train_base[0] = np.var(y_train)
for t in range(1, T_train):
    h_train_base[t] = garch_base_mle[0] + garch_base_mle[1] * y_train[t-1]**2 + garch_base_mle[2] * h_train_base[t-1]
    h_train_base[t] = max(h_train_base[t], 1e-8)

std_resid = y_train / np.sqrt(h_train_base)
print(f"  Standardized residuals: mean={std_resid.mean():.4f}, std={std_resid.std():.4f}, "
      f"skew={stats.skew(std_resid):.3f}, kurt={stats.kurtosis(std_resid):.3f}")

# ARCH LM on standardized residuals
try:
    arch_stat_r, arch_pval_r, *_ = het_arch(std_resid**2, nlags=5)
    print(f"  ARCH LM on std resid² (5 lags): stat={arch_stat_r:.2f}, p={arch_pval_r:.4f} → "
          f"{'Remaining ARCH' if arch_pval_r < 0.05 else 'No remaining ARCH'}")
except:
    print("  ARCH LM on std resid: computation failed")

# Ljung-Box on squared standardized residuals
try:
    lb_r = acorr_ljungbox(std_resid**2, lags=[10], return_df=True)
    lb_r_stat = lb_r['lb_stat'].values[0]
    lb_r_pval = lb_r['lb_pvalue'].values[0]
    print(f"  Ljung-Box on std resid² (10 lags): stat={lb_r_stat:.2f}, p={lb_r_pval:.4f}")
except:
    print("  Ljung-Box: computation failed")

# ============================================================
# 13. SUMMARY AND CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

total_time = time.time() - start_time

print(f"\n  Asset: SPY | Period: {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"  Train: {T_train} obs | OOS: {T_test} obs")
print(f"  MCMC: {n_total} iter ({n_burn} burn-in, {n_sample} sample)")
print(f"  Total time: {total_time:.1f}s")

print(f"\n  Posterior Inclusion Probabilities:")
for k in range(n_components):
    bar = "█" * int(pip[k] * 30)
    print(f"    {component_names[k]:25s}: {pip[k]:.4f} |{bar}")

# Determine which components are selected
strong_selected = [component_names[k] for k in range(n_components) if pip[k] > 0.5]
moderate_evidence = [component_names[k] for k in range(n_components) if 0.3 < pip[k] <= 0.5]
weak_evidence = [component_names[k] for k in range(n_components) if pip[k] <= 0.3]

print(f"\n  Strong evidence (PIP > 0.5): {strong_selected if strong_selected else 'NONE'}")
print(f"  Moderate evidence (0.3-0.5): {moderate_evidence if moderate_evidence else 'NONE'}")
print(f"  Weak/excluded (PIP ≤ 0.3):  {weak_evidence if weak_evidence else 'NONE'}")

# Best OOS model
best_oos = min(results_oos.items(), key=lambda x: x[1]['QLIKE'])
print(f"\n  Best OOS (QLIKE): {best_oos[0]} ({best_oos[1]['QLIKE']:.4f})")
print(f"  Base GARCH QLIKE: {results_oos['Base GARCH(1,1)']['QLIKE']:.4f}")

# Interpretation
if not strong_selected:
    if not moderate_evidence:
        interpretation = (
            "SSVS with 2^5=32 variance equation configurations confirms "
            "base GARCH(1,1) for SPY. No extension component (GJR, VIX, range, "
            "semivariance, absolute shock) achieves PIP > 0.5. The GARCH variance "
            "equation ceiling extends from the mean equation (K433) to structure itself."
        )
    else:
        interpretation = (
            f"SSVS finds moderate evidence for {', '.join(moderate_evidence)} "
            f"(PIP 0.3-0.5) but no component crosses the 0.5 threshold. "
            f"The base GARCH(1,1) remains the most parsimonious choice."
        )
else:
    interpretation = (
        f"SSVS selects {{{', '.join(strong_selected)}}} (PIP > 0.5) as "
        f"valuable variance equation components for SPY. "
    )
    if 'GJR_asymmetry' in strong_selected:
        interpretation += "GJR asymmetry is confirmed as the most important extension. "
    if len(strong_selected) > 1:
        interpretation += (
            f"Multiple extensions improve upon base GARCH, suggesting "
            f"the variance equation has more room for enrichment than the mean equation."
        )

print(f"\n  Interpretation: {interpretation}")

# ============================================================
# 14. SAVE RESULTS
# ============================================================
print("\n[14] Saving results...")

results = {
    "experiment_id": "K484",
    "title": "SSVS for Variance Equation Component Selection",
    "method": "Stochastic Search Variable Selection applied to GARCH variance equation",
    "innovation": "K433 applied SSVS to mean equation (null result). K484 extends to variance equation: which GARCH extensions are worth keeping?",
    "proposed_by": "User (creative extension of SSVS from mean eq to variance eq)",
    "asset": "SPY",
    "data_source": "yfinance (empirical)",
    "data_period": f"{spy.index[0].date()} to {spy.index[-1].date()}",
    "sample_split": {
        "total": int(T),
        "train": int(T_train),
        "test": int(T_test),
        "oos_start": oos_start_date,
    },
    "variance_equation_spec": {
        "base": "h_t = ω + α·ε²_{t-1} + β·h_{t-1}",
        "augmented": "h_t = base + Σ δ_k·λ_k·C_k(t)",
        "components": {
            "δ₁ GJR_asymmetry": "I(ε<0)·ε²_{t-1} — leverage effect",
            "δ₂ VIX_implied_var": "VIX²/252 — GARCH-X style",
            "δ₃ Parkinson_range": "(ln(H/L))²/(4ln2) — range-based info",
            "δ₄ Neg_semivariance": "5-day rolling RS⁻ — downside risk",
            "δ₅ Abs_shock_TGARCH": "|ε_{t-1}| — TGARCH/AVGARCH style",
        },
        "n_possible_configs": 32,  # 2^5
    },
    "mcmc_settings": {
        "total_iterations": n_total,
        "burn_in": n_burn,
        "effective_samples": n_sample,
        "c_value": c_val,
        "prior_inclusion_prob": P_prior,
        "tau_calibration": "MLE standard errors from augmented GARCH",
        "sampler": "Component-wise MH (K433 lesson)",
    },
    "mcmc_diagnostics": {
        "computation_time_seconds": float(mcmc_elapsed),
        "total_time_seconds": float(total_time),
        "final_garch_accept_rates": {
            "omega": float(final_g_rates[0]),
            "alpha": float(final_g_rates[1]),
            "beta": float(final_g_rates[2]),
        },
        "final_lambda_accept_rates": {
            name: float(final_l_rates[k]) for k, name in enumerate(component_names)
        },
    },
    "posterior_inclusion_probabilities": {
        name: {
            "PIP": float(pip[k]),
            "lambda_mean": float(lambda_mean[k]),
            "lambda_std": float(lambda_std[k]),
            "lambda_95CI": [float(lambda_p025[k]), float(lambda_p975[k])],
        }
        for k, name in enumerate(component_names)
    },
    "garch_posterior": {
        "omega": {"mean": float(garch_mean[0]), "std": float(garch_std[0])},
        "alpha": {"mean": float(garch_mean[1]), "std": float(garch_std[1])},
        "beta": {"mean": float(garch_mean[2]), "std": float(garch_std[2])},
        "persistence": float(garch_mean[1] + garch_mean[2]),
    },
    "top_models": [
        {
            "rank": rank + 1,
            "posterior_probability": float(count / n_sample),
            "n_components": int(sum(model)),
            "components": [component_names[i] for i in range(n_components) if model[i] == 1],
        }
        for rank, (model, count) in enumerate(top_models[:10])
    ],
    "oos_evaluation": results_oos,
    "dm_tests": dm_results,
    "bic_comparison": {
        "Base_GARCH": float(bic_base),
        "GJR_GARCH": float(bic_gjr),
        "SSVS_Median": float(bic_median),
        "Kitchen_Sink": float(bic_ks),
        "best": best_bic_model[0],
    },
    "conclusion": {
        "strong_pip_components": strong_selected,
        "moderate_pip_components": moderate_evidence,
        "weak_pip_components": weak_evidence,
        "ssvs_best_config": best_components if best_components else ["base GARCH only"],
        "ssvs_best_config_prob": float(best_prob),
        "best_oos_model": best_oos[0],
        "best_oos_qlike": float(best_oos[1]['QLIKE']),
        "baseline_qlike": float(results_oos['Base GARCH(1,1)']['QLIKE']),
        "interpretation": interpretation,
    },
    "references": [
        "So, Chen, Liu (2006) Best Subset Selection of ARX-GARCH, JRSS-C 55(2):201-224",
        "K433: SSVS for mean equation → null model wins (PIP all < 0.25)",
        "K438: GARCH-X VIX borderline for SPY",
        "K449/K460: Negative semivariance effective",
        "K465/K469: HAR range-based models effective",
    ],
}

# ESS results
ess_results = {}
for k, name in enumerate(component_names):
    ess_results[name] = {
        "ESS_lambda": float(effective_sample_size(lambda_samples[:, k])),
        "ESS_delta": float(effective_sample_size(delta_samples[:, k].astype(float))),
    }
for g, gname in enumerate(['omega', 'alpha', 'beta']):
    ess_results[f"GARCH_{gname}"] = {
        "ESS": float(effective_sample_size(garch_samples[:, g])),
    }
results["ess_diagnostics"] = ess_results

output_path = 'experiments/k484_ssvs_variance_eq_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K484 COMPLETE")
print("=" * 70)
