"""K1718 / ASIA-2: Japanese volatility baselines and lagged US VIX.

The Nikkei 225 index and the TOPIX ETF are modeled as separate tracks. The
script compares GARCH, GJR, and a daily-return-proxy HAR specification with
otherwise identical variants augmented by the latest completed US VIX close.

The augmented models nest their baselines. Clark-West MSPE-adjusted tests are
therefore the primary incremental-information inference. Canonical QLIKE DM
statistics are retained only as diagnostics.

Data source: Yahoo Finance via yfinance. All random starts use a fixed seed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
import time
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
from scipy.stats import spearmanr
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from volpred.stats.model_evaluation import (  # noqa: E402
    clark_west_test,
    dm_test,
    qlike,
    qlike_pointwise,
)


EXPERIMENT_ID = "K1718"
TASK_ID = "asia2_japan_vt_baseline"
SEED = 1718
TRADING_DAYS = 252
OOS_START_YEAR = 2020
OOS_END_YEAR = 2026
MIN_TRAIN_OBS = 1_000
DATA_START = "1990-01-01"
DATA_END_EXCLUSIVE = "2026-07-17"
TARGET_VOL = 0.12
MAX_LEVERAGE = 1.0
PRIMARY_COST_BPS = 10
TOPIX_USABLE_START = pd.Timestamp("2015-01-05")
TOPIX_SCALE_REPAIR_DATES = pd.DatetimeIndex(["2026-03-30", "2026-03-31"])
TOPIX_SCALE_REPAIR_FACTOR = 10.0
TOPIX_SPLIT_SOURCE = "https://www.jpx.co.jp/english/news/2020/20260316-01.html"
TOPIX_FUND_SOURCE = "https://nextfunds.jp/en/lineup/1306/"

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1718_results.json"
DATA_PATH = HERE / "k1718_data.csv"
OOS_PATH = HERE / "k1718_oos_forecasts.csv"
README_PATH = HERE / "README.md"

ASSETS = {
    "n225": {"ticker": "^N225", "label": "Nikkei 225 index", "tradable": False},
    "topix_etf": {
        "ticker": "1306.T",
        "label": "NEXT FUNDS TOPIX ETF",
        "tradable": True,
    },
}

MODEL_LABELS = {
    "garch": "GARCH",
    "garch_x_vix": "GARCH-X(VIX)",
    "gjr": "GJR",
    "gjr_x_vix": "GJR-X(VIX)",
    "har_r2": "HAR-style log-r2",
    "har_r2_x_vix": "HAR-style log-r2-X(VIX)",
}

LITERATURE = [
    {
        "authors": "Lin, Engle, and Ito",
        "year": 1991,
        "title": "Do Bulls and Bears Move Across Borders?",
        "url": "https://www.nber.org/papers/w3911",
        "design_relevance": "Tokyo/New York timing and mixed evidence on lagged volatility spillovers.",
    },
    {
        "authors": "Corsi",
        "year": 2009,
        "title": "A Simple Approximate Long-Memory Model of Realized Volatility",
        "doi": "10.1093/jjfinec/nbp001",
        "design_relevance": "Motivates heterogeneous daily, weekly, and monthly volatility components.",
    },
    {
        "authors": "Glosten, Jagannathan, and Runkle",
        "year": 1993,
        "title": "On the Relation between Expected Value and Volatility",
        "doi": "10.1111/j.1540-6261.1993.tb05128.x",
        "design_relevance": "Motivates asymmetric GJR variance dynamics.",
    },
    {
        "authors": "Patton",
        "year": 2011,
        "title": "Volatility Forecast Comparison Using Imperfect Volatility Proxies",
        "doi": "10.1016/j.jeconom.2010.03.034",
        "design_relevance": "Supports proxy-robust QLIKE ranking on noisy daily squared returns.",
    },
    {
        "authors": "Clark and West",
        "year": 2007,
        "title": "Approximately Normal Tests for Equal Predictive Accuracy in Nested Models",
        "doi": "10.1016/j.jeconom.2006.05.023",
        "design_relevance": "Primary nested-model incremental-predictive-content test.",
    },
    {
        "authors": "Wang",
        "year": 2019,
        "title": "VIX and Volatility Forecasting: A New Insight",
        "doi": "10.1016/j.physa.2019.121951",
        "design_relevance": "Cross-country evidence including Japan motivates a strict OOS replication.",
    },
]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (pd.Index, np.ndarray)):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if value is pd.NaT:
        return None
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_json_safe(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with open(tmp_name, encoding="utf-8") as handle:
            json.load(handle)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        frame.to_csv(tmp_name, index=True)
        pd.read_csv(tmp_name, nrows=5)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_ohlc(ticker: str) -> pd.DataFrame:
    """Download adjusted OHLC; retries are loud and bounded."""
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            raw = yf.download(
                ticker,
                start=DATA_START,
                end=DATA_END_EXCLUSIVE,
                auto_adjust=True,
                progress=False,
                actions=False,
                threads=False,
            )
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            frame = raw[["Open", "Close"]].copy()
            frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
            frame = frame[~frame.index.duplicated(keep="last")].sort_index().dropna()
            if len(frame) < 500:
                raise RuntimeError(f"{ticker}: only {len(frame)} adjusted OHLC rows")
            return frame
        except Exception as exc:  # bounded network retry, never silent
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(attempt)
    raise RuntimeError(f"{ticker} download failed: {'; '.join(errors)}")


def normalize_topix_vendor_scale(
    ohlc: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Put the 1306.T vendor snapshot on one continuous return basis.

    The 2026-07-16 Yahoo snapshot is internally inconsistent around the
    official 1:10 beneficial-interest split: 2026-03-30/31 are already on the
    new lower price scale while both the preceding adjusted history and the
    following observations are on the pre-split-equivalent adjusted scale.
    Multiplying exactly those two rows by ten restores a single scale without
    changing any economically meaningful return.  An unrelated 10x vendor
    unit discontinuity occurs between 2014-12-30 and 2015-01-05; because no
    primary issuer record was located for that boundary, the experiment drops
    the earlier regime instead of guessing an adjustment.
    """
    required = {"Open", "Close"}
    if not required.issubset(ohlc.columns):
        raise ValueError(f"1306.T OHLC missing columns: {sorted(required - set(ohlc.columns))}")
    raw = ohlc.sort_index().copy()
    missing_dates = TOPIX_SCALE_REPAIR_DATES.difference(raw.index)
    if len(missing_dates):
        raise RuntimeError(
            "1306.T snapshot no longer matches the audited split window; "
            f"missing {missing_dates.strftime('%Y-%m-%d').tolist()}"
        )

    prior_date = raw.index[raw.index < TOPIX_USABLE_START].max()
    first_date = raw.index[raw.index >= TOPIX_USABLE_START].min()
    boundary_close_ratio = float(raw.loc[prior_date, "Close"] / raw.loc[first_date, "Close"])
    normalized = raw.loc[raw.index >= TOPIX_USABLE_START].copy()
    values_before = normalized.loc[TOPIX_SCALE_REPAIR_DATES, ["Open", "Close"]].copy()
    normalized.loc[TOPIX_SCALE_REPAIR_DATES, ["Open", "Close"]] *= TOPIX_SCALE_REPAIR_FACTOR

    if not np.isfinite(normalized[["Open", "Close"]].to_numpy()).all():
        raise AssertionError("1306.T normalized OHLC contains non-finite values")
    if (normalized[["Open", "Close"]] <= 0).any().any():
        raise AssertionError("1306.T normalized OHLC must be strictly positive")
    largest_close_jump = float(np.log(normalized["Close"]).diff().abs().max())
    largest_open_jump = float(np.log(normalized["Open"]).diff().abs().max())
    if max(largest_close_jump, largest_open_jump) >= 0.25:
        raise AssertionError(
            "1306.T still has a >=25% adjacent log-price jump after normalization: "
            f"close={largest_close_jump:.4f}, open={largest_open_jump:.4f}"
        )

    diagnostics = {
        "policy": "continuous pre-split-equivalent adjusted-price basis",
        "vendor_snapshot_observed_on": "2026-07-16",
        "usable_start": TOPIX_USABLE_START,
        "pre_start_rows_dropped": int((raw.index < TOPIX_USABLE_START).sum()),
        "unverified_vendor_boundary": {
            "prior_date": prior_date,
            "first_kept_date": first_date,
            "prior_close_divided_by_first_kept_close": boundary_close_ratio,
            "treatment": "drop earlier regime; do not infer a corporate action",
        },
        "official_split": {
            "ratio": "1:10",
            "effective_date": "2026-04-01",
            "trading_adjustment_start": "2026-03-30",
            "jpx_source": TOPIX_SPLIT_SOURCE,
            "fund_source": TOPIX_FUND_SOURCE,
        },
        "vendor_rows_rescaled": TOPIX_SCALE_REPAIR_DATES,
        "factor": TOPIX_SCALE_REPAIR_FACTOR,
        "values_before": values_before.reset_index().to_dict(orient="records"),
        "largest_abs_log_close_change_after": largest_close_jump,
        "largest_abs_log_open_change_after": largest_open_jump,
    }
    return normalized, diagnostics


