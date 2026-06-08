#!/usr/bin/env python3
"""
K1090b: Nested-LOOCV + Expanded Asset Pool for Cross-Asset A4f Meta-Regression

Follow-up to K1090 and the Codex paper review on mile_f8af30d0. Two structural
issues are addressed here:

1. Leakage-safe evaluation:
   - imputation, standardisation, and LASSO feature selection are all fit
     inside each outer fold only;
   - hyperparameter tuning is performed by inner LOOCV on the outer-train set.
2. Expanded labeled pool:
   - reuse K1090's 12 assets and K1091's 4 validated assets;
   - add 4 new A4f-vs-GJR labels computed in this script to reach N=20.

Outputs:
  - k1090b_results.json
  - k1090b_nested_loocv.png
  - k1090b_feature_selection.png
  - k1090b_training_dm_t.png
"""

from __future__ import annotations

import json
import math
import pathlib
import time
import warnings
from collections import Counter
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from numba import njit
from scipy import optimize, stats
from sklearn.linear_model import Lasso, Ridge
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
np.random.seed(42)

HERE = pathlib.Path(__file__).resolve().parent
OUT_JSON = HERE / "k1090b_results.json"
CACHE_DIR = HERE / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_START = "2018-01-01"
FEATURE_END = "2024-12-31"
DATA_END = "2026-06-08"
SEED = 42

FEATURE_COLS = [
    "class_equity",
    "class_commodity",
    "class_bond",
    "class_crypto",
    "currency_usd",
    "log_n_constituents",
    "hhi",
    "log_avg_dollar_volume",
    "corr_ret_vix",
    "corr_r2_vix2",
    "annualized_vol",
    "r2_acf1",
]

BASE_TRAINING = [
    # ticker, dm_t, class, currency, n_constituents, hhi, source K
    ("SPY", 7.92, "equity_us_large", "USD", 500, 0.07, "K1085"),
    ("QQQ", 5.99, "equity_us_tech", "USD", 100, 0.12, "K1085"),
    ("EEM", 5.25, "equity_em_basket", "USD", 1100, 0.05, "K1086"),
    ("IWM", 4.80, "equity_us_small", "USD", 2000, 0.004, "K1085"),
    ("GLD", 4.46, "commodity_gold", "USD", 1, 1.00, "K1088"),
    ("USO", 4.48, "commodity_oil", "USD", 1, 1.00, "K1088"),
    ("FXI", 3.61, "equity_china", "USD", 50, 0.09, "K1086"),
    ("EWZ", 2.33, "equity_brazil", "USD", 80, 0.16, "K1086"),
    ("EWT", 2.26, "equity_taiwan_usd", "USD", 90, 0.25, "K1086"),
    ("TLT", 1.43, "bonds_long_dur", "USD", 30, 0.20, "K1087"),
    ("BTC-USD", 1.13, "crypto", "USD", 1, 1.00, "K1089"),
    ("0050.TW", -0.49, "equity_taiwan_twd", "TWD", 50, 0.50, "K1088"),
]

K1091_ASSETS = [
    ("VGK", "equity_europe", "USD", 1200, 0.04, "K1091"),
    ("EWJ", "equity_japan", "USD", 220, 0.05, "K1091"),
    ("CPER", "commodity_copper", "USD", 1, 1.00, "K1091"),
    ("SLV", "commodity_silver", "USD", 1, 1.00, "K1091"),
]

