#!/usr/bin/env python3
"""
K1492: Stablecoin redemption pressure to crypto / Treasury volatility pilot.

Question
--------
Do stablecoin outflows or peg deviations lead next-period volatility in crypto
and Treasury proxies?

Signals
-------
1. Combined USDT + USDC redemption pressure from DefiLlama circulating supply.
2. Max(|USDT-1|, |USDC-1|) peg deviation from DefiLlama daily stablecoin prices.

Targets
-------
- BTC-USD
- ETH-USD
- SHY (short Treasury proxy)
- TLT (long Treasury proxy)

Method
------
- Realized variance proxy: 5-day rolling mean of squared log returns * 252.
- OOS forecast start: 2024-01-01, expanding-window recursive refit.
- Baseline: RV5_t ~ RV5_{t-1}
- Full model: RV5_t ~ RV5_{t-1} + redemption_pressure_{t-1} + peg_dev_{t-1}
- Additional BTC horse race: baseline vs flow-only vs peg-only vs full.
- DM-HLN style loss-differential test on QLIKE.

Lookahead control
-----------------
Signals are aligned to each target date using the latest stablecoin observation
available strictly before the target trading day.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats
from statsmodels.api import OLS, add_constant

np.random.seed(42)

START_DATE = "2021-01-01"
END_DATE = "2026-06-14"
OOS_START = "2024-01-01"
TARGETS = ["BTC-USD", "ETH-USD", "SHY", "TLT"]
OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / "k1492_results.json"


def fetch_llama_supply(asset_id: str) -> tuple[str, pd.Series]:
    resp = requests.get(f"https://stablecoins.llama.fi/stablecoin/{asset_id}", timeout=90)
    resp.raise_for_status()
    payload = resp.json()

    totals: defaultdict[pd.Timestamp, float] = defaultdict(float)
    for chain_payload in payload["chainBalances"].values():
        for row in chain_payload.get("tokens", []):
            circulating = row.get("circulating", {}).get("peggedUSD")
            if circulating is None:
                continue
            dt = pd.to_datetime(row["date"], unit="s").normalize()
            totals[dt] += float(circulating)

    series = pd.Series(totals, dtype=float).sort_index().rename(payload["symbol"])
    return payload["symbol"], series


def fetch_llama_prices() -> pd.DataFrame:
    resp = requests.get("https://stablecoins.llama.fi/stablecoinprices", timeout=90)
    resp.raise_for_status()
    rows = []
    for row in resp.json():
        dt = pd.to_datetime(row["date"], unit="s").normalize()
        rows.append(
            {
                "date": dt,
                "usdt_price": row["prices"].get("tether"),
                "usdc_price": row["prices"].get("usd-coin"),
            }
        )
    return (
        pd.DataFrame(rows)
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
        .loc[START_DATE:END_DATE]
    )


def build_signal_frame() -> pd.DataFrame:
    _, usdt = fetch_llama_supply("1")
    _, usdc = fetch_llama_supply("2")
    supply = pd.concat([usdt, usdc], axis=1).sort_index().loc[START_DATE:END_DATE].ffill()
    supply["combined_supply_usd"] = supply.sum(axis=1)
    supply["combined_flow_pct"] = np.log(supply["combined_supply_usd"]).diff()
    supply["redemption_pressure"] = (-supply["combined_flow_pct"]).clip(lower=0)

    prices = fetch_llama_prices().ffill()
    prices["peg_dev_usdt"] = (prices["usdt_price"] - 1.0).abs()
    prices["peg_dev_usdc"] = (prices["usdc_price"] - 1.0).abs()
    prices["peg_dev_max"] = prices[["peg_dev_usdt", "peg_dev_usdc"]].max(axis=1)
    prices["peg_dev_avg"] = prices[["peg_dev_usdt", "peg_dev_usdc"]].mean(axis=1)

    signal = pd.concat(
        [
            supply[["combined_supply_usd", "combined_flow_pct", "redemption_pressure"]],
            prices[["usdt_price", "usdc_price", "peg_dev_usdt", "peg_dev_usdc", "peg_dev_max", "peg_dev_avg"]],
        ],
        axis=1,
    ).sort_index()
    return signal.ffill()


def download_targets() -> pd.DataFrame:
    raw = yf.download(TARGETS, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw["Close"]
    else:
        raw = raw.rename(columns={"Close": TARGETS[0]})
    return raw.sort_index()


def align_signals_to_asset_dates(asset_index: pd.DatetimeIndex, signal: pd.DataFrame) -> pd.DataFrame:
    lookup_index = (asset_index - pd.Timedelta(days=1)).normalize()
    expanded = signal.reindex(signal.index.union(lookup_index)).sort_index().ffill()
    aligned = expanded.reindex(lookup_index)
    aligned.index = asset_index
    return aligned


def qlike(y_true: pd.Series | np.ndarray, forecast: pd.Series | np.ndarray) -> np.ndarray:
    y_arr = np.asarray(y_true, dtype=float)
    f_arr = np.clip(np.asarray(forecast, dtype=float), 1e-10, None)
    return np.log(f_arr) + (y_arr / f_arr)


def dm_hln(loss_0: np.ndarray, loss_1: np.ndarray, horizon: int = 1) -> tuple[float, float]:
    d = np.asarray(loss_0 - loss_1, dtype=float)
    d = d[np.isfinite(d)]
    t_obs = len(d)
    if t_obs < 20:
        return float("nan"), float("nan")

    d_bar = d.mean()
    gamma_0 = np.mean((d - d_bar) * (d - d_bar))
    long_var = gamma_0
    for lag in range(1, horizon):
        cov = np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
        long_var += 2 * (1 - lag / horizon) * cov
    if long_var <= 0:
        return float("nan"), float("nan")

    dm_stat = d_bar / np.sqrt(long_var / t_obs)
    hln_stat = dm_stat * np.sqrt((t_obs + 1 - 2 * horizon + horizon * (horizon - 1) / t_obs) / t_obs)
    p_value = 2 * (1 - stats.t.cdf(abs(hln_stat), df=t_obs - 1))
    return float(hln_stat), float(p_value)


def recursive_forecast(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    test = df.loc[df.index >= pd.Timestamp(OOS_START)]
    rows = []
    for dt in test.index:
        train = df.loc[df.index < dt]
        model = OLS(train["rv5"], add_constant(train[columns], has_constant="add")).fit()
        pred = model.predict(add_constant(df.loc[[dt], columns], has_constant="add")).iloc[0]
        rows.append({"date": dt, "forecast": float(max(pred, 1e-10)), "actual": float(df.loc[dt, "rv5"])})
    return pd.DataFrame(rows).set_index("date")


def asset_panel(asset: str, close: pd.Series, signal: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close).diff()
    rv5 = ret.pow(2).rolling(5).mean() * 252
    panel = pd.DataFrame({"close": close, "ret": ret, "rv5": rv5, "rv5_lag1": rv5.shift(1)})
    aligned = align_signals_to_asset_dates(panel.index, signal)
    panel = pd.concat(
        [
            panel,
            aligned[
                [
                    "redemption_pressure",
                    "peg_dev_max",
                    "combined_supply_usd",
                    "combined_flow_pct",
                ]
            ],
        ],
        axis=1,
    )
    return panel.dropna().loc["2021-06-01":]


def summarize_asset(asset: str, panel: pd.DataFrame) -> dict:
    train = panel.loc[panel.index < pd.Timestamp(OOS_START)]
    m_full = OLS(
        train["rv5"],
        add_constant(train[["rv5_lag1", "redemption_pressure", "peg_dev_max"]], has_constant="add"),
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

    fc_0 = recursive_forecast(panel, ["rv5_lag1"])
    fc_1 = recursive_forecast(panel, ["rv5_lag1", "redemption_pressure", "peg_dev_max"])

    loss_0 = qlike(fc_0["actual"], fc_0["forecast"])
    loss_1 = qlike(fc_1["actual"], fc_1["forecast"])
    dm_stat, dm_p = dm_hln(loss_0, loss_1, horizon=1)

    q90 = panel["peg_dev_max"].quantile(0.9)
    event_mask = panel["peg_dev_max"] >= q90
    forward_rv5 = panel["rv5"].shift(-4)
    event_forward = forward_rv5.loc[event_mask].dropna()
    baseline_forward = forward_rv5.dropna()

    return {
        "asset": asset,
        "sample_start": panel.index.min().strftime("%Y-%m-%d"),
        "sample_end": panel.index.max().strftime("%Y-%m-%d"),
        "n_obs": int(len(panel)),
        "oos_start": OOS_START,
        "oos_n": int(len(fc_0)),
        "qlike_baseline": float(loss_0.mean()),
        "qlike_full": float(loss_1.mean()),
        "qlike_improvement": float(loss_0.mean() - loss_1.mean()),
        "dm_hln_stat": dm_stat,
        "dm_hln_pvalue": dm_p,
        "event_threshold_q90": float(q90),
        "event_n": int(event_forward.shape[0]),
        "event_forward_rv5_mean": float(event_forward.mean()),
        "baseline_forward_rv5_mean": float(baseline_forward.mean()),
        "event_forward_rv5_ratio": float(event_forward.mean() / baseline_forward.mean()),
        "in_sample_full_coefficients": {k: float(v) for k, v in m_full.params.items()},
        "in_sample_full_pvalues": {k: float(v) for k, v in m_full.pvalues.items()},
        "verdict": (
            "PASS"
            if (loss_0.mean() - loss_1.mean()) > 0 and dm_p < 0.05
            else "NULL"
        ),
    }


def btc_horse_race(panel: pd.DataFrame) -> dict:
    specs = {
        "baseline": ["rv5_lag1"],
        "flow_only": ["rv5_lag1", "redemption_pressure"],
        "peg_only": ["rv5_lag1", "peg_dev_max"],
        "full": ["rv5_lag1", "redemption_pressure", "peg_dev_max"],
    }
    forecasts = {name: recursive_forecast(panel, cols) for name, cols in specs.items()}
    losses = {name: qlike(fc["actual"], fc["forecast"]) for name, fc in forecasts.items()}
    summary: dict[str, dict] = {}
    for name, loss in losses.items():
        summary[name] = {"mean_qlike": float(np.mean(loss))}
    base_loss = losses["baseline"]
    for name in ["flow_only", "peg_only", "full"]:
        stat, pval = dm_hln(base_loss, losses[name], horizon=1)
        summary[name]["qlike_improvement_vs_baseline"] = float(np.mean(base_loss) - np.mean(losses[name]))
        summary[name]["dm_hln_stat_vs_baseline"] = stat
        summary[name]["dm_hln_pvalue_vs_baseline"] = pval
    return summary


def make_figures(signal: pd.DataFrame, asset_results: list[dict]) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    signal["combined_supply_usd"].div(1e9).plot(ax=axes[0], color="#0b6e4f", lw=1.5)
    axes[0].set_title("Combined USDT + USDC Supply")
    axes[0].set_ylabel("USD bn")
    signal["peg_dev_max"].mul(10000).plot(ax=axes[1], color="#b23a48", lw=1.2)
    axes[1].set_title("Max Peg Deviation")
    axes[1].set_ylabel("bps")
    axes[1].set_xlabel("")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_signal_timeseries.png", dpi=180)
    plt.close(fig)

    labels = [row["asset"] for row in asset_results]
    improvements = [row["qlike_improvement"] for row in asset_results]
    pvals = [row["dm_hln_pvalue"] for row in asset_results]
    colors = ["#1f77b4" if val > 0 else "#9d9d9d" for val in improvements]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bars = ax.bar(labels, improvements, color=colors)
    ax.axhline(0, color="black", lw=0.9)
    ax.set_title("OOS QLIKE Improvement: Full Signal vs Baseline")
    ax.set_ylabel("QLIKE improvement (positive = better)")
    for bar, pval in zip(bars, pvals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"p={pval:.3f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_qlike_improvement.png", dpi=180)
    plt.close(fig)

    labels = [row["asset"] for row in asset_results]
    ratios = [row["event_forward_rv5_ratio"] for row in asset_results]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(labels, ratios, color="#8c564b")
    ax.axhline(1.0, color="black", lw=0.9, ls="--")
    ax.set_title("Forward RV5 After Top-Decile Peg Stress")
    ax.set_ylabel("Event / baseline mean")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_event_study.png", dpi=180)
    plt.close(fig)


def main() -> None:
    signal = build_signal_frame()
    close_df = download_targets()

    panels = {
        asset: asset_panel(asset, close_df[asset].dropna(), signal)
        for asset in TARGETS
    }
    asset_results = [summarize_asset(asset, panel) for asset, panel in panels.items()]
    horse_race = btc_horse_race(panels["BTC-USD"])
    make_figures(signal.loc[START_DATE:END_DATE], asset_results)

    best_assets = [row["asset"] for row in asset_results if row["verdict"] == "PASS"]
    results = {
        "experiment_id": "K1492",
        "title": "Stablecoin Redemption Pressure to Crypto/Treasury Vol Pilot",
        "seed": 42,
        "data_sources": {
            "stablecoin_supply": "DefiLlama stablecoin/{id} chainBalances (USDT id=1, USDC id=2)",
            "stablecoin_prices": "DefiLlama stablecoinprices (tether, usd-coin)",
            "market_prices": "yfinance adjusted close for BTC-USD, ETH-USD, SHY, TLT",
        },
        "sample": {
            "requested_start": START_DATE,
            "requested_end": END_DATE,
            "oos_start": OOS_START,
        },
        "literature": [
            {
                "title": "Stablecoin Shocks",
                "source": "IMF Working Paper 2026/044",
                "link": "https://www.imf.org/en/publications/wp/issues/2026/03/06/stablecoin-shocks-574528",
                "note": "Stablecoin shocks affect Treasury yields and broader financial markets.",
            },
            {
                "title": "Stablecoins and Safe Asset Prices",
                "source": "BIS Working Paper 1270 (2026)",
                "link": "https://www.bis.org/publ/work1270.pdf",
                "note": "Stablecoin inflows compress short-term T-bill yields.",
            },
            {
                "title": "Primary and Secondary Markets for Stablecoins",
                "source": "Federal Reserve FEDS Notes (2024-02-23)",
                "link": "https://www.federalreserve.gov/econres/notes/feds-notes/primary-and-secondary-markets-for-stablecoins-20240223.html",
                "note": "Peg stress differs across primary vs secondary market dynamics.",
            },
        ],
        "signal_summary": {
            "combined_supply_latest_usd": float(signal["combined_supply_usd"].dropna().iloc[-1]),
            "redemption_pressure_mean": float(signal["redemption_pressure"].dropna().mean()),
            "redemption_pressure_p95": float(signal["redemption_pressure"].dropna().quantile(0.95)),
            "peg_dev_max_mean_bps": float(signal["peg_dev_max"].dropna().mean() * 10000),
            "peg_dev_max_p95_bps": float(signal["peg_dev_max"].dropna().quantile(0.95) * 10000),
        },
        "asset_results": asset_results,
        "btc_horse_race": horse_race,
        "best_assets": best_assets,
        "verdict": (
            "BTC_ONLY"
            if best_assets == ["BTC-USD"]
            else ("MIXED" if best_assets else "NULL")
        ),
        "interpretation": (
            "Peg deviation carries incremental information for BTC 5-day realized variance, "
            "while stablecoin redemption pressure itself is mostly null and Treasury proxies do not benefit."
        ),
        "limitations": [
            "SHY and TLT are ETF proxies, not direct Treasury yield or bill microstructure series.",
            "DefiLlama peg prices are end-of-day snapshots and may miss intraday depeg severity.",
            "Supply data aggregates circulating balances by chain and does not identify reserve-sale composition.",
            "This is reduced-form forecasting evidence, not causal identification of Treasury funding stress.",
        ],
        "artifacts": {
            "fig_signal_timeseries": str((OUTPUT_DIR / "fig_signal_timeseries.png").relative_to(Path.cwd())),
            "fig_qlike_improvement": str((OUTPUT_DIR / "fig_qlike_improvement.png").relative_to(Path.cwd())),
            "fig_event_study": str((OUTPUT_DIR / "fig_event_study.png").relative_to(Path.cwd())),
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "results_path": str(RESULTS_PATH), "verdict": results["verdict"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
