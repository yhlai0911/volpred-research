#!/usr/bin/env python3
"""California wildfire / drought public-proxy dose-response experiment.

Question:
    Do California wildfire and Western drought physical-risk proxies produce a
    monotone post-event volatility response in West-coast utilities or
    agriculture ETFs?

Lookahead policy:
    - CAL FIRE final acreage is used only as an ex-post physical dose in an
      event-study diagnostic, not as a tradable real-time signal.
    - Wildfire market targets start on the first trading day strictly after the
      alarm date.
    - USDM weekly drought maps are assumed observable two calendar days after
      validStart, then shifted one trading day before entering regressions.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_etf_dose_response"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
PRICE_CACHE = DATA_DIR / "price_adjusted_close.csv"
FIRE_RAW_CACHE = DATA_DIR / "calfire_fire_perimeters_raw.csv"
FIRE_DAILY_CACHE = DATA_DIR / "calfire_fire_daily.csv"
USDM_CACHE = DATA_DIR / "usdm_california_weekly.csv"
EVENT_PANEL_CACHE = DATA_DIR / "wildfire_event_panel.csv"
DROUGHT_PANEL_CACHE = DATA_DIR / "drought_regression_panel.csv"
FIG_PATH = FIG_DIR / "physical_risk_dose_response_summary.png"

SEED = 42
EPS = 1.0e-12
START_DATE = "2011-01-01"
END_DATE = "2026-07-03"
HORIZONS = [5, 22]
BOOT_REPS = 5000

UTILITY_TICKERS = ["PCG", "EIX", "SRE"]
UTILITY_CONTROL = "XLU"
AG_TICKERS = ["DBA", "CORN", "WEAT"]
MARKET_TICKER = "SPY"
TICKERS = UTILITY_TICKERS + [UTILITY_CONTROL] + AG_TICKERS + [MARKET_TICKER]

CALFIRE_CSV_URL = (
    "https://gis.data.cnra.ca.gov/api/download/v1/items/"
    "c3c10388e3b24cec8a954ba10458039d/csv?layers=0"
)
USDM_CA_URL = (
    "https://usdmdataservices.unl.edu/api/StateStatistics/"
    "GetDroughtSeverityStatisticsByAreaPercent"
)

LITERATURE_AND_DATA_CONTEXT = [
    {
        "citation": "U.S. Drought Monitor web services",
        "url": "https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx",
        "role": "Weekly California drought categories and DSCI-style severity proxy.",
    },
    {
        "citation": "CAL FIRE California Fire Perimeters (all)",
        "url": "https://data.ca.gov/dataset/california-fire-perimeters-all",
        "role": "Historical California wildfire alarm dates and final GIS-calculated acres.",
    },
    {
        "citation": "PNNL (2025), Wildfire Risk: Review of Utility Industry Trends",
        "url": "https://www.pnnl.gov/sites/default/files/media/file/Wildfire%20Risk%20Review%20of%20Utility%20Industry%20Trends_PNNL_July%202025.pdf",
        "role": "Context that wildfire mitigation/liability risk feeds into utility business risk.",
    },
    {
        "citation": "Global vulnerability of agricultural commodities to climate risk",
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S0313592623002217",
        "role": "Motivates drought/agricultural commodity risk channel; this run uses ETF proxies only.",
    },
]


@dataclass(frozen=True)
class FireDoseResult:
    target: str
    horizon: int
    n_events: int
    beta_log_acres: float
    t_log_acres: float
    p_log_acres: float
    low_tercile_mean: float | None
    mid_tercile_mean: float | None
    high_tercile_mean: float | None
    high_minus_low: float | None
    bootstrap_ci95_high_minus_low: list[float] | None
    monotone_positive: bool
    gate_pass: bool


@dataclass(frozen=True)
class DroughtResult:
    group: str
    target: str
    horizon: int
    n_obs: int
    beta_dsci_lag1: float
    t_dsci_lag1: float
    p_dsci_lag1: float
    beta_delta4w_lag1: float
    t_delta4w_lag1: float
    p_delta4w_lag1: float
    high_minus_low_target: float
    high_low_welch_t: float
    high_low_welch_p: float
    level_gate_pass: bool
    delta4w_gate_pass: bool
    gate_pass: bool


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_prices(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if PRICE_CACHE.exists() and not refresh:
        return pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date").sort_index()
    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        levels = [set(raw.columns.get_level_values(i)) for i in range(raw.columns.nlevels)]
        if "Close" in levels[-1]:
            close = raw.xs("Close", axis=1, level=-1).copy()
        else:
            close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = [TICKERS[0]]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.loc[:, [ticker for ticker in TICKERS if ticker in close.columns]].dropna(how="all")
    close.to_csv(PRICE_CACHE, index_label="Date")
    return close


def fetch_calfire(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_dirs()
    if FIRE_RAW_CACHE.exists() and FIRE_DAILY_CACHE.exists() and not refresh:
        raw = pd.read_csv(FIRE_RAW_CACHE, parse_dates=["alarm_date"])
        daily = pd.read_csv(FIRE_DAILY_CACHE, parse_dates=["alarm_date"]).set_index("alarm_date")
        return raw, daily

    raw_full = pd.read_csv(CALFIRE_CSV_URL)
    raw = pd.DataFrame(
        {
            "year": pd.to_numeric(raw_full["Year"], errors="coerce"),
            "fire_name": raw_full["Fire Name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip(),
            "agency": raw_full["Agency"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip(),
            "alarm_date": pd.to_datetime(
                raw_full["Alarm Date"],
                format="%m/%d/%Y %I:%M:%S %p",
                errors="coerce",
            ).dt.normalize(),
            "acres": pd.to_numeric(raw_full["GIS Calculated Acres"], errors="coerce"),
        }
    )
    raw = raw.dropna(subset=["alarm_date", "acres"])
    raw = raw[(raw["alarm_date"] >= START_DATE) & (raw["alarm_date"] < END_DATE) & (raw["acres"] > 0)]
    raw = raw.sort_values(["alarm_date", "acres"], ascending=[True, False])
    daily = raw.groupby("alarm_date").agg(
        fire_count=("acres", "size"),
        acres_total=("acres", "sum"),
        max_fire_acres=("acres", "max"),
        large_fire_count=("acres", lambda x: int((x >= 5000).sum())),
        very_large_fire_count=("acres", lambda x: int((x >= 50000).sum())),
    )
    daily["log1p_acres_total"] = np.log1p(daily["acres_total"])
    raw.to_csv(FIRE_RAW_CACHE, index=False)
    daily.to_csv(FIRE_DAILY_CACHE, index_label="alarm_date")
    return raw, daily


def fetch_usdm(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if USDM_CACHE.exists() and not refresh:
        return pd.read_csv(USDM_CACHE, parse_dates=["valid_start", "valid_end", "release_date"]).sort_values("valid_start")
    params = {
        "aoi": "06",
        "startdate": "1/1/2011",
        "enddate": "7/3/2026",
        "statisticsType": "1",
    }
    response = requests.get(USDM_CA_URL, params=params, headers={"Accept": "application/json"}, timeout=60)
    response.raise_for_status()
    data = response.json()
    frame = pd.DataFrame(data)
    frame = frame.rename(
        columns={
            "validStart": "valid_start",
            "validEnd": "valid_end",
            "stateAbbreviation": "state",
        }
    )
    for col in ["d0", "d1", "d2", "d3", "d4", "none"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["valid_start"] = pd.to_datetime(frame["valid_start"]).dt.normalize()
    frame["valid_end"] = pd.to_datetime(frame["valid_end"]).dt.normalize()
    frame["release_date"] = frame["valid_start"] + pd.Timedelta(days=2)
    # USDM traditional D0-D4 columns are cumulative area percentages at or
    # above each category. The DSCI-style score is therefore the sum of those
    # cumulative percentages, bounded by 0..500.
    frame["dsci"] = frame["d0"] + frame["d1"] + frame["d2"] + frame["d3"] + frame["d4"]
    frame["severe_dose"] = (frame["d2"] + 2 * frame["d3"] + 3 * frame["d4"]) / 100.0
    frame = frame.sort_values("valid_start")
    frame.to_csv(USDM_CACHE, index=False)
    return frame


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def build_market_panels(close: pd.DataFrame, drought_weekly: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close / close.shift(1))
    utility_names = [ticker for ticker in UTILITY_TICKERS if ticker in ret.columns]
    ag_names = [ticker for ticker in AG_TICKERS if ticker in ret.columns]
    utility_excess = ret[utility_names].sub(ret[UTILITY_CONTROL], axis=0)
    utility_basket = utility_excess.mean(axis=1)
    ag_excess = ret[ag_names].mean(axis=1) - ret[MARKET_TICKER]
    market_rv = ret[MARKET_TICKER].pow(2)

    panel = pd.DataFrame(index=close.index)
    panel["utility_rv_daily"] = utility_basket.pow(2)
    panel["utility_downside_daily"] = utility_basket.clip(upper=0).pow(2)
    panel["ag_rv_daily"] = ag_excess.pow(2)
    panel["ag_downside_daily"] = ag_excess.clip(upper=0).pow(2)
    panel["market_log_rv21_lag1"] = np.log(market_rv.rolling(21, min_periods=21).sum().shift(1) + EPS)

    release = drought_weekly[["release_date", "dsci", "severe_dose", "d2", "d3", "d4"]].sort_values("release_date")
    release = release.assign(date=pd.to_datetime(release["release_date"]).dt.normalize().astype("datetime64[ns]"))
    left_dates = pd.to_datetime(panel.index).normalize().astype("datetime64[ns]")
    aligned = pd.merge_asof(
        pd.DataFrame({"date": left_dates}),
        release.drop(columns=["release_date"]),
        on="date",
        direction="backward",
    ).set_index("date")
    panel[["dsci", "severe_dose", "d2", "d3", "d4"]] = aligned[["dsci", "severe_dose", "d2", "d3", "d4"]]
    panel["dsci_lag1"] = panel["dsci"].shift(1)
    panel["severe_dose_lag1"] = panel["severe_dose"].shift(1)
    panel["dsci_delta4w_lag1"] = panel["dsci"].diff(20).shift(1)

    for group in ["utility", "ag"]:
        for target in ["rv", "downside"]:
            daily = panel[f"{group}_{target}_daily"]
            for horizon in HORIZONS:
                panel[f"{group}_{target}_{horizon}d"] = forward_sum(daily, horizon)
                panel[f"{group}_{target}_past63_{horizon}d"] = daily.rolling(63, min_periods=42).mean().shift(6) * horizon
                panel[f"{group}_{target}_logpast63_{horizon}d"] = np.log(panel[f"{group}_{target}_past63_{horizon}d"] + EPS)
    return panel


def next_trading_day(trading_index: pd.Index, date: pd.Timestamp) -> pd.Timestamp | None:
    pos = trading_index.searchsorted(date + pd.Timedelta(days=1), side="left")
    if pos >= len(trading_index):
        return None
    return pd.Timestamp(trading_index[pos])


def build_fire_event_panel(fire_daily: pd.DataFrame, market_panel: pd.DataFrame) -> pd.DataFrame:
    trading_index = market_panel.index
    rows: list[dict[str, Any]] = []
    events = fire_daily[fire_daily["acres_total"] >= 5000].copy()
    for alarm_date, event in events.iterrows():
        trade_date = next_trading_day(trading_index, pd.Timestamp(alarm_date))
        if trade_date is None:
            continue
        row: dict[str, Any] = {
            "alarm_date": pd.Timestamp(alarm_date),
            "trade_date": trade_date,
            "acres_total": float(event["acres_total"]),
            "log1p_acres_total": float(event["log1p_acres_total"]),
            "fire_count": int(event["fire_count"]),
            "large_fire_count": int(event["large_fire_count"]),
            "very_large_fire_count": int(event["very_large_fire_count"]),
        }
        for horizon in HORIZONS:
            for target in ["rv", "downside"]:
                fwd = market_panel.loc[trade_date, f"utility_{target}_{horizon}d"]
                base = market_panel.loc[trade_date, f"utility_{target}_past63_{horizon}d"]
                row[f"utility_{target}_logratio_{horizon}d"] = float(np.log((fwd + EPS) / (base + EPS)))
        rows.append(row)
    panel = pd.DataFrame(rows).sort_values("trade_date")
    panel.to_csv(EVENT_PANEL_CACHE, index=False)
    return panel


def bootstrap_ci(values: np.ndarray, labels: np.ndarray) -> list[float] | None:
    high = values[labels == "high"]
    low = values[labels == "low"]
    if len(high) < 5 or len(low) < 5:
        return None
    rng = np.random.default_rng(SEED)
    diffs = np.empty(BOOT_REPS)
    for i in range(BOOT_REPS):
        diffs[i] = rng.choice(high, len(high), replace=True).mean() - rng.choice(low, len(low), replace=True).mean()
    return [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))]


def fire_dose_tests(event_panel: pd.DataFrame) -> list[FireDoseResult]:
    results: list[FireDoseResult] = []
    for horizon in HORIZONS:
        for target in ["rv", "downside"]:
            col = f"utility_{target}_logratio_{horizon}d"
            df = event_panel[[col, "log1p_acres_total"]].replace([np.inf, -np.inf], np.nan).dropna().copy()
            if len(df) < 20:
                continue
            fit = sm.OLS(df[col], sm.add_constant(df["log1p_acres_total"])).fit(cov_type="HC3")
            beta = float(fit.params["log1p_acres_total"])
            t_stat = float(fit.tvalues["log1p_acres_total"])
            p_val = float(fit.pvalues["log1p_acres_total"])
            labels = pd.qcut(df["log1p_acres_total"], q=3, labels=["low", "mid", "high"], duplicates="drop")
            grouped = df.groupby(labels, observed=True)[col].mean()
            low = float(grouped.get("low", np.nan)) if "low" in grouped.index else None
            mid = float(grouped.get("mid", np.nan)) if "mid" in grouped.index else None
            high = float(grouped.get("high", np.nan)) if "high" in grouped.index else None
            ci = bootstrap_ci(df[col].to_numpy(), labels.astype(str).to_numpy())
            high_minus_low = high - low if high is not None and low is not None else None
            monotone = bool(high is not None and mid is not None and low is not None and high > mid > low)
            gate = bool(beta > 0 and t_stat >= 3.0 and monotone and ci is not None and ci[0] > 0)
            results.append(
                FireDoseResult(
                    target=f"utility_{target}",
                    horizon=horizon,
                    n_events=int(len(df)),
                    beta_log_acres=beta,
                    t_log_acres=t_stat,
                    p_log_acres=p_val,
                    low_tercile_mean=low,
                    mid_tercile_mean=mid,
                    high_tercile_mean=high,
                    high_minus_low=high_minus_low,
                    bootstrap_ci95_high_minus_low=ci,
                    monotone_positive=monotone,
                    gate_pass=gate,
                )
            )
    return results


def drought_tests(panel: pd.DataFrame) -> list[DroughtResult]:
    panel.to_csv(DROUGHT_PANEL_CACHE, index_label="Date")
    results: list[DroughtResult] = []
    for group in ["utility", "ag"]:
        for target in ["rv", "downside"]:
            for horizon in HORIZONS:
                y_col = f"{group}_{target}_{horizon}d"
                x_cols = ["dsci_lag1", "dsci_delta4w_lag1", f"{group}_{target}_logpast63_{horizon}d", "market_log_rv21_lag1"]
                df = panel[[y_col] + x_cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
                df = df[df[y_col] > 0]
                y = np.log(df[y_col] + EPS)
                x = sm.add_constant(df[x_cols], has_constant="add")
                fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": max(1, horizon - 1)})
                q75 = df["dsci_lag1"].quantile(0.75)
                q25 = df["dsci_lag1"].quantile(0.25)
                high_vals = df.loc[df["dsci_lag1"] >= q75, y_col]
                low_vals = df.loc[df["dsci_lag1"] <= q25, y_col]
                ttest = sm.stats.ttest_ind(high_vals.to_numpy(), low_vals.to_numpy(), usevar="unequal")
                level_gate = bool(float(fit.params["dsci_lag1"]) > 0 and float(fit.tvalues["dsci_lag1"]) >= 3.0)
                delta_gate = bool(
                    float(fit.params["dsci_delta4w_lag1"]) > 0
                    and float(fit.tvalues["dsci_delta4w_lag1"]) >= 3.0
                )
                results.append(
                    DroughtResult(
                        group=group,
                        target=target,
                        horizon=horizon,
                        n_obs=int(len(df)),
                        beta_dsci_lag1=float(fit.params["dsci_lag1"]),
                        t_dsci_lag1=float(fit.tvalues["dsci_lag1"]),
                        p_dsci_lag1=float(fit.pvalues["dsci_lag1"]),
                        beta_delta4w_lag1=float(fit.params["dsci_delta4w_lag1"]),
                        t_delta4w_lag1=float(fit.tvalues["dsci_delta4w_lag1"]),
                        p_delta4w_lag1=float(fit.pvalues["dsci_delta4w_lag1"]),
                        high_minus_low_target=float(high_vals.mean() - low_vals.mean()),
                        high_low_welch_t=float(ttest[0]),
                        high_low_welch_p=float(ttest[1]),
                        level_gate_pass=level_gate,
                        delta4w_gate_pass=delta_gate,
                        gate_pass=bool(level_gate or delta_gate),
                    )
                )
    return results


def determine_verdict(fire_results: list[FireDoseResult], drought_results: list[DroughtResult]) -> dict[str, Any]:
    fire_passes = [r for r in fire_results if r.gate_pass]
    drought_passes = [r for r in drought_results if r.gate_pass]
    directional_fire = [r for r in fire_results if r.beta_log_acres > 0 and r.t_log_acres > 0]
    directional_drought = [r for r in drought_results if r.beta_dsci_lag1 > 0 and r.t_dsci_lag1 > 0]
    if fire_passes or drought_passes:
        verdict = "PARTIAL_PUBLIC_PROXY_DOSE_RESPONSE"
    elif len(directional_fire) >= 2 or len(directional_drought) >= 2:
        verdict = "DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC"
    else:
        verdict = "NULL_PUBLIC_PROXY_DIAGNOSTIC"
    return {
        "verdict": verdict,
        "fire_gate_pass_count": len(fire_passes),
        "drought_gate_pass_count": len(drought_passes),
        "directional_fire_count": len(directional_fire),
        "directional_drought_count": len(directional_drought),
        "fire_cells": len(fire_results),
        "drought_cells": len(drought_results),
        "gate": "PASS requires positive dose coefficient with t>=3. Drought accepts either level DSCI or 4-week DSCI increase; wildfire additionally requires monotone terciles and high-minus-low bootstrap CI > 0.",
    }


def make_figure(fire_daily: pd.DataFrame, drought_weekly: pd.DataFrame, fire_results: list[FireDoseResult], drought_results: list[DroughtResult]) -> None:
    annual_fire = fire_daily.groupby(fire_daily.index.year)["acres_total"].sum()
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), dpi=150)
    annual_fire.plot(kind="bar", ax=axes[0], color="#8c2d19")
    axes[0].set_title("CAL FIRE annual perimeter acres in sample")
    axes[0].set_ylabel("acres")
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].plot(drought_weekly["valid_start"], drought_weekly["dsci"], color="#7b5e00", linewidth=1.3)
    axes[1].set_title("USDM California drought severity index proxy")
    axes[1].set_ylabel("DSCI-style score")
    axes[1].grid(alpha=0.25)

    rows = []
    for item in fire_results:
        rows.append({"label": f"fire {item.target} {item.horizon}d", "t": item.t_log_acres})
    for item in drought_results:
        rows.append({"label": f"dry level {item.group}-{item.target} {item.horizon}d", "t": item.t_dsci_lag1})
        rows.append({"label": f"dry +4w {item.group}-{item.target} {item.horizon}d", "t": item.t_delta4w_lag1})
    tdf = pd.DataFrame(rows)
    colors = ["#0b6bcb" if value > 0 else "#9c2f2f" for value in tdf["t"]]
    axes[2].bar(tdf["label"], tdf["t"], color=colors)
    axes[2].axhline(3.0, color="#333333", linestyle="--", linewidth=0.8)
    axes[2].axhline(0.0, color="#777777", linewidth=0.8)
    axes[2].set_ylabel("dose coefficient t-stat")
    axes[2].set_title("Dose-response t-statistics (positive means higher dose -> higher log RV/downside)")
    axes[2].tick_params(axis="x", rotation=70)
    axes[2].grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_PATH)
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    np.random.seed(SEED)
    ensure_dirs()
    close = fetch_prices(refresh=refresh)
    fire_raw, fire_daily = fetch_calfire(refresh=refresh)
    drought_weekly = fetch_usdm(refresh=refresh)
    market_panel = build_market_panels(close, drought_weekly)
    event_panel = build_fire_event_panel(fire_daily, market_panel)
    fire_results = fire_dose_tests(event_panel)
    drought_results = drought_tests(market_panel)
    make_figure(fire_daily, drought_weekly, fire_results, drought_results)
    verdict = determine_verdict(fire_results, drought_results)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "price_source": "yfinance adjusted close, auto_adjust=True",
            "price_sample_start": close.index.min().strftime("%Y-%m-%d"),
            "price_sample_end": close.index.max().strftime("%Y-%m-%d"),
            "loaded_tickers": list(close.columns),
            "calfire_source": CALFIRE_CSV_URL,
            "calfire_fire_rows": int(len(fire_raw)),
            "calfire_daily_event_rows": int(len(fire_daily)),
            "calfire_event_rows_acres_ge_5000": int(len(event_panel)),
            "usdm_source": USDM_CA_URL,
            "usdm_weekly_rows": int(len(drought_weekly)),
            "usdm_start": drought_weekly["valid_start"].min().strftime("%Y-%m-%d"),
            "usdm_end": drought_weekly["valid_start"].max().strftime("%Y-%m-%d"),
        },
        "lookahead_controls": {
            "wildfire": "market targets start on the first trading day strictly after CAL FIRE alarm_date; final acres are ex-post physical dose only, not a tradable signal",
            "drought": "USDM validStart is treated as observable only after +2 calendar days and then shifted one trading day in regressions",
            "targets": "forward RV/downside targets are dependent variables only; lagged controls use rolling windows shifted before target start",
        },
        "fire_dose_results": [asdict(item) for item in fire_results],
        "drought_dose_results": [asdict(item) for item in drought_results],
        "literature_and_data_context": LITERATURE_AND_DATA_CONTEXT,
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(HERE)),
            "price_cache": str(PRICE_CACHE.relative_to(HERE)),
            "fire_raw_cache": str(FIRE_RAW_CACHE.relative_to(HERE)),
            "fire_daily_cache": str(FIRE_DAILY_CACHE.relative_to(HERE)),
            "usdm_cache": str(USDM_CACHE.relative_to(HERE)),
            "event_panel": str(EVENT_PANEL_CACHE.relative_to(HERE)),
            "drought_panel": str(DROUGHT_PANEL_CACHE.relative_to(HERE)),
            "figure": str(FIG_PATH.relative_to(HERE)),
        },
        "limitations": [
            "CAL FIRE final acres are final perimeter attributes and are not known on the alarm date; event-dose results are ex-post physical-risk diagnostics.",
            "USDM is weekly state-level California severity, not county/utility-service-territory or farm-belt crop-zone exposure.",
            "ETF proxies cannot identify actual utility wildfire liability, insured losses, crop yields, basis risk, or firm-level balance-sheet exposure.",
            "Daily close-to-close ETF data can miss intraday event pricing and public-safety power shutoff timing.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(_json_safe({"experiment_id": EXPERIMENT_ID, "verdict": verdict}), indent=2, ensure_ascii=False))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload CAL FIRE, USDM, and yfinance data")
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
