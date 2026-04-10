"""
K1031: Bayesian SSVS for ARX-GARCH Joint Estimation
====================================================
Extends K1013 (two-stage SSVS → NULL) by doing joint estimation of GARCH-X
variance equation with SSVS priors on exogenous variable coefficients.

Model:
    r_t = mu + e_t,  e_t ~ N(0, h_t)
    h_t = omega + alpha * e_{t-1}^2 + gamma * e_{t-1}^2 * I(e<0) + beta * h_{t-1}
          + sum_j delta_j * X_{j,t-1}

    SSVS prior on delta_j:
        delta_j | xi_j ~ xi_j * N(0, c^2 * tau^2) + (1-xi_j) * N(0, tau^2)
        xi_j ~ Bernoulli(p_j)

References:
    - So, Chen, Liu (2006, JRSS-C 55(2):201-224) — SSVS for GARCH
    - George & McCulloch (1993, JASA 88(423):881-889) — original SSVS
    - Patton (2011) — QLIKE loss function

Data: SPY 2005-2026, yfinance + local FRED cache
Seed: 42
"""

import numpy as np
import pandas as pd
import json
import os
import warnings
from datetime import datetime
from scipy.stats import norm
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. DATA LOADING
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
MACRO_DIR = os.path.join(PROJECT_DIR, 'storage', 'macro')

print("=" * 70)
print("K1031: Bayesian SSVS ARX-GARCH Joint Estimation")
print("=" * 70)

# Load SPY data
import yfinance as yf
print("\n[1] Loading SPY data from yfinance...")
spy = yf.download('SPY', start='2004-01-01', end='2026-12-31', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy.index = pd.DatetimeIndex(spy.index).tz_localize(None)
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['ret'])
print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()}, N={len(spy)}")

# Load VIX data
print("[2] Loading VIX/VIX9D/VIX3M from yfinance...")
vix_data = yf.download(['^VIX', '^VIX9D', '^VIX3M'], start='2004-01-01', end='2026-12-31', progress=False)
if isinstance(vix_data.columns, pd.MultiIndex):
    vix_close = vix_data['Close']
else:
    vix_close = vix_data[['Close']]

# Rename columns
vix_df = pd.DataFrame(index=vix_close.index)
for col in vix_close.columns:
    if 'VIX9D' in str(col):
        vix_df['VIX9D'] = vix_close[col]
    elif 'VIX3M' in str(col):
        vix_df['VIX3M'] = vix_close[col]
    elif 'VIX' in str(col):
        vix_df['VIX'] = vix_close[col]

vix_df.index = pd.DatetimeIndex(vix_df.index).tz_localize(None)
print(f"  VIX: {vix_df.index[0].date()} to {vix_df.index[-1].date()}")

# Load FRED data from local cache
print("[3] Loading FRED data from local cache...")

