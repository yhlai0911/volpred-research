"""
K1013: Bayesian SSVS for GARCH-X Variable Selection
====================================================
Systematically select optimal exogenous variables for GJR-GARCH-X variance equation
using Stochastic Search Variable Selection (George & McCulloch 1993; So, Chen, Liu 2006).

Candidate variables: VIX², VIX9D², VIX3M², TermSpread, UnempRate, RV_20d
All lagged by 1 day (no lookahead).

Method: Two-stage approach
  Stage 1: Estimate GJR-GARCH by MLE to get fixed GARCH parameters
  Stage 2: Bayesian SSVS on residual variance for exogenous variable selection

Reference: So, Chen, Liu (2006, JRSS-C 55(2):201-224)
           George & McCulloch (1993, JASA 88(423):881-889)

Data: SPY 2005-2026, yfinance + FRED
Seed: 42
"""

import numpy as np
import pandas as pd
import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 60)
print("K1013: Bayesian SSVS for GARCH-X Variable Selection")
print("=" * 60)

import yfinance as yf

# Download data
print("\n[1] Downloading data...")
tickers = ['SPY', '^VIX', '^VIX9D', '^VIX3M']
data = {}
for t in tickers:
    df = yf.download(t, start='2004-01-01', end='2026-04-08', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[t] = df
    print(f"  {t}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# FRED data (direct CSV download, avoiding pandas_datareader compatibility issues)
print("\n[2] Downloading FRED data...")

def download_fred(series_id, start='2004-01-01', end='2026-04-08'):
    """Download FRED series via direct CSV URL"""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}'
    df = pd.read_csv(url, index_col=0, parse_dates=True)
    df.columns = [series_id]
    # Replace '.' with NaN (FRED uses '.' for missing)
    df = df.replace('.', np.nan).astype(float)
    return df

term_spread = download_fred('T10Y3M')
unemp = download_fred('UNRATE')

# Forward-fill unemployment to daily
unemp_daily = unemp.reindex(data['SPY'].index, method='ffill')

print(f"  TermSpread: {len(term_spread)} rows")
print(f"  Unemployment: {len(unemp)} monthly rows -> {unemp_daily.dropna().shape[0]} daily")

# ============================================================
# 2. Construct Variables
# ============================================================
print("\n[3] Constructing variables...")

spy = data['SPY']['Close'].copy()
returns = np.log(spy / spy.shift(1)).dropna()
returns.name = 'r'

# Squared returns (r²) = GARCH target
r_sq = returns ** 2
r_sq.name = 'r_sq'

# VIX variables: convert to daily variance scale (VIX²/252)
vix = data['^VIX']['Close'].copy()
vix_sq = (vix ** 2) / 252
vix_sq.name = 'VIX_sq'

vix9d = data['^VIX9D']['Close'].copy()
vix9d_sq = (vix9d ** 2) / 252
vix9d_sq.name = 'VIX9D_sq'

vix3m = data['^VIX3M']['Close'].copy()
vix3m_sq = (vix3m ** 2) / 252
vix3m_sq.name = 'VIX3M_sq'

# Term spread
ts = term_spread.iloc[:, 0].reindex(returns.index, method='ffill')
ts.name = 'TermSpread'

# Unemployment rate
ur = unemp_daily.iloc[:, 0].reindex(returns.index, method='ffill')
ur.name = 'UnempRate'

# RV_20d: 20-day realized variance
rv_20d = r_sq.rolling(20).mean() * 252  # annualized
rv_20d.name = 'RV_20d'

# Combine all candidates (lagged by 1 day — no lookahead)
candidates = pd.DataFrame({
    'VIX_sq': vix_sq,
    'VIX9D_sq': vix9d_sq,
    'VIX3M_sq': vix3m_sq,
    'TermSpread': ts,
    'UnempRate': ur,
    'RV_20d': rv_20d
}).reindex(returns.index)

# Lag all candidates by 1 day (signal from t-1, target at t)
candidates_lagged = candidates.shift(1)

# Combine with returns
df = pd.DataFrame({'r': returns, 'r_sq': r_sq})
df = pd.concat([df, candidates_lagged], axis=1)
df = df.dropna()

print(f"  Combined dataset: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
print(f"  Candidate variables: {list(candidates_lagged.columns)}")

# ============================================================
# 3. Descriptive Statistics
# ============================================================
print("\n[4] Descriptive statistics of candidates:")
desc = df[['r', 'r_sq'] + list(candidates_lagged.columns)].describe()
print(desc.round(6).to_string())

# Correlations between candidates and r²
print("\n  Correlations with r²:")
corr_with_rsq = df[list(candidates_lagged.columns)].corrwith(df['r_sq'])
for var, c in corr_with_rsq.items():
    print(f"    {var}: {c:.4f}")

# ============================================================
# 4. Stage 1: Estimate GJR-GARCH by MLE
# ============================================================
print("\n[5] Stage 1: GJR-GARCH MLE estimation...")

from arch import arch_model

# Use first 2000 observations for estimation
N_est = 2000
r_est = df['r'].iloc[:N_est] * 100  # scale to percentage for arch package

gjr = arch_model(r_est, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
gjr_fit = gjr.fit(disp='off')

print(f"  Estimation sample: {N_est} observations")
print(f"  Convergence: {gjr_fit.convergence_flag}")
print(f"  Parameters:")
print(f"    mu     = {gjr_fit.params['mu']:.6f}")
print(f"    omega  = {gjr_fit.params['omega']:.6f}")
print(f"    alpha  = {gjr_fit.params['alpha[1]']:.6f}")
print(f"    gamma  = {gjr_fit.params['gamma[1]']:.6f}")
print(f"    beta   = {gjr_fit.params['beta[1]']:.6f}")
persistence = gjr_fit.params['alpha[1]'] + gjr_fit.params['gamma[1]']/2 + gjr_fit.params['beta[1]']
print(f"    persistence = {persistence:.4f}")

# Get conditional variance from GJR
cond_var = gjr_fit.conditional_volatility ** 2  # in percentage² scale
# Convert back to decimal scale
cond_var_decimal = cond_var / 10000

# ============================================================
# 5. Stage 2: Bayesian SSVS for Exogenous Variables
# ============================================================
print("\n[6] Stage 2: Bayesian SSVS...")

# The idea: after fitting GJR-GARCH, we look at:
#   h_t (from GJR) vs actual r²_t
# The residual variance (r²_t - h_t) might be explained by exogenous variables.
#
# More precisely, we model:
#   r²_t = h_t(GJR) + Σ δ_j θ_j X_{j,t-1} + u_t
#
# SSVS selects which X_j to include via latent binary indicators δ_j.

# Prepare data for SSVS
# Align indices
est_idx = df.index[:N_est]
r_sq_est = df['r_sq'].iloc[:N_est].values  # actual r² (decimal scale)
h_est = cond_var_decimal.reindex(est_idx).values  # GJR h_t (decimal scale)

# Residual: what GJR doesn't explain
resid_var = r_sq_est - h_est

# Candidate regressors (already lagged)
X_names = list(candidates_lagged.columns)
X_est = df[X_names].iloc[:N_est].values

# Standardize X for numerical stability
X_mean = X_est.mean(axis=0)
X_std = X_est.std(axis=0)
X_std[X_std == 0] = 1
X_norm = (X_est - X_mean) / X_std

p = len(X_names)
n = len(resid_var)

print(f"  Variables: {p}")
print(f"  Observations: {n}")
print(f"  Mean residual variance: {resid_var.mean():.6e}")
print(f"  Std residual variance: {resid_var.std():.6e}")

# SSVS Parameters (George & McCulloch 1993)
tau0 = 0.001  # small spike (variable excluded)
tau1 = 1.0    # large slab (variable included)
prior_p = 0.5  # uninformative prior on inclusion

# MCMC settings
n_iter = 10000
burn_in = 5000
rng = np.random.default_rng(42)

# Storage
delta_samples = np.zeros((n_iter, p))
theta_samples = np.zeros((n_iter, p))
sigma2_u_samples = np.zeros(n_iter)

# Initialize
delta = np.ones(p)  # start with all included
theta = np.zeros(p)
sigma2_u = np.var(resid_var)  # residual variance of u_t

# Prior for sigma2_u: InvGamma(a0, b0)
a0 = 2.0
b0 = sigma2_u * (a0 - 1)  # set prior mean = initial estimate

print(f"\n  MCMC: {n_iter} iterations, burn-in {burn_in}")
print(f"  SSVS priors: tau0={tau0}, tau1={tau1}, prior_p={prior_p}")
print(f"  Running Gibbs sampler...")

for it in range(n_iter):
    # ---- Step 1: Sample theta_j | delta_j, sigma2_u ----
    for j in range(p):
        x_j = X_norm[:, j]
        # Residual excluding variable j
        resid_j = resid_var.copy()
        for k in range(p):
            if k != j:
                resid_j = resid_j - delta[k] * theta[k] * X_norm[:, k]

        # Prior variance for theta_j depends on delta_j
        tau2_j = tau1**2 if delta[j] == 1 else tau0**2

        # Posterior for theta_j (conjugate Normal)
        precision_prior = 1.0 / tau2_j
        precision_lik = np.sum(x_j**2) / sigma2_u
        precision_post = precision_prior + precision_lik

        mean_post = (np.sum(x_j * resid_j) / sigma2_u) / precision_post
        var_post = 1.0 / precision_post

        theta[j] = rng.normal(mean_post, np.sqrt(var_post))

    # ---- Step 2: Sample delta_j | theta_j ----
    for j in range(p):
        # Log posterior odds
        log_p1 = np.log(prior_p) - 0.5 * np.log(tau1**2) - 0.5 * theta[j]**2 / tau1**2
        log_p0 = np.log(1 - prior_p) - 0.5 * np.log(tau0**2) - 0.5 * theta[j]**2 / tau0**2

        # Numerical stability
        log_max = max(log_p1, log_p0)
        p1 = np.exp(log_p1 - log_max)
        p0 = np.exp(log_p0 - log_max)
        prob_include = p1 / (p1 + p0)

        delta[j] = 1.0 if rng.random() < prob_include else 0.0

    # ---- Step 3: Sample sigma2_u | theta, delta ----
    fitted = np.zeros(n)
    for j in range(p):
        fitted += delta[j] * theta[j] * X_norm[:, j]

    residuals = resid_var - fitted
    ss = np.sum(residuals**2)

    a_post = a0 + n / 2
    b_post = b0 + ss / 2
    sigma2_u = 1.0 / rng.gamma(a_post, 1.0 / b_post)

    # Store samples
    delta_samples[it] = delta.copy()
    theta_samples[it] = theta.copy()
    sigma2_u_samples[it] = sigma2_u

print("  MCMC completed.")

# ============================================================
# 6. Posterior Analysis
# ============================================================
print("\n[7] Posterior analysis (after burn-in)...")

delta_post = delta_samples[burn_in:]
theta_post = theta_samples[burn_in:]
sigma2_u_post = sigma2_u_samples[burn_in:]

n_post = len(delta_post)

# Posterior Inclusion Probabilities (PIP)
pip = delta_post.mean(axis=0)
print("\n  Posterior Inclusion Probabilities (PIP):")
pip_results = {}
for j, name in enumerate(X_names):
    theta_mean = theta_post[:, j].mean()
    theta_std = theta_post[:, j].std()
    # Posterior mean conditional on inclusion
    included_mask = delta_post[:, j] == 1
    if included_mask.sum() > 0:
        theta_incl_mean = theta_post[included_mask, j].mean()
        theta_incl_std = theta_post[included_mask, j].std()
    else:
        theta_incl_mean = 0.0
        theta_incl_std = 0.0

    pip_results[name] = {
        'PIP': float(pip[j]),
        'theta_post_mean': float(theta_mean),
        'theta_post_std': float(theta_std),
        'theta_incl_mean': float(theta_incl_mean),
        'theta_incl_std': float(theta_incl_std)
    }

    marker = " ★★★" if pip[j] >= 0.8 else (" ★★" if pip[j] >= 0.5 else (" ★" if pip[j] >= 0.3 else ""))
    print(f"    {name:15s}: PIP={pip[j]:.4f}, θ_mean={theta_mean:.6f} (±{theta_std:.6f}){marker}")

# Model frequency table (top 10)
print("\n  Top 10 model configurations (by frequency):")
model_configs = {}
for i in range(n_post):
    config = tuple(delta_post[i].astype(int))
    model_configs[config] = model_configs.get(config, 0) + 1

sorted_models = sorted(model_configs.items(), key=lambda x: -x[1])
model_freq_results = []
for rank, (config, count) in enumerate(sorted_models[:10]):
    freq = count / n_post
    vars_in = [X_names[j] for j in range(p) if config[j] == 1]
    vars_str = '+'.join(vars_in) if vars_in else '(empty)'
    model_freq_results.append({
        'rank': rank + 1,
        'config': list(config),
        'variables': vars_str,
        'frequency': float(freq),
        'count': int(count)
    })
    print(f"    #{rank+1}: {vars_str:50s} freq={freq:.4f} ({count})")

# ============================================================
# 7. Predictive Validation (OOS comparison)
# ============================================================
print("\n[8] Out-of-sample validation...")

# Use SSVS-selected variables (PIP >= 0.5) for GARCH-X
selected_vars = [name for name, res in pip_results.items() if res['PIP'] >= 0.5]
print(f"  Selected variables (PIP >= 0.5): {selected_vars}")

if not selected_vars:
    # Use top variable if none >= 0.5
    top_var = max(pip_results, key=lambda k: pip_results[k]['PIP'])
    selected_vars = [top_var]
    print(f"  No variable >= 0.5, using top: {selected_vars}")

# OOS: rolling 1-step-ahead forecast
oos_start = N_est
oos_end = len(df)
n_oos = oos_end - oos_start
print(f"  OOS period: {df.index[oos_start].date()} to {df.index[oos_end-1].date()} ({n_oos} days)")

# Baseline: GJR-GARCH (no X)
# SSVS model: GJR-GARCH + selected X variables
# For efficiency, use expanding window with refit every 250 days

from arch import arch_model

def compute_oos_forecast_base(returns_decimal, oos_start, oos_end, refit_every=250):
    """GJR-GARCH baseline OOS forecasts using recursive conditional variance.

    Uses h[t] = omega + alpha*eps[t-1]^2 + gamma*eps[t-1]^2*I(eps<0) + beta*h[t-1]
    where eps = r - mu (in percentage scale for estimation, converted back).
    """
    forecasts = np.zeros(oos_end - oos_start)
    r_pct = returns_decimal * 100
    params = None

    for t in range(oos_start, oos_end):
        if params is None or (t - oos_start) % refit_every == 0:
            train = r_pct.iloc[:t]
            model = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
            fit_result = model.fit(disp='off')
            params = {
                'mu': fit_result.params['mu'],
                'omega': fit_result.params['omega'],
                'alpha': fit_result.params['alpha[1]'],
                'gamma': fit_result.params['gamma[1]'],
                'beta': fit_result.params['beta[1]']
            }
            # Get the last conditional variance from the fitted model
            cond_vol = fit_result.conditional_volatility
            h_prev = cond_vol.iloc[-1] ** 2  # in pct^2 scale

        # eps_{t-1} = r_{t-1} - mu (in percentage scale)
        eps_prev = r_pct.iloc[t-1] - params['mu']
        indicator = 1.0 if eps_prev < 0 else 0.0

        # GJR-GARCH(1,1,1) recursion
        h_t = (params['omega'] +
               params['alpha'] * eps_prev**2 +
               params['gamma'] * eps_prev**2 * indicator +
               params['beta'] * h_prev)

        forecasts[t - oos_start] = h_t / 10000  # convert pct^2 to decimal
        h_prev = h_t  # update for next step

    return forecasts

def compute_oos_forecast_ssvs(returns_decimal, X_data, selected_cols, theta_means,
                               oos_start, oos_end, refit_every=250):
    """GJR + SSVS selected variables OOS forecasts"""
    # First get base GJR forecasts
    h_base = compute_oos_forecast_base(returns_decimal, oos_start, oos_end, refit_every)
    forecasts = np.zeros(oos_end - oos_start)

    for i in range(oos_end - oos_start):
        t = oos_start + i
        h_gjr = h_base[i]

        # SSVS adjustment: Σ θ_j * X_{j,t-1} (X already lagged in df)
        adj = 0.0
        for col in selected_cols:
            j = X_names.index(col)
            x_val = (X_data[col].iloc[t] - X_mean[j]) / X_std[j]  # standardized
            adj += theta_means[col] * x_val

        forecasts[i] = max(h_gjr + adj, 1e-10)  # ensure positive

    return forecasts

# Compute OOS
print("  Computing baseline GJR forecasts...")
h_base = compute_oos_forecast_base(df['r'], oos_start, oos_end)

# Get theta means for selected variables
theta_means_sel = {}
for name in selected_vars:
    theta_means_sel[name] = pip_results[name]['theta_incl_mean']

print("  Computing SSVS-augmented forecasts...")
h_ssvs = compute_oos_forecast_ssvs(df['r'], df[X_names], selected_vars, theta_means_sel, oos_start, oos_end)

# Actual r² (target)
r_sq_oos = df['r_sq'].iloc[oos_start:oos_end].values

# QLIKE loss
def qlike(actual, forecast):
    """Patton (2011) QLIKE loss - handles zero actual values"""
    forecast = np.maximum(forecast, 1e-10)
    actual = np.maximum(actual, 1e-10)  # avoid log(0) for days with near-zero r²
    return np.mean(actual / forecast - np.log(actual / forecast) - 1)

def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)

qlike_base = qlike(r_sq_oos, h_base)
qlike_ssvs = qlike(r_sq_oos, h_ssvs)
mse_base = mse(r_sq_oos, h_base)
mse_ssvs = mse(r_sq_oos, h_ssvs)

print(f"\n  OOS Results ({n_oos} days):")
print(f"    Baseline GJR    : QLIKE={qlike_base:.6f}, MSE={mse_base:.4e}")
print(f"    SSVS-augmented  : QLIKE={qlike_ssvs:.6f}, MSE={mse_ssvs:.4e}")
print(f"    QLIKE improvement: {(qlike_ssvs - qlike_base)/qlike_base*100:.2f}%")
print(f"    MSE improvement  : {(mse_ssvs - mse_base)/mse_base*100:.2f}%")

# DM test
from scipy import stats

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (loss1 - loss2)"""
    d = loss1 - loss2
    mean_d = np.mean(d)
    var_d = np.var(d, ddof=1)
    # HAC variance (Newey-West with h-1 lags)
    for k in range(1, h):
        gamma_k = np.mean(d[k:] * d[:-k]) - mean_d**2
        var_d += 2 * (1 - k/h) * gamma_k
    se_d = np.sqrt(var_d / len(d))
    t_stat = mean_d / se_d if se_d > 0 else 0
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value

r_sq_oos_safe = np.maximum(r_sq_oos, 1e-10)
h_base_safe = np.maximum(h_base, 1e-10)
h_ssvs_safe = np.maximum(h_ssvs, 1e-10)
loss_base = r_sq_oos_safe / h_base_safe - np.log(r_sq_oos_safe / h_base_safe) - 1
loss_ssvs = r_sq_oos_safe / h_ssvs_safe - np.log(r_sq_oos_safe / h_ssvs_safe) - 1

dm_t, dm_p = dm_test(loss_base, loss_ssvs)
print(f"\n  DM test (base vs SSVS): t={dm_t:.4f}, p={dm_p:.4f}")
print(f"    Harvey (2016) threshold: |t| > 3.0 → {'PASS' if abs(dm_t) > 3.0 else 'FAIL'}")

# ============================================================
# 8. Also test VIX-only model (K988 comparison)
# ============================================================
print("\n[9] Comparison with VIX-only model (K988)...")

# VIX-only GARCH-X
theta_vix_only = {'VIX_sq': pip_results['VIX_sq']['theta_incl_mean']}
h_vix_only = compute_oos_forecast_ssvs(df['r'], df[X_names], ['VIX_sq'], theta_vix_only, oos_start, oos_end)

qlike_vix = qlike(r_sq_oos, h_vix_only)
mse_vix = mse(r_sq_oos, h_vix_only)

h_vix_safe = np.maximum(h_vix_only, 1e-10)
loss_vix = r_sq_oos_safe / h_vix_safe - np.log(r_sq_oos_safe / h_vix_safe) - 1
dm_vix_t, dm_vix_p = dm_test(loss_base, loss_vix)

print(f"    VIX-only        : QLIKE={qlike_vix:.6f}, MSE={mse_vix:.4e}")
print(f"    DM (base vs VIX): t={dm_vix_t:.4f}, p={dm_vix_p:.4f}")

# SSVS vs VIX-only
dm_ssvs_vix_t, dm_ssvs_vix_p = dm_test(loss_vix, loss_ssvs)
print(f"    DM (VIX vs SSVS): t={dm_ssvs_vix_t:.4f}, p={dm_ssvs_vix_p:.4f}")

# ============================================================
# 9. MCMC Diagnostics
# ============================================================
print("\n[10] MCMC diagnostics...")

# Trace of PIP (rolling window)
window = 500
pip_trace = {}
for j, name in enumerate(X_names):
    trace = pd.Series(delta_post[:, j]).rolling(window).mean().dropna().values
    pip_trace[name] = {
        'start': float(trace[0]),
        'end': float(trace[-1]),
        'range': float(trace.max() - trace.min())
    }
    print(f"    {name:15s}: PIP trace range={trace.max()-trace.min():.4f} (start={trace[0]:.3f}, end={trace[-1]:.3f})")

# Effective sample size (simple estimate)
print("\n  Effective sample size (ESS) for theta:")
for j, name in enumerate(X_names):
    theta_j = theta_post[:, j]
    # Simple ACF-based ESS
    acf1 = np.corrcoef(theta_j[:-1], theta_j[1:])[0, 1]
    ess = n_post * (1 - acf1) / (1 + acf1) if abs(acf1) < 1 else n_post
    print(f"    {name:15s}: ESS={ess:.0f} (ACF1={acf1:.3f})")

# ============================================================
# 10. Generate Plots
# ============================================================
print("\n[11] Generating plots...")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: PIP bar chart
ax = axes[0, 0]
colors = ['#e74c3c' if p >= 0.8 else '#f39c12' if p >= 0.5 else '#3498db' for p in pip]
bars = ax.bar(X_names, pip, color=colors, edgecolor='black', linewidth=0.5)
ax.axhline(y=0.5, color='red', linestyle='--', alpha=0.7, label='PIP=0.5 threshold')
ax.axhline(y=0.8, color='darkred', linestyle='--', alpha=0.7, label='PIP=0.8 threshold')
ax.set_ylabel('Posterior Inclusion Probability')
ax.set_title('SSVS Posterior Inclusion Probabilities')
ax.legend()
ax.set_ylim(0, 1.05)
for bar, p_val in zip(bars, pip):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
            f'{p_val:.3f}', ha='center', va='bottom', fontsize=9)
ax.tick_params(axis='x', rotation=30)

# Plot 2: Delta trace (PIP over iterations)
ax = axes[0, 1]
for j, name in enumerate(X_names):
    rolling_pip = pd.Series(delta_post[:, j]).rolling(500).mean()
    ax.plot(rolling_pip, label=name, alpha=0.8)
ax.set_xlabel('MCMC Iteration (after burn-in)')
ax.set_ylabel('Rolling PIP (window=500)')
ax.set_title('SSVS Convergence: Rolling PIP')
ax.legend(fontsize=8)
ax.axhline(y=0.5, color='red', linestyle='--', alpha=0.3)

# Plot 3: Theta posterior distributions (violin/box)
ax = axes[1, 0]
theta_data = [theta_post[:, j] for j in range(p)]
bp = ax.boxplot(theta_data, labels=X_names, patch_artist=True, showfliers=False)
for patch, c in zip(bp['boxes'], colors):
    patch.set_facecolor(c)
    patch.set_alpha(0.7)
ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
ax.set_ylabel('θ (standardized)')
ax.set_title('Posterior Distributions of θ')
ax.tick_params(axis='x', rotation=30)

# Plot 4: OOS cumulative QLIKE
ax = axes[1, 1]
cum_loss_base = np.cumsum(loss_base)
cum_loss_ssvs = np.cumsum(loss_ssvs)
cum_loss_vix = np.cumsum(loss_vix)
oos_dates = df.index[oos_start:oos_end]
ax.plot(oos_dates, cum_loss_base, label='GJR baseline', color='gray', alpha=0.7)
ax.plot(oos_dates, cum_loss_ssvs, label=f'SSVS ({"+".join(selected_vars)})', color='red')
ax.plot(oos_dates, cum_loss_vix, label='VIX-only', color='blue', alpha=0.7)
ax.set_ylabel('Cumulative QLIKE Loss')
ax.set_title('OOS Cumulative QLIKE Loss')
ax.legend(fontsize=8)

plt.tight_layout()
plot_path = os.path.join(os.path.dirname(__file__), 'k1013_ssvs_results.png')
plt.savefig(plot_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot_path}")

# ============================================================
# 11. Save Results
# ============================================================
print("\n[12] Saving results...")

results = {
    'experiment_id': 'K1013',
    'title': 'Bayesian SSVS for GARCH-X Variable Selection',
    'timestamp': datetime.now().isoformat(),
    'method': 'Two-stage SSVS: GJR-GARCH MLE + Bayesian variable selection (George & McCulloch 1993)',
    'reference': 'So, Chen, Liu (2006, JRSS-C 55(2):201-224); George & McCulloch (1993, JASA)',
    'data': {
        'asset': 'SPY',
        'source': 'yfinance + FRED',
        'estimation_period': f'{df.index[0].date()} to {df.index[N_est-1].date()}',
        'oos_period': f'{df.index[oos_start].date()} to {df.index[oos_end-1].date()}',
        'n_estimation': N_est,
        'n_oos': n_oos
    },
    'gjr_parameters': {
        'mu': float(gjr_fit.params['mu']),
        'omega': float(gjr_fit.params['omega']),
        'alpha': float(gjr_fit.params['alpha[1]']),
        'gamma': float(gjr_fit.params['gamma[1]']),
        'beta': float(gjr_fit.params['beta[1]']),
        'persistence': float(persistence),
        'convergence': int(gjr_fit.convergence_flag)
    },
    'ssvs_settings': {
        'n_candidates': p,
        'candidate_variables': X_names,
        'tau0': tau0,
        'tau1': tau1,
        'prior_inclusion_prob': prior_p,
        'mcmc_iterations': n_iter,
        'burn_in': burn_in,
        'seed': 42
    },
    'posterior_inclusion_probabilities': pip_results,
    'pip_ranking': sorted([(name, res['PIP']) for name, res in pip_results.items()], key=lambda x: -x[1]),
    'selected_variables_pip_05': selected_vars,
    'top_models': model_freq_results[:5],
    'mcmc_diagnostics': {
        'pip_trace': pip_trace,
        'sigma2_u_post_mean': float(sigma2_u_post.mean()),
        'sigma2_u_post_std': float(sigma2_u_post.std())
    },
    'oos_results': {
        'gjr_baseline': {
            'QLIKE': float(qlike_base),
            'MSE': float(mse_base)
        },
        'ssvs_augmented': {
            'variables': selected_vars,
            'QLIKE': float(qlike_ssvs),
            'MSE': float(mse_ssvs),
            'QLIKE_improvement_pct': float((qlike_ssvs - qlike_base)/qlike_base*100),
            'MSE_improvement_pct': float((mse_ssvs - mse_base)/mse_base*100)
        },
        'vix_only': {
            'QLIKE': float(qlike_vix),
            'MSE': float(mse_vix),
            'QLIKE_improvement_pct': float((qlike_vix - qlike_base)/qlike_base*100)
        },
        'dm_test_base_vs_ssvs': {
            't_stat': float(dm_t),
            'p_value': float(dm_p),
            'harvey_pass': bool(abs(dm_t) > 3.0)
        },
        'dm_test_base_vs_vix': {
            't_stat': float(dm_vix_t),
            'p_value': float(dm_vix_p),
            'harvey_pass': bool(abs(dm_vix_t) > 3.0)
        },
        'dm_test_vix_vs_ssvs': {
            't_stat': float(dm_ssvs_vix_t),
            'p_value': float(dm_ssvs_vix_p),
            'harvey_pass': bool(abs(dm_ssvs_vix_t) > 3.0)
        }
    },
    'conclusions': {
        'vix_dominance': 'TBD',
        'macro_irrelevance': 'TBD',
        'supports_k988': 'TBD',
        'summary': 'TBD'
    }
}

# Fill conclusions based on results
vix_vars = [name for name in ['VIX_sq', 'VIX9D_sq', 'VIX3M_sq'] if pip_results[name]['PIP'] >= 0.5]
macro_vars = [name for name in ['TermSpread', 'UnempRate'] if pip_results[name]['PIP'] >= 0.5]

results['conclusions']['vix_dominance'] = f"VIX-family variables with PIP>=0.5: {vix_vars}"
results['conclusions']['macro_irrelevance'] = f"Macro variables with PIP>=0.5: {macro_vars}" if macro_vars else "No macro variable selected (all PIP<0.5)"
results['conclusions']['supports_k988'] = "Yes" if any(pip_results[v]['PIP'] >= 0.5 for v in ['VIX_sq', 'VIX9D_sq']) else "No"

# Generate summary
top_pip = results['pip_ranking'][0]
summary_parts = [
    f"SSVS selects {len(selected_vars)} variable(s): {', '.join(selected_vars)}.",
    f"Top PIP: {top_pip[0]} ({top_pip[1]:.3f}).",
]
if not macro_vars:
    summary_parts.append("Macro variables (TermSpread, UnempRate) excluded (PIP<0.5), confirming K1001.")
if any(pip_results[v]['PIP'] >= 0.5 for v in ['VIX_sq', 'VIX9D_sq']):
    summary_parts.append("VIX-family dominance confirmed, supporting K988.")
summary_parts.append(f"OOS QLIKE: SSVS={qlike_ssvs:.6f} vs baseline={qlike_base:.6f} ({(qlike_ssvs-qlike_base)/qlike_base*100:.1f}%).")
summary_parts.append(f"DM test: t={dm_t:.3f} ({'Harvey PASS' if abs(dm_t)>3.0 else 'Harvey FAIL'}).")
results['conclusions']['summary'] = ' '.join(summary_parts)

results_path = os.path.join(os.path.dirname(__file__), 'k1013_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved: {results_path}")

# ============================================================
# 12. Print Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY: K1013 Bayesian SSVS for GARCH-X")
print("=" * 60)
print(f"\nPIP Ranking:")
for name, p_val in results['pip_ranking']:
    marker = " ★★★" if p_val >= 0.8 else (" ★★" if p_val >= 0.5 else "")
    print(f"  {name:15s}: {p_val:.4f}{marker}")
print(f"\nSelected variables (PIP >= 0.5): {selected_vars}")
print(f"\nConclusions:")
for k, v in results['conclusions'].items():
    print(f"  {k}: {v}")
print(f"\nOOS Performance:")
print(f"  GJR baseline    : QLIKE={qlike_base:.6f}")
print(f"  SSVS-augmented  : QLIKE={qlike_ssvs:.6f} ({(qlike_ssvs-qlike_base)/qlike_base*100:+.2f}%)")
print(f"  VIX-only        : QLIKE={qlike_vix:.6f} ({(qlike_vix-qlike_base)/qlike_base*100:+.2f}%)")
print(f"  DM base vs SSVS : t={dm_t:.3f}")
print(f"  DM base vs VIX  : t={dm_vix_t:.3f}")
print(f"  DM VIX vs SSVS  : t={dm_ssvs_vix_t:.3f}")
print("\nDone.")
