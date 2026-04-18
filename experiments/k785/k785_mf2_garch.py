"""
K785: MF2-GARCH (Multiplicative Factor Two-Component GARCH)
============================================================
Conrad & Engle (2025), "Long- and Short-Run Components of GARCH",
Journal of Applied Econometrics.

Research Question: Does separating short-run and long-run variance
components via multiplicative decomposition beat single-component
GJR-GARCH for OOS volatility forecasting?

Prior Knowledge:
- K783: GJR-GARCH expanding window QLIKE=0.529 (best so far)
- K144: MF2-GARCH wins for low-gamma assets (TLT) but not high-gamma (SPY)
- K783 showed expanding window > rolling window for GJR on SPY

Model: sigma^2_t = g_t * tau_t
  g_t: short-run GJR-GARCH on standardized returns z_t = r_t / sqrt(tau_t)
  tau_t: long-run component (EWMA of r^2 with slow decay OR MEM estimation)

Implementation (proper recursive filtering):
  At refit points: estimate GJR params (omega, alpha, gamma, beta) on z_t
  Between refits: recursively filter g_t using stored params + new data
  Forecast: sigma^2_{t+1} = g_{t+1|t} * tau_{t+1|t}

Variations:
  1. MF2-GARCH (lambda=0.999): very slow long-run
  2. MF2-GARCH (lambda=0.997): medium-slow long-run
  3. MF2-GARCH (lambda=0.995): faster long-run
  4. MF2-GARCH (MEM tau): tau estimated as MEM with Gamma MLE
  5. GJR-GARCH baseline: standard single-component (expanding window)
  6. EWMA baseline: lambda=0.94

Design:
- SPY from yfinance, start=2000-01-01
- Expanding window, refit every 63 days (quarterly)
- OOS: 2023-01-01 ~ 2024-12-31
- CRITICAL: No lookahead — forecast t+1 uses only data up to t
- Multiprocessing for speed

Evaluation:
- QLIKE on r^2 (Patton 2011 proxy-robust)
- MSE on r^2
- Spearman rank correlation (distribution-free)
- DM tests: MF2 vs GJR, Harvey (2016) t>3.0

References:
- Conrad & Engle (2025), Long- and Short-Run Components of GARCH, J. Applied Econometrics
- Engle & Rangel (2008), The Spline GARCH Model, Review of Financial Studies
- Engle, Ghysels, Sohn (2013), Stock Market Volatility and Macroeconomic Fundamentals, RFS
- Patton (2011), Volatility forecast comparison using imperfect volatility proxies, J. Econometrics
- Harvey et al. (2016), ...and the cross-section of expected returns, RFS (t>3.0 threshold)
- Hansen & Lunde (2005), A forecast comparison of volatility models, J. Applied Econometrics

Data source: yfinance (SPY, 2000-01-01 to 2024-12-31)
"""

import json
import math
import time
import warnings
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
ASSET = "SPY"
DATA_START = "2000-01-01"
DATA_END = "2024-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"

REFIT_INTERVAL = 63  # quarterly refit
MIN_TRAIN = 500  # minimum training observations
EWMA_LAMBDA = 0.94

# Harvey (2016) threshold
HARVEY_T_THRESHOLD = 3.0

# MF2 lambda values for long-run EWMA component
MF2_LAMBDAS = [0.999, 0.997, 0.995]


