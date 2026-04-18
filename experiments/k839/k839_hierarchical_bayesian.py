"""
K839: Hierarchical Bayesian GJR-GARCH — Cross-Asset Shared Prior
================================================================
[提出: K814v2 衍生, 執行: Claude]

Hypothesis: Cross-asset sharing of gamma (leverage) prior can improve
small-sample estimation for assets with less data (GLD, 0050.TW).

Method (2-Stage Empirical Bayes):
  Stage 1: Independent MLE for each asset → extract gamma distribution
  Stage 2: Use empirical gamma distribution as informative prior →
           Bayesian re-estimation with MCMC

Assets: SPY, QQQ, GLD, 0050.TW
IS: 2006-01-01 ~ 2022-12-31
OOS: 2023-01-01 ~ 2024-12-31
Proxy: squared returns (Patton 2011)

Error Log Rules:
  - 0050.TW: must use clean_tw50_data
  - Bayesian prior: gamma ~ Normal (allows negative, not HalfNormal)
  - GARCH OOS: recursive h[t] = f(h[t-1], r²[t-1])
  - DM test: use volpred.stats.model_evaluation.dm_test

References:
- Ardia & Hoogerheide (2010), Bayesian GARCH, R Journal
- Nakatsuma (2000), Bayesian ARMA-GARCH, J. Econometrics
- Fioruci et al. (2014), Bayesian multivariate GARCH, Comput. Stats & Data Analysis
- Patton (2011), Volatility forecast comparison, J. Econometrics
- Engle & Kroner (1995), Multivariate GARCH, Econometric Theory
"""

import numpy as np
import json
import time
import warnings
import os
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

print("=" * 70)
print("K839: Hierarchical Bayesian GJR-GARCH — Cross-Asset Shared Prior")
print("  Stage 1: Independent MLE per asset")
print("  Stage 2: Empirical Bayes — shared gamma prior from Stage 1")
print("  Stage 3: Independent Bayes (flat prior, K814v2 style)")
print("=" * 70)

# ============================================================
# 1. DATA COLLECTION
# ============================================================
import yfinance as yf
import pandas as pd

print("\n[1] Downloading data for 4 assets...")
assets = ['SPY', 'QQQ', 'GLD', '0050.TW']
asset_labels = {'SPY': 'SPY', 'QQQ': 'QQQ', 'GLD': 'GLD', '0050.TW': '0050.TW'}

