#!/usr/bin/env python3
"""K1668: Climate policy uncertainty and commodity ETF realized variance.

This experiment tests whether the official monthly news-based U.S. Climate
Policy Uncertainty index adds out-of-sample value beyond a monthly HAR realized
variance baseline for commodity ETF variance.

Anti-lookahead policy
---------------------
Monthly realized variance and CPU observations are first indexed by the month
through which they are observed.  Forecast features are then explicitly lagged
with ``signal = raw_signal.shift(1)`` so target month t uses only information
known through t-1.  OOS regressions are expanding-window one-step monthly
forecasts; row i is forecast using rows strictly before i.

Outputs
-------
- experiments/k1668/K1668_results.json
- experiments/k1668/data/*.csv
- experiments/k1668/figures/K1668_fig1_cpu_commodity_rv.png
- experiments/k1668/figures/K1668_fig2_oos_qlike_improvement.png
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402


EXPERIMENT_ID = "K1668"
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / f"{EXPERIMENT_ID}_results.json"

CPU_URL = (
    "https://raw.githubusercontent.com/dkaenzig/"
    "Climate-Policy-Uncertainty-Index/main/cpu_2026-05.dta"
)
GCPU_PROXY_URL = "https://www.policyuncertainty.com/media/cpu_base_pos_neg_all_countries_monthly.csv"
CPU_CACHE = DATA_DIR / "cpu_2026-05_gkrs.dta"
GCPU_PROXY_CACHE = DATA_DIR / "cpu_all_countries_monthly.csv"
PRICE_CACHE = DATA_DIR / "prices_yfinance_auto_adjust.csv"

TICKERS = ["USO", "UNG", "DBA", "CORN", "WEAT", "GLD"]
SECTOR = {
    "USO": "energy",
    "UNG": "energy",
    "DBA": "agriculture",
    "CORN": "agriculture",
    "WEAT": "agriculture",
    "GLD": "metal",
}
START = "2006-01-01"
TRADING_DAYS = 252.0
RV_FLOOR = 1e-12
INITIAL_TRAIN_MONTHS = 72

BASE_FEATURES = ["log_rv_1", "log_rv_3", "log_rv_12"]
CPU_FEATURES = BASE_FEATURES + ["cpu_log", "cpu_delta"]
GCPU_PROXY_FEATURES = BASE_FEATURES + ["gcpu_proxy_log", "gcpu_proxy_delta"]


@dataclass(frozen=True)
class OLSFit:
    beta: np.ndarray
    x_mean: np.ndarray
    x_std: np.ndarray
    residual_var: float
    r2: float
    n_obs: int


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    with tmp.open("r", encoding="utf-8") as fh:
        json.load(fh)
    os.replace(tmp, path)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_file(url: str, path: Path, *, refresh: bool = False) -> None:
    if path.exists() and not refresh:
        return
    tmp = path.with_suffix(path.suffix + ".download")
    with urllib.request.urlopen(url, timeout=60) as response, tmp.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    if tmp.stat().st_size <= 0:
        raise RuntimeError(f"Downloaded empty file from {url}")
    os.replace(tmp, path)


def load_cpu(refresh: bool = False) -> pd.DataFrame:
    download_file(CPU_URL, CPU_CACHE, refresh=refresh)
    cpu = pd.read_stata(CPU_CACHE)
    cpu["month"] = pd.to_datetime(cpu["date"]).dt.to_period("M").dt.to_timestamp()
    keep = [
        "month",
        "cpu_index_narrow",
        "cpu_index_broad",
        "cpu_index_narrow_llm",
        "cpnews_index_narrow",
        "cpnews_index_broad",
        "cpsent_index",
        "cpu_instrument",
        "cpu_shock",
    ]
    out = cpu[keep].sort_values("month").reset_index(drop=True)
    out.to_csv(DATA_DIR / "cpu_gkrs_2026_05_snapshot.csv", index=False)
    return out


def load_gcpu_proxy(refresh: bool = False) -> pd.DataFrame:
    """Equal-weight free proxy from policyuncertainty.com multi-country CPU data.

    This is not the Gavriilidis/Kanzig/Raghavan/Stock U.S. index.  It is used
    only as a pre-2020 robustness check because the public multi-country file
    currently ends in 2019.
    """

    download_file(GCPU_PROXY_URL, GCPU_PROXY_CACHE, refresh=refresh)
    raw = pd.read_csv(GCPU_PROXY_CACHE)
    raw["month"] = pd.to_datetime(
        {
            "year": pd.to_numeric(raw["year"], errors="coerce"),
            "month": pd.to_numeric(raw["month"], errors="coerce"),
            "day": 1,
        },
        errors="coerce",
    )
    country_cols = [
        col
        for col in raw.columns
        if col.startswith("CPU_")
        and "_pos_" not in col
        and "_neg_" not in col
        and col not in {"CPU_pos_US", "CPU_neg_US"}
    ]
    country_panel = raw[country_cols].apply(pd.to_numeric, errors="coerce")
    out = pd.DataFrame({"month": raw["month"]})
    out["gcpu_proxy_equal_weight"] = country_panel.mean(axis=1, skipna=True)
    out["gcpu_proxy_country_count"] = country_panel.notna().sum(axis=1)
    out.loc[out["gcpu_proxy_country_count"] < 3, "gcpu_proxy_equal_weight"] = np.nan
    out = out.sort_values("month").reset_index(drop=True)
    out.to_csv(DATA_DIR / "gcpu_equal_weight_proxy_snapshot.csv", index=False)
    return out


def download_or_load_prices(refresh: bool = False) -> pd.DataFrame:
    if PRICE_CACHE.exists() and not refresh:
        cached = pd.read_csv(PRICE_CACHE, parse_dates=["date"])
        return cached.sort_values(["ticker", "date"]).reset_index(drop=True)

    import yfinance as yf

    raw = yf.download(
        TICKERS,
        start=START,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no commodity ETF data")

    records: list[pd.DataFrame] = []
    for ticker in TICKERS:
        fields: dict[str, pd.Series] = {}
        for field in ["Open", "High", "Low", "Close", "Volume"]:
            if isinstance(raw.columns, pd.MultiIndex):
                if field not in raw.columns.get_level_values(0) or ticker not in raw[field].columns:
                    raise RuntimeError(f"Missing yfinance field {field}/{ticker}")
                fields[field.lower()] = raw[field][ticker]
            else:
                if field not in raw.columns:
                    raise RuntimeError(f"Missing yfinance field {field}")
                fields[field.lower()] = raw[field]
        sub = pd.DataFrame(fields)
        sub.insert(0, "date", pd.to_datetime(sub.index).tz_localize(None))
        sub.insert(1, "ticker", ticker)
        records.append(sub)

    price = pd.concat(records, ignore_index=True)
    price = price.sort_values(["ticker", "date"]).reset_index(drop=True)
    price.to_csv(PRICE_CACHE, index=False)
    return price


def build_monthly_rv(price: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ticker in TICKERS:
        sub = (
            price.loc[price["ticker"] == ticker, ["date", "close"]]
            .dropna()
            .drop_duplicates("date", keep="last")
            .sort_values("date")
            .set_index("date")
        )
        close = sub["close"].where(sub["close"] > 0).dropna()
        ret = np.log(close).diff().replace([np.inf, -np.inf], np.nan).dropna()
        month_key = ret.index.to_period("M")
        monthly_sum = ret.pow(2).groupby(month_key).sum()
        monthly_n = ret.groupby(month_key).count()
        monthly_ret = ret.groupby(month_key).sum()
        for period, rv_sum in monthly_sum.items():
            n_returns = int(monthly_n.loc[period])
            if n_returns < 10:
                continue
            month = period.to_timestamp()
            rows.append(
                {
                    "month": month,
                    "ticker": ticker,
                    "sector": SECTOR[ticker],
                    "n_returns": n_returns,
                    "monthly_realized_variance_sum": float(max(rv_sum, RV_FLOOR)),
                    "monthly_rv_annualized": float(max(rv_sum * TRADING_DAYS / n_returns, RV_FLOOR)),
                    "monthly_log_return": float(monthly_ret.loc[period]),
                }
            )
    out = pd.DataFrame(rows).sort_values(["ticker", "month"]).reset_index(drop=True)
    out.to_csv(DATA_DIR / "monthly_commodity_etf_rv.csv", index=False)
    return out


def build_design_matrix(monthly_rv: pd.DataFrame, cpu: pd.DataFrame, gcpu: pd.DataFrame) -> pd.DataFrame:
    climate = cpu.merge(gcpu, on="month", how="outer").sort_values("month")
    design_rows: list[pd.DataFrame] = []

    for ticker in TICKERS:
        sub = (
            monthly_rv.loc[monthly_rv["ticker"] == ticker]
            .merge(climate, on="month", how="left")
            .sort_values("month")
            .set_index("month")
        )
        rv = sub["monthly_rv_annualized"].clip(lower=RV_FLOOR)
        raw_signal = pd.DataFrame(index=sub.index)
        raw_signal["log_rv_1"] = np.log(rv)
        raw_signal["log_rv_3"] = np.log(rv.rolling(3, min_periods=3).mean().clip(lower=RV_FLOOR))
        raw_signal["log_rv_12"] = np.log(rv.rolling(12, min_periods=12).mean().clip(lower=RV_FLOOR))
        raw_signal["cpu_log"] = np.log(sub["cpu_index_narrow"].clip(lower=RV_FLOOR))
        raw_signal["cpu_delta"] = raw_signal["cpu_log"].diff()
        raw_signal["gcpu_proxy_log"] = np.log(sub["gcpu_proxy_equal_weight"].clip(lower=RV_FLOOR))
        raw_signal["gcpu_proxy_delta"] = raw_signal["gcpu_proxy_log"].diff()

        # Explicit anti-lookahead rule: target month t uses signals through t-1.
        signal = raw_signal.shift(1)

        out = signal.copy()
        out["target_rv"] = rv
        out["log_target_rv"] = np.log(rv)
        out["target_log_return"] = sub["monthly_log_return"]
        out["n_returns"] = sub["n_returns"]
        out["ticker"] = ticker
        out["sector"] = SECTOR[ticker]
        out["cpu_index_narrow_observed_same_month"] = sub["cpu_index_narrow"]
        out["gcpu_proxy_observed_same_month"] = sub["gcpu_proxy_equal_weight"]
        design_rows.append(out.reset_index())

    design = pd.concat(design_rows, ignore_index=True).sort_values(["ticker", "month"])
    design.to_csv(DATA_DIR / "monthly_design_matrix_shifted.csv", index=False)
    return design


def fit_log_ols(df: pd.DataFrame, feature_cols: list[str]) -> OLSFit:
    y = df["log_target_rv"].to_numpy(dtype=float)
    x_raw = df[feature_cols].to_numpy(dtype=float)
    x_mean = x_raw.mean(axis=0)
    x_std = x_raw.std(axis=0, ddof=0)
    x_std = np.where(x_std > 1e-12, x_std, 1.0)
    x = (x_raw - x_mean) / x_std
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    resid = y - fitted
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
    ddof = min(len(beta), max(len(resid) - 1, 1))
    residual_var = float(np.var(resid, ddof=ddof))
    return OLSFit(
        beta=beta,
        x_mean=x_mean,
        x_std=x_std,
        residual_var=max(residual_var, 0.0),
        r2=r2,
        n_obs=int(len(df)),
    )


def predict_log_ols(fit: OLSFit, row: pd.Series, feature_cols: list[str]) -> float:
    x_raw = np.array([float(row[col]) for col in feature_cols], dtype=float)
    x = (x_raw - fit.x_mean) / fit.x_std
    x = np.concatenate([[1.0], x])
    pred_log = float(x @ fit.beta)
    return float(max(np.exp(pred_log + 0.5 * fit.residual_var), RV_FLOOR))


def run_pair_oos(
    design: pd.DataFrame,
    ticker: str,
    *,
    challenger_name: str,
    challenger_features: list[str],
    initial_train: int = INITIAL_TRAIN_MONTHS,
) -> tuple[dict[str, Any], pd.DataFrame]:
    feature_cols = sorted(set(BASE_FEATURES + challenger_features), key=(BASE_FEATURES + challenger_features).index)
    work = (
        design.loc[design["ticker"] == ticker]
        .dropna(subset=["target_rv", "log_target_rv", *feature_cols])
        .sort_values("month")
        .reset_index(drop=True)
    )
    if len(work) <= initial_train + 10:
        raise RuntimeError(
            f"{ticker}/{challenger_name}: insufficient monthly rows after lags "
            f"({len(work)} <= {initial_train + 10})"
        )

    records: list[dict[str, Any]] = []
    for i in range(initial_train, len(work)):
        train = work.iloc[:i].copy()
        row = work.iloc[i]
        fit_har = fit_log_ols(train, BASE_FEATURES)
        fit_challenger = fit_log_ols(train, challenger_features)
        pred_har = predict_log_ols(fit_har, row, BASE_FEATURES)
        pred_challenger = predict_log_ols(fit_challenger, row, challenger_features)
        records.append(
            {
                "comparison": challenger_name,
                "month": row["month"],
                "ticker": ticker,
                "sector": SECTOR[ticker],
                "actual_rv": float(row["target_rv"]),
                "pred_har": pred_har,
                f"pred_{challenger_name}": pred_challenger,
                "train_n": int(len(train)),
            }
        )

    forecast = pd.DataFrame(records)
    actual = forecast["actual_rv"].to_numpy(dtype=float)
    base_pred = forecast["pred_har"].to_numpy(dtype=float)
    challenger_pred = forecast[f"pred_{challenger_name}"].to_numpy(dtype=float)
    base_loss = qlike_pointwise(actual, base_pred)
    challenger_loss = qlike_pointwise(actual, challenger_pred)
    forecast["loss_har"] = base_loss
    forecast[f"loss_{challenger_name}"] = challenger_loss
    forecast["loss_diff_challenger_minus_har"] = challenger_loss - base_loss

    q_har = float(np.mean(base_loss))
    q_challenger = float(np.mean(challenger_loss))
    dm_t, dm_p = dm_test(challenger_loss, base_loss, h=1)
    mse_har = float(np.mean((actual - base_pred) ** 2))
    mse_challenger = float(np.mean((actual - challenger_pred) ** 2))

    full_fit = fit_log_ols(work, challenger_features)
    beta = dict(zip(["intercept", *challenger_features], full_fit.beta.tolist(), strict=True))

    summary = {
        "ticker": ticker,
        "sector": SECTOR[ticker],
        "comparison": challenger_name,
        "n_monthly_design_rows": int(len(work)),
        "n_oos": int(len(forecast)),
        "initial_train_months": int(initial_train),
        "sample_start": pd.Timestamp(work["month"].iloc[0]).date().isoformat(),
        "sample_end": pd.Timestamp(work["month"].iloc[-1]).date().isoformat(),
        "forecast_start": pd.Timestamp(forecast["month"].iloc[0]).date().isoformat(),
        "forecast_end": pd.Timestamp(forecast["month"].iloc[-1]).date().isoformat(),
        "qlike_har": q_har,
        f"qlike_{challenger_name}": q_challenger,
        "qlike_improvement_pct": float((q_har - q_challenger) / q_har * 100.0),
        "mse_har": mse_har,
        f"mse_{challenger_name}": mse_challenger,
        "mse_improvement_pct": float((mse_har - mse_challenger) / mse_har * 100.0),
        "dm_t_challenger_vs_har": dm_t,
        "dm_p_challenger_vs_har": dm_p,
        "harvey_pass_challenger_better": bool(dm_t < -3.0 and q_challenger < q_har),
        "full_sample_log_ols_r2": full_fit.r2,
        "full_sample_standardized_beta": beta,
    }
    return summary, forecast


def aggregate_loss_summary(forecasts: pd.DataFrame, challenger_name: str, label: str) -> dict[str, Any]:
    loss_col = f"loss_{challenger_name}"
    clustered = (
        forecasts.groupby("month", as_index=False)[["loss_har", loss_col]]
        .mean()
        .dropna(subset=["loss_har", loss_col])
        .sort_values("month")
    )
    if len(clustered) < 10:
        return {
            "label": label,
            "comparison": challenger_name,
            "n_months": int(len(clustered)),
            "qlike_improvement_pct": None,
            "dm_t_challenger_vs_har": None,
            "dm_p_challenger_vs_har": None,
            "harvey_pass_challenger_better": False,
        }
    base = clustered["loss_har"].to_numpy(dtype=float)
    challenger = clustered[loss_col].to_numpy(dtype=float)
    q_har = float(np.mean(base))
    q_challenger = float(np.mean(challenger))
    dm_t, dm_p = dm_test(challenger, base, h=1)
    return {
        "label": label,
        "comparison": challenger_name,
        "n_months": int(len(clustered)),
        "month_start": pd.Timestamp(clustered["month"].iloc[0]).date().isoformat(),
        "month_end": pd.Timestamp(clustered["month"].iloc[-1]).date().isoformat(),
        "qlike_har": q_har,
        f"qlike_{challenger_name}": q_challenger,
        "qlike_improvement_pct": float((q_har - q_challenger) / q_har * 100.0),
        "dm_t_challenger_vs_har": dm_t,
        "dm_p_challenger_vs_har": dm_p,
        "harvey_pass_challenger_better": bool(dm_t < -3.0 and q_challenger < q_har),
    }


def run_comparison_set(
    design: pd.DataFrame,
    *,
    challenger_name: str,
    challenger_features: list[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    asset_summaries: dict[str, Any] = {}
    forecast_frames: list[pd.DataFrame] = []
    for ticker in TICKERS:
        summary, forecast = run_pair_oos(
            design,
            ticker,
            challenger_name=challenger_name,
            challenger_features=challenger_features,
        )
        asset_summaries[ticker] = summary
        forecast_frames.append(forecast)

    forecasts = pd.concat(forecast_frames, ignore_index=True).sort_values(["month", "ticker"])
    group_summaries = {
        group: aggregate_loss_summary(
            forecasts.loc[forecasts["sector"] == group],
            challenger_name,
            group,
        )
        for group in ["energy", "agriculture", "metal"]
    }
    overall = aggregate_loss_summary(forecasts, challenger_name, "all_assets_date_clustered")
    return {
        "challenger_name": challenger_name,
        "baseline_features": BASE_FEATURES,
        "challenger_features": challenger_features,
        "asset_results": asset_summaries,
        "sector_results": group_summaries,
        "overall_date_clustered": overall,
    }, forecasts


def make_figures(
    monthly_rv: pd.DataFrame,
    cpu: pd.DataFrame,
    comparison: dict[str, Any],
    *,
    challenger_name: str = "har_cpu",
) -> list[str]:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    avg_rv = (
        monthly_rv.groupby("month", as_index=False)["monthly_rv_annualized"]
        .mean()
        .rename(columns={"monthly_rv_annualized": "avg_commodity_rv"})
    )
    chart = avg_rv.merge(cpu[["month", "cpu_index_narrow"]], on="month", how="inner")
    chart = chart.loc[chart["month"] >= pd.Timestamp("2006-01-01")].copy()
    chart["avg_rv_3m"] = chart["avg_commodity_rv"].rolling(3, min_periods=1).mean()
    chart["cpu_3m"] = chart["cpu_index_narrow"].rolling(3, min_periods=1).mean()

    fig, ax1 = plt.subplots(figsize=(10.7, 5.3))
    ax1.plot(chart["month"], chart["cpu_3m"], color="#8B1E3F", lw=2.0, label="CPU index, 3m avg")
    ax1.set_ylabel("CPU index")
    ax1.set_title("K1668: Climate Policy Uncertainty vs Commodity ETF Realized Variance")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(
        chart["month"],
        chart["avg_rv_3m"],
        color="#1F77B4",
        lw=1.8,
        label="Equal-weight commodity ETF RV, 3m avg",
    )
    ax2.set_ylabel("Annualized monthly realized variance")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], loc="upper left", frameon=False)
    ax1.text(
        0.01,
        -0.16,
        "Sources: GKRS CPU dataset; Yahoo Finance adjusted closes via yfinance. Monthly signals are shifted by one month.",
        transform=ax1.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="#555555",
    )
    fig.tight_layout()
    fig1 = FIG_DIR / "K1668_fig1_cpu_commodity_rv.png"
    fig.savefig(fig1, bbox_inches="tight")
    plt.close(fig)

    rows = []
    for ticker, item in comparison["asset_results"].items():
        rows.append(
            {
                "label": ticker,
                "improvement": item["qlike_improvement_pct"],
                "pass": item["harvey_pass_challenger_better"],
                "kind": "asset",
            }
        )
    for sector, item in comparison["sector_results"].items():
        rows.append(
            {
                "label": sector,
                "improvement": item["qlike_improvement_pct"],
                "pass": item["harvey_pass_challenger_better"],
                "kind": "sector",
            }
        )
    rows.append(
        {
            "label": "all",
            "improvement": comparison["overall_date_clustered"]["qlike_improvement_pct"],
            "pass": comparison["overall_date_clustered"]["harvey_pass_challenger_better"],
            "kind": "overall",
        }
    )
    bars = pd.DataFrame(rows)
    colors = ["#2E7D32" if v > 0 else "#B23A48" for v in bars["improvement"]]
    fig, ax = plt.subplots(figsize=(10.7, 5.3))
    x = np.arange(len(bars))
    ax.bar(x, bars["improvement"], color=colors, alpha=0.88)
    ax.axhline(0, color="#333333", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(bars["label"], rotation=0)
    ax.set_ylabel("OOS QLIKE improvement vs HAR (%)")
    ax.set_title("K1668: HAR + lagged CPU vs monthly HAR baseline")
    ax.grid(axis="y", alpha=0.25)
    for idx, row in bars.iterrows():
        val = float(row["improvement"])
        marker = " *" if bool(row["pass"]) else ""
        va = "bottom" if val >= 0 else "top"
        offset = 0.15 if val >= 0 else -0.15
        ax.text(idx, val + offset, f"{val:+.2f}%{marker}", ha="center", va=va, fontsize=8)
    ax.text(
        0.01,
        -0.16,
        "* Harvey pass requires challenger-better DM t < -3 using date-clustered monthly losses.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="#555555",
    )
    fig.tight_layout()
    fig2 = FIG_DIR / "K1668_fig2_oos_qlike_improvement.png"
    fig.savefig(fig2, bbox_inches="tight")
    plt.close(fig)

    return [str(fig1.relative_to(HERE)), str(fig2.relative_to(HERE))]


def derive_verdict(main: dict[str, Any]) -> dict[str, str]:
    overall = main["overall_date_clustered"]
    group_passes = [
        group
        for group, item in main["sector_results"].items()
        if item.get("harvey_pass_challenger_better")
    ]
    improvement = overall.get("qlike_improvement_pct")
    overall_pass = bool(overall.get("harvey_pass_challenger_better"))
    if overall_pass:
        verdict = "CONDITIONAL_PASS_OVERALL_CPU_ADDS_OOS_QLIKE"
        plain = "Lagged U.S. CPU improves date-clustered OOS QLIKE beyond monthly HAR overall."
    elif group_passes:
        verdict = "CONDITIONAL_PASS_SECTOR_SPECIFIC_CPU_SIGNAL"
        plain = "Lagged U.S. CPU improves OOS QLIKE only in selected commodity sectors."
    elif improvement is not None and improvement > 0:
        verdict = "WEAK_POSITIVE_NOT_HARVEY_PASS"
        plain = "Lagged U.S. CPU has a positive overall point estimate, but does not clear the Harvey t<-3 gate."
    else:
        verdict = "NULL_NO_OOS_CPU_INCREMENT"
        plain = "Lagged U.S. CPU does not improve OOS QLIKE beyond the monthly HAR baseline in this ETF proxy."
    return {
        "verdict": verdict,
        "plain_english": plain,
        "group_harvey_passes": ", ".join(group_passes) if group_passes else "none",
    }


def run(refresh: bool = False) -> dict[str, Any]:
    ensure_dirs()
    cpu = load_cpu(refresh=refresh)
    gcpu = load_gcpu_proxy(refresh=refresh)
    price = download_or_load_prices(refresh=refresh)
    monthly_rv = build_monthly_rv(price)
    design = build_design_matrix(monthly_rv, cpu, gcpu)

    main_comparison, cpu_forecasts = run_comparison_set(
        design,
        challenger_name="har_cpu",
        challenger_features=CPU_FEATURES,
    )
    gcpu_comparison, gcpu_forecasts = run_comparison_set(
        design,
        challenger_name="har_gcpu_proxy",
        challenger_features=GCPU_PROXY_FEATURES,
    )

    cpu_forecasts.to_csv(DATA_DIR / "oos_forecasts_har_cpu.csv", index=False)
    gcpu_forecasts.to_csv(DATA_DIR / "oos_forecasts_har_gcpu_proxy.csv", index=False)
    figure_paths = make_figures(monthly_rv, cpu, main_comparison)
    verdict = derive_verdict(main_comparison)

    price_summary = (
        price.dropna(subset=["close"])
        .groupby("ticker")
        .agg(first_date=("date", "min"), last_date=("date", "max"), daily_rows=("close", "count"))
        .reset_index()
    )
    monthly_summary = (
        monthly_rv.groupby("ticker")
        .agg(
            first_month=("month", "min"),
            last_month=("month", "max"),
            monthly_rows=("month", "count"),
            mean_rv_ann=("monthly_rv_annualized", "mean"),
        )
        .reset_index()
    )

    payload: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict["verdict"],
        "plain_english": verdict["plain_english"],
        "data_sources": {
            "cpu_primary": {
                "url": CPU_URL,
                "local_cache": str(CPU_CACHE.relative_to(HERE)),
                "source_note": "Gavriilidis, Kanzig, Raghavan, and Stock 2026 monthly U.S. Climate Policy Uncertainty dataset.",
                "primary_field": "cpu_index_narrow",
                "available_months": {
                    "start": pd.Timestamp(cpu["month"].min()).date().isoformat(),
                    "end": pd.Timestamp(cpu["month"].max()).date().isoformat(),
                    "n": int(cpu["cpu_index_narrow"].notna().sum()),
                },
            },
            "gcpu_proxy_robustness": {
                "url": GCPU_PROXY_URL,
                "local_cache": str(GCPU_PROXY_CACHE.relative_to(HERE)),
                "source_note": "Equal-weight proxy from public multi-country CPU file; pre-2020 robustness only, not the GKRS U.S. index.",
                "available_months_with_at_least_3_countries": {
                    "start": pd.Timestamp(
                        gcpu.loc[gcpu["gcpu_proxy_equal_weight"].notna(), "month"].min()
                    ).date().isoformat(),
                    "end": pd.Timestamp(
                        gcpu.loc[gcpu["gcpu_proxy_equal_weight"].notna(), "month"].max()
                    ).date().isoformat(),
                    "n": int(gcpu["gcpu_proxy_equal_weight"].notna().sum()),
                },
            },
            "prices": {
                "source": "Yahoo Finance via yfinance.download(auto_adjust=True)",
                "tickers": TICKERS,
                "local_cache": str(PRICE_CACHE.relative_to(HERE)),
            },
        },
        "data_summary": {
            "daily_price_rows_by_ticker": price_summary.to_dict(orient="records"),
            "monthly_rv_rows_by_ticker": monthly_summary.to_dict(orient="records"),
            "monthly_target": "monthly sum of squared adjusted-close log returns, annualized by 252 / monthly trading-day count",
        },
        "methodology": {
            "frequency": "monthly",
            "target": "next-month annualized realized variance proxy from commodity ETF adjusted close returns",
            "baseline": "log-HAR using lagged 1m, 3m, and 12m realized variance",
            "challenger": "log-HAR plus lagged log CPU and lagged monthly CPU log change",
            "anti_lookahead": "raw monthly RV and CPU features are indexed at month t, then signal = raw_signal.shift(1); OOS row i is fit on work.iloc[:i]",
            "loss": "QLIKE pointwise losses from volpred.stats.model_evaluation.qlike_pointwise",
            "inference": "Diebold-Mariano HAC h=1; Harvey-style practical pass requires challenger-better t < -3",
            "cross_asset_inference": "date-clustered: per-month mean loss across assets before DM",
            "initial_train_months": INITIAL_TRAIN_MONTHS,
        },
        "main_oos_har_cpu": main_comparison,
        "gcpu_equal_weight_proxy_robustness_pre2020": gcpu_comparison,
        "figures": figure_paths,
        "conclusion": {
            "verdict": verdict["verdict"],
            "plain_english": verdict["plain_english"],
            "sector_harvey_passes": verdict["group_harvey_passes"],
            "research_honesty_notes": [
                "This is a commodity ETF proxy test, not a futures-contract replication of the Journal of Futures Markets article.",
                "The primary CPU series is U.S. GKRS CPU through 2026-04; the GCPU proxy is a shorter public equal-weight multi-country robustness series ending 2019.",
                "All forecast signals are lagged one month with signal = raw_signal.shift(1).",
            ],
        },
        "references": [
            {
                "key": "Gavriilidis-Kanzig-Raghavan-Stock-2026",
                "url": "https://www.nber.org/papers/w34762",
                "role": "Official U.S. CPU paper and supply-shock motivation.",
            },
            {
                "key": "GKRS-CPU-data",
                "url": "https://github.com/dkaenzig/Climate-Policy-Uncertainty-Index",
                "role": "Official downloadable monthly CPU dataset.",
            },
            {
                "key": "Zhu-Wu-Wan-Li-2026",
                "url": "https://ideas.repec.org/a/wly/jfutmk/v46y2026i1p197-220.html",
                "role": "Commodity futures volatility risk motivation and sector heterogeneity claim.",
            },
            {
                "key": "Bakas-Triantafyllou-2018",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0261560617302516",
                "role": "Prior evidence linking uncertainty shocks and commodity price volatility.",
            },
        ],
    }

    atomic_write_json(RESULTS_PATH, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download CPU and yfinance data")
    args = parser.parse_args()
    payload = run(refresh=args.refresh)
    overall = payload["main_oos_har_cpu"]["overall_date_clustered"]
    print(
        f"{EXPERIMENT_ID} {payload['verdict']}: "
        f"overall QLIKE improvement={overall['qlike_improvement_pct']:+.3f}% "
        f"DM t={overall['dm_t_challenger_vs_har']:.3f}"
    )
    print(f"Results: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
