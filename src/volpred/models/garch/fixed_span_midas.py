"""Lookahead-safe fixed-span GARCH-MIDAS primitives.

The public seam in this module keeps low-frequency VIX information at monthly
frequency while evaluating the likelihood on every daily return.  A daily return is
never paired with a row of unrelated monthly observations, and a forecast for month
M uses only completed months M-1 ... M-K.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from volpred.research.optimization import bounded_multistart_minimize


@dataclass(frozen=True)
class FixedSpanMidasPanel:
    returns: np.ndarray
    log_vix_lags: np.ndarray
    dates: pd.DatetimeIndex
    source_positions: np.ndarray
    valid_start: int


@dataclass(frozen=True)
class FixedSpanMidasFit:
    params: np.ndarray
    loglik: float
    g_last: float
    tau_last: float
    valid_start: int
    n_observations: int
    optimizer_iterations: int


@dataclass(frozen=True)
class FixedSpanMidasForecast:
    variance: float
    g: float
    tau: float


def _validated_inputs(
    returns: np.ndarray,
    return_dates: pd.DatetimeIndex,
    vix_history: np.ndarray,
    vix_history_dates: pd.DatetimeIndex,
) -> tuple[np.ndarray, pd.DatetimeIndex, np.ndarray, pd.DatetimeIndex]:
    returns_array = np.asarray(returns, dtype=float)
    return_index = pd.DatetimeIndex(return_dates)
    vix_array = np.asarray(vix_history, dtype=float)
    history_index = pd.DatetimeIndex(vix_history_dates)
    if returns_array.ndim != 1 or vix_array.ndim != 1:
        raise ValueError("returns and VIX history must be one-dimensional")
    if len(returns_array) != len(return_index):
        raise ValueError("returns and return_dates must have identical lengths")
    if len(vix_array) != len(history_index):
        raise ValueError("vix_history and vix_history_dates must have identical lengths")
    if len(return_index) == 0 or len(history_index) == 0:
        raise ValueError("fixed-span MIDAS requires non-empty input")
    if (
        return_index.has_duplicates
        or history_index.has_duplicates
        or not return_index.is_monotonic_increasing
        or not history_index.is_monotonic_increasing
    ):
        raise ValueError("return and VIX-history dates must be unique and increasing")
    if return_index[0] < history_index[0] or return_index[-1] > history_index[-1]:
        raise ValueError("VIX history must cover the complete return window")
    if not np.all(np.isfinite(returns_array)) or not np.all(np.isfinite(vix_array)):
        raise ValueError("returns and VIX history must be finite")
    if np.any(vix_array <= 0):
        raise ValueError("VIX observations must be positive")
    return returns_array, return_index, vix_array, history_index


def _monthly_log_vix(vix: np.ndarray, dates: pd.DatetimeIndex) -> pd.Series:
    periods = dates.to_period("M")
    return pd.Series(np.log(vix), index=periods).groupby(level=0, sort=True).mean()


def build_fixed_span_midas_panel(
    *,
    returns: np.ndarray,
    return_dates: pd.DatetimeIndex,
    vix_history: np.ndarray,
    vix_history_dates: pd.DatetimeIndex,
    lag_months: int,
    min_observations: int = 500,
) -> FixedSpanMidasPanel:
    """Align every eligible daily return with K prior monthly VIX averages."""

    returns_array, return_index, vix_array, history_index = _validated_inputs(
        returns,
        return_dates,
        vix_history,
        vix_history_dates,
    )
    if lag_months < 1:
        raise ValueError("lag_months must be positive")
    if min_observations < 1:
        raise ValueError("min_observations must be positive")

    monthly = _monthly_log_vix(vix_array, history_index)
    month_to_position = {month: i for i, month in enumerate(monthly.index)}
    daily_month_positions = np.array(
        [month_to_position[month] for month in return_index.to_period("M")],
        dtype=int,
    )
    source_positions = np.flatnonzero(daily_month_positions >= lag_months)
    if len(source_positions) < min_observations:
        raise ValueError(
            f"fixed-span MIDAS has {len(source_positions)} eligible daily rows; "
            f"requires at least {min_observations}"
        )

    monthly_values = monthly.to_numpy(dtype=float)
    lag_matrix = np.empty((len(source_positions), lag_months), dtype=float)
    for row, source_position in enumerate(source_positions):
        month_position = daily_month_positions[source_position]
        lag_matrix[row] = monthly_values[
            month_position - lag_months : month_position
        ][::-1]

    return FixedSpanMidasPanel(
        returns=returns_array[source_positions].copy(),
        log_vix_lags=lag_matrix,
        dates=return_index[source_positions].copy(),
        source_positions=source_positions,
        valid_start=int(source_positions[0]),
    )


def fixed_span_log_vix_lags(
    *,
    history_vix: np.ndarray,
    history_dates: pd.DatetimeIndex,
    forecast_date: pd.Timestamp,
    lag_months: int,
) -> np.ndarray:
    """Return M-1 ... M-K averages for a forecast in month M."""

    vix = np.asarray(history_vix, dtype=float)
    dates = pd.DatetimeIndex(history_dates)
    if len(vix) != len(dates) or len(vix) == 0:
        raise ValueError("history_vix and history_dates must be non-empty and aligned")
    if lag_months < 1:
        raise ValueError("lag_months must be positive")
    forecast_timestamp = pd.Timestamp(forecast_date)
    if np.any(dates >= forecast_timestamp):
        raise ValueError("history_dates must be strictly before forecast_date")
    if not np.all(np.isfinite(vix)) or np.any(vix <= 0):
        raise ValueError("history VIX observations must be finite and positive")

    monthly = _monthly_log_vix(vix, dates)
    prior = monthly[monthly.index < forecast_timestamp.to_period("M")]
    if len(prior) < lag_months:
        raise ValueError(
            f"only {len(prior)} completed months available; need {lag_months}"
        )
    return prior.iloc[-lag_months:].to_numpy(dtype=float)[::-1]


def fixed_span_beta_weights(lag_months: int, omega2: float) -> np.ndarray:
    if lag_months < 1 or not np.isfinite(omega2) or omega2 < 1.0:
        raise ValueError("lag_months must be positive and omega2 must be >= 1")
    positions = np.arange(1, lag_months + 1, dtype=float) / (lag_months + 1.0)
    log_weights = (omega2 - 1.0) * np.log1p(-positions)
    log_weights -= np.max(log_weights)
    weights = np.exp(log_weights)
    return weights / weights.sum()


def _tau(params: np.ndarray, log_vix_lags: np.ndarray) -> np.ndarray:
    m, theta, omega2 = params[:3]
    weights = fixed_span_beta_weights(log_vix_lags.shape[1], float(omega2))
    log_tau = m + theta * (log_vix_lags @ weights)
    return np.exp(np.clip(log_tau, -20.0, 20.0))


def _filter_g(
    returns: np.ndarray,
    tau: np.ndarray,
    alpha: float,
    gamma: float,
    beta: float,
) -> np.ndarray:
    intercept = 1.0 - alpha - gamma / 2.0 - beta
    if intercept <= 0:
        raise ValueError("short-run GARCH parameters are not stationary")
    g = np.ones(len(returns), dtype=float)
    for index in range(1, len(returns)):
        scaled = returns[index - 1] / np.sqrt(max(tau[index], 1e-16))
        leverage = gamma * scaled**2 if scaled < 0 else 0.0
        g[index] = max(
            intercept + alpha * scaled**2 + leverage + beta * g[index - 1],
            1e-10,
        )
    return g


def fit_fixed_span_garch_midas(
    *,
    returns: np.ndarray,
    return_dates: pd.DatetimeIndex,
    vix_history: np.ndarray,
    vix_history_dates: pd.DatetimeIndex,
    lag_months: int,
    min_observations: int = 500,
) -> FixedSpanMidasFit:
    """Fit the Paper 9 fixed-span model on its full daily likelihood panel."""

    panel = build_fixed_span_midas_panel(
        returns=returns,
        return_dates=return_dates,
        vix_history=vix_history,
        vix_history_dates=vix_history_dates,
        lag_months=lag_months,
        min_observations=min_observations,
    )

    def objective(params: np.ndarray) -> float:
        _m, _theta, _omega2, alpha, gamma, beta = params
        if alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10
        try:
            tau = _tau(params, panel.log_vix_lags)
            g = _filter_g(panel.returns, tau, alpha, gamma, beta)
        except ValueError:
            return 1e10
        variance = np.maximum(tau * g, 1e-16)
        nll = 0.5 * np.sum(
            np.log(2.0 * np.pi) + np.log(variance) + panel.returns**2 / variance
        )
        return float(nll) if np.isfinite(nll) else 1e10

    fit = bounded_multistart_minimize(
        objective,
        starts=[
            (-10.0, 1.0, 2.0, 0.05, 0.05, 0.90),
            (-8.0, 0.5, 5.0, 0.03, 0.08, 0.88),
            (-12.0, 1.5, 3.0, 0.08, 0.10, 0.80),
        ],
        bounds=[
            (-20.0, 0.0),
            (0.01, 5.0),
            (1.0, 20.0),
            (1e-4, 0.3),
            (1e-4, 0.3),
            (0.5, 0.999),
        ],
        options={"maxiter": 1000, "ftol": 1e-10},
    )
    tau = _tau(fit.params, panel.log_vix_lags)
    g = _filter_g(
        panel.returns,
        tau,
        float(fit.params[3]),
        float(fit.params[4]),
        float(fit.params[5]),
    )
    return FixedSpanMidasFit(
        params=fit.params,
        loglik=-fit.objective,
        g_last=float(g[-1]),
        tau_last=float(tau[-1]),
        valid_start=panel.valid_start,
        n_observations=len(panel.returns),
        optimizer_iterations=fit.iterations,
    )


def forecast_fixed_span_garch_midas(
    *,
    params: np.ndarray,
    g_previous: float,
    previous_return: float,
    log_vix_lags: np.ndarray,
) -> FixedSpanMidasForecast:
    """Advance a fitted fixed-span state by one daily observation."""

    params_array = np.asarray(params, dtype=float)
    lags = np.asarray(log_vix_lags, dtype=float)
    if params_array.shape != (6,) or lags.ndim != 1:
        raise ValueError("expected six parameters and a one-dimensional lag vector")
    tau = float(_tau(params_array, lags.reshape(1, -1))[0])
    alpha, gamma, beta = map(float, params_array[3:])
    intercept = 1.0 - alpha - gamma / 2.0 - beta
    if intercept <= 0 or not np.isfinite(g_previous):
        raise ValueError("invalid fixed-span forecast state")
    scaled = float(previous_return) / np.sqrt(max(tau, 1e-16))
    leverage = gamma * scaled**2 if scaled < 0 else 0.0
    g = max(intercept + alpha * scaled**2 + leverage + beta * g_previous, 1e-10)
    return FixedSpanMidasForecast(variance=tau * g, g=g, tau=tau)


__all__ = [
    "FixedSpanMidasFit",
    "FixedSpanMidasForecast",
    "FixedSpanMidasPanel",
    "build_fixed_span_midas_panel",
    "fit_fixed_span_garch_midas",
    "fixed_span_beta_weights",
    "fixed_span_log_vix_lags",
    "forecast_fixed_span_garch_midas",
]
