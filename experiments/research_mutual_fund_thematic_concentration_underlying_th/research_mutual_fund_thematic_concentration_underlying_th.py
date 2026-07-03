#!/usr/bin/env python3
"""Thematic fund concentration public-proxy volatility diagnostic.

This experiment does not replicate mutual-fund TCI from the RFS paper. It uses
current yfinance thematic-ETF top holdings as an ex-post public proxy for
portfolio concentration/overlap, then asks whether lagged ETF attention pressure
predicts forward residual RV/downside in the underlying stocks.

Lookahead policy:
    - ETF holdings are a current snapshot and therefore only define an ex-post
      public proxy universe. The experiment does not make a tradable holdings
      history claim.
    - The time-varying signal uses ETF dollar-volume attention with one trading
      day lag.
    - Forward RV/downside targets start at t+1.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_mutual_fund_thematic_concentration_underlying_th"
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = FIG_DIR / "thematic_concentration_proxy_summary.png"

SEED = 42
START_DATE = "2021-01-01"
END_DATE = "2026-07-03"
HORIZONS = [5, 22]
EPS = 1.0e-12

THEME_ETFS = [
    "ARKK",
    "ARKW",
    "ARKG",
    "ARKF",
    "AIQ",
    "BOTZ",
    "ROBO",
    "CIBR",
    "HACK",
    "FINX",
    "CLOU",
    "DRIV",
    "ICLN",
    "TAN",
    "LIT",
    "SKYY",
]
MARKET_CONTROLS = ["QQQ", "SPY"]

HOLDINGS_CACHE = DATA_DIR / "theme_etf_top_holdings_snapshot.csv"
PRICE_CACHE = DATA_DIR / "price_adjusted_close_volume.csv"
STOCK_PANEL_CACHE = DATA_DIR / "underlying_stock_pressure_panel.csv"
ETF_PANEL_CACHE = DATA_DIR / "theme_etf_pressure_panel.csv"

LITERATURE_AND_DATA_CONTEXT = [
    {
        "citation": "Thematic Concentration and Mutual Fund Performance, Review of Financial Studies advance article",
        "url": "https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhag021/8701142",
        "role": "Motivates mutual-fund TCI; this run is an ETF holdings public proxy, not a TCI replication.",
    },
    {
        "citation": "SEC Form N-PORT data sets",
        "url": "https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets",
        "role": "Confirms the proper fund-holdings source for a full replication; not used here because this run uses yfinance ETF top holdings.",
    },
    {
        "citation": "Thematic Investing: A Risk-Based Perspective, Financial Analysts Journal",
        "url": "https://www.tandfonline.com/doi/full/10.1080/0015198X.2025.2526483",
        "role": "Motivates testing residual-return co-movement and theme risk rather than only ETF returns.",
    },
    {
        "citation": "yfinance FundsData top_holdings documentation",
        "url": "https://ranaroussi.github.io/yfinance/reference/api/yfinance.scrapers.funds.FundsData.html",
        "role": "Public top-holdings source for the ETF proxy.",
    },
]


@dataclass(frozen=True)
class RegressionResult:
    panel: str
    target: str
    horizon: int
    n_obs: int
    n_entities: int
    beta: float
    t_stat: float
    p_value: float
    high_low_diff: float
    high_low_t: float
    high_low_p: float
    high_count: int
    low_count: int
    gate_pass: bool


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


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


def is_us_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{1,5}", str(symbol).strip()))


def fetch_holdings(refresh: bool = False) -> pd.DataFrame:
    ensure_dirs()
    if HOLDINGS_CACHE.exists() and not refresh:
        return pd.read_csv(HOLDINGS_CACHE)

    rows: list[dict[str, Any]] = []
    for etf in THEME_ETFS:
        try:
            top = yf.Ticker(etf).funds_data.top_holdings
        except Exception as exc:  # noqa: BLE001 - record unavailable ETF holdings
            rows.append({"etf": etf, "symbol": "", "name": "", "weight": np.nan, "download_error": repr(exc)})
            continue
        if top is None or top.empty:
            rows.append({"etf": etf, "symbol": "", "name": "", "weight": np.nan, "download_error": "empty"})
            continue
        frame = top.reset_index().rename(columns={"Symbol": "symbol", "Name": "name", "Holding Percent": "weight"})
        for _, row in frame.iterrows():
            symbol = str(row["symbol"]).strip().upper()
            weight = float(row["weight"])
            rows.append(
                {
                    "etf": etf,
                    "symbol": symbol,
                    "name": str(row.get("name", "")),
                    "weight": weight,
                    "is_us_symbol": is_us_symbol(symbol),
                    "download_error": "",
                }
            )
    out = pd.DataFrame(rows)
    out = out[out["download_error"].fillna("") == ""].copy()
    out = out[out["is_us_symbol"]].copy()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce")
    out = out.dropna(subset=["weight"])
    out = out[out["weight"] > 0].copy()
    concentration = out.groupby("etf")["weight"].agg(
        holdings_count="size",
        hhi=lambda s: float(np.square(s).sum()),
        top3_share=lambda s: float(s.sort_values(ascending=False).head(3).sum()),
        top5_share=lambda s: float(s.sort_values(ascending=False).head(5).sum()),
    )
    out = out.merge(concentration, on="etf", how="left")
    out["effective_n_top10"] = 1.0 / out["hhi"].replace(0, np.nan)
    out.to_csv(HOLDINGS_CACHE, index=False)
    return out


def fetch_prices(tickers: list[str], refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_dirs()
    if PRICE_CACHE.exists() and not refresh:
        raw = pd.read_csv(PRICE_CACHE, header=[0, 1], index_col=0, skiprows=[2])
        raw.index = pd.to_datetime(raw.index).normalize()
        close = raw.xs("Close", axis=1, level=1)
        volume = raw.xs("Volume", axis=1, level=1)
        return close.sort_index(), volume.sort_index()

    raw = yf.download(
        sorted(set(tickers)),
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        group_by="ticker",
        threads=False,
        progress=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data")
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("expected multi-index yfinance output")
    close = raw.xs("Close", axis=1, level=-1).copy()
    volume = raw.xs("Volume", axis=1, level=-1).copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    volume.index = pd.to_datetime(volume.index).tz_localize(None).normalize()
    combined = pd.concat({"Close": close, "Volume": volume}, axis=1).swaplevel(0, 1, axis=1).sort_index(axis=1)
    combined.to_csv(PRICE_CACHE, index_label="Date")
    return close, volume


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    return series.shift(-1).rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))


def rolling_z(series: pd.Series, window: int = 63) -> pd.Series:
    mean = series.rolling(window, min_periods=30).mean().shift(1)
    std = series.rolling(window, min_periods=30).std(ddof=0).shift(1)
    return (series - mean) / std.replace(0, np.nan)


def build_panels(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ensure_dirs()
    if STOCK_PANEL_CACHE.exists() and ETF_PANEL_CACHE.exists() and HOLDINGS_CACHE.exists() and not refresh:
        holdings = pd.read_csv(HOLDINGS_CACHE)
        stock_panel = pd.read_csv(STOCK_PANEL_CACHE, parse_dates=["date"])
        etf_panel = pd.read_csv(ETF_PANEL_CACHE, parse_dates=["date"])
        return holdings, stock_panel, etf_panel

    holdings = fetch_holdings(refresh=refresh)
    held_symbols = sorted(holdings["symbol"].dropna().unique())
    tickers = sorted(set(THEME_ETFS + MARKET_CONTROLS + held_symbols))
    close, volume = fetch_prices(tickers, refresh=refresh)
    available_symbols = [sym for sym in held_symbols if sym in close.columns and close[sym].notna().sum() >= 252]
    holdings = holdings[holdings["symbol"].isin(available_symbols)].copy()
    returns = np.log(close).diff()

    etf_rows: list[pd.DataFrame] = []
    attention_by_etf: dict[str, pd.Series] = {}
    for etf, group in holdings.groupby("etf"):
        if etf not in close.columns or etf not in volume.columns:
            continue
        dollar_volume = (close[etf] * volume[etf]).replace(0, np.nan)
        attention = rolling_z(np.log(dollar_volume)).shift(1)
        attention_by_etf[etf] = attention
        hhi = float(group["hhi"].iloc[0])
        pressure = attention * hhi
        ret = returns[etf] - returns["QQQ"]
        frame = pd.DataFrame(
            {
                "date": returns.index,
                "etf": etf,
                "attention_z_lag1": attention,
                "hhi": hhi,
                "top5_share": float(group["top5_share"].iloc[0]),
                "pressure": pressure,
                "resid_ret": ret,
            }
        )
        for horizon in HORIZONS:
            rv = frame["resid_ret"].pow(2)
            downside = frame["resid_ret"].where(frame["resid_ret"] < 0, 0).pow(2)
            frame["recent_rv_5d_lag1"] = rv.rolling(5, min_periods=3).sum().shift(1)
            baseline_rv = rv.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            baseline_down = downside.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            frame[f"target_etf_rv_{horizon}d"] = np.log((forward_sum(rv, horizon) + EPS) / (baseline_rv + EPS))
            frame[f"target_etf_downside_{horizon}d"] = np.log(
                (forward_sum(downside, horizon) + EPS) / (baseline_down + EPS)
            )
        etf_rows.append(frame)
    etf_panel = pd.concat(etf_rows, ignore_index=True)

    stock_signal_frames: list[pd.DataFrame] = []
    for _, row in holdings.iterrows():
        etf = row["etf"]
        symbol = row["symbol"]
        if etf not in attention_by_etf:
            continue
        contribution = attention_by_etf[etf] * float(row["hhi"]) * float(row["weight"])
        stock_signal_frames.append(pd.DataFrame({"date": returns.index, "symbol": symbol, "signal_component": contribution}))
    stock_signal = (
        pd.concat(stock_signal_frames, ignore_index=True)
        .groupby(["date", "symbol"], as_index=False)["signal_component"]
        .sum()
        .rename(columns={"signal_component": "pressure"})
    )
    static_crowding = (
        holdings.assign(static_component=holdings["hhi"] * holdings["weight"])
        .groupby("symbol")
        .agg(etf_count=("etf", "nunique"), static_crowding=("static_component", "sum"), total_top10_weight=("weight", "sum"))
        .reset_index()
    )

    stock_rows: list[pd.DataFrame] = []
    for symbol in available_symbols:
        if symbol not in returns.columns:
            continue
        ret = returns[symbol] - returns["QQQ"]
        frame = pd.DataFrame({"date": returns.index, "symbol": symbol, "resid_ret": ret})
        frame = frame.merge(stock_signal[stock_signal["symbol"] == symbol], on=["date", "symbol"], how="left")
        frame = frame.merge(static_crowding[static_crowding["symbol"] == symbol], on="symbol", how="left")
        frame["pressure"] = frame["pressure"].fillna(0.0)
        for horizon in HORIZONS:
            rv = frame["resid_ret"].pow(2)
            downside = frame["resid_ret"].where(frame["resid_ret"] < 0, 0).pow(2)
            frame["recent_rv_5d_lag1"] = rv.rolling(5, min_periods=3).sum().shift(1)
            baseline_rv = rv.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            baseline_down = downside.rolling(63, min_periods=42).sum().shift(1) * horizon / 63.0
            frame[f"target_stock_rv_{horizon}d"] = np.log((forward_sum(rv, horizon) + EPS) / (baseline_rv + EPS))
            frame[f"target_stock_downside_{horizon}d"] = np.log(
                (forward_sum(downside, horizon) + EPS) / (baseline_down + EPS)
            )
        stock_rows.append(frame)
    stock_panel = pd.concat(stock_rows, ignore_index=True)
    stock_panel = stock_panel[stock_panel["date"] >= "2021-06-01"].copy()
    etf_panel = etf_panel[etf_panel["date"] >= "2021-06-01"].copy()
    holdings.to_csv(HOLDINGS_CACHE, index=False)
    stock_panel.to_csv(STOCK_PANEL_CACHE, index=False)
    etf_panel.to_csv(ETF_PANEL_CACHE, index=False)
    return holdings, stock_panel, etf_panel


def standardize(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return series * np.nan
    return (series - series.mean()) / std


def run_regression(panel_name: str, panel: pd.DataFrame, entity_col: str, target: str, horizon: int) -> RegressionResult:
    df = panel[[entity_col, "pressure", "recent_rv_5d_lag1", target]].dropna().copy()
    df = df[np.isfinite(df["pressure"]) & np.isfinite(df[target])].copy()
    df["pressure_z"] = standardize(df["pressure"])
    df["recent_rv_z"] = standardize(np.log(df["recent_rv_5d_lag1"] + EPS))
    df = df.dropna(subset=["pressure_z", "recent_rv_z", target])
    dummies = pd.get_dummies(df[entity_col], prefix="id", drop_first=True, dtype=float)
    x = pd.concat([df[["pressure_z", "recent_rv_z"]].astype(float), dummies], axis=1)
    x = sm.add_constant(x, has_constant="add")
    model = sm.OLS(df[target].astype(float), x).fit(cov_type="cluster", cov_kwds={"groups": df[entity_col]})
    beta = float(model.params["pressure_z"])
    t_stat = float(model.tvalues["pressure_z"])
    p_value = float(model.pvalues["pressure_z"])
    rank = df["pressure_z"].rank(method="first", pct=True)
    high = df[rank >= 0.8][target].dropna()
    low = df[rank <= 0.5][target].dropna()
    if len(high) > 2 and len(low) > 2:
        welch = stats.ttest_ind(high, low, equal_var=False, nan_policy="omit")
        high_low_diff = float(high.mean() - low.mean())
        high_low_t = float(welch.statistic)
        high_low_p = float(welch.pvalue)
    else:
        high_low_diff = high_low_t = high_low_p = np.nan
    gate_pass = bool(beta > 0 and t_stat >= 3.0 and high_low_diff > 0 and high_low_t >= 3.0)
    return RegressionResult(
        panel=panel_name,
        target=target,
        horizon=horizon,
        n_obs=int(len(df)),
        n_entities=int(df[entity_col].nunique()),
        beta=beta,
        t_stat=t_stat,
        p_value=p_value,
        high_low_diff=high_low_diff,
        high_low_t=high_low_t,
        high_low_p=high_low_p,
        high_count=int(len(high)),
        low_count=int(len(low)),
        gate_pass=gate_pass,
    )


def make_figure(holdings: pd.DataFrame, stock_panel: pd.DataFrame, etf_panel: pd.DataFrame, results: list[RegressionResult]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=150)
    fig.patch.set_facecolor("white")

    etf_conc = holdings.groupby("etf").agg(hhi=("hhi", "first"), top5_share=("top5_share", "first")).sort_values("hhi", ascending=False)
    etf_conc.head(12)["hhi"].plot(kind="bar", ax=axes[0, 0], color="#244b6b")
    axes[0, 0].set_title("Current top-10 holdings concentration")
    axes[0, 0].set_ylabel("HHI")
    axes[0, 0].tick_params(axis="x", rotation=45)

    crowded = holdings.groupby("symbol").agg(etf_count=("etf", "nunique"), total_weight=("weight", "sum")).sort_values("total_weight", ascending=False).head(12)
    crowded["total_weight"].plot(kind="bar", ax=axes[0, 1], color="#6f9f5f")
    axes[0, 1].set_title("Repeated top holdings across theme ETFs")
    axes[0, 1].set_ylabel("Sum of top-10 weights")
    axes[0, 1].tick_params(axis="x", rotation=45)

    stock_results = [r for r in results if r.panel == "stock"]
    labels = [f"{r.target.replace('target_stock_', '')}\n{r.horizon}d" for r in stock_results]
    tstats = [r.t_stat for r in stock_results]
    colors = ["#2f6f4e" if r.gate_pass else "#8c8c8c" for r in stock_results]
    axes[1, 0].bar(range(len(tstats)), tstats, color=colors)
    axes[1, 0].axhline(3.0, color="#b22222", linestyle="--", linewidth=1.0)
    axes[1, 0].set_xticks(range(len(labels)))
    axes[1, 0].set_xticklabels(labels, rotation=45, ha="right")
    axes[1, 0].set_title("Underlying-stock pressure coefficient t-stat")
    axes[1, 0].set_ylabel("Clustered t-stat")

    tmp = stock_panel[["pressure", "target_stock_rv_5d"]].replace([np.inf, -np.inf], np.nan).dropna()
    tmp["bucket"] = pd.qcut(tmp["pressure"].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    bucket = tmp.groupby("bucket", observed=True)["target_stock_rv_5d"].mean()
    axes[1, 1].bar(bucket.index.astype(str), bucket.values, color="#5b8db8")
    axes[1, 1].set_title("5d stock RV target by pressure quintile")
    axes[1, 1].set_ylabel("Mean log RV vs 63d baseline")

    for ax in axes.ravel():
        ax.grid(axis="y", alpha=0.2)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG_PATH, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    ensure_dirs()
    np.random.seed(SEED)
    holdings, stock_panel, etf_panel = build_panels(refresh=refresh)
    results: list[RegressionResult] = []
    for horizon in HORIZONS:
        for base in ["rv", "downside"]:
            results.append(run_regression("stock", stock_panel, "symbol", f"target_stock_{base}_{horizon}d", horizon))
            results.append(run_regression("etf", etf_panel, "etf", f"target_etf_{base}_{horizon}d", horizon))

    stock_results = [r for r in results if r.panel == "stock"]
    etf_results = [r for r in results if r.panel == "etf"]
    verdict = {
        "verdict": "PASS_ETF_PROXY" if any(r.gate_pass for r in stock_results) else "NULL_ETF_PROXY_DIAGNOSTIC",
        "stock_gate_pass_count": int(sum(r.gate_pass for r in stock_results)),
        "stock_cells": int(len(stock_results)),
        "stock_directional_count": int(sum(r.beta > 0 for r in stock_results)),
        "etf_gate_pass_count": int(sum(r.gate_pass for r in etf_results)),
        "etf_cells": int(len(etf_results)),
        "gate": "Primary PASS requires underlying-stock pressure coefficient >0 with clustered t>=3 and high-minus-low Welch t>=3. ETF-level tests are auxiliary.",
    }
    strongest_stock = max(stock_results, key=lambda r: r.t_stat)
    strongest_any = max(results, key=lambda r: r.t_stat)
    make_figure(holdings, stock_panel, etf_panel, results)

    results_obj = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "sample_start": START_DATE,
            "sample_end": END_DATE,
            "theme_etf_candidates": THEME_ETFS,
            "theme_etfs_with_us_top_holdings": sorted(holdings["etf"].unique()),
            "theme_etf_count": int(holdings["etf"].nunique()),
            "top_holding_rows": int(len(holdings)),
            "unique_underlying_symbols": int(holdings["symbol"].nunique()),
            "stock_panel_rows": int(len(stock_panel)),
            "stock_panel_start": stock_panel["date"].min().strftime("%Y-%m-%d"),
            "stock_panel_end": stock_panel["date"].max().strftime("%Y-%m-%d"),
            "etf_panel_rows": int(len(etf_panel)),
            "etf_panel_start": etf_panel["date"].min().strftime("%Y-%m-%d"),
            "etf_panel_end": etf_panel["date"].max().strftime("%Y-%m-%d"),
            "max_etf_hhi": float(holdings.groupby("etf")["hhi"].first().max()),
            "max_top5_share": float(holdings.groupby("etf")["top5_share"].first().max()),
        },
        "lookahead_controls": {
            "holdings": "ETF top holdings are current snapshots and define only an ex-post ETF proxy universe; no tradable historical holdings claim is made.",
            "signal": "ETF dollar-volume attention is rolling-z transformed and shifted one trading day before use.",
            "targets": "Forward RV/downside targets start at t+1; lagged 63d baselines are shifted before target start.",
        },
        "regression_results": [asdict(item) for item in results],
        "strongest_stock_result": asdict(strongest_stock),
        "strongest_any_result": asdict(strongest_any),
        "literature_and_data_context": LITERATURE_AND_DATA_CONTEXT,
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(HERE)),
            "figure": str(FIG_PATH.relative_to(HERE)),
            "holdings_snapshot": str(HOLDINGS_CACHE.relative_to(HERE)),
            "price_cache": str(PRICE_CACHE.relative_to(HERE)),
            "stock_panel": str(STOCK_PANEL_CACHE.relative_to(HERE)),
            "etf_panel": str(ETF_PANEL_CACHE.relative_to(HERE)),
        },
        "limitations": [
            "This is an ETF top-holdings proxy, not a mutual-fund TCI replication.",
            "Current holdings snapshots are used to define ex-post baskets; historical holdings turnover is not observed.",
            "yfinance top_holdings usually exposes only top holdings, not full portfolios.",
            "ETF dollar-volume attention is a noisy flow/crowding proxy and can capture news demand unrelated to fund concentration.",
            "Daily close-to-close returns miss intraday basket rebalancing and creation/redemption timing.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(_json_safe(results_obj), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "verdict": verdict}, indent=2, ensure_ascii=False))
    return results_obj


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance holdings and price data")
    args = parser.parse_args()
    run(refresh=args.refresh)


if __name__ == "__main__":
    main()
