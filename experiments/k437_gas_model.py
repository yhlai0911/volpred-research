"""
K437: Generalized Autoregressive Score (GAS) Model for Volatility
=================================================================
[提出: 用戶, 執行: Claude]

Research Questions:
1. Does GAS-t(1,1) outperform GARCH/GJR-GARCH for SPY volatility forecasting?
2. Does the Student-t score effectively downweight outliers vs Gaussian score?
3. How does GAS-t perform during extreme events (VIX>30) vs normal periods?
4. What degree-of-freedom (ν) does GAS-t estimate? (quantifies heavy tail severity)

Literature:
- Creal, Koopman, Lucas (2013) "Generalized Autoregressive Score Models
  with Applications" JASA 108(501):214-232
  → GAS framework: score function drives time-varying parameters
  → GARCH is a special case of GAS (Gaussian score = squared residual)
- Harvey (2013) "Dynamic Models for Volatility and Heavy Tails" Cambridge UP
  → Beta-t-EGARCH: score-driven vol model with Student-t
- Blazsek & Villatoro (2015) "Is Beta-t-EGARCH(1,1) superior to GARCH(1,1)?"
  → Score-driven models more robust to outliers

Prior Knowledge:
- K435: SPY has frequent structural breaks → score-driven may be more robust
- SPY kurtosis ≈ 15.4 (heavy tails) → t-distribution score more appropriate
- GJR-GARCH is current best baseline for SPY (multiple K-entries confirm)
- Knowledge base: Python has no mature GAS package → must self-implement

Why GAS over GARCH:
1. GARCH uses ε² to update variance → sensitive to outliers (one large shock
   disproportionately affects subsequent estimates)
2. GAS uses score (∂logL/∂f_t) to update → Student-t score automatically
   downweights outliers via (ν+1)/(ν-2+u) factor
3. When u = y²/σ² is large (outlier), the t-score caps its influence

GAS-t(1,1) Model:
  f_{t+1} = ω + α · s_t + β · f_t
  where f_t = log(σ²_t) (log-volatility ensures positivity)

  Gaussian score: s_t = (y_t²/σ²_t - 1)  → equivalent to EGARCH-like
  Student-t score: s_t = ((ν+1)/(ν-2+y_t²/σ²_t)) · y_t²/σ²_t - 1

Data: SPY 2005-01-01 to 2026-03-25 (yfinance)
OOS: 2023-01-01 to 2024-12-31
Window: 2000 trading days (rolling), refit every 21 days
RV proxy: squared returns (standard in GARCH literature)
"""

import numpy as np
import pandas as pd
import json
import time
import warnings
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

# ============================================================
# STEP 0: Data Download
# ============================================================
print("=" * 70)
print("K437: Generalized Autoregressive Score (GAS) Model for Volatility")
print("Literature: Creal, Koopman, Lucas (2013) JASA; Harvey (2013)")
print("=" * 70)

import yfinance as yf

print("\n[0] Downloading SPY data...")
spy = yf.download('SPY', start='2005-01-01', end='2026-03-26', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)

if 'Adj Close' in spy.columns:
    prices = spy['Adj Close'].dropna()
elif 'Close' in spy.columns:
    prices = spy['Close'].dropna()
else:
    raise ValueError("No price column found")