raw_data = {}
for ticker in assets:
    df = yf.download(ticker, start='2005-06-01', end='2025-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[ticker] = df

# Clean 0050.TW data
from volpred.utils import clean_tw50_data
tw_prices = raw_data['0050.TW']['Close']
tw_returns = tw_prices.pct_change().dropna()
tw_prices_clean, tw_returns_clean = clean_tw50_data(tw_prices, tw_returns)

# Build return series (percentage returns)
returns_dict = {}
for ticker in assets:
    if ticker == '0050.TW':
        ret = tw_returns_clean * 100  # percentage
    else:
        ret = raw_data[ticker]['Close'].pct_change().dropna() * 100
    # Drop any NaN/inf
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
    returns_dict[ticker] = ret

# IS/OOS split
is_start, is_end = '2006-01-01', '2023-01-01'
oos_start, oos_end = '2023-01-01', '2025-01-01'

data = {}
for ticker in assets:
    ret = returns_dict[ticker]
    is_mask = (ret.index >= is_start) & (ret.index < is_end)
    oos_mask = (ret.index >= oos_start) & (ret.index < oos_end)
    r_is = ret[is_mask].values.astype(np.float64)
    r_oos = ret[oos_mask].values.astype(np.float64)
    data[ticker] = {'r_is': r_is, 'r_oos': r_oos}
    print(f"  {ticker}: IS={len(r_is)} obs, OOS={len(r_oos)} obs")

# ============================================================
# 2. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[2] Descriptive Statistics (IS period)...")
desc_stats = {}
for ticker in assets:
    r = data[ticker]['r_is']
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch
    adf_stat, adf_p, *_ = adfuller(r, maxlag=20)
    arch_stat, arch_p, *_ = het_arch(r, nlags=10)
    d = {
        'n': len(r),
        'mean': float(np.mean(r)),
        'std': float(np.std(r)),
        'skew': float(stats.skew(r)),
        'kurtosis': float(stats.kurtosis(r)),
        'adf_p': float(adf_p),
        'arch_lm_p': float(arch_p),
    }
    desc_stats[ticker] = d
    print(f"  {ticker}: n={d['n']}, mean={d['mean']:.4f}, std={d['std']:.4f}, "
          f"skew={d['skew']:.4f}, kurt={d['kurtosis']:.4f}, "
          f"ADF_p={d['adf_p']:.4f}, ARCH_p={d['arch_lm_p']:.6f}")

# ============================================================
# 3. NUMBA-ACCELERATED GJR-GARCH FUNCTIONS
# ============================================================
print("\n[3] Compiling Numba functions...")

@njit(cache=True)
def garch_variance(mu, omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) conditional variance series."""
    T = len(returns)
    eps = np.empty(T)
    h = np.empty(T)
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
def garch_loglik(mu, omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) log-likelihood."""
    h, eps = garch_variance(mu, omega, alpha, gamma, beta, returns)
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
    """Recursive OOS forecasting from IS-final state."""
    T = len(returns_oos)
    h = np.empty(T)
    eps = np.empty(T)
    leverage_last = eps_last ** 2 * (1.0 if eps_last < 0 else 0.0)
    h[0] = omega + alpha * eps_last ** 2 + gamma * leverage_last + beta * h_last
    if h[0] < 1e-8:
        h[0] = 1e-8
    eps[0] = returns_oos[0] - mu
    for t in range(1, T):
        leverage = eps[t-1] ** 2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * eps[t-1] ** 2 + gamma * leverage + beta * h[t-1]
        if h[t] < 1e-8:
            h[t] = 1e-8
        eps[t] = returns_oos[t] - mu
    return h, eps

# JIT warmup
_ = garch_loglik(0.04, 0.03, 0.02, 0.10, 0.85, np.random.randn(100))
_ = garch_oos_recursive(0.04, 0.03, 0.02, 0.10, 0.85, 1.0, -0.5, np.random.randn(10))
print("  JIT compilation done.")

# ============================================================
# 4. STAGE 1: INDEPENDENT MLE PER ASSET
# ============================================================
print("\n[4] Stage 1: Independent MLE GJR-GARCH per asset...")
from arch import arch_model

mle_results = {}
for ticker in assets:
    r_is = data[ticker]['r_is']
    am = arch_model(r_is, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
    res = am.fit(disp='off')
    params = {
        'mu': float(res.params['mu']),
        'omega': float(res.params['omega']),
        'alpha': float(res.params['alpha[1]']),
        'gamma': float(res.params['gamma[1]']),
        'beta': float(res.params['beta[1]']),
    }
    se = {
        'mu': float(res.std_err['mu']),
        'omega': float(res.std_err['omega']),
        'alpha': float(res.std_err['alpha[1]']),
        'gamma': float(res.std_err['gamma[1]']),
        'beta': float(res.std_err['beta[1]']),
    }
    persistence = params['alpha'] + params['gamma'] / 2 + params['beta']
    conv = int(res.convergence_flag)
    mle_results[ticker] = {
        'params': params,
        'se': se,
        'persistence': persistence,
        'convergence': conv,
    }
    print(f"  {ticker}: alpha={params['alpha']:.4f}, gamma={params['gamma']:.4f}, "
          f"beta={params['beta']:.4f}, persist={persistence:.4f}, conv={conv}")

# Compute cross-asset gamma distribution (empirical Bayes hyperprior)
gammas_mle = [mle_results[t]['params']['gamma'] for t in assets]
gamma_mean = float(np.mean(gammas_mle))
gamma_std = float(np.std(gammas_mle, ddof=1))  # sample std
print(f"\n  Cross-asset gamma: mean={gamma_mean:.4f}, std={gamma_std:.4f}")
print(f"  Individual gammas: {[f'{g:.4f}' for g in gammas_mle]}")

# ============================================================
# 5. MLE OOS FORECASTING
# ============================================================
print("\n[5] MLE OOS forecasting (recursive)...")

mle_oos = {}
for ticker in assets:
    r_is = data[ticker]['r_is']
    r_oos = data[ticker]['r_oos']
    p = mle_results[ticker]['params']

    # Get IS-final state
    h_is, eps_is = garch_variance(p['mu'], p['omega'], p['alpha'], p['gamma'], p['beta'], r_is)
    h_last = h_is[-1]
    eps_last = eps_is[-1]

    # Recursive OOS
    h_oos, eps_oos = garch_oos_recursive(
        p['mu'], p['omega'], p['alpha'], p['gamma'], p['beta'],
        h_last, eps_last, r_oos
    )

    # Evaluate: QLIKE on r^2
    r2_oos = r_oos ** 2
    valid = (h_oos > 0) & np.isfinite(h_oos) & (r2_oos > 0)
    qlike = float(np.mean(r2_oos[valid] / h_oos[valid] - np.log(r2_oos[valid] / h_oos[valid]) - 1))
    rho, rho_p = stats.spearmanr(r2_oos[valid], h_oos[valid])

    mle_oos[ticker] = {
        'h_oos': h_oos,
        'qlike': qlike,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
    }
    print(f"  {ticker}: QLIKE={qlike:.4f}, Spearman={rho:.4f} (p={rho_p:.4f})")

# ============================================================
# 6. BAYESIAN MCMC FUNCTIONS
# ============================================================
print("\n[6] Setting up Bayesian MCMC...")

def log_prior_independent(params):
    """Independent (flat-ish) priors — K814v2 style.
    gamma ~ Normal(0, 0.2) — allows negative.
    """
    mu, omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or beta >= 1.0:
        return -np.inf
    if alpha > 0.5 or gamma < -0.5 or gamma > 0.5:
        return -np.inf
    if alpha + max(gamma, 0) / 2 + beta >= 1.0:
        return -np.inf
    if alpha + gamma < -0.01:
        return -np.inf

    lp = 0.0
    lp += stats.expon.logpdf(omega, scale=0.01)      # omega ~ Exp(100)
    lp += stats.beta.logpdf(alpha / 0.5, 2, 5)       # alpha ~ Beta(2,5) on [0, 0.5]
    lp += stats.beta.logpdf(beta / 0.999, 5, 2)      # beta ~ Beta(5,2) on [0, 0.999]
    lp += stats.norm.logpdf(gamma, 0, 0.2)            # gamma ~ N(0, 0.2)
    lp += stats.norm.logpdf(mu, 0.05, 0.1)            # mu ~ N(0.05, 0.1)
    return lp

def log_prior_hierarchical(params, gamma_prior_mean, gamma_prior_std):
    """Hierarchical prior — gamma centered on cross-asset empirical mean.
    gamma ~ Normal(gamma_prior_mean, gamma_prior_std)
    Other priors same as independent.
    """
    mu, omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or beta < 0 or beta >= 1.0:
        return -np.inf
    if alpha > 0.5 or gamma < -0.5 or gamma > 0.5:
        return -np.inf
    if alpha + max(gamma, 0) / 2 + beta >= 1.0:
        return -np.inf
    if alpha + gamma < -0.01:
        return -np.inf

    lp = 0.0
    lp += stats.expon.logpdf(omega, scale=0.01)
    lp += stats.beta.logpdf(alpha / 0.5, 2, 5)
    lp += stats.beta.logpdf(beta / 0.999, 5, 2)
    # KEY DIFFERENCE: gamma prior from cross-asset distribution
    # Use minimum std of 0.05 to avoid over-shrinkage
    effective_std = max(gamma_prior_std, 0.05)
    lp += stats.norm.logpdf(gamma, gamma_prior_mean, effective_std)
    lp += stats.norm.logpdf(mu, 0.05, 0.1)
    return lp

def run_mcmc(r_is, log_prior_fn, init_params, n_iter=5000, n_burnin=1000,
             proposal_scale=None):
    """Random-walk Metropolis-Hastings MCMC for GJR-GARCH.

    Returns: (samples, accept_rate)
    """
    if proposal_scale is None:
        proposal_scale = np.array([0.005, 0.002, 0.005, 0.008, 0.005])

    n_params = 5
    samples = np.zeros((n_iter, n_params))
    current = np.array(init_params, dtype=np.float64)

    current_logpost = log_prior_fn(current) + garch_loglik(
        current[0], current[1], current[2], current[3], current[4], r_is
    )

    accept_count = 0
    for i in range(n_iter):
        # Propose
        proposal = current + np.random.randn(n_params) * proposal_scale
        prop_logpost = log_prior_fn(proposal)

        if np.isfinite(prop_logpost):
            prop_logpost += garch_loglik(
                proposal[0], proposal[1], proposal[2], proposal[3], proposal[4], r_is
            )

        # Accept/reject
        log_alpha = prop_logpost - current_logpost
        if np.log(np.random.rand()) < log_alpha:
            current = proposal.copy()
            current_logpost = prop_logpost
            accept_count += 1

        samples[i] = current

    accept_rate = accept_count / n_iter
    posterior = samples[n_burnin:]
    return posterior, accept_rate

# ============================================================
# 7. STAGE 2: INDEPENDENT BAYESIAN (FLAT PRIOR)
# ============================================================
print("\n[7] Stage 2: Independent Bayesian MCMC (flat prior)...")
t_start = time.time()

N_ITER = 5000
N_BURNIN = 1000

indep_bayes = {}
for ticker in assets:
    r_is = data[ticker]['r_is']
    p = mle_results[ticker]['params']
    init = [p['mu'], p['omega'], p['alpha'], p['gamma'], p['beta']]

    posterior, accept_rate = run_mcmc(
        r_is, log_prior_independent, init,
        n_iter=N_ITER, n_burnin=N_BURNIN
    )

    param_names = ['mu', 'omega', 'alpha', 'gamma', 'beta']
    post_means = {param_names[j]: float(np.mean(posterior[:, j])) for j in range(5)}
    post_std = {param_names[j]: float(np.std(posterior[:, j])) for j in range(5)}

    # OOS forecast using posterior mean
    h_is, eps_is = garch_variance(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'], r_is
    )
    h_oos, _ = garch_oos_recursive(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'],
        h_is[-1], eps_is[-1], data[ticker]['r_oos']
    )

    r2_oos = data[ticker]['r_oos'] ** 2
    valid = (h_oos > 0) & np.isfinite(h_oos) & (r2_oos > 0)
    qlike = float(np.mean(r2_oos[valid] / h_oos[valid] - np.log(r2_oos[valid] / h_oos[valid]) - 1))
    rho, rho_p = stats.spearmanr(r2_oos[valid], h_oos[valid])

    # P(gamma > 0)
    p_gamma_pos = float(np.mean(posterior[:, 3] > 0))

    indep_bayes[ticker] = {
        'params': post_means,
        'params_std': post_std,
        'accept_rate': accept_rate,
        'p_gamma_pos': p_gamma_pos,
        'h_oos': h_oos,
        'qlike': qlike,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
    }
    print(f"  {ticker}: gamma={post_means['gamma']:.4f} (std={post_std['gamma']:.4f}), "
          f"P(gamma>0)={p_gamma_pos:.3f}, accept={accept_rate:.3f}, "
          f"QLIKE={qlike:.4f}, Spearman={rho:.4f}")

t_indep = time.time() - t_start
print(f"  Independent Bayes time: {t_indep:.1f}s")

# ============================================================
# 8. STAGE 3: HIERARCHICAL BAYESIAN (SHARED GAMMA PRIOR)
# ============================================================
print("\n[8] Stage 3: Hierarchical Bayesian (shared gamma prior)...")
print(f"  Hyperprior: gamma ~ N({gamma_mean:.4f}, {max(gamma_std, 0.05):.4f})")
t_start = time.time()

hier_bayes = {}
for ticker in assets:
    r_is = data[ticker]['r_is']
    p = mle_results[ticker]['params']
    init = [p['mu'], p['omega'], p['alpha'], p['gamma'], p['beta']]

    # Use hierarchical prior with shared gamma
    def hier_prior(params, gm=gamma_mean, gs=gamma_std):
        return log_prior_hierarchical(params, gm, gs)

    posterior, accept_rate = run_mcmc(
        r_is, hier_prior, init,
        n_iter=N_ITER, n_burnin=N_BURNIN
    )

    param_names = ['mu', 'omega', 'alpha', 'gamma', 'beta']
    post_means = {param_names[j]: float(np.mean(posterior[:, j])) for j in range(5)}
    post_std = {param_names[j]: float(np.std(posterior[:, j])) for j in range(5)}

    # OOS forecast
    h_is, eps_is = garch_variance(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'], r_is
    )
    h_oos, _ = garch_oos_recursive(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'],
        h_is[-1], eps_is[-1], data[ticker]['r_oos']
    )

    r2_oos = data[ticker]['r_oos'] ** 2
    valid = (h_oos > 0) & np.isfinite(h_oos) & (r2_oos > 0)
    qlike = float(np.mean(r2_oos[valid] / h_oos[valid] - np.log(r2_oos[valid] / h_oos[valid]) - 1))
    rho, rho_p = stats.spearmanr(r2_oos[valid], h_oos[valid])

    p_gamma_pos = float(np.mean(posterior[:, 3] > 0))

    # Shrinkage: how much did hierarchical shrink gamma toward the mean?
    gamma_mle = mle_results[ticker]['params']['gamma']
    gamma_hier = post_means['gamma']
    gamma_indep = indep_bayes[ticker]['params']['gamma']
    shrinkage_vs_mle = abs(gamma_hier - gamma_mean) / max(abs(gamma_mle - gamma_mean), 1e-6)

    hier_bayes[ticker] = {
        'params': post_means,
        'params_std': post_std,
        'accept_rate': accept_rate,
        'p_gamma_pos': p_gamma_pos,
        'h_oos': h_oos,
        'qlike': qlike,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
        'shrinkage_ratio': float(shrinkage_vs_mle),
    }
    print(f"  {ticker}: gamma={post_means['gamma']:.4f} (std={post_std['gamma']:.4f}), "
          f"P(gamma>0)={p_gamma_pos:.3f}, accept={accept_rate:.3f}, "
          f"QLIKE={qlike:.4f}, Spearman={rho:.4f}, "
          f"shrink={shrinkage_vs_mle:.3f}")

t_hier = time.time() - t_start
print(f"  Hierarchical Bayes time: {t_hier:.1f}s")

# ============================================================
# 9. ITERATIVE HIERARCHICAL (2 ROUNDS)
# ============================================================
print("\n[9] Iterative Hierarchical (update hyperprior after round 1)...")

# Round 2: Use hierarchical posteriors to update hyperprior
hier_gammas_r1 = [hier_bayes[t]['params']['gamma'] for t in assets]
gamma_mean_r2 = float(np.mean(hier_gammas_r1))
gamma_std_r2 = float(np.std(hier_gammas_r1, ddof=1))
print(f"  Updated hyperprior: gamma ~ N({gamma_mean_r2:.4f}, {max(gamma_std_r2, 0.05):.4f})")

t_start = time.time()
hier_bayes_r2 = {}
for ticker in assets:
    r_is = data[ticker]['r_is']
    p = mle_results[ticker]['params']
    init = [p['mu'], p['omega'], p['alpha'], p['gamma'], p['beta']]

    def hier_prior_r2(params, gm=gamma_mean_r2, gs=gamma_std_r2):
        return log_prior_hierarchical(params, gm, gs)

    posterior, accept_rate = run_mcmc(
        r_is, hier_prior_r2, init,
        n_iter=N_ITER, n_burnin=N_BURNIN
    )

    param_names = ['mu', 'omega', 'alpha', 'gamma', 'beta']
    post_means = {param_names[j]: float(np.mean(posterior[:, j])) for j in range(5)}
    post_std = {param_names[j]: float(np.std(posterior[:, j])) for j in range(5)}

    # OOS
    h_is, eps_is = garch_variance(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'], r_is
    )
    h_oos, _ = garch_oos_recursive(
        post_means['mu'], post_means['omega'], post_means['alpha'],
        post_means['gamma'], post_means['beta'],
        h_is[-1], eps_is[-1], data[ticker]['r_oos']
    )

    r2_oos = data[ticker]['r_oos'] ** 2
    valid = (h_oos > 0) & np.isfinite(h_oos) & (r2_oos > 0)
    qlike = float(np.mean(r2_oos[valid] / h_oos[valid] - np.log(r2_oos[valid] / h_oos[valid]) - 1))
    rho, rho_p = stats.spearmanr(r2_oos[valid], h_oos[valid])
    p_gamma_pos = float(np.mean(posterior[:, 3] > 0))

    hier_bayes_r2[ticker] = {
        'params': post_means,
        'params_std': post_std,
        'accept_rate': accept_rate,
        'p_gamma_pos': p_gamma_pos,
        'h_oos': h_oos,
        'qlike': qlike,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
    }
    print(f"  {ticker}: gamma={post_means['gamma']:.4f}, "
          f"QLIKE={qlike:.4f}, Spearman={rho:.4f}")

t_iter = time.time() - t_start
print(f"  Iterative Hierarchical time: {t_iter:.1f}s")

# ============================================================
# 10. DM TESTS: HIERARCHICAL vs MLE (per asset)
# ============================================================
print("\n[10] DM Tests: Hierarchical vs MLE (QLIKE pointwise)...")
from volpred.stats.model_evaluation import dm_test, qlike_pointwise

dm_results = {}
for ticker in assets:
    r2_oos = data[ticker]['r_oos'] ** 2

    # QLIKE pointwise losses
    h_mle = mle_oos[ticker]['h_oos']
    h_indep = indep_bayes[ticker]['h_oos']
    h_hier = hier_bayes[ticker]['h_oos']
    h_hier_r2 = hier_bayes_r2[ticker]['h_oos']

    loss_mle = qlike_pointwise(r2_oos, h_mle)
    loss_indep = qlike_pointwise(r2_oos, h_indep)
    loss_hier = qlike_pointwise(r2_oos, h_hier)
    loss_hier_r2 = qlike_pointwise(r2_oos, h_hier_r2)

    # DM: Hier vs MLE (negative t → Hier better)
    t_hm, p_hm = dm_test(loss_hier, loss_mle)
    # DM: Hier vs IndepBayes
    t_hi, p_hi = dm_test(loss_hier, loss_indep)
    # DM: HierR2 vs MLE
    t_h2m, p_h2m = dm_test(loss_hier_r2, loss_mle)

    dm_results[ticker] = {
        'hier_vs_mle': {'t': float(t_hm), 'p': float(p_hm)},
        'hier_vs_indep': {'t': float(t_hi), 'p': float(p_hi)},
        'hier_r2_vs_mle': {'t': float(t_h2m), 'p': float(p_h2m)},
    }

    better_hm = "Hier" if t_hm < 0 else "MLE"
    sig_hm = "***" if abs(t_hm) > 3.0 else ("**" if abs(t_hm) > 2.0 else ("*" if abs(t_hm) > 1.65 else ""))
    print(f"  {ticker}: Hier vs MLE: t={t_hm:.3f} ({better_hm}{sig_hm}), "
          f"Hier vs Indep: t={t_hi:.3f}, "
          f"HierR2 vs MLE: t={t_h2m:.3f}")

# ============================================================
# 11. SUMMARY TABLE
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY TABLE: QLIKE (lower = better)")
print("=" * 70)
print(f"{'Asset':<10} {'MLE':>10} {'Ind.Bayes':>10} {'Hier.Bay':>10} {'Hier.R2':>10} {'Best':>10}")
print("-" * 60)

best_method = {}
for ticker in assets:
    q_mle = mle_oos[ticker]['qlike']
    q_indep = indep_bayes[ticker]['qlike']
    q_hier = hier_bayes[ticker]['qlike']
    q_hier2 = hier_bayes_r2[ticker]['qlike']

    values = {'MLE': q_mle, 'IndBay': q_indep, 'HierBay': q_hier, 'HierR2': q_hier2}
    best = min(values, key=values.get)
    best_method[ticker] = best

    print(f"{ticker:<10} {q_mle:>10.4f} {q_indep:>10.4f} {q_hier:>10.4f} {q_hier2:>10.4f} {best:>10}")

print("\nSUMMARY TABLE: Spearman Rank Correlation (higher = better)")
print("-" * 60)
print(f"{'Asset':<10} {'MLE':>10} {'Ind.Bayes':>10} {'Hier.Bay':>10} {'Hier.R2':>10}")
print("-" * 60)
for ticker in assets:
    r_mle = mle_oos[ticker]['spearman_rho']
    r_indep = indep_bayes[ticker]['spearman_rho']
    r_hier = hier_bayes[ticker]['spearman_rho']
    r_hier2 = hier_bayes_r2[ticker]['spearman_rho']
    print(f"{ticker:<10} {r_mle:>10.4f} {r_indep:>10.4f} {r_hier:>10.4f} {r_hier2:>10.4f}")

print("\nGAMMA ESTIMATES COMPARISON")
print("-" * 70)
print(f"{'Asset':<10} {'MLE':>10} {'Ind.Bay':>10} {'Hier.Bay':>10} {'Hier.R2':>10} {'Hyperprior':>12}")
print("-" * 70)
for ticker in assets:
    g_mle = mle_results[ticker]['params']['gamma']
    g_indep = indep_bayes[ticker]['params']['gamma']
    g_hier = hier_bayes[ticker]['params']['gamma']
    g_hier2 = hier_bayes_r2[ticker]['params']['gamma']
    print(f"{ticker:<10} {g_mle:>10.4f} {g_indep:>10.4f} {g_hier:>10.4f} {g_hier2:>10.4f} {gamma_mean:>12.4f}")

print(f"\nHyperprior R1: N({gamma_mean:.4f}, {max(gamma_std, 0.05):.4f})")
print(f"Hyperprior R2: N({gamma_mean_r2:.4f}, {max(gamma_std_r2, 0.05):.4f})")

# ============================================================
# 12. SMALL SAMPLE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("SMALL SAMPLE ANALYSIS: Does hierarchical help assets with less data?")
print("=" * 70)

for ticker in assets:
    n_is = len(data[ticker]['r_is'])
    q_mle = mle_oos[ticker]['qlike']
    q_hier = hier_bayes[ticker]['qlike']
    q_hier2 = hier_bayes_r2[ticker]['qlike']
    improvement = (q_mle - q_hier) / q_mle * 100  # positive = hier better
    improvement_r2 = (q_mle - q_hier2) / q_mle * 100

    gamma_se_mle = mle_results[ticker]['se']['gamma']
    gamma_se_hier = hier_bayes[ticker]['params_std']['gamma']
    se_reduction = (gamma_se_mle - gamma_se_hier) / gamma_se_mle * 100

    print(f"\n  {ticker} (n_IS={n_is}):")
    print(f"    QLIKE: MLE={q_mle:.4f}, Hier={q_hier:.4f} ({improvement:+.2f}%), "
          f"HierR2={q_hier2:.4f} ({improvement_r2:+.2f}%)")
    print(f"    Gamma SE: MLE={gamma_se_mle:.4f}, Hier={gamma_se_hier:.4f} "
          f"(reduction={se_reduction:+.1f}%)")
    dm_t = dm_results[ticker]['hier_vs_mle']['t']
    dm_p = dm_results[ticker]['hier_vs_mle']['p']
    print(f"    DM test (Hier vs MLE): t={dm_t:.3f}, p={dm_p:.4f} "
          f"({'Hier sig. better' if dm_t < -3.0 else 'Not significant'})")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'K839',
    'title': 'Hierarchical Bayesian GJR-GARCH — Cross-Asset Shared Prior',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'assets': assets,
    'is_period': '2006-01-01 ~ 2022-12-31',
    'oos_period': '2023-01-01 ~ 2024-12-31',
    'mcmc_settings': {
        'n_iter': N_ITER,
        'n_burnin': N_BURNIN,
    },
    'descriptive_stats': desc_stats,
    'stage1_mle': {
        ticker: {
            'params': mle_results[ticker]['params'],
            'se': mle_results[ticker]['se'],
            'persistence': mle_results[ticker]['persistence'],
            'convergence': mle_results[ticker]['convergence'],
            'oos_qlike': mle_oos[ticker]['qlike'],
            'oos_spearman': mle_oos[ticker]['spearman_rho'],
        } for ticker in assets
    },
    'hyperprior': {
        'round1': {'gamma_mean': gamma_mean, 'gamma_std': max(gamma_std, 0.05)},
        'round2': {'gamma_mean': gamma_mean_r2, 'gamma_std': max(gamma_std_r2, 0.05)},
    },
    'independent_bayes': {
        ticker: {
            'params': indep_bayes[ticker]['params'],
            'params_std': indep_bayes[ticker]['params_std'],
            'accept_rate': indep_bayes[ticker]['accept_rate'],
            'p_gamma_pos': indep_bayes[ticker]['p_gamma_pos'],
            'oos_qlike': indep_bayes[ticker]['qlike'],
            'oos_spearman': indep_bayes[ticker]['spearman_rho'],
        } for ticker in assets
    },
    'hierarchical_bayes_r1': {
        ticker: {
            'params': hier_bayes[ticker]['params'],
            'params_std': hier_bayes[ticker]['params_std'],
            'accept_rate': hier_bayes[ticker]['accept_rate'],
            'p_gamma_pos': hier_bayes[ticker]['p_gamma_pos'],
            'oos_qlike': hier_bayes[ticker]['qlike'],
            'oos_spearman': hier_bayes[ticker]['spearman_rho'],
            'shrinkage_ratio': hier_bayes[ticker]['shrinkage_ratio'],
        } for ticker in assets
    },
    'hierarchical_bayes_r2': {
        ticker: {
            'params': hier_bayes_r2[ticker]['params'],
            'params_std': hier_bayes_r2[ticker]['params_std'],
            'accept_rate': hier_bayes_r2[ticker]['accept_rate'],
            'p_gamma_pos': hier_bayes_r2[ticker]['p_gamma_pos'],
            'oos_qlike': hier_bayes_r2[ticker]['qlike'],
            'oos_spearman': hier_bayes_r2[ticker]['spearman_rho'],
        } for ticker in assets
    },
    'dm_tests': dm_results,
    'best_method_per_asset': best_method,
    'timing': {
        'independent_bayes_s': round(t_indep, 1),
        'hierarchical_bayes_s': round(t_hier, 1),
        'iterative_hier_s': round(t_iter, 1),
    },
    'conclusion': '',  # Will be filled after analysis
    'references': [
        'Ardia & Hoogerheide (2010), Bayesian GARCH, R Journal',
        'Nakatsuma (2000), Bayesian ARMA-GARCH, J. Econometrics',
        'Fioruci et al. (2014), Bayesian multivariate GARCH, CSDA',
        'Patton (2011), Volatility forecast comparison, J. Econometrics',
    ],
}

# Fill conclusion based on results
hier_wins = sum(1 for t in assets if best_method[t] in ['HierBay', 'HierR2'])
mle_wins = sum(1 for t in assets if best_method[t] == 'MLE')
indep_wins = sum(1 for t in assets if best_method[t] == 'IndBay')

# Check if hierarchical helps small-sample assets
small_assets = ['GLD', '0050.TW']  # less data or different market
small_hier_helps = 0
for t in small_assets:
    if hier_bayes[t]['qlike'] < mle_oos[t]['qlike']:
        small_hier_helps += 1

conclusion_parts = []
conclusion_parts.append(f"Cross-asset hierarchical Bayesian GJR-GARCH tested on 4 assets (SPY, QQQ, GLD, 0050.TW).")
conclusion_parts.append(f"Best method by QLIKE: MLE wins {mle_wins}/4, IndepBayes wins {indep_wins}/4, Hierarchical wins {hier_wins}/4.")
conclusion_parts.append(f"Hyperprior gamma ~ N({gamma_mean:.4f}, {max(gamma_std, 0.05):.4f}) from MLE cross-section.")

if small_hier_helps > 0:
    conclusion_parts.append(f"Hierarchical helped {small_hier_helps}/{len(small_assets)} small-sample assets (GLD/0050.TW) — shrinkage toward group mean improved estimation.")
else:
    conclusion_parts.append(f"Hierarchical did NOT help small-sample assets — individual MLE already sufficient with {min(len(data[t]['r_is']) for t in small_assets)}+ IS observations.")

# Check DM significance
any_sig = any(abs(dm_results[t]['hier_vs_mle']['t']) > 3.0 for t in assets)
if any_sig:
    sig_assets = [t for t in assets if abs(dm_results[t]['hier_vs_mle']['t']) > 3.0]
    conclusion_parts.append(f"DM test significant (|t|>3.0) for: {sig_assets}.")
else:
    conclusion_parts.append("No DM test reached Harvey (2016) significance (|t|>3.0) — differences are noise.")

results['conclusion'] = ' '.join(conclusion_parts)

# Save
results_path = os.path.join(SCRIPT_DIR, 'k839_hierarchical_bayesian_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {results_path}")

print("\n" + "=" * 70)
print("CONCLUSION:")
print(results['conclusion'])
print("=" * 70)
print("\nDone!")