NEW_LABEL_ASSETS = {
    "IEF": {
        "data_start": "2002-01-01",
        "window": 2000,
        "oos_start": "2022-01-03",
        "refit_every": 63,
        "class_label": "bonds_medium_dur",
        "currency": "USD",
        "n_constituents": 10,
        "hhi": 0.18,
    },
    "ETH-USD": {
        "data_start": "2017-11-01",
        "window": 1500,
        "oos_start": "2022-01-03",
        "refit_every": 63,
        "class_label": "crypto",
        "currency": "USD",
        "n_constituents": 1,
        "hhi": 1.00,
    },
    "AAPL": {
        "data_start": "2014-01-01",
        "window": 2000,
        "oos_start": "2022-01-03",
        "refit_every": 63,
        "class_label": "equity_us_single",
        "currency": "USD",
        "n_constituents": 1,
        "hhi": 1.00,
    },
    "NVDA": {
        "data_start": "2014-01-01",
        "window": 2000,
        "oos_start": "2022-01-03",
        "refit_every": 63,
        "class_label": "equity_us_single",
        "currency": "USD",
        "n_constituents": 1,
        "hhi": 1.00,
    },
}

RIDGE_ALPHA_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]
LASSO_ALPHA_GRID = [0.01, 0.03, 0.1, 0.3, 1.0]


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


def fit_gjr(returns: np.ndarray):
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
    for start in starts:
        try:
            res = optimize.minimize(
                gjr_loglik, start, args=(returns,), method="L-BFGS-B", bounds=bounds
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = bool(res.success)
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params: np.ndarray, h_prev: float, r_prev: float) -> float:
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f_vix(returns: np.ndarray, vix_vals: np.ndarray):
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = vix_vals[0]
    x_lag[1:] = vix_vals[:-1]
    x_lag_sq = x_lag**2

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
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)
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
    for start in starts:
        try:
            res = optimize.minimize(
                neg_loglik, start, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = bool(res.success)
        except Exception:
            continue
    return best_params, converged


def init_a4f_state(train_ret: np.ndarray, vix_train: np.ndarray, params: np.ndarray) -> float:
    theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params
    x_lag = np.empty(len(vix_train))
    x_lag[0] = vix_train[0]
    x_lag[1:] = vix_train[:-1]
    tau = np.maximum(theta0 + theta1 * x_lag**2, 1e-16)
    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / (1.0 - persist)
    for i in range(1, len(train_ret)):
        u_prev = train_ret[i - 1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
        g = max(g, 1e-10)
    return g


def qlike_loss(fc: np.ndarray, r2_vals: np.ndarray) -> np.ndarray:
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array: np.ndarray):
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T ** (1 / 3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        weight = 1.0 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2.0 * weight * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2.0 * (1.0 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr: np.ndarray, n_boot: int = 1000, seed: int = SEED):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    block_len = max(1, int(n ** (1 / 3)))
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 2))
        blocks = [arr[s : s + block_len] for s in starts if s + block_len <= n]
        sample = np.concatenate(blocks)[:n]
        boot_means[i] = np.mean(sample)
    return (
        float(np.percentile(boot_means, 2.5)),
        float(np.percentile(boot_means, 97.5)),
    )


def evaluate_pair(fc_base: np.ndarray, fc_alt: np.ndarray, r2_vals: np.ndarray):
    valid = (~np.isnan(fc_base)) & (fc_base > 0) & (~np.isnan(fc_alt)) & (fc_alt > 0)
    if valid.sum() < 30:
        return None
    b = fc_base[valid]
    a = fc_alt[valid]
    r2 = r2_vals[valid]
    ql_b = qlike_loss(b, r2)
    ql_a = qlike_loss(a, r2)
    loss_diff = ql_b - ql_a
    dm_t, dm_p, n = hac_dm_test(loss_diff)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(loss_diff)
    rho_b, _ = stats.spearmanr(b, r2)
    rho_a, _ = stats.spearmanr(a, r2)
    return {
        "n": int(n),
        "qlike_base": float(np.mean(ql_b)),
        "qlike_a4f_vix": float(np.mean(ql_a)),
        "qlike_diff_pct": float((np.mean(ql_a) - np.mean(ql_b)) / abs(np.mean(ql_b)) * 100.0),
        "dm_t": float(dm_t) if np.isfinite(dm_t) else None,
        "dm_p": float(dm_p) if np.isfinite(dm_p) else None,
        "harvey_pass": bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        "spearman_base": float(rho_b),
        "spearman_a4f_vix": float(rho_a),
        "bootstrap_ci_95_qlike_diff": [ci_lo, ci_hi],
    }


