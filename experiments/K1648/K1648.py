"""K1648: QML/Kalman stochastic-volatility class comparison.

This experiment tests whether a tractable stochastic-volatility (SV) family can
beat standard GARCH-family baselines in one-day-ahead daily variance and VaR
forecasts.

Models:
  - EWMA(0.94)
  - GARCH(1,1), Normal innovations
  - GJR-GARCH(1,1), Student-t innovations
  - SV-KF: log-squared-return QML stochastic volatility estimated by Kalman
    filter on log(r_t^2)
  - TSV-KF: SV-KF plus threshold/leverage state term 1[r_{t-1}<0]
  - RSV-KF: SV-KF plus an additional OHLC Parkinson-range log-variance
    measurement

Forecast alignment:
  Every forecast for day t is generated before observing day-t return. The
  Kalman and GARCH states are updated with day-t data only after the forecast is
  recorded, so the information set is t-1. This is equivalent to the required
  signal.shift(1) convention for a one-step forecast.
"""

from __future__ import annotations

import json
import math
import os
import sys
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

from volpred.evaluation.statistical_tests import christoffersen_test, kupiec_test
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.simplefilter("ignore", category=RuntimeWarning)

SEED = 42
RNG = np.random.default_rng(SEED)
HERE = Path(__file__).resolve().parent
DATA_CACHE = HERE / "K1648_ohlc_cache.parquet"
RESULTS_PATH = HERE / "K1648_results.json"

ASSETS = ["SPY", "TLT", "HYG"]
START = "2010-01-01"
END = "2026-07-07"
OOS_START = pd.Timestamp("2018-01-02")
MIN_TRAIN = 1000
ALPHAS = [0.05, 0.01]
MODELS = ["EWMA_094", "GARCH_N", "GJR_T", "SV_KF", "TSV_KF", "RSV_KF"]
SV_MODELS = {"SV_KF", "TSV_KF", "RSV_KF"}
SV_CONVERGENCE_THRESHOLD = 0.95

LOG_CHI2_MEAN = -1.2703628454614782
LOG_CHI2_VAR = math.pi**2 / 2.0
EPS_VAR = 1e-10
BOUND_TOL = 1e-5


def warn(msg: str) -> None:
    print(f"[K1648] WARN {msg}", file=sys.stderr)


