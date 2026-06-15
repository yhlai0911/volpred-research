#!/usr/bin/env python3
"""Downside/upside VRP proxy and cross-horizon SPY predictability test."""

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
START = "2004-01-01"
END = "2026-06-15"
ANALYSIS_START = pd.Timestamp("2010-01-04")
TICKERS = ["SPY", "^VIX"]
RV_WINDOW = 22
SHARE_WINDOW = 252
HORIZONS = [21, 63, 126]
TRADING_DAYS = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
EPS = 1e-12

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_vrp_vrp_horizon_results.json"
FIG_MEANS = HERE / "fig_vrp_component_means.png"
FIG_HORIZONS = HERE / "fig_vrp_horizon_tstats.png"


@dataclass(frozen=True)
class MeanTest:
    nobs: int
    mean: float
    mean_vol_pts2: float
    hac_t: float
    hac_p: float


@dataclass(frozen=True)
class RegressionTest:
    nobs: int
    coef_down_vrp: float | None
    t_down_vrp: float | None
    p_down_vrp: float | None
    coef_up_vrp: float | None
    t_up_vrp: float | None
    p_up_vrp: float | None
    coef_total_vrp: float | None
    t_total_vrp: float | None
    p_total_vrp: float | None
    r2: float
    hac_lags: int


def download_prices() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    close = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].copy()
    close = close.rename(columns={"SPY": "SPY", "^VIX": "VIX"})
    if "^VIX" in close.columns:
        close = close.rename(columns={"^VIX": "VIX"})
    close.index = pd.to_datetime(close.index)
    close = close[["SPY", "VIX"]].dropna()
    close.to_csv(DATA_DIR / "close.csv")
    return close


def forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    total = pd.Series(0.0, index=series.index)
    for step in range(1, horizon + 1):
        total = total + series.shift(-step)
    return total


def forward_annualized_variance(sq: pd.Series, horizon: int) -> pd.Series:
    return forward_sum(sq, horizon) * TRADING_DAYS / horizon


def zscore(series: pd.Series) -> pd.Series:
    sd = series.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return series * np.nan
    return (series - series.mean()) / sd


def build_panel(close: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(close["SPY"] / close["SPY"].shift(1))
    down_sq = ret.clip(upper=0.0) ** 2
    up_sq = ret.clip(lower=0.0) ** 2
    total_sq = ret**2

    panel = pd.DataFrame({"ret": ret, "down_sq": down_sq, "up_sq": up_sq, "total_sq": total_sq})
    panel["iv_total_lag1"] = ((close["VIX"] / 100.0) ** 2).shift(1)
    panel["rv_total_22_lag1"] = (total_sq.rolling(RV_WINDOW).sum() * TRADING_DAYS / RV_WINDOW).shift(1)
    panel["rv_down_22_lag1"] = (down_sq.rolling(RV_WINDOW).sum() * TRADING_DAYS / RV_WINDOW).shift(1)
    panel["rv_up_22_lag1"] = (up_sq.rolling(RV_WINDOW).sum() * TRADING_DAYS / RV_WINDOW).shift(1)

    down_share = down_sq.rolling(SHARE_WINDOW).sum() / total_sq.rolling(SHARE_WINDOW).sum()
    panel["down_share_252_lag1"] = down_share.shift(1)
    panel["up_share_252_lag1"] = 1.0 - panel["down_share_252_lag1"]

    # Reduced-form free-data split: VIX gives only total implied variance. The
    # down/up split uses yesterday's trailing realized semivariance share.
    panel["iv_down_proxy_lag1"] = panel["iv_total_lag1"] * panel["down_share_252_lag1"]
    panel["iv_up_proxy_lag1"] = panel["iv_total_lag1"] * panel["up_share_252_lag1"]
    panel["vrp_total_lag1"] = panel["iv_total_lag1"] - panel["rv_total_22_lag1"]
    panel["vrp_down_lag1"] = panel["iv_down_proxy_lag1"] - panel["rv_down_22_lag1"]
    panel["vrp_up_lag1"] = panel["iv_up_proxy_lag1"] - panel["rv_up_22_lag1"]
    panel["vrp_down_minus_up_lag1"] = panel["vrp_down_lag1"] - panel["vrp_up_lag1"]
    panel["log_rv_total_22_lag1"] = np.log(panel["rv_total_22_lag1"] + EPS)
    panel["ret_21_lag1"] = ret.rolling(21).sum().shift(1)

    for horizon in HORIZONS:
        panel[f"fwd_ret_{horizon}"] = forward_sum(ret, horizon)
        panel[f"fwd_rv_total_{horizon}"] = forward_annualized_variance(total_sq, horizon)
        panel[f"log_fwd_rv_total_{horizon}"] = np.log(panel[f"fwd_rv_total_{horizon}"] + EPS)

    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "panel.csv")
    return panel