returns_pct = prices.pct_change().dropna() * 100  # percentage returns
print(f"  Total observations: {len(returns_pct)}")
print(f"  Date range: {returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
      f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")

# Download VIX for regime analysis
vix = yf.download('^VIX', start='2005-01-01', end='2026-03-26', progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_close = vix['Close'].dropna()
print(f"  VIX observations: {len(vix_close)}")

# ============================================================
# STEP 1: Descriptive Statistics (diagnostics first — CLAUDE.md rule 4)
# ============================================================
is_mask = returns_pct.index < '2023-01-01'
oos_mask = (returns_pct.index >= '2023-01-01') & (returns_pct.index < '2025-01-01')
r_is = returns_pct[is_mask].values
r_oos = returns_pct[oos_mask].values
dates_oos = returns_pct[oos_mask].index

print(f"\n[1] Descriptive Statistics")
print(f"  IS: {is_mask.sum()} obs, OOS: {oos_mask.sum()} obs")

desc_stats = {
    'mean': float(np.mean(r_is)),
    'std': float(np.std(r_is)),
    'skew': float(stats.skew(r_is)),
    'kurtosis': float(stats.kurtosis(r_is)),  # excess kurtosis
    'min': float(np.min(r_is)),
    'max': float(np.max(r_is)),
    'n_is': int(is_mask.sum()),
    'n_oos': int(oos_mask.sum())
}
print(f"  Mean: {desc_stats['mean']:.4f}%, Std: {desc_stats['std']:.4f}%")
print(f"  Skew: {desc_stats['skew']:.4f}, Excess Kurtosis: {desc_stats['kurtosis']:.4f}")
print(f"  Min: {desc_stats['min']:.4f}%, Max: {desc_stats['max']:.4f}%")

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, *_ = adfuller(r_is, maxlag=20)
print(f"  ADF: stat={adf_stat:.4f}, p={adf_p:.6f} "
      f"({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, *_ = het_arch(r_is, nlags=10)
print(f"  ARCH LM(10): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f} "
      f"({'ARCH effects present' if arch_lm_p < 0.05 else 'no ARCH effects'})")

# Ljung-Box test on squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_result = acorr_ljungbox(r_is**2, lags=10, return_df=True)
lb_stat = float(lb_result['lb_stat'].iloc[-1])
lb_p = float(lb_result['lb_pvalue'].iloc[-1])
print(f"  Ljung-Box Q(10) on r²: stat={lb_stat:.4f}, p={lb_p:.6f} "
      f"({'serial dependence' if lb_p < 0.05 else 'no dependence'})")

diagnostics = {
    'descriptive_stats': desc_stats,
    'adf_test': {'stat': float(adf_stat), 'p_value': float(adf_p),
                 'stationary': bool(adf_p < 0.05)},
    'arch_lm_test': {'stat': float(arch_lm_stat), 'p_value': float(arch_lm_p),
                     'arch_effects': bool(arch_lm_p < 0.05)},
    'ljung_box_r2': {'stat': lb_stat, 'p_value': lb_p,
                     'serial_dependence': bool(lb_p < 0.05)}
}

# ============================================================
# STEP 2: GAS Model Implementation
# ============================================================
print("\n[2] GAS Model Implementation (Creal et al. 2013)")


def gas_gaussian_loglik(params, returns):
    """
    GAS-Gaussian(1,1) negative log-likelihood.
    f_t = log(σ²_t), updated by Gaussian score.
    Gaussian score: s_t = y²/σ² - 1
    This is equivalent to an EGARCH-like model.
    """
    omega, alpha, beta = params
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns[:min(252, T)]))  # initialize with sample var

    ll = 0.0
    for t in range(T):
        sigma2 = np.exp(f[t])
        # Prevent numerical issues
        if sigma2 < 1e-10:
            sigma2 = 1e-10
        if sigma2 > 1e6:
            sigma2 = 1e6

        # Gaussian log-likelihood
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(sigma2) - 0.5 * returns[t]**2 / sigma2

        if t < T - 1:
            u = returns[t]**2 / sigma2
            score = u - 1  # Gaussian score for log-variance
            f[t + 1] = omega + alpha * score + beta * f[t]
            # Clamp to prevent explosion
            f[t + 1] = np.clip(f[t + 1], -20, 20)

    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


def gas_t_loglik(params, returns):
    """
    GAS-t(1,1) negative log-likelihood.
    f_t = log(σ²_t), updated by Student-t score.
    Student-t score: s_t = ((ν+1)/(ν-2+u)) · u - 1
    where u = y²/σ²

    Key insight: when u is large (outlier), (ν+1)/(ν-2+u) < 1,
    so the score is downweighted. This is the robustness advantage.
    """
    omega, alpha, beta, nu = params
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns[:min(252, T)]))

    ll = 0.0
    # Scale factor for Student-t: σ² · (ν-2)/ν
    for t in range(T):
        sigma2 = np.exp(f[t])
        if sigma2 < 1e-10:
            sigma2 = 1e-10
        if sigma2 > 1e6:
            sigma2 = 1e6

        # Student-t log-likelihood (scaled by sqrt(sigma2 * (nu-2)/nu) for variance = sigma2)
        # Using scipy's t distribution with scale = sqrt(sigma2 * (nu-2)/nu)
        scale = np.sqrt(sigma2 * (nu - 2) / nu) if nu > 2 else np.sqrt(sigma2)
        ll += stats.t.logpdf(returns[t], df=nu, scale=scale)

        if t < T - 1:
            u = returns[t]**2 / sigma2
            # Student-t score for log-variance
            # s_t = (ν+1)/(ν-2+u) · u - 1
            score = (nu + 1) / (nu - 2 + u) * u - 1
            f[t + 1] = omega + alpha * score + beta * f[t]
            f[t + 1] = np.clip(f[t + 1], -20, 20)

    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


def gas_t_forecast(params, returns):
    """Generate 1-step-ahead variance forecasts from GAS-t model."""
    omega, alpha, beta, nu = params
    T = len(returns)
    f = np.zeros(T + 1)
    f[0] = np.log(np.var(returns[:min(252, T)]))

    for t in range(T):
        sigma2 = np.exp(f[t])
        if sigma2 < 1e-10:
            sigma2 = 1e-10
        if sigma2 > 1e6:
            sigma2 = 1e6
        u = returns[t]**2 / sigma2
        score = (nu + 1) / (nu - 2 + u) * u - 1
        f[t + 1] = omega + alpha * score + beta * f[t]
        f[t + 1] = np.clip(f[t + 1], -20, 20)

    return np.exp(f)  # variance forecasts (T+1 values, last is 1-step-ahead)