def _cache_path(ticker: str) -> pathlib.Path:
    return CACHE_DIR / f"{ticker.replace('/', '_').replace('^', '')}.csv"


def _fallback_sources(ticker: str) -> list[pathlib.Path]:
    normalized = ticker.replace("^", "")
    candidates = [
        HERE / "data" / f"{normalized}.csv",
        HERE.parent / "k1090" / "data" / f"{ticker}.csv",
        HERE.parent / "k1090" / "data" / f"{normalized}.csv",
        HERE.parent / "k1263" / "data" / f"{normalized}.csv",
        HERE.parent / "k1147" / "data" / f"{normalized}.parquet",
        HERE.parent / "k1151" / "data" / f"{normalized}.parquet",
    ]
    return [path for path in candidates if path.exists()]


def _load_local_price(path: pathlib.Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.set_index("Date")
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    df = pd.read_csv(path)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    else:
        df.index = pd.to_datetime(df.index)
    return df.sort_index()


def load_price(ticker: str, start: str, end: str) -> pd.DataFrame:
    cache = _cache_path(ticker)
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        if not df.empty and df.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=10):
            return df
    for fallback in _fallback_sources(ticker):
        df = _load_local_price(fallback)
        if not df.empty:
            if df.index.max() >= pd.Timestamp(start):
                trimmed = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))].copy()
                if not trimmed.empty:
                    if cache != fallback and cache.suffix == ".csv":
                        trimmed.to_csv(cache)
                    return trimmed
    try:
        raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.to_csv(cache)
        return raw
    except Exception:
        return pd.DataFrame()


def load_asset_for_oos(ticker: str, data_start: str) -> pd.DataFrame:
    raw = load_price(ticker, data_start, DATA_END)
    if raw.empty:
        raise RuntimeError(f"No data for {ticker}")
    price_col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    price = raw[price_col].astype(float)
    log_ret = np.log(price / price.shift(1))

    vix_raw = load_price("^VIX", data_start, DATA_END)
    if vix_raw.empty:
        raise RuntimeError("No VIX data")
    vix_close = vix_raw["Close"].astype(float)

    df = pd.DataFrame({"price": price, "log_ret": log_ret}).dropna()
    df["VIX"] = vix_close.reindex(df.index).ffill()
    return df.dropna(subset=["VIX"])


