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

import sys
import numpy as np
import pandas as pd
import json
import time
import warnings
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

warnings.filterwarnings('ignore')

# ============================================================
# STEP 0: Data Download
# ============================================================
print("=" * 70)
print("K437: Generalized Autoregressive Score (GAS) Model for Volatility")
print("Literature: Creal, Koopman, Lucas (2013) JASA; Harvey (2013)")
print("=" * 70)
sys.stdout.flush()

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
sys.stdout.flush()

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
sys.stdout.flush()

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
sys.stdout.flush()


def gas_gaussian_filter(params, returns, f0=None):
    """
    Filter GAS-Gaussian(1,1): run through data, return log-variance path.
    Returns f array of length T+1 (last element is 1-step-ahead forecast).
    """
    omega, alpha, beta = params
    T = len(returns)
    f = np.zeros(T + 1)
    if f0 is not None:
        f[0] = f0
    else:
        f[0] = np.log(np.var(returns[:min(252, T)]) + 1e-10)

    for t in range(T):
        sigma2 = np.exp(f[t])
        sigma2 = max(sigma2, 1e-10)
        sigma2 = min(sigma2, 1e6)
        u = returns[t]**2 / sigma2
        score = u - 1  # Gaussian score for log-variance
        f[t + 1] = omega + alpha * score + beta * f[t]
        f[t + 1] = np.clip(f[t + 1], -20, 20)

    return f


def gas_t_filter(params, returns, f0=None):
    """
    Filter GAS-t(1,1): run through data, return log-variance path.
    Returns f array of length T+1 (last element is 1-step-ahead forecast).
    """
    omega, alpha, beta, nu = params
    T = len(returns)
    f = np.zeros(T + 1)
    if f0 is not None:
        f[0] = f0
    else:
        f[0] = np.log(np.var(returns[:min(252, T)]) + 1e-10)

    for t in range(T):
        sigma2 = np.exp(f[t])
        sigma2 = max(sigma2, 1e-10)
        sigma2 = min(sigma2, 1e6)
        u = returns[t]**2 / sigma2
        # Student-t score: downweights large u
        score = (nu + 1) / (nu - 2 + u) * u - 1
        f[t + 1] = omega + alpha * score + beta * f[t]
        f[t + 1] = np.clip(f[t + 1], -20, 20)

    return f


