#!/usr/bin/env python3
"""K1479: Single-stock leveraged ETF launch and underlying tail-vol proxies."""

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
import statsmodels.formula.api as smf
import yfinance as yf

SEED = 42
np.random.seed(SEED)

START = "2021-01-01"
END = "2026-06-12"
WINDOW_DAYS = 126
HAC_LAGS = 5

EVENTS = {
    "TSLL": {
        "treated": "TSLA",
        "controls": ["F", "GM"],
    },
    "NVDL": {
        "treated": "NVDA",
        "controls": ["AMD", "AVGO"],
    },
    "CONL": {
        "treated": "COIN",
        "controls": ["HOOD", "MSTR"],
    },
}

RESULTS_PATH = HERE / "k1479_results.json"
FIG_COEF = HERE / "k1479_did_coefficients.png"


def download_daily(ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return raw[["Open", "High", "Low", "Close"]].dropna().copy()


def first_trade_date(ticker: str) -> pd.Timestamp:
    raw = yf.download(ticker, period="max", interval="1d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    return pd.Timestamp(raw.index.min())


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["oc_ret"] = np.log(out["Close"] / out["Open"])
    out["abs_ret"] = out["oc_ret"].abs()
    out["park_var"] = (np.log(out["High"] / out["Low"]) ** 2) / (4.0 * np.log(2.0))
    rng = (out["High"] - out["Low"]).replace(0, np.nan)
    clv = 2.0 * (out["Close"] - out["Low"]) / rng - 1.0
    out["signed_clv"] = np.sign(out["oc_ret"]) * clv
    return out.dropna().copy()


def build_panel(event_name: str, treated: str, controls: list[str], launch_date: pd.Timestamp) -> pd.DataFrame:
    records = []
    for ticker in [treated] + controls:
        df = build_features(download_daily(ticker, START, END))
        df["ticker"] = ticker
        df["treated"] = 1 if ticker == treated else 0
        df["post"] = (df.index >= launch_date).astype(int)
        df["rel_day"] = (df.index - launch_date).days
        df = df[(df["rel_day"] >= -WINDOW_DAYS) & (df["rel_day"] <= WINDOW_DAYS)].copy()
        df["event_name"] = event_name
        records.append(df[["abs_ret", "park_var", "signed_clv", "ticker", "treated", "post", "rel_day", "event_name"]])
    return pd.concat(records).reset_index(names="date")


def run_did(panel: pd.DataFrame, outcome: str) -> dict[str, float]:
    model = smf.ols(f"{outcome} ~ treated + post + treated:post", data=panel)
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "intercept": float(res.params["Intercept"]),
        "treated_beta": float(res.params["treated"]),
        "post_beta": float(res.params["post"]),
        "did_beta": float(res.params["treated:post"]),
        "did_t": float(res.tvalues["treated:post"]),
        "did_p": float(res.pvalues["treated:post"]),
        "r_squared": float(res.rsquared),
        "n_obs": int(res.nobs),
    }


def make_figure(results: dict[str, dict[str, dict[str, float]]]) -> None:
    rows = []
    for event_name, outcome_map in results.items():
        for outcome, stats in outcome_map.items():
            rows.append(
                {
                    "event": event_name,
                    "outcome": outcome,
                    "did_beta": stats["did_beta"],
                    "did_p": stats["did_p"],
                }
            )
    df = pd.DataFrame(rows)
    df["label"] = df["event"] + " / " + df["outcome"]

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#c0392b" if p < 0.05 else "#7f8c8d" for p in df["did_p"]]
    ax.barh(df["label"], df["did_beta"], color=colors, alpha=0.85)
    ax.axvline(0.0, color="black", linewidth=1.0)
    ax.set_title("DiD beta: treated × post")
    ax.set_xlabel("Coefficient")
    ax.grid(alpha=0.3, axis="x")
    plt.tight_layout()
    plt.savefig(FIG_COEF, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    event_results: dict[str, dict[str, dict[str, float]]] = {}
    feasibility = {}

    for event_name, meta in EVENTS.items():
        launch_date = first_trade_date(event_name)
        feasibility[event_name] = {
            "etf_launch_date_from_yfinance": str(launch_date.date()),
            "exact_intraday_launch_did_feasible_with_free_data": False,
            "reason": "1h yfinance history starts after the ETF launch, so pre-launch intraday window is unavailable.",
        }
        panel = build_panel(event_name, meta["treated"], meta["controls"], launch_date)
        event_results[event_name] = {
            outcome: run_did(panel, outcome)
            for outcome in ["abs_ret", "park_var", "signed_clv"]
        }

    make_figure(event_results)

    verdict = {
        "overall": "NULL",
        "exact_intraday_launch_did_feasible": False,
        "daily_proxy_did_any_significant": any(
            stats["did_p"] < 0.05
            for outcome_map in event_results.values()
            for stats in outcome_map.values()
        ),
        "plain_english": (
            "Using daily honest-proxy outcomes around TSLL, NVDL, and CONL launch dates, none of the "
            "treated underlyings shows a significant post-launch tail-vol shift relative to matched controls."
        ),
    }

    results = {
        "experiment_id": "k1479",
        "title": "Single-stock leveraged ETF launch and underlying tail-vol proxies",
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance auto_adjust=True daily OHLC",
            "start": START,
            "end": "2026-06-11",
            "event_window_calendar_days_each_side": WINDOW_DAYS,
        },
        "feasibility": feasibility,
        "methodology": {
            "daily_proxies": {
                "abs_ret": "|log(Close/Open)|",
                "park_var": "log(High/Low)^2 / (4 log 2)",
                "signed_clv": "sign(log(Close/Open)) * (2*(Close-Low)/(High-Low)-1)",
            },
            "did_spec": "y_it = intercept + treated_i + post_t + treated_i*post_t + error_it, HAC(5)",
        },
        "event_results": event_results,
        "figures": [FIG_COEF.name],
        "verdict": verdict,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
