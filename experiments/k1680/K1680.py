#!/usr/bin/env python3
"""K1680: geographic investor attention and next-week risk pilot.

Two evidence arms are kept separate:

1. The official RCFS replication demo is used for a directional sanity check
   involving state-level searches, national/local news, volatility, and spread.
2. A retrospective expanding-window free-data diagnostic combines cached yfinance OHLCV
   with fresh Google Trends queries for each firm's headquarters state and the
   United States.  No price/VIX/news proxy is substituted when Trends fails.

The forecasting signal is explicitly lagged one full week.  Nested forecast
inference uses Clark-West; ordinary DM/QLIKE is descriptive only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import scipy.stats as sps
import statsmodels.api as sm
import statsmodels.formula.api as smf


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "K1680"
SEED = 42
TREND_START = "2021-07-01"
TREND_END = "2026-07-01"
ANCHOR_TERM = "SPY stock"
ROLLING_Z_WEEKS = 52
ROLLING_Z_MIN = 26
INITIAL_TRAIN = 156
MIN_TRENDS_WEEKS = 156
HAC_LAGS = 4
EPS = 1e-12

DATA_DIR = ROOT / "data"
RESULTS_PATH = ROOT / "K1680_results.json"
FIGURE_PATH = ROOT / "K1680_geographic_attention.png"
MANIFEST_PATH = DATA_DIR / "manifest.json"

HQ_SOURCE = REPO_ROOT / "experiments" / "k1588" / "data" / "hq_county_geocodes.csv"
PRICE_SOURCE = REPO_ROOT / "experiments" / "k1588" / "data" / "prices_long.csv"
RCFS_PATH = DATA_DIR / "DatasetDemo.dta"
RCFS_URL = "https://dataverse.harvard.edu/api/access/datafile/9554951?format=original"
RCFS_MD5 = "e31f2f677d4fa6f4ab62a712b199a48e"

FIRMS = {
    "AAPL": {"state": "California", "geo": "US-CA", "term": "AAPL stock"},
    "AMZN": {"state": "Washington", "geo": "US-WA", "term": "AMZN stock"},
    "BAC": {"state": "North Carolina", "geo": "US-NC", "term": "BAC stock"},
    "CVX": {"state": "Texas", "geo": "US-TX", "term": "CVX stock"},
    "AIG": {"state": "New York", "geo": "US-NY", "term": "AIG stock"},
    "ABBV": {"state": "Illinois", "geo": "US-IL", "term": "ABBV stock"},
}

REFERENCES = [
    {
        "citation": "Mengoli, Pagano & Pattitoni (2025), RCFS 14(3), 752-803",
        "doi": "10.1093/rcfs/cfae016",
        "replication_doi": "10.7910/DVN/94UPDQ",
    },
    {
        "citation": "Da, Engelberg & Gao (2011), Journal of Finance 66(5), 1461-1499",
        "doi": "10.1111/j.1540-6261.2011.01679.x",
    },
    {
        "citation": "Andrei & Hasler (2015), Review of Financial Studies 28(1), 33-72",
        "doi": "10.1093/rfs/hhu059",
    },
    {
        "citation": "Shive (2012), Journal of Financial Economics 104(1), 145-161",
        "doi": "10.1016/j.jfineco.2011.10.015",
    },
    {
        "citation": "Clark & West (2007), Journal of Econometrics 138(1), 291-311",
        "doi": "10.1016/j.jeconom.2006.05.023",
    },
    {
        "citation": "Corwin & Schultz (2012), Journal of Finance 67(2), 719-760",
        "doi": "10.1111/j.1540-6261.2012.01729.x",
    },
]


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    with tmp.open("r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False, float_format="%.10g")
    pd.read_csv(tmp, nrows=2)
    os.replace(tmp, path)


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def download_rcfs_demo() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not RCFS_PATH.exists():
        response = requests.get(RCFS_URL, timeout=60)
        response.raise_for_status()
        tmp = RCFS_PATH.with_suffix(".dta.tmp")
        tmp.write_bytes(response.content)
        if file_hash(tmp, "md5") != RCFS_MD5:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("RCFS Dataverse MD5 mismatch")
        os.replace(tmp, RCFS_PATH)
    if file_hash(RCFS_PATH, "md5") != RCFS_MD5:
        raise RuntimeError("Cached RCFS Dataverse MD5 mismatch")
    return {
        "path": str(RCFS_PATH.relative_to(REPO_ROOT)),
        "source_url": RCFS_URL,
        "bytes": RCFS_PATH.stat().st_size,
        "md5": file_hash(RCFS_PATH, "md5"),
        "sha256": file_hash(RCFS_PATH),
        "license": "CC0 1.0 (Harvard Dataverse metadata)",
    }


def rcfs_sanity() -> dict[str, Any]:
    frame = pd.read_stata(RCFS_PATH, convert_categoricals=False)
    formula = (
        "GSearch ~ SameState + News + SameStateXNews + Vol + SameStateXVol + "
        "LocalNewsPaper + SameStateXLocalNewsPaper + C(Unit) + C(State) + C(Week)"
    )
    fit = smf.ols(formula, data=frame).fit(
        cov_type="cluster", cov_kwds={"groups": frame["IdUnitState"]}
    )
    keys = [
        "SameState",
        "News",
        "SameStateXNews",
        "Vol",
        "SameStateXVol",
        "LocalNewsPaper",
        "SameStateXLocalNewsPaper",
    ]
    coefficients = {
        key: {
            "coef": safe_float(fit.params.get(key)),
            "p_value": safe_float(fit.pvalues.get(key)),
        }
        for key in keys
    }

    local = frame.loc[frame["SameState"] == 1, "GSearch"]
    nonlocal_search = frame.loc[frame["SameState"] == 0, "GSearch"]

    return {
        "role": "directional replication-package sanity check, not K1680 OOS sample",
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "firms_anonymized": int(frame["Unit"].nunique()),
        "states": int(frame["State"].nunique()),
        "weeks": int(frame["Week"].nunique()),
        "mean_search_same_state": float(local.mean()),
        "mean_search_other_states": float(nonlocal_search.mean()),
        "same_state_ratio": float(local.mean() / nonlocal_search.mean()),
        "fixed_effect_regression": coefficients,
        "dynamic_sanity": {
            "available": False,
            "reason": (
                "Demo GSearch is rebased within each firm-week and cannot be used "
                "across weeks. The RCFS dynamic LocalSearch/NonLocalSearch series "
                "requires state shares multiplied by national aggregate ticker "
                "searches and is not reconstructed from this demo."
            ),
        },
        "causal_claim_allowed": False,
    }


def patch_pytrends_urllib3() -> None:
    """Translate pytrends' deprecated urllib3 Retry keyword."""

    import urllib3.util.retry as retry

    original = retry.Retry.__init__
    if getattr(original, "_k1680_patched", False):
        return

    def patched(self, *args, **kwargs):
        if "method_whitelist" in kwargs and "allowed_methods" not in kwargs:
            kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
        return original(self, *args, **kwargs)

    patched._k1680_patched = True  # type: ignore[attr-defined]
    retry.Retry.__init__ = patched


