"""K592: MF2-GARCH (Conrad & Engle 2025) — Two-Component Volatility Model
========================================================================
[提出: User (K590 literature), 執行: Claude]

Research Question:
Does the MF2-GARCH (Multiplicative Factor Multi-Frequency GARCH) from Conrad
& Engle (JAE 2025) beat single-component GJR-GARCH and HAR-ABS for SPY
daily volatility prediction?

Motivation:
- K590 literature search found Conrad & Engle (JAE 2025) MF2-GARCH
- Different from K526 GARCH-MIDAS (which was null) and K144 MF2 (joint QML)
- K144 used joint QML with λ1+λ2*V^m+λ3*τ_{t-1} — this experiment uses the
  simplified 2-step approach with log-linear long-run component

MF2-GARCH decomposes:
  σ²_t = g_t × τ_t
  g_t: short-run GJR-GARCH on standardized returns
    g_t = (1-α-β-γ/2) + α*z²_{t-1} + γ*z²_{t-1}*I_{t-1<0} + β*g_{t-1}
    where z_t = r_t / sqrt(τ_t)  (returns standardized by long-run only)
  τ_t: long-run component (simplified MEM)
    τ_t = exp(ω + δ*log(RV22_{t-1}))
    RV22_{t-1} = (1/22) * sum_{j=1}^{22} r²_{t-j}  (22-day realized variance)

2-Step Estimation:
  Step 1: Estimate τ_t using log-linear model on 22-day RV
  Step 2: Estimate GJR on z_t = r_t / sqrt(τ_t) (long-run standardized returns)

Key difference from K144:
  K144: joint QML, τ_t = λ1 + λ2*V^m + λ3*τ_{t-1} (linear MEM)
  K592: 2-step, τ_t = exp(ω + δ*log(RV22)) (log-linear, simpler, fewer params)

Benchmarks: GJR-GARCH(1,1), HAR-ABS (K530 gold standard)
Rolling window: w=2000, OOS: 2023-2024
Evaluation: QLIKE + DM test

References:
- Conrad & Engle (2025, JAE): MF2-GARCH
- K144: MF2-GARCH joint QML (cross-asset, null for SPY)
- K530: HAR-ABS framework (DM=-15.45 vs GJR)
- K591: MF2 post-hoc correction (failed, worsened QLIKE)

Data: yfinance SPY 2005-2026

Usage:
    uv run python experiments/k592_mf2_garch.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Try numba for speed
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


# ======================================================================
# Data
# ======================================================================

def download_data(ticker: str = "SPY",
                  start: str = "2005-01-01",
                  end: str = "2026-03-27") -> pd.DataFrame:
    """Download daily data for a ticker, return DataFrame with returns."""
    import yfinance as yf
    print(f"Downloading {ticker} ({start} to {end})...", flush=True)
    df = yf.download(ticker, start=start, end=end, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_localize(None)
    df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna(subset=["log_return"])
    print(f"  {len(df)} trading days: {df.index[0].date()} to {df.index[-1].date()}")
    return df


# ======================================================================
# Realized Variance (22-day rolling)
# ======================================================================

def compute_rv22(returns: np.ndarray) -> np.ndarray:
    """Compute 22-day rolling realized variance: RV22_t = mean(r²_{t-21}...r²_t)."""
    n = len(returns)
    rv22 = np.full(n, np.nan)
    r2 = returns ** 2
    for t in range(21, n):
        rv22[t] = np.mean(r2[t - 21: t + 1])
    return rv22


# ======================================================================
# Long-run component τ_t = exp(ω + δ*log(RV22_{t-1}))
# ======================================================================

def estimate_tau(returns: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Estimate the long-run component using log-linear model on RV22.

    τ_t = exp(ω + δ * log(RV22_{t-1}))

    We fit ω, δ by regressing log(r²_t) on log(RV22_{t-1}) and adjusting
    for the E[log(χ²(1))] bias.

    Returns: (tau_array, omega, delta)
    """
    rv22 = compute_rv22(returns)

    # Use valid observations where both rv22 and returns exist
    # We need RV22_{t-1} to predict σ²_t, so use t >= 23
    valid = np.where(~np.isnan(rv22[:-1]))[0]
    valid = valid[valid >= 22]  # ensure rv22 is computed

    log_rv22_lag = np.log(np.maximum(rv22[valid], 1e-20))
    # Target: log(r²_t) for t = valid+1
    r2_next = returns[valid + 1] ** 2
    log_r2 = np.log(np.maximum(r2_next, 1e-20))

    # OLS: log(r²_{t}) = c + δ*log(RV22_{t-1}) + ε
    # E[log(r²)] = E[log(σ²)] + E[log(χ²(1))]
    # E[log(χ²(1))] = ψ(1/2) - log(2) ≈ -1.2704 (digamma bias)
    from scipy.special import digamma
    chi2_bias = digamma(0.5) + np.log(2)  # ≈ -1.2704

    X = np.column_stack([np.ones(len(log_rv22_lag)), log_rv22_lag])
    beta = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    # Adjust intercept for chi-squared bias
    omega = beta[0] - chi2_bias
    delta = beta[1]

    # Compute τ for all t
    n = len(returns)
    tau = np.full(n, np.nan)

    # For t < 22, use unconditional variance
    unc_var = np.var(returns)
    for t in range(22):
        tau[t] = unc_var

    for t in range(22, n):
        rv22_prev = rv22[t - 1] if t > 0 and not np.isnan(rv22[t - 1]) else unc_var
        tau[t] = np.exp(omega + delta * np.log(max(rv22_prev, 1e-20)))

    return tau, omega, delta


