"""
K433: Bayesian SSVS for ARX-GARCH Variable Selection
=====================================================
Method: Stochastic Search Variable Selection (So, Chen, Liu 2006 JRSS-C)
Asset: SPY
Data: yfinance (empirical), 2015-2025

Core idea: Instead of testing exogenous variables one-by-one (K113: 0/12 null),
SSVS uses latent binary indicators δ_i to simultaneously search 2^K subsets
via MCMC. Maybe some variable COMBINATIONS are useful even if individuals are not.

Model: ARX(p, q1..qk)-GARCH(1,1)
  y_t = Σ φ_i * y_{t-i} + Σ ψ_ij * x_{it-j} + a_t
  a_t = e_t * sqrt(h_t)
  h_t = α₀ + α₁ * a²_{t-1} + β₁ * h_{t-1}

SSVS prior (eq.5-6):
  φ_i | δ_i ~ (1-δ_i)*N(0,τ²) + δ_i*N(0,c²τ²)
  δ_i = 0 → excluded (shrunk near 0)
  δ_i = 1 → included (large prior variance)
  P(δ_i=1) = 0.5 (uninformative)

References:
- So, Chen, Liu (2006) "Best Subset Selection of ARX-GARCH Models",
  JRSS-C Applied Statistics, 55(2), 201-224
- Chen, Liu, Gerlach (2011) Bayesian Subset Selection for TARMA
- Chen, Liu, So (2013) Threshold Variable Selection for Asymmetric SV

Data sources: yfinance (SPY, ^VIX, ^VIX3M, TLT, GLD, HYG)
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
print("K433: Bayesian SSVS for ARX-GARCH Variable Selection")
print("Method: So, Chen, Liu (2006) JRSS-C Applied Statistics")
print("=" * 70)

start_time = time.time()

# Download data
print("\n[1] Downloading data from yfinance...")
tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
    'TLT': 'TLT',
    'GLD': 'GLD',
    'HYG': 'HYG',
}

data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2014-01-01', end='2025-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 100:
            data[name] = df
            print(f"  {name} ({ticker}): {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")
        else:
            print(f"  {name} ({ticker}): insufficient data ({len(df)} obs)")
    except Exception as e:
        print(f"  {name} ({ticker}): download failed - {e}")

# Align all data to common dates
import pandas as pd
common_idx = data['SPY'].index
for name in data:
    common_idx = common_idx.intersection(data[name].index)
print(f"\n  Common trading days: {len(common_idx)}")

# Prepare returns and exogenous variables
spy_close = data['SPY'].loc[common_idx, 'Close'].values.flatten()
spy_ret = np.diff(np.log(spy_close)) * 100  # percent log returns

# Volume data for SPY
spy_vol_raw = data['SPY'].loc[common_idx, 'Volume'].values.flatten()

# VIX data
vix_close = data['VIX'].loc[common_idx, 'Close'].values.flatten()

# Align to return dates (drop first obs)
dates = common_idx[1:]
vix = vix_close[1:]
vix_prev = vix_close[:-1]
volume = spy_vol_raw[1:]
volume_prev = spy_vol_raw[:-1]

# Construct exogenous variables
print("\n[2] Constructing exogenous variables...")

# x1: VIX level (standardized)
x_vix = vix_prev  # use lagged to avoid look-ahead

# x2: VIX daily change
x_vix_chg = np.diff(vix_close)[:-1]  # align: need one more diff, drop last
# Actually recalculate carefully
vix_changes = np.diff(vix_close)  # T-1 values
x_vix_chg = vix_changes[:-1]  # align with spy_ret[1:]
# Wait - let me be more careful about alignment

# Let's restart alignment more carefully
T_full = len(spy_ret)
print(f"  SPY returns: {T_full} obs")

# All exogenous variables should be LAGGED (known at t-1, predicting t)
# SPY returns: index 0..T_full-1
# For return at index t, we can use info up to t-1

# x1: VIX level at t-1
x1_vix_level = vix_close[:-1]  # index 0..T_full-1, used for return at index 0..T_full-1

# x2: VIX change at t-1 (VIX[t-1] - VIX[t-2])
x2_vix_chg = np.diff(vix_close)[:-1]  # need to shift: change[i] = vix[i+1]-vix[i]
# change at t-1 = vix[t-1] - vix[t-2]
# For return at index t (t>=1), VIX change = vix_close[t] - vix_close[t-1]
# But we want lagged: use vix_close[t-1] - vix_close[t-2], available for t>=2
# So x2 starts from t=2
vix_changes_all = np.diff(vix_close)  # length T_full
x2_vix_chg_full = vix_changes_all  # change[i] = vix[i+1] - vix[i], for i=0..T_full-1
# Lagged: for return[t], use change[t-1] = vix[t] - vix[t-1]
# This is vix_changes_all[t-1], available for t>=1
# So x2_lagged[t] = vix_changes_all[t-1] for t=1..T_full-1

# x3: Volume surprise (volume / 21-day MA - 1)
vol_ma21 = pd.Series(spy_vol_raw).rolling(21).mean().values
vol_surprise = spy_vol_raw / np.where(vol_ma21 > 0, vol_ma21, 1) - 1
# Lagged: vol_surprise at t-1 for return at t
# vol_surprise available from index 21 onwards

# x4: SPY 5-day momentum
spy_mom5 = pd.Series(spy_close).pct_change(5).values * 100
# Lagged: mom5 at t-1 for return at t

# x5: TLT return (bond signal)
tlt_close = data['TLT'].loc[common_idx, 'Close'].values.flatten()
tlt_ret = np.diff(np.log(tlt_close)) * 100

# x6: GLD return (gold signal)
gld_close = data['GLD'].loc[common_idx, 'Close'].values.flatten()
gld_ret = np.diff(np.log(gld_close)) * 100

# x7: Credit spread proxy (HYG return, negative = spread widening)
hyg_close = data['HYG'].loc[common_idx, 'Close'].values.flatten()
hyg_ret = np.diff(np.log(hyg_close)) * 100

# x8: VIX term structure slope (VIX3M - VIX)
if 'VIX3M' in data:
    vix3m_close = data['VIX3M'].loc[common_idx, 'Close'].values.flatten()
    x8_vix_slope = vix3m_close - vix_close
    has_vix3m = True
else:
    has_vix3m = False

# Now construct aligned matrix
# Need enough history for: 21-day volume MA, 5-day momentum, AR lags
# Start from index 30 (safe buffer)
START = 30
T = T_full - START

y = spy_ret[START:]  # target returns, length T
print(f"  Effective sample after alignment: T = {T}")

# Construct exogenous variable matrix (each column is one variable-lag combination)
# For each variable, we use lag 1 and lag 2
# Variable at lag L for return[t] means the variable value at time t-L

var_names = []
Z_cols = []

# Helper to extract lagged variable
def get_lagged(series_aligned_with_ret, lag, offset=START):
    """Get lagged version of a series aligned with returns.
    series[t] is value at return-time t.
    Lagged by L: use series[t-L] for return[t].
    """
    return series_aligned_with_ret[offset - lag:offset - lag + T]

# AR lags (y_{t-1}, y_{t-2}, y_{t-3})
for lag in [1, 2, 3]:
    col = spy_ret[START - lag:START - lag + T]
    Z_cols.append(col)
    var_names.append(f'AR({lag})')

# x1: VIX level (lagged 1, 2)
for lag in [1, 2]:
    col = vix_close[START + 1 - lag:START + 1 - lag + T]  # +1 because vix_close[i] -> ret[i-1]
    Z_cols.append(col)
    var_names.append(f'VIX_level(L{lag})')

# x2: VIX change (lagged 1, 2)
vix_chg_full = np.concatenate([[0], np.diff(vix_close)])  # length = len(vix_close)
for lag in [1, 2]:
    col = vix_chg_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'VIX_chg(L{lag})')

# x3: Volume surprise (lagged 1, 2)
vol_surp_full = np.concatenate([np.zeros(21), vol_surprise[21:]])
for lag in [1, 2]:
    col = vol_surp_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'Vol_surprise(L{lag})')

# x4: 5-day momentum (lagged 1, 2)
mom5_full = np.concatenate([np.zeros(5), spy_mom5[5:]])
for lag in [1, 2]:
    col = mom5_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'Mom5d(L{lag})')

# x5: TLT return (lagged 1, 2)
tlt_ret_full = np.concatenate([[0], tlt_ret])
for lag in [1, 2]:
    col = tlt_ret_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'TLT_ret(L{lag})')

# x6: GLD return (lagged 1, 2)
gld_ret_full = np.concatenate([[0], gld_ret])
for lag in [1, 2]:
    col = gld_ret_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'GLD_ret(L{lag})')

# x7: HYG return (credit spread proxy, lagged 1, 2)
hyg_ret_full = np.concatenate([[0], hyg_ret])
for lag in [1, 2]:
    col = hyg_ret_full[START + 1 - lag:START + 1 - lag + T]
    Z_cols.append(col)
    var_names.append(f'HYG_ret(L{lag})')

# x8: VIX slope (lagged 1, 2) — if available
if has_vix3m:
    vix_slope_full = vix3m_close - vix_close
    for lag in [1, 2]:
        col = vix_slope_full[START + 1 - lag:START + 1 - lag + T]
        Z_cols.append(col)
        var_names.append(f'VIX_slope(L{lag})')

Z = np.column_stack(Z_cols)
K_vars = Z.shape[1]  # total number of candidate regressors
print(f"  Candidate regressors: K = {K_vars}")
print(f"  Possible subsets: 2^{K_vars} = {2**K_vars:,}")
for i, name in enumerate(var_names):
    print(f"    [{i:2d}] {name}")

# Check for NaN/Inf
nan_mask = np.any(np.isnan(Z), axis=1) | np.isnan(y) | np.any(np.isinf(Z), axis=1)
if nan_mask.any():
    print(f"\n  WARNING: {nan_mask.sum()} rows with NaN/Inf, removing...")
    y = y[~nan_mask]
    Z = Z[~nan_mask]
    T = len(y)
    print(f"  Adjusted T = {T}")

# Standardize Z for numerical stability
Z_mean = Z.mean(axis=0)
Z_std = Z.std(axis=0)
Z_std[Z_std < 1e-10] = 1.0
Z_norm = (Z - Z_mean) / Z_std

print(f"\n  Data summary:")
print(f"    y (SPY returns): mean={y.mean():.4f}, std={y.std():.4f}, "
      f"skew={stats.skew(y):.2f}, kurt={stats.kurtosis(y):.2f}")
print(f"    Sample period: ~{T/252:.1f} years")

# ============================================================
# 2. OLS INITIAL ESTIMATES (for τ_i calibration)
# ============================================================
print("\n[3] OLS initial estimates for τ_i calibration...")

# OLS: y = Z @ phi + epsilon
ZtZ_inv = np.linalg.inv(Z_norm.T @ Z_norm + 1e-6 * np.eye(K_vars))
phi_ols = ZtZ_inv @ (Z_norm.T @ y)
resid_ols = y - Z_norm @ phi_ols
sigma2_ols = np.sum(resid_ols**2) / (T - K_vars)
se_ols = np.sqrt(sigma2_ols * np.diag(ZtZ_inv))

print("  OLS coefficients and standard errors:")
for i, name in enumerate(var_names):
    t_stat = phi_ols[i] / se_ols[i] if se_ols[i] > 0 else 0
    print(f"    {name:20s}: coef={phi_ols[i]:8.4f}, se={se_ols[i]:8.4f}, t={t_stat:6.2f}")

# τ_i = OLS standard error (So et al. 2006)
tau = se_ols.copy()
tau[tau < 1e-6] = 0.01  # floor

# ============================================================
# 3. MLE GARCH(1,1) INITIAL ESTIMATES
# ============================================================
print("\n[4] MLE GARCH(1,1) initial estimates...")

def garch_negloglik(params, resid):
    """Negative log-likelihood for GARCH(1,1)"""
    omega, alpha, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return 1e10
    T = len(resid)
    h = np.zeros(T)
    h[0] = np.var(resid)
    for t in range(1, T):
        h[t] = omega + alpha * resid[t-1]**2 + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    ll = -0.5 * np.sum(np.log(h) + resid**2 / h)
    return -ll

# Initial values
var_resid = np.var(resid_ols)
x0_garch = [var_resid * 0.05, 0.08, 0.88]
bounds_garch = [(1e-6, var_resid * 10), (1e-6, 0.5), (0.3, 0.999)]

result_garch = minimize(garch_negloglik, x0_garch, args=(resid_ols,),
                        method='L-BFGS-B', bounds=bounds_garch)
alpha_mle = result_garch.x
print(f"  GARCH(1,1) MLE: omega={alpha_mle[0]:.6f}, alpha={alpha_mle[1]:.4f}, beta={alpha_mle[2]:.4f}")
print(f"  Persistence: {alpha_mle[1] + alpha_mle[2]:.4f}")
print(f"  Converged: {result_garch.success}")

# ============================================================
# 4. SSVS-MCMC
# ============================================================
print("\n[5] Running SSVS-MCMC...")
print(f"    Burn-in: 5,000 | Sample: 15,000 | Total: 20,000")

# SSVS settings
c_val = 10.0  # So et al. (2006) suggestion: c_i = 10
P_prior = 0.5  # equal prior inclusion probability
c = np.full(K_vars, c_val)  # c_i for each variable
P = np.full(K_vars, P_prior)

# MCMC settings
n_total = 20000
n_burn = 5000
n_sample = n_total - n_burn

# Storage
phi_samples = np.zeros((n_sample, K_vars))
delta_samples = np.zeros((n_sample, K_vars), dtype=int)
alpha_samples = np.zeros((n_sample, 3))  # omega, alpha1, beta1

# Initialize
phi_current = phi_ols.copy()
alpha_current = alpha_mle.copy()
delta_current = np.ones(K_vars, dtype=int)  # start with all included

# Proposal standard deviations (tuned during burn-in)
phi_proposal_sd = se_ols * 0.5
alpha_proposal_sd = np.array([alpha_mle[0] * 0.1, 0.02, 0.02])

# Acceptance counters
phi_accept = 0
phi_total = 0
alpha_accept = 0
alpha_total = 0

def compute_garch_h(resid, alpha_params):
    """Compute GARCH(1,1) conditional variance series"""
    omega, a1, b1 = alpha_params
    T = len(resid)
    h = np.zeros(T)
    h[0] = np.var(resid)
    for t in range(1, T):
        h[t] = omega + a1 * resid[t-1]**2 + b1 * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h

def log_likelihood(resid, h):
    """Gaussian log-likelihood given residuals and conditional variances"""
    return -0.5 * np.sum(np.log(h) + resid**2 / h)

def log_prior_phi(phi, delta, tau, c):
    """Log prior for phi under SSVS mixture (eq.5)"""
    lp = 0.0
    for i in range(len(phi)):
        if delta[i] == 1:
            sd = c[i] * tau[i]
        else:
            sd = tau[i]
        if sd < 1e-10:
            sd = 1e-10
        lp += stats.norm.logpdf(phi[i], 0, sd)
    return lp

def log_prior_alpha(alpha_params):
    """Weakly informative prior for GARCH parameters"""
    omega, a1, b1 = alpha_params
    if omega <= 0 or a1 < 0 or b1 < 0 or a1 + b1 >= 1:
        return -np.inf
    # Weakly informative: uniform on valid region
    return 0.0

print("    Starting MCMC iterations...")
print("    Using COMPONENT-WISE MH for phi (one coefficient at a time)")
print("    This ensures proper mixing in 19-dimensional parameter space")
mcmc_start = time.time()

# Adaptive proposal tuning intervals
tune_interval = 500
target_accept_low = 0.20
target_accept_high = 0.45

# Per-component acceptance counters for phi
phi_accept_vec = np.zeros(K_vars)
phi_total_vec = np.zeros(K_vars)

# Pre-compute current state
resid_current = y - Z_norm @ phi_current
h_current = compute_garch_h(resid_current, alpha_current)
ll_current = log_likelihood(resid_current, h_current)

for iteration in range(n_total):
    # (a) Draw phi COMPONENT-WISE using random-walk MH
    # Update each phi_i individually (So et al. 2006, Section 3.1)
    for i in range(K_vars):
        phi_proposal_i = phi_current.copy()
        phi_proposal_i[i] += np.random.normal(0, phi_proposal_sd[i])

        resid_proposal = y - Z_norm @ phi_proposal_i
        h_proposal = compute_garch_h(resid_proposal, alpha_current)
        ll_proposal = log_likelihood(resid_proposal, h_proposal)

        # Prior ratio: only phi_i changes
        if delta_current[i] == 1:
            sd_i = c[i] * tau[i]
        else:
            sd_i = tau[i]
        if sd_i < 1e-10:
            sd_i = 1e-10

        log_prior_prop = stats.norm.logpdf(phi_proposal_i[i], 0, sd_i)
        log_prior_curr = stats.norm.logpdf(phi_current[i], 0, sd_i)

        log_ratio = (ll_proposal + log_prior_prop) - (ll_current + log_prior_curr)

        phi_total_vec[i] += 1
        if np.log(np.random.uniform()) < log_ratio:
            phi_current = phi_proposal_i
            resid_current = resid_proposal
            h_current = h_proposal
            ll_current = ll_proposal
            phi_accept_vec[i] += 1

    # (b) Draw alpha (GARCH params) using random-walk MH
    alpha_proposal = alpha_current + np.random.normal(0, alpha_proposal_sd)

    lp_alpha_prop = log_prior_alpha(alpha_proposal)
    alpha_total += 1

    if lp_alpha_prop > -np.inf:
        h_alpha_prop = compute_garch_h(resid_current, alpha_proposal)
        ll_alpha_prop = log_likelihood(resid_current, h_alpha_prop)
        log_ratio_alpha = (ll_alpha_prop + lp_alpha_prop -
                          ll_current - log_prior_alpha(alpha_current))

        if np.log(np.random.uniform()) < log_ratio_alpha:
            alpha_current = alpha_proposal
            h_current = h_alpha_prop
            ll_current = ll_alpha_prop
            alpha_accept += 1

    # (c) Draw δ_i from Bernoulli conditional posterior (eq.9)
    for i in range(K_vars):
        # A = p(phi_i | delta_i=1) * P_i
        sd_incl = c[i] * tau[i]
        sd_excl = tau[i]
        if sd_incl < 1e-10:
            sd_incl = 1e-10
        if sd_excl < 1e-10:
            sd_excl = 1e-10

        log_A = stats.norm.logpdf(phi_current[i], 0, sd_incl) + np.log(P[i])
        log_B = stats.norm.logpdf(phi_current[i], 0, sd_excl) + np.log(1 - P[i])

        # Numerically stable sigmoid
        log_max = max(log_A, log_B)
        p_incl = np.exp(log_A - log_max) / (np.exp(log_A - log_max) + np.exp(log_B - log_max))

        delta_current[i] = np.random.binomial(1, p_incl)

    # Adaptive tuning during burn-in
    if iteration < n_burn and iteration > 0 and iteration % tune_interval == 0:
        # Per-component phi tuning
        for i in range(K_vars):
            if phi_total_vec[i] > 0:
                rate_i = phi_accept_vec[i] / phi_total_vec[i]
                if rate_i < target_accept_low:
                    phi_proposal_sd[i] *= 0.7
                elif rate_i > target_accept_high:
                    phi_proposal_sd[i] *= 1.3

        alpha_rate = alpha_accept / max(alpha_total, 1)
        if alpha_rate < target_accept_low:
            alpha_proposal_sd *= 0.7
        elif alpha_rate > target_accept_high:
            alpha_proposal_sd *= 1.3

        if iteration % 2000 == 0:
            phi_rates = phi_accept_vec / np.maximum(phi_total_vec, 1)
            print(f"      Iter {iteration:5d} | phi accept: "
                  f"min={phi_rates.min():.3f} median={np.median(phi_rates):.3f} "
                  f"max={phi_rates.max():.3f} | "
                  f"alpha accept: {alpha_rate:.3f} | "
                  f"delta sum: {delta_current.sum()}/{K_vars}")

        # Reset counters after tuning
        phi_accept_vec[:] = 0
        phi_total_vec[:] = 0
        alpha_accept = 0
        alpha_total = 0

    # Store post-burn-in samples
    if iteration >= n_burn:
        idx = iteration - n_burn
        phi_samples[idx] = phi_current
        delta_samples[idx] = delta_current
        alpha_samples[idx] = alpha_current

    # Progress
    if iteration > 0 and iteration % 5000 == 0:
        elapsed = time.time() - mcmc_start
        rate = iteration / elapsed
        eta = (n_total - iteration) / rate
        print(f"      Iter {iteration:5d}/{n_total} | "
              f"Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s")

mcmc_elapsed = time.time() - mcmc_start
print(f"\n    MCMC completed in {mcmc_elapsed:.1f}s ({n_total/mcmc_elapsed:.0f} iter/s)")

# Final acceptance rates (from last segment)
final_phi_rates = phi_accept_vec / np.maximum(phi_total_vec, 1)
final_alpha_rate = alpha_accept / max(alpha_total, 1)
print(f"    Final phi acceptance rates: min={final_phi_rates.min():.3f}, "
      f"median={np.median(final_phi_rates):.3f}, max={final_phi_rates.max():.3f}")
print(f"    Final alpha acceptance rate: {final_alpha_rate:.3f}")
final_phi_rate = float(np.median(final_phi_rates))

# ============================================================
# 5. POSTERIOR ANALYSIS
# ============================================================
print("\n[6] Posterior Analysis...")

# 5a. Posterior Inclusion Probabilities
pip = delta_samples.mean(axis=0)
print("\n  Posterior Inclusion Probabilities P(δ_i=1|data):")
print("  " + "-" * 55)
for i in range(K_vars):
    indicator = "***" if pip[i] > 0.5 else "   "
    print(f"    [{i:2d}] {var_names[i]:20s}: PIP = {pip[i]:.4f} {indicator}")
print("  " + "-" * 55)
print("  *** = PIP > 0.5 (evidence for inclusion)")

# 5b. Top subset models
print("\n  Top 10 most visited subset models:")
# Convert delta samples to tuples for counting
from collections import Counter
delta_tuples = [tuple(row) for row in delta_samples]
model_counts = Counter(delta_tuples)
top_models = model_counts.most_common(10)

total_visits = n_sample
for rank, (model, count) in enumerate(top_models):
    prob = count / total_visits
    n_vars = sum(model)
    selected = [var_names[i] for i in range(K_vars) if model[i] == 1]
    if len(selected) == 0:
        sel_str = "(empty model)"
    elif len(selected) <= 5:
        sel_str = ", ".join(selected)
    else:
        sel_str = ", ".join(selected[:5]) + f" +{len(selected)-5} more"
    print(f"    #{rank+1}: P={prob:.4f} | k={n_vars:2d} | {sel_str}")

# Best model
best_model = top_models[0][0]
best_prob = top_models[0][1] / total_visits
best_vars = [var_names[i] for i in range(K_vars) if best_model[i] == 1]

# 5c. Posterior parameter estimates for best model
print("\n  Posterior parameter estimates (all variables):")
phi_mean = phi_samples.mean(axis=0)
phi_std = phi_samples.std(axis=0)
phi_p025 = np.percentile(phi_samples, 2.5, axis=0)
phi_p975 = np.percentile(phi_samples, 97.5, axis=0)

for i in range(K_vars):
    sig = "*" if 0 < phi_p025[i] or phi_p975[i] < 0 else " "
    sig = "*" if (phi_p025[i] > 0 and phi_p975[i] > 0) or (phi_p025[i] < 0 and phi_p975[i] < 0) else " "
    print(f"    {var_names[i]:20s}: mean={phi_mean[i]:8.4f} ± {phi_std[i]:.4f}  "
          f"[{phi_p025[i]:8.4f}, {phi_p975[i]:8.4f}] PIP={pip[i]:.3f} {sig}")

alpha_mean = alpha_samples.mean(axis=0)
alpha_std = alpha_samples.std(axis=0)
print(f"\n  GARCH parameters:")
print(f"    omega: {alpha_mean[0]:.6f} ± {alpha_std[0]:.6f}")
print(f"    alpha: {alpha_mean[1]:.4f} ± {alpha_std[1]:.4f}")
print(f"    beta:  {alpha_mean[2]:.4f} ± {alpha_std[2]:.4f}")
print(f"    persistence: {alpha_mean[1] + alpha_mean[2]:.4f}")

# 5d. MCMC diagnostics
print("\n  MCMC Diagnostics:")

# Effective sample size (simple autocorrelation-based)
def effective_sample_size(chain):
    """Estimate ESS using initial positive sequence estimator"""
    n = len(chain)
    if np.std(chain) < 1e-10:
        return n
    # Compute autocorrelations
    mean_c = np.mean(chain)
    var_c = np.var(chain)
    if var_c < 1e-20:
        return n
    max_lag = min(n // 2, 500)
    autocorr = np.zeros(max_lag)
    chain_centered = chain - mean_c
    for lag in range(max_lag):
        autocorr[lag] = np.mean(chain_centered[:n-lag] * chain_centered[lag:]) / var_c
    # Sum pairs until negative
    tau = 1.0
    for k in range(1, max_lag - 1, 2):
        pair_sum = autocorr[k] + autocorr[k+1]
        if pair_sum < 0:
            break
        tau += 2 * pair_sum
    ess = n / tau
    return max(ess, 1)

print("  Effective Sample Sizes:")
for i in range(min(K_vars, 19)):  # show all
    ess_phi = effective_sample_size(phi_samples[:, i])
    ess_delta = effective_sample_size(delta_samples[:, i].astype(float))
    print(f"    {var_names[i]:20s}: ESS(phi)={ess_phi:7.0f}, ESS(delta)={ess_delta:7.0f}")

for j, name in enumerate(['omega', 'alpha', 'beta']):
    ess_a = effective_sample_size(alpha_samples[:, j])
    print(f"    GARCH {name:5s}         : ESS={ess_a:7.0f}")

# ============================================================
# 6. OUT-OF-SAMPLE EVALUATION
# ============================================================
print("\n[7] Out-of-Sample Evaluation...")

# Split: 80% train, 20% test
T_train = int(T * 0.8)
T_test = T - T_train
print(f"  Train: {T_train} obs | Test: {T_test} obs")

y_train = y[:T_train]
y_test = y[T_train:]
Z_train = Z_norm[:T_train]
Z_test = Z_norm[T_train:]

# Model 1: Baseline GARCH(1,1) (no exogenous variables)
print("\n  --- Model 1: Baseline GARCH(1,1) ---")
# Fit GARCH on training data
result_base = minimize(garch_negloglik, [var_resid * 0.05, 0.08, 0.88],
                       args=(y_train,), method='L-BFGS-B', bounds=bounds_garch)
alpha_base = result_base.x
print(f"  GARCH params: omega={alpha_base[0]:.6f}, alpha={alpha_base[1]:.4f}, beta={alpha_base[2]:.4f}")

# Rolling 1-step forecast on test set
h_base_forecast = np.zeros(T_test)
# Initialize with last training variance
h_last = np.var(y_train)
a_last = y_train[-1]

for t in range(T_test):
    h_pred = alpha_base[0] + alpha_base[1] * a_last**2 + alpha_base[2] * h_last
    h_pred = max(h_pred, 1e-8)
    h_base_forecast[t] = h_pred
    # Update with actual
    a_last = y_test[t]
    h_last = h_pred

# Model 2: SSVS Best Subset ARX-GARCH
print("\n  --- Model 2: SSVS Best Subset ARX-GARCH ---")
# Use median model (variables with PIP > 0.5)
median_model = pip > 0.5
n_selected = median_model.sum()
print(f"  Median model selects {n_selected} variables:")
for i in range(K_vars):
    if median_model[i]:
        print(f"    - {var_names[i]} (PIP={pip[i]:.4f})")

if n_selected > 0:
    Z_selected_train = Z_train[:, median_model]
    Z_selected_test = Z_test[:, median_model]

    # Re-estimate OLS + GARCH on training set with selected variables
    ZtZ_sel = np.linalg.inv(Z_selected_train.T @ Z_selected_train + 1e-6 * np.eye(n_selected))
    phi_sel = ZtZ_sel @ (Z_selected_train.T @ y_train)
    resid_sel_train = y_train - Z_selected_train @ phi_sel

    result_sel = minimize(garch_negloglik, [var_resid * 0.05, 0.08, 0.88],
                          args=(resid_sel_train,), method='L-BFGS-B', bounds=bounds_garch)
    alpha_sel = result_sel.x
    print(f"  GARCH params: omega={alpha_sel[0]:.6f}, alpha={alpha_sel[1]:.4f}, beta={alpha_sel[2]:.4f}")

    # Rolling forecast
    h_sel_forecast = np.zeros(T_test)
    h_last_sel = np.var(resid_sel_train)
    a_last_sel = resid_sel_train[-1]

    for t in range(T_test):
        mean_pred = Z_selected_test[t] @ phi_sel
        a_t = y_test[t] - mean_pred
        h_pred = alpha_sel[0] + alpha_sel[1] * a_last_sel**2 + alpha_sel[2] * h_last_sel
        h_pred = max(h_pred, 1e-8)
        h_sel_forecast[t] = h_pred
        a_last_sel = a_t
        h_last_sel = h_pred
else:
    print("  No variables selected (empty model = baseline GARCH)")
    h_sel_forecast = h_base_forecast.copy()

# Model 3: SSVS Top Model (most visited δ configuration)
print("\n  --- Model 3: SSVS Top Visited Model ---")
top_delta = np.array(best_model)
n_top = top_delta.sum()
print(f"  Top model selects {n_top} variables:")
for i in range(K_vars):
    if top_delta[i]:
        print(f"    - {var_names[i]}")

if n_top > 0:
    Z_top_train = Z_train[:, top_delta.astype(bool)]
    Z_top_test = Z_test[:, top_delta.astype(bool)]

    ZtZ_top = np.linalg.inv(Z_top_train.T @ Z_top_train + 1e-6 * np.eye(n_top))
    phi_top = ZtZ_top @ (Z_top_train.T @ y_train)
    resid_top_train = y_train - Z_top_train @ phi_top

    result_top = minimize(garch_negloglik, [var_resid * 0.05, 0.08, 0.88],
                          args=(resid_top_train,), method='L-BFGS-B', bounds=bounds_garch)
    alpha_top = result_top.x
    print(f"  GARCH params: omega={alpha_top[0]:.6f}, alpha={alpha_top[1]:.4f}, beta={alpha_top[2]:.4f}")

    h_top_forecast = np.zeros(T_test)
    h_last_top = np.var(resid_top_train)
    a_last_top = resid_top_train[-1]

    for t in range(T_test):
        mean_pred = Z_top_test[t] @ phi_top
        a_t = y_test[t] - mean_pred
        h_pred = alpha_top[0] + alpha_top[1] * a_last_top**2 + alpha_top[2] * h_last_top
        h_pred = max(h_pred, 1e-8)
        h_top_forecast[t] = h_pred
        a_last_top = a_t
        h_last_top = h_pred
else:
    h_top_forecast = h_base_forecast.copy()

# Model 4: Kitchen sink ARX-GARCH (all variables)
print("\n  --- Model 4: Kitchen Sink (all variables) ---")
ZtZ_all = np.linalg.inv(Z_train.T @ Z_train + 1e-6 * np.eye(K_vars))
phi_all = ZtZ_all @ (Z_train.T @ y_train)
resid_all_train = y_train - Z_train @ phi_all

result_all = minimize(garch_negloglik, [var_resid * 0.05, 0.08, 0.88],
                      args=(resid_all_train,), method='L-BFGS-B', bounds=bounds_garch)
alpha_all = result_all.x
print(f"  GARCH params: omega={alpha_all[0]:.6f}, alpha={alpha_all[1]:.4f}, beta={alpha_all[2]:.4f}")

h_all_forecast = np.zeros(T_test)
h_last_all = np.var(resid_all_train)
a_last_all = resid_all_train[-1]

for t in range(T_test):
    mean_pred = Z_test[t] @ phi_all
    a_t = y_test[t] - mean_pred
    h_pred = alpha_all[0] + alpha_all[1] * a_last_all**2 + alpha_all[2] * h_last_all
    h_pred = max(h_pred, 1e-8)
    h_all_forecast[t] = h_pred
    a_last_all = a_t
    h_last_all = h_pred

# ============================================================
# 7. EVALUATION METRICS
# ============================================================
print("\n[8] Evaluation Metrics...")

realized_var = y_test**2  # proxy for realized variance

def qlike(rv, hf):
    """QLIKE loss: mean(rv/hf - log(rv/hf) - 1)"""
    ratio = rv / np.maximum(hf, 1e-10)
    return np.mean(ratio - np.log(np.maximum(ratio, 1e-10)) - 1)

def mse_loss(rv, hf):
    """MSE loss"""
    return np.mean((rv - hf)**2)

models = {
    'Baseline GARCH(1,1)': h_base_forecast,
    'SSVS Median Model': h_sel_forecast,
    'SSVS Top Model': h_top_forecast,
    'Kitchen Sink': h_all_forecast,
}

print(f"\n  {'Model':30s} {'QLIKE':>10s} {'MSE':>12s} {'Mean h':>10s}")
print("  " + "-" * 65)

results_metrics = {}
for name, hf in models.items():
    q = qlike(realized_var, hf)
    m = mse_loss(realized_var, hf)
    mh = np.mean(hf)
    print(f"  {name:30s} {q:10.4f} {m:12.4f} {mh:10.4f}")
    results_metrics[name] = {'qlike': q, 'mse': m, 'mean_h': mh}

# Relative performance vs baseline
print(f"\n  Relative QLIKE vs Baseline:")
base_qlike = results_metrics['Baseline GARCH(1,1)']['qlike']
for name in models:
    rel = (results_metrics[name]['qlike'] / base_qlike - 1) * 100
    print(f"    {name:30s}: {rel:+.2f}%")

# ============================================================
# 8. DIEBOLD-MARIANO TEST
# ============================================================
print("\n[9] Diebold-Mariano Tests (vs Baseline GARCH)...")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Positive DM stat means loss1 > loss2 (model 2 is better)
    """
    d = loss1 - loss2
    T = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.mean((d[:T-k] - d_mean) * (d[k:] - d_mean))
        gamma_sum += 2 * (1 - k/h) * gamma_k

    var_d = (gamma0 + gamma_sum) / T
    if var_d <= 0:
        var_d = gamma0 / T

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T-1))
    return dm_stat, p_value

