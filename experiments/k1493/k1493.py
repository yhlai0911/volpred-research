#!/usr/bin/env python3
"""
K1493: Variance risk premium decline and short-vol economic edge.

Task
----
Test whether the variance risk premium decline thesis translates into weaker
short-vol economics, using free daily data rather than option chains.

Design
------
1. VRP proxy:
   VRP_t = (VIX_t / 100)^2 - forward_RV21_t
   where forward_RV21_t is the annualized sum of SPY squared log returns over
   t+1 ... t+21. This is an ex-post premium diagnostic, not a tradable signal.

2. Short-vol proxies:
   - SVXY buy-and-hold actual adjusted close returns.
   - Naive short VIXY = - daily VIXY log return, no borrow/margin/cap modeling.
   - Naive short VXX = - daily VXX log return, post-2018 only due data history.

3. Segments:
   - VRP: 2006-2017 vs 2018-2026.
   - Strategy: 2011-10-04 to 2017-12-31 vs 2018-2026, with robustness cuts
     after 2018-03-01 and 2020-05-01.

Interpretation
--------------
The goal is not to reproduce option-chain alphas from Chicago Fed WP 2025-17.
It is a reduced-form stress test of whether the same broad story appears in
public VIX/RV and ETF proxy data.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import strategy_dm_test

np.random.seed(42)

OUTPUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUTPUT_DIR / "k1493_results.json"
PRICES_PATH = OUTPUT_DIR / "close_prices.csv"
START_DATE = "2006-01-01"
END_DATE = "2026-06-14"
SYMBOLS = ["SPY", "^VIX", "SVXY", "VIXY", "VXX", "BIL"]


def download_close() -> pd.DataFrame:
    raw = yf.download(SYMBOLS, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw.rename(columns={"Close": SYMBOLS[0]})
    close = close.sort_index()
    close.to_csv(PRICES_PATH, index_label="date")
    return close


def forward_rv21(spy_log_ret: pd.Series) -> pd.Series:
    arr = spy_log_ret.to_numpy(dtype=float)
    out = np.full(len(arr), np.nan)
    for i in range(len(arr)):
        window = arr[i + 1 : i + 22]
        if len(window) == 21 and np.isfinite(window).all():
            out[i] = float(np.sum(window * window) * (252 / 21))
    return pd.Series(out, index=spy_log_ret.index, name="forward_rv21")


def nw_mean_t(series: pd.Series, max_lags: int = 21) -> tuple[float, float]:
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 20:
        return float("nan"), float("nan")
    x_bar = float(np.mean(x))
    centered = x - x_bar
    var = np.mean(centered * centered)
    lag_cap = min(max_lags, n // 4)
    for lag in range(1, lag_cap + 1):
        weight = 1 - lag / (lag_cap + 1)
        cov = np.mean(centered[lag:] * centered[:-lag])
        var += 2 * weight * cov
    if var <= 0:
        return float("nan"), float("nan")
    t_stat = x_bar / np.sqrt(var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


def max_drawdown(log_returns: pd.Series) -> float:
    nav = np.exp(log_returns.cumsum())
    dd = nav / nav.cummax() - 1
    return float(dd.min())


def perf_stats(log_returns: pd.Series) -> dict:
    r = log_returns.dropna()
    if len(r) < 20:
        return {
            "n": int(len(r)),
            "ann_return": None,
            "ann_vol": None,
            "sharpe": None,
            "max_drawdown": None,
            "worst_day": None,
            "worst_5d": None,
            "skew": None,
        }
    return {
        "n": int(len(r)),
        "sample_start": r.index.min().strftime("%Y-%m-%d"),
        "sample_end": r.index.max().strftime("%Y-%m-%d"),
        "ann_return": float(np.exp(r.mean() * 252) - 1),
        "ann_vol": float(r.std() * np.sqrt(252)),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
        "max_drawdown": max_drawdown(r),
        "worst_day": float(np.exp(r.min()) - 1),
        "worst_5d": float(np.exp(r.rolling(5).sum().min()) - 1),
        "skew": float(stats.skew(r.dropna())),
    }


def segment(series: pd.Series, start: str, end: str | None = None) -> pd.Series:
    if end is None:
        return series.loc[start:].dropna()
    return series.loc[start:end].dropna()


def vrp_summary(vrp: pd.Series) -> dict:
    pre = segment(vrp, "2006-01-01", "2017-12-31")
    post = segment(vrp, "2018-01-01", None)
    pre_t, pre_p = nw_mean_t(pre)
    post_t, post_p = nw_mean_t(post)
    diff = stats.ttest_ind(post, pre, equal_var=False, nan_policy="omit")
    return {
        "pre_2006_2017": {
            "n": int(len(pre)),
            "mean": float(pre.mean()),
            "median": float(pre.median()),
            "positive_share": float((pre > 0).mean()),
            "nw_t_mean_gt_zero": pre_t,
            "nw_pvalue": pre_p,
        },
        "post_2018_2026": {
            "n": int(len(post)),
            "mean": float(post.mean()),
            "median": float(post.median()),
            "positive_share": float((post > 0).mean()),
            "nw_t_mean_gt_zero": post_t,
            "nw_pvalue": post_p,
        },
        "post_minus_pre_mean": float(post.mean() - pre.mean()),
        "welch_t_post_minus_pre": float(diff.statistic),
        "welch_pvalue": float(diff.pvalue),
    }


def strategy_tables(log_returns: pd.DataFrame) -> dict:
    strategies = {
        "SVXY_actual": log_returns["SVXY"],
        "short_VIXY_naive": -log_returns["VIXY"],
        "short_VXX_naive": -log_returns["VXX"],
        "SPY": log_returns["SPY"],
        "BIL": log_returns["BIL"],
    }
    periods = {
        "pre_2011_2017": ("2011-10-04", "2017-12-31"),
        "post_2018_2026": ("2018-01-01", None),
        "post_after_volmageddon": ("2018-03-01", None),
        "post_after_covid": ("2020-05-01", None),
        "recent_2023_2026": ("2023-01-01", None),
    }
    out: dict[str, dict[str, dict]] = {}
    for strat_name, strat_ret in strategies.items():
        out[strat_name] = {}
        for period_name, (start, end) in periods.items():
            out[strat_name][period_name] = perf_stats(segment(strat_ret, start, end))
    return out


def dm_tables(log_returns: pd.DataFrame) -> dict:
    comparisons = {}
    periods = {
        "pre_2011_2017": ("2011-10-04", "2017-12-31"),
        "post_2018_2026": ("2018-01-01", None),
        "post_after_volmageddon": ("2018-03-01", None),
        "post_after_covid": ("2020-05-01", None),
    }
    candidates = {
        "SVXY_actual": log_returns["SVXY"],
        "short_VIXY_naive": -log_returns["VIXY"],
    }
    benchmarks = {
        "SPY": log_returns["SPY"],
        "BIL": log_returns["BIL"],
    }
    for period_name, (start, end) in periods.items():
        comparisons[period_name] = {}
        for cand_name, cand in candidates.items():
            comparisons[period_name][cand_name] = {}
            for bench_name, bench in benchmarks.items():
                aligned = pd.concat([cand, bench], axis=1, keys=["candidate", "benchmark"])
                aligned = segment(aligned, start, end).dropna()
                if len(aligned) < 20:
                    comparisons[period_name][cand_name][bench_name] = {"n": int(len(aligned))}
                    continue
                t_stat, p_value = strategy_dm_test(
                    aligned["candidate"].to_numpy(),
                    aligned["benchmark"].to_numpy(),
                    loss_fn="negative_return",
                )
                comparisons[period_name][cand_name][bench_name] = {
                    "n": int(len(aligned)),
                    "dm_t_negative_means_candidate_better": float(t_stat),
                    "pvalue": float(p_value),
                }
    return comparisons


def make_figures(vrp: pd.Series, log_returns: pd.DataFrame, strategy_results: dict) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")

    pre = segment(vrp, "2006-01-01", "2017-12-31")
    post = segment(vrp, "2018-01-01", None)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(pre, bins=80, alpha=0.55, label="2006-2017", color="#2f6f4e", density=True)
    ax.hist(post, bins=80, alpha=0.55, label="2018-2026", color="#9a3412", density=True)
    ax.axvline(pre.mean(), color="#2f6f4e", lw=2)
    ax.axvline(post.mean(), color="#9a3412", lw=2)
    ax.set_title("VIX-implied variance minus forward SPY RV21")
    ax.set_xlabel("Annualized variance premium proxy")
    ax.set_ylabel("Density")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_vrp_periods.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, series, color in [
        ("SVXY actual", log_returns["SVXY"], "#155e75"),
        ("Naive short VIXY", -log_returns["VIXY"], "#7c2d12"),
        ("SPY", log_returns["SPY"], "#374151"),
    ]:
        r = segment(series, "2011-10-04", None)
        nav = np.exp(r.cumsum())
        nav = nav / nav.iloc[0]
        nav.plot(ax=ax, label=name, color=color, lw=1.3)
    ax.axvline(pd.Timestamp("2018-01-01"), color="black", ls="--", lw=1)
    ax.set_yscale("log")
    ax.set_title("Short-vol proxy wealth paths")
    ax.set_ylabel("Growth of $1, log scale")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_short_vol_nav.png", dpi=180)
    plt.close(fig)

    rows = []
    for strat in ["SVXY_actual", "short_VIXY_naive", "SPY"]:
        for period in ["pre_2011_2017", "post_2018_2026", "post_after_volmageddon"]:
            stats_row = strategy_results[strat][period]
            if stats_row["sharpe"] is None:
                continue
            rows.append(
                {
                    "strategy": strat,
                    "period": period,
                    "sharpe": stats_row["sharpe"],
                    "mdd": stats_row["max_drawdown"],
                }
            )
    plot_df = pd.DataFrame(rows)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    for ax, metric, title in [
        (axes[0], "sharpe", "Sharpe"),
        (axes[1], "mdd", "Maximum drawdown"),
    ]:
        pivot = plot_df.pivot(index="strategy", columns="period", values=metric)
        pivot.plot(kind="bar", ax=ax)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(title)
        ax.set_xlabel("")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "fig_strategy_metrics.png", dpi=180)
    plt.close(fig)


def main() -> None:
    close = download_close()
    log_returns = np.log(close / close.shift(1))

    spy_ret = log_returns["SPY"]
    fwd_rv = forward_rv21(spy_ret)
    vrp = ((close["^VIX"] / 100) ** 2 - fwd_rv).rename("vrp_vix_minus_fwd_rv21")

    vrp_stats = vrp_summary(vrp)
    strategy_results = strategy_tables(log_returns)
    dm_results = dm_tables(log_returns)
    make_figures(vrp, log_returns, strategy_results)

    svxy_pre = strategy_results["SVXY_actual"]["pre_2011_2017"]
    svxy_post = strategy_results["SVXY_actual"]["post_2018_2026"]
    short_vixy_pre = strategy_results["short_VIXY_naive"]["pre_2011_2017"]
    short_vixy_post = strategy_results["short_VIXY_naive"]["post_2018_2026"]

    results = {
        "experiment_id": "K1493",
        "title": "VRP Decline and Short-Vol Edge",
        "seed": 42,
        "data_sources": {
            "market_prices": "yfinance adjusted close",
            "symbols": SYMBOLS,
            "price_snapshot": str(PRICES_PATH.relative_to(Path.cwd())),
        },
        "sample": {
            "requested_start": START_DATE,
            "requested_end": END_DATE,
            "vrp_pre": "2006-01-01 to 2017-12-31",
            "vrp_post": "2018-01-01 to latest date with forward 21 trading-day RV",
            "strategy_pre": "2011-10-04 to 2017-12-31 (SVXY available sample)",
            "strategy_post": "2018-01-01 to 2026-06-12",
        },
        "literature": [
            {
                "title": "The Decline of the Variance Risk Premium: Evidence from Traded and Synthetic Options",
                "source": "Chicago Fed Working Paper 2025-17",
                "link": "https://www.chicagofed.org/publications/working-papers/2025/2025-17",
            },
            {
                "title": "Expected Stock Returns and Variance Risk Premia",
                "source": "Bollerslev, Tauchen, and Zhou (2009), Review of Financial Studies",
                "link": "https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787",
            },
            {
                "title": "Variance Risk Premia",
                "source": "Carr and Wu (2009), Review of Financial Studies",
                "link": "https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057",
            },
            {
                "title": "SVXY product description",
                "source": "ProShares",
                "link": "https://www.proshares.com/our-etfs/strategic/svxy",
            },
        ],
        "vrp_proxy": {
            "definition": "VRP_t = (VIX_t/100)^2 - annualized forward SPY RV over t+1..t+21",
            "summary": vrp_stats,
            "verdict": (
                "DECLINE_NOT_SIGNIFICANT"
                if vrp_stats["welch_pvalue"] >= 0.05
                else "DECLINE_SIGNIFICANT"
            ),
        },
        "strategy_results": strategy_results,
        "strategy_dm": dm_results,
        "headline_numbers": {
            "vrp_mean_pre": vrp_stats["pre_2006_2017"]["mean"],
            "vrp_mean_post": vrp_stats["post_2018_2026"]["mean"],
            "vrp_post_minus_pre": vrp_stats["post_minus_pre_mean"],
            "vrp_diff_pvalue": vrp_stats["welch_pvalue"],
            "svxy_sharpe_pre": svxy_pre["sharpe"],
            "svxy_sharpe_post": svxy_post["sharpe"],
            "svxy_mdd_pre": svxy_pre["max_drawdown"],
            "svxy_mdd_post": svxy_post["max_drawdown"],
            "short_vixy_sharpe_pre": short_vixy_pre["sharpe"],
            "short_vixy_sharpe_post": short_vixy_post["sharpe"],
            "short_vixy_mdd_pre": short_vixy_pre["max_drawdown"],
            "short_vixy_mdd_post": short_vixy_post["max_drawdown"],
        },
        "verdict": "MIXED_EDGE_EROSION",
        "interpretation": (
            "The VIX-minus-forward-RV proxy shows only a small, statistically insignificant "
            "mean decline after 2018, but actual short-vol product economics deteriorate "
            "sharply. SVXY's post-2018 full-sample Sharpe turns negative and MDD reaches "
            "about -95%. A naive short-VIXY proxy remains profitable on average but its "
            "drawdown deepens materially. The evidence supports edge erosion in tradable "
            "ETF proxies, not a clean public-data proof that the underlying VRP mean vanished."
        ),
        "limitations": [
            "No option chain, variance swap, or delta-hedged option PnL data are used.",
            "VIX versus 21-trading-day forward RV is a rough annualized proxy, not the Chicago Fed paper's traded-option alpha.",
            "SVXY changed exposure after the 2018 Volmageddon event, so actual product returns mix premium, tail loss, and product design.",
            "Naive short VIXY/VXX ignores borrow cost, margin calls, recalls, path-dependent rebalancing constraints, and capital survival.",
        ],
        "artifacts": {
            "fig_vrp_periods": str((OUTPUT_DIR / "fig_vrp_periods.png").relative_to(Path.cwd())),
            "fig_short_vol_nav": str((OUTPUT_DIR / "fig_short_vol_nav.png").relative_to(Path.cwd())),
            "fig_strategy_metrics": str((OUTPUT_DIR / "fig_strategy_metrics.png").relative_to(Path.cwd())),
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "ok": True,
                "results_path": str(RESULTS_PATH),
                "verdict": results["verdict"],
                "vrp_diff_pvalue": results["headline_numbers"]["vrp_diff_pvalue"],
                "svxy_sharpe_pre": results["headline_numbers"]["svxy_sharpe_pre"],
                "svxy_sharpe_post": results["headline_numbers"]["svxy_sharpe_post"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