# ======================================================================
# GJR-GARCH on standardized returns (short-run g_t)
# ======================================================================

@njit
def _gjr_nll(params, z, n):
    """Negative log-likelihood for GJR-GARCH(1,1) on standardized returns z.

    g_t = (1 - α - β - γ/2) + α*z²_{t-1} + γ*z²_{t-1}*I_{z_{t-1}<0} + β*g_{t-1}

    Note: intercept is constrained so E[g_t] = 1 (since z is already scaled by τ).
    """
    alpha = params[0]
    gamma_p = params[1]
    beta = params[2]

    if alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + beta + gamma_p / 2.0 >= 1.0:
        return 1e10

    base = 1.0 - alpha - beta - gamma_p / 2.0
    if base <= 0:
        return 1e10

    g = 1.0  # E[g_t] = 1 by construction
    loglik = 0.0

    for t in range(1, n):
        z_prev = z[t - 1]
        z2_prev = z_prev * z_prev
        indicator = 1.0 if z_prev < 0 else 0.0

        g = base + (alpha + gamma_p * indicator) * z2_prev + beta * g
        g = max(g, 1e-10)

        z2_t = z[t] * z[t]
        loglik += -0.5 * (np.log(2.0 * np.pi) + np.log(g) + z2_t / g)

    return -loglik


@njit
def _gjr_filter(params, z, n):
    """Run GJR filter, return g array."""
    alpha = params[0]
    gamma_p = params[1]
    beta = params[2]

    base = 1.0 - alpha - beta - gamma_p / 2.0
    g_arr = np.ones(n)

    for t in range(1, n):
        z_prev = z[t - 1]
        z2_prev = z_prev * z_prev
        indicator = 1.0 if z_prev < 0 else 0.0
        g_arr[t] = base + (alpha + gamma_p * indicator) * z2_prev + beta * g_arr[t - 1]
        g_arr[t] = max(g_arr[t], 1e-10)

    return g_arr