def fetch_ohlc(force: bool = False) -> pd.DataFrame:
    if DATA_CACHE.exists() and not force:
        return pd.read_parquet(DATA_CACHE)
    import yfinance as yf

    raw = yf.download(
        ASSETS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty OHLC panel")
    raw = raw.sort_index()
    DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(DATA_CACHE)
    return raw


def _field(raw: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        return raw[(field, ticker)].astype(float)
    return raw[field].astype(float)


def build_panel(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    close = _field(raw, "Close", ticker)
    high = _field(raw, "High", ticker)
    low = _field(raw, "Low", ticker)

    ret = 100.0 * np.log(close).diff()
    log_hl = np.log(high / low)
    parkinson_var = (100.0**2) * (log_hl**2) / (4.0 * math.log(2.0))

    panel = pd.DataFrame(
        {
            "ret": ret,
            "r2": ret**2,
            "range_var": parkinson_var,
        },
        index=raw.index,
    )
    panel["log_r2"] = np.log(np.maximum(panel["r2"], EPS_VAR))
    panel["log_range_var"] = np.log(np.maximum(panel["range_var"], EPS_VAR))
    return panel.replace([np.inf, -np.inf], np.nan).dropna()


def refit_dates(index: pd.DatetimeIndex) -> set[pd.Timestamp]:
    oos = index[index >= OOS_START]
    first_by_year: list[pd.Timestamp] = []
    seen: set[int] = set()
    for dt in oos:
        if dt.year not in seen:
            first_by_year.append(dt)
            seen.add(dt.year)
    return set(first_by_year)


def pinball_loss(y: np.ndarray, q: np.ndarray, alpha: float) -> np.ndarray:
    err = y - q
    return np.where(err >= 0, alpha * err, (alpha - 1.0) * err)


@dataclass
class ArchState:
    omega: float
    alpha: float
    beta: float
    gamma: float
    last_var: float
    last_ret: float
    q_emp: dict[str, float]


@dataclass
class EwmaState:
    lam: float
    last_var: float
    last_ret: float
    q_emp: dict[str, float]


@dataclass
class SvParams:
    mu: float
    phi: float
    q: float
    gamma: float
    c2: float
    r2_meas: float
    model: str


@dataclass
class SvState:
    params: SvParams
    h_filt: float
    p_filt: float
    last_ret: float
    q_emp: dict[str, float]
    fit_info: dict[str, Any]


def ewma_train_variance(ret: np.ndarray, lam: float = 0.94) -> np.ndarray:
    out = np.empty(len(ret))
    out[:] = np.nan
    init = float(np.nanvar(ret[: min(250, len(ret))]))
    last_var = max(init, EPS_VAR)
    last_ret = float(ret[0])
    for i in range(len(ret)):
        out[i] = max(last_var, EPS_VAR)
        last_var = lam * last_var + (1.0 - lam) * float(ret[i - 1 if i > 0 else 0]) ** 2
        last_ret = float(ret[i])
    if not np.isfinite(last_ret):
        warn("EWMA last_ret was non-finite; using zero for next forecast")
        last_ret = 0.0
    return out


def fit_ewma(train: pd.DataFrame) -> EwmaState:
    ret = train["ret"].to_numpy(float)
    train_var = ewma_train_variance(ret)
    std = ret / np.sqrt(np.maximum(train_var, EPS_VAR))
    q_emp = {str(a): float(np.nanquantile(std[np.isfinite(std)], a)) for a in ALPHAS}
    last_var = float(train_var[-1])
    last_ret = float(ret[-1])
    return EwmaState(lam=0.94, last_var=max(last_var, EPS_VAR), last_ret=last_ret, q_emp=q_emp)


def ewma_forecast_update(state: EwmaState, ret_t: float) -> float:
    forecast = max(state.lam * state.last_var + (1.0 - state.lam) * state.last_ret**2, EPS_VAR)
    state.last_var = forecast
    state.last_ret = float(ret_t)
    return forecast


def fit_arch_state(train: pd.DataFrame, model: str) -> ArchState:
    from arch import arch_model

    y = train["ret"].to_numpy(float)
    if model == "GARCH_N":
        spec = arch_model(y, mean="Zero", vol="GARCH", p=1, o=0, q=1, dist="normal", rescale=False)
    elif model == "GJR_T":
        spec = arch_model(y, mean="Zero", vol="GARCH", p=1, o=1, q=1, dist="t", rescale=False)
    else:
        raise ValueError(f"unknown ARCH model: {model}")

    res = spec.fit(update_freq=0, disp="off", show_warning=False)
    params = res.params
    cond_var = np.asarray(res.conditional_volatility, dtype=float) ** 2
    std = y / np.sqrt(np.maximum(cond_var, EPS_VAR))
    q_emp = {str(a): float(np.nanquantile(std[np.isfinite(std)], a)) for a in ALPHAS}
    return ArchState(
        omega=float(params.get("omega", 0.0)),
        alpha=float(params.get("alpha[1]", 0.0)),
        beta=float(params.get("beta[1]", 0.0)),
        gamma=float(params.get("gamma[1]", 0.0)),
        last_var=max(float(cond_var[-1]), EPS_VAR),
        last_ret=float(y[-1]),
        q_emp=q_emp,
    )


def arch_forecast_update(state: ArchState, ret_t: float) -> float:
    leverage = 1.0 if state.last_ret < 0 else 0.0
    forecast = (
        state.omega
        + state.alpha * state.last_ret**2
        + state.gamma * leverage * state.last_ret**2
        + state.beta * state.last_var
    )
    forecast = max(float(forecast), EPS_VAR)
    state.last_var = forecast
    state.last_ret = float(ret_t)
    return forecast


def _sv_unpack(theta: np.ndarray, model: str) -> SvParams:
    if model == "SV_KF":
        mu, phi, log_q = theta
        return SvParams(float(mu), float(phi), float(np.exp(log_q)), 0.0, 0.0, 1.0, model)
    if model == "TSV_KF":
        mu, phi, log_q, gamma = theta
        return SvParams(float(mu), float(phi), float(np.exp(log_q)), float(gamma), 0.0, 1.0, model)
    if model == "RSV_KF":
        mu, phi, log_q, c2, log_r2_meas = theta
        return SvParams(
            float(mu),
            float(phi),
            float(np.exp(log_q)),
            0.0,
            float(c2),
            float(np.exp(log_r2_meas)),
            model,
        )
    raise ValueError(f"unknown SV model: {model}")


def _sv_bounds(model: str) -> list[tuple[float, float]]:
    if model == "SV_KF":
        return [(-8.0, 4.0), (0.20, 0.995), (-8.0, 2.0)]
    if model == "TSV_KF":
        return [(-8.0, 4.0), (0.20, 0.995), (-8.0, 2.0), (-2.5, 2.5)]
    if model == "RSV_KF":
        return [(-8.0, 4.0), (0.20, 0.995), (-8.0, 2.0), (-3.0, 3.0), (-5.0, 3.0)]
    raise ValueError(f"unknown SV model: {model}")


def _sv_param_names(model: str) -> list[str]:
    if model == "SV_KF":
        return ["mu", "phi", "log_q"]
    if model == "TSV_KF":
        return ["mu", "phi", "log_q", "gamma"]
    if model == "RSV_KF":
        return ["mu", "phi", "log_q", "c2", "log_r2_meas"]
    raise ValueError(f"unknown SV model: {model}")


def _sv_bound_hits(theta: np.ndarray, model: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for name, value, (lower, upper) in zip(_sv_param_names(model), theta, _sv_bounds(model), strict=True):
        if abs(float(value) - lower) <= BOUND_TOL:
            hits.append({"param": name, "side": "lower", "value": float(value), "bound": float(lower)})
        if abs(float(value) - upper) <= BOUND_TOL:
            hits.append({"param": name, "side": "upper", "value": float(value), "bound": float(upper)})
    return hits


def lognormal_variance_mean(h: np.ndarray | float, p: np.ndarray | float) -> np.ndarray:
    """Conditional mean E[exp(h_t)] under the Gaussian Kalman state approximation."""
    h_arr = np.asarray(h, dtype=float)
    p_arr = np.maximum(np.asarray(p, dtype=float), 0.0)
    return np.exp(np.clip(h_arr + 0.5 * p_arr, -20.0, 10.0))


def _sv_start(train: pd.DataFrame, model: str) -> np.ndarray:
    mu0 = float(np.nanmean(train["log_r2"].to_numpy(float)))
    if model == "SV_KF":
        return np.array([mu0, 0.96, math.log(0.05)])
    if model == "TSV_KF":
        return np.array([mu0, 0.96, math.log(0.05), 0.05])
    c2 = float(np.nanmean(train["log_range_var"] - train["log_r2"] - LOG_CHI2_MEAN))
    return np.array([mu0, 0.96, math.log(0.05), c2, math.log(0.5)])


def _kalman_update(h: float, p: float, z: float, c: float, r: float) -> tuple[float, float, float]:
    if not np.isfinite(z):
        return h, p, 0.0
    s = max(p + r, 1e-10)
    err = z - (h + c)
    ll = -0.5 * (math.log(2.0 * math.pi * s) + (err * err) / s)
    k = p / s
    h_new = h + k * err
    p_new = max((1.0 - k) * p, 1e-8)
    return float(h_new), float(p_new), float(ll)


def kalman_filter_sv(
    train: pd.DataFrame,
    params: SvParams,
) -> tuple[float, np.ndarray, np.ndarray, float, float]:
    y1 = train["log_r2"].to_numpy(float)
    y2 = train["log_range_var"].to_numpy(float)
    ret = train["ret"].to_numpy(float)
    n = len(train)

    h = params.mu
    p = max(params.q / max(1e-4, 1.0 - params.phi**2), 1e-4)
    prev_neg = 0.0
    ll = 0.0
    h_forecasts = np.empty(n)
    p_forecasts = np.empty(n)

    for i in range(n):
        h_pred = params.mu + params.phi * (h - params.mu) + params.gamma * prev_neg
        p_pred = params.phi**2 * p + params.q
        h_forecasts[i] = h_pred
        p_forecasts[i] = p_pred

        h_upd, p_upd, ll1 = _kalman_update(h_pred, p_pred, y1[i], LOG_CHI2_MEAN, LOG_CHI2_VAR)
        ll += ll1
        if params.model == "RSV_KF":
            h_upd, p_upd, ll2 = _kalman_update(h_upd, p_upd, y2[i], params.c2, params.r2_meas)
            ll += ll2
        h, p = h_upd, p_upd
        prev_neg = 1.0 if ret[i] < 0 else 0.0

    return float(ll), h_forecasts, p_forecasts, float(h), float(p)


def fit_sv_state(train: pd.DataFrame, model: str) -> SvState:
    starts = [_sv_start(train, model)]
    for _ in range(1):
        base = _sv_start(train, model)
        jitter = RNG.normal(0.0, 0.15, size=len(base))
        starts.append(base + jitter)

    records: list[dict[str, Any]] = []
    candidates: list[tuple[dict[str, Any], np.ndarray]] = []

    def obj(theta: np.ndarray) -> float:
        params = _sv_unpack(theta, model)
        ll, _, _, _, _ = kalman_filter_sv(train, params)
        penalty = 0.0
        if not np.isfinite(ll):
            penalty = 1e9
        return float(-ll + penalty)

    bounds = _sv_bounds(model)
    for start_id, start in enumerate(starts):
        try:
            res = optimize.minimize(
                obj,
                start,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 300, "ftol": 1e-6},
            )
            theta_res = np.asarray(res.x, dtype=float)
            fun = float(res.fun) if np.isfinite(res.fun) else None
            record = {
                "start_id": start_id,
                "success": bool(res.success),
                "status": int(res.status),
                "message": str(res.message),
                "fun": fun,
                "loglik": float(-res.fun) if np.isfinite(res.fun) else None,
                "nit": int(getattr(res, "nit", 0)),
                "nfev": int(getattr(res, "nfev", 0)),
                "bound_hits": _sv_bound_hits(theta_res, model),
            }
            records.append(record)
            if fun is not None:
                candidates.append((record, theta_res))
        except Exception as exc:  # noqa: BLE001
            warn(f"{model} optimizer start failed: {type(exc).__name__}: {exc}")
            records.append(
                {
                    "start_id": start_id,
                    "success": False,
                    "status": None,
                    "message": f"{type(exc).__name__}: {exc}",
                    "fun": None,
                    "loglik": None,
                    "nit": 0,
                    "nfev": 0,
                    "bound_hits": [],
                }
            )

    successful_candidates = [item for item in candidates if item[0]["success"]]
    candidate_pool = successful_candidates or candidates
    fallback_used = False
    chosen_record: dict[str, Any] | None = None
    if not candidate_pool:
        warn(f"{model} optimizer failed for all starts; using deterministic start")
        theta = starts[0]
        fallback_used = True
    else:
        chosen_record, theta = min(candidate_pool, key=lambda item: item[0]["fun"])

    params = _sv_unpack(theta, model)
    ll, h_fore, p_fore, h_filt, p_filt = kalman_filter_sv(train, params)
    var_fore = lognormal_variance_mean(h_fore, p_fore)
    ret = train["ret"].to_numpy(float)
    std = ret / np.sqrt(np.maximum(var_fore, EPS_VAR))
    q_emp = {str(a): float(np.nanquantile(std[np.isfinite(std)], a)) for a in ALPHAS}
    chosen_success = bool(chosen_record and chosen_record["success"])
    fit_info = {
        "model": model,
        "n_train": int(len(train)),
        "start_count": len(starts),
        "success_count": int(sum(bool(record["success"]) for record in records)),
        "success_any": bool(any(bool(record["success"]) for record in records)),
        "chosen_success": chosen_success,
        "fallback_used": fallback_used,
        "chosen_start_id": chosen_record["start_id"] if chosen_record else None,
        "chosen_loglik": float(ll),
        "chosen_fun": float(-ll),
        "params": asdict(params),
        "theta": {name: float(value) for name, value in zip(_sv_param_names(model), theta, strict=True)},
        "bound_hits": _sv_bound_hits(theta, model),
        "optimizer_records": records,
    }
    return SvState(
        params=params,
        h_filt=h_filt,
        p_filt=p_filt,
        last_ret=float(ret[-1]),
        q_emp=q_emp,
        fit_info=fit_info,
    )


def sv_forecast_update(state: SvState, obs: pd.Series) -> float:
    params = state.params
    prev_neg = 1.0 if state.last_ret < 0 else 0.0
    h_pred = params.mu + params.phi * (state.h_filt - params.mu) + params.gamma * prev_neg
    p_pred = params.phi**2 * state.p_filt + params.q
    forecast = float(lognormal_variance_mean(h_pred, p_pred))

    h_upd, p_upd, _ = _kalman_update(h_pred, p_pred, float(obs["log_r2"]), LOG_CHI2_MEAN, LOG_CHI2_VAR)
    if params.model == "RSV_KF":
        h_upd, p_upd, _ = _kalman_update(
            h_upd,
            p_upd,
            float(obs["log_range_var"]),
            params.c2,
            params.r2_meas,
        )
    state.h_filt = h_upd
    state.p_filt = p_upd
    state.last_ret = float(obs["ret"])
    return max(forecast, EPS_VAR)


def fit_model_state(train: pd.DataFrame, model: str) -> Any:
    if model == "EWMA_094":
        return fit_ewma(train)
    if model in {"GARCH_N", "GJR_T"}:
        return fit_arch_state(train, model)
    return fit_sv_state(train, model)


def forecast_update(state: Any, model: str, obs: pd.Series) -> float:
    if model == "EWMA_094":
        return ewma_forecast_update(state, float(obs["ret"]))
    if model in {"GARCH_N", "GJR_T"}:
        return arch_forecast_update(state, float(obs["ret"]))
    return sv_forecast_update(state, obs)


def summarize_sv_diagnostics(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(diagnostics)
    chosen_success_count = sum(1 for item in diagnostics if item.get("chosen_success"))
    fallback_count = sum(1 for item in diagnostics if item.get("fallback_used"))
    bound_hit_fit_count = sum(1 for item in diagnostics if item.get("bound_hits"))
    by_model: dict[str, dict[str, Any]] = {}
    for model in sorted(SV_MODELS):
        model_items = [item for item in diagnostics if item.get("model") == model]
        model_total = len(model_items)
        model_success = sum(1 for item in model_items if item.get("chosen_success"))
        by_model[model] = {
            "fit_count": model_total,
            "chosen_success_count": model_success,
            "chosen_success_rate": float(model_success / model_total) if model_total else None,
            "fallback_count": sum(1 for item in model_items if item.get("fallback_used")),
            "bound_hit_fit_count": sum(1 for item in model_items if item.get("bound_hits")),
        }
    chosen_success_rate = float(chosen_success_count / total) if total else None
    return {
        "fit_count": total,
        "chosen_success_count": chosen_success_count,
        "chosen_success_rate": chosen_success_rate,
        "threshold": SV_CONVERGENCE_THRESHOLD,
        "passes_threshold": bool(chosen_success_rate is not None and chosen_success_rate >= SV_CONVERGENCE_THRESHOLD),
        "fallback_count": fallback_count,
        "bound_hit_fit_count": bound_hit_fit_count,
        "by_model": by_model,
    }


def run_asset(panel: pd.DataFrame, asset: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    idx = panel.index
    oos_idx = idx[idx >= OOS_START]
    dates_to_refit = refit_dates(idx)
    states: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    fit_errors: list[str] = []
    sv_fit_diagnostics: list[dict[str, Any]] = []

    for dt in oos_idx:
        train = panel.loc[panel.index < dt]
        if len(train) < MIN_TRAIN:
            continue
        # Lookahead guard: this is the explicit one-step lag. The day-t forecast
        # is computed from a state fitted/updated only through t-1; the day-t
        # observation is applied only inside forecast_update() after the forecast
        # has been recorded. This is equivalent to signal.shift(1).
        if dt in dates_to_refit or not states:
            for model in MODELS:
                try:
                    states[model] = fit_model_state(train, model)
                    if model in SV_MODELS:
                        fit_info = dict(states[model].fit_info)
                        fit_info["asset"] = asset
                        fit_info["refit_date"] = str(dt.date())
                        fit_info["n_train"] = int(len(train))
                        sv_fit_diagnostics.append(fit_info)
                except Exception as exc:  # noqa: BLE001
                    msg = f"{asset} {dt.date()} {model} fit failed: {type(exc).__name__}: {exc}"
                    warn(msg)
                    fit_errors.append(msg)

        obs = panel.loc[dt]
        for model, state in list(states.items()):
            try:
                var_fore = forecast_update(state, model, obs)
            except Exception as exc:  # noqa: BLE001
                msg = f"{asset} {dt.date()} {model} forecast/update failed: {type(exc).__name__}: {exc}"
                warn(msg)
                fit_errors.append(msg)
                continue
            row: dict[str, Any] = {
                "date": dt,
                "asset": asset,
                "model": model,
                "ret": float(obs["ret"]),
                "r2": float(obs["r2"]),
                "var_forecast": float(var_fore),
            }
            for alpha in ALPHAS:
                q_emp = float(state.q_emp[str(alpha)])
                row[f"var_{int(alpha * 100)}pct"] = q_emp * math.sqrt(max(var_fore, EPS_VAR))
            rows.append(row)

    forecasts = pd.DataFrame(rows).set_index("date").sort_index()
    meta = {
        "asset": asset,
        "n_total": int(len(panel)),
        "n_oos_dates": int(forecasts.index.nunique()) if not forecasts.empty else 0,
        "oos_start": str(forecasts.index.min().date()) if not forecasts.empty else None,
        "oos_end": str(forecasts.index.max().date()) if not forecasts.empty else None,
        "fit_error_count": len(fit_errors),
        "fit_errors_sample": fit_errors[:10],
        "sv_fit_summary": summarize_sv_diagnostics(sv_fit_diagnostics),
        "sv_fit_diagnostics": sv_fit_diagnostics,
    }
    return forecasts, meta


def evaluate_forecasts(forecasts: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"by_asset": {}, "aggregate": {}}
    all_rows: list[dict[str, Any]] = []

    for asset, asset_df in forecasts.groupby("asset"):
        asset_out: dict[str, Any] = {}
        base = asset_df[asset_df["model"] == "GARCH_N"].copy()
        base = base[~base.index.duplicated(keep="last")]
        base_loss_map = qlike_pointwise(base["r2"].to_numpy(float), base["var_forecast"].to_numpy(float))
        base_loss = pd.Series(base_loss_map, index=base.index)
        base_qlike = qlike(base["r2"].to_numpy(float), base["var_forecast"].to_numpy(float))

        for model, model_df_raw in asset_df.groupby("model"):
            model_df = model_df_raw[~model_df_raw.index.duplicated(keep="last")].copy()
            common = model_df.index.intersection(base.index)
            model_df = model_df.loc[common]
            actual = model_df["r2"].to_numpy(float)
            pred = model_df["var_forecast"].to_numpy(float)
            losses = qlike_pointwise(actual, pred)
            ql = qlike(actual, pred)
            if model == "GARCH_N":
                dm_t, dm_p = 0.0, 1.0
            else:
                dm_t, dm_p = dm_test(losses, base_loss.loc[common].to_numpy(float), h=1)

            row: dict[str, Any] = {
                "asset": asset,
                "model": model,
                "n": int(len(model_df)),
                "qlike": float(ql),
                "qlike_rel_vs_garch_n": float((base_qlike - ql) / base_qlike),
                "dm_t_vs_garch_n": float(dm_t),
                "dm_p_vs_garch_n": float(dm_p),
            }

            for alpha in ALPHAS:
                col = f"var_{int(alpha * 100)}pct"
                q = model_df[col].to_numpy(float)
                y = model_df["ret"].to_numpy(float)
                viol = (y < q).astype(int)
                pb = pinball_loss(y, q, alpha)
                kup = kupiec_test(viol, alpha=alpha)
                cc = christoffersen_test(viol, alpha=alpha)
                row[f"pinball_{int(alpha * 100)}pct"] = float(np.nanmean(pb))
                row[f"viol_rate_{int(alpha * 100)}pct"] = float(np.nanmean(viol))
                row[f"kupiec_p_{int(alpha * 100)}pct"] = float(kup["p_value"])
                row[f"cc_p_{int(alpha * 100)}pct"] = float(cc.get("cc_pval", np.nan))

            asset_out[model] = row
            all_rows.append(row)
        out["by_asset"][asset] = asset_out

    summary = pd.DataFrame(all_rows)
    for model, model_df in summary.groupby("model"):
        out["aggregate"][model] = {
            "assets": sorted(model_df["asset"].tolist()),
            "mean_qlike": float(model_df["qlike"].mean()),
            "mean_qlike_rel_vs_garch_n": float(model_df["qlike_rel_vs_garch_n"].mean()),
            "harvey_wins_vs_garch_n": int((model_df["dm_t_vs_garch_n"] < -3.0).sum()),
            "harvey_losses_vs_garch_n": int((model_df["dm_t_vs_garch_n"] > 3.0).sum()),
            "mean_pinball_5pct": float(model_df["pinball_5pct"].mean()),
            "mean_pinball_1pct": float(model_df["pinball_1pct"].mean()),
            "kupiec_pass_5pct": int((model_df["kupiec_p_5pct"] >= 0.05).sum()),
            "kupiec_pass_1pct": int((model_df["kupiec_p_1pct"] >= 0.05).sum()),
        }

    best = summary.loc[summary.groupby("asset")["qlike"].idxmin()]
    out["asset_qlike_winners"] = {
        str(row["asset"]): {
            "model": str(row["model"]),
            "qlike": float(row["qlike"]),
        }
        for _, row in best.iterrows()
    }
    return out


def make_figures(evaluation: dict[str, Any]) -> dict[str, str]:
    agg = pd.DataFrame.from_dict(evaluation["aggregate"], orient="index").sort_values("mean_qlike")
    fig_paths: dict[str, str] = {}

    plt.figure(figsize=(9, 5), dpi=160)
    colors = ["#2f5d8c" if idx == "GARCH_N" else "#6b9ac4" for idx in agg.index]
    plt.bar(agg.index, agg["mean_qlike"], color=colors)
    plt.ylabel("Mean QLIKE on r² (lower is better)")
    plt.title("K1648 model-class comparison")
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    path = HERE / "fig_k1648_mean_qlike.png"
    plt.savefig(path)
    plt.close()
    fig_paths["mean_qlike"] = str(path.relative_to(HERE))

    plt.figure(figsize=(9, 5), dpi=160)
    rel = agg["mean_qlike_rel_vs_garch_n"].sort_values(ascending=False)
    plt.axhline(0, color="#333333", linewidth=1)
    plt.bar(rel.index, 100 * rel, color=["#26826c" if v > 0 else "#b74f4f" for v in rel])
    plt.ylabel("Mean QLIKE improvement vs GARCH_N (%)")
    plt.title("Positive values beat GARCH_N")
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    path = HERE / "fig_k1648_rel_vs_garch.png"
    plt.savefig(path)
    plt.close()
    fig_paths["relative_vs_garch"] = str(path.relative_to(HERE))
    return fig_paths


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def main() -> None:
    raw = fetch_ohlc()
    all_forecasts: list[pd.DataFrame] = []
    data_meta: dict[str, Any] = {}
    for asset in ASSETS:
        panel = build_panel(raw, asset)
        forecasts, meta = run_asset(panel, asset)
        all_forecasts.append(forecasts)
        data_meta[asset] = meta

    forecasts = pd.concat(all_forecasts, axis=0).sort_index()
    forecast_path = HERE / "K1648_forecasts.parquet"
    forecasts.to_parquet(forecast_path)
    evaluation = evaluate_forecasts(forecasts)
    figures = make_figures(evaluation)
    all_sv_diagnostics = [
        item
        for meta in data_meta.values()
        for item in meta.get("sv_fit_diagnostics", [])
    ]
    sv_convergence = summarize_sv_diagnostics(all_sv_diagnostics)

    aggregate = evaluation["aggregate"]
    sv_models = ["SV_KF", "TSV_KF", "RSV_KF"]
    sv_best = max(sv_models, key=lambda m: aggregate[m]["mean_qlike_rel_vs_garch_n"])
    sv_best_rel = aggregate[sv_best]["mean_qlike_rel_vs_garch_n"]
    harvey_sv_wins = sum(aggregate[m]["harvey_wins_vs_garch_n"] for m in sv_models)
    harvey_sv_losses = sum(aggregate[m]["harvey_losses_vs_garch_n"] for m in sv_models)

    if not sv_convergence["passes_threshold"]:
        verdict = "UNRELIABLE_SV_CONVERGENCE_BELOW_THRESHOLD"
    elif harvey_sv_wins > 0:
        verdict = "CONDITIONAL_PASS_SV_HAS_AT_LEAST_ONE_HARVEY_WIN"
    elif sv_best_rel > 0:
        verdict = "WEAK_SV_AVERAGE_QLIKE_EDGE_NO_HARVEY_WIN"
    else:
        verdict = "NULL_NO_SV_CLASS_EDGE_VS_GARCH"

    payload: dict[str, Any] = {
        "experiment_id": "K1648",
        "title": "QML/Kalman stochastic-volatility class vs GARCH baselines",
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "source": "yfinance daily OHLC, auto_adjust=True",
            "assets": ASSETS,
            "start": START,
            "end": END,
            "cache": str(DATA_CACHE.relative_to(HERE)),
            "metadata_by_asset": data_meta,
        },
        "methods": {
            "forecast_horizon": "one trading day",
            "oos_start": str(OOS_START.date()),
            "refit_cadence": "first available trading day of each calendar year",
            "sv_variance_forecast": "log-normal Kalman mean exp(h_pred + 0.5 * p_pred)",
            "sv_convergence_threshold": SV_CONVERGENCE_THRESHOLD,
            "lookahead_policy": (
                "Forecasts for t are produced from state through t-1; day-t returns/range "
                "update the state only after forecast recording. Equivalent to signal.shift(1)."
            ),
            "primary_loss": "Patton QLIKE on close-to-close r_t^2",
            "var_loss": "Empirical standardized-residual quantiles at 5% and 1%; pinball + Kupiec/CC",
            "sv_qml_note": (
                "SV variants are QML/Kalman approximations on log(r_t^2); RSV_KF adds "
                "Parkinson range log-variance as a second measurement. This is not a full "
                "Bayesian realized-SV skew-t implementation."
            ),
        },
        "diagnostics": {
            "sv_convergence": sv_convergence,
        },
        "literature_used": [
            {
                "name": "Threshold stochastic volatility: properties and forecasting",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0169207017300717",
            },
            {
                "name": "Realized Stochastic Volatility Model with Skew-t Distributions",
                "url": "https://arxiv.org/abs/2401.13179",
            },
            {
                "name": "Patton (2011) volatility forecast comparison with imperfect proxies",
                "url": "https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf",
            },
        ],
        "evaluation": evaluation,
        "figures": figures,
        "summary": {
            "best_sv_model_by_mean_qlike_rel": sv_best,
            "best_sv_mean_qlike_rel_vs_garch_n": float(sv_best_rel),
            "sv_harvey_wins_vs_garch_n_total": int(harvey_sv_wins),
            "sv_harvey_losses_vs_garch_n_total": int(harvey_sv_losses),
            "sv_convergence_passes_threshold": bool(sv_convergence["passes_threshold"]),
            "asset_qlike_winners": evaluation["asset_qlike_winners"],
        },
    }
    atomic_write_json(RESULTS_PATH, payload)
    print(json.dumps(to_jsonable(payload["summary"]), ensure_ascii=False, indent=2))
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
