#!/usr/bin/env python3
"""
K1508: AI power-demand narrative and utility/grid ETF forward volatility.

This experiment was generated from stale queue task id K1345. K1345 was already
used by K1345_pre_fomc_iv_drift, so the executable experiment id is K1508.

Question:
    Did the post-ChatGPT / AI data-center power narrative reprice utilities and
    grid/infrastructure ETFs from low-vol defensive assets into higher-vol
    growth/power-infrastructure assets?

Lookahead policy:
    - All daily signals are explicitly shifted by one trading day.
    - Targets are forward realized volatility over t+1..t+21.
    - Monthly power proxy is shifted two months for conservative publication lag,
      then shifted one more trading day after daily alignment.

Data:
    - yfinance adjusted close: XLU, VPU, GRID, PAVE, SPY, QQQ.
    - FRED IPG2211S: Industrial Production: Utilities: Electric Power
      Generation, Transmission, and Distribution. This is not an EIA load series;
      EIA API v2 requires an API key and the public bulk ELEC file is ~226MB, so
      this free hourly-run experiment uses IPG2211S as a reproducible power
      activity proxy and reports that limitation.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

START = "2016-01-01"
AI_DATE = pd.Timestamp("2022-11-30")
HORIZON = 21
HAC_LAG = 21
BOOT_REPS = 5000

TARGETS = ["XLU", "VPU", "GRID", "PAVE"]
BENCHMARKS = ["SPY", "QQQ"]
TICKERS = TARGETS + BENCHMARKS

LITERATURE = [
    {
        "citation": "Lawrence Berkeley National Laboratory / DOE (2024), 2024 Report on U.S. Data Center Energy Use",
        "url": "https://www.energy.gov/articles/doe-releases-new-report-evaluating-increase-electricity-demand-data-centers",
        "role": "data-center electricity load growth tripled over the past decade and may double or triple by 2028",
    },
    {
        "citation": "IEA (2025), Energy and AI",
        "url": "https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai",
        "role": "global data-center electricity demand projected to roughly double by 2030",
    },
    {
        "citation": "Grid Strategies (2025), Power Demand Forecasts Revised Up",
        "url": "https://gridstrategiesllc.com/wp-content/uploads/Grid-Strategies-National-Load-Growth-Report-2025.pdf",
        "role": "data centers are a large driver of utility load-forecast revisions",
    },
    {
        "citation": "EIA Today in Energy (2026), Data center server energy use grows across the commercial sector",
        "url": "https://www.eia.gov/todayinenergy/detail.php?id=67704",
        "role": "EIA context for server electricity demand and commercial-sector load share",
    },
]

AI_POWER_EVENTS = [
    {"date": "2022-11-30", "label": "ChatGPT launch"},
    {"date": "2023-05-24", "label": "NVDA AI guidance shock"},
    {"date": "2024-03-18", "label": "NVIDIA GTC 2024"},
    {"date": "2024-12-20", "label": "DOE/LBNL data-center energy report"},
    {"date": "2025-01-27", "label": "DeepSeek AI power-efficiency shock"},
    {"date": "2025-05-29", "label": "EIA server-energy article"},
]


def download_close(ticker: str, refresh: bool = False) -> pd.Series:
    cache = DATA_DIR / f"{ticker}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")["Close"].sort_index()

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(cache, index=False)
    return close


def download_power_proxy(refresh: bool = False) -> pd.Series:
    cache = DATA_DIR / "IPG2211S.csv"
    if cache.exists() and not refresh:
        raw = pd.read_csv(cache, parse_dates=["observation_date"]).set_index("observation_date")["IPG2211S"]
        return raw.sort_index()

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IPG2211S"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    cache.write_bytes(response.content)
    raw = pd.read_csv(cache, parse_dates=["observation_date"]).set_index("observation_date")["IPG2211S"]
    raw = pd.to_numeric(raw, errors="coerce").dropna().sort_index()
    return raw


def forward_realized_vol(log_returns: pd.Series, horizon: int = HORIZON) -> pd.Series:
    values = log_returns.to_numpy()
    out = np.full(len(values), np.nan)
    for i in range(len(values) - horizon):
        window = values[i + 1 : i + 1 + horizon]
        if np.isfinite(window).sum() == horizon:
            out[i] = math.sqrt(np.sum(window**2) * 252.0 / horizon)
    return pd.Series(out, index=log_returns.index)


def newey_west_se(x: np.ndarray, residuals: np.ndarray, lag: int) -> np.ndarray:
    n, k = x.shape
    s = x * residuals[:, None]
    meat = s.T @ s
    for ell in range(1, lag + 1):
        weight = 1.0 - ell / (lag + 1.0)
        gamma = s[ell:].T @ s[:-ell]
        meat += weight * (gamma + gamma.T)
    xtx_inv = np.linalg.inv(x.T @ x)
    cov = xtx_inv @ meat @ xtx_inv
    return np.sqrt(np.maximum(np.diag(cov), 0.0))


def hac_regression(y: pd.Series, x: pd.DataFrame, lag: int = HAC_LAG) -> dict:
    frame = pd.concat([y.rename("y"), x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 100:
        return {"n": int(len(frame)), "error": "insufficient_data"}
    yv = frame["y"].to_numpy(dtype=float)
    xv = np.column_stack([np.ones(len(frame)), frame[x.columns].to_numpy(dtype=float)])
    beta = np.linalg.lstsq(xv, yv, rcond=None)[0]
    residuals = yv - xv @ beta
    se = newey_west_se(xv, residuals, min(lag, max(1, len(frame) // 4)))
    tvals = beta / se
    pvals = 2.0 * (1.0 - stats.norm.cdf(np.abs(tvals)))
    names = ["const"] + list(x.columns)
    return {
        "n": int(len(frame)),
        "params": {name: float(val) for name, val in zip(names, beta)},
        "se_hac": {name: float(val) for name, val in zip(names, se)},
        "t_hac": {name: float(val) for name, val in zip(names, tvals)},
        "p_norm": {name: float(val) for name, val in zip(names, pvals)},
        "r2": float(1.0 - np.sum(residuals**2) / np.sum((yv - yv.mean()) ** 2)),
    }


def bootstrap_mean_diff(post: np.ndarray, pre: np.ndarray, reps: int = BOOT_REPS) -> dict:
    rng = np.random.default_rng(SEED)
    post = post[np.isfinite(post)]
    pre = pre[np.isfinite(pre)]
    diffs = np.empty(reps)
    for i in range(reps):
        diffs[i] = rng.choice(post, len(post), replace=True).mean() - rng.choice(pre, len(pre), replace=True).mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {
        "mean_diff": float(post.mean() - pre.mean()),
        "ci95": [float(lo), float(hi)],
        "p_gt_0": float(np.mean(diffs > 0.0)),
        "n_post": int(len(post)),
        "n_pre": int(len(pre)),
    }


def build_panel(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    close = pd.DataFrame({ticker: download_close(ticker, refresh=refresh) for ticker in TICKERS}).dropna(how="all")
    log_returns = np.log(close / close.shift(1))

    fwd_vol = pd.DataFrame({ticker: forward_realized_vol(log_returns[ticker]) for ticker in TICKERS})
    vix_close = download_close("^VIX", refresh=refresh)
    vix_signal = np.log(vix_close).reindex(close.index).ffill().shift(1).rename("log_vix_lag1")

    power_proxy = download_power_proxy(refresh=refresh)
    power_yoy = power_proxy.pct_change(12)
    # Conservative release lag: monthly t is usable after two monthly steps.
    power_yoy_lagged = power_yoy.shift(2)
    power_daily = power_yoy_lagged.reindex(close.index, method="ffill")
    power_z = ((power_daily - power_daily.rolling(756, min_periods=252).mean())
               / power_daily.rolling(756, min_periods=252).std()).shift(1)
    power_z.name = "power_yoy_z_lagged"

    post_ai_signal = pd.Series((close.index >= AI_DATE).astype(float), index=close.index, name="post_ai_raw")
    post_ai_signal = post_ai_signal.shift(1).rename("post_ai_signal_shift1")

    rows = []
    for ticker in TARGETS:
        rel_log_vol = np.log(fwd_vol[ticker]) - np.log(fwd_vol["SPY"])
        target_log_vol = np.log(fwd_vol[ticker])
        frame = pd.concat(
            [
                rel_log_vol.rename("rel_log_fwd_rv21_vs_spy"),
                target_log_vol.rename("log_fwd_rv21"),
                post_ai_signal,
                vix_signal,
                power_z,
            ],
            axis=1,
        )
        frame["ticker"] = ticker
        rows.append(frame.reset_index().rename(columns={"index": "date", "Date": "date"}))
    panel = pd.concat(rows, ignore_index=True).dropna()
    meta = {
        "price_source": "yfinance adjusted close",
        "power_proxy_source": "FRED IPG2211S (Federal Reserve G.17, not EIA load)",
        "eia_status": "EIA v2 API requires api_key; public ELEC bulk zip observed as ~226MB, not downloaded in hourly run",
        "tickers": TICKERS,
        "start": START,
        "last_price_date": str(close.dropna(how="all").index.max().date()),
        "last_power_proxy_date": str(power_proxy.index.max().date()),
        "lookahead_policy": "post_ai_signal_shift1, log_vix_lag1, power_yoy_z_lagged; target is forward t+1..t+21 RV",
    }
    return panel, meta


def run_tests(panel: pd.DataFrame) -> dict:
    results = {}
    for ticker, grp in panel.groupby("ticker"):
        grp = grp.set_index("date").sort_index()
        x = grp[["post_ai_signal_shift1", "log_vix_lag1", "power_yoy_z_lagged"]]
        reg = hac_regression(grp["rel_log_fwd_rv21_vs_spy"], x)
        post_vals = grp.loc[grp["post_ai_signal_shift1"] > 0.5, "rel_log_fwd_rv21_vs_spy"].to_numpy()
        pre_vals = grp.loc[grp["post_ai_signal_shift1"] < 0.5, "rel_log_fwd_rv21_vs_spy"].to_numpy()
        boot = bootstrap_mean_diff(post_vals, pre_vals)
        results[ticker] = {"regression": reg, "post_minus_pre_bootstrap": boot}
    return results


def event_study(panel: pd.DataFrame) -> list[dict]:
    out = []
    for event in AI_POWER_EVENTS:
        date = pd.Timestamp(event["date"])
        for ticker, grp in panel.groupby("ticker"):
            g = grp.set_index("date").sort_index()
            pos = g.index.searchsorted(date)
            if pos >= len(g):
                continue
            event_date = g.index[pos]
            fwd = float(g.iloc[pos]["log_fwd_rv21"])
            pre = g.iloc[max(0, pos - 63):pos]["log_fwd_rv21"].mean()
            if np.isfinite(fwd) and np.isfinite(pre):
                out.append(
                    {
                        "event": event["label"],
                        "requested_date": event["date"],
                        "trading_date": str(pd.Timestamp(event_date).date()),
                        "ticker": ticker,
                        "log_fwd_rv21": fwd,
                        "pre63_mean_log_fwd_rv21": float(pre),
                        "event_minus_pre63": float(fwd - pre),
                    }
                )
    return out


def make_plot(panel: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    for ticker, grp in panel.groupby("ticker"):
        g = grp.set_index("date").sort_index()
        monthly = g["rel_log_fwd_rv21_vs_spy"].rolling(63, min_periods=30).mean()
        ax.plot(monthly.index, monthly.values, label=ticker, linewidth=1.4)
    ax.axvline(AI_DATE, color="black", linestyle="--", linewidth=1.0, label="AI_DATE")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title("K1508: Target ETF forward 21d vol relative to SPY")
    ax.set_ylabel("log(fwd RV21 ETF) - log(fwd RV21 SPY), 63d rolling mean")
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(refresh: bool = False) -> dict:
    panel, data_meta = build_panel(refresh=refresh)
    panel_path = HERE / "k1508_panel.csv"
    panel.to_csv(panel_path, index=False)

    test_results = run_tests(panel)
    events = event_study(panel)
    fig_path = FIG_DIR / "k1508_relative_forward_vol.png"
    make_plot(panel, fig_path)

    passes = []
    for ticker, res in test_results.items():
        reg = res["regression"]
        t_post = reg.get("t_hac", {}).get("post_ai_signal_shift1", float("nan"))
        p_post = reg.get("p_norm", {}).get("post_ai_signal_shift1", float("nan"))
        passes.append(bool(np.isfinite(t_post) and t_post > 3.0 and p_post < 0.0125))

    verdict = "PASS" if sum(passes) >= 3 else "NULL"
    if sum(passes) in (1, 2):
        verdict = "MIXED_WEAK"

    output = {
        "experiment_id": "K1508",
        "remapped_from_stale_task_id": "K1345",
        "title": "AI power-demand narrative and utility/grid ETF forward volatility",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": data_meta,
        "design": {
            "ai_date": str(AI_DATE.date()),
            "horizon_trading_days": HORIZON,
            "hac_lag": HAC_LAG,
            "target": "forward realized volatility over t+1..t+21",
            "primary_regression": "log(fwd_rv21 ETF) - log(fwd_rv21 SPY) ~ post_ai_signal_shift1 + log_vix_lag1 + power_yoy_z_lagged",
            "primary_gate": ">=3 of 4 ETFs have post_ai_signal_shift1 HAC t>3 and p<0.0125",
        },
        "literature": LITERATURE,
        "results": test_results,
        "event_study": events,
        "verdict": verdict,
        "pass_count": int(sum(passes)),
        "n_assets": len(TARGETS),
        "outputs": {
            "panel_csv": str(panel_path.relative_to(HERE)),
            "figure": str(fig_path.relative_to(HERE)),
        },
        "interpretation": (
            "Free-data test does not support a broad, statistically robust post-AI "
            "relative-volatility repricing of utility/grid ETFs unless verdict is PASS. "
            "EIA load-series access is a limitation; IPG2211S is a reproducible power-activity proxy."
        ),
    }

    results_path = HERE / "k1508_results.json"
    with results_path.open("w") as f:
        json.dump(output, f, indent=2)
    print(json.dumps({"verdict": verdict, "pass_count": int(sum(passes)), "results_path": str(results_path)}, indent=2))
    return output


if __name__ == "__main__":
    main(refresh=False)