def run_a4f_label(ticker: str, cfg: dict) -> dict:
    print(f"[label] running {ticker} ...")
    df = load_asset_for_oos(ticker, cfg["data_start"])
    ret = df["log_ret"].values.astype(float)
    vix = df["VIX"].values.astype(float)
    dates = df.index
    r2 = ret**2

    oos_indices = np.where(dates >= cfg["oos_start"])[0]
    if len(oos_indices) == 0:
        raise RuntimeError(f"{ticker}: no OOS observations")
    first_oos = int(oos_indices[0])
    if first_oos < cfg["window"]:
        raise RuntimeError(f"{ticker}: first OOS {first_oos} < window {cfg['window']}")

    n_oos = len(oos_indices)
    gjr_fc = np.full(n_oos, np.nan)
    a4f_fc = np.full(n_oos, np.nan)
    refit_log = []
    gjr_params = gjr_h = a4f_params = a4f_g = None

    for t_idx, abs_idx in enumerate(oos_indices):
        if t_idx == 0 or t_idx % cfg["refit_every"] == 0:
            train_start = max(0, abs_idx - cfg["window"])
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            gjr_new, gjr_conv = fit_gjr(train_ret)
            if gjr_new is not None:
                gjr_params = gjr_new
                gjr_h = np.var(train_ret[: min(250, len(train_ret))])
                for i in range(1, len(train_ret)):
                    gjr_h = gjr_forecast_1step(gjr_params, gjr_h, train_ret[i - 1])
            else:
                gjr_conv = False

            a4f_new, a4f_conv = fit_a4f_vix(train_ret, train_vix)
            if a4f_new is not None:
                a4f_params = a4f_new
                a4f_g = init_a4f_state(train_ret, train_vix, a4f_params)
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

            if gjr_params is None or a4f_params is None or gjr_h is None or a4f_g is None:
                raise RuntimeError(f"{ticker}: initial model fit failed at {dates[abs_idx].date()}")

        r_prev = ret[abs_idx - 1]
        gjr_h = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_fc[t_idx] = gjr_h

        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        tau_t = max(theta0 + theta1 * (vix[abs_idx - 1] ** 2), 1e-16)
        u_prev = r_prev / math.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        a4f_g = max(omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g, 1e-10)
        a4f_fc[t_idx] = tau_t * a4f_g

    evaluation = evaluate_pair(gjr_fc, a4f_fc, r2[oos_indices])
    if evaluation is None:
        raise RuntimeError(f"{ticker}: evaluation returned None")

    return {
        "ticker": ticker,
        "class_label": cfg["class_label"],
        "currency": cfg["currency"],
        "n_constituents": cfg["n_constituents"],
        "hhi": cfg["hhi"],
        "data_start": str(df.index[0].date()),
        "data_end": str(df.index[-1].date()),
        "window": cfg["window"],
        "oos_start": cfg["oos_start"],
        "oos_end": str(dates[oos_indices[-1]].date()),
        "n_total": int(len(df)),
        "n_oos": int(evaluation["n"]),
        "full_oos": evaluation,
        "dm_t": float(evaluation["dm_t"]),
        "source_K": "K1090b",
        "refit_log_head": refit_log[:5],
    }


def class_dummies(cls: str) -> dict:
    return {
        "class_equity": int("equity" in cls),
        "class_commodity": int("commodity" in cls),
        "class_bond": int("bond" in cls),
        "class_crypto": int("crypto" in cls),
    }


def currency_dummy(cur: str) -> int:
    return int(cur.upper() == "USD")


def build_features(
    ticker: str,
    cls: str,
    cur: str,
    n_const: int,
    hhi: float,
    vix: pd.Series,
) -> dict:
    px = load_price(ticker, FEATURE_START, FEATURE_END)
    feats = {
        "ticker": ticker,
        "class_label": cls,
        "currency": cur,
        "n_constituents": int(n_const),
        "hhi": float(hhi),
        "log_n_constituents": float(np.log(max(n_const, 1))),
    }
    feats.update(class_dummies(cls))
    feats["currency_usd"] = currency_dummy(cur)

    if px.empty:
        for key in (
            "log_avg_dollar_volume",
            "corr_ret_vix",
            "corr_r2_vix2",
            "annualized_vol",
            "r2_acf1",
        ):
            feats[key] = np.nan
        return feats

    close_col = "Adj Close" if "Adj Close" in px.columns else "Close"
    close = px[close_col].astype(float).dropna()
    vol_col = "Volume" if "Volume" in px.columns else None
    if vol_col is not None:
        adv = (close * px[vol_col].astype(float)).replace([np.inf, -np.inf], np.nan).dropna().mean()
    else:
        adv = np.nan

    ret = np.log(close).diff().dropna()
    r2 = ret**2
    vix_aligned = vix.reindex(ret.index).ffill()
    vix_change = vix_aligned.diff()

    corr_ret_vix = ret.corr(vix_change) if vix_change.notna().sum() > 50 else np.nan
    corr_r2_vix2 = r2.corr(vix_aligned**2) if vix_aligned.notna().sum() > 50 else np.nan
    ann_vol = float(ret.std() * np.sqrt(252)) if len(ret) > 50 else np.nan
    r2_acf1 = float(r2.autocorr(lag=1)) if len(r2) > 50 else np.nan

    feats.update(
        {
            "log_avg_dollar_volume": float(np.log(adv)) if adv and adv > 0 else np.nan,
            "corr_ret_vix": float(corr_ret_vix) if not np.isnan(corr_ret_vix) else np.nan,
            "corr_r2_vix2": float(corr_r2_vix2) if not np.isnan(corr_r2_vix2) else np.nan,
            "annualized_vol": ann_vol,
            "r2_acf1": r2_acf1,
        }
    )
    return feats


