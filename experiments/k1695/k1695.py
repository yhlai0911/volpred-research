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

2026-07-15 EXPOSURE CORRECTION
------------------------------
The first run of this experiment reported the raw MDD difference (VT minus BH) as
evidence of international drawdown protection: +12.61 pp on the common sample,
+27.50 pp inception-aware, positive in 13/13 markets, and a pre-registered kill gate
that the result "survived".  Every one of those numbers is arithmetically correct and
none of them supports the claim that was built on top of them.

12/VIX holds an average of ~73% equity.  Its realized volatility is 0.52-0.68x
buy-and-hold in all 13 markets of both samples -- far outside the 20% band inside which a
raw max drawdown is comparable at all (``.claude/rules/experiments.md``).  Raw MDD is not
scale-invariant: anyone who simply holds less equity draws down less.  That is taking
less risk, not timing risk.

This version therefore:

* routes every drawdown comparison through the canonical
  ``volpred.stats.drawdown.compare_max_drawdown``, which emits the realized-vol ratio,
  the exposure-mismatch flag, and the exposure-matched gap
  MDD(VT) - MDD(lambda * BH) with lambda chosen so the benchmark carries VT's own
  realized volatility;
* keeps every raw number (they are real computations, and the correction has to be
  auditable against what was published) but never lets one stand alone as a claim;
* tests the exposure-matched gap against an EXACT circular-shift randomization null --
  all calendar-month phases of the same 12/VIX weight path, which preserves the weight
  values and their autocorrelation exactly and destroys only their alignment with
  returns.  A positive exposure-matched gap is necessary but NOT sufficient: matching
  unconditional volatility does not match the volatility PATH, so the gap must be read
  against its own null, not against zero;
* recomputes the joint stationary-bootstrap CI and the kill gate on the exposure-matched
  statistic, and reports the original raw-statistic gate beside it as the mis-specified
  pre-registration it was; and
