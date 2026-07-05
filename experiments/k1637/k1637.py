#!/usr/bin/env python3
"""K1637: Markov-switching multifractal volatility forecasting.

Research question
-----------------
Can a Calvet-Fisher/Lux-style Markov-switching multifractal (MSM)
volatility mechanism beat simpler HAR / fractional-persistence /
two-state Markov-volatility baselines in one-day-ahead close-to-close
variance forecasting?

Design guardrails
-----------------
* All models forecast return variance for day t using information available
  through day t-1. The code keeps explicit target alignment and includes
  shifted HAR features.
* Parameters are estimated only on the initial in-sample window. OOS filtering
  updates latent probabilities sequentially after observing each return.
* 0050.TW prices are passed through volpred.utils.clean_tw50_data.
* Pooled inference aggregates loss differentials by date before DM tests
  (K1355 rule), not by stacked asset-day iid.
* Random procedures use seed=42.
"""
from __future__ import annotations

import itertools
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.utils import clean_tw50_data  # noqa: E402


EXPERIMENT_ID = "k1637"
SEED = 42
PRICE_DB = ROOT / "data/cache/price_cache.db"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "k1637_results.json"

ASSETS = ["SPY", "QQQ", "GLD", "TLT", "0050.TW"]
START_DATE = "2016-01-01"
END_DATE = "2026-07-03"
MIN_TRAIN = 750
REFIT_EVERY = 63
HARVEY_T = 3.0
EPS = 1e-10
MSM_K = 4
FI_MAX_LAG = 252
FI_D_GRID = np.round(np.arange(0.05, 0.51, 0.05), 2)

np.random.seed(SEED)