# ============================================================
# Data Loading
# ============================================================
def load_data():
    """Load SPY data from yfinance."""
    print(f"Downloading {ASSET} data from {DATA_START} to {DATA_END}...")
    df = yf.download(ASSET, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df["Return"] = df["Close"].pct_change()
    df = df.dropna(subset=["Return"])
    # Scale returns to percentage for arch package
    df["Return_pct"] = df["Return"] * 100
    print(
        f"Loaded {len(df)} observations "
        f"({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})"
    )
    return df


# ============================================================
# EWMA Long-Run Component
# ============================================================
def compute_ewma_tau(r2_array, lam):
    """
    Compute EWMA of squared returns as long-run variance.
    tau_t = lam * tau_{t-1} + (1 - lam) * r^2_{t-1}
    tau[0] initialized with sample mean of r^2.
    """
    n = len(r2_array)
    tau = np.zeros(n)
    tau[0] = np.mean(r2_array)
    for t in range(1, n):
        tau[t] = lam * tau[t - 1] + (1 - lam) * r2_array[t - 1]
    return tau


# ============================================================
# MEM Long-Run Component (Gamma MLE)
# ============================================================
def mem_nll(params, r2_series):
    """
    Negative log-likelihood for Multiplicative Error Model on r^2:
      tau_t = omega + alpha_tau * r^2_{t-1} + beta_tau * tau_{t-1}
      r^2_t / tau_t ~ Gamma(kappa, 1/kappa)
    """
    omega, alpha_tau, beta_tau, kappa = params

    if omega <= 1e-10 or alpha_tau < 0 or beta_tau < 0 or kappa <= 0.01:
        return 1e10
    if alpha_tau + beta_tau >= 0.9999:
        return 1e10

    n = len(r2_series)
    tau = np.zeros(n)
    tau[0] = max(np.mean(r2_series), 1e-10)

    nll = 0.0
    for t in range(1, n):
        tau[t] = omega + alpha_tau * r2_series[t - 1] + beta_tau * tau[t - 1]
        tau[t] = max(tau[t], 1e-10)

        x = max(r2_series[t], 1e-20)
        theta = tau[t] / kappa
        nll -= (
            (kappa - 1) * np.log(x)
            - x / theta
            - kappa * np.log(theta)
            - math.lgamma(kappa)
        )

    return nll


def fit_mem_tau(r2_train):
    """Fit MEM model to r^2, return tau array + params."""
    mean_r2 = np.mean(r2_train)

    best_res = None
    best_nll = np.inf

    # Try multiple initializations
    inits = [
        np.array([mean_r2 * 0.01, 0.05, 0.94, 2.0]),
        np.array([mean_r2 * 0.05, 0.10, 0.85, 1.0]),
        np.array([mean_r2 * 0.001, 0.02, 0.97, 5.0]),
        np.array([mean_r2 * 0.02, 0.08, 0.90, 3.0]),
    ]
    bounds = [(1e-10, mean_r2 * 10), (1e-6, 0.4), (0.5, 0.9998), (0.1, 50)]

    for x0 in inits:
        try:
            res = minimize(
                mem_nll, x0, args=(r2_train,),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-10}
            )
            if res.success and res.fun < best_nll and not np.any(np.isnan(res.x)):
                best_nll = res.fun
                best_res = res
        except Exception:
            pass

    if best_res is None:
        return None, None

    omega, alpha_tau, beta_tau, kappa = best_res.x

    # Re-filter tau
    n = len(r2_train)
    tau = np.zeros(n)
    tau[0] = max(np.mean(r2_train), 1e-10)
    for t in range(1, n):
        tau[t] = omega + alpha_tau * r2_train[t - 1] + beta_tau * tau[t - 1]
        tau[t] = max(tau[t], 1e-10)

    params = {
        "omega": float(omega), "alpha_tau": float(alpha_tau),
        "beta_tau": float(beta_tau), "kappa": float(kappa)
    }
    return tau, params


# ============================================================
# GJR-GARCH Estimation helpers
# ============================================================
def fit_gjr_get_params(returns_pct):
    """
    Fit GJR-GARCH(1,1) and return parameters + conditional variances.
    Returns: (params_dict, cond_var_array, converged)
    """
    try:
        am = arch_model(
            returns_pct, vol="GARCH", p=1, o=1, q=1,
            dist="normal", mean="Zero"
        )
        res = am.fit(disp="off", show_warning=False, options={"maxiter": 300})

        omega = float(res.params.get("omega", np.nan))
        alpha = float(res.params.get("alpha[1]", np.nan))
        beta = float(res.params.get("beta[1]", np.nan))
        gamma = float(res.params.get("gamma[1]", 0.0))

        converged = res.convergence_flag == 0
        cond_var = res.conditional_volatility ** 2  # in pct^2

        # One-step forecast
        forecast = res.forecast(horizon=1)
        fvar = forecast.variance.iloc[-1, 0]

        params = {"omega": omega, "alpha": alpha, "beta": beta, "gamma": gamma}
        return params, cond_var.values, fvar, converged
    except Exception:
        return None, None, np.nan, False


def gjr_recursive_filter_and_forecast(params, returns_pct_arr, init_var):
    """
    Recursively filter GJR-GARCH variance and produce 1-step forecast.
    params: dict with omega, alpha, beta, gamma
    returns_pct_arr: returns in pct
    init_var: initial variance (pct^2)
    Returns: (filtered_var_array, 1-step-ahead forecast)
    """
    omega = params["omega"]
    alpha = params["alpha"]
    beta = params["beta"]
    gamma = params["gamma"]

    n = len(returns_pct_arr)
    h = np.zeros(n)
    h[0] = init_var

    for t in range(1, n):
        r = returns_pct_arr[t - 1]
        indicator = 1.0 if r < 0 else 0.0
        h[t] = omega + (alpha + gamma * indicator) * r * r + beta * h[t - 1]
        h[t] = max(h[t], 1e-10)

    # 1-step forecast
    r_last = returns_pct_arr[-1]
    indicator = 1.0 if r_last < 0 else 0.0
    h_next = omega + (alpha + gamma * indicator) * r_last * r_last + beta * h[-1]
    h_next = max(h_next, 1e-10)

    return h, h_next


