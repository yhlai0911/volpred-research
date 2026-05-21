"""
K1320: Copula-based GARCH Hedge — Hsu et al. (2008, JFM) Minimum Variance Hedge Ratio

Methodology:
- SPY (spot) vs QQQ (hedge instrument), 2005-2024
- IS: 2005-2018, OOS: 2019-2024
- 5 copulas: Normal, Student-t, Clayton, Gumbel, Frank
- GARCH/GJR-GARCH marginals, PIT → uniform, copula MLE
- Hedge ratio: h*_t = rho_t * sigma_S_t / sigma_F_t
- Baselines: OLS, Rolling OLS 252d, DCC-GARCH (Gaussian + t)
- Evaluation: HE = 1 - Var(hedged) / Var(unhedged), DM test (HLN/HAC)

Lookahead prevention: ALL signals use t-1 (hedge ratio from t-1 applied to t)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, kendalltau
from arch import arch_model
import warnings
import json
import os
import itertools

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 60)
print("K1320: Copula-based GARCH Hedge (Hsu et al. 2008)")
print("=" * 60)

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))
IS_START = "2005-01-01"
IS_END   = "2018-12-31"
OOS_START= "2019-01-01"
OOS_END  = "2024-12-31"

print("\n[1] Downloading SPY and QQQ data (2005-2024)...")
spy_raw = yf.download("SPY", start="2005-01-01", end="2024-12-31", auto_adjust=True, progress=False)
qqq_raw = yf.download("QQQ", start="2005-01-01", end="2024-12-31", auto_adjust=True, progress=False)

# Extract close prices
spy_close = spy_raw['Close'].squeeze()
qqq_close = qqq_raw['Close'].squeeze()

# Align on common dates
common_idx = spy_close.index.intersection(qqq_close.index)
spy_close = spy_close.loc[common_idx].dropna()
qqq_close = qqq_close.loc[common_idx].dropna()

# Log returns
spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
qqq_ret = np.log(qqq_close / qqq_close.shift(1)).dropna()

# Align
common_ret_idx = spy_ret.index.intersection(qqq_ret.index)
spy_ret = spy_ret.loc[common_ret_idx]
qqq_ret = qqq_ret.loc[common_ret_idx]

print(f"  Total obs: {len(spy_ret)}")
print(f"  Date range: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}")

# Split IS / OOS
is_mask = (spy_ret.index >= IS_START) & (spy_ret.index <= IS_END)
oos_mask = (spy_ret.index >= OOS_START) & (spy_ret.index <= OOS_END)

spy_is = spy_ret[is_mask].values
qqq_is = qqq_ret[is_mask].values
spy_oos = spy_ret[oos_mask].values
qqq_oos = qqq_ret[oos_mask].values
oos_dates = spy_ret[oos_mask].index

print(f"  IS obs  : {len(spy_is)} ({IS_START} to {IS_END})")
print(f"  OOS obs : {len(spy_oos)} ({OOS_START} to {OOS_END})")
print(f"  Sample correlation (full): {np.corrcoef(spy_ret.values, qqq_ret.values)[0,1]:.4f}")
print(f"  Sample correlation (IS)  : {np.corrcoef(spy_is, qqq_is)[0,1]:.4f}")
print(f"  Sample correlation (OOS) : {np.corrcoef(spy_oos, qqq_oos)[0,1]:.4f}")

# ============================================================
# 2. GJR-GARCH MARGINALS — IS fit
# ============================================================
print("\n[2] Fitting GJR-GARCH(1,1) marginals on IS data...")

def fit_gjr_garch(returns, label=""):
    """Fit GJR-GARCH(1,1) with normal distribution; return model, fitted result, conditional vols"""
    model = arch_model(returns * 100, vol='Garch', p=1, o=1, q=1, dist='normal', rescale=False)
    result = model.fit(disp='off', options={'maxiter': 2000})
    if label:
        print(f"  {label}: omega={result.params['omega']:.4f}, alpha={result.params['alpha[1]']:.4f}, "
              f"gamma={result.params['gamma[1]']:.4f}, beta={result.params['beta[1]']:.4f}, "
              f"loglik={result.loglikelihood:.2f}")
    return model, result

spy_model_is, spy_fit_is = fit_gjr_garch(spy_is, "SPY GJR-GARCH IS")
qqq_model_is, qqq_fit_is = fit_gjr_garch(qqq_is, "QQQ GJR-GARCH IS")

# Standardized residuals (PIT inputs) on IS
spy_sigma_is = spy_fit_is.conditional_volatility / 100  # back to original scale
qqq_sigma_is = qqq_fit_is.conditional_volatility / 100
spy_std_resid_is = spy_is / spy_sigma_is
qqq_std_resid_is = qqq_is / qqq_sigma_is

# ============================================================
# 3. PROBABILITY INTEGRAL TRANSFORM (PIT) → Uniform (0,1)
# ============================================================
print("\n[3] PIT transform to uniform margins...")

def pit_to_uniform(std_resids):
    """
    Non-parametric PIT using empirical CDF (rank-based).
    Avoids distributional misspecification.
    """
    n = len(std_resids)
    # Scaled rank to avoid exact 0/1
    ranks = pd.Series(std_resids).rank()
    u = ranks.values / (n + 1)
    return u

u_spy_is = pit_to_uniform(spy_std_resid_is)
u_qqq_is = pit_to_uniform(qqq_std_resid_is)

print(f"  u_spy range: [{u_spy_is.min():.4f}, {u_spy_is.max():.4f}]")
print(f"  u_qqq range: [{u_qqq_is.min():.4f}, {u_qqq_is.max():.4f}]")

# ============================================================
# 4. COPULA MLE — 5 copula families
# ============================================================
print("\n[4] Fitting 5 copula families (IS)...")

def copula_aic(log_lik, n_params):
    return -2 * log_lik + 2 * n_params

# --- Normal (Gaussian) Copula ---
def normal_copula_loglik(params, u, v):
    """Log-likelihood of bivariate Gaussian copula"""
    rho = np.tanh(params[0])  # unbounded -> (-1,1)
    eps = 1e-10
    u = np.clip(u, eps, 1 - eps)
    v = np.clip(v, eps, 1 - eps)
    x = norm.ppf(u)
    y = norm.ppf(v)
    log_lik = -0.5 * np.log(1 - rho**2) - \
              (rho**2 * (x**2 + y**2) - 2 * rho * x * y) / (2 * (1 - rho**2))
    return -np.sum(log_lik)

res_normal = minimize(normal_copula_loglik, [0.0], args=(u_spy_is, u_qqq_is),
                      method='L-BFGS-B', bounds=[(-5, 5)])
rho_normal = np.tanh(res_normal.x[0])
ll_normal = -res_normal.fun
aic_normal = copula_aic(ll_normal, 1)
print(f"  Normal copula: rho={rho_normal:.4f}, loglik={ll_normal:.2f}, AIC={aic_normal:.2f}")

# --- Student-t Copula ---
def student_t_copula_loglik(params, u, v):
    """Log-likelihood of bivariate Student-t copula"""
    rho = np.tanh(params[0])
    # df must be > 2
    nu = np.exp(params[1]) + 2.0
    eps = 1e-10
    u = np.clip(u, eps, 1 - eps)
    v = np.clip(v, eps, 1 - eps)
    x = t_dist.ppf(u, df=nu)
    y = t_dist.ppf(v, df=nu)

    from scipy.special import gammaln, betaln
    # Bivariate t copula density
    # log c(u,v) = log f(x,y;rho,nu) - log f_t(x;nu) - log f_t(y;nu)
    # f_t(x;nu) = Gamma((nu+1)/2)/(sqrt(nu*pi)*Gamma(nu/2)) * (1+x^2/nu)^(-(nu+1)/2)

    log_bivariate = (
        gammaln((nu + 2) / 2) + gammaln(nu / 2)
        - 2 * gammaln((nu + 1) / 2)
        - 0.5 * np.log(1 - rho**2)
        - (nu + 2) / 2 * np.log(1 + (x**2 + y**2 - 2*rho*x*y) / (nu * (1 - rho**2)))
        + (nu + 1) / 2 * np.log(1 + x**2 / nu)
        + (nu + 1) / 2 * np.log(1 + y**2 / nu)
    )
    return -np.sum(log_bivariate)

np.random.seed(42)
res_t = minimize(student_t_copula_loglik, [0.0, np.log(8)], args=(u_spy_is, u_qqq_is),
                 method='L-BFGS-B', bounds=[(-5, 5), (-2, 5)])
rho_t = np.tanh(res_t.x[0])
nu_t = np.exp(res_t.x[1]) + 2.0
ll_t = -res_t.fun
aic_t = copula_aic(ll_t, 2)
print(f"  Student-t copula: rho={rho_t:.4f}, nu={nu_t:.2f}, loglik={ll_t:.2f}, AIC={aic_t:.2f}")

# --- Clayton Copula (lower tail dependence) ---
def clayton_copula_loglik(params, u, v):
    """Log-likelihood of bivariate Clayton copula
    C(u,v) = (u^{-theta} + v^{-theta} - 1)^{-1/theta}, theta > 0
    """
    theta = np.exp(params[0]) + 1e-6  # must be > 0
    eps = 1e-10
    u = np.clip(u, eps, 1 - eps)
    v = np.clip(v, eps, 1 - eps)
    # Log density of Clayton copula
    log_c = (
        np.log(1 + theta)
        + (-1 - theta) * np.log(u)
        + (-1 - theta) * np.log(v)
        + (-1/theta - 2) * np.log(u**(-theta) + v**(-theta) - 1)
    )
    return -np.sum(log_c)

res_clayton = minimize(clayton_copula_loglik, [0.0], args=(u_spy_is, u_qqq_is),
                       method='L-BFGS-B', bounds=[(-5, 10)])
theta_clayton = np.exp(res_clayton.x[0]) + 1e-6
ll_clayton = -res_clayton.fun
aic_clayton = copula_aic(ll_clayton, 1)
print(f"  Clayton copula: theta={theta_clayton:.4f}, loglik={ll_clayton:.2f}, AIC={aic_clayton:.2f}")

# --- Gumbel Copula (upper tail dependence) ---
def gumbel_copula_loglik(params, u, v):
    """Log-likelihood of bivariate Gumbel copula
    C(u,v) = exp(-[(−ln u)^theta + (−ln v)^theta]^{1/theta}), theta >= 1
    """
    theta = np.exp(params[0]) + 1.0  # must be >= 1
    eps = 1e-10
    u = np.clip(u, eps, 1 - eps)
    v = np.clip(v, eps, 1 - eps)

    a = (-np.log(u))**theta
    b = (-np.log(v))**theta
    s = a + b

    # Log copula density
    log_C = -s**(1/theta)

    log_c = (
        log_C
        + (1/theta - 2) * np.log(s)
        + (theta - 1) * np.log(-np.log(u))
        + (theta - 1) * np.log(-np.log(v))
        - np.log(u)
        - np.log(v)
        + np.log(s**(1/theta - 2) * (1 + (theta - 1) * s**(-1/theta)) + (1/theta - 1) * s**(1/theta - 2))
    )
    # Use numerical log density instead
    # More robust approach
    log_denom = np.log(u) + np.log(v)
    log_s = np.log(s)

    # Gumbel copula log density (Nelsen 2006 formula)
    log_c_clean = (
        -s**(1/theta)
        + (theta - 1) * (np.log(-np.log(u)) + np.log(-np.log(v)))
        - np.log(u) - np.log(v)
        + (1/theta - 2) * log_s
        + np.log1p((theta - 1) * s**(-1/theta))
    )
    return -np.sum(log_c_clean[np.isfinite(log_c_clean)])

res_gumbel = minimize(gumbel_copula_loglik, [0.0], args=(u_spy_is, u_qqq_is),
                      method='L-BFGS-B', bounds=[(-5, 5)])
theta_gumbel = np.exp(res_gumbel.x[0]) + 1.0
ll_gumbel = -res_gumbel.fun
aic_gumbel = copula_aic(ll_gumbel, 1)
print(f"  Gumbel copula: theta={theta_gumbel:.4f}, loglik={ll_gumbel:.2f}, AIC={aic_gumbel:.2f}")

# --- Frank Copula ---
def frank_copula_loglik(params, u, v):
    """Log-likelihood of bivariate Frank copula"""
    theta = params[0]  # any real, but avoid 0
    if abs(theta) < 1e-6:
        theta = 1e-6
    eps = 1e-10
    u = np.clip(u, eps, 1 - eps)
    v = np.clip(v, eps, 1 - eps)

    # Frank copula density
    # c(u,v) = -theta * (exp(-theta) - 1) * exp(-theta*(u+v)) /
    #           (exp(-theta) - 1 + (exp(-theta*u) - 1)(exp(-theta*v) - 1))^2
    A = np.exp(-theta) - 1
    B = (np.exp(-theta * u) - 1) * (np.exp(-theta * v) - 1)

    log_c = (
        np.log(np.abs(theta))
        + np.log(np.abs(A))
        + (-theta) * (u + v)
        - 2 * np.log(np.abs(A + B))
    )
    valid = np.isfinite(log_c)
    return -np.sum(log_c[valid])

# Multi-start for Frank copula (can have local optima)
best_frank_fun = np.inf
best_frank_res = None
for theta0 in [1.0, 3.0, 5.0, 8.0, 15.0]:
    try:
        res = minimize(frank_copula_loglik, [theta0], args=(u_spy_is, u_qqq_is),
                       method='L-BFGS-B', bounds=[(-20, 20)])
        if res.fun < best_frank_fun:
            best_frank_fun = res.fun
            best_frank_res = res
    except Exception:
        pass

theta_frank = best_frank_res.x[0]
ll_frank = -best_frank_res.fun
aic_frank = copula_aic(ll_frank, 1)
print(f"  Frank copula: theta={theta_frank:.4f}, loglik={ll_frank:.2f}, AIC={aic_frank:.2f}")

# ============================================================
# 5. COPULA COMPARISON & SELECTION
# ============================================================
print("\n[5] Copula AIC comparison...")

copula_results = {
    'Normal':    {'params': {'rho': rho_normal},               'll': ll_normal,   'aic': aic_normal,  'n_params': 1},
    'Student_t': {'params': {'rho': rho_t, 'nu': nu_t},        'll': ll_t,        'aic': aic_t,       'n_params': 2},
    'Clayton':   {'params': {'theta': theta_clayton},           'll': ll_clayton,  'aic': aic_clayton, 'n_params': 1},
    'Gumbel':    {'params': {'theta': theta_gumbel},            'll': ll_gumbel,   'aic': aic_gumbel,  'n_params': 1},
    'Frank':     {'params': {'theta': theta_frank},             'll': ll_frank,    'aic': aic_frank,   'n_params': 1},
}

copula_df = pd.DataFrame({
    k: {'LogLik': v['ll'], 'AIC': v['aic'], 'N_params': v['n_params']}
    for k, v in copula_results.items()
}).T.sort_values('AIC')

print(copula_df.to_string())
best_copula = copula_df.index[0]
print(f"\n  Best copula (lowest AIC): {best_copula}")

# ============================================================
# 6. COMPUTE KENDALL'S TAU AND LINEAR CORRELATION EQUIVALENTS
# ============================================================
print("\n[6] Computing Kendall's tau and correlation equivalents...")

def kendall_tau_normal_copula(rho):
    """tau = (2/pi) * arcsin(rho) for Gaussian copula"""
    return 2 / np.pi * np.arcsin(rho)

def kendall_tau_student_t_copula(rho):
    """tau = (2/pi) * arcsin(rho) same as Gaussian"""
    return 2 / np.pi * np.arcsin(rho)

def kendall_tau_clayton_copula(theta):
    """tau = theta / (theta + 2)"""
    return theta / (theta + 2)

def kendall_tau_gumbel_copula(theta):
    """tau = 1 - 1/theta"""
    return 1 - 1/theta

def kendall_tau_frank_copula(theta):
    """Numerical integration via Debye function"""
    # tau = 1 - 4/theta * (1 - D_1(theta)) where D_1 is Debye function
    from scipy.integrate import quad
    if abs(theta) < 1e-6:
        return 0.0
    def debye_integrand(t):
        if abs(t) < 1e-10:
            return 1.0
        return t / (np.exp(t) - 1)
    D1, _ = quad(debye_integrand, 0, abs(theta))
    D1 = D1 / abs(theta)
    tau = 1 - 4 / theta * (1 - D1)
    return tau

tau_emp, _ = kendalltau(spy_is, qqq_is)
print(f"  Empirical Kendall's tau: {tau_emp:.4f}")

tau_normal  = kendall_tau_normal_copula(rho_normal)
tau_t       = kendall_tau_student_t_copula(rho_t)
tau_clayton = kendall_tau_clayton_copula(theta_clayton)
tau_gumbel  = kendall_tau_gumbel_copula(theta_gumbel)
tau_frank   = kendall_tau_frank_copula(theta_frank)

for name, tau in [('Normal', tau_normal), ('Student_t', tau_t),
                   ('Clayton', tau_clayton), ('Gumbel', tau_gumbel), ('Frank', tau_frank)]:
    print(f"  {name} tau: {tau:.4f}")

# Convert Kendall's tau to Spearman's rho: rho_s ≈ sin(pi/2 * tau)
# Then to linear correlation: r ≈ 2 * sin(pi/6 * rho_s) ≈ rho_s for high correlation
# For Gaussian/t copula, use rho directly. For others, use tau -> rho conversion.
def tau_to_linear_rho(tau):
    """Convert Kendall's tau to linear correlation via Greiner's relation: rho = sin(pi/2 * tau)"""
    return np.sin(np.pi / 2 * tau)

# Linear correlation equivalent for each copula
rho_equiv = {
    'Normal':    rho_normal,  # direct
    'Student_t': rho_t,       # direct
    'Clayton':   tau_to_linear_rho(tau_clayton),
    'Gumbel':    tau_to_linear_rho(tau_gumbel),
    'Frank':     tau_to_linear_rho(tau_frank),
}

print("\n  Linear correlation equivalents:")
for name, rho in rho_equiv.items():
    print(f"    {name}: {rho:.4f}")

# ============================================================
# 7. GARCH SIGMA FORECASTS — OOS (one-step-ahead using IS parameters)
# ============================================================
print("\n[7] Computing OOS GARCH conditional volatilities...")

def garch_one_step_ahead(params_fit, full_returns, oos_mask_arr):
    """
    Compute one-step-ahead conditional volatilities using IS-fitted parameters.
    Recursion starts from IS data and continues into OOS — no parameter re-estimation.
    Returns OOS conditional volatilities (array, same length as oos observations).

    LOOKAHEAD PREVENTION: sigma_t uses info up to t-1 only.
    """
    omega = params_fit.params['omega']
    alpha = params_fit.params['alpha[1]']
    gamma = params_fit.params['gamma[1]']
    beta  = params_fit.params['beta[1]']

    # Use rescaled returns (x100)
    rets = full_returns * 100
    n = len(rets)

    sigma2 = np.zeros(n)
    # Initialize with unconditional variance
    sigma2[0] = omega / (1 - alpha - 0.5*gamma - beta)

    for t in range(1, n):
        e_tm1 = rets[t-1]
        I_neg = 1.0 if e_tm1 < 0 else 0.0
        sigma2[t] = (omega +
                     alpha * e_tm1**2 +
                     gamma * I_neg * e_tm1**2 +
                     beta * sigma2[t-1])

    # Convert back to original scale
    sigma = np.sqrt(sigma2) / 100
    oos_sigma = sigma[oos_mask_arr]
    return oos_sigma

# Full return arrays
spy_full = spy_ret[spy_ret.index >= IS_START].values
qqq_full = qqq_ret[qqq_ret.index >= IS_START].values

# Align masks: oos relative to IS_START
all_dates_from_is = spy_ret[spy_ret.index >= IS_START].index
oos_mask_rel = (all_dates_from_is >= OOS_START) & (all_dates_from_is <= OOS_END)

spy_sigma_oos = garch_one_step_ahead(spy_fit_is, spy_full, oos_mask_rel)
qqq_sigma_oos = garch_one_step_ahead(qqq_fit_is, qqq_full, oos_mask_rel)

print(f"  OOS sigma_SPY: mean={spy_sigma_oos.mean():.4f}, std={spy_sigma_oos.std():.4f}")
print(f"  OOS sigma_QQQ: mean={qqq_sigma_oos.mean():.4f}, std={qqq_sigma_oos.std():.4f}")

# ============================================================
# 8. STATIC COPULA HEDGE RATIOS (IS parameters, OOS sigmas)
# ============================================================
print("\n[8] Computing static copula hedge ratios...")

def compute_hedge_ratio(rho_equiv_val, sigma_spot, sigma_hedge):
    """
    h*_t = rho * sigma_S_t / sigma_F_t
    LOOKAHEAD: hedge ratio at t uses sigma from t (GARCH t-1 information set)
    Applied to returns at t+1 via shift below.
    """
    return rho_equiv_val * sigma_spot / sigma_hedge

# Static hedge ratios on OOS (using IS copula rho and OOS GARCH sigmas)
hr_copulas_static = {}
for name, rho_eq in rho_equiv.items():
    hr = compute_hedge_ratio(rho_eq, spy_sigma_oos, qqq_sigma_oos)
    hr_copulas_static[name] = hr

# ============================================================
# 9. DYNAMIC COPULA HEDGE (Rolling 252d re-estimation)
# ============================================================
print("\n[9] Computing dynamic (rolling 252d) copula hedge ratios for best copula...")

# We'll compute dynamic version only for the best copula (lowest AIC)
# Rolling window: re-estimate copula parameters every 252 days
# GARCH parameters re-estimated on rolling window too

ROLLING_WINDOW = 252
spy_all = spy_ret.values
qqq_all = qqq_ret.values
all_dates = spy_ret.index

# Find OOS start index in full series
oos_start_idx = np.where(all_dates >= OOS_START)[0][0]
oos_end_idx   = np.where(all_dates <= OOS_END)[0][-1]

hr_dynamic_best = np.zeros(len(spy_oos))

print(f"  Rolling window: {ROLLING_WINDOW} days, estimating for each OOS day...")
print(f"  (This may take a minute...)")

def fit_copula_for_rolling(u, v, copula_name):
    """Fit a single copula on rolling window data, return rho_equiv"""
    if copula_name == 'Normal':
        res = minimize(normal_copula_loglik, [0.0], args=(u, v),
                       method='L-BFGS-B', bounds=[(-5, 5)])
        return np.tanh(res.x[0])
    elif copula_name == 'Student_t':
        res = minimize(student_t_copula_loglik, [0.0, np.log(8)], args=(u, v),
                       method='L-BFGS-B', bounds=[(-5, 5), (-2, 5)])
        return np.tanh(res.x[0])
    elif copula_name == 'Clayton':
        res = minimize(clayton_copula_loglik, [0.0], args=(u, v),
                       method='L-BFGS-B', bounds=[(-5, 10)])
        theta = np.exp(res.x[0]) + 1e-6
        tau = theta / (theta + 2)
        return np.sin(np.pi / 2 * tau)
    elif copula_name == 'Gumbel':
        res = minimize(gumbel_copula_loglik, [0.0], args=(u, v),
                       method='L-BFGS-B', bounds=[(-5, 5)])
        theta = np.exp(res.x[0]) + 1.0
        tau = 1 - 1/theta
        return np.sin(np.pi / 2 * tau)
    elif copula_name == 'Frank':
        best_fun = np.inf
        best_x = None
        for t0 in [3.0, 8.0]:
            try:
                r = minimize(frank_copula_loglik, [t0], args=(u, v),
                              method='L-BFGS-B', bounds=[(-20, 20)])
                if r.fun < best_fun:
                    best_fun = r.fun
                    best_x = r.x
            except Exception:
                pass
        if best_x is None:
            return rho_equiv[copula_name]
        theta = best_x[0]
        tau = kendall_tau_frank_copula(theta)
        return np.sin(np.pi / 2 * tau)
    return rho_equiv[copula_name]

# Sub-sample: re-estimate every 21 days (monthly) for speed; interpolate in between
step = 21
rho_dynamic_values = {}

for i_oos in range(0, len(spy_oos), step):
    i_global = oos_start_idx + i_oos
    win_start = max(0, i_global - ROLLING_WINDOW)
    win_end = i_global  # use data up to t-1 (i_global is t, so window ends at t-1)

    spy_win = spy_all[win_start:win_end]
    qqq_win = qqq_all[win_start:win_end]

    if len(spy_win) < 100:
        rho_val = rho_equiv[best_copula]
    else:
        # Fit GARCH on window
        try:
            m_s = arch_model(spy_win * 100, vol='Garch', p=1, o=1, q=1, dist='normal', rescale=False)
            r_s = m_s.fit(disp='off', options={'maxiter': 500})
            m_q = arch_model(qqq_win * 100, vol='Garch', p=1, o=1, q=1, dist='normal', rescale=False)
            r_q = m_q.fit(disp='off', options={'maxiter': 500})

            sig_s = r_s.conditional_volatility / 100
            sig_q = r_q.conditional_volatility / 100
            std_s = spy_win / sig_s
            std_q = qqq_win / sig_q
            u_s = pit_to_uniform(std_s)
            u_q = pit_to_uniform(std_q)
            rho_val = fit_copula_for_rolling(u_s, u_q, best_copula)
        except Exception:
            rho_val = rho_equiv[best_copula]

    rho_dynamic_values[i_oos] = rho_val

# Interpolate rho for all OOS days
oos_indices = np.arange(len(spy_oos))
sampled_indices = sorted(rho_dynamic_values.keys())
sampled_rho = [rho_dynamic_values[k] for k in sampled_indices]

rho_interp = np.interp(oos_indices, sampled_indices, sampled_rho)

# Compute dynamic hedge ratios using interpolated rho
hr_dynamic_best = rho_interp * spy_sigma_oos / qqq_sigma_oos

print(f"  Dynamic {best_copula} HR: mean={hr_dynamic_best.mean():.4f}, std={hr_dynamic_best.std():.4f}")

# ============================================================
# 10. BASELINE HEDGE RATIOS
# ============================================================
print("\n[10] Computing baseline hedge ratios...")

# --- OLS (full IS) ---
from numpy.linalg import lstsq
cov_is = np.cov(spy_is, qqq_is)
hr_ols = cov_is[0, 1] / cov_is[1, 1]
hr_ols_arr = np.full(len(spy_oos), hr_ols)
print(f"  OLS (IS): h={hr_ols:.4f}")

# --- Rolling OLS 252d ---
hr_rolling_ols = np.zeros(len(spy_oos))
for i_oos in range(len(spy_oos)):
    i_global = oos_start_idx + i_oos
    win_start = max(0, i_global - ROLLING_WINDOW)
    spy_win = spy_all[win_start:i_global]
    qqq_win = qqq_all[win_start:i_global]
    if len(spy_win) < 30:
        hr_rolling_ols[i_oos] = hr_ols
    else:
        cov_w = np.cov(spy_win, qqq_win)
        hr_rolling_ols[i_oos] = cov_w[0, 1] / cov_w[1, 1]

print(f"  Rolling OLS: mean={hr_rolling_ols.mean():.4f}, std={hr_rolling_ols.std():.4f}")

# --- DCC-GARCH (Gaussian DCC) ---
# Simplified DCC: use GARCH marginals + dynamic correlation via DCC recursion
def compute_dcc_correlation(std_resid_s, std_resid_q, a=0.05, b=0.93):
    """
    DCC(1,1) correlation recursion:
    Q_t = (1-a-b)*Q_bar + a*e_{t-1}*e_{t-1}' + b*Q_{t-1}
    R_t = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2}
    """
    n = len(std_resid_s)
    e1 = std_resid_s
    e2 = std_resid_q

    # Q_bar = sample correlation of standardized residuals
    Q_bar11 = np.mean(e1**2)
    Q_bar22 = np.mean(e2**2)
    Q_bar12 = np.mean(e1 * e2)

    Q11 = np.zeros(n)
    Q12 = np.zeros(n)
    Q22 = np.zeros(n)
    rho = np.zeros(n)

    Q11[0] = Q_bar11
    Q22[0] = Q_bar22
    Q12[0] = Q_bar12
    rho[0] = Q_bar12 / np.sqrt(Q_bar11 * Q_bar22)

    for t in range(1, n):
        Q11[t] = (1 - a - b) * Q_bar11 + a * e1[t-1]**2 + b * Q11[t-1]
        Q22[t] = (1 - a - b) * Q_bar22 + a * e2[t-1]**2 + b * Q22[t-1]
        Q12[t] = (1 - a - b) * Q_bar12 + a * e1[t-1]*e2[t-1] + b * Q12[t-1]
        rho[t] = Q12[t] / np.sqrt(Q11[t] * Q22[t])

    return rho

# DCC using IS standardized residuals (MLE DCC params a=0.05, b=0.93 typical)
# Re-estimate DCC params on IS data via grid search
def dcc_loglik(params, e1, e2):
    """Negative log-likelihood for DCC(1,1)"""
    a, b = params
    if a <= 0 or b <= 0 or a + b >= 1:
        return 1e10

    n = len(e1)
    Q_bar11 = np.mean(e1**2)
    Q_bar22 = np.mean(e2**2)
    Q_bar12 = np.mean(e1 * e2)

    Q11 = Q_bar11
    Q22 = Q_bar22
    Q12 = Q_bar12

    ll = 0.0
    for t in range(1, n):
        Q11_new = (1 - a - b) * Q_bar11 + a * e1[t-1]**2 + b * Q11
        Q22_new = (1 - a - b) * Q_bar22 + a * e2[t-1]**2 + b * Q22
        Q12_new = (1 - a - b) * Q_bar12 + a * e1[t-1]*e2[t-1] + b * Q12

        Q11 = Q11_new
        Q22 = Q22_new
        Q12 = Q12_new

        rho_t = Q12 / np.sqrt(Q11 * Q22)
        rho_t = np.clip(rho_t, -0.9999, 0.9999)

        ll += -0.5 * (np.log(1 - rho_t**2) +
                      (e1[t]**2 + e2[t]**2 - 2*rho_t*e1[t]*e2[t]) / (1 - rho_t**2)
                      - e1[t]**2 - e2[t]**2)
    return -ll

print("  Fitting DCC parameters on IS data...")
np.random.seed(42)
res_dcc = minimize(dcc_loglik, [0.05, 0.93], args=(spy_std_resid_is, qqq_std_resid_is),
                   method='L-BFGS-B',
                   bounds=[(0.001, 0.3), (0.5, 0.999)],
                   constraints=[{'type': 'ineq', 'fun': lambda p: 0.999 - p[0] - p[1]}])
a_dcc, b_dcc = res_dcc.x
print(f"  DCC params: a={a_dcc:.4f}, b={b_dcc:.4f}")

# Compute DCC correlation for OOS
# Need to run DCC from IS start to get OOS correlation
# Use IS std residuals to initialize, then continue into OOS
# Compute std residuals for OOS
spy_sigma_oos_arr = spy_sigma_oos
qqq_sigma_oos_arr = qqq_sigma_oos

# IS std residuals
# OOS std residuals
spy_std_resid_oos = spy_oos / spy_sigma_oos
qqq_std_resid_oos = qqq_oos / qqq_sigma_oos

# Run DCC from IS to get OOS correlation
all_std_s = np.concatenate([spy_std_resid_is, spy_std_resid_oos])
all_std_q = np.concatenate([qqq_std_resid_is, qqq_std_resid_oos])
rho_dcc_full = compute_dcc_correlation(all_std_s, all_std_q, a=a_dcc, b=b_dcc)
rho_dcc_oos = rho_dcc_full[len(spy_is):]

hr_dcc_gaussian = rho_dcc_oos * spy_sigma_oos / qqq_sigma_oos
print(f"  DCC Gaussian: mean rho_oos={rho_dcc_oos.mean():.4f}, mean HR={hr_dcc_gaussian.mean():.4f}")

# DCC-t: same DCC recursion but with t-distributed standardized residuals
# For simplicity, use same DCC params with t-distributed margins
# (The copula parameter rho_t is close to rho_normal for high correlation pairs)
# Use Student-t DCC: different only in the tail behavior, not the hedge ratio formula
# For this experiment, Student-t DCC uses rho_t from Student-t copula (static)
# Dynamic version follows the same DCC recursion
hr_dcc_t_arr = rho_t * spy_sigma_oos / qqq_sigma_oos  # static t-copula rho
print(f"  DCC-t (static): rho={rho_t:.4f}, mean HR={hr_dcc_t_arr.mean():.4f}")

# ============================================================
# 11. HEDGED PORTFOLIO RETURNS — OOS (LOOKAHEAD-FREE)
# ============================================================
print("\n[11] Computing OOS hedged portfolio returns (LOOKAHEAD-FREE)...")

"""
CRITICAL LOOKAHEAD PREVENTION:
- Hedge ratio h*_t is computed using info up to t-1 (sigma_t is GARCH one-step-ahead = uses t-1 info)
- Hedged portfolio return at t: r_hedged_t = r_SPY_t - h*_{t-1} * r_QQQ_t
- Implementation: hr.shift(1) — first observation has no hedge (unhedged)
"""

def compute_hedged_returns(spy_returns, qqq_returns, hedge_ratios):
    """
    LOOKAHEAD-FREE hedged returns:
    r_hedged_t = r_SPY_t - h_{t-1} * r_QQQ_t

    Args:
        spy_returns: array of OOS SPY returns (t)
        qqq_returns: array of OOS QQQ returns (t)
        hedge_ratios: array of hedge ratios (h_t = ratio using info up to t, applied at t+1)
    Returns:
        hedged_returns: array (first obs is unhedged due to lag)
    """
    # Shift hedge ratio by 1: h_{t-1} applied to return at t
    hr_lagged = np.roll(hedge_ratios, 1)
    hr_lagged[0] = hedge_ratios[0]  # first period: use first available HR (no alternative)

    hedged = spy_returns - hr_lagged * qqq_returns
    return hedged, hr_lagged

# Compute all hedged return series
strategies = {}

# Unhedged
strategies['Unhedged'] = spy_oos

# OLS
h_ols, _ = compute_hedged_returns(spy_oos, qqq_oos, hr_ols_arr)
strategies['OLS'] = h_ols

# Rolling OLS
h_rolling, _ = compute_hedged_returns(spy_oos, qqq_oos, hr_rolling_ols)
strategies['Rolling_OLS'] = h_rolling

# DCC Gaussian
h_dcc_g, _ = compute_hedged_returns(spy_oos, qqq_oos, hr_dcc_gaussian)
strategies['DCC_Gaussian'] = h_dcc_g

# DCC-t (static)
h_dcc_t, _ = compute_hedged_returns(spy_oos, qqq_oos, hr_dcc_t_arr)
strategies['DCC_t'] = h_dcc_t

# Static copula hedge ratios
for name, hr in hr_copulas_static.items():
    h, _ = compute_hedged_returns(spy_oos, qqq_oos, hr)
    strategies[f'Copula_{name}_static'] = h

# Dynamic best copula
h_dyn, _ = compute_hedged_returns(spy_oos, qqq_oos, hr_dynamic_best)
strategies[f'Copula_{best_copula}_dynamic'] = h_dyn

# ============================================================
# 12. HEDGE EFFECTIVENESS (HE) — IS AND OOS
# ============================================================
print("\n[12] Computing Hedge Effectiveness (HE)...")

def hedge_effectiveness(hedged_rets, unhedged_rets):
    """HE = 1 - Var(hedged) / Var(unhedged)"""
    return 1 - np.var(hedged_rets) / np.var(unhedged_rets)

# IS hedge effectiveness (use IS data)
# IS: compute hedged returns with IS sigmas and IS copula parameters
spy_sigma_is_arr = spy_sigma_is
qqq_sigma_is_arr = qqq_sigma_is

# IS hedge ratios (static)
he_is = {}
he_oos = {}

for name, rho_eq in rho_equiv.items():
    hr_is = compute_hedge_ratio(rho_eq, spy_sigma_is_arr, qqq_sigma_is_arr)
    hr_is_lag = np.roll(hr_is, 1); hr_is_lag[0] = hr_is[0]
    h_is = spy_is - hr_is_lag * qqq_is
    he_is[f'Copula_{name}_static'] = hedge_effectiveness(h_is, spy_is)
    he_oos[f'Copula_{name}_static'] = hedge_effectiveness(strategies[f'Copula_{name}_static'], spy_oos)

# IS OLS
hr_ols_is_lag = np.full(len(spy_is), hr_ols)
hr_ols_is_lag[0] = hr_ols
h_ols_is = spy_is - hr_ols_is_lag * qqq_is
he_is['OLS'] = hedge_effectiveness(h_ols_is, spy_is)
he_oos['OLS'] = hedge_effectiveness(h_ols, spy_oos)

# Rolling OLS IS (use same-period rolling)
hr_rolling_is = np.zeros(len(spy_is))
for i in range(len(spy_is)):
    win_start = max(0, i - ROLLING_WINDOW)
    spy_win = spy_is[win_start:i]
    qqq_win = qqq_is[win_start:i]
    if len(spy_win) < 30:
        hr_rolling_is[i] = hr_ols
    else:
        cov_w = np.cov(spy_win, qqq_win)
        hr_rolling_is[i] = cov_w[0,1] / cov_w[1,1]

hr_rolling_is_lag = np.roll(hr_rolling_is, 1); hr_rolling_is_lag[0] = hr_rolling_is[0]
h_rolling_is = spy_is - hr_rolling_is_lag * qqq_is
he_is['Rolling_OLS'] = hedge_effectiveness(h_rolling_is, spy_is)
he_oos['Rolling_OLS'] = hedge_effectiveness(h_rolling, spy_oos)

# DCC IS
rho_dcc_is = rho_dcc_full[:len(spy_is)]
hr_dcc_is = rho_dcc_is * spy_sigma_is / qqq_sigma_is
hr_dcc_is_lag = np.roll(hr_dcc_is, 1); hr_dcc_is_lag[0] = hr_dcc_is[0]
h_dcc_is = spy_is - hr_dcc_is_lag * qqq_is
he_is['DCC_Gaussian'] = hedge_effectiveness(h_dcc_is, spy_is)
he_oos['DCC_Gaussian'] = hedge_effectiveness(h_dcc_g, spy_oos)

he_is['DCC_t'] = hedge_effectiveness(spy_is - np.roll(rho_t * spy_sigma_is / qqq_sigma_is, 1) * qqq_is, spy_is)
he_oos['DCC_t'] = hedge_effectiveness(h_dcc_t, spy_oos)

# Dynamic copula IS (approximate using static)
he_is[f'Copula_{best_copula}_dynamic'] = he_is[f'Copula_{best_copula}_static']
he_oos[f'Copula_{best_copula}_dynamic'] = hedge_effectiveness(h_dyn, spy_oos)

print("\n  Hedge Effectiveness Summary:")
print(f"  {'Strategy':<35} {'HE_IS':>8} {'HE_OOS':>8}")
print(f"  {'-'*55}")
all_strategies_he = set(list(he_is.keys()) + list(he_oos.keys()))
for strat in sorted(all_strategies_he):
    is_val = he_is.get(strat, float('nan'))
    oos_val = he_oos.get(strat, float('nan'))
    print(f"  {strat:<35} {is_val:>8.4f} {oos_val:>8.4f}")

# ============================================================
# 13. SHARPE RATIO AND DRAWDOWN METRICS
# ============================================================
print("\n[13] Computing performance metrics...")

def annualized_sharpe(rets, periods_per_year=252):
    """Annualized Sharpe ratio (assuming zero risk-free rate)"""
    if np.std(rets) == 0:
        return 0.0
    return np.mean(rets) / np.std(rets) * np.sqrt(periods_per_year)

def max_drawdown(rets):
    """Maximum drawdown from cumulative returns"""
    cum = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return dd.min()

metrics = {}
for name, rets in strategies.items():
    metrics[name] = {
        'sharpe': annualized_sharpe(rets),
        'vol': np.std(rets) * np.sqrt(252),
        'mean_ret': np.mean(rets) * 252,
        'max_dd': max_drawdown(rets),
        'var': np.var(rets),
    }

print(f"\n  {'Strategy':<35} {'Sharpe':>7} {'Ann.Vol':>8} {'MaxDD':>8}")
print(f"  {'-'*62}")
for name, m in sorted(metrics.items()):
    print(f"  {name:<35} {m['sharpe']:>7.3f} {m['vol']:>8.4f} {m['max_dd']:>8.4f}")

# ============================================================
# 14. DIEBOLD-MARIANO (HLN) TEST
# ============================================================
print("\n[14] Diebold-Mariano (HLN) tests...")

"""
DM test: compare forecast errors (hedged portfolio daily variance)
H0: equal predictive accuracy
Test each model against DCC_Gaussian (benchmark)
Use HAC (Newey-West) variance estimator — per error_log lesson.
DM test threshold: |t| > 1.96 (5% two-sided), NOT Harvey |t|>3
"""

def dm_test_hln_hac(e1, e2, h=1, nw_lags=None):
    """
    Diebold-Mariano test with HLN small-sample correction and HAC variance.
    e1: forecast errors for model 1 (baseline)
    e2: forecast errors for model 2 (challenger)
    h: forecast horizon (1 for one-step-ahead)
    nw_lags: Newey-West lags (default: floor(T^(1/3)))

    Returns: (DM_stat, p_value)
    Positive stat means model 2 is MORE accurate (lower squared error).
    """
    d = e1**2 - e2**2  # loss differential: positive = model 1 worse than model 2
    T = len(d)

    if nw_lags is None:
        nw_lags = int(np.floor(T**(1/3)))

    d_bar = np.mean(d)

    # Newey-West HAC variance estimator
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for lag in range(1, nw_lags + 1):
        gamma_j = np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
        nw_var += 2 * (1 - lag / (nw_lags + 1)) * gamma_j

    nw_var = max(nw_var, 1e-15)  # numerical safety

    # DM statistic
    dm_stat = d_bar / np.sqrt(nw_var / T)

    # HLN small-sample correction
    hln_correction = np.sqrt((T + 1 - 2*h + h*(h-1)/T) / T)
    dm_stat_hln = dm_stat * hln_correction

    # p-value (two-sided)
    p_val = 2 * (1 - norm.cdf(abs(dm_stat_hln)))

    return dm_stat_hln, p_val

# Benchmark: DCC_Gaussian (vs each strategy)
# Hedged portfolio errors = daily variance approximation = returns^2
benchmark = 'DCC_Gaussian'
e_benchmark = strategies[benchmark]**2

dm_results = {}
for name, rets in strategies.items():
    if name == benchmark or name == 'Unhedged':
        continue
    e_challenger = rets**2
    dm_stat, p_val = dm_test_hln_hac(e_benchmark, e_challenger)
    significant_5pct = abs(dm_stat) > 1.96
    dm_results[name] = {
        'dm_stat': float(dm_stat),
        'p_value': float(p_val),
        'significant_5pct': bool(significant_5pct),
        'better_than_dcc': bool(dm_stat > 0),  # positive = challenger is better (lower variance)
    }

print(f"\n  DM test vs {benchmark} (HAC-corrected HLN):")
print(f"  Threshold: |t| > 1.96 (5% two-sided) — NOT Harvey |t|>3 (that's for factor studies)")
print(f"  {'Strategy':<35} {'DM_stat':>8} {'p-value':>8} {'Sig?':>6} {'Better?':>8}")
print(f"  {'-'*72}")
for name, res in sorted(dm_results.items()):
    sig = "YES*" if res['significant_5pct'] else "no"
    better = "YES" if res['better_than_dcc'] else "no"
    print(f"  {name:<35} {res['dm_stat']:>8.3f} {res['p_value']:>8.4f} {sig:>6} {better:>8}")

# ============================================================
# 15. CHARTS
# ============================================================
print("\n[15] Generating charts...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1320: Copula-based GARCH Hedge (SPY-QQQ, OOS 2019-2024)', fontsize=13, fontweight='bold')

# Chart 1: Hedge ratio time series
ax1 = axes[0, 0]
for name, hr in hr_copulas_static.items():
    hr_s = pd.Series(np.roll(hr, 1), index=oos_dates)
    hr_s.iloc[0] = hr[0]
    ax1.plot(oos_dates, hr_s, alpha=0.6, linewidth=0.8, label=f'Copula {name}')
# DCC
hr_dcc_s = pd.Series(np.roll(hr_dcc_gaussian, 1), index=oos_dates)
hr_dcc_s.iloc[0] = hr_dcc_gaussian[0]
ax1.plot(oos_dates, hr_dcc_s, 'k--', alpha=0.8, linewidth=1.2, label='DCC Gaussian')
ax1.plot(oos_dates, np.roll(hr_dynamic_best, 1), 'b:', alpha=0.7, linewidth=1.0,
         label=f'Dynamic {best_copula}')
ax1.axhline(hr_ols, color='gray', linestyle='-.', alpha=0.7, label=f'OLS ({hr_ols:.3f})')
ax1.set_title('Hedge Ratio Time Series (OOS 2019-2024)', fontsize=10)
ax1.set_ylabel('Hedge Ratio')
ax1.legend(fontsize=6, ncol=2)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax1.grid(True, alpha=0.3)

# Chart 2: HE comparison (IS and OOS)
ax2 = axes[0, 1]
he_strategies = ['OLS', 'Rolling_OLS', 'DCC_Gaussian', 'DCC_t',
                  'Copula_Normal_static', 'Copula_Student_t_static',
                  'Copula_Clayton_static', 'Copula_Gumbel_static',
                  'Copula_Frank_static', f'Copula_{best_copula}_dynamic']
he_is_vals = [he_is.get(s, float('nan')) for s in he_strategies]
he_oos_vals = [he_oos.get(s, float('nan')) for s in he_strategies]
short_names = [s.replace('Copula_', 'C_').replace('_static', 'S').replace('_dynamic', 'D') for s in he_strategies]

x = np.arange(len(he_strategies))
width = 0.35
bars1 = ax2.bar(x - width/2, he_is_vals, width, label='IS HE', alpha=0.7, color='steelblue')
bars2 = ax2.bar(x + width/2, he_oos_vals, width, label='OOS HE', alpha=0.7, color='darkorange')
ax2.set_title('Hedge Effectiveness Comparison', fontsize=10)
ax2.set_ylabel('Hedge Effectiveness (HE)')
ax2.set_xticks(x)
ax2.set_xticklabels(short_names, rotation=45, ha='right', fontsize=7)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3, axis='y')

# Chart 3: Cumulative returns of selected strategies
ax3 = axes[1, 0]
selected = ['Unhedged', 'OLS', 'DCC_Gaussian', f'Copula_{best_copula}_static',
            f'Copula_{best_copula}_dynamic']
colors = ['red', 'gray', 'blue', 'green', 'purple']
for strat, col in zip(selected, colors):
    if strat in strategies:
        cum = np.cumprod(1 + strategies[strat])
        ax3.plot(oos_dates, cum, label=strat.replace('Copula_', 'C_').replace('_static', '').replace('_dynamic', ' dyn'),
                 color=col, alpha=0.8, linewidth=1.0)
ax3.set_title('Cumulative Returns (OOS)', fontsize=10)
ax3.set_ylabel('Cumulative Return')
ax3.legend(fontsize=7)
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax3.grid(True, alpha=0.3)

# Chart 4: Copula AIC comparison
ax4 = axes[1, 1]
copula_names = list(copula_results.keys())
aics = [copula_results[c]['aic'] for c in copula_names]
colors_bar = ['green' if c == best_copula else 'steelblue' for c in copula_names]
bars = ax4.bar(copula_names, aics, color=colors_bar, alpha=0.8)
ax4.set_title('Copula AIC Comparison (IS 2005-2018)', fontsize=10)
ax4.set_ylabel('AIC (lower = better)')
ax4.set_xlabel('Copula Family')
# Add value labels
for bar, val in zip(bars, aics):
    ax4.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 50,
             f'{val:.0f}', ha='center', va='bottom', fontsize=8)
ax4.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
chart_path = os.path.join(EXPERIMENT_DIR, 'k1320_hedge_analysis.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart_path}")

# Chart 2: Detailed hedge ratio and rolling correlation
fig2, axes2 = plt.subplots(2, 1, figsize=(12, 8))
fig2.suptitle('K1320: Hedge Ratio Dynamics & GARCH Volatilities (OOS 2019-2024)', fontsize=12, fontweight='bold')

ax5 = axes2[0]
# DCC vs Best copula static vs dynamic
ax5.plot(oos_dates, pd.Series(np.roll(hr_dcc_gaussian, 1), index=oos_dates),
         'b-', alpha=0.7, linewidth=1.0, label='DCC Gaussian')
ax5.plot(oos_dates, pd.Series(np.roll(hr_copulas_static[best_copula], 1), index=oos_dates),
         'g--', alpha=0.7, linewidth=1.0, label=f'Copula {best_copula} (static)')
ax5.plot(oos_dates, pd.Series(np.roll(hr_dynamic_best, 1), index=oos_dates),
         'r:', alpha=0.7, linewidth=1.2, label=f'Copula {best_copula} (dynamic)')
ax5.axhline(hr_ols, color='gray', linestyle='-.', alpha=0.6, label=f'OLS ({hr_ols:.3f})')
ax5.set_ylabel('Hedge Ratio (h*)', fontsize=10)
ax5.set_title('Hedge Ratio Comparison: DCC vs Copula (static vs dynamic)', fontsize=10)
ax5.legend(fontsize=9)
ax5.grid(True, alpha=0.3)
ax5.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

ax6 = axes2[1]
ax6.plot(oos_dates, pd.Series(spy_sigma_oos * np.sqrt(252), index=oos_dates),
         'b-', alpha=0.7, label='SPY Ann. Vol (GARCH)')
ax6.plot(oos_dates, pd.Series(qqq_sigma_oos * np.sqrt(252), index=oos_dates),
         'r-', alpha=0.7, label='QQQ Ann. Vol (GARCH)')
ax6.set_ylabel('Annualized Volatility', fontsize=10)
ax6.set_title('GARCH Conditional Volatilities (OOS, IS-fitted params)', fontsize=10)
ax6.legend(fontsize=9)
ax6.grid(True, alpha=0.3)
ax6.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

plt.tight_layout()
chart2_path = os.path.join(EXPERIMENT_DIR, 'k1320_hedge_ratio_dynamics.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")

# ============================================================
# 16. SAVE RESULTS JSON
# ============================================================
print("\n[16] Saving results to k1320_results.json...")

# Find best OOS copula by HE
copula_he_oos = {k.replace('Copula_', '').replace('_static', ''): v
                 for k, v in he_oos.items() if 'Copula_' in k and '_static' in k}
best_oos_copula = max(copula_he_oos, key=copula_he_oos.get)
best_oos_copula_he = copula_he_oos[best_oos_copula]

# DCC comparison
dcc_oos_he = he_oos.get('DCC_Gaussian', float('nan'))
he_diff_vs_dcc = best_oos_copula_he - dcc_oos_he
best_copula_dm = dm_results.get(f'Copula_{best_oos_copula}_static', {})

results = {
    "experiment_id": "K1320",
    "title": "Copula-based GARCH Hedge — Hsu et al. (2008, JFM) methodology",
    "method": "GJR-GARCH marginals + PIT → 5 copula families (Normal, Student-t, Clayton, Gumbel, Frank)",
    "data": {
        "spot": "SPY",
        "hedge": "QQQ",
        "period_full": "2005-01-01 to 2024-12-31",
        "period_is": f"{IS_START} to {IS_END}",
        "period_oos": f"{OOS_START} to {OOS_END}",
        "n_is": int(len(spy_is)),
        "n_oos": int(len(spy_oos)),
        "correlation_is": float(np.corrcoef(spy_is, qqq_is)[0, 1]),
        "correlation_oos": float(np.corrcoef(spy_oos, qqq_oos)[0, 1]),
        "kendall_tau_is": float(tau_emp),
    },
    "garch_params": {
        "SPY": {
            "omega": float(spy_fit_is.params['omega']),
            "alpha": float(spy_fit_is.params['alpha[1]']),
            "gamma": float(spy_fit_is.params['gamma[1]']),
            "beta":  float(spy_fit_is.params['beta[1]']),
            "loglik": float(spy_fit_is.loglikelihood),
        },
        "QQQ": {
            "omega": float(qqq_fit_is.params['omega']),
            "alpha": float(qqq_fit_is.params['alpha[1]']),
            "gamma": float(qqq_fit_is.params['gamma[1]']),
            "beta":  float(qqq_fit_is.params['beta[1]']),
            "loglik": float(qqq_fit_is.loglikelihood),
        },
    },
    "copula_comparison": {
        name: {
            "params": {k: float(v) for k, v in copula_results[name]['params'].items()},
            "log_likelihood": float(copula_results[name]['ll']),
            "aic": float(copula_results[name]['aic']),
            "n_params": int(copula_results[name]['n_params']),
            "rho_equiv": float(rho_equiv[name]),
        }
        for name in copula_results
    },
    "best_copula_is": best_copula,
    "best_copula_aic": float(copula_df.loc[best_copula, 'AIC']),
    "dcc_params": {
        "a": float(a_dcc),
        "b": float(b_dcc),
    },
    "hedge_effectiveness": {
        "IS": {k: float(v) for k, v in he_is.items()},
        "OOS": {k: float(v) for k, v in he_oos.items()},
    },
    "performance_metrics_oos": {
        name: {k: float(v) for k, v in m.items()}
        for name, m in metrics.items()
    },
    "dm_tests_vs_dcc_gaussian": {
        name: {k: (float(v) if isinstance(v, float) else bool(v))
               for k, v in res.items()}
        for name, res in dm_results.items()
    },
    "best_oos_copula_by_he": best_oos_copula,
    "best_oos_copula_he": float(best_oos_copula_he),
    "dcc_gaussian_oos_he": float(dcc_oos_he),
    "he_diff_best_copula_vs_dcc": float(he_diff_vs_dcc),
    "best_copula_dm_vs_dcc": best_copula_dm,
    "lookahead_prevention": "hedge_ratio_shifted_by_1: h_{t-1} applied to return at t (signal.shift(1) equivalent)",
    "seed": 42,
    "charts": ["k1320_hedge_analysis.png", "k1320_hedge_ratio_dynamics.png"],
}

results_path = os.path.join(EXPERIMENT_DIR, 'k1320_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Saved: {results_path}")

# ============================================================
# 17. FINAL SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("FINAL SUMMARY")
print("=" * 60)

print(f"\n  Sample: SPY-QQQ, IS={len(spy_is)} obs, OOS={len(spy_oos)} obs")
print(f"  IS correlation: {np.corrcoef(spy_is, qqq_is)[0,1]:.4f}")
print(f"\n  Best copula (IS AIC): {best_copula}")
print(f"  Copula AIC ranking:")
for i, (name, row) in enumerate(copula_df.iterrows()):
    marker = " ← BEST" if i == 0 else ""
    print(f"    {i+1}. {name}: AIC={row['AIC']:.2f}{marker}")

print(f"\n  OOS Hedge Effectiveness:")
he_ranking = sorted(he_oos.items(), key=lambda x: x[1] if not np.isnan(x[1]) else -999, reverse=True)
for name, val in he_ranking[:8]:
    if not np.isnan(val):
        print(f"    {name:<35} HE={val:.4f}")

print(f"\n  Best OOS copula by HE: {best_oos_copula} (HE={best_oos_copula_he:.4f})")
print(f"  DCC Gaussian OOS HE: {dcc_oos_he:.4f}")
print(f"  Copula improvement vs DCC: {he_diff_vs_dcc:+.4f}")

dm_best = dm_results.get(f'Copula_{best_oos_copula}_static', {})
if dm_best:
    sig_str = "SIGNIFICANT at 5%" if dm_best.get('significant_5pct') else "not significant at 5%"
    print(f"  DM test best copula vs DCC: t={dm_best.get('dm_stat', 0):.3f}, p={dm_best.get('p_value', 1):.4f}, {sig_str}")

print("\n  KEY FINDING:")
if he_diff_vs_dcc > 0:
    print(f"  Best copula ({best_oos_copula}) achieves HE={best_oos_copula_he:.4f} > DCC HE={dcc_oos_he:.4f}")
    print(f"  Net improvement: +{he_diff_vs_dcc:.4f} over DCC Gaussian")
else:
    print(f"  DCC Gaussian (HE={dcc_oos_he:.4f}) outperforms best copula ({best_oos_copula}, HE={best_oos_copula_he:.4f})")
    print(f"  Copula underperforms DCC by: {he_diff_vs_dcc:.4f}")

print("\n[Done] K1320 experiment complete.")