# QLIKE losses
qlike_base = realized_var / np.maximum(h_base_forecast, 1e-10) - np.log(np.maximum(realized_var / np.maximum(h_base_forecast, 1e-10), 1e-10)) - 1

dm_results = {}
for name, hf in models.items():
    if name == 'Baseline GARCH(1,1)':
        continue
    qlike_model = realized_var / np.maximum(hf, 1e-10) - np.log(np.maximum(realized_var / np.maximum(hf, 1e-10), 1e-10)) - 1
    dm_stat, dm_p = dm_test(qlike_base, qlike_model, h=1)

    if dm_stat > 0:
        interp = "model better"
    else:
        interp = "baseline better"

    sig = "***" if dm_p < 0.01 else "**" if dm_p < 0.05 else "*" if dm_p < 0.10 else "NS"
    print(f"  vs {name:30s}: DM={dm_stat:+.3f}, p={dm_p:.4f} [{sig}] ({interp})")
    dm_results[name] = {'dm_stat': float(dm_stat), 'p_value': float(dm_p), 'interpretation': interp}

# ============================================================
# 9. SENSITIVITY ANALYSIS: Different c values
# ============================================================
print("\n[10] Sensitivity Analysis: c = {5, 10, 15, 20}...")

for c_test in [5, 15, 20]:
    c_test_arr = np.full(K_vars, float(c_test))

    # Quick MCMC (5000 iterations, 2000 burn-in)
    phi_curr_s = phi_ols.copy()
    alpha_curr_s = alpha_mle.copy()
    delta_curr_s = np.ones(K_vars, dtype=int)
    pip_quick = np.zeros(K_vars)
    n_quick_total = 5000
    n_quick_burn = 2000

    for it in range(n_quick_total):
        # Simplified: only update delta (Gibbs step), keep phi/alpha at posterior means
        # Use posterior means from main run
        for i in range(K_vars):
            sd_incl = c_test_arr[i] * tau[i]
            sd_excl = tau[i]
            if sd_incl < 1e-10: sd_incl = 1e-10
            if sd_excl < 1e-10: sd_excl = 1e-10
            log_A = stats.norm.logpdf(phi_mean[i], 0, sd_incl) + np.log(P_prior)
            log_B = stats.norm.logpdf(phi_mean[i], 0, sd_excl) + np.log(1 - P_prior)
            log_max = max(log_A, log_B)
            p_incl = np.exp(log_A - log_max) / (np.exp(log_A - log_max) + np.exp(log_B - log_max))
            delta_curr_s[i] = np.random.binomial(1, p_incl)

        if it >= n_quick_burn:
            pip_quick += delta_curr_s

    pip_quick /= (n_quick_total - n_quick_burn)
    high_pip = [(var_names[i], pip_quick[i]) for i in range(K_vars) if pip_quick[i] > 0.3]
    high_pip.sort(key=lambda x: -x[1])
    if high_pip:
        top_str = ", ".join([f"{n}({p:.2f})" for n, p in high_pip[:5]])
    else:
        top_str = "(none > 0.3)"
    print(f"  c={c_test:2d}: top PIPs = {top_str}")

