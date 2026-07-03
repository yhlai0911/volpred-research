#!/usr/bin/env python3
"""Minimum-wage effective-date events and wage-sensitive equity volatility.

Experiment question:
Do public minimum-wage effective dates line up with higher realized volatility
or downside variance in public restaurant/retail equities?

Research-honesty guardrails:
- This is a public event-date proxy, not a replication of county-border or
  firm-establishment exposure designs.
- Event dates are known before market trading. The script never multiplies a
  same-day trading signal by a same-day return.
- Outcomes are post-event realized variance changes relative to pre-event
  windows and benchmark controls.
- Inference uses event-level tests, Holm correction, and bootstrap confidence
  intervals. A placebo calendar test is run for the primary 22-day RV cell.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st
import yfinance as yf
from statsmodels.stats.multitest import multipletests


EXPERIMENT_ID = "research_minimum_wage_state_event_retail_vol"
SEED = 42
START = "2020-01-01"
END = "2026-07-04"
TRADING_DAYS = 252
WINDOWS = [10, 22]
N_BOOT = 2000
N_PLACEBO = 2000

ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "figures"
DATA_DIR = ROOT / "data"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"


DATA_SOURCES = {
    "event_dates": {
        "dol_state_minimum_wage": "https://www.dol.gov/agencies/whd/minimum-wage/state",
        "dol_consolidated_table": "https://www.dol.gov/agencies/whd/mw-consolidated",
        "epi_tracker": "https://www.epi.org/minimum-wage-tracker/",
        "ncsl_state_minimum_wages": "https://www.ncsl.org/labor-and-employment/state-minimum-wages",
        "california_fast_food": "https://www.dir.ca.gov/dlse/minimum_wage.htm",
    },
    "market": {
        "provider": "yfinance",
        "price_field": "Close, auto_adjust=True",
    },
}

LITERATURE = [
    {
        "citation": "Dube, Lester, and Reich (2010), Review of Economics and Statistics",
        "url": "https://irle.berkeley.edu/publications/scholarly-publications/minimum-wage-effects-across-state-borders-estimates-using-contiguous-counties/",
        "role": "state-border discontinuity motivation in restaurants and low-wage sectors",
    },
    {
        "citation": "Card and Krueger, The Effect of the Minimum Wage on Shareholder Wealth",
        "url": "https://davidcard.berkeley.edu/papers/minwage-shareholder.pdf",
        "role": "stock-market event-study precedent for minimum-wage news",
    },
    {
        "citation": "Rao and Risch (2026), Quarterly Journal of Economics",
        "url": "https://academic.oup.com/qje/article/141/1/373/8376639",
        "role": "recent state-policy variation evidence on exposed businesses and cost pass-through",
    },
    {
        "citation": "Luca and Luca, Survival of the Fittest",
        "url": "https://www.hbs.edu/ris/Publication%20Files/17-088_9f5c63e3-fcb7-4144-b9cf-74bf594cc308.pdf",
        "role": "restaurant-industry minimum-wage exposure and firm-exit channel",
    },
]


EVENTS = [
    # Repeated broad state-level effective-date clusters. The labels are
    # intentionally coarse: this pilot tests calendar-cost shocks, not exact
    # store-level exposure.
    ("2021-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2021-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
    ("2021-09-30", "florida_step", "Florida constitutional step increase"),
    ("2021-12-31", "ny_step", "New York annual step increase"),
    ("2022-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2022-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
    ("2022-09-30", "florida_step", "Florida constitutional step increase"),
    ("2022-12-31", "ny_step", "New York annual step increase"),
    ("2023-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2023-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
    ("2023-09-30", "florida_step", "Florida constitutional step increase"),
    ("2023-12-31", "ny_step", "New York annual step increase"),
    ("2024-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2024-04-01", "ca_fast_food_20", "California fast-food $20 minimum wage"),
    ("2024-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
    ("2024-09-30", "florida_step", "Florida constitutional step increase"),
    ("2025-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2025-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
    ("2025-09-30", "florida_step", "Florida constitutional step increase"),
    ("2026-01-01", "multi_state_jan", "Annual state minimum-wage increases"),
    ("2026-07-01", "midyear_state", "Mid-year state/local minimum-wage increases"),
]


GROUPS = {
    "restaurants": [
        "MCD",
        "SBUX",
        "CMG",
        "YUM",
        "DRI",
        "WEN",
        "DPZ",
        "TXRH",
        "EAT",
        "SHAK",
    ],
    "retail": [
        "WMT",
        "TGT",
        "COST",
        "DG",
        "DLTR",
        "TJX",
        "ROST",
        "M",
        "KSS",
        "BBY",
    ],
    "low_labor_tech": [
        "AAPL",
        "MSFT",
        "GOOGL",
        "META",
        "NVDA",
        "ADBE",
        "CRM",
        "AVGO",
        "INTU",
        "ORCL",
    ],
}

BENCHMARKS = ["SPY", "XLY", "XLP"]
ALL_TICKERS = sorted({t for tickers in GROUPS.values() for t in tickers} | set(BENCHMARKS))


@dataclass(frozen=True)
class TestSpec:
    group: str
    control: str
    window: int
    metric: str

    @property
    def key(self) -> str:
        return f"{self.group}_minus_{self.control}_{self.window}d_{self.metric}"


PRIMARY_SPECS = [
    TestSpec("restaurants", "XLY", 22, "rv"),
    TestSpec("retail", "XLY", 22, "rv"),
    TestSpec("wage_sensitive", "XLY", 22, "rv"),
    TestSpec("restaurants", "SPY", 22, "rv"),
    TestSpec("retail", "SPY", 22, "rv"),
    TestSpec("wage_sensitive", "SPY", 22, "rv"),
    TestSpec("restaurants", "XLY", 22, "downside"),
    TestSpec("retail", "XLY", 22, "downside"),
    TestSpec("wage_sensitive", "XLY", 22, "downside"),
    TestSpec("restaurants", "low_labor_tech", 22, "rv"),
    TestSpec("retail", "low_labor_tech", 22, "rv"),
    TestSpec("wage_sensitive", "low_labor_tech", 22, "rv"),
]


def fetch_close() -> pd.DataFrame:
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:
        close = raw[["Close"]].copy()
        close.columns = ALL_TICKERS
    close = close.dropna(axis=1, how="all").sort_index()
    missing = sorted(set(ALL_TICKERS) - set(close.columns))
    if missing:
        raise RuntimeError(f"Missing yfinance close columns: {missing}")
    return close[ALL_TICKERS]


def build_return_panel(close: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    ret = np.log(close).diff().dropna(how="all")
    panel = pd.DataFrame(index=ret.index)
    components: dict[str, Any] = {}

    for group, tickers in GROUPS.items():
        available = [t for t in tickers if t in ret.columns]
        min_count = max(3, int(np.ceil(len(available) * 0.6)))
        counts = ret[available].notna().sum(axis=1)
        series = ret[available].mean(axis=1, skipna=True)
        series[counts < min_count] = np.nan
        panel[group] = series
        components[group] = {
            "tickers": available,
            "min_daily_count": min_count,
            "median_daily_count": float(counts.median()),
        }

    wage_sensitive = sorted(set(GROUPS["restaurants"]) | set(GROUPS["retail"]))
    counts = ret[wage_sensitive].notna().sum(axis=1)
    series = ret[wage_sensitive].mean(axis=1, skipna=True)
    series[counts < 10] = np.nan
    panel["wage_sensitive"] = series
    components["wage_sensitive"] = {
        "tickers": wage_sensitive,
        "min_daily_count": 10,
        "median_daily_count": float(counts.median()),
    }

    for ticker in BENCHMARKS:
        panel[ticker] = ret[ticker]
        components[ticker] = {"tickers": [ticker], "min_daily_count": 1}

    return panel, components


def _event_trade_date(index: pd.DatetimeIndex, event_date: str) -> pd.Timestamp | None:
    event_ts = pd.Timestamp(event_date)
    pos = index.searchsorted(event_ts)
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def _window_stats(series: pd.Series, event_trade_date: pd.Timestamp, window: int) -> dict[str, float] | None:
    clean = series.dropna()
    if event_trade_date not in clean.index:
        return None
    pos = clean.index.get_loc(event_trade_date)
    if pos < window or pos + window > len(clean):
        return None
    pre = clean.iloc[pos - window : pos]
    post = clean.iloc[pos : pos + window]
    eps = 1e-12
    pre_rv = float(pre.pow(2).sum() * TRADING_DAYS / len(pre))
    post_rv = float(post.pow(2).sum() * TRADING_DAYS / len(post))
    pre_down = float(np.minimum(pre, 0).pow(2).sum() * TRADING_DAYS / len(pre))
    post_down = float(np.minimum(post, 0).pow(2).sum() * TRADING_DAYS / len(post))
    return {
        "pre_rv": pre_rv,
        "post_rv": post_rv,
        "delta_log_rv": float(np.log(post_rv + eps) - np.log(pre_rv + eps)),
        "pre_downside": pre_down,
        "post_downside": post_down,
        "delta_log_downside": float(np.log(post_down + eps) - np.log(pre_down + eps)),
        "pre_return": float(pre.sum()),
        "post_return": float(post.sum()),
        "delta_return": float(post.sum() - pre.sum()),
    }


def build_event_panel(ret_panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event_date, event_type, label in EVENTS:
        trade_date = _event_trade_date(ret_panel.index, event_date)
        if trade_date is None:
            continue
        for window in WINDOWS:
            stats_by_series = {
                name: _window_stats(ret_panel[name], trade_date, window)
                for name in ret_panel.columns
            }
            for group in ["restaurants", "retail", "wage_sensitive"]:
                group_stats = stats_by_series.get(group)
                if group_stats is None:
                    continue
                for control in ["SPY", "XLY", "XLP", "low_labor_tech"]:
                    control_stats = stats_by_series.get(control)
                    if control_stats is None:
                        continue
                    rows.append(
                        {
                            "event_date": event_date,
                            "event_trade_date": trade_date.date().isoformat(),
                            "event_type": event_type,
                            "event_label": label,
                            "window": window,
                            "group": group,
                            "control": control,
                            "did_rv": group_stats["delta_log_rv"] - control_stats["delta_log_rv"],
                            "did_downside": group_stats["delta_log_downside"]
                            - control_stats["delta_log_downside"],
                            "group_delta_log_rv": group_stats["delta_log_rv"],
                            "control_delta_log_rv": control_stats["delta_log_rv"],
                            "group_delta_log_downside": group_stats["delta_log_downside"],
                            "control_delta_log_downside": control_stats["delta_log_downside"],
                            "group_delta_return": group_stats["delta_return"],
                            "control_delta_return": control_stats["delta_return"],
                        }
                    )
    return pd.DataFrame(rows)


def bootstrap_mean_ci(values: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    if len(values) == 0:
        return {"ci_low": np.nan, "ci_high": np.nan, "p_mean_gt_0": np.nan}
    draws = rng.choice(values, size=(N_BOOT, len(values)), replace=True).mean(axis=1)
    return {
        "ci_low": float(np.percentile(draws, 2.5)),
        "ci_high": float(np.percentile(draws, 97.5)),
        "p_mean_gt_0": float(np.mean(draws > 0)),
    }


def summarize_tests(event_panel: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows: list[dict[str, Any]] = []
    for spec in PRIMARY_SPECS:
        metric_col = f"did_{spec.metric}"
        subset = event_panel[
            (event_panel["group"] == spec.group)
            & (event_panel["control"] == spec.control)
            & (event_panel["window"] == spec.window)
        ].copy()
        values = subset[metric_col].dropna().to_numpy(dtype=float)
        if len(values) < 5:
            rows.append(
                {
                    "key": spec.key,
                    "group": spec.group,
                    "control": spec.control,
                    "window": spec.window,
                    "metric": spec.metric,
                    "n_events": int(len(values)),
                    "insufficient": True,
                }
            )
            continue
        t_stat, p_value = st.ttest_1samp(values, 0.0)
        try:
            wilcoxon_p = float(st.wilcoxon(values, alternative="two-sided").pvalue)
        except ValueError:
            wilcoxon_p = np.nan
        ci = bootstrap_mean_ci(values, rng)
        rows.append(
            {
                "key": spec.key,
                "group": spec.group,
                "control": spec.control,
                "window": spec.window,
                "metric": spec.metric,
                "n_events": int(len(values)),
                "mean_did": float(values.mean()),
                "median_did": float(np.median(values)),
                "std_did": float(values.std(ddof=1)),
                "t_stat": float(t_stat),
                "p_value_two_sided": float(p_value),
                "wilcoxon_p": wilcoxon_p,
                "positive_event_share": float(np.mean(values > 0)),
                "bootstrap_ci_low": ci["ci_low"],
                "bootstrap_ci_high": ci["ci_high"],
                "bootstrap_p_mean_gt_0": ci["p_mean_gt_0"],
                "insufficient": False,
            }
        )
    summary = pd.DataFrame(rows)
    mask = ~summary["insufficient"].fillna(False)
    if mask.any():
        _, p_holm, _, _ = multipletests(summary.loc[mask, "p_value_two_sided"], method="holm")
        _, p_bonf, _, _ = multipletests(summary.loc[mask, "p_value_two_sided"], method="bonferroni")
        summary.loc[mask, "p_holm"] = p_holm
        summary.loc[mask, "p_bonferroni"] = p_bonf
        summary.loc[mask, "positive_support_gate"] = (
            (summary.loc[mask, "mean_did"] > 0)
            & (summary.loc[mask, "t_stat"].abs() >= 3.0)
            & (summary.loc[mask, "p_holm"] < 0.05)
            & (summary.loc[mask, "bootstrap_ci_low"] > 0)
        )
    return summary.sort_values("t_stat", ascending=False)


def _single_date_did(
    ret_panel: pd.DataFrame,
    trade_date: pd.Timestamp,
    group: str,
    control: str,
    window: int,
    metric: str,
) -> float | None:
    group_stats = _window_stats(ret_panel[group], trade_date, window)
    control_stats = _window_stats(ret_panel[control], trade_date, window)
    if group_stats is None or control_stats is None:
        return None
    metric_key = "delta_log_rv" if metric == "rv" else "delta_log_downside"
    return group_stats[metric_key] - control_stats[metric_key]


def placebo_test(ret_panel: pd.DataFrame, event_panel: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED + 1)
    group = "wage_sensitive"
    control = "XLY"
    window = 22
    metric = "rv"
    event_values = event_panel[
        (event_panel["group"] == group)
        & (event_panel["control"] == control)
        & (event_panel["window"] == window)
    ]["did_rv"].dropna()
    event_mean = float(event_values.mean())

    event_trade_dates = pd.to_datetime(
        event_panel.loc[event_panel["window"] == window, "event_trade_date"].drop_duplicates()
    )
    event_positions = [ret_panel.index.get_loc(d) for d in event_trade_dates if d in ret_panel.index]
    candidate_values: list[float] = []
    candidate_dates: list[str] = []
    for pos in range(window, len(ret_panel.index) - window):
        if any(abs(pos - ep) <= window for ep in event_positions):
            continue
        if pos % 3 != 0:
            continue
        trade_date = pd.Timestamp(ret_panel.index[pos])
        did = _single_date_did(ret_panel, trade_date, group, control, window, metric)
        if did is not None and np.isfinite(did):
            candidate_values.append(float(did))
            candidate_dates.append(trade_date.date().isoformat())

    candidates = np.array(candidate_values, dtype=float)
    n_events = len(event_values)
    if len(candidates) < n_events or n_events == 0:
        return {
            "key": "wage_sensitive_minus_XLY_22d_rv",
            "error": "insufficient placebo candidates",
            "event_mean": event_mean,
            "n_events": int(n_events),
            "n_candidates": int(len(candidates)),
        }
    placebo_means = np.empty(N_PLACEBO)
    for i in range(N_PLACEBO):
        sample = rng.choice(candidates, size=n_events, replace=False)
        placebo_means[i] = sample.mean()

    placebo_df = pd.DataFrame({"placebo_mean_did": placebo_means})
    placebo_df.to_csv(DATA_DIR / "placebo_primary_means.csv", index=False)
    return {
        "key": "wage_sensitive_minus_XLY_22d_rv",
        "event_mean": event_mean,
        "n_events": int(n_events),
        "n_candidates": int(len(candidates)),
        "n_placebo": int(N_PLACEBO),
        "placebo_mean": float(placebo_means.mean()),
        "placebo_std": float(placebo_means.std(ddof=1)),
        "event_percentile_vs_placebo": float(np.mean(placebo_means <= event_mean)),
        "one_sided_p_placebo_ge_event": float((np.sum(placebo_means >= event_mean) + 1) / (N_PLACEBO + 1)),
        "candidate_date_start": candidate_dates[0],
        "candidate_date_end": candidate_dates[-1],
    }


def make_figures(summary: pd.DataFrame, placebo: dict[str, Any]) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    figure_paths: list[str] = []

    plot_df = summary.copy()
    plot_df["label"] = (
        plot_df["group"]
        + "-"
        + plot_df["control"]
        + "-"
        + plot_df["metric"]
    )
    plot_df = plot_df.sort_values("t_stat")
    plt.figure(figsize=(10, 6))
    colors = ["#2c7fb8" if x > 0 else "#d95f0e" for x in plot_df["t_stat"]]
    plt.barh(plot_df["label"], plot_df["t_stat"], color=colors)
    plt.axvline(3.0, color="black", linestyle="--", linewidth=1, label="Harvey |t|=3")
    plt.axvline(-3.0, color="black", linestyle="--", linewidth=1)
    plt.xlabel("One-sample t-stat of event-level DID")
    plt.title("Minimum-wage event windows: target basket minus control")
    plt.tight_layout()
    path = FIG_DIR / "event_did_tstats.png"
    plt.savefig(path, dpi=160)
    plt.close()
    figure_paths.append(str(path))

    placebo_path = DATA_DIR / "placebo_primary_means.csv"
    if placebo_path.exists() and "event_mean" in placebo:
        placebo_df = pd.read_csv(placebo_path)
        plt.figure(figsize=(9, 5))
        plt.hist(placebo_df["placebo_mean_did"], bins=40, color="#8da0cb", alpha=0.85)
        plt.axvline(placebo["event_mean"], color="#d95f02", linewidth=2, label="event mean")
        plt.xlabel("Placebo mean DID, wage-sensitive minus XLY 22d RV")
        plt.ylabel("Random calendar samples")
        plt.title("Placebo calendar distribution")
        plt.legend()
        plt.tight_layout()
        path = FIG_DIR / "primary_placebo_distribution.png"
        plt.savefig(path, dpi=160)
        plt.close()
        figure_paths.append(str(path))
    return figure_paths


def build_results(
    close: pd.DataFrame,
    ret_panel: pd.DataFrame,
    components: dict[str, Any],
    event_panel: pd.DataFrame,
    summary: pd.DataFrame,
    placebo: dict[str, Any],
    figures: list[str],
) -> dict[str, Any]:
    valid_tests = summary[~summary["insufficient"].fillna(False)].copy()
    positive_support_count = int(valid_tests["positive_support_gate"].fillna(False).sum())
    raw_positive_t2 = int(((valid_tests["mean_did"] > 0) & (valid_tests["t_stat"] >= 2.0)).sum())
    strongest = valid_tests.iloc[valid_tests["t_stat"].abs().argmax()].to_dict()
    strongest_positive = (
        valid_tests[valid_tests["mean_did"] > 0]
        .sort_values("t_stat", ascending=False)
        .head(1)
    )
    if positive_support_count > 0:
        verdict = "CONDITIONAL_SUPPORT_PUBLIC_EVENT_PROXY"
        conclusion = (
            "At least one positive event-window DID cell survives the Harvey-Holm gate, "
            "but this remains a public calendar-event proxy rather than state-border or "
            "firm-establishment exposure identification."
        )
    elif raw_positive_t2 > 0:
        verdict = "WEAK_RAW_ONLY_NO_ROBUST_PASS"
        conclusion = (
            "Some cells have raw positive t-statistics above 2, but no primary cell "
            "survives the Harvey-Holm and bootstrap gate."
        )
    else:
        verdict = "NULL_PUBLIC_EVENT_STUDY"
        conclusion = (
            "The public minimum-wage effective-date calendar does not provide robust "
            "evidence of higher restaurant/retail realized volatility relative to controls."
        )

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "Minimum-wage effective dates and restaurant/retail realized volatility",
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "conclusion": conclusion,
        "data_sources": DATA_SOURCES,
        "literature": LITERATURE,
        "event_design": {
            "events_embedded": len(EVENTS),
            "events_used": int(event_panel[["event_date", "event_trade_date"]].drop_duplicates().shape[0]),
            "windows_trading_days": WINDOWS,
            "event_table": [
                {"event_date": d, "event_type": t, "label": label}
                for d, t, label in EVENTS
            ],
            "limitations": [
                "Events are common public effective-date clusters, not store-level exposure shocks.",
                "Large public chains have geographically diversified operations; state exposure is measured only indirectly.",
                "Jan-1 events are seasonal and partly anticipated; benchmark DID and placebo tests reduce but do not eliminate this confounding.",
            ],
        },
        "market_data": {
            "sample_start": close.index.min().date().isoformat(),
            "sample_end": close.index.max().date().isoformat(),
            "return_sample_start": ret_panel.index.min().date().isoformat(),
            "return_sample_end": ret_panel.index.max().date().isoformat(),
            "tickers_requested": ALL_TICKERS,
            "components": components,
            "n_trading_days": int(ret_panel.shape[0]),
        },
        "primary_tests": int(len(PRIMARY_SPECS)),
        "positive_support_count": positive_support_count,
        "raw_positive_t_gt_2_count": raw_positive_t2,
        "strongest_absolute_t": _json_clean(strongest),
        "strongest_positive": _json_clean(
            strongest_positive.iloc[0].to_dict() if not strongest_positive.empty else {}
        ),
        "placebo_primary": _json_clean(placebo),
        "figures": figures,
        "output_files": {
            "event_panel_csv": str(DATA_DIR / "event_panel.csv"),
            "summary_table_csv": str(DATA_DIR / "summary_table.csv"),
            "placebo_csv": str(DATA_DIR / "placebo_primary_means.csv"),
        },
    }


def _json_clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def main() -> None:
    np.random.seed(SEED)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    close = fetch_close()
    ret_panel, components = build_return_panel(close)
    event_panel = build_event_panel(ret_panel)
    if event_panel.empty:
        raise RuntimeError("Event panel is empty; check yfinance data and event dates.")

    summary = summarize_tests(event_panel)
    placebo = placebo_test(ret_panel, event_panel)
    event_panel.to_csv(DATA_DIR / "event_panel.csv", index=False)
    summary.to_csv(DATA_DIR / "summary_table.csv", index=False)
    figures = make_figures(summary, placebo)
    results = build_results(close, ret_panel, components, event_panel, summary, placebo, figures)
    RESULTS_PATH.write_text(json.dumps(_json_clean(results), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_json_clean({k: results[k] for k in [
        "experiment_id",
        "verdict",
        "positive_support_count",
        "raw_positive_t_gt_2_count",
        "conclusion",
    ]}), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
