#!/usr/bin/env python3
"""
K1091: Out-of-Sample Validation of K1090 Meta-Regression (VGK + EWJ + CPER + SLV)
===================================================================================
[提出: 用戶 (via K1091 brief), 執行: Claude]

Motivation
----------
K1090 trained a 12-asset meta-regression that maps asset-level features to the
realized A4f-VIX² vs GJR DM-t statistic. Its preferred (compact OLS) formula:

    DM_t ≈ -1.22 + 3.38·USD_dummy − 4.11·corr(ret, ΔVIX)

    R² = 0.54, LOOCV R² = 0.26, LOOCV RMSE = 1.94.

For four liquid US-listed ETFs, the K1090 ridge regressor predicts:

    VGK  (European equity) : 4.71  (strong_run)
    EWJ  (Japan   equity)  : 4.34  (strong_run)
    CPER (US copper ETF)   : 3.58  (run)
    SLV  (US silver ETF)   : 3.58  (run)

K1091 actually fits A4f-VIX² on each of these assets (OOS, rolling,
refit every 63 days) and compares the realized DM-t to the K1090 predictions.
This is an out-of-sample validation of the meta-regression itself.

Hypotheses
----------
H1  VGK  A4f-VIX² vs GJR has Harvey-PASS (|t|>3, positive).
H2  EWJ  A4f-VIX² vs GJR has Harvey-PASS.
H3  CPER A4f-VIX² vs GJR has Harvey-PASS.
H4  SLV  A4f-VIX² vs GJR has Harvey-PASS.
H5  Mean-absolute-error between K1090 ridge predictions and realized DM-t
    is below the K1090 LOOCV RMSE of 1.94.

Design (aligned with K1075, K1085, K1088, K1089)
------------------------------------------------
  • Four assets, one unified pipeline, seed 42.
  • One regressor per asset: A4f-VIX², i.e.
        tau_t = theta0 + theta1 * VIX_{t-1}^2
    with GJR(1,1) filter applied to standardised residuals.
  • Rolling window, refit every 63 days (quarterly).
  • Window / OOS choices per asset reflect data availability:

        Asset | Data begins | WINDOW | OOS window
        ------+-------------+--------+-----------------
        VGK   | 2005-03-10  |  2000  | 2013-01-02 .. 2026-04-10
        EWJ   | 1996-03-18  |  2000  | 2007-01-02 .. 2026-04-10
        CPER  | 2011-11-15  |  1500  | 2020-01-02 .. 2026-04-10
        SLV   | 2006-04-28  |  2000  | 2014-05-01 .. 2026-04-10

    CPER uses WINDOW=1500 because yfinance only goes back to 2011 and the
    standard 2000 window would leave a short post-2019 OOS. The shorter
    window is still above the 500-day Hwang & Valls Pereira (2006) minimum.

  • Evaluation:
      - QLIKE on r² (Patton 2011)
      - DM test with Newey-West HAC variance (Harvey, Leybourne, Newbold 2016)
      - Harvey pass threshold |t| > 3.0
      - Bootstrap 95% CI for mean QLIKE loss differential (block bootstrap,
        1000 reps, block length = n^{1/3}, seed 42)
      - Spearman rank correlation
  • Meta validation: compare realized full-OOS DM-t to K1090 ridge_pred.

No TX cost, no trading signals in this experiment — we evaluate
forecast accuracy, not PnL. No lookahead: VIX used at time t is VIX at t-1.

Data
----
yfinance, downloaded at runtime:
    VGK, EWJ, CPER, SLV, ^VIX (Close).

References
----------
  • Engle, Ghysels, Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.  [GARCH-MIDAS / A4f source]
  • Patton (2011). Volatility forecast comparison using imperfect volatility
    proxies. J Econometrics 160:246-256.  [QLIKE]
  • Harvey, Leybourne, Newbold (2016). Testing the equality of prediction
    MSE.  [Harvey |t|>3 threshold]
  • Andersen, Bollerslev, Diebold, Labys (2003). Modeling and Forecasting
    Realized Volatility.  [Realized vol target]
  • Diebold & Mariano (1995). Comparing Predictive Accuracy.  [DM test]

Author:  VolPred Research System (Claude)
Date:    2026-04-12
Experiment: K1091
Upstream: K1090 (meta-regression), K1075 (A4f baseline), K1088 (OVX pattern)
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize, stats

warnings.filterwarnings("ignore")
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1091"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, f"{EXPERIMENT_ID.lower()}_results.json")

# ============================================================
# CONFIGURATION
# ============================================================

DATA_END = "2026-04-13"

# K1090 ridge predictions (source: experiments/k1090/k1090_results.json -> new_asset_predictions.ridge_pred)
K1090_RIDGE_PRED = {
    "VGK": 4.708657433115338,
    "EWJ": 4.339689983398169,
    "CPER": 3.579902046160302,
    "SLV": 3.583805960400902,
}
# K1090 ridge 95% PI
K1090_RIDGE_PI95 = {
    "VGK": (3.2610300990945134, 5.839911828209797),
    "EWJ": (3.1595157584597446, 5.401306137507816),
    "CPER": (0.35350537938578613, 4.471380070584446),
    "SLV": (0.7023882806676324, 4.28821391919544),
}
K1090_RECOMMEND = {
    "VGK": "strong_run",
    "EWJ": "strong_run",
    "CPER": "run",
    "SLV": "run",
}

# Per-asset setup
ASSET_CONFIG = {
    "VGK": {
        "data_start": "2005-01-01",
        "window": 2000,
        # VGK starts 2005-03-11, so 2000 trading days finish around 2013-02-22.
        # Use 2013-03-01 to guarantee a clean 2000-day training window.
        "oos_start": "2013-03-01",
        "refit_every": 63,
        "class_label": "equity_europe",
        "currency": "USD",
    },
    "EWJ": {
        "data_start": "1996-01-01",
        "window": 2000,
        "oos_start": "2007-01-02",
        "refit_every": 63,
        "class_label": "equity_japan",
        "currency": "USD",
    },
    "CPER": {
        "data_start": "2011-01-01",
        "window": 1500,   # shorter window: data only goes back to 2011-11
        "oos_start": "2020-01-02",
        "refit_every": 63,
        "class_label": "commodity_copper",
        "currency": "USD",
    },
    "SLV": {
        "data_start": "2006-01-01",
        "window": 2000,
        "oos_start": "2014-05-01",
        "refit_every": 63,
        "class_label": "commodity_silver",
        "currency": "USD",
    },
}

print("=" * 78)
print(f"{EXPERIMENT_ID}: OOS Validation of K1090 Meta-Regression")
print("  Assets: VGK, EWJ, CPER, SLV  |  Model: A4f-VIX² vs GJR baseline")
print("=" * 78)


# ============================================================
# MODEL IMPLEMENTATIONS (copied/adapted from K1088/K1089)
# ============================================================


@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[: min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    converged = False
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(
                gjr_loglik, s, args=(returns,), method="L-BFGS-B", bounds=bounds
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev ** 2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev ** 2 + asym + beta * h_prev, 1e-10)


def fit_a4f_vix(returns, vix_vals):
    """A4f with tau_t = theta0 + theta1 * VIX_{t-1}^2."""
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = vix_vals[0]
    x_lag[1:] = vix_vals[:-1]
    x_lag_sq = x_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * x_lag_sq, 1e-16)

        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (
                    np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2
                )
        return -ll

    var0 = np.var(returns)
    x2_mean = np.mean(x_lag_sq) + 1e-8

    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-1, 1e-1),
        (1e-12, 1.0),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]

    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(
                neg_loglik, s, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def init_a4f_state(train_ret, vix_train, params):
    """Run filter on training set to yield the final g state."""
    theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params
    x_lag = np.empty(len(vix_train))
    x_lag[0] = vix_train[0]
    x_lag[1:] = vix_train[:-1]
    tau = np.maximum(theta0 + theta1 * x_lag ** 2, 1e-16)

    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / (1.0 - persist)
    for i in range(1, len(train_ret)):
        u_prev = train_ret[i - 1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
        g = max(g, 1e-10)
    return g


# ============================================================
# EVALUATION UTILITIES
# ============================================================


def qlike_loss(fc, r2_vals):
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array):
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T ** (1 / 3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    block_len = max(1, int(n ** (1 / 3)))
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        starts_ = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s : s + block_len] for s in starts_ if s + block_len <= n]
        if not blocks:
            return (np.nan, np.nan)
        sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(sample)
    return (float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5)))


def evaluate_pair(fc_base, fc_alt, r2_vals, label_alt="a4f_vix"):
    both_valid = (
        ~np.isnan(fc_base) & (fc_base > 0) & ~np.isnan(fc_alt) & (fc_alt > 0)
    )
    n = int(both_valid.sum())
    if n < 30:
        return None

    b = fc_base[both_valid]
    a = fc_alt[both_valid]
    r2_v = r2_vals[both_valid]

    ql_b = float(np.mean(qlike_loss(b, r2_v)))
    ql_a = float(np.mean(qlike_loss(a, r2_v)))
    loss_diff = qlike_loss(b, r2_v) - qlike_loss(a, r2_v)  # positive => alt better

    dm_t, dm_p, _ = hac_dm_test(loss_diff)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(loss_diff, n_boot=1000, seed=42)

    rho_b, _ = stats.spearmanr(b, r2_v)
    rho_a, _ = stats.spearmanr(a, r2_v)

    return {
        "n": n,
        "qlike_base": ql_b,
        f"qlike_{label_alt}": ql_a,
        "qlike_diff_pct": (ql_a - ql_b) / abs(ql_b) * 100.0,
        "dm_t": float(dm_t) if np.isfinite(dm_t) else None,
        "dm_p": float(dm_p) if np.isfinite(dm_p) else None,
        "harvey_pass": bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        "spearman_base": float(rho_b),
        f"spearman_{label_alt}": float(rho_a),
        "bootstrap_ci_95_qlike_diff": [ci_lo, ci_hi],
    }


# ============================================================
# MAIN PIPELINE (per asset)
# ============================================================


def load_asset(ticker, data_start):
    """Download ticker and VIX, align on ticker dates, drop NaN."""
    import yfinance as yf  # local import so fit_* funcs import fast

    raw = yf.download(
        ticker, start=data_start, end=DATA_END, progress=False, auto_adjust=False
    )
    if raw.empty:
        raise RuntimeError(f"No data for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    # Use Adj Close to be robust to splits/dividends, fallback to Close
    if "Adj Close" in raw.columns:
        price = raw["Adj Close"].astype(float)
    else:
        price = raw["Close"].astype(float)
    log_ret = np.log(price / price.shift(1))

    vix_raw = yf.download(
        "^VIX", start=data_start, end=DATA_END, progress=False, auto_adjust=False
    )
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    vix_close = vix_raw["Close"].astype(float)

    df = pd.DataFrame({"price": price, "log_ret": log_ret})
    df = df.dropna()
    df["VIX"] = vix_close.reindex(df.index).ffill()
    df = df.dropna(subset=["VIX"])
    return df


def run_asset(ticker, cfg):
    """Run A4f-VIX vs GJR for one ticker over its OOS window."""
    print("\n" + "=" * 78)
    print(f"ASSET: {ticker}  ({cfg['class_label']}, {cfg['currency']})")
    print(
        f"  data_start={cfg['data_start']}  window={cfg['window']}  "
        f"oos_start={cfg['oos_start']}  refit_every={cfg['refit_every']}"
    )
    print("=" * 78)

    df = load_asset(ticker, cfg["data_start"])
    print(
        f"  Aligned data: {df.index[0].date()} .. {df.index[-1].date()}  n={len(df)}"
    )

    ret = df["log_ret"].values.astype(float)
    vix = df["VIX"].values.astype(float)
    dates = df.index
    r2 = ret ** 2

    # Diagnostics (per Research Integrity #5 "observation before estimation")
    ret_for_stats = ret[~np.isnan(ret)]
    diag = {
        "n": int(len(ret_for_stats)),
        "mean_ret_ann": float(np.mean(ret_for_stats) * 252),
        "std_ret_ann": float(np.std(ret_for_stats) * np.sqrt(252)),
        "skew": float(stats.skew(ret_for_stats)),
        "kurt": float(stats.kurtosis(ret_for_stats)),
        "vix_mean": float(np.mean(vix)),
        "vix_max": float(np.max(vix)),
        "corr_ret_vix_level": float(np.corrcoef(ret_for_stats, vix[~np.isnan(ret)])[0, 1])
        if len(ret_for_stats) > 2
        else np.nan,
    }
    print(
        f"  Diagnostics: mean(ann)={diag['mean_ret_ann']:+.4f}  "
        f"std(ann)={diag['std_ret_ann']:.4f}  "
        f"skew={diag['skew']:+.3f}  kurt={diag['kurt']:.3f}  "
        f"corr(ret,VIX)={diag['corr_ret_vix_level']:+.3f}"
    )

    # OOS indices
    oos_mask = dates >= cfg["oos_start"]
    oos_indices = np.where(oos_mask)[0]
    if len(oos_indices) == 0:
        raise RuntimeError(f"{ticker}: no OOS observations from {cfg['oos_start']}")
    first_oos = oos_indices[0]
    if first_oos < cfg["window"]:
        raise RuntimeError(
            f"{ticker}: first OOS idx {first_oos} < window {cfg['window']}"
        )

    n_oos = len(oos_indices)
    print(
        f"  OOS: {dates[first_oos].date()} .. {dates[oos_indices[-1]].date()}  "
        f"n_oos={n_oos}"
    )

    gjr_fc = np.full(n_oos, np.nan)
    a4f_fc = np.full(n_oos, np.nan)
    refit_log = []

    gjr_params = None
    gjr_h = None
    a4f_params = None
    a4f_g = None
    refit_count = 0
    WINDOW = cfg["window"]
    REFIT_EVERY = cfg["refit_every"]

    asset_start = time.time()

    for t_idx, abs_idx in enumerate(oos_indices):
        need_refit = t_idx == 0 or (t_idx % REFIT_EVERY == 0)

        if need_refit:
            refit_count += 1
            train_start = max(0, abs_idx - WINDOW)
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            # GJR
            gjr_p, gjr_conv = fit_gjr(train_ret)
            if gjr_p is not None:
                gjr_params = gjr_p
                h = np.var(train_ret[: min(250, len(train_ret))])
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_params, h, train_ret[i - 1])
                gjr_h = h
            else:
                gjr_conv = False

            # A4f-VIX
            a4f_p, a4f_conv = fit_a4f_vix(train_ret, train_vix)
            if a4f_p is not None:
                a4f_params = a4f_p
                a4f_g = init_a4f_state(train_ret, train_vix, a4f_p)
            else:
                a4f_conv = False

            refit_log.append(
                {
                    "date": dates[abs_idx].strftime("%Y-%m-%d"),
                    "gjr_conv": bool(gjr_conv),
                    "a4f_conv": bool(a4f_conv),
                    "a4f_theta0": float(a4f_params[0]) if a4f_params is not None else None,
                    "a4f_theta1": float(a4f_params[1]) if a4f_params is not None else None,
                }
            )

            if refit_count % 10 == 0:
                elapsed = time.time() - asset_start
                print(
                    f"    [{ticker}] refit #{refit_count} at "
                    f"{dates[abs_idx].strftime('%Y-%m-%d')} elapsed {elapsed:.0f}s"
                )

        r_prev = ret[abs_idx - 1]

        if gjr_params is not None:
            h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
            gjr_fc[t_idx] = h_new
            gjr_h = h_new

        if a4f_params is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            v_lag = vix[abs_idx - 1]
            tau_t = max(theta0 + theta1 * v_lag ** 2, 1e-16)
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * a4f_g
            g_new = max(g_new, 1e-10)
            a4f_fc[t_idx] = tau_t * g_new
            a4f_g = g_new

    elapsed = time.time() - asset_start
    print(f"  Done: {refit_count} refits, {elapsed:.0f}s")

    oos_r2 = r2[oos_indices]
    full = evaluate_pair(gjr_fc, a4f_fc, oos_r2, label_alt="a4f_vix")
    if full is None:
        raise RuntimeError(f"{ticker}: insufficient valid OOS observations")

    dm_t = full["dm_t"]
    harvey = "PASS" if full["harvey_pass"] else "FAIL"
    print(
        f"  Full OOS ({ticker}): n={full['n']}  QL_base={full['qlike_base']:.5f}  "
        f"QL_a4f={full['qlike_a4f_vix']:.5f}  Δ%={full['qlike_diff_pct']:+.2f}  "
        f"DM_t={dm_t:+.3f}  {harvey}"
    )

    # Meta prediction comparison
    pred = K1090_RIDGE_PRED.get(ticker)
    pi_lo, pi_hi = K1090_RIDGE_PI95.get(ticker, (None, None))
    realized = dm_t if dm_t is not None else np.nan
    abs_err = abs(realized - pred) if (pred is not None and np.isfinite(realized)) else None
    within_pi = (
        bool(pi_lo <= realized <= pi_hi)
        if (pi_lo is not None and pi_hi is not None and np.isfinite(realized))
        else None
    )
    print(
        f"  Meta: K1090 ridge_pred={pred:+.2f}  realized={realized:+.2f}  "
        f"|err|={abs_err:.3f}  within_PI95={within_pi}"
    )

    return {
        "ticker": ticker,
        "class_label": cfg["class_label"],
        "currency": cfg["currency"],
        "data_start": str(dates[0].date()),
        "data_end": str(dates[-1].date()),
        "n_total": int(len(df)),
        "window": int(cfg["window"]),
        "refit_every": int(cfg["refit_every"]),
        "oos_start": str(dates[first_oos].date()),
        "oos_end": str(dates[oos_indices[-1]].date()),
        "n_oos": int(n_oos),
        "n_refits": int(refit_count),
        "diagnostics": diag,
        "full_oos": full,
        "meta_validation": {
            "k1090_ridge_pred": pred,
            "k1090_ridge_pi95": [pi_lo, pi_hi],
            "k1090_recommendation": K1090_RECOMMEND.get(ticker),
            "realized_dm_t": realized if np.isfinite(realized) else None,
            "abs_error": abs_err,
            "within_pi95": within_pi,
            "harvey_pass": full["harvey_pass"],
            "meta_prediction_correct_direction": (
                bool(
                    (pred >= 3.0 and full["harvey_pass"])
                    or (pred < 3.0 and not full["harvey_pass"])
                )
                if pred is not None
                else None
            ),
        },
        "forecasts": {
            # Store only last/first few for debugging; full arrays omitted to keep JSON small
            "first_date": dates[first_oos].strftime("%Y-%m-%d"),
            "last_date": dates[oos_indices[-1]].strftime("%Y-%m-%d"),
            "gjr_qlike_full": full["qlike_base"],
            "a4f_qlike_full": full["qlike_a4f_vix"],
        },
        "refit_log": refit_log,
    }


# ============================================================
# RUN ALL FOUR ASSETS
# ============================================================

all_results = {}
for ticker, cfg in ASSET_CONFIG.items():
    all_results[ticker] = run_asset(ticker, cfg)


# ============================================================
# META SUMMARY
# ============================================================

print("\n" + "=" * 78)
print("META VALIDATION SUMMARY")
print("=" * 78)
print(
    f"  {'Ticker':<8} {'K1090_pred':>12} {'Realized':>10} {'|Err|':>8} "
    f"{'in_PI95':>8} {'Harvey':>8} {'Rec':<12}"
)

pred_list = []
real_list = []
err_list = []
directions_correct = 0
harvey_pass_count = 0
for ticker, r in all_results.items():
    mv = r["meta_validation"]
    pred = mv["k1090_ridge_pred"]
    real = mv["realized_dm_t"]
    err = mv["abs_error"]
    in_pi = mv["within_pi95"]
    harvey = "PASS" if r["full_oos"]["harvey_pass"] else "FAIL"
    rec = mv["k1090_recommendation"]
    if mv["meta_prediction_correct_direction"]:
        directions_correct += 1
    if r["full_oos"]["harvey_pass"]:
        harvey_pass_count += 1
    pred_list.append(pred)
    real_list.append(real if real is not None else np.nan)
    err_list.append(err if err is not None else np.nan)
    print(
        f"  {ticker:<8} {pred:>+12.3f} {real:>+10.3f} {err:>8.3f} "
        f"{str(in_pi):>8} {harvey:>8} {rec:<12}"
    )

mae = float(np.nanmean(err_list)) if err_list else None
rmse = float(np.sqrt(np.nanmean(np.array(err_list) ** 2))) if err_list else None
bias = float(np.nanmean(np.array(real_list) - np.array(pred_list))) if real_list else None

print(
    f"\n  MAE  = {mae:.3f}  (K1090 LOOCV RMSE was 1.943 → {'LOWER' if mae < 1.943 else 'HIGHER'})"
)
print(f"  RMSE = {rmse:.3f}")
print(f"  Mean bias (realized − pred) = {bias:+.3f}")
print(f"  Harvey pass count: {harvey_pass_count}/4")
print(f"  Direction-correct predictions: {directions_correct}/4")

# H5 check: MAE < 1.943
h5_pass = mae < 1.943 if mae is not None else False

out = {
    "metadata": {
        "experiment_id": EXPERIMENT_ID,
        "title": "Out-of-sample validation of K1090 meta-regression (VGK/EWJ/CPER/SLV)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": 42,
        "data_end": DATA_END,
        "upstream_K": ["K1090", "K1075", "K1085", "K1088", "K1089"],
        "caveat": (
            "Validation sample of only N=4 assets. MAE is a point estimate; "
            "with n=4 the confidence interval on MAE itself is very wide."
        ),
    },
    "asset_results": all_results,
    "meta_summary": {
        "k1090_formula_compact": "DM_t ~ -1.22 + 3.38*USD_dummy - 4.11*corr(ret, dVIX)",
        "k1090_loocv_rmse": 1.942752,
        "n_assets": len(all_results),
        "harvey_pass_count": harvey_pass_count,
        "direction_correct_count": directions_correct,
        "mae_realized_vs_pred": mae,
        "rmse_realized_vs_pred": rmse,
        "mean_bias_realized_minus_pred": bias,
        "h1_vgk_harvey_pass": all_results["VGK"]["full_oos"]["harvey_pass"],
        "h2_ewj_harvey_pass": all_results["EWJ"]["full_oos"]["harvey_pass"],
        "h3_cper_harvey_pass": all_results["CPER"]["full_oos"]["harvey_pass"],
        "h4_slv_harvey_pass": all_results["SLV"]["full_oos"]["harvey_pass"],
        "h5_mae_below_loocv_rmse": bool(h5_pass),
    },
}

with open(RESULTS_PATH, "w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"\n  Results saved: {RESULTS_PATH}")

total_elapsed = time.time() - START_TIME
print(f"\nTotal runtime: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")

# ============================================================
# PLOTS
# ============================================================
print("\n[Plots] Generating figures...")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TICKS = list(ASSET_CONFIG.keys())
preds = [K1090_RIDGE_PRED[t] for t in TICKS]
reals = [all_results[t]["full_oos"]["dm_t"] for t in TICKS]
pi_lo = [K1090_RIDGE_PI95[t][0] for t in TICKS]
pi_hi = [K1090_RIDGE_PI95[t][1] for t in TICKS]

# 1. Meta validation scatter
fig, ax = plt.subplots(figsize=(7, 6))
ax.errorbar(
    preds,
    reals,
    xerr=[np.array(preds) - np.array(pi_lo), np.array(pi_hi) - np.array(preds)],
    fmt="o",
    color="#1f77b4",
    ecolor="#aaa",
    capsize=4,
    markersize=10,
    label="Realized vs K1090 ridge",
)
lo = min(min(preds), min(reals), -1)
hi = max(max(preds), max(reals), 6)
ax.plot([lo, hi], [lo, hi], "k--", lw=1, alpha=0.5, label="perfect prediction")
ax.axhline(3.0, color="red", lw=1, ls=":", alpha=0.6, label="Harvey |t|=3 threshold")
ax.axvline(3.0, color="red", lw=1, ls=":", alpha=0.6)
for x, y, t in zip(preds, reals, TICKS):
    ax.annotate(
        t,
        (x, y),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
    )
ax.set_xlabel("K1090 ridge prediction (DM t)")
ax.set_ylabel("Realized A4f-VIX² DM t (OOS)")
ax.set_title("K1091: Meta-regression predictions vs realized (VGK/EWJ/CPER/SLV)")
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1091_meta_validation.png"), dpi=150)
plt.close(fig)

# 2. Four-asset DM bar chart (+ Harvey line)
fig, ax = plt.subplots(figsize=(8, 5))
colors = ["#2ca02c" if all_results[t]["full_oos"]["harvey_pass"] else "#d62728" for t in TICKS]
bars = ax.bar(TICKS, reals, color=colors, alpha=0.85, edgecolor="black")
ax.bar(
    TICKS,
    preds,
    color="none",
    edgecolor="#1f77b4",
    linewidth=2,
    linestyle="--",
    label="K1090 ridge prediction",
)
ax.axhline(3.0, color="black", lw=1.2, ls=":", label="Harvey |t|=3")
ax.axhline(0.0, color="grey", lw=0.8)
for bar, val in zip(bars, reals):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        val + (0.12 if val >= 0 else -0.28),
        f"{val:+.2f}",
        ha="center",
        va="bottom" if val >= 0 else "top",
        fontsize=10,
        fontweight="bold",
    )
ax.set_ylabel("DM t-statistic (A4f-VIX² vs GJR)")
ax.set_title("K1091: Realized DM-t for four new assets (green=PASS, red=FAIL)")
ax.legend(loc="upper right", fontsize=9)
ax.grid(True, alpha=0.3, axis="y")
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1091_four_assets_dm.png"), dpi=150)
plt.close(fig)

# 3. Updated Paper 9 16-asset matrix (training 12 + K1091 4)
K1090_TRAIN = {
    "SPY": 7.92,
    "QQQ": 5.99,
    "EEM": 5.25,
    "IWM": 4.80,
    "GLD": 4.46,
    "USO": 4.48,
    "FXI": 3.61,
    "EWZ": 2.33,
    "EWT": 2.26,
    "TLT": 1.43,
    "BTC-USD": 1.13,
    "0050.TW": -0.49,
}

combined_order = (
    sorted(K1090_TRAIN.keys(), key=lambda k: -K1090_TRAIN[k])
    + sorted(TICKS, key=lambda k: -all_results[k]["full_oos"]["dm_t"])
)
combined_values = [K1090_TRAIN[k] for k in combined_order[:12]] + [
    all_results[k]["full_oos"]["dm_t"] for k in combined_order[12:]
]
combined_source = ["training"] * 12 + ["K1091"] * 4
combined_colors = []
for k, s in zip(combined_order, combined_source):
    v = K1090_TRAIN[k] if s == "training" else all_results[k]["full_oos"]["dm_t"]
    if s == "K1091":
        combined_colors.append("#2ca02c" if v > 3.0 else "#d62728")
    else:
        combined_colors.append("#1f77b4" if v > 3.0 else "#bbbbbb")

fig, ax = plt.subplots(figsize=(12, 6))
bars = ax.bar(combined_order, combined_values, color=combined_colors, edgecolor="black", alpha=0.85)
ax.axhline(3.0, color="black", lw=1.2, ls=":", label="Harvey |t|=3")
ax.axhline(0.0, color="grey", lw=0.8)
for bar, val, src in zip(bars, combined_values, combined_source):
    label = f"{val:+.2f}"
    if src == "K1091":
        label += "*"
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        val + (0.12 if val >= 0 else -0.28),
        label,
        ha="center",
        va="bottom" if val >= 0 else "top",
        fontsize=9,
    )
ax.set_ylabel("DM t-statistic (A4f-VIX² vs GJR)")
ax.set_title(
    "Paper 9 cross-asset matrix: 12 training assets (blue) + 4 K1091 validation assets (green/red, *) "
)
ax.set_xticklabels(combined_order, rotation=45, ha="right")
ax.legend(loc="upper right", fontsize=9)
ax.grid(True, alpha=0.3, axis="y")
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, "k1091_updated_matrix.png"), dpi=150)
plt.close(fig)

print("  Plots saved: k1091_meta_validation.png, k1091_four_assets_dm.png, k1091_updated_matrix.png")
print("\nK1091 COMPLETE.")