def transform_fold(X_train_df: pd.DataFrame, X_test_df: pd.DataFrame):
    means = X_train_df.mean(numeric_only=True)
    X_train_imp = X_train_df.fillna(means)
    X_test_imp = X_test_df.fillna(means)
    scaler = StandardScaler()
    X_train_std = scaler.fit_transform(X_train_imp.values)
    X_test_std = scaler.transform(X_test_imp.values)
    return X_train_imp, X_test_imp, X_train_std, X_test_std, means


def nested_ridge_predict(X_df: pd.DataFrame, y: np.ndarray):
    n = len(y)
    preds = np.zeros(n)
    chosen_alphas = []
    for i in range(n):
        outer_mask = np.arange(n) != i
        X_outer = X_df.iloc[outer_mask].reset_index(drop=True)
        y_outer = y[outer_mask]
        best_alpha = None
        best_rmse = np.inf
        for alpha in RIDGE_ALPHA_GRID:
            inner_preds = np.zeros(len(y_outer))
            for j in range(len(y_outer)):
                inner_mask = np.arange(len(y_outer)) != j
                X_in_train = X_outer.iloc[inner_mask]
                X_in_test = X_outer.iloc[[j]]
                Xtr_imp, Xte_imp, Xtr_std, Xte_std, _ = transform_fold(X_in_train, X_in_test)
                model = Ridge(alpha=alpha, random_state=SEED)
                model.fit(Xtr_std, y_outer[inner_mask])
                inner_preds[j] = model.predict(Xte_std)[0]
            rmse = float(np.sqrt(np.mean((inner_preds - y_outer) ** 2)))
            if rmse < best_rmse:
                best_rmse = rmse
                best_alpha = alpha

        Xtr_imp, Xte_imp, Xtr_std, Xte_std, _ = transform_fold(X_outer, X_df.iloc[[i]])
        model = Ridge(alpha=best_alpha, random_state=SEED)
        model.fit(Xtr_std, y_outer)
        preds[i] = model.predict(Xte_std)[0]
        chosen_alphas.append(float(best_alpha))

    rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
    r2 = float(1.0 - np.sum((preds - y) ** 2) / np.sum((y - y.mean()) ** 2))
    return preds, rmse, r2, chosen_alphas


def nested_compact_predict(X_df: pd.DataFrame, y: np.ndarray):
    n = len(y)
    preds = np.zeros(n)
    selected_sets = []
    selected_coefs = []
    chosen_alphas = []
    for i in range(n):
        outer_mask = np.arange(n) != i
        X_outer = X_df.iloc[outer_mask].reset_index(drop=True)
        y_outer = y[outer_mask]

        best_alpha = None
        best_rmse = np.inf
        for alpha in LASSO_ALPHA_GRID:
            inner_preds = np.zeros(len(y_outer))
            for j in range(len(y_outer)):
                inner_mask = np.arange(len(y_outer)) != j
                X_in_train = X_outer.iloc[inner_mask]
                X_in_test = X_outer.iloc[[j]]
                _, _, Xtr_std, Xte_std, _ = transform_fold(X_in_train, X_in_test)
                model = Lasso(alpha=alpha, random_state=SEED, max_iter=20000)
                model.fit(Xtr_std, y_outer[inner_mask])
                inner_preds[j] = model.predict(Xte_std)[0]
            rmse = float(np.sqrt(np.mean((inner_preds - y_outer) ** 2)))
            if rmse < best_rmse:
                best_rmse = rmse
                best_alpha = alpha

        Xtr_imp, Xte_imp, Xtr_std, Xte_std, _ = transform_fold(X_outer, X_df.iloc[[i]])
        lasso = Lasso(alpha=best_alpha, random_state=SEED, max_iter=20000)
        lasso.fit(Xtr_std, y_outer)
        feat_names = [name for name, coef in zip(FEATURE_COLS, lasso.coef_) if abs(coef) > 1e-8]
        if not feat_names:
            feat_names = ["currency_usd", "corr_ret_vix"]
        selected_sets.append(tuple(feat_names))
        chosen_alphas.append(float(best_alpha))

        Xc_train = sm.add_constant(Xtr_imp[feat_names].values, has_constant="add")
        fit = sm.OLS(y_outer, Xc_train).fit()
        Xc_test = sm.add_constant(Xte_imp[feat_names].values, has_constant="add")
        preds[i] = float(fit.predict(Xc_test)[0])
        selected_coefs.append(
            {
                "features": feat_names,
                "params": {name: float(val) for name, val in zip(["const"] + feat_names, fit.params)},
            }
        )

    rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
    r2 = float(1.0 - np.sum((preds - y) ** 2) / np.sum((y - y.mean()) ** 2))
    return preds, rmse, r2, selected_sets, chosen_alphas, selected_coefs


