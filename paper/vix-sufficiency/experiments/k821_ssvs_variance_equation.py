"""
K821: Bayesian SSVS for ARX-GARCH Variance Equation (External Variables)
=========================================================================
Reference: So, Chen, Liu (2006) JRSS-C Applied Statistics 55(2):201-224
Prior work:
  - K433: SSVS mean equation → null model (no exogenous helps predict SPY returns)
  - K461: SSVS Taiwan mean equation → SPY_ret PIP=1.000
  - K484: SSVS variance equation with INTERNAL components (GJR, VIX_implied,
           Parkinson, semivariance, abs_shock) → 4/5 PIP=1.000, QLIKE -7.43%
  - K818: SSVS return prediction with Gibbs → NULL for SPY

K821 innovation (user-proposed direction):
  K484 tested internal GARCH extensions (structural components).
  K821 asks: which EXTERNAL/MARKET variables truly improve variance prediction?

  Variance equation:
    σ²_t = ω + (α + γ·I_{t-1})·ε²_{t-1} + β·σ²_{t-1} + Σ δ_i·θ_i·X_{i,t-1}

  where δ_i ∈ {0,1} (SSVS indicator), θ_i is the coefficient for external variable i.

  Strategy: Fix GARCH parameters via MLE (GJR-GARCH baseline), then run SSVS
  only on the external variable coefficients. This two-stage approach avoids the
  convergence issues of joint GARCH+SSVS MCMC (K484 lesson: ESS for GARCH
  parameters was very low ~8-55).

Candidate external variables (8):
  1. VIX_level        — implied volatility level (lagged)
  2. VIX_change       — daily VIX change (regime shift signal)
  3. VIX9D            — 9-day VIX (short-term implied vol)
  4. VVIX_proxy       — VIX 20d rolling std (vol-of-vol proxy)
  5. TLT_vol          — 20d realized vol of TLT (bond vol → flight to quality)
  6. HYG_spread       — HYG - LQD return spread (credit risk proxy)
  7. term_spread      — TLT - SHY return spread (yield curve slope proxy)
  8. SPY_volume_ratio — SPY volume / 20d avg volume (activity proxy)

MCMC: Gibbs Sampler (conjugate for linear regression on pseudo-target)
  - Fix σ²_t from GJR-GARCH MLE → define z_t = σ²_t - (ω + α·ε²_{t-1} + β·σ²_{t-1})
  - Then z_t = Σ δ_i·θ_i·X_{i,t-1} + noise
  - This is a standard linear regression with SSVS → closed-form Gibbs steps
  - 10000 iterations, 2000 burn-in
  - Prior: δ ~ Bernoulli(0.5), θ|δ=1 ~ N(0, τ²), θ|δ=0 ~ N(0, (cτ)²) with c=0.01

Evaluation:
  - PIP ranking (which external variables matter?)
  - Median Probability Model (PIP > 0.5) vs GJR-GARCH baseline
  - QLIKE on r², DM test (Harvey t > 3.0 threshold)
  - Comparison with K484 internal components and K113 individual testing
  - OOS: expanding window, refit every 126 days (half-year)

Asset: SPY
Data: yfinance (empirical)
Period: 2007-01-01 to latest
OOS: 2023-01-01 to 2024-12-31

[提出: 用戶 (K433 direction), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import time
import warnings
from datetime import datetime, timezone
from scipy import stats as sp_stats
from scipy.optimize import minimize

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. DATA DOWNLOAD AND PREPARATION
# ============================================================
print("=" * 70)
print("K821: Bayesian SSVS for ARX-GARCH Variance Equation (External Vars)")
print("Reference: So, Chen, Liu (2006) JRSS-C 55(2):201-224")
print("=" * 70)

start_time = time.time()

print("\n[1] Downloading data from yfinance...")
tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX9D': '^VIX9D',
    'TLT': 'TLT',
    'SHY': 'SHY',
    'HYG': 'HYG',
    'LQD': 'LQD',
}

raw_data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2007-01-01', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw_data[name] = df
        print(f"  {name} ({ticker}): {len(df)} rows, "
              f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {name} ({ticker}): FAILED - {e}")

# Build master DataFrame on SPY trading days
spy_close = raw_data['SPY']['Close']
spy_ret = spy_close.pct_change().dropna() * 100  # percentage returns
spy_volume = raw_data['SPY']['Volume']

data = pd.DataFrame(index=spy_ret.index)
data['spy_ret'] = spy_ret
data['spy_ret_sq'] = spy_ret ** 2  # squared return (proxy for σ²)

# ============================================================
# 2. CONSTRUCT 8 CANDIDATE EXTERNAL VARIABLES (all lagged by 1)
# ============================================================
print("\n[2] Constructing 8 candidate external variables...")

# 1. VIX level (standardized as VIX²/252 for variance scale)
vix_close = raw_data['VIX']['Close'].reindex(data.index, method='ffill')
data['VIX_level'] = (vix_close ** 2) / 252.0  # daily implied variance

# 2. VIX daily change (absolute, captures regime shifts)
data['VIX_change'] = vix_close.diff().abs()

# 3. VIX9D (short-term implied vol, VIX²/252 scale)
if 'VIX9D' in raw_data and len(raw_data['VIX9D']) > 100:
    vix9d_close = raw_data['VIX9D']['Close'].reindex(data.index, method='ffill')
    data['VIX9D'] = (vix9d_close ** 2) / 252.0
    has_vix9d = True
    print("  VIX9D available")
else:
    # VIX9D only available from ~2011. Use VIX * 0.9 as rough proxy for earlier period.
    vix9d_close = raw_data['VIX']['Close'].reindex(data.index, method='ffill')
    data['VIX9D'] = (vix9d_close * 0.9) ** 2 / 252.0
    has_vix9d = False
    print("  VIX9D not available, using VIX*0.9 proxy")

# 4. VVIX proxy: 20-day rolling std of VIX (vol-of-vol)
data['VVIX_proxy'] = vix_close.rolling(20).std()

# 5. TLT realized vol: 20-day rolling std of TLT returns (annualized)
tlt_close = raw_data['TLT']['Close'].reindex(data.index, method='ffill')
tlt_ret = tlt_close.pct_change() * 100
data['TLT_vol'] = tlt_ret.rolling(20).std() * np.sqrt(252)

# 6. HYG-LQD spread: credit risk proxy (return differential)
hyg_close = raw_data['HYG']['Close'].reindex(data.index, method='ffill')
lqd_close = raw_data['LQD']['Close'].reindex(data.index, method='ffill')
hyg_ret = hyg_close.pct_change() * 100
lqd_ret = lqd_close.pct_change() * 100
data['HYG_spread'] = (hyg_ret - lqd_ret).abs()  # absolute spread

# 7. Term spread: TLT - SHY return spread (yield curve slope proxy)
shy_close = raw_data['SHY']['Close'].reindex(data.index, method='ffill')
shy_ret = shy_close.pct_change() * 100
data['term_spread'] = (tlt_ret - shy_ret).abs()  # absolute for variance

# 8. SPY volume ratio: volume / 20d average (activity proxy)
spy_vol_series = spy_volume.reindex(data.index, method='ffill')
data['SPY_volume_ratio'] = spy_vol_series / spy_vol_series.rolling(20).mean()

# Variable names
candidate_vars = [
    'VIX_level', 'VIX_change', 'VIX9D', 'VVIX_proxy',
    'TLT_vol', 'HYG_spread', 'term_spread', 'SPY_volume_ratio'
]
n_candidates = len(candidate_vars)

# Drop NaN and infinity
data = data.dropna()
data = data.replace([np.inf, -np.inf], np.nan).dropna()

# Winsorize at 1st/99th percentile for stability
for col in candidate_vars:
    lo, hi = data[col].quantile(0.01), data[col].quantile(0.99)
    data[col] = data[col].clip(lo, hi)

print(f"  Dataset: {len(data)} observations "
      f"({data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')})")
for v in candidate_vars:
    print(f"    {v:20s}: mean={data[v].mean():10.4f}, std={data[v].std():10.4f}")

# ============================================================
# 3. DESCRIPTIVE STATISTICS AND DIAGNOSTICS
# ============================================================
print("\n[3] Descriptive statistics and diagnostics...")

y_all = data['spy_ret'].values
print(f"  SPY returns:")
print(f"    Mean:     {np.mean(y_all):.4f}%")
print(f"    Std:      {np.std(y_all):.4f}%")
print(f"    Skewness: {pd.Series(y_all).skew():.4f}")
print(f"    Kurtosis: {pd.Series(y_all).kurtosis():.4f} (excess)")
print(f"    N:        {len(y_all)}")

from statsmodels.tsa.stattools import adfuller
adf_stat, adf_pval, *_ = adfuller(y_all, maxlag=10, autolag='AIC')
print(f"  ADF test: stat={adf_stat:.4f}, p={adf_pval:.6f} "
      f"{'(stationary)' if adf_pval < 0.01 else ''}")

from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
arch_lm = het_arch(y_all, nlags=5)
print(f"  ARCH LM (5 lags): stat={arch_lm[0]:.4f}, p={arch_lm[1]:.6f} "
      f"{'(ARCH effects)' if arch_lm[1] < 0.05 else ''}")

lb_sq = acorr_ljungbox(y_all**2, lags=[10], return_df=True)
print(f"  Ljung-Box on r² (10): stat={lb_sq['lb_stat'].values[0]:.4f}, "
      f"p={lb_sq['lb_pvalue'].values[0]:.6f}")

# Correlations between candidate variables
print("\n  Candidate variable correlations (top 5 pairs):")
corr_pairs = []
for i in range(n_candidates):
    for j in range(i+1, n_candidates):
        r = np.corrcoef(data[candidate_vars[i]].values,
                        data[candidate_vars[j]].values)[0, 1]
        corr_pairs.append((candidate_vars[i], candidate_vars[j], r))
corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)
for v1, v2, r in corr_pairs[:5]:
    print(f"    {v1:20s} × {v2:20s}: r={r:.4f}")

# ============================================================
# 4. GJR-GARCH(1,1) MLE ESTIMATION (FIXED BASE)
# ============================================================
print("\n[4] GJR-GARCH(1,1) MLE estimation (base model)...")

oos_start = pd.Timestamp('2023-01-01')
oos_end = pd.Timestamp('2024-12-31')
is_data = data[data.index < oos_start]
oos_data = data[(data.index >= oos_start) & (data.index <= oos_end)]

y_is = is_data['spy_ret'].values
y_oos = oos_data['spy_ret'].values
X_is = is_data[candidate_vars].values
X_oos = oos_data[candidate_vars].values

T_is = len(y_is)
T_oos = len(y_oos)
print(f"  In-sample: {T_is} obs ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {T_oos} obs ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")


def gjr_garch_loglik(params, returns):
    """Negative log-likelihood for GJR-GARCH(1,1).
    h_t = ω + α·ε²_{t-1} + γ·I(ε_{t-1}<0)·ε²_{t-1} + β·h_{t-1}
    """
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < -alpha or beta < 0:
        return 1e10
    if alpha + gamma/2 + beta >= 0.9999:
        return 1e10

    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        leverage = gamma * (returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + leverage + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll


def gjr_garch_filter(params, returns):
    """Filter conditional variance from GJR-GARCH(1,1)."""
    omega, alpha, gamma, beta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        leverage = gamma * (returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + leverage + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


# Fit GJR-GARCH on full in-sample
var_y = np.var(y_is)
x0_gjr = [var_y * 0.05, 0.05, 0.05, 0.88]
bounds_gjr = [(1e-8, var_y * 5), (1e-6, 0.5), (0.0, 0.5), (0.3, 0.9999)]

res_gjr = minimize(gjr_garch_loglik, x0_gjr, args=(y_is,),
                   method='L-BFGS-B', bounds=bounds_gjr)
gjr_params = res_gjr.x
omega_mle, alpha_mle, gamma_mle, beta_mle = gjr_params
persist = alpha_mle + gamma_mle/2 + beta_mle

print(f"  GJR-GARCH(1,1) MLE:")
print(f"    ω = {omega_mle:.6f}")
print(f"    α = {alpha_mle:.4f}")
print(f"    γ = {gamma_mle:.4f} (leverage)")
print(f"    β = {beta_mle:.4f}")
print(f"    Persistence = {persist:.4f}")
print(f"    Converged: {res_gjr.success}")

# Compute conditional variance series
h_is = gjr_garch_filter(gjr_params, y_is)

# ============================================================
# 5. SSVS GIBBS SAMPLER ON VARIANCE EQUATION RESIDUALS
# ============================================================
print("\n[5] SSVS Gibbs Sampler on variance equation...")
print("    Strategy: Fix GJR-GARCH params → extract z_t = r²_t - h_t(GARCH)")
print("    Then z_t = Σ δ_i·θ_i·X_{i,t-1} + η_t (linear regression with SSVS)")

# Construct pseudo-target: z_t = r²_t - h_t (what GARCH leaves unexplained)
# This is the variance residual that external variables might explain
z_is = y_is**2 - h_is  # residual variance to explain

# Lagged external variables: X_{i,t-1} for predicting z_t
# We need to align: z_t uses X from t-1
X_lagged_is = X_is[:-1]  # X_{t-1} for t = 1,...,T-1
z_target = z_is[1:]       # z_t for t = 1,...,T-1
T_reg = len(z_target)

print(f"    Regression sample: T = {T_reg}")
print(f"    z_t stats: mean={z_target.mean():.4f}, std={z_target.std():.4f}")
print(f"    X_lagged shape: {X_lagged_is.shape}")


def gibbs_ssvs_variance(z, X, n_iter=10000, n_burnin=2000,
                         c_spike=0.01, p_prior=0.5, verbose=True):
    """
    Gibbs Sampler for SSVS in variance equation residual regression.

    Model: z_t = Σ θ_j · X_{j,t-1} + η_t, η_t ~ N(0, σ²_η)

    SSVS prior (George & McCulloch 1993 / So, Chen, Liu 2006):
      δ_j ~ Bernoulli(p_prior)
      θ_j | δ_j=1 ~ N(0, τ_j²)        [slab — wide]
      θ_j | δ_j=0 ~ N(0, (c·τ_j)²)    [spike — tight, c=0.01]
      σ²_η ~ InverseGamma(a0/2, b0/2)

    All Gibbs steps are conjugate (closed-form).
    """
    T, K = X.shape

    # --- Prior calibration (τ from OLS standard errors) ---
    XtX = X.T @ X + np.eye(K) * 1e-8
    theta_ols = np.linalg.solve(XtX, X.T @ z)
    resid_ols = z - X @ theta_ols
    sigma2_ols = np.sum(resid_ols**2) / (T - K)
    se_ols = np.sqrt(np.abs(sigma2_ols * np.diag(np.linalg.inv(XtX))))

    # τ = 10 × SE_OLS (slab is wide), per So et al. (2006)
    tau = 10.0 * se_ols
    tau = np.maximum(tau, 1e-4)

    # Inverse-Gamma prior for σ²_η (diffuse)
    a0, b0 = 0.01, 0.01

    # --- Initialize ---
    theta = theta_ols.copy()
    sigma2 = sigma2_ols
    delta = np.ones(K)  # start all included

    # Storage
    n_save = n_iter - n_burnin
    theta_samples = np.zeros((n_save, K))
    delta_samples = np.zeros((n_save, K))
    sigma2_samples = np.zeros(n_save)

    # Precompute
    XtX_full = X.T @ X
    Xtz = X.T @ z

    for it in range(n_iter):
        # --- Step 1: Sample θ | δ, σ², z (multivariate normal) ---
        D2 = np.zeros(K)
        for j in range(K):
            if delta[j] == 1:
                D2[j] = tau[j]**2       # slab
            else:
                D2[j] = (c_spike * tau[j])**2  # spike

        D2_inv = 1.0 / np.maximum(D2, 1e-20)

        # Posterior: θ | rest ~ N(θ_post, Σ_post)
        Sigma_post_inv = XtX_full / sigma2 + np.diag(D2_inv)

        try:
            L = np.linalg.cholesky(Sigma_post_inv)
            theta_post = np.linalg.solve(Sigma_post_inv, Xtz / sigma2)
            z_rand = np.random.randn(K)
            theta = theta_post + np.linalg.solve(L.T, z_rand)
        except np.linalg.LinAlgError:
            eigvals, eigvecs = np.linalg.eigh(Sigma_post_inv)
            eigvals = np.maximum(eigvals, 1e-10)
            Sigma_post = eigvecs @ np.diag(1.0 / eigvals) @ eigvecs.T
            theta_post = Sigma_post @ (Xtz / sigma2)
            theta = np.random.multivariate_normal(theta_post, Sigma_post)

        # --- Step 2: Sample σ² | θ, z (inverse gamma) ---
        resid = z - X @ theta
        a_post = a0 + T
        b_post = b0 + np.sum(resid**2)
        sigma2 = 1.0 / np.random.gamma(a_post / 2, 2.0 / b_post)
        sigma2 = max(sigma2, 1e-10)

        # --- Step 3: Sample δ_j | θ_j (Bernoulli) ---
        for j in range(K):
            log_p1 = (np.log(p_prior + 1e-20)
                       - 0.5 * np.log(tau[j]**2 + 1e-20)
                       - 0.5 * theta[j]**2 / (tau[j]**2 + 1e-20))
            log_p0 = (np.log(1 - p_prior + 1e-20)
                       - 0.5 * np.log((c_spike * tau[j])**2 + 1e-20)
                       - 0.5 * theta[j]**2 / ((c_spike * tau[j])**2 + 1e-20))

            log_max = max(log_p1, log_p0)
            prob1 = np.exp(log_p1 - log_max) / (np.exp(log_p1 - log_max) +
                                                   np.exp(log_p0 - log_max))

            if not np.isfinite(prob1):
                prob1 = 0.5

            delta[j] = 1.0 if np.random.rand() < prob1 else 0.0

        # --- Store post-burn-in ---
        if it >= n_burnin:
            idx = it - n_burnin
            theta_samples[idx] = theta
            delta_samples[idx] = delta
            sigma2_samples[idx] = sigma2

        if verbose and it > 0 and it % 2000 == 0:
            pip_now = delta_samples[:max(1, it - n_burnin)].mean(axis=0) if it > n_burnin else delta.copy()
            print(f"      Iter {it:5d}/{n_iter} | "
                  f"σ²_η={sigma2:.4f} | "
                  f"PIP range: [{pip_now.min():.3f}, {pip_now.max():.3f}]")

    # --- Results ---
    pip = delta_samples.mean(axis=0)
    theta_mean = theta_samples.mean(axis=0)
    theta_std = theta_samples.std(axis=0)
    sigma2_mean = sigma2_samples.mean()

    # ESS for each parameter
    def compute_ess(chain):
        """Effective Sample Size from autocorrelation."""
        n = len(chain)
        if n < 10:
            return n
        mean = np.mean(chain)
        var = np.var(chain)
        if var < 1e-20:
            return n
        acf = np.correlate(chain - mean, chain - mean, mode='full')
        acf = acf[n-1:] / (var * n)
        # Find first negative autocorrelation
        cutoff = 1
        for k in range(1, min(n // 2, 500)):
            if acf[k] < 0:
                cutoff = k
                break
            cutoff = k
        return n / (1 + 2 * np.sum(acf[1:cutoff]))

    ess_theta = [compute_ess(theta_samples[:, j]) for j in range(K)]
    ess_delta = [compute_ess(delta_samples[:, j]) for j in range(K)]

    return {
        'pip': pip,
        'theta_mean': theta_mean,
        'theta_std': theta_std,
        'sigma2_mean': sigma2_mean,
        'theta_ols': theta_ols,
        'se_ols': se_ols,
        'tau': tau,
        'theta_samples': theta_samples,
        'delta_samples': delta_samples,
        'sigma2_samples': sigma2_samples,
        'ess_theta': ess_theta,
        'ess_delta': ess_delta,
    }


# Run full in-sample SSVS
print("\n  Running Gibbs sampler (10000 iter, 2000 burn-in)...")
ssvs_start = time.time()

ssvs_result = gibbs_ssvs_variance(
    z_target, X_lagged_is,
    n_iter=10000, n_burnin=2000,
    c_spike=0.01, p_prior=0.5, verbose=True
)

ssvs_time = time.time() - ssvs_start
print(f"\n  Gibbs sampler completed in {ssvs_time:.1f}s")

# Display PIP table
print("\n  Posterior Inclusion Probabilities (PIP):")
print(f"  {'Variable':20s} {'PIP':>8s} {'θ_mean':>10s} {'θ_std':>10s} "
      f"{'OLS_θ':>10s} {'ESS_θ':>8s} {'ESS_δ':>8s}")
print(f"  {'-'*76}")

pip_table = {}
for j, var in enumerate(candidate_vars):
    pip = ssvs_result['pip'][j]
    theta_m = ssvs_result['theta_mean'][j]
    theta_s = ssvs_result['theta_std'][j]
    ols_t = ssvs_result['theta_ols'][j]
    ess_t = ssvs_result['ess_theta'][j]
    ess_d = ssvs_result['ess_delta'][j]
    selected = "***" if pip > 0.9 else "**" if pip > 0.7 else "*" if pip > 0.5 else ""
    print(f"  {var:20s} {pip:8.4f} {theta_m:10.5f} {theta_s:10.5f} "
          f"{ols_t:10.5f} {ess_t:8.1f} {ess_d:8.1f} {selected}")

    # 95% credible interval
    theta_chain = ssvs_result['theta_samples'][:, j]
    ci_lo = np.percentile(theta_chain, 2.5)
    ci_hi = np.percentile(theta_chain, 97.5)

    pip_table[var] = {
        'PIP': float(pip),
        'theta_posterior_mean': float(theta_m),
        'theta_posterior_std': float(theta_s),
        'theta_95CI': [float(ci_lo), float(ci_hi)],
        'OLS_coef': float(ols_t),
        'OLS_se': float(ssvs_result['se_ols'][j]),
        'ESS_theta': float(ess_t),
        'ESS_delta': float(ess_d),
        'selected_median': bool(pip > 0.5),
    }

# Median probability model
median_model_vars = [v for v, info in pip_table.items() if info['PIP'] > 0.5]
print(f"\n  Median probability model ({len(median_model_vars)} vars): {median_model_vars}")
print(f"  σ²_η (noise): {ssvs_result['sigma2_mean']:.4f}")

# ============================================================
# 6. OUT-OF-SAMPLE EVALUATION (EXPANDING WINDOW, REFIT EVERY 126 DAYS)
# ============================================================
print("\n[6] Out-of-sample evaluation...")
print("    Expanding window, refit GJR-GARCH + SSVS every 126 days")

refit_interval = 126
oos_dates = oos_data.index

# Models to evaluate:
# 1. GJR-GARCH(1,1) baseline
# 2. GJR-GARCH-X with median probability model variables
# 3. GJR-GARCH-X with all variables (kitchen sink)
# 4. GJR-GARCH-X with only VIX_level (benchmark single variable)

def gjr_garchx_loglik(params, returns, X_ext):
    """Negative log-likelihood for GJR-GARCH-X(1,1) with external variables.
    h_t = ω + α·ε²_{t-1} + γ·I(ε_{t-1}<0)·ε²_{t-1} + β·h_{t-1} + Σ θ_i·X_{i,t-1}
    """
    n_ext = X_ext.shape[1]
    omega, alpha, gamma_l, beta = params[:4]
    thetas = params[4:]

    if omega <= 0 or alpha < 0 or gamma_l < -alpha or beta < 0:
        return 1e10
    if alpha + gamma_l/2 + beta >= 0.9999:
        return 1e10

    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        leverage = gamma_l * (returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + leverage + beta * h[t-1]
        # Add external variables (lagged: X_ext[t-1] for h_t)
        if t >= 1:
            for k in range(n_ext):
                h[t] += thetas[k] * X_ext[t-1, k]
        if h[t] < 1e-10:
            h[t] = 1e-10

    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll


def gjr_garchx_filter(params, returns, X_ext):
    """Filter conditional variance for GJR-GARCH-X."""
    n_ext = X_ext.shape[1]
    omega, alpha, gamma_l, beta = params[:4]
    thetas = params[4:]

    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        leverage = gamma_l * (returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + leverage + beta * h[t-1]
        if t >= 1:
            for k in range(n_ext):
                h[t] += thetas[k] * X_ext[t-1, k]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


def fit_gjr_garchx(returns, X_ext):
    """Fit GJR-GARCH-X model via MLE."""
    n_ext = X_ext.shape[1]
    var_r = np.var(returns)

    x0 = [var_r * 0.05, 0.05, 0.05, 0.88] + [0.0] * n_ext
    bounds = [(1e-8, var_r * 5), (1e-6, 0.5), (0.0, 0.5), (0.3, 0.9999)]
    bounds += [(-var_r * 2, var_r * 2)] * n_ext

    res = minimize(gjr_garchx_loglik, x0, args=(returns, X_ext),
                   method='L-BFGS-B', bounds=bounds)
    return res.x, res.success


# Prepare OOS arrays
all_dates = data.index
is_end_idx = data.index.get_loc(is_data.index[-1])

# We'll collect predictions for each model
predictions = {
    'GJR_baseline': [],
    'SSVS_median': [],
    'Kitchen_sink': [],
    'VIX_only': [],
}
actuals_r2 = []  # r²_t as proxy for σ²_t
oos_date_list = []

# Determine refit points
oos_indices = np.arange(T_oos)
refit_points = list(range(0, T_oos, refit_interval))
print(f"    OOS obs: {T_oos}, Refit points: {len(refit_points)}")

# Track which variables are selected at each refit
ssvs_selections = []

current_gjr_params = gjr_params.copy()
current_ssvs_vars = median_model_vars.copy()
current_garchx_params = None
current_ks_params = None
current_vix_params = None

for refit_idx, refit_start in enumerate(refit_points):
    refit_end = min(refit_start + refit_interval, T_oos)

    # Expanding window: all data up to current point
    expand_end_date = oos_data.index[refit_start]
    train_data = data[data.index < expand_end_date]

    y_train = train_data['spy_ret'].values
    X_train = train_data[candidate_vars].values

    print(f"\n    Refit {refit_idx+1}/{len(refit_points)}: "
          f"train={len(y_train)}, predict={refit_end - refit_start} obs")

    # --- (a) Fit GJR-GARCH baseline ---
    var_train = np.var(y_train)
    x0_base = [var_train * 0.05, 0.05, 0.05, 0.88]
    bounds_base = [(1e-8, var_train * 5), (1e-6, 0.5), (0.0, 0.5), (0.3, 0.9999)]

    res_base = minimize(gjr_garch_loglik, x0_base, args=(y_train,),
                        method='L-BFGS-B', bounds=bounds_base)
    current_gjr_params = res_base.x

    # --- (b) Run SSVS on variance residuals ---
    h_train = gjr_garch_filter(current_gjr_params, y_train)
    z_train = y_train**2 - h_train
    X_lag_train = X_train[:-1]
    z_tgt_train = z_train[1:]

    ssvs_refit = gibbs_ssvs_variance(
        z_tgt_train, X_lag_train,
        n_iter=5000, n_burnin=1000,  # fewer iterations for OOS refits
        c_spike=0.01, p_prior=0.5, verbose=False
    )

    current_ssvs_vars = [v for v, p in zip(candidate_vars, ssvs_refit['pip']) if p > 0.5]
    pip_str = ", ".join([f"{v}={p:.3f}" for v, p in zip(candidate_vars, ssvs_refit['pip'])])
    print(f"      SSVS selected: {current_ssvs_vars}")
    print(f"      PIPs: {pip_str}")

    ssvs_selections.append({
        'refit_date': expand_end_date.strftime('%Y-%m-%d'),
        'selected_vars': current_ssvs_vars,
        'pips': {v: float(p) for v, p in zip(candidate_vars, ssvs_refit['pip'])}
    })

    # --- (c) Fit GJR-GARCH-X models ---
    # Median model (SSVS selected)
    if len(current_ssvs_vars) > 0:
        ssvs_var_idx = [candidate_vars.index(v) for v in current_ssvs_vars]
        X_ssvs = X_train[:, ssvs_var_idx]
        current_garchx_params, _ = fit_gjr_garchx(y_train, X_ssvs)

    # Kitchen sink (all 8 variables)
    current_ks_params, _ = fit_gjr_garchx(y_train, X_train)

    # VIX-only benchmark
    vix_idx = candidate_vars.index('VIX_level')
    X_vix_only = X_train[:, [vix_idx]]
    current_vix_params, _ = fit_gjr_garchx(y_train, X_vix_only)

    # --- (d) Forecast OOS segment ---
    for t_oos in range(refit_start, refit_end):
        oos_date = oos_data.index[t_oos]
        r_t = oos_data['spy_ret'].iloc[t_oos]
        actuals_r2.append(r_t**2)
        oos_date_list.append(oos_date)

        # For prediction, we need all history up to t-1
        # Use expanding data up to oos_date
        hist_data = data[data.index <= oos_date]
        y_hist = hist_data['spy_ret'].values
        X_hist = hist_data[candidate_vars].values

        # 1. GJR baseline: filter full history
        h_base = gjr_garch_filter(current_gjr_params, y_hist)
        predictions['GJR_baseline'].append(h_base[-1])

        # 2. SSVS median model
        if len(current_ssvs_vars) > 0:
            ssvs_var_idx = [candidate_vars.index(v) for v in current_ssvs_vars]
            X_ssvs_hist = X_hist[:, ssvs_var_idx]
            h_ssvs = gjr_garchx_filter(current_garchx_params, y_hist, X_ssvs_hist)
            predictions['SSVS_median'].append(h_ssvs[-1])
        else:
            predictions['SSVS_median'].append(h_base[-1])

        # 3. Kitchen sink
        h_ks = gjr_garchx_filter(current_ks_params, y_hist, X_hist)
        predictions['Kitchen_sink'].append(h_ks[-1])

        # 4. VIX only
        X_vix_hist = X_hist[:, [vix_idx]]
        h_vix = gjr_garchx_filter(current_vix_params, y_hist, X_vix_hist)
        predictions['VIX_only'].append(h_vix[-1])

print("\n  OOS predictions complete.")

# ============================================================
# 7. EVALUATION METRICS
# ============================================================
print("\n[7] Evaluation metrics...")

actuals_r2 = np.array(actuals_r2)
for k in predictions:
    predictions[k] = np.array(predictions[k])
    # Floor predictions at small positive value
    predictions[k] = np.maximum(predictions[k], 1e-8)

def qlike(actual, predicted):
    """QLIKE loss (Patton 2011 — proxy-robust when actual = r²).
    Floor both at 1e-8 to avoid log(0) and division by zero.
    """
    a = np.maximum(actual, 1e-8)
    p = np.maximum(predicted, 1e-8)
    return np.mean(a / p - np.log(a / p) - 1)

def mse(actual, predicted):
    """Mean Squared Error."""
    return np.mean((actual - predicted)**2)

def mae(actual, predicted):
    """Mean Absolute Error."""
    return np.mean(np.abs(actual - predicted))

# Compute metrics
print(f"\n  {'Model':25s} {'QLIKE':>10s} {'MSE':>12s} {'MAE':>10s} {'QLIKE_Δ%':>10s}")
print(f"  {'-'*70}")

baseline_qlike = qlike(actuals_r2, predictions['GJR_baseline'])
oos_results = {}

for model_name in ['GJR_baseline', 'SSVS_median', 'Kitchen_sink', 'VIX_only']:
    q = qlike(actuals_r2, predictions[model_name])
    m = mse(actuals_r2, predictions[model_name])
    a = mae(actuals_r2, predictions[model_name])
    pct_diff = (q - baseline_qlike) / baseline_qlike * 100

    print(f"  {model_name:25s} {q:10.4f} {m:12.4f} {a:10.4f} {pct_diff:+10.2f}%")

    oos_results[model_name] = {
        'QLIKE': float(q),
        'MSE': float(m),
        'MAE': float(a),
        'relative_QLIKE_pct': float(pct_diff),
    }

# ============================================================
# 8. DM TESTS (vs GJR baseline)
# ============================================================
print("\n[8] Diebold-Mariano tests (vs GJR baseline)...")

def dm_test(actual, pred1, pred2, loss='QLIKE'):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    pred1 = baseline, pred2 = challenger.
    Negative DM stat → challenger is better.
    """
    a = np.maximum(actual, 1e-8)
    p1 = np.maximum(pred1, 1e-8)
    p2 = np.maximum(pred2, 1e-8)
    if loss == 'QLIKE':
        d1 = a / p1 - np.log(a / p1) - 1
        d2 = a / p2 - np.log(a / p2) - 1
    else:
        d1 = (a - p1)**2
        d2 = (a - p2)**2

    d = d1 - d2
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC standard error (10 lags)
    max_lag = min(10, n // 5)
    gamma_0 = np.var(d, ddof=0)
    nw_var = gamma_0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_lag = np.mean((d[:n-lag] - d_mean) * (d[lag:] - d_mean))
        nw_var += 2 * w * gamma_lag

    se = np.sqrt(nw_var / n)
    if se < 1e-10:
        return np.nan, np.nan

    dm_stat = d_mean / se
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

print(f"\n  {'Model':25s} {'DM_stat':>10s} {'p-value':>10s} {'|t|>3.0':>10s} {'Interpretation':>20s}")
print(f"  {'-'*80}")

dm_results = {}
for model_name in ['SSVS_median', 'Kitchen_sink', 'VIX_only']:
    dm_stat, dm_p = dm_test(actuals_r2, predictions['GJR_baseline'],
                             predictions[model_name], loss='QLIKE')

    significant = abs(dm_stat) > 3.0 if not np.isnan(dm_stat) else False
    # Positive DM stat = baseline loss > challenger loss = challenger BETTER
    if dm_stat > 0:
        interp = "BETTER*" if significant else "better (NS)"
    else:
        interp = "WORSE*" if significant else "worse (NS)"

    print(f"  {model_name:25s} {dm_stat:10.4f} {dm_p:10.6f} "
          f"{'YES' if significant else 'no':>10s} {interp:>20s}")

    dm_results[model_name] = {
        'dm_stat': float(dm_stat) if not np.isnan(dm_stat) else None,
        'p_value': float(dm_p) if not np.isnan(dm_p) else None,
        'significant_harvey': bool(significant),
        'interpretation': interp,
    }

# ============================================================
# 9. SPEARMAN RANK CORRELATION
# ============================================================
print("\n[9] Spearman rank correlation with r²...")

spearman_results = {}
for model_name in ['GJR_baseline', 'SSVS_median', 'Kitchen_sink', 'VIX_only']:
    rho, p_val = sp_stats.spearmanr(actuals_r2, predictions[model_name])
    print(f"  {model_name:25s}: ρ = {rho:.4f} (p = {p_val:.6f})")
    spearman_results[model_name] = {
        'rho': float(rho),
        'p_value': float(p_val),
    }

# ============================================================
# 10. COMPARISON WITH K484 (INTERNAL COMPONENTS)
# ============================================================
print("\n[10] Comparison with K484 (internal components SSVS)...")
print("  K484 used internal GARCH extensions: GJR, VIX_implied, Parkinson, Semivar, Abs_shock")
print("  K484 result: 4/5 PIP=1.000, QLIKE -7.43% vs GARCH(1,1)")
print(f"  K821 uses external market variables: {candidate_vars}")
print(f"  K821 SSVS median model: {median_model_vars}")
print(f"  K821 SSVS QLIKE change: {oos_results['SSVS_median']['relative_QLIKE_pct']:+.2f}%")

k484_qlike_improvement = -7.43
k821_qlike_improvement = oos_results['SSVS_median']['relative_QLIKE_pct']

print(f"\n  K484 internal SSVS: QLIKE {k484_qlike_improvement:+.2f}%")
print(f"  K821 external SSVS: QLIKE {k821_qlike_improvement:+.2f}%")

if abs(k821_qlike_improvement) > abs(k484_qlike_improvement):
    comparison = "External variables MORE informative than internal components"
elif abs(k821_qlike_improvement) > 1.0:
    comparison = "External variables moderately informative, but less than internal"
else:
    comparison = "External variables add little beyond GJR-GARCH (internal structure dominates)"

print(f"  Interpretation: {comparison}")

# ============================================================
# 11. SSVS SELECTION STABILITY ACROSS REFITS
# ============================================================
print("\n[11] SSVS selection stability across OOS refits...")

# Count how often each variable is selected
selection_counts = {v: 0 for v in candidate_vars}
n_refits = len(ssvs_selections)
for sel in ssvs_selections:
    for v in sel['selected_vars']:
        selection_counts[v] += 1

print(f"  {'Variable':20s} {'Selected':>10s} {'%':>8s}")
print(f"  {'-'*40}")
for v in candidate_vars:
    pct = selection_counts[v] / n_refits * 100 if n_refits > 0 else 0
    print(f"  {v:20s} {selection_counts[v]:10d}/{n_refits} {pct:7.1f}%")

# Average PIP across refits
avg_pips = {v: 0.0 for v in candidate_vars}
for sel in ssvs_selections:
    for v, p in sel['pips'].items():
        avg_pips[v] += p
for v in avg_pips:
    avg_pips[v] /= max(n_refits, 1)

print(f"\n  Average PIPs across refits:")
for v in candidate_vars:
    print(f"    {v:20s}: avg_PIP = {avg_pips[v]:.4f}")

# ============================================================
# 12. SAVE RESULTS
# ============================================================
total_time = time.time() - start_time
print(f"\n[12] Saving results... (total time: {total_time:.1f}s)")

results = {
    "experiment_id": "K821",
    "title": "Bayesian SSVS for ARX-GARCH Variance Equation (External Variables)",
    "method": "SSVS (So, Chen, Liu 2006) applied to GJR-GARCH variance equation with external market variables",
    "innovation": "K484 tested internal GARCH components (GJR, VIX, Parkinson etc). K821 tests external market variables: VIX level/change, VIX9D, VVIX_proxy, TLT_vol, HYG_spread, term_spread, volume_ratio",
    "proposed_by": "User (K433 direction: SSVS on variance equation)",
    "executed_by": "Claude",
    "asset": "SPY",
    "data_source": "yfinance (empirical)",
    "data_period": f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    "vix9d_available": has_vix9d,
    "sample_split": {
        "total": len(data),
        "in_sample": T_is,
        "oos": T_oos,
        "oos_period": f"{oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')}",
    },
    "variance_equation_spec": {
        "base": "σ²_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·σ²_{t-1}",
        "augmented": "σ²_t = base + Σ δ_i·θ_i·X_{i,t-1}",
        "external_candidates": candidate_vars,
        "n_candidates": n_candidates,
        "n_possible_models": 2**n_candidates,
    },
    "gjr_garch_mle": {
        "omega": float(omega_mle),
        "alpha": float(alpha_mle),
        "gamma": float(gamma_mle),
        "beta": float(beta_mle),
        "persistence": float(persist),
    },
    "mcmc_settings": {
        "sampler": "Gibbs (conjugate for linear regression on variance residuals)",
        "total_iterations": 10000,
        "burn_in": 2000,
        "effective_samples": 8000,
        "c_spike": 0.01,
        "prior_inclusion_prob": 0.5,
        "tau_calibration": "10 × OLS SE (So et al. 2006)",
        "oos_refit_iterations": 5000,
        "oos_refit_burnin": 1000,
        "oos_refit_interval": refit_interval,
    },
    "in_sample_pip": pip_table,
    "in_sample_median_model_vars": median_model_vars,
    "oos_evaluation": oos_results,
    "dm_tests": dm_results,
    "spearman_rank_correlation": spearman_results,
    "ssvs_oos_selections": ssvs_selections,
    "selection_stability": {
        "selection_counts": selection_counts,
        "n_refits": n_refits,
        "average_pips": avg_pips,
    },
    "comparison_with_k484": {
        "k484_qlike_improvement": k484_qlike_improvement,
        "k821_qlike_improvement": k821_qlike_improvement,
        "interpretation": comparison,
    },
    "diagnostics": {
        "spy_returns": {
            "mean": float(np.mean(y_all)),
            "std": float(np.std(y_all)),
            "skewness": float(pd.Series(y_all).skew()),
            "kurtosis": float(pd.Series(y_all).kurtosis()),
            "N": len(y_all),
        },
        "adf_test": {"stat": float(adf_stat), "p_value": float(adf_pval)},
        "arch_lm_test": {"stat": float(arch_lm[0]), "p_value": float(arch_lm[1])},
        "ljung_box_r2": {"stat": float(lb_sq['lb_stat'].values[0]),
                         "p_value": float(lb_sq['lb_pvalue'].values[0])},
        "ssvs_time_seconds": ssvs_time,
        "total_time_seconds": total_time,
        "ess_diagnostics": {
            v: {"ESS_theta": float(ssvs_result['ess_theta'][j]),
                "ESS_delta": float(ssvs_result['ess_delta'][j])}
            for j, v in enumerate(candidate_vars)
        },
    },
    "conclusion": {
        "strong_pip_vars": [v for v, info in pip_table.items() if info['PIP'] > 0.9],
        "moderate_pip_vars": [v for v, info in pip_table.items() if 0.5 < info['PIP'] <= 0.9],
        "weak_pip_vars": [v for v, info in pip_table.items() if info['PIP'] <= 0.5],
        "median_model": median_model_vars,
        "best_oos_model": min(oos_results, key=lambda k: oos_results[k]['QLIKE']),
        "interpretation": "",  # filled below
    },
    "references": [
        "So, Chen, Liu (2006) Best Subset Selection of ARX-GARCH, JRSS-C 55(2):201-224",
        "George & McCulloch (1993) Variable Selection via Gibbs Sampling, JASA 88:881-889",
        "Patton (2011) Volatility forecast comparison using imperfect proxies, JoE",
        "Harvey et al. (2016) Testing the accuracy of volatility forecasts, t>3.0 threshold",
        "K484: SSVS internal components → 4/5 PIP=1.000, QLIKE -7.43%",
        "K818: SSVS return prediction → null for SPY",
        "K433: SSVS mean equation → null for SPY",
        "K461: SSVS Taiwan → SPY_ret PIP=1.000 in mean equation",
    ],
}

# Generate interpretation
strong = results['conclusion']['strong_pip_vars']
moderate = results['conclusion']['moderate_pip_vars']
weak = results['conclusion']['weak_pip_vars']
best_model = results['conclusion']['best_oos_model']
best_qlike = oos_results[best_model]['QLIKE']

interpretation_parts = []
if len(strong) > 0:
    interpretation_parts.append(f"Strong evidence ({', '.join(strong)}) for inclusion in variance equation.")
else:
    interpretation_parts.append("No external variable has strong PIP (>0.9).")

if len(moderate) > 0:
    interpretation_parts.append(f"Moderate evidence for {', '.join(moderate)}.")

if abs(k821_qlike_improvement) > 3.0:
    interpretation_parts.append(f"SSVS median model achieves meaningful QLIKE improvement ({k821_qlike_improvement:+.2f}%).")
elif abs(k821_qlike_improvement) > 1.0:
    interpretation_parts.append(f"SSVS median model achieves modest QLIKE change ({k821_qlike_improvement:+.2f}%).")
else:
    interpretation_parts.append(f"External variables provide negligible OOS improvement ({k821_qlike_improvement:+.2f}%), consistent with VIX sufficiency hypothesis.")

interpretation_parts.append(comparison)
interpretation_parts.append(f"Best OOS model: {best_model} (QLIKE={best_qlike:.4f}).")

results['conclusion']['interpretation'] = " ".join(interpretation_parts)

# Save
output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k821_ssvs_variance_equation_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K821 FINAL SUMMARY")
print("=" * 70)
print(f"\n  Method: SSVS on GJR-GARCH variance equation with 8 external variables")
print(f"  Asset: SPY | OOS: {oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')}")
print(f"\n  PIP Ranking:")
pip_sorted = sorted(pip_table.items(), key=lambda x: x[1]['PIP'], reverse=True)
for rank, (v, info) in enumerate(pip_sorted, 1):
    marker = "***" if info['PIP'] > 0.9 else "**" if info['PIP'] > 0.7 else "*" if info['PIP'] > 0.5 else ""
    print(f"    {rank}. {v:20s} PIP={info['PIP']:.4f} {marker}")

print(f"\n  Median Probability Model: {median_model_vars}")
print(f"  QLIKE improvement: {k821_qlike_improvement:+.2f}% (K484 internal: {k484_qlike_improvement:+.2f}%)")
print(f"  Best OOS model: {best_model}")
print(f"\n  {results['conclusion']['interpretation']}")
print(f"\n  Total time: {total_time:.1f}s")
print("=" * 70)
