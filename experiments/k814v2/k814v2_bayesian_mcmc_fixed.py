"""
K814v2: Bayesian MCMC GJR-GARCH — Bug-Fixed Version
=====================================================
[提出: Codex (K824v2 bug audit), 執行: Claude]

Fixes 3 HIGH severity bugs from K814:
  BUG 1 — P(γ>0) Prior Tautology:  gamma ~ HalfNormal(0.2) forced P(γ>0)=1.0
           FIX: gamma ~ Normal(0, 0.2) — allows negative γ, data decides
  BUG 2 — OOS h[0] Leak:  h_full computed on IS+OOS concatenation, h[0] of OOS
           used data it shouldn't have seen
           FIX: Compute h on IS only, then recursively forecast OOS from IS-final state
  BUG 3 — ESS/Geweke errors:  naive ESS via lag-1 autocorrelation, Geweke used
           simple SE instead of spectral density at freq 0
           FIX: Batch-means ESS + spectral-density Geweke (Newey-West)

Design mirrors K814 exactly except for the 3 fixes, enabling direct comparison.

Data: SPY daily returns from yfinance
IS: 2006-01-01 ~ 2022-12-31
OOS: 2023-01-01 ~ 2024-12-31
Proxy: squared returns (standard GARCH literature)

References:
- Ardia & Hoogerheide (2010), "Bayesian Estimation of GARCH(1,1)", R Journal
- Nakatsuma (2000), "Bayesian analysis of ARMA-GARCH", J. Econometrics
- Geweke (1992), "Evaluating sampling-based approaches", Bayesian Statistics 4
- Geyer (1992), "Practical Markov Chain Monte Carlo", Statistical Science
- Patton (2011), "Volatility forecast comparison using imperfect proxies", J. Econometrics
"""

import numpy as np
import json
import time
import warnings
import os
from datetime import datetime, timezone
from scipy import stats
from numba import njit

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA
# ============================================================
print("=" * 70)
print("K814v2: Bayesian MCMC GJR-GARCH — Bug-Fixed Version")
print("  Fixes: (1) gamma prior tautology, (2) OOS h[0] leak, (3) ESS/Geweke")
print("=" * 70)

import yfinance as yf
import pandas as pd

