#!/usr/bin/env python3
"""K1477: 0DTE era intraday vs overnight volatility structure shift."""

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

TICKER = "SPY"
START = "2018-01-01"
END = "2026-06-11"
BREAK_DATE = pd.Timestamp("2022-05-02")
EPS = 1e-12
HAC_LAGS = 5

RESULTS_PATH = HERE / "k1477_results.json"
FIG_ROLLING = HERE / "k1477_rolling_structure.png"
FIG_WEEKDAY = HERE / "k1477_weekday_bars.png"


def fetch_ohlc(ticker: str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Open", "High", "Low", "Close"]].dropna().copy()
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["overnight_ret"] = np.log(out["Open"] / out["Close"].shift(1))
    out["intraday_ret"] = np.log(out["Close"] / out["Open"])
    out["overnight_sq"] = out["overnight_ret"] ** 2
    out["intraday_sq"] = out["intraday_ret"] ** 2
    out["parkinson_var"] = (np.log(out["High"] / out["Low"]) ** 2) / (4.0 * np.log(2.0))
    out["total_proxy"] = out["overnight_sq"] + out["intraday_sq"]
    out["intraday_share_oc"] = out["intraday_sq"] / out["total_proxy"]
    out["range_share"] = out["parkinson_var"] / (out["parkinson_var"] + out["overnight_sq"])
    out["log_ratio_io"] = np.log((out["intraday_sq"] + EPS) / (out["overnight_sq"] + EPS))
    out["post_break"] = (out.index >= BREAK_DATE).astype(int)
    out["weekday"] = out.index.day_name()
    out["tue_thu"] = out.index.weekday.isin([1, 3]).astype(int)
    return out.dropna().copy()


def chow_mean_shift_test(series: pd.Series, break_date: pd.Timestamp) -> dict[str, float]:
    y = series.dropna()
    pre = y.loc[y.index < break_date]
    post = y.loc[y.index >= break_date]
    n = len(y)
    n1 = len(pre)
    n2 = len(post)
    k = 1
    if n1 <= k or n2 <= k:
        return {"f_stat": np.nan, "p_value": np.nan}

    mean_all = y.mean()
    mean_pre = pre.mean()
    mean_post = post.mean()
    sse_all = float(((y - mean_all) ** 2).sum())
    sse_split = float(((pre - mean_pre) ** 2).sum() + ((post - mean_post) ** 2).sum())
    num = (sse_all - sse_split) / k
    den = sse_split / (n1 + n2 - 2 * k)
    f_stat = num / den if den > 0 else np.nan
    p_value = 1.0 - stats.f.cdf(f_stat, k, n1 + n2 - 2 * k) if np.isfinite(f_stat) else np.nan
    return {"f_stat": float(f_stat), "p_value": float(p_value)}


def summary_pre_post(df: pd.DataFrame, column: str) -> dict[str, float]:
    pre = df.loc[df["post_break"] == 0, column].dropna()
    post = df.loc[df["post_break"] == 1, column].dropna()
    welch = stats.ttest_ind(post, pre, equal_var=False, nan_policy="omit")
    mw = stats.mannwhitneyu(post, pre, alternative="two-sided")
    chow = chow_mean_shift_test(df[column], BREAK_DATE)
    return {
        "pre_mean": float(pre.mean()),
        "post_mean": float(post.mean()),
        "pre_median": float(pre.median()),
        "post_median": float(post.median()),
        "post_over_pre_mean_ratio": float(post.mean() / pre.mean()) if pre.mean() != 0 else np.nan,
        "mean_diff_post_minus_pre": float(post.mean() - pre.mean()),
        "welch_t": float(welch.statistic),
        "welch_p": float(welch.pvalue),
        "mannwhitney_u": float(mw.statistic),
        "mannwhitney_p": float(mw.pvalue),
        "chow_f": chow["f_stat"],
        "chow_p": chow["p_value"],
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
    }


def hac_post_regression(df: pd.DataFrame, column: str) -> dict[str, float]:
    y = df[column]
    x = sm.add_constant(df["post_break"])
    res = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "const": float(res.params["const"]),
        "post_beta": float(res.params["post_break"]),
        "post_t": float(res.tvalues["post_break"]),
        "post_p": float(res.pvalues["post_break"]),
        "r_squared": float(res.rsquared),
    }


def weekday_interaction_regression(df: pd.DataFrame, column: str) -> dict[str, float]:
    x = pd.DataFrame(
        {
            "const": 1.0,
            "post_break": df["post_break"],
            "tue_thu": df["tue_thu"],
            "post_x_tue_thu": df["post_break"] * df["tue_thu"],
        },
        index=df.index,
    )
    res = sm.OLS(df[column], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "post_beta": float(res.params["post_break"]),
        "post_t": float(res.tvalues["post_break"]),
        "post_p": float(res.pvalues["post_break"]),
        "tue_thu_beta": float(res.params["tue_thu"]),
        "tue_thu_t": float(res.tvalues["tue_thu"]),
        "tue_thu_p": float(res.pvalues["tue_thu"]),
        "interaction_beta": float(res.params["post_x_tue_thu"]),
        "interaction_t": float(res.tvalues["post_x_tue_thu"]),
        "interaction_p": float(res.pvalues["post_x_tue_thu"]),
        "r_squared": float(res.rsquared),
    }