def hac_mean(series: pd.Series, maxlags: int = RV_WINDOW) -> MeanTest:
    sample = series.dropna()
    x = np.ones((len(sample), 1))
    fit = sm.OLS(sample.to_numpy(dtype=float), x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    mean = float(fit.params[0])
    return MeanTest(
        nobs=int(fit.nobs),
        mean=round(mean, 8),
        mean_vol_pts2=round(mean * 10000.0, 4),
        hac_t=round(float(fit.tvalues[0]), 4),
        hac_p=round(float(fit.pvalues[0]), 6),
    )


def regression(df: pd.DataFrame, target: str, mode: str, hac_lags: int) -> RegressionTest:
    controls = {
        "target": df[target],
        "log_rv": df["log_rv_total_22_lag1"],
        "ret_21": df["ret_21_lag1"],
    }
    if mode == "split":
        controls["down_vrp"] = zscore(df["vrp_down_lag1"])
        controls["up_vrp"] = zscore(df["vrp_up_lag1"])
        xcols = ["down_vrp", "up_vrp", "log_rv", "ret_21"]
    elif mode == "total":
        controls["total_vrp"] = zscore(df["vrp_total_lag1"])
        xcols = ["total_vrp", "log_rv", "ret_21"]
    else:
        raise ValueError(f"unknown mode: {mode}")

    reg = pd.DataFrame(controls).dropna()
    x = sm.add_constant(reg[xcols])
    fit = sm.OLS(reg["target"], x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})

    def coef(name: str) -> float | None:
        if name not in fit.params.index:
            return None
        return round(float(fit.params[name]), 8)

    def tval(name: str) -> float | None:
        if name not in fit.tvalues.index:
            return None
        return round(float(fit.tvalues[name]), 4)

    def pval(name: str) -> float | None:
        if name not in fit.pvalues.index:
            return None
        return round(float(fit.pvalues[name]), 6)

    return RegressionTest(
        nobs=int(fit.nobs),
        coef_down_vrp=coef("down_vrp"),
        t_down_vrp=tval("down_vrp"),
        p_down_vrp=pval("down_vrp"),
        coef_up_vrp=coef("up_vrp"),
        t_up_vrp=tval("up_vrp"),
        p_up_vrp=pval("up_vrp"),
        coef_total_vrp=coef("total_vrp"),
        t_total_vrp=tval("total_vrp"),
        p_total_vrp=pval("total_vrp"),
        r2=round(float(fit.rsquared), 6),
        hac_lags=hac_lags,
    )


def moving_block_bootstrap_mean(series: pd.Series) -> dict:
    sample = series.dropna().to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    rows = []
    for _ in range(BOOTSTRAP_REPS):
        chosen: list[int] = []
        while len(chosen) < len(sample):
            start = int(rng.integers(0, max(1, len(sample) - BOOTSTRAP_BLOCK + 1)))
            chosen.extend(range(start, min(start + BOOTSTRAP_BLOCK, len(sample))))
        rows.append(float(sample[np.asarray(chosen[: len(sample)], dtype=int)].mean()))
    vals = np.asarray(rows, dtype=float)
    return {
        "mean_vol_pts2": round(float(vals.mean() * 10000.0), 4),
        "ci_2p5_vol_pts2": round(float(np.quantile(vals, 0.025) * 10000.0), 4),
        "ci_97p5_vol_pts2": round(float(np.quantile(vals, 0.975) * 10000.0), 4),
        "p_gt_0": round(float((vals > 0).mean()), 4),
        "reps": BOOTSTRAP_REPS,
        "block_length": BOOTSTRAP_BLOCK,
        "seed": SEED,
    }