def strict_asof_signal(
    signal: pd.Series, target_index: pd.DatetimeIndex
) -> tuple[pd.Series, pd.Series]:
    """Latest source observation strictly earlier than each target date."""
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
    values = pd.Series(merged["value"].to_numpy(), index=merged["target_date"])
    sources = pd.Series(
        pd.to_datetime(merged["source_date"]).to_numpy(), index=merged["target_date"]
    )
    valid = sources.notna()
    if not (sources.loc[valid].to_numpy() < sources.loc[valid].index.to_numpy()).all():
        raise AssertionError("VIX source date must be strictly earlier than Japan target date")
    return values.reindex(target_index), sources.reindex(target_index)


def build_frame(
    ohlc: pd.DataFrame, vix_close: pd.Series, common_start: pd.Timestamp
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ohlc = ohlc.loc[ohlc.index >= common_start].copy()
    returns = np.log(ohlc["Close"]).diff()
    r2 = returns.pow(2)
    vix_signal, vix_source = strict_asof_signal(vix_close, ohlc.index)

    # Literal row-shift is a diagnostic. The canonical signal is strict
    # calendar as-of; applying another shift to it would double-lag US VIX.
    row_shift_signal = vix_close.reindex(ohlc.index).ffill().shift(1)  # signal.shift(1)
    common = row_shift_signal.notna() & vix_signal.notna()
    disagreements = pd.Series(False, index=ohlc.index)
    disagreements.loc[common] = ~np.isclose(
        row_shift_signal.loc[common],
        vix_signal.loc[common],
        rtol=0.0,
        atol=0.0,
    )

    lagged_r2 = r2.shift(1)
    frame = pd.DataFrame(
        {
            "open": ohlc["Open"],
            "close": ohlc["Close"],
            "return": returns,
            "r2": r2,
            "open_to_next_open_return": ohlc["Open"].shift(-1) / ohlc["Open"] - 1.0,
            "vix_signal": vix_signal,
            "vix_source_date": vix_source,
            "vix_daily_var": (vix_signal / 100.0) ** 2 / TRADING_DAYS,
            "har_d": np.log(lagged_r2.clip(lower=1e-12)),
            "har_w": np.log(lagged_r2.rolling(5).mean().clip(lower=1e-12)),
            "har_m": np.log(lagged_r2.rolling(22).mean().clip(lower=1e-12)),
            "log_r2": np.log(r2.clip(lower=1e-12)),
            "log_vix_var": np.log(
                ((vix_signal / 100.0) ** 2 / TRADING_DAYS).clip(lower=1e-12)
            ),
        },
        index=ohlc.index,
    )
    required = [
        "return", "r2", "vix_signal", "vix_source_date", "har_d", "har_w",
        "har_m", "log_r2", "log_vix_var",
    ]
    model_frame = frame.dropna(subset=required).copy()
    source_age = (
        model_frame.index.to_series() - pd.to_datetime(model_frame["vix_source_date"])
    ).dt.days
    if (source_age <= 0).any():
        raise AssertionError("Every VIX observation must precede its Japan target")
    diagnostics = {
        "raw_adjusted_ohlc_start": ohlc.index.min(),
        "raw_adjusted_ohlc_end": ohlc.index.max(),
        "n_raw_adjusted_ohlc": len(ohlc),
        "model_start": model_frame.index.min(),
        "model_end": model_frame.index.max(),
        "n_model": len(model_frame),
        "duplicate_dates": int(model_frame.index.duplicated().sum()),
        "return_summary": {
            "mean_daily": float(model_frame["return"].mean()),
            "annualized_vol": float(model_frame["return"].std(ddof=1) * np.sqrt(TRADING_DAYS)),
            "skewness": float(model_frame["return"].skew()),
            "excess_kurtosis": float(model_frame["return"].kurtosis()),
            "acf_r2_lag1": float(model_frame["r2"].autocorr(1)),
            "acf_r2_lag5": float(model_frame["r2"].autocorr(5)),
            "largest_abs_return": float(model_frame["return"].abs().max()),
        },
        "vix_timing": {
            "rule": "latest US VIX close with source_date strictly before Japan target date",
            "source_age_days_min": int(source_age.min()),
            "source_age_days_median": float(source_age.median()),
            "source_age_days_max": int(source_age.max()),
            "row_shift_vs_strict_asof_disagreements": int(disagreements.sum()),
        },
        "oos_stress_coverage": {
            "year_2020_obs": int((model_frame.index.year == 2020).sum()),
            "year_2022_obs": int((model_frame.index.year == 2022).sum()),
        },
    }
    return model_frame, diagnostics


def _unpack_params(
    params: np.ndarray, asymmetric: bool, has_exog: bool
) -> tuple[float, float, float, float, float]:
    omega = float(params[0])
    alpha = float(params[1])
    if asymmetric:
        gamma = float(params[2])
        beta = float(params[3])
        delta = float(params[4]) if has_exog else 0.0
    else:
        gamma = 0.0
        beta = float(params[2])
        delta = float(params[3]) if has_exog else 0.0
    return omega, alpha, gamma, beta, delta


def variance_filter(
    params: np.ndarray,
    returns_pct: np.ndarray,
    exog_pct_var: np.ndarray | None,
    asymmetric: bool,
) -> np.ndarray:
    omega, alpha, gamma, beta, delta = _unpack_params(
        params, asymmetric, exog_pct_var is not None
    )
    h = np.empty(len(returns_pct), dtype=float)
    h[0] = max(float(np.var(returns_pct[: min(len(returns_pct), 252)], ddof=1)), 1e-6)
    for t in range(1, len(returns_pct)):
        previous_r2 = float(returns_pct[t - 1] ** 2)
        leverage = previous_r2 if returns_pct[t - 1] < 0 else 0.0
        x_t = float(exog_pct_var[t]) if exog_pct_var is not None else 0.0
        h[t] = max(
            omega + alpha * previous_r2 + gamma * leverage + beta * h[t - 1] + delta * x_t,
            1e-8,
        )
    return h


def fit_garch(
    train: pd.DataFrame,
    exog_column: str | None,
    asymmetric: bool,
    rng: np.random.Generator,
) -> dict[str, Any]:
    returns_pct = train["return"].to_numpy(dtype=float) * 100.0
    exog_pct_var = (
        train[exog_column].to_numpy(dtype=float) * 10_000.0
        if exog_column is not None else None
    )
    burn_in = min(252, max(50, len(returns_pct) // 10))
    sample_var = max(float(np.var(returns_pct, ddof=1)), 1e-4)

    def persistence(p: np.ndarray) -> float:
        return float(p[1] + (0.5 * p[2] + p[3] if asymmetric else p[2]))

    def objective(p: np.ndarray) -> float:
        if persistence(p) >= 0.998:
            return 1e12 + 1e8 * (persistence(p) - 0.998)
        h = variance_filter(p, returns_pct, exog_pct_var, asymmetric)
        contributions = 0.5 * (np.log(2.0 * np.pi) + np.log(h) + returns_pct**2 / h)
        return float(np.sum(contributions[burn_in:]))

    if asymmetric:
        starts = [
            np.array([sample_var * 0.02, 0.04, 0.06, 0.88]),
            np.array([sample_var * 0.05, 0.08, 0.10, 0.78]),
        ]
    else:
        starts = [
            np.array([sample_var * 0.02, 0.06, 0.90]),
            np.array([sample_var * 0.05, 0.12, 0.80]),
        ]
    if exog_column is not None:
        starts = [np.append(start, delta) for start, delta in zip(starts, (0.05, 0.15))]
    for _ in range(3):
        alpha = float(rng.uniform(0.02, 0.14))
        if asymmetric:
            gamma = float(rng.uniform(0.01, 0.14))
            beta = float(rng.uniform(0.65, max(0.66, 0.96 - alpha - 0.5 * gamma)))
            start = np.array([sample_var * rng.uniform(0.005, 0.08), alpha, gamma, beta])
        else:
            beta = float(rng.uniform(0.65, max(0.66, 0.96 - alpha)))
            start = np.array([sample_var * rng.uniform(0.005, 0.08), alpha, beta])
        if exog_column is not None:
            start = np.append(start, rng.uniform(0.01, 0.30))
        starts.append(start)

    bounds = [(1e-8, 50.0), (0.0, 0.998)]
    bounds.extend([(0.0, 0.998), (0.0, 0.998)] if asymmetric else [(0.0, 0.998)])
    if exog_column is not None:
        bounds.append((0.0, 5.0))
    constraint = {"type": "ineq", "fun": lambda p: 0.998 - persistence(p)}
    candidates = [
        minimize(
            objective, start, method="SLSQP", bounds=bounds,
            constraints=[constraint], options={"maxiter": 800, "ftol": 1e-9, "disp": False},
        )
        for start in starts
    ]
    successful = [
        candidate for candidate in candidates
        if candidate.success and np.isfinite(candidate.fun)
    ]
    if not successful:
        messages = "; ".join(str(candidate.message) for candidate in candidates)
        raise RuntimeError(f"All {'GJR' if asymmetric else 'GARCH'} starts failed: {messages}")
    best = min(successful, key=lambda candidate: float(candidate.fun))
    params = np.asarray(best.x, dtype=float)
    filtered = variance_filter(params, returns_pct, exog_pct_var, asymmetric)
    standardized = pd.Series(returns_pct[burn_in:] / np.sqrt(filtered[burn_in:]))
    names = ["omega", "alpha"] + (["gamma"] if asymmetric else []) + ["beta"]
    if exog_column is not None:
        names.append("delta_vix")
    return {
        "params": dict(zip(names, params)),
        "params_vector": params,
        "objective": float(best.fun),
        "converged": bool(best.success),
        "n_starts": len(starts),
        "n_successful_starts": len(successful),
        "persistence": persistence(params),
        "constraint_slack": float(0.998 - persistence(params)),
        "last_variance_pct2": float(filtered[-1]),
        "last_return_pct": float(returns_pct[-1]),
        "burn_in_not_scored": burn_in,
        "standardized_residuals": {
            "mean": float(standardized.mean()),
            "std": float(standardized.std(ddof=1)),
            "squared_acf_lag1": float(standardized.pow(2).autocorr(1)),
            "squared_acf_lag5": float(standardized.pow(2).autocorr(5)),
        },
    }


def forecast_garch(
    fitted: dict[str, Any],
    test: pd.DataFrame,
    exog_column: str | None,
    asymmetric: bool,
) -> np.ndarray:
    params = np.asarray(fitted["params_vector"], dtype=float)
    omega, alpha, gamma, beta, delta = _unpack_params(
        params, asymmetric, exog_column is not None
    )
    previous_h = float(fitted["last_variance_pct2"])
    previous_return = float(fitted["last_return_pct"])
    output = np.empty(len(test), dtype=float)
    for i, (_, row) in enumerate(test.iterrows()):
        previous_r2 = previous_return**2
        leverage = previous_r2 if previous_return < 0 else 0.0
        x_t = float(row[exog_column]) * 10_000.0 if exog_column else 0.0
        h_t = max(
            omega + alpha * previous_r2 + gamma * leverage + beta * previous_h + delta * x_t,
            1e-8,
        )
        output[i] = h_t / 10_000.0
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
    residuals = y_train - x_train @ beta
    residual_variance = float(np.var(residuals, ddof=x_train.shape[1]))
    x_test = np.column_stack([np.ones(len(test)), test[columns].to_numpy(dtype=float)])
    log_forecast = x_test @ beta + 0.5 * residual_variance
    return np.exp(np.clip(log_forecast, -30.0, 2.0)), {
        "columns": ["intercept"] + columns,
        "coefficients": beta,
        "residual_variance": residual_variance,
        "rank": int(np.linalg.matrix_rank(x_train)),
        "n_train": len(train),
    }


def annual_expanding_oos(
    frame: pd.DataFrame, seed_offset: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rng = np.random.default_rng(SEED + seed_offset)
    forecasts: list[pd.DataFrame] = []
    fit_log: dict[str, Any] = {}
    for year in range(OOS_START_YEAR, OOS_END_YEAR + 1):
        train = frame.loc[frame.index < pd.Timestamp(f"{year}-01-01")].copy()
        test = frame.loc[
            (frame.index >= pd.Timestamp(f"{year}-01-01"))
            & (frame.index <= pd.Timestamp(f"{year}-12-31"))
        ].copy()
        if test.empty:
            continue
        if len(train) < MIN_TRAIN_OBS:
            raise RuntimeError(f"{year}: only {len(train)} training observations")
        garch = fit_garch(train, None, False, rng)
        garch_x = fit_garch(train, "vix_daily_var", False, rng)
        gjr = fit_garch(train, None, True, rng)
        gjr_x = fit_garch(train, "vix_daily_var", True, rng)
        har, har_fit = fit_predict_har(train, test, None)
        har_x, har_x_fit = fit_predict_har(train, test, "log_vix_var")
        forecasts.append(
            pd.DataFrame(
                {
                    "actual_r2": test["r2"],
                    "return": test["return"],
                    "open_to_next_open_return": test["open_to_next_open_return"],
                    "garch": forecast_garch(garch, test, None, False),
                    "garch_x_vix": forecast_garch(garch_x, test, "vix_daily_var", False),
                    "gjr": forecast_garch(gjr, test, None, True),
                    "gjr_x_vix": forecast_garch(gjr_x, test, "vix_daily_var", True),
                    "har_r2": har,
                    "har_r2_x_vix": har_x,
                },
                index=test.index,
            )
        )
        fit_log[str(year)] = {
            "train_start": train.index.min(),
            "train_end": train.index.max(),
            "n_train": len(train),
            "test_start": test.index.min(),
            "test_end": test.index.max(),
            "n_test": len(test),
            "models": {
                "garch": garch,
                "garch_x_vix": garch_x,
                "gjr": gjr,
                "gjr_x_vix": gjr_x,
                "har_r2": har_fit,
                "har_r2_x_vix": har_x_fit,
            },
        }
    oos = pd.concat(forecasts).sort_index()
    if oos.index.duplicated().any():
        raise AssertionError("OOS dates must be unique")
    if len(oos) < 252:
        raise RuntimeError(f"Only {len(oos)} OOS observations")
    missing_stress = {2020, 2022} - set(oos.index.year)
    if missing_stress:
        raise RuntimeError(f"Missing stress years: {sorted(missing_stress)}")
    return oos, fit_log


def hac_lag_sensitivity(loss_differential: np.ndarray) -> dict[str, Any]:
    """Diagnostic Bartlett-HAC t statistics; canonical dm_test remains the DM owner."""
    values = np.asarray(loss_differential, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    canonical_lag = max(1, min(math.ceil(n ** (1 / 3)), n // 4))
    centered = values - np.mean(values)
    output: dict[str, Any] = {}
    for lag in sorted({0, 1, 5, 10, canonical_lag, 20}):
        lag = min(lag, n - 1)
        long_run_var = float(np.mean(centered**2))
        for k in range(1, lag + 1):
            weight = 1.0 - k / (lag + 1.0)
            long_run_var += 2.0 * weight * float(
                np.mean(centered[k:] * centered[:-k])
            )
        t_stat = (
            float(np.mean(values) / math.sqrt(long_run_var / n))
            if long_run_var > 0 else None
        )
        output[f"lag_{lag}"] = {
            "t_stat": t_stat,
            "hac_applied": bool(lag > 0),
            "is_canonical_bandwidth": bool(lag == canonical_lag),
        }
    return output


def evaluate_forecasts(
    oos: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    model_names = list(MODEL_LABELS)
    mask = np.isfinite(oos["actual_r2"].to_numpy(dtype=float)) & (
        oos["actual_r2"].to_numpy(dtype=float) > 0
    )
    for name in model_names:
        values = oos[name].to_numpy(dtype=float)
        mask &= np.isfinite(values) & (values > 0)
    evaluated = oos.loc[mask].copy()
    actual = evaluated["actual_r2"].to_numpy(dtype=float)
    metrics: dict[str, Any] = {}
    losses: dict[str, np.ndarray] = {}
    for name in model_names:
        predicted = evaluated[name].to_numpy(dtype=float)
        rho, rho_p = spearmanr(actual, predicted)
        losses[name] = qlike_pointwise(actual, predicted)
        metrics[name] = {
            "qlike": qlike(actual, predicted),
            "mse": float(np.mean((actual - predicted) ** 2)),
            "spearman_rho": float(rho),
            "spearman_p_value": float(rho_p),
            "mean_forecast_annualized_vol": float(
                np.sqrt(np.mean(predicted) * TRADING_DAYS)
            ),
            "n_obs_shared_positive_mask": len(evaluated),
        }
    pairs = {
        "garch": ("garch", "garch_x_vix"),
        "gjr": ("gjr", "gjr_x_vix"),
        "har_r2": ("har_r2", "har_r2_x_vix"),
    }
    comparisons: dict[str, Any] = {}
    # nested-dm: diagnostic-only
    # Raw QLIKE DM is transparent diagnostics and never feeds the verdict.
    for family, (base, augmented) in pairs.items():
        t_stat, p_value = dm_test(losses[augmented], losses[base], h=1)
        differential = losses[augmented] - losses[base]
        series = pd.Series(differential, index=evaluated.index)
        # nested-dm: cw-primary
        cw = clark_west_test(
            actual,
            evaluated[base].to_numpy(dtype=float),
            evaluated[augmented].to_numpy(dtype=float),
            h=1,
        )
        comparisons[family] = {
            "baseline_model": base,
            "augmented_model": augmented,
            "qlike_improvement_pct": float(
                100.0 * (metrics[base]["qlike"] - metrics[augmented]["qlike"])
                / abs(metrics[base]["qlike"])
            ),
            "canonical_qlike_dm_diagnostic": {
                "t_stat": t_stat,
                "p_value_two_sided": p_value,
                "direction": "negative favors VIX-augmented model",
                "inference_role": "nested diagnostic only; not verdict evidence",
                "canonical_hac_lag": max(
                    1, min(math.ceil(len(differential) ** (1 / 3)), len(differential) // 4)
                ),
                "loss_diff_acf": {
                    "lag_1": float(series.autocorr(1)),
                    "lag_5": float(series.autocorr(5)),
                    "lag_10": float(series.autocorr(10)),
                },
                "hac_lag_sensitivity": hac_lag_sensitivity(differential),
            },
            "clark_west_primary": cw,
        }
    comparisons["shared_mask"] = {
        "rule": "actual r2 and all six forecasts finite and strictly positive",
        "n_raw_oos": len(oos),
        "n_evaluated": len(evaluated),
        "n_dropped": int(len(oos) - len(evaluated)),
    }
    return evaluated, metrics, comparisons


def strategy_scorecard(oos: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    """Exploratory TOPIX ETF open-to-next-open volatility targeting."""
    frame = oos.dropna(subset=["open_to_next_open_return"]).copy()
    paths: dict[str, pd.Series] = {}
    result: dict[str, Any] = {
        "role": "exploratory diagnostic; not forecast-gate or deployment evidence",
        "holding_period": "1306.T adjusted Open[t] to adjusted Open[t+1]",
        "forecast_target_mismatch": (
            "Forecast target is close-to-close r2; tradable holding is open-to-next-open."
        ),
        "target_vol": TARGET_VOL,
        "max_leverage": MAX_LEVERAGE,
        "cost_sensitivity_bps": [0, 10, 25],
        "models": {},
    }
    weights: dict[str, pd.Series] = {"buy_and_hold": pd.Series(1.0, index=frame.index)}
    for model in MODEL_LABELS:
        annualized = np.sqrt(frame[model].clip(lower=1e-12) * TRADING_DAYS)
        weights[model] = (TARGET_VOL / annualized).clip(lower=0.0, upper=MAX_LEVERAGE)
    for name, weight in weights.items():
        result["models"][name] = {}
        turnover = weight.diff().abs().fillna(abs(float(weight.iloc[0])))
        for bps in (0, 10, 25):
            returns = (
                weight * frame["open_to_next_open_return"]
                - (bps / 10_000.0) * turnover
            )
            std = float(returns.std(ddof=1))
            result["models"][name][f"cost_{bps}bps"] = {
                "annualized_return": float(returns.mean() * TRADING_DAYS),
                "annualized_vol": float(std * np.sqrt(TRADING_DAYS)),
                "sharpe_zero_rate": float(
                    returns.mean() / std * np.sqrt(TRADING_DAYS) if std > 0 else 0.0
                ),
                "annualized_turnover": float(turnover.mean() * TRADING_DAYS),
                "mean_weight": float(weight.mean()),
                "n_obs": len(returns),
            }
            if bps == PRIMARY_COST_BPS:
                paths[name] = (1.0 + returns).cumprod()
    return result, pd.DataFrame(paths)


def render_figures(
    assets: dict[str, dict[str, Any]],
    oos_by_asset: dict[str, pd.DataFrame],
    strategy_paths: pd.DataFrame,
) -> list[str]:
    plt.style.use("seaborn-v0_8-whitegrid")
    models = list(MODEL_LABELS)
    x = np.arange(len(models))
    width = 0.36
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for offset, (asset, payload) in zip((-width / 2, width / 2), assets.items()):
        values = [payload["metrics"][model]["qlike"] for model in models]
        ax.bar(x + offset, values, width, label=ASSETS[asset]["label"])
    ax.set_xticks(x, [MODEL_LABELS[model] for model in models], rotation=18, ha="right")
    ax.set_ylabel("OOS QLIKE (lower is better)")
    ax.set_title("K1718: Japan volatility forecast baseline sweep, 2020-2026")
    ax.legend()
    fig.tight_layout()
    qlike_path = HERE / "k1718_oos_qlike.png"
    fig.savefig(qlike_path, dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, (asset, oos) in zip(axes, oos_by_asset.items()):
        annual = []
        for year, group in oos.groupby(oos.index.year):
            actual = group["actual_r2"].to_numpy(dtype=float)
            row = {"year": year}
            for family, (base, augmented) in {
                "GARCH": ("garch", "garch_x_vix"),
                "GJR": ("gjr", "gjr_x_vix"),
                "HAR-r2": ("har_r2", "har_r2_x_vix"),
            }.items():
                valid = (
                    np.isfinite(actual) & (actual > 0)
                    & np.isfinite(group[base].to_numpy(dtype=float))
                    & np.isfinite(group[augmented].to_numpy(dtype=float))
                )
                base_loss = qlike(actual[valid], group.loc[valid, base].to_numpy(dtype=float))
                x_loss = qlike(actual[valid], group.loc[valid, augmented].to_numpy(dtype=float))
                row[family] = base_loss - x_loss
            annual.append(row)
        pd.DataFrame(annual).set_index("year").plot(ax=ax, marker="o")
        ax.axhline(0.0, color="black", linewidth=1)
        ax.set_title(ASSETS[asset]["label"])
        ax.set_ylabel("QLIKE(base) - QLIKE(VIX-X)")
        ax.set_xlabel("OOS year")
    fig.suptitle("Annual VIX incremental forecast-loss improvement")
    fig.tight_layout()
    annual_path = HERE / "k1718_annual_stability.png"
    fig.savefig(annual_path, dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(13, 6.5))
    strategy_paths.plot(ax=ax, linewidth=1.2)
    ax.set_title("Exploratory 1306.T VT paths (10 bps turnover cost)")
    ax.set_ylabel("Growth of 1")
    ax.set_xlabel("Date")
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    strategy_path = HERE / "k1718_vt_paths.png"
    fig.savefig(strategy_path, dpi=180)
    plt.close(fig)
    return [path.name for path in (qlike_path, annual_path, strategy_path)]


def render_readme(results: dict[str, Any]) -> str:
    lines = [
        "# K1718 / ASIA-2：日股波動基準與前一美股日 VIX 增量",
        "",
        "## 問題與範圍",
        "",
        "本實驗檢驗：在日本市場開盤前已知的最近一筆美國 VIX 完整收盤，是否能改善日股次一日波動預測。"
        "^N225 是價格加權 Nikkei 225；1306.T 是市值加權 TOPIX 的可交易 ETF。兩者成分與權重不同，"
        "因此各自估計、各自評分，不把指數預測冒充 ETF replication。",
        "",
        "本 K 使用 yfinance auto_adjust=True 的 adjusted OHLC；另對 1306.T 的 2026 年官方 1:10"
        " 分割窗口做可稽核尺度正規化，並因 2015-01-05 前另有無法由發行人紀錄驗證的 10 倍 vendor"
        " unit break 而捨棄較早區段。正式 OOS 為 2020–2026，包含 COVID 與 2022 空頭。",
        "",
        "## 預先設計的方法",
        "",
        "- 三個 family：Gaussian GARCH(1,1)、GJR-GARCH(1,1)、HAR-style log-r²。最後一個只用落後日報酬"
        "  平方的 1/5/22 日成分，不是 5 分鐘 realized variance，因此不稱 HAR-RV。",
        "- VIX-X 加入 (VIX/100)^2/252；VIX 以 strict backward as-of join 對齊，source date 嚴格早於"
        "  Japan target。HAR 本地特徵先 r².shift(1)。",
        "- 每年年初用截至前一年末的 expanding sample 重估。六個 forecast 在同一嚴格正值 mask 上以"
        "  Patton QLIKE、MSE、Spearman 評分。",
        "- X 對 base 是巢狀模型；主要推論為 Clark-West one-sided MSPE-adjusted test。六格一起做 Holm。"
        "  canonical dm_test 的 QLIKE DM 只列診斷，不餵入 verdict。",
        "- 預註冊 robust gate：六格都必須 QLIKE_X < QLIKE_base 且 Holm-adjusted Clark-West p<0.05。"
        "  0 格為 NULL，1–5 格為 PARTIAL，6 格才是 ROBUST。",
        "",
        "## 文獻定位",
        "",
        "Lin、Engle、Ito (1991, NBER w3911) 對東京與紐約指出跨時區資訊傳遞，但 lagged volatility"
        " spillover 並非普遍顯著；本實驗不預設 VIX 一定有效。模型與評分另依 GJR (1993)、Corsi (2009)、"
        "Patton (2011)、Clark-West (2007)。Wang (2019) 是本次嚴格 OOS replication 的直接動機。",
        "",
        "## 資料診斷",
        "",
        f"- 共同比較起點：{results['data']['common_start'][:10]}；VIX "
        f"{results['data']['vix']['start'][:10]} 至 {results['data']['vix']['end'][:10]}。",
        "- 1306.T 尺度稽核：2026-03-30/31 的 adjusted Open/Close 乘 10，轉成與相鄰日期一致的"
        " pre-split-equivalent basis；官方分割生效日 2026-04-01，交易調整自 2026-03-30。",
    ]
    for asset, payload in results["assets"].items():
        d = payload["diagnostics"]
        lines.append(
            f"- {ASSETS[asset]['label']}：adjusted OHLC {d['raw_adjusted_ohlc_start'][:10]} 至 "
            f"{d['raw_adjusted_ohlc_end'][:10]}，model n={d['n_model']:,}；年化波動 "
            f"{d['return_summary']['annualized_vol']:.2%}；VIX source age median "
            f"{d['vix_timing']['source_age_days_median']:.1f} 日。"
        )
    lines.extend(
        [
            "", "## OOS forecast 結果", "",
            "| Track | Model | QLIKE | MSE | Spearman |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for asset, payload in results["assets"].items():
        for model, metric in payload["metrics"].items():
            lines.append(
                f"| {ASSETS[asset]['label']} | {MODEL_LABELS[model]} | "
                f"{metric['qlike']:.4f} | {metric['mse']:.8f} | {metric['spearman_rho']:.3f} |"
            )
    lines.extend(
        [
            "", "### VIX 增量 gate", "",
            "| Track | Family | QLIKE improvement | CW t | raw p | Holm p | pass |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for asset, payload in results["assets"].items():
        for family, comparison in payload["comparisons"].items():
            if family == "shared_mask":
                continue
            cw = comparison["clark_west_primary"]
            lines.append(
                f"| {ASSETS[asset]['label']} | {family} | "
                f"{comparison['qlike_improvement_pct']:+.2f}% | {cw['t_stat']:.3f} | "
                f"{cw['p_value_one_sided']:.4f} | {cw['holm_p_value_6_tests']:.4f} | "
                f"{'PASS' if cw['pre_registered_cell_pass'] else 'FAIL'} |"
            )
    lines.extend(
        [
            "",
            f"**結論：{results['scientific_verdict']}。** {results['conclusion']}",
            "", "## Exploratory 1306.T VT scorecard", "",
            "權重在 1306.T 開盤時計算為 min(1, 12% / annualized forecast vol)，持有 adjusted "
            "Open[t]→Open[t+1]，主口徑每單位 turnover 10 bps。forecast target 是 close-to-close r²，"
            "策略 holding 是 open-to-next-open；下表只作描述性診斷，不支撐上架。",
            "",
            "| Model | Ann. return | Ann. vol | Sharpe | Ann. turnover | Mean weight |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model, costs in results["exploratory_vt"]["models"].items():
        metric = costs["cost_10bps"]
        label = "Buy & hold" if model == "buy_and_hold" else MODEL_LABELS[model]
        lines.append(
            f"| {label} | {metric['annualized_return']:.2%} | {metric['annualized_vol']:.2%} | "
            f"{metric['sharpe_zero_rate']:.3f} | {metric['annualized_turnover']:.2f} | "
            f"{metric['mean_weight']:.3f} |"
        )
    lines.extend(
        [
            "", "## 限制", "",
            "- 日報酬平方是 noisy proxy；HAR-style log-r² 不是 intraday HAR-RV。",
            "- 1306.T 與 ^N225 是不同籃子；一致性只能視為跨指標 robustness。",
            "- yfinance 是 2026-07-16 vendor snapshot；1306.T 的尺度修復只保證報酬連續，"
            "不宣稱輸出價格水準是可交易報價；本結果未使用不可得的 ^NKVI。",
            "- Clark-West 對 nested MSPE 有正確方向，但主要 ranking loss 是 QLIKE；兩者不互相冒充。",
            "- VT target/holding-period 不完全一致，且只測簡化 turnover cost。",
            "", "## 產物", "",
            "- k1718.py、k1718_results.json、k1718_data.csv、k1718_oos_forecasts.csv",
            "- k1718_oos_qlike.png、k1718_annual_stability.png、k1718_vt_paths.png",
            "",
            "完整 fit diagnostics、canonical DM HAC/ACF/sensitivity、六格 Holm receipt、資料 SHA 與"
            " 0/10/25 bps sensitivity 均在 results JSON。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    print("K1718: downloading adjusted Japanese OHLC and US VIX...")
    ohlc_by_asset = {
        asset: download_ohlc(metadata["ticker"]) for asset, metadata in ASSETS.items()
    }
    ohlc_by_asset["topix_etf"], topix_scale_diagnostics = normalize_topix_vendor_scale(
        ohlc_by_asset["topix_etf"]
    )
    vix_close = download_ohlc("^VIX")["Close"].rename("vix_close")
    common_start = max(frame.index.min() for frame in ohlc_by_asset.values())
    frames: dict[str, pd.DataFrame] = {}
    oos_by_asset: dict[str, pd.DataFrame] = {}
    assets_result: dict[str, Any] = {}
    for offset, (asset, ohlc) in enumerate(ohlc_by_asset.items()):
        print(f"  building {asset} from common start {common_start.date()}...")
        frame, diagnostic = build_frame(ohlc, vix_close, common_start)
        oos, fit_log = annual_expanding_oos(frame, offset * 100)
        evaluated, metrics, comparisons = evaluate_forecasts(oos)
        frames[asset] = frame
        oos_by_asset[asset] = evaluated
        assets_result[asset] = {
            "ticker": ASSETS[asset]["ticker"],
            "label": ASSETS[asset]["label"],
            "diagnostics": diagnostic,
            "metrics": metrics,
            "comparisons": comparisons,
            "fit_log": fit_log,
        }

    cw_cells: list[tuple[str, str, dict[str, Any], float]] = []
    for asset, payload in assets_result.items():
        for family, comparison in payload["comparisons"].items():
            if family == "shared_mask":
                continue
            cw = comparison["clark_west_primary"]
            cw_cells.append((asset, family, cw, float(cw["p_value_one_sided"])))
    rejected, adjusted, _, _ = multipletests(
        [cell[3] for cell in cw_cells], alpha=0.05, method="holm"
    )
    passed_cells = 0
    for (asset, family, cw, _), reject, adjusted_p in zip(cw_cells, rejected, adjusted):
        cw["holm_p_value_6_tests"] = float(adjusted_p)
        cw["holm_reject_5pct_6_tests"] = bool(reject)
        improvement = assets_result[asset]["comparisons"][family]["qlike_improvement_pct"]
        cw["pre_registered_cell_pass"] = bool(reject and improvement > 0)
        passed_cells += int(cw["pre_registered_cell_pass"])

    if passed_cells == 6:
        scientific_verdict = "ROBUST POSITIVE"
        conclusion = (
            "Lagged US VIX improves all six Japanese cells under lower QLIKE and "
            "Holm-adjusted Clark-West evidence."
        )
    elif passed_cells == 0:
        scientific_verdict = "NULL"
        conclusion = (
            "Lagged US VIX passes none of six pre-registered nested-model cells; "
            "evidence does not support a robust Japan VIX overlay."
        )
    else:
        scientific_verdict = "PARTIAL"
        conclusion = (
            f"Lagged US VIX passes {passed_cells}/6 cells. Evidence is family- or "
            "track-specific and insufficient for a robust Japan-wide overlay."
        )

    strategy, strategy_paths = strategy_scorecard(oos_by_asset["topix_etf"])
    figures = render_figures(assets_result, oos_by_asset, strategy_paths)
    snapshot_parts: dict[str, pd.Series] = {"vix_adjusted_close": vix_close}
    for asset, ohlc in ohlc_by_asset.items():
        snapshot_parts[f"{asset}_adjusted_open"] = ohlc["Open"]
        snapshot_parts[f"{asset}_adjusted_close"] = ohlc["Close"]
        snapshot_parts[f"{asset}_vix_source_date"] = frames[asset]["vix_source_date"]
        snapshot_parts[f"{asset}_vix_signal"] = frames[asset]["vix_signal"]
    atomic_write_csv(DATA_PATH, pd.concat(snapshot_parts, axis=1).sort_index())
    atomic_write_csv(
        OOS_PATH,
        pd.concat(oos_by_asset, names=["asset", "date"]),
    )
    results = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": TASK_ID,
        "executed_at_utc": datetime.now(timezone.utc),
        "scientific_verdict": scientific_verdict,
        "conclusion": conclusion,
        "pre_registered_gate": {
            "rule": (
                "Each of 2 assets x 3 families needs lower augmented QLIKE and "
                "Holm-adjusted one-sided Clark-West p<0.05; 0=NULL, 1-5=PARTIAL, 6=ROBUST."
            ),
            "passed_cells": passed_cells,
            "total_cells": 6,
        },
        "design": {
            "seed": SEED,
            "oos_start_year": OOS_START_YEAR,
            "oos_end_year": OOS_END_YEAR,
            "refit": "annual expanding window",
            "forecast_target": "one-day adjusted close-to-close log-return squared",
            "har_label": "HAR-style log-r2, not HAR-RV",
            "vix_information_set": (
                "latest completed US VIX close with source date strictly before Japan target"
            ),
            "primary_loss": "Patton QLIKE actual/predicted",
            "nested_primary_inference": (
                "Clark-West MSPE-adjusted, one-sided, Holm over 6 cells"
            ),
            "nested_dm_role": "canonical QLIKE DM diagnostic only",
        },
        "literature": LITERATURE,
        "data": {
            "source": "Yahoo Finance via yfinance",
            "adjustment": (
                "auto_adjust=True plus audited 1306.T scale normalization; repaired series is "
                "on a continuous pre-split-equivalent basis for return computation"
            ),
            "repairs": {"topix_etf": topix_scale_diagnostics},
            "download_start": DATA_START,
            "download_end_exclusive": DATA_END_EXCLUSIVE,
            "common_start": common_start,
            "vix": {
                "start": vix_close.index.min(),
                "end": vix_close.index.max(),
                "n_obs": len(vix_close),
            },
            "snapshot_file": DATA_PATH.name,
            "snapshot_sha256": sha256_file(DATA_PATH),
            "oos_forecast_file": OOS_PATH.name,
            "oos_forecast_sha256": sha256_file(OOS_PATH),
        },
        "assets": assets_result,
        "familywise_inference": {
            "method": "Holm over six one-sided Clark-West p-values",
            "alpha": 0.05,
            "cells": [
                {
                    "asset": asset,
                    "family": family,
                    "raw_p": cw["p_value_one_sided"],
                    "holm_p": cw["holm_p_value_6_tests"],
                    "reject": cw["holm_reject_5pct_6_tests"],
                    "cell_pass": cw["pre_registered_cell_pass"],
                }
                for asset, family, cw, _ in cw_cells
            ],
        },
        "exploratory_vt": strategy,
        "figures": figures,
        "limitations": [
            "Daily squared return is noisy; HAR-style log-r2 is not HAR-RV.",
            "Nikkei 225 and TOPIX ETF are separate baskets, not index/ETF replication.",
            "Yahoo Finance is a vendor snapshot and ^NKVI is unavailable.",
            "The 1306.T scale repair targets the audited 2026-07-16 snapshot and may need "
            "re-audit if Yahoo rewrites its history.",
            "Clark-West uses MSE adjustment while primary ranking loss is QLIKE.",
            "VT forecast target and open-to-next-open holding differ; strategy is descriptive.",
        ],
    }
    atomic_write_json(RESULTS_PATH, results)
    atomic_write_text(README_PATH, render_readme(_json_safe(results)))
    print(
        f"K1718 complete: verdict={scientific_verdict}, cells={passed_cells}/6, "
        f"results={RESULTS_PATH}"
    )


if __name__ == "__main__":
    main()