def estimate_gjr_on_z(z: np.ndarray) -> tuple[np.ndarray, float, float, float]:
    """Estimate GJR-GARCH on standardized returns z_t = r_t / sqrt(τ_t).

    Returns: (g_array, alpha, gamma, beta)
    """
    n = len(z)

    best_nll = np.inf
    best_params = None

    # Multi-start optimization
    starts = [
        [0.05, 0.05, 0.90],
        [0.03, 0.10, 0.85],
        [0.08, 0.03, 0.88],
        [0.10, 0.10, 0.75],
        [0.02, 0.02, 0.94],
        [0.06, 0.08, 0.82],
    ]

    bounds = [(1e-6, 0.3), (1e-6, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = minimize(
                lambda p: _gjr_nll(p, z, n),
                x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-12}
            )
            if res.fun < best_nll:
                best_nll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        # Fallback
        best_params = np.array([0.05, 0.05, 0.90])

    alpha, gamma_p, beta = best_params
    g_arr = _gjr_filter(best_params, z, n)
    return g_arr, alpha, gamma_p, beta


# ======================================================================
# Standard GJR-GARCH(1,1) benchmark
# ======================================================================

@njit
def _std_gjr_nll(params, returns, n):
    """Standard GJR-GARCH(1,1) negative log-likelihood."""
    omega = params[0]
    alpha = params[1]
    gamma_p = params[2]
    beta = params[3]

    if omega <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + beta + gamma_p / 2.0 >= 1.0:
        return 1e10

    sigma2 = np.var(returns)
    loglik = 0.0

    for t in range(1, n):
        r = returns[t - 1]
        indicator = 1.0 if r < 0 else 0.0
        sigma2 = omega + (alpha + gamma_p * indicator) * r * r + beta * sigma2
        sigma2 = max(sigma2, 1e-20)
        loglik += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)

    return -loglik


@njit
def _std_gjr_forecast(params, returns, n):
    """One-step-ahead forecast from standard GJR-GARCH."""
    omega = params[0]
    alpha = params[1]
    gamma_p = params[2]
    beta = params[3]

    sigma2 = np.var(returns)
    for t in range(1, n):
        r = returns[t - 1]
        indicator = 1.0 if r < 0 else 0.0
        sigma2 = omega + (alpha + gamma_p * indicator) * r * r + beta * sigma2
        sigma2 = max(sigma2, 1e-20)

    r_last = returns[n - 1]
    indicator = 1.0 if r_last < 0 else 0.0
    fc = omega + (alpha + gamma_p * indicator) * r_last * r_last + beta * sigma2
    return max(fc, 1e-20)