def trends_cache_path(symbol: str, geo: str) -> Path:
    return DATA_DIR / f"trends_{symbol}_{geo.replace('-', '_')}.csv"


def validate_trends_calendar(frame: pd.DataFrame, context: str) -> None:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise RuntimeError(f"Invalid/duplicate/nonmonotonic Trends dates: {context}")
    if not (dates.dt.weekday == 6).all():
        raise RuntimeError(f"Trends dates are not Sunday week starts: {context}")
    gaps = dates.diff().dropna().dt.days
    if len(gaps) == 0 or not (gaps == 7).all():
        raise RuntimeError(f"Trends cadence is not contiguous weekly: {context}")


def fetch_trends_pair(
    symbol: str,
    geo: str,
    term: str,
    *,
    refresh: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = trends_cache_path(symbol, geo)
    if path.exists() and not refresh:
        cached = pd.read_csv(path, parse_dates=["date"])
        required = {"date", "company_search", "anchor_search"}
        if not required.issubset(cached.columns):
            raise RuntimeError(f"Invalid Trends cache columns: {path}")
        validate_trends_calendar(cached, str(path))
        return cached, {
            "source": "local_cache",
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": file_hash(path),
            "bytes": path.stat().st_size,
            "rows": int(len(cached)),
            "first_week": str(cached["date"].min().date()),
            "last_week": str(cached["date"].max().date()),
            "geo": geo,
            "term": term,
            "anchor": ANCHOR_TERM,
        }

    patch_pytrends_urllib3()
    from pytrends.request import TrendReq

    client = TrendReq(
        hl="en-US",
        tz=360,
        retries=0,
        backoff_factor=0,
        requests_args={
            "headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
                )
            }
        },
    )
    client.build_payload(
        [term, ANCHOR_TERM],
        timeframe=f"{TREND_START} {TREND_END}",
        geo=geo,
    )
    raw = client.interest_over_time()
    if raw is None or raw.empty or term not in raw or ANCHOR_TERM not in raw:
        raise RuntimeError(f"Empty Google Trends response for {symbol} {geo}")
    if "isPartial" in raw:
        raw = raw.loc[~raw["isPartial"].astype(bool)]
    out = raw[[term, ANCHOR_TERM]].rename(
        columns={term: "company_search", ANCHOR_TERM: "anchor_search"}
    )
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out.index.name = "date"
    out = out.reset_index()
    validate_trends_calendar(out, f"live {symbol} {geo}")
    atomic_write_csv(out, path)
    return out, {
        "source": "pytrends_live_fetch",
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": file_hash(path),
        "bytes": path.stat().st_size,
        "rows": int(len(out)),
        "first_week": str(out["date"].min().date()),
        "last_week": str(out["date"].max().date()),
        "geo": geo,
        "term": term,
        "anchor": ANCHOR_TERM,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "normalization_note": "term and anchor share one payload; ratio cancels payload-wide scaling",
    }