def build_figures(mean_tests: dict[str, dict], horizon_results: dict[str, dict]) -> None:
    labels = ["total", "down", "up", "down_minus_up"]
    means = [mean_tests[label]["mean_vol_pts2"] for label in labels]
    colors = ["#4c78a8", "#e45756", "#54a24b", "#b279a2"]
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(labels, means, color=colors)
    ax.axhline(0.0, color="#333333", linewidth=1)
    ax.set_ylabel("Mean VRP proxy (vol points squared)")
    ax.set_title("Total vs Downside/Upside VRP Proxy Means")
    fig.tight_layout()
    fig.savefig(FIG_MEANS, dpi=180)
    plt.close(fig)

    horizons = [str(h) for h in HORIZONS]
    ret_down = [horizon_results[h]["return_split"]["t_down_vrp"] for h in horizons]
    ret_up = [horizon_results[h]["return_split"]["t_up_vrp"] for h in horizons]
    rv_down = [horizon_results[h]["rv_split"]["t_down_vrp"] for h in horizons]
    rv_up = [horizon_results[h]["rv_split"]["t_up_vrp"] for h in horizons]
    x = np.arange(len(horizons))
    width = 0.35
    fig2, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    axes[0].bar(x - width / 2, ret_down, width, label="downside VRP", color="#e45756")
    axes[0].bar(x + width / 2, ret_up, width, label="upside VRP", color="#54a24b")
    axes[0].set_xticks(x, horizons)
    axes[0].set_title("Forward SPY Return")
    axes[0].set_ylabel("HAC t-stat")
    axes[1].bar(x - width / 2, rv_down, width, label="downside VRP", color="#e45756")
    axes[1].bar(x + width / 2, rv_up, width, label="upside VRP", color="#54a24b")
    axes[1].set_xticks(x, horizons)
    axes[1].set_title("Forward SPY Realized Variance")
    for ax in axes:
        ax.axhline(3.0, color="#333333", linestyle="--", linewidth=1)
        ax.axhline(-3.0, color="#333333", linestyle="--", linewidth=1)
        ax.set_xlabel("Horizon (trading days)")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig2.legend(handles, legend_labels, loc="lower center", ncol=2, frameon=False)
    fig2.suptitle("Cross-Horizon Predictive t-stats")
    fig2.tight_layout(rect=[0, 0.08, 1, 0.95])
    fig2.savefig(FIG_HORIZONS, dpi=180)
    plt.close(fig2)