def gas_gaussian_loglik(params, returns):
    """GAS-Gaussian(1,1) negative log-likelihood."""
    omega, alpha, beta = params
    f = gas_gaussian_filter(params, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        sigma2 = np.exp(f[t])
        sigma2 = max(sigma2, 1e-10)
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(sigma2) - 0.5 * returns[t]**2 / sigma2
    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


def gas_t_loglik(params, returns):
    """GAS-t(1,1) negative log-likelihood."""
    omega, alpha, beta, nu = params
    f = gas_t_filter(params, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        sigma2 = np.exp(f[t])
        sigma2 = max(sigma2, 1e-10)
        # Student-t log-likelihood with variance = sigma2
        # scale = sqrt(sigma2 * (nu-2)/nu) so that Var = sigma2
        scale = np.sqrt(sigma2 * (nu - 2) / nu) if nu > 2 else np.sqrt(sigma2)
        ll += stats.t.logpdf(returns[t], df=nu, scale=scale)
    if np.isnan(ll) or np.isinf(ll):
        return 1e10
    return -ll


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
    starts = [
        [0.01, 0.05, 0.95, 8.0],
        [0.05, 0.10, 0.90, 5.0],
        [-0.01, 0.03, 0.97, 12.0],
        [0.1, 0.15, 0.85, 6.0],
        [0.0, 0.08, 0.92, 10.0],
    ]
    for x0 in starts[:n_starts]:
        try:
            result = minimize(gas_t_loglik, x0, args=(returns,),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 500, 'ftol': 1e-10})
            if result.fun < best_nll and result.success:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue
    if best_result is None:
        # Accept non-converged if finite
        for x0 in starts[:n_starts]:
            try:
                result = minimize(gas_t_loglik, x0, args=(returns,),
                                method='L-BFGS-B', bounds=bounds,
                                options={'maxiter': 500})
                if result.fun < best_nll and np.isfinite(result.fun):
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue
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
    for x0 in starts[:n_starts]:
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
        for x0 in starts[:n_starts]:
            try:
                result = minimize(gas_gaussian_loglik, x0, args=(returns,),
                                method='L-BFGS-B', bounds=bounds,
                                options={'maxiter': 500})
                if result.fun < best_nll and np.isfinite(result.fun):
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue
    return best_result


# ============================================================
# STEP 3: Setup OOS Framework
# ============================================================
print("\n[3] Setting up OOS rolling forecast framework...")
sys.stdout.flush()

from arch import arch_model

all_returns = returns_pct.values
all_dates = returns_pct.index

oos_start_idx = np.where(returns_pct.index >= '2023-01-01')[0][0]
oos_end_idx = np.where(returns_pct.index < '2025-01-01')[0][-1] + 1
n_oos = oos_end_idx - oos_start_idx
window = 2000
refit_every = 21

print(f"  OOS: index {oos_start_idx} to {oos_end_idx-1} ({n_oos} days)")
print(f"  Window: {window}, Refit every: {refit_every} days")
print(f"  Expected refits: {n_oos // refit_every + 1}")

# Align VIX
vix_aligned = vix_close.reindex(returns_pct.index).ffill()

# Storage
forecasts = {
    'garch_n': np.full(n_oos, np.nan),
    'garch_t': np.full(n_oos, np.nan),
    'gjr_n': np.full(n_oos, np.nan),
    'gjr_t': np.full(n_oos, np.nan),
    'gas_gaussian': np.full(n_oos, np.nan),
    'gas_t': np.full(n_oos, np.nan),
}
realized_var = np.zeros(n_oos)

gas_t_params_history = []
gas_gaussian_params_history = []
convergence_log = {k: [] for k in forecasts.keys()}

# ============================================================
# STEP 4: Rolling OOS — refit every 21 days, filter in batch
# ============================================================
print("\n[4] Rolling OOS forecasting (efficient batch approach)...")
sys.stdout.flush()

start_time = time.time()

# Identify refit points
refit_days = list(range(0, n_oos, refit_every))
n_refits = len(refit_days)
print(f"  Total refits: {n_refits}")

for ri, refit_i in enumerate(refit_days):
    t_refit = oos_start_idx + refit_i
    train_start = t_refit - window
    train_data = all_returns[train_start:t_refit]

    # How many days until next refit (or end of OOS)
    if ri + 1 < len(refit_days):
        next_refit_i = refit_days[ri + 1]
    else:
        next_refit_i = n_oos
    n_forecast_days = next_refit_i - refit_i

    # The data we need to filter through: training + forecast period
    # For 1-step-ahead: filter train_data, then extend day by day
    filter_data = all_returns[train_start:t_refit + n_forecast_days]

    if ri % 4 == 0:
        elapsed_so_far = time.time() - start_time
        print(f"  Refit #{ri+1}/{n_refits} at day {refit_i}/{n_oos} "
              f"(date: {all_dates[t_refit].strftime('%Y-%m-%d')}) "
              f"[{elapsed_so_far:.1f}s elapsed]")
        sys.stdout.flush()

    # --- GARCH benchmarks (arch package) ---
    # Fit on training data, then manually implement GARCH recursion for OOS
    for model_name, dist, vol_o in [
        ('garch_n', 'Normal', 0), ('garch_t', 'StudentsT', 0),
        ('gjr_n', 'Normal', 1), ('gjr_t', 'StudentsT', 1)
    ]:
        try:
            am = arch_model(train_data, vol='Garch', p=1, o=vol_o, q=1, dist=dist)
            res = am.fit(disp='off')
            convergence_log[model_name].append(int(res.convergence_flag))

            # Extract fitted parameters
            p = res.params
            mu = p['mu'] if 'mu' in p.index else 0
            omega_g = p['omega']
            alpha_g = p['alpha[1]']
            beta_g = p['beta[1]']
            gamma_g = p.get('gamma[1]', 0)  # 0 for GARCH, >0 for GJR

            # Get the last conditional variance from training fit
            cv = np.asarray(res.conditional_volatility)
            last_h = cv[-1]**2
            last_resid = (train_data[-1] - mu)

            # Now extend the GARCH filter into the OOS period
            h_prev = last_h
            e_prev = last_resid
            for d in range(n_forecast_days):
                # 1-step-ahead forecast: h_{t+1} = omega + alpha*e_t^2 + gamma*e_t^2*I(e_t<0) + beta*h_t
                indicator = 1.0 if e_prev < 0 else 0.0
                h_next = omega_g + alpha_g * e_prev**2 + gamma_g * e_prev**2 * indicator + beta_g * h_prev
                forecasts[model_name][refit_i + d] = h_next

                # Update for next step using the actual observed return
                actual_return = filter_data[window + d]
                e_prev = actual_return - mu
                h_prev = h_next
        except Exception as e:
            convergence_log[model_name].append(-1)

    # --- GAS-Gaussian(1,1) ---
    try:
        gas_g_res = fit_gas_gaussian(train_data, n_starts=5)
        if gas_g_res is not None:
            convergence_log['gas_gaussian'].append(0 if gas_g_res.success else 1)
            gp = gas_g_res.x
            gas_gaussian_params_history.append({
                'date': all_dates[t_refit].strftime('%Y-%m-%d'),
                'omega': float(gp[0]), 'alpha': float(gp[1]), 'beta': float(gp[2]),
                'persistence': float(gp[2]),
                'nll': float(gas_g_res.fun), 'converged': bool(gas_g_res.success)
            })
            # Filter through the extended data
            f_path = gas_gaussian_filter(gp, filter_data)
            for d in range(n_forecast_days):
                # f_path[window + d] is the forecast for day (window + d),
                # made using info up to day (window + d - 1)
                forecasts['gas_gaussian'][refit_i + d] = np.exp(f_path[window + d])
        else:
            convergence_log['gas_gaussian'].append(-1)
    except Exception:
        convergence_log['gas_gaussian'].append(-1)

    # --- GAS-t(1,1) ---
    try:
        gas_t_res = fit_gas_t(train_data, n_starts=5)
        if gas_t_res is not None:
            convergence_log['gas_t'].append(0 if gas_t_res.success else 1)
            gp = gas_t_res.x
            gas_t_params_history.append({
                'date': all_dates[t_refit].strftime('%Y-%m-%d'),
                'omega': float(gp[0]), 'alpha': float(gp[1]),
                'beta': float(gp[2]), 'nu': float(gp[3]),
                'persistence': float(gp[2]),
                'nll': float(gas_t_res.fun), 'converged': bool(gas_t_res.success)
            })
            # Filter through the extended data
            f_path = gas_t_filter(gp, filter_data)
            for d in range(n_forecast_days):
                forecasts['gas_t'][refit_i + d] = np.exp(f_path[window + d])
        else:
            convergence_log['gas_t'].append(-1)
    except Exception:
        convergence_log['gas_t'].append(-1)

# Realized variance
for i in range(n_oos):
    realized_var[i] = all_returns[oos_start_idx + i]**2

elapsed = time.time() - start_time
print(f"\n  Forecasting complete: {elapsed:.1f}s ({n_refits} refits)")
sys.stdout.flush()

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
        print(f"  {model_name}: {n_success}/{n_total} converged "
              f"({convergence_summary[model_name]['rate']}%)")

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
    print(f"    nu (degrees of freedom): mean={gas_t_param_summary['nu_mean']:.2f}, "
          f"std={gas_t_param_summary['nu_std']:.2f}, "
          f"range=[{gas_t_param_summary['nu_min']:.2f}, {gas_t_param_summary['nu_max']:.2f}]")
    print(f"    alpha (score weight): mean={gas_t_param_summary['alpha_mean']:.4f}, "
          f"std={gas_t_param_summary['alpha_std']:.4f}")
    print(f"    beta (persistence): mean={gas_t_param_summary['beta_mean']:.4f}, "
          f"std={gas_t_param_summary['beta_std']:.4f}")

    # Check persistence < 1
    if gas_t_param_summary['beta_mean'] >= 0.999:
        print("  WARNING: GAS-t persistence at boundary! Results may be unreliable.")
else:
    gas_t_param_summary = {}
    print("  WARNING: No GAS-t parameters estimated!")

sys.stdout.flush()

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


def mse_fn(realized, forecast):
    """MSE loss: (r² - h)². Lower is better."""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean((realized[valid] - forecast[valid])**2))


