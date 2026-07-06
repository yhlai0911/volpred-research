"""K1651: CAViaR direct dynamic-quantile VaR vs GARCH-VaR.

Question
--------
Can Engle-Manganelli CAViaR specifications forecast 1-day left-tail VaR
better than a conventional GJR-GARCH skew-t VaR baseline, without first
building a volatility model?

Design
------
Assets: SPY and HYG daily adjusted-close log returns.
Alphas: 5% and 1% left-tail VaR.
Models: HS250, CAViaR-SAV, CAViaR-AS, CAViaR-IG, CAViaR-AD, GJR-GARCH-SkewT.
OOS: 2015-01-01 onward. Annual expanding-window refit; daily recursion.

Lookahead policy
----------------
For every forecast at date t:
  - refits use only rows with index < t;
  - recursions update q_t or sigma_t from q_{t-1}, sigma_{t-1}, and r_{t-1};
  - HS250 uses y.shift(1).rolling(...).quantile(alpha).

Seed is fixed to 42. Results JSON is written atomically.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

warnings.simplefilter("ignore", category=RuntimeWarning)
warnings.simplefilter("ignore", category=UserWarning)

EXPERIMENT_ID = "K1651"
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_CACHE = HERE / "k1651_prices.parquet"
FORECASTS_PATH = HERE / "k1651_forecasts.parquet"
RESULTS_PATH = HERE / "k1651_results.json"

TICKERS = ["SPY", "HYG"]
ASSETS = ["SPY", "HYG"]
START = "2006-01-01"
END = "2026-07-07"
OOS_START = pd.Timestamp("2015-01-01")
ALPHAS = (0.05, 0.01)
HS_WINDOW = 250
CAVIAR_RESTARTS = 2
CAVIAR_MAXITER = 180
DQ_LAGS = 4
HARVEY_ABS_T_THRESHOLD = 3.0
G_ADAPTIVE = 10.0


@dataclass
class ForecastSeries:
    name: str
    var: pd.Series
    loss: pd.Series
    violations: pd.Series
    fit_failures: int = 0
    refits: int = 0


def fetch_prices(force_fetch: bool = False) -> pd.DataFrame:
    if DATA_CACHE.exists() and not force_fetch:
        return pd.read_parquet(DATA_CACHE)

    import yfinance as yf

    px = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(TICKERS[0])
    px = px.dropna(how="any").sort_index()
    DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    px.to_parquet(DATA_CACHE)
    return px


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices).diff().dropna()


def refit_dates(index: pd.DatetimeIndex, cadence: str = "year") -> List[pd.Timestamp]:
    dates: List[pd.Timestamp] = []
    last_key: Tuple[int, int] | None = None
    for ts in index:
        if ts < OOS_START:
            continue
        if cadence == "year":
            key = (ts.year, 0)
        elif cadence == "quarter":
            key = (ts.year, (ts.month - 1) // 3)
        else:
            key = (ts.year, ts.month)
        if key != last_key:
            dates.append(ts)
            last_key = key
    return dates


def pinball_loss(y: pd.Series, q: pd.Series, alpha: float) -> pd.Series:
    u = y - q
    return pd.Series(
        np.where(u.to_numpy(dtype=float) >= 0.0, alpha * u, (alpha - 1.0) * u),
        index=y.index,
        name="pinball_loss",
    )


def pinball_array(y: np.ndarray, q: np.ndarray, alpha: float) -> np.ndarray:
    u = y - q
    return np.where(u >= 0.0, alpha * u, (alpha - 1.0) * u)


# ---------------------------------------------------------------------------
# CAViaR recursions. All functions return lower-tail VaR values, so q is
# usually negative. IG is deliberately implemented as -sqrt(...) to avoid the
# common sign bug where a scale forecast is accidentally treated as a VaR.


def caviar_sav(params: np.ndarray, y: np.ndarray, q0: float, alpha: float) -> np.ndarray:
    b0, b1, b2 = params
    q = np.empty(len(y), dtype=float)
    q[0] = q0
    for i in range(1, len(y)):
        q[i] = b0 + b1 * q[i - 1] + b2 * abs(y[i - 1])
    return q


def caviar_as(params: np.ndarray, y: np.ndarray, q0: float, alpha: float) -> np.ndarray:
    b0, b1, b2, b3 = params
    q = np.empty(len(y), dtype=float)
    q[0] = q0
    y_pos = np.maximum(y, 0.0)
    y_neg = np.minimum(y, 0.0)
    for i in range(1, len(y)):
        q[i] = b0 + b1 * q[i - 1] + b2 * y_pos[i - 1] + b3 * y_neg[i - 1]
    return q


def caviar_ig(params: np.ndarray, y: np.ndarray, q0: float, alpha: float) -> np.ndarray:
    b0, b1, b2 = params
    q = np.empty(len(y), dtype=float)
    q[0] = min(q0, -1e-8)
    y2 = y * y
    for i in range(1, len(y)):
        inside = b0 + b1 * q[i - 1] ** 2 + b2 * y2[i - 1]
        q[i] = -math.sqrt(max(float(inside), 1e-12))
    return q


def caviar_ad(params: np.ndarray, y: np.ndarray, q0: float, alpha: float) -> np.ndarray:
    b1 = params[0]
    q = np.empty(len(y), dtype=float)
    q[0] = q0
    for i in range(1, len(y)):
        z = np.clip(G_ADAPTIVE * (y[i - 1] - q[i - 1]), -500.0, 500.0)
        logistic = 1.0 / (1.0 + math.exp(float(z)))
        q[i] = q[i - 1] + b1 * (logistic - alpha)
    return q


def caviar_next(spec: str, params: np.ndarray, q_prev: float, y_prev: float, alpha: float) -> float:
    if spec == "SAV":
        b0, b1, b2 = params
        return float(b0 + b1 * q_prev + b2 * abs(y_prev))
    if spec == "AS":
        b0, b1, b2, b3 = params
        return float(b0 + b1 * q_prev + b2 * max(y_prev, 0.0) + b3 * min(y_prev, 0.0))
    if spec == "IG":
        b0, b1, b2 = params
        return float(-math.sqrt(max(b0 + b1 * q_prev * q_prev + b2 * y_prev * y_prev, 1e-12)))
    if spec == "AD":
        b1 = params[0]
        z = np.clip(G_ADAPTIVE * (y_prev - q_prev), -500.0, 500.0)
        logistic = 1.0 / (1.0 + math.exp(float(z)))
        return float(q_prev + b1 * (logistic - alpha))
    raise ValueError(f"unknown CAViaR spec: {spec}")


CAVIAR_SPECS: Dict[str, Tuple[Callable[[np.ndarray, np.ndarray, float, float], np.ndarray], int]] = {
    "SAV": (caviar_sav, 3),
    "AS": (caviar_as, 4),
    "IG": (caviar_ig, 3),
    "AD": (caviar_ad, 1),
}


def initial_params(spec: str, y: np.ndarray, alpha: float, rng: np.random.Generator) -> np.ndarray:
    emp_q = float(np.quantile(y, alpha))
    mean_abs = float(np.mean(np.abs(y)))
    var_y = float(np.mean(y * y))
    if spec == "SAV":
        b1 = rng.uniform(0.65, 0.98)
        b2 = rng.uniform(-1.4, 0.15)
        b0 = emp_q * (1.0 - b1) - b2 * mean_abs
        return np.array([b0, b1, b2], dtype=float)
    if spec == "AS":
        b1 = rng.uniform(0.65, 0.98)
        b2 = rng.uniform(-1.0, 0.5)
        b3 = rng.uniform(0.0, 2.5)
        b0 = emp_q * (1.0 - b1)
        return np.array([b0, b1, b2, b3], dtype=float)
    if spec == "IG":
        b1 = rng.uniform(0.65, 0.98)
        b2 = rng.uniform(0.01, 1.0)
        b0 = max(emp_q * emp_q * (1.0 - b1) - b2 * var_y, 1e-8)
        return np.array([b0, b1, b2], dtype=float)
    if spec == "AD":
        return np.array([rng.uniform(-0.015, -0.0001)], dtype=float)
    raise ValueError(f"unknown CAViaR spec: {spec}")


def bounds_for_spec(spec: str) -> List[Tuple[float, float]]:
    if spec == "SAV":
        return [(-0.25, 0.05), (0.0, 0.995), (-5.0, 2.0)]
    if spec == "AS":
        return [(-0.25, 0.05), (0.0, 0.995), (-5.0, 5.0), (-2.0, 8.0)]
    if spec == "IG":
        return [(1e-10, 0.05), (0.0, 0.995), (0.0, 8.0)]
    if spec == "AD":
        return [(-0.08, 0.02)]
    raise ValueError(f"unknown CAViaR spec: {spec}")


def fit_caviar(y: np.ndarray, alpha: float, spec: str, seed_offset: int) -> Dict[str, Any]:
    func, _ = CAVIAR_SPECS[spec]
    q0 = float(np.quantile(y[: min(len(y), 750)], alpha))
    rng = np.random.default_rng(SEED + seed_offset)
    starts = [initial_params(spec, y, alpha, rng) for _ in range(CAVIAR_RESTARTS)]
    if spec == "AD":
        starts.insert(0, np.array([-0.003], dtype=float))
    best_fun = np.inf
    best_x = starts[0]
    best_success = False

    def objective(params: np.ndarray) -> float:
        q = func(np.asarray(params, dtype=float), y, q0, alpha)
        if (not np.all(np.isfinite(q))) or np.max(np.abs(q)) > 1.0:
            return 1e6
        # Mild penalty discourages positive lower-tail VaR forecasts.
        penalty = 1e4 * float(np.mean(np.maximum(q, 0.0) ** 2))
        return float(np.mean(pinball_array(y, q, alpha)) + penalty)

    for x0 in starts:
        try:
            res = optimize.minimize(
                objective,
                x0=x0,
                method="L-BFGS-B",
                bounds=bounds_for_spec(spec),
                options={"maxiter": CAVIAR_MAXITER, "ftol": 1e-10, "maxls": 30},
            )
        except Exception:
            continue
        if np.isfinite(res.fun) and float(res.fun) < best_fun:
            best_fun = float(res.fun)
            best_x = np.asarray(res.x, dtype=float)
            best_success = bool(res.success)

    q = func(best_x, y, q0, alpha)
    if (not np.all(np.isfinite(q))) or best_fun >= 1e5:
        best_x = np.array([float(np.quantile(y, alpha))], dtype=float)
        q = np.full(len(y), float(np.quantile(y, alpha)), dtype=float)
        best_success = False
        best_fun = float(np.mean(pinball_array(y, q, alpha)))

    return {
        "params": best_x,
        "q_last": float(q[-1]),
        "loss": best_fun,
        "success": best_success,
    }


def run_caviar(y: pd.Series, alpha: float, spec: str, cadence: str) -> ForecastSeries:
    dates = set(refit_dates(y.index, cadence=cadence))
    var = pd.Series(index=y.index[y.index >= OOS_START], dtype=float)
    current_params: np.ndarray | None = None
    q_prev: float | None = None
    y_prev: float | None = None
    fit_failures = 0
    refits = 0

    for ts in y.index[y.index >= OOS_START]:
        pos = y.index.get_loc(ts)
        if pos < HS_WINDOW:
            continue
        if current_params is None or ts in dates:
            train = y.iloc[:pos].dropna().to_numpy(dtype=float)
            try:
                fit = fit_caviar(train, alpha, spec, seed_offset=pos + int(alpha * 1000))
                current_params = np.asarray(fit["params"], dtype=float)
                q_prev = float(fit["q_last"])
                y_prev = float(y.iloc[pos - 1])
                refits += 1
                if not fit["success"]:
                    fit_failures += 1
            except Exception:
                fit_failures += 1
                current_params = current_params if current_params is not None else np.array([float(np.quantile(train, alpha))])
                q_prev = q_prev if q_prev is not None else float(np.quantile(train, alpha))
                y_prev = float(y.iloc[pos - 1])

        assert current_params is not None and q_prev is not None and y_prev is not None
        if len(current_params) == 1 and spec != "AD":
            q_t = float(current_params[0])
        else:
            q_t = caviar_next(spec, current_params, q_prev, y_prev, alpha)
        var.loc[ts] = q_t
        q_prev = q_t
        y_prev = float(y.loc[ts])

    var = var.dropna()
    actual = y.loc[var.index]
    loss = pinball_loss(actual, var, alpha)
    violations = (actual < var).astype(int)
    return ForecastSeries(
        name=f"CAViaR-{spec}",
        var=var,
        loss=loss,
        violations=violations,
        fit_failures=fit_failures,
        refits=refits,
    )


def run_hs(y: pd.Series, alpha: float) -> ForecastSeries:
    var = y.shift(1).rolling(HS_WINDOW).quantile(alpha)
    var = var[var.index >= OOS_START].dropna()
    actual = y.loc[var.index]
    loss = pinball_loss(actual, var, alpha)
    violations = (actual < var).astype(int)
    return ForecastSeries(name=f"HS{HS_WINDOW}", var=var, loss=loss, violations=violations)


def run_gjr_skewt(y: pd.Series, alpha: float, cadence: str) -> ForecastSeries:
    from arch import arch_model
    from arch.univariate.distribution import SkewStudent

    dates = set(refit_dates(y.index, cadence=cadence))
    var = pd.Series(index=y.index[y.index >= OOS_START], dtype=float)
    fit_failures = 0
    refits = 0
    omega = 0.01
    a1 = 0.05
    gamma = 0.05
    beta = 0.90
    eta = 8.0
    lam = 0.0
    sigma2_prev: float | None = None

    skewt = SkewStudent()
    for ts in y.index[y.index >= OOS_START]:
        pos = y.index.get_loc(ts)
        if pos < HS_WINDOW:
            continue
        if sigma2_prev is None or ts in dates:
            train_pct = y.iloc[:pos].dropna().to_numpy(dtype=float) * 100.0
            try:
                model = arch_model(
                    train_pct,
                    vol="GARCH",
                    p=1,
                    o=1,
                    q=1,
                    mean="Zero",
                    dist="skewt",
                    rescale=False,
                )
                res = model.fit(disp="off", show_warning=False)
                params = dict(res.params)
                omega = float(params.get("omega", omega))
                a1 = float(params.get("alpha[1]", a1))
                gamma = float(params.get("gamma[1]", gamma))
                beta = float(params.get("beta[1]", beta))
                eta = float(params.get("eta", params.get("nu", eta)))
                lam = float(params.get("lambda", lam))
                sigma2_prev = float(np.asarray(res.conditional_volatility)[-1]) ** 2
                refits += 1
            except Exception:
                fit_failures += 1
                sigma2_prev = float(np.var(train_pct)) if sigma2_prev is None else sigma2_prev

        assert sigma2_prev is not None
        y_prev_pct = float(y.iloc[pos - 1]) * 100.0
        indicator = 1.0 if y_prev_pct < 0.0 else 0.0
        sigma2_t = omega + (a1 + gamma * indicator) * y_prev_pct * y_prev_pct + beta * sigma2_prev
        sigma2_t = max(float(sigma2_t), 1e-10)
        q_std = float(skewt.ppf(alpha, parameters=np.array([eta, lam], dtype=float)))
        var.loc[ts] = math.sqrt(sigma2_t) / 100.0 * q_std
        sigma2_prev = sigma2_t

    var = var.dropna()
    actual = y.loc[var.index]
    loss = pinball_loss(actual, var, alpha)
    violations = (actual < var).astype(int)
    return ForecastSeries(
        name="GJR-GARCH-SkewT",
        var=var,
        loss=loss,
        violations=violations,
        fit_failures=fit_failures,
        refits=refits,
    )


def align_forecasts(forecasts: Dict[str, ForecastSeries]) -> Dict[str, ForecastSeries]:
    common: pd.DatetimeIndex | None = None
    for fs in forecasts.values():
        common = fs.var.index if common is None else common.intersection(fs.var.index)
    assert common is not None
    aligned: Dict[str, ForecastSeries] = {}
    for name, fs in forecasts.items():
        var = fs.var.loc[common]
        loss = fs.loss.loc[common]
        violations = fs.violations.loc[common]
        aligned[name] = ForecastSeries(
            name=fs.name,
            var=var,
            loss=loss,
            violations=violations,
            fit_failures=fs.fit_failures,
            refits=fs.refits,
        )
    return aligned


def run_models(y: pd.Series, alpha: float, cadence: str) -> Dict[str, ForecastSeries]:
    forecasts: Dict[str, ForecastSeries] = {"HS250": run_hs(y, alpha)}
    for spec in ["SAV", "AS", "IG", "AD"]:
        print(f"    CAViaR-{spec}", flush=True)
        forecasts[f"CAViaR-{spec}"] = run_caviar(y, alpha, spec, cadence=cadence)
    print("    GJR-GARCH-SkewT", flush=True)
    forecasts["GJR-GARCH-SkewT"] = run_gjr_skewt(y, alpha, cadence=cadence)
    return align_forecasts(forecasts)


# ---------------------------------------------------------------------------
# Evaluation


def kupiec_pof(violations: pd.Series, alpha: float) -> Dict[str, Any]:
    n = int(len(violations))
    x = int(violations.sum())
    if n == 0:
        return {"n": n, "violations": x, "rate": float("nan"), "stat": float("nan"), "p": float("nan"), "pass": False}
    pi_hat = x / n
    eps = 1e-12
    ph = min(max(pi_hat, eps), 1.0 - eps)
    pa = min(max(alpha, eps), 1.0 - eps)
    ll0 = x * math.log(pa) + (n - x) * math.log(1.0 - pa)
    ll1 = x * math.log(ph) + (n - x) * math.log(1.0 - ph)
    stat = max(0.0, -2.0 * (ll0 - ll1))
    p = float(1.0 - stats.chi2.cdf(stat, 1))
    return {
        "n": n,
        "violations": x,
        "rate": float(pi_hat),
        "expected_rate": float(alpha),
        "stat": float(stat),
        "p": p,
        "pass": bool(p > 0.05),
    }


def christoffersen_independence(violations: pd.Series) -> Dict[str, Any]:
    v = violations.to_numpy(dtype=int)
    if len(v) < 2:
        return {"stat": float("nan"), "p": float("nan"), "pass": False}
    n00 = n01 = n10 = n11 = 0
    for i in range(1, len(v)):
        a, b = int(v[i - 1]), int(v[i])
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    n0 = n00 + n01
    n1 = n10 + n11
    total = n0 + n1
    if n0 == 0 or n1 == 0 or total == 0:
        return {"n00": n00, "n01": n01, "n10": n10, "n11": n11, "stat": float("nan"), "p": float("nan"), "pass": False}
    eps = 1e-12
    pi01 = min(max(n01 / n0, eps), 1.0 - eps)
    pi11 = min(max(n11 / n1, eps), 1.0 - eps)
    pi = min(max((n01 + n11) / total, eps), 1.0 - eps)
    ll_null = (n00 + n10) * math.log(1.0 - pi) + (n01 + n11) * math.log(pi)
    ll_alt = n00 * math.log(1.0 - pi01) + n01 * math.log(pi01) + n10 * math.log(1.0 - pi11) + n11 * math.log(pi11)
    stat = max(0.0, -2.0 * (ll_null - ll_alt))
    p = float(1.0 - stats.chi2.cdf(stat, 1))
    return {
        "n00": n00,
        "n01": n01,
        "n10": n10,
        "n11": n11,
        "stat": float(stat),
        "p": p,
        "pass": bool(p > 0.05),
    }


def basel_binomial_zone(violations: pd.Series, alpha: float) -> Dict[str, Any]:
    n = int(len(violations))
    x = int(violations.sum())
    green_cutoff = int(stats.binom.ppf(0.95, n, alpha))
    yellow_cutoff = int(stats.binom.ppf(0.9999, n, alpha))
    if x <= green_cutoff:
        zone = "green"
    elif x <= yellow_cutoff:
        zone = "yellow"
    else:
        zone = "red"
    return {
        "zone": zone,
        "green_cutoff": green_cutoff,
        "yellow_cutoff": yellow_cutoff,
        "pass": bool(zone == "green"),
    }


def dq_test(y: pd.Series, var: pd.Series, alpha: float, lags: int = DQ_LAGS) -> Dict[str, Any]:
    common = y.index.intersection(var.index)
    yy = y.loc[common].to_numpy(dtype=float)
    qq = var.loc[common].to_numpy(dtype=float)
    hits = (yy < qq).astype(float) - alpha
    n = len(hits)
    if n <= lags + 5:
        return {"stat": float("nan"), "p": float("nan"), "df": 0, "pass": False}
    rows = n - lags
    cols = [np.ones(rows)]
    for lag in range(1, lags + 1):
        cols.append(hits[lags - lag : n - lag])
    cols.append(qq[lags:])
    x = np.column_stack(cols)
    h = hits[lags:]
    try:
        xtx = x.T @ x
        inv = np.linalg.pinv(xtx)
        stat = float(h.T @ x @ inv @ x.T @ h / (alpha * (1.0 - alpha)))
        df = int(x.shape[1])
        p = float(1.0 - stats.chi2.cdf(stat, df))
    except Exception:
        return {"stat": float("nan"), "p": float("nan"), "df": 0, "pass": False}
    return {"stat": stat, "p": p, "df": df, "lags": lags, "pass": bool(p > 0.05)}


def dm_test_hac(loss_a: pd.Series, loss_b: pd.Series, h: int = 1) -> Dict[str, Any]:
    common = loss_a.index.intersection(loss_b.index)
    d = (loss_a.loc[common] - loss_b.loc[common]).dropna().to_numpy(dtype=float)
    n = len(d)
    if n < 30:
        return {"n": n, "dbar": float("nan"), "stat": float("nan"), "p": float("nan")}
    dbar = float(np.mean(d))
    lag = max(1, int(math.floor(1.5 * n ** (1.0 / 3.0))))
    var = float(np.mean((d - dbar) ** 2))
    for k in range(1, lag + 1):
        cov = float(np.mean((d[k:] - dbar) * (d[:-k] - dbar)))
        var += 2.0 * (1.0 - k / (lag + 1.0)) * cov
    if var <= 0.0 or not np.isfinite(var):
        return {"n": n, "dbar": dbar, "stat": float("nan"), "p": float("nan"), "nw_lag": lag}
    stat = dbar / math.sqrt(var / n)
    if h > 1:
        stat *= math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    p = float(2.0 * (1.0 - stats.t.cdf(abs(stat), df=n - 1)))
    return {
        "n": n,
        "dbar": dbar,
        "stat": float(stat),
        "p": p,
        "nw_lag": lag,
        "harvey_abs_t_gt_3": bool(abs(stat) > HARVEY_ABS_T_THRESHOLD),
    }


def summarize(asset: str, alpha: float, y: pd.Series, forecasts: Dict[str, ForecastSeries]) -> Dict[str, Any]:
    per_model: Dict[str, Any] = {}
    for name, fs in forecasts.items():
        actual = y.loc[fs.var.index]
        kupiec = kupiec_pof(fs.violations, alpha)
        christ = christoffersen_independence(fs.violations)
        basel = basel_binomial_zone(fs.violations, alpha)
        dq = dq_test(actual, fs.var, alpha)
        per_model[name] = {
            "obs": int(len(fs.loss)),
            "mean_pinball": float(fs.loss.mean()),
            "violation_rate": float(fs.violations.mean()),
            "fit_failures": int(fs.fit_failures),
            "refits": int(fs.refits),
            "kupiec": kupiec,
            "christoffersen_independence": christ,
            "basel_binomial": basel,
            "dq": dq,
            "trinity_pass": bool(kupiec["pass"] and christ["pass"] and basel["pass"]),
            "var_dq_gate_pass": bool(kupiec["pass"] and christ["pass"] and basel["pass"] and dq["pass"]),
        }

    garch = "GJR-GARCH-SkewT"
    dm_vs_garch: Dict[str, Any] = {}
    for name, fs in forecasts.items():
        if name == garch:
            continue
        dm_vs_garch[f"{name}_vs_{garch}"] = dm_test_hac(fs.loss, forecasts[garch].loss)
    best_model = min(per_model, key=lambda k: float(per_model[k]["mean_pinball"]))
    gate_pass_models = [m for m, row in per_model.items() if bool(row["var_dq_gate_pass"])]
    return {
        "asset": asset,
        "alpha": alpha,
        "per_model": per_model,
        "dm_vs_garch": dm_vs_garch,
        "best_mean_pinball_model": best_model,
        "var_dq_gate_pass_models": gate_pass_models,
    }


def forecast_frame(asset: str, alpha: float, y: pd.Series, forecasts: Dict[str, ForecastSeries]) -> pd.DataFrame:
    rows = []
    for name, fs in forecasts.items():
        actual = y.loc[fs.var.index]
        rows.append(
            pd.DataFrame(
                {
                    "date": fs.var.index,
                    "asset": asset,
                    "alpha": alpha,
                    "model": name,
                    "return": actual.to_numpy(dtype=float),
                    "var": fs.var.to_numpy(dtype=float),
                    "pinball_loss": fs.loss.to_numpy(dtype=float),
                    "violation": fs.violations.to_numpy(dtype=int),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def build_overall(results: Dict[str, Any]) -> Dict[str, Any]:
    cells = results["by_asset_alpha"]
    caviar_models = ["CAViaR-SAV", "CAViaR-AS", "CAViaR-IG", "CAViaR-AD"]
    best_counts: Dict[str, int] = {}
    gate_counts: Dict[str, int] = {}
    caviar_harvey_wins_vs_garch = 0
    caviar_best_cells = 0
    for block in cells.values():
        best = block["best_mean_pinball_model"]
        best_counts[best] = best_counts.get(best, 0) + 1
        if best in caviar_models:
            caviar_best_cells += 1
        for model in block["var_dq_gate_pass_models"]:
            gate_counts[model] = gate_counts.get(model, 0) + 1
        for pair, dm in block["dm_vs_garch"].items():
            model = pair.split("_vs_")[0]
            if model in caviar_models and float(dm.get("dbar", float("nan"))) < 0.0 and bool(dm.get("harvey_abs_t_gt_3")):
                caviar_harvey_wins_vs_garch += 1

    if caviar_harvey_wins_vs_garch > 0:
        verdict = "CAVIAR_SIGNIFICANT_EDGE"
    elif caviar_best_cells > 0:
        verdict = "CONDITIONAL_CAVIAR_COMPETITIVE_NO_HARVEY_EDGE"
    else:
        verdict = "NULL_GARCH_OR_HS_COMPETITIVE"
    return {
        "best_mean_pinball_counts": best_counts,
        "var_dq_gate_pass_counts": gate_counts,
        "caviar_best_cells": caviar_best_cells,
        "caviar_harvey_wins_vs_garch": caviar_harvey_wins_vs_garch,
        "harvey_abs_t_threshold": HARVEY_ABS_T_THRESHOLD,
        "verdict": verdict,
    }


def plot_pinball(results: Dict[str, Any], out: Path) -> None:
    records = []
    for key, block in results["by_asset_alpha"].items():
        for model, row in block["per_model"].items():
            records.append({"cell": key, "model": model, "mean_pinball": row["mean_pinball"]})
    df = pd.DataFrame(records)
    cells = list(df["cell"].drop_duplicates())
    models = ["HS250", "CAViaR-SAV", "CAViaR-AS", "CAViaR-IG", "CAViaR-AD", "GJR-GARCH-SkewT"]
    colors = ["#4c78a8", "#59a14f", "#f28e2b", "#e15759", "#b07aa1", "#4e79a7"]
    x = np.arange(len(cells))
    width = 0.13
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for i, model in enumerate(models):
        vals = [
            float(df[(df["cell"] == cell) & (df["model"] == model)]["mean_pinball"].iloc[0])
            for cell in cells
        ]
        ax.bar(x + (i - 2.5) * width, vals, width=width, label=model, color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels(cells)
    ax.set_ylabel("Mean pinball loss")
    ax.set_title("K1651 VaR forecast loss: lower is better")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_violations(results: Dict[str, Any], out: Path) -> None:
    records = []
    for key, block in results["by_asset_alpha"].items():
        alpha = float(block["alpha"])
        for model, row in block["per_model"].items():
            records.append({"cell": key, "model": model, "alpha": alpha, "violation_rate": row["violation_rate"]})
    df = pd.DataFrame(records)
    cells = list(df["cell"].drop_duplicates())
    models = ["HS250", "CAViaR-SAV", "CAViaR-AS", "CAViaR-IG", "CAViaR-AD", "GJR-GARCH-SkewT"]
    colors = ["#4c78a8", "#59a14f", "#f28e2b", "#e15759", "#b07aa1", "#4e79a7"]
    x = np.arange(len(cells))
    width = 0.13
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for i, model in enumerate(models):
        vals = [
            float(df[(df["cell"] == cell) & (df["model"] == model)]["violation_rate"].iloc[0])
            for cell in cells
        ]
        ax.bar(x + (i - 2.5) * width, vals, width=width, label=model, color=colors[i])
    for i, cell in enumerate(cells):
        alpha = float(df[df["cell"] == cell]["alpha"].iloc[0])
        ax.hlines(alpha, i - 0.45, i + 0.45, color="#222222", linestyle="--", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(cells)
    ax.set_ylabel("Violation rate")
    ax.set_title("K1651 VaR coverage: bars vs dashed target")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-fetch", action="store_true")
    parser.add_argument("--cadence", choices=["year", "quarter", "month"], default="year")
    args = parser.parse_args()

    prices = fetch_prices(force_fetch=args.force_fetch)
    rets = log_returns(prices)
    print(
        f"[data] source=yfinance adjusted close rows={len(rets)} "
        f"first={rets.index.min().date()} last={rets.index.max().date()}",
        flush=True,
    )

    results: Dict[str, Any] = {
        "meta": {
            "experiment_id": EXPERIMENT_ID,
            "seed": SEED,
            "data_source": "Yahoo Finance adjusted close via yfinance",
            "price_cache": str(DATA_CACHE.relative_to(HERE)),
            "data_start": str(rets.index.min().date()),
            "data_end": str(rets.index.max().date()),
            "oos_start": str(OOS_START.date()),
            "assets": ASSETS,
            "alphas": list(ALPHAS),
            "models": ["HS250", "CAViaR-SAV", "CAViaR-AS", "CAViaR-IG", "CAViaR-AD", "GJR-GARCH-SkewT"],
            "refit_cadence": f"{args.cadence}_expanding",
            "lookahead_policy": (
                "Forecast at t uses model fit on index < t and recursion from r[t-1]; "
                "HS250 uses y.shift(1).rolling(250).quantile(alpha)."
            ),
            "dq_lags": DQ_LAGS,
            "harvey_abs_t_threshold": HARVEY_ABS_T_THRESHOLD,
            "literature_used": [
                "Engle and Manganelli (2004), CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles.",
                "Dumitrescu, Hurlin, Pham (2012), Backtesting Value-at-Risk: From Dynamic Quantile to Dynamic Binary Tests.",
                "Cai et al. (2026), CAViaR Model Selection via Adaptive Lasso.",
                "Forecasting Expected Shortfall and Value-at-Risk With Cross-Sectional Aggregation CAViaR-FZ (2025).",
            ],
            "es_scope_note": (
                "This experiment is VaR-only because vanilla CAViaR has no native ES forecast. "
                "No ES superiority claim is made; CAViaR-FZ/RES-CAViaR is the correct extension for joint VaR-ES."
            ),
        },
        "panels": {},
        "by_asset_alpha": {},
    }

    forecast_frames: List[pd.DataFrame] = []
    for asset in ASSETS:
        y = rets[asset].dropna()
        results["panels"][asset] = {
            "rows": int(len(y)),
            "first": str(y.index.min().date()),
            "last": str(y.index.max().date()),
            "oos_rows_available": int((y.index >= OOS_START).sum()),
        }
        for alpha in ALPHAS:
            print(f"[run] asset={asset} alpha={alpha:.0%}", flush=True)
            forecasts = run_models(y, alpha, cadence=args.cadence)
            key = f"{asset}_VaR{int(alpha * 100):02d}"
            block = summarize(asset, alpha, y, forecasts)
            results["by_asset_alpha"][key] = block
            forecast_frames.append(forecast_frame(asset, alpha, y, forecasts))
            for name, fs in forecasts.items():
                print(
                    f"  {name:16s} obs={len(fs.loss):4d} "
                    f"pinball={fs.loss.mean():.8f} viol={fs.violations.mean():.4f} "
                    f"refits={fs.refits} fail={fs.fit_failures}",
                    flush=True,
                )

    results["overall"] = build_overall(results)
    forecasts_df = pd.concat(forecast_frames, ignore_index=True)
    forecasts_df.to_parquet(FORECASTS_PATH, index=False)
    plot_pinball(results, HERE / "fig_k1651_pinball.png")
    plot_violations(results, HERE / "fig_k1651_violations.png")
    atomic_write_json(RESULTS_PATH, results)
    print(f"[write] {RESULTS_PATH}", flush=True)
    print(f"[write] {FORECASTS_PATH}", flush=True)
    print(f"[verdict] {results['overall']['verdict']}", flush=True)


if __name__ == "__main__":
    main()
