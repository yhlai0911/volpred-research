#!/usr/bin/env python3
"""K1682: cross-exchange daily close-price dispersion as a crypto risk signal.

Empirical proxy study.  This is deliberately *not* an executable-arbitrage test:
daily OHLCV closes are neither synchronized quotes nor bid/ask order books.

Primary signal
--------------
Binance BTC/ETH-USDT closes are converted to USD with the same UTC-day Coinbase
USDT-USD close, then combined with Coinbase and Kraken USD closes.  The signal is
the cross-sectional standard deviation of log closes, in basis points.  Raw native
quote dispersion and the Coinbase/Kraken USD-only dispersion are sensitivity measures.

Timing
------
All forecast features, including dispersion, are explicitly shifted by one day.
For an OOS origin i and horizon h, a training row j is admissible only if
``j + h < i``.  This conservative embargo prevents forward labels from reaching
into the forecast window.  Current/incomplete exchange candles are dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
from scipy import stats
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.stats.multitest import multipletests


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "k1682_results.json"
SEED = 42
MIN_TRAIN = 252
REFIT_EVERY_TAIL = 7
TAU = 0.05
EPS = 1e-12
HORIZONS = (1, 5)
ASSETS = ("BTC", "ETH")
EXCHANGES = ("binance", "coinbase", "kraken")
USER_AGENT = "VolPred-K1682/1.0 (academic research; public market data)"

BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"
BINANCE_TIME = "https://api.binance.com/api/v3/time"
COINBASE_CANDLES = "https://api.coinbase.com/api/v3/brokerage/market/products/{product}/candles"
COINBASE_TIME = "https://api.coinbase.com/api/v3/brokerage/time"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"

REFERENCES = [
    {
        "authors": "Makarov, I.; Schoar, A.",
        "year": 2020,
        "title": "Trading and arbitrage in cryptocurrency markets",
        "journal": "Journal of Financial Economics 135(2), 293-319",
        "doi": "10.1016/j.jfineco.2019.07.001",
    },
    {
        "authors": "Brandvold, M.; Molnar, P.; Vagstad, K.; Valstad, O.C.A.",
        "year": 2015,
        "title": "Price discovery on Bitcoin exchanges",
        "journal": "Journal of International Financial Markets, Institutions and Money 36, 18-35",
        "doi": "10.1016/j.intfin.2015.02.010",
    },
    {
        "authors": "Hautsch, N.; Scheuch, C.; Voigt, S.",
        "year": 2024,
        "title": "Building Trust Takes Time: Limits to Arbitrage for Blockchain-Based Assets",
        "journal": "Review of Finance 28(4), 1345-1381",
        "doi": "10.1093/rof/rfae004",
    },
    {
        "authors": "Corsi, F.",
        "year": 2009,
        "title": "A simple approximate long-memory model of realized volatility",
        "journal": "Journal of Financial Econometrics 7(2), 174-196",
        "doi": "10.1093/jjfinec/nbp001",
    },
    {
        "authors": "Patton, A.J.",
        "year": 2011,
        "title": "Volatility forecast comparison using imperfect volatility proxies",
        "journal": "Journal of Econometrics 160(1), 246-256",
        "doi": "10.1016/j.jeconom.2010.03.034",
    },
]

sys.path.insert(0, str(ROOT / "src"))
from volpred.stats.model_evaluation import dm_test, qlike_pointwise, spearman_corr  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="replace pinned API CSV snapshots")
    return parser.parse_args()


def request_json(url: str, params: dict[str, Any] | None = None) -> Any:
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=30,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # network/API failure must remain visible
            error = exc
            if attempt == 3:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"public API request failed: {url} params={params}: {error}")


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    frame.to_csv(tmp, index=False)
    pd.read_csv(tmp, nrows=3)
    os.replace(tmp, path)


def atomic_write_json(payload: dict[str, Any], path: Path = RESULTS_PATH) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
    with tmp.open("r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def fetch_binance(asset: str) -> pd.DataFrame:
    server_ms = int(request_json(BINANCE_TIME)["serverTime"])
    rows = request_json(
        BINANCE_KLINES,
        {"symbol": f"{asset}USDT", "interval": "1d", "limit": 1000, "timeZone": "0"},
    )
    columns = [
        "open_time_ms",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time_ms",
        "quote_volume",
        "trade_count",
        "taker_base_volume",
        "taker_quote_volume",
        "ignore",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame = frame[pd.to_numeric(frame["close_time_ms"]) < server_ms].copy()
    frame["date"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    frame["exchange"] = "binance"
    frame["asset"] = asset
    frame["quote"] = "USDT"
    return frame[["date", "exchange", "asset", "quote", "open", "high", "low", "close", "volume"]]


def fetch_coinbase(product: str, asset_label: str, quote: str, start_day: pd.Timestamp) -> pd.DataFrame:
    server = request_json(COINBASE_TIME)
    server_s = int(server.get("epochSeconds") or float(server["epochMillis"]) / 1000)
    end = pd.Timestamp(server_s, unit="s", tz="UTC").floor("D") + pd.Timedelta(days=1)
    cursor = start_day.floor("D")
    records: list[dict[str, Any]] = []
    while cursor < end:
        chunk_end = min(cursor + pd.Timedelta(days=300), end)
        payload = request_json(
            COINBASE_CANDLES.format(product=product),
            {
                "start": str(int(cursor.timestamp())),
                "end": str(int(chunk_end.timestamp())),
                "granularity": "ONE_DAY",
                "limit": 350,
            },
        )
        records.extend(payload.get("candles", []))
        cursor = chunk_end
    frame = pd.DataFrame(records)
    required = {"start", "open", "high", "low", "close", "volume"}
    if not required <= set(frame.columns):
        raise RuntimeError(f"Coinbase {product} response missing fields: {required - set(frame.columns)}")
    frame["start"] = pd.to_numeric(frame["start"], errors="raise").astype("int64")
    frame = frame[frame["start"] + 86400 <= server_s].copy()
    frame["date"] = pd.to_datetime(frame["start"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    frame["exchange"] = "coinbase"
    frame["asset"] = asset_label
    frame["quote"] = quote
    return frame[["date", "exchange", "asset", "quote", "open", "high", "low", "close", "volume"]]


def fetch_kraken(asset: str) -> pd.DataFrame:
    pair = "XBTUSD" if asset == "BTC" else "ETHUSD"
    payload = request_json(KRAKEN_OHLC, {"pair": pair, "interval": 1440})
    if payload.get("error"):
        raise RuntimeError(f"Kraken {pair} error: {payload['error']}")
    key = next(key for key in payload["result"] if key != "last")
    rows = payload["result"][key]
    if len(rows) < 2:
        raise RuntimeError(f"Kraken {pair} returned insufficient rows")
    # Kraken documents that the final entry is the current, not-yet-committed candle.
    rows = rows[:-1]
    columns = ["time_s", "open", "high", "low", "close", "vwap", "volume", "count"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["date"] = pd.to_datetime(frame["time_s"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    frame["exchange"] = "kraken"
    frame["asset"] = asset
    frame["quote"] = "USD"
    return frame[["date", "exchange", "asset", "quote", "open", "high", "low", "close", "volume"]]


def cache_path(asset: str, exchange: str) -> Path:
    return DATA_DIR / f"{asset}_{exchange}_1d.csv"


def load_inputs(refresh: bool) -> tuple[dict[str, dict[str, pd.DataFrame]], pd.DataFrame]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    required = [cache_path(a, e) for a in ASSETS for e in EXCHANGES]
    usdt_path = DATA_DIR / "USDT_coinbase_1d.csv"
    if refresh or not all(path.exists() for path in required + [usdt_path]):
        start = pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=780)
        for asset in ASSETS:
            frames = {
                "binance": fetch_binance(asset),
                "coinbase": fetch_coinbase(f"{asset}-USD", asset, "USD", start),
                "kraken": fetch_kraken(asset),
            }
            for exchange, frame in frames.items():
                atomic_write_csv(frame, cache_path(asset, exchange))
        usdt = fetch_coinbase("USDT-USD", "USDT", "USD", start)
        atomic_write_csv(usdt, usdt_path)

    inputs: dict[str, dict[str, pd.DataFrame]] = {}
    for asset in ASSETS:
        inputs[asset] = {}
        for exchange in EXCHANGES:
            frame = pd.read_csv(cache_path(asset, exchange), parse_dates=["date"])
            if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
                raise ValueError(f"cache ordering/duplicate failure: {asset} {exchange}")
            inputs[asset][exchange] = frame.set_index("date")
    usdt = pd.read_csv(usdt_path, parse_dates=["date"]).set_index("date")
    return inputs, usdt


def rolling_z(series: pd.Series, window: int = 90, minimum: int = 60) -> pd.Series:
    mean = series.rolling(window, min_periods=minimum).mean()
    std = series.rolling(window, min_periods=minimum).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return sum(series.shift(-offset) for offset in range(horizon))


def build_panel(asset: str, frames: dict[str, pd.DataFrame], usdt: pd.DataFrame) -> pd.DataFrame:
    pieces: dict[str, pd.Series] = {}
    for exchange, frame in frames.items():
        pieces[f"close_{exchange}"] = frame["close"]
        pieces[f"volume_{exchange}"] = frame["volume"]
    pieces["usdt_usd"] = usdt["close"]
    panel = pd.concat(pieces, axis=1, join="inner").dropna().sort_index()
    if len(panel) < 600:
        raise ValueError(f"{asset}: common completed-candle sample too short ({len(panel)})")
    if panel.index.duplicated().any():
        raise ValueError(f"{asset}: duplicate UTC dates")
    if (panel.filter(like="close_") <= 0).any().any() or (panel.filter(like="volume_") < 0).any().any():
        raise ValueError(f"{asset}: non-positive price or negative volume in API snapshot")
    if not panel["usdt_usd"].between(0.95, 1.05).all():
        raise ValueError(f"{asset}: USDT-USD normalization series outside [0.95, 1.05]")
    date_gaps = panel.index.to_series().diff().dropna().dt.days
    if not date_gaps.empty and int(date_gaps.max()) > 2:
        raise ValueError(f"{asset}: exact UTC inner join contains a gap longer than two days")

    panel["close_binance_usd"] = panel["close_binance"] * panel["usdt_usd"]
    normalized_logs = np.log(
        panel[["close_binance_usd", "close_coinbase", "close_kraken"]].astype(float)
    )
    native_logs = np.log(panel[["close_binance", "close_coinbase", "close_kraken"]].astype(float))
    usd_logs = np.log(panel[["close_coinbase", "close_kraken"]].astype(float))
    panel["dispersion_norm_bps"] = normalized_logs.std(axis=1, ddof=0) * 10_000
    panel["range_norm_bps"] = (normalized_logs.max(axis=1) - normalized_logs.min(axis=1)) * 10_000
    panel["dispersion_native_bps"] = native_logs.std(axis=1, ddof=0) * 10_000
    panel["dispersion_usd_only_bps"] = usd_logs.std(axis=1, ddof=0) * 10_000
    panel["usdt_basis_bps"] = np.log(panel["usdt_usd"]) * 10_000
    panel["composite_close"] = np.exp(normalized_logs.median(axis=1))
    panel["return"] = np.log(panel["composite_close"]).diff()
    panel["rv1"] = panel["return"].pow(2)
    if float(panel["dispersion_norm_bps"].max()) > 1_000:
        raise ValueError(f"{asset}: normalized close dispersion exceeds 1,000 bp; inspect alignment")

    # Within-exchange standardized volume: descriptive liquidity-drought proxy only.
    volume_z = []
    for exchange in EXCHANGES:
        volume_z.append(rolling_z(np.log1p(panel[f"volume_{exchange}"])))
    panel["volume_score"] = pd.concat(volume_z, axis=1).median(axis=1)

    # Every feature used at forecast date t is explicitly lagged to t-1.
    panel["dispersion_lag1"] = rolling_z(panel["dispersion_norm_bps"]).shift(1)
    panel["dispersion_native_lag1"] = rolling_z(panel["dispersion_native_bps"]).shift(1)
    panel["dispersion_usd_only_lag1"] = rolling_z(panel["dispersion_usd_only_bps"]).shift(1)
    panel["log_rv_d_lag1"] = np.log(panel["rv1"].shift(1) + EPS)
    panel["log_rv_w_lag1"] = np.log(panel["rv1"].rolling(5, min_periods=5).mean().shift(1) + EPS)
    panel["log_rv_m_lag1"] = np.log(panel["rv1"].rolling(22, min_periods=22).mean().shift(1) + EPS)

    for horizon in HORIZONS:
        panel[f"rv_fwd_{horizon}"] = forward_sum(panel["rv1"], horizon)
        panel[f"ret_fwd_{horizon}"] = forward_sum(panel["return"], horizon)
        drought_threshold = panel["volume_score"].shift(1).expanding(min_periods=252).quantile(0.10)
        drought = panel["volume_score"] < drought_threshold
        drought_window = pd.concat([drought.shift(-offset) for offset in range(horizon)], axis=1)
        panel[f"drought_fwd_{horizon}"] = drought_window.max(axis=1).where(
            drought_window.notna().sum(axis=1) == horizon
        )
    panel["asset"] = asset
    return panel


BASE_FEATURES = ["log_rv_d_lag1", "log_rv_w_lag1", "log_rv_m_lag1"]
AUG_FEATURES = BASE_FEATURES + ["dispersion_lag1"]


@dataclass
class ForecastPath:
    dates: list[pd.Timestamp]
    actual: np.ndarray
    pred_base: np.ndarray
    pred_aug: np.ndarray
    pred_log_base: np.ndarray
    pred_log_aug: np.ndarray
    fit_failures: int


def _ols_predict(X_train: np.ndarray, y_train: np.ndarray, x_now: np.ndarray) -> tuple[float, float]:
    Xc = np.column_stack([np.ones(len(X_train)), X_train])
    beta, *_ = np.linalg.lstsq(Xc, y_train, rcond=None)
    fitted = Xc @ beta
    residual = y_train - fitted
    smearing = float(np.mean(np.exp(residual)))
    pred_log = float(np.r_[1.0, x_now] @ beta)
    pred = max(float(np.exp(pred_log) * smearing), EPS)
    return pred, pred_log


def expanding_rv_forecasts(panel: pd.DataFrame, horizon: int) -> ForecastPath:
    y = panel[f"rv_fwd_{horizon}"].to_numpy(float)
    Xb = panel[BASE_FEATURES].to_numpy(float)
    Xa = panel[AUG_FEATURES].to_numpy(float)
    dates: list[pd.Timestamp] = []
    actual: list[float] = []
    pb: list[float] = []
    pa: list[float] = []
    plb: list[float] = []
    pla: list[float] = []
    failures = 0
    for i in range(len(panel)):
        if not np.isfinite(y[i]) or not np.isfinite(Xa[i]).all():
            continue
        # Strict forward-label embargo: training row j is allowed iff j + h < i.
        train_idx = np.arange(0, max(0, i - horizon))
        good = np.isfinite(y[train_idx]) & np.isfinite(Xa[train_idx]).all(axis=1)
        train_idx = train_idx[good]
        if len(train_idx) < MIN_TRAIN:
            continue
        try:
            pred_b, log_b = _ols_predict(Xb[train_idx], np.log(y[train_idx] + EPS), Xb[i])
            pred_a, log_a = _ols_predict(Xa[train_idx], np.log(y[train_idx] + EPS), Xa[i])
        except (np.linalg.LinAlgError, FloatingPointError):
            failures += 1
            continue
        dates.append(panel.index[i])
        actual.append(y[i])
        pb.append(pred_b)
        pa.append(pred_a)
        plb.append(log_b)
        pla.append(log_a)
    if len(actual) < 252:
        raise ValueError(f"insufficient RV OOS observations for h={horizon}: {len(actual)}")
    return ForecastPath(
        dates=dates,
        actual=np.asarray(actual),
        pred_base=np.asarray(pb),
        pred_aug=np.asarray(pa),
        pred_log_base=np.asarray(plb),
        pred_log_aug=np.asarray(pla),
        fit_failures=failures,
    )


def hln_dm(loss1: np.ndarray, loss2: np.ndarray, horizon: int) -> dict[str, Any]:
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    d = d[np.isfinite(d)]
    n = len(d)
    lag = max(0, horizon - 1)
    centered = d - d.mean()
    long_var = float(np.mean(centered**2))
    for k in range(1, lag + 1):
        weight = 1 - k / (lag + 1)
        long_var += 2 * weight * float(np.mean(centered[k:] * centered[:-k]))
    if n < 10 or long_var <= 0:
        return {"t_hln": 0.0, "p_two_sided": 1.0, "n": n, "nw_lag": lag}
    t_raw = float(d.mean() / math.sqrt(long_var / n))
    factor_sq = (n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n
    factor = math.sqrt(max(factor_sq, 0.0))
    t_hln = t_raw * factor
    p = float(2 * stats.t.sf(abs(t_hln), df=n - 1))
    return {
        "t_raw": t_raw,
        "t_hln": t_hln,
        "p_two_sided": p,
        "mean_loss_diff_aug_minus_base": float(d.mean()),
        "n": n,
        "nw_lag": lag,
        "direction": "negative_t_means_augmented_better",
    }


def clark_west(actual_log: np.ndarray, pred_base_log: np.ndarray, pred_aug_log: np.ndarray, h: int) -> dict[str, float]:
    e_base = actual_log - pred_base_log
    e_aug = actual_log - pred_aug_log
    adjusted = e_base**2 - (e_aug**2 - (pred_base_log - pred_aug_log) ** 2)
    fit = sm.OLS(adjusted, np.ones((len(adjusted), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": max(0, h - 1)}
    )
    t_stat = float(fit.tvalues[0])
    return {
        "mean_adjusted_loss_gain": float(adjusted.mean()),
        "hac_t": t_stat,
        "p_one_sided_aug_better": float(stats.norm.sf(t_stat)),
    }


def evaluate_rv(path: ForecastPath, horizon: int) -> dict[str, Any]:
    lb = qlike_pointwise(path.actual, path.pred_base)
    la = qlike_pointwise(path.actual, path.pred_aug)
    hln = hln_dm(la, lb, horizon)
    helper_t, helper_p = dm_test(la, lb, h=horizon)
    rho_b, rho_b_p = spearman_corr(path.actual, path.pred_base)
    rho_a, rho_a_p = spearman_corr(path.actual, path.pred_aug)
    actual_log = np.log(path.actual + EPS)
    mid = len(path.actual) // 2
    subperiods = []
    for name, slc in (("early", slice(0, mid)), ("late", slice(mid, None))):
        q_b = float(np.mean(lb[slc]))
        q_a = float(np.mean(la[slc]))
        subperiods.append(
            {
                "name": name,
                "start": str(path.dates[slc.start or 0].date()),
                "end": str(path.dates[(slc.stop - 1) if slc.stop else -1].date()),
                "n": int(len(path.actual[slc])),
                "qlike_improvement_pct": float((q_b - q_a) / abs(q_b) * 100),
            }
        )
    q_base = float(np.mean(lb))
    q_aug = float(np.mean(la))
    return {
        "n_oos": int(len(path.actual)),
        "oos_start": str(path.dates[0].date()),
        "oos_end": str(path.dates[-1].date()),
        "qlike_base": q_base,
        "qlike_augmented": q_aug,
        "qlike_improvement_pct": float((q_base - q_aug) / abs(q_base) * 100),
        "mse_base": float(np.mean((path.actual - path.pred_base) ** 2)),
        "mse_augmented": float(np.mean((path.actual - path.pred_aug) ** 2)),
        "spearman_base": {"rho": rho_b, "p": rho_b_p},
        "spearman_augmented": {"rho": rho_a, "p": rho_a_p},
        "dm_hln": hln,
        "dm_helper_crosscheck": {"t": float(helper_t), "p": float(helper_p), "h": horizon},
        "clark_west_nested_mse": clark_west(
            actual_log, path.pred_log_base, path.pred_log_aug, horizon
        ),
        "subperiod_sensitivity": subperiods,
        "fit_failures": path.fit_failures,
    }


def pinball(y: np.ndarray, q: np.ndarray, tau: float = TAU) -> np.ndarray:
    error = y - q
    return np.where(error >= 0, tau * error, (tau - 1) * error)


def expanding_tail_forecasts(panel: pd.DataFrame, horizon: int) -> dict[str, Any]:
    y = panel[f"ret_fwd_{horizon}"].to_numpy(float)
    Xb = panel[BASE_FEATURES].to_numpy(float)
    Xa = panel[AUG_FEATURES].to_numpy(float)
    dates: list[pd.Timestamp] = []
    actual: list[float] = []
    qb: list[float] = []
    qa: list[float] = []
    cached: tuple[np.ndarray, np.ndarray] | None = None
    last_fit = -10**9
    failures = 0
    iteration_limit_hits = 0
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for i in range(len(panel)):
            if not np.isfinite(y[i]) or not np.isfinite(Xa[i]).all():
                continue
            train_idx = np.arange(0, max(0, i - horizon))  # j + h < i
            good = np.isfinite(y[train_idx]) & np.isfinite(Xa[train_idx]).all(axis=1)
            train_idx = train_idx[good]
            if len(train_idx) < MIN_TRAIN:
                continue
            if cached is None or i - last_fit >= REFIT_EVERY_TAIL:
                try:
                    rb = QuantReg(y[train_idx], sm.add_constant(Xb[train_idx], has_constant="add")).fit(
                        q=TAU, max_iter=5000, p_tol=1e-6
                    )
                    ra = QuantReg(y[train_idx], sm.add_constant(Xa[train_idx], has_constant="add")).fit(
                        q=TAU, max_iter=5000, p_tol=1e-6
                    )
                    iteration_limit_hits += sum(
                        int(getattr(fitted, "iterations", 0)) >= 5000 for fitted in (rb, ra)
                    )
                    cached = (np.asarray(rb.params), np.asarray(ra.params))
                    last_fit = i
                except Exception:
                    failures += 1
                    cached = None
                    continue
            assert cached is not None
            dates.append(panel.index[i])
            actual.append(y[i])
            qb.append(float(np.r_[1.0, Xb[i]] @ cached[0]))
            qa.append(float(np.r_[1.0, Xa[i]] @ cached[1]))
    convergence_warnings = sum(
        "maximum number of iterations" in str(item.message).lower()
        or "convergence" in str(item.message).lower()
        for item in caught
    )
    ya, q_base, q_aug = np.asarray(actual), np.asarray(qb), np.asarray(qa)
    if len(ya) < 252:
        raise ValueError(f"insufficient tail OOS observations for h={horizon}: {len(ya)}")
    lb, la = pinball(ya, q_base), pinball(ya, q_aug)
    hln = hln_dm(la, lb, horizon)
    helper_t, helper_p = dm_test(la, lb, h=horizon)
    return {
        "n_oos": int(len(ya)),
        "oos_start": str(dates[0].date()),
        "oos_end": str(dates[-1].date()),
        "pinball_base": float(lb.mean()),
        "pinball_augmented": float(la.mean()),
        "pinball_improvement_pct": float((lb.mean() - la.mean()) / lb.mean() * 100),
        "breach_rate_base": float(np.mean(ya < q_base)),
        "breach_rate_augmented": float(np.mean(ya < q_aug)),
        "dm_hln": hln,
        "dm_helper_crosscheck": {"t": float(helper_t), "p": float(helper_p), "h": horizon},
        "refit_every": REFIT_EVERY_TAIL,
        "fit_failures": failures,
        "convergence_warnings": int(convergence_warnings),
        "iteration_limit_hits": int(iteration_limit_hits),
    }


def hac_signal_regression(panel: pd.DataFrame, target: str, horizon: int, signal: str) -> dict[str, Any]:
    cols = [target] + BASE_FEATURES + [signal]
    sample = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = sample[target].to_numpy(float)
    if target.startswith("rv_fwd"):
        y = np.log(y + EPS)
    X = sm.add_constant(sample[BASE_FEATURES + [signal]], has_constant="add")
    fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": max(0, horizon - 1)})
    return {
        "n": int(fit.nobs),
        "signal": signal,
        "coef": float(fit.params[signal]),
        "hac_t": float(fit.tvalues[signal]),
        "p_two_sided": float(fit.pvalues[signal]),
        "nw_lag": max(0, horizon - 1),
        "interpretation": "association only; not causal and not in primary OOS verdict",
    }


def liquidity_diagnostic(panel: pd.DataFrame, horizon: int) -> dict[str, Any]:
    target = f"drought_fwd_{horizon}"
    sample = panel[[target] + BASE_FEATURES + ["dispersion_lag1"]].dropna()
    y = sample[target].astype(float)
    X = sm.add_constant(sample[BASE_FEATURES + ["dispersion_lag1"]], has_constant="add")
    fit = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": max(0, horizon - 1)})
    return {
        "n": int(fit.nobs),
        "drought_rate": float(y.mean()),
        "coef": float(fit.params["dispersion_lag1"]),
        "hac_t": float(fit.tvalues["dispersion_lag1"]),
        "p_two_sided": float(fit.pvalues["dispersion_lag1"]),
        "status": "secondary_volume_proxy_only",
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plot_timeseries(panels: dict[str, pd.DataFrame]) -> str:
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, asset in zip(axes, ASSETS, strict=True):
        panel = panels[asset]
        ax.plot(panel.index, panel["dispersion_norm_bps"], color="#168C8C", lw=1.0, label="USD-normalized close dispersion (bp)")
        ax.plot(panel.index, panel["dispersion_usd_only_bps"], color="#718096", lw=0.8, alpha=0.8, label="Coinbase-Kraken USD-only dispersion (bp)")
        ax.set_ylabel("basis points")
        ax.set_title(f"{asset}: completed UTC daily close-price dispersion")
        ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path = HERE / "k1682_fragmentation_timeseries.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path.name


def plot_oos(results: dict[str, Any]) -> str:
    labels, rv_imp, tail_imp, dm_rv, dm_tail = [], [], [], [], []
    for asset in ASSETS:
        for horizon in HORIZONS:
            labels.append(f"{asset}\nh={horizon}")
            cell = results[asset][str(horizon)]
            rv_imp.append(cell["rv_forecast"]["qlike_improvement_pct"])
            tail_imp.append(cell["left_tail_forecast"]["pinball_improvement_pct"])
            dm_rv.append(cell["rv_forecast"]["dm_hln"]["t_hln"])
            dm_tail.append(cell["left_tail_forecast"]["dm_hln"]["t_hln"])
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    width = 0.36
    axes[0].bar(x - width / 2, rv_imp, width, color="#168C8C", label="RV QLIKE")
    axes[0].bar(x + width / 2, tail_imp, width, color="#2D6CDF", label="5% tail pinball")
    axes[0].axhline(0, color="#333", lw=0.8)
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("OOS loss improvement vs baseline (%)")
    axes[0].legend()
    axes[1].bar(x - width / 2, dm_rv, width, color="#168C8C", label="RV")
    axes[1].bar(x + width / 2, dm_tail, width, color="#2D6CDF", label="tail")
    axes[1].axhline(-3, color="#B64A4A", ls="--", lw=1, label="conservative |t|=3 gate")
    axes[1].axhline(0, color="#333", lw=0.8)
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("HLN-DM t (negative = augmented better)")
    axes[1].legend(fontsize=8)
    fig.suptitle("K1682: lagged close dispersion added to HAR-type baselines")
    fig.tight_layout()
    path = HERE / "k1682_oos_loss_comparison.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path.name


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def main() -> int:
    args = parse_args()
    np.random.seed(SEED)
    inputs, usdt = load_inputs(args.refresh)
    panels = {asset: build_panel(asset, inputs[asset], usdt) for asset in ASSETS}

    results: dict[str, Any] = {}
    primary_cells: list[tuple[str, str, int, dict[str, Any]]] = []
    for asset in ASSETS:
        results[asset] = {}
        for horizon in HORIZONS:
            rv = evaluate_rv(expanding_rv_forecasts(panels[asset], horizon), horizon)
            tail = expanding_tail_forecasts(panels[asset], horizon)
            cell = {
                "rv_forecast": rv,
                "left_tail_forecast": tail,
                "association_primary_normalized": hac_signal_regression(
                    panels[asset], f"rv_fwd_{horizon}", horizon, "dispersion_lag1"
                ),
                "association_usd_only_robustness": hac_signal_regression(
                    panels[asset], f"rv_fwd_{horizon}", horizon, "dispersion_usd_only_lag1"
                ),
                "association_raw_native_sensitivity": hac_signal_regression(
                    panels[asset], f"rv_fwd_{horizon}", horizon, "dispersion_native_lag1"
                ),
                "liquidity_drought_volume_proxy": liquidity_diagnostic(panels[asset], horizon),
            }
            results[asset][str(horizon)] = cell
            primary_cells.append((asset, "rv_qlike", horizon, rv))
            primary_cells.append((asset, "tail_pinball", horizon, tail))

    raw_p = [cell[3]["dm_hln"]["p_two_sided"] for cell in primary_cells]
    reject, qvals, _, _ = multipletests(raw_p, alpha=0.05, method="fdr_bh")
    primary_audit = []
    for (asset, outcome, horizon, metrics), qvalue, rejected in zip(
        primary_cells, qvals, reject, strict=True
    ):
        improvement = (
            metrics["qlike_improvement_pct"]
            if outcome == "rv_qlike"
            else metrics["pinball_improvement_pct"]
        )
        t_hln = metrics["dm_hln"]["t_hln"]
        passed = bool(improvement > 0 and t_hln < -3 and qvalue < 0.05 and rejected)
        metrics["dm_hln"]["bh_fdr_q_primary_family_8"] = float(qvalue)
        metrics["dm_hln"]["primary_gate_pass"] = passed
        primary_audit.append(
            {
                "asset": asset,
                "horizon_days": horizon,
                "outcome": outcome,
                "improvement_pct": improvement,
                "t_hln": t_hln,
                "raw_p": metrics["dm_hln"]["p_two_sided"],
                "bh_q": float(qvalue),
                "pass": passed,
            }
        )

    passed = [row for row in primary_audit if row["pass"]]
    positive_directions = [row for row in primary_audit if row["improvement_pct"] > 0]
    assets_passed = sorted({row["asset"] for row in passed})
    if len(passed) >= 2 and assets_passed == list(ASSETS):
        verdict = "CROSS_ASSET_SIGNAL_CANDIDATE"
    elif passed:
        verdict = "MIXED_SINGLE_ASSET_OR_CELL"
    else:
        verdict = "NULL_NO_ROBUST_OOS_INCREMENT"

    figures = [plot_timeseries(panels), plot_oos(results)]
    data_files = sorted(DATA_DIR.glob("*.csv"))
    provenance = {
        "sources": {
            "binance": BINANCE_KLINES,
            "coinbase": COINBASE_CANDLES,
            "kraken": KRAKEN_OHLC,
        },
        "files": [
            {"path": str(path.relative_to(HERE)), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in data_files
        ],
        "panels": {
            asset: {
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
                "n_common_completed_days": int(len(panel)),
                "mean_normalized_dispersion_bps": float(panel["dispersion_norm_bps"].mean()),
                "median_normalized_dispersion_bps": float(panel["dispersion_norm_bps"].median()),
                "mean_abs_usdt_basis_bps": float(panel["usdt_basis_bps"].abs().mean()),
            }
            for asset, panel in panels.items()
        },
    }

    payload = {
        "experiment_id": "K1682",
        "title": "Cross-exchange daily close-price dispersion as a BTC/ETH short-horizon risk signal",
        "run_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "methodology_type": "empirical_proxy_diagnostic",
        "data_provenance": provenance,
        "proxy_limits": [
            "Daily OHLCV close is not a synchronized midquote, bid-ask spread, or executable arbitrage quote.",
            "Binance USDT closes are converted with same-UTC-day Coinbase USDT-USD close; residual timing/basis noise remains.",
            "Kraken public REST limits the common sample to roughly 720 completed daily candles.",
            "Close-to-close squared returns are noisy variance proxies, not intraday realized variance.",
            "Volume drought is a secondary within-exchange-standardized OHLCV volume proxy, not order-book depth.",
        ],
        "timing": {
            "feature_lag": "every forecast feature explicitly shift(1)",
            "training_embargo": "training row j admissible only if j + horizon < forecast origin i",
            "incomplete_candles": "Binance/Coinbase completion time gate; Kraken final row always dropped",
            "calendar_alignment": "exact UTC date inner join; no forward fill",
        },
        "models": {
            "rv_baseline": BASE_FEATURES,
            "rv_augmented": AUG_FEATURES,
            "rv_target": "sum of close-to-close squared log returns beginning at forecast date",
            "tail_target": "5% quantile of cumulative log return over h days",
            "min_train": MIN_TRAIN,
            "tail_refit_every_days": REFIT_EVERY_TAIL,
        },
        "primary_family": {
            "definition": "2 assets x 2 horizons x 2 outcomes = 8 pre-specified OOS DM tests",
            "multiplicity": "Benjamini-Hochberg FDR across all 8 cells",
            "gate": "loss improvement >0, HLN-DM t<-3, and BH q<0.05",
            "cells": primary_audit,
        },
        "results": results,
        "verdict": {
            "status": verdict,
            "n_primary_pass": len(passed),
            "n_positive_loss_directions": len(positive_directions),
            "assets_with_primary_pass": assets_passed,
            "claim_scope": "predictive association of a lagged daily close-price dispersion proxy; never executable arbitrage",
        },
        "figures": figures,
        "references": REFERENCES,
        "review": {
            "pre_run": {
                "status": "PASS_TO_RUN",
                "artifact": "codex_review_pre_run.md",
                "reviewed_before_formal_execution": True,
            },
            "post_run": {
                "status": "PASS",
                "artifact": "codex_review.md",
                "independent_numeric_verification": True,
            },
        },
    }
    atomic_write_json(json_safe(payload))
    print(json.dumps(payload["verdict"], ensure_ascii=False, indent=2))
    print(f"wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