def mae_fn(realized, forecast):
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
        'mse': mse_fn(realized_var, fc),
        'mae': mae_fn(realized_var, fc),
        'n_valid': int(valid_mask.sum())
    }
    metrics[name] = m
    print(f"  {name:15s}: QLIKE={m['qlike']:.6f}  MSE={m['mse']:.6f}  "
          f"MAE={m['mae']:.6f} (n={m['n_valid']})")

sys.stdout.flush()

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
    for k in range(1, max(h, 2)):
        if k < n:
            gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
            gamma_sum += 2 * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n

    dm_stat = d_mean / np.sqrt(max(var_d, 1e-20))
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

sys.stdout.flush()

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

# Also check VIX > 20 as a milder stress regime
mid_vix_mask = (vix_oos > 20) & (vix_oos <= 30)
low_vix_mask = vix_oos <= 20
n_mid = int(np.sum(mid_vix_mask))
n_low = int(np.sum(low_vix_mask))
print(f"  Mid VIX (20-30) days: {n_mid}, Low VIX (<=20) days: {n_low}")

regime_metrics = {}
for regime_name, mask in [('high_vix_gt30', high_vix_mask),
                           ('mid_vix_20_30', mid_vix_mask),
                           ('low_vix_le20', low_vix_mask),
                           ('normal_le30', normal_mask)]:
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
        sorted_models = sorted(regime_metrics[regime_name].items(),
                             key=lambda x: x[1]['qlike'])
        for rank, (name, m) in enumerate(sorted_models, 1):
            marker = " <--" if name in ('gas_t', 'gas_gaussian') else ""
            print(f"    #{rank} {name:15s}: QLIKE={m['qlike']:.6f}  MSE={m['mse']:.6f}{marker}")