def bootstrap_modal_ols(X_df: pd.DataFrame, y: np.ndarray, modal_features: list[str]):
    rng = np.random.default_rng(SEED)
    X_fixed = sm.add_constant(X_df[modal_features].values, has_constant="add")
    fit = sm.OLS(y, X_fixed).fit()
    B = 5000
    coefs = np.zeros((B, X_fixed.shape[1]))
    n = len(y)
    for b in range(B):
        idx = rng.integers(0, n, n)
        bfit = sm.OLS(y[idx], X_fixed[idx]).fit()
        coefs[b] = bfit.params
    ci_lo = np.percentile(coefs, 2.5, axis=0)
    ci_hi = np.percentile(coefs, 97.5, axis=0)
    table = []
    for i, name in enumerate(["const"] + modal_features):
        table.append(
            {
                "feature": name,
                "coef": float(fit.params[i]),
                "se": float(fit.bse[i]),
                "t": float(fit.tvalues[i]),
                "p": float(fit.pvalues[i]),
                "boot_ci95_low": float(ci_lo[i]),
                "boot_ci95_hi": float(ci_hi[i]),
            }
        )
    return fit, table


def load_k1091_labels():
    path = HERE.parent / "k1091" / "k1091_results.json"
    data = json.loads(path.read_text())
    asset_results = data["asset_results"]
    labels = {}
    for ticker, cls, cur, n_const, hhi, source in K1091_ASSETS:
        realized = asset_results[ticker]["full_oos"]["dm_t"]
        labels[ticker] = {
            "ticker": ticker,
            "dm_t": float(realized),
            "class_label": cls,
            "currency": cur,
            "n_constituents": int(n_const),
            "hhi": float(hhi),
            "source_K": source,
            "n_oos": int(asset_results[ticker]["full_oos"]["n"]),
            "qlike_diff_pct": float(asset_results[ticker]["full_oos"]["qlike_diff_pct"]),
        }
    return labels


def build_training_rows(vix: pd.Series, extra_labels: dict[str, dict]):
    rows = []
    for ticker, dm_t, cls, cur, n_const, hhi, src in BASE_TRAINING:
        feats = build_features(ticker, cls, cur, n_const, hhi, vix)
        feats["dm_t"] = float(dm_t)
        feats["source_K"] = src
        feats["pass"] = int(dm_t >= 3.0)
        rows.append(feats)

    for label in load_k1091_labels().values():
        feats = build_features(
            label["ticker"],
            label["class_label"],
            label["currency"],
            label["n_constituents"],
            label["hhi"],
            vix,
        )
        feats["dm_t"] = float(label["dm_t"])
        feats["source_K"] = label["source_K"]
        feats["pass"] = int(label["dm_t"] >= 3.0)
        rows.append(feats)

    for label in extra_labels.values():
        feats = build_features(
            label["ticker"],
            label["class_label"],
            label["currency"],
            label["n_constituents"],
            label["hhi"],
            vix,
        )
        feats["dm_t"] = float(label["dm_t"])
        feats["source_K"] = label["source_K"]
        feats["pass"] = int(label["dm_t"] >= 3.0)
        rows.append(feats)

    return pd.DataFrame(rows)


