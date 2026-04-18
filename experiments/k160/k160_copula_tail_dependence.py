"""
K160: Copula-based Tail Dependence for Portfolio Risk
=====================================================
[提出: User, 執行: Claude]

Research Question:
  Do copula models (Clayton, Gumbel, t-copula) reveal significant tail
  dependence in the SPY-GLD-TLT-EEM portfolio that standard Pearson/DCC
  correlation misses? Does this matter for portfolio VaR?

Method:
  1. Assets: SPY, GLD, TLT, EEM (core portfolio)
  2. GJR-GARCH to filter each asset -> standardized residuals -> PIT to uniform
  3. Fit copula models to pairs:
     - Gaussian copula (benchmark, no tail dependence)
     - Student-t copula (symmetric tail dependence)
     - Clayton copula (lower tail dependence - crashes)
     - Gumbel copula (upper tail dependence)
  4. Measure tail dependence coefficients (empirical + parametric)
  5. Monte Carlo VaR from each copula vs historical VaR
  6. Rolling window: 2000 days estimation, OOS 2023-2024
  7. Bootstrap CIs for tail dependence coefficients (1000 reps)

Usage:
    uv run python experiments/k160_copula_tail_dependence.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats, special
from scipy.optimize import minimize, minimize_scalar
from arch import arch_model

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ======================================================================
# CONFIG
# ======================================================================
ASSETS = ["SPY", "GLD", "TLT", "EEM"]
DATA_START = "2005-01-01"
DATA_END = "2024-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
GARCH_WINDOW = 2000
N_BOOTSTRAP = 1000
MC_SIMULATIONS = 10000
VAR_LEVEL = 0.05  # 5% VaR
PORTFOLIO_WEIGHTS = np.array([0.25, 0.25, 0.25, 0.25])  # equal-weight
TAIL_THRESHOLDS = [0.05, 0.10]  # for empirical tail dependence

np.random.seed(42)

print("=" * 80)
print("K160: COPULA-BASED TAIL DEPENDENCE FOR PORTFOLIO RISK")
print("=" * 80)
print(f"  [提出: User, 執行: Claude]")
print(f"  Assets:       {ASSETS}")
print(f"  OOS:          {OOS_START} to {OOS_END}")
print(f"  GARCH window: {GARCH_WINDOW}")
print(f"  Bootstrap:    {N_BOOTSTRAP} reps")
print(f"  MC sims:      {MC_SIMULATIONS}")
print(f"  VaR level:    {VAR_LEVEL}")
print()

# ======================================================================
# DATA LOADING
# ======================================================================
print("[1] Loading data via yfinance...")
t0 = time.time()

import yfinance as yf

prices = {}
for asset in ASSETS:
    ticker = yf.Ticker(asset)
    df = ticker.history(start=DATA_START, end=DATA_END, auto_adjust=True)
    prices[asset] = df["Close"].dropna()
    print(f"    {asset}: {len(prices[asset])} days ({prices[asset].index[0].strftime('%Y-%m-%d')} to {prices[asset].index[-1].strftime('%Y-%m-%d')})")

# Align dates
price_df = pd.DataFrame(prices)
price_df = price_df.dropna()
returns_df = np.log(price_df / price_df.shift(1)).dropna() * 100  # percentage returns
print(f"    Aligned: {len(returns_df)} days")
print(f"    Data loaded in {time.time()-t0:.1f}s")
print()

# ======================================================================
# GJR-GARCH FILTERING
# ======================================================================
print("[2] Fitting GJR-GARCH and extracting standardized residuals...")

def fit_gjr_garch(returns: pd.Series, window: int = GARCH_WINDOW):
    """Fit GJR-GARCH(1,1) and return standardized residuals + conditional vol."""
    am = arch_model(returns, vol="Garch", p=1, o=1, q=1, dist="t", mean="Constant")
    res = am.fit(disp="off", last_obs=len(returns))
    std_resid = res.std_resid
    cond_vol = res.conditional_volatility
    return std_resid, cond_vol, res

garch_results = {}
std_resids = {}
cond_vols = {}

for asset in ASSETS:
    ret = returns_df[asset]
    std_r, cvol, res = fit_gjr_garch(ret)
    garch_results[asset] = res
    std_resids[asset] = std_r
    cond_vols[asset] = cvol
    params = res.params
    gamma = params.get("gamma[1]", params.get("o[1]", 0))
    print(f"    {asset}: omega={params.get('omega', 0):.4f}, alpha={params.get('alpha[1]', 0):.4f}, "
          f"gamma={gamma:.4f}, beta={params.get('beta[1]', 0):.4f}")

print()

# ======================================================================
# PIT TRANSFORMATION TO UNIFORM MARGINS
# ======================================================================
print("[3] PIT transformation to uniform margins...")

def pit_transform(std_resid: pd.Series, df_t: float = 5.0) -> pd.Series:
    """Probability integral transform using Student-t CDF."""
    u = stats.t.cdf(std_resid, df=df_t)
    # Clip to avoid boundary issues
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return pd.Series(u, index=std_resid.index)

uniform_margins = {}
for asset in ASSETS:
    # Get degrees of freedom from GARCH fit
    try:
        nu = garch_results[asset].params.get("nu", 5.0)
    except:
        nu = 5.0
    uniform_margins[asset] = pit_transform(std_resids[asset], df_t=nu)

# Align to OOS period
oos_mask = (returns_df.index >= OOS_START) & (returns_df.index <= OOS_END)
oos_returns = returns_df[oos_mask]
pre_oos_mask = returns_df.index < OOS_START
n_oos = oos_mask.sum()
print(f"    OOS period: {n_oos} days")

# For copula fitting, use the pre-OOS data (last GARCH_WINDOW days before OOS)
fit_end_idx = returns_df.index.get_loc(oos_returns.index[0])
fit_start_idx = max(0, fit_end_idx - GARCH_WINDOW)
fit_mask = np.zeros(len(returns_df), dtype=bool)
fit_mask[fit_start_idx:fit_end_idx] = True

uniform_fit = {}
uniform_oos = {}
for asset in ASSETS:
    u = uniform_margins[asset]
    uniform_fit[asset] = u.iloc[fit_start_idx:fit_end_idx].values
    uniform_oos[asset] = u[oos_mask].values

print(f"    Fit window: {sum(fit_mask)} days (pre-OOS)")
print(f"    OOS window: {n_oos} days")
print()

# ======================================================================
# COPULA IMPLEMENTATIONS
# ======================================================================

def gaussian_copula_nll(rho, u1, u2):
    """Negative log-likelihood for bivariate Gaussian copula."""
    z1 = stats.norm.ppf(u1)
    z2 = stats.norm.ppf(u2)
    n = len(u1)
    if abs(rho) >= 0.999:
        return 1e10
    det = 1 - rho**2
    nll = 0.5 * n * np.log(det) + 0.5 * np.sum(
        (rho**2 * (z1**2 + z2**2) - 2 * rho * z1 * z2) / det
    )
    return nll


def fit_gaussian_copula(u1, u2):
    """Fit Gaussian copula, return rho."""
    result = minimize_scalar(
        lambda rho: gaussian_copula_nll(rho, u1, u2),
        bounds=(-0.99, 0.99), method="bounded"
    )
    return {"rho": result.x, "nll": result.fun, "type": "gaussian"}


def t_copula_nll(params, u1, u2):
    """Negative log-likelihood for bivariate Student-t copula."""
    rho, nu = params
    if abs(rho) >= 0.999 or nu <= 2.01 or nu > 50:
        return 1e10
    t1 = stats.t.ppf(u1, df=nu)
    t2 = stats.t.ppf(u2, df=nu)
    n = len(u1)
    det = 1 - rho**2

    # Bivariate t density / product of marginal t densities
    nll = 0.0
    for i in range(n):
        x = np.array([t1[i], t2[i]])
        # log of bivariate t density
        Sigma_inv = np.array([[1, -rho], [-rho, 1]]) / det
        quad = x @ Sigma_inv @ x
        log_joint = (
            special.gammaln((nu + 2) / 2) - special.gammaln(nu / 2)
            - np.log(nu * np.pi) - 0.5 * np.log(det)
            - ((nu + 2) / 2) * np.log(1 + quad / nu)
        )
        # log of marginal t densities
        log_marg1 = stats.t.logpdf(t1[i], df=nu)
        log_marg2 = stats.t.logpdf(t2[i], df=nu)
        nll -= (log_joint - log_marg1 - log_marg2)
    return nll


def t_copula_nll_vectorized(params, u1, u2):
    """Vectorized NLL for bivariate Student-t copula."""
    rho, nu = params
    if abs(rho) >= 0.999 or nu <= 2.01 or nu > 50:
        return 1e10
    t1 = stats.t.ppf(u1, df=nu)
    t2 = stats.t.ppf(u2, df=nu)
    n = len(u1)
    det = 1 - rho**2

    # Quadratic form: (1/(1-rho^2)) * (t1^2 - 2*rho*t1*t2 + t2^2)
    quad = (t1**2 - 2 * rho * t1 * t2 + t2**2) / det

    log_joint = (
        special.gammaln((nu + 2) / 2) - special.gammaln(nu / 2)
        - np.log(nu * np.pi) - 0.5 * np.log(det)
        - ((nu + 2) / 2) * np.log(1 + quad / nu)
    )
    log_marg1 = stats.t.logpdf(t1, df=nu)
    log_marg2 = stats.t.logpdf(t2, df=nu)
    nll = -np.sum(log_joint - log_marg1 - log_marg2)
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_t_copula(u1, u2):
    """Fit bivariate Student-t copula, return rho, nu."""
    # Initial guess: sample correlation, nu=5
    z1 = stats.norm.ppf(u1)
    z2 = stats.norm.ppf(u2)
    rho0 = np.corrcoef(z1, z2)[0, 1]

    best = {"nll": 1e10}
    for nu0 in [4, 6, 10, 15]:
        try:
            result = minimize(
                t_copula_nll_vectorized, [rho0, nu0], args=(u1, u2),
                method="Nelder-Mead",
                options={"maxiter": 5000, "xatol": 1e-6, "fatol": 1e-6}
            )
            if result.fun < best["nll"]:
                best = {"rho": result.x[0], "nu": result.x[1], "nll": result.fun}
        except:
            pass
    best["type"] = "t"
    return best


def clayton_copula_logpdf(theta, u1, u2):
    """Log-density of Clayton copula."""
    if theta <= 0.01:
        return -1e10 * np.ones(len(u1))
    # C(u,v) = (u^(-theta) + v^(-theta) - 1)^(-1/theta)
    # c(u,v) = (1+theta) * (u*v)^(-theta-1) * (u^(-theta)+v^(-theta)-1)^(-1/theta-2)
    u1_t = u1**(-theta)
    u2_t = u2**(-theta)
    A = u1_t + u2_t - 1.0
    # Avoid numerical issues
    A = np.maximum(A, 1e-300)
    log_c = (
        np.log(1 + theta)
        + (-theta - 1) * (np.log(u1) + np.log(u2))
        + (-1.0/theta - 2) * np.log(A)
    )
    return log_c


def clayton_copula_nll(theta, u1, u2):
    """Negative log-likelihood for Clayton copula."""
    if theta <= 0.01 or theta > 50:
        return 1e10
    log_c = clayton_copula_logpdf(theta, u1, u2)
    nll = -np.sum(log_c)
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_clayton_copula(u1, u2):
    """Fit Clayton copula, return theta."""
    result = minimize_scalar(
        lambda theta: clayton_copula_nll(theta, u1, u2),
        bounds=(0.02, 30), method="bounded"
    )
    return {"theta": result.x, "nll": result.fun, "type": "clayton"}


def gumbel_copula_logpdf(theta, u1, u2):
    """Log-density of Gumbel copula."""
    if theta < 1.001:
        return -1e10 * np.ones(len(u1))
    # Let s = (-log u1)^theta + (-log u2)^theta
    # C(u,v) = exp(-s^(1/theta))
    log_u1 = -np.log(u1)
    log_u2 = -np.log(u2)
    log_u1_t = log_u1**theta
    log_u2_t = log_u2**theta
    s = log_u1_t + log_u2_t
    s = np.maximum(s, 1e-300)
    s_inv = s**(1.0/theta)

    # c(u,v) = C(u,v) * (1/(u*v)) * (log_u1 * log_u2)^(theta-1) / s^(2-1/theta)
    #          * (s^(1/theta) + theta - 1)
    log_c = (
        -s_inv
        + (theta - 1) * (np.log(log_u1) + np.log(log_u2))
        - np.log(u1) - np.log(u2)
        + (1.0/theta - 2) * np.log(s)
        + np.log(s_inv + theta - 1)
    )
    return log_c


def gumbel_copula_nll(theta, u1, u2):
    """Negative log-likelihood for Gumbel copula."""
    if theta < 1.001 or theta > 50:
        return 1e10
    log_c = gumbel_copula_logpdf(theta, u1, u2)
    nll = -np.sum(log_c)
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_gumbel_copula(u1, u2):
    """Fit Gumbel copula, return theta."""
    result = minimize_scalar(
        lambda theta: gumbel_copula_nll(theta, u1, u2),
        bounds=(1.01, 20), method="bounded"
    )
    return {"theta": result.x, "nll": result.fun, "type": "gumbel"}


# ======================================================================
# TAIL DEPENDENCE COEFFICIENTS
# ======================================================================

def empirical_tail_dependence(u1, u2, threshold=0.05):
    """
    Empirical lower and upper tail dependence.
    lambda_L = P(U2 <= u | U1 <= u) for small u
    lambda_U = P(U2 > 1-u | U1 > 1-u) for small u
    """
    n = len(u1)
    # Lower tail
    lower_mask = u1 <= threshold
    n_lower = np.sum(lower_mask)
    if n_lower > 0:
        lambda_L = np.mean(u2[lower_mask] <= threshold)
    else:
        lambda_L = 0.0

    # Upper tail
    upper_mask = u1 >= (1 - threshold)
    n_upper = np.sum(upper_mask)
    if n_upper > 0:
        lambda_U = np.mean(u2[upper_mask] >= (1 - threshold))
    else:
        lambda_U = 0.0

    return lambda_L, lambda_U, n_lower, n_upper


def parametric_tail_dependence(copula_fit):
    """Compute parametric tail dependence from fitted copula parameters."""
    ctype = copula_fit["type"]
    if ctype == "gaussian":
        # Gaussian copula: lambda_L = lambda_U = 0 (asymptotically)
        return 0.0, 0.0
    elif ctype == "t":
        # Student-t copula: symmetric tail dependence
        rho = copula_fit["rho"]
        nu = copula_fit["nu"]
        if nu <= 2:
            return 0.0, 0.0
        # lambda = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))
        arg = -np.sqrt((nu + 1) * (1 - rho) / (1 + rho))
        lam = 2 * stats.t.cdf(arg, df=nu + 1)
        return lam, lam  # symmetric
    elif ctype == "clayton":
        theta = copula_fit["theta"]
        # Clayton: lambda_L = 2^(-1/theta), lambda_U = 0
        lambda_L = 2**(-1.0/theta)
        return lambda_L, 0.0
    elif ctype == "gumbel":
        theta = copula_fit["theta"]
        # Gumbel: lambda_L = 0, lambda_U = 2 - 2^(1/theta)
        lambda_U = 2 - 2**(1.0/theta)
        return 0.0, lambda_U
    return 0.0, 0.0


def bootstrap_tail_dependence(u1, u2, threshold=0.05, n_bootstrap=N_BOOTSTRAP):
    """Bootstrap CIs for empirical tail dependence."""
    n = len(u1)
    lam_L_boot = np.zeros(n_bootstrap)
    lam_U_boot = np.zeros(n_bootstrap)
    for b in range(n_bootstrap):
        idx = np.random.choice(n, n, replace=True)
        lL, lU, _, _ = empirical_tail_dependence(u1[idx], u2[idx], threshold)
        lam_L_boot[b] = lL
        lam_U_boot[b] = lU
    return lam_L_boot, lam_U_boot


# ======================================================================
# COPULA SIMULATION FOR VaR
# ======================================================================

def simulate_gaussian_copula(rho, n_sim):
    """Simulate from bivariate Gaussian copula."""
    cov = np.array([[1, rho], [rho, 1]])
    z = np.random.multivariate_normal([0, 0], cov, n_sim)
    u = stats.norm.cdf(z)
    return u


def simulate_t_copula(rho, nu, n_sim):
    """Simulate from bivariate Student-t copula."""
    cov = np.array([[1, rho], [rho, 1]])
    z = np.random.multivariate_normal([0, 0], cov, n_sim)
    chi2 = np.random.chisquare(nu, n_sim) / nu
    t = z / np.sqrt(chi2[:, None])
    u = stats.t.cdf(t, df=nu)
    return u


def simulate_clayton_copula(theta, n_sim):
    """Simulate from Clayton copula using conditional method."""
    u1 = np.random.uniform(0, 1, n_sim)
    t = np.random.uniform(0, 1, n_sim)
    # Conditional: u2 = (t^(-theta/(1+theta)) * u1^(-theta) - u1^(-theta) + 1)^(-1/theta)
    # Using the inverse conditional CDF
    u2 = (u1**(-theta) * (t**(-theta/(1+theta)) - 1) + 1)**(-1.0/theta)
    u2 = np.clip(u2, 1e-6, 1-1e-6)
    return np.column_stack([u1, u2])


def simulate_gumbel_copula(theta, n_sim):
    """Simulate from Gumbel copula using Marshall-Olkin method with stable distribution."""
    # Generate stable random variable with alpha=1/theta, beta=1
    # Use Chambers-Mallows-Stuck method
    alpha = 1.0 / theta
    if abs(alpha - 1.0) < 0.01:
        # Near Gaussian, just use Gaussian copula
        return simulate_gaussian_copula(0.5, n_sim)

    # Generate stable(alpha, 1, cos(pi*alpha/2)^(1/alpha), 0; 1) parameterization
    V = np.random.uniform(-np.pi/2, np.pi/2, n_sim)
    W = np.random.exponential(1, n_sim)

    # Stable(alpha, beta=1) using CMS method
    if alpha != 1:
        B = np.arctan(np.tan(np.pi * alpha / 2))
        S = (1 + np.tan(np.pi * alpha / 2)**2)**(1.0/(2*alpha))
        stable = S * np.sin(alpha * (V + B)) / (np.cos(V)**(1.0/alpha)) * \
                 (np.cos(V - alpha * (V + B)) / W)**((1-alpha)/alpha)
    else:
        stable = np.ones(n_sim)

    # Generate exponential variables
    E1 = np.random.exponential(1, n_sim)
    E2 = np.random.exponential(1, n_sim)

    # Transform
    u1 = np.exp(-(E1 / stable)**(1.0/theta))
    u2 = np.exp(-(E2 / stable)**(1.0/theta))
    u1 = np.clip(u1, 1e-6, 1-1e-6)
    u2 = np.clip(u2, 1e-6, 1-1e-6)
    return np.column_stack([u1, u2])


def simulate_portfolio_copula(copula_fits, asset_pairs, garch_vols, n_sim=MC_SIMULATIONS):
    """
    Simulate portfolio returns using pairwise copulas.
    Uses the first asset's copula fits to build a correlation structure.
    Simplified: use the average pairwise structure.
    """
    n_assets = len(ASSETS)

    # Build correlation matrix from Gaussian copula fits
    corr_mat = np.eye(n_assets)
    for (a1, a2), fit in copula_fits.items():
        i = ASSETS.index(a1)
        j = ASSETS.index(a2)
        if "rho" in fit:
            corr_mat[i, j] = fit["rho"]
            corr_mat[j, i] = fit["rho"]

    # Ensure positive definite
    eigvals, eigvecs = np.linalg.eigh(corr_mat)
    eigvals = np.maximum(eigvals, 1e-6)
    corr_mat = eigvecs @ np.diag(eigvals) @ eigvecs.T
    # Re-normalize to correlation
    d = np.sqrt(np.diag(corr_mat))
    corr_mat = corr_mat / np.outer(d, d)

    # Simulate from multivariate normal (Gaussian copula)
    z = np.random.multivariate_normal(np.zeros(n_assets), corr_mat, n_sim)
    u_gauss = stats.norm.cdf(z)

    # Convert back to returns using marginal distributions (inverse PIT)
    sim_returns = np.zeros((n_sim, n_assets))
    for k, asset in enumerate(ASSETS):
        vol = garch_vols[asset]
        # Use Student-t marginals
        try:
            nu = garch_results[asset].params.get("nu", 5.0)
        except:
            nu = 5.0
        sim_returns[:, k] = stats.t.ppf(u_gauss[:, k], df=nu) * vol

    return sim_returns


def simulate_portfolio_t_copula(t_copula_avg_rho, t_copula_avg_nu, garch_vols, n_sim=MC_SIMULATIONS):
    """Simulate portfolio using multivariate t-copula."""
    n_assets = len(ASSETS)

    # Build correlation matrix
    corr_mat = np.eye(n_assets)
    rho_avg = t_copula_avg_rho
    for i in range(n_assets):
        for j in range(i+1, n_assets):
            pair = (ASSETS[i], ASSETS[j])
            if pair in t_copula_avg_rho:
                corr_mat[i, j] = t_copula_avg_rho[pair]
                corr_mat[j, i] = t_copula_avg_rho[pair]
            else:
                corr_mat[i, j] = 0.0
                corr_mat[j, i] = 0.0

    # Ensure positive definite
    eigvals, eigvecs = np.linalg.eigh(corr_mat)
    eigvals = np.maximum(eigvals, 1e-6)
    corr_mat = eigvecs @ np.diag(eigvals) @ eigvecs.T
    d = np.sqrt(np.diag(corr_mat))
    corr_mat = corr_mat / np.outer(d, d)

    nu = t_copula_avg_nu

    # Simulate multivariate t
    z = np.random.multivariate_normal(np.zeros(n_assets), corr_mat, n_sim)
    chi2 = np.random.chisquare(nu, n_sim) / nu
    t_samples = z / np.sqrt(chi2[:, None])
    u_t = stats.t.cdf(t_samples, df=nu)

    sim_returns = np.zeros((n_sim, n_assets))
    for k, asset in enumerate(ASSETS):
        vol = garch_vols[asset]
        try:
            nu_marg = garch_results[asset].params.get("nu", 5.0)
        except:
            nu_marg = 5.0
        sim_returns[:, k] = stats.t.ppf(u_t[:, k], df=nu_marg) * vol

    return sim_returns


# ======================================================================
# MAIN ANALYSIS
# ======================================================================

# Generate all pairs
pairs = []
for i in range(len(ASSETS)):
    for j in range(i+1, len(ASSETS)):
        pairs.append((ASSETS[i], ASSETS[j]))

print(f"[4] Fitting copulas to {len(pairs)} asset pairs...")
print(f"    Pairs: {pairs}")
print()

# ======================================================================
# FIT COPULAS TO PRE-OOS DATA
# ======================================================================

all_copula_fits = {}  # {pair: {copula_type: fit_result}}
tail_dep_results = {}  # {pair: {empirical, parametric}}

for pair in pairs:
    a1, a2 = pair
    u1 = uniform_fit[a1]
    u2 = uniform_fit[a2]
    print(f"  --- {a1}-{a2} ---")

    # Fit all 4 copulas
    t_fit_start = time.time()

    gauss_fit = fit_gaussian_copula(u1, u2)
    print(f"    Gaussian:  rho={gauss_fit['rho']:.4f}, NLL={gauss_fit['nll']:.1f}")

    t_fit = fit_t_copula(u1, u2)
    print(f"    Student-t: rho={t_fit.get('rho', 0):.4f}, nu={t_fit.get('nu', 0):.2f}, NLL={t_fit['nll']:.1f}")

    clay_fit = fit_clayton_copula(u1, u2)
    print(f"    Clayton:   theta={clay_fit['theta']:.4f}, NLL={clay_fit['nll']:.1f}")

    gumb_fit = fit_gumbel_copula(u1, u2)
    print(f"    Gumbel:    theta={gumb_fit['theta']:.4f}, NLL={gumb_fit['nll']:.1f}")

    all_copula_fits[pair] = {
        "gaussian": gauss_fit,
        "t": t_fit,
        "clayton": clay_fit,
        "gumbel": gumb_fit,
    }

    # Empirical tail dependence
    emp_td = {}
    for thresh in TAIL_THRESHOLDS:
        lL, lU, nL, nU = empirical_tail_dependence(u1, u2, thresh)
        emp_td[f"thresh_{thresh}"] = {
            "lambda_L": lL, "lambda_U": lU,
            "n_lower": int(nL), "n_upper": int(nU)
        }

    # Parametric tail dependence
    param_td = {}
    for cname, cfit in all_copula_fits[pair].items():
        lL, lU = parametric_tail_dependence(cfit)
        param_td[cname] = {"lambda_L": lL, "lambda_U": lU}

    # Bootstrap CIs for empirical tail dependence (threshold=0.05)
    lam_L_boot, lam_U_boot = bootstrap_tail_dependence(u1, u2, threshold=0.05)
    boot_ci = {
        "lambda_L_mean": float(np.mean(lam_L_boot)),
        "lambda_L_ci95": [float(np.percentile(lam_L_boot, 2.5)), float(np.percentile(lam_L_boot, 97.5))],
        "lambda_U_mean": float(np.mean(lam_U_boot)),
        "lambda_U_ci95": [float(np.percentile(lam_U_boot, 2.5)), float(np.percentile(lam_U_boot, 97.5))],
        "lambda_L_sig": float(np.percentile(lam_L_boot, 2.5)) > 0,
        "lambda_U_sig": float(np.percentile(lam_U_boot, 2.5)) > 0,
    }

    tail_dep_results[pair] = {
        "empirical": emp_td,
        "parametric": param_td,
        "bootstrap": boot_ci,
    }

    print(f"    Empirical (5%): lambda_L={emp_td['thresh_0.05']['lambda_L']:.4f}, "
          f"lambda_U={emp_td['thresh_0.05']['lambda_U']:.4f}")
    print(f"    Bootstrap CI(L): [{boot_ci['lambda_L_ci95'][0]:.4f}, {boot_ci['lambda_L_ci95'][1]:.4f}]"
          f"  sig={boot_ci['lambda_L_sig']}")
    print(f"    Bootstrap CI(U): [{boot_ci['lambda_U_ci95'][0]:.4f}, {boot_ci['lambda_U_ci95'][1]:.4f}]"
          f"  sig={boot_ci['lambda_U_sig']}")
    print(f"    Parametric: t-cop lambda={param_td['t']['lambda_L']:.4f}, "
          f"Clayton lambda_L={param_td['clayton']['lambda_L']:.4f}, "
          f"Gumbel lambda_U={param_td['gumbel']['lambda_U']:.4f}")
    print(f"    ({time.time()-t_fit_start:.1f}s)")
    print()

# ======================================================================
# COPULA MODEL SELECTION (AIC/BIC)
# ======================================================================
print("[5] Model selection (AIC) per pair...")

model_selection = {}
for pair in pairs:
    a1, a2 = pair
    n = len(uniform_fit[a1])
    fits = all_copula_fits[pair]

    aic_results = {}
    for cname, cfit in fits.items():
        nll = cfit["nll"]
        if cname == "gaussian":
            k = 1  # rho
        elif cname == "t":
            k = 2  # rho, nu
        elif cname in ("clayton", "gumbel"):
            k = 1  # theta
        else:
            k = 1
        aic = 2 * nll + 2 * k
        bic = 2 * nll + k * np.log(n)
        aic_results[cname] = {"AIC": float(aic), "BIC": float(bic), "NLL": float(nll)}

    best_aic = min(aic_results, key=lambda x: aic_results[x]["AIC"])
    best_bic = min(aic_results, key=lambda x: aic_results[x]["BIC"])
    model_selection[pair] = {
        "aic": aic_results,
        "best_aic": best_aic,
        "best_bic": best_bic,
    }
    print(f"  {a1}-{a2}: Best AIC={best_aic}, Best BIC={best_bic}")
    for cname, res in sorted(aic_results.items(), key=lambda x: x[1]["AIC"]):
        print(f"    {cname:10s}: AIC={res['AIC']:.1f}, BIC={res['BIC']:.1f}")

print()

# ======================================================================
# OOS VaR COMPARISON (Rolling)
# ======================================================================
print("[6] Out-of-sample VaR comparison (rolling window)...")

# We'll compute VaR for each OOS day using:
# 1. Historical VaR (from past returns)
# 2. Gaussian copula VaR (MC simulation)
# 3. t-copula VaR (MC simulation)
# 4. Clayton-augmented VaR
# 5. Parametric normal VaR (sample covariance)

oos_indices = returns_df.index[oos_mask]
n_oos_days = len(oos_indices)

var_results = {
    "historical": np.zeros(n_oos_days),
    "normal": np.zeros(n_oos_days),
    "gaussian_copula": np.zeros(n_oos_days),
    "t_copula": np.zeros(n_oos_days),
}

portfolio_oos_returns = np.zeros(n_oos_days)

# Rolling VaR estimation
REFIT_EVERY = 22  # Refit copulas monthly
last_copula_fits = None
last_t_copula_rhos = None
last_t_copula_nu = None

print(f"    Computing rolling VaR for {n_oos_days} OOS days (refit every {REFIT_EVERY} days)...")

for day_idx in range(n_oos_days):
    oos_date = oos_indices[day_idx]
    global_idx = returns_df.index.get_loc(oos_date)

    # Get training window returns
    train_start = max(0, global_idx - GARCH_WINDOW)
    train_returns = returns_df.iloc[train_start:global_idx]

    # Portfolio return for this OOS day
    port_ret = (returns_df.iloc[global_idx] * PORTFOLIO_WEIGHTS).sum()
    portfolio_oos_returns[day_idx] = port_ret

    # Historical VaR: from training window portfolio returns
    hist_port_rets = (train_returns * PORTFOLIO_WEIGHTS).sum(axis=1)
    var_results["historical"][day_idx] = np.percentile(hist_port_rets, VAR_LEVEL * 100)

    # Normal parametric VaR
    mu = hist_port_rets.mean()
    sigma = hist_port_rets.std()
    var_results["normal"][day_idx] = mu + stats.norm.ppf(VAR_LEVEL) * sigma

    # Copula-based VaR (refit periodically)
    if day_idx % REFIT_EVERY == 0 or last_copula_fits is None:
        # Get conditional vols for each asset (last value before OOS day)
        current_vols = {}
        for asset in ASSETS:
            # Use most recent conditional volatility from GARCH
            cv = cond_vols[asset]
            recent_cv = cv.iloc[train_start:global_idx]
            current_vols[asset] = recent_cv.iloc[-1] if len(recent_cv) > 0 else 1.0

        # Get uniform margins for training window
        u_train = {}
        for asset in ASSETS:
            u_all = uniform_margins[asset]
            u_train[asset] = u_all.iloc[train_start:global_idx].values

        # Refit pairwise copulas
        pair_gauss = {}
        pair_t_rho = {}
        pair_t_nu = []
        for p_pair in pairs:
            pa1, pa2 = p_pair
            u1_tr = u_train[pa1][-500:]  # Use last 500 obs for speed
            u2_tr = u_train[pa2][-500:]
            gf = fit_gaussian_copula(u1_tr, u2_tr)
            pair_gauss[p_pair] = gf
            tf = fit_t_copula(u1_tr, u2_tr)
            pair_t_rho[p_pair] = tf.get("rho", 0)
            pair_t_nu.append(tf.get("nu", 5))

        last_copula_fits = pair_gauss
        last_t_copula_rhos = pair_t_rho
        last_t_copula_nu = float(np.median(pair_t_nu))

    # Gaussian copula MC VaR
    sim_gauss = simulate_portfolio_copula(
        last_copula_fits, pairs, current_vols, n_sim=MC_SIMULATIONS
    )
    port_sim_gauss = (sim_gauss * PORTFOLIO_WEIGHTS).sum(axis=1)
    var_results["gaussian_copula"][day_idx] = np.percentile(port_sim_gauss, VAR_LEVEL * 100)

    # t-copula MC VaR
    sim_t = simulate_portfolio_t_copula(
        last_t_copula_rhos, last_t_copula_nu, current_vols, n_sim=MC_SIMULATIONS
    )
    port_sim_t = (sim_t * PORTFOLIO_WEIGHTS).sum(axis=1)
    var_results["t_copula"][day_idx] = np.percentile(port_sim_t, VAR_LEVEL * 100)

    if (day_idx + 1) % 50 == 0 or day_idx == 0:
        print(f"    Day {day_idx+1}/{n_oos_days}: hist_VaR={var_results['historical'][day_idx]:.3f}%, "
              f"norm_VaR={var_results['normal'][day_idx]:.3f}%, "
              f"gauss_cop={var_results['gaussian_copula'][day_idx]:.3f}%, "
              f"t_cop={var_results['t_copula'][day_idx]:.3f}%")

print()

# ======================================================================
# VaR BACKTESTING
# ======================================================================
print("[7] VaR Backtesting (Kupiec test)...")

def kupiec_test(returns, var_forecast, alpha=VAR_LEVEL):
    """Kupiec unconditional coverage test."""
    violations = returns < var_forecast
    n_violations = violations.sum()
    n_total = len(returns)
    violation_rate = n_violations / n_total

    # Kupiec LR_uc
    p_hat = violation_rate
    if p_hat == 0:
        p_hat = 0.5 / n_total
    if p_hat >= 1:
        p_hat = 1 - 0.5 / n_total

    lr = -2 * (
        n_violations * np.log(alpha) + (n_total - n_violations) * np.log(1 - alpha)
        - n_violations * np.log(p_hat) - (n_total - n_violations) * np.log(1 - p_hat)
    )
    p_value = 1 - stats.chi2.cdf(lr, df=1)

    return {
        "n_violations": int(n_violations),
        "n_total": int(n_total),
        "violation_rate": float(violation_rate),
        "expected_rate": float(alpha),
        "lr_stat": float(lr),
        "p_value": float(p_value),
        "pass": p_value > 0.05,
    }


backtest_results = {}
for method, var_series in var_results.items():
    bt = kupiec_test(portfolio_oos_returns, var_series)
    backtest_results[method] = bt
    status = "PASS" if bt["pass"] else "FAIL"
    print(f"  {method:20s}: violations={bt['n_violations']}/{bt['n_total']} "
          f"({bt['violation_rate']:.3f} vs {bt['expected_rate']:.3f}), "
          f"Kupiec p={bt['p_value']:.4f} [{status}]")

print()

# ======================================================================
# COMPARATIVE ANALYSIS: DM TEST
# ======================================================================
print("[8] Diebold-Mariano test: Copula VaR vs Historical VaR...")

def quantile_loss(returns, var_forecast, alpha=VAR_LEVEL):
    """Tick/quantile loss function."""
    violations = returns < var_forecast
    loss = (alpha - violations.astype(float)) * (returns - var_forecast)
    return loss


# Compute quantile losses
ql_hist = quantile_loss(portfolio_oos_returns, var_results["historical"])
ql_norm = quantile_loss(portfolio_oos_returns, var_results["normal"])
ql_gauss = quantile_loss(portfolio_oos_returns, var_results["gaussian_copula"])
ql_t = quantile_loss(portfolio_oos_returns, var_results["t_copula"])


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. loss1 - loss2 < 0 means model 1 is better."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=1)
    V = gamma_0
    for k in range(1, min(h + 1, T // 2)):
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / T
        V += 2 * gamma_k
    dm_stat = d_bar / np.sqrt(max(V / T, 1e-20))
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return {"statistic": float(dm_stat), "p_value": float(p_value),
            "better": "model1" if d_bar < 0 else "model2"}


dm_results = {}
comparisons = [
    ("t_copula vs historical", ql_t, ql_hist),
    ("t_copula vs normal", ql_t, ql_norm),
    ("t_copula vs gaussian_copula", ql_t, ql_gauss),
    ("gaussian_copula vs historical", ql_gauss, ql_hist),
]

for name, l1, l2 in comparisons:
    dm = dm_test(l1, l2)
    dm_results[name] = dm
    print(f"  {name:40s}: DM={dm['statistic']:+.3f}, p={dm['p_value']:.4f}, better={dm['better']}")

print()

# ======================================================================
# SUMMARY STATISTICS
# ======================================================================
print("[9] Summary of tail dependence across all pairs...")
print()

print(f"{'Pair':12s} | {'Emp λ_L (5%)':14s} | {'Emp λ_U (5%)':14s} | "
      f"{'t-cop λ':10s} | {'Clayton λ_L':12s} | {'Gumbel λ_U':12s} | "
      f"{'Best AIC':12s}")
print("-" * 100)

n_sig_lower = 0
n_sig_upper = 0
n_pairs_total = len(pairs)

for pair in pairs:
    a1, a2 = pair
    td = tail_dep_results[pair]
    emp = td["empirical"]["thresh_0.05"]
    param = td["parametric"]
    boot = td["bootstrap"]
    ms = model_selection[pair]

    sig_L = "*" if boot["lambda_L_sig"] else " "
    sig_U = "*" if boot["lambda_U_sig"] else " "

    if boot["lambda_L_sig"]:
        n_sig_lower += 1
    if boot["lambda_U_sig"]:
        n_sig_upper += 1

    print(f"{a1}-{a2:5s}     | {emp['lambda_L']:.4f}{sig_L}         | {emp['lambda_U']:.4f}{sig_U}         | "
          f"{param['t']['lambda_L']:.4f}     | {param['clayton']['lambda_L']:.4f}       | "
          f"{param['gumbel']['lambda_U']:.4f}       | {ms['best_aic']:12s}")

print()
print(f"  * = Bootstrap 95% CI excludes zero")
print(f"  Significant lower tail dependence: {n_sig_lower}/{n_pairs_total} pairs")
print(f"  Significant upper tail dependence: {n_sig_upper}/{n_pairs_total} pairs")
print()

# ======================================================================
# VaR COMPARISON SUMMARY
# ======================================================================
print("[10] VaR Comparison Summary")
print()
print(f"{'Method':20s} | {'Violations':12s} | {'Rate':8s} | {'Kupiec p':10s} | {'Status':8s} | {'Avg VaR':10s}")
print("-" * 80)

for method, bt in backtest_results.items():
    status = "PASS" if bt["pass"] else "FAIL"
    avg_var = float(np.mean(var_results[method]))
    print(f"{method:20s} | {bt['n_violations']:5d}/{bt['n_total']:5d} | {bt['violation_rate']:.4f} | "
          f"{bt['p_value']:.4f}     | {status:8s} | {avg_var:.4f}%")

print()

# ======================================================================
# DETERMINE STAR RATING
# ======================================================================
print("=" * 80)
print("CONCLUSIONS")
print("=" * 80)

# Criteria for star rating:
# ★★★ if copula significantly improves VaR (DM test p<0.05 for t-copula vs historical)
# ★★ if tail dependence found but no VaR improvement
# ★ if null (no tail dependence found)

has_sig_tail_dep = n_sig_lower > 0 or n_sig_upper > 0
t_vs_hist_dm = dm_results.get("t_copula vs historical", {})
copula_improves_var = (t_vs_hist_dm.get("p_value", 1) < 0.05 and
                       t_vs_hist_dm.get("better", "") == "model1")

# Also check: does t-copula pass Kupiec while historical fails?
t_kupiec_pass = backtest_results.get("t_copula", {}).get("pass", False)
hist_kupiec_pass = backtest_results.get("historical", {}).get("pass", False)
copula_kupiec_advantage = t_kupiec_pass and not hist_kupiec_pass

if copula_improves_var or copula_kupiec_advantage:
    star_rating = 3
    star_str = "★★★"
    conclusion = ("Copula models SIGNIFICANTLY improve portfolio VaR. "
                  "t-copula captures tail dependence missed by standard methods.")
elif has_sig_tail_dep:
    star_rating = 2
    star_str = "★★"
    conclusion = ("Significant tail dependence FOUND in asset pairs, "
                  "but copula VaR does NOT significantly outperform historical VaR. "
                  "Tail dependence is statistically real but economically marginal for VaR.")
else:
    star_rating = 1
    star_str = "★"
    conclusion = ("No significant tail dependence found. "
                  "Standard correlation is sufficient for this portfolio.")

print(f"\n  Star Rating: {star_str}")
print(f"  Conclusion: {conclusion}")
print()

# Detail findings
findings = []

# Finding 1: Tail dependence
if has_sig_tail_dep:
    findings.append(f"Significant tail dependence found: {n_sig_lower}/{n_pairs_total} pairs (lower), "
                    f"{n_sig_upper}/{n_pairs_total} pairs (upper)")
else:
    findings.append("No statistically significant tail dependence at 5% threshold")

# Finding 2: Best copula model
best_aic_counts = {}
for pair, ms in model_selection.items():
    b = ms["best_aic"]
    best_aic_counts[b] = best_aic_counts.get(b, 0) + 1
best_overall = max(best_aic_counts, key=best_aic_counts.get)
findings.append(f"Best copula by AIC across pairs: {best_overall} ({best_aic_counts[best_overall]}/{n_pairs_total} pairs)")

# Finding 3: VaR performance
for method, bt in backtest_results.items():
    if bt["pass"]:
        findings.append(f"{method} VaR passes Kupiec test (p={bt['p_value']:.4f})")
    else:
        findings.append(f"{method} VaR FAILS Kupiec test (p={bt['p_value']:.4f})")

# Finding 4: DM test
for name, dm in dm_results.items():
    if dm["p_value"] < 0.05:
        findings.append(f"DM test significant: {name} (p={dm['p_value']:.4f}, better={dm['better']})")

print("  Findings:")
for i, f in enumerate(findings, 1):
    print(f"    {i}. {f}")

print()

# ======================================================================
# SAVE RESULTS JSON
# ======================================================================
print("[11] Saving results...")

# Convert pair tuples to strings for JSON
tail_dep_json = {}
for pair, td in tail_dep_results.items():
    key = f"{pair[0]}-{pair[1]}"
    tail_dep_json[key] = td

copula_fits_json = {}
for pair, fits in all_copula_fits.items():
    key = f"{pair[0]}-{pair[1]}"
    copula_fits_json[key] = {}
    for cname, cfit in fits.items():
        copula_fits_json[key][cname] = {k: float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v
                                         for k, v in cfit.items()}

model_sel_json = {}
for pair, ms in model_selection.items():
    key = f"{pair[0]}-{pair[1]}"
    model_sel_json[key] = ms

var_comparison_json = {}
for method, bt in backtest_results.items():
    var_comparison_json[method] = {
        **bt,
        "avg_var": float(np.mean(var_results[method])),
        "std_var": float(np.std(var_results[method])),
    }

dm_json = {}
for name, dm in dm_results.items():
    dm_json[name] = dm

results = {
    "experiment_id": "K160",
    "title": "Copula Tail Dependence for Portfolio Risk",
    "timestamp": datetime.now().isoformat(),
    "star_rating": star_str,
    "star_rating_num": star_rating,
    "conclusion": conclusion,
    "findings": findings,
    "config": {
        "assets": ASSETS,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "garch_window": GARCH_WINDOW,
        "n_bootstrap": N_BOOTSTRAP,
        "mc_simulations": MC_SIMULATIONS,
        "var_level": VAR_LEVEL,
        "portfolio_weights": PORTFOLIO_WEIGHTS.tolist(),
    },
    "tail_dependence": tail_dep_json,
    "copula_fits": copula_fits_json,
    "model_selection": model_sel_json,
    "var_comparison": var_comparison_json,
    "dm_tests": dm_json,
    "summary_stats": {
        "n_sig_lower_tail": n_sig_lower,
        "n_sig_upper_tail": n_sig_upper,
        "n_pairs": n_pairs_total,
        "best_copula_overall": best_overall,
        "oos_portfolio_vol": float(np.std(portfolio_oos_returns)),
        "oos_portfolio_mean": float(np.mean(portfolio_oos_returns)),
    },
}

output_path = Path(__file__).resolve().parent / "k160_copula_tail_dependence_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"    Saved to: {output_path}")
print()

# ======================================================================
# FINAL SUMMARY
# ======================================================================
print("=" * 80)
print(f"K160 COMPLETE — {star_str}")
print("=" * 80)
print(f"  Portfolio: {ASSETS} (equal-weight)")
print(f"  OOS: {OOS_START} to {OOS_END} ({n_oos_days} days)")
print(f"  Tail dependence: {n_sig_lower} lower / {n_sig_upper} upper significant (of {n_pairs_total} pairs)")
print(f"  Best copula (AIC): {best_overall}")
print(f"  Copula improves VaR: {'YES' if copula_improves_var or copula_kupiec_advantage else 'NO'}")
print(f"  Conclusion: {conclusion}")
print("=" * 80)