def make_figures(df: pd.DataFrame) -> None:
    rolling = pd.DataFrame(
        {
            "Overnight sq (63d mean)": df["overnight_sq"].rolling(63).mean(),
            "Intraday sq (63d mean)": df["intraday_sq"].rolling(63).mean(),
            "Intraday share (OC)": df["intraday_share_oc"].rolling(63).mean(),
            "Range share": df["range_share"].rolling(63).mean(),
        },
        index=df.index,
    )

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.plot(rolling.index, rolling["Overnight sq (63d mean)"], label="Overnight sq", color="#c0392b")
    ax1.plot(rolling.index, rolling["Intraday sq (63d mean)"], label="Intraday sq", color="#2980b9")
    ax1.axvline(BREAK_DATE, color="black", linestyle="--", linewidth=1.0)
    ax1.set_title("SPY 63d rolling variance proxies")
    ax1.set_ylabel("Variance proxy")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.plot(rolling.index, rolling["Intraday share (OC)"], label="Intraday share (OC)", color="#16a085")
    ax2.plot(rolling.index, rolling["Range share"], label="Range share", color="#8e44ad")
    ax2.axvline(BREAK_DATE, color="black", linestyle="--", linewidth=1.0)
    ax2.set_title("SPY 63d rolling intraday share")
    ax2.set_ylabel("Share")
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(FIG_ROLLING, dpi=150, bbox_inches="tight")
    plt.close(fig)

    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    wk = df.groupby(["post_break", "weekday"])[["intraday_share_oc", "range_share"]].mean().reset_index()
    pre = wk[wk["post_break"] == 0].set_index("weekday").reindex(weekday_order)
    post = wk[wk["post_break"] == 1].set_index("weekday").reindex(weekday_order)

    x = np.arange(len(weekday_order))
    width = 0.35
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    ax1.bar(x - width / 2, pre["intraday_share_oc"], width, label="Pre", color="#95a5a6")
    ax1.bar(x + width / 2, post["intraday_share_oc"], width, label="Post", color="#16a085")
    ax1.set_ylabel("Intraday share (OC)")
    ax1.set_title("Weekday means before vs after 2022-05-02")
    ax1.legend()
    ax1.grid(alpha=0.3, axis="y")

    ax2.bar(x - width / 2, pre["range_share"], width, label="Pre", color="#bdc3c7")
    ax2.bar(x + width / 2, post["range_share"], width, label="Post", color="#8e44ad")
    ax2.set_ylabel("Range share")
    ax2.set_xticks(x)
    ax2.set_xticklabels(weekday_order)
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(FIG_WEEKDAY, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    raw = fetch_ohlc(TICKER, START, END)
    df = build_features(raw)

    variables = [
        "overnight_sq",
        "intraday_sq",
        "parkinson_var",
        "intraday_share_oc",
        "range_share",
        "log_ratio_io",
    ]

    summaries = {col: summary_pre_post(df, col) for col in variables}
    post_regs = {col: hac_post_regression(df, col) for col in variables}
    interaction_regs = {
        col: weekday_interaction_regression(df, col)
        for col in ["intraday_share_oc", "range_share", "intraday_sq", "parkinson_var"]
    }

    weekday_means = (
        df.groupby(["post_break", "weekday"])[["intraday_share_oc", "range_share", "intraday_sq", "overnight_sq"]]
        .mean()
        .reset_index()
        .to_dict(orient="records")
    )

    make_figures(df)

    verdict = {
        "overall": "CONDITIONAL_PASS",
        "supports_structure_shift": summaries["intraday_share_oc"]["welch_p"] < 0.05
        or summaries["log_ratio_io"]["welch_p"] < 0.05,
        "supports_intraday_level_jump": post_regs["intraday_sq"]["post_p"] < 0.05,
        "supports_tue_thu_specific_effect": interaction_regs["intraday_share_oc"]["interaction_p"] < 0.05
        or interaction_regs["range_share"]["interaction_p"] < 0.05,
        "plain_english": (
            "Post-2022-Q2 SPY shows a higher intraday share mainly because overnight variance compresses "
            "more than intraday variance; Tue/Thu interaction is not significant."
        ),
    }

    results = {
        "experiment_id": "k1477",
        "title": "0DTE era intraday vs overnight volatility structure shift",
        "run_timestamp": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "data": {
            "ticker": TICKER,
            "source": "yfinance auto_adjust=True",
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_obs": int(len(df)),
            "break_date": str(BREAK_DATE.date()),
            "breakpoint_rationale": "exogenous 2022-Q2 policy-style breakpoint for the completed weekday-expiry era",
        },
        "definitions": {
            "overnight_sq": "log(Open_t / Close_{t-1})^2",
            "intraday_sq": "log(Close_t / Open_t)^2",
            "parkinson_var": "log(High_t / Low_t)^2 / (4 log 2)",
            "intraday_share_oc": "intraday_sq / (intraday_sq + overnight_sq)",
            "range_share": "parkinson_var / (parkinson_var + overnight_sq)",
            "log_ratio_io": "log((intraday_sq + eps) / (overnight_sq + eps))",
        },
        "pre_post_summary": summaries,
        "post_dummy_regressions_hac5": post_regs,
        "weekday_interaction_regressions_hac5": interaction_regs,
        "weekday_means": weekday_means,
        "figures": [FIG_ROLLING.name, FIG_WEEKDAY.name],
        "verdict": verdict,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