def collect_trends(refresh: bool, sleep_seconds: float) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    panels: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {"queries": {}, "errors": {}}
    for symbol, spec in FIRMS.items():
        by_geo: dict[str, pd.DataFrame] = {}
        for label, geo in [("local", spec["geo"]), ("national", "US")]:
            key = f"{symbol}:{label}"
            try:
                frame, meta = fetch_trends_pair(
                    symbol,
                    geo,
                    spec["term"],
                    refresh=refresh,
                )
                by_geo[label] = frame
                manifest["queries"][key] = meta
            except Exception as exc:
                manifest["errors"][key] = f"{type(exc).__name__}: {exc}"
                break
            if meta["source"] == "pytrends_live_fetch" and sleep_seconds > 0:
                time.sleep(sleep_seconds)
        if set(by_geo) != {"local", "national"}:
            continue

        local = by_geo["local"].rename(
            columns={
                "company_search": "local_company",
                "anchor_search": "local_anchor",
            }
        )
        national = by_geo["national"].rename(
            columns={
                "company_search": "national_company",
                "anchor_search": "national_anchor",
            }
        )
        merged = local.merge(national, on="date", how="inner").sort_values("date")
        # Google dates are week starts (Sunday). Align to that week's Friday;
        # signal.shift(1) below then moves it to the next tradable week.
        merged["date"] = pd.to_datetime(merged["date"]) + pd.Timedelta(days=5)
        merged = merged.set_index("date")
        merged["local_ratio"] = np.log(
            (merged["local_company"] + 0.5) / (merged["local_anchor"] + 0.5)
        )
        merged["national_ratio"] = np.log(
            (merged["national_company"] + 0.5) / (merged["national_anchor"] + 0.5)
        )
        for source in ["local", "national"]:
            values = merged[f"{source}_ratio"]
            rolling = values.rolling(ROLLING_Z_WEEKS, min_periods=ROLLING_Z_MIN)
            merged[f"{source}_z_raw"] = (values - rolling.mean()) / rolling.std(ddof=1)
        merged["local_excess_raw"] = merged["local_z_raw"] - merged["national_z_raw"]
        # LOOKAHEAD FIREWALL: target week t receives only attention from t-1.
        merged["signal"] = merged["local_excess_raw"].shift(1)
        merged["national_signal"] = merged["national_z_raw"].shift(1)
        merged["local_signal"] = merged["local_z_raw"].shift(1)
        panels[symbol] = merged
    manifest["complete_firms"] = sorted(panels)
    manifest["required_firms"] = sorted(FIRMS)
    manifest["complete"] = set(panels) == set(FIRMS)
    return panels, manifest


def corwin_schultz(high: pd.Series, low: pd.Series) -> pd.Series:
    log_hl = np.log(high / low)
    beta = log_hl.pow(2) + log_hl.pow(2).shift(1)
    high_2d = pd.concat([high, high.shift(1)], axis=1).max(axis=1)
    low_2d = pd.concat([low, low.shift(1)], axis=1).min(axis=1)
    gamma = np.log(high_2d / low_2d).pow(2)
    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = alpha.clip(lower=0.0, upper=5.0)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    return spread.where(np.isfinite(spread))


