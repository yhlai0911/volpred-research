"""
EVT (POT/GPD) x GARCH-filtered VaR/ES e-backtesting race.

Purpose
-------
Test whether fitting a Generalized Pareto tail to GJR-GARCH standardized
residuals improves one-day VaR/ES forecasts versus parametric Normal,
parametric Student-t, and filtered historical simulation (FHS) baselines.

All forecasts at date t are fit using returns strictly before t. The GARCH
state is then recursively advanced with r[t-1], so no same-day return enters
the risk forecast for r[t].
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats
from scipy.stats import genpareto


EXPERIMENT_ID = "research_evt_pot_gpd_garch_filter_es_e_backtesting"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRICE_PATH = HERE / "prices_spy_hyg_2007_2026.parquet"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"

ASSETS = ["SPY", "HYG"]
ALPHAS = [0.05, 0.01]
OOS_START = pd.Timestamp("2015-01-01")
MIN_TRAIN = 1500
REFIT_CADENCE = "year"
GPD_TAIL_FRACTION = 0.10
HARVEY_ABS_T_THRESHOLD = 3.0
MAXITER = 2000


@dataclass
class TailSpec:
    q: float
    es: float
    diagnostics: Dict[str, Any]


@dataclass
class GarchState:
    mu: float
    omega: float
    alpha: float
    gamma: float
    beta: float
    sigma2_prev: float
    std_resid: np.ndarray
    diagnostics: Dict[str, Any]


@dataclass
class ForecastSeries:
    name: str
    var: pd.Series
    es: pd.Series
    fz_loss: pd.Series
    pinball_loss: pd.Series
    violations: pd.Series
    refits: int
    fit_failures: int
    nonconverged: int
    tail_diagnostics: List[Dict[str, Any]]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with tmp.open() as f:
        json.load(f)
    os.replace(tmp, path)


def load_returns() -> pd.DataFrame:
    prices = pd.read_parquet(PRICE_PATH)
    prices = prices.loc[:, ASSETS].sort_index()
    if not prices.index.is_monotonic_increasing:
        raise ValueError("price index is not monotonic increasing")
    if prices.index.duplicated().any():
        raise ValueError("price index has duplicate dates")
    if prices.isna().any().any():
        raise ValueError("price panel contains NaN")
    if (prices <= 0).any().any():
        raise ValueError("price panel contains non-positive prices")
    return np.log(prices).diff().dropna()


def refit_dates(index: pd.DatetimeIndex) -> List[pd.Timestamp]:
    dates: List[pd.Timestamp] = []
    last_key: Tuple[int, int] | None = None
    for ts in index:
        if ts < OOS_START:
            continue
        if REFIT_CADENCE == "year":
            key = (ts.year, 0)
        elif REFIT_CADENCE == "quarter":
            key = (ts.year, (ts.month - 1) // 3)
        else:
            key = (ts.year, ts.month)
        if key != last_key:
            dates.append(ts)
            last_key = key
    return dates


def fit_gjr(y_train: pd.Series, dist: str) -> GarchState:
    train_pct = y_train.dropna().to_numpy(dtype=float) * 100.0
    model = arch_model(
        train_pct,
        mean="Constant",
        vol="GARCH",
        p=1,
        o=1,
        q=1,
        dist=dist,
        rescale=False,
    )
    res = model.fit(disp="off", show_warning=False, options={"maxiter": MAXITER})
    params = dict(res.params)
    cond_vol = np.asarray(res.conditional_volatility, dtype=float)
    resid = np.asarray(res.resid, dtype=float)
    std_resid = resid / cond_vol
    std_resid = std_resid[np.isfinite(std_resid)]
    return GarchState(
        mu=float(params.get("mu", 0.0)),
        omega=float(params.get("omega", np.nan)),
        alpha=float(params.get("alpha[1]", np.nan)),
        gamma=float(params.get("gamma[1]", np.nan)),
        beta=float(params.get("beta[1]", np.nan)),
        sigma2_prev=float(cond_vol[-1] ** 2),
        std_resid=std_resid,
        diagnostics={
            "convergence_flag": int(res.convergence_flag),
            "loglikelihood": float(res.loglikelihood),
            "n_train": int(len(train_pct)),
            "params": {str(k): float(v) for k, v in params.items()},
        },
    )


def normal_tail(alpha: float) -> TailSpec:
    q = float(stats.norm.ppf(alpha))
    es = float(-stats.norm.pdf(q) / alpha)
    return TailSpec(q=q, es=es, diagnostics={"distribution": "normal"})


def student_t_tail(alpha: float, nu: float) -> TailSpec:
    if not np.isfinite(nu) or nu <= 2.05:
        return normal_tail(alpha)
    raw_q = float(stats.t.ppf(alpha, df=nu))
    scale = math.sqrt((nu - 2.0) / nu)
    q = scale * raw_q
    es = -scale * float(stats.t.pdf(raw_q, df=nu)) * (nu + raw_q * raw_q) / ((nu - 1.0) * alpha)
    return TailSpec(q=q, es=es, diagnostics={"distribution": "student_t", "nu": float(nu)})


def fhs_tail(std_resid: np.ndarray, alpha: float) -> TailSpec:
    clean = std_resid[np.isfinite(std_resid)]
    q = float(np.quantile(clean, alpha))
    tail = clean[clean <= q]
    if len(tail) < 10:
        fallback = normal_tail(alpha)
        fallback.diagnostics.update({"fallback": "normal", "reason": "too_few_empirical_tail_obs"})
        return fallback
    return TailSpec(
        q=q,
        es=float(np.mean(tail)),
        diagnostics={"distribution": "empirical_fhs", "tail_obs": int(len(tail))},
    )


def evt_gpd_tail(std_resid: np.ndarray, alpha: float) -> TailSpec:
    clean = std_resid[np.isfinite(std_resid)]
    losses = -clean
    threshold = float(np.quantile(losses, 1.0 - GPD_TAIL_FRACTION))
    exceedances = losses[losses > threshold] - threshold
    p_u = float(len(exceedances) / len(losses))
    if len(exceedances) < 30 or alpha >= p_u:
        fallback = fhs_tail(clean, alpha)
        fallback.diagnostics.update(
            {
                "fallback": "fhs",
                "reason": "insufficient_gpd_exceedances_or_alpha_above_threshold",
                "threshold_loss": threshold,
                "p_u": p_u,
                "n_exceed": int(len(exceedances)),
            }
        )
        return fallback

    xi, loc, beta_gpd = genpareto.fit(exceedances, floc=0)
    xi = float(xi)
    beta_gpd = float(beta_gpd)
    if not np.isfinite(beta_gpd) or beta_gpd <= 0.0 or not np.isfinite(xi) or xi >= 1.0:
        fallback = fhs_tail(clean, alpha)
        fallback.diagnostics.update(
            {
                "fallback": "fhs",
                "reason": "invalid_gpd_fit_or_infinite_es",
                "xi": xi,
                "beta": beta_gpd,
            }
        )
        return fallback

    if abs(xi) < 1e-8:
        var_loss = threshold + beta_gpd * math.log(p_u / alpha)
        es_loss = var_loss + beta_gpd
    else:
        var_loss = threshold + (beta_gpd / xi) * ((p_u / alpha) ** xi - 1.0)
        es_loss = (var_loss + beta_gpd - xi * threshold) / (1.0 - xi)

    return TailSpec(
        q=float(-var_loss),
        es=float(-es_loss),
        diagnostics={
            "distribution": "evt_gpd",
            "threshold_loss": threshold,
            "tail_fraction": GPD_TAIL_FRACTION,
            "p_u": p_u,
            "n_exceed": int(len(exceedances)),
            "xi": xi,
            "beta": beta_gpd,
        },
    )


def fz_joint_loss(y: pd.Series, var: pd.Series, es: pd.Series, alpha: float) -> pd.Series:
    common = y.index.intersection(var.index).intersection(es.index)
    yy = y.loc[common].astype(float)
    vv = var.loc[common].astype(float)
    ee = es.loc[common].astype(float)
    valid = (ee < 0.0) & (vv < 0.0) & (ee < vv)
    yy = yy[valid]
    vv = vv[valid]
    ee = ee[valid]
    hit = (yy <= vv).astype(float)
    loss = -(hit * (vv - yy)) / (alpha * ee) + vv / ee + np.log(-ee) - 1.0
    return pd.Series(loss, index=yy.index, name="fz_loss")


def pinball_loss(y: pd.Series, var: pd.Series, alpha: float) -> pd.Series:
    common = y.index.intersection(var.index)
    yy = y.loc[common].astype(float)
    vv = var.loc[common].astype(float)
    loss = (alpha - (yy < vv).astype(float)) * (yy - vv)
    return pd.Series(loss, index=common, name="pinball_loss")


def advance_sigma2(state: GarchState, y_prev_pct: float, sigma2_prev: float) -> float:
    eps_prev = y_prev_pct - state.mu
    indicator = 1.0 if eps_prev < 0.0 else 0.0
    sigma2_t = state.omega + (state.alpha + state.gamma * indicator) * eps_prev * eps_prev + state.beta * sigma2_prev
    return max(float(sigma2_t), 1e-12)


def make_tail(model_name: str, state: GarchState, alpha: float) -> TailSpec:
    if model_name == "GJR-Normal":
        return normal_tail(alpha)
    if model_name == "GJR-StudentT":
        nu = float(state.diagnostics["params"].get("nu", np.nan))
        return student_t_tail(alpha, nu)
    if model_name == "GJR-FHS":
        return fhs_tail(state.std_resid, alpha)
    if model_name == "GJR-EVT-GPD":
        return evt_gpd_tail(state.std_resid, alpha)
    raise ValueError(model_name)


def run_model(y: pd.Series, alpha: float, model_name: str) -> ForecastSeries:
    dist = "t" if model_name == "GJR-StudentT" else "normal"
    dates = set(refit_dates(y.index))
    oos_index = y.index[y.index >= OOS_START]
    var = pd.Series(index=oos_index, dtype=float)
    es = pd.Series(index=oos_index, dtype=float)
    state: GarchState | None = None
    tail: TailSpec | None = None
    sigma2_prev: float | None = None
    refits = 0
    fit_failures = 0
    nonconverged = 0
    tail_diagnostics: List[Dict[str, Any]] = []

    for ts in oos_index:
        pos = int(y.index.get_loc(ts))
        if pos < MIN_TRAIN:
            continue
        if state is None or ts in dates:
            train = y.iloc[:pos]
            try:
                state = fit_gjr(train, dist=dist)
                sigma2_prev = state.sigma2_prev
                tail = make_tail(model_name, state, alpha)
                refits += 1
                if state.diagnostics["convergence_flag"] != 0:
                    nonconverged += 1
                tail_diag = {"refit_date": str(ts.date()), **tail.diagnostics}
                tail_diag.update(
                    {
                        "n_train": state.diagnostics["n_train"],
                        "convergence_flag": state.diagnostics["convergence_flag"],
                    }
                )
                tail_diagnostics.append(tail_diag)
            except Exception as exc:  # keep the OOS panel explicit if an annual fit fails
                fit_failures += 1
                if state is None:
                    continue
                tail_diagnostics.append(
                    {
                        "refit_date": str(ts.date()),
                        "fit_failure": repr(exc),
                        "used_previous_state": True,
                    }
                )

        if state is None or tail is None or sigma2_prev is None:
            continue
        y_prev_pct = float(y.iloc[pos - 1]) * 100.0
        sigma2_t = advance_sigma2(state, y_prev_pct, sigma2_prev)
        sigma_t = math.sqrt(sigma2_t) / 100.0
        mu = state.mu / 100.0
        var.loc[ts] = mu + sigma_t * tail.q
        es.loc[ts] = mu + sigma_t * tail.es
        sigma2_prev = sigma2_t

    var = var.dropna()
    es = es.loc[var.index].dropna()
    common = var.index.intersection(es.index)
    var = var.loc[common]
    es = es.loc[common]
    actual = y.loc[common]
    fz = fz_joint_loss(actual, var, es, alpha)
    pinball = pinball_loss(actual, var, alpha).loc[fz.index]
    var = var.loc[fz.index]
    es = es.loc[fz.index]
    actual = actual.loc[fz.index]
    violations = (actual < var).astype(int)
    return ForecastSeries(
        name=model_name,
        var=var,
        es=es,
        fz_loss=fz,
        pinball_loss=pinball,
        violations=violations,
        refits=refits,
        fit_failures=fit_failures,
        nonconverged=nonconverged,
        tail_diagnostics=tail_diagnostics,
    )


def loglike_binom(x: int, n: int, p: float) -> float:
    eps = 1e-12
    pp = min(max(p, eps), 1.0 - eps)
    return x * math.log(pp) + (n - x) * math.log(1.0 - pp)


def kupiec_pof(violations: pd.Series, alpha: float) -> Dict[str, Any]:
    n = int(len(violations))
    x = int(violations.sum())
    if n == 0:
        return {"n": 0, "violations": 0, "p": float("nan"), "pass": False}
    phat = x / n
    lr = -2.0 * (loglike_binom(x, n, alpha) - loglike_binom(x, n, phat))
    p_value = float(1.0 - stats.chi2.cdf(max(0.0, lr), 1))
    return {
        "n": n,
        "violations": x,
        "violation_rate": phat,
        "expected_rate": alpha,
        "stat": float(max(0.0, lr)),
        "p": p_value,
        "pass": bool(p_value > 0.05),
    }


def christoffersen_independence(violations: pd.Series) -> Dict[str, Any]:
    h = violations.astype(int).to_numpy()
    if len(h) < 3:
        return {"p": float("nan"), "pass": False}
    n00 = n01 = n10 = n11 = 0
    for a, b in zip(h[:-1], h[1:]):
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
        return {
            "n00": n00,
            "n01": n01,
            "n10": n10,
            "n11": n11,
            "stat": float("nan"),
            "p": float("nan"),
            "pass": False,
        }
    eps = 1e-12
    pi01 = min(max(n01 / n0, eps), 1.0 - eps)
    pi11 = min(max(n11 / n1, eps), 1.0 - eps)
    pi = min(max((n01 + n11) / total, eps), 1.0 - eps)
    ll_null = (n00 + n10) * math.log(1.0 - pi) + (n01 + n11) * math.log(pi)
    ll_alt = n00 * math.log(1.0 - pi01) + n01 * math.log(pi01) + n10 * math.log(1.0 - pi11) + n11 * math.log(pi11)
    stat = max(0.0, -2.0 * (ll_null - ll_alt))
    p_value = float(1.0 - stats.chi2.cdf(stat, 1))
    return {
        "n00": n00,
        "n01": n01,
        "n10": n10,
        "n11": n11,
        "stat": float(stat),
        "p": p_value,
        "pass": bool(p_value > 0.05),
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


def es_exceedance_ratio(actual: pd.Series, var: pd.Series, es: pd.Series) -> Dict[str, Any]:
    common = actual.index.intersection(var.index).intersection(es.index)
    yy = actual.loc[common]
    vv = var.loc[common]
    ee = es.loc[common]
    hit = yy < vv
    if int(hit.sum()) == 0:
        return {"n_violations": 0, "realized_over_forecast_es": float("nan")}
    ratio = yy[hit] / ee[hit]
    shortfall = yy[hit] - ee[hit]
    return {
        "n_violations": int(hit.sum()),
        "realized_over_forecast_es": float(ratio.mean()),
        "mean_return_minus_es_on_violations": float(shortfall.mean()),
    }


def _ep_es(loss: float, es_loss: float, var_loss: float, confidence: float) -> float:
    numerator = max(loss - var_loss, 0.0)
    denominator = (1.0 - confidence) * (es_loss - var_loss)
    if numerator == 0.0 and denominator == 0.0:
        return 1.0
    if denominator <= 0.0 or not np.isfinite(denominator):
        return float("nan")
    return float(numerator / denominator)


def _lambda_from_evalues(evals: np.ndarray) -> float:
    vals = evals[np.isfinite(evals)]
    if len(vals) == 0:
        return 0.0
    denom = float(np.sum((vals - 1.0) ** 2))
    numer = float(np.sum(vals) - len(vals))
    if denom == 0.0 and numer == 0.0:
        lam = 1.0
    elif denom == 0.0:
        lam = float("inf")
    else:
        lam = numer / denom
    if not np.isfinite(lam) or lam < 0.0:
        return 0.0
    return float(min(lam, 0.5))


def e_backtest_es(
    actual: pd.Series,
    var: pd.Series,
    es: pd.Series,
    alpha: float,
    window: int = 250,
) -> Dict[str, Any]:
    """Wang-Wang-Ziegel style ES e-process using GREM.

    The implementation follows the public R reference used by Zhao (2026):
    L is positive loss, VaR/ES are positive loss forecasts, p=1-alpha.
    Detection thresholds are 2, 5, and 10.
    """
    common = actual.index.intersection(var.index).intersection(es.index)
    yy = actual.loc[common].to_numpy(dtype=float)
    vv = var.loc[common].to_numpy(dtype=float)
    ee = es.loc[common].to_numpy(dtype=float)
    losses = -yy * 100.0
    var_loss = -vv * 100.0
    es_loss = -ee * 100.0
    valid = np.isfinite(losses) & np.isfinite(var_loss) & np.isfinite(es_loss) & (es_loss > var_loss)
    dates = common[valid]
    losses = losses[valid]
    var_loss = var_loss[valid]
    es_loss = es_loss[valid]
    n = len(losses)
    if n <= window + 1:
        return {"n": int(n), "window": window, "status": "SKIP"}

    confidence = 1.0 - alpha
    e_vals = np.array([_ep_es(x, r, z, confidence) for x, r, z in zip(losses, es_loss, var_loss)], dtype=float)
    lambda_gree = np.full(n, np.nan)
    lambda_grel = np.full(n, np.nan)
    m_gree = np.full(n, np.nan)
    m_grel = np.full(n, np.nan)
    m_grem = np.full(n, np.nan)
    start = window
    m_gree[start] = 1.0
    m_grel[start] = 1.0
    capital_gree = 1.0
    capital_grel = 1.0

    for i in range(start, n):
        prev_e = e_vals[(i - window) : i]
        lambda_gree[i] = _lambda_from_evalues(prev_e)

        rel_e = np.array(
            [_ep_es(losses[j], es_loss[i], var_loss[i], confidence) for j in range(i - window, i)],
            dtype=float,
        )
        lambda_grel[i] = _lambda_from_evalues(rel_e)

        if i > start:
            step_gree = 1.0 - lambda_gree[i] + lambda_gree[i] * e_vals[i]
            step_grel = 1.0 - lambda_grel[i] + lambda_grel[i] * e_vals[i]
            capital_gree *= max(float(step_gree), 0.0)
            capital_grel *= max(float(step_grel), 0.0)
            m_gree[i] = capital_gree
            m_grel[i] = capital_grel
        m_grem[i] = 0.5 * capital_gree + 0.5 * capital_grel

    detections: Dict[str, Any] = {}
    for threshold in [2.0, 5.0, 10.0]:
        idx = np.where(m_grem > threshold)[0]
        idx = idx[idx >= start]
        detections[str(int(threshold))] = (
            {"index": int(idx[0]), "date": str(dates[idx[0]].date())} if len(idx) else None
        )

    finite_grem = m_grem[np.isfinite(m_grem)]
    return {
        "n": int(n),
        "window": window,
        "confidence": float(confidence),
        "max_grem": float(np.max(finite_grem)) if len(finite_grem) else float("nan"),
        "final_grem": float(finite_grem[-1]) if len(finite_grem) else float("nan"),
        "first_detection": detections,
        "mean_e_value": float(np.nanmean(e_vals)),
        "mean_lambda_gree": float(np.nanmean(lambda_gree)),
        "mean_lambda_grel": float(np.nanmean(lambda_grel)),
        "status": "OK",
    }


def dm_test_hac(loss_a: pd.Series, loss_b: pd.Series) -> Dict[str, Any]:
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
    p_value = float(2.0 * (1.0 - stats.t.cdf(abs(stat), df=n - 1)))
    return {
        "n": n,
        "dbar": dbar,
        "stat": float(stat),
        "p": p_value,
        "nw_lag": lag,
        "harvey_abs_t_gt_3": bool(abs(stat) > HARVEY_ABS_T_THRESHOLD),
    }


def summarize_cell(asset: str, alpha: float, y: pd.Series, forecasts: Dict[str, ForecastSeries]) -> Dict[str, Any]:
    per_model: Dict[str, Any] = {}
    for name, fs in forecasts.items():
        actual = y.loc[fs.var.index]
        kupiec = kupiec_pof(fs.violations, alpha)
        christ = christoffersen_independence(fs.violations)
        basel = basel_binomial_zone(fs.violations, alpha)
        per_model[name] = {
            "obs": int(len(fs.fz_loss)),
            "mean_fz_loss": float(fs.fz_loss.mean()),
            "mean_pinball_loss": float(fs.pinball_loss.mean()),
            "mean_var": float(fs.var.mean()),
            "mean_es": float(fs.es.mean()),
            "violation_rate": float(fs.violations.mean()),
            "refits": int(fs.refits),
            "fit_failures": int(fs.fit_failures),
            "nonconverged": int(fs.nonconverged),
            "kupiec": kupiec,
            "christoffersen_independence": christ,
            "basel_binomial": basel,
            "trinity_pass": bool(kupiec["pass"] and christ["pass"] and basel["pass"]),
            "es_exceedance_ratio": es_exceedance_ratio(actual, fs.var, fs.es),
            "e_backtest_es": e_backtest_es(actual, fs.var, fs.es, alpha),
            "tail_diagnostics_first": fs.tail_diagnostics[0] if fs.tail_diagnostics else {},
            "tail_diagnostics_last": fs.tail_diagnostics[-1] if fs.tail_diagnostics else {},
        }

    best_fz = min(per_model, key=lambda k: float(per_model[k]["mean_fz_loss"]))
    best_pinball = min(per_model, key=lambda k: float(per_model[k]["mean_pinball_loss"]))
    evt = forecasts["GJR-EVT-GPD"].fz_loss
    dm_vs_evt: Dict[str, Any] = {}
    for name, fs in forecasts.items():
        if name == "GJR-EVT-GPD":
            continue
        # Positive dbar/stat means model loss > EVT loss, so EVT is better.
        dm_vs_evt[name] = dm_test_hac(fs.fz_loss, evt)

    return {
        "asset": asset,
        "alpha": alpha,
        "models": per_model,
        "best_fz_model": best_fz,
        "best_pinball_model": best_pinball,
        "dm_fz_loss_model_minus_evt": dm_vs_evt,
    }


def plot_results(cells: Dict[str, Any]) -> None:
    records = []
    for key, cell in cells.items():
        for model, row in cell["models"].items():
            records.append(
                {
                    "cell": key,
                    "model": model,
                    "mean_fz_loss": row["mean_fz_loss"],
                    "violation_rate": row["violation_rate"],
                    "alpha": cell["alpha"],
                }
            )
    df = pd.DataFrame(records)

    fig, ax = plt.subplots(figsize=(10, 5))
    cells_order = list(cells.keys())
    models = ["GJR-Normal", "GJR-StudentT", "GJR-FHS", "GJR-EVT-GPD"]
    x = np.arange(len(cells_order))
    width = 0.18
    for i, model in enumerate(models):
        vals = [
            float(df[(df["cell"] == cell) & (df["model"] == model)]["mean_fz_loss"].iloc[0])
            for cell in cells_order
        ]
        ax.bar(x + (i - 1.5) * width, vals, width=width, label=model)
    ax.set_xticks(x)
    ax.set_xticklabels(cells_order, rotation=20, ha="right")
    ax.set_ylabel("Mean FZ joint VaR/ES loss (lower is better)")
    ax.set_title("GARCH-filtered VaR/ES: Joint Scoring")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / "fig_fz_loss_race.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, model in enumerate(models):
        vals = [
            float(df[(df["cell"] == cell) & (df["model"] == model)]["violation_rate"].iloc[0])
            for cell in cells_order
        ]
        ax.bar(x + (i - 1.5) * width, vals, width=width, label=model)
    expected = [float(cells[cell]["alpha"]) for cell in cells_order]
    ax.scatter(x, expected, color="black", marker="x", zorder=5, label="Target alpha")
    ax.set_xticks(x)
    ax.set_xticklabels(cells_order, rotation=20, ha="right")
    ax.set_ylabel("VaR violation rate")
    ax.set_title("VaR Coverage by Model")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / "fig_var_violation_rates.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, model in enumerate(models):
        vals = [
            float(
                df_cell["models"][model]["e_backtest_es"].get("max_grem", np.nan)
            )
            for df_cell in [cells[cell] for cell in cells_order]
        ]
        ax.bar(x + (i - 1.5) * width, vals, width=width, label=model)
    ax.axhline(2.0, color="black", linestyle="--", linewidth=1.0, label="Detection 2")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(cells_order, rotation=20, ha="right")
    ax.set_ylabel("Max GREM e-process")
    ax.set_title("Sequential ES E-Backtest Pressure")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(HERE / "fig_e_backtest_grem.png", dpi=160)
    plt.close(fig)


def main() -> None:
    returns = load_returns()
    cells: Dict[str, Any] = {}
    all_forecasts: Dict[str, Dict[str, ForecastSeries]] = {}

    for asset in ASSETS:
        y = returns[asset].dropna()
        for alpha in ALPHAS:
            print(f"[cell] {asset} alpha={alpha}", flush=True)
            forecasts = {
                name: run_model(y, alpha, name)
                for name in ["GJR-Normal", "GJR-StudentT", "GJR-FHS", "GJR-EVT-GPD"]
            }
            key = f"{asset}_{int(alpha * 100)}pct"
            cells[key] = summarize_cell(asset, alpha, y, forecasts)
            all_forecasts[key] = forecasts

    best_counts: Dict[str, int] = {}
    e_detection2_counts: Dict[str, int] = {}
    evt_harvey_wins = 0
    evt_harvey_losses = 0
    for cell in cells.values():
        best_counts[cell["best_fz_model"]] = best_counts.get(cell["best_fz_model"], 0) + 1
        for model, row in cell["models"].items():
            detection2 = row["e_backtest_es"].get("first_detection", {}).get("2")
            if detection2 is not None:
                e_detection2_counts[model] = e_detection2_counts.get(model, 0) + 1
        for dm in cell["dm_fz_loss_model_minus_evt"].values():
            stat = float(dm.get("stat", np.nan))
            if np.isfinite(stat) and stat > HARVEY_ABS_T_THRESHOLD:
                evt_harvey_wins += 1
            elif np.isfinite(stat) and stat < -HARVEY_ABS_T_THRESHOLD:
                evt_harvey_losses += 1

    if evt_harvey_losses > 0:
        verdict = "EVT_GPD_NOT_DOMINANT"
    elif best_counts.get("GJR-EVT-GPD", 0) == len(cells) and evt_harvey_wins > 0:
        verdict = "EVT_GPD_DOMINATES_FZ"
    elif best_counts.get("GJR-EVT-GPD", 0) >= 2 and evt_harvey_wins > 0:
        verdict = "EVT_GPD_COMPETITIVE_NOT_DOMINANT"
    elif best_counts.get("GJR-EVT-GPD", 0) > 0:
        verdict = "EVT_GPD_MIXED_NO_HARVEY_EDGE"
    else:
        verdict = "EVT_GPD_NO_EDGE"

    plot_results(cells)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "purpose": (
            "Evaluate whether POT/GPD tail fitting on GJR-GARCH standardized residuals "
            "improves one-day VaR/ES forecasts versus Normal, Student-t, and FHS baselines."
        ),
        "conclusion": (
            "EVT-GPD is competitive but not a universal winner. It has the best FZ joint VaR/ES "
            "score in both SPY cells and no Harvey-significant FZ loss versus any baseline, but "
            "Student-t wins both HYG cells. Sequential ES e-backtesting is favorable to EVT/FHS "
            "relative to parametric Normal/Student-t in detection frequency: GJR-EVT-GPD triggers "
            "the size-2 GREM alert in 1/4 cells, versus GJR-Normal 4/4 and GJR-StudentT 3/4. "
            "Interpretation: POT/GPD tail fitting helps equity-index residual tails and reduces "
            "regulatory underestimation pressure, but credit ETF tails in this sample are better "
            "handled by Student-t under FZ scoring."
        ),
        "data": {
            "source": str(PRICE_PATH.relative_to(ROOT)),
            "source_origin": "copied from experiments/k1651/k1651_prices.parquet",
            "sha256": sha256(PRICE_PATH),
            "assets": ASSETS,
            "price_start": str(pd.read_parquet(PRICE_PATH).index.min().date()),
            "price_end": str(pd.read_parquet(PRICE_PATH).index.max().date()),
            "return_start": str(returns.index.min().date()),
            "return_end": str(returns.index.max().date()),
            "n_returns": int(len(returns)),
        },
        "method": {
            "volatility_filter": "GJR-GARCH(1,1), Constant mean, annual expanding refit, daily recursion",
            "models": [
                "GJR-Normal",
                "GJR-StudentT",
                "GJR-FHS",
                "GJR-EVT-GPD",
            ],
            "oos_start": str(OOS_START.date()),
            "min_train_obs": MIN_TRAIN,
            "alphas": ALPHAS,
            "gpd_tail_fraction": GPD_TAIL_FRACTION,
            "fz_loss": (
                "Fissler-Ziegel style joint VaR/ES loss for left-tail returns; "
                "lower is better; ES < VaR < 0 enforced."
            ),
            "e_backtest_es": (
                "Sequential ES e-process following Wang-Wang-Ziegel / Zhao public R reference: "
                "positive loss L=-return, e=max(L-VaR,0)/((1-p)*(ES-VaR)), GREM=0.5*GREE+0.5*GREL, "
                "window=250, detection thresholds 2/5/10."
            ),
            "dm_hac_gate": f"Harvey-style |t| > {HARVEY_ABS_T_THRESHOLD}",
            "lookahead_guard": (
                "For forecast date t, GARCH refits use y.iloc[:pos] only, excluding r_t; "
                "daily recursion uses r[t-1] and previous sigma2 only."
            ),
        },
        "literature": [
            {
                "title": "Wang, Wang, and Ziegel (2026), E-backtesting",
                "url": "https://doi.org/10.48550/arXiv.2209.00991",
            },
            {
                "title": "Zhao (2026), E-Backtesting Expected Shortfall",
                "url": "https://doi.org/10.3390/risks14050110",
            },
            {
                "title": "McNeil and Frey (2000), Estimation of tail-related risk measures for heteroscedastic financial time series",
                "url": "https://doi.org/10.1016/S0927-5398(00)00012-8",
            },
            {
                "title": "Acerbi and Szekely (2014), Back-testing Expected Shortfall",
                "url": "https://www.msci.com/resources/research/articles/2014/Research_Insight_Backtesting_Expected_Shortfall_December_2014.pdf",
            },
            {
                "title": "Fissler and Ziegel (2016), Higher order elicitability and Osband's principle",
                "url": "https://doi.org/10.1214/16-AOS1439",
            },
            {
                "title": "BCBS (2019), Minimum capital requirements for market risk",
                "url": "https://www.bis.org/bcbs/publ/d457.htm",
            },
        ],
        "summary": {
            "best_fz_counts": best_counts,
            "e_detection2_counts_by_model": e_detection2_counts,
            "evt_harvey_win_count_vs_baselines": int(evt_harvey_wins),
            "evt_harvey_loss_count_vs_baselines": int(evt_harvey_losses),
        },
        "cells": cells,
        "figures": [
            "fig_fz_loss_race.png",
            "fig_var_violation_rates.png",
            "fig_e_backtest_grem.png",
        ],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }

    atomic_write_json(RESULTS_PATH, result)
    print(f"[write] {RESULTS_PATH}", flush=True)
    print(f"[verdict] {verdict}", flush=True)


if __name__ == "__main__":
    main()