sys.stdout.flush()

# ============================================================
# STEP 9: Score Downweighting Analysis
# ============================================================
print("\n[9] Score Downweighting Analysis (key GAS-t advantage)")

score_comparison = []
if gas_t_param_summary:
    nu_est = gas_t_param_summary['nu_mean']

    print(f"\n  Using estimated nu = {nu_est:.2f}")
    print(f"  {'|return/sigma|':>14s} {'Gaussian score':>16s} {'t-score':>12s} {'Downweight':>12s}")
    print(f"  {'-'*56}")

    for shock in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        u = shock**2
        gaussian_score = u - 1
        t_score = (nu_est + 1) / (nu_est - 2 + u) * u - 1
        downweight = t_score / gaussian_score if gaussian_score > 0 else np.nan
        score_comparison.append({
            'shock_sigma': float(shock),
            'gaussian_score': float(gaussian_score),
            't_score': float(t_score),
            'downweight_ratio': float(downweight) if np.isfinite(downweight) else None
        })
        dw_str = f"{downweight:.2%}" if np.isfinite(downweight) else "N/A"
        print(f"  {shock:14.1f}sigma {gaussian_score:16.2f} {t_score:12.2f} {dw_str:>12s}")

    if len(score_comparison) > 3 and score_comparison[3]['downweight_ratio'] is not None:
        print(f"\n  Interpretation: At 5sigma shock, GAS-t score is only "
              f"{score_comparison[3]['downweight_ratio']:.0%} of Gaussian score")
        print(f"  → outliers are heavily downweighted in variance update.")

sys.stdout.flush()

# ============================================================
# STEP 10: Residual Diagnostics on GAS-t
# ============================================================
print("\n[10] GAS-t Residual Diagnostics")