* adds a no-timing reference strategy (constant equity weight equal to VT's own average),
  which reproduces most of the raw MDD "improvement" while knowing nothing about VIX.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

# The repo owns exactly one honest drawdown comparison.  Re-implementing it here is how
# the original claim got made in the first place.
from volpred.stats.drawdown import (  # noqa: E402
    annualized_volatility as vp_annualized_volatility,
    compare_max_drawdown,
    max_drawdown as vp_max_drawdown,
)


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
EXPOSURE_FIGURE_PATH = SCRIPT_DIR / "figure_exposure_matched.png"
NULL_GAPS_PATH = SCRIPT_DIR / "circular_shift_null_gaps.csv"

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

# Exposure correction (2026-07-15).
TRADING_DAYS = 252
#: alpha for the Holm-corrected family of 13 per-market circular-shift tests
NULL_ALPHA = 0.10
#: the fast scenario simulator must reproduce the canonical scalar simulator exactly
SIMULATOR_EQUIVALENCE_TOL = 1e-12

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


def annualized_vol_by_column(returns: np.ndarray) -> np.ndarray:
    """Column-wise annualized volatility, matching ``vp_annualized_volatility``."""
    if returns.ndim != 2:
        raise ValueError("returns must be a 2-D date x market matrix")
    return np.std(returns, axis=0, ddof=1) * math.sqrt(TRADING_DAYS)


def exposure_matched_mdd_by_column(
    strategy: np.ndarray, benchmark: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized twin of ``volpred.stats.drawdown.compare_max_drawdown``.

    Returns ``(lambda, MDD(lambda * benchmark))`` per column, where lambda makes the
    benchmark carry the strategy's own realized volatility.  Equivalence with the
    canonical scalar helper is asserted at run time -- see
    :func:`assert_vectorized_matches_canonical`.  It exists only because the null and the
    bootstrap need this statistic tens of thousands of times.
    """
    strategy_vol = annualized_vol_by_column(strategy)
    benchmark_vol = annualized_vol_by_column(benchmark)
    lam = np.where(benchmark_vol > 0.0, strategy_vol / benchmark_vol, np.nan)
    scaled = lam * benchmark
    if np.nanmin(scaled) <= -1.0:
        raise ValueError("exposure-matched benchmark implies wealth <= 0; MDD undefined")
    return lam, max_drawdown_by_column(scaled)


def assert_vectorized_matches_canonical(
    strategy: np.ndarray, benchmark: np.ndarray, *, tickers: list[str]
) -> None:
    """Fail closed unless the fast path reproduces the canonical helper exactly.

    The whole correction rests on the exposure-matched gap.  A fast re-implementation of
    it that silently disagreed with ``volpred.stats.drawdown`` would just be the original
    bug wearing a new hat.
    """
    lam_vec, matched_vec = exposure_matched_mdd_by_column(strategy, benchmark)
    mdd_vec = max_drawdown_by_column(strategy)
    for column, ticker in enumerate(tickers):
        canonical = compare_max_drawdown(strategy[:, column], benchmark[:, column])
        checks = {
            "matched_lambda": (lam_vec[column], canonical.matched_lambda),
            "matched_benchmark_mdd": (matched_vec[column], canonical.matched_benchmark_mdd),
            "strategy_mdd": (mdd_vec[column], canonical.strategy_mdd),
        }
        for name, (fast, slow) in checks.items():
            if not math.isclose(float(fast), float(slow), rel_tol=0.0, abs_tol=SIMULATOR_EQUIVALENCE_TOL):
                raise AssertionError(
                    f"{ticker}: vectorized {name}={fast!r} != canonical {slow!r}"
                )


def joint_mdd_bootstrap(
    paired_returns: pd.DataFrame,
    market_order: Iterable[str],
    *,
    reps: int,
    mean_block: int,
    seed: int,
    ci_level: float = CI_LEVEL,
) -> dict[str, Any]:
    """Joint stationary bootstrap of BOTH the raw and the exposure-matched delta MDD.

    Both statistics are computed inside the SAME resample, from the same shared date
    index, so the raw CI and the exposure-matched CI are directly comparable and the
    difference between them is entirely the statistic, not the resampling.  Lambda is
    re-estimated inside each replication: it is part of the statistic, not a constant.
    """
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
    avg_matched = np.empty(reps, dtype=float)
    all_positive = np.empty(reps, dtype=bool)
    all_matched_positive = np.empty(reps, dtype=bool)
    market_delta = np.empty((reps, len(markets)), dtype=float)
    market_matched = np.empty((reps, len(markets)), dtype=float)
    for replication in range(reps):
        indices = stationary_bootstrap_indices(len(panel), mean_block, rng)
        # One shared index simultaneously resamples all 26 paired columns.
        bh_b = bh[indices]
        vt_b = vt[indices]
        bh_mdd = max_drawdown_by_column(bh_b)
        vt_mdd = max_drawdown_by_column(vt_b)
        _, matched_mdd = exposure_matched_mdd_by_column(vt_b, bh_b)
        delta_pp = (vt_mdd - bh_mdd) * 100.0
        matched_pp = (vt_mdd - matched_mdd) * 100.0
        market_delta[replication] = delta_pp
        market_matched[replication] = matched_pp
        avg_delta[replication] = float(delta_pp.mean())
        avg_matched[replication] = float(matched_pp.mean())
        all_positive[replication] = bool(np.all(delta_pp > 0.0))
        all_matched_positive[replication] = bool(np.all(matched_pp > 0.0))

    alpha = (1.0 - ci_level) / 2.0

    def _interval(draws: np.ndarray) -> dict[str, Any]:
        lower, upper = np.quantile(draws, [alpha, 1.0 - alpha])
        return {
            "lower": lower,
            "median": float(np.median(draws)),
            "upper": upper,
            "mean": float(draws.mean()),
            "probability_le_zero": float(np.mean(draws <= 0.0)),
        }

    per_market_ci: dict[str, Any] = {}
    per_market_matched_ci: dict[str, Any] = {}
    for column_index, ticker in enumerate(markets):
        lo, hi = np.quantile(market_delta[:, column_index], [alpha, 1.0 - alpha])
        per_market_ci[ticker] = {
            "lower_pp": lo,
            "median_pp": float(np.median(market_delta[:, column_index])),
            "upper_pp": hi,
        }
        mlo, mhi = np.quantile(market_matched[:, column_index], [alpha, 1.0 - alpha])
        per_market_matched_ci[ticker] = {
            "lower_pp": mlo,
            "median_pp": float(np.median(market_matched[:, column_index])),
            "upper_pp": mhi,
        }
    return {
        "n_obs": len(panel),
        "reps": reps,
        "seed": seed,
        "method": "joint circular stationary bootstrap; shared date indices across 13 paired BH/VT vectors",
        "mean_block_days": mean_block,
        "ci_level": ci_level,
        "statistic_note": (
            "average_delta_mdd_pp is the RAW statistic (VT minus BH) and is not "
            "scale-invariant; average_exposure_matched_delta_mdd_pp rescales BH to VT's own "
            "realized volatility inside every replication and is the reportable one."
        ),
        "average_delta_mdd_pp": _interval(avg_delta),
        "average_exposure_matched_delta_mdd_pp": _interval(avg_matched),
        "probability_all_13_positive": float(all_positive.mean()),
        "probability_all_13_exposure_matched_positive": float(all_matched_positive.mean()),
        "per_market_delta_mdd_ci": per_market_ci,
        "per_market_exposure_matched_delta_mdd_ci": per_market_matched_ci,
    }


# ---------------------------------------------------------------------------
# Exposure correction: circular-shift randomization null
# ---------------------------------------------------------------------------
def monthly_signal_over_span(vix_level: pd.Series, periods: pd.PeriodIndex) -> pd.Series:
    """The lagged 12/VIX monthly weight, restricted to the calendar months of a sample.

    Same construction as :func:`build_monthly_lagged_weights` (month m gets the signal
    formed at the end of month m-1); this variant just exposes the monthly vector so it
    can be circularly rotated.  Rotating in calendar-month space keeps the phase shift
    identical across all 13 markets even when their samples start on different dates.
    """
    vix = vix_level.dropna().sort_index()
    monthly_vix = vix.groupby(vix.index.to_period("M")).last()
    full_periods = pd.period_range(monthly_vix.index.min(), monthly_vix.index.max() + 1, freq="M")
    unlagged = (VT_NUMERATOR / monthly_vix).clip(lower=0.0, upper=MAX_EQUITY_WEIGHT).reindex(
        full_periods
    )
    lagged = unlagged.shift(1)
    signal = lagged.reindex(periods)
    if signal.isna().any():
        missing = signal.index[signal.isna()].tolist()
        raise ValueError(f"monthly signal has no value for {missing[:3]}")
    return signal.astype(float)


def month_start_mask(dates: pd.DatetimeIndex) -> np.ndarray:
    """True on the first observed trading date of each calendar month (rebalance days)."""
    periods = pd.DatetimeIndex(dates).to_period("M")
    mask = np.empty(len(periods), dtype=bool)
    mask[0] = True
    mask[1:] = periods[1:] != periods[:-1]
    return mask


def simulate_monthly_hold_scenarios(
    equity: np.ndarray,
    cash: np.ndarray,
    targets: np.ndarray,
    rebalance: np.ndarray,
    *,
    cost_rate: float = TRANSACTION_COST,
) -> np.ndarray:
    """Vectorized twin of :func:`simulate_monthly_hold`, run over R weight scenarios at once.

    ``targets`` is (T, R): one column per circular shift.  Equivalence with the scalar
    simulator is asserted against the observed weight path before any null is trusted.
    """
    n_obs, n_scen = targets.shape
    if equity.shape != (n_obs,) or cash.shape != (n_obs,) or rebalance.shape != (n_obs,):
        raise ValueError("scenario simulator received misaligned inputs")

    equity_value = targets[0] * 1.0
    cash_value = 1.0 - targets[0]
    nav = np.ones(n_scen, dtype=float)
    out = np.empty((n_obs, n_scen), dtype=float)
    for t in range(n_obs):
        nav_before = nav.copy()
        if t > 0:
            if rebalance[t]:
                pretrade = equity_value / nav
                turnover = np.abs(targets[t] - pretrade)
                nav_after_cost = nav - cost_rate * turnover * nav
                equity_value = targets[t] * nav_after_cost
                cash_value = (1.0 - targets[t]) * nav_after_cost
        equity_value = equity_value * (1.0 + equity[t])
        cash_value = cash_value * (1.0 + cash[t])
        nav = equity_value + cash_value
        out[t] = nav / nav_before - 1.0
    return out


@dataclass
class MarketPath:
    """Everything the null needs to re-simulate one market on its own observed dates."""

    ticker: str
    dates: pd.DatetimeIndex
    equity: np.ndarray
    cash: np.ndarray
    observed_targets: np.ndarray
    rebalance: np.ndarray
    bh_returns: np.ndarray
    vt_returns: np.ndarray


def _shifted_target_matrix(
    signal: pd.Series, dates: pd.DatetimeIndex, n_shifts: int
) -> np.ndarray:
    """(T, n_shifts) daily targets: column s rolls THIS MARKET'S OWN month vector by s months.

    Rolling each market's own months -- rather than a shared union-span vector -- is what
    makes the null an exact permutation of the weights that market actually experienced.
    Rolling a union vector would have fed INDA and MCHI (which start in 2012 and 2011)
    weights from calendar months they were never trading in, including the 2008 crisis
    lows; that inflates their weight dispersion and therefore inflates the null.

    The shift index s is still SHARED across markets, so the calendar displacement is
    common and the cross-market dependence survives.  Markets with shorter histories wrap
    sooner (s mod len), which just means their null draws repeat with period len.
    """
    values = signal.to_numpy(dtype=float)
    n_months = len(values)
    periods = signal.index
    lookup = {period: index for index, period in enumerate(periods)}
    row_of_date = np.array([lookup[period] for period in pd.DatetimeIndex(dates).to_period("M")])
    rolled = np.empty((n_shifts, n_months), dtype=float)
    for shift in range(n_shifts):
        rolled[shift] = np.roll(values, shift % n_months)
    return rolled[:, row_of_date].T  # (T, n_shifts)


def circular_shift_null(
    paths: list[MarketPath],
    vix_level: pd.Series,
    *,
    sample_name: str,
) -> tuple[dict[str, Any], np.ndarray]:
    """Exact randomization test of the exposure-matched gap over all calendar-month phases.

    Under the null "the 12/VIX weight path knows nothing about WHEN returns are bad",
    every phase of that path is equally likely.  A circular shift preserves the weight
    values exactly (it is a permutation of time) and preserves their autocorrelation; it
    destroys only the alignment with returns.  Shift 0 is the observed path and is part of
    the reference set, so p = #{gap_s >= gap_observed} / (n_shifts + 1) can never be zero.

    The same shift is applied to every market simultaneously, so the null preserves the
    cross-market dependence that makes 13/13 counts look more impressive than they are.

    Stated assumption: this requires the weight process to be approximately circularly
    stationary.  12/VIX is persistent but not exactly stationary, so this is a strong
    diagnostic, not an exact size-alpha test.
    """
    span = pd.period_range(
        min(path.dates.min() for path in paths).to_period("M"),
        max(path.dates.max() for path in paths).to_period("M"),
        freq="M",
    )
    n_shifts = len(span)

    raw_by_market = np.empty((n_shifts, len(paths)), dtype=float)
    matched_by_market = np.empty((n_shifts, len(paths)), dtype=float)
    vol_ratio_by_market = np.empty((n_shifts, len(paths)), dtype=float)
    own_months: dict[str, int] = {}
    for column, path in enumerate(paths):
        # Each market rolls the months IT actually traded -- see _shifted_target_matrix.
        market_months = pd.PeriodIndex(path.dates.to_period("M").unique(), freq="M")
        signal = monthly_signal_over_span(vix_level, market_months)
        own_months[path.ticker] = len(market_months)
        targets = _shifted_target_matrix(signal, path.dates, n_shifts)
        if not np.allclose(
            targets[:, 0], path.observed_targets, rtol=0.0, atol=SIMULATOR_EQUIVALENCE_TOL
        ):
            raise AssertionError(
                f"{path.ticker}: shift-0 targets do not reproduce the observed weight path"
            )
        observed_weights = np.sort(signal.to_numpy(dtype=float))
        for shift in (1, n_shifts // 2):
            rolled_weights = np.sort(np.unique(targets[:, shift % n_shifts]))
            if not np.isin(rolled_weights, observed_weights).all():
                raise AssertionError(
                    f"{path.ticker}: shift {shift} introduced weights this market never held"
                )
        vt = simulate_monthly_hold_scenarios(path.equity, path.cash, targets, path.rebalance)
        if not np.allclose(
            vt[:, 0], path.vt_returns, rtol=0.0, atol=SIMULATOR_EQUIVALENCE_TOL
        ):
            raise AssertionError(
                f"{path.ticker}: scenario simulator does not reproduce the canonical VT path"
            )
        benchmark = np.repeat(path.bh_returns[:, None], n_shifts, axis=1)
        vt_mdd = max_drawdown_by_column(vt)
        bh_mdd = max_drawdown_by_column(benchmark)
        lam, matched_mdd = exposure_matched_mdd_by_column(vt, benchmark)
        raw_by_market[:, column] = (vt_mdd - bh_mdd) * 100.0
        matched_by_market[:, column] = (vt_mdd - matched_mdd) * 100.0
        vol_ratio_by_market[:, column] = lam

    joint_matched = matched_by_market.mean(axis=1)
    joint_raw = raw_by_market.mean(axis=1)
    joint_vol_ratio = vol_ratio_by_market.mean(axis=1)

    def _one_sided(draws: np.ndarray, observed: float) -> dict[str, Any]:
        # The shift group is enumerated exhaustively and contains the identity (shift 0),
        # so the exact randomization p-value is #{T_s >= T_obs} / |G|.  The Monte-Carlo
        # convention (B + 1 in the denominator) belongs to SAMPLED reference sets; using it
        # here would shave ~0.6% off p in the anti-conservative direction.  Reported too,
        # only so this run can be compared with K1265b, which used that convention.
        n_ge = int((draws >= observed).sum())
        return {
            "observed_pp": float(observed),
            "null_mean_pp": float(draws.mean()),
            "null_p50_pp": float(np.percentile(draws, 50)),
            "null_p95_pp": float(np.percentile(draws, 95)),
            "n_null_ge_observed": n_ge,
            "p_one_sided": float(n_ge / len(draws)),
            "p_one_sided_monte_carlo_convention": float(n_ge / (len(draws) + 1)),
        }

    per_market: dict[str, Any] = {}
    p_values: dict[str, float] = {}
    for column, path in enumerate(paths):
        draws = matched_by_market[:, column]
        detail = _one_sided(draws, float(draws[0]))
        detail["raw_observed_pp"] = float(raw_by_market[0, column])
        detail["raw_null_mean_pp"] = float(raw_by_market[:, column].mean())
        per_market[path.ticker] = detail
        p_values[path.ticker] = detail["p_one_sided"]

    holm_result = holm_correction(p_values, alpha=NULL_ALPHA)
    survivors = [ticker for ticker, item in holm_result.items() if item["reject"]]

    # WHY THE RAW STATISTIC CAN REJECT THIS NULL WHILE THE MATCHED ONE CANNOT.
    # Measured, not asserted: where does the OBSERVED phase's realized volatility sit among
    # all phases?  12/VIX conditions on lagged VIX, and VIX does forecast volatility -- so
    # the observed phase de-levers into genuinely turbulent months and ends up with a lower
    # realized vol than a randomly-phased version of the same weight path.  The raw MDD gap
    # rewards exactly that.  It is a real property of the signal, and it is a property about
    # RISK REDUCTION, not about drawing down less than a benchmark carrying the same risk.
    observed_vol_ratio = float(joint_vol_ratio[0])
    n_le = int((joint_vol_ratio <= observed_vol_ratio).sum())
    exposure_of_the_null = {
        "observed_vol_ratio": observed_vol_ratio,
        "null_mean_vol_ratio": float(joint_vol_ratio.mean()),
        "null_min_vol_ratio": float(joint_vol_ratio.min()),
        "null_max_vol_ratio": float(joint_vol_ratio.max()),
        "observed_rank_among_phases": n_le,
        "observed_percentile": float(n_le / len(joint_vol_ratio)),
        "interpretation": (
            "The observed phase realizes LOWER volatility than a randomly re-phased copy of the "
            "same weight path. That is real: VIX forecasts volatility, so 12/VIX de-levers into "
            "genuinely turbulent months. It is also exactly what the RAW MDD gap rewards, which is "
            "why the raw statistic can reject this null while the exposure-matched one cannot. "
            "Lowering realized risk is not the same as drawing down less than a benchmark carrying "
            "the same risk -- and the paper's contribution claimed the latter."
        ),
    }

    result = {
        "sample": sample_name,
        "test": "exact circular-shift randomization over all calendar-month phases of the 12/VIX weight path",
        "statistic": "exposure-matched delta MDD = MDD(VT) - MDD(lambda * BH), lambda = vol(VT)/vol(BH)",
        "n_shifts": n_shifts,
        "shift_unit": "calendar month",
        "month_span": f"{span.min()}..{span.max()}",
        "months_per_market": own_months,
        "shift_group_note": (
            "Each market circularly rolls the months IT actually traded, by a SHARED shift index. "
            "Every null draw is therefore an exact permutation of the weights that market really "
            "held, while the calendar displacement stays common across markets. Markets with "
            "shorter histories wrap sooner (s mod own_months), so their draws repeat with that "
            "period."
        ),
        "seed": None,
        "deterministic": True,
        "randomization_note": (
            "Exhaustive over the shift group; no sampling, so no seed is required. "
            "Shift 0 is the observed path and is included in the reference set."
        ),
        "exposure_of_the_null": exposure_of_the_null,
        "joint_exposure_matched": _one_sided(joint_matched, float(joint_matched[0])),
        "joint_raw_delta_mdd": _one_sided(joint_raw, float(joint_raw[0])),
        "per_market": per_market,
        "holm": {
            "alpha": NULL_ALPHA,
            "family_size": len(p_values),
            "per_market": holm_result,
            "n_survivors": len(survivors),
            "survivors": survivors,
        },
        "stationarity_caveat": (
            "Circular-shift randomization assumes the weight process is approximately "
            "circularly stationary. 12/VIX is persistent but not exactly stationary, so this "
            "is a strong diagnostic rather than an exact size-alpha test."
        ),
    }
    return result, matched_by_market


def holm_correction(p_values: dict[str, float], *, alpha: float) -> dict[str, dict[str, Any]]:
    """Holm step-down over a family of one-sided p-values."""
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    family = len(ordered)
    out: dict[str, dict[str, Any]] = {}
    still_rejecting = True
    for rank, (key, p_value) in enumerate(ordered):
        threshold = alpha / (family - rank)
        if p_value > threshold:
            still_rejecting = False
        out[key] = {
            "p_one_sided": p_value,
            "holm_threshold": threshold,
            "reject": bool(still_rejecting),
        }
    return out


def constant_weight_reference(paths: list[MarketPath]) -> dict[str, Any]:
    """A strategy that de-levers to VT's own average weight and never looks at VIX.

    It is the null hypothesis made concrete.  If it reproduces most of VT's raw MDD
    "improvement" while scoring a ~zero exposure-matched gap, then the raw improvement was
    never about volatility timing.
    """
    rows: dict[str, Any] = {}
    raw_gaps: list[float] = []
    matched_gaps: list[float] = []
    for path in paths:
        constant = float(path.observed_targets.mean())
        targets = np.full((len(path.dates), 1), constant, dtype=float)
        constant_returns = simulate_monthly_hold_scenarios(
            path.equity, path.cash, targets, path.rebalance
        )[:, 0]
        comparison = compare_max_drawdown(constant_returns, path.bh_returns)
        rows[path.ticker] = {
            "constant_equity_weight": constant,
            "raw_delta_mdd_pp": comparison.raw_mdd_improvement * 100.0,
            "exposure_matched_delta_mdd_pp": comparison.exposure_matched_gap * 100.0,
            "vol_ratio": comparison.vol_ratio,
        }
        raw_gaps.append(comparison.raw_mdd_improvement * 100.0)
        matched_gaps.append(comparison.exposure_matched_gap * 100.0)
    return {
        "description": (
            "Constant equity weight equal to each market's own average 12/VIX target, "
            "same SHY cash sleeve, same monthly rebalance, same 10 bp cost. Knows nothing "
            "about VIX."
        ),
        "average_raw_delta_mdd_pp": float(np.mean(raw_gaps)),
        "average_exposure_matched_delta_mdd_pp": float(np.mean(matched_gaps)),
        "n_raw_improved": int(np.sum(np.array(raw_gaps) > 0.0)),
        "per_market": rows,
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
) -> tuple[dict[str, Any], pd.DataFrame, MarketPath]:
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

    # The single honest drawdown comparison in this file.  Everything the paper says about
    # drawdown protection has to survive this object, not the raw difference above it.
    drawdown = compare_max_drawdown(
        comparison["vt_return"].to_numpy(dtype=float),
        comparison["bh"].to_numpy(dtype=float),
    )

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
        # RAW. Real arithmetic, but not scale-invariant: see .exposure below before quoting it.
        "delta_mdd_pp": (vt_metrics["max_drawdown"] - bh_metrics["max_drawdown"]) * 100.0,
        "exposure": {
            "vt_realized_vol": drawdown.strategy_vol,
            "bh_realized_vol": drawdown.benchmark_vol,
            "vol_ratio": drawdown.vol_ratio,
            "exposure_mismatch": drawdown.exposure_mismatch,
            "raw_mdd_improvement_is_reportable_alone": drawdown.raw_mdd_improvement_is_reportable_alone,
            "matched_lambda": drawdown.matched_lambda,
            "matched_benchmark_mdd": drawdown.matched_benchmark_mdd,
            "raw_delta_mdd_pp": drawdown.raw_mdd_improvement * 100.0,
            "exposure_matched_delta_mdd_pp": drawdown.exposure_matched_gap * 100.0,
            "vt_mdd_per_vol": drawdown.strategy_mdd_per_vol,
            "bh_mdd_per_vol": drawdown.benchmark_mdd_per_vol,
            "warnings": list(drawdown.warnings),
            "source": "volpred.stats.drawdown.compare_max_drawdown",
        },
        "exposure_matched_delta_mdd_pp": drawdown.exposure_matched_gap * 100.0,
        "annual_return_cost_pp": (vt_metrics["cagr"] - bh_metrics["cagr"]) * 100.0,
        "vix_sensitivity_pearson_r": float(vix_r),
        "vix_sensitivity_p": float(vix_p),
        "average_target_equity_weight": float(comparison["target_weight"].mean()),
        "annualized_turnover": float(comparison["turnover"].sum() / (len(comparison) / 252.0)),
        "total_transaction_cost_pct": float(comparison["transaction_cost"].sum() * 100.0),
        "n_rebalances_with_cost": int((comparison["transaction_cost"] > 0).sum()),
    }
    cash_on_path = aligned["shy"].reindex(comparison.index)
    if cash_on_path.isna().any():
        raise ValueError(f"{ticker}: cash sleeve has gaps on the evaluated path")
    path = MarketPath(
        ticker=ticker,
        dates=comparison.index,
        equity=comparison["bh"].to_numpy(dtype=float),
        cash=cash_on_path.to_numpy(dtype=float),
        observed_targets=comparison["target_weight"].to_numpy(dtype=float),
        rebalance=month_start_mask(comparison.index),
        bh_returns=comparison["bh"].to_numpy(dtype=float),
        vt_returns=comparison["vt_return"].to_numpy(dtype=float),
    )
    comparison = comparison.rename(
        columns={"bh": f"{ticker}_bh", "vt_return": f"{ticker}_vt"}
    )
    return result, comparison, path


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    delta_mdd = np.array([row["delta_mdd_pp"] for row in rows], dtype=float)
    matched_mdd = np.array([row["exposure_matched_delta_mdd_pp"] for row in rows], dtype=float)
    vol_ratio = np.array([row["exposure"]["vol_ratio"] for row in rows], dtype=float)
    mismatch = np.array([row["exposure"]["exposure_mismatch"] for row in rows], dtype=bool)
    delta_sharpe = np.array([row["delta_sharpe"] for row in rows], dtype=float)
    annual_cost = np.array([row["annual_return_cost_pp"] for row in rows], dtype=float)
    vix_sensitivity = np.array([row["vix_sensitivity_pearson_r"] for row in rows], dtype=float)
    pearson = stats.pearsonr(vix_sensitivity, delta_mdd)
    spearman = stats.spearmanr(vix_sensitivity, delta_mdd)
    dm = [row["delta_mdd_pp"] for row in rows if row["region"] == "DM"]
    em = [row["delta_mdd_pp"] for row in rows if row["region"] == "EM"]
    dm_matched = [row["exposure_matched_delta_mdd_pp"] for row in rows if row["region"] == "DM"]
    em_matched = [row["exposure_matched_delta_mdd_pp"] for row in rows if row["region"] == "EM"]
    return {
        "n_markets": len(rows),
        "n_mdd_improved": int(np.sum(delta_mdd > 0)),
        "n_exposure_matched_improved": int(np.sum(matched_mdd > 0)),
        "n_exposure_mismatch": int(mismatch.sum()),
        "n_sharpe_improved": int(np.sum(delta_sharpe > 0)),
        "average_delta_mdd_pp": float(delta_mdd.mean()),
        "average_exposure_matched_delta_mdd_pp": float(matched_mdd.mean()),
        "average_vol_ratio": float(vol_ratio.mean()),
        "min_vol_ratio": float(vol_ratio.min()),
        "max_vol_ratio": float(vol_ratio.max()),
        "average_delta_sharpe": float(delta_sharpe.mean()),
        "average_annual_return_cost_pp": float(annual_cost.mean()),
        "dm_average_delta_mdd_pp": float(np.mean(dm)),
        "em_average_delta_mdd_pp": float(np.mean(em)),
        "dm_average_exposure_matched_delta_mdd_pp": float(np.mean(dm_matched)),
        "em_average_exposure_matched_delta_mdd_pp": float(np.mean(em_matched)),
        "raw_delta_mdd_reportable_alone": bool(not mismatch.any()),
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
                "vol_ratio_vt_over_bh": row["exposure"]["vol_ratio"],
                "exposure_mismatch": row["exposure"]["exposure_mismatch"],
                "matched_lambda": row["exposure"]["matched_lambda"],
                "matched_bh_mdd_pct": row["exposure"]["matched_benchmark_mdd"] * 100.0,
                "exposure_matched_delta_mdd_pp": row["exposure_matched_delta_mdd_pp"],
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


def _render_exposure_figure(
    rows: list[dict[str, Any]],
    null_result: dict[str, Any],
    null_draws: np.ndarray,
    no_timing: dict[str, Any],
) -> None:
    """The correction in one picture: the raw bars vanish once exposure is matched."""
    tickers = [row["ticker"] for row in rows]
    raw = np.array([row["delta_mdd_pp"] for row in rows], dtype=float)
    matched = np.array([row["exposure_matched_delta_mdd_pp"] for row in rows], dtype=float)
    constant_raw = np.array(
        [no_timing["per_market"][ticker]["raw_delta_mdd_pp"] for ticker in tickers], dtype=float
    )
    order = np.argsort(-raw)

    fig, (left, right) = plt.subplots(1, 2, figsize=(14.0, 6.4), dpi=150)

    positions = np.arange(len(tickers))
    width = 0.28
    left.bar(
        positions - width,
        raw[order],
        width,
        color="#94a3b8",
        label="raw ΔMDD (VT − BH)",
    )
    left.bar(
        positions,
        constant_raw[order],
        width,
        color="#f59e0b",
        label="raw ΔMDD of a constant-weight strategy (no VIX)",
    )
    left.bar(
        positions + width,
        matched[order],
        width,
        color="#2563eb",
        label="exposure-matched ΔMDD (same realized vol)",
    )
    left.axhline(0.0, color="black", linewidth=0.9)
    left.set_xticks(positions)
    left.set_xticklabels([tickers[index] for index in order], rotation=45, ha="right")
    left.set_ylabel("ΔMDD (percentage points; positive = shallower than benchmark)")
    left.set_title(
        "A strategy that never looks at VIX buys most of the raw 'protection'",
        fontsize=11,
    )
    left.legend(fontsize=8, loc="upper right")
    left.grid(axis="y", alpha=0.25)

    joint = null_draws.mean(axis=1)
    observed = float(joint[0])
    p_value = null_result["joint_exposure_matched"]["p_one_sided"]
    right.hist(joint, bins=40, color="#cbd5e1", edgecolor="#94a3b8")
    right.axvline(
        observed,
        color="#dc2626",
        linewidth=2.0,
        label=f"observed = {observed:+.2f} pp (p = {p_value:.3f})",
    )
    right.axvline(0.0, color="black", linewidth=0.9, linestyle=":")
    right.set_xlabel("average exposure-matched ΔMDD across 13 markets (pp)")
    right.set_ylabel(f"count over all {null_result['n_shifts']} calendar-month phases")
    right.set_title(
        "Observed 12/VIX timing vs every other phase of the same weight path",
        fontsize=11,
    )
    right.legend(fontsize=9)
    right.grid(axis="y", alpha=0.25)

    fig.suptitle(
        "K1695 correction: the 13-market drawdown result is an exposure artifact",
        fontsize=13,
    )
    fig.tight_layout()
    fig.savefig(EXPOSURE_FIGURE_PATH, bbox_inches="tight")
    plt.close(fig)


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
        "exposure_figure": {
            "data_artifact": NULL_GAPS_PATH.name,
            "image_artifact": EXPOSURE_FIGURE_PATH.name,
            "json_path": "$.inference.circular_shift_null.common_period",
        },
        "abstract_average_delta_mdd_RAW_DO_NOT_QUOTE_ALONE": (
            "$.samples.inception_aware.summary.average_delta_mdd_pp"
        ),
        "abstract_average_delta_mdd": (
            "$.samples.inception_aware.summary.average_exposure_matched_delta_mdd_pp"
        ),
        "abstract_average_delta_sharpe": "$.samples.inception_aware.summary.average_delta_sharpe",
        "abstract_annual_return_cost": "$.samples.inception_aware.summary.average_annual_return_cost_pp",
        "joint_bootstrap_ci": "$.inference.primary.average_exposure_matched_delta_mdd_pp",
        "joint_bootstrap_ci_raw": "$.inference.primary.average_delta_mdd_pp",
        "circular_shift_null_p": (
            "$.inference.circular_shift_null.common_period.joint_exposure_matched.p_one_sided"
        ),
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
    inception_paths: list[MarketPath] = []
    for ticker in MARKETS:
        row, _, path = _run_one_market(
            ticker,
            start=pd.Timestamp(INCEPTION_SAMPLE_START),
            market_return=total_returns[ticker],
            shy_return=shy_return,
            vix_level=vix_level,
            irx_level=irx_level,
        )
        inception_rows.append(row)
        inception_paths.append(path)
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
    common_paths: list[MarketPath] = []
    paired_parts: list[pd.DataFrame] = []
    for ticker in MARKETS:
        row, comparison, path = _run_one_market(
            ticker,
            start=common_start,
            market_return=total_returns[ticker],
            shy_return=shy_return,
            vix_level=vix_level,
            irx_level=irx_level,
            required_dates=common_dates,
        )
        common_rows.append(row)
        common_paths.append(path)
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

    # Fail closed before any null is trusted: the vectorized statistic must equal the
    # canonical one on the observed data, market by market.
    assert_vectorized_matches_canonical(
        paired[[f"{ticker}_vt" for ticker in MARKETS]].to_numpy(dtype=float),
        paired[[f"{ticker}_bh" for ticker in MARKETS]].to_numpy(dtype=float),
        tickers=list(MARKETS),
    )

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

    common_null, common_null_draws = circular_shift_null(
        common_paths, vix_level, sample_name="common_period"
    )
    inception_null, _ = circular_shift_null(
        inception_paths, vix_level, sample_name="inception_aware"
    )
    no_timing_reference = {
        "common_period": constant_weight_reference(common_paths),
        "inception_aware": constant_weight_reference(inception_paths),
    }
    null_frame = pd.DataFrame(
        common_null_draws, columns=[f"{ticker}_matched_gap_pp" for ticker in MARKETS]
    )
    null_frame.insert(0, "shift_months", np.arange(len(null_frame)))
    null_frame["joint_average_matched_gap_pp"] = common_null_draws.mean(axis=1)
    atomic_write_csv(null_frame, NULL_GAPS_PATH)

    inception_summary = _summary(inception_rows)
    common_summary = _summary(common_rows)

    raw_ci = primary["average_delta_mdd_pp"]
    matched_ci = primary["average_exposure_matched_delta_mdd_pp"]

    # The rule that was actually pre-registered.  It is reported because it was
    # pre-registered, not because it is valid: it gates on a statistic that is not
    # scale-invariant, so a strategy holding 73% equity passes it by construction.
    raw_kill_triggered = bool(
        inception_summary["n_mdd_improved"] < len(MARKETS)
        or common_summary["n_mdd_improved"] < len(MARKETS)
        or raw_ci["lower"] <= 0.0 <= raw_ci["upper"]
    )
    # The rule that governs the claim.  A positive exposure-matched gap is necessary but NOT
    # sufficient, so the null test -- not the sign, and not the CI -- is the binding condition.
    # Both samples are gated: the abstract quotes the inception-aware average, the
    # pre-registered inference used the common panel.  A claim made from both must hold in both.
    per_sample_verdict: dict[str, Any] = {}
    for name, null_result, summary in (
        ("common_period", common_null, common_summary),
        ("inception_aware", inception_null, inception_summary),
    ):
        joint = null_result["joint_exposure_matched"]
        rejects = bool(
            joint["p_one_sided"] <= NULL_ALPHA and null_result["holm"]["n_survivors"] > 0
        )
        per_sample_verdict[name] = {
            "raw_average_delta_mdd_pp": summary["average_delta_mdd_pp"],
            "exposure_matched_average_delta_mdd_pp": summary[
                "average_exposure_matched_delta_mdd_pp"
            ],
            "n_exposure_matched_positive": summary["n_exposure_matched_improved"],
            "null_p_one_sided": joint["p_one_sided"],
            "null_mean_pp": joint["null_mean_pp"],
            "holm_survivors": null_result["holm"]["n_survivors"],
            "rejects_no_timing_null": rejects,
        }
    ci_excludes_zero = bool(not (matched_ci["lower"] <= 0.0 <= matched_ci["upper"]))
    claim_supported = bool(
        ci_excludes_zero and all(item["rejects_no_timing_null"] for item in per_sample_verdict.values())
    )
    matched_kill_triggered = not claim_supported

    # Every number in the prose below is interpolated from the run, never typed in.  A
    # correction whose narrative can drift away from its own results is not a correction.
    common_verdict = per_sample_verdict["common_period"]
    inception_verdict = per_sample_verdict["inception_aware"]
    common_no_timing = no_timing_reference["common_period"]
    inception_no_timing = no_timing_reference["inception_aware"]

    decision = {
        "kill_triggered": matched_kill_triggered,
        "kill_rule": (
            "The drawdown-protection claim survives ONLY IF (a) the exposure-matched joint-bootstrap "
            f"CI excludes zero, AND (b) BOTH samples reject the circular-shift no-timing null at "
            f"{NULL_ALPHA:.0%} with at least one market surviving Holm. Otherwise the claim is killed."
        ),
        "claim_status": "retracted" if matched_kill_triggered else "supported",
        "exposure_matched_ci_excludes_zero": ci_excludes_zero,
        "per_sample": per_sample_verdict,
        "narrative_implication": (
            "The international drawdown-protection contribution must be withdrawn. The headline raw "
            f"MDD gaps ({inception_verdict['raw_average_delta_mdd_pp']:+.2f} pp inception-aware, "
            f"{common_verdict['raw_average_delta_mdd_pp']:+.2f} pp common, 13/13 positive) measure "
            "de-levering, not volatility timing: a constant-weight strategy that never looks at VIX "
            "reproduces most of them and earns a ~zero exposure-matched gap."
            if matched_kill_triggered
            else "The drawdown-protection result survives an exposure-matched test against its own "
            "circular-shift null in both samples."
        ),
        "what_the_evidence_does_and_does_not_say": [
            "SUPPORTED: the raw 13/13 result is reproduced exactly, and it is an exposure artifact. "
            f"VT holds {common_summary['average_vol_ratio']:.2f}x buy-and-hold realized volatility on "
            f"the common panel (range {common_summary['min_vol_ratio']:.2f}-"
            f"{common_summary['max_vol_ratio']:.2f}x, mismatch flagged in "
            f"{common_summary['n_exposure_mismatch']}/13 markets). A constant-weight strategy with the "
            "same average exposure and no VIX input earns "
            f"{common_no_timing['average_raw_delta_mdd_pp']:+.2f} pp (common) / "
            f"{inception_no_timing['average_raw_delta_mdd_pp']:+.2f} pp (inception-aware) of raw MDD "
            "'improvement' and an exposure-matched gap of "
            f"{common_no_timing['average_exposure_matched_delta_mdd_pp']:+.2f} pp / "
            f"{inception_no_timing['average_exposure_matched_delta_mdd_pp']:+.2f} pp.",
            "SUPPORTED: on the common panel the exposure-matched gap is indistinguishable from the "
            f"no-timing null (observed {common_verdict['exposure_matched_average_delta_mdd_pp']:+.2f} pp "
            f"vs null mean {common_verdict['null_mean_pp']:+.2f} pp, p = "
            f"{common_verdict['null_p_one_sided']:.3f}).",
            "SUPPORTED, AND IT CUTS THE OTHER WAY: 12/VIX really does reduce risk, and the RAW "
            "statistic does reject the phase null on the long sample "
            f"(raw {inception_null['joint_raw_delta_mdd']['observed_pp']:+.2f} pp vs raw-null mean "
            f"{inception_null['joint_raw_delta_mdd']['null_mean_pp']:+.2f} pp, p = "
            f"{inception_null['joint_raw_delta_mdd']['p_one_sided']:.3f}). That rejection is not "
            "noise and it is not dismissed here. Its cause is measured: among all "
            f"{inception_null['n_shifts']} phases of its own weight path, the observed phase realizes "
            f"the LOWEST volatility (rank "
            f"{inception_null['exposure_of_the_null']['observed_rank_among_phases']}/"
            f"{inception_null['n_shifts']}; vol ratio "
            f"{inception_null['exposure_of_the_null']['observed_vol_ratio']:.3f} vs phase-null mean "
            f"{inception_null['exposure_of_the_null']['null_mean_vol_ratio']:.3f}). VIX forecasts "
            "volatility, so 12/VIX de-levers into genuinely turbulent months -- a real property of "
            "the signal. But it is a property about REDUCING RISK, and the raw MDD gap rewards "
            "exactly that. Reducing risk is not the same as drawing down less than a benchmark "
            "carrying the same risk, and the withdrawn contribution claimed the latter. Strip the "
            "risk reduction out and nothing survives.",
            "NOT SUPPORTED: that volatility timing HURTS. The common-sample point estimate is negative "
            "but sits in the middle of its own null; that is a failure to detect an effect, not "
            "evidence of a negative one.",
            "NOT SUPPORTED, AND NOT REFUTED: a modest positive effect on the long sample. The "
            "inception-aware exposure-matched gap is "
            f"{inception_verdict['exposure_matched_average_delta_mdd_pp']:+.2f} pp and positive in "
            f"{inception_verdict['n_exposure_matched_positive']}/13 markets, but it does not reject its "
            f"own null (p = {inception_verdict['null_p_one_sided']:.3f}) and "
            f"{inception_verdict['holm_survivors']}/13 markets survive Holm. That sample's extra years "
            "are the 2008 crisis window; one crisis is not a test.",
        ],
        "superseded_pre_registration": {
            "kill_triggered": raw_kill_triggered,
            "pre_registered_kill_rule": (
                "TRUE if either observed sample has fewer than 13/13 positive MDD improvements "
                "or the primary joint-bootstrap CI for common-sample average delta MDD includes zero"
            ),
            "why_superseded": (
                "The pre-registered rule gates on the RAW delta MDD, which is not scale-invariant. "
                f"12/VIX runs at {common_summary['min_vol_ratio']:.2f}-"
                f"{common_summary['max_vol_ratio']:.2f}x buy-and-hold volatility on the common panel "
                "(13/13 markets flagged), so both of its conditions are satisfied by de-levering "
                "alone -- the constant-weight no-timing strategy passes the same gate 13/13. The gate "
                "could not have failed and therefore never tested the claim. Reported here for "
                "auditability, not as evidence."
            ),
            "status": "mis-specified; not evidence for or against the claim",
        },
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
    _render_exposure_figure(
        common_rows, common_null, common_null_draws, no_timing_reference["common_period"]
    )

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
            "circular_shift_null": {
                "common_period": common_null,
                "inception_aware": inception_null,
            },
            "no_timing_reference": no_timing_reference,
            "primary_statistic": "exposure_matched_delta_mdd_pp",
            "excluded_legacy_test": (
                "No iid one-sample t-test across 13 markets; markets share crisis dates and VIX signal."
            ),
            "per_market_wording": "Per-market positive delta MDD is descriptive, not individual significance.",
            "raw_statistic_status": (
                "Retained for auditability against the published numbers. NOT reportable alone: "
                "realized-vol ratio is outside the 20% band in 13/13 markets, so the raw gap is a "
                "scale artifact of holding less equity."
            ),
            "inference_order": (
                "1. exposure-matched gap vs its own circular-shift null (binding); "
                "2. exposure-matched joint-bootstrap CI (sampling uncertainty); "
                "3. raw delta MDD (audit trail only)."
            ),
        },
        "decision": decision,
        "source_bindings": _source_bindings(),
        "artifacts": {
            "table5_rows": TABLE5_PATH.name,
            "common_rows": COMMON_PATH.name,
            "figure_data": FIGURE_DATA_PATH.name,
            "figure_png": FIGURE_PATH.name,
            "exposure_figure_png": EXPOSURE_FIGURE_PATH.name,
            "circular_shift_null_gaps": NULL_GAPS_PATH.name,
            "paired_returns": str(RETURNS_PATH.relative_to(SCRIPT_DIR)),
            "sha256": {
                TABLE5_PATH.name: sha256_file(TABLE5_PATH),
                COMMON_PATH.name: sha256_file(COMMON_PATH),
                FIGURE_DATA_PATH.name: sha256_file(FIGURE_DATA_PATH),
                FIGURE_PATH.name: sha256_file(FIGURE_PATH),
                EXPOSURE_FIGURE_PATH.name: sha256_file(EXPOSURE_FIGURE_PATH),
                NULL_GAPS_PATH.name: sha256_file(NULL_GAPS_PATH),
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
            "The circular-shift null assumes the 12/VIX weight path is approximately circularly "
            "stationary. It is persistent but not exactly stationary, so the null is a strong "
            "diagnostic, not an exact size-alpha test.",
            "Exposure matching equalizes UNCONDITIONAL realized volatility, not the volatility path. "
            "That is why the gap is read against its own null and not against zero.",
            "Failing to reject does not prove the absence of timing skill; with 13 dependent markets "
            "and one shared signal, the effective sample for the joint test is small and its power "
            "against a modest true effect is limited.",
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
    common = results["samples"]["common_period"]["summary"]
    matched_ci = results["inference"]["primary"]["average_exposure_matched_delta_mdd_pp"]
    raw_ci = results["inference"]["primary"]["average_delta_mdd_pp"]
    null = results["inference"]["circular_shift_null"]["common_period"]
    print(
        f"{EXPERIMENT_ID} complete (exposure-corrected)\n"
        f"  RAW (not reportable alone): inception avg ΔMDD={summary['average_delta_mdd_pp']:.2f} pp "
        f"({summary['n_mdd_improved']}/13 positive); common avg={common['average_delta_mdd_pp']:.2f} pp "
        f"({common['n_mdd_improved']}/13); joint {CI_LEVEL:.0%} CI=[{raw_ci['lower']:.2f}, {raw_ci['upper']:.2f}]\n"
        f"  EXPOSURE: vol ratio {common['min_vol_ratio']:.2f}-{common['max_vol_ratio']:.2f}x BH; "
        f"mismatch in {common['n_exposure_mismatch']}/13 markets\n"
        f"  EXPOSURE-MATCHED: inception avg={summary['average_exposure_matched_delta_mdd_pp']:.2f} pp "
        f"({summary['n_exposure_matched_improved']}/13 positive); "
        f"common avg={common['average_exposure_matched_delta_mdd_pp']:.2f} pp "
        f"({common['n_exposure_matched_improved']}/13); "
        f"joint {CI_LEVEL:.0%} CI=[{matched_ci['lower']:.2f}, {matched_ci['upper']:.2f}]\n"
        f"  CIRCULAR-SHIFT NULL (n={null['n_shifts']} phases): observed="
        f"{null['joint_exposure_matched']['observed_pp']:+.2f} pp, "
        f"null mean={null['joint_exposure_matched']['null_mean_pp']:+.2f} pp, "
        f"p={null['joint_exposure_matched']['p_one_sided']:.3f}; "
        f"Holm survivors={null['holm']['n_survivors']}/13\n"
        f"  DECISION: kill={results['decision']['kill_triggered']} "
        f"claim={results['decision']['claim_status']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