def load_fred_csv(filename, value_col):
    """Load FRED data from local CSV cache."""
    path = os.path.join(MACRO_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {filename} not found")
        return None
    df = pd.read_csv(path, parse_dates=['observation_date'])
    df = df.rename(columns={'observation_date': 'date', value_col: value_col})
    df = df.set_index('date')
    df.index = pd.DatetimeIndex(df.index)
    df = df[[value_col]].dropna()
    return df

dgs10 = load_fred_csv('fred_DGS10.csv', 'DGS10')
dgs2 = load_fred_csv('fred_DGS2.csv', 'DGS2')
stlfsi = load_fred_csv('fred_STLFSI4.csv', 'STLFSI4')

print(f"  DGS10: {len(dgs10)} obs" if dgs10 is not None else "  DGS10: MISSING")
print(f"  DGS2: {len(dgs2)} obs" if dgs2 is not None else "  DGS2: MISSING")
print(f"  STLFSI4: {len(stlfsi)} obs" if stlfsi is not None else "  STLFSI4: MISSING")

# ============================================================
# 2. CONSTRUCT CANDIDATE VARIABLES (all lagged by 1 day)
# ============================================================
print("\n[4] Constructing candidate variables...")

# Merge everything to daily
df = spy[['ret']].copy()
df['r_sq'] = df['ret'] ** 2

# VIX variables (squared, annualized → daily variance scale)
df = df.join(vix_df[['VIX']], how='left')
df['VIX'] = df['VIX'].ffill()
df['VIX_sq'] = (df['VIX'] ** 2) / 252  # daily variance scale

if 'VIX9D' in vix_df.columns:
    df = df.join(vix_df[['VIX9D']], how='left')
    df['VIX9D'] = df['VIX9D'].ffill()
    df['VIX9D_sq'] = (df['VIX9D'] ** 2) / 252
else:
    print("  VIX9D not available, using VIX as proxy")
    df['VIX9D_sq'] = df['VIX_sq']

if 'VIX3M' in vix_df.columns:
    df = df.join(vix_df[['VIX3M']], how='left')
    df['VIX3M'] = df['VIX3M'].ffill()
    df['VIX3M_sq'] = (df['VIX3M'] ** 2) / 252
else:
    print("  VIX3M not available, using VIX as proxy")
    df['VIX3M_sq'] = df['VIX_sq']

# Term spread (DGS10 - DGS2)
if dgs10 is not None and dgs2 is not None:
    ts = dgs10.join(dgs2, how='inner')
    ts['TermSpread'] = ts['DGS10'] - ts['DGS2']
    df = df.join(ts[['TermSpread']], how='left')
    df['TermSpread'] = df['TermSpread'].ffill()
else:
    df['TermSpread'] = 0.0

# STLFSI4
if stlfsi is not None:
    df = df.join(stlfsi, how='left')
    df['STLFSI4'] = df['STLFSI4'].ffill()
else:
    df['STLFSI4'] = 0.0

# RV_20d (20-day realized variance, annualized)
df['RV_20d'] = df['r_sq'].rolling(20).mean() * 252

# All exogenous variables — LAG by 1 day to prevent lookahead
exog_cols = ['VIX_sq', 'VIX9D_sq', 'VIX3M_sq', 'TermSpread', 'STLFSI4', 'RV_20d']
for col in exog_cols:
    df[f'{col}_lag1'] = df[col].shift(1)

# Drop NaN
df = df.dropna()
print(f"  Final dataset: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# ============================================================
# 3. SPLIT IN-SAMPLE / OUT-OF-SAMPLE
# ============================================================
# Use ~2000 obs for IS, rest for OOS
IS_SIZE = 2000
is_data = df.iloc[:IS_SIZE]
oos_data = df.iloc[IS_SIZE:]

print(f"\n[5] Sample split:")
print(f"  IS:  {is_data.index[0].date()} to {is_data.index[-1].date()}, N={len(is_data)}")
print(f"  OOS: {oos_data.index[0].date()} to {oos_data.index[-1].date()}, N={len(oos_data)}")

# Descriptive stats
print(f"\n[6] Descriptive statistics (IS):")
print(f"  Return: mean={is_data['ret'].mean()*252:.4f}, std={is_data['ret'].std()*np.sqrt(252):.4f}")
print(f"  Skewness: {is_data['ret'].skew():.4f}")
print(f"  Kurtosis: {is_data['ret'].kurtosis():.4f}")

# ============================================================
# 4. GJR-GARCH MLE BASELINE (for comparison)
# ============================================================
print("\n[7] Fitting GJR-GARCH baseline via MLE...")

def gjr_garch_loglik(params, returns):
    """Negative log-likelihood for GJR-GARCH(1,1,1)."""
    mu, omega, alpha, gamma, beta = params
    T = len(returns)
    r = returns - mu

    # Constraints
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    if alpha + gamma/2 + beta >= 1.0:
        return 1e10

    h = np.zeros(T)
    h[0] = np.var(r)

    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * (r[t-1] < 0) + beta * h[t-1]
        if h[t] <= 0:
            h[t] = 1e-8

    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + r**2 / h)
    return -ll

returns_is = is_data['ret'].values
x0 = [np.mean(returns_is), 1e-6, 0.05, 0.1, 0.85]
bounds = [(-0.01, 0.01), (1e-8, 1e-3), (0, 0.5), (0, 0.5), (0, 0.999)]

result_gjr = minimize(gjr_garch_loglik, x0, args=(returns_is,), method='L-BFGS-B', bounds=bounds)
mu_mle, omega_mle, alpha_mle, gamma_mle, beta_mle = result_gjr.x
persistence_mle = alpha_mle + gamma_mle/2 + beta_mle

print(f"  Convergence: {result_gjr.success}")
print(f"  mu={mu_mle:.6f}, omega={omega_mle:.2e}")
print(f"  alpha={alpha_mle:.4f}, gamma={gamma_mle:.4f}, beta={beta_mle:.4f}")
print(f"  Persistence: {persistence_mle:.4f}")

# Generate IS conditional variance
def gjr_variance(params, returns):
    mu, omega, alpha, gamma, beta = params
    T = len(returns)
    r = returns - mu
    h = np.zeros(T)
    h[0] = np.var(r)
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * (r[t-1] < 0) + beta * h[t-1]
        if h[t] <= 0:
            h[t] = 1e-8
    return h

h_gjr_is = gjr_variance(result_gjr.x, returns_is)

# ============================================================
# 5. BAYESIAN SSVS JOINT ESTIMATION (Gibbs Sampler)
# ============================================================
print("\n[8] Running Bayesian SSVS Joint GARCH-X Estimation...")
print("    (This is the key difference from K1013: joint, not two-stage)")

# Prepare data
r = is_data['ret'].values
T = len(r)
X = np.column_stack([is_data[f'{col}_lag1'].values for col in exog_cols])
K = X.shape[1]  # number of candidate variables

print(f"  T={T}, K={K} candidate variables")
print(f"  Variables: {exog_cols}")

# Standardize X for numerical stability (save scaling for later)
X_means = X.mean(axis=0)
X_stds = X.std(axis=0)
X_stds[X_stds == 0] = 1.0
X_std = (X - X_means) / X_stds

# SSVS hyperparameters
tau_spike = 0.001   # spike (near-zero when excluded)
tau_slab = 1.0      # slab (diffuse when included)
c = tau_slab / tau_spike  # slab/spike ratio = 1000
p_prior = 0.5       # prior inclusion probability (uninformative)

# MCMC settings
N_MCMC = 10000
N_BURN = 5000
N_POST = N_MCMC - N_BURN

# Storage for posterior samples
mu_samples = np.zeros(N_MCMC)
omega_samples = np.zeros(N_MCMC)
alpha_samples = np.zeros(N_MCMC)
gamma_samples = np.zeros(N_MCMC)
beta_samples = np.zeros(N_MCMC)
delta_samples = np.zeros((N_MCMC, K))
xi_samples = np.zeros((N_MCMC, K))  # inclusion indicators

# Initialize from MLE
mu_curr = mu_mle
omega_curr = omega_mle
alpha_curr = alpha_mle
gamma_curr = gamma_mle
beta_curr = beta_mle
delta_curr = np.zeros(K)
xi_curr = np.zeros(K, dtype=int)

# Compute conditional variance
def compute_h(mu, omega, alpha, gamma_p, beta, delta, X, r):
    """Compute conditional variance h_t for GARCH-X model."""
    T = len(r)
    eps = r - mu
    h = np.zeros(T)
    h[0] = np.var(eps)

    for t in range(1, T):
        exog_term = np.dot(delta, X[t])
        h[t] = (omega + alpha * eps[t-1]**2
                + gamma_p * eps[t-1]**2 * (eps[t-1] < 0)
                + beta * h[t-1]
                + exog_term)
        # Ensure positivity
        if h[t] <= 1e-10:
            h[t] = 1e-10
    return h

def log_likelihood(mu, omega, alpha, gamma_p, beta, delta, X, r):
    """Log-likelihood of GARCH-X model."""
    h = compute_h(mu, omega, alpha, gamma_p, beta, delta, X, r)
    eps = r - mu
    ll = -0.5 * np.sum(np.log(2 * np.pi * h) + eps**2 / h)
    return ll

# MH proposal scales (tuned for ~25-40% acceptance)
prop_scale_mu = 0.0001
prop_scale_omega = omega_mle * 0.1
prop_scale_alpha = 0.01
prop_scale_gamma = 0.01
prop_scale_beta = 0.005
prop_scale_delta = 0.0001  # small because delta effects are subtle

# Acceptance counters
accept_counts = {'mu': 0, 'omega': 0, 'alpha': 0, 'gamma': 0, 'beta': 0, 'delta': np.zeros(K)}

print(f"  MCMC: {N_MCMC} iterations, {N_BURN} burn-in")
print("  Running Gibbs + MH sampler...")

rng = np.random.default_rng(42)

for iteration in range(N_MCMC):
    if iteration % 2000 == 0:
        print(f"    Iteration {iteration}/{N_MCMC}")

    # Current log-likelihood
    ll_curr = log_likelihood(mu_curr, omega_curr, alpha_curr, gamma_curr,
                             beta_curr, delta_curr, X_std, r)

    # --- MH step for mu ---
    mu_prop = mu_curr + rng.normal() * prop_scale_mu
    ll_prop = log_likelihood(mu_prop, omega_curr, alpha_curr, gamma_curr,
                             beta_curr, delta_curr, X_std, r)
    log_ratio = ll_prop - ll_curr
    if np.log(rng.uniform()) < log_ratio:
        mu_curr = mu_prop
        ll_curr = ll_prop
        accept_counts['mu'] += 1

    # --- MH step for omega ---
    omega_prop = omega_curr * np.exp(rng.normal() * 0.1)  # log-normal proposal
    if omega_prop > 0:
        ll_prop = log_likelihood(mu_curr, omega_prop, alpha_curr, gamma_curr,
                                 beta_curr, delta_curr, X_std, r)
        # Jacobian for log-normal proposal
        log_ratio = ll_prop - ll_curr + np.log(omega_prop) - np.log(omega_curr)
        if np.log(rng.uniform()) < log_ratio:
            omega_curr = omega_prop
            ll_curr = ll_prop
            accept_counts['omega'] += 1

    # --- MH step for alpha ---
    alpha_prop = alpha_curr + rng.normal() * prop_scale_alpha
    if 0 <= alpha_prop < 0.5 and alpha_prop + gamma_curr/2 + beta_curr < 1.0:
        ll_prop = log_likelihood(mu_curr, omega_curr, alpha_prop, gamma_curr,
                                 beta_curr, delta_curr, X_std, r)
        log_ratio = ll_prop - ll_curr
        if np.log(rng.uniform()) < log_ratio:
            alpha_curr = alpha_prop
            ll_curr = ll_prop
            accept_counts['alpha'] += 1

    # --- MH step for gamma ---
    gamma_prop = gamma_curr + rng.normal() * prop_scale_gamma
    if 0 <= gamma_prop < 0.5 and alpha_curr + gamma_prop/2 + beta_curr < 1.0:
        ll_prop = log_likelihood(mu_curr, omega_curr, alpha_curr, gamma_prop,
                                 beta_curr, delta_curr, X_std, r)
        log_ratio = ll_prop - ll_curr
        if np.log(rng.uniform()) < log_ratio:
            gamma_curr = gamma_prop
            ll_curr = ll_prop
            accept_counts['gamma'] += 1

    # --- MH step for beta ---
    beta_prop = beta_curr + rng.normal() * prop_scale_beta
    if 0 <= beta_prop < 0.999 and alpha_curr + gamma_curr/2 + beta_prop < 1.0:
        ll_prop = log_likelihood(mu_curr, omega_curr, alpha_curr, gamma_curr,
                                 beta_prop, delta_curr, X_std, r)
        log_ratio = ll_prop - ll_curr
        if np.log(rng.uniform()) < log_ratio:
            beta_curr = beta_prop
            ll_curr = ll_prop
            accept_counts['beta'] += 1

    # --- Gibbs/MH step for each delta_j with SSVS ---
    for j in range(K):
        # Current delta_j
        delta_j_old = delta_curr[j]

        # Propose new delta_j
        delta_prop_j = delta_curr.copy()
        delta_prop_j[j] = delta_j_old + rng.normal() * prop_scale_delta

        # Compute likelihood with proposed delta
        ll_prop = log_likelihood(mu_curr, omega_curr, alpha_curr, gamma_curr,
                                 beta_curr, delta_prop_j, X_std, r)

        # SSVS prior ratio
        if xi_curr[j] == 1:
            # Included: slab prior N(0, c^2 * tau^2)
            var_prior = (c * tau_spike) ** 2
        else:
            # Excluded: spike prior N(0, tau^2)
            var_prior = tau_spike ** 2

        log_prior_new = -0.5 * delta_prop_j[j]**2 / var_prior
        log_prior_old = -0.5 * delta_j_old**2 / var_prior

        log_ratio = (ll_prop - ll_curr) + (log_prior_new - log_prior_old)

        if np.log(rng.uniform()) < log_ratio:
            delta_curr[j] = delta_prop_j[j]
            ll_curr = ll_prop
            accept_counts['delta'][j] += 1

        # --- Gibbs step for xi_j (inclusion indicator) ---
        # P(xi_j=1 | delta_j, ...) proportional to p * N(delta_j; 0, c^2*tau^2)
        # P(xi_j=0 | delta_j, ...) proportional to (1-p) * N(delta_j; 0, tau^2)

        log_p1 = (np.log(p_prior)
                   - 0.5 * np.log(2 * np.pi * (c * tau_spike)**2)
                   - 0.5 * delta_curr[j]**2 / (c * tau_spike)**2)
        log_p0 = (np.log(1 - p_prior)
                   - 0.5 * np.log(2 * np.pi * tau_spike**2)
                   - 0.5 * delta_curr[j]**2 / tau_spike**2)

        # Numerically stable softmax
        log_max = max(log_p1, log_p0)
        p1 = np.exp(log_p1 - log_max)
        p0 = np.exp(log_p0 - log_max)
        prob_incl = p1 / (p1 + p0)

        xi_curr[j] = 1 if rng.uniform() < prob_incl else 0

    # Store samples
    mu_samples[iteration] = mu_curr
    omega_samples[iteration] = omega_curr
    alpha_samples[iteration] = alpha_curr
    gamma_samples[iteration] = gamma_curr
    beta_samples[iteration] = beta_curr
    delta_samples[iteration] = delta_curr.copy()
    xi_samples[iteration] = xi_curr.copy()

print("  MCMC complete!")

# ============================================================
# 6. POSTERIOR ANALYSIS
# ============================================================
print("\n[9] Posterior Analysis...")

# Posterior samples (after burn-in)
post_mu = mu_samples[N_BURN:]
post_omega = omega_samples[N_BURN:]
post_alpha = alpha_samples[N_BURN:]
post_gamma = gamma_samples[N_BURN:]
post_beta = beta_samples[N_BURN:]
post_delta = delta_samples[N_BURN:]
post_xi = xi_samples[N_BURN:]

# PIP = posterior mean of xi_j
pip = post_xi.mean(axis=0)

print("\n  Posterior Inclusion Probabilities (PIP):")
print("  " + "-" * 40)
pip_results = []
for j, col in enumerate(exog_cols):
    status = "INCLUDE" if pip[j] >= 0.5 else "exclude"
    print(f"  {col:15s}: PIP = {pip[j]:.4f} [{status}]")
    pip_results.append({
        'variable': col,
        'pip': float(pip[j]),
        'delta_mean': float(post_delta[:, j].mean()),
        'delta_std': float(post_delta[:, j].std()),
        'delta_median': float(np.median(post_delta[:, j])),
        'status': status
    })

# Sort by PIP
pip_results.sort(key=lambda x: x['pip'], reverse=True)
print("\n  Ranked by PIP:")
for i, r_item in enumerate(pip_results):
    print(f"  {i+1}. {r_item['variable']:15s}: PIP={r_item['pip']:.4f}, "
          f"delta={r_item['delta_mean']:.6f} (+/- {r_item['delta_std']:.6f})")

# GARCH parameter posteriors
print(f"\n  GARCH parameter posteriors (mean +/- std):")
print(f"  mu    = {post_mu.mean():.6f} +/- {post_mu.std():.6f}")
print(f"  omega = {post_omega.mean():.2e} +/- {post_omega.std():.2e}")
print(f"  alpha = {post_alpha.mean():.4f} +/- {post_alpha.std():.4f}")
print(f"  gamma = {post_gamma.mean():.4f} +/- {post_gamma.std():.4f}")
print(f"  beta  = {post_beta.mean():.4f} +/- {post_beta.std():.4f}")

persistence_post = post_alpha.mean() + post_gamma.mean()/2 + post_beta.mean()
print(f"  Persistence = {persistence_post:.4f}")

# Acceptance rates
print(f"\n  MH Acceptance rates:")
print(f"  mu:    {accept_counts['mu']/N_MCMC*100:.1f}%")
print(f"  omega: {accept_counts['omega']/N_MCMC*100:.1f}%")
print(f"  alpha: {accept_counts['alpha']/N_MCMC*100:.1f}%")
print(f"  gamma: {accept_counts['gamma']/N_MCMC*100:.1f}%")
print(f"  beta:  {accept_counts['beta']/N_MCMC*100:.1f}%")
for j, col in enumerate(exog_cols):
    print(f"  delta_{col}: {accept_counts['delta'][j]/N_MCMC*100:.1f}%")

# MCMC diagnostics: ESS (using batch means)
def effective_sample_size(chain):
    """Compute ESS using autocorrelation."""
    n = len(chain)
    if n < 10:
        return n
    mean_x = np.mean(chain)
    var_x = np.var(chain, ddof=1)
    if var_x == 0:
        return n

    # Compute autocorrelation up to lag n/2
    max_lag = min(n // 2, 500)
    rho_sum = 0
    for lag in range(1, max_lag + 1):
        rho = np.corrcoef(chain[:-lag], chain[lag:])[0, 1]
        if np.isnan(rho) or rho < 0.05:
            break
        rho_sum += rho

    ess = n / (1 + 2 * rho_sum)
    return max(1, ess)

print(f"\n  MCMC Diagnostics (ESS):")
ess_mu = effective_sample_size(post_mu)
ess_omega = effective_sample_size(post_omega)
ess_alpha = effective_sample_size(post_alpha)
ess_gamma = effective_sample_size(post_gamma)
ess_beta = effective_sample_size(post_beta)
print(f"  ESS(mu)    = {ess_mu:.0f}")
print(f"  ESS(omega) = {ess_omega:.0f}")
print(f"  ESS(alpha) = {ess_alpha:.0f}")
print(f"  ESS(gamma) = {ess_gamma:.0f}")
print(f"  ESS(beta)  = {ess_beta:.0f}")

ess_delta = {}
for j, col in enumerate(exog_cols):
    ess_j = effective_sample_size(post_delta[:, j])
    ess_delta[col] = ess_j
    print(f"  ESS(delta_{col}) = {ess_j:.0f}")

# ============================================================
# 7. OOS FORECAST COMPARISON
# ============================================================
print("\n[10] Out-of-Sample Forecast Comparison...")

# Use posterior mean parameters for forecasting
mu_post = post_mu.mean()
omega_post = post_omega.mean()
alpha_post = post_alpha.mean()
gamma_post = post_gamma.mean()
beta_post = post_beta.mean()
delta_post = post_delta.mean(axis=0)

# Identify variables with PIP >= 0.5 for best subset model
selected_vars = [j for j in range(K) if pip[j] >= 0.5]
selected_names = [exog_cols[j] for j in selected_vars]

# Also test with best single variable (highest PIP)
best_var_idx = np.argmax(pip)
best_var_name = exog_cols[best_var_idx]

print(f"  Selected variables (PIP >= 0.5): {selected_names if selected_names else 'NONE (null model)'}")
print(f"  Best single variable: {best_var_name} (PIP={pip[best_var_idx]:.4f})")

# OOS returns and exogenous data
r_oos = oos_data['ret'].values
X_oos = np.column_stack([oos_data[f'{col}_lag1'].values for col in exog_cols])
X_oos_std = (X_oos - X_means) / X_stds  # Use IS mean/std for standardization
r_sq_oos = r_oos ** 2
T_oos = len(r_oos)

# Forecast 1: GJR baseline (no exogenous)
h_base_oos = np.zeros(T_oos)
# Initialize from last IS variance
h_base_oos[0] = h_gjr_is[-1]
eps_base = r_oos - mu_mle
for t in range(1, T_oos):
    h_base_oos[t] = (omega_mle + alpha_mle * eps_base[t-1]**2
                     + gamma_mle * eps_base[t-1]**2 * (eps_base[t-1] < 0)
                     + beta_mle * h_base_oos[t-1])
    if h_base_oos[t] <= 0:
        h_base_oos[t] = 1e-10

# Forecast 2: GARCH-X with all variables (posterior mean delta)
h_garchx_oos = np.zeros(T_oos)
h_garchx_oos[0] = h_gjr_is[-1]
eps_garchx = r_oos - mu_post
for t in range(1, T_oos):
    exog_all = np.dot(delta_post, X_oos_std[t])
    h_garchx_oos[t] = (omega_post + alpha_post * eps_garchx[t-1]**2
                        + gamma_post * eps_garchx[t-1]**2 * (eps_garchx[t-1] < 0)
                        + beta_post * h_garchx_oos[t-1]
                        + exog_all)
    if h_garchx_oos[t] <= 1e-10:
        h_garchx_oos[t] = 1e-10

# Forecast 3: GARCH-X with selected variables only (PIP >= 0.5)
delta_selected = np.zeros(K)
for j in selected_vars:
    delta_selected[j] = delta_post[j]

h_selected_oos = np.zeros(T_oos)
h_selected_oos[0] = h_gjr_is[-1]
eps_selected = r_oos - mu_post
for t in range(1, T_oos):
    exog_sel = np.dot(delta_selected, X_oos_std[t])
    h_selected_oos[t] = (omega_post + alpha_post * eps_selected[t-1]**2
                         + gamma_post * eps_selected[t-1]**2 * (eps_selected[t-1] < 0)
                         + beta_post * h_selected_oos[t-1]
                         + exog_sel)
    if h_selected_oos[t] <= 1e-10:
        h_selected_oos[t] = 1e-10

# Forecast 4: GARCH-X with best single variable
delta_best = np.zeros(K)
delta_best[best_var_idx] = delta_post[best_var_idx]

h_best_oos = np.zeros(T_oos)
h_best_oos[0] = h_gjr_is[-1]
eps_best = r_oos - mu_post
for t in range(1, T_oos):
    exog_best_val = np.dot(delta_best, X_oos_std[t])
    h_best_oos[t] = (omega_post + alpha_post * eps_best[t-1]**2
                     + gamma_post * eps_best[t-1]**2 * (eps_best[t-1] < 0)
                     + beta_post * h_best_oos[t-1]
                     + exog_best_val)
    if h_best_oos[t] <= 1e-10:
        h_best_oos[t] = 1e-10

# QLIKE loss function (Patton 2011)
def qlike(target, forecast):
    """QLIKE loss: L = log(h) + r^2/h. Lower is better."""
    valid = (forecast > 0) & (target >= 0) & np.isfinite(target) & np.isfinite(forecast)
    return np.mean(np.log(forecast[valid]) + target[valid] / forecast[valid])

def mse_loss(target, forecast):
    valid = np.isfinite(target) & np.isfinite(forecast)
    return np.mean((target[valid] - forecast[valid])**2)

# Target: r^2 (correct for GARCH evaluation per preamble)
target_oos = r_sq_oos

qlike_base = qlike(target_oos, h_base_oos)
qlike_garchx = qlike(target_oos, h_garchx_oos)
qlike_selected = qlike(target_oos, h_selected_oos)
qlike_best = qlike(target_oos, h_best_oos)

mse_base = mse_loss(target_oos, h_base_oos)
mse_garchx = mse_loss(target_oos, h_garchx_oos)
mse_selected = mse_loss(target_oos, h_selected_oos)
mse_best = mse_loss(target_oos, h_best_oos)

print(f"\n  OOS QLIKE (lower = better):")
print(f"  GJR baseline:         {qlike_base:.4f}")
print(f"  GARCH-X (all vars):   {qlike_garchx:.4f} ({(qlike_garchx/qlike_base - 1)*100:+.2f}%)")
print(f"  GARCH-X (selected):   {qlike_selected:.4f} ({(qlike_selected/qlike_base - 1)*100:+.2f}%)")
print(f"  GARCH-X (best single):{qlike_best:.4f} ({(qlike_best/qlike_base - 1)*100:+.2f}%)")

print(f"\n  OOS MSE:")
print(f"  GJR baseline:         {mse_base:.2e}")
print(f"  GARCH-X (all vars):   {mse_garchx:.2e}")
print(f"  GARCH-X (selected):   {mse_selected:.2e}")
print(f"  GARCH-X (best single):{mse_best:.2e}")

# DM test
def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability."""
    d = loss1 - loss2
    d_bar = np.mean(d)
    n = len(d)

    # Newey-West variance
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, h + 1):
        gamma_k = np.cov(d[:-k], d[k:])[0, 1]
        var_d += 2 * gamma_k * (1 - k / (h + 1))

    se = np.sqrt(var_d / n)
    if se == 0:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return t_stat, p_val

# QLIKE losses for DM test
qlike_losses_base = np.log(h_base_oos) + target_oos / h_base_oos
qlike_losses_garchx = np.log(h_garchx_oos) + target_oos / h_garchx_oos
qlike_losses_best = np.log(h_best_oos) + target_oos / h_best_oos

dm_t_garchx, dm_p_garchx = dm_test(qlike_losses_base, qlike_losses_garchx)
dm_t_best, dm_p_best = dm_test(qlike_losses_base, qlike_losses_best)

print(f"\n  DM test (baseline vs GARCH-X all):")
print(f"    t-stat = {dm_t_garchx:.3f}, p = {dm_p_garchx:.4f}")
print(f"    Harvey (2016) |t| > 3.0: {'PASS' if abs(dm_t_garchx) > 3.0 else 'FAIL'}")

print(f"  DM test (baseline vs GARCH-X best single):")
print(f"    t-stat = {dm_t_best:.3f}, p = {dm_p_best:.4f}")
print(f"    Harvey (2016) |t| > 3.0: {'PASS' if abs(dm_t_best) > 3.0 else 'FAIL'}")

# ============================================================
# 8. NULL MODEL FREQUENCY
# ============================================================
print("\n[11] Null Model Analysis...")

# How often all xi_j = 0 (null model selected)
null_freq = np.mean(np.all(post_xi == 0, axis=1))
print(f"  Null model frequency (all xi=0): {null_freq*100:.2f}%")

# How often exactly 1 variable selected
one_var_freq = np.mean(np.sum(post_xi, axis=1) == 1)
print(f"  Exactly 1 variable selected: {one_var_freq*100:.2f}%")

# How often >= 2 variables
two_plus_freq = np.mean(np.sum(post_xi, axis=1) >= 2)
print(f"  2+ variables selected: {two_plus_freq*100:.2f}%")

# Most common model (subset)
from collections import Counter
model_counter = Counter()
for i in range(N_POST):
    model_key = tuple(post_xi[i].astype(int))
    model_counter[model_key] += 1

print(f"\n  Top 5 most frequent models:")
for rank, (model, count) in enumerate(model_counter.most_common(5)):
    vars_in = [exog_cols[j] for j in range(K) if model[j] == 1]
    pct = count / N_POST * 100
    label = vars_in if vars_in else "NULL (empty)"
    print(f"    {rank+1}. {label} — {pct:.1f}%")

# ============================================================
# 9. COMPARISON WITH K1013 (Two-Stage)
# ============================================================
print("\n[12] Comparison with K1013 (Two-Stage SSVS)...")
print("  K1013 two-stage PIP: all < 0.01 (null model 99.56%)")
print(f"  K1031 joint PIP max: {max(pip):.4f} ({exog_cols[np.argmax(pip)]})")
print(f"  K1031 null model frequency: {null_freq*100:.2f}%")

# Interpretation
if max(pip) < 0.5:
    conclusion = ("NULL — Joint estimation also selects null model. "
                  "GJR-GARCH internal dynamics sufficient; "
                  "exogenous variables do not improve variance prediction "
                  "even with joint estimation.")
    finding_type = "NULL (confirms K1013)"
elif max(pip) >= 0.5 and max(pip) < 0.8:
    conclusion = ("WEAK INCLUSION — Some variables marginally selected. "
                  "Joint estimation reveals effects missed by two-stage, "
                  "but inclusion is not strong.")
    finding_type = "WEAK positive"
else:
    conclusion = ("STRONG INCLUSION — Joint estimation reveals clear variable selection "
                  "that two-stage method missed.")
    finding_type = "POSITIVE (contradicts K1013)"

print(f"\n  Conclusion: {finding_type}")
print(f"  {conclusion}")

# ============================================================
# 10. SAVE RESULTS
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'K1031',
    'title': 'Bayesian SSVS ARX-GARCH Joint Estimation',
    'description': ('Joint Bayesian SSVS in GARCH-X variance equation, '
                    'extending K1013 two-stage approach. Tests whether '
                    'joint estimation reveals exogenous variable importance '
                    'missed by two-stage method.'),
    'timestamp': datetime.now().isoformat(),
    'seed': 42,
    'data': {
        'asset': 'SPY',
        'source': 'yfinance + FRED (local cache)',
        'is_period': f"{is_data.index[0].date()} to {is_data.index[-1].date()}",
        'is_n': len(is_data),
        'oos_period': f"{oos_data.index[0].date()} to {oos_data.index[-1].date()}",
        'oos_n': len(oos_data),
    },
    'candidate_variables': exog_cols,
    'ssvs_hyperparameters': {
        'tau_spike': tau_spike,
        'tau_slab': tau_slab,
        'c_ratio': c,
        'p_prior': p_prior,
    },
    'mcmc': {
        'n_total': N_MCMC,
        'n_burnin': N_BURN,
        'n_posterior': N_POST,
        'acceptance_rates': {
            'mu': float(accept_counts['mu'] / N_MCMC),
            'omega': float(accept_counts['omega'] / N_MCMC),
            'alpha': float(accept_counts['alpha'] / N_MCMC),
            'gamma': float(accept_counts['gamma'] / N_MCMC),
            'beta': float(accept_counts['beta'] / N_MCMC),
            'delta': {col: float(accept_counts['delta'][j] / N_MCMC)
                      for j, col in enumerate(exog_cols)},
        },
        'ess': {
            'mu': float(ess_mu),
            'omega': float(ess_omega),
            'alpha': float(ess_alpha),
            'gamma': float(ess_gamma),
            'beta': float(ess_beta),
            'delta': {col: float(ess_delta[col]) for col in exog_cols},
        },
    },
    'pip_results': pip_results,
    'garch_posterior': {
        'mu': {'mean': float(post_mu.mean()), 'std': float(post_mu.std())},
        'omega': {'mean': float(post_omega.mean()), 'std': float(post_omega.std())},
        'alpha': {'mean': float(post_alpha.mean()), 'std': float(post_alpha.std())},
        'gamma': {'mean': float(post_gamma.mean()), 'std': float(post_gamma.std())},
        'beta': {'mean': float(post_beta.mean()), 'std': float(post_beta.std())},
        'persistence': float(persistence_post),
    },
    'gjr_mle_baseline': {
        'mu': float(mu_mle),
        'omega': float(omega_mle),
        'alpha': float(alpha_mle),
        'gamma': float(gamma_mle),
        'beta': float(beta_mle),
        'persistence': float(persistence_mle),
    },
    'null_model_analysis': {
        'null_freq': float(null_freq),
        'one_var_freq': float(one_var_freq),
        'two_plus_freq': float(two_plus_freq),
        'top5_models': [
            {
                'variables': [exog_cols[j] for j in range(K) if model[j] == 1] or ['NULL'],
                'frequency': float(count / N_POST),
            }
            for model, count in model_counter.most_common(5)
        ],
    },
    'oos_comparison': {
        'qlike': {
            'gjr_baseline': float(qlike_base),
            'garchx_all': float(qlike_garchx),
            'garchx_selected': float(qlike_selected),
            'garchx_best_single': float(qlike_best),
        },
        'mse': {
            'gjr_baseline': float(mse_base),
            'garchx_all': float(mse_garchx),
            'garchx_selected': float(mse_selected),
            'garchx_best_single': float(mse_best),
        },
        'dm_test': {
            'base_vs_garchx_all': {
                't_stat': float(dm_t_garchx),
                'p_value': float(dm_p_garchx),
                'harvey_pass': bool(abs(dm_t_garchx) > 3.0),
            },
            'base_vs_best_single': {
                't_stat': float(dm_t_best),
                'p_value': float(dm_p_best),
                'harvey_pass': bool(abs(dm_t_best) > 3.0),
            },
        },
        'selected_variables': selected_names,
        'best_single_variable': best_var_name,
    },
    'comparison_with_k1013': {
        'k1013_method': 'two-stage (MLE GARCH → residual SSVS)',
        'k1013_pip_max': 0.0012,
        'k1013_null_freq': 0.9956,
        'k1031_method': 'joint estimation (MCMC GARCH-X with SSVS)',
        'k1031_pip_max': float(max(pip)),
        'k1031_null_freq': float(null_freq),
    },
    'conclusion': conclusion,
    'finding_type': finding_type,
    'references': [
        'So, Chen, Liu (2006, JRSS-C 55(2):201-224) — SSVS for GARCH',
        'George & McCulloch (1993, JASA 88(423):881-889) — original SSVS',
        'Patton (2011) — QLIKE loss function',
        'Harvey (2016) — DM test threshold |t| > 3.0',
    ],
}

results_path = os.path.join(BASE_DIR, 'k1031_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {results_path}")

# ============================================================
# 11. PLOTS
# ============================================================
print("\n[14] Generating plots...")

fig, axes = plt.subplots(2, 3, figsize=(18, 10))
fig.suptitle('K1031: Bayesian SSVS ARX-GARCH Joint Estimation\n'
             '(SPY, joint estimation vs K1013 two-stage)', fontsize=14, fontweight='bold')

# Plot 1: PIP bar chart
ax = axes[0, 0]
colors = ['#2ecc71' if p >= 0.5 else '#e74c3c' for p in pip]
bars = ax.barh(range(K), pip, color=colors, edgecolor='black', alpha=0.8)
ax.set_yticks(range(K))
ax.set_yticklabels(exog_cols, fontsize=9)
ax.axvline(x=0.5, color='black', linestyle='--', linewidth=1.5, label='PIP=0.5 threshold')
ax.set_xlabel('Posterior Inclusion Probability (PIP)')
ax.set_title('Variable Selection (PIP)')
ax.legend(fontsize=8)
ax.set_xlim(0, 1)

# Plot 2: PIP comparison K1013 vs K1031
ax = axes[0, 1]
k1013_pips = [0.0012, 0.0006, 0.0006, 0.0010, 0.0002, 0.0008]  # From K1013 README
# Note: K1013 had UnempRate instead of STLFSI4, reorder accordingly
k1013_labels = ['VIX_sq', 'VIX9D_sq', 'VIX3M_sq', 'TermSpread', 'STLFSI4*', 'RV_20d']
x_pos = np.arange(K)
width = 0.35
ax.bar(x_pos - width/2, k1013_pips, width, label='K1013 (two-stage)', color='#3498db', alpha=0.7)
ax.bar(x_pos + width/2, pip, width, label='K1031 (joint)', color='#e74c3c', alpha=0.7)
ax.set_xticks(x_pos)
ax.set_xticklabels(exog_cols, rotation=45, ha='right', fontsize=8)
ax.set_ylabel('PIP')
ax.set_title('K1013 vs K1031 PIP Comparison')
ax.legend(fontsize=8)
ax.set_ylim(0, max(max(pip), max(k1013_pips)) * 1.3 + 0.05)

# Plot 3: GARCH parameter posteriors
ax = axes[0, 2]
param_names = ['alpha', 'gamma', 'beta']
param_means = [post_alpha.mean(), post_gamma.mean(), post_beta.mean()]
param_stds = [post_alpha.std(), post_gamma.std(), post_beta.std()]
mle_vals = [alpha_mle, gamma_mle, beta_mle]

x_pos = np.arange(len(param_names))
ax.bar(x_pos - 0.2, mle_vals, 0.35, label='MLE', color='#3498db', alpha=0.7)
ax.bar(x_pos + 0.2, param_means, 0.35, yerr=param_stds, label='Bayes posterior',
       color='#e74c3c', alpha=0.7, capsize=3)
ax.set_xticks(x_pos)
ax.set_xticklabels(param_names)
ax.set_title('GARCH Parameters: MLE vs Posterior')
ax.legend(fontsize=8)

# Plot 4: Delta posterior distributions (top 3 by PIP)
ax = axes[1, 0]
top3_idx = np.argsort(pip)[-3:][::-1]
for j in top3_idx:
    ax.hist(post_delta[:, j], bins=50, alpha=0.6, label=f'{exog_cols[j]} (PIP={pip[j]:.3f})',
            density=True)
ax.axvline(x=0, color='black', linestyle='--', linewidth=1)
ax.set_xlabel('delta coefficient')
ax.set_ylabel('Density')
ax.set_title('Posterior Distributions (Top 3 by PIP)')
ax.legend(fontsize=7)

# Plot 5: PIP trace plots (convergence check)
ax = axes[1, 1]
# Rolling PIP over MCMC iterations
window = 500
for j in range(K):
    rolling_pip = pd.Series(xi_samples[N_BURN:, j]).rolling(window).mean()
    ax.plot(rolling_pip, alpha=0.7, label=exog_cols[j], linewidth=0.8)
ax.set_xlabel('Post-burn-in iteration')
ax.set_ylabel('Rolling PIP (window=500)')
ax.set_title('PIP Convergence Trace')
ax.legend(fontsize=6, loc='upper right')

# Plot 6: OOS QLIKE comparison
ax = axes[1, 2]
models = ['GJR\nbaseline', 'GARCH-X\n(all)', 'GARCH-X\n(selected)', 'GARCH-X\n(best)']
qlikes = [qlike_base, qlike_garchx, qlike_selected, qlike_best]
colors_bar = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12']
bars = ax.bar(models, qlikes, color=colors_bar, alpha=0.8, edgecolor='black')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('OOS Forecast Comparison')
# Add percentage labels
for i, (bar_obj, ql) in enumerate(zip(bars, qlikes)):
    if i > 0:
        pct = (ql / qlike_base - 1) * 100
        ax.text(bar_obj.get_x() + bar_obj.get_width()/2, bar_obj.get_height(),
                f'{pct:+.2f}%', ha='center', va='bottom', fontsize=8)

plt.tight_layout()
fig_path = os.path.join(BASE_DIR, 'k1031_ssvs_joint_results.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Figure saved to {fig_path}")

# ============================================================
# 12. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K1031 SUMMARY")
print("=" * 70)
print(f"  Method: Joint Bayesian SSVS in GARCH-X variance equation")
print(f"  MCMC: {N_MCMC} iterations, {N_BURN} burn-in")
print(f"  Asset: SPY, IS={len(is_data)}, OOS={len(oos_data)}")
print(f"\n  PIP Results:")
for r_item in pip_results:
    print(f"    {r_item['variable']:15s}: PIP={r_item['pip']:.4f}")
print(f"\n  Null model frequency: {null_freq*100:.2f}%")
print(f"  Best QLIKE: GJR baseline = {qlike_base:.4f}")
print(f"  Finding: {finding_type}")
print(f"\n  Key insight: {conclusion}")
print("=" * 70)