resid_diag = {}
if gas_t_params_history:
    # Use OOS forecasts to compute standardized residuals
    valid_mask = np.isfinite(forecasts['gas_t']) & (forecasts['gas_t'] > 0)
    oos_returns = all_returns[oos_start_idx:oos_end_idx]
    std_resid = np.full(n_oos, np.nan)
    std_resid[valid_mask] = oos_returns[valid_mask] / np.sqrt(forecasts['gas_t'][valid_mask])

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
        print(f"  Ljung-Box Q(10) on r^2_std: stat={lb_sq_stat:.4f}, p={lb_sq_p:.4f}")

sys.stdout.flush()

# ============================================================
# STEP 11: Summary & Rankings
# ============================================================
print("\n" + "=" * 70)
print("[11] FINAL RANKINGS")
print("=" * 70)

gas_t_qlike_rank = None
gas_t_mse_rank = None

if metrics:
    qlike_ranking = sorted(metrics.items(), key=lambda x: x[1]['qlike'])
    print("\n  QLIKE Ranking (lower is better — preferred loss for volatility):")
    for rank, (name, m) in enumerate(qlike_ranking, 1):
        marker = ""
        if name == 'gas_t':
            marker = " <-- GAS-t"
        elif name == 'gas_gaussian':
            marker = " <-- GAS-Gaussian"
        print(f"    #{rank} {name:15s}: QLIKE={m['qlike']:.6f}{marker}")

    mse_ranking = sorted(metrics.items(), key=lambda x: x[1]['mse'])
    print("\n  MSE Ranking (lower is better):")
    for rank, (name, m) in enumerate(mse_ranking, 1):
        marker = ""
        if name == 'gas_t':
            marker = " <-- GAS-t"
        elif name == 'gas_gaussian':
            marker = " <-- GAS-Gaussian"
        print(f"    #{rank} {name:15s}: MSE={m['mse']:.6f}{marker}")

    mae_ranking = sorted(metrics.items(), key=lambda x: x[1]['mae'])
    print("\n  MAE Ranking (lower is better):")
    for rank, (name, m) in enumerate(mae_ranking, 1):
        marker = ""
        if name == 'gas_t':
            marker = " <-- GAS-t"
        elif name == 'gas_gaussian':
            marker = " <-- GAS-Gaussian"
        print(f"    #{rank} {name:15s}: MAE={m['mae']:.6f}{marker}")

    best_qlike = qlike_ranking[0][0]
    best_mse = mse_ranking[0][0]
    print(f"\n  Best by QLIKE: {best_qlike}")
    print(f"  Best by MSE: {best_mse}")

    gas_t_qlike_rank = next((i+1 for i, (n, _) in enumerate(qlike_ranking)
                            if n == 'gas_t'), None)
    gas_t_mse_rank = next((i+1 for i, (n, _) in enumerate(mse_ranking)
                          if n == 'gas_t'), None)
    gas_g_qlike_rank = next((i+1 for i, (n, _) in enumerate(qlike_ranking)
                            if n == 'gas_gaussian'), None)
    print(f"\n  GAS-t rank: QLIKE #{gas_t_qlike_rank}, MSE #{gas_t_mse_rank}")
    print(f"  GAS-Gaussian rank: QLIKE #{gas_g_qlike_rank}")

sys.stdout.flush()

# ============================================================
# STEP 12: Conclusions
# ============================================================
print("\n[12] Conclusions")

gas_vs_gjr_t = dm_results.get('gas_t_vs_gjr_t', {})
gas_vs_gjr_n = dm_results.get('gas_t_vs_gjr_n', {})
gas_vs_garch_n = dm_results.get('gas_t_vs_garch_n', {})

gas_t_sig_vs_gjr_t = (gas_vs_gjr_t.get('qlike_dm_p', 1) < 0.05 and
                       gas_vs_gjr_t.get('qlike_gas_t_better', False))
gas_t_sig_vs_gjr_n = (gas_vs_gjr_n.get('qlike_dm_p', 1) < 0.05 and
                       gas_vs_gjr_n.get('qlike_gas_t_better', False))

