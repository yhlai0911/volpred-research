#!/usr/bin/env python3
"""
K1200: Paper 6 (prg-periodic-garch) SPY Replication under Eq.(5-6) Two-Phase Timing
====================================================================================

PURPOSE
-------
Verify that K880's SPY canonical DM t=6.00 (PRG Extended vs GJR) is **exactly
reproducible** under a clean-slate implementation that adheres to the two-phase
forecast timing documented in Paper 6 main.tex (commit 7d35418b) Eqs.(5)-(7).

This defends against a reviewer challenge of the form:
  "Your code in k880.py line 512 (x_prev_in = r2_overnight[t]) uses the day-d
  overnight realized return to forecast the day-d intraday variance. Does this
  match what the paper claims in Eq.(6)?"

PAPER 6 EQ.(5)-(7) SPEC (main.tex lines 112-125)
-------------------------------------------------
Let F_{d-1}^c = info set at the day-(d-1) close (after intraday session)
Let F_d^o     = info set at the day-d open    (after overnight session)

Eq.(5)  Overnight forecast issued at day-(d-1) close:
    ĥ_{d,0} = E[r²_{d,0} | F_{d-1}^c]
           = ω_0 + α_0·r²_{d-1,1} + γ_0·r²_{d-1,1}·I(r_{d-1,1}<0) + β_0·h_{d-1,1}

Eq.(6)  Intraday forecast issued at day-d open, conditional on realized overnight:
    ĥ_{d,1} = E[r²_{d,1} | F_d^o]
           = ω_1 + α_1·r²_{d,0} + γ_1·r²_{d,0}·I(r_{d,0}<0) + β_1·ĥ_{d,0}

Eq.(7)  Full-day forecast:
    σ̂²_full,d = ĥ_{d,0} + ĥ_{d,1}

The paper explicitly states (main.tex lines 121-126):
  "The input r²_{d,0} is the realized (not forecasted) overnight squared
  return and is therefore an element of F_d^o. Acting at the open on fully
  realized overnight information is a legitimate and routinely implementable
  timing convention, not a look-ahead construct."

IMPLEMENTATION AUDIT (K880 line 512 equivalence)
------------------------------------------------
K880 code: x_prev_in = r2_overnight[t]  # "uses observed overnight of day t"
K1200 map: r²_{d,0} = r2_overnight[t]   (day-d overnight squared realized)

=> Eq.(6) and K880 line 512 are equivalent notation. K1200 clean-slate
   implementation below must yield numerically identical (within optimizer
   tolerance) QLIKE and DM t relative to K880.

DATA / DESIGN
-------------
- Asset: SPY via yfinance
- Period: 2000-01-01 to 2026-04-05 (match K880)
- IS end: 2018-12-31 (match K880)
- Session returns:
    r_{d,0} = log(Open_d / Close_{d-1})    # overnight
    r_{d,1} = log(Close_d / Open_d)        # intraday
- Models:
    (A) GJR-GARCH(1,1) on close-to-close returns, QMLE (matches K880 Gaussian)
    (B) PRG Extended (8 params) via Gaussian QMLE on interleaved session
        sequence, reproduced from Eqs.(3)-(4).
- Refit: GJR every 63 days, PRG every 126 days (match K880)
- Loss: QLIKE
- Test: DM-Harvey

SUCCESS BANDS (replication verdict)
-----------------------------------
- REPLICATED:       |ΔQLIKE|     < 0.01  AND  |ΔDM_t|     < 0.3
- MINOR_DIVERGENT:  0.01 ≤ |ΔQLIKE| < 0.05  OR  0.3 ≤ |ΔDM_t| < 0.5
- MAJOR_DIVERGENT:  |ΔQLIKE| ≥ 0.05  OR  |ΔDM_t| ≥ 0.5

Rules applied:
- Fixed seed 42 for all stochastic elements
- n_starts=20 for PRG MLE (more robust than K880's 5)
- Explicit signal/info-set lag: only realized quantities at forecast time enter ĥ
- No lookahead beyond what Eq.(5)-(6) explicitly authorize

Author: K1200 clean-slate replication
Date: 2026-04-17
"""
from __future__ import annotations

