#!/usr/bin/env python3
"""Commodity inventory/seasonality regime-conditional volatility test."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
TICKERS = ["CL=F", "USO", "NG=F", "UNG", "DBA"]
START = "2006-01-01"
END = "2026-06-15"
OOS_START = pd.Timestamp("2018-01-02")
FWD_HORIZON = 5
TRADING_DAYS = 252
HAC_LAGS = 5
INVENTORY_ROLL = 156
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 5
EPS = 1e-12

CRUDE_XLS = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"
GAS_XLS = "https://www.eia.gov/dnav/ng/xls/NG_STOR_WKLY_S1_W.xls"

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_inventory_seasonality_surprise_regime_conditiona_results.json"
FIG_TSTATS = HERE / "fig_inventory_seasonality_interaction_tstats.png"
FIG_REGIMES = HERE / "fig_forward_rv_by_regime.png"

ASSET_GROUP = {
    "CL=F": "oil",
    "USO": "oil",
    "NG=F": "gas",
    "UNG": "gas",
    "DBA": "agriculture",
}

SEASONAL_STRESS_MONTHS = {
    "oil": {8, 9, 10},
    "gas": {1, 2, 7, 8, 12},
    "agriculture": {4, 5, 6, 7, 8},
}


@dataclass(frozen=True)
class RegressionSummary:
    nobs: int
    coef_seasonal: float
    t_seasonal: float
    p_seasonal: float
    coef_low_inventory: float | None
    t_low_inventory: float | None
    p_low_inventory: float | None
    coef_season_low_interaction: float | None
    t_season_low_interaction: float | None
    p_season_low_interaction: float | None
    coef_abs_surprise: float | None
    t_abs_surprise: float | None
    p_abs_surprise: float | None
    coef_season_abs_surprise: float | None
    t_season_abs_surprise: float | None
    p_season_abs_surprise: float | None
    r2: float


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()[TICKERS]
    else:
        close = raw[["Close"]].rename(columns={"Close": TICKERS[0]})
    close.index = pd.to_datetime(close.index)
    close = close.dropna(how="all")
    close.to_csv(DATA_DIR / "close.csv")
    return close


def read_eia_series(url: str, value_col: int, name: str) -> pd.Series:
    raw = pd.read_excel(url, sheet_name="Data 1", header=None)
    dates = pd.to_datetime(raw.iloc[2:, 0].astype(str), errors="coerce", format="mixed")
    data = pd.DataFrame({"date": dates, name: raw.iloc[2:, value_col]})
    data[name] = pd.to_numeric(data[name], errors="coerce")
    data = data.dropna().sort_values("date")
    series = pd.Series(data[name].to_numpy(dtype=float), index=data["date"], name=name)
    # EIA weekly values are as-of week-ending dates. Use a conservative 7-day
    # publication lag before making them available to daily regressions.
    series.index = series.index + pd.Timedelta(days=7)
    series.to_csv(DATA_DIR / f"{name}.csv", header=True)
    return series


def build_inventory_features(series: pd.Series, prefix: str) -> pd.DataFrame:
    weekly = pd.DataFrame({"level": series}).dropna()
    weekly["change"] = weekly["level"].diff()
    weekly["level_mean"] = weekly["level"].rolling(INVENTORY_ROLL, min_periods=52).mean().shift(1)
    weekly["level_std"] = weekly["level"].rolling(INVENTORY_ROLL, min_periods=52).std(ddof=1).shift(1)
    weekly["change_mean"] = weekly["change"].rolling(52, min_periods=26).mean().shift(1)
    weekly["change_std"] = weekly["change"].rolling(52, min_periods=26).std(ddof=1).shift(1)
    weekly[f"{prefix}_inventory_z"] = (weekly["level"] - weekly["level_mean"]) / weekly["level_std"]
    weekly[f"{prefix}_surprise_z"] = (weekly["change"] - weekly["change_mean"]) / weekly["change_std"]
    weekly[f"{prefix}_low_inventory"] = (
        weekly[f"{prefix}_inventory_z"]
        < weekly[f"{prefix}_inventory_z"].rolling(INVENTORY_ROLL, min_periods=52).quantile(0.2).shift(1)
    ).astype(float)
    out = weekly[[f"{prefix}_inventory_z", f"{prefix}_surprise_z", f"{prefix}_low_inventory"]].replace(
        [np.inf, -np.inf], np.nan
    )
    out.to_csv(DATA_DIR / f"{prefix}_inventory_features.csv")
    return out


def forward_rv(ret: pd.Series) -> pd.Series:
    total = pd.Series(0.0, index=ret.index)
    for h in range(1, FWD_HORIZON + 1):
        total = total + ret.shift(-h) ** 2
    return (total * TRADING_DAYS / FWD_HORIZON).rename("fwd5_ann_var")


def trailing_rv(ret: pd.Series) -> pd.Series:
    return (ret.rolling(FWD_HORIZON).apply(lambda x: float(np.sum(x * x)), raw=True) * TRADING_DAYS / FWD_HORIZON)


def align_inventory_to_daily(index: pd.DatetimeIndex, features: pd.DataFrame | None, prefix: str) -> pd.DataFrame:
    if features is None:
        return pd.DataFrame(index=index)
    daily = features.reindex(index.union(features.index)).sort_index().ffill().reindex(index)
    # Explicit prediction lag: even after conservative report-date lagging,
    # regressions use yesterday's known inventory features.
    daily = daily.shift(1)
    daily.columns = [c.replace(f"{prefix}_", "") for c in daily.columns]
    return daily


def build_asset_frame(ticker: str, close: pd.Series, inventory_features: dict[str, pd.DataFrame]) -> pd.DataFrame:
    group = ASSET_GROUP[ticker]
    # Use simple returns, not log returns: WTI front-month futures briefly
    # settled below zero in 2020, making log returns undefined for CL=F.
    ret = close.pct_change().dropna()
    df = pd.DataFrame({"ret": ret})
    df["fwd5_ann_var"] = forward_rv(df["ret"])
    df["log_fwd5_ann_var"] = np.log(df["fwd5_ann_var"] + EPS)
    df["log_trailing5_ann_var_lag1"] = np.log(trailing_rv(df["ret"]).shift(1) + EPS)

    seasonal = df.index.month.isin(SEASONAL_STRESS_MONTHS[group]).astype(float)
    df["seasonal_stress_lag1"] = pd.Series(seasonal, index=df.index).shift(1)

    inv = None
    prefix = group
    if group in {"oil", "gas"}:
        inv = inventory_features[group]
        aligned = align_inventory_to_daily(df.index, inv, prefix)
        df["inventory_z_lag1"] = aligned["inventory_z"]
        df["surprise_abs_lag1"] = aligned["surprise_z"].abs()
        df["low_inventory_lag1"] = aligned["low_inventory"]
        df["season_low_interaction"] = df["seasonal_stress_lag1"] * df["low_inventory_lag1"]
        df["season_abs_surprise_interaction"] = df["seasonal_stress_lag1"] * df["surprise_abs_lag1"]
    else:
        df["inventory_z_lag1"] = np.nan
        df["surprise_abs_lag1"] = np.nan
        df["low_inventory_lag1"] = np.nan
        df["season_low_interaction"] = np.nan
        df["season_abs_surprise_interaction"] = np.nan

    return df.replace([np.inf, -np.inf], np.nan)


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return s * np.nan
    return (s - s.mean()) / sd


def regression_for_asset(df: pd.DataFrame, has_inventory: bool) -> RegressionSummary:
    oos = df[df.index >= OOS_START].copy()
    if has_inventory:
        reg = pd.DataFrame(
            {
                "target": oos["log_fwd5_ann_var"],
                "lag_rv": oos["log_trailing5_ann_var_lag1"],
                "seasonal": oos["seasonal_stress_lag1"],
                "low_inventory": oos["low_inventory_lag1"],
                "abs_surprise": zscore(oos["surprise_abs_lag1"]),
                "season_low": oos["season_low_interaction"],
                "season_abs_surprise": zscore(oos["season_abs_surprise_interaction"]),
            }
        ).dropna()
        xcols = ["lag_rv", "seasonal", "low_inventory", "abs_surprise", "season_low", "season_abs_surprise"]
    else:
        reg = pd.DataFrame(
            {
                "target": oos["log_fwd5_ann_var"],
                "lag_rv": oos["log_trailing5_ann_var_lag1"],
                "seasonal": oos["seasonal_stress_lag1"],
            }
        ).dropna()
        xcols = ["lag_rv", "seasonal"]

    x = sm.add_constant(reg[xcols])
    fit = sm.OLS(reg["target"], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})

    def val(field: str, series) -> float | None:
        if field not in series.index:
            return None
        return round(float(series[field]), 6)

    def tval(field: str) -> float | None:
        if field not in fit.tvalues.index:
            return None
        return round(float(fit.tvalues[field]), 4)

    return RegressionSummary(
        nobs=int(fit.nobs),
        coef_seasonal=val("seasonal", fit.params),
        t_seasonal=tval("seasonal"),
        p_seasonal=val("seasonal", fit.pvalues),
        coef_low_inventory=val("low_inventory", fit.params),
        t_low_inventory=tval("low_inventory"),
        p_low_inventory=val("low_inventory", fit.pvalues),
        coef_season_low_interaction=val("season_low", fit.params),
        t_season_low_interaction=tval("season_low"),
        p_season_low_interaction=val("season_low", fit.pvalues),
        coef_abs_surprise=val("abs_surprise", fit.params),
        t_abs_surprise=tval("abs_surprise"),
        p_abs_surprise=val("abs_surprise", fit.pvalues),
        coef_season_abs_surprise=val("season_abs_surprise", fit.params),
        t_season_abs_surprise=tval("season_abs_surprise"),
        p_season_abs_surprise=val("season_abs_surprise", fit.pvalues),
        r2=round(float(fit.rsquared), 6),
    )


def bootstrap_regime_means(df: pd.DataFrame, has_inventory: bool) -> dict:
    oos = df[df.index >= OOS_START].copy()
    if has_inventory:
        cols = ["fwd5_ann_var", "seasonal_stress_lag1", "low_inventory_lag1"]
        sample = oos[cols].dropna()
    else:
        cols = ["fwd5_ann_var", "seasonal_stress_lag1"]
        sample = oos[cols].dropna()
    arr = sample.to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)

    def sample_once(values: np.ndarray) -> dict:
        chosen: list[int] = []
        n = len(values)
        while len(chosen) < n:
            start = int(rng.integers(0, max(1, n - BOOTSTRAP_BLOCK + 1)))
            chosen.extend(range(start, min(start + BOOTSTRAP_BLOCK, n)))
        b = values[np.asarray(chosen[:n], dtype=int)]
        if has_inventory:
            seasonal_low = b[(b[:, 1] == 1.0) & (b[:, 2] == 1.0), 0]
            seasonal_normal = b[(b[:, 1] == 1.0) & (b[:, 2] == 0.0), 0]
            nonseason_low = b[(b[:, 1] == 0.0) & (b[:, 2] == 1.0), 0]
            return {
                "seasonal_low_minus_seasonal_normal": np.nanmean(seasonal_low) - np.nanmean(seasonal_normal),
                "low_season_interaction_diff": (
                    np.nanmean(seasonal_low)
                    - np.nanmean(seasonal_normal)
                    - (np.nanmean(nonseason_low) - np.nanmean(b[(b[:, 1] == 0.0) & (b[:, 2] == 0.0), 0]))
                ),
            }
        seasonal = b[b[:, 1] == 1.0, 0]
        normal = b[b[:, 1] == 0.0, 0]
        return {"seasonal_minus_normal": np.nanmean(seasonal) - np.nanmean(normal)}

    rows = [sample_once(arr) for _ in range(BOOTSTRAP_REPS)]
    boot = pd.DataFrame(rows)
    out = {}
    for col in boot:
        vals = boot[col].dropna().to_numpy()
        out[col] = {
            "mean_ann_var_pct2": round(float(vals.mean() * 10000.0), 6),
            "ci_2p5_ann_var_pct2": round(float(np.quantile(vals, 0.025) * 10000.0), 6),
            "ci_97p5_ann_var_pct2": round(float(np.quantile(vals, 0.975) * 10000.0), 6),
            "p_gt_0": round(float((vals > 0).mean()), 4),
        }
    return out


def summarize_asset(ticker: str, df: pd.DataFrame) -> dict:
    has_inventory = ASSET_GROUP[ticker] in {"oil", "gas"}
    reg = regression_for_asset(df, has_inventory)
    boot = bootstrap_regime_means(df, has_inventory)
    oos = df[df.index >= OOS_START].copy()
    oos_valid = oos.dropna(subset=["fwd5_ann_var", "seasonal_stress_lag1"])
    return {
        "ticker": ticker,
        "group": ASSET_GROUP[ticker],
        "has_inventory_proxy": has_inventory,
        "n_oos": int(len(oos_valid)),
        "oos_start": str(oos_valid.index[0].date()),
        "oos_end": str(oos_valid.index[-1].date()),
        "mean_fwd5_ann_var_pct2": round(float(oos_valid["fwd5_ann_var"].mean() * 10000.0), 6),
        "seasonal_stress_share": round(float(oos_valid["seasonal_stress_lag1"].mean()), 6),
        "low_inventory_share": (
            round(float(oos["low_inventory_lag1"].dropna().mean()), 6) if has_inventory else None
        ),
        "regression_oos_hac": asdict(reg),
        "bootstrap_regime_means": boot,
    }


def build_figures(summaries: dict[str, dict]) -> None:
    labels = list(summaries)
    tstats = [
        summaries[t]["regression_oos_hac"]["t_season_low_interaction"]
        if summaries[t]["regression_oos_hac"]["t_season_low_interaction"] is not None
        else summaries[t]["regression_oos_hac"]["t_seasonal"]
        for t in labels
    ]
    colors = ["#4c78a8" if summaries[t]["has_inventory_proxy"] else "#999999" for t in labels]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(labels))
    ax.bar(x, tstats, color=colors)
    ax.axhline(3.0, color="#444444", linestyle="--", linewidth=1)
    ax.axhline(-3.0, color="#444444", linestyle="--", linewidth=1)
    ax.set_xticks(x, labels)
    ax.set_ylabel("HAC t-stat")
    ax.set_title("Inventory-Seasonality Interaction t-stat (DBA: Seasonality Only)")
    fig.tight_layout()
    fig.savefig(FIG_TSTATS, dpi=180)
    plt.close(fig)

    means = [summaries[t]["mean_fwd5_ann_var_pct2"] for t in labels]
    fig2, ax2 = plt.subplots(figsize=(9, 5))
    ax2.bar(x, means, color=["#f58518" if summaries[t]["group"] == "gas" else "#4c78a8" for t in labels])
    ax2.set_xticks(x, labels)
    ax2.set_ylabel("Mean forward 5d annualized variance (%^2)")
    ax2.set_title("Forward RV Scale by Commodity Asset")
    fig2.tight_layout()
    fig2.savefig(FIG_REGIMES, dpi=180)
    plt.close(fig2)


def main() -> None:
    np.random.seed(SEED)
    close = download_prices()
    crude_inventory = read_eia_series(CRUDE_XLS, 1, "crude_inventory")
    gas_inventory = read_eia_series(GAS_XLS, 1, "gas_inventory")
    inventory_features = {
        "oil": build_inventory_features(crude_inventory, "oil"),
        "gas": build_inventory_features(gas_inventory, "gas"),
    }

    frames = {
        ticker: build_asset_frame(ticker, close[ticker].dropna(), inventory_features)
        for ticker in TICKERS
        if ticker in close.columns
    }
    summaries = {ticker: summarize_asset(ticker, frame) for ticker, frame in frames.items()}
    build_figures(summaries)

    interaction_pass_assets = [
        ticker
        for ticker, summary in summaries.items()
        if summary["has_inventory_proxy"]
        and summary["regression_oos_hac"]["t_season_low_interaction"] is not None
        and summary["regression_oos_hac"]["t_season_low_interaction"] > 3.0
    ]
    group_passes = []
    for group, tickers in {"oil": ["CL=F", "USO"], "gas": ["NG=F", "UNG"]}.items():
        if all(t in interaction_pass_assets for t in tickers):
            group_passes.append(group)

    verdict = "NULL"
    if group_passes:
        verdict = "PARTIAL"
    if len(group_passes) == 2:
        verdict = "SUPPORT"

    results = {
        "experiment_id": "research_inventory_seasonality_surprise_regime_conditiona",
        "title": "Commodity inventory/seasonality regime-conditional forward-RV test",
        "date_run_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "price_source": "yfinance adjusted close; auto_adjust=True",
            "price_tickers": TICKERS,
            "price_start": START,
            "price_end": END,
            "inventory_sources": {
                "crude": {
                    "url": CRUDE_XLS,
                    "series": "Weekly U.S. Ending Stocks excluding SPR of Crude Oil (WCESTUS1)",
                    "unit": "thousand barrels",
                },
                "natural_gas": {
                    "url": GAS_XLS,
                    "series": "Weekly Lower 48 States Natural Gas Working Underground Storage",
                    "unit": "billion cubic feet",
                },
            },
            "oos_start": str(OOS_START.date()),
            "cached_data_dir": "experiments/research_inventory_seasonality_surprise_regime_conditiona/data/",
        },
        "method": {
            "target": "forward 5-trading-day annualized realized variance from simple close-to-close returns",
            "seasonal_stress_months": {k: sorted(v) for k, v in SEASONAL_STRESS_MONTHS.items()},
            "inventory_feature_policy": [
                "weekly EIA as-of dates are delayed by 7 calendar days before daily alignment",
                "inventory z-score and surprise z-score use rolling historical windows shifted by one observation",
                "daily regression features are shifted by one trading day",
                "DBA has no matched inventory proxy and is treated as seasonality-only placebo",
            ],
            "regression": {
                "inventory_assets": (
                    "log(fwd5_RV) ~ lagged log trailing5_RV + seasonal + low_inventory + abs_surprise "
                    "+ seasonal*low_inventory + seasonal*abs_surprise"
                ),
                "dba_placebo": "log(fwd5_RV) ~ lagged log trailing5_RV + seasonal",
                "standard_errors": f"Newey-West HAC maxlags={HAC_LAGS}",
            },
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block_length": BOOTSTRAP_BLOCK, "seed": SEED},
            "success_rule": (
                "PARTIAL requires both tickers in either oil or gas group to have seasonal*low_inventory HAC t > 3; "
                "SUPPORT requires both oil and gas groups to pass"
            ),
        },
        "asset_results": summaries,
        "figures": [FIG_TSTATS.name, FIG_REGIMES.name],
        "literature": [
            {
                "citation": "Gorton, Hayashi, and Rouwenhorst (2013), The Fundamentals of Commodity Futures Returns",
                "url": "https://www.nber.org/papers/w13249",
            },
            {
                "citation": "Futures basis, inventory and commodity price volatility",
                "url": "https://mpra.ub.uni-muenchen.de/39903/",
            },
            {
                "citation": "Pindyck (2004), Volatility and Commodity Price Dynamics",
                "url": "https://web.mit.edu/rpindyck/www/Papers/Volatility_Comm_Price.pdf",
            },
            {
                "citation": "EIA weekly crude oil and natural gas storage data",
                "url": "https://www.eia.gov/",
            },
        ],
        "research_honesty_notes": [
            "Only oil and natural gas have matched public weekly inventory proxies in this experiment.",
            "DBA is not assigned a fake inventory proxy; it is included only as a seasonality placebo.",
            "Inventory values are conservatively delayed and shifted before prediction to avoid report-date lookahead.",
            "This is a forward-RV diagnostic, not a tradable futures inventory-surprise strategy.",
        ],
        "verdict": {
            "overall": verdict,
            "interaction_pass_assets": interaction_pass_assets,
            "group_passes": group_passes,
            "plain_english": (
                "Both oil and gas inventory-seasonality interaction gates pass."
                if verdict == "SUPPORT"
                else "One commodity group passes the paired futures/ETF interaction gate."
                if verdict == "PARTIAL"
                else "The inventory-low regime does not robustly amplify seasonal forward-RV predictability across paired commodity futures/ETFs."
            ),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(json.dumps({k: v["regression_oos_hac"] for k, v in summaries.items()}, indent=2))


if __name__ == "__main__":
    main()