def load_price_panels() -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    if not HQ_SOURCE.exists() or not PRICE_SOURCE.exists():
        raise FileNotFoundError("K1588 pinned HQ/price sources are missing")
    hq = pd.read_csv(HQ_SOURCE)
    prices = pd.read_csv(PRICE_SOURCE, parse_dates=["date"])
    hq_subset = hq[hq["Symbol"].isin(FIRMS)][["Symbol", "state_name"]]
    actual_states = dict(zip(hq_subset["Symbol"], hq_subset["state_name"], strict=True))
    expected_states = {symbol: spec["state"] for symbol, spec in FIRMS.items()}
    if actual_states != expected_states:
        raise RuntimeError(f"HQ-state drift: actual={actual_states}, expected={expected_states}")

    outputs: dict[str, pd.DataFrame] = {}
    coverage: dict[str, Any] = {}
    for symbol in FIRMS:
        daily = prices.loc[prices["yf_symbol"] == symbol].copy().sort_values("date")
        if daily.empty:
            raise RuntimeError(f"No K1588 price rows for {symbol}")
        daily = daily.set_index("date")
        daily["ret"] = np.log(daily["close"]).diff()
        daily["gap"] = np.log(daily["open"] / daily["close"].shift(1))
        daily["cs"] = corwin_schultz(daily["high"], daily["low"])
        weekly = pd.DataFrame(
            {
                "rv": daily["ret"].pow(2).resample("W-FRI").sum(min_count=1),
                "gap": daily["gap"].pow(2).resample("W-FRI").sum(min_count=1),
                "corwin_schultz": daily["cs"].resample("W-FRI").mean(),
            }
        )
        outputs[symbol] = weekly
        coverage[symbol] = {
            "daily_rows": int(len(daily)),
            "first_date": str(daily.index.min().date()),
            "last_date": str(daily.index.max().date()),
            "weekly_rows": int(len(weekly)),
        }
    return outputs, {
        "hq_source": str(HQ_SOURCE.relative_to(REPO_ROOT)),
        "hq_sha256": file_hash(HQ_SOURCE),
        "price_source": str(PRICE_SOURCE.relative_to(REPO_ROOT)),
        "price_sha256": file_hash(PRICE_SOURCE),
        "source_description": "K1588 pinned yfinance adjusted OHLCV and current-HQ snapshot",
        "coverage": coverage,
    }


def build_model_frame(
    target: str,
    prices: pd.DataFrame,
    trends: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str], str]:
    merged = prices.join(trends, how="inner")
    if target == "national_attention":
        merged["target"] = merged["national_z_raw"]
        merged["target_model"] = merged["target"]
        for lag in [1, 4, 13]:
            merged[f"target_lag{lag}"] = merged["target_model"].shift(lag)
        base = ["target_lag1", "target_lag4", "target_lag13"]
        augmented = base + ["local_signal"]
        target_transform = "level"
    elif target == "corwin_schultz":
        merged["target"] = merged[target].clip(lower=0.0)
        # CS legitimately equals zero when estimated alpha is negative.  A
        # log1p transform preserves those observations without EPS outliers.
        merged["target_model"] = np.log1p(merged["target"])
        for lag in [1, 4, 13]:
            merged[f"target_lag{lag}"] = merged["target_model"].shift(lag)
        base = ["target_lag1", "target_lag4", "target_lag13", "national_signal"]
        augmented = base + ["signal"]
        target_transform = "log1p"
    else:
        merged["target"] = merged[target].clip(lower=EPS)
        merged["target_model"] = np.log(merged["target"])
        for lag in [1, 4, 13]:
            merged[f"target_lag{lag}"] = merged["target_model"].shift(lag)
        base = ["target_lag1", "target_lag4", "target_lag13", "national_signal"]
        augmented = base + ["signal"]
        target_transform = "log"
    needed = ["target", "target_model", *augmented]
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(subset=needed)
    return merged, base, augmented, target_transform