def main() -> None:
    np.random.seed(SEED)
    close = download_prices()
    panel = build_panel(close)
    sample = panel[panel.index >= ANALYSIS_START].copy()

    mean_tests = {
        "total": asdict(hac_mean(sample["vrp_total_lag1"])),
        "down": asdict(hac_mean(sample["vrp_down_lag1"])),
        "up": asdict(hac_mean(sample["vrp_up_lag1"])),
        "down_minus_up": asdict(hac_mean(sample["vrp_down_minus_up_lag1"])),
    }
    bootstrap = {
        "down_minus_up": moving_block_bootstrap_mean(sample["vrp_down_minus_up_lag1"]),
        "down": moving_block_bootstrap_mean(sample["vrp_down_lag1"]),
        "up": moving_block_bootstrap_mean(sample["vrp_up_lag1"]),
    }

    horizon_results: dict[str, dict] = {}
    for horizon in HORIZONS:
        h = str(horizon)
        horizon_results[h] = {
            "return_split": asdict(regression(sample, f"fwd_ret_{horizon}", "split", horizon)),
            "return_total": asdict(regression(sample, f"fwd_ret_{horizon}", "total", horizon)),
            "rv_split": asdict(regression(sample, f"log_fwd_rv_total_{horizon}", "split", horizon)),
            "rv_total": asdict(regression(sample, f"log_fwd_rv_total_{horizon}", "total", horizon)),
        }

    build_figures(mean_tests, horizon_results)

    sign_support = (
        mean_tests["down"]["hac_t"] > 3.0
        and mean_tests["down_minus_up"]["hac_t"] > 3.0
        and bootstrap["down_minus_up"]["ci_2p5_vol_pts2"] > 0.0
    )
    medium_horizons = ["63", "126"]
    return_medium_pass = any(
        horizon_results[h]["return_split"]["t_down_vrp"] is not None
        and horizon_results[h]["return_split"]["t_down_vrp"] > 3.0
        and horizon_results[h]["return_split"]["t_down_vrp"] > horizon_results["21"]["return_split"]["t_down_vrp"]
        for h in medium_horizons
    )
    rv_medium_pass = any(
        horizon_results[h]["rv_split"]["t_down_vrp"] is not None
        and horizon_results[h]["rv_split"]["t_down_vrp"] > 3.0
        and horizon_results[h]["rv_split"]["t_down_vrp"] > horizon_results["21"]["rv_split"]["t_down_vrp"]
        for h in medium_horizons
    )

    verdict = "NULL"
    if sign_support or return_medium_pass or rv_medium_pass:
        verdict = "PARTIAL"
    if sign_support and return_medium_pass and rv_medium_pass:
        verdict = "SUPPORT"

    results = {
        "experiment_id": "research_vrp_vrp_horizon",
        "title": "Downside/upside VRP proxy and cross-horizon SPY predictability",
        "date_run_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted close",
            "tickers": TICKERS,
            "start": START,
            "end": END,
            "analysis_start": str(ANALYSIS_START.date()),
            "n_analysis_rows": int(len(sample.dropna(subset=["vrp_down_lag1", "vrp_up_lag1"]))),
            "cached_data_dir": "experiments/research_vrp_vrp_horizon/data/",
        },
        "method": {
            "total_implied_variance_proxy": "(VIX / 100)^2, shifted by one trading day before prediction",
            "down_up_split": (
                "VIX gives only total implied variance; downside/upside IV proxies allocate total IV with "
                "trailing 252-day realized semivariance shares shifted by one day"
            ),
            "realized_vrp_leg": "trailing 22-trading-day annualized realized semivariance, shifted by one day",
            "targets": {
                "return": "forward cumulative SPY log return over 21/63/126 trading days",
                "rv": "log forward annualized realized variance over 21/63/126 trading days",
            },
            "regression_controls": ["lagged log 22d realized variance", "lagged 21d SPY return"],
            "standard_errors": "Newey-West HAC maxlags equal to the overlapping target horizon",
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block_length": BOOTSTRAP_BLOCK, "seed": SEED},
            "success_rule": (
                "SUPPORT requires a positive downside VRP mean/spread gate and positive downside-VRP predictive "
                "t-stats > 3 at medium horizons for both returns and RV; PARTIAL requires at least one leg"
            ),
        },
        "mean_tests": mean_tests,
        "bootstrap_mean_tests": bootstrap,
        "horizon_results": horizon_results,
        "figures": [FIG_MEANS.name, FIG_HORIZONS.name],
        "literature": [
            {
                "citation": "Bollerslev, Tauchen, and Zhou (2009), Expected Stock Returns and Variance Risk Premia",
                "url": "https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787",
            },
            {
                "citation": "Bekaert and Hoerova (2014), The VIX, the Variance Premium and Stock Market Volatility",
                "url": "https://ideas.repec.org/p/nbr/nberwo/18995.html",
            },
            {
                "citation": "Downside Variance Risk Premium, Federal Reserve FEDS working paper",
                "url": "https://www.federalreserve.gov/econresdata/feds/2015/files/2015020pap.pdf",
            },
            {
                "citation": "Variance and Skewness Risk Premium and Expected Equity Returns",
                "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6712647",
            },
        ],
        "research_honesty_notes": [
            "This is not a true option-implied downside/upside variance decomposition.",
            "All predictors use explicit one-trading-day lags before forward targets.",
            "VIX is a roughly 30-calendar-day implied variance proxy, so long-horizon tests are reduced-form.",
            "The free-data proxy can reject or motivate follow-up work but cannot prove option-market component premia.",
        ],
        "verdict": {
            "overall": verdict,
            "sign_support": sign_support,
            "return_medium_pass": return_medium_pass,
            "rv_medium_pass": rv_medium_pass,
            "plain_english": (
                "The free-data downside/upside VRP proxy supports the sign and medium-horizon prediction story."
                if verdict == "SUPPORT"
                else "At least one leg of the downside/upside VRP hypothesis passes, but the full gate fails."
                if verdict == "PARTIAL"
                else "The free-data downside/upside VRP proxy does not pass the pre-specified sign plus medium-horizon prediction gate."
            ),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(json.dumps({"mean_tests": mean_tests, "horizon_results": horizon_results}, indent=2))


if __name__ == "__main__":
    main()