def gas_gaussian_forecast(params, returns):
    """Generate 1-step-ahead variance forecasts from GAS-Gaussian model."""
    omega, alpha, beta = params
    T = len(returns)
    f = np.zeros(T + 1)
    f[0] = np.log(np.var(returns[:min(252, T)]))

    for t in range(T):
        sigma2 = np.exp(f[t])
        if sigma2 < 1e-10:
            sigma2 = 1e-10
        if sigma2 > 1e6:
            sigma2 = 1e6
        u = returns[t]**2 / sigma2
        score = u - 1
        f[t + 1] = omega + alpha * score + beta * f[t]
        f[t + 1] = np.clip(f[t + 1], -20, 20)

    return np.exp(f)


def fit_gas_t(returns, n_starts=5):
    """Fit GAS-t(1,1) with multiple starting points."""
    bounds = [
        (-5.0, 5.0),     # omega
        (0.001, 2.0),    # alpha
        (0.001, 0.999),  # beta
        (2.1, 100.0),    # nu (degrees of freedom)
    ]

    best_result = None
    best_nll = np.inf

    np.random.seed(42)
    starts = [
        [0.01, 0.05, 0.95, 8.0],
        [0.05, 0.10, 0.90, 5.0],
        [-0.01, 0.03, 0.97, 12.0],
        [0.1, 0.15, 0.85, 6.0],
        [0.0, 0.08, 0.92, 10.0],
    ]

    for i, x0 in enumerate(starts[:n_starts]):
        try:
            result = minimize(gas_t_loglik, x0, args=(returns,),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 500, 'ftol': 1e-10})
            if result.fun < best_nll and result.success:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    # Fallback: try Nelder-Mead if L-BFGS-B fails
    if best_result is None:
        try:
            result = minimize(gas_t_loglik, [0.01, 0.05, 0.95, 8.0],
                            args=(returns,), method='Nelder-Mead',
                            options={'maxiter': 2000})
            if np.isfinite(result.fun):
                best_result = result
                best_nll = result.fun
        except Exception:
            pass

    return best_result


def fit_gas_gaussian(returns, n_starts=5):
    """Fit GAS-Gaussian(1,1) with multiple starting points."""
    bounds = [
        (-5.0, 5.0),     # omega
        (0.001, 2.0),    # alpha
        (0.001, 0.999),  # beta
    ]

    best_result = None
    best_nll = np.inf

    starts = [
        [0.01, 0.05, 0.95],
        [0.05, 0.10, 0.90],
        [-0.01, 0.03, 0.97],
        [0.1, 0.15, 0.85],
        [0.0, 0.08, 0.92],
    ]

    for i, x0 in enumerate(starts[:n_starts]):
        try:
            result = minimize(gas_gaussian_loglik, x0, args=(returns,),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 500, 'ftol': 1e-10})
            if result.fun < best_nll and result.success:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        try:
            result = minimize(gas_gaussian_loglik, [0.01, 0.05, 0.95],
                            args=(returns,), method='Nelder-Mead',
                            options={'maxiter': 2000})
            if np.isfinite(result.fun):
                best_result = result
        except Exception:
            pass

    return best_result


# ============================================================
# STEP 3: GARCH/GJR Benchmarks (arch package)
# ============================================================
print("\n[3] Fitting benchmark GARCH models (arch package)...")
from arch import arch_model

# Setup
all_returns = returns_pct.values
all_dates = returns_pct.index

# Define OOS period
oos_start_idx = np.where(returns_pct.index >= '2023-01-01')[0][0]
oos_end_idx = np.where(returns_pct.index < '2025-01-01')[0][-1] + 1
n_oos = oos_end_idx - oos_start_idx
window = 2000
refit_every = 63  # quarterly refit for efficiency

print(f"  OOS: index {oos_start_idx} to {oos_end_idx-1} ({n_oos} days)")
print(f"  Window: {window}, Refit every: {refit_every} days")

# Align VIX with returns for regime analysis
vix_aligned = vix_close.reindex(returns_pct.index).ffill()

# Storage for forecasts
forecasts = {
    'garch_n': np.zeros(n_oos),
    'garch_t': np.zeros(n_oos),
    'gjr_n': np.zeros(n_oos),
    'gjr_t': np.zeros(n_oos),
    'gas_gaussian': np.zeros(n_oos),
    'gas_t': np.zeros(n_oos),
}
realized_var = np.zeros(n_oos)  # squared returns as proxy

# Track GAS-t parameters
gas_t_params_history = []
gas_gaussian_params_history = []
convergence_log = {
    'garch_n': [], 'garch_t': [], 'gjr_n': [], 'gjr_t': [],
    'gas_gaussian': [], 'gas_t': []
}

start_time = time.time()

# ============================================================
# STEP 4: Rolling OOS Forecasting
# ============================================================
print("\n[4] Rolling OOS forecasting...")

n_refits = 0
last_params = {
    'garch_n': None, 'garch_t': None, 'gjr_n': None, 'gjr_t': None,
    'gas_gaussian': None, 'gas_t': None
}

