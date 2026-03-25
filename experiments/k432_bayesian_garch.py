"""
K432: Bayesian MCMC GJR-GARCH Volatility Prediction
=====================================================
[提出: 用戶 (MCMC suggestion), 執行: Claude]

Research Questions:
1. Does Bayesian GJR-GARCH posterior mean beat MLE point estimate?
2. Can posterior predictive distribution improve VaR estimation?
3. How large is parameter uncertainty?

Data: SPY daily returns from yfinance
IS: 2005-01-01 ~ 2022-12-31
OOS: 2023-01-01 ~ 2024-12-31
Proxy for realized vol: squared returns (standard in GARCH literature)

Method:
- Random Walk Metropolis-Hastings for GJR-GARCH(1,1)
- 5000 iterations (1000 burn-in + 4000 posterior samples) per chain
- 2 chains for convergence diagnostic (Gelman-Rubin Rhat)
- Comparison: MLE (arch package) vs Bayesian posterior mean vs Bayesian posterior median
"""

import numpy as np
import json
import time
import warnings
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K432: Bayesian MCMC GJR-GARCH Volatility Prediction")
print("=" * 60)

import yfinance as yf

print("\n[1] Downloading SPY data...")
spy = yf.download('SPY', start='2005-01-01', end='2025-01-01', progress=False)
if isinstance(spy.columns, __import__('pandas').MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
returns = spy['Close'].pct_change().dropna() * 100  # percentage returns
print(f"  Total observations: {len(returns)}")
print(f"  Date range: {returns.index[0].strftime('%Y-%m-%d')} ~ {returns.index[-1].strftime('%Y-%m-%d')}")

# Split
is_mask = returns.index < '2023-01-01'
oos_mask = (returns.index >= '2023-01-01') & (returns.index < '2025-01-01')
r_is = returns[is_mask].values
r_oos = returns[oos_mask].values
print(f"  IS: {is_mask.sum()} obs, OOS: {oos_mask.sum()} obs")

# ============================================================
# 2. DESCRIPTIVE STATISTICS (diagnostics first)
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

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, *_ = adfuller(r_is, maxlag=20)
print(f"  ADF: stat={adf_stat:.4f}, p={adf_p:.6f} ({'stationary' if adf_p < 0.05 else 'non-stationary'})")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, *_ = het_arch(r_is, nlags=10)
print(f"  ARCH LM(10): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f} ({'ARCH effects' if arch_lm_p < 0.05 else 'no ARCH effects'})")

# Ljung-Box on squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox
lb = acorr_ljungbox(r_is**2, lags=[10], return_df=True)
lb_stat = float(lb['lb_stat'].iloc[0])
lb_p = float(lb['lb_pvalue'].iloc[0])
print(f"  Ljung-Box(10) on r²: stat={lb_stat:.4f}, p={lb_p:.6f}")

# ============================================================
# 3. MLE GJR-GARCH (baseline)
# ============================================================
print("\n[3] MLE GJR-GARCH(1,1)...")
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
persistence_mle = mle_params['alpha'] + mle_params['gamma']/2 + mle_params['beta']
print(f"  MLE params: mu={mle_params['mu']:.4f}, omega={mle_params['omega']:.4f}")
print(f"  alpha={mle_params['alpha']:.4f}, gamma={mle_params['gamma']:.4f}, beta={mle_params['beta']:.4f}")
print(f"  Persistence: {persistence_mle:.4f}")
print(f"  Convergence: {mle_res.convergence_flag} (0=success)")

# ============================================================
# 4. BAYESIAN GJR-GARCH via Metropolis-Hastings
# ============================================================
print("\n[4] Bayesian GJR-GARCH via Metropolis-Hastings...")

def garch_variance(params, returns):
    """Compute GJR-GARCH(1,1) conditional variance series."""
    mu, omega, alpha, gamma, beta = params
    T = len(returns)
    eps = returns - mu
    h = np.empty(T)
    h[0] = np.var(eps)

    for t in range(1, T):
        leverage = eps[t-1]**2 * (eps[t-1] < 0)
        h[t] = omega + alpha * eps[t-1]**2 + gamma * leverage + beta * h[t-1]
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h, eps

def garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood (normal)."""
    h, eps = garch_variance(params, returns)
    if np.any(h <= 0) or np.any(np.isnan(h)):
        return -np.inf
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + eps**2 / h)
    if np.isnan(ll) or np.isinf(ll):
        return -np.inf
    return ll

def log_prior(params):
    """Weakly informative priors for GJR-GARCH parameters."""
    mu, omega, alpha, gamma, beta = params

    # Boundary checks
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or beta >= 1:
        return -np.inf
    if alpha + gamma / 2 + beta >= 1.0:
        return -np.inf
    if alpha > 0.5 or gamma > 0.5:
        return -np.inf

    lp = 0.0
    # mu ~ N(0.05, 0.1)
    lp += stats.norm.logpdf(mu, 0.05, 0.1)
    # omega ~ HalfNormal(scale=0.1)
    lp += stats.halfnorm.logpdf(omega, scale=0.1)
    # alpha ~ Beta(2, 10) scaled to [0, 0.5]
    lp += stats.beta.logpdf(alpha / 0.5, 2, 10) - np.log(0.5)
    # gamma ~ HalfNormal(scale=0.1)
    lp += stats.halfnorm.logpdf(gamma, scale=0.1)
    # beta ~ Beta(10, 2) scaled to [0, 0.999]
    lp += stats.beta.logpdf(beta / 0.999, 10, 2) - np.log(0.999)

    if np.isnan(lp):
        return -np.inf
    return lp

def run_mcmc_chain(returns, n_iter=5000, burn_in=1000, seed=None):
    """Run a single MCMC chain with Random Walk Metropolis-Hastings."""
    if seed is not None:
        np.random.seed(seed)

    # Initialize at MLE
    current = np.array([mle_params['mu'], mle_params['omega'],
                        mle_params['alpha'], mle_params['gamma'],
                        mle_params['beta']])

    # Adaptive proposal (start conservative)
    proposal_std = np.array([0.003, 0.003, 0.005, 0.005, 0.003])

    n_params = len(current)
    samples = np.zeros((n_iter, n_params))
    current_ll = garch_loglik(current, returns)
    current_lp = log_prior(current)
    current_post = current_ll + current_lp
    accept = 0

    # Adaptation phase (first 500 iterations)
    adapt_interval = 100

    for i in range(n_iter):
        # Propose
        proposal = current + proposal_std * np.random.randn(n_params)

        prop_lp = log_prior(proposal)
        if prop_lp == -np.inf:
            samples[i] = current
            continue

        prop_ll = garch_loglik(proposal, returns)
        prop_post = prop_ll + prop_lp

        log_ratio = prop_post - current_post
        if np.log(np.random.rand()) < log_ratio:
            current = proposal
            current_post = prop_post
            accept += 1

        samples[i] = current

        # Adapt proposal std during burn-in
        if i < burn_in and i > 0 and i % adapt_interval == 0:
            recent_rate = np.mean(np.diff(samples[max(0, i-adapt_interval):i+1], axis=0).any(axis=1))
            if recent_rate < 0.15:
                proposal_std *= 0.7
            elif recent_rate > 0.45:
                proposal_std *= 1.3

    accept_rate = accept / n_iter
    posterior = samples[burn_in:]
    return posterior, accept_rate

# Run 2 chains
t0 = time.time()
print("  Running Chain 1...")
chain1, ar1 = run_mcmc_chain(r_is, n_iter=5000, burn_in=1000, seed=42)
print(f"    Acceptance rate: {ar1:.3f}")
print("  Running Chain 2...")
chain2, ar2 = run_mcmc_chain(r_is, n_iter=5000, burn_in=1000, seed=123)
print(f"    Acceptance rate: {ar2:.3f}")
mcmc_time = time.time() - t0
print(f"  MCMC total time: {mcmc_time:.1f}s")

# Combine chains
all_samples = np.vstack([chain1, chain2])  # 8000 samples total
param_names = ['mu', 'omega', 'alpha', 'gamma', 'beta']

# ============================================================
# 5. CONVERGENCE DIAGNOSTICS
# ============================================================
print("\n[5] Convergence Diagnostics...")

def gelman_rubin(chains):
    """Compute Gelman-Rubin Rhat for each parameter."""
    n_chains = len(chains)
    n = chains[0].shape[0]
    n_params = chains[0].shape[1]
    rhat = np.zeros(n_params)

    for p in range(n_params):
        chain_means = np.array([c[:, p].mean() for c in chains])
        chain_vars = np.array([c[:, p].var(ddof=1) for c in chains])

        W = np.mean(chain_vars)  # within-chain variance
        B = n * np.var(chain_means, ddof=1)  # between-chain variance

        var_hat = (1 - 1/n) * W + (1/n) * B
        if W > 0:
            rhat[p] = np.sqrt(var_hat / W)
        else:
            rhat[p] = np.nan
    return rhat

rhat = gelman_rubin([chain1, chain2])

# Effective sample size (simple estimate)
def ess_simple(x):
    """Simple ESS using autocorrelation."""
    n = len(x)
    if n < 10:
        return n
    # Use first 50 lags
    max_lag = min(50, n // 2)
    acf_vals = np.correlate(x - x.mean(), x - x.mean(), mode='full')
    acf_vals = acf_vals[n-1:] / acf_vals[n-1]

    # Sum pairs of autocorrelations until they go negative
    tau = 1.0
    for k in range(1, max_lag):
        if acf_vals[k] < 0:
            break
        tau += 2 * acf_vals[k]

    return max(1, int(n / tau))

ess_values = {}
for i, name in enumerate(param_names):
    ess_values[name] = ess_simple(all_samples[:, i])

print(f"  {'Param':>8} {'Rhat':>8} {'ESS':>8}")
print(f"  {'-'*26}")
for i, name in enumerate(param_names):
    print(f"  {name:>8} {rhat[i]:>8.4f} {ess_values[name]:>8d}")

# ============================================================
# 6. POSTERIOR SUMMARY
# ============================================================
print("\n[6] Posterior Parameter Summary...")
posterior_summary = {}
print(f"  {'Param':>8} {'Mean':>10} {'Median':>10} {'Std':>10} {'CI_2.5':>10} {'CI_97.5':>10} {'MLE':>10}")
print(f"  {'-'*72}")

for i, name in enumerate(param_names):
    samples_p = all_samples[:, i]
    ci = np.percentile(samples_p, [2.5, 97.5])
    summary = {
        'mean': float(np.mean(samples_p)),
        'median': float(np.median(samples_p)),
        'std': float(np.std(samples_p)),
        'ci_2.5': float(ci[0]),
        'ci_97.5': float(ci[1]),
        'mle': float(mle_params[name])
    }
    posterior_summary[name] = summary
    print(f"  {name:>8} {summary['mean']:>10.5f} {summary['median']:>10.5f} "
          f"{summary['std']:>10.5f} {summary['ci_2.5']:>10.5f} {summary['ci_97.5']:>10.5f} "
          f"{summary['mle']:>10.5f}")

# Check if MLE falls within 95% CI
print("\n  MLE within 95% posterior CI?")
for name in param_names:
    s = posterior_summary[name]
    inside = s['ci_2.5'] <= s['mle'] <= s['ci_97.5']
    print(f"    {name}: {'YES' if inside else 'NO'} (MLE={s['mle']:.5f}, CI=[{s['ci_2.5']:.5f}, {s['ci_97.5']:.5f}])")

# ============================================================
# 7. OOS FORECASTING
# ============================================================
print("\n[7] OOS Forecasting...")

# Method 1: MLE forecast
# Refit full MLE on IS
mle_h_is, mle_eps_is = garch_variance(
    [mle_params['mu'], mle_params['omega'], mle_params['alpha'],
     mle_params['gamma'], mle_params['beta']], r_is)

# Rolling 1-step forecast on OOS
T_oos = len(r_oos)
all_returns = np.concatenate([r_is, r_oos])

# MLE forecast
mle_forecast_h = np.zeros(T_oos)
h_full_mle, eps_full_mle = garch_variance(
    [mle_params['mu'], mle_params['omega'], mle_params['alpha'],
     mle_params['gamma'], mle_params['beta']], all_returns)
# OOS forecasts are h[T_is], h[T_is+1], ... (each is forecast from t-1 info)
T_is = len(r_is)
mle_forecast_h = h_full_mle[T_is:]

# Method 2: Bayesian posterior mean forecast
bayes_mean_params = np.mean(all_samples, axis=0)
h_full_bayes_mean, _ = garch_variance(bayes_mean_params, all_returns)
bayes_mean_forecast_h = h_full_bayes_mean[T_is:]

# Method 3: Bayesian posterior median forecast
bayes_median_params = np.median(all_samples, axis=0)
h_full_bayes_median, _ = garch_variance(bayes_median_params, all_returns)
bayes_median_forecast_h = h_full_bayes_median[T_is:]

# Method 4: Bayesian Model Averaging (BMA) - average over posterior samples
# Sample 200 parameter sets from posterior, average the variance forecasts
n_bma = 200
bma_indices = np.random.choice(len(all_samples), n_bma, replace=False)
bma_h_sum = np.zeros(T_oos)
bma_count = 0
for idx in bma_indices:
    try:
        h_tmp, _ = garch_variance(all_samples[idx], all_returns)
        if np.all(np.isfinite(h_tmp[T_is:])):
            bma_h_sum += h_tmp[T_is:]
            bma_count += 1
    except:
        pass
bma_forecast_h = bma_h_sum / bma_count if bma_count > 0 else bayes_mean_forecast_h
print(f"  BMA: used {bma_count}/{n_bma} posterior samples")

# Realized vol proxy: squared returns
rv_oos = r_oos ** 2

# ============================================================
# 8. EVALUATION METRICS
# ============================================================
print("\n[8] Evaluation Metrics...")

def qlike(rv, h):
    """QLIKE loss (lower is better)."""
    valid = (h > 0) & np.isfinite(h) & np.isfinite(rv) & (rv > 0)
    return float(np.mean(rv[valid] / h[valid] - np.log(rv[valid] / h[valid]) - 1))

def mse(rv, h):
    valid = np.isfinite(h) & np.isfinite(rv)
    return float(np.mean((rv[valid] - h[valid])**2))

def mae(rv, h):
    valid = np.isfinite(h) & np.isfinite(rv)
    return float(np.mean(np.abs(rv[valid] - h[valid])))

# Compute metrics
methods = {
    'MLE': mle_forecast_h,
    'Bayes_Mean': bayes_mean_forecast_h,
    'Bayes_Median': bayes_median_forecast_h,
    'Bayes_BMA': bma_forecast_h
}

results_metrics = {}
print(f"\n  {'Method':>15} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
print(f"  {'-'*50}")
for name, h in methods.items():
    q = qlike(rv_oos, h)
    m = mse(rv_oos, h)
    a = mae(rv_oos, h)
    results_metrics[name] = {'qlike': q, 'mse': m, 'mae': a}
    print(f"  {name:>15} {q:>10.4f} {m:>12.4f} {a:>10.4f}")

# ============================================================
# 9. DIEBOLD-MARIANO TESTS
# ============================================================
print("\n[9] Diebold-Mariano Tests (QLIKE loss)...")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West variance (for h-step ahead)
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(nw_var / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

# QLIKE losses for each method
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
print(f"\n  {'Comparison':>30} {'DM_stat':>10} {'p_value':>10} {'Better':>10}")
print(f"  {'-'*62}")
for method1, method2 in comparisons:
    dm_stat, dm_p = dm_test(qlike_losses[method1], qlike_losses[method2])
    better = method1 if dm_stat < 0 else method2
    sig = '*' if dm_p < 0.10 else ('**' if dm_p < 0.05 else ('***' if dm_p < 0.01 else ''))
    dm_results[f'{method1}_vs_{method2}'] = {
        'dm_stat': dm_stat, 'p_value': dm_p, 'better': better
    }
    print(f"  {method1+' vs '+method2:>30} {dm_stat:>10.4f} {dm_p:>10.4f} {better:>10} {sig}")

# ============================================================
# 10. VaR ANALYSIS
# ============================================================
print("\n[10] VaR Analysis...")

# MLE VaR (normal distribution assumption)
alpha_var = 0.05
mle_var_5 = -(mle_params['mu'] + stats.norm.ppf(alpha_var) * np.sqrt(mle_forecast_h))

# Bayesian predictive VaR: for each day, sample from posterior
# and compute VaR as average over posterior samples
n_var_samples = 500
var_sample_idx = np.random.choice(len(all_samples), n_var_samples, replace=False)

# For efficiency: compute VaR at each OOS day by averaging quantiles
# across posterior parameter samples
bayes_var_5 = np.zeros(T_oos)
for idx in var_sample_idx:
    try:
        h_tmp, _ = garch_variance(all_samples[idx], all_returns)
        h_oos_tmp = h_tmp[T_is:]
        mu_tmp = all_samples[idx, 0]
        var_tmp = -(mu_tmp + stats.norm.ppf(alpha_var) * np.sqrt(h_oos_tmp))
        if np.all(np.isfinite(var_tmp)):
            bayes_var_5 += var_tmp
    except:
        pass
bayes_var_5 /= n_var_samples

# VaR exceedance
mle_violations = np.sum(r_oos < -mle_var_5)
bayes_violations = np.sum(r_oos < -bayes_var_5)
expected_violations = int(alpha_var * T_oos)

# Kupiec POF test
def kupiec_test(violations, n, alpha):
    """Kupiec Proportion of Failures test."""
    p_hat = violations / n
    if p_hat == 0 or p_hat == 1:
        return np.nan, np.nan
    lr = 2 * (violations * np.log(p_hat / alpha) +
              (n - violations) * np.log((1 - p_hat) / (1 - alpha)))
    p_val = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(p_val)

kupiec_mle_stat, kupiec_mle_p = kupiec_test(mle_violations, T_oos, alpha_var)
kupiec_bayes_stat, kupiec_bayes_p = kupiec_test(bayes_violations, T_oos, alpha_var)

print(f"  5% VaR Analysis (OOS, n={T_oos}):")
print(f"  Expected violations: {expected_violations} ({alpha_var*100:.0f}%)")
print(f"  MLE violations:      {mle_violations} ({mle_violations/T_oos*100:.1f}%) | Kupiec LR={kupiec_mle_stat:.3f}, p={kupiec_mle_p:.4f}")
print(f"  Bayesian violations: {bayes_violations} ({bayes_violations/T_oos*100:.1f}%) | Kupiec LR={kupiec_bayes_stat:.3f}, p={kupiec_bayes_p:.4f}")

# ============================================================
# 11. PARAMETER UNCERTAINTY ANALYSIS
# ============================================================
print("\n[11] Parameter Uncertainty Analysis...")
persistence_samples = all_samples[:, 2] + all_samples[:, 3] / 2 + all_samples[:, 4]
persist_ci = np.percentile(persistence_samples, [2.5, 97.5])
print(f"  Persistence (α + γ/2 + β):")
print(f"    Mean: {np.mean(persistence_samples):.4f}, Std: {np.std(persistence_samples):.4f}")
print(f"    95% CI: [{persist_ci[0]:.4f}, {persist_ci[1]:.4f}]")
print(f"    MLE:  {persistence_mle:.4f}")

# Coefficient of variation for each parameter
print(f"\n  Parameter uncertainty (CV = std/|mean|):")
for i, name in enumerate(param_names):
    cv = posterior_summary[name]['std'] / abs(posterior_summary[name]['mean']) if posterior_summary[name]['mean'] != 0 else np.inf
    print(f"    {name}: CV = {cv:.3f} ({'high uncertainty' if cv > 0.3 else 'moderate' if cv > 0.1 else 'well-determined'})")

# ============================================================
# 12. RESIDUAL DIAGNOSTICS
# ============================================================
print("\n[12] Residual Diagnostics (MLE model)...")
h_is_mle, eps_is_mle = garch_variance(
    [mle_params['mu'], mle_params['omega'], mle_params['alpha'],
     mle_params['gamma'], mle_params['beta']], r_is)
std_resid = eps_is_mle / np.sqrt(h_is_mle)
std_resid = std_resid[np.isfinite(std_resid)]

# ARCH LM on standardized residuals
arch_resid_stat, arch_resid_p, *_ = het_arch(std_resid, nlags=10)
print(f"  ARCH LM(10) on std residuals: stat={arch_resid_stat:.4f}, p={arch_resid_p:.4f}")
print(f"  {'No remaining ARCH effects' if arch_resid_p > 0.05 else 'WARNING: residual ARCH effects'}")

lb_resid = acorr_ljungbox(std_resid**2, lags=[10], return_df=True)
lb_resid_p = float(lb_resid['lb_pvalue'].iloc[0])
print(f"  Ljung-Box(10) on std_resid²: p={lb_resid_p:.4f}")

# ============================================================
# 13. COMPILE RESULTS
# ============================================================
print("\n[13] Compiling results...")

# Determine overall conclusion
best_method = min(results_metrics.keys(), key=lambda k: results_metrics[k]['qlike'])
mle_qlike = results_metrics['MLE']['qlike']
best_bayes_method = min([k for k in results_metrics if k != 'MLE'], key=lambda k: results_metrics[k]['qlike'])
best_bayes_qlike = results_metrics[best_bayes_method]['qlike']
improvement_pct = (mle_qlike - best_bayes_qlike) / mle_qlike * 100

# Check DM significance
any_dm_sig = any(v['p_value'] < 0.10 for v in dm_results.values())

results = {
    "experiment_id": "K432",
    "title": "Bayesian MCMC GJR-GARCH Volatility Prediction",
    "date": datetime.now(timezone.utc).isoformat(),
    "asset": "SPY",
    "data_source": "yfinance",
    "data_period": {
        "total": "2005-01-01 ~ 2024-12-31",
        "in_sample": "2005-01-01 ~ 2022-12-31",
        "out_of_sample": "2023-01-01 ~ 2024-12-31",
        "is_n": int(len(r_is)),
        "oos_n": int(T_oos)
    },
    "methodology": {
        "model": "GJR-GARCH(1,1) with Normal innovations",
        "bayesian_method": "Random Walk Metropolis-Hastings",
        "n_iterations": 5000,
        "burn_in": 1000,
        "n_chains": 2,
        "n_posterior_samples": int(len(all_samples)),
        "bma_samples": int(bma_count),
        "var_samples": n_var_samples,
        "priors": {
            "mu": "N(0.05, 0.1)",
            "omega": "HalfNormal(0.1)",
            "alpha": "Beta(2,10) * 0.5",
            "gamma": "HalfNormal(0.1)",
            "beta": "Beta(10,2) * 0.999"
        },
        "rv_proxy": "squared returns"
    },
    "diagnostics": {
        "descriptive_stats": desc,
        "adf_test": {"stat": float(adf_stat), "p_value": float(adf_p), "stationary": bool(adf_p < 0.05)},
        "arch_lm_test": {"stat": float(arch_lm_stat), "p_value": float(arch_lm_p), "arch_effects": bool(arch_lm_p < 0.05)},
        "ljung_box_sq": {"stat": lb_stat, "p_value": lb_p},
        "residual_arch_lm": {"stat": float(arch_resid_stat), "p_value": float(arch_resid_p), "clean": bool(arch_resid_p > 0.05)},
        "mle_convergence": int(mle_res.convergence_flag),
        "mle_persistence": persistence_mle
    },
    "mcmc_diagnostics": {
        "chain1_acceptance_rate": ar1,
        "chain2_acceptance_rate": ar2,
        "gelman_rubin_rhat": {name: float(rhat[i]) for i, name in enumerate(param_names)},
        "effective_sample_size": ess_values,
        "mcmc_time_seconds": round(mcmc_time, 1),
        "convergence_ok": all(rhat[i] < 1.1 for i in range(len(param_names)))
    },
    "posterior_summary": posterior_summary,
    "persistence_posterior": {
        "mean": float(np.mean(persistence_samples)),
        "std": float(np.std(persistence_samples)),
        "ci_2.5": float(persist_ci[0]),
        "ci_97.5": float(persist_ci[1]),
        "mle": persistence_mle
    },
    "oos_metrics": results_metrics,
    "dm_tests": dm_results,
    "var_analysis": {
        "alpha": alpha_var,
        "expected_violations": expected_violations,
        "mle": {
            "violations": int(mle_violations),
            "violation_rate": float(mle_violations / T_oos),
            "kupiec_lr": kupiec_mle_stat,
            "kupiec_p": kupiec_mle_p,
            "kupiec_pass": bool(kupiec_mle_p > 0.05 if not np.isnan(kupiec_mle_p) else False)
        },
        "bayesian": {
            "violations": int(bayes_violations),
            "violation_rate": float(bayes_violations / T_oos),
            "kupiec_lr": kupiec_bayes_stat,
            "kupiec_p": kupiec_bayes_p,
            "kupiec_pass": bool(kupiec_bayes_p > 0.05 if not np.isnan(kupiec_bayes_p) else False)
        }
    },
    "conclusion": {
        "best_method_by_qlike": best_method,
        "best_bayesian_method": best_bayes_method,
        "bayesian_qlike_improvement_pct": round(improvement_pct, 3),
        "dm_significant_at_10pct": any_dm_sig,
        "bayesian_improves_prediction": improvement_pct > 0,
        "bayesian_significantly_better": any_dm_sig and improvement_pct > 0,
        "summary": ""
    }
}

# Write summary
if improvement_pct > 0 and any_dm_sig:
    results["conclusion"]["summary"] = (
        f"Bayesian GJR-GARCH ({best_bayes_method}) significantly outperforms MLE "
        f"with {improvement_pct:.2f}% QLIKE improvement (DM test significant). "
        f"Parameter uncertainty is non-trivial — posterior provides richer information."
    )
elif improvement_pct > 0:
    results["conclusion"]["summary"] = (
        f"Bayesian GJR-GARCH ({best_bayes_method}) shows {improvement_pct:.2f}% QLIKE improvement "
        f"over MLE, but the difference is NOT statistically significant (DM test). "
        f"Bayesian and MLE produce nearly identical point forecasts — the real value of "
        f"Bayesian GARCH is in uncertainty quantification, not point prediction improvement."
    )
else:
    results["conclusion"]["summary"] = (
        f"Bayesian GJR-GARCH does NOT improve over MLE point forecasts "
        f"(QLIKE {improvement_pct:.2f}% {'worse' if improvement_pct < 0 else 'same'}). "
        f"With weakly informative priors, posterior concentrates near MLE. "
        f"Bayesian value is in uncertainty quantification (posterior intervals), not point prediction."
    )

# Print summary
print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)
print(f"  Best overall: {best_method}")
print(f"  Best Bayesian: {best_bayes_method}")
print(f"  QLIKE improvement: {improvement_pct:.3f}%")
print(f"  DM significant? {any_dm_sig}")
print(f"  VaR: MLE {mle_violations} violations ({kupiec_mle_p:.4f}), "
      f"Bayesian {bayes_violations} violations ({kupiec_bayes_p:.4f})")
print(f"\n  {results['conclusion']['summary']}")

# Save
output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a87353fb/experiments/k432_bayesian_garch_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("\nDone.")