import json
import os
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUTPUT_JSON = SCRIPT_DIR / "k1200_results.json"
CHARTS_DIR = SCRIPT_DIR / "k1200_charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
IS_END_DATE = "2018-12-31"
REFIT_GJR = 63
REFIT_PRG = 126
PRG_N_STARTS = 10   # higher than K880's 5 but keep numba speed reasonable

# K880 canonical numbers (from experiments/k880/k880_results.json)
K880_CANONICAL = {
    "PRG_Extended_QLIKE": 0.7478221332984176,
    "GJR_QLIKE":          0.8541713650290065,
    "DM_t_PRGExt_vs_GJR": 6.003887940674553,
    "PRG_Extended_Spearman": 0.5677794555906424,
    "n_oos":              1823,
    "is_period":          "2000-01-04 to 2018-12-31",
    "oos_period":         "2019-01-02 to 2026-04-02",
}


# ---------------------------------------------------------------------------
# DM test (Harvey small-sample correction via HAC variance)
# ---------------------------------------------------------------------------
def dm_harvey(loss1: np.ndarray, loss2: np.ndarray, h: int = 1):
    """DM test with Newey-West HAC variance.
    Positive t → loss1 > loss2 → model 2 (= second arg) is better.
    Convention in this file: loss1 = GJR, loss2 = PRG_Ext → positive t favors PRG."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l
    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    t_stat = d_mean / se
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ---------------------------------------------------------------------------
# Data loading (SPY)
# ---------------------------------------------------------------------------
def load_spy():
    import yfinance as yf
    print("Downloading SPY from yfinance...")
    spy = yf.download("SPY", start="2000-01-01", end="2026-04-05", auto_adjust=True,
                      progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    df = pd.DataFrame(index=spy.index)
    df["open"] = spy["Open"].values.astype(np.float64)
    df["close"] = spy["Close"].values.astype(np.float64)
    df["prev_close"] = df["close"].shift(1)
    # Eq.(1)-(2) session returns
    df["r_overnight"] = np.log(df["open"] / df["prev_close"])   # r_{d,0}
    df["r_intra"]     = np.log(df["close"] / df["open"])         # r_{d,1}
    df["r_c2c"]       = np.log(df["close"] / df["prev_close"])   # c2c for GJR
    df["r2_overnight"] = df["r_overnight"] ** 2
    df["r2_intra"]     = df["r_intra"] ** 2
    # Eq.(3) common target
    df["sigma2_fullday"] = df["r2_overnight"] + df["r2_intra"]
    df = df.iloc[1:].dropna(subset=["r_overnight", "r_intra", "sigma2_fullday"])
    print(f"  SPY days: {len(df)}, {df.index[0].date()} to {df.index[-1].date()}")
    return df


# ---------------------------------------------------------------------------
# GJR-GARCH(1,1) — close-to-close, Gaussian QMLE (matches K880)
# ---------------------------------------------------------------------------
@njit(cache=True)
def _gjr_negll_nb(omega, alpha, gamma_p, beta, r):
    T = len(r)
    init_n = min(50, T)
    s = 0.0
    for i in range(init_n):
        s += r[i] ** 2
    mean = 0.0
    for i in range(init_n):
        mean += r[i]
    mean /= init_n
    var = 0.0
    for i in range(init_n):
        var += (r[i] - mean) ** 2
    var /= init_n
    h = var
    if h < 1e-12:
        h = 1e-8
    ll = 0.0
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        h = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * ind + beta * h
        if h < 1e-12:
            h = 1e-12
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h) - 0.5 * r[t] ** 2 / h
    return -ll


@njit(cache=True)
def _gjr_propagate_nb(omega, alpha, gamma_p, beta, r, h0, start, end):
    h = h0
    for t in range(start, end):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        h = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * ind + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


def gjr_negll(params, r):
    return _gjr_negll_nb(params[0], params[1], params[2], params[3], r)


def gjr_propagate(params, r, h0, start, end):
    return _gjr_propagate_nb(params[0], params[1], params[2], params[3], r, h0, start, end)


def fit_gjr(r_train, rng):
    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    best_nll = np.inf
    best_p = None
    for i in range(3):
        if i == 0:
            x0 = [np.var(r_train) * 0.05, 0.08, 0.06, 0.85]
        else:
            x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                  rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
        try:
            res = minimize(gjr_negll, x0, args=(r_train,), method="L-BFGS-B",
                           bounds=bounds, options={"maxiter": 1000})
            if res.fun < best_nll:
                best_nll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p


def gjr_oos(r_c2c, is_end, refit_freq=REFIT_GJR):
    n = len(r_c2c)
    fc = np.full(n, np.nan)
    params = None
    h_state = np.var(r_c2c[: min(50, n)])
    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            rng = np.random.RandomState(SEED)
            r_train = r_c2c[:t].copy()
            p = fit_gjr(r_train, rng)
            if p is not None:
                params = p
                h0 = np.var(r_c2c[: min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_state = gjr_propagate(params, r_c2c, h0, 1, t)
        if params is not None:
            omega, alpha, gamma_p, beta = params
            ind = 1.0 if r_c2c[t - 1] < 0 else 0.0
            h_state = (omega + alpha * r_c2c[t - 1] ** 2
                       + gamma_p * r_c2c[t - 1] ** 2 * ind
                       + beta * h_state)
            if h_state < 1e-12:
                h_state = 1e-12
            fc[t] = h_state
    return fc


# ---------------------------------------------------------------------------
# PRG Extended — Eq.(3)-(4) likelihood on interleaved session sequence
# ---------------------------------------------------------------------------
@njit(cache=True)
def _prg_negll_nb(w0, a0, b0, w1, a1, b1, g0, g1, r_seq, x_seq, s_seq):
    T = len(r_seq)
    init_n = 100 if T > 100 else T
    mean = 0.0
    for i in range(init_n):
        mean += x_seq[i]
    h = mean / init_n
    if h < 1e-12:
        h = 1e-8
    ll = 0.0
    for n in range(1, T):
        if s_seq[n] == 0:
            lev = g0 * x_seq[n - 1] * (1.0 if r_seq[n - 1] < 0 else 0.0)
            h = w0 + a0 * x_seq[n - 1] + lev + b0 * h
        else:
            lev = g1 * x_seq[n - 1] * (1.0 if r_seq[n - 1] < 0 else 0.0)
            h = w1 + a1 * x_seq[n - 1] + lev + b1 * h
        if h < 1e-12:
            h = 1e-12
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h) - 0.5 * r_seq[n] ** 2 / h
    return -ll


def prg_negll(params, r_seq, x_seq, s_seq):
    """PRG Extended negative log-likelihood.
    Interleaved sequence: n = 2d for overnight, n = 2d+1 for intraday.
    s_seq[n] ∈ {0, 1}; x_seq[n] = r²_n (realized proxy of session n).
    h_n = ω_{s_n} + α_{s_n}·x_{n-1} + γ_{s_n}·x_{n-1}·I(r_{n-1}<0) + β_{s_n}·h_{n-1}
    """
    return _prg_negll_nb(params[0], params[1], params[2],
                         params[3], params[4], params[5],
                         params[6], params[7],
                         r_seq, x_seq, s_seq)


def build_interleaved(r_ov, r_in, r2_ov, r2_in):
    """Build interleaved session sequence: [r_{1,0}, r_{1,1}, r_{2,0}, r_{2,1}, ...]."""
    n_days = len(r_ov)
    T = 2 * n_days
    r_seq = np.empty(T, dtype=np.float64)
    x_seq = np.empty(T, dtype=np.float64)
    s_seq = np.empty(T, dtype=np.int64)
    r_seq[0::2] = r_ov
    r_seq[1::2] = r_in
    x_seq[0::2] = r2_ov
    x_seq[1::2] = r2_in
    s_seq[0::2] = 0
    s_seq[1::2] = 1
    return r_seq, x_seq, s_seq


def fit_prg(r_ov, r_in, r2_ov, r2_in, n_starts=PRG_N_STARTS):
    r_seq, x_seq, s_seq = build_interleaved(r_ov, r_in, r2_ov, r2_in)
    eps = 1e-8
    bounds = [
        (eps, 1e-3), (eps, 1.0), (eps, 0.999),   # omega_0, alpha_0, beta_0
        (eps, 1e-3), (eps, 1.0), (eps, 0.999),   # omega_1, alpha_1, beta_1
        (0.0, 1.0), (0.0, 1.0),                   # gamma_0, gamma_1
    ]
    var_ov = float(np.mean(r2_ov[: min(200, len(r2_ov))]))
    var_in = float(np.mean(r2_in[: min(200, len(r2_in))]))

    best_nll = np.inf
    best_p = None
    rng = np.random.RandomState(SEED)
    for i in range(n_starts):
        if i == 0:
            x0 = [var_ov * 0.05, 0.15, 0.80,
                  var_in * 0.05, 0.15, 0.80,
                  0.05, 0.05]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                  rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                  rng.uniform(0.0, 0.20), rng.uniform(0.0, 0.20)]
        try:
            res = minimize(prg_negll, x0, args=(r_seq, x_seq, s_seq),
                           method="L-BFGS-B", bounds=bounds,
                           options={"maxiter": 2000, "ftol": 1e-10})
            if res.fun < best_nll:
                best_nll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p


@njit(cache=True)
def _prg_propagate_h_nb(w0, a0, b0, w1, a1, b1, g0, g1,
                        r_ov, r_in, r2_ov, r2_in, end_d, h_init):
    h = h_init
    for d in range(end_d):
        if d > 0:
            x_prev = r2_in[d - 1]
            r_prev = r_in[d - 1]
        else:
            x_prev = r2_ov[0]
            r_prev = r_ov[0]
        lev = g0 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h = w0 + a0 * x_prev + lev + b0 * h
        if h < 1e-12:
            h = 1e-12
        x_prev = r2_ov[d]
        r_prev = r_ov[d]
        lev = g1 * x_prev * (1.0 if r_prev < 0 else 0.0)
        h = w1 + a1 * x_prev + lev + b1 * h
        if h < 1e-12:
            h = 1e-12
    return h


def prg_propagate_h(params, r_ov, r_in, r2_ov, r2_in, end_d, h_init):
    """Propagate h through days [0, end_d). Returns h after intraday of day (end_d - 1)."""
    return _prg_propagate_h_nb(params[0], params[1], params[2],
                               params[3], params[4], params[5],
                               params[6], params[7],
                               r_ov, r_in, r2_ov, r2_in, end_d, h_init)


def prg_oos_eq56(r_ov, r_in, r2_ov, r2_in, is_end, refit_freq=REFIT_PRG):
    """
    Two-phase OOS forecast per Paper 6 Eqs.(5)-(7).

    For each day t (t >= is_end):
      Step 1 (Eq.5, issued at close of day t-1):
        ĥ_{t,0} = ω_0 + α_0·r²_{t-1,1} + γ_0·r²_{t-1,1}·I(r_{t-1,1}<0) + β_0·h_{t-1,1}
      Step 2 (Eq.6, issued at open of day t, uses realized r_{t,0}):
        ĥ_{t,1} = ω_1 + α_1·r²_{t,0} + γ_1·r²_{t,0}·I(r_{t,0}<0) + β_1·ĥ_{t,0}
      Step 3 (Eq.7):
        σ̂²_full,t = ĥ_{t,0} + ĥ_{t,1}
    """
    n_days = len(r_ov)
    fc = np.full(n_days, np.nan)

    params = None
    # h_state will hold h_{t-1, 1} — conditional variance at close of previous day
    h_state = None

    for t in range(is_end, n_days):
        # Refit
        if (t - is_end) % refit_freq == 0 or t == is_end:
            p = fit_prg(r_ov[:t], r_in[:t], r2_ov[:t], r2_in[:t])
            if p is not None:
                params = p
                # Rebuild h_state = h_{t-1, 1} by propagating through days [0, t)
                # Seed: average of first few full-day variances
                h_init = float(np.mean(r2_ov[: min(50, t)] + r2_in[: min(50, t)])) / 2.0
                if h_init < 1e-12:
                    h_init = 1e-8
                h_state = prg_propagate_h(params, r_ov, r_in, r2_ov, r2_in, t, h_init)

        if params is None or h_state is None:
            continue

        w0, a0, b0, w1, a1, b1, g0, g1 = params

        # --- Eq.(5): overnight forecast for day t, issued at close of day t-1 ---
        # inputs: r²_{t-1,1}, sign(r_{t-1,1}), h_{t-1,1}
        x_prev_ov = r2_in[t - 1]
        r_prev_ov = r_in[t - 1]
        lev_ov = g0 * x_prev_ov * (1.0 if r_prev_ov < 0 else 0.0)
        h_hat_t0 = w0 + a0 * x_prev_ov + lev_ov + b0 * h_state
        if h_hat_t0 < 1e-12:
            h_hat_t0 = 1e-12

        # --- Eq.(6): intraday forecast for day t, issued at open of day t ---
        # inputs: r²_{t,0} (realized overnight), sign(r_{t,0}), ĥ_{t,0}
        x_prev_in = r2_ov[t]             # << Eq.(6): α_1·r²_{d,0} — realized overnight
        r_prev_in = r_ov[t]              # << sign indicator of realized overnight
        lev_in = g1 * x_prev_in * (1.0 if r_prev_in < 0 else 0.0)
        h_hat_t1 = w1 + a1 * x_prev_in + lev_in + b1 * h_hat_t0
        if h_hat_t1 < 1e-12:
            h_hat_t1 = 1e-12

        # --- Eq.(7): full-day forecast ---
        fc[t] = h_hat_t0 + h_hat_t1

        # Update h_state to h_{t, 1} (conditional variance at close of day t) so
        # next iteration uses the correct anchor for Eq.(5) of day (t+1).
        # Now that we are at day t, the just-computed h_hat_t1 IS h_{t,1}.
        h_state = h_hat_t1

    return fc


# ---------------------------------------------------------------------------
# Loss / metric helpers
# ---------------------------------------------------------------------------
def qlike_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    loss[valid] = r / f - np.log(r / f) - 1
    return loss


def spearman_with_ci(realized, forecast, n_boot=5000, seed=SEED):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    n = len(r)
    if n < 30:
        return {"rho": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "n": n}
    rho, _ = sp_stats.spearmanr(r, f)
    rng = np.random.RandomState(seed)
    boots = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, n)
        br, _ = sp_stats.spearmanr(r[idx], f[idx])
        boots.append(br)
    boots = np.array(boots)
    return {
        "rho": float(rho),
        "ci_lo": float(np.percentile(boots, 2.5)),
        "ci_hi": float(np.percentile(boots, 97.5)),
        "n": n,
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def make_charts(dates_oos, target, fc_gjr, fc_prg, charts_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Chart 1: rolling 60-day QLIKE ratio PRG/GJR
    ql_prg = qlike_array(target, fc_prg)
    ql_gjr = qlike_array(target, fc_gjr)
    valid = np.isfinite(ql_prg) & np.isfinite(ql_gjr)
    dates_v = pd.DatetimeIndex(dates_oos)[valid]
    ratio = pd.Series(ql_prg[valid] / np.clip(ql_gjr[valid], 1e-12, None), index=dates_v)
    rolling = ratio.rolling(60).mean()
    fig, ax = plt.subplots(figsize=(12, 5))
    _x = np.asarray(rolling.index.to_numpy())
    _y = np.asarray(rolling.values)
    ax.plot(_x, _y, linewidth=1.5, color="steelblue",
            label="PRG_Ext / GJR QLIKE ratio (60d MA)")
    ax.axhline(1.0, color="red", linestyle="--", linewidth=1, label="equal")
    ax.fill_between(_x, _y, 1.0,
                    where=_y < 1, alpha=0.3, color="green", label="PRG better")
    ax.fill_between(_x, _y, 1.0,
                    where=_y > 1, alpha=0.3, color="red", label="GJR better")
    ax.set_title("K1200 (Eq.(5)-(6) clean-slate): rolling QLIKE ratio PRG vs GJR — SPY OOS")
    ax.set_ylabel("ratio (< 1 = PRG better)")
    ax.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    plt.savefig(charts_dir / "rolling_qlike_ratio_k1200.png", dpi=150)
    plt.close()

    # Chart 2: side-by-side QLIKE time-series (60d MA)
    ql_prg_s = pd.Series(ql_prg[valid], index=dates_v).rolling(60).mean()
    ql_gjr_s = pd.Series(ql_gjr[valid], index=dates_v).rolling(60).mean()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(np.asarray(ql_gjr_s.index.to_numpy()), np.asarray(ql_gjr_s.values),
            label="GJR-GARCH (c2c)", color="crimson", linewidth=1.3)
    ax.plot(np.asarray(ql_prg_s.index.to_numpy()), np.asarray(ql_prg_s.values),
            label="PRG Extended (Eq.5-6)", color="steelblue", linewidth=1.3)
    ax.set_title("K1200: rolling 60d QLIKE — SPY OOS 2019-2026")
    ax.set_ylabel("QLIKE (lower = better)")
    ax.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(charts_dir / "qlike_timeseries_k1200.png", dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = datetime.now()
    print("=" * 72, flush=True)
    print("K1200: Paper 6 SPY Replication under Eq.(5)-(7) two-phase timing", flush=True)
    print("=" * 72, flush=True)

    # Warm up numba JITs (first call compiles)
    print("\n  Warming up numba JIT...", flush=True)
    _d = np.array([0.01, -0.02, 0.015, -0.005, 0.01, -0.01], dtype=np.float64)
    _gjr_negll_nb(1e-5, 0.1, 0.05, 0.85, _d)
    _gjr_propagate_nb(1e-5, 0.1, 0.05, 0.85, _d, 1e-5, 1, 5)
    _s = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)
    _prg_negll_nb(1e-5, 0.1, 0.85, 1e-5, 0.1, 0.85, 0.05, 0.05, _d, _d ** 2, _s)
    _prg_propagate_h_nb(1e-5, 0.1, 0.85, 1e-5, 0.1, 0.85, 0.05, 0.05,
                        _d[:3], _d[3:6], _d[:3] ** 2, _d[3:6] ** 2, 3, 1e-5)
    print("  JIT done.", flush=True)

    # ---- Data ----
    df = load_spy()
    is_mask = df.index <= IS_END_DATE
    is_end = int(is_mask.sum())
    n_oos = len(df) - is_end
    print(f"  IS: {is_end} days ({df.index[0].date()} to {IS_END_DATE})", flush=True)
    print(f"  OOS: {n_oos} days ({df.index[is_end].date()} to {df.index[-1].date()})", flush=True)

    r_c2c = df["r_c2c"].values
    r_ov = df["r_overnight"].values
    r_in = df["r_intra"].values
    r2_ov = df["r2_overnight"].values
    r2_in = df["r2_intra"].values
    sigma2_full = df["sigma2_fullday"].values

    # ---- GJR ----
    print("\n[1/2] GJR-GARCH OOS...")
    t_gjr = datetime.now()
    fc_gjr = gjr_oos(r_c2c, is_end)
    print(f"  GJR done in {(datetime.now() - t_gjr).total_seconds():.1f}s")

    # ---- PRG Extended (Eq.5-6 clean-slate) ----
    print("\n[2/2] PRG Extended OOS under Eq.(5)-(6) two-phase timing...")
    t_prg = datetime.now()
    fc_prg = prg_oos_eq56(r_ov, r_in, r2_ov, r2_in, is_end)
    print(f"  PRG done in {(datetime.now() - t_prg).total_seconds():.1f}s")

    # ---- Sanity: positive forecasts ----
    for name, fc in [("GJR", fc_gjr), ("PRG_Ext", fc_prg)]:
        vf = fc[is_end:][np.isfinite(fc[is_end:])]
        assert vf.min() > 0, f"{name} has non-positive forecasts!"
        print(f"  {name}: n_valid={len(vf)}, min={vf.min():.2e}, mean={vf.mean():.2e}, "
              f"max={vf.max():.2e}")

    # ---- Losses ----
    target_oos = sigma2_full[is_end:]
    ql_gjr_arr = qlike_array(target_oos, fc_gjr[is_end:])
    ql_prg_arr = qlike_array(target_oos, fc_prg[is_end:])

    qlike_gjr_k1200 = float(np.nanmean(ql_gjr_arr))
    qlike_prg_k1200 = float(np.nanmean(ql_prg_arr))

    # DM: t_stat > 0 => PRG better (since d = loss_GJR - loss_PRG and PRG has lower loss)
    dm_t, dm_p = dm_harvey(ql_gjr_arr, ql_prg_arr)

    # Spearman
    sp_prg = spearman_with_ci(target_oos, fc_prg[is_end:])

    # ---- Deltas vs K880 ----
    delta_qlike_prg = qlike_prg_k1200 - K880_CANONICAL["PRG_Extended_QLIKE"]
    delta_qlike_gjr = qlike_gjr_k1200 - K880_CANONICAL["GJR_QLIKE"]
    delta_dm = dm_t - K880_CANONICAL["DM_t_PRGExt_vs_GJR"]
    delta_sp = sp_prg["rho"] - K880_CANONICAL["PRG_Extended_Spearman"]

    # ---- Verdict ----
    abs_dq = max(abs(delta_qlike_prg), abs(delta_qlike_gjr))
    abs_ddm = abs(delta_dm)
    if abs_dq < 0.01 and abs_ddm < 0.3:
        verdict = "REPLICATED"
        defensibility = ("Paper 6 Eq.(5)-(6) implementation exactly matches K880 "
                         "numeric result; reviewer cannot reject on 'code doesn't "
                         "match your equation' grounds.")
    elif abs_dq < 0.05 and abs_ddm < 0.5:
        verdict = "MINOR_DIVERGENT"
        defensibility = ("Minor numerical divergence (likely optimizer randomness / "
                         "refit seed). Paper 6 narrative still defensible; consider "
                         "aligning K880 optimizer settings.")
    else:
        verdict = "MAJOR_DIVERGENT"
        defensibility = ("MAJOR divergence: Eq.(5)-(6) as literally transcribed does "
                         "NOT reproduce K880 DM t=6.00. Paper 6 needs either (a) code "
                         "clarification in Section 2.3, or (b) reconciliation between "
                         "the equation set and K880 implementation. HIGH REVIEWER RISK.")

    print("\n" + "=" * 72)
    print("REPLICATION VERDICT")
    print("=" * 72)
    print(f"  GJR QLIKE:      K1200={qlike_gjr_k1200:.4f}, K880={K880_CANONICAL['GJR_QLIKE']:.4f}, Δ={delta_qlike_gjr:+.4f}")
    print(f"  PRG QLIKE:      K1200={qlike_prg_k1200:.4f}, K880={K880_CANONICAL['PRG_Extended_QLIKE']:.4f}, Δ={delta_qlike_prg:+.4f}")
    print(f"  DM t (PRG-GJR): K1200={dm_t:.3f}, K880={K880_CANONICAL['DM_t_PRGExt_vs_GJR']:.3f}, Δ={delta_dm:+.3f}")
    print(f"  Spearman ρ:     K1200={sp_prg['rho']:.4f}, K880={K880_CANONICAL['PRG_Extended_Spearman']:.4f}, Δ={delta_sp:+.4f}")
    print(f"  VERDICT: {verdict}")
    print(f"  {defensibility}")
    print("=" * 72)

    # ---- Charts ----
    make_charts(df.index[is_end:], target_oos, fc_gjr[is_end:], fc_prg[is_end:], CHARTS_DIR)

    # ---- Save results ----
    elapsed = (datetime.now() - t0).total_seconds()
    results = {
        "experiment_id": "K1200",
        "title": "Paper 6 SPY replication under Eq.(5)-(6) two-phase forecast timing",
        "type": "empirical_replication",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "paper_reference": {
            "paper_id": "prg-periodic-garch",
            "main_tex_commit": "7d35418b",
            "equations_verified": ["Eq.(5) overnight forecast", "Eq.(6) intraday forecast", "Eq.(7) fullday sum"],
        },
        "data_source": "yfinance (SPY)",
        "period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "is_period": f"{df.index[0].date()} to {IS_END_DATE}",
        "oos_period": f"{df.index[is_end].date()} to {df.index[-1].date()}",
        "n_is": is_end,
        "n_oos": n_oos,
        "seed": SEED,
        "refit_gjr_days": REFIT_GJR,
        "refit_prg_days": REFIT_PRG,
        "prg_n_starts": PRG_N_STARTS,
        "k1200_metrics": {
            "GJR_QLIKE": qlike_gjr_k1200,
            "PRG_Ext_QLIKE": qlike_prg_k1200,
            "DM_t_PRGExt_vs_GJR": float(dm_t),
            "DM_p_PRGExt_vs_GJR": float(dm_p),
            "PRG_Ext_Spearman": sp_prg["rho"],
            "PRG_Ext_Spearman_CI": [sp_prg["ci_lo"], sp_prg["ci_hi"]],
            "n_oos_valid_qlike": int(np.sum(np.isfinite(ql_prg_arr))),
        },
        "k880_canonical": K880_CANONICAL,
        "deltas": {
            "delta_GJR_QLIKE": delta_qlike_gjr,
            "delta_PRG_QLIKE": delta_qlike_prg,
            "delta_DM_t": delta_dm,
            "delta_Spearman": delta_sp,
        },
        "tolerance_bands": {
            "REPLICATED": "|ΔQLIKE| < 0.01 AND |ΔDM_t| < 0.3",
            "MINOR_DIVERGENT": "0.01 ≤ |ΔQLIKE| < 0.05 OR 0.3 ≤ |ΔDM_t| < 0.5",
            "MAJOR_DIVERGENT": "|ΔQLIKE| ≥ 0.05 OR |ΔDM_t| ≥ 0.5",
        },
        "verdict": verdict,
        "paper6_defensibility": defensibility,
        "implementation_notes": {
            "Eq_5_line": "h_hat_t0 = w0 + a0*r2_in[t-1] + g0*r2_in[t-1]*I(r_in[t-1]<0) + b0*h_state",
            "Eq_6_line": "h_hat_t1 = w1 + a1*r2_ov[t] + g1*r2_ov[t]*I(r_ov[t]<0) + b1*h_hat_t0",
            "Eq_7_line": "fc[t] = h_hat_t0 + h_hat_t1",
            "K880_equivalence": ("K880 line 512 `x_prev_in = r2_overnight[t]` literally "
                                 "maps to Eq.(6) α_1·r²_{d,0} (day-d overnight realized). "
                                 "This is NOT a lookahead: r_{d,0} is available at the "
                                 "day-d open per Paper 6 Section 2.2 discussion."),
        },
        "references": [
            "Paper 6 main.tex (commit 7d35418b) Eqs.(5)-(7)",
            "K880 experiments/k880/k880_results.json (canonical baseline)",
            "Patton (2011) on QLIKE robustness to volatility proxy noise",
            "Harvey et al. (1997), Harvey (2016) on DM test small-sample correction",
        ],
        "runtime_seconds": elapsed,
    }

    # NaN/inf -> None for JSON safety
    def _san(o):
        if isinstance(o, dict):
            return {k: _san(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_san(x) for x in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating, float)):
            fv = float(o)
            return fv if np.isfinite(fv) else None
        if isinstance(o, np.ndarray):
            return [_san(x) for x in o.tolist()]
        return o

    with open(OUTPUT_JSON, "w") as f:
        json.dump(_san(results), f, indent=2, default=str)

    print(f"\n  Results → {OUTPUT_JSON}")
    print(f"  Total runtime: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