for i in range(n_oos):
    t = oos_start_idx + i
    realized_var[i] = all_returns[t]**2  # squared return as RV proxy

    need_refit = (i % refit_every == 0) or (i == 0)

    if need_refit:
        n_refits += 1
        train_start = t - window
        train_end = t
        train_data = all_returns[train_start:train_end]

        if i % (refit_every * 4) == 0:
            print(f"  Refit #{n_refits} at OOS day {i}/{n_oos} "
                  f"(date: {all_dates[t].strftime('%Y-%m-%d')})")

        # --- GARCH(1,1) Normal ---
        try:
            am = arch_model(train_data, vol='Garch', p=1, q=1, dist='Normal')
            res = am.fit(disp='off')
            last_params['garch_n'] = res
            convergence_log['garch_n'].append(int(res.convergence_flag))
        except Exception:
            convergence_log['garch_n'].append(-1)

        # --- GARCH(1,1) Student-t ---
        try:
            am = arch_model(train_data, vol='Garch', p=1, q=1, dist='StudentsT')
            res = am.fit(disp='off')
            last_params['garch_t'] = res
            convergence_log['garch_t'].append(int(res.convergence_flag))
        except Exception:
            convergence_log['garch_t'].append(-1)

        # --- GJR-GARCH(1,1) Normal ---
        try:
            am = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='Normal')
            res = am.fit(disp='off')
            last_params['gjr_n'] = res
            convergence_log['gjr_n'].append(int(res.convergence_flag))
        except Exception:
            convergence_log['gjr_n'].append(-1)

        # --- GJR-GARCH(1,1) Student-t ---
        try:
            am = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='StudentsT')
            res = am.fit(disp='off')
            last_params['gjr_t'] = res
            convergence_log['gjr_t'].append(int(res.convergence_flag))
        except Exception:
            convergence_log['gjr_t'].append(-1)

        # --- GAS-Gaussian(1,1) ---
        try:
            gas_g_res = fit_gas_gaussian(train_data, n_starts=5)
            if gas_g_res is not None:
                last_params['gas_gaussian'] = gas_g_res.x
                convergence_log['gas_gaussian'].append(0 if gas_g_res.success else 1)
                gas_gaussian_params_history.append({
                    'date': all_dates[t].strftime('%Y-%m-%d'),
                    'omega': float(gas_g_res.x[0]),
                    'alpha': float(gas_g_res.x[1]),
                    'beta': float(gas_g_res.x[2]),
                    'persistence': float(gas_g_res.x[2]),  # beta only for GAS
                    'nll': float(gas_g_res.fun),
                    'converged': bool(gas_g_res.success)
                })
            else:
                convergence_log['gas_gaussian'].append(-1)
        except Exception:
            convergence_log['gas_gaussian'].append(-1)

        # --- GAS-t(1,1) ---
        try:
            gas_t_res = fit_gas_t(train_data, n_starts=5)
            if gas_t_res is not None:
                last_params['gas_t'] = gas_t_res.x
                convergence_log['gas_t'].append(0 if gas_t_res.success else 1)
                gas_t_params_history.append({
                    'date': all_dates[t].strftime('%Y-%m-%d'),
                    'omega': float(gas_t_res.x[0]),
                    'alpha': float(gas_t_res.x[1]),
                    'beta': float(gas_t_res.x[2]),
                    'nu': float(gas_t_res.x[3]),
                    'persistence': float(gas_t_res.x[2]),
                    'nll': float(gas_t_res.fun),
                    'converged': bool(gas_t_res.success)
                })
            else:
                convergence_log['gas_t'].append(-1)
        except Exception:
            convergence_log['gas_t'].append(-1)

    # Generate 1-step-ahead forecasts using last fitted params
    # For GARCH models: use recursive forecast from arch
    train_start = t - window
    train_data_full = all_returns[train_start:t+1]  # include current obs for filtering

    # GARCH/GJR forecasts via arch filtering
    for model_name, dist, vol_o in [
        ('garch_n', 'Normal', 0), ('garch_t', 'StudentsT', 0),
        ('gjr_n', 'Normal', 1), ('gjr_t', 'StudentsT', 1)
    ]:
        try:
            res = last_params[model_name]
            if res is not None:
                # Use the fitted parameters to filter the full data up to t
                # and get 1-step forecast
                am = arch_model(train_data_full, vol='Garch', p=1, o=vol_o, q=1, dist=dist)
                filtered = am.fit(disp='off', starting_values=res.params)
                fc = filtered.forecast(horizon=1)
                forecasts[model_name][i] = fc.variance.iloc[-1, 0]
            else:
                forecasts[model_name][i] = np.nan
        except Exception:
            # Fallback: use unconditional variance
            forecasts[model_name][i] = np.var(train_data_full[-252:])

    # GAS-Gaussian forecast
    try:
        if last_params['gas_gaussian'] is not None:
            gp = last_params['gas_gaussian']
            var_path = gas_gaussian_forecast(gp, train_data_full)
            forecasts['gas_gaussian'][i] = var_path[-1]  # 1-step-ahead
        else:
            forecasts['gas_gaussian'][i] = np.nan
    except Exception:
        forecasts['gas_gaussian'][i] = np.var(train_data_full[-252:])

    # GAS-t forecast
    try:
        if last_params['gas_t'] is not None:
            gp = last_params['gas_t']
            var_path = gas_t_forecast(gp, train_data_full)
            forecasts['gas_t'][i] = var_path[-1]  # 1-step-ahead
        else:
            forecasts['gas_t'][i] = np.nan
    except Exception:
        forecasts['gas_t'][i] = np.var(train_data_full[-252:])