def run_expanding_oos(
    frame: pd.DataFrame,
    base_features: list[str],
    augmented_features: list[str],
    *,
    target_transform: str,
) -> pd.DataFrame:
    if len(frame) < INITIAL_TRAIN + 52:
        raise RuntimeError(f"Insufficient model rows: {len(frame)}")
    rows: list[dict[str, Any]] = []
    for index in range(INITIAL_TRAIN, len(frame)):
        train = frame.iloc[:index]
        test = frame.iloc[[index]]
        base_fit = sm.OLS(
            train["target_model"],
            sm.add_constant(train[base_features], has_constant="add"),
        ).fit()
        aug_fit = sm.OLS(
            train["target_model"],
            sm.add_constant(train[augmented_features], has_constant="add"),
        ).fit()
        base_pred_model = float(
            base_fit.predict(
                sm.add_constant(test[base_features], has_constant="add")
            ).iloc[0]
        )
        aug_pred_model = float(
            aug_fit.predict(
                sm.add_constant(test[augmented_features], has_constant="add")
            ).iloc[0]
        )
        actual = float(test["target"].iloc[0])
        actual_model = float(test["target_model"].iloc[0])
        if target_transform == "log":
            base_level = max(math.exp(base_pred_model), EPS)
            aug_level = max(math.exp(aug_pred_model), EPS)
        elif target_transform == "log1p":
            base_level = max(math.expm1(base_pred_model), 0.0)
            aug_level = max(math.expm1(aug_pred_model), 0.0)
        elif target_transform == "level":
            base_level = base_pred_model
            aug_level = aug_pred_model
        else:
            raise ValueError(f"Unknown target transform: {target_transform}")
        base_error = actual_model - base_pred_model
        aug_error = actual_model - aug_pred_model
        cw_adjusted = base_error**2 - (
            aug_error**2 - (base_pred_model - aug_pred_model) ** 2
        )
        rows.append(
            {
                "date": test.index[0],
                "actual": actual,
                "actual_model": actual_model,
                "base_pred": base_level,
                "aug_pred": aug_level,
                "base_pred_model": base_pred_model,
                "aug_pred_model": aug_pred_model,
                "base_sq_error": base_error**2,
                "aug_sq_error": aug_error**2,
                "cw_adjusted": cw_adjusted,
            }
        )
    return pd.DataFrame(rows)


