#!/usr/bin/env python3
"""K1695: canonical 13-market volatility-targeting Table 5 rerun.

This experiment replaces K1178's live/auto-adjusted/daily-signal pipeline with:

* a pinned yfinance snapshot fetched with ``auto_adjust=False``;
* explicit ETF total returns from split-normalized Close plus distributions;
* an inception-aware panel and a separate all-market common-date panel;
* a previous-calendar-month 12/VIX signal, monthly rebalancing, and 10 bp
  one-way turnover cost;
* prior-day ^IRX for time-varying Sharpe excess returns; and
* a synchronous joint stationary bootstrap that resamples the paired BH/VT
  return vector for all 13 markets with one shared date index.

The script writes only inside ``experiments/k1695``.  A live refresh is never
implicit: first-time data acquisition requires ``--refresh-data`` and an
existing snapshot requires ``--force-refresh-data`` to be replaced.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "K1695"
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
SNAPSHOT_PATH = DATA_DIR / "yfinance_raw_snapshot.csv.gz"
MANIFEST_PATH = DATA_DIR / "snapshot_manifest.json"
RESULTS_PATH = SCRIPT_DIR / "k1695_results.json"
TABLE5_PATH = SCRIPT_DIR / "table5_rows.csv"
COMMON_PATH = SCRIPT_DIR / "common_sample_rows.csv"
FIGURE_DATA_PATH = SCRIPT_DIR / "figure2_data.csv"
FIGURE_PATH = SCRIPT_DIR / "figure_cross_asset.png"
RETURNS_PATH = DATA_DIR / "paired_common_returns.csv.gz"

DATA_START = "2004-01-01"
# yfinance end is exclusive.  The manuscript sample ends on 2026-03-31.
DATA_END_EXCLUSIVE = "2026-04-01"
EXPECTED_LAST_DATE = pd.Timestamp("2026-03-31")
INCEPTION_SAMPLE_START = "2007-01-01"
COMMON_SAMPLE_REQUESTED_START = "2012-01-01"

VT_NUMERATOR = 12.0
MAX_EQUITY_WEIGHT = 1.0
TRANSACTION_COST = 0.001  # 10 bp per one-way portfolio turnover
SEED = 42
PRIMARY_BOOTSTRAP_REPS = 10_000
PRIMARY_MEAN_BLOCK = 252
SENSITIVITY_BLOCKS = (63, 126, 504)
SENSITIVITY_REPS = 3_000
CI_LEVEL = 0.90
NON_DISTRIBUTION_CROSSCHECK_TOL = 1e-4  # 1 bp on ordinary price-only dates
DISTRIBUTION_CROSSCHECK_TOL = 3e-3  # 30 bp; Yahoo action amounts are rounded

MARKETS: dict[str, dict[str, str]] = {
    "EFA": {"name": "EAFE (Developed ex-US)", "region": "DM"},
    "EWJ": {"name": "Japan", "region": "DM"},
    "EWG": {"name": "Germany", "region": "DM"},
    "EWU": {"name": "United Kingdom", "region": "DM"},
    "EWA": {"name": "Australia", "region": "DM"},
    "EWC": {"name": "Canada", "region": "DM"},
    "VGK": {"name": "Europe", "region": "DM"},
    "EEM": {"name": "Emerging Markets", "region": "EM"},
    "FXI": {"name": "China Large-Cap", "region": "EM"},
    "EWZ": {"name": "Brazil", "region": "EM"},
    "INDA": {"name": "India", "region": "EM"},
    "EWT": {"name": "Taiwan", "region": "EM"},
    "MCHI": {"name": "China Broad", "region": "EM"},
}

REQUIRED_TICKERS = tuple(MARKETS) + ("^VIX", "SHY", "^IRX")

REFERENCES = [
    {
        "authors": "Moreira, A., & Muir, T.",
        "year": 2017,
        "title": "Volatility-Managed Portfolios",
        "journal": "Journal of Finance, 72(4), 1611-1644",
        "doi": "10.1111/jofi.12513",
        "role": "Foundational volatility-managed portfolio design.",
    },
    {
        "authors": "Harvey, C. R., Hoyle, E., Korgaonkar, R., Rattray, S., Sargaison, M., & Van Hemert, O.",
        "year": 2018,
        "title": "The Impact of Volatility Targeting",
        "journal": "Journal of Portfolio Management, 45(1), 14-33",
        "doi": "10.3905/jpm.2018.45.1.014",
        "role": "Cross-asset evidence and drawdown interpretation for volatility targeting.",
    },
    {
        "authors": "Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X.",
        "year": 2020,
        "title": "On the Performance of Volatility-Managed Portfolios",
        "journal": "Journal of Financial Economics, 138(1), 95-117",
        "doi": "10.1016/j.jfineco.2020.04.015",
        "role": "Out-of-sample and implementation caveats for volatility-managed portfolios.",
    },
    {
        "authors": "Politis, D. N., & Romano, J. P.",
        "year": 1994,
        "title": "The Stationary Bootstrap",
        "journal": "Journal of the American Statistical Association, 89(428), 1303-1313",
        "doi": "10.1080/01621459.1994.10476870",
        "role": "Dependence-preserving time-series bootstrap used for joint inference.",
    },
]


def _to_builtin(value: Any) -> Any:
    """Convert numpy/pandas values without hiding NaN or boolean type errors."""
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NA:
        return None
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Validate and atomically replace a JSON artifact in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _to_builtin(payload)
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    # Parse before touching the final path; this catches invalid serialization.
    json.loads(serialized)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        json.loads(tmp.read_text(encoding="utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        frame.to_csv(tmp, index=False, lineterminator="\n")
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        pd.read_csv(tmp, nrows=2)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_gzip_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write a deterministic gzip CSV (mtime=0) and atomically replace final."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", fileobj=raw_handle, mode="wb", mtime=0) as gz:
                with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text_handle:
                    frame.to_csv(text_handle, index=False, lineterminator="\n")
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
        pd.read_csv(tmp, compression="gzip", nrows=2)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_snapshot_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    """Fail closed on truncated or internally stale required series."""
    coverage: dict[str, Any] = {}
    for ticker in REQUIRED_TICKERS:
        ticker_frame = frame[frame["ticker"] == ticker].dropna(subset=["date", "close"])
        if ticker_frame.empty:
            raise ValueError(f"{ticker}: no usable close observations")
        dates = pd.DatetimeIndex(ticker_frame["date"]).sort_values().unique()
        last_date = pd.Timestamp(dates[-1])
        if last_date != EXPECTED_LAST_DATE:
            raise ValueError(
                f"{ticker}: truncated snapshot end {last_date.date()} != "
                f"{EXPECTED_LAST_DATE.date()}"
            )
        gaps = pd.Series(dates[1:] - dates[:-1])
        max_gap_days = int(gaps.max().days) if len(gaps) else 0
        # US market holidays create at most short calendar gaps.  Ten days is
        # deliberately generous but catches stale IRX/VIX/ETF fetches.
        if max_gap_days > 10:
            raise ValueError(f"{ticker}: abnormal internal quote gap of {max_gap_days} days")
        coverage[ticker] = {
            "first_date": pd.Timestamp(dates[0]),
            "last_date": last_date,
            "n_close": len(dates),
            "max_calendar_gap_days": max_gap_days,
        }
    return coverage


def _flatten_download(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    required = {"Close", "Adj Close"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"{ticker}: missing required columns {sorted(missing)}")
    for column in ("Dividends", "Capital Gains", "Stock Splits", "Volume"):
        if column not in frame.columns:
            frame[column] = 0.0
    out = frame[
        ["Close", "Adj Close", "Dividends", "Capital Gains", "Stock Splits", "Volume"]
    ].rename(
        columns={
            "Close": "close",
            "Adj Close": "adj_close",
            "Dividends": "dividends",
            "Capital Gains": "capital_gains",
            "Stock Splits": "stock_splits",
            "Volume": "volume",
        }
    )
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out.index.name = "date"
    out = out.reset_index()
    out.insert(1, "ticker", ticker)
    for column in ("close", "adj_close", "dividends", "capital_gains", "stock_splits"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    return out.sort_values("date").reset_index(drop=True)


def fetch_snapshot(*, force: bool) -> dict[str, Any]:
    if SNAPSHOT_PATH.exists() and not force:
        raise FileExistsError(
            f"snapshot already exists: {SNAPSHOT_PATH}; use --force-refresh-data to replace"
        )
    fetched_at = datetime.now(timezone.utc).isoformat()
    pieces: list[pd.DataFrame] = []
    diagnostics: dict[str, Any] = {}
    for ticker in REQUIRED_TICKERS:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = yf.download(
                    ticker,
                    start=DATA_START,
                    end=DATA_END_EXCLUSIVE,
                    auto_adjust=False,
                    actions=True,
                    repair=False,
                    progress=False,
                    threads=False,
                    timeout=30,
                )
                piece = _flatten_download(raw, ticker)
                pieces.append(piece)
                diagnostics[ticker] = {
                    "rows": len(piece),
                    "first_date": piece["date"].min(),
                    "last_date": piece["date"].max(),
                    "dividend_events": int((piece["dividends"].fillna(0) != 0).sum()),
                    "capital_gain_events": int((piece["capital_gains"].fillna(0) != 0).sum()),
                    "split_events": int((piece["stock_splits"].fillna(0) != 0).sum()),
                }
                break
            except Exception as exc:  # noqa: BLE001 - retries retain final cause
                last_error = exc
                if attempt == 3:
                    raise RuntimeError(f"failed to fetch {ticker}: {exc}") from exc
        if last_error is not None and ticker not in diagnostics:
            raise RuntimeError(f"failed to fetch {ticker}: {last_error}")

    snapshot = pd.concat(pieces, ignore_index=True)
    snapshot = snapshot.sort_values(["ticker", "date"]).reset_index(drop=True)
    if snapshot.duplicated(["ticker", "date"]).any():
        raise ValueError("snapshot contains duplicate ticker/date rows")
    if set(snapshot["ticker"].unique()) != set(REQUIRED_TICKERS):
        raise ValueError("snapshot ticker set does not match REQUIRED_TICKERS")
    coverage = validate_snapshot_coverage(snapshot)

    atomic_write_gzip_csv(snapshot, SNAPSHOT_PATH)
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "fetched_at_utc": fetched_at,
        "source": "Yahoo Finance via yfinance",
        "yfinance_version": yf.__version__,
        "parameters": {
            "start_inclusive": DATA_START,
            "end_exclusive": DATA_END_EXCLUSIVE,
            "auto_adjust": False,
            "actions": True,
            "repair": False,
            "tickers": list(REQUIRED_TICKERS),
        },
        "snapshot_file": SNAPSHOT_PATH.name,
        "snapshot_sha256": sha256_file(SNAPSHOT_PATH),
        "rows": len(snapshot),
        "ticker_diagnostics": diagnostics,
        "coverage_validation": coverage,
    }
    atomic_write_json(MANIFEST_PATH, manifest)
    return manifest


def load_snapshot() -> tuple[pd.DataFrame, dict[str, Any]]:
    if not SNAPSHOT_PATH.exists() or not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            "pinned snapshot missing; run once with --refresh-data (never fetched implicitly)"
        )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    observed_hash = sha256_file(SNAPSHOT_PATH)
    expected_hash = manifest.get("snapshot_sha256")
    if observed_hash != expected_hash:
        raise ValueError(
            f"snapshot hash drift: expected={expected_hash}, observed={observed_hash}"
        )
    frame = pd.read_csv(SNAPSHOT_PATH, compression="gzip", parse_dates=["date"])
    if frame.empty or frame.duplicated(["ticker", "date"]).any():
        raise ValueError("snapshot is empty or contains duplicate ticker/date rows")
    if set(frame["ticker"].unique()) != set(REQUIRED_TICKERS):
        raise ValueError("snapshot required ticker set mismatch")
    if frame["date"].max() >= pd.Timestamp(DATA_END_EXCLUSIVE):
        raise ValueError("snapshot contains observations beyond exclusive end date")
    validate_snapshot_coverage(frame)
    return frame.sort_values(["ticker", "date"]), manifest


def explicit_total_returns(frame: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    """Rebuild ETF total return from split-normalized Close + distributions.

    Yahoo/yfinance's historical ``Close`` is normalized for stock splits even
    when ``auto_adjust=False``; ``Stock Splits`` is therefore retained as an
    audit field but must not be applied a second time.  Dividends and capital
    gains are explicitly reinvested on their ex-date:

        r_t = (Close_t + Dividend_t + CapitalGain_t) / Close_(t-1) - 1.

    ``Adj Close`` is used only as a hard diagnostic cross-check, never as the
    return input.
    """
    ordered = frame.sort_values("date").set_index("date")
    ticker = str(frame["ticker"].iloc[0])
    close = ordered["close"].astype(float)
    distribution = (
        ordered["dividends"].fillna(0).astype(float)
        + ordered["capital_gains"].fillna(0).astype(float)
    )
    returns = (close + distribution) / close.shift(1) - 1.0
    adj_returns = ordered["adj_close"].astype(float).pct_change()
    comparison = pd.concat([returns.rename("explicit"), adj_returns.rename("adj")], axis=1).dropna()
    abs_diff = (comparison["explicit"] - comparison["adj"]).abs()
    max_diff = float(abs_diff.max()) if len(abs_diff) else math.nan
    distribution_mask = distribution.reindex(comparison.index).fillna(0.0) != 0.0
    ordinary_diff = abs_diff[~distribution_mask]
    action_diff = abs_diff[distribution_mask]
    ordinary_max = float(ordinary_diff.max()) if len(ordinary_diff) else 0.0
    action_max = float(action_diff.max()) if len(action_diff) else 0.0
    if not math.isfinite(max_diff):
        raise ValueError(f"{ticker}: total-return cross-check produced no finite differences")
    if ordinary_max > NON_DISTRIBUTION_CROSSCHECK_TOL:
        raise ValueError(
            f"{ticker}: ordinary-day total-return cross-check failed: "
            f"max_abs_diff={ordinary_max:.8f}"
        )
    if action_max > DISTRIBUTION_CROSSCHECK_TOL:
        raise ValueError(
            f"{ticker}: distribution-day total-return cross-check failed: "
            f"max_abs_diff={action_max:.8f}"
        )
    returns.name = ticker
    diagnostics = {
        "n_returns": int(returns.notna().sum()),
        "first_return_date": returns.dropna().index.min(),
        "last_return_date": returns.dropna().index.max(),
        "dividend_events": int((ordered["dividends"].fillna(0) != 0).sum()),
        "capital_gain_events": int((ordered["capital_gains"].fillna(0) != 0).sum()),
        "split_events_audit_only": int((ordered["stock_splits"].fillna(0) != 0).sum()),
        "adj_close_max_abs_return_diff": max_diff,
        "adj_close_mean_abs_return_diff": float(abs_diff.mean()),
        "adj_close_ordinary_day_max_abs_return_diff": ordinary_max,
        "adj_close_distribution_day_max_abs_return_diff": action_max,
        "crosscheck_thresholds": {
            "ordinary_day": NON_DISTRIBUTION_CROSSCHECK_TOL,
            "distribution_day": DISTRIBUTION_CROSSCHECK_TOL,
        },
    }
    return returns.dropna(), diagnostics


def build_monthly_lagged_weights(vix_level: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """Map prior calendar-month-end VIX to every day in the next month."""
    vix = vix_level.dropna().sort_index()
    monthly_vix = vix.groupby(vix.index.to_period("M")).last()
    # Include one future calendar-month label so the final observed month-end
    # signal is available throughout the following month after shift(1).
    full_periods = pd.period_range(monthly_vix.index.min(), monthly_vix.index.max() + 1, freq="M")
    unlagged_signal = (VT_NUMERATOR / monthly_vix).clip(
        lower=0.0, upper=MAX_EQUITY_WEIGHT
    ).reindex(full_periods)
    # Explicit anti-lookahead rule: month m receives only the signal from m-1.
    lagged_signal = unlagged_signal.shift(1)
    periods = pd.DatetimeIndex(dates).to_period("M")
    values = [lagged_signal.get(period, np.nan) for period in periods]
    return pd.Series(values, index=pd.DatetimeIndex(dates), name="target_weight", dtype=float)


def prior_day_irx_daily(irx_level: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """Prior-day ^IRX annual percent converted to a daily return proxy."""
    irx = irx_level.sort_index().astype(float)
    target_dates = pd.DatetimeIndex(dates)
    # First align only from past observations, then shift on the return-date
    # calendar.  Shifting the sparse IRX source before reindexing would delay a
    # quote until the next *IRX observation* rather than the next return day.
    aligned_same_day = (irx / 100.0).reindex(target_dates, method="ffill")
    aligned = aligned_same_day.shift(1)
    daily = aligned / 252.0  # repo convention; ^IRX is a bank-discount-yield proxy
    daily.name = "rf_daily"
    return daily


def _assert_calendar_mapping() -> None:
    toy_vix = pd.Series(
        [10.0, 20.0, 40.0],
        index=pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
    )
    toy_dates = pd.to_datetime(["2025-02-03", "2025-02-28", "2025-03-03", "2025-04-01"])
    mapped = build_monthly_lagged_weights(toy_vix, toy_dates)
    expected = np.array([1.0, 1.0, 0.6, 0.3])
    if not np.allclose(mapped.to_numpy(), expected, atol=1e-12):
        raise AssertionError(f"month mapping failed: got={mapped.tolist()} expected={expected.tolist()}")


@dataclass
class StrategyPath:
    returns: pd.Series
    target_weight: pd.Series
    pretrade_equity_weight: pd.Series
    turnover: pd.Series
    transaction_cost: pd.Series


def simulate_monthly_hold(
    equity_returns: pd.Series,
    cash_returns: pd.Series,
    target_weights: pd.Series,
    *,
    cost_rate: float = TRANSACTION_COST,
) -> StrategyPath:
    """Rebalance at the first observed date of each month, then let weights drift."""
    panel = pd.concat(
        [
            equity_returns.rename("equity"),
            cash_returns.rename("cash"),
            target_weights.rename("target"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if panel.empty:
        raise ValueError("no aligned observations for monthly strategy")

    nav = 1.0
    equity_value = math.nan
    cash_value = math.nan
    previous_period: pd.Period | None = None
    daily_returns: list[float] = []
    pretrade_weights: list[float] = []
    turnovers: list[float] = []
    costs: list[float] = []

    for date, row in panel.iterrows():
        period = date.to_period("M")
        nav_before = nav
        target = float(row["target"])
        turnover = 0.0
        cost = 0.0

        if previous_period is None:
            # Initial allocation is not counted as turnover; both BH and VT
            # begin from cash on the same first return date.
            pretrade_weight = target
            equity_value = target * nav
            cash_value = (1.0 - target) * nav
        else:
            pretrade_weight = equity_value / nav if nav > 0 else math.nan
            if period != previous_period:
                turnover = abs(target - pretrade_weight)
                cost = cost_rate * turnover * nav
                nav_after_cost = nav - cost
                equity_value = target * nav_after_cost
                cash_value = (1.0 - target) * nav_after_cost
                nav = nav_after_cost

        equity_value *= 1.0 + float(row["equity"])
        cash_value *= 1.0 + float(row["cash"])
        nav = equity_value + cash_value
        daily_returns.append(nav / nav_before - 1.0)
        pretrade_weights.append(pretrade_weight)
        turnovers.append(turnover)
        costs.append(cost / nav_before)
        previous_period = period

    index = panel.index
    return StrategyPath(
        returns=pd.Series(daily_returns, index=index, name="vt_return"),
        target_weight=panel["target"].rename("target_weight").copy(),
        pretrade_equity_weight=pd.Series(pretrade_weights, index=index, name="pretrade_weight"),
        turnover=pd.Series(turnovers, index=index, name="turnover"),
        transaction_cost=pd.Series(costs, index=index, name="transaction_cost"),
    )


def compute_metrics(returns: pd.Series, rf_daily: pd.Series) -> dict[str, Any]:
    aligned = pd.concat([returns.rename("r"), rf_daily.rename("rf")], axis=1, join="inner").dropna()
    if len(aligned) < 252:
        raise ValueError(f"insufficient observations for metrics: {len(aligned)}")
    r = aligned["r"].astype(float)
    if (r <= -1.0).any():
        raise ValueError("return <= -100% encountered")
    wealth = (1.0 + r).cumprod()
    # Initial NAV=1 is an economically real running peak.  Omitting it makes
    # any path that begins with losses report too-small drawdown.
    running_peak = wealth.cummax().clip(lower=1.0)
    drawdown = wealth / running_peak - 1.0
    years = len(r) / 252.0
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
    annual_vol = float(r.std(ddof=1) * math.sqrt(252.0))
    excess = r - aligned["rf"]
    sharpe = float(excess.mean() / r.std(ddof=1) * math.sqrt(252.0))
    mdd = float(drawdown.min())
    return {
        "start": r.index.min(),
        "end": r.index.max(),
        "n_obs": len(r),
        "years": years,
        "cagr": cagr,
        "annualized_arithmetic_return": float(r.mean() * 252.0),
        "annual_volatility": annual_vol,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else None,
    }


def max_drawdown_by_column(returns: np.ndarray) -> np.ndarray:
    if returns.ndim != 2:
        raise ValueError("returns must be a 2-D date x market matrix")
    wealth = np.cumprod(1.0 + returns, axis=0)
    peaks = np.maximum.accumulate(
        np.vstack([np.ones((1, wealth.shape[1]), dtype=float), wealth]), axis=0
    )[1:]
    return np.min(wealth / peaks - 1.0, axis=0)


def stationary_bootstrap_indices(
    n_obs: int, mean_block: int, rng: np.random.Generator
) -> np.ndarray:
    """Circular stationary-bootstrap indices of exactly ``n_obs`` length."""
    if n_obs < 2 or mean_block < 1:
        raise ValueError("invalid stationary bootstrap dimensions")
    probability = 1.0 / float(mean_block)
    chunks: list[np.ndarray] = []
    remaining = n_obs
    while remaining > 0:
        start = int(rng.integers(0, n_obs))
        length = min(int(rng.geometric(probability)), remaining)
        chunks.append((start + np.arange(length, dtype=int)) % n_obs)
        remaining -= length
    indices = np.concatenate(chunks)
    if len(indices) != n_obs:
        raise AssertionError("bootstrap path length differs from source sample")
    return indices


def joint_mdd_bootstrap(
    paired_returns: pd.DataFrame,
    market_order: Iterable[str],
    *,
    reps: int,
    mean_block: int,
    seed: int,
    ci_level: float = CI_LEVEL,
) -> dict[str, Any]:
    markets = list(market_order)
    bh_columns = [f"{ticker}_bh" for ticker in markets]
    vt_columns = [f"{ticker}_vt" for ticker in markets]
    expected = bh_columns + vt_columns
    if any(column not in paired_returns.columns for column in expected):
        raise ValueError("paired return panel is missing BH/VT columns")
    panel = paired_returns[expected].dropna()
    bh = panel[bh_columns].to_numpy(dtype=float)
    vt = panel[vt_columns].to_numpy(dtype=float)
    if not np.isfinite(bh).all() or not np.isfinite(vt).all():
        raise ValueError("non-finite returns in joint bootstrap panel")

    rng = np.random.default_rng(seed)
    avg_delta = np.empty(reps, dtype=float)
    all_positive = np.empty(reps, dtype=bool)
    market_delta = np.empty((reps, len(markets)), dtype=float)
    for replication in range(reps):
        indices = stationary_bootstrap_indices(len(panel), mean_block, rng)
        # One shared index simultaneously resamples all 26 paired columns.
        bh_mdd = max_drawdown_by_column(bh[indices])
        vt_mdd = max_drawdown_by_column(vt[indices])
        delta_pp = (vt_mdd - bh_mdd) * 100.0
        market_delta[replication] = delta_pp
        avg_delta[replication] = float(delta_pp.mean())
        all_positive[replication] = bool(np.all(delta_pp > 0.0))

    alpha = (1.0 - ci_level) / 2.0
    lower, upper = np.quantile(avg_delta, [alpha, 1.0 - alpha])
    per_market_ci: dict[str, Any] = {}
    for column_index, ticker in enumerate(markets):
        lo, hi = np.quantile(market_delta[:, column_index], [alpha, 1.0 - alpha])
        per_market_ci[ticker] = {
            "lower_pp": lo,
            "median_pp": float(np.median(market_delta[:, column_index])),
            "upper_pp": hi,
        }
    return {
        "n_obs": len(panel),
        "reps": reps,
        "seed": seed,
        "method": "joint circular stationary bootstrap; shared date indices across 13 paired BH/VT vectors",
        "mean_block_days": mean_block,
        "ci_level": ci_level,
        "average_delta_mdd_pp": {
            "lower": lower,
            "median": float(np.median(avg_delta)),
            "upper": upper,
            "mean": float(avg_delta.mean()),
            "probability_le_zero": float(np.mean(avg_delta <= 0.0)),
        },
        "probability_all_13_positive": float(all_positive.mean()),
        "per_market_delta_mdd_ci": per_market_ci,
    }


def _market_panel(snapshot: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    returns: dict[str, pd.Series] = {}
    diagnostics: dict[str, Any] = {}
    for ticker in tuple(MARKETS) + ("SHY",):
        series, detail = explicit_total_returns(snapshot[snapshot["ticker"] == ticker])
        returns[ticker] = series
        diagnostics[ticker] = detail
    return returns, diagnostics


def _level(snapshot: pd.DataFrame, ticker: str) -> pd.Series:
    frame = snapshot[snapshot["ticker"] == ticker].sort_values("date")
    series = frame.set_index("date")["close"].astype(float).dropna()
    series.name = ticker
    return series


def _run_one_market(
    ticker: str,
    *,
    start: pd.Timestamp,
    market_return: pd.Series,
    shy_return: pd.Series,
    vix_level: pd.Series,
    irx_level: pd.Series,
    required_dates: pd.DatetimeIndex | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    candidate_dates = market_return.index.intersection(shy_return.index)
    candidate_dates = candidate_dates[candidate_dates >= start]
    if required_dates is not None:
        candidate_dates = candidate_dates.intersection(required_dates)
    weights = build_monthly_lagged_weights(vix_level, candidate_dates)
    rf = prior_day_irx_daily(irx_level, candidate_dates)
    aligned = pd.concat(
        [
            market_return.reindex(candidate_dates).rename("bh"),
            shy_return.reindex(candidate_dates).rename("shy"),
            weights,
            rf,
        ],
        axis=1,
    ).dropna()
    if len(aligned) < 252:
        raise ValueError(f"{ticker}: insufficient aligned observations ({len(aligned)})")

    strategy = simulate_monthly_hold(
        aligned["bh"], aligned["shy"], aligned["target_weight"]
    )
    comparison = pd.concat(
        [
            aligned["bh"].reindex(strategy.returns.index),
            strategy.returns,
            aligned["rf_daily"].reindex(strategy.returns.index),
            strategy.target_weight,
            strategy.turnover,
            strategy.transaction_cost,
        ],
        axis=1,
    ).dropna()
    bh_metrics = compute_metrics(comparison["bh"], comparison["rf_daily"])
    vt_metrics = compute_metrics(comparison["vt_return"], comparison["rf_daily"])
    vix_change = vix_level.pct_change().reindex(comparison.index)
    sens_frame = pd.concat([comparison["bh"], vix_change.rename("vix_change")], axis=1).dropna()
    vix_r, vix_p = stats.pearsonr(sens_frame["bh"], sens_frame["vix_change"])

    result = {
        "ticker": ticker,
        "name": MARKETS[ticker]["name"],
        "region": MARKETS[ticker]["region"],
        "sample_start": comparison.index.min(),
        "sample_end": comparison.index.max(),
        "n_obs": len(comparison),
        "bh": bh_metrics,
        "vt": vt_metrics,
        "delta_sharpe": vt_metrics["sharpe"] - bh_metrics["sharpe"],
        "delta_mdd_pp": (vt_metrics["max_drawdown"] - bh_metrics["max_drawdown"]) * 100.0,
        "annual_return_cost_pp": (vt_metrics["cagr"] - bh_metrics["cagr"]) * 100.0,
        "vix_sensitivity_pearson_r": float(vix_r),
        "vix_sensitivity_p": float(vix_p),
        "average_target_equity_weight": float(comparison["target_weight"].mean()),
        "annualized_turnover": float(comparison["turnover"].sum() / (len(comparison) / 252.0)),
        "total_transaction_cost_pct": float(comparison["transaction_cost"].sum() * 100.0),
        "n_rebalances_with_cost": int((comparison["transaction_cost"] > 0).sum()),
    }
    comparison = comparison.rename(
        columns={"bh": f"{ticker}_bh", "vt_return": f"{ticker}_vt"}
    )
    return result, comparison


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    delta_mdd = np.array([row["delta_mdd_pp"] for row in rows], dtype=float)
    delta_sharpe = np.array([row["delta_sharpe"] for row in rows], dtype=float)
    annual_cost = np.array([row["annual_return_cost_pp"] for row in rows], dtype=float)
    vix_sensitivity = np.array([row["vix_sensitivity_pearson_r"] for row in rows], dtype=float)
    pearson = stats.pearsonr(vix_sensitivity, delta_mdd)
    spearman = stats.spearmanr(vix_sensitivity, delta_mdd)
    dm = [row["delta_mdd_pp"] for row in rows if row["region"] == "DM"]
    em = [row["delta_mdd_pp"] for row in rows if row["region"] == "EM"]
    return {
        "n_markets": len(rows),
        "n_mdd_improved": int(np.sum(delta_mdd > 0)),
        "n_sharpe_improved": int(np.sum(delta_sharpe > 0)),
        "average_delta_mdd_pp": float(delta_mdd.mean()),
        "average_delta_sharpe": float(delta_sharpe.mean()),
        "average_annual_return_cost_pp": float(annual_cost.mean()),
        "dm_average_delta_mdd_pp": float(np.mean(dm)),
        "em_average_delta_mdd_pp": float(np.mean(em)),
        "vix_sensitivity_vs_delta_mdd": {
            "pearson_r": float(pearson.statistic),
            "pearson_p": float(pearson.pvalue),
            "spearman_rho": float(spearman.statistic),
            "spearman_p": float(spearman.pvalue),
            "interpretation": "descriptive cross-sectional association; not causal",
        },
    }


def _rows_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "ticker": row["ticker"],
                "name": row["name"],
                "region": row["region"],
                "sample_start": pd.Timestamp(row["sample_start"]).date().isoformat(),
                "sample_end": pd.Timestamp(row["sample_end"]).date().isoformat(),
                "n_obs": row["n_obs"],
                "bh_sharpe": row["bh"]["sharpe"],
                "bh_mdd_pct": row["bh"]["max_drawdown"] * 100.0,
                "bh_cagr_pct": row["bh"]["cagr"] * 100.0,
                "vt_sharpe": row["vt"]["sharpe"],
                "vt_mdd_pct": row["vt"]["max_drawdown"] * 100.0,
                "vt_cagr_pct": row["vt"]["cagr"] * 100.0,
                "delta_sharpe": row["delta_sharpe"],
                "delta_mdd_pp": row["delta_mdd_pp"],
                "annual_return_cost_pp": row["annual_return_cost_pp"],
                "vix_sensitivity": row["vix_sensitivity_pearson_r"],
                "annualized_turnover": row["annualized_turnover"],
                "total_transaction_cost_pct": row["total_transaction_cost_pct"],
            }
        )
    return pd.DataFrame.from_records(records)


def _render_figure(frame: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 7.0), dpi=150)
    palette = {"DM": "#2563eb", "EM": "#dc2626"}
    marker = {"DM": "o", "EM": "s"}
    for region in ("DM", "EM"):
        subset = frame[frame["region"] == region]
        ax.scatter(
            subset["delta_sharpe"],
            subset["delta_mdd_pp"],
            s=80,
            c=palette[region],
            marker=marker[region],
            alpha=0.88,
            edgecolor="white",
            linewidth=0.8,
            label="Developed" if region == "DM" else "Emerging",
        )
        for _, row in subset.iterrows():
            ax.annotate(
                row["ticker"],
                (row["delta_sharpe"], row["delta_mdd_pp"]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9,
            )
    ax.axvline(0.0, color="#64748b", linewidth=1.0, linestyle="--")
    ax.axhline(0.0, color="#64748b", linewidth=1.0, linestyle="--")
    ax.axvline(frame["delta_sharpe"].mean(), color="#94a3b8", linewidth=1.0, linestyle=":")
    ax.axhline(frame["delta_mdd_pp"].mean(), color="#94a3b8", linewidth=1.0, linestyle=":")
    ax.set_title("International Volatility Targeting: Sharpe Cost vs Drawdown Protection")
    ax.set_xlabel("Change in Sharpe ratio (VT minus buy-and-hold)")
    ax.set_ylabel("Maximum-drawdown improvement (percentage points)")
    ax.grid(alpha=0.18)
    ax.legend(frameon=False)
    fig.tight_layout()
    tmp = FIGURE_PATH.with_name(f".{FIGURE_PATH.name}.tmp.{os.getpid()}.png")
    try:
        fig.savefig(tmp, bbox_inches="tight")
        os.replace(tmp, FIGURE_PATH)
    finally:
        plt.close(fig)
        tmp.unlink(missing_ok=True)


def _source_bindings() -> dict[str, Any]:
    return {
        "table5_rows": {
            "artifact": TABLE5_PATH.name,
            "json_path": "$.samples.inception_aware.rows[*]",
        },
        "common_sample_rows": {
            "artifact": COMMON_PATH.name,
            "json_path": "$.samples.common_period.rows[*]",
        },
        "figure2": {
            "data_artifact": FIGURE_DATA_PATH.name,
            "image_artifact": FIGURE_PATH.name,
            "json_path": "$.samples.inception_aware.rows[*]",
        },
        "abstract_average_delta_mdd": "$.samples.inception_aware.summary.average_delta_mdd_pp",
        "abstract_average_delta_sharpe": "$.samples.inception_aware.summary.average_delta_sharpe",
        "abstract_annual_return_cost": "$.samples.inception_aware.summary.average_annual_return_cost_pp",
        "joint_bootstrap_ci": "$.inference.primary.average_delta_mdd_pp",
        "joint_bootstrap_kill_flag": "$.decision.kill_triggered",
    }


def run_experiment(
    *,
    primary_reps: int,
    sensitivity_reps: int,
) -> dict[str, Any]:
    _assert_calendar_mapping()
    snapshot, manifest = load_snapshot()
    total_returns, return_diagnostics = _market_panel(snapshot)
    vix_level = _level(snapshot, "^VIX")
    irx_level = _level(snapshot, "^IRX")
    shy_return = total_returns["SHY"]

    inception_rows: list[dict[str, Any]] = []
    for ticker in MARKETS:
        row, _ = _run_one_market(
            ticker,
            start=pd.Timestamp(INCEPTION_SAMPLE_START),
            market_return=total_returns[ticker],
            shy_return=shy_return,
            vix_level=vix_level,
            irx_level=irx_level,
        )
        inception_rows.append(row)
    if any(pd.Timestamp(row["sample_end"]) != EXPECTED_LAST_DATE for row in inception_rows):
        raise ValueError("one or more inception-aware market samples do not reach paper cutoff")

    # Derive the first date on which every market has an observed total return.
    common_dates = shy_return.index[shy_return.index >= pd.Timestamp(COMMON_SAMPLE_REQUESTED_START)]
    for ticker in MARKETS:
        eligible = total_returns[ticker].index[
            total_returns[ticker].index >= pd.Timestamp(COMMON_SAMPLE_REQUESTED_START)
        ]
        common_dates = common_dates.intersection(eligible)
    if len(common_dates) < 252:
        raise ValueError("all-market common sample is too short")
    common_start = common_dates.min()

    common_rows: list[dict[str, Any]] = []
    paired_parts: list[pd.DataFrame] = []
    for ticker in MARKETS:
        row, comparison = _run_one_market(
            ticker,
            start=common_start,
            market_return=total_returns[ticker],
            shy_return=shy_return,
            vix_level=vix_level,
            irx_level=irx_level,
            required_dates=common_dates,
        )
        common_rows.append(row)
        paired_parts.append(comparison[[f"{ticker}_bh", f"{ticker}_vt"]])
    paired = pd.concat(paired_parts, axis=1, join="inner").dropna()
    if paired.index.min() != common_start:
        common_start = paired.index.min()
    if paired.isna().any().any() or len(paired) < 252:
        raise ValueError("paired common return panel is incomplete")
    if paired.index.max() != EXPECTED_LAST_DATE:
        raise ValueError(
            f"paired common sample end {paired.index.max().date()} != {EXPECTED_LAST_DATE.date()}"
        )
    if any(pd.Timestamp(row["sample_end"]) != EXPECTED_LAST_DATE for row in common_rows):
        raise ValueError("one or more common-sample market rows do not reach paper cutoff")
    paired_export = paired.reset_index().rename(columns={paired.index.name or "index": "date"})
    atomic_write_gzip_csv(paired_export, RETURNS_PATH)

    primary = joint_mdd_bootstrap(
        paired,
        MARKETS,
        reps=primary_reps,
        mean_block=PRIMARY_MEAN_BLOCK,
        seed=SEED,
    )
    sensitivity: dict[str, Any] = {}
    for offset, block in enumerate(SENSITIVITY_BLOCKS, start=1):
        sensitivity[str(block)] = joint_mdd_bootstrap(
            paired,
            MARKETS,
            reps=sensitivity_reps,
            mean_block=block,
            seed=SEED + 10_000 * offset,
        )

    inception_summary = _summary(inception_rows)
    common_summary = _summary(common_rows)
    ci = primary["average_delta_mdd_pp"]
    kill_triggered = bool(
        inception_summary["n_mdd_improved"] < len(MARKETS)
        or common_summary["n_mdd_improved"] < len(MARKETS)
        or ci["lower"] <= 0.0 <= ci["upper"]
    )
    decision = {
        "kill_triggered": kill_triggered,
        "pre_registered_kill_rule": (
            "TRUE if either observed sample has fewer than 13/13 positive MDD improvements "
            "or the primary joint-bootstrap CI for common-sample average delta MDD includes zero"
        ),
        "narrative_implication": (
            "downgrade international contribution to conditional"
            if kill_triggered
            else "international drawdown-protection result survives the pre-registered gate"
        ),
    }

    table_frame = _rows_frame(inception_rows)
    common_frame = _rows_frame(common_rows)
    atomic_write_csv(table_frame, TABLE5_PATH)
    atomic_write_csv(common_frame, COMMON_PATH)
    figure_frame = table_frame[
        [
            "ticker",
            "name",
            "region",
            "delta_sharpe",
            "delta_mdd_pp",
            "annual_return_cost_pp",
            "vix_sensitivity",
        ]
    ].copy()
    atomic_write_csv(figure_frame, FIGURE_DATA_PATH)
    _render_figure(figure_frame)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "VT Trend-Following Table 5: Canonical 13-Market Rerun",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "empirical descriptive study with dependence-robust bootstrap inference",
        "motivation": (
            "Replace K1178's mixed-vintage Table 5 pipeline with one pinned, auditable run "
            "covering every row, summary statistic, figure point, and abstract number."
        ),
        "data": {
            "source": "Yahoo Finance via yfinance; pinned local snapshot",
            "snapshot": str(SNAPSHOT_PATH.relative_to(SCRIPT_DIR)),
            "snapshot_sha256": manifest["snapshot_sha256"],
            "fetched_at_utc": manifest["fetched_at_utc"],
            "requested_period": {
                "start_inclusive": DATA_START,
                "end_exclusive": DATA_END_EXCLUSIVE,
            },
            "tickers": list(REQUIRED_TICKERS),
            "auto_adjust": False,
            "total_return_formula": "(Close_t + Dividends_t + CapitalGains_t) / Close_(t-1) - 1",
            "stock_split_treatment": (
                "Yahoo historical Close is split-normalized; split actions retained for audit and not applied twice"
            ),
            "return_reconstruction_diagnostics": return_diagnostics,
            "proxy_limitations": [
                "SHY total return is the investable cash sleeve, not a frictionless risk-free asset.",
                "^IRX/100/252 is a prior-day daily Sharpe benchmark approximation to a 13-week bank-discount yield.",
                "US-listed country ETFs include fund fees, tracking error, and US trading-calendar effects.",
            ],
        },
        "strategy": {
            "rule": "equity target = min(12 / previous-calendar-month-end VIX, 1.0)",
            "information_lag": "monthly VIX signal.shift(1), mapped by PeriodIndex; t-1 information only",
            "rebalance": "first observed trading date of each calendar month; holdings drift within month",
            "cash_sleeve": "SHY explicit total return",
            "transaction_cost": "10 bp x one-way portfolio turnover; no initial-allocation charge",
            "risk_free_for_sharpe": "prior-day ^IRX / 100 / 252, forward-filled only from past observations",
        },
        "samples": {
            "inception_aware": {
                "requested_start": INCEPTION_SAMPLE_START,
                "description": "Each ETF enters at its own first valid return after the requested start.",
                "rows": inception_rows,
                "summary": inception_summary,
            },
            "common_period": {
                "requested_start": COMMON_SAMPLE_REQUESTED_START,
                "actual_start": paired.index.min(),
                "actual_end": paired.index.max(),
                "n_obs": len(paired),
                "description": "All 13 paired BH/VT return vectors on identical US trading dates.",
                "rows": common_rows,
                "summary": common_summary,
                "paired_returns_artifact": str(RETURNS_PATH.relative_to(SCRIPT_DIR)),
                "paired_returns_sha256": sha256_file(RETURNS_PATH),
            },
        },
        "inference": {
            "primary": primary,
            "block_length_sensitivity": sensitivity,
            "excluded_legacy_test": (
                "No iid one-sample t-test across 13 markets; markets share crisis dates and VIX signal."
            ),
            "per_market_wording": "Per-market positive delta MDD is descriptive, not individual significance.",
        },
        "decision": decision,
        "source_bindings": _source_bindings(),
        "artifacts": {
            "table5_rows": TABLE5_PATH.name,
            "common_rows": COMMON_PATH.name,
            "figure_data": FIGURE_DATA_PATH.name,
            "figure_png": FIGURE_PATH.name,
            "paired_returns": str(RETURNS_PATH.relative_to(SCRIPT_DIR)),
            "sha256": {
                TABLE5_PATH.name: sha256_file(TABLE5_PATH),
                COMMON_PATH.name: sha256_file(COMMON_PATH),
                FIGURE_DATA_PATH.name: sha256_file(FIGURE_DATA_PATH),
                FIGURE_PATH.name: sha256_file(FIGURE_PATH),
                str(RETURNS_PATH.relative_to(SCRIPT_DIR)): sha256_file(RETURNS_PATH),
            },
        },
        "references": REFERENCES,
        "related_experiments": {
            "K1178": "legacy mixed-vintage comparison; not reused as canonical data",
            "K1192": "monthly VT / 252-day MDD-bootstrap precedent; mapping bug not copied",
            "K1376": "MDD-bootstrap performance precedent; independent-asset resampling not copied",
        },
        "limitations": [
            "MDD is path-dependent; the stationary-bootstrap CI remains sensitive to block length.",
            "The analysis is descriptive and does not identify a causal insurance-pricing mechanism.",
            "One common US VIX signal may proxy global crises rather than locally priced volatility.",
            "Results are frozen to the 2026-03-31 manuscript sample and do not use later observations.",
        ],
    }
    atomic_write_json(RESULTS_PATH, results)
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Fetch and pin data only when no snapshot exists.",
    )
    parser.add_argument(
        "--force-refresh-data",
        action="store_true",
        help="Explicitly replace an existing pinned snapshot.",
    )
    parser.add_argument("--primary-reps", type=int, default=PRIMARY_BOOTSTRAP_REPS)
    parser.add_argument("--sensitivity-reps", type=int, default=SENSITIVITY_REPS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.primary_reps < 1_000 or args.sensitivity_reps < 1_000:
        raise ValueError("all bootstrap configurations require at least 1,000 replications")
    if args.force_refresh_data:
        fetch_snapshot(force=True)
    elif args.refresh_data:
        fetch_snapshot(force=False)
    results = run_experiment(
        primary_reps=args.primary_reps,
        sensitivity_reps=args.sensitivity_reps,
    )
    summary = results["samples"]["inception_aware"]["summary"]
    ci = results["inference"]["primary"]["average_delta_mdd_pp"]
    print(
        f"{EXPERIMENT_ID} complete: n_mdd={summary['n_mdd_improved']}/13, "
        f"avg_delta_mdd={summary['average_delta_mdd_pp']:.2f} pp, "
        f"joint {CI_LEVEL:.0%} CI=[{ci['lower']:.2f}, {ci['upper']:.2f}], "
        f"kill={results['decision']['kill_triggered']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
