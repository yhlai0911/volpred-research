#!/usr/bin/env python3
"""T+1 settlement-cycle change and ETF/ADR overnight gap volatility.

This is a daily public-data structural-break diagnostic around the U.S. move
from T+2 to T+1 settlement, effective 2024-05-28. It uses yfinance daily OHLCV
and tests whether post-change overnight gap variance, realized variance, or
month/quarter-end rebalance-day volatility changed for liquid ETFs and ADRs.

The design is descriptive, not a trading signal. No same-day signal is used for
returns, and all random bootstrap draws use seed=42.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from collections import OrderedDict
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

warnings.filterwarnings("ignore", category=FutureWarning)


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = HERE / "figures"
for directory in (DATA_DIR, RAW_DIR, FIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "research_t_1_2024_05_28_etf_gap_realized_vol"
SEED = 42
np.random.seed(SEED)

START = "2022-01-01"
END = "2026-06-24"
EVENT_DATE = pd.Timestamp("2024-05-28")
HAC_LAGS = 5
HARVEY_T = 3.0
EPS = 1e-12

UNIVERSE: "OrderedDict[str, dict[str, str]]" = OrderedDict(
    [
        ("SPY", {"group": "us_etf", "label": "S&P 500 ETF"}),
        ("QQQ", {"group": "us_etf", "label": "Nasdaq-100 ETF"}),
        ("IWM", {"group": "us_etf", "label": "Russell 2000 ETF"}),
        ("VTI", {"group": "us_etf", "label": "Total-market ETF"}),
        ("EFA", {"group": "intl_etf", "label": "Developed ex-US ETF"}),
        ("EEM", {"group": "intl_etf", "label": "Emerging-market ETF"}),
        ("HYG", {"group": "credit_etf", "label": "High-yield credit ETF"}),
        ("LQD", {"group": "credit_etf", "label": "Investment-grade credit ETF"}),
        ("TLT", {"group": "bond_etf", "label": "Long Treasury ETF"}),
        ("BABA", {"group": "adr", "label": "Alibaba ADR"}),
        ("TSM", {"group": "adr", "label": "TSMC ADR"}),
        ("ASML", {"group": "adr", "label": "ASML ADR"}),
        ("NVO", {"group": "adr", "label": "Novo Nordisk ADR"}),
        ("SAP", {"group": "adr", "label": "SAP ADR"}),
        ("TM", {"group": "adr", "label": "Toyota ADR"}),
    ]
)

LITERATURE = [
    {
        "citation": "SEC (2023/2024), Shortening the Securities Transaction Settlement Cycle; T+1 effective May 28, 2024",
        "url": "https://www.sec.gov/investment/settlement-cycle-small-entity-compliance-guide-15c6-1-15c6-2-204-2",
        "role": "official source for the U.S. T+1 settlement-cycle date and scope",
    },
    {
        "citation": "SEC Chair statement (2024-05-21), Upcoming implementation of T+1 settlement cycle",
        "url": "https://www.sec.gov/newsroom/press-releases/2024-62",
        "role": "confirms May 28, 2024 conversion date",
    },
    {
        "citation": "DTCC (2023), Comments on SEC T+1 implementation date",
        "url": "https://www.dtcc.com/news/2023/february/15/dtcc-comments-on-sec-announcement-regarding-the-t1-implementation-date-of-may-2024",
        "role": "market-infrastructure rationale: reduced risk, margin, and liquidity needs",
    },
    {
        "citation": "SIFMA/CCMA/ISDA (2024), T+1 Securities Settlement Industry Implementation Playbook",
        "url": "https://www.sifma.org/research/white-papers/t1-playbook",
        "role": "implementation concerns around trade processing and cross-market timing",
    },
    {
        "citation": "LSEG/FTSE Russell (2024), The market and index impact of shorter equity settlement cycles",
        "url": "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/research/market-index-impact-of-shorter-equity-settlement-cycles.pdf",
        "role": "index and settlement-cycle frictions motivating ETF/ADR market-quality diagnostics",
    },
]


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else value
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _clean_float(value: Any) -> float | None:
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    return fval if math.isfinite(fval) else None


def fetch_ohlcv(refresh: bool = False) -> dict[str, pd.DataFrame]:
    tickers = list(UNIVERSE)
    cached = {
        ticker: RAW_DIR / f"{ticker}_{START}_{END}_ohlcv.csv"
        for ticker in tickers
    }
    if not refresh and all(path.exists() for path in cached.values()):
        return {
            ticker: pd.read_csv(path, parse_dates=["Date"], index_col="Date").sort_index()
            for ticker, path in cached.items()
        }

    print(f"[fetch] yfinance {len(tickers)} tickers {START} -> {END}", flush=True)
    downloaded = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    out = {}
    for ticker, path in cached.items():
        if isinstance(downloaded.columns, pd.MultiIndex):
            frame = downloaded[ticker].copy()
        else:
            frame = downloaded.copy()
        frame = frame[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in frame.columns]]
        if set(frame.columns) != {"Open", "High", "Low", "Close", "Volume"}:
            raise RuntimeError(f"Missing OHLCV for {ticker}")
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        frame = frame.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()
        frame.to_csv(path, index_label="Date")
        out[ticker] = frame
    return out


def add_calendar_flags(index: pd.DatetimeIndex) -> pd.DataFrame:
    dates = pd.DatetimeIndex(index)
    cal = pd.DataFrame(index=dates)
    month_end_dates = pd.Series(dates, index=dates).groupby([dates.year, dates.month]).max()
    quarter_end_dates = pd.Series(dates, index=dates).groupby([dates.year, dates.quarter]).max()
    cal["month_end"] = dates.isin(pd.DatetimeIndex(month_end_dates.values)).astype(int)
    cal["quarter_end"] = dates.isin(pd.DatetimeIndex(quarter_end_dates.values)).astype(int)
    cal["event_week"] = ((dates >= EVENT_DATE - pd.offsets.BDay(3)) & (dates <= EVENT_DATE + pd.offsets.BDay(3))).astype(int)
    return cal


def build_panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ticker, frame in frames.items():
        close = frame["Close"].astype(float)
        open_ = frame["Open"].astype(float)
        high = frame["High"].astype(float)
        low = frame["Low"].astype(float)
        prev_close = close.shift(1)
        gap = np.log(open_ / prev_close)
        intraday = np.log(close / open_)
        cc = np.log(close / prev_close)
        range_var = np.log(high / low).pow(2) / (4.0 * np.log(2.0))
        ticker_panel = pd.DataFrame(
            {
                "Date": frame.index,
                "ticker": ticker,
                "group": UNIVERSE[ticker]["group"],
                "label": UNIVERSE[ticker]["label"],
                "gap": gap,
                "intraday_ret": intraday,
                "cc_ret": cc,
                "gap_var": gap.pow(2).clip(lower=EPS),
                "intraday_var": intraday.pow(2).clip(lower=EPS),
                "cc_var": cc.pow(2).clip(lower=EPS),
                "range_var": range_var.clip(lower=EPS),
                "dollar_volume": close * frame["Volume"].astype(float),
            }
        ).dropna()
        cal = add_calendar_flags(ticker_panel["Date"])
        ticker_panel = ticker_panel.set_index("Date").join(cal).reset_index()
        rows.append(ticker_panel)
    panel = pd.concat(rows, ignore_index=True)
    panel["post_t1"] = (panel["Date"] >= EVENT_DATE).astype(int)
    panel["post_t1_ex_event_week"] = ((panel["Date"] >= EVENT_DATE) & (panel["event_week"] == 0)).astype(int)
    for col in ["gap_var", "intraday_var", "cc_var", "range_var", "dollar_volume"]:
        panel[f"log_{col}"] = np.log(panel[col].clip(lower=EPS))
    panel["is_adr"] = panel["group"].eq("adr").astype(int)
    panel["is_us_etf"] = panel["group"].eq("us_etf").astype(int)
    panel.to_csv(DATA_DIR / f"{EXPERIMENT_ID}_daily_panel.csv", index=False)
    return panel


def standardize(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    std = s.std(ddof=0)
    if not math.isfinite(std) or std == 0.0:
        return s * np.nan
    return (s - s.mean()) / std


def bh_qvalues(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    if n == 0:
        return []
    order = np.argsort(np.asarray(pvalues))
    q = np.empty(n)
    prev = 1.0
    for rank, idx in enumerate(order[::-1], start=1):
        original_rank = n - rank + 1
        val = min(prev, pvalues[idx] * n / original_rank)
        q[idx] = val
        prev = val
    return [float(min(max(v, 0.0), 1.0)) for v in q]


def fit_hac(df: pd.DataFrame, y_col: str, x_cols: list[str], standardize_y: bool = True) -> dict[str, Any]:
    data = df[[y_col, *x_cols]].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(data) < 120:
        return {"status": "too_few_observations", "n": int(len(data))}
    y = data[y_col].astype(float)
    if standardize_y:
        y = standardize(y)
    x = pd.DataFrame(index=data.index)
    for col in x_cols:
        if set(data[col].dropna().unique()).issubset({0, 1}):
            x[col] = data[col].astype(float)
        else:
            x[col] = standardize(data[col])
    x = sm.add_constant(x)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "status": "ok",
        "n": int(model.nobs),
        "r2": float(model.rsquared),
        "params": {k: _clean_float(v) for k, v in model.params.items()},
        "tvalues": {k: _clean_float(v) for k, v in model.tvalues.items()},
        "pvalues": {k: _clean_float(v) for k, v in model.pvalues.items()},
    }


def block_bootstrap_diff(pre: np.ndarray, post: np.ndarray, reps: int = 1000, block: int = 5) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)

    def sample_blocks(values: np.ndarray) -> np.ndarray:
        if len(values) <= block:
            return rng.choice(values, size=len(values), replace=True)
        starts = rng.integers(0, len(values) - block + 1, size=int(math.ceil(len(values) / block)))
        sampled = np.concatenate([values[s : s + block] for s in starts])
        return sampled[: len(values)]

    diffs = []
    for _ in range(reps):
        diffs.append(float(sample_blocks(post).mean() - sample_blocks(pre).mean()))
    return {
        "bootstrap_reps": reps,
        "block": block,
        "ci95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
        "p_diff_gt_0": float(np.mean(np.asarray(diffs) > 0.0)),
    }


def summarize_ticker_breaks(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, sub in panel.groupby("ticker"):
        pre = sub.loc[sub["Date"] < EVENT_DATE].copy()
        post = sub.loc[sub["Date"] >= EVENT_DATE].copy()
        for metric in ["log_gap_var", "log_cc_var", "log_range_var"]:
            pre_values = pre[metric].dropna().to_numpy()
            post_values = post[metric].dropna().to_numpy()
            if len(pre_values) < 120 or len(post_values) < 120:
                continue
            tstat, pval = stats.ttest_ind(post_values, pre_values, equal_var=False)
            boot = block_bootstrap_diff(pre_values, post_values)
            reg = fit_hac(
                sub,
                metric,
                ["post_t1", "month_end", "quarter_end", "log_dollar_volume"],
            )
            rows.append(
                {
                    "ticker": ticker,
                    "group": sub["group"].iloc[0],
                    "metric": metric,
                    "n_pre": int(len(pre_values)),
                    "n_post": int(len(post_values)),
                    "pre_mean": float(pre_values.mean()),
                    "post_mean": float(post_values.mean()),
                    "post_minus_pre": float(post_values.mean() - pre_values.mean()),
                    "welch_t": _clean_float(tstat),
                    "welch_p": _clean_float(pval),
                    "bootstrap_ci95_low": boot["ci95"][0],
                    "bootstrap_ci95_high": boot["ci95"][1],
                    "bootstrap_p_diff_gt_0": boot["p_diff_gt_0"],
                    "hac_post_coef": reg.get("params", {}).get("post_t1"),
                    "hac_post_t": reg.get("tvalues", {}).get("post_t1"),
                    "hac_post_p": reg.get("pvalues", {}).get("post_t1"),
                }
            )
    table = pd.DataFrame(rows)
    ok = table["hac_post_p"].notna()
    table["bh_q_metric_family"] = np.nan
    if ok.any():
        table.loc[ok, "bh_q_metric_family"] = bh_qvalues(
            [float(v) for v in table.loc[ok, "hac_post_p"]]
        )
    table["harvey_abs_pass"] = table["hac_post_t"].abs() >= HARVEY_T
    table.to_csv(HERE / f"{EXPERIMENT_ID}_ticker_breaks.csv", index=False)
    return table


def rebalance_interaction_tests(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group, sub in panel.groupby("group"):
        for metric in ["log_gap_var", "log_cc_var", "log_range_var"]:
            data = sub.copy()
            data["post_month_end"] = data["post_t1"] * data["month_end"]
            data["post_quarter_end"] = data["post_t1"] * data["quarter_end"]
            reg = fit_hac(
                data,
                metric,
                ["post_t1", "month_end", "quarter_end", "post_month_end", "post_quarter_end", "log_dollar_volume"],
            )
            for term in ["post_month_end", "post_quarter_end"]:
                rows.append(
                    {
                        "group": group,
                        "metric": metric,
                        "term": term,
                        "n": reg.get("n"),
                        "coef": reg.get("params", {}).get(term),
                        "hac_t": reg.get("tvalues", {}).get(term),
                        "p_value": reg.get("pvalues", {}).get(term),
                    }
                )
    table = pd.DataFrame(rows)
    ok = table["p_value"].notna()
    table["bh_q"] = np.nan
    if ok.any():
        table.loc[ok, "bh_q"] = bh_qvalues([float(v) for v in table.loc[ok, "p_value"]])
    table["harvey_abs_pass"] = table["hac_t"].abs() >= HARVEY_T
    table.to_csv(HERE / f"{EXPERIMENT_ID}_rebalance_interactions.csv", index=False)
    return table


def group_interaction_tests(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    data = panel.loc[panel["group"].isin(["us_etf", "adr", "intl_etf", "credit_etf", "bond_etf"])].copy()
    data["post_x_adr"] = data["post_t1"] * data["is_adr"]
    data["post_x_us_etf"] = data["post_t1"] * data["is_us_etf"]
    for metric in ["log_gap_var", "log_cc_var", "log_range_var"]:
        reg = fit_hac(
            data,
            metric,
            ["post_t1", "is_adr", "is_us_etf", "post_x_adr", "post_x_us_etf", "month_end", "quarter_end", "log_dollar_volume"],
        )
        for term in ["post_x_adr", "post_x_us_etf"]:
            rows.append(
                {
                    "metric": metric,
                    "term": term,
                    "n": reg.get("n"),
                    "coef": reg.get("params", {}).get(term),
                    "hac_t": reg.get("tvalues", {}).get(term),
                    "p_value": reg.get("pvalues", {}).get(term),
                }
            )
    table = pd.DataFrame(rows)
    ok = table["p_value"].notna()
    table["bh_q"] = np.nan
    if ok.any():
        table.loc[ok, "bh_q"] = bh_qvalues([float(v) for v in table.loc[ok, "p_value"]])
    table["harvey_abs_pass"] = table["hac_t"].abs() >= HARVEY_T
    table.to_csv(HERE / f"{EXPERIMENT_ID}_group_interactions.csv", index=False)
    return table


def make_figures(ticker_table: pd.DataFrame, panel: pd.DataFrame) -> list[str]:
    paths = []
    gap = ticker_table.loc[ticker_table["metric"].eq("log_gap_var")].copy()
    if not gap.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        gap = gap.sort_values("hac_post_t")
        colors = ["#E45756" if abs(v) >= HARVEY_T else "#4C78A8" for v in gap["hac_post_t"]]
        ax.barh(gap["ticker"], gap["hac_post_t"], color=colors)
        ax.axvline(HARVEY_T, color="black", ls="--", lw=0.8)
        ax.axvline(-HARVEY_T, color="black", ls="--", lw=0.8)
        ax.set_title("T+1 post dummy effect on overnight gap variance (OLS-HAC t)")
        ax.set_xlabel("HAC t-stat")
        fig.tight_layout()
        path = FIG_DIR / "t1_gap_var_hac_tstats.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(HERE)))

    group_daily = (
        panel.groupby(["Date", "group"])["gap_var"]
        .mean()
        .reset_index()
        .pivot(index="Date", columns="group", values="gap_var")
        .rolling(21, min_periods=10)
        .mean()
    )
    fig, ax = plt.subplots(figsize=(9, 5))
    for group in ["us_etf", "intl_etf", "credit_etf", "bond_etf", "adr"]:
        if group in group_daily.columns:
            ax.plot(group_daily.index, group_daily[group], label=group, lw=1.1)
    ax.axvline(EVENT_DATE, color="black", ls="--", lw=1.0, label="T+1 effective")
    ax.set_title("21-day mean overnight gap variance by group")
    ax.set_ylabel("Mean gap variance")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = FIG_DIR / "t1_group_gap_var_timeline.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(HERE)))
    return paths


def build_results(
    frames: dict[str, pd.DataFrame],
    panel: pd.DataFrame,
    ticker_table: pd.DataFrame,
    rebalance_table: pd.DataFrame,
    group_table: pd.DataFrame,
    figures: list[str],
) -> dict[str, Any]:
    primary_gap = ticker_table.loc[ticker_table["metric"].eq("log_gap_var")].copy()
    n_gap_harvey = int(primary_gap["harvey_abs_pass"].fillna(False).sum())
    n_gap_bh = int(
        (
            primary_gap["harvey_abs_pass"].fillna(False)
            & (primary_gap["bh_q_metric_family"] <= 0.05)
        ).sum()
    )
    rebalance_pass = int(
        (
            rebalance_table["harvey_abs_pass"].fillna(False)
            & (rebalance_table["bh_q"] <= 0.05)
        ).sum()
    )
    group_pass = int(
        (
            group_table["harvey_abs_pass"].fillna(False)
            & (group_table["bh_q"] <= 0.05)
        ).sum()
    )

    if n_gap_bh >= 3 or rebalance_pass >= 2 or group_pass >= 1:
        verdict = "CONDITIONAL_BREAK_DIAGNOSTIC"
    else:
        verdict = "NULL_DAILY_PROXY"

    sample = {}
    for ticker, frame in frames.items():
        sample[ticker] = {
            "start": frame.index.min().date().isoformat(),
            "end": frame.index.max().date().isoformat(),
            "n": int(len(frame)),
            "group": UNIVERSE[ticker]["group"],
        }

    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "event": {
            "event_date": EVENT_DATE.date().isoformat(),
            "description": "U.S. standard securities settlement cycle moved from T+2 to T+1 for covered securities.",
        },
        "data_sources": {
            "market_data": {
                "source": "yfinance daily adjusted OHLCV, auto_adjust=True",
                "requested_start": START,
                "requested_end_exclusive": END,
                "sample": sample,
            },
            "official_sources": LITERATURE,
        },
        "method": {
            "targets": ["log_gap_var", "log_cc_var", "log_range_var"],
            "primary_test": "per-ticker OLS-HAC: z(log_gap_var) ~ post_t1 + month_end + quarter_end + z(log_dollar_volume)",
            "secondary_tests": [
                "group-level post_t1 x ADR / US ETF interactions",
                "post_t1 x month_end and post_t1 x quarter_end rebalance-day interactions",
            ],
            "inference": f"OLS-HAC maxlags={HAC_LAGS}; Harvey absolute threshold |t| >= {HARVEY_T}; BH q-values within test families",
            "bootstrap": "stationary-style simple block bootstrap of post-minus-pre means, block=5, reps=1000, seed=42",
        },
        "lookahead_policy": "Descriptive structural-break test; no trading signal. Overnight gap uses open_t / close_{t-1}; post dummy is calendar event classification.",
        "primary_summary": {
            "n_gap_primary_tests": int(len(primary_gap)),
            "n_gap_abs_harvey": n_gap_harvey,
            "n_gap_abs_harvey_and_bh": n_gap_bh,
            "top_abs_gap_effects": primary_gap.assign(abs_t=primary_gap["hac_post_t"].abs())
            .sort_values("abs_t", ascending=False)
            .head(8)
            .drop(columns=["abs_t"])
            .to_dict(orient="records"),
            "rebalance_interaction_passes": rebalance_pass,
            "group_interaction_passes": group_pass,
        },
        "outputs": {
            "daily_panel": f"data/{EXPERIMENT_ID}_daily_panel.csv",
            "ticker_breaks": f"{EXPERIMENT_ID}_ticker_breaks.csv",
            "rebalance_interactions": f"{EXPERIMENT_ID}_rebalance_interactions.csv",
            "group_interactions": f"{EXPERIMENT_ID}_group_interactions.csv",
            "figures": figures,
        },
        "limitations": [
            "Daily OHLCV cannot see intraday settlement-fail dynamics, locate market-on-close imbalance, or identify true ETF primary-market creation/redemption timing.",
            "T+1 is a single common date; macro and market regime changes around 2024-2026 are not causally separated.",
            "ADR basket is a free-data proxy for cross-border settlement pressure, not a direct fails/affirmation-rate dataset.",
            "Month-end/quarter-end flags are mechanical last-trading-day proxies, not official index-rebalance calendars.",
        ],
        "claim_rule": "A strong structural-break claim requires multiple gap-variance cells passing |t|>=3 and BH q<=0.05 or a robust group/rebalance interaction. Otherwise report NULL_DAILY_PROXY.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    frames = fetch_ohlcv(refresh=args.refresh)
    panel = build_panel(frames)
    ticker_table = summarize_ticker_breaks(panel)
    rebalance_table = rebalance_interaction_tests(panel)
    group_table = group_interaction_tests(panel)
    figures = make_figures(ticker_table, panel)
    results = build_results(frames, panel, ticker_table, rebalance_table, group_table, figures)

    out = HERE / f"{EXPERIMENT_ID}_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(
        f"[{EXPERIMENT_ID}] verdict={results['verdict']} | "
        f"gap pass={results['primary_summary']['n_gap_abs_harvey_and_bh']} | wrote {out}",
        flush=True,
    )


if __name__ == "__main__":
    main()