# ============================================================
# Diebold-Mariano Test
# ============================================================
def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. Positive DM = loss1 > loss2 (model 2 better).
    """
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, max(h, 2)):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)


# ============================================================
# Worker: MF2-GARCH with EWMA tau (proper recursive)
# ============================================================
def run_mf2_ewma(args):
    """
    MF2-GARCH with EWMA long-run component.
    - tau_t: EWMA(r^2, lambda_slow) — updated daily
    - g_t: GJR-GARCH on z_t = r_t/sqrt(tau_t) — re-estimated every REFIT_INTERVAL
    - Between refits: recursively filter g using stored GJR params

    sigma^2_{t+1} = g_{t+1|t} * tau_{t+1|t}
    """
    lam_slow, returns_pct_arr, r2_arr, oos_positions, label = args
    n_total = len(returns_pct_arr)
    n_oos = len(oos_positions)
    forecasts = np.full(n_oos, np.nan)
    realized = np.full(n_oos, np.nan)

    # Pre-compute full tau series (EWMA of r^2) — no lookahead, each tau_t
    # only uses r^2 up to t-1
    tau_full = compute_ewma_tau(r2_arr, lam_slow)

    # State for GJR on standardized returns
    gjr_params = None
    last_g = None  # last filtered g value (pct^2 scale relative to tau=1)
    last_refit_oos_idx = -REFIT_INTERVAL

    for i, idx in enumerate(oos_positions):
        # Realized: r^2_t in pct^2
        realized[i] = r2_arr[idx]

        train_end = idx  # use data[0:idx]
        if train_end < MIN_TRAIN:
            continue

        need_refit = (i - last_refit_oos_idx) >= REFIT_INTERVAL or gjr_params is None

        if need_refit:
            # Standardize all training returns by tau
            tau_train = tau_full[:train_end]
            tau_safe = np.maximum(tau_train, 1e-10)
            z_pct = returns_pct_arr[:train_end] / np.sqrt(tau_safe)

            # Fit GJR-GARCH on standardized returns
            z_series = pd.Series(z_pct, name="z")
            params, cond_var, forecast_g, converged = fit_gjr_get_params(z_series)

            if params is None or not converged:
                continue

            gjr_params = params
            last_g = cond_var[-1]  # last in-sample g (from the fit)
            last_refit_oos_idx = i

            # g_{t+1} forecast from the fit (1-step ahead)
            g_forecast = forecast_g

        else:
            # Between refits: recursively update g using new standardized return
            # z_{t-1} = r_{t-1} / sqrt(tau_{t-1})
            tau_prev = max(tau_full[idx - 1], 1e-10)
            z_prev = returns_pct_arr[idx - 1] / np.sqrt(tau_prev)
            indicator = 1.0 if z_prev < 0 else 0.0

            g_t = (gjr_params["omega"]
                   + (gjr_params["alpha"] + gjr_params["gamma"] * indicator) * z_prev * z_prev
                   + gjr_params["beta"] * last_g)
            g_t = max(g_t, 1e-10)
            last_g = g_t

            # Forecast g_{t+1}: use today's standardized return
            tau_today = max(tau_full[idx], 1e-10)
            z_today = returns_pct_arr[idx - 1] / np.sqrt(tau_today)
            # Wait — we can't use today's return for the forecast. The forecast
            # for t+1 uses information up to t. But z_t depends on r_t which
            # IS known at time t (it's today's close). So:
            # g_{t+1|t} = omega + (alpha + gamma*I(z_t<0)) * z_t^2 + beta * g_t
            z_t = returns_pct_arr[idx - 1] / np.sqrt(max(tau_full[idx - 1], 1e-10))
            indicator_t = 1.0 if z_t < 0 else 0.0
            g_forecast = (gjr_params["omega"]
                         + (gjr_params["alpha"] + gjr_params["gamma"] * indicator_t) * z_t * z_t
                         + gjr_params["beta"] * last_g)
            g_forecast = max(g_forecast, 1e-10)

        # tau_{t+1|t} = lam * tau_t + (1-lam) * r^2_t
        # But we're forecasting for time idx, and tau_full[idx] already uses r^2_{idx-1}
        # The forecast for time idx+1 needs r^2_idx which we DON'T have yet
        # So tau forecast = tau_full[idx] (which is tau at time idx, using data up to idx-1)
        # This is the best we can do: tau_{t+1|t} ~ tau_t since lambda is very close to 1
        tau_forecast = tau_full[idx]

        # sigma^2_{t+1|t} = g_{t+1|t} * tau_{t+1|t}
        forecasts[i] = g_forecast * tau_forecast

    # Metrics
    valid = ~np.isnan(forecasts) & ~np.isnan(realized) & (forecasts > 0) & (realized > 0)
    n_valid = int(valid.sum())

    if n_valid < 10:
        return {
            "model": label, "n_valid": n_valid,
            "qlike": np.nan, "mse": np.nan, "spearman": np.nan,
            "forecasts": [], "realized": [],
        }

    f = forecasts[valid]
    r = realized[valid]
    qlike = float(np.mean(r / f + np.log(f)))
    mse = float(np.mean((f - r) ** 2))
    spearman = float(stats.spearmanr(f, r)[0])

    return {
        "model": label, "n_valid": n_valid,
        "qlike": qlike, "mse": mse, "spearman": spearman,
        "forecasts": f.tolist(), "realized": r.tolist(),
    }


# ============================================================
# Worker: MF2-GARCH with MEM tau
# ============================================================
def run_mf2_mem(args):
    """
    MF2-GARCH with MEM-estimated long-run component.
    Same recursive filtering approach as EWMA variant.
    """
    returns_pct_arr, r2_arr, oos_positions, label = args
    n_oos = len(oos_positions)
    forecasts = np.full(n_oos, np.nan)
    realized = np.full(n_oos, np.nan)

    gjr_params = None
    mem_params = None
    last_g = None
    last_tau = None
    last_refit_oos_idx = -REFIT_INTERVAL

    # Pre-compute initial MEM tau for efficiency (will refit periodically)
    tau_cache = None  # full tau array from last MEM fit

    for i, idx in enumerate(oos_positions):
        realized[i] = r2_arr[idx]

        train_end = idx
        if train_end < MIN_TRAIN:
            continue

        need_refit = (i - last_refit_oos_idx) >= REFIT_INTERVAL or gjr_params is None

        if need_refit:
            # Step 1: Fit MEM on r^2 to get tau
            tau_mem, mp = fit_mem_tau(r2_arr[:train_end])
            if tau_mem is None:
                continue

            mem_params = mp
            tau_cache = tau_mem

            # Step 2: Standardize returns
            tau_safe = np.maximum(tau_mem, 1e-10)
            z_pct = returns_pct_arr[:train_end] / np.sqrt(tau_safe)

            # Step 3: Fit GJR on standardized returns
            z_series = pd.Series(z_pct, name="z")
            params, cond_var, forecast_g, converged = fit_gjr_get_params(z_series)

            if params is None or not converged:
                continue

            gjr_params = params
            last_g = cond_var[-1]
            last_tau = tau_mem[-1]
            last_refit_oos_idx = i

            g_forecast = forecast_g
        else:
            if mem_params is None:
                continue

            # Update tau_{t} using MEM recursion
            tau_t = (mem_params["omega"]
                     + mem_params["alpha_tau"] * r2_arr[idx - 1]
                     + mem_params["beta_tau"] * last_tau)
            tau_t = max(tau_t, 1e-10)
            last_tau = tau_t

            # Update g_t using recursive GJR on standardized return
            z_prev = returns_pct_arr[idx - 1] / np.sqrt(max(last_tau, 1e-10))
            indicator = 1.0 if z_prev < 0 else 0.0
            g_t = (gjr_params["omega"]
                   + (gjr_params["alpha"] + gjr_params["gamma"] * indicator) * z_prev * z_prev
                   + gjr_params["beta"] * last_g)
            g_t = max(g_t, 1e-10)
            last_g = g_t

            # Forecast g_{t+1}
            z_t = returns_pct_arr[idx - 1] / np.sqrt(max(last_tau, 1e-10))
            indicator_t = 1.0 if z_t < 0 else 0.0
            g_forecast = (gjr_params["omega"]
                         + (gjr_params["alpha"] + gjr_params["gamma"] * indicator_t) * z_t * z_t
                         + gjr_params["beta"] * last_g)
            g_forecast = max(g_forecast, 1e-10)

        # tau_{t+1|t} forecast
        tau_forecast = (mem_params["omega"]
                       + mem_params["alpha_tau"] * r2_arr[idx - 1]
                       + mem_params["beta_tau"] * last_tau)
        tau_forecast = max(tau_forecast, 1e-10)

        forecasts[i] = g_forecast * tau_forecast

    valid = ~np.isnan(forecasts) & ~np.isnan(realized) & (forecasts > 0) & (realized > 0)
    n_valid = int(valid.sum())

    if n_valid < 10:
        return {
            "model": label, "n_valid": n_valid,
            "qlike": np.nan, "mse": np.nan, "spearman": np.nan,
            "forecasts": [], "realized": [],
        }

    f = forecasts[valid]
    r = realized[valid]
    qlike = float(np.mean(r / f + np.log(f)))
    mse = float(np.mean((f - r) ** 2))
    spearman = float(stats.spearmanr(f, r)[0])

    return {
        "model": label, "n_valid": n_valid,
        "qlike": qlike, "mse": mse, "spearman": spearman,
        "forecasts": f.tolist(), "realized": r.tolist(),
    }


# ============================================================
# Worker: Plain GJR-GARCH (baseline — daily expanding refit)
# ============================================================
def run_gjr_baseline(args):
    """
    Plain GJR-GARCH(1,1) expanding window, refits every day.
    This matches K783 "ALL" window approach.
    """
    returns_pct_series, r2_arr, oos_positions, label = args
    n_oos = len(oos_positions)
    forecasts = np.full(n_oos, np.nan)
    realized = np.full(n_oos, np.nan)

    for i, idx in enumerate(oos_positions):
        realized[i] = r2_arr[idx]

        train_end = idx
        if train_end < MIN_TRAIN:
            continue

        train = returns_pct_series.iloc[:train_end]

        try:
            am = arch_model(
                train, vol="GARCH", p=1, o=1, q=1,
                dist="normal", mean="Zero"
            )
            res = am.fit(disp="off", show_warning=False, options={"maxiter": 300})
            if res.convergence_flag != 0:
                continue
            forecast = res.forecast(horizon=1)
            fvar = forecast.variance.iloc[-1, 0]
            if np.isnan(fvar) or fvar <= 0:
                continue
            forecasts[i] = fvar
        except Exception:
            continue

    valid = ~np.isnan(forecasts) & ~np.isnan(realized) & (forecasts > 0) & (realized > 0)
    n_valid = int(valid.sum())

    if n_valid < 10:
        return {
            "model": label, "n_valid": n_valid,
            "qlike": np.nan, "mse": np.nan, "spearman": np.nan,
            "forecasts": [], "realized": [],
        }

    f = forecasts[valid]
    r = realized[valid]
    qlike = float(np.mean(r / f + np.log(f)))
    mse = float(np.mean((f - r) ** 2))
    spearman = float(stats.spearmanr(f, r)[0])

    return {
        "model": label, "n_valid": n_valid,
        "qlike": qlike, "mse": mse, "spearman": spearman,
        "forecasts": f.tolist(), "realized": r.tolist(),
    }


# ============================================================
# Worker: EWMA baseline
# ============================================================
def run_ewma_baseline(args):
    """EWMA (lambda=0.94) baseline."""
    returns_pct_arr, r2_arr, oos_positions, label = args
    n_oos = len(oos_positions)
    forecasts = np.full(n_oos, np.nan)
    realized = np.full(n_oos, np.nan)

    # Run EWMA up to first OOS point
    ewma_var = returns_pct_arr[0] ** 2
    for t in range(1, oos_positions[0]):
        ewma_var = EWMA_LAMBDA * ewma_var + (1 - EWMA_LAMBDA) * returns_pct_arr[t] ** 2

    prev_idx = oos_positions[0]
    for i, idx in enumerate(oos_positions):
        realized[i] = r2_arr[idx]

        # Update EWMA up to idx-1
        if i > 0:
            for t in range(prev_idx, idx):
                ewma_var = EWMA_LAMBDA * ewma_var + (1 - EWMA_LAMBDA) * returns_pct_arr[t] ** 2

        # Forecast for idx (uses info up to idx-1, which is already in ewma_var)
        forecasts[i] = ewma_var

        # Update with idx for next iteration
        ewma_var = EWMA_LAMBDA * ewma_var + (1 - EWMA_LAMBDA) * returns_pct_arr[idx] ** 2
        prev_idx = idx + 1

    valid = ~np.isnan(forecasts) & ~np.isnan(realized) & (forecasts > 0) & (realized > 0)
    n_valid = int(valid.sum())

    if n_valid < 10:
        return {
            "model": label, "n_valid": n_valid,
            "qlike": np.nan, "mse": np.nan, "spearman": np.nan,
            "forecasts": [], "realized": [],
        }

    f = forecasts[valid]
    r = realized[valid]
    qlike = float(np.mean(r / f + np.log(f)))
    mse = float(np.mean((f - r) ** 2))
    spearman = float(stats.spearmanr(f, r)[0])

    return {
        "model": label, "n_valid": n_valid,
        "qlike": qlike, "mse": mse, "spearman": spearman,
        "forecasts": f.tolist(), "realized": r.tolist(),
    }


# ============================================================
# Main
# ============================================================
def main():
    start_time = time.time()
    print("=" * 70)
    print("K785: MF2-GARCH (Multiplicative Factor Two-Component GARCH)")
    print("Conrad & Engle (2025), J. Applied Econometrics")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Load data
    # ----------------------------------------------------------
    df = load_data()
    returns_pct = df["Return_pct"]
    returns_pct_arr = returns_pct.values.copy()
    r2_arr = returns_pct_arr ** 2

    all_dates = df.index

    # ----------------------------------------------------------
    # 2. Descriptive statistics
    # ----------------------------------------------------------
    print(f"\n{'='*50}")
    print("Descriptive Statistics (full sample)")
    print(f"{'='*50}")
    print(f"  N observations: {len(returns_pct)}")
    print(f"  Mean return:    {returns_pct.mean():.4f}% per day")
    print(f"  Std:            {returns_pct.std():.4f}%")
    print(f"  Skewness:       {returns_pct.skew():.4f}")
    print(f"  Kurtosis:       {returns_pct.kurtosis():.4f}")

    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_pval, _, _, _, _ = adfuller(returns_pct, maxlag=20)
    print(f"  ADF statistic:  {adf_stat:.4f} (p={adf_pval:.6f})")
    print(f"  Stationary:     {'Yes' if adf_pval < 0.05 else 'No'}")

    from statsmodels.stats.diagnostic import het_arch
    arch_lm_stat, arch_lm_pval, _, _ = het_arch(returns_pct, nlags=10)
    print(f"  ARCH LM(10):    {arch_lm_stat:.2f} (p={arch_lm_pval:.6f})")
    print(f"  ARCH effects:   {'Yes' if arch_lm_pval < 0.05 else 'No'}")

    # ----------------------------------------------------------
    # 3. OOS period
    # ----------------------------------------------------------
    oos_mask = (all_dates >= OOS_START) & (all_dates <= OOS_END)
    oos_positions = np.where(oos_mask)[0]
    print(f"\nOOS period: {all_dates[oos_positions[0]].strftime('%Y-%m-%d')} "
          f"to {all_dates[oos_positions[-1]].strftime('%Y-%m-%d')}")
    print(f"OOS observations: {len(oos_positions)}")
    print(f"Data before first OOS: {oos_positions[0]} observations")
    print(f"Refit interval: {REFIT_INTERVAL} days")

    # ----------------------------------------------------------
    # 4. Run models
    # ----------------------------------------------------------
    print(f"\n{'='*50}")
    print("Running models...")
    print(f"{'='*50}")

    all_results = {}

    # 4a. GJR-GARCH baseline (daily refit, expanding)
    print("\n[1/6] GJR-GARCH baseline (expanding, daily refit)...")
    t0 = time.time()
    gjr_result = run_gjr_baseline((
        returns_pct, r2_arr, oos_positions, "GJR-GARCH (expanding)"
    ))
    print(f"  Done in {time.time()-t0:.1f}s — QLIKE={gjr_result['qlike']:.4f}, "
          f"Spearman={gjr_result['spearman']:.4f}, n={gjr_result['n_valid']}")
    all_results["gjr_baseline"] = gjr_result

    # 4b. EWMA baseline
    print("\n[2/6] EWMA baseline (lambda=0.94)...")
    t0 = time.time()
    ewma_result = run_ewma_baseline((
        returns_pct_arr, r2_arr, oos_positions, f"EWMA (lambda={EWMA_LAMBDA})"
    ))
    print(f"  Done in {time.time()-t0:.1f}s — QLIKE={ewma_result['qlike']:.4f}, "
          f"Spearman={ewma_result['spearman']:.4f}, n={ewma_result['n_valid']}")
    all_results["ewma_baseline"] = ewma_result

    # 4c. MF2-GARCH with EWMA tau (parallel)
    print("\n[3-5/6] MF2-GARCH with EWMA tau (3 lambda values, parallel)...")
    mf2_ewma_tasks = [
        (lam, returns_pct_arr, r2_arr, oos_positions,
         f"MF2-GARCH (EWMA lam={lam})")
        for lam in MF2_LAMBDAS
    ]
    t0 = time.time()
    n_workers = min(cpu_count(), len(mf2_ewma_tasks))
    with Pool(n_workers) as pool:
        mf2_ewma_results = pool.map(run_mf2_ewma, mf2_ewma_tasks)
    for lam, res in zip(MF2_LAMBDAS, mf2_ewma_results):
        key = f"mf2_ewma_{lam}"
        all_results[key] = res
        q = res.get('qlike', np.nan)
        s = res.get('spearman', np.nan)
        q_str = f"{q:.4f}" if not np.isnan(q) else "N/A"
        s_str = f"{s:.4f}" if not np.isnan(s) else "N/A"
        print(f"  MF2 lam={lam}: QLIKE={q_str}, Spearman={s_str}, n={res['n_valid']}")
    print(f"  All MF2-EWMA done in {time.time()-t0:.1f}s")

    # 4d. MF2-GARCH with MEM tau
    print("\n[6/6] MF2-GARCH with MEM tau (Gamma MLE)...")
    t0 = time.time()
    mem_result = run_mf2_mem((
        returns_pct_arr, r2_arr, oos_positions, "MF2-GARCH (MEM tau)"
    ))
    q = mem_result.get('qlike', np.nan)
    s = mem_result.get('spearman', np.nan)
    q_str = f"{q:.4f}" if not np.isnan(q) else "N/A"
    s_str = f"{s:.4f}" if not np.isnan(s) else "N/A"
    print(f"  Done in {time.time()-t0:.1f}s — QLIKE={q_str}, "
          f"Spearman={s_str}, n={mem_result['n_valid']}")
    all_results["mf2_mem"] = mem_result

    # ----------------------------------------------------------
    # 5. Results Summary
    # ----------------------------------------------------------
    total_time = time.time() - start_time
    print(f"\n{'='*70}")
    print("RESULTS SUMMARY")
    print(f"{'='*70}")

    header = f"{'Model':<35} | {'QLIKE':>8} | {'MSE':>10} | {'Spearman':>8} | {'N':>5}"
    print(header)
    print("-" * len(header))

    sorted_results = sorted(
        all_results.items(),
        key=lambda x: x[1].get("qlike", 999) if not np.isnan(x[1].get("qlike", 999)) else 999
    )
    for key, res in sorted_results:
        q = res.get("qlike", np.nan)
        m = res.get("mse", np.nan)
        s = res.get("spearman", np.nan)
        n = res.get("n_valid", 0)
        label = res.get("model", key)
        q_str = f"{q:.4f}" if not np.isnan(q) else "N/A"
        m_str = f"{m:.4f}" if not np.isnan(m) else "N/A"
        s_str = f"{s:.4f}" if not np.isnan(s) else "N/A"
        print(f"{label:<35} | {q_str:>8} | {m_str:>10} | {s_str:>8} | {n:>5}")

    # ----------------------------------------------------------
    # 6. DM Tests vs GJR baseline
    # ----------------------------------------------------------
    print(f"\n{'='*70}")
    print("DM Tests: each model vs GJR-GARCH baseline (QLIKE loss)")
    print(f"Harvey (2016) threshold: |t| > {HARVEY_T_THRESHOLD}")
    print(f"{'='*70}")

    gjr_f = np.array(gjr_result.get("forecasts", []))
    gjr_r = np.array(gjr_result.get("realized", []))
    dm_results = {}

    if len(gjr_f) > 0:
        gjr_loss = gjr_r / gjr_f + np.log(gjr_f)

        header = f"{'Model':<35} | {'DM stat':>8} | {'p-value':>8} | {'Sig':>6} | {'Better':>18}"
        print(header)
        print("-" * len(header))

        for key, res in sorted_results:
            if key == "gjr_baseline":
                print(f"{'GJR-GARCH (ref)':<35} | {'(ref)':>8} | {'(ref)':>8} | {'(ref)':>6} | {'(ref)':>18}")
                continue

            test_f = np.array(res.get("forecasts", []))
            test_r = np.array(res.get("realized", []))

            if len(test_f) == 0:
                label = res.get("model", key)
                print(f"{label:<35} | {'N/A':>8} | {'N/A':>8} | {'N/A':>6} | {'N/A':>18}")
                continue

            min_len = min(len(gjr_loss), len(test_f))
            test_loss = test_r[:min_len] / test_f[:min_len] + np.log(test_f[:min_len])
            ref_loss = gjr_loss[:min_len]

            dm_stat, p_val = dm_test(ref_loss, test_loss, h=1)

            sig_str = "|t|>3" if not np.isnan(dm_stat) and abs(dm_stat) > HARVEY_T_THRESHOLD else "no"
            if not np.isnan(dm_stat):
                better = res.get("model", key)[:18] if dm_stat > 0 else "GJR baseline"
            else:
                better = "N/A"
                sig_str = "N/A"

            label = res.get("model", key)
            dm_str = f"{dm_stat:.3f}" if not np.isnan(dm_stat) else "N/A"
            p_str = f"{p_val:.4f}" if not np.isnan(p_val) else "N/A"
            print(f"{label:<35} | {dm_str:>8} | {p_str:>8} | {sig_str:>6} | {better:>18}")

            dm_results[key] = {
                "dm_stat": float(dm_stat) if not np.isnan(dm_stat) else None,
                "p_value": float(p_val) if not np.isnan(p_val) else None,
                "significant_harvey": bool(abs(dm_stat) > HARVEY_T_THRESHOLD) if not np.isnan(dm_stat) else False,
                "better_model": better,
            }

    # ----------------------------------------------------------
    # 6b. DM pairwise among MF2
    # ----------------------------------------------------------
    print(f"\n{'='*70}")
    print("DM Tests: pairwise among MF2 variants")
    print(f"{'='*70}")

    mf2_keys = [k for k in all_results if k.startswith("mf2_") and all_results[k]["n_valid"] > 0]
    dm_pairwise = {}
    for i_m, k1 in enumerate(mf2_keys):
        for k2 in mf2_keys[i_m + 1:]:
            f1 = np.array(all_results[k1].get("forecasts", []))
            r1 = np.array(all_results[k1].get("realized", []))
            f2 = np.array(all_results[k2].get("forecasts", []))
            r2 = np.array(all_results[k2].get("realized", []))

            if len(f1) == 0 or len(f2) == 0:
                continue

            min_len = min(len(f1), len(f2))
            loss1 = r1[:min_len] / f1[:min_len] + np.log(f1[:min_len])
            loss2 = r2[:min_len] / f2[:min_len] + np.log(f2[:min_len])

            dm_s, p_v = dm_test(loss1, loss2, h=1)
            l1 = all_results[k1].get("model", k1)
            l2 = all_results[k2].get("model", k2)
            sig = "|t|>3" if not np.isnan(dm_s) and abs(dm_s) > HARVEY_T_THRESHOLD else "no"
            print(f"  {l1} vs {l2}: DM={dm_s:.3f}, p={p_v:.4f}, sig={sig}")
            dm_pairwise[f"{k1}_vs_{k2}"] = {
                "dm_stat": float(dm_s) if not np.isnan(dm_s) else None,
                "p_value": float(p_v) if not np.isnan(p_v) else None,
                "significant_harvey": bool(abs(dm_s) > HARVEY_T_THRESHOLD) if not np.isnan(dm_s) else False,
            }

    # ----------------------------------------------------------
    # 7. Conclusions
    # ----------------------------------------------------------
    print(f"\n{'='*70}")
    print("CONCLUSIONS")
    print(f"{'='*70}")

    valid_results = {k: v for k, v in all_results.items()
                     if not np.isnan(v.get("qlike", np.nan))}
    if valid_results:
        best_key = min(valid_results, key=lambda k: valid_results[k]["qlike"])
        best_result = valid_results[best_key]
        gjr_qlike = gjr_result.get("qlike", np.nan)
        best_qlike = best_result.get("qlike", np.nan)

        print(f"  Best model:     {best_result.get('model', best_key)}")
        print(f"  Best QLIKE:     {best_qlike:.4f}")
        print(f"  GJR baseline:   {gjr_qlike:.4f}")
        if not np.isnan(gjr_qlike) and not np.isnan(best_qlike):
            improvement = (gjr_qlike - best_qlike) / abs(gjr_qlike) * 100
            print(f"  Improvement:    {improvement:.2f}%")

        any_mf2_sig = any(
            v.get("significant_harvey", False) and v.get("dm_stat") is not None and v["dm_stat"] > 0
            for v in dm_results.values()
        )
        print(f"  Any MF2 significantly beats GJR (t>{HARVEY_T_THRESHOLD})? {'YES' if any_mf2_sig else 'No'}")

        mf2_better = any(
            valid_results[k]["qlike"] < gjr_qlike
            for k in valid_results if k.startswith("mf2_")
        )
        print(f"  Any MF2 variant has lower QLIKE than GJR? {'Yes' if mf2_better else 'No'}")
    else:
        gjr_qlike = np.nan
        best_qlike = np.nan
        any_mf2_sig = False
        mf2_better = False
        best_key = "none"
        best_result = {}

    k783_qlike = 0.5287
    print(f"\n  K783 reference (GJR expanding, daily): QLIKE={k783_qlike}")
    print(f"  Our GJR baseline (expanding, daily):   QLIKE={gjr_qlike:.4f}" if not np.isnan(gjr_qlike) else "  Our GJR baseline: N/A")
    if not np.isnan(best_qlike):
        print(f"  Our best model:                        QLIKE={best_qlike:.4f}")

    print(f"\nTotal execution time: {total_time:.1f} seconds")

    # ----------------------------------------------------------
    # 8. Save results
    # ----------------------------------------------------------
    results_json = {
        "experiment_id": "K785",
        "title": "MF2-GARCH (Multiplicative Factor Two-Component GARCH)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "asset": ASSET,
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "n_oos": int(len(oos_positions)),
        "refit_interval": REFIT_INTERVAL,
        "window_type": "expanding",
        "models_tested": [res.get("model", k) for k, res in sorted_results],
        "references": [
            "Conrad & Engle (2025), Long- and Short-Run Components of GARCH, J. Applied Econometrics",
            "Engle & Rangel (2008), The Spline GARCH Model, Review of Financial Studies",
            "Engle, Ghysels, Sohn (2013), Stock Market Volatility and Macroeconomic Fundamentals, RFS",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies, J. Econometrics",
            "Harvey et al. (2016), ...and the cross-section of expected returns, RFS",
            "Hansen & Lunde (2005), A forecast comparison of volatility models, J. Applied Econometrics",
        ],
        "results": {
            k: {
                "model": res.get("model", k),
                "n_valid": res.get("n_valid", 0),
                "qlike": res.get("qlike"),
                "mse": res.get("mse"),
                "spearman": res.get("spearman"),
            }
            for k, res in all_results.items()
        },
        "dm_tests_vs_gjr": dm_results,
        "dm_tests_pairwise_mf2": dm_pairwise,
        "summary": {
            "best_model": best_result.get("model", best_key),
            "best_qlike": float(best_qlike) if not np.isnan(best_qlike) else None,
            "gjr_baseline_qlike": float(gjr_qlike) if not np.isnan(gjr_qlike) else None,
            "improvement_pct": float((gjr_qlike - best_qlike) / abs(gjr_qlike) * 100)
            if not np.isnan(gjr_qlike) and not np.isnan(best_qlike) else None,
            "any_mf2_significantly_beats_gjr_harvey": any_mf2_sig,
            "any_mf2_lower_qlike_than_gjr": mf2_better,
            "k783_reference_qlike": k783_qlike,
            "conclusion": (
                "MF2-GARCH decomposes variance into slow-moving tau (EWMA/MEM) and "
                "fast-reacting g (GJR on standardized returns). Tested 3 EWMA decay rates "
                "(0.999, 0.997, 0.995) and a MEM-estimated long-run component. "
                "Compared against plain GJR-GARCH with daily expanding refit and EWMA(0.94)."
            ),
        },
        "descriptive_stats": {
            "mean_return_pct": float(returns_pct.mean()),
            "std_return_pct": float(returns_pct.std()),
            "skewness": float(returns_pct.skew()),
            "kurtosis": float(returns_pct.kurtosis()),
            "n_total": int(len(returns_pct)),
            "adf_statistic": float(adf_stat),
            "adf_pvalue": float(adf_pval),
            "arch_lm_statistic": float(arch_lm_stat),
            "arch_lm_pvalue": float(arch_lm_pval),
        },
        "execution_time_seconds": round(total_time, 1),
    }

    out_path = Path(__file__).parent / "k785_mf2_garch_results.json"
    with open(out_path, "w") as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