if gas_t_sig_vs_gjr_t:
    conclusion = ("SIGNIFICANT: GAS-t outperforms GJR-GARCH-t by QLIKE DM test. "
                  "Score-driven volatility with heavy tails is superior for SPY.")
elif gas_t_sig_vs_gjr_n:
    conclusion = ("PARTIAL: GAS-t significantly outperforms GJR-N but not GJR-t. "
                  "Heavy tails (Student-t) matter more than score function.")
elif gas_t_qlike_rank == 1:
    conclusion = ("GAS-t has best QLIKE but NOT significantly better than GJR (DM p>0.05). "
                  "Practically equivalent to GARCH family — added complexity not justified.")
elif gas_t_qlike_rank is not None and gas_t_qlike_rank <= 3:
    conclusion = ("GAS-t competitive (rank #{}) but does not beat GARCH family. "
                  "Score-driven approach adds complexity without clear OOS gain for SPY.".format(
                      gas_t_qlike_rank))
else:
    conclusion = ("GAS-t underperforms standard GARCH family. "
                  "The score-driven approach does not help for SPY OOS 2023-2024.")

print(f"\n  {conclusion}")

# Additional interpretation
if gas_t_param_summary:
    nu_mean = gas_t_param_summary['nu_mean']
    if nu_mean < 5:
        print(f"\n  Heavy tail finding: nu={nu_mean:.1f} confirms very heavy tails in SPY")
        print(f"  (Gaussian would be nu -> infinity; nu<5 means infinite 4th moment)")
    elif nu_mean < 10:
        print(f"\n  Moderate tail finding: nu={nu_mean:.1f} indicates moderate heavy tails")
    else:
        print(f"\n  Near-Gaussian: nu={nu_mean:.1f} suggests tails are not extremely heavy")

sys.stdout.flush()

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
        'total': (f"{returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
                  f"{returns_pct.index[-1].strftime('%Y-%m-%d')}"),
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
        'optimization': '5-start L-BFGS-B + fallback to non-converged if needed'
    },
    'diagnostics': diagnostics,
    'convergence': convergence_summary,
    'gas_t_parameters': gas_t_param_summary,
    'gas_t_parameter_history': gas_t_params_history,
    'gas_gaussian_parameter_history': gas_gaussian_params_history,
    'forecast_metrics': metrics,
    'rankings': {
        'by_qlike': [(name, m['qlike']) for name, m in sorted(
            metrics.items(), key=lambda x: x[1]['qlike'])],
        'by_mse': [(name, m['mse']) for name, m in sorted(
            metrics.items(), key=lambda x: x[1]['mse'])],
        'by_mae': [(name, m['mae']) for name, m in sorted(
            metrics.items(), key=lambda x: x[1]['mae'])],
        'gas_t_qlike_rank': gas_t_qlike_rank,
        'gas_t_mse_rank': gas_t_mse_rank,
    },
    'dm_tests': dm_results,
    'regime_analysis': {
        'n_high_vix_gt30': n_high,
        'n_mid_vix_20_30': n_mid,
        'n_low_vix_le20': n_low,
        'metrics_by_regime': regime_metrics
    },
    'score_downweighting': {
        'estimated_nu': gas_t_param_summary.get('nu_mean', None),
        'comparison': score_comparison,
        'interpretation': (
            f"With nu={gas_t_param_summary.get('nu_mean', 0):.1f}, "
            f"a 5sigma shock receives {score_comparison[3]['downweight_ratio']:.0%} "
            f"of the Gaussian update weight"
        ) if (score_comparison and len(score_comparison) > 3
              and score_comparison[3]['downweight_ratio'] is not None) else 'N/A'
    },
    'residual_diagnostics': resid_diag,
    'conclusion': conclusion,
    'limitations': [
        'RV proxy is squared returns (noisy); realized variance from 5-min data would be better',
        'GAS-t self-implemented (no established Python package for cross-validation)',
        'Single asset (SPY) — generalizability to other assets unknown',
        'OOS period 2023-2024 is relatively calm — no extreme crisis like COVID',
        'Student-t score assumes symmetric tails; skewed-t GAS extension not tested',
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
print("=" * 70)
