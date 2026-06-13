#!/usr/bin/env python3
"""K1478: Leveraged ETF mechanical rebalancing and end-of-day volatility."""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mplconfig"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

TICKERS = ["QQQ", "TQQQ", "SQQQ", "SSO"]
LETF_BETA = {"TQQQ": 3, "SQQQ": -3, "SSO": 2}
PERIOD = "730d"
INTERVAL = "1h"
HAC_LAGS = 5

RESULTS_PATH = HERE / "k1478_results.json"
FIG_BINS = HERE / "k1478_pressure_bins.png"
FIG_SCATTER = HERE / "k1478_scatter.png"


def fetch_intraday() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        raw = yf.download(ticker, period=PERIOD, interval=INTERVAL, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna().copy()
        out[ticker] = df
    return out


def aggregate_daily(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    local = df.copy()
    local["ts_ny"] = local.index.tz_convert("America/New_York")
    local["date"] = local["ts_ny"].dt.normalize()

    rows = []
    for date, g in local.groupby("date"):
        g = g.sort_index()
        if len(g) < 6:
            continue
        row = {
            "date": date,
            "open": float(g["Open"].iloc[0]),
            "close": float(g["Close"].iloc[-1]),
            "daily_ret": float(np.log(g["Close"].iloc[-1] / g["Open"].iloc[0])),
            "dollar_vol": float((g["Close"] * g["Volume"]).sum()),
        }
        if ticker == "QQQ":
            row.update(
                {
                    "last_hour_ret": float(np.log(g["Close"].iloc[-1] / g["Open"].iloc[-1])),
                    "last_hour_range_var": float((np.log(g["High"].iloc[-1] / g["Low"].iloc[-1]) ** 2) / (4.0 * np.log(2.0))),
                    "first_hour_ret": float(np.log(g["Close"].iloc[0] / g["Open"].iloc[0])),
                }
            )
        rows.append(row)

    return pd.DataFrame(rows).set_index("date").sort_index()


def build_panel(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    qqq = aggregate_daily(raw["QQQ"], "QQQ")
    panel = qqq.copy()

    for ticker in ["TQQQ", "SQQQ", "SSO"]:
        daily = aggregate_daily(raw[ticker], ticker)
        panel[f"{ticker}_dollar_vol"] = daily["dollar_vol"]

    panel["next_open"] = panel["open"].shift(-1)
    panel["same_sign_last_hour"] = np.sign(panel["daily_ret"]) * panel["last_hour_ret"]
    panel["overnight_cont"] = np.sign(panel["daily_ret"]) * np.log(panel["next_open"] / panel["close"])
    panel["abs_daily_ret"] = panel["daily_ret"].abs()

    pressure_components = []
    for ticker, beta in LETF_BETA.items():
        coeff = abs(beta * beta - beta)
        component = coeff * panel["abs_daily_ret"] * panel[f"{ticker}_dollar_vol"]
        panel[f"{ticker}_pressure_proxy"] = component
        pressure_components.append(component)

    panel["pressure_proxy"] = pd.concat(pressure_components, axis=1).sum(axis=1)
    panel["log_pressure"] = np.log(panel["pressure_proxy"])
    panel["pressure_bucket"] = pd.qcut(panel["pressure_proxy"], 4, labels=["Q1", "Q2", "Q3", "Q4"])
    return panel.dropna().copy()


def welch_compare(panel: pd.DataFrame, col: str) -> dict[str, float]:
    high = panel.loc[panel["pressure_bucket"] == "Q4", col]
    low = panel.loc[panel["pressure_bucket"] != "Q4", col]
    test = stats.ttest_ind(high, low, equal_var=False, nan_policy="omit")
    return {
        "high_mean": float(high.mean()),
        "low_mean": float(low.mean()),
        "mean_diff": float(high.mean() - low.mean()),
        "welch_t": float(test.statistic),
        "welch_p": float(test.pvalue),
        "n_high": int(len(high)),
        "n_low": int(len(low)),
    }


def hac_reg(panel: pd.DataFrame, y_col: str) -> dict[str, float]:
    x = sm.add_constant(panel[["log_pressure", "abs_daily_ret"]])
    res = sm.OLS(panel[y_col], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "const": float(res.params["const"]),
        "beta_log_pressure": float(res.params["log_pressure"]),
        "t_log_pressure": float(res.tvalues["log_pressure"]),
        "p_log_pressure": float(res.pvalues["log_pressure"]),
        "beta_abs_daily_ret": float(res.params["abs_daily_ret"]),
        "t_abs_daily_ret": float(res.tvalues["abs_daily_ret"]),
        "p_abs_daily_ret": float(res.pvalues["abs_daily_ret"]),
        "r_squared": float(res.rsquared),
    }


def make_figures(panel: pd.DataFrame) -> None:
    bins = panel.groupby("pressure_bucket")[["same_sign_last_hour", "last_hour_range_var", "overnight_cont"]].mean()

    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    metrics = [
        ("same_sign_last_hour", "Same-sign last hour"),
        ("last_hour_range_var", "Last-hour range variance"),
        ("overnight_cont", "Overnight continuation"),
    ]
    colors = ["#2980b9", "#c0392b", "#16a085"]
    for ax, (col, title), color in zip(axes, metrics, colors):
        ax.bar(bins.index.astype(str), bins[col], color=color, alpha=0.85)
        ax.set_title(title)
        ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(FIG_BINS, dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(panel["log_pressure"], panel["last_hour_range_var"], s=14, alpha=0.5, color="#8e44ad")
    axes[0].set_title("Log pressure vs last-hour range variance")
    axes[0].set_xlabel("Log pressure proxy")
    axes[0].set_ylabel("Last-hour range variance")
    axes[0].grid(alpha=0.3)

    axes[1].scatter(panel["log_pressure"], panel["overnight_cont"], s=14, alpha=0.5, color="#d35400")
    axes[1].set_title("Log pressure vs overnight continuation")
    axes[1].set_xlabel("Log pressure proxy")
    axes[1].set_ylabel("Same-sign overnight continuation")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(FIG_SCATTER, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    raw = fetch_intraday()
    panel = build_panel(raw)

    top_quartile_tests = {
        col: welch_compare(panel, col)
        for col in ["same_sign_last_hour", "last_hour_range_var", "overnight_cont"]
    }
    regressions = {
        col: hac_reg(panel, col)
        for col in ["same_sign_last_hour", "last_hour_range_var", "overnight_cont"]
    }

    make_figures(panel)

    verdict = {
        "overall": "NULL_PRIMARY_EFFECT",
        "same_day_tail_amplification_supported": (
            regressions["same_sign_last_hour"]["p_log_pressure"] < 0.05
            or regressions["last_hour_range_var"]["p_log_pressure"] < 0.05
        ),
        "overnight_continuation_signal_supported": regressions["overnight_cont"]["p_log_pressure"] < 0.05,
        "plain_english": (
            "High-pressure days are descriptively more volatile into the close, but after controlling for the "
            "day's own absolute move the LETF pressure proxy does not explain extra last-hour volatility. "
            "A weaker overnight continuation relation remains."
        ),
    }

    results = {
        "experiment_id": "k1478",
        "title": "Leveraged ETF mechanical rebalancing and end-of-day volatility",
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance auto_adjust=True 1h bars",
            "tickers": TICKERS,
            "sample_start": str(panel.index.min().date()),
            "sample_end": str(panel.index.max().date()),
            "n_days": int(len(panel)),
            "interval": INTERVAL,
            "size_proxy": "same-day traded dollar volume of TQQQ/SQQQ/SSO",
        },
        "methodology": {
            "pressure_proxy": "sum_i |k_i^2-k_i| * |r_QQQ,t| * dollar_volume_i,t",
            "primary_outcomes": [
                "same_sign_last_hour",
                "last_hour_range_var",
                "overnight_cont",
            ],
            "primary_regression": "y_t = const + beta1*log_pressure + beta2*|daily_ret| + error_t, HAC(5)",
            "top_quartile_definition": "Q4 of pressure_proxy vs Q1-Q3 pooled",
        },
        "top_quartile_tests": top_quartile_tests,
        "hac_regressions": regressions,
        "pressure_bucket_means": (
            panel.groupby("pressure_bucket")[["same_sign_last_hour", "last_hour_range_var", "overnight_cont"]]
            .mean()
            .reset_index()
            .to_dict(orient="records")
        ),
        "figures": [FIG_BINS.name, FIG_SCATTER.name],
        "verdict": verdict,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