def make_figures(df_train: pd.DataFrame, y: np.ndarray, ridge_preds: np.ndarray, compact_preds: np.ndarray, selected_sets: list[tuple[str, ...]]):
    order = np.argsort(y)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.barh(np.arange(len(y)), y[order], color=["#1f77b4" if val >= 3 else "#b0b0b0" for val in y[order]])
    ax.axvline(3.0, color="crimson", linestyle="--", linewidth=1)
    ax.set_yticks(np.arange(len(y)))
    ax.set_yticklabels(df_train.iloc[order]["ticker"])
    ax.set_xlabel("A4f vs GJR DM t")
    ax.set_title("K1090b training asset labels (N=20)")
    fig.tight_layout()
    fig.savefig(HERE / "k1090b_training_dm_t.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(y, ridge_preds, label="Nested Ridge", s=55, alpha=0.85)
    ax.scatter(y, compact_preds, label="Nested Compact OLS", s=55, alpha=0.85)
    bound_min = min(float(y.min()), float(ridge_preds.min()), float(compact_preds.min())) - 0.5
    bound_max = max(float(y.max()), float(ridge_preds.max()), float(compact_preds.max())) + 0.5
    ax.plot([bound_min, bound_max], [bound_min, bound_max], "--", color="grey")
    ax.axhline(3.0, color="crimson", linestyle=":", linewidth=1)
    ax.axvline(3.0, color="crimson", linestyle=":", linewidth=1)
    for _, row in df_train.iterrows():
        ax.text(row["dm_t"] + 0.03, compact_preds[df_train.index.get_loc(row.name)] + 0.03, row["ticker"], fontsize=8)
    ax.set_xlim(bound_min, bound_max)
    ax.set_ylim(bound_min, bound_max)
    ax.set_xlabel("Actual DM t")
    ax.set_ylabel("Nested-LOOCV predicted DM t")
    ax.set_title("K1090b nested LOOCV predictions vs actual")
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "k1090b_nested_loocv.png", dpi=140)
    plt.close(fig)

    freq = Counter(selected_sets)
    labels = [" + ".join(item[0]) for item in freq.most_common()]
    values = [item[1] for item in freq.most_common()]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(range(len(values)), values, color="#2ca02c")
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_ylabel("Outer-fold count")
    ax.set_title("K1090b nested compact model feature-set frequency")
    fig.tight_layout()
    fig.savefig(HERE / "k1090b_feature_selection.png", dpi=140)
    plt.close(fig)