elapsed = time.time() - start_time
print(f"\n  Forecasting complete: {elapsed:.1f}s ({n_refits} refits)")

# ============================================================
# STEP 5: Convergence & Parameter Diagnostics
# ============================================================
print("\n[5] Convergence & Parameter Diagnostics")

convergence_summary = {}
for model_name, flags in convergence_log.items():
    if flags:
        n_success = sum(1 for f in flags if f == 0)
        n_total = len(flags)
        convergence_summary[model_name] = {
            'converged': n_success,
            'total': n_total,
            'rate': round(n_success / n_total * 100, 1)
        }
        print(f"  {model_name}: {n_success}/{n_total} converged ({convergence_summary[model_name]['rate']}%)")

# GAS-t parameter summary
if gas_t_params_history:
    nus = [p['nu'] for p in gas_t_params_history]
    alphas = [p['alpha'] for p in gas_t_params_history]
    betas = [p['beta'] for p in gas_t_params_history]

    gas_t_param_summary = {
        'nu_mean': float(np.mean(nus)),
        'nu_std': float(np.std(nus)),
        'nu_min': float(np.min(nus)),
        'nu_max': float(np.max(nus)),
        'alpha_mean': float(np.mean(alphas)),
        'alpha_std': float(np.std(alphas)),
        'beta_mean': float(np.mean(betas)),
        'beta_std': float(np.std(betas)),
        'persistence_mean': float(np.mean(betas)),
        'n_estimates': len(gas_t_params_history)
    }

    print(f"\n  GAS-t parameter summary:")
    print(f"    ν (degrees of freedom): mean={gas_t_param_summary['nu_mean']:.2f}, "
          f"std={gas_t_param_summary['nu_std']:.2f}, "
          f"range=[{gas_t_param_summary['nu_min']:.2f}, {gas_t_param_summary['nu_max']:.2f}]")
    print(f"    α (score weight): mean={gas_t_param_summary['alpha_mean']:.4f}, "
          f"std={gas_t_param_summary['alpha_std']:.4f}")
    print(f"    β (persistence): mean={gas_t_param_summary['beta_mean']:.4f}, "
          f"std={gas_t_param_summary['beta_std']:.4f}")

    # Check persistence < 1
    if gas_t_param_summary['beta_mean'] >= 0.999:
        print("  ⚠ WARNING: GAS-t persistence at boundary! Results may be unreliable.")
else:
    gas_t_param_summary = {}
    print("  ⚠ WARNING: No GAS-t parameters estimated!")

# ============================================================
# STEP 6: Forecast Evaluation (QLIKE, MSE, MAE)
# ============================================================
print("\n[6] Forecast Evaluation Metrics")