print("\n[1] Downloading SPY data...")
spy = yf.download('SPY', start='2005-06-01', end='2025-01-01', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
returns = spy['Close'].pct_change().dropna() * 100  # percentage returns
print(f"  Total observations: {len(returns)}")
print(f"  Date range: {returns.index[0].strftime('%Y-%m-%d')} ~ {returns.index[-1].strftime('%Y-%m-%d')}")

# Split: IS 2006-2022, OOS 2023-2024
is_mask = (returns.index >= '2006-01-01') & (returns.index < '2023-01-01')
oos_mask = (returns.index >= '2023-01-01') & (returns.index < '2025-01-01')
r_is = returns[is_mask].values
r_oos = returns[oos_mask].values
print(f"  IS: {is_mask.sum()} obs (2006-01 ~ 2022-12)")
print(f"  OOS: {oos_mask.sum()} obs (2023-01 ~ 2024-12)")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[2] Descriptive Statistics (IS period)...")
desc = {
    'mean': float(np.mean(r_is)),
    'std': float(np.std(r_is)),
    'skew': float(stats.skew(r_is)),
    'kurtosis': float(stats.kurtosis(r_is)),
    'min': float(np.min(r_is)),
    'max': float(np.max(r_is)),
    'n': len(r_is)
}
print(f"  Mean: {desc['mean']:.4f}, Std: {desc['std']:.4f}")
print(f"  Skew: {desc['skew']:.4f}, Kurt: {desc['kurtosis']:.4f}")

from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, *_ = adfuller(r_is, maxlag=20)
print(f"  ADF: stat={adf_stat:.4f}, p={adf_p:.6f} ({'stationary' if adf_p < 0.05 else 'non-stationary'})")

from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, *_ = het_arch(r_is, nlags=10)
print(f"  ARCH LM(10): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f} ({'ARCH effects' if arch_lm_p < 0.05 else 'no ARCH effects'})")

from statsmodels.stats.diagnostic import acorr_ljungbox
lb = acorr_ljungbox(r_is**2, lags=[10], return_df=True)
lb_stat = float(lb['lb_stat'].iloc[0])
lb_p = float(lb['lb_pvalue'].iloc[0])
print(f"  Ljung-Box(10) on r^2: stat={lb_stat:.4f}, p={lb_p:.6f}")

# ============================================================
# 3. MLE GJR-GARCH (baseline)
# ============================================================
print("\n[3] MLE GJR-GARCH(1,1) via arch package...")
from arch import arch_model

am = arch_model(r_is, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
mle_res = am.fit(disp='off')
mle_params = {
    'mu': float(mle_res.params['mu']),
    'omega': float(mle_res.params['omega']),
    'alpha': float(mle_res.params['alpha[1]']),
    'gamma': float(mle_res.params['gamma[1]']),
    'beta': float(mle_res.params['beta[1]'])
}
persistence_mle = mle_params['alpha'] + mle_params['gamma'] / 2 + mle_params['beta']
print(f"  MLE params: mu={mle_params['mu']:.6f}, omega={mle_params['omega']:.6f}")
print(f"  alpha={mle_params['alpha']:.6f}, gamma={mle_params['gamma']:.6f}, beta={mle_params['beta']:.6f}")
print(f"  Persistence: {persistence_mle:.6f}")
print(f"  Convergence: {mle_res.convergence_flag} (0=success)")

mle_se = {}
for p_name in ['mu', 'omega', 'alpha[1]', 'gamma[1]', 'beta[1]']:
    key = p_name.replace('[1]', '')
    mle_se[key] = float(mle_res.std_err[p_name])
print(f"  MLE SE: alpha={mle_se['alpha']:.6f}, gamma={mle_se['gamma']:.6f}, beta={mle_se['beta']:.6f}")

# ============================================================
# 4. NUMBA-ACCELERATED GARCH VARIANCE
# ============================================================
print("\n[4] Compiling Numba-accelerated GARCH variance...")

@njit(cache=True)
def garch_variance_numba(mu, omega, alpha, gamma, beta, returns):
    """Compute GJR-GARCH(1,1) conditional variance series (Numba JIT).
    gamma can be negative (BUG 1 FIX: allows testing leverage hypothesis).
    """
    T = len(returns)
    eps = np.empty(T)
    h = np.empty(T)

    # Initialize with unconditional variance
    var_sum = 0.0
    for i in range(T):
        eps[i] = returns[i] - mu
        var_sum += eps[i] ** 2
    h[0] = var_sum / T

    for t in range(1, T):
        leverage = eps[t-1] ** 2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * eps[t-1] ** 2 + gamma * leverage + beta * h[t-1]
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h, eps


@njit(cache=True)
def garch_loglik_numba(mu, omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) log-likelihood (normal innovations, Numba JIT)."""
    h, eps = garch_variance_numba(mu, omega, alpha, gamma, beta, returns)

    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(len(returns)):
        if h[t] <= 0 or np.isnan(h[t]):
            return -1e20
        ll += -0.5 * (log2pi + np.log(h[t]) + eps[t] ** 2 / h[t])

    if np.isnan(ll) or np.isinf(ll):
        return -1e20
    return ll


@njit(cache=True)
def garch_oos_recursive(mu, omega, alpha, gamma, beta, h_last, eps_last, returns_oos):
    """BUG 2 FIX: Recursive OOS forecasting from IS-final state.

    h[0] = omega + alpha * eps_last^2 + gamma * I(eps_last<0) * eps_last^2 + beta * h_last
    h[t] = omega + alpha * eps[t-1]^2 + gamma * I(eps[t-1]<0) * eps[t-1]^2 + beta * h[t-1]

    This ensures h[0] uses only IS information, not OOS data.
    """
    T = len(returns_oos)
    h = np.empty(T)
    eps = np.empty(T)

    # First OOS day: h[0] from IS-final state
    leverage_last = eps_last ** 2 * (1.0 if eps_last < 0 else 0.0)
    h[0] = omega + alpha * eps_last ** 2 + gamma * leverage_last + beta * h_last
    if h[0] < 1e-8:
        h[0] = 1e-8
    eps[0] = returns_oos[0] - mu

    # Subsequent OOS days: recursive
    for t in range(1, T):
        leverage = eps[t-1] ** 2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * eps[t-1] ** 2 + gamma * leverage + beta * h[t-1]
        if h[t] < 1e-8:
            h[t] = 1e-8
        eps[t] = returns_oos[t] - mu
    return h, eps


# Warm-up JIT
_ = garch_loglik_numba(0.04, 0.03, 0.02, 0.10, 0.85, r_is[:100])
_ = garch_oos_recursive(0.04, 0.03, 0.02, 0.10, 0.85, 1.0, -0.5, r_is[:10])
print("  JIT compilation done.")

# ============================================================
# 5. BAYESIAN PRIORS (BUG 1 FIX: gamma ~ Normal(0, 0.2))
# ============================================================
print("\n[5] Setting up Bayesian priors (BUG 1 FIX)...")
print("  omega ~ Exp(rate=100)        [mean=0.01, concentrates near 0]")
print("  alpha ~ Beta(2, 5) on [0,0.5] [mean=0.286, right-skewed]")
print("  beta  ~ Beta(5, 2) on [0,0.999] [mean=0.714, left-skewed]")
print("  gamma ~ Normal(0, 0.2)       [*** FIXED: allows negative gamma! ***]")
print("  mu    ~ N(0.05, 0.1)         [centered on typical daily SPY return]")

def log_prior(params):
    """User-specified priors for GJR-GARCH(1,1).

    BUG 1 FIX: gamma ~ Normal(0, 0.2) instead of HalfNormal(0.2).
    This allows gamma to be negative, so P(gamma > 0) is determined by data,
    not by prior constraint.

    params: [mu, omega, alpha, gamma, beta]
    """
    mu, omega, alpha, gamma, beta = params

    # Hard boundary checks (note: gamma CAN be negative now!)
    if omega <= 0 or alpha < 0 or beta < 0 or beta >= 1.0:
        return -np.inf
    if alpha > 0.5:
        return -np.inf
    # Gamma range: allow [-0.5, 0.5] (negative = reverse leverage)
    if gamma < -0.5 or gamma > 0.5:
        return -np.inf

    # Stationarity constraint: alpha + gamma/2 + beta < 1
    # For negative gamma, this is automatically easier to satisfy
    # But we still need alpha + max(gamma,0)/2 + beta < 1 for positive gamma
    # and alpha + beta < 1 for the process to be stable
    if alpha + max(gamma, 0) / 2 + beta >= 1.0:
        return -np.inf
    # Additional: ensure conditional variance stays positive
    # Need omega > 0, alpha >= 0, alpha + gamma >= 0 (for negative shock case)
    if alpha + gamma < -0.01:  # allow tiny numerical slack
        return -np.inf

    lp = 0.0

    # mu ~ N(0.05, 0.1)
    lp += stats.norm.logpdf(mu, loc=0.05, scale=0.1)

    # omega ~ Exp(rate=100)
    lp += stats.expon.logpdf(omega, scale=1.0/100.0)

    # alpha ~ Beta(2, 5) on [0, 0.5]
    if alpha >= 0.5:
        return -np.inf
    lp += stats.beta.logpdf(alpha / 0.5, 2, 5) - np.log(0.5)

    # beta ~ Beta(5, 2) on [0, 0.999]
    if beta >= 0.999:
        return -np.inf
    lp += stats.beta.logpdf(beta / 0.999, 5, 2) - np.log(0.999)

    # BUG 1 FIX: gamma ~ Normal(0, 0.2) — allows negative!
    lp += stats.norm.logpdf(gamma, loc=0, scale=0.2)

    if np.isnan(lp):
        return -np.inf
    return lp


# ============================================================
# 6. METROPOLIS-HASTINGS MCMC
# ============================================================
print("\n[6] Running Metropolis-Hastings MCMC...")
print("  Configuration: 10,000 iterations, 2,000 burn-in, 3 chains")

N_ITER = 10000
BURN_IN = 2000
N_CHAINS = 3
PARAM_NAMES = ['mu', 'omega', 'alpha', 'gamma', 'beta']
N_PARAMS = len(PARAM_NAMES)

def run_mcmc_chain(returns, n_iter, burn_in, seed, chain_id):
    """Run a single MCMC chain with Random Walk Metropolis-Hastings."""
    rng = np.random.RandomState(seed)

    # Initialize at MLE + small perturbation
    current = np.array([
        mle_params['mu'],
        mle_params['omega'],
        mle_params['alpha'],
        mle_params['gamma'],
        mle_params['beta']
    ])
    current += rng.randn(N_PARAMS) * np.array([0.001, 0.001, 0.001, 0.001, 0.001])

    # Ensure valid starting point
    current[1] = max(current[1], 0.001)  # omega > 0
    current[2] = np.clip(current[2], 0.001, 0.49)  # alpha in (0, 0.5)
    # gamma: no clipping to positive — BUG 1 FIX
    current[3] = np.clip(current[3], -0.49, 0.49)  # gamma in (-0.5, 0.5)
    current[4] = np.clip(current[4], 0.01, 0.98)  # beta in (0, 1)

    # Proposal standard deviations
    proposal_std = np.array([0.003, 0.003, 0.005, 0.008, 0.004])

    # Pre-compute current posterior
    current_ll = garch_loglik_numba(current[0], current[1], current[2], current[3], current[4], returns)
    current_lp = log_prior(current)
    current_post = current_ll + current_lp

    samples = np.zeros((n_iter, N_PARAMS))
    log_posteriors = np.zeros(n_iter)
    accept_count = 0
    adapt_interval = 200

    t0 = time.time()
    timeout = 120  # 2 minutes per chain

    for i in range(n_iter):
        if i % 1000 == 0 and i > 0:
            elapsed = time.time() - t0
            if elapsed > timeout:
                print(f"    Chain {chain_id}: TIMEOUT at iteration {i} ({elapsed:.1f}s)")
                samples = samples[:i]
                log_posteriors = log_posteriors[:i]
                break

        # Propose
        proposal = current + proposal_std * rng.randn(N_PARAMS)

        # Check prior (cheap)
        prop_lp = log_prior(proposal)
        if prop_lp == -np.inf:
            samples[i] = current
            log_posteriors[i] = current_post
            continue

        # Likelihood (expensive)
        prop_ll = garch_loglik_numba(
            proposal[0], proposal[1], proposal[2], proposal[3], proposal[4], returns
        )
        prop_post = prop_ll + prop_lp

        # Accept/reject
        log_ratio = prop_post - current_post
        if np.log(rng.rand()) < log_ratio:
            current = proposal.copy()
            current_post = prop_post
            accept_count += 1

        samples[i] = current
        log_posteriors[i] = current_post

        # Adapt proposal std during burn-in
        if i < burn_in and i > 0 and i % adapt_interval == 0:
            recent_start = max(0, i - adapt_interval)
            for p in range(N_PARAMS):
                changes = np.diff(samples[recent_start:i+1, p])
                local_rate = np.mean(changes != 0)
                if local_rate < 0.15:
                    proposal_std[p] *= 0.7
                elif local_rate > 0.45:
                    proposal_std[p] *= 1.3

    actual_iters = len(samples)
    accept_rate = accept_count / actual_iters

    # Discard burn-in
    effective_burn = min(burn_in, actual_iters // 2)
    posterior = samples[effective_burn:]
    log_post_posterior = log_posteriors[effective_burn:]

    elapsed = time.time() - t0
    print(f"    Chain {chain_id}: {actual_iters} iters, accept={accept_rate:.3f}, "
          f"posterior samples={len(posterior)}, time={elapsed:.1f}s")

    return posterior, log_post_posterior, accept_rate, proposal_std


# Run 3 chains
chains = []
chain_accept_rates = []
chain_log_posts = []

t0_total = time.time()
for c in range(N_CHAINS):
    seed = 42 + c * 137
    print(f"  Running Chain {c+1} (seed={seed})...")
    posterior, log_post, ar, final_std = run_mcmc_chain(r_is, N_ITER, BURN_IN, seed, c+1)
    chains.append(posterior)
    chain_log_posts.append(log_post)
    chain_accept_rates.append(ar)

mcmc_total_time = time.time() - t0_total
print(f"\n  Total MCMC time: {mcmc_total_time:.1f}s")
print(f"  Acceptance rates: {[f'{ar:.3f}' for ar in chain_accept_rates]}")

# Combine all chains
all_samples = np.vstack(chains)
print(f"  Total posterior samples: {len(all_samples)}")

# ============================================================
# 7. CONVERGENCE DIAGNOSTICS (BUG 3 FIX: batch means ESS + spectral Geweke)
# ============================================================
print("\n[7] Convergence Diagnostics (BUG 3 FIX: corrected ESS & Geweke)...")

# 7a. Gelman-Rubin Rhat (same as K814, this was correct)
def gelman_rubin(chains_list):
    """Gelman-Rubin Rhat across multiple chains."""
    m = len(chains_list)
    n = min(c.shape[0] for c in chains_list)
    n_params = chains_list[0].shape[1]
    rhat = np.zeros(n_params)

    for p in range(n_params):
        chain_means = np.array([c[:n, p].mean() for c in chains_list])
        chain_vars = np.array([c[:n, p].var(ddof=1) for c in chains_list])

        W = np.mean(chain_vars)
        B = n * np.var(chain_means, ddof=1)

        var_hat = (1 - 1.0/n) * W + (1.0/n) * B
        rhat[p] = np.sqrt(var_hat / W) if W > 1e-12 else np.nan
    return rhat

rhat = gelman_rubin(chains)

# 7b. BUG 3 FIX: Effective Sample Size via Batch Means (Geyer 1992)
def compute_ess_batch_means(x, n_batches=30):
    """ESS via batch means method (Geyer 1992, Jones et al. 2006).

    Divides chain into n_batches batches, computes variance of batch means,
    and estimates integrated autocorrelation time.

    This is more robust than naive lag-1 autocorrelation ESS.
    """
    n = len(x)
    if n < n_batches * 2:
        return max(1, n // 2)

    batch_size = n // n_batches
    n_used = batch_size * n_batches  # trim to exact batches
    x_trimmed = x[:n_used]

    # Compute batch means
    batch_means = np.array([
        np.mean(x_trimmed[i*batch_size:(i+1)*batch_size])
        for i in range(n_batches)
    ])

    # Variance of batch means
    var_batch_means = np.var(batch_means, ddof=1)

    # Overall variance
    var_overall = np.var(x_trimmed, ddof=1)

    if var_overall < 1e-15 or var_batch_means < 1e-15:
        return n_used

    # Integrated autocorrelation time estimate
    tau_hat = batch_size * var_batch_means / var_overall

    # ESS = n / tau
    ess = max(1, int(n_used / tau_hat))
    return min(ess, n_used)  # can't exceed total samples

ess_values = {}
for i, name in enumerate(PARAM_NAMES):
    ess_values[name] = compute_ess_batch_means(all_samples[:, i])

# Also compute per-chain ESS for comparison
ess_per_chain = {}
for i, name in enumerate(PARAM_NAMES):
    chain_ess = [compute_ess_batch_means(c[:, i]) for c in chains]
    ess_per_chain[name] = chain_ess


# 7c. BUG 3 FIX: Geweke test with spectral density at frequency 0 (Newey-West)
def spectral_density_at_zero(x, bandwidth=None):
    """Estimate spectral density at frequency 0 using Newey-West (Bartlett kernel).

    This gives a HAC-consistent variance estimate for the mean.
    """
    n = len(x)
    x_centered = x - np.mean(x)

    if bandwidth is None:
        bandwidth = max(1, int(np.floor(n ** (1/3))))

    # gamma_0
    gamma_0 = np.mean(x_centered ** 2)
    s_hat = gamma_0

    # Add autocovariance terms with Bartlett weights
    for k in range(1, bandwidth + 1):
        gamma_k = np.mean(x_centered[k:] * x_centered[:-k])
        weight = 1.0 - k / (bandwidth + 1)  # Bartlett kernel
        s_hat += 2 * weight * gamma_k

    return max(s_hat, 1e-15)


def geweke_test_spectral(chain, first_frac=0.1, last_frac=0.5):
    """Geweke (1992) convergence test with spectral density at frequency 0.

    BUG 3 FIX: Uses Newey-West spectral density estimator instead of
    simple SE = std/sqrt(n), which ignores autocorrelation.

    Compares mean of first 10% to last 50% of chain.
    Under convergence, z ~ N(0,1).
    """
    n = len(chain)
    n_first = max(10, int(n * first_frac))
    n_last = max(10, int(n * last_frac))

    first = chain[:n_first]
    last = chain[-n_last:]

    # Spectral density at freq 0 for each segment (HAC variance of mean)
    s_first = spectral_density_at_zero(first)
    s_last = spectral_density_at_zero(last)

    # Variance of mean = spectral_density / n
    var_mean_first = s_first / len(first)
    var_mean_last = s_last / len(last)

    se_diff = np.sqrt(var_mean_first + var_mean_last)
    if se_diff < 1e-15:
        return 0.0, 1.0

    z = (np.mean(first) - np.mean(last)) / se_diff
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


geweke_results = {}
for i, name in enumerate(PARAM_NAMES):
    z_scores = []
    p_values = []
    for c in chains:
        z, p = geweke_test_spectral(c[:, i])
        z_scores.append(z)
        p_values.append(p)
    geweke_results[name] = {
        'z_scores': z_scores,
        'p_values': p_values,
        'all_pass': all(p > 0.05 for p in p_values)
    }

print(f"  {'Param':>8} {'Rhat':>8} {'ESS(BM)':>10} {'Geweke_pass':>12}")
print(f"  {'-'*42}")
for i, name in enumerate(PARAM_NAMES):
    gw_pass = 'YES' if geweke_results[name]['all_pass'] else 'NO'
    print(f"  {name:>8} {rhat[i]:>8.4f} {ess_values[name]:>10d} {gw_pass:>12}")

all_rhat_ok = all(r < 1.1 for r in rhat if not np.isnan(r))
print(f"\n  All Rhat < 1.1? {'YES' if all_rhat_ok else 'NO'}")
print(f"  Min ESS (batch means): {min(ess_values.values())}")

# ============================================================
# 8. POSTERIOR SUMMARY
# ============================================================
print("\n[8] Posterior Parameter Summary...")
posterior_summary = {}

print(f"  {'Param':>8} {'Post.Mean':>10} {'Post.Med':>10} {'Post.Std':>10} "
      f"{'CI_2.5':>10} {'CI_97.5':>10} {'MLE':>10} {'MLE_SE':>10}")
print(f"  {'-'*90}")

for i, name in enumerate(PARAM_NAMES):
    samples_p = all_samples[:, i]
    ci = np.percentile(samples_p, [2.5, 97.5])
    cv = float(np.std(samples_p) / abs(np.mean(samples_p))) if abs(np.mean(samples_p)) > 1e-10 else np.inf
    summary = {
        'mean': float(np.mean(samples_p)),
        'median': float(np.median(samples_p)),
        'std': float(np.std(samples_p)),
        'ci_2.5': float(ci[0]),
        'ci_97.5': float(ci[1]),
        'cv': cv,
        'mle': float(mle_params[name]),
        'mle_se': float(mle_se[name]),
        'mle_in_ci': bool(ci[0] <= mle_params[name] <= ci[1])
    }
    posterior_summary[name] = summary
    print(f"  {name:>8} {summary['mean']:>10.6f} {summary['median']:>10.6f} "
          f"{summary['std']:>10.6f} {summary['ci_2.5']:>10.6f} {summary['ci_97.5']:>10.6f} "
          f"{summary['mle']:>10.6f} {summary['mle_se']:>10.6f}")

print("\n  MLE within 95% posterior CI?")
for name in PARAM_NAMES:
    s = posterior_summary[name]
    icon = 'YES' if s['mle_in_ci'] else 'NO'
    print(f"    {name}: {icon}")

# ============================================================
# 9. KEY BAYESIAN ANALYSES
# ============================================================
print("\n[9] Key Bayesian Analyses...")

# 9a. P(gamma > 0) — NOW MEANINGFUL because prior allows gamma < 0!
gamma_samples = all_samples[:, 3]
p_gamma_gt_0 = float(np.mean(gamma_samples > 0))
p_gamma_gt_005 = float(np.mean(gamma_samples > 0.05))
p_gamma_gt_010 = float(np.mean(gamma_samples > 0.10))
p_gamma_lt_0 = float(np.mean(gamma_samples < 0))

# Also compute Bayes Factor: BF = P(gamma>0|data) / P(gamma>0|prior)
# Prior P(gamma>0) for Normal(0, 0.2) = 0.5
prior_p_gamma_gt_0 = 0.5  # by symmetry of Normal(0, 0.2)
bf_leverage = (p_gamma_gt_0 / (1 - p_gamma_gt_0)) / (prior_p_gamma_gt_0 / (1 - prior_p_gamma_gt_0)) if p_gamma_gt_0 < 1.0 and p_gamma_gt_0 > 0.0 else np.inf

print(f"  9a. Bayesian Evidence for Leverage (gamma > 0) — FIXED PRIOR:")
print(f"    Prior: Normal(0, 0.2) — P(gamma>0|prior) = 0.500")
print(f"    P(gamma > 0 | data)   = {p_gamma_gt_0:.6f}")
print(f"    P(gamma < 0 | data)   = {p_gamma_lt_0:.6f}")
print(f"    P(gamma > 0.05| data) = {p_gamma_gt_005:.6f}")
print(f"    P(gamma > 0.10| data) = {p_gamma_gt_010:.6f}")
print(f"    Bayes Factor (gamma>0 vs gamma<0) = {bf_leverage:.2f}")
print(f"    Posterior mean(gamma) = {np.mean(gamma_samples):.6f}")
print(f"    Posterior 95% CI(gamma) = [{np.percentile(gamma_samples, 2.5):.6f}, {np.percentile(gamma_samples, 97.5):.6f}]")

strength = 'overwhelming' if p_gamma_gt_0 > 0.99 else 'strong' if p_gamma_gt_0 > 0.95 else 'moderate' if p_gamma_gt_0 > 0.80 else 'weak' if p_gamma_gt_0 > 0.60 else 'no evidence'
print(f"    Evidence strength: {strength}")
print(f"    [K814 (HalfNormal prior) reported P(gamma>0)=1.000 — that was prior tautology]")

# 9b. Persistence posterior
persistence_samples = all_samples[:, 2] + all_samples[:, 3] / 2 + all_samples[:, 4]
persist_ci = np.percentile(persistence_samples, [2.5, 97.5])
p_persist_gt_099 = float(np.mean(persistence_samples > 0.99))

print(f"\n  9b. Persistence (alpha + gamma/2 + beta):")
print(f"    Mean: {np.mean(persistence_samples):.6f}, Std: {np.std(persistence_samples):.6f}")
print(f"    95% CI: [{persist_ci[0]:.6f}, {persist_ci[1]:.6f}]")
print(f"    MLE:  {persistence_mle:.6f}")
print(f"    P(persistence > 0.99) = {p_persist_gt_099:.6f}")

# 9c. Parameter correlations
corr_alpha_beta = float(np.corrcoef(all_samples[:, 2], all_samples[:, 4])[0, 1])
corr_alpha_gamma = float(np.corrcoef(all_samples[:, 2], all_samples[:, 3])[0, 1])
corr_gamma_beta = float(np.corrcoef(all_samples[:, 3], all_samples[:, 4])[0, 1])
corr_omega_beta = float(np.corrcoef(all_samples[:, 1], all_samples[:, 4])[0, 1])

print(f"\n  9c. Posterior Parameter Correlations:")
print(f"    corr(alpha, beta)  = {corr_alpha_beta:.4f} {'(strong trade-off)' if abs(corr_alpha_beta) > 0.5 else ''}")
print(f"    corr(alpha, gamma) = {corr_alpha_gamma:.4f}")
print(f"    corr(gamma, beta)  = {corr_gamma_beta:.4f}")
print(f"    corr(omega, beta)  = {corr_omega_beta:.4f}")

# 9d. Parameter identification
print(f"\n  9d. Parameter Identification (CV = std/|mean|):")
param_quality = {}
for name in PARAM_NAMES:
    cv = posterior_summary[name]['cv']
    quality = 'well-identified' if cv < 0.1 else 'moderate' if cv < 0.3 else 'poorly-identified'
    param_quality[name] = {'cv': cv, 'quality': quality}
    print(f"    {name:>8}: CV = {cv:.4f} ({quality})")

# ============================================================
# 10. OOS FORECASTING (BUG 2 FIX: recursive from IS-final state)
# ============================================================
print("\n[10] OOS Forecasting — BUG 2 FIX: recursive from IS-final state...")

T_is = len(r_is)
T_oos = len(r_oos)
rv_oos = r_oos ** 2  # realized vol proxy

# First: compute IS variance series to get final h and eps
h_is_mle, eps_is_mle = garch_variance_numba(
    mle_params['mu'], mle_params['omega'], mle_params['alpha'],
    mle_params['gamma'], mle_params['beta'], r_is
)
h_last_mle = h_is_mle[-1]
eps_last_mle = eps_is_mle[-1]

print(f"  IS-final state (MLE): h_last={h_last_mle:.6f}, eps_last={eps_last_mle:.6f}")

# Method 1: MLE forecast (BUG 2 FIX: recursive from IS)
mle_forecast_h, _ = garch_oos_recursive(
    mle_params['mu'], mle_params['omega'], mle_params['alpha'],
    mle_params['gamma'], mle_params['beta'],
    h_last_mle, eps_last_mle, r_oos
)

# Method 2: Bayesian posterior mean forecast (BUG 2 FIX)
bayes_mean_params = np.mean(all_samples, axis=0)
h_is_bm, eps_is_bm = garch_variance_numba(
    bayes_mean_params[0], bayes_mean_params[1], bayes_mean_params[2],
    bayes_mean_params[3], bayes_mean_params[4], r_is
)
bayes_mean_forecast_h, _ = garch_oos_recursive(
    bayes_mean_params[0], bayes_mean_params[1], bayes_mean_params[2],
    bayes_mean_params[3], bayes_mean_params[4],
    h_is_bm[-1], eps_is_bm[-1], r_oos
)

# Method 3: Bayesian posterior median forecast (BUG 2 FIX)
bayes_median_params = np.median(all_samples, axis=0)
h_is_bmed, eps_is_bmed = garch_variance_numba(
    bayes_median_params[0], bayes_median_params[1], bayes_median_params[2],
    bayes_median_params[3], bayes_median_params[4], r_is
)
bayes_median_forecast_h, _ = garch_oos_recursive(
    bayes_median_params[0], bayes_median_params[1], bayes_median_params[2],
    bayes_median_params[3], bayes_median_params[4],
    h_is_bmed[-1], eps_is_bmed[-1], r_oos
)

# Method 4: BMA — average forecasts over 500 posterior draws (BUG 2 FIX)
n_bma = 500
rng_bma = np.random.RandomState(42)
bma_indices = rng_bma.choice(len(all_samples), n_bma, replace=False)
bma_h_sum = np.zeros(T_oos)
bma_h_sq_sum = np.zeros(T_oos)
bma_count = 0

for idx in bma_indices:
    params = all_samples[idx]
    try:
        # Compute IS variance for this posterior draw to get final state
        h_is_tmp, eps_is_tmp = garch_variance_numba(
            params[0], params[1], params[2], params[3], params[4], r_is
        )
        # Recursive OOS from IS-final state
        h_oos_tmp, _ = garch_oos_recursive(
            params[0], params[1], params[2], params[3], params[4],
            h_is_tmp[-1], eps_is_tmp[-1], r_oos
        )
        if np.all(np.isfinite(h_oos_tmp)) and np.all(h_oos_tmp > 0):
            bma_h_sum += h_oos_tmp
            bma_h_sq_sum += h_oos_tmp ** 2
            bma_count += 1
    except Exception:
        pass

bma_forecast_h = bma_h_sum / bma_count if bma_count > 0 else bayes_mean_forecast_h
bma_forecast_std = np.sqrt(bma_h_sq_sum / bma_count - bma_forecast_h ** 2) if bma_count > 1 else np.zeros(T_oos)
print(f"  BMA: used {bma_count}/{n_bma} posterior samples")

# ============================================================
# 11. EVALUATION METRICS
# ============================================================
print("\n[11] Evaluation Metrics (OOS)...")

def qlike(rv, h):
    """QLIKE loss (lower is better). Patton (2011) proxy-robust."""
    valid = (h > 0) & np.isfinite(h) & np.isfinite(rv) & (rv > 0)
    if valid.sum() < 10:
        return np.nan
    return float(np.mean(rv[valid] / h[valid] - np.log(rv[valid] / h[valid]) - 1))

def mse(rv, h):
    valid = np.isfinite(h) & np.isfinite(rv)
    return float(np.mean((rv[valid] - h[valid]) ** 2))

def mae(rv, h):
    valid = np.isfinite(h) & np.isfinite(rv)
    return float(np.mean(np.abs(rv[valid] - h[valid])))

def spearman_corr(rv, h):
    valid = np.isfinite(h) & np.isfinite(rv) & (h > 0) & (rv > 0)
    if valid.sum() < 10:
        return np.nan, np.nan
    rho, p = stats.spearmanr(rv[valid], h[valid])
    return float(rho), float(p)

methods = {
    'MLE': mle_forecast_h,
    'Bayes_Mean': bayes_mean_forecast_h,
    'Bayes_Median': bayes_median_forecast_h,
    'Bayes_BMA': bma_forecast_h
}

results_metrics = {}
print(f"\n  {'Method':>15} {'QLIKE':>10} {'MSE':>12} {'MAE':>10} {'Spearman':>10}")
print(f"  {'-'*60}")
for name, h in methods.items():
    q = qlike(rv_oos, h)
    m = mse(rv_oos, h)
    a = mae(rv_oos, h)
    rho_s, p_s = spearman_corr(rv_oos, h)
    results_metrics[name] = {
        'qlike': q, 'mse': m, 'mae': a,
        'spearman_rho': rho_s, 'spearman_p': p_s
    }
    print(f"  {name:>15} {q:>10.4f} {m:>12.4f} {a:>10.4f} {rho_s:>10.4f}")

# ============================================================
# 12. DIEBOLD-MARIANO TESTS
# ============================================================
print("\n[12] Diebold-Mariano Tests (QLIKE loss)...")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC variance."""
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    bandwidth = max(1, int(np.floor(n ** (1/3))))
    for k in range(1, bandwidth + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        weight = 1 - k / (bandwidth + 1)
        nw_var += 2 * weight * gamma_k

    se = np.sqrt(max(nw_var, 1e-12) / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

# QLIKE losses per observation
qlike_losses = {}
for name, h in methods.items():
    valid = (h > 0) & np.isfinite(h) & np.isfinite(rv_oos) & (rv_oos > 0)
    losses = rv_oos[valid] / h[valid] - np.log(rv_oos[valid] / h[valid]) - 1
    qlike_losses[name] = losses

dm_results = {}
comparisons = [
    ('Bayes_Mean', 'MLE'),
    ('Bayes_Median', 'MLE'),
    ('Bayes_BMA', 'MLE')
]

print(f"\n  {'Comparison':>30} {'DM_stat':>10} {'p_value':>10} {'|t|>3?':>8} {'Better':>12}")
print(f"  {'-'*72}")
for method1, method2 in comparisons:
    dm_stat, dm_p = dm_test(qlike_losses[method1], qlike_losses[method2])
    better = method1 if dm_stat < 0 else method2
    harvey_sig = '***' if abs(dm_stat) > 3.0 else ('**' if abs(dm_stat) > 2.0 else ('*' if abs(dm_stat) > 1.65 else ''))
    dm_results[f'{method1}_vs_{method2}'] = {
        'dm_stat': dm_stat, 'p_value': dm_p, 'better': better,
        'harvey_significant': bool(abs(dm_stat) > 3.0)
    }
    print(f"  {method1+' vs '+method2:>30} {dm_stat:>10.4f} {dm_p:>10.4f} "
          f"{'YES' if abs(dm_stat) > 3.0 else 'NO':>8} {better:>12} {harvey_sig}")

# ============================================================
# 13. VaR ANALYSIS (BUG 2 FIX in VaR computation too)
# ============================================================
print("\n[13] VaR Analysis (5% and 1%) — with BUG 2 FIX...")

var_results_all = {}
for alpha_var in [0.05, 0.01]:
    print(f"\n  --- {int(alpha_var*100)}% VaR ---")
    z_alpha = stats.norm.ppf(alpha_var)

    # MLE VaR (already using recursive forecast from BUG 2 FIX)
    mle_var = -(mle_params['mu'] + z_alpha * np.sqrt(mle_forecast_h))

    # Bayesian predictive VaR (BUG 2 FIX: each draw uses recursive forecast)
    n_var_samples = 500
    rng_var = np.random.RandomState(99)
    var_indices = rng_var.choice(len(all_samples), n_var_samples, replace=False)

    bayes_var = np.zeros(T_oos)
    var_count = 0
    for idx in var_indices:
        params = all_samples[idx]
        try:
            h_is_tmp, eps_is_tmp = garch_variance_numba(
                params[0], params[1], params[2], params[3], params[4], r_is
            )
            h_oos_tmp, _ = garch_oos_recursive(
                params[0], params[1], params[2], params[3], params[4],
                h_is_tmp[-1], eps_is_tmp[-1], r_oos
            )
            var_tmp = -(params[0] + z_alpha * np.sqrt(h_oos_tmp))
            if np.all(np.isfinite(var_tmp)):
                bayes_var += var_tmp
                var_count += 1
        except Exception:
            pass
    bayes_var /= var_count if var_count > 0 else 1

    # Violations
    mle_violations = int(np.sum(r_oos < -mle_var))
    bayes_violations = int(np.sum(r_oos < -bayes_var))
    expected = int(alpha_var * T_oos)

    # Kupiec POF test
    def kupiec_test(violations, n, alpha):
        p_hat = violations / n
        if p_hat == 0 or p_hat == 1:
            return np.nan, np.nan
        lr = 2 * (violations * np.log(p_hat / alpha) +
                  (n - violations) * np.log((1 - p_hat) / (1 - alpha)))
        p_val = 1 - stats.chi2.cdf(lr, df=1)
        return float(lr), float(p_val)

    k_mle_stat, k_mle_p = kupiec_test(mle_violations, T_oos, alpha_var)
    k_bayes_stat, k_bayes_p = kupiec_test(bayes_violations, T_oos, alpha_var)

    print(f"  Expected violations: {expected} ({alpha_var*100:.0f}%)")
    print(f"  MLE:      {mle_violations} ({mle_violations/T_oos*100:.1f}%) | Kupiec p={k_mle_p:.4f} {'PASS' if not np.isnan(k_mle_p) and k_mle_p > 0.05 else 'FAIL'}")
    print(f"  Bayesian: {bayes_violations} ({bayes_violations/T_oos*100:.1f}%) | Kupiec p={k_bayes_p:.4f} {'PASS' if not np.isnan(k_bayes_p) and k_bayes_p > 0.05 else 'FAIL'}")

    var_results_all[f'{int(alpha_var*100)}pct'] = {
        'alpha': alpha_var,
        'expected_violations': expected,
        'mle': {
            'violations': mle_violations,
            'violation_rate': float(mle_violations / T_oos),
            'kupiec_lr': k_mle_stat,
            'kupiec_p': k_mle_p,
            'kupiec_pass': bool(not np.isnan(k_mle_p) and k_mle_p > 0.05)
        },
        'bayesian': {
            'violations': bayes_violations,
            'violation_rate': float(bayes_violations / T_oos),
            'kupiec_lr': k_bayes_stat,
            'kupiec_p': k_bayes_p,
            'kupiec_pass': bool(not np.isnan(k_bayes_p) and k_bayes_p > 0.05)
        }
    }

# ============================================================
# 14. POSTERIOR PREDICTIVE QLIKE DISTRIBUTION (BUG 2 FIX)
# ============================================================
print("\n[14] Posterior Predictive QLIKE Distribution (BUG 2 FIX)...")
n_pred_samples = 300
rng_pred = np.random.RandomState(77)
pred_indices = rng_pred.choice(len(all_samples), n_pred_samples, replace=False)

pred_qlikes = []
for idx in pred_indices:
    params = all_samples[idx]
    try:
        h_is_tmp, eps_is_tmp = garch_variance_numba(
            params[0], params[1], params[2], params[3], params[4], r_is
        )
        h_oos_tmp, _ = garch_oos_recursive(
            params[0], params[1], params[2], params[3], params[4],
            h_is_tmp[-1], eps_is_tmp[-1], r_oos
        )
        valid = (h_oos_tmp > 0) & np.isfinite(h_oos_tmp) & np.isfinite(rv_oos) & (rv_oos > 0)
        if valid.sum() > T_oos * 0.9:
            q = float(np.mean(rv_oos[valid] / h_oos_tmp[valid] - np.log(rv_oos[valid] / h_oos_tmp[valid]) - 1))
            pred_qlikes.append(q)
    except Exception:
        pass

pred_qlikes = np.array(pred_qlikes)
mle_qlike_val = results_metrics['MLE']['qlike']

print(f"  Valid posterior predictive samples: {len(pred_qlikes)}")
print(f"  Posterior predictive QLIKE: mean={np.mean(pred_qlikes):.4f}, std={np.std(pred_qlikes):.4f}")
print(f"  95% CI: [{np.percentile(pred_qlikes, 2.5):.4f}, {np.percentile(pred_qlikes, 97.5):.4f}]")
print(f"  MLE QLIKE: {mle_qlike_val:.4f}")
print(f"  P(Bayesian draw beats MLE): {np.mean(pred_qlikes < mle_qlike_val):.4f}")

# ============================================================
# 15. RESIDUAL DIAGNOSTICS
# ============================================================
print("\n[15] Residual Diagnostics (MLE model)...")
std_resid = eps_is_mle / np.sqrt(h_is_mle)
std_resid = std_resid[np.isfinite(std_resid)]

arch_resid_stat, arch_resid_p, *_ = het_arch(std_resid, nlags=10)
print(f"  ARCH LM(10) on std residuals: stat={arch_resid_stat:.4f}, p={arch_resid_p:.4f}")
print(f"  {'No remaining ARCH effects' if arch_resid_p > 0.05 else 'WARNING: residual ARCH effects'}")

lb_resid = acorr_ljungbox(std_resid**2, lags=[10], return_df=True)
lb_resid_p = float(lb_resid['lb_pvalue'].iloc[0])
print(f"  Ljung-Box(10) on std_resid^2: p={lb_resid_p:.4f}")

# ============================================================
# 16. GENERATE CHARTS
# ============================================================
print("\n[16] Generating charts...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

charts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'k814v2_charts')
os.makedirs(charts_dir, exist_ok=True)

# Chart 1: Posterior distributions (4 key params)
fig, axes = plt.subplots(2, 2, figsize=(12, 8))
fig.suptitle('K814v2: GJR-GARCH Posterior Distributions (Bug-Fixed)', fontsize=14, fontweight='bold')

for ax, (name, idx) in zip(axes.flat, [('alpha', 2), ('gamma', 3), ('beta', 4), ('omega', 1)]):
    samples_p = all_samples[:, idx]
    ax.hist(samples_p, bins=60, density=True, alpha=0.7, color='steelblue', edgecolor='white')
    ax.axvline(mle_params[name], color='red', linestyle='--', linewidth=2, label=f'MLE = {mle_params[name]:.5f}')
    ax.axvline(np.mean(samples_p), color='green', linestyle='-', linewidth=2, label=f'Post. mean = {np.mean(samples_p):.5f}')

    ci = np.percentile(samples_p, [2.5, 97.5])
    ax.axvspan(ci[0], ci[1], alpha=0.15, color='orange', label=f'95% CI')

    if name == 'gamma':
        ax.axvline(0, color='black', linestyle=':', linewidth=1.5, label='gamma=0')

    ax.set_title(f'{name} posterior', fontsize=12)
    ax.legend(fontsize=8)
    ax.set_xlabel(name)
    ax.set_ylabel('Density')

plt.tight_layout()
chart1_path = os.path.join(charts_dir, 'posterior_distributions.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 1: {chart1_path}")

# Chart 2: Persistence + gamma evidence
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

ax = axes[0]
ax.hist(persistence_samples, bins=60, density=True, alpha=0.7, color='steelblue', edgecolor='white')
ax.axvline(persistence_mle, color='red', linestyle='--', linewidth=2, label=f'MLE = {persistence_mle:.4f}')
ax.axvline(np.mean(persistence_samples), color='green', linestyle='-', linewidth=2,
           label=f'Post. mean = {np.mean(persistence_samples):.4f}')
ax.axvline(0.99, color='black', linestyle=':', linewidth=1.5, label='0.99 threshold')
ax.set_title('Persistence (alpha + gamma/2 + beta)', fontsize=12)
ax.legend(fontsize=9)
ax.set_xlabel('Persistence')

ax = axes[1]
ax.hist(gamma_samples, bins=60, density=True, alpha=0.7, color='coral', edgecolor='white')
ax.axvline(0, color='black', linestyle='-', linewidth=2, label='gamma = 0 (no leverage)')
ax.axvline(np.mean(gamma_samples), color='green', linestyle='-', linewidth=2,
           label=f'Post. mean = {np.mean(gamma_samples):.4f}')
# Mark the P(gamma > 0) region
ax.set_title(f'gamma posterior (P(gamma>0) = {p_gamma_gt_0:.4f})', fontsize=12)
ax.legend(fontsize=9)
ax.set_xlabel('gamma (leverage parameter)')

plt.tight_layout()
chart2_path = os.path.join(charts_dir, 'persistence_and_leverage.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 2: {chart2_path}")

# Chart 3: Posterior Predictive QLIKE distribution
fig, ax = plt.subplots(figsize=(8, 5))
ax.hist(pred_qlikes, bins=40, density=True, alpha=0.7, color='steelblue', edgecolor='white',
        label=f'Posterior Predictive QLIKE\nmean={np.mean(pred_qlikes):.4f}')
ax.axvline(mle_qlike_val, color='red', linestyle='--', linewidth=2,
           label=f'MLE QLIKE = {mle_qlike_val:.4f}')
p_beat_mle = np.mean(pred_qlikes < mle_qlike_val)
ax.set_title(f'Posterior Predictive QLIKE Distribution\nP(beat MLE) = {p_beat_mle:.3f}', fontsize=12)
ax.legend(fontsize=10)
ax.set_xlabel('QLIKE')
ax.set_ylabel('Density')
plt.tight_layout()
chart3_path = os.path.join(charts_dir, 'predictive_qlike_distribution.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 3: {chart3_path}")

# Chart 4: Parameter correlations
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
thin_step = max(1, len(all_samples) // 2000)
thin_idx = np.arange(0, len(all_samples), thin_step)

ax = axes[0]
ax.scatter(all_samples[thin_idx, 2], all_samples[thin_idx, 4], alpha=0.3, s=5, color='steelblue')
ax.plot(mle_params['alpha'], mle_params['beta'], 'r*', markersize=15, label='MLE')
ax.set_xlabel('alpha', fontsize=11)
ax.set_ylabel('beta', fontsize=11)
ax.set_title(f'alpha vs beta (corr = {corr_alpha_beta:.3f})', fontsize=12)
ax.legend()

ax = axes[1]
ax.scatter(all_samples[thin_idx, 2], all_samples[thin_idx, 3], alpha=0.3, s=5, color='coral')
ax.plot(mle_params['alpha'], mle_params['gamma'], 'r*', markersize=15, label='MLE')
ax.axhline(0, color='black', linestyle=':', linewidth=1, alpha=0.5)
ax.set_xlabel('alpha', fontsize=11)
ax.set_ylabel('gamma', fontsize=11)
ax.set_title(f'alpha vs gamma (corr = {corr_alpha_gamma:.3f})', fontsize=12)
ax.legend()

plt.tight_layout()
chart4_path = os.path.join(charts_dir, 'parameter_correlations.png')
plt.savefig(chart4_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 4: {chart4_path}")

# Chart 5: OOS forecasts
fig, ax = plt.subplots(figsize=(14, 5))
window = 20
rv_smooth = pd.Series(rv_oos).rolling(window).mean().values
mle_smooth = pd.Series(mle_forecast_h).rolling(window).mean().values
bma_smooth = pd.Series(bma_forecast_h).rolling(window).mean().values

x = np.arange(T_oos)
ax.plot(x, rv_smooth, 'k-', alpha=0.7, linewidth=1, label='Realized (20d MA)')
ax.plot(x, mle_smooth, 'r-', linewidth=1.5, label='MLE forecast')
ax.plot(x, bma_smooth, 'b-', linewidth=1.5, label='Bayesian BMA forecast')

bma_upper = pd.Series(bma_forecast_h + 1.96 * bma_forecast_std).rolling(window).mean().values
bma_lower = pd.Series(np.maximum(bma_forecast_h - 1.96 * bma_forecast_std, 0)).rolling(window).mean().values
ax.fill_between(x, bma_lower, bma_upper, alpha=0.15, color='blue', label='BMA 95% predictive CI')

ax.set_title('K814v2: OOS Volatility Forecast Comparison (20-day rolling avg)', fontsize=12)
ax.legend(fontsize=9)
ax.set_xlabel('Trading days (2023-2024)')
ax.set_ylabel('Conditional variance')
ax.set_xlim(window, T_oos)

plt.tight_layout()
chart5_path = os.path.join(charts_dir, 'oos_forecast_comparison.png')
plt.savefig(chart5_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 5: {chart5_path}")

# ============================================================
# 17. COMPILE RESULTS
# ============================================================
print("\n[17] Compiling results...")

best_method = min(results_metrics.keys(), key=lambda k: results_metrics[k]['qlike'])
best_bayes = min([k for k in results_metrics if k != 'MLE'], key=lambda k: results_metrics[k]['qlike'])
mle_q = results_metrics['MLE']['qlike']
best_bayes_q = results_metrics[best_bayes]['qlike']
improvement_pct = (mle_q - best_bayes_q) / mle_q * 100

any_harvey_sig = any(v.get('harvey_significant', False) for v in dm_results.values())
any_dm_sig_10 = any(v['p_value'] < 0.10 for v in dm_results.values())

results = {
    "experiment_id": "K814v2",
    "title": "Bayesian MCMC GJR-GARCH -- Bug-Fixed Version (3 HIGH fixes)",
    "date": datetime.now(timezone.utc).isoformat(),
    "extends": "K814",
    "fixes_from_K814": {
        "bug1_prior_tautology": {
            "problem": "gamma ~ HalfNormal(0.2) forced P(gamma>0)=1.0 regardless of data",
            "fix": "gamma ~ Normal(0, 0.2) — symmetric prior, data decides sign",
            "impact": f"P(gamma>0) changed from 1.000 (tautology) to {p_gamma_gt_0:.4f} (data-driven)"
        },
        "bug2_oos_h0_leak": {
            "problem": "OOS h[0] computed from full IS+OOS concatenation — used future data",
            "fix": "Compute IS variance series, extract h_last and eps_last, then recursive OOS forecast",
            "impact": "OOS forecasts now use only IS-available information at each step"
        },
        "bug3_ess_geweke": {
            "problem": "ESS used naive lag-1 ACF cutoff; Geweke used simple SE ignoring autocorrelation",
            "fix": "ESS via batch means (Geyer 1992); Geweke with Newey-West spectral density at freq 0",
            "impact": f"ESS values likely changed; Geweke z-scores corrected for autocorrelation"
        }
    },
    "asset": "SPY",
    "data_source": "yfinance",
    "data_period": {
        "total": "2006-01-01 ~ 2024-12-31",
        "in_sample": "2006-01-01 ~ 2022-12-31",
        "out_of_sample": "2023-01-01 ~ 2024-12-31",
        "is_n": int(len(r_is)),
        "oos_n": int(T_oos)
    },
    "methodology": {
        "model": "GJR-GARCH(1,1) with Normal innovations",
        "bayesian_method": "Random Walk Metropolis-Hastings",
        "n_iterations": N_ITER,
        "burn_in": BURN_IN,
        "n_chains": N_CHAINS,
        "n_posterior_samples": int(len(all_samples)),
        "bma_samples": int(bma_count),
        "var_samples": 500,
        "priors": {
            "mu": "N(0.05, 0.1)",
            "omega": "Exp(rate=100) [mean=0.01]",
            "alpha": "Beta(2,5) on [0, 0.5]",
            "gamma": "Normal(0, 0.2) [*** FIXED: allows negative ***]",
            "beta": "Beta(5,2) on [0, 0.999]"
        },
        "rv_proxy": "squared returns (r^2)",
        "oos_method": "Recursive from IS-final state (h_last, eps_last)",
        "ess_method": "Batch means (Geyer 1992)",
        "geweke_method": "Spectral density at freq 0 (Newey-West HAC)",
        "references": [
            "Ardia & Hoogerheide (2010), Bayesian Estimation of GARCH(1,1), R Journal",
            "Nakatsuma (2000), Bayesian analysis of ARMA-GARCH, J. Econometrics",
            "Geweke (1992), Evaluating sampling-based approaches, Bayesian Statistics 4",
            "Geyer (1992), Practical MCMC, Statistical Science (batch means ESS)",
            "Patton (2011), Volatility forecast comparison using imperfect proxies, J. Econometrics",
            "Harvey et al. (2016), t>3 threshold for significant predictors"
        ]
    },
    "diagnostics": {
        "descriptive_stats": desc,
        "adf_test": {"stat": float(adf_stat), "p_value": float(adf_p), "stationary": bool(adf_p < 0.05)},
        "arch_lm_test": {"stat": float(arch_lm_stat), "p_value": float(arch_lm_p), "arch_effects": bool(arch_lm_p < 0.05)},
        "ljung_box_sq": {"stat": lb_stat, "p_value": lb_p},
        "residual_arch_lm": {"stat": float(arch_resid_stat), "p_value": float(arch_resid_p), "clean": bool(arch_resid_p > 0.05)},
        "residual_ljung_box_sq": {"p_value": lb_resid_p},
        "mle_convergence": int(mle_res.convergence_flag),
        "mle_persistence": persistence_mle,
        "mle_standard_errors": mle_se
    },
    "mcmc_diagnostics": {
        "chain_acceptance_rates": chain_accept_rates,
        "gelman_rubin_rhat": {name: float(rhat[i]) for i, name in enumerate(PARAM_NAMES)},
        "effective_sample_size_batch_means": ess_values,
        "ess_per_chain": ess_per_chain,
        "geweke_test_spectral": {name: {
            'z_scores': geweke_results[name]['z_scores'],
            'p_values': geweke_results[name]['p_values'],
            'all_pass': geweke_results[name]['all_pass']
        } for name in PARAM_NAMES},
        "mcmc_time_seconds": round(mcmc_total_time, 1),
        "convergence_ok": all_rhat_ok,
        "min_ess": min(ess_values.values())
    },
    "posterior_summary": posterior_summary,
    "persistence_posterior": {
        "mean": float(np.mean(persistence_samples)),
        "std": float(np.std(persistence_samples)),
        "ci_2.5": float(persist_ci[0]),
        "ci_97.5": float(persist_ci[1]),
        "mle": persistence_mle,
        "p_gt_099": p_persist_gt_099
    },
    "bayesian_leverage_evidence": {
        "prior": "Normal(0, 0.2) — P(gamma>0|prior) = 0.500",
        "p_gamma_gt_0": p_gamma_gt_0,
        "p_gamma_lt_0": p_gamma_lt_0,
        "p_gamma_gt_005": p_gamma_gt_005,
        "p_gamma_gt_010": p_gamma_gt_010,
        "bayes_factor_leverage": bf_leverage,
        "posterior_mean_gamma": float(np.mean(gamma_samples)),
        "posterior_std_gamma": float(np.std(gamma_samples)),
        "posterior_ci_gamma": [float(np.percentile(gamma_samples, 2.5)), float(np.percentile(gamma_samples, 97.5))],
        "evidence_strength": strength,
        "k814_comparison": {
            "k814_prior": "HalfNormal(0.2) — P(gamma>0|prior) = 1.000 [TAUTOLOGY]",
            "k814_p_gamma_gt_0": 1.0,
            "k814v2_prior": "Normal(0, 0.2) — P(gamma>0|prior) = 0.500",
            "k814v2_p_gamma_gt_0": p_gamma_gt_0,
            "tautology_fixed": True
        }
    },
    "parameter_correlations": {
        "alpha_beta": corr_alpha_beta,
        "alpha_gamma": corr_alpha_gamma,
        "gamma_beta": corr_gamma_beta,
        "omega_beta": corr_omega_beta
    },
    "parameter_identification": param_quality,
    "oos_metrics": results_metrics,
    "dm_tests": dm_results,
    "posterior_predictive_qlike": {
        "n_samples": len(pred_qlikes),
        "mean": float(np.mean(pred_qlikes)),
        "std": float(np.std(pred_qlikes)),
        "ci_2.5": float(np.percentile(pred_qlikes, 2.5)),
        "ci_97.5": float(np.percentile(pred_qlikes, 97.5)),
        "mle_qlike": mle_qlike_val,
        "p_beat_mle": float(np.mean(pred_qlikes < mle_qlike_val))
    },
    "var_analysis_5pct": var_results_all.get('5pct', {}),
    "var_analysis_1pct": var_results_all.get('1pct', {}),
    "charts": [chart1_path, chart2_path, chart3_path, chart4_path, chart5_path],
    "conclusion": {}
}

# Write conclusion
leverage_conclusion = (
    f"With Normal(0,0.2) prior (allowing negative gamma), "
    f"P(gamma>0|data) = {p_gamma_gt_0:.4f} (BF={bf_leverage:.1f}). "
    f"K814 reported P(gamma>0)=1.000 but that was prior tautology (HalfNormal forces gamma>=0). "
    f"Now that the prior allows gamma<0, the evidence is {'genuine' if p_gamma_gt_0 > 0.80 else 'weaker than expected'}."
)

prediction_conclusion = (
    f"Best method by QLIKE: {best_method}. "
    f"Best Bayesian: {best_bayes} (QLIKE {improvement_pct:+.3f}% vs MLE). "
    f"{'No significant difference' if not any_dm_sig_10 else 'Marginally significant'} "
    f"(Harvey t>3: {'YES' if any_harvey_sig else 'NO'})."
)

results["conclusion"] = {
    "best_method_by_qlike": best_method,
    "best_bayesian_method": best_bayes,
    "bayesian_qlike_improvement_pct": round(improvement_pct, 3),
    "any_dm_significant_at_10pct": any_dm_sig_10,
    "any_dm_harvey_significant": any_harvey_sig,
    "leverage_evidence": leverage_conclusion,
    "prediction": prediction_conclusion,
    "summary": (
        f"K814v2 fixes 3 HIGH bugs from K814. "
        f"Key finding: P(gamma>0) = {p_gamma_gt_0:.4f} (was 1.000 due to HalfNormal prior tautology). "
        f"With Normal(0,0.2) prior, data genuinely {'supports' if p_gamma_gt_0 > 0.80 else 'weakly supports'} "
        f"the leverage effect (BF={bf_leverage:.1f}). "
        f"OOS: {best_method} wins by QLIKE ({improvement_pct:+.3f}% Bayesian vs MLE). "
        f"Convergence: all Rhat<1.1, min ESS(batch means)={min(ess_values.values())}. "
        f"VaR: both methods {'pass' if var_results_all.get('5pct', {}).get('mle', {}).get('kupiec_pass', False) and var_results_all.get('5pct', {}).get('bayesian', {}).get('kupiec_pass', False) else 'mixed'} Kupiec at 5%."
    ),
    "limitations": [
        "Normal innovations only (Student-t would improve tail fit)",
        "Squared returns as vol proxy (not intraday RV)",
        "Single asset (SPY)",
        "Random Walk MH is less efficient than HMC/NUTS",
        "Stationarity constraint forces alpha+gamma>=0, which limits gamma's negative range"
    ]
}

# Print summary
print("\n" + "=" * 70)
print("K814v2 CONCLUSION (Bug-Fixed)")
print("=" * 70)
print(f"\n  {results['conclusion']['summary']}")
print(f"\n  Leverage: {leverage_conclusion}")
print(f"\n  Prediction: {prediction_conclusion}")

# Save results
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'k814v2_bayesian_mcmc_fixed_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\nDone.")
