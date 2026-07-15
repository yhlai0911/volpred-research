"""K1717 / ASIA-1: India VIX vs US VIX information content for NIFTY 50.

Empirical experiment using yfinance daily observations.  The forecast target is
next Indian trading-day close-to-close squared log return.  Every signal is
available strictly before the target date.  Both VIX series use a strict
backward as-of join; an explicit India ``signal.shift(1)`` diagnostic detects
vendor-calendar gaps, whose multi-session NIFTY targets are excluded.

The pre-registered sequence is:
1. Diagnose the longest available sample and timing alignment.
2. Conditional Granger tests for India VIX and US VIX.
3. Annual expanding-origin GARCH-X and HAR-proxy-X OOS forecasts for 2020-2026.
4. Patton QLIKE + canonical HAC DM comparisons.
5. Run the monthly c/IndiaVIX VT simulation only if the relative-information gate
   is passed.  The c grid calibrates risk, not Sharpe.

References are recorded in ``REFERENCES`` and in the result artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from statsmodels.stats.multitest import multipletests
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller

from volpred.stats.drawdown import compare_max_drawdown, max_drawdown
from volpred.stats.model_evaluation import (
    clark_west_test,
    dm_test,
    qlike,
    qlike_pointwise,
    spearman_corr,
    strategy_dm_test,
)


warnings.filterwarnings("ignore", category=FutureWarning)

EXPERIMENT_ID = "k1717"
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_START = "2007-09-01"
INDIA_DATA_END_EXCLUSIVE = "2026-07-16"
# At the 2026-07-15 Asia/Taipei execution time, the 2026-07-15 US session had
# not closed.  Pin US data to the last fully completed session (2026-07-14).
US_DATA_END_EXCLUSIVE = "2026-07-15"
OOS_START_YEAR = 2020
OOS_END_YEAR = 2026
TRADING_DAYS = 252
SEED = 42
MIN_TRAIN_OBS = 500
HAR_WINDOWS = (1, 5, 22)
TARGET_VOL = 0.12
MAX_EQUITY_WEIGHT = 1.0
TX_COST_BPS_PRIMARY = 10.0
TX_COST_BPS_SENSITIVITY = (0.0, 10.0, 25.0)
BOOTSTRAP_REPS = 1000

REFERENCES = [
    {
        "authors": "Shaikh, I. and Padhi, P.",
        "year": 2014,
        "title": "The forecasting performance of implied volatility index: evidence from India VIX",
        "venue": "Economic Change and Restructuring 47(4), 251-274",
        "doi": "10.1007/s10644-014-9149-z",
        "design_relevance": "Compares India VIX with RiskMetrics and GJR-GARCH forecasts.",
    },
    {
        "authors": "Pati, P. C., Barai, P., and Rajib, P.",
        "year": 2018,
        "title": "Forecasting stock market volatility and information content of implied volatility index",
        "venue": "Applied Economics 50(23), 2552-2568",
        "doi": "10.1080/00036846.2017.1403557",
        "design_relevance": "Tests incremental implied-volatility information in India and other Asia-Pacific markets.",
    },
    {
        "authors": "Patton, A. J.",
        "year": 2011,
        "title": "Volatility forecast comparison using imperfect volatility proxies",
        "venue": "Journal of Econometrics 160(1), 246-256",
        "doi": "10.1016/j.jeconom.2010.03.034",
        "design_relevance": "Justifies proxy-robust QLIKE with squared returns as the noisy variance proxy.",
    },
    {
        "authors": "Corsi, F.",
        "year": 2009,
        "title": "A Simple Approximate Long-Memory Model of Realized Volatility",
        "venue": "Journal of Financial Econometrics 7(2), 174-196",
        "doi": "10.1093/jjfinec/nbp001",
        "design_relevance": "Motivates daily, weekly, and monthly heterogeneous volatility components.",
    },
    {
        "authors": "Diebold, F. X. and Mariano, R. S.",
        "year": 1995,
        "title": "Comparing Predictive Accuracy",
        "venue": "Journal of Business & Economic Statistics 13(3), 253-263",
        "doi": "10.1080/07350015.1995.10524599",
        "design_relevance": "Forecast-loss comparison with serial-correlation-robust inference.",
    },
    {
        "authors": "National Stock Exchange of India",
        "year": 2023,
        "title": "India VIX computation methodology and white paper",
        "venue": "NSE official methodology",
        "url": "https://www.nseindia.com/static/products-services/indices-indiavix-index",
        "design_relevance": "Defines India VIX as 30-calendar-day annualized implied volatility from NIFTY options.",
    },
]


def _json_safe(value: Any) -> Any:
    """Convert numpy/pandas objects and non-finite floats to strict JSON values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
        value = pd.Timestamp(value)
        return value.isoformat()
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write, parse-check, then atomically replace the result JSON."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    safe_payload = _json_safe(payload)
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(safe_payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    with tmp.open("r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=True, index_label="date")
    pd.read_csv(tmp, nrows=5)
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_ohlc(ticker: str, end_exclusive: str) -> pd.DataFrame:
    raw = yf.download(
        ticker,
        start=DATA_START,
        end=end_exclusive,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close"]
    if raw.empty or any(column not in raw for column in required):
        raise RuntimeError(f"No complete OHLC data returned for {ticker}")
    ohlc = raw[required].astype(float).dropna(subset=["Open", "Close"]).sort_index()
    ohlc.index = pd.DatetimeIndex(ohlc.index).tz_localize(None).normalize()
    ohlc = ohlc[~ohlc.index.duplicated(keep="last")]
    if len(ohlc) < 252 or (ohlc[["Open", "Close"]] <= 0).any().any():
        raise RuntimeError(f"Invalid OHLC series for {ticker}: n={len(ohlc)}")
    return ohlc


def download_close(ticker: str, end_exclusive: str) -> pd.Series:
    close = download_ohlc(ticker, end_exclusive)["Close"].copy()
    close.name = ticker
    return close


def strict_asof_signal(
    signal: pd.Series, target_index: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Latest signal with source date strictly before each target date.

    This is the cross-market equivalent of ``signal.shift(1)``.  It handles a
    US-open / India-closed holiday without discarding the intervening US close.
    """
    left = pd.DataFrame({"target_date": pd.DatetimeIndex(target_index)}).sort_values("target_date")
    right = pd.DataFrame(
        {"source_date": pd.DatetimeIndex(signal.index), "value": signal.to_numpy(dtype=float)}
    ).sort_values("source_date")
    merged = pd.merge_asof(
        left,
        right,
        left_on="target_date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=False,
    )
    values = pd.Series(merged["value"].to_numpy(), index=merged["target_date"], name=signal.name)
    sources = pd.Series(
        pd.to_datetime(merged["source_date"]).to_numpy(),
        index=merged["target_date"],
        name=f"{signal.name}_source_date",
    )
    valid = sources.notna()
    if not (sources.loc[valid].to_numpy() < sources.loc[valid].index.to_numpy()).all():
        raise AssertionError("strict-asof timing violation: source_date must precede target_date")
    return values.reindex(target_index), sources.reindex(target_index)


def build_dataset(
    nifty_ohlc: pd.DataFrame, india_vix: pd.Series, us_vix: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    nifty = nifty_ohlc["Close"].copy()
    index = nifty.index
    returns = np.log(nifty).diff()
    simple_returns = nifty.pct_change()
    open_to_next_open_returns = nifty_ohlc["Open"].shift(-1) / nifty_ohlc["Open"] - 1.0
    holding_end_date = index.to_series().shift(-1)
    r2 = returns.pow(2)

    # Same-market row-lag diagnostic plus canonical strict-as-of signal.  Yahoo
    # occasionally omits a NIFTY date for which India VIX has an observation;
    # strict as-of finds that gap instead of silently applying a second lag.
    local_on_nifty_days = india_vix.reindex(index).ffill()
    local_row_shift_signal = local_on_nifty_days.shift(1)  # explicit signal.shift(1)
    strict_local_signal, local_source_date = strict_asof_signal(india_vix, index)
    common_local = local_row_shift_signal.notna() & strict_local_signal.notna()
    row_shift_disagreement = common_local & ~np.isclose(
        local_row_shift_signal,
        strict_local_signal,
        rtol=0.0,
        atol=0.0,
    )
    local_signal = strict_local_signal

    # Cross-market holidays require a strict calendar as-of, not a row shift.
    us_signal, us_source_date = strict_asof_signal(us_vix, index)

    frame = pd.DataFrame(
        {
            "nifty_close": nifty,
            "return": returns,
            "simple_return": simple_returns,
            "open_to_next_open_return": open_to_next_open_returns,
            "holding_end_date": holding_end_date,
            "r2": r2,
            "india_vix_signal": local_signal,
            "us_vix_signal": us_signal,
            "india_vix_source_date": local_source_date,
            "us_vix_source_date": us_source_date,
        },
        index=index,
    )
    previous_nifty_date = frame.index.to_series().shift(1)
    frame["previous_nifty_date"] = previous_nifty_date
    frame["intervening_india_vix_session"] = (
        pd.to_datetime(frame["india_vix_source_date"]) > previous_nifty_date
    )
    # Such a row's close-to-close return spans an omitted NIFTY vendor date and
    # its India VIX source falls inside that aggregated return window.  Exclude
    # the target, and exclude the corresponding Open[t]->Open[next] strategy
    # holding interval rather than pretending either is a one-session return.
    bad_holding_start = frame["intervening_india_vix_session"].shift(
        -1, fill_value=False
    )
    frame.loc[bad_holding_start, "open_to_next_open_return"] = np.nan
    frame["india_iv_daily_var"] = (frame["india_vix_signal"] / 100.0) ** 2 / TRADING_DAYS
    frame["us_iv_daily_var"] = (frame["us_vix_signal"] / 100.0) ** 2 / TRADING_DAYS

    clean_r2 = frame.loc[~frame["intervening_india_vix_session"], "r2"]
    lagged_r2 = clean_r2.shift(1)
    frame["har_d"] = np.log(lagged_r2.clip(lower=1e-12))
    frame["har_w"] = np.log(lagged_r2.rolling(HAR_WINDOWS[1]).mean().clip(lower=1e-12))
    frame["har_m"] = np.log(lagged_r2.rolling(HAR_WINDOWS[2]).mean().clip(lower=1e-12))
    frame["log_india_iv"] = np.log(frame["india_iv_daily_var"].clip(lower=1e-12))
    frame["log_us_iv"] = np.log(frame["us_iv_daily_var"].clip(lower=1e-12))
    frame["log_r2"] = np.log(clean_r2.clip(lower=1e-12))

    required = [
        "return",
        "r2",
        "india_vix_signal",
        "us_vix_signal",
        "har_d",
        "har_w",
        "har_m",
    ]
    model_frame = frame.loc[~frame["intervening_india_vix_session"]].dropna(
        subset=required
    ).copy()

    local_age = (
        model_frame.index.to_series()
        - pd.to_datetime(model_frame["india_vix_source_date"])
    ).dt.days
    us_age = (
        model_frame.index.to_series() - pd.to_datetime(model_frame["us_vix_source_date"])
    ).dt.days
    if (local_age <= 0).any() or (us_age <= 0).any():
        raise AssertionError("Every forecasting signal must predate its target")

    diagnostics = {
        "nifty": {
            "start": nifty.index.min(),
            "end": nifty.index.max(),
            "n_obs_close": len(nifty),
            "n_obs_returns": int(returns.notna().sum()),
            "duplicate_dates": int(nifty.index.duplicated().sum()),
        },
        "india_vix": {
            "start": india_vix.index.min(),
            "end": india_vix.index.max(),
            "n_obs": len(india_vix),
            "duplicate_dates": int(india_vix.index.duplicated().sum()),
        },
        "us_vix": {
            "start": us_vix.index.min(),
            "end": us_vix.index.max(),
            "n_obs": len(us_vix),
            "duplicate_dates": int(us_vix.index.duplicated().sum()),
        },
        "common_model_sample": {
            "start": model_frame.index.min(),
            "end": model_frame.index.max(),
            "n_obs": len(model_frame),
            "local_signal_age_days": {
                "min": int(local_age.min()),
                "median": float(local_age.median()),
                "max": int(local_age.max()),
            },
            "us_signal_age_days": {
                "min": int(us_age.min()),
                "median": float(us_age.median()),
                "max": int(us_age.max()),
            },
        },
        "vendor_calendar_integrity": {
            "india_row_shift_vs_strict_asof_disagreements": int(
                row_shift_disagreement.sum()
            ),
            "excluded_multi_session_nifty_targets": int(
                frame["intervening_india_vix_session"].sum()
            ),
            "excluded_target_dates": [
                timestamp.date().isoformat()
                for timestamp in frame.index[frame["intervening_india_vix_session"]]
            ],
            "rule": "Exclude a NIFTY target when the latest prior India VIX source date is later than the previous observed NIFTY date; that target return spans a vendor-calendar gap and would otherwise contain the predictor inside its return window.",
        },
        "return_diagnostics": {
            "mean_daily": float(model_frame["return"].mean()),
            "annualized_vol": float(model_frame["return"].std(ddof=1) * np.sqrt(TRADING_DAYS)),
            "skewness": float(model_frame["return"].skew()),
            "excess_kurtosis": float(model_frame["return"].kurtosis()),
            "acf_r2_lag1": float(model_frame["r2"].autocorr(1)),
            "acf_r2_lag5": float(model_frame["r2"].autocorr(5)),
            "zero_close_to_close_returns": int((model_frame["return"] == 0).sum()),
        },
        "bear_market_oos_coverage": {
            "covid_2020_obs": int((model_frame.index.year == 2020).sum()),
            "inflation_bear_2022_obs": int((model_frame.index.year == 2022).sum()),
            "gfc_2008_descriptive_only": int((model_frame.index.year == 2008).sum()),
            "note": "2008 is retained for diagnostics/training; formal OOS includes 2020 and 2022 because India VIX begins in 2008.",
        },
    }
    strategy_frame = frame.copy()
    return model_frame, strategy_frame, diagnostics


def run_granger(
    nifty_returns: pd.Series,
    india_vix: pd.Series,
    us_vix: pd.Series,
    excluded_gap_targets: int,
) -> dict[str, Any]:
    """Conditional VAR Granger tests using exact common calendar dates.

    All causes enter with lag >= 1.  For US VIX this is also the latest US close
    available before the next Indian session.  Daily log-r2 is non-overlapping;
    this avoids manufacturing significance with a rolling multi-day target.
    """
    daily_r2 = nifty_returns.pow(2)
    gc = pd.concat(
        [
            np.log(daily_r2.clip(lower=1e-12)).rename("nifty_log_r2"),
            np.log(india_vix.clip(lower=1e-6)).rename("india_log_vix"),
            np.log(us_vix.clip(lower=1e-6)).rename("us_log_vix"),
        ],
        axis=1,
        sort=False,
        join="inner",
    ).dropna()
    if len(gc) < 500:
        raise RuntimeError(f"Insufficient exact-date observations for Granger test: {len(gc)}")

    lag_selection_sample = gc.loc[gc.index < pd.Timestamp(f"{OOS_START_YEAR}-01-01")]
    select = VAR(lag_selection_sample).select_order(maxlags=5)
    selected_lag = int(select.selected_orders.get("aic") or 1)
    selected_lag = max(1, min(selected_lag, 5))
    fitted = VAR(gc).fit(selected_lag, trend="c")

    raw_tests: dict[str, Any] = {}
    p_values: list[float] = []
    for cause in ("india_log_vix", "us_log_vix"):
        test = fitted.test_causality("nifty_log_r2", [cause], kind="f")
        raw_tests[cause] = {
            "f_stat": float(test.test_statistic),
            "p_value": float(test.pvalue),
            "df": [int(v) for v in np.atleast_1d(test.df)],
            "direction": f"{cause} -> next NIFTY log r2 conditional on the other VIX",
        }
        p_values.append(float(test.pvalue))
    rejected, adjusted, _, _ = multipletests(p_values, alpha=0.05, method="holm")
    for i, cause in enumerate(("india_log_vix", "us_log_vix")):
        raw_tests[cause]["holm_p_value"] = float(adjusted[i])
        raw_tests[cause]["holm_reject_5pct"] = bool(rejected[i])

    adf = {}
    for column in gc.columns:
        stat, p_value, usedlag, nobs, *_ = adfuller(gc[column], autolag="AIC")
        adf[column] = {
            "stat": float(stat),
            "p_value": float(p_value),
            "used_lag": int(usedlag),
            "n_obs": int(nobs),
        }
    return {
        "sample_start": gc.index.min(),
        "sample_end": gc.index.max(),
        "n_obs": len(gc),
        "excluded_vendor_calendar_gap_targets": excluded_gap_targets,
        "selected_lag_aic": selected_lag,
        "lag_selected_on_pre_oos_sample": {
            "end": lag_selection_sample.index.max(),
            "n_obs": len(lag_selection_sample),
        },
        "tests": raw_tests,
        "adf_levels": adf,
        "caveat": "Granger predictability is not structural causality; daily log-r2 is noisy, and daily r2 OOS QLIKE is primary.",
    }


def garch_filter(
    params: np.ndarray, returns_pct: np.ndarray, exog_pct_var: np.ndarray | None
) -> np.ndarray:
    omega, alpha, gamma, beta = params[:4]
    delta = params[4] if exog_pct_var is not None else 0.0
    n = len(returns_pct)
    h = np.empty(n, dtype=float)
    h[0] = max(float(np.var(returns_pct[: min(n, 252)], ddof=1)), 1e-6)
    for t in range(1, n):
        x_t = float(exog_pct_var[t]) if exog_pct_var is not None else 0.0
        previous_r2 = returns_pct[t - 1] ** 2
        leverage = previous_r2 if returns_pct[t - 1] < 0 else 0.0
        h[t] = omega + alpha * previous_r2 + gamma * leverage + beta * h[t - 1] + delta * x_t
        h[t] = max(h[t], 1e-8)
    return h


def fit_garch_x(
    returns: pd.Series, exog_daily_var: pd.Series | None, rng: np.random.Generator
) -> dict[str, Any]:
    r_pct = returns.to_numpy(dtype=float) * 100.0
    x_pct_var = (
        exog_daily_var.to_numpy(dtype=float) * 10000.0 if exog_daily_var is not None else None
    )
    burn_in = min(252, max(50, len(r_pct) // 10))

    def objective(params: np.ndarray) -> float:
        omega, alpha, gamma, beta = params[:4]
        persistence = alpha + 0.5 * gamma + beta
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or persistence >= 0.998:
            return 1e12 + 1e8 * max(persistence - 0.998, 0.0)
        if len(params) == 5 and params[4] < 0:
            return 1e12
        h = garch_filter(params, r_pct, x_pct_var)
        contributions = 0.5 * (np.log(2 * np.pi) + np.log(h) + r_pct**2 / h)
        return float(np.sum(contributions[burn_in:]))

    sample_var = max(float(np.var(r_pct, ddof=1)), 1e-4)
    starts = [
        np.array([sample_var * 0.02, 0.04, 0.06, 0.88] + ([0.05] if x_pct_var is not None else [])),
        np.array([sample_var * 0.05, 0.08, 0.10, 0.78] + ([0.15] if x_pct_var is not None else [])),
    ]
    for _ in range(3):
        alpha = float(rng.uniform(0.02, 0.15))
        gamma = float(rng.uniform(0.01, 0.16))
        beta_upper = max(0.73, 0.96 - alpha - 0.5 * gamma)
        beta = float(rng.uniform(0.70, beta_upper))
        delta = [float(rng.uniform(0.01, 0.30))] if x_pct_var is not None else []
        starts.append(
            np.array([sample_var * rng.uniform(0.005, 0.08), alpha, gamma, beta] + delta)
        )

    bounds = [(1e-8, 50.0), (0.0, 0.998), (0.0, 0.998), (0.0, 0.998)]
    if x_pct_var is not None:
        bounds.append((0.0, 5.0))
    constraint = {"type": "ineq", "fun": lambda p: 0.998 - p[1] - 0.5 * p[2] - p[3]}
    candidates = []
    for start in starts:
        fitted = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=bounds,
            constraints=[constraint],
            options={"maxiter": 1000, "ftol": 1e-10, "disp": False},
        )
        candidates.append(fitted)
    successful = [result for result in candidates if result.success and np.isfinite(result.fun)]
    if not successful:
        messages = "; ".join(str(result.message) for result in candidates)
        raise RuntimeError(f"All GJR-GARCH-X optimization starts failed: {messages}")
    best = min(successful, key=lambda result: float(result.fun))
    params = np.asarray(best.x, dtype=float)
    filtered = garch_filter(params, r_pct, x_pct_var)
    standardized = pd.Series(r_pct[burn_in:] / np.sqrt(filtered[burn_in:]))
    parameter_names = ["omega", "alpha", "gamma", "beta"] + (
        ["delta"] if x_pct_var is not None else []
    )
    lower_bounds = np.asarray([bound[0] for bound in bounds], dtype=float)
    upper_bounds = np.asarray([bound[1] for bound in bounds], dtype=float)
    tolerance = 1e-6 * np.maximum(1.0, upper_bounds - lower_bounds)
    successful_objectives = sorted(float(result.fun) for result in successful)
    return {
        "params": params,
        "last_variance_pct2": float(filtered[-1]),
        "last_return_pct": float(r_pct[-1]),
        "objective": float(best.fun),
        "converged": bool(best.success),
        "message": str(best.message),
        "n_starts": len(starts),
        "n_successful_starts": len(successful),
        "burn_in_not_scored": burn_in,
        "successful_objectives_sorted": successful_objectives,
        "best_objective_gap_to_second": (
            float(successful_objectives[1] - successful_objectives[0])
            if len(successful_objectives) > 1
            else None
        ),
        "optimizer_gradient_max_abs": (
            float(np.max(np.abs(np.asarray(best.jac, dtype=float))))
            if getattr(best, "jac", None) is not None
            else None
        ),
        "constraint_slack": float(0.998 - params[1] - 0.5 * params[2] - params[3]),
        "bound_hits": {
            name: {
                "lower": bool(abs(value - lower) <= tol),
                "upper": bool(abs(value - upper) <= tol),
            }
            for name, value, lower, upper, tol in zip(
                parameter_names, params, lower_bounds, upper_bounds, tolerance
            )
        },
        "persistence": float(params[1] + 0.5 * params[2] + params[3]),
        "near_persistence_boundary": bool(params[1] + 0.5 * params[2] + params[3] > 0.995),
        "standardized_residual_diagnostics": {
            "n_obs": len(standardized),
            "mean": float(standardized.mean()),
            "std": float(standardized.std(ddof=1)),
            "skewness": float(standardized.skew()),
            "excess_kurtosis": float(standardized.kurtosis()),
            "acf_lag_1": float(standardized.autocorr(1)),
            "squared_acf_lag_1": float(standardized.pow(2).autocorr(1)),
            "squared_acf_lag_5": float(standardized.pow(2).autocorr(5)),
        },
    }


def forecast_garch_x(
    fitted: dict[str, Any], test: pd.DataFrame, exog_column: str | None
) -> np.ndarray:
    params = np.asarray(fitted["params"], dtype=float)
    omega, alpha, gamma, beta = params[:4]
    delta = params[4] if exog_column is not None else 0.0
    previous_h = float(fitted["last_variance_pct2"])
    previous_return = float(fitted["last_return_pct"])
    output = np.empty(len(test), dtype=float)
    for i, (_, row) in enumerate(test.iterrows()):
        x_t = float(row[exog_column]) * 10000.0 if exog_column is not None else 0.0
        previous_r2 = previous_return**2
        leverage = previous_r2 if previous_return < 0 else 0.0
        h_t = omega + alpha * previous_r2 + gamma * leverage + beta * previous_h + delta * x_t
        h_t = max(float(h_t), 1e-8)
        output[i] = h_t / 10000.0
        previous_h = h_t
        previous_return = float(row["return"]) * 100.0
    return output


def fit_predict_har(
    train: pd.DataFrame, test: pd.DataFrame, exog_column: str | None
) -> tuple[np.ndarray, dict[str, Any]]:
    columns = ["har_d", "har_w", "har_m"] + ([exog_column] if exog_column else [])
    x_train = np.column_stack([np.ones(len(train)), train[columns].to_numpy(dtype=float)])
    y_train = train["log_r2"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    residual = y_train - x_train @ beta
    residual_variance = float(np.var(residual, ddof=x_train.shape[1]))
    x_test = np.column_stack([np.ones(len(test)), test[columns].to_numpy(dtype=float)])
    log_forecast = x_test @ beta + 0.5 * residual_variance
    forecast = np.exp(np.clip(log_forecast, -30.0, 2.0))
    return forecast, {
        "columns": ["intercept"] + columns,
        "coefficients": beta,
        "residual_variance": residual_variance,
        "rank": int(np.linalg.matrix_rank(x_train)),
        "n_train": len(train),
    }


def annual_expanding_oos(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    forecasts: list[pd.DataFrame] = []
    fit_log: dict[str, Any] = {}
    rng = np.random.default_rng(SEED)

    for year in range(OOS_START_YEAR, OOS_END_YEAR + 1):
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        train = frame.loc[frame.index < start].copy()
        test = frame.loc[(frame.index >= start) & (frame.index <= end)].copy()
        if len(test) == 0:
            continue
        if len(train) < MIN_TRAIN_OBS:
            raise RuntimeError(f"Year {year}: only {len(train)} training observations")

        year_fit: dict[str, Any] = {
            "train_start": train.index.min(),
            "train_end": train.index.max(),
            "n_train": len(train),
            "test_start": test.index.min(),
            "test_end": test.index.max(),
            "n_test": len(test),
            "models": {},
        }

        base_fit = fit_garch_x(train["return"], None, rng)
        india_fit = fit_garch_x(train["return"], train["india_iv_daily_var"], rng)
        us_fit = fit_garch_x(train["return"], train["us_iv_daily_var"], rng)
        year_fit["models"]["garch_base"] = base_fit
        year_fit["models"]["garch_x_india"] = india_fit
        year_fit["models"]["garch_x_us"] = us_fit

        har_base, har_base_fit = fit_predict_har(train, test, None)
        har_india, har_india_fit = fit_predict_har(train, test, "log_india_iv")
        har_us, har_us_fit = fit_predict_har(train, test, "log_us_iv")
        year_fit["models"]["har_base"] = har_base_fit
        year_fit["models"]["har_x_india"] = har_india_fit
        year_fit["models"]["har_x_us"] = har_us_fit

        fold = pd.DataFrame(
            {
                "actual_r2": test["r2"],
                "return": test["return"],
                "garch_base": forecast_garch_x(base_fit, test, None),
                "garch_x_india": forecast_garch_x(india_fit, test, "india_iv_daily_var"),
                "garch_x_us": forecast_garch_x(us_fit, test, "us_iv_daily_var"),
                "har_base": har_base,
                "har_x_india": har_india,
                "har_x_us": har_us,
            },
            index=test.index,
        )
        # Direct IV forecasts are calibrated using train data only.
        for label, column in (
            ("direct_india_iv", "india_iv_daily_var"),
            ("direct_us_iv", "us_iv_daily_var"),
        ):
            scale = float(train["r2"].mean() / train[column].mean())
            fold[label] = test[column] * scale
            year_fit["models"][label] = {"train_only_scale": scale}

        forecasts.append(fold)
        fit_log[str(year)] = year_fit

    oos = pd.concat(forecasts).sort_index()
    if oos.index.duplicated().any():
        raise AssertionError("OOS forecast dates must be unique")
    if len(oos) < 252:
        raise RuntimeError(f"Insufficient OOS observations: {len(oos)}")
    required_stress_years = {2020, 2022}
    observed_years = set(oos.index.year)
    missing_stress_years = sorted(required_stress_years - observed_years)
    if missing_stress_years:
        raise RuntimeError(
            f"Required OOS stress years are absent: {missing_stress_years}"
        )
    return oos, fit_log


def forecast_metrics(oos: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    model_names = [column for column in oos.columns if column not in {"actual_r2", "return"}]
    shared_mask = np.isfinite(oos["actual_r2"].to_numpy(dtype=float)) & (
        oos["actual_r2"].to_numpy(dtype=float) > 0
    )
    for name in model_names:
        predicted = oos[name].to_numpy(dtype=float)
        shared_mask &= np.isfinite(predicted) & (predicted > 0)
    evaluated = oos.loc[shared_mask].copy()
    if len(evaluated) < 252:
        raise RuntimeError(f"Insufficient shared positive OOS evaluation sample: {len(evaluated)}")

    actual = evaluated["actual_r2"].to_numpy(dtype=float)
    metrics: dict[str, Any] = {}
    losses: dict[str, np.ndarray] = {}
    for name in model_names:
        predicted = evaluated[name].to_numpy(dtype=float)
        pointwise = qlike_pointwise(actual, predicted)
        rho, rho_p = spearman_corr(actual, predicted)
        metrics[name] = {
            "qlike": qlike(actual, predicted),
            "mse": float(np.mean((actual - predicted) ** 2)),
            "spearman_rho": rho,
            "spearman_p_value": rho_p,
            "mean_forecast_annualized_vol": float(np.sqrt(np.mean(predicted) * TRADING_DAYS)),
            "n_obs_shared_positive_mask": len(evaluated),
        }
        losses[name] = pointwise

    pairs = [
        ("garch_x_india", "garch_x_us", "primary_local_vs_us_garch"),
        ("har_x_india", "har_x_us", "primary_local_vs_us_har"),
        ("garch_x_india", "garch_base", "local_vs_base_garch"),
        ("garch_x_us", "garch_base", "us_vs_base_garch"),
        ("har_x_india", "har_base", "local_vs_base_har"),
        ("har_x_us", "har_base", "us_vs_base_har"),
    ]
    # nested-dm: cw-primary
    # The four X-vs-base raw-DM rows never feed the verdict; Clark-West covers
    # every nested comparison.  Only the two India-vs-US non-nested pairs use
    # primary DM inference.
    comparisons: dict[str, Any] = {}
    primary_labels = {"primary_local_vs_us_garch", "primary_local_vs_us_har"}
    primary_p_values = []
    for model1, model2, label in pairs:
        t_stat, p_value = dm_test(losses[model1], losses[model2], h=1)
        diff = pd.Series(losses[model1] - losses[model2], index=evaluated.index)
        comparisons[label] = {
            "model_1": model1,
            "model_2": model2,
            "t_stat": t_stat,
            "p_value": p_value,
            "direction": "negative favors model_1; positive favors model_2",
            "harvey_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "n_obs": len(diff),
            "canonical_hac_lag": int(max(1, min(math.ceil(len(diff) ** (1 / 3)), len(diff) // 4))),
            "loss_diff_acf": {
                "lag_1": float(diff.autocorr(1)),
                "lag_5": float(diff.autocorr(5)),
                "lag_10": float(diff.autocorr(10)),
            },
            "hac_lag_sensitivity_dm_t": hac_lag_sensitivity(diff.to_numpy(dtype=float)),
            "inference_role": (
                "primary non-nested forecast comparison"
                if label in primary_labels
                else "nested diagnostic DM; Clark-West MSE test is also reported"
            ),
        }
        if label in primary_labels:
            primary_p_values.append(p_value)
    rejected, adjusted, _, _ = multipletests(primary_p_values, alpha=0.05, method="holm")
    for i, label in enumerate(("primary_local_vs_us_garch", "primary_local_vs_us_har")):
        comparisons[label]["holm_p_value_2_primary_tests"] = float(adjusted[i])
        comparisons[label]["holm_reject_5pct_2_primary_tests"] = bool(rejected[i])

    comparisons["nested_clark_west_mse"] = {
        "local_vs_base_garch": clark_west_test(
            actual,
            evaluated["garch_base"].to_numpy(dtype=float),
            evaluated["garch_x_india"].to_numpy(dtype=float),
            h=1,
        ),
        "us_vs_base_garch": clark_west_test(
            actual,
            evaluated["garch_base"].to_numpy(dtype=float),
            evaluated["garch_x_us"].to_numpy(dtype=float),
            h=1,
        ),
        "local_vs_base_har": clark_west_test(
            actual,
            evaluated["har_base"].to_numpy(dtype=float),
            evaluated["har_x_india"].to_numpy(dtype=float),
            h=1,
        ),
        "us_vs_base_har": clark_west_test(
            actual,
            evaluated["har_base"].to_numpy(dtype=float),
            evaluated["har_x_us"].to_numpy(dtype=float),
            h=1,
        ),
    }
    comparisons["nested_clark_west_inference_note"] = {
        "role": "exploratory nested-model diagnostics; never feeds the pre-registered India-vs-US gate",
        "multiplicity": "individual unadjusted p-values across four diagnostics; no familywise claim is made",
    }
    comparisons["shared_evaluation_mask"] = {
        "rule": "actual_r2 and every model forecast must be finite and strictly positive",
        "n_raw_oos": len(oos),
        "n_evaluated": len(evaluated),
        "n_dropped": int(len(oos) - len(evaluated)),
    }

    return metrics, comparisons


def hac_lag_sensitivity(loss_differential: np.ndarray) -> dict[str, Any]:
    """Diagnostic Bartlett-HAC t statistics; canonical ``dm_test`` remains primary."""
    values = np.asarray(loss_differential, dtype=np.float64)
    values = values[np.isfinite(values)]
    n = len(values)
    canonical_lag = max(1, min(math.ceil(n ** (1 / 3)), n // 4))
    output: dict[str, Any] = {}
    mean = float(np.mean(values))
    centered = values - mean
    for lag in sorted({0, 1, 5, 10, canonical_lag, 20, 30}):
        lag = min(lag, n - 1)
        long_run_var = float(np.mean(centered**2))
        for k in range(1, lag + 1):
            weight = 1.0 - k / (lag + 1.0)
            long_run_var += 2.0 * weight * float(
                np.mean(centered[k:] * centered[:-k])
            )
        t_stat = mean / math.sqrt(long_run_var / n) if long_run_var > 0 else None
        output[f"lag_{lag}"] = {
            "t_stat": t_stat,
            "hac_applied": bool(lag > 0),
            "is_canonical_bandwidth": bool(lag == canonical_lag),
        }
    return output


def information_gate(metrics: dict[str, Any], comparisons: dict[str, Any]) -> dict[str, Any]:
    garch_cmp = comparisons["primary_local_vs_us_garch"]
    har_cmp = comparisons["primary_local_vs_us_har"]
    local_better_both = (
        metrics["garch_x_india"]["qlike"] < metrics["garch_x_us"]["qlike"]
        and metrics["har_x_india"]["qlike"] < metrics["har_x_us"]["qlike"]
    )
    significant_local_win = all(
        cmp["t_stat"] < -3.0 and cmp["holm_reject_5pct_2_primary_tests"]
        for cmp in (garch_cmp, har_cmp)
    )
    significant_opposing_win = any(
        cmp["t_stat"] > 3.0 and cmp["holm_reject_5pct_2_primary_tests"]
        for cmp in (garch_cmp, har_cmp)
    )
    passed = bool(local_better_both and significant_local_win and not significant_opposing_win)
    return {
        "passed": passed,
        "pre_registered_rule": "India VIX must have lower OOS QLIKE in both GJR-GARCH-X and HAR-style-X; both local-vs-US canonical DM tests must have t<-3 and Holm p<0.05 across the two primary non-nested comparisons; no opposing significant win is allowed.",
        "local_lower_qlike_both_families": bool(local_better_both),
        "both_families_significant_local_win": bool(significant_local_win),
        "no_significant_opposing_win": bool(not significant_opposing_win),
    }


def monthly_weights(signal: pd.Series, c_value: float) -> pd.Series:
    raw = (c_value / signal).clip(lower=0.0, upper=MAX_EQUITY_WEIGHT)
    month = pd.Series(raw.index.to_period("M"), index=raw.index)
    rebalance = month.ne(month.shift(1))
    held = raw.where(rebalance).ffill()
    return held


def strategy_path(
    weights: pd.Series, returns: pd.Series, tx_cost_bps: float
) -> pd.DataFrame:
    """Self-financing monthly-target portfolio on one-period holding returns.

    ``weights`` repeats the monthly target on daily rows.  Between target
    changes the risky share drifts with the asset return rather than being
    costlessly reset each day.  At a target change, costs are assessed on the
    actual pre-trade risky share; the post-cost portfolio then starts at the
    requested target weight.
    """
    timeline = pd.concat(
        [weights.rename("weight"), returns.rename("return")], axis=1
    ).sort_index()
    output_index: list[pd.Timestamp] = []
    net_returns: list[float] = []
    turnover_values: list[float] = []
    start_weights: list[float] = []
    cost_fraction_values: list[float] = []
    current_weight = 0.0
    previous_month: pd.Period | None = None
    cost_rate = tx_cost_bps / 10000.0
    for date, target, asset_return in timeline[["weight", "return"]].itertuples(
        index=True, name=None
    ):
        if not (np.isfinite(target) and np.isfinite(asset_return)):
            # A missing holding return breaks self-financing continuity.  Move
            # to cash at the endpoint of the last observed interval (including
            # its exit turnover/cost), then require a fresh entry on the next
            # valid interval.  No unobserved return is imputed.
            if net_returns and current_weight != 0.0:
                exit_turnover = abs(current_weight)
                exit_cost = exit_turnover * cost_rate
                net_returns[-1] = (1.0 + net_returns[-1]) * (1.0 - exit_cost) - 1.0
                turnover_values[-1] += exit_turnover
                cost_fraction_values[-1] = 1.0 - (
                    (1.0 - cost_fraction_values[-1]) * (1.0 - exit_cost)
                )
            current_weight = 0.0
            previous_month = None
            continue
        target = float(target)
        asset_return = float(asset_return)
        month = pd.Timestamp(date).to_period("M")
        rebalance = previous_month is None or month != previous_month
        if rebalance:
            turnover = abs(target - current_weight)
            start_weight = target
        else:
            turnover = 0.0
            start_weight = current_weight
        cost_fraction = turnover * cost_rate
        gross_factor = 1.0 + start_weight * asset_return
        net_return = (1.0 - cost_fraction) * gross_factor - 1.0
        if gross_factor <= 0:
            raise RuntimeError("Nonpositive portfolio gross factor in VT simulation")
        output_index.append(pd.Timestamp(date))
        net_returns.append(net_return)
        turnover_values.append(turnover)
        start_weights.append(start_weight)
        cost_fraction_values.append(cost_fraction)
        current_weight = start_weight * (1.0 + asset_return) / gross_factor
        previous_month = month
    return pd.DataFrame(
        {
            "strategy_return": net_returns,
            "turnover": turnover_values,
            "start_weight": start_weights,
            "cost_fraction": cost_fraction_values,
        },
        index=pd.DatetimeIndex(output_index),
    )


def strategy_returns(
    weights: pd.Series, returns: pd.Series, tx_cost_bps: float
) -> tuple[pd.Series, pd.Series]:
    path = strategy_path(weights, returns, tx_cost_bps)
    return path["strategy_return"], path["turnover"]


def strategy_metrics(returns: pd.Series, turnover: pd.Series | None = None) -> dict[str, Any]:
    ann_return = float(returns.mean() * TRADING_DAYS)
    ann_vol = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    return {
        "n_obs": len(returns),
        "annualized_return": ann_return,
        "annualized_vol": ann_vol,
        "sharpe_zero_cash_rate": ann_return / ann_vol if ann_vol > 0 else None,
        "max_drawdown": max_drawdown(returns.to_numpy()),
        "cumulative_return": float(np.prod(1.0 + returns.to_numpy()) - 1.0),
        "turnover_per_year": (
            float(turnover.sum() / len(turnover) * TRADING_DAYS) if turnover is not None else 0.0
        ),
    }


def phase_randomization_mdd_test(
    weights: pd.Series,
    returns: pd.Series,
    benchmark: pd.Series,
    tx_cost_bps: float,
) -> dict[str, Any]:
    observed_path = strategy_path(weights, returns, tx_cost_bps)
    aligned = pd.concat(
        [
            observed_path,
            returns.rename("return"),
            benchmark.rename("benchmark"),
        ],
        axis=1,
    ).dropna()
    observed_cmp = compare_max_drawdown(
        aligned["strategy_return"].to_numpy(), aligned["benchmark"].to_numpy()
    )
    rng = np.random.default_rng(SEED + 1717)
    null_gaps = np.empty(BOOTSTRAP_REPS, dtype=float)
    n = len(aligned)
    for i in range(BOOTSTRAP_REPS):
        offset = int(rng.integers(1, n))
        # Shift the already-realized exposure and cost paths together.  This
        # preserves their exact values, persistence, and total cost while
        # destroying only their phase alignment with the return path.
        shifted_weight = np.roll(aligned["start_weight"].to_numpy(), offset)
        shifted_cost = np.roll(aligned["cost_fraction"].to_numpy(), offset)
        shifted_returns = (
            (1.0 - shifted_cost)
            * (1.0 + shifted_weight * aligned["return"].to_numpy(dtype=float))
            - 1.0
        )
        null_cmp = compare_max_drawdown(shifted_returns, aligned["benchmark"].to_numpy())
        null_gaps[i] = null_cmp.exposure_matched_gap
    p_value = (1.0 + float(np.sum(null_gaps >= observed_cmp.exposure_matched_gap))) / (
        BOOTSTRAP_REPS + 1.0
    )
    return {
        "observed_comparison": asdict(observed_cmp),
        "null_reps": BOOTSTRAP_REPS,
        "null_gap_mean": float(np.mean(null_gaps)),
        "null_gap_ci_95": [float(np.quantile(null_gaps, 0.025)), float(np.quantile(null_gaps, 0.975))],
        "one_sided_p_value": p_value,
        "timing_drawdown_skill_reject_5pct": bool(
            observed_cmp.exposure_matched_gap > 0 and p_value < 0.05
        ),
        "positive_exposure_matched_gap_required": bool(
            observed_cmp.exposure_matched_gap > 0
        ),
        "interpretation_rule": "A positive exposure-matched gap alone is insufficient; significance requires beating the circular-shift weight-path null.",
        "null_construction": "Circularly shift the realized start-of-holding exposure path and its cost-fraction path together; their values, persistence, and total cost remain fixed while alignment with NIFTY returns is destroyed.",
    }


def run_vt_strategy(frame: pd.DataFrame) -> dict[str, Any]:
    # Retain rows with a deliberately missing holding return so strategy_path
    # can reset the self-financing state and charge exit/re-entry costs.  Only
    # the terminal row (no next open) is removed here.
    strategy_frame = frame.dropna(subset=["holding_end_date"]).copy()
    oos_start = pd.Timestamp(f"{OOS_START_YEAR}-01-01")
    # Each row earns Open[t] -> Open[t+1].  Keep calibration holding periods
    # wholly before OOS so the 2019 fit cannot consume a 2020 return.
    in_sample = strategy_frame.loc[
        pd.to_datetime(strategy_frame["holding_end_date"]) < oos_start
    ]
    oos = strategy_frame.loc[strategy_frame.index >= oos_start]
    c_grid = np.arange(4.0, 20.5, 0.5)
    calibration: dict[str, Any] = {}
    selected: dict[str, float] = {}

    for source, signal_column in (
        ("india_vix", "india_vix_signal"),
        ("us_vix", "us_vix_signal"),
    ):
        rows = []
        for c_value in c_grid:
            weights = monthly_weights(in_sample[signal_column], float(c_value))
            strategy, turnover = strategy_returns(
                weights, in_sample["open_to_next_open_return"], TX_COST_BPS_PRIMARY
            )
            metrics = strategy_metrics(strategy, turnover)
            rows.append(
                {
                    "c": float(c_value),
                    "is_annualized_vol": metrics["annualized_vol"],
                    "is_sharpe_diagnostic_not_selection_target": metrics[
                        "sharpe_zero_cash_rate"
                    ],
                }
            )
        best = min(rows, key=lambda row: abs(float(row["is_annualized_vol"]) - TARGET_VOL))
        calibration[source] = {
            "selection_rule": f"minimize |IS annualized vol - {TARGET_VOL:.0%}|; never maximize Sharpe",
            "grid": rows,
            "selected": best,
        }
        selected[source] = float(best["c"])

    weights_local = monthly_weights(oos["india_vix_signal"], selected["india_vix"])
    weights_us = monthly_weights(oos["us_vix_signal"], selected["us_vix"])
    gross_holding_return = oos["open_to_next_open_return"].copy()
    cost_sensitivity: dict[str, Any] = {}
    primary_returns: dict[str, pd.Series] = {}
    primary_benchmark = pd.Series(dtype=float)
    primary_benchmark_turnover = pd.Series(dtype=float)
    for cost_bps in TX_COST_BPS_SENSITIVITY:
        local_ret, local_turnover = strategy_returns(
            weights_local, gross_holding_return, cost_bps
        )
        us_ret, us_turnover = strategy_returns(
            weights_us, gross_holding_return, cost_bps
        )
        baseline_ret, baseline_turnover = strategy_returns(
            pd.Series(1.0, index=oos.index, name="always_invested_weight"),
            gross_holding_return,
            cost_bps,
        )
        cost_sensitivity[str(cost_bps)] = {
            "india_vix_vt": strategy_metrics(local_ret, local_turnover),
            "us_vix_vt": strategy_metrics(us_ret, us_turnover),
            "always_invested_open_to_open": strategy_metrics(
                baseline_ret, baseline_turnover
            ),
        }
        if cost_bps == TX_COST_BPS_PRIMARY:
            primary_returns = {"india": local_ret, "us": us_ret}
            primary_benchmark = baseline_ret
            primary_benchmark_turnover = baseline_turnover

    benchmark = primary_benchmark.reindex(primary_returns["india"].index)
    local_vs_always_invested = compare_max_drawdown(
        primary_returns["india"].to_numpy(), benchmark.to_numpy()
    )
    local_vs_us = compare_max_drawdown(
        primary_returns["india"].to_numpy(), primary_returns["us"].to_numpy()
    )
    dm_return = strategy_dm_test(
        primary_returns["india"].to_numpy(),
        primary_returns["us"].to_numpy(),
        h=1,
        loss_fn="negative_return",
    )
    dm_downside = strategy_dm_test(
        primary_returns["india"].to_numpy(),
        primary_returns["us"].to_numpy(),
        h=1,
        loss_fn="downside",
    )
    phase_test = phase_randomization_mdd_test(
        weights_local,
        gross_holding_return,
        benchmark,
        TX_COST_BPS_PRIMARY,
    )

    return {
        "status": "run_after_information_gate_pass",
        "method_type": "empirical NIFTY open-to-next-open index-return simulation; not a directly tradable product backtest",
        "in_sample_calibration_period": {
            "start": in_sample.index.min(),
            "end": in_sample.index.max(),
            "n_obs": len(in_sample),
        },
        "oos_period": {
            "start": oos.index.min(),
            "end": oos.index.max(),
            "n_obs": len(oos),
        },
        "monthly_rebalance": True,
        "max_equity_weight": MAX_EQUITY_WEIGHT,
        "cash_return_assumption": 0.0,
        "execution_timing": "The prior-close signal is known before Open[t]; monthly exposure is set at Open[t] and earns Open[t] to Open[t+1], including the economically inseparable overnight holding return. Turnover is charged only when that held weight changes.",
        "transaction_cost_assumption": {
            "primary_bps_per_dollar_turnover": TX_COST_BPS_PRIMARY,
            "sensitivity_bps": list(TX_COST_BPS_SENSITIVITY),
            "limitation": "No canonical India cash-index transaction-cost table exists in the repo; these are transparent hypothetical sensitivities, not an official cost estimate.",
        },
        "calibration": calibration,
        "selected_c": selected,
        "cost_sensitivity": cost_sensitivity,
        "always_invested_open_to_open": strategy_metrics(
            benchmark, primary_benchmark_turnover.reindex(benchmark.index)
        ),
        "primary_comparisons": {
            "india_vix_vt_vs_always_invested_open_to_open_drawdown": asdict(
                local_vs_always_invested
            ),
            "india_vix_vt_vs_us_vix_vt_drawdown": asdict(local_vs_us),
            "india_vs_us_strategy_dm_negative_return": {
                "t_stat": dm_return[0],
                "p_value": dm_return[1],
                "direction": "negative favors India VIX VT",
                "inference_role": "conditional exploratory diagnostic after forecast-gate selection; unadjusted and not a deployment claim",
            },
            "india_vs_us_strategy_dm_downside": {
                "t_stat": dm_downside[0],
                "p_value": dm_downside[1],
                "direction": "negative favors India VIX VT",
                "inference_role": "conditional exploratory diagnostic after forecast-gate selection; unadjusted and not a deployment claim",
            },
            "india_vix_vt_drawdown_phase_randomization": phase_test,
        },
        "series_for_chart": {
            "india_vix_vt": primary_returns["india"],
            "us_vix_vt": primary_returns["us"],
            "always_invested_open_to_open": benchmark,
            "india_weight": weights_local.reindex(benchmark.index),
            "us_weight": weights_us.reindex(benchmark.index),
        },
    }


def annual_model_metrics(oos: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for year, group in oos.groupby(oos.index.year):
        year_metrics = {}
        actual = group["actual_r2"].to_numpy(dtype=float)
        for model in ("garch_x_india", "garch_x_us", "har_x_india", "har_x_us"):
            year_metrics[model] = qlike(actual, group[model].to_numpy(dtype=float))
        output[str(year)] = {"n_obs": len(group), "qlike": year_metrics}
    return output


def render_charts(
    metrics: dict[str, Any], annual_metrics: dict[str, Any], strategy: dict[str, Any]
) -> list[str]:
    chart_paths: list[str] = []
    names = [
        "garch_base",
        "garch_x_india",
        "garch_x_us",
        "har_base",
        "har_x_india",
        "har_x_us",
        "direct_india_iv",
        "direct_us_iv",
    ]
    labels = ["GJR", "GJR-X India", "GJR-X US", "HAR-style", "HAR-X India", "HAR-X US", "Direct India IV", "Direct US IV"]
    colors = ["#64748b", "#f97316", "#2563eb", "#94a3b8", "#fb923c", "#60a5fa", "#fdba74", "#93c5fd"]
    fig, ax = plt.subplots(figsize=(12, 6))
    values = [metrics[name]["qlike"] for name in names]
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("Mean QLIKE (lower is better)")
    ax.set_title("K1717: NIFTY one-day variance forecast comparison, OOS 2020-2026")
    ax.tick_params(axis="x", rotation=28)
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    path = SCRIPT_DIR / "k1717_oos_qlike.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path.name)

    years = [int(year) for year in annual_metrics]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
    for ax, family, title in (
        (axes[0], "garch_x", "GJR-GARCH-X"),
        (axes[1], "har_x", "HAR-style-X"),
    ):
        india_values = [annual_metrics[str(year)]["qlike"][f"{family}_india"] for year in years]
        us_values = [annual_metrics[str(year)]["qlike"][f"{family}_us"] for year in years]
        ax.plot(years, india_values, marker="o", color="#f97316", label="India VIX")
        ax.plot(years, us_values, marker="o", color="#2563eb", label="US VIX")
        ax.set_title(title)
        ax.set_ylabel("QLIKE")
        ax.grid(alpha=0.25)
        ax.legend()
    fig.suptitle("K1717: annual OOS stability (includes COVID 2020 and bear 2022)")
    fig.tight_layout()
    path = SCRIPT_DIR / "k1717_annual_stability.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    chart_paths.append(path.name)

    if strategy.get("status") == "run_after_information_gate_pass":
        series = strategy.pop("series_for_chart")
        fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
        for label, color in (("india_vix_vt", "#f97316"), ("us_vix_vt", "#2563eb"), ("always_invested_open_to_open", "#64748b")):
            cumulative = (1.0 + series[label]).cumprod()
            axes[0].plot(cumulative.index, cumulative, label=label.replace("_", " ").title(), color=color)
        axes[0].set_yscale("log")
        axes[0].set_ylabel("Growth of 1 (log scale)")
        axes[0].set_title("Monthly c/VIX NIFTY open-to-next-open index-return simulation, OOS")
        axes[0].grid(alpha=0.25)
        axes[0].legend()
        axes[1].plot(series["india_weight"].index, series["india_weight"], color="#f97316", label="India VIX weight")
        axes[1].plot(series["us_weight"].index, series["us_weight"], color="#2563eb", alpha=0.8, label="US VIX weight")
        axes[1].set_ylabel("NIFTY weight")
        axes[1].set_ylim(0, 1.05)
        axes[1].grid(alpha=0.25)
        axes[1].legend()
        fig.tight_layout()
        path = SCRIPT_DIR / "k1717_vt_oos.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        chart_paths.append(path.name)
    return chart_paths


def main() -> None:
    np.random.seed(SEED)
    print("K1717 ASIA-1: downloading longest available daily sample...")
    nifty_ohlc = download_ohlc("^NSEI", INDIA_DATA_END_EXCLUSIVE)
    nifty = nifty_ohlc["Close"].copy()
    india_vix = download_close("^INDIAVIX", INDIA_DATA_END_EXCLUSIVE)
    us_vix = download_close("^VIX", US_DATA_END_EXCLUSIVE)

    raw_data = pd.concat(
        [
            nifty_ohlc.rename(
                columns={
                    "Open": "nifty_open",
                    "High": "nifty_high",
                    "Low": "nifty_low",
                    "Close": "nifty_close",
                }
            ),
            india_vix.rename("india_vix"),
            us_vix.rename("us_vix"),
        ],
        axis=1,
        sort=False,
    )
    data_path = SCRIPT_DIR / "k1717_data.csv"
    atomic_write_csv(data_path, raw_data)

    model_frame, strategy_frame, diagnostics = build_dataset(
        nifty_ohlc, india_vix, us_vix
    )
    granger = run_granger(
        model_frame["return"],
        india_vix,
        us_vix,
        diagnostics["vendor_calendar_integrity"]["excluded_multi_session_nifty_targets"],
    )
    print(
        f"Data: NIFTY {nifty.index.min().date()}->{nifty.index.max().date()} n={len(nifty)}; "
        f"India VIX {india_vix.index.min().date()}->{india_vix.index.max().date()} n={len(india_vix)}"
    )
    print("Running annual expanding-origin OOS forecasts...")
    oos, fit_log = annual_expanding_oos(model_frame)
    metrics, comparisons = forecast_metrics(oos)
    gate = information_gate(metrics, comparisons)
    annual_metrics = annual_model_metrics(oos)

    if gate["passed"]:
        print("India-information gate PASS: running conditional VT simulation...")
        strategy = run_vt_strategy(strategy_frame)
    else:
        print("India-information gate FAIL: VT simulation skipped by pre-registered rule.")
        strategy = {
            "status": "skipped_by_pre_registered_information_gate",
            "reason": gate,
        }

    chart_names = render_charts(metrics, annual_metrics, strategy)
    convergence = {
        year: {
            name: model.get("converged")
            for name, model in details["models"].items()
            if name.startswith("garch")
        }
        for year, details in fit_log.items()
    }
    all_garch_converged = all(
        bool(value)
        for yearly in convergence.values()
        for value in yearly.values()
    )

    local_garch = comparisons["primary_local_vs_us_garch"]
    local_har = comparisons["primary_local_vs_us_har"]
    if gate["passed"]:
        conclusion = (
            "India VIX passes the pre-registered relative standalone forecast-performance gate versus US VIX. "
            "The conditional monthly NIFTY VT simulation is reported as an open-to-next-open index-return exercise, "
            "with hypothetical cost sensitivity and drawdown phase-randomization rather than a production strategy claim."
        )
        verdict = "CONDITIONAL_POSITIVE_INFORMATION_GATE_PASS"
    else:
        conclusion = (
            "India VIX does not pass the strict pre-registered relative standalone forecast-performance gate versus US VIX. "
            "The c/IndiaVIX VT sweep is therefore not run, and no trading conclusion is drawn."
        )
        verdict = "NULL_OR_MIXED_INFORMATION_GATE_FAIL"

    results = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "task_id": "asia1_india_vt_indiavix",
        "generated_at_utc": datetime.now(timezone.utc),
        "seed": SEED,
        "methodology_type": "empirical",
        "data_source": {
            "provider": "yfinance",
            "tickers": ["^NSEI", "^INDIAVIX", "^VIX"],
            "requested_period": {
                "start": DATA_START,
                "india_end_exclusive": INDIA_DATA_END_EXCLUSIVE,
                "us_end_exclusive": US_DATA_END_EXCLUSIVE,
                "us_cutoff_reason": "2026-07-15 US session was incomplete at execution time; last eligible US close is 2026-07-14.",
            },
            "snapshot_file": data_path.name,
            "snapshot_sha256": sha256_file(data_path),
            "retrieval_note": "Yahoo Finance is a mutable vendor source; the committed snapshot is the byte-level reproduction source.",
        },
        "pre_registered_design": {
            "forecast_target": "NIFTY close-to-close squared log return on Indian target date t",
            "information_set": "India VIX or latest US VIX close strictly before target date t; HAR return features end at t-1",
            "forecast_protocol": "Annual expanding-origin refit, one-day forecasts, OOS calendar years 2020-2026",
            "primary_loss": "Patton QLIKE(actual/predicted) on r2",
            "inference": "volpred.stats.model_evaluation.dm_test with canonical Newey-West bandwidth; Harvey |t|>3 plus Holm correction",
            "strategy_gate": gate["pre_registered_rule"],
        },
        "references": REFERENCES,
        "data_diagnostics": diagnostics,
        "granger_diagnostic": granger,
        "oos": {
            "start": oos.index.min(),
            "end": oos.index.max(),
            "n_obs": len(oos),
            "contains_covid_2020": bool((oos.index.year == 2020).any()),
            "contains_bear_2022": bool((oos.index.year == 2022).any()),
            "metrics": metrics,
            "dm_comparisons": comparisons,
            "annual_metrics": annual_metrics,
            "fit_log": fit_log,
            "garch_convergence_by_year": convergence,
            "all_garch_fits_converged": all_garch_converged,
        },
        "information_gate": gate,
        "strategy": strategy,
        "key_numbers": {
            "garch_x_india_qlike": metrics["garch_x_india"]["qlike"],
            "garch_x_us_qlike": metrics["garch_x_us"]["qlike"],
            "garch_local_vs_us_dm_t": local_garch["t_stat"],
            "har_x_india_qlike": metrics["har_x_india"]["qlike"],
            "har_x_us_qlike": metrics["har_x_us"]["qlike"],
            "har_local_vs_us_dm_t": local_har["t_stat"],
        },
        "charts": chart_names,
        "limitations": [
            "Daily squared return is an unbiased but very noisy variance proxy; QLIKE is used for proxy robustness.",
            "The HAR specification is a low-frequency HAR proxy on lagged daily squared returns, not a high-frequency realized-volatility HAR-RV claim.",
            "Annual rather than daily parameter refits balance genuine expanding-origin OOS evaluation with numerical stability; within-year parameters are fixed.",
            "India VIX and US VIX are 30-calendar-day implied volatility measures used to forecast a one-day variance target; scale is learned only from past data where applicable.",
            "Granger predictability is not causal identification.",
            "The NIFTY index-return simulation omits an investable vehicle, dividends, financing, taxes, and official Indian trading costs; it cannot support strategy listing.",
            "The forecast target is close-to-close squared return, while a gated strategy holds from one open to the next; forecast ranking is only a screening gate and does not itself prove timing relevance for the strategy holding interval.",
            f"The {diagnostics['vendor_calendar_integrity']['excluded_multi_session_nifty_targets']} vendor-calendar gap targets are omitted from forecast estimation and scoring. GARCH/HAR state updates then advance across the remaining clean observations rather than reconstructing unobserved one-session NIFTY returns.",
        ],
        "verdict": verdict,
        "conclusion": conclusion,
    }
    result_path = SCRIPT_DIR / "k1717_results.json"
    atomic_write_json(result_path, results)
    print(f"Wrote {result_path}")
    print(json.dumps(_json_safe(results["key_numbers"]), indent=2))
    print(f"Information gate: {'PASS' if gate['passed'] else 'FAIL'}")


if __name__ == "__main__":
    main()