def _jsonify(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    return obj


def qlike_pointwise(actual: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Patton QLIKE loss: actual/pred - log(actual/pred) - 1."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    mask = np.isfinite(a) & np.isfinite(p) & (a > 0) & (p > 0)
    out = np.full_like(a, np.nan, dtype=float)
    ratio = np.clip(a[mask], EPS, None) / np.clip(p[mask], EPS, None)
    out[mask] = ratio - np.log(ratio) - 1.0
    return out


def dm_hac(loss_a: np.ndarray, loss_b: np.ndarray, max_lag: int = 5) -> dict:
    """Newey-West DM test on loss_a - loss_b; negative means a is better."""
    a = np.asarray(loss_a, dtype=float)
    b = np.asarray(loss_b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    d = a[mask] - b[mask]
    n = len(d)
    if n < 30:
        return {"n": int(n), "mean_diff": None, "t_stat": None, "p_value": None, "harvey_pass": False}
    d = d - np.nanmean(d)
    mean_diff = float(np.nanmean(a[mask] - b[mask]))
    gamma0 = float(np.dot(d, d) / n)
    lrv = gamma0
    lag = int(min(max_lag, n - 1))
    for k in range(1, lag + 1):
        cov = float(np.dot(d[k:], d[:-k]) / n)
        lrv += 2.0 * (1.0 - k / (lag + 1.0)) * cov
    if lrv <= 0 or not np.isfinite(lrv):
        return {"n": int(n), "mean_diff": mean_diff, "t_stat": 0.0, "p_value": 1.0, "harvey_pass": False}
    se = math.sqrt(lrv / n)
    t_stat = mean_diff / se if se > 0 else 0.0
    p = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
    return {
        "n": int(n),
        "mean_diff": mean_diff,
        "t_stat": float(t_stat),
        "p_value": float(p),
        "hac_lag": int(lag),
        "harvey_pass": bool(abs(t_stat) > HARVEY_T),
    }


def load_price_panel() -> tuple[dict[str, pd.Series], dict]:
    if not PRICE_DB.exists():
        raise FileNotFoundError(f"missing price cache: {PRICE_DB}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PRICE_DB)
    prices: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    for ticker in ASSETS:
        df = pd.read_sql_query(
            """
            select date, adj_close, close
            from price_data
            where ticker = ? and date >= ? and date <= ?
            order by date
            """,
            con,
            params=(ticker, START_DATE, END_DATE),
            parse_dates=["date"],
        )
        if df.empty:
            raise RuntimeError(f"no price rows for {ticker} in {PRICE_DB}")
        df = df.set_index("date").sort_index()
        price = df["adj_close"].fillna(df["close"]).astype(float)
        if ticker == "0050.TW":
            price, _ = clean_tw50_data(price)
        price = price.dropna()
        prices[ticker] = price
        price.to_csv(DATA_DIR / f"{ticker.replace('.', '_')}_adj_close.csv", header=["adj_close"])
        meta[ticker] = {
            "source": str(PRICE_DB.relative_to(ROOT)),
            "start": str(price.index.min().date()),
            "end": str(price.index.max().date()),
            "n_prices": int(len(price)),
            "clean_tw50_data": bool(ticker == "0050.TW"),
        }
    con.close()
    return prices, meta


def build_returns(price: pd.Series) -> pd.DataFrame:
    ret = np.log(price / price.shift(1)).dropna()
    # Conservative ETF sanity filter; no rows should be close to this bound in
    # clean samples, but it protects against split/cache artifacts.
    ret = ret[ret.abs() < 0.40]
    var = (ret ** 2).clip(lower=EPS)
    return pd.DataFrame({"ret": ret, "var": var, "log_var": np.log(var)})


def har_forecast(panel: pd.DataFrame) -> pd.Series:
    y = panel["log_var"].copy()
    x = pd.DataFrame(index=panel.index)
    x["const"] = 1.0
    # Explicit shift(1): forecast for day t only uses volatility through t-1.
    x["d1"] = y.shift(1)
    x["w5"] = y.shift(1).rolling(5, min_periods=5).mean()
    x["m22"] = y.shift(1).rolling(22, min_periods=22).mean()
    pred = pd.Series(np.nan, index=panel.index, name="HAR")
    beta = None
    smear = 0.0
    for i in range(MIN_TRAIN, len(panel)):
        if beta is None or (i - MIN_TRAIN) % REFIT_EVERY == 0:
            train = pd.concat([y.rename("target"), x], axis=1).iloc[:i].dropna()
            xx = train[["const", "d1", "w5", "m22"]].to_numpy(float)
            yy = train["target"].to_numpy(float)
            beta, *_ = np.linalg.lstsq(xx, yy, rcond=None)
            resid = yy - xx @ beta
            smear = float(np.nanvar(resid) / 2.0)
        row = x.iloc[i][["const", "d1", "w5", "m22"]]
        if np.isfinite(row).all():
            pred.iloc[i] = float(np.exp(float(row.to_numpy(float) @ beta) + smear))
    return pred.clip(lower=EPS)


def constant_forecast(panel: pd.DataFrame) -> pd.Series:
    """Expanding mean variance baseline using only observations before day t."""
    var = panel["var"].to_numpy(float)
    pred = pd.Series(np.nan, index=panel.index, name="CONST")
    current = np.nanmean(var[:MIN_TRAIN])
    for i in range(MIN_TRAIN, len(panel)):
        if (i - MIN_TRAIN) % REFIT_EVERY == 0:
            current = float(np.nanmean(var[:i]))
        pred.iloc[i] = current
    return pred.clip(lower=EPS)


def ewma_forecast(panel: pd.DataFrame, lam: float = 0.94) -> pd.Series:
    """RiskMetrics-style variance recursion; forecast for t uses variance through t-1."""
    var = panel["var"].to_numpy(float)
    pred = pd.Series(np.nan, index=panel.index, name="EWMA_094")
    h = float(np.nanmean(var[:MIN_TRAIN]))
    for i in range(1, len(panel)):
        # h is the forecast for i based on observations through i-1.
        pred.iloc[i] = h
        h = lam * h + (1.0 - lam) * float(var[i])
    return pred.clip(lower=EPS)


def _fractional_feature(y: pd.Series, d: float) -> pd.Series:
    lags = np.arange(1, FI_MAX_LAG + 1, dtype=float)
    weights = lags ** (d - 1.0)
    weights = weights / weights.sum()
    arr = y.to_numpy(float)
    out = np.full(len(arr), np.nan)
    for i in range(FI_MAX_LAG, len(arr)):
        past = arr[i - FI_MAX_LAG:i][::-1]
        if np.isfinite(past).all():
            out[i] = float(np.dot(weights, past))
    return pd.Series(out, index=y.index)


def fractional_forecast(panel: pd.DataFrame) -> tuple[pd.Series, dict]:
    y = panel["log_var"].copy()
    features = {float(d): _fractional_feature(y, float(d)) for d in FI_D_GRID}
    pred = pd.Series(np.nan, index=panel.index, name="FIGARCH_lite")
    beta = None
    best_d = None
    smear = 0.0
    choices: list[dict] = []
    for i in range(max(MIN_TRAIN, FI_MAX_LAG + 10), len(panel)):
        if beta is None or (i - MIN_TRAIN) % REFIT_EVERY == 0:
            best = None
            for d, feat in features.items():
                train = pd.DataFrame({"target": y, "feat": feat}).iloc[:i].dropna()
                if len(train) < 250:
                    continue
                xx = np.column_stack([np.ones(len(train)), train["feat"].to_numpy(float)])
                yy = train["target"].to_numpy(float)
                b, *_ = np.linalg.lstsq(xx, yy, rcond=None)
                fitted = np.exp(xx @ b)
                loss = np.nanmean(qlike_pointwise(np.exp(yy), fitted))
                if best is None or loss < best[0]:
                    resid = yy - xx @ b
                    best = (float(loss), float(d), b, float(np.nanvar(resid) / 2.0))
            if best is not None:
                _, best_d, beta, smear = best
                choices.append({"origin": str(panel.index[i].date()), "d": best_d})
        if beta is not None and best_d is not None:
            f = features[best_d].iloc[i]
            if np.isfinite(f):
                pred.iloc[i] = float(np.exp(float(beta[0] + beta[1] * f) + smear))
    summary = {
        "d_grid": [float(x) for x in FI_D_GRID],
        "n_refits": len(choices),
        "selected_d_counts": pd.Series([c["d"] for c in choices]).value_counts().sort_index().to_dict() if choices else {},
        "label": "FIGARCH-lite fractional-decay log-variance baseline; not full FIGARCH MLE",
    }
    return pred.clip(lower=EPS), summary


@dataclass
class HMM2:
    p0: np.ndarray
    trans: np.ndarray
    means: np.ndarray
    vars: np.ndarray
    loglik: float


def _normal_pdf(x: np.ndarray, means: np.ndarray, vars_: np.ndarray) -> np.ndarray:
    v = np.clip(vars_, 1e-6, None)
    z = (x[:, None] - means[None, :]) ** 2 / v[None, :]
    return np.exp(-0.5 * z) / np.sqrt(2.0 * np.pi * v[None, :])


def fit_hmm2_logvar(y: np.ndarray, n_iter: int = 80) -> HMM2:
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    q30, q70 = np.nanquantile(y, [0.30, 0.70])
    means = np.array([q30, q70], dtype=float)
    vars_ = np.array([np.nanvar(y), np.nanvar(y)], dtype=float)
    trans = np.array([[0.96, 0.04], [0.04, 0.96]], dtype=float)
    p0 = np.array([0.5, 0.5], dtype=float)
    loglik = float("nan")
    for _ in range(n_iter):
        emit = _normal_pdf(y, means, vars_)
        n = len(y)
        alpha = np.zeros((n, 2))
        scale = np.zeros(n)
        alpha[0] = p0 * emit[0]
        scale[0] = max(alpha[0].sum(), 1e-300)
        alpha[0] /= scale[0]
        for t in range(1, n):
            alpha[t] = (alpha[t - 1] @ trans) * emit[t]
            scale[t] = max(alpha[t].sum(), 1e-300)
            alpha[t] /= scale[t]
        beta = np.zeros((n, 2))
        beta[-1] = 1.0
        for t in range(n - 2, -1, -1):
            beta[t] = trans @ (emit[t + 1] * beta[t + 1])
            beta[t] /= max(beta[t].sum(), 1e-300)
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        xi_sum = np.zeros((2, 2))
        for t in range(n - 1):
            xi = alpha[t][:, None] * trans * emit[t + 1][None, :] * beta[t + 1][None, :]
            denom = max(xi.sum(), 1e-300)
            xi_sum += xi / denom
        p0 = gamma[0]
        trans = xi_sum / np.clip(xi_sum.sum(axis=1, keepdims=True), 1e-12, None)
        weights = gamma.sum(axis=0)
        means = (gamma * y[:, None]).sum(axis=0) / np.clip(weights, 1e-12, None)
        vars_ = (gamma * (y[:, None] - means[None, :]) ** 2).sum(axis=0) / np.clip(weights, 1e-12, None)
        vars_ = np.clip(vars_, 1e-4, None)
        loglik = float(np.log(scale).sum())
    order = np.argsort(means)
    return HMM2(p0=p0[order], trans=trans[np.ix_(order, order)], means=means[order], vars=vars_[order], loglik=loglik)


def hmm2_forecast(panel: pd.DataFrame) -> tuple[pd.Series, dict]:
    y = panel["log_var"].to_numpy(float)
    model = fit_hmm2_logvar(y[:MIN_TRAIN])
    pred = pd.Series(np.nan, index=panel.index, name="MS_vol_lite")
    posterior = model.p0.copy()
    for i, obs in enumerate(y):
        prior = posterior @ model.trans
        pred.iloc[i] = float(np.dot(prior, np.exp(model.means + 0.5 * model.vars)))
        emit = _normal_pdf(np.array([obs]), model.means, model.vars)[0]
        posterior = prior * emit
        posterior = posterior / max(posterior.sum(), 1e-300)
    meta = {
        "label": "two-state Markov log-variance HMM baseline; not full MS-GARCH MLE",
        "transition": model.trans.tolist(),
        "means": model.means.tolist(),
        "vars": model.vars.tolist(),
        "loglik_initial_train": model.loglik,
    }
    return pred.clip(lower=EPS), meta


def msm_state_space(k: int, m0: float, gammas: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m1 = 2.0 - m0
    states = np.array(list(itertools.product([0, 1], repeat=k)), dtype=int)
    mult_by_component = np.where(states == 0, m0, m1)
    products = mult_by_component.prod(axis=1)
    n_states = len(states)
    trans = np.ones((n_states, n_states), dtype=float)
    for i in range(n_states):
        for j in range(n_states):
            prob = 1.0
            for kk in range(k):
                same = states[i, kk] == states[j, kk]
                g = gammas[kk]
                prob *= (1.0 - g) * float(same) + 0.5 * g
            trans[i, j] = prob
    trans = trans / trans.sum(axis=1, keepdims=True)
    stationary = np.full(n_states, 1.0 / n_states)
    return products, trans, stationary


def _acf(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) <= lag + 5:
        return np.nan
    a = x[:-lag] - np.nanmean(x[:-lag])
    b = x[lag:] - np.nanmean(x[lag:])
    den = np.sqrt(np.dot(a, a) * np.dot(b, b))
    if den <= 0:
        return np.nan
    return float(np.dot(a, b) / den)


def fit_msm_gmm(panel: pd.DataFrame) -> dict:
    """Moment-match a binary MSM on log squared returns.

    This is intentionally a transparent GMM-lite calibration, not a black-box
    full MLE. Moments: log-variance variance and ACF at lags 1/5/22/66.
    """
    y = panel["log_var"].iloc[:MIN_TRAIN].to_numpy(float)
    y = y[np.isfinite(y)]
    y = np.clip(y, np.quantile(y, 0.01), np.quantile(y, 0.99))
    obs_var = float(np.nanvar(y))
    lags = np.array([1, 5, 22, 66], dtype=int)
    obs_acf = np.array([_acf(y, int(l)) for l in lags], dtype=float)
    obs_acf = np.where(np.isfinite(obs_acf), obs_acf, 0.0)

    def unpack(theta: np.ndarray) -> tuple[float, float, float, float, np.ndarray]:
        # m0 in [0.15, 0.95], gamma_min in [0.001, 0.25], b in [1.10, 4.0],
        # signal_share in [0.05, 0.95].
        m0 = 0.15 + 0.80 / (1.0 + np.exp(-theta[0]))
        gamma_min = 0.001 + 0.249 / (1.0 + np.exp(-theta[1]))
        b = 1.10 + 2.90 / (1.0 + np.exp(-theta[2]))
        share = 0.05 + 0.90 / (1.0 + np.exp(-theta[3]))
        gammas = np.minimum(0.95, gamma_min * (b ** np.arange(MSM_K)))
        return float(m0), float(gamma_min), float(b), float(share), gammas

    def objective(theta: np.ndarray) -> float:
        m0, _, _, share, gammas = unpack(theta)
        m1 = 2.0 - m0
        var_log_m = MSM_K * ((np.log(m1) - np.log(m0)) ** 2) / 4.0
        rho = 1.0 - gammas
        acf_model_signal = np.array([np.mean(rho ** int(l)) for l in lags])
        acf_model_obs = share * acf_model_signal
        var_model_obs = var_log_m / max(share, 1e-6)
        acf_err = obs_acf - acf_model_obs
        var_err = np.log(max(obs_var, 1e-8)) - np.log(max(var_model_obs, 1e-8))
        return float(8.0 * np.mean(acf_err ** 2) + 0.25 * var_err ** 2)

    best = None
    starts = [
        np.array([0.0, -2.0, 0.0, 0.0]),
        np.array([-1.0, -3.0, 1.0, -0.5]),
        np.array([1.0, -1.5, -1.0, 0.5]),
        np.array([-2.0, -4.0, 0.5, -1.0]),
    ]
    for x0 in starts:
        res = optimize.minimize(objective, x0, method="Nelder-Mead", options={"maxiter": 400, "xatol": 1e-5, "fatol": 1e-7})
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    m0, gamma_min, b, share, gammas = unpack(best.x)
    return {
        "k": MSM_K,
        "m0": m0,
        "m1": 2.0 - m0,
        "gamma_min": gamma_min,
        "b": b,
        "gammas": gammas.tolist(),
        "signal_share": share,
        "objective": float(best.fun),
        "observed_moments": {
            "var_log_r2_winsorized": obs_var,
            "acf": {str(int(l)): float(v) for l, v in zip(lags, obs_acf)},
        },
        "estimator": "GMM-lite moment matching on log r^2 variance and ACF lags 1/5/22/66",
    }


def msm_gmm_forecast(panel: pd.DataFrame) -> tuple[pd.Series, dict]:
    params = fit_msm_gmm(panel)
    ret = panel["ret"].to_numpy(float)
    train_ret = ret[:MIN_TRAIN]
    mu = float(np.nanmean(train_ret))
    sigma2 = float(np.nanvar(train_ret - mu))
    products, trans, stationary = msm_state_space(params["k"], params["m0"], np.asarray(params["gammas"], dtype=float))
    pred = pd.Series(np.nan, index=panel.index, name="MSM_GMM")
    posterior = stationary.copy()
    for i, r in enumerate(ret):
        prior = posterior @ trans
        pred.iloc[i] = float(sigma2 * np.dot(prior, products))
        state_var = np.clip(sigma2 * products, EPS, None)
        ll = np.exp(-0.5 * ((r - mu) ** 2) / state_var) / np.sqrt(2.0 * np.pi * state_var)
        posterior = prior * ll
        posterior = posterior / max(posterior.sum(), 1e-300)
    params["mu_initial_train"] = mu
    params["sigma2_initial_train"] = sigma2
    params["state_count"] = int(len(products))
    return pred.clip(lower=EPS), params


def evaluate_asset(asset: str, price: pd.Series) -> dict:
    panel = build_returns(price)
    if len(panel) < MIN_TRAIN + 252:
        raise RuntimeError(f"{asset}: insufficient rows after cleaning")
    forecasts: dict[str, pd.Series] = {}
    forecasts["CONST"] = constant_forecast(panel)
    forecasts["EWMA_094"] = ewma_forecast(panel)
    forecasts["HAR"] = har_forecast(panel)
    forecasts["FIGARCH_lite"], fig_meta = fractional_forecast(panel)
    forecasts["MS_vol_lite"], hmm_meta = hmm2_forecast(panel)
    forecasts["MSM_GMM"], msm_meta = msm_gmm_forecast(panel)

    common = pd.DataFrame({"actual": panel["var"]})
    for name, pred in forecasts.items():
        common[name] = pred
    common = common.iloc[MIN_TRAIN:].dropna()
    for col in ["actual", *forecasts.keys()]:
        common[col] = common[col].clip(lower=EPS)

    losses = {m: qlike_pointwise(common["actual"].values, common[m].values) for m in forecasts}
    qlike = {m: float(np.nanmean(v)) for m, v in losses.items()}
    mse = {m: float(np.nanmean((common["actual"].values - common[m].values) ** 2)) for m in forecasts}
    dm_vs_har = {}
    for m in forecasts:
        if m == "HAR":
            continue
        dm = dm_hac(losses[m], losses["HAR"], max_lag=5)
        dm["qlike_improvement_pct_vs_HAR"] = float(100.0 * (qlike["HAR"] - qlike[m]) / qlike["HAR"])
        dm_vs_har[f"{m}_vs_HAR"] = dm
    dm_msm_vs_msvol = dm_hac(losses["MSM_GMM"], losses["MS_vol_lite"], max_lag=5)
    dm_msm_vs_msvol["qlike_improvement_pct_vs_MS_vol_lite"] = float(
        100.0 * (qlike["MS_vol_lite"] - qlike["MSM_GMM"]) / qlike["MS_vol_lite"]
    )
    dm_msm_vs_ewma = dm_hac(losses["MSM_GMM"], losses["EWMA_094"], max_lag=5)
    dm_msm_vs_ewma["qlike_improvement_pct_vs_EWMA_094"] = float(
        100.0 * (qlike["EWMA_094"] - qlike["MSM_GMM"]) / qlike["EWMA_094"]
    )

    out_rows = common.copy()
    out_rows["date"] = out_rows.index
    out_rows["asset"] = asset
    for m in forecasts:
        out_rows[f"loss_{m}"] = losses[m]
    out_rows.to_csv(DATA_DIR / f"{asset.replace('.', '_')}_oos_forecasts.csv", index=False)

    return {
        "asset": asset,
        "sample": {
            "n_returns": int(len(panel)),
            "return_start": str(panel.index.min().date()),
            "return_end": str(panel.index.max().date()),
            "n_oos_common": int(len(common)),
            "oos_start": str(common.index.min().date()),
            "oos_end": str(common.index.max().date()),
        },
        "qlike": qlike,
        "mse": mse,
        "dm_vs_HAR": dm_vs_har,
        "dm_MSM_GMM_vs_MS_vol_lite": dm_msm_vs_msvol,
        "dm_MSM_GMM_vs_EWMA_094": dm_msm_vs_ewma,
        "model_params": {
            "FIGARCH_lite": fig_meta,
            "MS_vol_lite": hmm_meta,
            "MSM_GMM": msm_meta,
        },
        "oos_frame": out_rows,
    }


def pooled_results(asset_results: dict[str, dict]) -> dict:
    frames = [res["oos_frame"] for res in asset_results.values()]
    all_oos = pd.concat(frames, ignore_index=True)
    all_oos.to_csv(DATA_DIR / "pooled_oos_forecasts.csv", index=False)
    models = ["CONST", "EWMA_094", "HAR", "FIGARCH_lite", "MS_vol_lite", "MSM_GMM"]
    pooled_qlike = {m: float(np.nanmean(all_oos[f"loss_{m}"].to_numpy(float))) for m in models}
    dm = {}
    for m in models:
        if m == "HAR":
            continue
        dd = all_oos[["date", f"loss_{m}", "loss_HAR"]].dropna().copy()
        by_date = dd.groupby("date")[[f"loss_{m}", "loss_HAR"]].mean()
        test = dm_hac(by_date[f"loss_{m}"].values, by_date["loss_HAR"].values, max_lag=5)
        test["qlike_improvement_pct_vs_HAR"] = float(100.0 * (pooled_qlike["HAR"] - pooled_qlike[m]) / pooled_qlike["HAR"])
        dm[f"{m}_vs_HAR"] = test
    by_date = all_oos.groupby("date")[["loss_MSM_GMM", "loss_MS_vol_lite"]].mean()
    msm_vs_msvol = dm_hac(by_date["loss_MSM_GMM"].values, by_date["loss_MS_vol_lite"].values, max_lag=5)
    msm_vs_msvol["qlike_improvement_pct_vs_MS_vol_lite"] = float(
        100.0 * (pooled_qlike["MS_vol_lite"] - pooled_qlike["MSM_GMM"]) / pooled_qlike["MS_vol_lite"]
    )
    by_date = all_oos.groupby("date")[["loss_MSM_GMM", "loss_EWMA_094"]].mean()
    msm_vs_ewma = dm_hac(by_date["loss_MSM_GMM"].values, by_date["loss_EWMA_094"].values, max_lag=5)
    msm_vs_ewma["qlike_improvement_pct_vs_EWMA_094"] = float(
        100.0 * (pooled_qlike["EWMA_094"] - pooled_qlike["MSM_GMM"]) / pooled_qlike["EWMA_094"]
    )
    best = min(pooled_qlike, key=pooled_qlike.get)
    msm = dm["MSM_GMM_vs_HAR"]
    if (
        best == "MSM_GMM"
        and msm["t_stat"] is not None
        and msm["t_stat"] < -HARVEY_T
        and msm["qlike_improvement_pct_vs_HAR"] > 0
        and msm_vs_msvol["t_stat"] is not None
        and msm_vs_msvol["t_stat"] < -HARVEY_T
    ):
        verdict = "CONDITIONAL_PASS_MSM_GMM_LITE_BEST"
    elif best == "MSM_GMM" and msm["qlike_improvement_pct_vs_HAR"] > 0:
        verdict = "DIRECTIONAL_MSM_GMM_BEST_NOT_HARVEY"
    elif (
        msm["t_stat"] is not None
        and msm["t_stat"] < -HARVEY_T
        and msm["qlike_improvement_pct_vs_HAR"] > 0
        and best == "EWMA_094"
    ):
        verdict = "CONDITIONAL_NULL_MSM_BEATS_HAR_BUT_LOSES_TO_EWMA"
    elif msm["t_stat"] is not None and msm["t_stat"] < -HARVEY_T and msm["qlike_improvement_pct_vs_HAR"] > 0:
        verdict = "REGIME_MODELS_BEAT_HAR_MSM_NOT_BEST"
    else:
        verdict = "NULL_NO_MSM_GMM_EDGE"
    return {
        "pooled_qlike": pooled_qlike,
        "pooled_dm_vs_HAR_by_date": dm,
        "pooled_dm_MSM_GMM_vs_MS_vol_lite_by_date": msm_vs_msvol,
        "pooled_dm_MSM_GMM_vs_EWMA_094_by_date": msm_vs_ewma,
        "best_pooled_model": best,
        "verdict": verdict,
        "n_pooled_rows": int(len(all_oos)),
        "n_unique_dates": int(pd.to_datetime(all_oos["date"]).nunique()),
    }


def plot_summary(asset_results: dict[str, dict], pooled: dict) -> dict:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    models = ["CONST", "EWMA_094", "FIGARCH_lite", "MS_vol_lite", "MSM_GMM"]
    assets = list(asset_results.keys())
    data = np.array([
        [asset_results[a]["dm_vs_HAR"][f"{m}_vs_HAR"]["qlike_improvement_pct_vs_HAR"] for m in models]
        for a in assets
    ])
    x = np.arange(len(assets))
    width = 0.15
    fig, ax = plt.subplots(figsize=(12, 6), dpi=140)
    colors = ["#8E8E8E", "#B279A2", "#4C78A8", "#F58518", "#54A24B"]
    for j, m in enumerate(models):
        ax.bar(x + (j - 2) * width, data[:, j], width=width, label=m, color=colors[j])
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("QLIKE improvement vs HAR (%)")
    ax.set_title("K1637: constant / EWMA / fractional / regime forecasts vs HAR")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p1 = FIG_DIR / "k1637_qlike_improvement_vs_har.png"
    fig.savefig(p1)
    plt.close(fig)

    pooled_vals = pooled["pooled_qlike"]
    fig, ax = plt.subplots(figsize=(8, 5), dpi=140)
    names = list(pooled_vals.keys())
    vals = [pooled_vals[n] for n in names]
    ax.bar(names, vals, color=["#333333", "#4C78A8", "#F58518", "#54A24B"])
    ax.set_ylabel("Mean QLIKE (lower is better)")
    ax.set_title("Pooled date/asset OOS QLIKE")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p2 = FIG_DIR / "k1637_pooled_qlike.png"
    fig.savefig(p2)
    plt.close(fig)
    return {"qlike_improvement": str(p1.relative_to(HERE)), "pooled_qlike": str(p2.relative_to(HERE))}


def main() -> None:
    prices, price_meta = load_price_panel()
    asset_results = {}
    for asset, price in prices.items():
        print(f"[K1637] running {asset} ...", flush=True)
        asset_results[asset] = evaluate_asset(asset, price)
    pooled = pooled_results(asset_results)
    figures = plot_summary(asset_results, pooled)

    # Remove bulky dataframes before JSON serialization.
    compact_assets = {}
    for asset, res in asset_results.items():
        compact = {k: v for k, v in res.items() if k != "oos_frame"}
        compact_assets[asset] = compact

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "question": "Does GMM-lite MSM volatility forecasting beat HAR / fractional / Markov-volatility baselines on one-day close-to-close variance?",
        "data": {
            "price_cache": str(PRICE_DB.relative_to(ROOT)),
            "assets": price_meta,
            "target": "one-day close-to-close squared log return r_t^2",
            "sample_note": "US ETF cache begins 2016-01-04; 0050.TW begins 2009 but experiment uses common START_DATE lower bound where available.",
        },
        "method": {
            "oos_alignment": "Forecast for return day t uses features/latent posterior through t-1; HAR features explicitly use shift(1).",
            "initial_train_rows": MIN_TRAIN,
            "har_refit_every_trading_days": REFIT_EVERY,
            "msm_components": MSM_K,
            "msm_estimator": "GMM-lite moment matching on log r^2 variance and autocorrelations, then exact finite-state filter for forecasts.",
            "figarch_lite": "Fractional-decay log-variance baseline selected from d grid by in-sample QLIKE; not full FIGARCH MLE.",
            "ms_vol_lite": "Two-state Gaussian HMM on log variance; not full MS-GARCH MLE.",
            "constant_and_ewma_sanity": "Expanding constant variance and RiskMetrics EWMA(0.94) included to check whether HAR is merely weak on noisy r^2.",
            "loss": "Patton QLIKE actual/predicted on r_t^2 plus MSE diagnostic.",
            "inference": "DM-HAC max_lag=5; pooled tests aggregate loss differentials by date before testing.",
            "harvey_threshold": f"|t| > {HARVEY_T}",
        },
        "asset_results": compact_assets,
        "pooled_results": pooled,
        "figures": figures,
        "honesty": {
            "lookahead_controls": [
                "HAR d/w/m predictors are y.shift(1)-based.",
                "MSM/HMM latent probabilities are forecast with posterior_{t-1} transition before observing r_t.",
                "Parameters are fit on initial training rows only before OOS evaluation.",
                "Pooled inference is by-date, not stacked asset-day iid.",
            ],
            "limitations": [
                "MSM estimator is transparent GMM-lite moment matching, not full Calvet-Fisher simulated GMM or exact MLE.",
                "FIGARCH_lite and MS_vol_lite are mechanism baselines, not full production FIGARCH/MS-GARCH packages.",
                "Daily close-to-close variance target avoids mixing model-native targets with intraday RV, but does not test high-frequency RV-MSM directly.",
            ],
        },
    }
    RESULTS_PATH.write_text(json.dumps(_jsonify(results), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(_jsonify({"verdict": pooled["verdict"], "pooled_qlike": pooled["pooled_qlike"]}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