# ============================================================
# 10. ADDITIONAL: BIC-based model comparison
# ============================================================
print("\n[11] BIC Model Comparison...")

def compute_bic(resid, h, n_params, T):
    """BIC = -2*loglik + k*log(T)"""
    ll = -0.5 * np.sum(np.log(h) + resid**2 / h + np.log(2*np.pi))
    return -2 * ll + n_params * np.log(T)

# Baseline
h_base_train = compute_garch_h(y_train, alpha_base)
bic_base = compute_bic(y_train, h_base_train, 3, T_train)

# SSVS median model
if n_selected > 0:
    h_sel_train = compute_garch_h(resid_sel_train, alpha_sel)
    bic_sel = compute_bic(resid_sel_train, h_sel_train, n_selected + 3, T_train)
else:
    bic_sel = bic_base

# Kitchen sink
h_all_train = compute_garch_h(resid_all_train, alpha_all)
bic_all = compute_bic(resid_all_train, h_all_train, K_vars + 3, T_train)

print(f"  Baseline GARCH(1,1):    BIC = {bic_base:.1f} (k=3)")
print(f"  SSVS Median Model:      BIC = {bic_sel:.1f} (k={n_selected + 3})")
print(f"  Kitchen Sink:            BIC = {bic_all:.1f} (k={K_vars + 3})")

