"""K144: MF2-GARCH Cross-Asset Bond Verification (v2 — proper joint QML)

Tests whether MF2-GARCH's advantage extends to OTHER bond/low-gamma assets.
K141 found MF2-GARCH wins for TLT (gamma~0) but NOT for SPY/GLD (gamma>0.10).
Hypothesis: MF2 wins iff gamma~0 -> robust asset-class-dependent model selection rule.

Assets: IEF (7-10yr Treasury), AGG (US Agg Bond), LQD (IG Corp), HYG (HY Corp)

MF2-GARCH specification (Conrad & Engle 2025):
  sigma^2_t = tau_t * g_t

  Short-run g_t (normalized GJR):
    g_t = (1 - alpha - gamma/2 - beta)
        + (alpha + gamma * I_{r_{t-1}<0}) * (r^2_{t-1} / tau_{t-1})
        + beta * g_{t-1}

  Long-run tau_t:
    tau_t = lam1 + lam2 * V^m_{t-1} + lam3 * tau_{t-1}
    V_t   = r^2_t / (g_t * tau_t)
    V^m_t = (1/m) * sum_{j=1}^{m} V_{t-j}

  Joint QML estimation with L-BFGS-B.  m in {22, 44, 66}, pick by BIC.

Usage:
    uv run python experiments/k144_mf2_cross_bond.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Try numba for speed; fall back to pure numpy
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

def download_asset(ticker: str, start: str = "2005-01-01", end: str = "2026-03-22") -> pd.Series:
    """Download daily log returns for a ticker."""
    import yfinance as yf
    print(f"  Downloading {ticker} ({start} to {end})...", end="", flush=True)
    df = yf.download(ticker, start=start, end=end, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_localize(None)
    df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
    returns = df["log_return"].dropna()
    print(f" {len(returns)} days ({returns.index[0].date()} to {returns.index[-1].date()})")
    return returns


# ======================================================================
# MF2-GARCH core  (numba-accelerated inner loops)
# ======================================================================

@njit
def _mf2_filter(alpha, gamma_p, beta, lam1, lam2, lam3, returns, n, m):
    """Run the full MF2-GARCH filter and return negative log-likelihood.

    Parameters (all floats except returns which is ndarray):
        alpha, gamma_p, beta   -- short-run GJR params
        lam1, lam2, lam3       -- long-run tau params
        returns                -- array of log returns (length n)
        n                      -- length of returns
        m                      -- lookback for V^m

    Returns (nll, g_arr, tau_arr, V_arr):
        nll      -- negative log-likelihood (scalar)
        g_arr    -- short-run component array
        tau_arr  -- long-run component array
        V_arr    -- standardized variance ratio array
    """
    base = 1.0 - alpha - beta - gamma_p / 2.0

    g_arr = np.ones(n)
    tau_arr = np.ones(n)
    V_arr = np.ones(n)

    # Initialize tau_0 with sample variance
    var_r = 0.0
    for i in range(n):
        var_r += returns[i] * returns[i]
    var_r /= n
    tau_arr[0] = max(var_r, 1e-20)
    g_arr[0] = 1.0
    V_arr[0] = 1.0

    loglik = 0.0

    for t in range(1, n):
        r_prev = returns[t - 1]
        r2_prev = r_prev * r_prev
        indicator = 1.0 if r_prev < 0 else 0.0

        # Short-run g_t
        r2_over_tau = r2_prev / max(tau_arr[t - 1], 1e-20)
        g_t = base + (alpha + gamma_p * indicator) * r2_over_tau + beta * g_arr[t - 1]
        g_t = max(g_t, 1e-6)
        g_arr[t] = g_t

        # V_{t-1} = r^2_{t-1} / (g_{t-1} * tau_{t-1})
        V_prev = r2_prev / max(g_arr[t - 1] * tau_arr[t - 1], 1e-20)
        V_arr[t - 1] = V_prev

        # V^m_{t-1} = average of V over last m periods
        vm = 0.0
        count = 0
        for j in range(1, m + 1):
            idx = t - j
            if idx >= 0:
                vm += V_arr[idx]
                count += 1
        if count > 0:
            vm /= count
        else:
            vm = 1.0

        # Long-run tau_t
        tau_t = lam1 + lam2 * vm + lam3 * tau_arr[t - 1]
        tau_t = max(tau_t, 1e-20)
        tau_arr[t] = tau_t

        # sigma^2_t = tau_t * g_t
        sigma2 = tau_t * g_t
        sigma2 = max(sigma2, 1e-20)

        r2_t = returns[t] * returns[t]
        loglik += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + r2_t / sigma2)

    return -loglik, g_arr, tau_arr, V_arr


@njit
def _mf2_nll_only(alpha, gamma_p, beta, lam1, lam2, lam3, returns, n, m):
    """Compute only the negative log-likelihood (for optimization)."""
    base = 1.0 - alpha - beta - gamma_p / 2.0

    g_prev = 1.0
    var_r = 0.0
    for i in range(n):
        var_r += returns[i] * returns[i]
    var_r /= n
    tau_prev = max(var_r, 1e-20)

    # Ring buffer for V values (only need last m)
    V_buf = np.ones(m)
    buf_idx = 0

    loglik = 0.0

    for t in range(1, n):
        r_prev = returns[t - 1]
        r2_prev = r_prev * r_prev
        indicator = 1.0 if r_prev < 0 else 0.0

        r2_over_tau = r2_prev / max(tau_prev, 1e-20)
        g_t = base + (alpha + gamma_p * indicator) * r2_over_tau + beta * g_prev
        g_t = max(g_t, 1e-6)

        V_prev = r2_prev / max(g_prev * tau_prev, 1e-20)
        V_buf[buf_idx % m] = V_prev
        buf_idx += 1

        # V^m: average of ring buffer (up to min(t, m) filled entries)
        count = min(buf_idx, m)
        vm = 0.0
        for j in range(count):
            vm += V_buf[j]
        vm /= count

        tau_t = lam1 + lam2 * vm + lam3 * tau_prev
        tau_t = max(tau_t, 1e-20)

        sigma2 = tau_t * g_t
        sigma2 = max(sigma2, 1e-20)

        r2_t = returns[t] * returns[t]
        loglik += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + r2_t / sigma2)

        g_prev = g_t
        tau_prev = tau_t

    return -loglik


@njit
def _gjr_loglik(params, returns, n):
    """Negative log-likelihood for standard GJR-GARCH(1,1).

    params = [omega, alpha, gamma, beta]
    """
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
        r2 = returns[t] * returns[t]
        loglik += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + r2 / sigma2)

    return -loglik


@njit
def _gjr_forecast(params, returns, n):
    """1-step-ahead forecast from GJR-GARCH."""
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


@njit
def _mf2_forecast(alpha, gamma_p, beta, lam1, lam2, lam3, returns, n, m):
    """1-step-ahead forecast from MF2-GARCH."""
    base = 1.0 - alpha - beta - gamma_p / 2.0

    g_prev = 1.0
    var_r = 0.0
    for i in range(n):
        var_r += returns[i] * returns[i]
    var_r /= n
    tau_prev = max(var_r, 1e-20)

    V_buf = np.ones(m)
    buf_idx = 0

    for t in range(1, n):
        r_prev = returns[t - 1]
        r2_prev = r_prev * r_prev
        indicator = 1.0 if r_prev < 0 else 0.0

        r2_over_tau = r2_prev / max(tau_prev, 1e-20)
        g_t = base + (alpha + gamma_p * indicator) * r2_over_tau + beta * g_prev
        g_t = max(g_t, 1e-6)

        V_prev = r2_prev / max(g_prev * tau_prev, 1e-20)
        V_buf[buf_idx % m] = V_prev
        buf_idx += 1

        count = min(buf_idx, m)
        vm = 0.0
        for j in range(count):
            vm += V_buf[j]
        vm /= count

        tau_t = lam1 + lam2 * vm + lam3 * tau_prev
        tau_t = max(tau_t, 1e-20)

        g_prev = g_t
        tau_prev = tau_t

    # Forecast: one more step
    r_last = returns[n - 1]
    r2_last = r_last * r_last
    indicator = 1.0 if r_last < 0 else 0.0

    r2_over_tau = r2_last / max(tau_prev, 1e-20)
    g_next = base + (alpha + gamma_p * indicator) * r2_over_tau + beta * g_prev
    g_next = max(g_next, 1e-6)

    V_last = r2_last / max(g_prev * tau_prev, 1e-20)
    V_buf[buf_idx % m] = V_last
    buf_idx += 1
    count = min(buf_idx, m)
    vm = 0.0
    for j in range(count):
        vm += V_buf[j]
    vm /= count

    tau_next = lam1 + lam2 * vm + lam3 * tau_prev
    tau_next = max(tau_next, 1e-20)

    return tau_next * g_next


# ======================================================================
# Estimation
# ======================================================================

def fit_mf2_joint(returns_arr: np.ndarray, m: int, n_starts: int = 8):
    """Joint QML estimation of MF2-GARCH via L-BFGS-B.

    Parameters: [alpha, gamma, beta, lam1, lam2, lam3]
    """
    from scipy.optimize import minimize

    n = len(returns_arr)
    var_r = float(np.var(returns_arr))

    def objective(x):
        alpha, gamma_p, beta, lam1, lam2, lam3 = x
        # Stationarity + positivity constraints are handled by bounds
        base = 1.0 - alpha - beta - gamma_p / 2.0
        if base < 0.01:
            return 1e10
        if alpha + beta + gamma_p / 2.0 >= 0.999:
            return 1e10
        if lam3 >= 0.999:
            return 1e10
        return _mf2_nll_only(alpha, gamma_p, beta, lam1, lam2, lam3,
                             returns_arr, n, m)

    bounds = [
        (1e-6, 0.30),    # alpha
        (0.0, 0.30),     # gamma
        (0.50, 0.999),   # beta
        (1e-10, var_r),  # lam1
        (1e-10, var_r * 2),  # lam2
        (0.50, 0.999),   # lam3
    ]

    best_nll = 1e20
    best_x = None

    for trial in range(n_starts):
        np.random.seed(trial * 137 + 42)
        alpha0 = np.random.uniform(0.01, 0.12)
        gamma0 = np.random.uniform(0.0, 0.10)
        beta0 = np.random.uniform(0.75, 0.95)
        if alpha0 + beta0 + gamma0 / 2 >= 0.98:
            beta0 = 0.97 - alpha0 - gamma0 / 2

        lam1_0 = var_r * np.random.uniform(0.001, 0.05)
        lam2_0 = var_r * np.random.uniform(0.01, 0.20)
        lam3_0 = np.random.uniform(0.80, 0.97)

        x0 = np.array([alpha0, gamma0, beta0, lam1_0, lam2_0, lam3_0])

        try:
            res = minimize(
                objective, x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 3000, "ftol": 1e-10, "gtol": 1e-7},
            )
            if res.fun < best_nll and res.fun < 1e9:
                best_nll = res.fun
                best_x = res.x
        except Exception:
            continue

    if best_x is None:
        return None

    alpha, gamma_est, beta, lam1, lam2, lam3 = best_x
    n_params = 6
    bic = 2 * best_nll + n_params * np.log(n)

    return {
        "alpha": float(alpha),
        "gamma": float(gamma_est),
        "beta": float(beta),
        "lam1": float(lam1),
        "lam2": float(lam2),
        "lam3": float(lam3),
        "persistence_short": float(alpha + beta + gamma_est / 2),
        "nll": float(best_nll),
        "bic": float(bic),
        "n_params": n_params,
        "m": m,
    }


def fit_gjr(returns_arr: np.ndarray, n_starts: int = 8):
    """Fit GJR-GARCH(1,1) via MLE with L-BFGS-B."""
    from scipy.optimize import minimize

    n = len(returns_arr)
    var_r = float(np.var(returns_arr))

    def objective(x):
        return _gjr_loglik(x, returns_arr, n)

    bounds = [
        (1e-12, var_r * 0.5),  # omega
        (1e-6, 0.30),          # alpha
        (0.0, 0.50),           # gamma
        (0.50, 0.999),         # beta
    ]

    best_nll = 1e20
    best_x = None

    for trial in range(n_starts):
        np.random.seed(trial * 257 + 13)
        omega0 = var_r * np.random.uniform(0.01, 0.10)
        alpha0 = np.random.uniform(0.01, 0.12)
        gamma0 = np.random.uniform(0.0, 0.15)
        beta0 = np.random.uniform(0.75, 0.95)
        if alpha0 + beta0 + gamma0 / 2 >= 0.98:
            beta0 = 0.97 - alpha0 - gamma0 / 2

        x0 = np.array([omega0, alpha0, gamma0, beta0])

        try:
            res = minimize(
                objective, x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 3000, "ftol": 1e-10, "gtol": 1e-7},
            )
            if res.fun < best_nll and res.fun < 1e9:
                best_nll = res.fun
                best_x = res.x
        except Exception:
            continue

    if best_x is None:
        return None

    omega, alpha, gamma_est, beta = best_x
    n_params = 4
    bic = 2 * best_nll + n_params * np.log(n)

    return {
        "omega": float(omega),
        "alpha": float(alpha),
        "gamma": float(gamma_est),
        "beta": float(beta),
        "persistence": float(alpha + beta + gamma_est / 2),
        "nll": float(best_nll),
        "bic": float(bic),
        "n_params": n_params,
    }


# ======================================================================
# Gamma estimation (full-sample for classification)
# ======================================================================

def estimate_gamma_fullsample(returns_arr: np.ndarray) -> float:
    """Estimate GJR gamma on the full sample for asset classification."""
    result = fit_gjr(returns_arr, n_starts=10)
    if result is None:
        return float("nan")
    return result["gamma"]


# ======================================================================
# Evaluation
# ======================================================================

def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(rv/fv - log(rv/fv) - 1). Lower is better."""
    mask = (realized > 0) & (forecast > 0)
    rv = realized[mask]
    fv = np.maximum(forecast[mask], 1e-20)
    ratio = rv / fv
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_log(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE in log form: mean(log(fv) + rv/fv). Lower is better."""
    mask = (realized > 0) & (forecast > 0)
    rv = realized[mask]
    fv = np.maximum(forecast[mask], 1e-20)
    return float(np.mean(np.log(fv) + rv / fv))


def mse_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean((realized - forecast) ** 2))


def dm_test_onesided(loss1: np.ndarray, loss2: np.ndarray) -> tuple:
    """One-sided DM test: H0: loss1 >= loss2, H1: loss1 < loss2.
    Negative t -> model 1 is better.
    Returns (t_stat, p_value).
    """
    from scipy.stats import norm as norm_dist

    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return 0.0, 0.5
    d_mean = d.mean()
    # Newey-West HAC variance (bandwidth = floor(n^(1/3)))
    bw = max(1, int(n ** (1 / 3)))
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for j in range(1, bw + 1):
        weight = 1 - j / (bw + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * weight * gamma_j

    hac_var = max(hac_var, 1e-20)
    dm = d_mean / np.sqrt(hac_var / n)
    pval = float(norm_dist.cdf(dm))
    return float(dm), pval


# ======================================================================
# Main experiment loop for one asset
# ======================================================================

def run_asset(ticker: str, returns: pd.Series, window: int = 2000,
              oos_start: str = "2020-01-01", refit_every: int = 63,
              m_values: list = None) -> dict:
    """Run MF2-GARCH vs GJR-GARCH comparison for one asset."""
    if m_values is None:
        m_values = [22, 44, 66]

    all_returns = returns.copy()
    oos_mask = all_returns.index >= oos_start
    oos_dates = all_returns.index[oos_mask]
    n_oos = len(oos_dates)

    if n_oos < 100:
        return {"error": f"Insufficient OOS data: {n_oos} days"}

    # Full-sample gamma for asset classification
    full_gamma = estimate_gamma_fullsample(all_returns.values)

    print(f"\n  {'='*60}")
    print(f"  Asset: {ticker}")
    print(f"  Data:  {all_returns.index[0].date()} to {all_returns.index[-1].date()} ({len(all_returns)} days)")
    print(f"  OOS:   {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")
    print(f"  Window: {window}, Refit: every {refit_every} days")
    print(f"  Full-sample GJR gamma: {full_gamma:.6f}")
    print(f"  {'='*60}")

    all_dates = all_returns.index
    oos_positions = [all_dates.get_loc(d) for d in oos_dates]

    # Storage
    fc_gjr = np.zeros(n_oos)
    fc_mf2 = {m_val: np.zeros(n_oos) for m_val in m_values}
    r2_oos = all_returns.values[oos_mask] ** 2

    # Track fitted params
    last_gjr_params = None
    last_mf2_params = {}

    last_refit = -refit_every
    t0 = time.time()
    n_refits = 0

    for i, pos in enumerate(oos_positions):
        win_start = max(0, pos - window)
        win_returns = all_returns.values[win_start:pos]
        n_win = len(win_returns)

        need_refit = (i - last_refit >= refit_every) or (i == 0)

        if need_refit:
            last_refit = i
            n_refits += 1

            if n_refits > 1 and n_refits % 5 == 0:
                elapsed = time.time() - t0
                pct = i / n_oos
                eta = elapsed / pct * (1 - pct) if pct > 0 else 0
                print(f"    [{i}/{n_oos}] {pct:.0%} done, ETA {eta:.0f}s (refit #{n_refits})")

            # Fit GJR
            gjr_result = fit_gjr(win_returns, n_starts=8)
            if gjr_result is not None:
                last_gjr_params = np.array([
                    gjr_result["omega"], gjr_result["alpha"],
                    gjr_result["gamma"], gjr_result["beta"]
                ])

            # Fit MF2 for each m
            for m_val in m_values:
                mf2_result = fit_mf2_joint(win_returns, m_val, n_starts=8)
                if mf2_result is not None:
                    last_mf2_params[m_val] = mf2_result

        # Generate forecasts
        if last_gjr_params is not None:
            fc_gjr[i] = _gjr_forecast(last_gjr_params, win_returns, n_win)
        else:
            fc_gjr[i] = np.var(win_returns)

        for m_val in m_values:
            if m_val in last_mf2_params:
                p = last_mf2_params[m_val]
                fc_mf2[m_val][i] = _mf2_forecast(
                    p["alpha"], p["gamma"], p["beta"],
                    p["lam1"], p["lam2"], p["lam3"],
                    win_returns, n_win, m_val,
                )
            else:
                fc_mf2[m_val][i] = np.var(win_returns)

    elapsed = time.time() - t0
    print(f"    Completed in {elapsed:.1f}s ({n_refits} refits)")

    # Get gamma from last GJR fit
    gjr_gamma_last = float(last_gjr_params[2]) if last_gjr_params is not None else float("nan")

    # Compute metrics
    ql_gjr = qlike_loss(r2_oos, fc_gjr)
    ql_gjr_log = qlike_log(r2_oos, fc_gjr)
    mse_gjr = mse_loss(r2_oos, fc_gjr)

    # Individual QLIKE losses for DM test
    mask_nz = (r2_oos > 0) & (fc_gjr > 0)
    loss_gjr_arr = r2_oos[mask_nz] / np.maximum(fc_gjr[mask_nz], 1e-20) - \
                   np.log(r2_oos[mask_nz] / np.maximum(fc_gjr[mask_nz], 1e-20)) - 1

    results = {
        "ticker": ticker,
        "n_oos": n_oos,
        "n_refits": n_refits,
        "elapsed_s": round(elapsed, 1),
        "data_range": f"{all_returns.index[0].date()} to {all_returns.index[-1].date()} ({len(all_returns)} obs)",
        "oos_range": f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
        "full_sample_gamma": float(full_gamma),
        "last_fit_gamma": gjr_gamma_last,
        "annualized_vol": float(np.std(all_returns.values[oos_mask]) * np.sqrt(252) * 100),
        "gjr": {
            "qlike": ql_gjr,
            "qlike_log": ql_gjr_log,
            "mse": mse_gjr,
        },
    }

    # Get the last GJR params
    if last_gjr_params is not None:
        results["gjr_params"] = {
            "omega": float(last_gjr_params[0]),
            "alpha": float(last_gjr_params[1]),
            "gamma": float(last_gjr_params[2]),
            "beta": float(last_gjr_params[3]),
        }

    # BIC comparison for MF2 m selection (from last fit window)
    best_mf2_bic = 1e20
    best_mf2_m = m_values[0]

    for m_val in m_values:
        if m_val in last_mf2_params:
            bic_val = last_mf2_params[m_val]["bic"]
            if bic_val < best_mf2_bic:
                best_mf2_bic = bic_val
                best_mf2_m = m_val

    results["bic_selected_m"] = best_mf2_m

    # Evaluate all m variants
    best_mf2_qlike = 1e10
    best_mf2_m_by_qlike = m_values[0]

    for m_val in m_values:
        ql_mf2 = qlike_loss(r2_oos, fc_mf2[m_val])
        ql_mf2_log = qlike_log(r2_oos, fc_mf2[m_val])
        mse_mf2 = mse_loss(r2_oos, fc_mf2[m_val])

        mask_m = (r2_oos > 0) & (fc_mf2[m_val] > 0)
        loss_mf2_arr = r2_oos[mask_m] / np.maximum(fc_mf2[m_val][mask_m], 1e-20) - \
                       np.log(r2_oos[mask_m] / np.maximum(fc_mf2[m_val][mask_m], 1e-20)) - 1

        # DM test: MF2 vs GJR (negative DM = MF2 better)
        # Need same mask for both
        common_mask = mask_nz & mask_m
        loss_mf2_dm = r2_oos[common_mask] / np.maximum(fc_mf2[m_val][common_mask], 1e-20) - \
                      np.log(r2_oos[common_mask] / np.maximum(fc_mf2[m_val][common_mask], 1e-20)) - 1
        loss_gjr_dm = r2_oos[common_mask] / np.maximum(fc_gjr[common_mask], 1e-20) - \
                      np.log(r2_oos[common_mask] / np.maximum(fc_gjr[common_mask], 1e-20)) - 1
        dm_t, dm_p = dm_test_onesided(loss_mf2_dm, loss_gjr_dm)

        better = ql_mf2 < ql_gjr

        bic_val = last_mf2_params[m_val]["bic"] if m_val in last_mf2_params else float("nan")

        results[f"mf2_m{m_val}"] = {
            "qlike": ql_mf2,
            "qlike_log": ql_mf2_log,
            "mse": mse_mf2,
            "dm_t": dm_t,
            "dm_p": dm_p,
            "better_than_gjr": better,
            "bic": bic_val,
        }

        if m_val in last_mf2_params:
            results[f"mf2_m{m_val}"]["params"] = {
                "alpha": last_mf2_params[m_val]["alpha"],
                "gamma": last_mf2_params[m_val]["gamma"],
                "beta": last_mf2_params[m_val]["beta"],
                "lam1": last_mf2_params[m_val]["lam1"],
                "lam2": last_mf2_params[m_val]["lam2"],
                "lam3": last_mf2_params[m_val]["lam3"],
            }

        if ql_mf2 < best_mf2_qlike:
            best_mf2_qlike = ql_mf2
            best_mf2_m_by_qlike = m_val

    results["best_mf2_m_by_bic"] = best_mf2_m
    results["best_mf2_m_by_qlike"] = best_mf2_m_by_qlike
    results["best_mf2_wins_gjr"] = best_mf2_qlike < ql_gjr

    # Print summary
    print(f"\n  --- {ticker} Results ---")
    print(f"  Full-sample gamma: {full_gamma:.6f}  (last-fit gamma: {gjr_gamma_last:.6f})")
    print(f"  Ann. Vol (OOS):    {results['annualized_vol']:.1f}%")
    print(f"  GJR QLIKE:         {ql_gjr:.6f}")
    print(f"  BIC-selected m:    {best_mf2_m}")
    for m_val in m_values:
        r = results[f"mf2_m{m_val}"]
        flag = " ***" if r["better_than_gjr"] and r["dm_p"] < 0.05 else \
               (" **" if r["better_than_gjr"] and r["dm_p"] < 0.10 else \
               (" *" if r["better_than_gjr"] else ""))
        bic_mark = " [BIC]" if m_val == best_mf2_m else ""
        print(f"  MF2 m={m_val:2d} QLIKE: {r['qlike']:.6f}  DM={r['dm_t']:+.3f} p={r['dm_p']:.4f}{flag}{bic_mark}")
    print(f"  Best MF2 (QLIKE): m={best_mf2_m_by_qlike}, wins GJR: {results['best_mf2_wins_gjr']}")

    return results


# ======================================================================
# Main
# ======================================================================

def main():
    np.random.seed(2025)  # Reproducibility

    print("=" * 74)
    print("  K144: MF2-GARCH Cross-Asset Bond Verification (v2)")
    print("  Joint QML estimation — Conrad & Engle 2025 specification")
    print("  Testing gamma-dependent model selection rule")
    print("=" * 74)

    # JIT warmup
    if HAS_NUMBA:
        print("\n  Warming up numba JIT...", end="", flush=True)
        dummy = np.random.randn(200) * 0.01
        _mf2_nll_only(0.05, 0.05, 0.85, 1e-5, 1e-4, 0.90, dummy, 200, 22)
        _mf2_forecast(0.05, 0.05, 0.85, 1e-5, 1e-4, 0.90, dummy, 200, 22)
        _gjr_loglik(np.array([1e-6, 0.05, 0.05, 0.85]), dummy, 200)
        _gjr_forecast(np.array([1e-6, 0.05, 0.05, 0.85]), dummy, 200)
        print(" done")
    else:
        print("\n  Note: numba not available, using pure Python (slower but correct)")

    # Download data
    print("\n  --- Downloading Data ---")
    assets = ["IEF", "AGG", "LQD", "HYG"]
    ref_assets = ["TLT", "SPY"]
    all_tickers = assets + ref_assets
    returns_data = {}
    for ticker in all_tickers:
        try:
            returns_data[ticker] = download_asset(ticker)
        except Exception as e:
            print(f"  ERROR downloading {ticker}: {e}")

    # Run experiments
    print("\n  --- Running Experiments ---")
    all_results = {}
    for ticker in all_tickers:
        if ticker not in returns_data:
            all_results[ticker] = {"error": "Data download failed"}
            continue

        ret = returns_data[ticker]
        if len(ret) < 3000:
            all_results[ticker] = {"error": f"Insufficient data: {len(ret)} days (need 3000+)"}
            continue

        result = run_asset(
            ticker, ret,
            window=2000,
            oos_start="2020-01-01",
            refit_every=63,
            m_values=[22, 44, 66],
        )
        all_results[ticker] = result

    # ======================================================================
    # Grand summary
    # ======================================================================
    print("\n" + "=" * 74)
    print("  GRAND SUMMARY: K144 Cross-Asset Bond Verification (v2)")
    print("=" * 74)

    header = f"  {'Asset':<6} {'Gamma':>8} {'AnnVol':>7} {'GJR QL':>10} {'MF2 QL':>10} {'Winner':>7} {'DM-t':>8} {'DM-p':>8} {'Sig':>4} {'m':>3}"
    print(f"\n{header}")
    print(f"  {'-'*79}")

    scoreboard = {}
    gamma_values = {}

    for ticker in all_tickers:
        if ticker not in all_results or "error" in all_results[ticker]:
            err = all_results.get(ticker, {}).get("error", "unknown")
            print(f"  {ticker:<6} ERROR: {err}")
            continue

        r = all_results[ticker]
        gamma = r["full_sample_gamma"]
        gamma_values[ticker] = gamma

        gjr_q = r["gjr"]["qlike"]
        ann_vol = r["annualized_vol"]

        # Use BIC-selected m for main comparison
        best_m = r["best_mf2_m_by_bic"]
        best_m_key = f"mf2_m{best_m}"
        best_mf2_q = r[best_m_key]["qlike"]
        dm_t = r[best_m_key]["dm_t"]
        dm_p = r[best_m_key]["dm_p"]
        winner = "MF2" if best_mf2_q < gjr_q else "GJR"
        sig = "***" if dm_p < 0.01 else ("**" if dm_p < 0.05 else ("*" if dm_p < 0.10 else ""))

        scoreboard[ticker] = {
            "winner": winner,
            "gjr_qlike": gjr_q,
            "mf2_qlike": best_mf2_q,
            "qlike_improvement_pct": (gjr_q - best_mf2_q) / abs(gjr_q) * 100 if gjr_q != 0 else 0,
            "dm_t": dm_t,
            "dm_p": dm_p,
            "gamma": gamma,
            "best_m": best_m,
        }

        print(f"  {ticker:<6} {gamma:>8.4f} {ann_vol:>6.1f}% {gjr_q:>10.6f} {best_mf2_q:>10.6f} {winner:>7} {dm_t:>+8.3f} {dm_p:>8.4f} {sig:>4} {best_m:>3}")

    # Gamma-dependent rule test
    print(f"\n  --- Gamma-Dependent Rule Test ---")
    low_gamma_thresh = 0.05
    low_gamma_assets = [t for t, g in gamma_values.items() if g < low_gamma_thresh]
    high_gamma_assets = [t for t, g in gamma_values.items() if g >= low_gamma_thresh]

    mf2_wins_low = sum(1 for t in low_gamma_assets if t in scoreboard and scoreboard[t]["winner"] == "MF2")
    mf2_wins_high = sum(1 for t in high_gamma_assets if t in scoreboard and scoreboard[t]["winner"] == "MF2")

    n_low = len(low_gamma_assets)
    n_high = len(high_gamma_assets)

    print(f"  Low gamma (<{low_gamma_thresh}):  {low_gamma_assets}")
    print(f"    MF2 wins: {mf2_wins_low}/{n_low}")
    for t in low_gamma_assets:
        if t in scoreboard:
            s = scoreboard[t]
            print(f"      {t}: gamma={s['gamma']:.4f} winner={s['winner']} DM_p={s['dm_p']:.4f} improv={s['qlike_improvement_pct']:+.2f}%")

    print(f"  High gamma (>={low_gamma_thresh}): {high_gamma_assets}")
    print(f"    MF2 wins: {mf2_wins_high}/{n_high}")
    for t in high_gamma_assets:
        if t in scoreboard:
            s = scoreboard[t]
            print(f"      {t}: gamma={s['gamma']:.4f} winner={s['winner']} DM_p={s['dm_p']:.4f} improv={s['qlike_improvement_pct']:+.2f}%")

    # Rule: MF2 should win for LOW-gamma, GJR should win for HIGH-gamma
    # Require strict majority (>50%) in BOTH directions
    rule_confirmed = (
        n_low > 0 and n_high > 0 and
        mf2_wins_low > n_low * 0.5 and          # strict majority of MF2 wins in low-gamma
        mf2_wins_high < n_high * 0.5             # strict majority of GJR wins in high-gamma
    )

    # Stronger test: with significance
    sig_mf2_low = sum(1 for t in low_gamma_assets
                      if t in scoreboard and scoreboard[t]["winner"] == "MF2" and scoreboard[t]["dm_p"] < 0.10)
    sig_gjr_high = sum(1 for t in high_gamma_assets
                       if t in scoreboard and scoreboard[t]["winner"] == "GJR" and scoreboard[t]["dm_p"] > 0.90)

    print(f"\n  GAMMA-DEPENDENT RULE: {'CONFIRMED' if rule_confirmed else 'NOT CONFIRMED'}")
    print(f"  Significant MF2 wins in low-gamma group:  {sig_mf2_low}/{n_low}")
    print(f"  Significant GJR wins in high-gamma group: {sig_gjr_high}/{n_high}")

    # Key findings
    print(f"\n  --- Key Findings ---")
    findings = []
    if rule_confirmed:
        findings.append(f"MF2-GARCH outperforms GJR for low-gamma (<{low_gamma_thresh}) assets: {mf2_wins_low}/{n_low}.")
        findings.append(f"GJR-GARCH preferred for high-gamma (>={low_gamma_thresh}) assets: {n_high - mf2_wins_high}/{n_high}.")
        findings.append("This constitutes a ROBUST asset-class-dependent model selection rule.")
        findings.append(f"Rule: Use MF2-GARCH when gamma < {low_gamma_thresh}, GJR-GARCH otherwise.")
    else:
        findings.append("The gamma-dependent rule does NOT generalize cleanly.")
        findings.append(f"Low-gamma MF2 win rate: {mf2_wins_low}/{n_low}, High-gamma MF2 win rate: {mf2_wins_high}/{n_high}.")
        if mf2_wins_low / max(n_low, 1) > 0.5:
            findings.append("MF2 does tend to help for bonds, but the rule is not sharp enough for high-gamma assets.")
        else:
            findings.append("MF2 advantage may be TLT-specific, not a general low-gamma property.")

    for f_str in findings:
        print(f"  - {f_str}")

    # Save results
    output = {
        "experiment_id": "K144_mf2_cross_bond_v2",
        "version": 2,
        "created_at": pd.Timestamp.now().isoformat(),
        "model": "MF2-GARCH (Conrad & Engle 2025 — joint QML)",
        "description": "Cross-asset bond verification with proper joint QML MF2-GARCH. "
                       "Tests whether low-gamma -> MF2 advantage pattern holds across bond types.",
        "specification": {
            "short_run": "g_t = (1-a-b-g/2) + (a + g*I) * (r^2/tau) + b*g_{t-1}",
            "long_run": "tau_t = lam1 + lam2 * V^m_{t-1} + lam3 * tau_{t-1}",
            "V_def": "V_t = r^2_t / (g_t * tau_t)",
            "Vm_def": "V^m_t = (1/m) * sum_{j=1}^m V_{t-j}",
            "total": "sigma^2_t = tau_t * g_t",
            "estimation": "Joint QML with L-BFGS-B",
            "m_selection": "BIC over m in {22, 44, 66}",
        },
        "benchmark": "GJR-GARCH(1,1)",
        "oos_period": "2020-01-01 to 2024-12-31+",
        "window": 2000,
        "refit_frequency": 63,
        "assets": {},
        "scoreboard": scoreboard,
        "gamma_values": gamma_values,
        "gamma_rule_confirmed": rule_confirmed,
        "key_findings": findings,
    }

    for ticker in all_tickers:
        if ticker in all_results:
            # Clean up for JSON serialization
            asset_result = {}
            for k, v in all_results[ticker].items():
                asset_result[k] = v
            output["assets"][ticker] = asset_result

    out_path = project_root / "storage" / "experiments" / "k144_mf2_cross_bond_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    # Record to memory system
    try:
        from volpred.memory.system import MemorySystem
        mem = MemorySystem(storage_dir=str(project_root / "storage"))

        gamma_str = ", ".join(
            f"{t}={gamma_values.get(t, 0):.4f}"
            for t in all_tickers if t in gamma_values
        )
        scoreboard_str = ", ".join(
            f"{t}={scoreboard[t]['winner']}(p={scoreboard[t]['dm_p']:.3f})"
            for t in all_tickers if t in scoreboard
        )

        confidence = 0.85 if rule_confirmed else 0.55

        mem.add_knowledge(
            category="experiment",
            content=f"K144v2: MF2-GARCH cross-bond verification (joint QML, L-BFGS-B). "
                    f"Gammas: {gamma_str}. "
                    f"Winners: {scoreboard_str}. "
                    f"Gamma-dependent rule {'CONFIRMED' if rule_confirmed else 'NOT confirmed'}. "
                    + (f"MF2 wins {mf2_wins_low}/{n_low} low-gamma, {mf2_wins_high}/{n_high} high-gamma. "
                       if True else "")
                    + " ".join(findings[:2]),
            confidence=confidence,
        )

        mem.add_log_entry(
            phase="Phase_K",
            action="K144_mf2_cross_bond_v2",
            observation=f"Tested MF2(joint QML) vs GJR on {','.join(all_tickers)}. "
                       f"Gamma rule {'confirmed' if rule_confirmed else 'not confirmed'}. "
                       f"Low-gamma MF2 win rate: {mf2_wins_low}/{n_low}.",
            decision="MF2-GARCH model selection rule is " +
                    ("robust: use MF2 for gamma<0.05 assets" if rule_confirmed
                     else "not cleanly generalizable"),
        )
    except Exception as e:
        print(f"  Warning: Could not save to memory system: {e}")

    print(f"\n{'=' * 74}")
    print(f"  K144 v2 COMPLETE")
    print(f"{'=' * 74}")

    return output


if __name__ == "__main__":
    main()