def hac_mean_test(values: pd.Series, *, one_sided_positive: bool) -> dict[str, Any]:
    clean = pd.Series(values).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 10:
        return {"n": int(len(clean)), "mean": None, "t": None, "p": None}
    fit = sm.OLS(clean.to_numpy(), np.ones((len(clean), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}
    )
    mean = float(fit.params[0])
    t_value = float(fit.tvalues[0])
    if not np.isfinite(mean) or not np.isfinite(t_value) or not np.isfinite(fit.bse[0]):
        raise RuntimeError("Degenerate/nonfinite HAC mean test")
    if one_sided_positive:
        p_value = float(sps.norm.sf(t_value))
    else:
        p_value = float(2 * sps.norm.sf(abs(t_value)))
    if not np.isfinite(p_value):
        raise RuntimeError("Nonfinite HAC p-value")
    return {"n": int(len(clean)), "mean": mean, "t": t_value, "p": p_value}


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, (name, p_value) in enumerate(ordered):
        candidate = min(1.0, (total - rank) * p_value)
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def summarize_target(
    target: str,
    forecasts: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    combined = []
    per_firm: dict[str, Any] = {}
    use_qlike = target in {"rv", "gap"}
    common_dates: set[pd.Timestamp] | None = None
    for frame in forecasts.values():
        dates = set(pd.to_datetime(frame["date"]))
        common_dates = dates if common_dates is None else common_dates & dates
    common_dates = common_dates or set()
    if len(common_dates) < 52:
        raise RuntimeError(f"Only {len(common_dates)} common evaluation dates for {target}")
    for symbol, frame in forecasts.items():
        local = frame.loc[pd.to_datetime(frame["date"]).isin(common_dates)].copy()
        local["symbol"] = symbol
        combined.append(local)
        cw = hac_mean_test(local["cw_adjusted"], one_sided_positive=True)
        base_mse = float(local["base_sq_error"].mean())
        aug_mse = float(local["aug_sq_error"].mean())
        if not np.isfinite(base_mse) or not np.isfinite(aug_mse) or base_mse <= 0:
            raise RuntimeError(f"Degenerate firm MSE for {target}/{symbol}")
        per_firm[symbol] = {
            "evaluation_n": int(len(local)),
            "evaluation_start": str(pd.to_datetime(local["date"]).min().date()),
            "evaluation_end": str(pd.to_datetime(local["date"]).max().date()),
            "base_model_scale_mse": base_mse,
            "aug_model_scale_mse": aug_mse,
            "mse_improvement_pct": float((base_mse - aug_mse) / base_mse * 100),
            "clark_west": cw,
        }
    stacked = pd.concat(combined, ignore_index=True)
    by_date = (
        stacked.groupby("date", as_index=False)
        .agg(
            cw_adjusted=("cw_adjusted", "mean"),
            base_sq_error=("base_sq_error", "mean"),
            aug_sq_error=("aug_sq_error", "mean"),
            firm_count=("symbol", "nunique"),
        )
        .sort_values("date")
    )
    if not (by_date["firm_count"] == len(FIRMS)).all():
        raise RuntimeError(f"Unbalanced pooled panel for {target}")
    cw = hac_mean_test(by_date["cw_adjusted"], one_sided_positive=True)
    base_mse = float(by_date["base_sq_error"].mean())
    aug_mse = float(by_date["aug_sq_error"].mean())
    if not np.isfinite(base_mse) or not np.isfinite(aug_mse) or base_mse <= 0:
        raise RuntimeError(f"Degenerate pooled MSE for {target}")
    result: dict[str, Any] = {
        "pooled_by_week": {
            "common_evaluation_weeks": int(len(by_date)),
            "firms_per_week": int(by_date["firm_count"].min()),
            "base_model_scale_mse": base_mse,
            "aug_model_scale_mse": aug_mse,
            "mse_improvement_pct": float((base_mse - aug_mse) / base_mse * 100),
            "clark_west": cw,
        },
        "per_firm": per_firm,
    }

    if use_qlike:
        stacked["base_loss"] = qlike_pointwise(
            stacked["actual"].to_numpy(), stacked["base_pred"].to_numpy()
        )
        stacked["aug_loss"] = qlike_pointwise(
            stacked["actual"].to_numpy(), stacked["aug_pred"].to_numpy()
        )
    else:
        stacked["base_loss"] = (
            stacked["actual"].to_numpy() - stacked["base_pred"].to_numpy()
        ) ** 2
        stacked["aug_loss"] = (
            stacked["actual"].to_numpy() - stacked["aug_pred"].to_numpy()
        ) ** 2
    loss_by_date = stacked.groupby("date")[["base_loss", "aug_loss"]].mean()
    dm_t, dm_p = dm_test(
        loss_by_date["aug_loss"].to_numpy(),
        loss_by_date["base_loss"].to_numpy(),
        h=1,
    )
    result["descriptive_loss"] = {
        "metric": "QLIKE" if target in {"rv", "gap"} else "squared_error",
        "base": float(loss_by_date["base_loss"].mean()),
        "augmented": float(loss_by_date["aug_loss"].mean()),
        "improvement_pct": float(
            (loss_by_date["base_loss"].mean() - loss_by_date["aug_loss"].mean())
            / loss_by_date["base_loss"].mean()
            * 100
        ),
        "dm_t_aug_vs_base": float(dm_t),
        "dm_p_two_sided": float(dm_p),
        "formal_gate": False,
    }
    return result


def make_figure(results: dict[str, Any]) -> None:
    targets = ["rv", "gap", "corwin_schultz", "national_attention"]
    labels = ["RV", "Gap variance", "CS spread", "National attention"]
    if results["verdict"]["status"] == "NULL_DATA_LIMITATION":
        fig, ax = plt.subplots(figsize=(10, 5.8))
        ax.axis("off")
        ax.text(0.5, 0.62, "K1680: Google Trends data gate not met", ha="center", fontsize=20, weight="bold")
        ax.text(0.5, 0.45, "No substitute attention proxy was used.", ha="center", fontsize=15)
        ax.text(0.5, 0.30, results["verdict"]["summary"], ha="center", fontsize=11, wrap=True)
    else:
        improvements = [
            results["retrospective_pseudo_oos_results"][target]["pooled_by_week"]["mse_improvement_pct"]
            for target in targets
        ]
        cw_t = [
            results["retrospective_pseudo_oos_results"][target]["pooled_by_week"]["clark_west"]["t"]
            for target in targets
        ]
        colors = ["#238b8e" if value > 0 else "#cf5c5c" for value in improvements]
        fig, axes = plt.subplots(1, 2, figsize=(12, 5.6))
        axes[0].bar(labels, improvements, color=colors)
        axes[0].axhline(0, color="black", linewidth=1)
        axes[0].set_ylabel("Retrospective model-scale MSE improvement (%)")
        axes[0].set_title("Expanding-window pseudo-OOS diagnostic")
        axes[0].tick_params(axis="x", rotation=20)
        axes[1].bar(labels, cw_t, color="#356fa3")
        axes[1].axhline(3, color="#b66a11", linestyle="--", label="Harvey t=3 gate")
        axes[1].axhline(0, color="black", linewidth=1)
        axes[1].set_ylabel("Clark-West t statistic")
        axes[1].set_title("One-sided nested-model inference")
        axes[1].tick_params(axis="x", rotation=20)
        axes[1].legend(frameon=False)
        fig.suptitle("K1680: Local-minus-national attention retrospective pilot", fontsize=15, weight="bold")
    fig.tight_layout()
    fig.savefig(FIGURE_PATH, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(SEED)
    started = datetime.now(timezone.utc)
    try:
        rcfs_meta = download_rcfs_demo()
        sanity = rcfs_sanity()
    except Exception as exc:
        rcfs_meta = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        sanity = {
            "available": False,
            "role": "independent sanity arm; failure does not alter the primary pilot",
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        price_panels, price_meta = load_price_panels()
        price_error = None
    except Exception as exc:
        price_panels = {}
        price_meta = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        price_error = f"{type(exc).__name__}: {exc}"
    try:
        trends_panels, trends_meta = collect_trends(
            refresh=args.refresh_trends,
            sleep_seconds=args.sleep_seconds,
        )
        trends_fatal_error = None
    except Exception as exc:
        trends_panels = {}
        trends_meta = {
            "complete": False,
            "queries": {},
            "errors": {"fatal": f"{type(exc).__name__}: {exc}"},
        }
        trends_fatal_error = f"{type(exc).__name__}: {exc}"

    data_manifest = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rcfs": rcfs_meta,
        "pinned_yfinance": price_meta,
        "google_trends": trends_meta,
    }
    atomic_write_json(MANIFEST_PATH, data_manifest)

    base_results: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Geographic investor attention and next-week firm risk pilot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "retrospective empirical proxy diagnostic; not real-time OOS and not causal",
        "seed": SEED,
        "config": {
            "firms": FIRMS,
            "trend_timeframe": [TREND_START, TREND_END],
            "anchor_term": ANCHOR_TERM,
            "rolling_z_weeks": ROLLING_Z_WEEKS,
            "rolling_z_min": ROLLING_Z_MIN,
            "initial_expanding_train_weeks": INITIAL_TRAIN,
            "lookahead_policy": "raw attention is transformed then signal.shift(1), preventing same-week target use; Google historical-vintage availability is not claimed",
            "primary_targets": ["rv", "gap", "corwin_schultz", "national_attention"],
            "evaluation_design": "expanding-window pseudo-OOS on a single retrospectively downloaded Google Trends vintage",
            "vintage_caveat": "full-window Trends normalization cancels in the within-payload ticker/anchor ratio, but sampling/revision history is unavailable; results are not genuine real-time OOS",
            "formal_test": "Clark-West one-sided on six-firm common-week adjusted log-MSE; Holm across four targets",
            "harvey_gate": "CW t >= 3, Holm p < 0.05, MSE improvement > 0",
        },
        "references": REFERENCES,
        "data_provenance": {
            "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
            "manifest_sha256": file_hash(MANIFEST_PATH),
            **data_manifest,
        },
        "rcfs_replication_demo_sanity": sanity,
        "prior_related_results": {
            "K192_K473_K750_K789": "broad Google attention/fear signals were OOS null or reactive; no spatial channel test",
            "research_google_trends_vol": "partial real Trends panel, no robust OOS increment; no fake fallback allowed",
            "K1588": "source of pinned current-HQ and yfinance OHLCV snapshot",
        },
        "limitations": [
            "Six firms are below the general N>=7 cross-sectional threshold; this remains a pilot.",
            "US national Trends includes the HQ state, so local-minus-national is not a clean nonlocal measure.",
            "Google Trends uses sampled and normalized search intensity; the ticker/SPY ratio is a proxy.",
            "K1588 headquarters are current snapshots and may not capture historical relocations.",
            "Corwin-Schultz is a daily OHLC range-based spread proxy, not quoted/effective TAQ spread.",
            "RCFS demo has four anonymized firms and is a directional sanity arm, not merged with OOS data.",
            "Predictive timing does not identify a causal local information-processing advantage.",
            "Google Trends was downloaded retrospectively in one current vintage; expanding evaluation is pseudo-OOS, not a historical-vintage real-time backtest.",
        ],
        "runtime_seconds": None,
    }

    incomplete = sorted(set(FIRMS) - set(trends_panels))
    too_short = {
        symbol: int(len(frame))
        for symbol, frame in trends_panels.items()
        if len(frame) < MIN_TRENDS_WEEKS
    }
    if price_error or trends_fatal_error or incomplete or too_short:
        base_results["retrospective_pseudo_oos_results"] = {}
        base_results["verdict"] = {
            "status": "NULL_DATA_LIMITATION",
            "passed_targets": [],
            "summary": (
                "The state-level Google Trends gate was not met; no VIX, price, volume, "
                "Wikipedia, or news proxy was substituted for attention."
            ),
            "incomplete_firms": incomplete,
            "too_short": too_short,
            "price_error": price_error,
            "trends_fatal_error": trends_fatal_error,
        }
        base_results["runtime_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
        return base_results

    forecasts_by_target: dict[str, dict[str, pd.DataFrame]] = {
        target: {} for target in ["rv", "gap", "corwin_schultz", "national_attention"]
    }
    sample_meta: dict[str, Any] = {}
    try:
        for symbol in FIRMS:
            sample_meta[symbol] = {}
            for target in forecasts_by_target:
                frame, base_features, aug_features, target_transform = build_model_frame(
                    target,
                    price_panels[symbol],
                    trends_panels[symbol],
                )
                forecast = run_expanding_oos(
                    frame,
                    base_features,
                    aug_features,
                    target_transform=target_transform,
                )
                forecasts_by_target[target][symbol] = forecast
                sample_meta[symbol][target] = {
                    "model_rows": int(len(frame)),
                    "first_model_week": str(frame.index.min().date()),
                    "last_model_week": str(frame.index.max().date()),
                    "evaluation_rows_before_common_date_intersection": int(len(forecast)),
                }
        summaries = {
            target: summarize_target(target, forecasts)
            for target, forecasts in forecasts_by_target.items()
        }
    except Exception as exc:
        base_results["sample"] = sample_meta
        base_results["retrospective_pseudo_oos_results"] = {}
        base_results["verdict"] = {
            "status": "NULL_DATA_LIMITATION",
            "passed_targets": [],
            "summary": "Post-transform/common-date model sample gate was not met; no substitute attention proxy was used.",
            "model_sample_error": f"{type(exc).__name__}: {exc}",
        }
        base_results["runtime_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
        return base_results

    try:
        raw_p = {
            target: float(summary["pooled_by_week"]["clark_west"]["p"])
            for target, summary in summaries.items()
        }
        if not all(np.isfinite(value) for value in raw_p.values()):
            raise RuntimeError("Nonfinite Clark-West p-value family")
        holm = holm_adjust(raw_p)
        passed: list[str] = []
        for target, summary in summaries.items():
            pooled = summary["pooled_by_week"]
            gate_values = [
                pooled["mse_improvement_pct"],
                pooled["clark_west"]["t"],
                holm[target],
            ]
            if not all(np.isfinite(value) for value in gate_values):
                raise RuntimeError(f"Nonfinite retrospective gate value for {target}")
            pooled["clark_west"]["holm_p"] = holm[target]
            target_pass = bool(
                pooled["mse_improvement_pct"] > 0
                and pooled["clark_west"]["t"] >= 3.0
                and holm[target] < 0.05
            )
            pooled["passes_retrospective_gate"] = target_pass
            if target_pass:
                passed.append(target)
    except Exception as exc:
        base_results["sample"] = sample_meta
        base_results["retrospective_pseudo_oos_results"] = {}
        base_results["verdict"] = {
            "status": "NULL_DATA_LIMITATION",
            "passed_targets": [],
            "summary": "Clark-West/multiple-testing gate was degenerate; no positive or null research claim is made.",
            "inference_error": f"{type(exc).__name__}: {exc}",
        }
        base_results["runtime_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
        return base_results

    risk_passes = len(set(passed) & {"rv", "gap", "corwin_schultz"})
    if risk_passes >= 2:
        status = "RETROSPECTIVE_STRONG_DIAGNOSTIC"
    elif passed:
        status = "RETROSPECTIVE_CONDITIONAL_DIAGNOSTIC"
    else:
        status = "RETROSPECTIVE_NULL"
    base_results["sample"] = sample_meta
    base_results["retrospective_pseudo_oos_results"] = summaries
    base_results["multiple_testing"] = {
        "family": list(summaries),
        "raw_one_sided_cw_p": raw_p,
        "holm_adjusted_p": holm,
    }
    base_results["verdict"] = {
        "status": status,
        "passed_targets": passed,
        "summary": (
            f"{len(passed)}/4 targets passed the pre-registered Clark-West + Holm + "
            "Harvey t>=3 retrospective gate. This is current-vintage pseudo-OOS proxy evidence, not real-time OOS or causal evidence."
        ),
    }
    base_results["runtime_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
    return base_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-trends",
        action="store_true",
        help="Ignore local Trends CSV caches and fetch all payloads again.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=6.0,
        help="Pause after each live pytrends payload to reduce HTTP 429 risk.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    results = run(args)
    make_figure(results)
    results["output_artifacts"] = {
        "results": str(RESULTS_PATH.relative_to(REPO_ROOT)),
        "figure": str(FIGURE_PATH.relative_to(REPO_ROOT)),
        "figure_sha256": file_hash(FIGURE_PATH),
    }
    atomic_write_json(RESULTS_PATH, results)
    print(json.dumps(results["verdict"], ensure_ascii=False, indent=2))
    print(f"wrote {RESULTS_PATH}")
    print(f"wrote {FIGURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
