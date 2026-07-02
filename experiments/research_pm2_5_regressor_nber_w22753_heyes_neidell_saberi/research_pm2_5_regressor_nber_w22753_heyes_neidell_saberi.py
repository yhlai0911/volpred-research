#!/usr/bin/env python3
"""
PM2.5/AQI pollution proxy as a lagged volatility regressor.

Task:
    research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi

Scope:
    This is a conservative, reproducible pilot. It uses EPA AirData county
    daily AQI for New York County as the pollution proxy and SPY daily OHLC
    data from yfinance as a daily volatility proxy. It does not claim to be a
    full replication of Heyes-Neidell-Saberian because it does not use the
    original Manhattan monitor PM2.5 concentration panel or long-history
    intraday realized variance.

Research honesty safeguards:
    - Primary pollution feature is AQI[t-1], created with signal.shift(1).
    - Forecast day t uses only market and AQI information available before t.
    - OOS comparison uses expanding-window OLS and Patton QLIKE on daily
      variance proxy.
    - Random bootstrap diagnostics use fixed seed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parent
EXPERIMENT_ID = "research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi"
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
EPA_AIRDATA_BASE = "https://aqs.epa.gov/aqsweb/airdata"
RNG_SEED = 42


@dataclass(frozen=True)
class ModelSpec:
    name: str
    cols: tuple[str, ...]


BASE_SPEC = ModelSpec(
    name="HAR_daily_proxy_plus_VIX",
    cols=(
        "log_rv_lag1",
        "log_rv_week_lag1",
        "log_rv_month_lag1",
        "log_vix_var_lag1",
        "abs_ret_lag1",
    ),
)

POLLUTION_SPEC = ModelSpec(
    name="HAR_daily_proxy_plus_VIX_plus_AQI_lag1",
    cols=BASE_SPEC.cols
    + (
        "aqi_lag1_per10",
        "pm25_defining_lag1",
        "aqi_pm25_lag1_per10",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_with_cache(url: str, dest: Path, refresh: bool = False) -> Path:
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    print(f"[download] {url}", flush=True)
    with requests.get(url, stream=True, timeout=(10, 120)) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
    tmp.replace(dest)
    return dest


def load_ny_county_aqi(
    start_year: int,
    end_year: int,
    refresh: bool = False,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        zip_path = DATA_DIR / f"daily_aqi_by_county_{year}.zip"
        url = f"{EPA_AIRDATA_BASE}/daily_aqi_by_county_{year}.zip"
        download_with_cache(url, zip_path, refresh=refresh)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if len(names) != 1:
                raise RuntimeError(f"Unexpected AirData zip contents for {year}: {names}")
            with zf.open(names[0]) as fh:
                raw = pd.read_csv(fh)

        required = {
            "State Code",
            "County Code",
            "Date",
            "AQI",
            "Category",
            "Defining Parameter",
            "Defining Site",
            "Number of Sites Reporting",
        }
        missing = required - set(raw.columns)
        if missing:
            raise RuntimeError(f"AirData {year} missing columns: {sorted(missing)}")

        ny = raw[(raw["State Code"] == 36) & (raw["County Code"] == 61)].copy()
        if ny.empty:
            raise RuntimeError(f"No New York County AQI rows in {year}")
        frames.append(ny)

    aqi = pd.concat(frames, ignore_index=True)
    aqi = aqi.rename(
        columns={
            "Date": "date",
            "AQI": "aqi",
            "Category": "category",
            "Defining Parameter": "defining_parameter",
            "Defining Site": "defining_site",
            "Number of Sites Reporting": "n_sites_reporting",
        }
    )
    aqi["date"] = pd.to_datetime(aqi["date"])
    aqi["aqi"] = pd.to_numeric(aqi["aqi"], errors="coerce")
    aqi["is_pm25_defining"] = (
        aqi["defining_parameter"].astype(str).str.upper().str.contains("PM2.5")
    )
    cols = [
        "date",
        "aqi",
        "category",
        "defining_parameter",
        "defining_site",
        "n_sites_reporting",
        "is_pm25_defining",
    ]
    aqi = aqi[cols].sort_values("date").drop_duplicates("date", keep="last")
    out = DATA_DIR / f"ny_county_daily_aqi_{start_year}_{end_year}.csv"
    aqi.to_csv(out, index=False)
    return aqi


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [col[0] for col in df.columns]
    return df


def download_market_data(
    start_year: int,
    end_year: int,
    refresh: bool = False,
) -> pd.DataFrame:
    cache = DATA_DIR / f"market_spy_vix_{start_year}_{end_year}.csv"
    if cache.exists() and not refresh:
        cached = pd.read_csv(cache, parse_dates=["date"])
        return cached.set_index("date")

    start = f"{start_year}-01-01"
    end = f"{end_year + 1}-01-10"
    spy = yf.download("SPY", start=start, end=end, auto_adjust=False, progress=False)
    vix = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False)
    spy = _flatten_yfinance_columns(spy)
    vix = _flatten_yfinance_columns(vix)
    if spy.empty or vix.empty:
        raise RuntimeError("yfinance returned empty SPY or VIX data")

    for label, df in {"SPY": spy, "VIX": vix}.items():
        required = {"Open", "High", "Low", "Close"}
        missing = required - set(df.columns)
        if missing:
            raise RuntimeError(f"{label} data missing columns: {sorted(missing)}")

    panel = pd.DataFrame(index=spy.index)
    close_for_return = spy["Adj Close"] if "Adj Close" in spy.columns else spy["Close"]
    panel["spy_open"] = spy["Open"]
    panel["spy_high"] = spy["High"]
    panel["spy_low"] = spy["Low"]
    panel["spy_close"] = spy["Close"]
    panel["spy_adj_close"] = close_for_return
    panel["vix_close"] = vix["Close"].reindex(panel.index)
    panel = panel.loc[
        (panel.index >= pd.Timestamp(f"{start_year}-01-01"))
        & (panel.index <= pd.Timestamp(f"{end_year}-12-31"))
    ].dropna()
    panel.index.name = "date"
    panel.to_csv(cache)
    return panel


def compute_market_features(market: pd.DataFrame) -> pd.DataFrame:
    df = market.copy()
    df["log_ret"] = np.log(df["spy_adj_close"] / df["spy_adj_close"].shift(1))
    log_hl = np.log(df["spy_high"] / df["spy_low"])
    log_co = np.log(df["spy_close"] / df["spy_open"])
    df["rv_parkinson"] = (log_hl**2) / (4.0 * np.log(2.0))
    df["rv_garman_klass_raw"] = 0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2
    df["rv_garman_klass"] = df["rv_garman_klass_raw"].clip(lower=1e-10)
    df["range_variance_proxy"] = log_hl**2
    df["squared_return"] = df["log_ret"] ** 2
    df["log_rv"] = np.log(df["rv_garman_klass"])
    df["log_rv_lag1"] = df["log_rv"].shift(1)
    df["log_rv_week_lag1"] = df["log_rv"].rolling(5).mean().shift(1)
    df["log_rv_month_lag1"] = df["log_rv"].rolling(22).mean().shift(1)
    vix_daily_var = ((df["vix_close"] / 100.0) ** 2) / 252.0
    df["log_vix_var_lag1"] = np.log(vix_daily_var).shift(1)
    df["abs_ret_lag1"] = df["log_ret"].abs().shift(1)
    return df


def attach_aqi_signals(market: pd.DataFrame, aqi: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    full_dates = pd.date_range(aqi["date"].min(), aqi["date"].max(), freq="D")
    cal = aqi.set_index("date").reindex(full_dates)
    cal.index.name = "date"
    cal["is_pm25_defining"] = cal["is_pm25_defining"].fillna(False).astype(bool)
    p90 = float(cal["aqi"].quantile(0.90))
    p95 = float(cal["aqi"].quantile(0.95))

    high_p90 = (cal["aqi"] >= p90).fillna(False)
    consec = high_p90.astype(int)
    cal["consecutive_p90"] = 0
    run = 0
    for dt, value in high_p90.items():
        run = run + 1 if bool(value) else 0
        cal.loc[dt, "consecutive_p90"] = run

    # The explicit signal.shift(1) block is the lookahead guard: market day t
    # gets only the previous calendar day's AQI summary.
    cal["aqi_signal"] = cal["aqi"].shift(1)
    cal["pm25_defining_signal"] = cal["is_pm25_defining"].astype(float).shift(1)
    cal["aqi_pm25_signal"] = (cal["aqi"] * cal["is_pm25_defining"].astype(float)).shift(1)
    cal["high_aqi_150_signal"] = (cal["aqi"] >= 150).astype(float).shift(1)
    cal["high_aqi_p90_signal"] = (cal["aqi"] >= p90).astype(float).shift(1)
    cal["high_aqi_p95_signal"] = (cal["aqi"] >= p95).astype(float).shift(1)
    cal["consecutive_p90_signal"] = (cal["consecutive_p90"] >= 2).astype(float).shift(1)

    signals = cal[
        [
            "aqi_signal",
            "pm25_defining_signal",
            "aqi_pm25_signal",
            "high_aqi_150_signal",
            "high_aqi_p90_signal",
            "high_aqi_p95_signal",
            "consecutive_p90_signal",
        ]
    ].rename(
        columns={
            "aqi_signal": "aqi_lag1",
            "pm25_defining_signal": "pm25_defining_lag1",
            "aqi_pm25_signal": "aqi_pm25_lag1",
            "high_aqi_150_signal": "high_aqi_150_lag1",
            "high_aqi_p90_signal": "high_aqi_p90_lag1",
            "high_aqi_p95_signal": "high_aqi_p95_lag1",
            "consecutive_p90_signal": "consec_p90_lag1",
        }
    )

    panel = market.join(signals, how="left")
    panel["aqi_lag1_per10"] = panel["aqi_lag1"] / 10.0
    panel["aqi_pm25_lag1_per10"] = panel["aqi_pm25_lag1"] / 10.0
    panel["pm25_defining_lag1"] = panel["pm25_defining_lag1"].fillna(0.0)
    for col in [
        "high_aqi_150_lag1",
        "high_aqi_p90_lag1",
        "high_aqi_p95_lag1",
        "consec_p90_lag1",
    ]:
        panel[col] = panel[col].fillna(0.0)

    diagnostics = {
        "aqi_p90": p90,
        "aqi_p95": p95,
        "calendar_days": int(len(cal)),
        "calendar_days_with_aqi": int(cal["aqi"].notna().sum()),
        "calendar_missing_aqi": int(cal["aqi"].isna().sum()),
        "pm25_defining_share_calendar": float(cal["is_pm25_defining"].mean()),
        "days_aqi_ge_150_calendar": int((cal["aqi"] >= 150).sum()),
        "days_aqi_ge_p90_calendar": int((cal["aqi"] >= p90).sum()),
    }
    return panel, diagnostics


def model_frame(panel: pd.DataFrame) -> pd.DataFrame:
    required = (
        "rv_garman_klass",
        "log_rv",
        "log_ret",
        *POLLUTION_SPEC.cols,
        "high_aqi_150_lag1",
        "high_aqi_p90_lag1",
        "high_aqi_p95_lag1",
        "consec_p90_lag1",
        "range_variance_proxy",
    )
    df = panel.dropna(subset=list(required)).copy()
    df = df[np.isfinite(df[list(required)]).all(axis=1)]
    return df


def fit_hac_ols(df: pd.DataFrame, y_col: str, cols: Iterable[str], maxlags: int = 5):
    X = sm.add_constant(df[list(cols)], has_constant="add")
    y = df[y_col]
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})


def summarize_regression(result, cols: Iterable[str]) -> dict:
    summary = {}
    for col in ("const", *cols):
        if col not in result.params.index:
            continue
        summary[col] = {
            "coef": float(result.params[col]),
            "std_err_hac": float(result.bse[col]),
            "t_hac": float(result.tvalues[col]),
            "p_hac": float(result.pvalues[col]),
        }
    return summary


def expanding_oos(
    df: pd.DataFrame,
    base_spec: ModelSpec,
    pollution_spec: ModelSpec,
    oos_start_year: int,
    min_train: int = 500,
) -> pd.DataFrame:
    rows: list[dict] = []
    y_col = "log_rv"
    start_pos = max(min_train, int(np.searchsorted(df.index.values, np.datetime64(f"{oos_start_year}-01-01"))))

    for pos in range(start_pos, len(df)):
        current = df.iloc[[pos]]
        train = df.iloc[:pos]
        if train[list(pollution_spec.cols) + [y_col]].dropna().shape[0] < min_train:
            continue

        base_fit = sm.OLS(
            train[y_col],
            sm.add_constant(train[list(base_spec.cols)], has_constant="add"),
        ).fit()
        poll_fit = sm.OLS(
            train[y_col],
            sm.add_constant(train[list(pollution_spec.cols)], has_constant="add"),
        ).fit()

        base_x = sm.add_constant(current[list(base_spec.cols)], has_constant="add")
        poll_x = sm.add_constant(current[list(pollution_spec.cols)], has_constant="add")
        base_log = float(base_fit.predict(base_x).iloc[0])
        poll_log = float(poll_fit.predict(poll_x).iloc[0])
        actual = float(current["rv_garman_klass"].iloc[0])
        rows.append(
            {
                "date": current.index[0],
                "actual_rv": actual,
                "base_pred_rv": float(np.exp(np.clip(base_log, -30, 0))),
                "pollution_pred_rv": float(np.exp(np.clip(poll_log, -30, 0))),
                "aqi_lag1": float(current["aqi_lag1"].iloc[0]),
                "pm25_defining_lag1": float(current["pm25_defining_lag1"].iloc[0]),
            }
        )

    return pd.DataFrame(rows).set_index("date")


def qlike_pointwise(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
    f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
    ratio = a / f
    return ratio - np.log(ratio) - 1.0


def dm_hac(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> tuple[float, float]:
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    mean = float(np.mean(d))
    max_lag = max(1, min(int(math.ceil((h ** (1 / 3)) * (n ** (1 / 3)))), n // 4))
    centered = d - mean
    gamma0 = float(np.mean(centered**2))
    var = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        gamma = float(np.mean(centered[lag:] * centered[:-lag]))
        var += 2.0 * weight * gamma
    if var <= 0:
        return 0.0, 1.0
    se = math.sqrt(var / n)
    if se <= 1e-15:
        return 0.0, 1.0
    t_stat = mean / se
    p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def bootstrap_diff_ci(
    event_values: np.ndarray,
    control_values: np.ndarray,
    reps: int = 2000,
    seed: int = RNG_SEED,
) -> dict:
    event = np.asarray(event_values, dtype=float)
    control = np.asarray(control_values, dtype=float)
    event = event[np.isfinite(event)]
    control = control[np.isfinite(control)]
    if len(event) < 2 or len(control) < 2:
        return {"n_event": int(len(event)), "n_control": int(len(control)), "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    diffs = np.empty(reps)
    for i in range(reps):
        e = rng.choice(event, size=len(event), replace=True)
        c = rng.choice(control, size=len(control), replace=True)
        diffs[i] = float(np.mean(e) - np.mean(c))
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    return {
        "n_event": int(len(event)),
        "n_control": int(len(control)),
        "mean_event": float(np.mean(event)),
        "mean_control": float(np.mean(control)),
        "mean_diff": float(np.mean(event) - np.mean(control)),
        "ci95": [float(lo), float(hi)],
        "seed": seed,
        "reps": reps,
    }


def event_diagnostics(df: pd.DataFrame) -> dict:
    diagnostics: dict[str, dict] = {}
    for event_col in [
        "high_aqi_150_lag1",
        "high_aqi_p90_lag1",
        "high_aqi_p95_lag1",
        "consec_p90_lag1",
        "pm25_defining_lag1",
    ]:
        event_mask = df[event_col].astype(float) > 0.5
        entry: dict[str, dict] = {}
        for target in ["rv_garman_klass", "range_variance_proxy", "log_ret"]:
            event_values = df.loc[event_mask, target].to_numpy()
            control_values = df.loc[~event_mask, target].to_numpy()
            boot = bootstrap_diff_ci(event_values, control_values)
            if boot["n_event"] >= 5 and boot["n_control"] >= 5:
                t_stat, p_val = stats.ttest_ind(
                    event_values,
                    control_values,
                    equal_var=False,
                    nan_policy="omit",
                )
                boot["welch_t"] = float(t_stat)
                boot["welch_p"] = float(p_val)
            else:
                boot["welch_t"] = None
                boot["welch_p"] = None
                boot["note"] = "underpowered: fewer than 5 event or control observations"
            entry[target] = boot
        diagnostics[event_col] = entry
    return diagnostics


def make_figures(df: pd.DataFrame, oos: pd.DataFrame, reg_summary: dict) -> list[str]:
    paths: list[str] = []

    fig, ax1 = plt.subplots(figsize=(10, 4.8))
    ax1.plot(df.index, df["aqi_lag1"], color="#466fb3", linewidth=1.0, label="AQI lag1")
    ax1.axhline(reg_summary["aqi_thresholds"]["aqi_p90"], color="#466fb3", linestyle="--", alpha=0.5)
    ax1.set_ylabel("New York County AQI[t-1]")
    ax2 = ax1.twinx()
    ax2.plot(df.index, np.sqrt(df["rv_garman_klass"] * 252.0) * 100.0, color="#b34d4a", linewidth=1.0, alpha=0.75, label="SPY daily proxy vol")
    ax2.set_ylabel("SPY GK proxy vol, annualized %")
    ax1.set_title("Lagged AQI and SPY Daily Volatility Proxy")
    ax1.grid(True, alpha=0.25)
    fig.tight_layout()
    out = FIG_DIR / "aqi_lag1_vs_spy_proxy_vol.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    paths.append(str(out.relative_to(ROOT)))

    if not oos.empty:
        base_loss = qlike_pointwise(oos["actual_rv"], oos["base_pred_rv"])
        poll_loss = qlike_pointwise(oos["actual_rv"], oos["pollution_pred_rv"])
        cum_diff = np.cumsum(base_loss - poll_loss)
        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(oos.index, cum_diff, color="#2d7f5e", linewidth=1.3)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title("OOS Cumulative QLIKE Advantage: AQI Add-on vs Base")
        ax.set_ylabel("Cumulative base loss - AQI-add-on loss")
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        out = FIG_DIR / "oos_cumulative_qlike_advantage.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        paths.append(str(out.relative_to(ROOT)))

    pollution_terms = ["aqi_lag1_per10", "pm25_defining_lag1", "aqi_pm25_lag1_per10"]
    coefs = []
    for term in pollution_terms:
        item = reg_summary["pollution_model"]["coefficients"].get(term)
        if not item:
            continue
        coefs.append((term, item["coef"], item["std_err_hac"]))
    if coefs:
        labels, vals, ses = zip(*coefs)
        fig, ax = plt.subplots(figsize=(8, 4.2))
        ax.bar(range(len(vals)), vals, yerr=[1.96 * s for s in ses], color="#6b7f3b", alpha=0.85)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_title("HAC Coefficients for Lagged AQI Add-on Terms")
        ax.set_ylabel("Coefficient on log daily variance proxy")
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        out = FIG_DIR / "pollution_coefficients_hac.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        paths.append(str(out.relative_to(ROOT)))

    return paths


def infer_verdict(oos_summary: dict, residual_summary: dict) -> str:
    dm_t = oos_summary.get("dm_t_pollution_vs_base")
    improvement = oos_summary.get("qlike_improvement_pct")
    resid_p = (
        residual_summary.get("coefficients", {})
        .get("aqi_lag1_per10", {})
        .get("p_hac")
    )
    if dm_t is not None and improvement is not None and improvement > 0 and abs(dm_t) >= 3:
        return "CONDITIONAL_PASS"
    if resid_p is not None and resid_p < 0.05 and improvement is not None and improvement > 0:
        return "MIXED"
    return "NULL"


def run(args: argparse.Namespace) -> dict:
    ensure_dirs()
    aqi = load_ny_county_aqi(args.start_year, args.end_year, refresh=args.refresh)
    market = download_market_data(args.start_year, args.end_year, refresh=args.refresh)
    market = compute_market_features(market)
    panel, aqi_diag = attach_aqi_signals(market, aqi)
    df = model_frame(panel)
    panel_out = DATA_DIR / f"model_panel_{args.start_year}_{args.end_year}.csv"
    df.to_csv(panel_out)

    base_fit = fit_hac_ols(df, "log_rv", BASE_SPEC.cols)
    pollution_fit = fit_hac_ols(df, "log_rv", POLLUTION_SPEC.cols)

    base_residual = pd.Series(base_fit.resid, index=df.index, name="base_residual")
    residual_df = pd.concat([base_residual, df[list(POLLUTION_SPEC.cols[-3:])]], axis=1).dropna()
    residual_fit = fit_hac_ols(
        residual_df.rename(columns={"base_residual": "target"}),
        "target",
        POLLUTION_SPEC.cols[-3:],
    )

    oos = expanding_oos(
        df,
        BASE_SPEC,
        POLLUTION_SPEC,
        oos_start_year=args.oos_start_year,
        min_train=args.min_train,
    )
    if not oos.empty:
        oos_out = DATA_DIR / f"oos_forecasts_{args.start_year}_{args.end_year}.csv"
        oos.to_csv(oos_out)
        base_loss = qlike_pointwise(oos["actual_rv"], oos["base_pred_rv"])
        pollution_loss = qlike_pointwise(oos["actual_rv"], oos["pollution_pred_rv"])
        dm_t, dm_p = dm_hac(pollution_loss, base_loss, h=1)
        base_mean = float(np.mean(base_loss))
        pollution_mean = float(np.mean(pollution_loss))
        oos_summary = {
            "oos_start": str(oos.index.min().date()),
            "oos_end": str(oos.index.max().date()),
            "n_oos": int(len(oos)),
            "base_qlike": base_mean,
            "pollution_qlike": pollution_mean,
            "qlike_improvement_pct": float((base_mean - pollution_mean) / base_mean * 100.0),
            "dm_t_pollution_vs_base": dm_t,
            "dm_p_pollution_vs_base": dm_p,
            "dm_direction_note": "negative t means AQI add-on lower QLIKE than base",
        }
    else:
        oos_summary = {"n_oos": 0, "note": "No OOS forecasts generated"}

    reg_summary = {
        "base_model": {
            "name": BASE_SPEC.name,
            "target": "log(rv_garman_klass)",
            "nobs": int(base_fit.nobs),
            "r2": float(base_fit.rsquared),
            "coefficients": summarize_regression(base_fit, BASE_SPEC.cols),
        },
        "pollution_model": {
            "name": POLLUTION_SPEC.name,
            "target": "log(rv_garman_klass)",
            "nobs": int(pollution_fit.nobs),
            "r2": float(pollution_fit.rsquared),
            "delta_r2_vs_base": float(pollution_fit.rsquared - base_fit.rsquared),
            "coefficients": summarize_regression(pollution_fit, POLLUTION_SPEC.cols),
        },
        "vix_controlled_residual_model": {
            "target": "base HAR+VIX residual",
            "nobs": int(residual_fit.nobs),
            "r2": float(residual_fit.rsquared),
            "coefficients": summarize_regression(residual_fit, POLLUTION_SPEC.cols[-3:]),
        },
        "aqi_thresholds": {
            "aqi_p90": aqi_diag["aqi_p90"],
            "aqi_p95": aqi_diag["aqi_p95"],
        },
    }

    events = event_diagnostics(df)
    figures = make_figures(df, oos, reg_summary)
    verdict = infer_verdict(oos_summary, reg_summary["vix_controlled_residual_model"])

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": utc_now(),
        "verdict": verdict,
        "title": "Lagged New York County AQI as an add-on volatility regressor for SPY daily variance proxy",
        "data": {
            "pollution_source": "US EPA AirData daily_aqi_by_county pre-generated zip files",
            "pollution_url_template": f"{EPA_AIRDATA_BASE}/daily_aqi_by_county_<YEAR>.zip",
            "market_source": "yfinance SPY and ^VIX daily OHLC",
            "start_year": args.start_year,
            "end_year": args.end_year,
            "market_trading_days_raw": int(len(market)),
            "model_observations": int(len(df)),
            "effective_start_date": str(df.index.min().date()),
            "effective_end_date": str(df.index.max().date()),
            "aqi_diagnostics": aqi_diag,
            "saved_files": {
                "ny_county_aqi_csv": str((DATA_DIR / f"ny_county_daily_aqi_{args.start_year}_{args.end_year}.csv").relative_to(ROOT)),
                "market_csv": str((DATA_DIR / f"market_spy_vix_{args.start_year}_{args.end_year}.csv").relative_to(ROOT)),
                "model_panel_csv": str(panel_out.relative_to(ROOT)),
            },
        },
        "method": {
            "primary_target": "SPY daily Garman-Klass variance proxy from daily OHLC",
            "base_model": BASE_SPEC.name,
            "add_on": "AQI[t-1]/10, PM2.5-defining indicator[t-1], and interaction",
            "lookahead_guard": "AQI signals are created with signal.shift(1); market HAR/VIX features are shifted by one trading day.",
            "oos": "Expanding-window OLS. Forecast day t uses only rows before t.",
            "inference": "Statsmodels OLS with HAC covariance (maxlags=5); OOS QLIKE DM-HAC h=1.",
            "random_seed": RNG_SEED,
        },
        "regressions": reg_summary,
        "oos": oos_summary,
        "event_diagnostics": events,
        "figures": figures,
        "limitations": [
            "Uses county daily AQI, not monitor-level PM2.5 concentration; AQI is a public-health index and can be defined by ozone or other pollutants.",
            "Uses daily Garman-Klass/range variance proxies, not long-history 5-minute realized variance or bid-ask spread.",
            "No weather, traffic, macro-news, or wildfire-specific controls; results are only a volatility-prediction pilot.",
            "Sample starts in 2020, so COVID and 2023 wildfire regimes are part of the sample and should not be over-generalized.",
            "High AQI >=150 events are rare in New York County; event-test power is limited.",
        ],
        "references": [
            {
                "title": "Heyes, Neidell, and Saberian (2016), NBER w22753",
                "url": "https://www.nber.org/papers/w22753",
            },
            {
                "title": "Kiihamaki, Korhonen, and Jaakkola (2021), Scientific Reports",
                "url": "https://www.nature.com/articles/s41598-021-88041-w",
            },
            {
                "title": "Meyer and Pagel (2017), NBER w24048",
                "url": "https://www.nber.org/papers/w24048",
            },
            {
                "title": "US EPA AirData pre-generated data files",
                "url": "https://aqs.epa.gov/aqsweb/airdata/download_files.html",
            },
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--oos-start-year", type=int, default=2023)
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--refresh", action="store_true", help="redownload EPA/yfinance data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be >= --start-year")
    results = run(args)
    print(json.dumps({
        "experiment_id": results["experiment_id"],
        "verdict": results["verdict"],
        "model_observations": results["data"]["model_observations"],
        "oos": results["oos"],
        "results_path": str(RESULTS_PATH),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