def main():
    start_time = time.time()
    print("[K1090b] expanding labeled pool ...")

    extra_labels = {}
    for ticker, cfg in NEW_LABEL_ASSETS.items():
        result = run_a4f_label(ticker, cfg)
        extra_labels[ticker] = {
            "ticker": ticker,
            "dm_t": float(result["dm_t"]),
            "class_label": cfg["class_label"],
            "currency": cfg["currency"],
            "n_constituents": cfg["n_constituents"],
            "hhi": cfg["hhi"],
            "source_K": "K1090b",
            "oos_eval": result,
        }

    vix_px = load_price("^VIX", FEATURE_START, FEATURE_END)
    if vix_px.empty:
        raise RuntimeError("Unable to load VIX for feature extraction.")
    vix = vix_px["Close"].astype(float)

    df_train = build_training_rows(vix, extra_labels)
    X_df = df_train[FEATURE_COLS].copy()
    y = df_train["dm_t"].values.astype(float)

    print(f"[K1090b] nested ridge on N={len(y)} assets ...")
    ridge_preds, ridge_rmse, ridge_r2, ridge_alphas = nested_ridge_predict(X_df, y)

    print(f"[K1090b] nested compact OLS on N={len(y)} assets ...")
    compact_preds, compact_rmse, compact_r2, selected_sets, compact_alphas, selected_coefs = nested_compact_predict(X_df, y)

    valid_full_means = X_df.mean(numeric_only=True)
    X_imp_full = X_df.fillna(valid_full_means)
    selection_counts = Counter(selected_sets)
    modal_features = list(selection_counts.most_common(1)[0][0])
    modal_fit, modal_coef_table = bootstrap_modal_ols(X_imp_full, y, modal_features)

    make_figures(df_train, y, ridge_preds, compact_preds, selected_sets)

    results = {
        "meta": {
            "experiment_id": "K1090b",
            "title": "Nested LOOCV + expanded asset pool for cross-asset A4f meta-regression",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "random_seed": SEED,
            "feature_window": f"{FEATURE_START} .. {FEATURE_END}",
            "n_train": int(len(df_train)),
            "n_base_k1090": len(BASE_TRAINING),
            "n_k1091_reuse": len(K1091_ASSETS),
            "n_new_labels": len(extra_labels),
            "feature_cols": FEATURE_COLS,
            "leakage_fixes": [
                "imputation fit inside each outer fold",
                "StandardScaler fit inside each outer fold",
                "LASSO alpha selected by inner LOOCV on outer-train only",
                "feature selection performed on outer-train only",
            ],
            "runtime_seconds": round(time.time() - start_time, 2),
        },
        "training_assets": df_train.to_dict(orient="records"),
        "new_label_runs": {k: v["oos_eval"] for k, v in extra_labels.items()},
        "nested_ridge": {
            "loocv_rmse": ridge_rmse,
            "loocv_r2": ridge_r2,
            "chosen_alphas": ridge_alphas,
            "alpha_median": float(np.median(ridge_alphas)),
            "predictions": [
                {"ticker": t, "actual": float(a), "pred": float(p)}
                for t, a, p in zip(df_train["ticker"], y, ridge_preds)
            ],
        },
        "nested_compact": {
            "loocv_rmse": compact_rmse,
            "loocv_r2": compact_r2,
            "chosen_lasso_alphas": compact_alphas,
            "selected_feature_sets": [
                {"ticker": t, "features": list(fs)}
                for t, fs in zip(df_train["ticker"], selected_sets)
            ],
            "selection_frequency": [
                {"features": list(fs), "count": int(count)}
                for fs, count in selection_counts.most_common()
            ],
            "modal_feature_set": modal_features,
            "predictions": [
                {"ticker": t, "actual": float(a), "pred": float(p)}
                for t, a, p in zip(df_train["ticker"], y, compact_preds)
            ],
        },
        "modal_full_sample_ols": {
            "features": modal_features,
            "r2": float(modal_fit.rsquared),
            "adj_r2": float(modal_fit.rsquared_adj),
            "coefficients": modal_coef_table,
        },
        "comparison_vs_k1090": {
            "k1090_compact_loocv_r2": 0.2574861910398165,
            "k1090_compact_loocv_rmse": 1.942752136650331,
            "k1090_train_n": 12,
            "k1090b_nested_compact_loocv_r2": compact_r2,
            "k1090b_nested_compact_loocv_rmse": compact_rmse,
            "k1090b_nested_ridge_loocv_r2": ridge_r2,
            "k1090b_nested_ridge_loocv_rmse": ridge_rmse,
        },
        "references": [
            "Engle, Ghysels, Sohn (2013) RES 95(3):776-797",
            "Patton (2011) J Econometrics 160:246-256",
            "Varma and Simon (2006) BMC Bioinformatics 7:91",
            "Cawley and Talbot (2010) JMLR 11:2079-2107",
            "K1090 and K1091 (VolPred internal upstream experiments)",
        ],
    }
    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"[K1090b] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