def fit_std_gjr(returns: np.ndarray) -> np.ndarray:
    """Fit standard GJR-GARCH and return parameters."""
    n = len(returns)
    best_nll = np.inf
    best_params = None

    var_r = np.var(returns)
    starts = [
        [var_r * 0.05, 0.05, 0.05, 0.90],
        [var_r * 0.02, 0.03, 0.10, 0.85],
        [var_r * 0.10, 0.08, 0.03, 0.88],
        [var_r * 0.01, 0.10, 0.10, 0.75],
    ]

    bounds = [(1e-10, var_r), (1e-6, 0.3), (1e-6, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = minimize(
                lambda p: _std_gjr_nll(p, returns, n),
                x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-12}
            )
            if res.fun < best_nll:
                best_nll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        best_params = np.array([var_r * 0.05, 0.05, 0.05, 0.90])

    return best_params


# ======================================================================
# HAR-ABS benchmark (K530 gold standard)
# ======================================================================

def har_abs_forecast(returns: np.ndarray) -> float:
    """Fit HAR-ABS model and produce 1-step-ahead forecast.

    σ²_{t+1} = c + β1*|r_t| + β5*MA5(|r|) + β22*MA22(|r|)

    Target: |r_{t+1}|, then squared for QLIKE comparison.
    """
    n = len(returns)
    abs_r = np.abs(returns)

    # Need at least 22 lags
    if n < 50:
        return np.var(returns)

    # Construct regressors
    T = n - 22  # usable observations
    Y = abs_r[22:]  # |r_t| for t=22..n-1

    X = np.ones((T, 4))
    for i in range(T):
        t = i + 22
        X[i, 1] = abs_r[t - 1]  # |r_{t-1}|
        X[i, 2] = np.mean(abs_r[t - 5:t])  # MA5
        X[i, 3] = np.mean(abs_r[t - 22:t])  # MA22

    # OLS
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return np.var(returns)

    # Forecast: use last observation
    x_new = np.array([
        1.0,
        abs_r[-1],
        np.mean(abs_r[-5:]),
        np.mean(abs_r[-22:])
    ])

    fc_abs = np.dot(beta, x_new)
    fc_abs = max(fc_abs, 1e-6)

    # Return σ² forecast (squared absolute return forecast)
    return fc_abs ** 2


# ======================================================================
# MF2-GARCH forecast (2-step)
# ======================================================================

def mf2_forecast(returns: np.ndarray) -> tuple[float, dict]:
    """Full MF2-GARCH 2-step estimation and 1-step-ahead forecast.

    Step 1: Estimate τ_t = exp(ω + δ*log(RV22_{t-1}))
    Step 2: Estimate GJR on z_t = r_t / sqrt(τ_t)
    Forecast: σ²_{t+1} = g_{t+1|t} × τ_{t+1|t}

    Returns: (forecast_variance, diagnostics_dict)
    """
    n = len(returns)

    # Step 1: Long-run component
    tau, omega, delta = estimate_tau(returns)

    # Standardize returns by long-run component
    # z_t = r_t / sqrt(τ_t)
    z = np.zeros(n)
    for t in range(n):
        if np.isnan(tau[t]) or tau[t] <= 0:
            z[t] = returns[t] / np.sqrt(np.var(returns))
        else:
            z[t] = returns[t] / np.sqrt(tau[t])

    # Step 2: Short-run GJR on z
    g_arr, alpha, gamma_p, beta = estimate_gjr_on_z(z)

    # Forecast τ_{t+1}
    rv22_last = np.mean(returns[-22:] ** 2)
    tau_next = np.exp(omega + delta * np.log(max(rv22_last, 1e-20)))

    # Forecast g_{t+1}
    z_last = z[-1]
    indicator = 1.0 if z_last < 0 else 0.0
    base = 1.0 - alpha - beta - gamma_p / 2.0
    g_next = base + (alpha + gamma_p * indicator) * z_last ** 2 + beta * g_arr[-1]
    g_next = max(g_next, 1e-10)

    # Combined forecast
    sigma2_fc = tau_next * g_next
    sigma2_fc = max(sigma2_fc, 1e-20)

    persistence = alpha + beta + gamma_p / 2.0
    diagnostics = {
        "omega": float(omega),
        "delta": float(delta),
        "alpha": float(alpha),
        "gamma": float(gamma_p),
        "beta": float(beta),
        "persistence": float(persistence),
        "tau_last": float(tau[-1]),
        "g_last": float(g_arr[-1]),
        "tau_next": float(tau_next),
        "g_next": float(g_next),
    }

    return sigma2_fc, diagnostics


# ======================================================================
# QLIKE loss
# ======================================================================

def qlike(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(RV/σ² - log(RV/σ²) - 1)."""
    ratio = realized / forecast
    ratio = np.maximum(ratio, 1e-20)
    return np.mean(ratio - np.log(ratio) - 1.0)


# ======================================================================
# Diebold-Mariano test
# ======================================================================

def dm_test(loss1: np.ndarray, loss2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test for equal predictive ability.

    H0: E[d_t] = 0 where d_t = L1_t - L2_t
    Negative t-stat means model 1 is better.

    Returns: (t_stat, p_value)
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with automatic bandwidth)
    max_lag = int(np.floor(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0

    for k in range(1, max_lag + 1):
        weight = 1.0 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * weight * gamma_k

    hac_var = max(hac_var, 1e-20)
    t_stat = d_mean / np.sqrt(hac_var / n)

    from scipy.stats import norm
    p_value = 2 * norm.sf(abs(t_stat))

    return float(t_stat), float(p_value)


# ======================================================================
# Main rolling-window evaluation
# ======================================================================

def run_experiment():
    """Run MF2-GARCH vs GJR vs HAR-ABS rolling window evaluation."""
    t0 = time.time()
    print("=" * 70)
    print("K592: MF2-GARCH (Conrad & Engle 2025) — Two-Component Volatility")
    print("=" * 70)

    # Download data
    df = download_data("SPY", "2005-01-01", "2026-03-27")
    returns = df["log_return"].values
    dates = df.index

    # OOS period: 2023-01-01 to 2024-12-31
    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")

    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        print("ERROR: No OOS data found!")
        return

    print(f"\nOOS period: {dates[oos_indices[0]].date()} to {dates[oos_indices[-1]].date()}")
    print(f"OOS days: {len(oos_indices)}")

    w = 2000  # rolling window
    print(f"Rolling window: w={w}")

    # Verify we have enough history
    first_oos_idx = oos_indices[0]
    if first_oos_idx < w + 22:  # need w + 22 days for RV22
        print(f"ERROR: Not enough history. First OOS at {first_oos_idx}, need {w + 22}")
        return

    print(f"First estimation window: {dates[first_oos_idx - w].date()} to {dates[first_oos_idx - 1].date()}")

    # Storage for forecasts
    n_oos = len(oos_indices)
    fc_mf2 = np.zeros(n_oos)
    fc_gjr = np.zeros(n_oos)
    fc_har = np.zeros(n_oos)
    rv_actual = np.zeros(n_oos)

    # Diagnostics storage (sample a few)
    diag_samples = {}
    refit_interval = 22  # refit every 22 days (monthly)

    # Cached parameters
    cached_gjr_params = None
    cached_mf2_diag = None
    last_refit = -refit_interval  # force initial fit

    print(f"\nRunning rolling forecasts (refit every {refit_interval} days)...")

    for i, oos_idx in enumerate(oos_indices):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Day {i + 1}/{n_oos} ({dates[oos_idx].date()})...", flush=True)

        # Training window
        train_start = oos_idx - w
        train_end = oos_idx  # exclusive: train on [start, end)
        train_ret = returns[train_start:train_end]

        # Realized variance proxy: r²_t
        rv_actual[i] = returns[oos_idx] ** 2

        # Refit models periodically
        need_refit = (i - last_refit) >= refit_interval

        # --- MF2-GARCH ---
        if need_refit:
            try:
                fc_val, diag = mf2_forecast(train_ret)
                fc_mf2[i] = fc_val
                cached_mf2_diag = diag
                if i in [0, n_oos // 4, n_oos // 2, 3 * n_oos // 4]:
                    diag_samples[str(dates[oos_idx].date())] = diag
            except Exception as e:
                print(f"    MF2 error at {dates[oos_idx].date()}: {e}")
                fc_mf2[i] = np.var(train_ret)
        else:
            # Quick update: reuse params, update tau and g with new data
            try:
                fc_val, _ = mf2_forecast(train_ret)
                fc_mf2[i] = fc_val
            except Exception:
                fc_mf2[i] = np.var(train_ret)

        # --- Standard GJR-GARCH ---
        if need_refit:
            try:
                cached_gjr_params = fit_std_gjr(train_ret)
            except Exception:
                var_r = np.var(train_ret)
                cached_gjr_params = np.array([var_r * 0.05, 0.05, 0.05, 0.90])

        try:
            fc_gjr[i] = _std_gjr_forecast(cached_gjr_params, train_ret, len(train_ret))
        except Exception:
            fc_gjr[i] = np.var(train_ret)

        # --- HAR-ABS ---
        try:
            fc_har[i] = har_abs_forecast(train_ret)
        except Exception:
            fc_har[i] = np.var(train_ret)

        if need_refit:
            last_refit = i

    # Ensure no zeros or negatives
    fc_mf2 = np.maximum(fc_mf2, 1e-20)
    fc_gjr = np.maximum(fc_gjr, 1e-20)
    fc_har = np.maximum(fc_har, 1e-20)
    rv_actual = np.maximum(rv_actual, 1e-20)

    elapsed = time.time() - t0
    print(f"\nForecasting completed in {elapsed:.1f}s")

    # ======================================================================
    # Evaluation
    # ======================================================================
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    # QLIKE
    ql_mf2 = qlike(rv_actual, fc_mf2)
    ql_gjr = qlike(rv_actual, fc_gjr)
    ql_har = qlike(rv_actual, fc_har)

    print(f"\nQLIKE (lower is better):")
    print(f"  MF2-GARCH:     {ql_mf2:.6f}")
    print(f"  GJR-GARCH:     {ql_gjr:.6f}")
    print(f"  HAR-ABS:       {ql_har:.6f}")

    # QLIKE ratios
    mf2_vs_gjr_pct = (ql_mf2 / ql_gjr - 1) * 100
    mf2_vs_har_pct = (ql_mf2 / ql_har - 1) * 100
    har_vs_gjr_pct = (ql_har / ql_gjr - 1) * 100

    print(f"\nQLIKE ratios (negative = model 1 wins):")
    print(f"  MF2 vs GJR:    {mf2_vs_gjr_pct:+.3f}%")
    print(f"  MF2 vs HAR:    {mf2_vs_har_pct:+.3f}%")
    print(f"  HAR vs GJR:    {har_vs_gjr_pct:+.3f}%")

    # Pointwise QLIKE losses for DM test
    loss_mf2 = rv_actual / fc_mf2 - np.log(rv_actual / fc_mf2) - 1.0
    loss_gjr = rv_actual / fc_gjr - np.log(rv_actual / fc_gjr) - 1.0
    loss_har = rv_actual / fc_har - np.log(rv_actual / fc_har) - 1.0

    # DM tests
    dm_mf2_gjr, p_mf2_gjr = dm_test(loss_mf2, loss_gjr)
    dm_mf2_har, p_mf2_har = dm_test(loss_mf2, loss_har)
    dm_har_gjr, p_har_gjr = dm_test(loss_har, loss_gjr)

    print(f"\nDiebold-Mariano tests (negative t = model 1 better):")
    print(f"  MF2 vs GJR:    t={dm_mf2_gjr:+.4f}, p={p_mf2_gjr:.4f} {'***' if p_mf2_gjr < 0.001 else '**' if p_mf2_gjr < 0.01 else '*' if p_mf2_gjr < 0.05 else 'NS'}")
    print(f"  MF2 vs HAR:    t={dm_mf2_har:+.4f}, p={p_mf2_har:.4f} {'***' if p_mf2_har < 0.001 else '**' if p_mf2_har < 0.01 else '*' if p_mf2_har < 0.05 else 'NS'}")
    print(f"  HAR vs GJR:    t={dm_har_gjr:+.4f}, p={p_har_gjr:.4f} {'***' if p_har_gjr < 0.001 else '**' if p_har_gjr < 0.01 else '*' if p_har_gjr < 0.05 else 'NS'}")

    # Harvey (2016) threshold
    print(f"\nHarvey (2016) |t| > 3.0 threshold:")
    print(f"  MF2 vs GJR:    {'PASS' if abs(dm_mf2_gjr) > 3.0 else 'FAIL'} (|t|={abs(dm_mf2_gjr):.2f})")
    print(f"  MF2 vs HAR:    {'PASS' if abs(dm_mf2_har) > 3.0 else 'FAIL'} (|t|={abs(dm_mf2_har):.2f})")
    print(f"  HAR vs GJR:    {'PASS' if abs(dm_har_gjr) > 3.0 else 'FAIL'} (|t|={abs(dm_har_gjr):.2f})")

    # Diagnostics
    print(f"\nMF2-GARCH diagnostics (sampled windows):")
    for date_str, diag in diag_samples.items():
        print(f"  {date_str}: ω={diag['omega']:.4f}, δ={diag['delta']:.4f}, "
              f"α={diag['alpha']:.4f}, γ={diag['gamma']:.4f}, β={diag['beta']:.4f}, "
              f"pers={diag['persistence']:.4f}")

    # Forecast descriptive statistics
    print(f"\nForecast statistics:")
    print(f"  {'Model':<15} {'Mean':>12} {'Std':>12} {'Min':>12} {'Max':>12}")
    for name, fc in [("MF2-GARCH", fc_mf2), ("GJR-GARCH", fc_gjr), ("HAR-ABS", fc_har), ("Realized r²", rv_actual)]:
        # Convert to annualized vol %
        ann = np.sqrt(fc * 252) * 100
        print(f"  {name:<15} {np.mean(ann):>12.2f}% {np.std(ann):>12.2f}% {np.min(ann):>12.2f}% {np.max(ann):>12.2f}%")

    # Correlation of forecasts
    corr_mf2_gjr = np.corrcoef(fc_mf2, fc_gjr)[0, 1]
    corr_mf2_har = np.corrcoef(fc_mf2, fc_har)[0, 1]
    corr_gjr_har = np.corrcoef(fc_gjr, fc_har)[0, 1]

    print(f"\nForecast correlations:")
    print(f"  MF2 vs GJR:    {corr_mf2_gjr:.4f}")
    print(f"  MF2 vs HAR:    {corr_mf2_har:.4f}")
    print(f"  GJR vs HAR:    {corr_gjr_har:.4f}")

    # Sub-period analysis (2023 vs 2024)
    print(f"\nSub-period QLIKE:")
    for year in [2023, 2024]:
        year_mask = np.array([dates[oos_indices[j]].year == year for j in range(n_oos)])
        if year_mask.sum() > 0:
            ql_m = qlike(rv_actual[year_mask], fc_mf2[year_mask])
            ql_g = qlike(rv_actual[year_mask], fc_gjr[year_mask])
            ql_h = qlike(rv_actual[year_mask], fc_har[year_mask])
            print(f"  {year}: MF2={ql_m:.6f}, GJR={ql_g:.6f}, HAR={ql_h:.6f}  "
                  f"MF2 vs GJR: {(ql_m / ql_g - 1) * 100:+.3f}%  "
                  f"MF2 vs HAR: {(ql_m / ql_h - 1) * 100:+.3f}%")

    # Winner determination
    print(f"\n{'=' * 70}")
    if ql_mf2 < ql_gjr and ql_mf2 < ql_har:
        winner = "MF2-GARCH"
    elif ql_har < ql_gjr:
        winner = "HAR-ABS"
    else:
        winner = "GJR-GARCH"
    print(f"WINNER by QLIKE: {winner}")

    mf2_sig = "YES" if p_mf2_gjr < 0.05 else "NO"
    mf2_harvey = "YES" if abs(dm_mf2_gjr) > 3.0 else "NO"
    print(f"MF2 significantly better than GJR? {mf2_sig} (Harvey pass: {mf2_harvey})")

    # ======================================================================
    # Save results
    # ======================================================================
    results = {
        "experiment_id": "K592",
        "title": "MF2-GARCH (Conrad & Engle 2025) — Two-Component Volatility",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "model": "MF2-GARCH (2-step)",
            "short_run": "GJR on z_t = r_t / sqrt(τ_t), E[g_t]=1 constraint",
            "long_run": "τ_t = exp(ω + δ*log(RV22_{t-1}))",
            "benchmarks": ["GJR-GARCH(1,1)", "HAR-ABS"],
            "estimation": "2-step: (1) log-linear τ by OLS, (2) GJR by MLE on standardized z_t",
            "refit_interval": refit_interval,
            "rolling_window": w,
            "oos_period": f"{dates[oos_indices[0]].date()} to {dates[oos_indices[-1]].date()}",
            "oos_days": n_oos,
            "proxy": "r²_t (daily squared log return)",
            "reference": "Conrad & Engle (2025, Journal of Applied Econometrics)"
        },
        "data": {
            "source": "yfinance",
            "asset": "SPY",
            "period": f"{dates[0].date()} to {dates[-1].date()}",
            "total_days": len(returns),
        },
        "results": {
            "qlike": {
                "MF2_GARCH": round(ql_mf2, 6),
                "GJR_GARCH": round(ql_gjr, 6),
                "HAR_ABS": round(ql_har, 6),
            },
            "qlike_ratio_pct": {
                "MF2_vs_GJR": round(mf2_vs_gjr_pct, 4),
                "MF2_vs_HAR": round(mf2_vs_har_pct, 4),
                "HAR_vs_GJR": round(har_vs_gjr_pct, 4),
            },
            "dm_tests": {
                "MF2_vs_GJR": {"t_stat": round(dm_mf2_gjr, 4), "p_value": round(p_mf2_gjr, 4),
                               "significant_5pct": p_mf2_gjr < 0.05,
                               "harvey_pass": abs(dm_mf2_gjr) > 3.0},
                "MF2_vs_HAR": {"t_stat": round(dm_mf2_har, 4), "p_value": round(p_mf2_har, 4),
                               "significant_5pct": p_mf2_har < 0.05,
                               "harvey_pass": abs(dm_mf2_har) > 3.0},
                "HAR_vs_GJR": {"t_stat": round(dm_har_gjr, 4), "p_value": round(p_har_gjr, 4),
                               "significant_5pct": p_har_gjr < 0.05,
                               "harvey_pass": abs(dm_har_gjr) > 3.0},
            },
            "winner": winner,
            "mf2_beats_gjr_significant": p_mf2_gjr < 0.05,
            "mf2_beats_gjr_harvey": abs(dm_mf2_gjr) > 3.0,
        },
        "diagnostics": {
            "mf2_params_samples": diag_samples,
            "forecast_correlations": {
                "MF2_GJR": round(corr_mf2_gjr, 4),
                "MF2_HAR": round(corr_mf2_har, 4),
                "GJR_HAR": round(corr_gjr_har, 4),
            },
            "forecast_stats": {
                model: {
                    "mean_ann_vol_pct": round(float(np.mean(np.sqrt(fc * 252) * 100)), 2),
                    "std_ann_vol_pct": round(float(np.std(np.sqrt(fc * 252) * 100)), 2),
                }
                for model, fc in [("MF2_GARCH", fc_mf2), ("GJR_GARCH", fc_gjr), ("HAR_ABS", fc_har)]
            },
        },
        "sub_period": {},
        "comparison_with_prior": {
            "K144_mf2_joint_qml": "K144 used joint QML with linear MEM (λ1+λ2*V^m+λ3*τ). K592 uses 2-step log-linear.",
            "K530_har_abs": "K530 established HAR-ABS as gold standard (DM=-15.45 vs GJR).",
            "K591_post_hoc": "K591 post-hoc MF2 correction failed (+0.3-2.4% QLIKE). K592 tests proper 2-step.",
        },
        "elapsed_seconds": round(elapsed, 1),
    }

    # Add sub-period results
    for year in [2023, 2024]:
        year_mask = np.array([dates[oos_indices[j]].year == year for j in range(n_oos)])
        if year_mask.sum() > 0:
            ql_m = qlike(rv_actual[year_mask], fc_mf2[year_mask])
            ql_g = qlike(rv_actual[year_mask], fc_gjr[year_mask])
            ql_h = qlike(rv_actual[year_mask], fc_har[year_mask])
            results["sub_period"][str(year)] = {
                "MF2_GARCH": round(ql_m, 6),
                "GJR_GARCH": round(ql_g, 6),
                "HAR_ABS": round(ql_h, 6),
                "MF2_vs_GJR_pct": round((ql_m / ql_g - 1) * 100, 4),
                "MF2_vs_HAR_pct": round((ql_m / ql_h - 1) * 100, 4),
                "n_days": int(year_mask.sum()),
            }

    # Save results JSON
    results_path = Path(__file__).parent / "k592_mf2_garch_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    # Conclusion
    print(f"\n{'=' * 70}")
    print("CONCLUSION")
    print("=" * 70)
    if ql_mf2 < ql_gjr and p_mf2_gjr < 0.05:
        print(f"MF2-GARCH (2-step) SIGNIFICANTLY BEATS GJR-GARCH (QLIKE {mf2_vs_gjr_pct:+.3f}%, DM t={dm_mf2_gjr:.2f})")
        if abs(dm_mf2_gjr) > 3.0:
            print("  Passes Harvey (2016) threshold — robust finding!")
        else:
            print("  FAILS Harvey (2016) threshold — conventional significance only.")
    elif ql_mf2 < ql_gjr:
        print(f"MF2-GARCH (2-step) slightly better than GJR (QLIKE {mf2_vs_gjr_pct:+.3f}%) but NOT significant (p={p_mf2_gjr:.4f})")
    else:
        print(f"MF2-GARCH (2-step) does NOT beat GJR-GARCH (QLIKE {mf2_vs_gjr_pct:+.3f}%)")
        print(f"  GJR-GARCH remains the Occam winner for SPY daily vol prediction.")

    if ql_har < ql_gjr:
        print(f"\nHAR-ABS confirms K530: beats GJR by {har_vs_gjr_pct:+.3f}% (DM t={dm_har_gjr:.2f})")

    print(f"\nKey insight: Conrad & Engle's MF2-GARCH was tested with 2-step log-linear τ specification.")
    print(f"  Differs from K144 (joint QML, linear MEM) — both test the same decomposition idea.")
    print(f"  QLIKE ceiling stands: {abs(dm_mf2_gjr) > 3.0 and dm_mf2_gjr < 0 and 'BROKEN' or 'CONFIRMED'}")

    return results


if __name__ == "__main__":
    run_experiment()
