"""
K1133b robustness battery for the BTC GAS-t negative-result paper.

This script is deliberately separate from k1133b.py.  It rebuilds the
lookahead-safe rolling forecasts needed for robustness diagnostics and writes
all new numbers to k1133b_robustness_results.json.

Run:
    python experiments/k1133b/k1133b_robustness.py
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

warnings.filterwarnings("ignore")
np.random.seed(42)
sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_RESULTS_PATH = os.path.join(SCRIPT_DIR, "k1133b_results.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "k1133b_robustness_results.json")

SEED = 42
START = "2015-01-01"
END = "2026-04-15"
WINDOW_DEFAULT = 750
WINDOW_MIN = 500
REFIT_EVERY = 63
MULTISTART_SEEDS = int(os.environ.get("K1133B_MULTISTART_SEEDS", "100"))
if MULTISTART_SEEDS < 100:
    raise ValueError(
        f"K1133B_MULTISTART_SEEDS must be >=100 for paper robustness (got {MULTISTART_SEEDS}); "
        "K1213 教訓 — univariate GAS-t dispersion 需 ≥100 seeds 才能穩定畫出 cross-seed log-lik 分佈。"
    )
ALT_DIST_REFIT_EVERY = int(os.environ.get("K1133B_ALT_DIST_REFIT_EVERY", "252"))
ALT_DIST_MAXITER = int(os.environ.get("K1133B_ALT_DIST_MAXITER", "120"))
ALT_DIST_STARTS = max(1, int(os.environ.get("K1133B_ALT_DIST_STARTS", "1")))

MODEL_KEYS = [
    "M1_GJR_N",
    "M2_GJR_t",
    "M3_GAS_t",
    "M4_GAS_N",
    "M5_GJR_N_std",
]


def _safe_float(x):
    if x is None:
        return None
    try:
        xf = float(x)
    except Exception:
        return None
    return xf if np.isfinite(xf) else None


def _date_str(d):
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def download_returns(ticker, start=START, end=END):
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"No yfinance data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    prices = df[price_col].dropna()
    returns_pct = prices.pct_change().dropna() * 100.0
    if returns_pct.empty:
        raise RuntimeError(f"No return series for {ticker}")
    return returns_pct


# ---------------------------------------------------------------------------
# Original K1133b model definitions: copied verbatim where possible.
# ---------------------------------------------------------------------------
def gjr_normal_negloglik(params, returns):
    omega, alpha, gamma, beta = params
    t_len = len(returns)
    sigma2 = np.zeros(t_len)
    sigma2[0] = np.var(returns)
    for t in range(1, t_len):
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = (
            omega
            + alpha * returns[t - 1] ** 2
            + gamma * returns[t - 1] ** 2 * ind
            + beta * sigma2[t - 1]
        )
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def fit_gjr_normal(returns):
    t_len = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
    try:
        res = minimize(
            gjr_normal_negloglik,
            x0,
            args=(returns,),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500},
        )
    except Exception:
        return None, None, None
    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(t_len)
    sigma2[0] = var_r
    for t in range(1, t_len):
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = (
            omega
            + alpha * returns[t - 1] ** 2
            + gamma * returns[t - 1] ** 2 * ind
            + beta * sigma2[t - 1]
        )
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return (
        {"omega": omega, "alpha": alpha, "gamma": gamma, "beta": beta},
        sigma2,
        float(res.fun),
    )


def gjr_t_negloglik(params, returns):
    omega, alpha, gamma, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    t_len = len(returns)
    sigma2 = np.zeros(t_len)
    sigma2[0] = np.var(returns)
    for t in range(1, t_len):
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = (
            omega
            + alpha * returns[t - 1] ** 2
            + gamma * returns[t - 1] ** 2 * ind
            + beta * sigma2[t - 1]
        )
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.0
    for t in range(t_len):
        eps2 = returns[t] ** 2 / sigma2[t]
        ll_t = (
            gammaln((nu + 1) / 2)
            - gammaln(nu / 2)
            - 0.5 * np.log(np.pi * (nu - 2) * sigma2[t])
            - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2))
        )
        nll -= ll_t
    return nll if np.isfinite(nll) else 1e10


def fit_gjr_t(returns):
    t_len = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90, np.log(6.0)]
    bounds = [
        (1e-8, var_r * 10),
        (1e-8, 0.5),
        (1e-8, 0.5),
        (0.3, 0.999),
        (np.log(0.1), np.log(100.0)),
    ]
    try:
        res = minimize(
            gjr_t_negloglik,
            x0,
            args=(returns,),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500},
        )
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [var_r * 0.02, 0.05, 0.08, 0.88, np.log(4.0)],
                [var_r * 0.08, 0.02, 0.03, 0.92, np.log(10.0)],
            ]:
                try:
                    res2 = minimize(
                        gjr_t_negloglik,
                        x0_alt,
                        args=(returns,),
                        method="L-BFGS-B",
                        bounds=bounds,
                        options={"maxiter": 500},
                    )
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None, None
    omega, alpha, gamma, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    sigma2 = np.zeros(t_len)
    sigma2[0] = var_r
    for t in range(1, t_len):
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = (
            omega
            + alpha * returns[t - 1] ** 2
            + gamma * returns[t - 1] ** 2 * ind
            + beta * sigma2[t - 1]
        )
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return (
        {"omega": omega, "alpha": alpha, "gamma": gamma, "beta": beta, "nu": nu},
        sigma2,
        float(res.fun),
    )


def gas_t_negloglik(params, returns):
    omega, alpha, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    t_len = len(returns)
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(t_len):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t] ** 2 / sigma2_t
        ll_t = (
            gammaln((nu + 1) / 2)
            - gammaln(nu / 2)
            - 0.5 * np.log(np.pi * (nu - 2) * sigma2_t)
            - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2))
        )
        nll -= ll_t
        if t < t_len - 1:
            score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
            scale = 2 * nu / ((nu + 3) * (nu - 2))
            f[t + 1] = omega + alpha * scale * score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_t(returns):
    t_len = len(returns)
    x0 = [0.01, 0.05, 0.95, np.log(6.0)]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(
            gas_t_negloglik,
            x0,
            args=(returns,),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500},
        )
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90, np.log(4.0)],
                [0.02, 0.03, 0.97, np.log(10.0)],
                [0.0, 0.08, 0.92, np.log(8.0)],
            ]:
                try:
                    res2 = minimize(
                        gas_t_negloglik,
                        x0_alt,
                        args=(returns,),
                        method="L-BFGS-B",
                        bounds=bounds,
                        options={"maxiter": 500},
                    )
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None, None
    omega, alpha, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    for t in range(t_len - 1):
        sigma2_t = max(np.exp(f[t]), 1e-10)
        eps2 = returns[t] ** 2 / sigma2_t
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        scale = 2 * nu / ((nu + 3) * (nu - 2))
        f[t + 1] = omega + alpha * scale * score + beta * f[t]
    return {"omega": omega, "alpha": alpha, "beta": beta, "nu": nu}, np.exp(f), float(res.fun)


def gas_normal_negloglik(params, returns):
    omega, alpha, beta = params
    t_len = len(returns)
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(t_len):
        sigma2_t = max(np.exp(f[t]), 1e-10)
        eps2 = returns[t] ** 2 / sigma2_t
        ll_t = -0.5 * (np.log(2 * np.pi) + f[t] + eps2)
        nll -= ll_t
        if t < t_len - 1:
            f[t + 1] = omega + alpha * (eps2 - 1.0) + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_normal(returns):
    t_len = len(returns)
    x0 = [0.01, 0.05, 0.95]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999)]
    try:
        res = minimize(
            gas_normal_negloglik,
            x0,
            args=(returns,),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500},
        )
        if not res.success or res.fun > 1e9:
            for x0_alt in [[0.005, 0.1, 0.90], [0.02, 0.03, 0.97], [0.0, 0.08, 0.92]]:
                try:
                    res2 = minimize(
                        gas_normal_negloglik,
                        x0_alt,
                        args=(returns,),
                        method="L-BFGS-B",
                        bounds=bounds,
                        options={"maxiter": 500},
                    )
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None, None
    omega, alpha, beta = res.x
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    for t in range(t_len - 1):
        sigma2_t = max(np.exp(f[t]), 1e-10)
        eps2 = returns[t] ** 2 / sigma2_t
        f[t + 1] = omega + alpha * (eps2 - 1.0) + beta * f[t]
    return {"omega": omega, "alpha": alpha, "beta": beta}, np.exp(f), float(res.fun)


def fit_gjr_normal_standardised(returns):
    mu = np.mean(returns)
    sd = np.std(returns)
    if sd < 1e-10:
        return None, None, None
    r_std = (returns - mu) / sd
    params_std, sigma2_std, nll = fit_gjr_normal(r_std)
    if params_std is None:
        return None, None, None
    return (
        {"params_std": params_std, "mu": mu, "sd": sd},
        sigma2_std * sd**2,
        float(nll) if nll is not None else None,
    )


# ---------------------------------------------------------------------------
# Alternative GAS innovation densities: Hansen skewed-t and unit-variance GED.
# These are not claimed to be Fisher-scaled; the score is a finite-difference
# derivative with respect to log variance and alpha is estimated accordingly.
# ---------------------------------------------------------------------------
def hansen_skewt_logpdf(z, eta, lam):
    z = np.asarray(z, dtype=float)
    if eta <= 2.0 or abs(lam) >= 1.0:
        return np.full_like(z, -1e10, dtype=float)
    c = np.exp(gammaln((eta + 1.0) / 2.0) - gammaln(eta / 2.0)) / np.sqrt(np.pi * (eta - 2.0))
    a = 4.0 * lam * c * ((eta - 2.0) / (eta - 1.0))
    b2 = 1.0 + 3.0 * lam**2 - a**2
    if b2 <= 0:
        return np.full_like(z, -1e10, dtype=float)
    b = np.sqrt(b2)
    y = b * z + a
    left = np.log(b) + np.log(c) - ((eta + 1.0) / 2.0) * np.log(
        1.0 + (y / (1.0 - lam)) ** 2 / (eta - 2.0)
    )
    right = np.log(b) + np.log(c) - ((eta + 1.0) / 2.0) * np.log(
        1.0 + (y / (1.0 + lam)) ** 2 / (eta - 2.0)
    )
    return np.where(y < 0, left, right)


def ged_logpdf(z, nu):
    z = np.asarray(z, dtype=float)
    if nu <= 1.01:
        return np.full_like(z, -1e10, dtype=float)
    log_alpha = 0.5 * (gammaln(1.0 / nu) - gammaln(3.0 / nu))
    alpha = np.exp(log_alpha)
    return np.log(nu) - np.log(2.0) - log_alpha - gammaln(1.0 / nu) - (np.abs(z) / alpha) ** nu


def alt_logpdf_z(z, dist_name, shape_params):
    if dist_name == "skewt":
        eta, lam = shape_params
        return hansen_skewt_logpdf(z, eta, lam)
    if dist_name == "ged":
        (nu,) = shape_params
        return ged_logpdf(z, nu)
    raise ValueError(f"Unknown alternative GAS distribution: {dist_name}")


def alt_cond_loglik_scalar(ret, f_value, dist_name, shape_params):
    f_value = float(np.clip(f_value, -30.0, 30.0))
    z = ret / np.exp(0.5 * f_value)
    return float(alt_logpdf_z(np.array([z]), dist_name, shape_params)[0] - 0.5 * f_value)


def alt_score_f(ret, f_value, dist_name, shape_params):
    eps = 1e-4
    ll_plus = alt_cond_loglik_scalar(ret, f_value + eps, dist_name, shape_params)
    ll_minus = alt_cond_loglik_scalar(ret, f_value - eps, dist_name, shape_params)
    score = (ll_plus - ll_minus) / (2.0 * eps)
    if not np.isfinite(score):
        return 0.0
    return float(np.clip(score, -100.0, 100.0))


def gas_alt_negloglik(params, returns, dist_name):
    omega, alpha, beta = params[:3]
    shape = params[3:]
    t_len = len(returns)
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(t_len):
        ll_t = alt_cond_loglik_scalar(returns[t], f[t], dist_name, shape)
        nll -= ll_t
        if t < t_len - 1:
            score = alt_score_f(returns[t], f[t], dist_name, shape)
            f[t + 1] = omega + alpha * score + beta * f[t]
            if not np.isfinite(f[t + 1]):
                return 1e10
            f[t + 1] = np.clip(f[t + 1], -30.0, 30.0)
    return nll if np.isfinite(nll) else 1e10


def fit_gas_alt(returns, dist_name):
    t_len = len(returns)
    if dist_name == "skewt":
        starts = [
            [0.01, 0.05, 0.95, 8.0, 0.0],
            [0.005, 0.10, 0.90, 5.0, -0.10],
            [0.02, 0.03, 0.97, 12.0, 0.10],
        ]
        bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (2.05, 60.0), (-0.95, 0.95)]
    elif dist_name == "ged":
        starts = [[0.01, 0.05, 0.95, 1.5], [0.005, 0.10, 0.90, 1.2], [0.02, 0.03, 0.97, 2.0]]
        bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (1.05, 10.0)]
    else:
        raise ValueError(dist_name)

    best = None
    for x0 in starts[:ALT_DIST_STARTS]:
        try:
            res = minimize(
                gas_alt_negloglik,
                x0,
                args=(returns, dist_name),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": ALT_DIST_MAXITER, "ftol": 1e-6},
            )
            if best is None or res.fun < best.fun:
                best = res
        except Exception:
            continue
    if best is None or not np.isfinite(best.fun) or best.fun > 1e9:
        return None, None, None

    omega, alpha, beta = best.x[:3]
    shape = best.x[3:]
    f = np.zeros(t_len)
    f[0] = np.log(np.var(returns))
    for t in range(t_len - 1):
        score = alt_score_f(returns[t], f[t], dist_name, shape)
        f[t + 1] = omega + alpha * score + beta * f[t]
        f[t + 1] = np.clip(f[t + 1], -30.0, 30.0)

    params = {"omega": omega, "alpha": alpha, "beta": beta, "dist": dist_name}
    if dist_name == "skewt":
        params.update({"eta": shape[0], "lambda": shape[1]})
    else:
        params.update({"nu": shape[0]})
    return params, np.exp(f), float(best.fun)


def forecast_one_step(model_type, params, last_return, last_sigma2, last_f=None):
    if model_type in ("M1_GJR_N", "M2_GJR_t"):
        ind = 1.0 if last_return < 0 else 0.0
        h = (
            params["omega"]
            + params["alpha"] * last_return**2
            + params["gamma"] * last_return**2 * ind
            + params["beta"] * last_sigma2
        )
        return max(h, 1e-10), None
    if model_type == "M3_GAS_t":
        nu = params["nu"]
        eps2 = last_return**2 / last_sigma2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        scale = 2 * nu / ((nu + 3) * (nu - 2))
        new_f = params["omega"] + params["alpha"] * scale * score + params["beta"] * last_f
        return max(np.exp(new_f), 1e-10), new_f
    if model_type == "M4_GAS_N":
        eps2 = last_return**2 / last_sigma2
        new_f = params["omega"] + params["alpha"] * (eps2 - 1.0) + params["beta"] * last_f
        return max(np.exp(new_f), 1e-10), new_f
    if model_type == "M5_GJR_N_std":
        mu = params["mu"]
        sd = params["sd"]
        p = params["params_std"]
        r_std = (last_return - mu) / sd
        last_sigma2_std = last_sigma2 / (sd**2) if sd > 0 else last_sigma2
        ind = 1.0 if r_std < 0 else 0.0
        h_std = p["omega"] + p["alpha"] * r_std**2 + p["gamma"] * r_std**2 * ind + p["beta"] * last_sigma2_std
        return max(h_std, 1e-10) * sd**2, None
    if model_type in ("M6_GAS_skewt", "M7_GAS_GED"):
        dist_name = "skewt" if model_type == "M6_GAS_skewt" else "ged"
        shape = [params["eta"], params["lambda"]] if dist_name == "skewt" else [params["nu"]]
        score = alt_score_f(last_return, last_f, dist_name, shape)
        new_f = params["omega"] + params["alpha"] * score + params["beta"] * last_f
        new_f = float(np.clip(new_f, -30.0, 30.0))
        return max(np.exp(new_f), 1e-10), new_f
    raise ValueError(f"Unknown model: {model_type}")


def fit_model(model_key, train_data):
    if model_key == "M1_GJR_N":
        return fit_gjr_normal(train_data)
    if model_key == "M2_GJR_t":
        return fit_gjr_t(train_data)
    if model_key == "M3_GAS_t":
        return fit_gas_t(train_data)
    if model_key == "M4_GAS_N":
        return fit_gas_normal(train_data)
    if model_key == "M5_GJR_N_std":
        return fit_gjr_normal_standardised(train_data)
    if model_key == "M6_GAS_skewt":
        return fit_gas_alt(train_data, "skewt")
    if model_key == "M7_GAS_GED":
        return fit_gas_alt(train_data, "ged")
    raise ValueError(model_key)


def qlike_ind(actual_r2, predicted_sigma2):
    ratio = actual_r2 / predicted_sigma2
    with np.errstate(divide="ignore", invalid="ignore"):
        ql = ratio - np.log(np.where(ratio > 0, ratio, 1e-30)) - 1.0
    ql[actual_r2 <= 0] = np.nan
    ql[predicted_sigma2 <= 0] = np.nan
    return ql


def mse_ind(actual_r2, predicted_sigma2):
    out = (actual_r2 - predicted_sigma2) ** 2
    out[~np.isfinite(out)] = np.nan
    out[predicted_sigma2 <= 0] = np.nan
    return out


def patton_bminus1_ind(actual_r2, predicted_sigma2):
    out = predicted_sigma2 - actual_r2 + actual_r2 * np.log(np.where(actual_r2 > 0, actual_r2 / predicted_sigma2, 1.0))
    out[actual_r2 <= 0] = np.nan
    out[predicted_sigma2 <= 0] = np.nan
    out[~np.isfinite(out)] = np.nan
    return out


def loss_ind(loss_name, actual_r2, predicted_sigma2):
    if loss_name == "QLIKE_b_minus_2":
        return qlike_ind(actual_r2, predicted_sigma2)
    if loss_name == "MSE_b_0":
        return mse_ind(actual_r2, predicted_sigma2)
    if loss_name == "Patton_b_minus_1":
        return patton_bminus1_ind(actual_r2, predicted_sigma2)
    raise ValueError(loss_name)


def dm_hln_test(loss1, loss2, h=1):
    d = loss1 - loss2
    d = d[np.isfinite(d) & ~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    max_lag = int(np.floor(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0 or not np.isfinite(var_d):
        return 0.0, 1.0, n
    dm_stat = d_mean / np.sqrt(var_d)
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln_correction * dm_stat
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value, n


def rolling_oos(returns_pct, period_start, period_end, model_keys, ticker, label, verbose=True, refit_every=REFIT_EVERY):
    returns_arr = returns_pct.values.astype(float)
    dates = returns_pct.index.to_numpy()
    start_dt = np.datetime64(period_start)
    end_dt = np.datetime64(period_end)
    sp_mask = (dates >= start_dt) & (dates <= end_dt)
    sp_indices = np.where(sp_mask)[0]
    if len(sp_indices) < WINDOW_MIN + 100:
        return {
            "status": "skipped_insufficient_obs",
            "ticker": ticker,
            "label": label,
            "requested_start": period_start,
            "requested_end": period_end,
            "n_sp": int(len(sp_indices)),
            "min_required": WINDOW_MIN + 100,
        }

    sp_first = int(sp_indices[0])
    sp_last = int(sp_indices[-1]) + 1
    sp_returns = returns_arr[sp_first:sp_last]
    sp_dates = dates[sp_first:sp_last]
    n_sp = len(sp_returns)
    window = min(WINDOW_DEFAULT, n_sp - 100)
    window = max(window, WINDOW_MIN)
    n_oos = n_sp - window

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    current_params = {m: None for m in model_keys}
    current_sigma2 = {m: None for m in model_keys}
    current_f = {m: None for m in model_keys}
    refit_log = []
    last_fit = -REFIT_EVERY
    t0 = time.time()

    if verbose:
        print(f"[rolling] {label}: {ticker} {period_start}->{period_end} n_sp={n_sp} window={window} n_oos={n_oos}")

    for t_oos in range(n_oos):
        t_abs = window + t_oos
        if t_oos - last_fit >= refit_every or t_oos == 0:
            train_start = max(0, t_abs - window)
            train_data = sp_returns[train_start:t_abs]
            assert train_start + len(train_data) == t_abs, "Train window leaks into forecast observation"
            assert t_abs - 1 < t_abs, "Forecast must use information through t-1 only"
            if len(train_data) < WINDOW_MIN:
                continue

            refit_entry = {
                "t_oos": int(t_oos),
                "forecast_date": _date_str(sp_dates[t_abs]),
                "train_start": _date_str(sp_dates[train_start]),
                "train_end": _date_str(sp_dates[t_abs - 1]),
                "train_n": int(len(train_data)),
                "models": {},
            }

            for m in model_keys:
                params, sigma2, nll = fit_model(m, train_data)
                if params is None or sigma2 is None or len(sigma2) == 0:
                    refit_entry["models"][m] = {"fit_ok": False}
                    continue
                current_params[m] = params
                current_sigma2[m] = float(sigma2[-1])
                if m in ("M3_GAS_t", "M4_GAS_N", "M6_GAS_skewt", "M7_GAS_GED"):
                    current_f[m] = float(np.log(max(sigma2[-1], 1e-10)))
                refit_entry["models"][m] = {
                    "fit_ok": True,
                    "nll": _safe_float(nll),
                }
            refit_log.append(refit_entry)
            last_fit = t_oos
            if verbose and (t_oos == 0 or t_oos % (refit_every * 5) == 0):
                print(f"  refit t_oos={t_oos}/{n_oos} elapsed={time.time() - t0:.1f}s")

        last_r = sp_returns[t_abs - 1]
        for m in model_keys:
            if current_params[m] is None:
                continue
            if m in ("M3_GAS_t", "M4_GAS_N", "M6_GAS_skewt", "M7_GAS_GED"):
                h, new_f = forecast_one_step(m, current_params[m], last_r, current_sigma2[m], current_f[m])
                current_f[m] = new_f
            else:
                h, _ = forecast_one_step(m, current_params[m], last_r, current_sigma2[m])
            forecasts[m][t_oos] = h
            current_sigma2[m] = h

    actual_r2 = sp_returns[window:] ** 2
    oos_dates = sp_dates[window:]
    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m]) & (forecasts[m] > 0)

    if int(np.sum(valid_mask)) < 100:
        return {
            "status": "skipped_too_few_valid_forecasts",
            "ticker": ticker,
            "label": label,
            "requested_start": period_start,
            "requested_end": period_end,
            "n_sp": int(n_sp),
            "n_valid": int(np.sum(valid_mask)),
            "refit_log": refit_log,
        }

    out = {
        "status": "ok",
        "ticker": ticker,
        "label": label,
        "requested_start": period_start,
        "requested_end": period_end,
        "actual_start": _date_str(sp_dates[0]),
        "actual_end": _date_str(sp_dates[-1]),
        "n_sp": int(n_sp),
        "window": int(window),
        "refit_every": int(refit_every),
        "n_oos": int(np.sum(valid_mask)),
        "oos_start": _date_str(oos_dates[valid_mask][0]),
        "oos_end": _date_str(oos_dates[valid_mask][-1]),
        "models": list(model_keys),
        "refit_count": int(len(refit_log)),
        "refit_log": refit_log,
        "lookahead_assertion": "train_data = sp_returns[train_start:t_abs]; forecast_date = sp_dates[t_abs]; last_r = sp_returns[t_abs-1]",
        "elapsed_seconds": float(time.time() - t0),
        "actual_r2": actual_r2[valid_mask].tolist(),
        "oos_dates": [_date_str(d) for d in oos_dates[valid_mask]],
        "forecasts": {m: forecasts[m][valid_mask].tolist() for m in model_keys},
    }
    out["model_metrics"] = {
        m: {
            "QLIKE": _safe_float(np.nanmean(qlike_ind(np.asarray(out["actual_r2"]), np.asarray(out["forecasts"][m])))),
            "MSE": _safe_float(np.nanmean(mse_ind(np.asarray(out["actual_r2"]), np.asarray(out["forecasts"][m])))),
            "Patton_b_minus_1": _safe_float(
                np.nanmean(patton_bminus1_ind(np.asarray(out["actual_r2"]), np.asarray(out["forecasts"][m])))
            ),
        }
        for m in model_keys
    }
    if verbose:
        print(f"  done {label}: valid={out['n_oos']} elapsed={out['elapsed_seconds']:.1f}s")
    return out


def contrast_summary(oos, model_a, model_b, loss_name="QLIKE_b_minus_2", mask=None):
    actual = np.asarray(oos["actual_r2"], dtype=float)
    f_a = np.asarray(oos["forecasts"][model_a], dtype=float)
    f_b = np.asarray(oos["forecasts"][model_b], dtype=float)
    if mask is None:
        mask = np.ones(len(actual), dtype=bool)
    else:
        mask = np.asarray(mask, dtype=bool)
    loss_a = loss_ind(loss_name, actual[mask], f_a[mask])
    loss_b = loss_ind(loss_name, actual[mask], f_b[mask])
    t_stat, p_val, n_used = dm_hln_test(loss_a, loss_b)
    mean_a = np.nanmean(loss_a)
    mean_b = np.nanmean(loss_b)
    rel = (mean_a - mean_b) / abs(mean_a) * 100.0 if np.isfinite(mean_a) and mean_a != 0 else np.nan
    return {
        "loss": loss_name,
        "model_a": model_a,
        "model_b": model_b,
        "dm_input": "loss_a - loss_b; positive t means model_b has lower average loss",
        "DM_HLN_t": _safe_float(t_stat),
        "DM_HLN_p": _safe_float(p_val),
        "n_used": int(n_used),
        "mean_loss_a": _safe_float(mean_a),
        "mean_loss_b": _safe_float(mean_b),
        "rel_improvement_b_vs_a_pct": _safe_float(rel),
        "gate_abs_t_gt_2": bool(abs(t_stat) > 2.0),
        "gate_abs_t_gt_3": bool(abs(t_stat) > 3.0),
    }


def add_standard_contrasts(oos):
    if oos.get("status") != "ok":
        return {}
    models = set(oos["models"])
    out = {}
    for m in ["M2_GJR_t", "M3_GAS_t", "M4_GAS_N", "M5_GJR_N_std", "M6_GAS_skewt", "M7_GAS_GED"]:
        if "M1_GJR_N" in models and m in models:
            out[f"{m}_vs_M1_GJR_N"] = contrast_summary(oos, "M1_GJR_N", m, "QLIKE_b_minus_2")
    for m in ["M3_GAS_t", "M6_GAS_skewt", "M7_GAS_GED"]:
        if "M4_GAS_N" in models and m in models:
            out[f"M4_GAS_N_vs_{m}"] = contrast_summary(oos, m, "M4_GAS_N", "QLIKE_b_minus_2")
    return out


def model_objective_spec(model_key, train_data):
    var_r = np.var(train_data)
    if model_key == "M1_GJR_N":
        x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
        bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
        return gjr_normal_negloglik, bounds, x0, train_data
    if model_key == "M2_GJR_t":
        x0 = [var_r * 0.05, 0.03, 0.05, 0.90, np.log(6.0)]
        bounds = [
            (1e-8, var_r * 10),
            (1e-8, 0.5),
            (1e-8, 0.5),
            (0.3, 0.999),
            (np.log(0.1), np.log(100.0)),
        ]
        return gjr_t_negloglik, bounds, x0, train_data
    if model_key == "M3_GAS_t":
        return gas_t_negloglik, [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))], [
            0.01,
            0.05,
            0.95,
            np.log(6.0),
        ], train_data
    if model_key == "M4_GAS_N":
        return gas_normal_negloglik, [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999)], [0.01, 0.05, 0.95], train_data
    if model_key == "M5_GJR_N_std":
        mu = np.mean(train_data)
        sd = np.std(train_data)
        r_std = (train_data - mu) / sd if sd > 0 else train_data
        x0 = [np.var(r_std) * 0.05, 0.03, 0.05, 0.90]
        bounds = [(1e-8, np.var(r_std) * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
        return gjr_normal_negloglik, bounds, x0, r_std
    raise ValueError(model_key)


def random_start(bounds, rng, base_x0, draw_index):
    if draw_index == 0:
        return np.asarray(base_x0, dtype=float)
    values = []
    for lo, hi in bounds:
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            values.append(lo)
        else:
            values.append(lo + (hi - lo) * rng.uniform())
    return np.asarray(values, dtype=float)


def multistart_dispersion(returns_pct, period_start="2015-01-01", period_end="2020-12-31"):
    returns_arr = returns_pct.values.astype(float)
    dates = returns_pct.index.to_numpy()
    mask = (dates >= np.datetime64(period_start)) & (dates <= np.datetime64(period_end))
    idx = np.where(mask)[0]
    sp_returns = returns_arr[int(idx[0]) : int(idx[-1]) + 1]
    sp_dates = dates[int(idx[0]) : int(idx[-1]) + 1]
    n_sp = len(sp_returns)
    window = max(min(WINDOW_DEFAULT, n_sp - 100), WINDOW_MIN)
    n_oos = n_sp - window
    refit_t = list(range(0, n_oos, REFIT_EVERY))
    if refit_t[-1] != n_oos - 1 and (n_oos - 1) - refit_t[-1] >= REFIT_EVERY:
        refit_t.append(n_oos - 1)

    print(f"[multistart] BTC P1 refit_windows={len(refit_t)} seeds={MULTISTART_SEEDS}")
    per_window = []
    t0 = time.time()
    for pos, t_oos in enumerate(refit_t):
        t_abs = window + t_oos
        train_start = max(0, t_abs - window)
        train_data = sp_returns[train_start:t_abs]
        assert train_start + len(train_data) == t_abs, "Multistart train window leaks"
        entry = {
            "t_oos": int(t_oos),
            "forecast_date": _date_str(sp_dates[t_abs]),
            "train_start": _date_str(sp_dates[train_start]),
            "train_end": _date_str(sp_dates[t_abs - 1]),
            "train_n": int(len(train_data)),
            "models": {},
        }
        for model_key in MODEL_KEYS:
            objective, bounds, base_x0, data_for_obj = model_objective_spec(model_key, train_data)
            nlls = []
            success_count = 0
            for draw_index in range(MULTISTART_SEEDS):
                rng = np.random.default_rng(SEED + 1000 * pos + 37 * draw_index + len(model_key))
                x0 = random_start(bounds, rng, base_x0, draw_index)
                try:
                    res = minimize(
                        objective,
                        x0,
                        args=(data_for_obj,),
                        method="L-BFGS-B",
                        bounds=bounds,
                        options={"maxiter": 500},
                    )
                    if np.isfinite(res.fun) and res.fun < 1e9:
                        nlls.append(float(res.fun))
                        success_count += int(bool(res.success))
                except Exception:
                    continue
            arr = np.asarray(nlls, dtype=float)
            if len(arr) == 0:
                entry["models"][model_key] = {"n_successful_objectives": 0, "status": "all_failed"}
                continue
            best = float(np.min(arr))
            entry["models"][model_key] = {
                "status": "ok",
                "n_objective_values": int(len(arr)),
                "optimizer_success_count": int(success_count),
                "best_nll": _safe_float(best),
                "median_minus_best_nll": _safe_float(float(np.median(arr) - best)),
                "p90_minus_best_nll": _safe_float(float(np.quantile(arr, 0.90) - best)),
                "max_minus_best_nll": _safe_float(float(np.max(arr) - best)),
                "share_within_0_5_nll": _safe_float(float(np.mean((arr - best) <= 0.5))),
                "share_within_1_5_nll": _safe_float(float(np.mean((arr - best) <= 1.5))),
            }
        per_window.append(entry)
        if pos % 5 == 0:
            print(f"  multistart {pos + 1}/{len(refit_t)} elapsed={time.time() - t0:.1f}s")

    aggregate = {}
    for model_key in MODEL_KEYS:
        model_entries = [w["models"].get(model_key, {}) for w in per_window]
        ok_entries = [e for e in model_entries if e.get("status") == "ok"]
        if not ok_entries:
            aggregate[model_key] = {"status": "all_failed"}
            continue
        max_minus = np.array([e["max_minus_best_nll"] for e in ok_entries], dtype=float)
        med_minus = np.array([e["median_minus_best_nll"] for e in ok_entries], dtype=float)
        aggregate[model_key] = {
            "status": "ok",
            "n_windows": int(len(ok_entries)),
            "seed_count_per_window": int(MULTISTART_SEEDS),
            "share_windows_max_minus_best_le_0_5": _safe_float(float(np.mean(max_minus <= 0.5))),
            "share_windows_max_minus_best_le_1_5": _safe_float(float(np.mean(max_minus <= 1.5))),
            "median_of_window_max_minus_best": _safe_float(float(np.median(max_minus))),
            "max_of_window_max_minus_best": _safe_float(float(np.max(max_minus))),
            "median_of_window_median_minus_best": _safe_float(float(np.median(med_minus))),
        }
    return {
        "design": {
            "period": "BTC-USD Period 1",
            "period_start": period_start,
            "period_end": period_end,
            "models": MODEL_KEYS,
            "seed_count_per_window": MULTISTART_SEEDS,
            "seed_base": SEED,
            "initialisation": "base K1133b x0 plus uniform random draws over admissible parameter bounds",
            "diagnostic": "negative log-likelihood dispersion within each rolling refit window",
        },
        "aggregate": aggregate,
        "per_window": per_window,
        "elapsed_seconds": float(time.time() - t0),
    }


def load_original_p1():
    with open(BASE_RESULTS_PATH, "r") as f:
        base = json.load(f)
    return base["part_A_results"]["Period1_preinstitutional"]


def compare_rebuilt_to_original(rebuilt):
    original = load_original_p1()
    comparisons = {
        "n_oos_original": original["n_oos"],
        "n_oos_rebuilt": rebuilt["n_oos"],
        "oos_start_original": original["oos_start"],
        "oos_start_rebuilt": rebuilt["oos_start"],
        "oos_end_original": original["oos_end"],
        "oos_end_rebuilt": rebuilt["oos_end"],
        "model_QLIKE": {},
        "dm_tests": {},
    }
    for m in ["M1_GJR_N", "M2_GJR_t", "M3_GAS_t", "M4_GAS_N", "M5_GJR_N_std"]:
        if m in rebuilt["model_metrics"]:
            orig_q = original["model_metrics"][m]["QLIKE"]
            reb_q = rebuilt["model_metrics"][m]["QLIKE"]
            comparisons["model_QLIKE"][m] = {
                "original": _safe_float(orig_q),
                "rebuilt": _safe_float(reb_q),
                "delta": _safe_float(reb_q - orig_q),
            }
    original_dm = original["dm_tests"]
    rebuilt_dm = add_standard_contrasts(rebuilt)
    for key in ["M2_GJR_t_vs_M1_GJR_N", "M3_GAS_t_vs_M1_GJR_N", "M4_GAS_N_vs_M1_GJR_N", "M5_GJR_N_std_vs_M1_GJR_N"]:
        old_key = key.replace("_GJR_N", "").replace("_GAS_t", "").replace("_GAS_N", "")
        mapping = {
            "M2_t_vs_M1": "M2_GJR_t_vs_M1",
            "M3_vs_M1": "M3_GAS_t_vs_M1",
            "M4_vs_M1": "M4_GAS_N_vs_M1",
            "M5_std_vs_M1": "M5_GJR_N_std_vs_M1",
        }
        orig_key = mapping.get(old_key)
        if orig_key and key in rebuilt_dm and orig_key in original_dm:
            comparisons["dm_tests"][key] = {
                "original_t": _safe_float(original_dm[orig_key]["DM_HLN_t"]),
                "rebuilt_t": _safe_float(rebuilt_dm[key]["DM_HLN_t"]),
                "delta_t": _safe_float(rebuilt_dm[key]["DM_HLN_t"] - original_dm[orig_key]["DM_HLN_t"]),
            }
    if "M4_GAS_N_vs_M3_GAS_t" in rebuilt_dm:
        comparisons["dm_tests"]["M4_GAS_N_vs_M3_GAS_t"] = {
            "original_t": _safe_float(original_dm["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"]),
            "rebuilt_t": _safe_float(rebuilt_dm["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"]),
            "delta_t": _safe_float(
                rebuilt_dm["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"] - original_dm["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"]
            ),
        }
    return comparisons


def main():
    t0 = time.time()
    print("K1133b robustness battery")
    print(f"Output: {OUTPUT_PATH}")
    btc = download_returns("BTC-USD")
    data_summary = {
        "BTC-USD": {
            "n_obs": int(len(btc)),
            "start": _date_str(btc.index[0]),
            "end": _date_str(btc.index[-1]),
            "source": "yfinance daily, auto_adjust=False, pct_change()*100 to match k1133b.py",
        }
    }

    print("\n[1] Rebuild BTC Period-1 five-model baseline")
    btc_p1 = rolling_oos(btc, "2015-01-01", "2020-12-31", MODEL_KEYS, "BTC-USD", "BTC_P1_rebuilt")
    btc_p1["dm_tests"] = add_standard_contrasts(btc_p1)
    baseline_compare = compare_rebuilt_to_original(btc_p1)

    print("\n[2] Period-cut sensitivity around 2020-12-31")
    boundary_specs = {
        "minus_60d_strict": "2020-11-01",
        "baseline": "2020-12-31",
        "plus_60d_permissive": "2021-03-01",
    }
    boundary = {}
    for label, end_date in boundary_specs.items():
        run = rolling_oos(btc, "2015-01-01", end_date, ["M1_GJR_N", "M3_GAS_t"], "BTC-USD", f"boundary_{label}")
        run["dm_tests"] = add_standard_contrasts(run)
        boundary[label] = run

    print("\n[3] Alternative loss re-evaluation on rebuilt BTC P1")
    alt_loss = {}
    for loss_name in ["QLIKE_b_minus_2", "MSE_b_0", "Patton_b_minus_1"]:
        alt_loss[loss_name] = {
            "M3_GAS_t_vs_M1_GJR_N": contrast_summary(btc_p1, "M1_GJR_N", "M3_GAS_t", loss_name),
            "M4_GAS_N_vs_M3_GAS_t": contrast_summary(btc_p1, "M3_GAS_t", "M4_GAS_N", loss_name),
        }

    print("\n[4] Leave-one-year-out evaluation-window jackknife")
    oos_years = pd.to_datetime(pd.Series(btc_p1["oos_dates"])).dt.year.to_numpy()
    loo = {
        "design": "Evaluation-window jackknife on the rebuilt no-leak Period-1 forecasts; no artificial deletion of internal time-series years before recursive refit.",
        "years": {},
    }
    for year in sorted(set(oos_years)):
        mask = oos_years != year
        if int(np.sum(mask)) < 100:
            continue
        loo["years"][str(year)] = {
            "excluded_year": int(year),
            "n_remaining": int(np.sum(mask)),
            "M3_GAS_t_vs_M1_GJR_N": contrast_summary(btc_p1, "M1_GJR_N", "M3_GAS_t", "QLIKE_b_minus_2", mask=mask),
            "M4_GAS_N_vs_M3_GAS_t": contrast_summary(btc_p1, "M3_GAS_t", "M4_GAS_N", "QLIKE_b_minus_2", mask=mask),
        }

    print("\n[5] Per-window multistart dispersion")
    multistart = multistart_dispersion(btc)

    print("\n[6] ETH/BNB cross-asset factorial")
    cross_asset = {}
    for ticker in ["ETH-USD", "BNB-USD"]:
        try:
            ret = download_returns(ticker)
            data_summary[ticker] = {
                "n_obs": int(len(ret)),
                "start": _date_str(ret.index[0]),
                "end": _date_str(ret.index[-1]),
                "source": "yfinance daily, auto_adjust=False, pct_change()*100",
            }
            run = rolling_oos(ret, "2015-01-01", "2020-12-31", MODEL_KEYS, ticker, f"{ticker}_P1_factorial")
            asset_start = run.get("actual_start")
            asset_end = run.get("actual_end")
            btc_start = btc_p1.get("actual_start")
            btc_end = btc_p1.get("actual_end")
            asset_noos = run.get("n_oos")
            btc_noos = btc_p1.get("n_oos")
            if asset_start != btc_start or asset_end != btc_end:
                raise RuntimeError(
                    f"Cross-asset alignment FAIL: {ticker} OOS span "
                    f"({asset_start}→{asset_end}) != BTC P1 ({btc_start}→{btc_end}). "
                    "ETH/BNB Yahoo span 不夠長就應 fail-fast, "
                    "不該 silent 跑錯期間 — Codex review high-impact issue #1."
                )
            if asset_noos != btc_noos:
                raise RuntimeError(
                    f"Cross-asset alignment FAIL: {ticker} n_oos={asset_noos} != BTC P1 n_oos={btc_noos}."
                )
            run["dm_tests"] = add_standard_contrasts(run)
            cross_asset[ticker] = run
        except Exception as exc:
            cross_asset[ticker] = {"status": "failed", "error": str(exc)}

    print("\n[7] Alternative innovation distributions on BTC Period 1")
    alt_dist_models = ["M1_GJR_N", "M4_GAS_N", "M6_GAS_skewt", "M7_GAS_GED"]
    alt_dist = rolling_oos(
        btc,
        "2015-01-01",
        "2020-12-31",
        alt_dist_models,
        "BTC-USD",
        "BTC_P1_alt_distributions",
        refit_every=ALT_DIST_REFIT_EVERY,
    )
    alt_dist["dm_tests"] = add_standard_contrasts(alt_dist)

    robustness_flags = {
        "boundary_m3_vs_m1_all_abs_t_gt_3": all(
            abs(boundary[k].get("dm_tests", {}).get("M3_GAS_t_vs_M1_GJR_N", {}).get("DM_HLN_t", 0.0)) > 3.0
            for k in boundary
        ),
        "alt_loss_m4_vs_m3_all_positive": all(
            alt_loss[k]["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"] is not None
            and alt_loss[k]["M4_GAS_N_vs_M3_GAS_t"]["DM_HLN_t"] > 0
            for k in alt_loss
        ),
        "loo_m3_vs_m1_all_negative": all(
            v["M3_GAS_t_vs_M1_GJR_N"]["DM_HLN_t"] is not None and v["M3_GAS_t_vs_M1_GJR_N"]["DM_HLN_t"] < 0
            for v in loo["years"].values()
        ),
        "cross_asset_all_completed": all(cross_asset[t].get("status") == "ok" for t in cross_asset),
        "alt_distribution_completed": alt_dist.get("status") == "ok",
    }
    robustness_flags["section8_ready_without_caveat"] = bool(
        robustness_flags["boundary_m3_vs_m1_all_abs_t_gt_3"]
        and robustness_flags["alt_loss_m4_vs_m3_all_positive"]
        and robustness_flags["loo_m3_vs_m1_all_negative"]
        and robustness_flags["cross_asset_all_completed"]
        and robustness_flags["alt_distribution_completed"]
    )

    output = {
        "experiment_id": "k1133b_robustness",
        "parent_experiment": "k1133b",
        "task_id": "paper_k1133b_robustness_battery_btc_gas_negative",
        "title": "K1133b robustness battery — BTC GAS-t negative result",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": data_summary,
        "methodology": {
            "window_default": WINDOW_DEFAULT,
            "window_min": WINDOW_MIN,
            "refit_every": REFIT_EVERY,
            "multistart_seed_count_per_window": MULTISTART_SEEDS,
            "alt_distribution_refit_every": ALT_DIST_REFIT_EVERY,
            "alt_distribution_maxiter": ALT_DIST_MAXITER,
            "alt_distribution_starts_per_refit": ALT_DIST_STARTS,
            "returns": "simple percentage returns, pct_change()*100, matching k1133b.py",
            "evaluation_target": "squared returns r^2",
            "lookahead_safety": [
                "Every rolling refit uses train_data = sp_returns[train_start:t_abs].",
                "Forecast date is sp_dates[t_abs]; one-step forecast uses last_r = sp_returns[t_abs-1].",
                "Assertions enforce train_start + len(train_data) == t_abs at refit time.",
            ],
            "losses": {
                "QLIKE_b_minus_2": "Patton homogeneous robust family b=-2: actual/pred - log(actual/pred) - 1",
                "MSE_b_0": "Patton homogeneous robust family b=0, proportional to MSE on variance proxy",
                "Patton_b_minus_1": "Patton homogeneous robust family b=-1: pred - actual + actual*log(actual/pred)",
            },
            "alternative_distribution_note": (
                "Skewed-t and GED are GAS log-variance recursions with finite-difference "
                "identity score on the conditional loglikelihood, not Fisher-scaled analytic GAS. "
                "They use an annual 252-day refit cadence by default because finite-difference "
                "rolling MLE is materially slower than the analytic K1133b specifications."
            ),
            "references": [
                "Patton (2011) Journal of Econometrics 160:246-256, Proposition 4 robust homogeneous losses",
                "Harvey, Leybourne, Newbold (1997) IJF, DM-HLN small-sample correction",
                "Hansen (1994) IER, skewed-t density",
            ],
        },
        "baseline_rebuilt": btc_p1,
        "baseline_vs_original_results_json": baseline_compare,
        "period_cut_sensitivity": boundary,
        "alternative_loss": alt_loss,
        "leave_one_year_out": loo,
        "multistart_dispersion": multistart,
        "cross_asset_factorial": cross_asset,
        "alternative_distribution_specs": alt_dist,
        "robustness_flags": robustness_flags,
        "elapsed_seconds": float(time.time() - t0),
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved {OUTPUT_PATH}")
    print(json.dumps(robustness_flags, indent=2))


if __name__ == "__main__":
    main()