def qlike(realized, forecast):
    """QLIKE loss: L = log(h) + r²/h. Lower is better."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    h = forecast[valid]
    return float(np.mean(np.log(h) + r / h))

def mse(realized, forecast):
    """MSE loss: (r² - h)². Lower is better."""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean((realized[valid] - forecast[valid])**2))

def mae(realized, forecast):
    """MAE loss: |r² - h|. Lower is better."""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean(np.abs(realized[valid] - forecast[valid])))

metrics = {}
for name, fc in forecasts.items():
    valid_mask = np.isfinite(fc) & (fc > 0)
    if valid_mask.sum() < 10:
        print(f"  {name}: insufficient valid forecasts ({valid_mask.sum()})")
        continue

    m = {
        'qlike': qlike(realized_var, fc),
        'mse': mse(realized_var, fc),
        'mae': mae(realized_var, fc),
        'n_valid': int(valid_mask.sum())
    }
    metrics[name] = m
    print(f"  {name:15s}: QLIKE={m['qlike']:.6f}  MSE={m['mse']:.6f}  MAE={m['mae']:.6f} (n={m['n_valid']})")

# ============================================================
# STEP 7: Diebold-Mariano Tests
# ============================================================
print("\n[7] Diebold-Mariano Tests (GAS-t vs benchmarks)")


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 (equal predictive accuracy)
    loss1 - loss2: positive means model 2 is better
    Returns (DM stat, p-value, mean_diff)
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan, np.nan

    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(p_value), float(d_mean)


# QLIKE losses for each model
qlike_losses = {}
for name, fc in forecasts.items():
    valid = np.isfinite(fc) & (fc > 0) & (realized_var > 0)
    losses = np.full(n_oos, np.nan)
    losses[valid] = np.log(fc[valid]) + realized_var[valid] / fc[valid]
    qlike_losses[name] = losses

# MSE losses
mse_losses = {}
for name, fc in forecasts.items():
    valid = np.isfinite(fc)
    losses = np.full(n_oos, np.nan)
    losses[valid] = (realized_var[valid] - fc[valid])**2
    mse_losses[name] = losses

dm_results = {}
reference = 'gas_t'
for benchmark in ['garch_n', 'garch_t', 'gjr_n', 'gjr_t', 'gas_gaussian']:
    if benchmark not in qlike_losses or reference not in qlike_losses:
        continue

    # QLIKE DM test
    dm_stat_q, dm_p_q, dm_diff_q = dm_test(qlike_losses[benchmark], qlike_losses[reference])
    # MSE DM test
    dm_stat_m, dm_p_m, dm_diff_m = dm_test(mse_losses[benchmark], mse_losses[reference])

    dm_results[f'{reference}_vs_{benchmark}'] = {
        'qlike_dm_stat': dm_stat_q,
        'qlike_dm_p': dm_p_q,
        'qlike_diff': dm_diff_q,
        'qlike_gas_t_better': bool(dm_diff_q > 0) if np.isfinite(dm_diff_q) else None,
        'mse_dm_stat': dm_stat_m,
        'mse_dm_p': dm_p_m,
        'mse_diff': dm_diff_m,
        'mse_gas_t_better': bool(dm_diff_m > 0) if np.isfinite(dm_diff_m) else None,
    }

    q_sig = '***' if dm_p_q < 0.01 else ('**' if dm_p_q < 0.05 else ('*' if dm_p_q < 0.10 else ''))
    m_sig = '***' if dm_p_m < 0.01 else ('**' if dm_p_m < 0.05 else ('*' if dm_p_m < 0.10 else ''))
    q_dir = "GAS-t BETTER" if dm_diff_q > 0 else "benchmark BETTER"
    m_dir = "GAS-t BETTER" if dm_diff_m > 0 else "benchmark BETTER"

    print(f"  GAS-t vs {benchmark:15s}:")
    print(f"    QLIKE: DM={dm_stat_q:+.3f}, p={dm_p_q:.4f}{q_sig} ({q_dir})")
    print(f"    MSE:   DM={dm_stat_m:+.3f}, p={dm_p_m:.4f}{m_sig} ({m_dir})")

# ============================================================
# STEP 8: Regime Analysis (VIX>30 vs normal)
# ============================================================
print("\n[8] Regime Analysis: Extreme (VIX>30) vs Normal periods")

vix_oos = vix_aligned.iloc[oos_start_idx:oos_end_idx].values
high_vix_mask = vix_oos > 30
normal_mask = vix_oos <= 30

n_high = int(np.sum(high_vix_mask))
n_normal = int(np.sum(normal_mask))
print(f"  High VIX (>30) days: {n_high}, Normal days: {n_normal}")

regime_metrics = {}
for regime_name, mask in [('high_vix', high_vix_mask), ('normal', normal_mask)]:
    if np.sum(mask) < 5:
        print(f"  {regime_name}: insufficient data ({np.sum(mask)} days)")
        continue

    regime_metrics[regime_name] = {}
    print(f"\n  {regime_name} period ({np.sum(mask)} days):")
    for model_name, fc in forecasts.items():
        rv_sub = realized_var[mask]
        fc_sub = fc[mask]
        valid = np.isfinite(fc_sub) & (fc_sub > 0) & (rv_sub > 0)
        if valid.sum() < 3:
            continue

        q = float(np.mean(np.log(fc_sub[valid]) + rv_sub[valid] / fc_sub[valid]))
        m = float(np.mean((rv_sub[valid] - fc_sub[valid])**2))
        regime_metrics[regime_name][model_name] = {'qlike': q, 'mse': m}

    # Print comparison
    if regime_metrics[regime_name]:
        sorted_models = sorted(regime_metrics[regime_name].items(), key=lambda x: x[1]['qlike'])
        for rank, (name, m) in enumerate(sorted_models, 1):
            print(f"    #{rank} {name:15s}: QLIKE={m['qlike']:.6f}  MSE={m['mse']:.6f}")

# ============================================================
# STEP 9: Score Downweighting Analysis
# ============================================================
print("\n[9] Score Downweighting Analysis (key GAS-t advantage)")

# Demonstrate how GAS-t downweights outliers
if last_params['gas_t'] is not None and gas_t_params_history:
    nu_est = gas_t_param_summary['nu_mean']

    # Compare Gaussian vs t-score for different shock sizes
    print(f"\n  Using estimated ν = {nu_est:.2f}")
    print(f"  {'|return/σ|':>12s} {'Gaussian score':>16s} {'t-score':>12s} {'Downweight':>12s}")
    print(f"  {'-'*54}")

    score_comparison = []
    for shock in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        u = shock**2
        gaussian_score = u - 1
        t_score = (nu_est + 1) / (nu_est - 2 + u) * u - 1
        downweight = t_score / gaussian_score if gaussian_score > 0 else np.nan
        score_comparison.append({
            'shock_sigma': shock,
            'gaussian_score': float(gaussian_score),
            't_score': float(t_score),
            'downweight_ratio': float(downweight) if np.isfinite(downweight) else None
        })
        print(f"  {shock:12.1f}σ {gaussian_score:16.2f} {t_score:12.2f} {downweight:12.2%}")

    print(f"\n  Interpretation: At {shock:.0f}σ, GAS-t score is only "
          f"{downweight:.0%} of Gaussian score → outliers are heavily downweighted.")
else:
    score_comparison = []

# ============================================================
# STEP 10: Residual Diagnostics on GAS-t
# ============================================================
print("\n[10] GAS-t Residual Diagnostics")

if last_params['gas_t'] is not None:
    # Get standardized residuals from the last fitted GAS-t
    gp = last_params['gas_t']
    nu_final = gp[3]

    # Use OOS forecasts to compute standardized residuals
    valid_mask = np.isfinite(forecasts['gas_t']) & (forecasts['gas_t'] > 0)
    std_resid = np.zeros(n_oos)
    std_resid[valid_mask] = (all_returns[oos_start_idx:oos_end_idx][valid_mask] /
                              np.sqrt(forecasts['gas_t'][valid_mask]))
    std_resid[~valid_mask] = np.nan

    sr = std_resid[np.isfinite(std_resid)]

    resid_diag = {
        'mean': float(np.mean(sr)),
        'std': float(np.std(sr)),
        'skew': float(stats.skew(sr)),
        'kurtosis': float(stats.kurtosis(sr)),
    }
    print(f"  Standardized residuals: mean={resid_diag['mean']:.4f}, std={resid_diag['std']:.4f}")
    print(f"  Skew={resid_diag['skew']:.4f}, Excess Kurt={resid_diag['kurtosis']:.4f}")

    # ARCH LM on standardized residuals
    if len(sr) > 20:
        arch_resid_stat, arch_resid_p, *_ = het_arch(sr, nlags=5)
        resid_diag['arch_lm_stat'] = float(arch_resid_stat)
        resid_diag['arch_lm_p'] = float(arch_resid_p)
        resid_diag['remaining_arch'] = bool(arch_resid_p < 0.05)
        print(f"  ARCH LM(5) on residuals: stat={arch_resid_stat:.4f}, p={arch_resid_p:.4f} "
              f"({'REMAINING ARCH!' if arch_resid_p < 0.05 else 'clean'})")

    # Ljung-Box on squared standardized residuals
    if len(sr) > 20:
        lb_sq = acorr_ljungbox(sr**2, lags=10, return_df=True)
        lb_sq_stat = float(lb_sq['lb_stat'].iloc[-1])
        lb_sq_p = float(lb_sq['lb_pvalue'].iloc[-1])
        resid_diag['ljung_box_sq_stat'] = lb_sq_stat
        resid_diag['ljung_box_sq_p'] = lb_sq_p
        print(f"  Ljung-Box Q(10) on r²_std: stat={lb_sq_stat:.4f}, p={lb_sq_p:.4f}")
else:
    resid_diag = {}

# ============================================================
# STEP 11: Summary & Rankings
# ============================================================
print("\n" + "=" * 70)
print("[11] FINAL RANKINGS")
print("=" * 70)

# QLIKE ranking
if metrics:
    qlike_ranking = sorted(metrics.items(), key=lambda x: x[1]['qlike'])
    print("\n  QLIKE Ranking (lower is better — preferred loss for volatility):")
    for rank, (name, m) in enumerate(qlike_ranking, 1):
        marker = " ← GAS-t" if name == 'gas_t' else ""
        marker = " ← GAS-Gaussian" if name == 'gas_gaussian' else marker
        print(f"    #{rank} {name:15s}: QLIKE={m['qlike']:.6f}{marker}")

    # MSE ranking
    mse_ranking = sorted(metrics.items(), key=lambda x: x[1]['mse'])
    print("\n  MSE Ranking (lower is better):")
    for rank, (name, m) in enumerate(mse_ranking, 1):
        marker = " ← GAS-t" if name == 'gas_t' else ""
        marker = " ← GAS-Gaussian" if name == 'gas_gaussian' else marker
        print(f"    #{rank} {name:15s}: MSE={m['mse']:.6f}{marker}")

    # Best model
    best_qlike = qlike_ranking[0][0]
    best_mse = mse_ranking[0][0]
    print(f"\n  Best by QLIKE: {best_qlike}")
    print(f"  Best by MSE: {best_mse}")

    # GAS-t rank
    gas_t_qlike_rank = next((i+1 for i, (n, _) in enumerate(qlike_ranking) if n == 'gas_t'), None)
    gas_t_mse_rank = next((i+1 for i, (n, _) in enumerate(mse_ranking) if n == 'gas_t'), None)
    print(f"  GAS-t rank: QLIKE #{gas_t_qlike_rank}, MSE #{gas_t_mse_rank}")

# ============================================================
# STEP 12: Conclusions
# ============================================================
print("\n[12] Conclusions")

# Determine if GAS-t is significantly better than GJR-t (the typical best)
gas_vs_gjr_t = dm_results.get('gas_t_vs_gjr_t', {})
gas_vs_gjr_n = dm_results.get('gas_t_vs_gjr_n', {})

gas_t_significant_vs_gjr_t = (gas_vs_gjr_t.get('qlike_dm_p', 1) < 0.05 and
                               gas_vs_gjr_t.get('qlike_gas_t_better', False))
gas_t_significant_vs_gjr_n = (gas_vs_gjr_n.get('qlike_dm_p', 1) < 0.05 and
                               gas_vs_gjr_n.get('qlike_gas_t_better', False))

if gas_t_significant_vs_gjr_t:
    conclusion = "★★ GAS-t SIGNIFICANTLY outperforms GJR-t! Score-driven volatility is superior."
elif gas_t_significant_vs_gjr_n:
    conclusion = "★ GAS-t significantly outperforms GJR-N, but not GJR-t. Heavy tails matter more than score function."
elif gas_t_qlike_rank == 1:
    conclusion = "GAS-t has best QLIKE but NOT significantly better (DM p>0.05). Practically equivalent to GARCH family."
elif gas_t_qlike_rank <= 3:
    conclusion = "GAS-t competitive but does not beat GARCH family. Score-driven approach adds complexity without clear gain."
else:
    conclusion = "GAS-t underperforms standard GARCH. Possible implementation issue or model misspecification."

print(f"  {conclusion}")

# ============================================================
# STEP 13: Save Results
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'K437',
    'title': 'GAS-t(1,1) Score-Driven Volatility Model',
    'date': datetime.now(timezone.utc).isoformat(),
    'author': '[提出: 用戶, 執行: Claude]',
    'asset': 'SPY',
    'data_source': 'yfinance',
    'data_period': {
        'total': f"{returns_pct.index[0].strftime('%Y-%m-%d')} ~ {returns_pct.index[-1].strftime('%Y-%m-%d')}",
        'in_sample': f"{returns_pct.index[0].strftime('%Y-%m-%d')} ~ 2022-12-31",
        'out_of_sample': '2023-01-01 ~ 2024-12-31',
        'is_n': int(is_mask.sum()),
        'oos_n': int(oos_mask.sum()),
        'window': window,
        'refit_every': refit_every,
        'n_refits': n_refits
    },
    'literature': [
        'Creal, Koopman, Lucas (2013) "Generalized Autoregressive Score Models" JASA 108(501):214-232',
        'Harvey (2013) "Dynamic Models for Volatility and Heavy Tails" Cambridge UP',
    ],
    'methodology': {
        'models_compared': [
            'GARCH(1,1)-Normal', 'GARCH(1,1)-t',
            'GJR-GARCH(1,1)-Normal', 'GJR-GARCH(1,1)-t',
            'GAS-Gaussian(1,1)', 'GAS-t(1,1)'
        ],
        'gas_t_description': (
            'f_{t+1} = omega + alpha * s_t + beta * f_t, '
            'f_t = log(sigma^2_t), '
            's_t = (nu+1)/(nu-2+u) * u - 1, u = y^2/sigma^2. '
            'Student-t score automatically downweights outliers.'
        ),
        'rv_proxy': 'squared returns',
        'loss_functions': ['QLIKE', 'MSE', 'MAE'],
        'statistical_test': 'Diebold-Mariano (HAC variance)',
        'optimization': '5-start L-BFGS-B + Nelder-Mead fallback'
    },
    'diagnostics': diagnostics,
    'convergence': convergence_summary,
    'gas_t_parameters': gas_t_param_summary,
    'gas_t_parameter_history': gas_t_params_history,
    'gas_gaussian_parameter_history': gas_gaussian_params_history,
    'forecast_metrics': metrics,
    'rankings': {
        'by_qlike': [(name, m['qlike']) for name, m in sorted(metrics.items(), key=lambda x: x[1]['qlike'])],
        'by_mse': [(name, m['mse']) for name, m in sorted(metrics.items(), key=lambda x: x[1]['mse'])],
        'by_mae': [(name, m['mae']) for name, m in sorted(metrics.items(), key=lambda x: x[1]['mae'])],
        'gas_t_qlike_rank': gas_t_qlike_rank,
        'gas_t_mse_rank': gas_t_mse_rank,
    },
    'dm_tests': dm_results,
    'regime_analysis': {
        'n_high_vix': n_high,
        'n_normal': n_normal,
        'metrics_by_regime': regime_metrics
    },
    'score_downweighting': {
        'estimated_nu': gas_t_param_summary.get('nu_mean', None),
        'comparison': score_comparison,
        'interpretation': (
            f"With ν≈{gas_t_param_summary.get('nu_mean', 'N/A'):.1f}, "
            f"a 5σ shock receives {score_comparison[3]['downweight_ratio']:.0%} "
            f"of the Gaussian update weight"
        ) if score_comparison and len(score_comparison) > 3 else 'N/A'
    },
    'residual_diagnostics': resid_diag,
    'conclusion': conclusion,
    'limitations': [
        'RV proxy is squared returns (noisy); realized variance from 5-min data would be better',
        'GAS-t self-implemented (no established Python package for validation)',
        'Single asset (SPY) — generalizability to other assets unknown',
        'OOS period 2023-2024 is relatively calm — no extreme crisis like COVID',
        'Student-t score assumes symmetric tails; skewed-t extension not tested',
        'L-BFGS-B optimization may find local optima despite multiple starts',
    ],
    'elapsed_seconds': round(elapsed, 1)
}

output_path = 'experiments/k437_gas_model_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Results saved to {output_path}")
print(f"\n  CONCLUSION: {conclusion}")
print(f"  Elapsed: {elapsed:.1f}s")