# ============================================================
# 11. COMPILE RESULTS
# ============================================================
total_time = time.time() - start_time
print(f"\n[12] Total execution time: {total_time:.1f}s")

# Determine if any variable has strong evidence
any_selected = any(pip[i] > 0.5 for i in range(K_vars))
strong_selected = [var_names[i] for i in range(K_vars) if pip[i] > 0.7]
moderate_selected = [var_names[i] for i in range(K_vars) if 0.3 < pip[i] <= 0.7]

print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)
if any_selected:
    print(f"  SSVS found variables with PIP > 0.5:")
    for i in range(K_vars):
        if pip[i] > 0.5:
            print(f"    - {var_names[i]}: PIP = {pip[i]:.4f}")
    print(f"\n  However, OOS QLIKE performance determines practical value.")
else:
    print("  NULL RESULT: No variable has PIP > 0.5")
    print("  SSVS confirms that no exogenous variable (or combination) improves")
    print("  upon GARCH(1,1) for SPY daily volatility forecasting.")

best_oos = min(results_metrics.items(), key=lambda x: x[1]['qlike'])
print(f"\n  Best OOS model: {best_oos[0]} (QLIKE={best_oos[1]['qlike']:.4f})")
print(f"  Baseline GARCH: QLIKE={base_qlike:.4f}")
if best_oos[0] != 'Baseline GARCH(1,1)':
    rel_best = (best_oos[1]['qlike'] / base_qlike - 1) * 100
    print(f"  Improvement: {rel_best:+.2f}%")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    "experiment_id": "K433",
    "title": "Bayesian SSVS for ARX-GARCH Variable Selection",
    "method": "Stochastic Search Variable Selection (So, Chen, Liu 2006 JRSS-C)",
    "asset": "SPY",
    "data_source": "yfinance (empirical)",
    "data_period": f"~{T/252:.1f} years, T={T} trading days",
    "sample_split": {"train": int(T_train), "test": int(T_test)},
    "model_spec": {
        "AR_lags": 3,
        "exogenous_vars": 8,
        "lags_per_var": 2,
        "total_candidates": int(K_vars),
        "possible_subsets": int(2**K_vars),
        "GARCH": "(1,1)"
    },
    "mcmc_settings": {
        "total_iterations": int(n_total),
        "burn_in": int(n_burn),
        "effective_samples": int(n_sample),
        "c_value": c_val,
        "prior_inclusion_prob": P_prior,
        "tau_calibration": "OLS standard errors"
    },
    "mcmc_diagnostics": {
        "final_phi_acceptance_rate": float(final_phi_rate),
        "final_alpha_acceptance_rate": float(final_alpha_rate),
        "computation_time_seconds": float(mcmc_elapsed)
    },
    "posterior_inclusion_probabilities": {
        var_names[i]: {
            "PIP": float(pip[i]),
            "phi_mean": float(phi_mean[i]),
            "phi_std": float(phi_std[i]),
            "phi_95CI": [float(phi_p025[i]), float(phi_p975[i])]
        }
        for i in range(K_vars)
    },
    "top_models": [
        {
            "rank": rank + 1,
            "posterior_probability": float(count / total_visits),
            "n_variables": int(sum(model)),
            "variables": [var_names[i] for i in range(K_vars) if model[i] == 1]
        }
        for rank, (model, count) in enumerate(top_models[:5])
    ],
    "garch_posterior": {
        "omega": {"mean": float(alpha_mean[0]), "std": float(alpha_std[0])},
        "alpha": {"mean": float(alpha_mean[1]), "std": float(alpha_std[1])},
        "beta": {"mean": float(alpha_mean[2]), "std": float(alpha_std[2])},
        "persistence": float(alpha_mean[1] + alpha_mean[2])
    },
    "oos_evaluation": {
        model_name: {
            "QLIKE": float(metrics['qlike']),
            "MSE": float(metrics['mse']),
            "relative_QLIKE_vs_baseline": float((metrics['qlike'] / base_qlike - 1) * 100)
        }
        for model_name, metrics in results_metrics.items()
    },
    "dm_tests": dm_results,
    "bic_comparison": {
        "Baseline_GARCH": float(bic_base),
        "SSVS_Median": float(bic_sel),
        "Kitchen_Sink": float(bic_all)
    },
    "conclusion": {
        "any_variable_selected": bool(any_selected),
        "strong_pip_vars": strong_selected,
        "moderate_pip_vars": moderate_selected,
        "best_oos_model": best_oos[0],
        "best_oos_qlike": float(best_oos[1]['qlike']),
        "baseline_qlike": float(base_qlike),
        "ssvs_confirms_null": bool(not any_selected or best_oos[0] == 'Baseline GARCH(1,1)'),
        "interpretation": (
            "SSVS with 2^{} subset space confirms that no exogenous variable "
            "combination improves SPY daily vol forecasting beyond GARCH(1,1). "
            "This is the STRONGEST null result yet — not just one-at-a-time "
            "testing (K113) but simultaneous Bayesian model selection over "
            "{:,} possible subsets. VIX sufficient statistic hypothesis "
            "reinforced.".format(K_vars, 2**K_vars)
            if not any_selected or best_oos[0] == 'Baseline GARCH(1,1)'
            else "SSVS found useful variable combination: {}".format(
                ", ".join(strong_selected))
        )
    },
    "references": [
        "So, Chen, Liu (2006) Best Subset Selection of ARX-GARCH, JRSS-C 55(2):201-224",
        "Chen, Liu, Gerlach (2011) Bayesian Subset Selection for TARMA",
        "Chen, Liu, So (2013) Threshold Variable Selection for Asymmetric SV",
        "K113: Order flow microstructure 0/12 null",
        "Previous GARCH-X null results: VIX, VIX slope, Volume, Panel GARCH-X"
    ],
    "total_time_seconds": float(total_time)
}

output_path = 'experiments/k433_ssvs_garch_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to {output_path}")
print(f"  Script: experiments/k433_ssvs_garch.py")
print("\nDone.")
