#!/usr/bin/env python3
"""
Attention-utility winner focus proxy diagnostic.

Question:
Do recent winners in retail-heavy / meme-risk stocks show stronger next-session
volume, range-volatility, gap-risk, and squared-return reactions than recent
losers, and is the asymmetry larger than in a large-cap control basket?

This is deliberately a proxy diagnostic, not a replication of brokerage-login,
Google Trends, Reddit, or Stocktwits attention measures. All winner/loser event
labels are computed from information available at t-1 and outcomes are measured
on t.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_attention_utility_winner_focus_winner_side_rv_vo"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_summary.png"

DATA_START = "2020-01-01"
DATA_END = "2026-06-29"  # yfinance end is exclusive.
SEED = 42
BOOT_REPS = 5000

BASKETS: dict[str, list[str]] = {
    "retail_meme_risk": [
        "GME",
        "AMC",
        "BB",
        "PLTR",
        "RIVN",
        "SOFI",
        "COIN",
        "HOOD",
        "DKNG",
        "CVNA",
    ],
    "large_cap_control": [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "JPM",
        "XOM",
        "UNH",
        "WMT",
    ],
}

OUTCOMES: dict[str, str] = {
    "abn_volume_z": "Abnormal volume z-score",
    "range_vol_z": "Range-vol z-score",
    "gap_abs_z": "Absolute gap z-score",
    "rv_z": "Squared-return z-score",
}


@dataclass(frozen=True)
class WindowSpec:
    name: str
    description: str
    mask: Callable[[pd.DataFrame], pd.Series]
    min_events_per_side: int


WINDOWS: list[WindowSpec] = [
    WindowSpec(
        name="all_next_sessions",
        description="All next trading sessions after the t-1 winner/loser label",
        mask=lambda df: pd.Series(True, index=df.index),
        min_events_per_side=20,
    ),
    WindowSpec(
        name="monday_post_weekend",
        description="Monday sessions, proxying post-weekend attention release",
        mask=lambda df: df["post_weekend"].astype(bool),
        min_events_per_side=4,
    ),
]


def json_safe(obj):
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


def safe_float(value: float | int | np.floating | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not np.isfinite(value):
        return None
    return value


def download_panel(tickers: list[str]) -> dict[str, pd.DataFrame]:
    print(f"Downloading {len(tickers)} tickers from yfinance...")
    raw = yf.download(
        tickers,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    panel: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        df: pd.DataFrame | None = None
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = raw.columns.get_level_values(0)
            level1 = raw.columns.get_level_values(1)
            if ticker in set(level0):
                df = raw[ticker].copy()
            elif ticker in set(level1):
                df = raw.xs(ticker, axis=1, level=1).copy()
        else:
            # Single ticker fallback; not expected here but keeps the helper safe.
            df = raw.copy()

        if df is None or df.empty:
            print(f"  WARN {ticker}: no data returned")
            continue

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            print(f"  WARN {ticker}: missing columns {missing}")
            continue

        df = df[required].dropna().copy()
        df = df[df["Volume"] > 0]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        if len(df) < 360:
            print(f"  WARN {ticker}: too few rows after cleaning ({len(df)})")
            continue
        panel[ticker] = df

    return panel


def lagged_zscore(series: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    past = series.shift(1)
    mean = past.rolling(window, min_periods=min_periods).mean()
    std = past.rolling(window, min_periods=min_periods).std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def build_features(ticker: str, group: str, ohlcv: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv.copy()

    close = df["Close"]
    open_ = df["Open"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    log_ret_pct = np.log(close / close.shift(1)) * 100.0
    range_vol = (np.log(high / low) * 100.0) ** 2
    gap_abs = (np.log(open_ / close.shift(1)) * 100.0).abs()
    rv = log_ret_pct**2
    log_volume = np.log(volume.replace(0, np.nan))

    ret21_lag = close.pct_change(21).shift(1)
    ret21_q80_lag = ret21_lag.rolling(252, min_periods=126).quantile(0.80)
    ret21_q20_lag = ret21_lag.rolling(252, min_periods=126).quantile(0.20)

    close_lag = close.shift(1)
    high63_lag = close_lag.rolling(63, min_periods=42).max()
    low63_lag = close_lag.rolling(63, min_periods=42).min()

    high_return_winner = ret21_lag >= ret21_q80_lag
    near_recent_high = close_lag >= 0.98 * high63_lag
    high_return_loser = ret21_lag <= ret21_q20_lag
    near_recent_low = close_lag <= 1.02 * low63_lag

    winner_event = (high_return_winner | near_recent_high).fillna(False)
    loser_event = (high_return_loser | near_recent_low).fillna(False)

    # Rare conflicts can happen after sharp reversals. Dropping them keeps the
    # event-side comparison unambiguous rather than forcing an arbitrary label.
    conflict = winner_event & loser_event
    winner_event = winner_event & ~conflict
    loser_event = loser_event & ~conflict

    out = pd.DataFrame(
        {
            "ticker": ticker,
            "group": group,
            "close": close,
            "ret21_lag": ret21_lag,
            "ret21_q80_lag": ret21_q80_lag,
            "ret21_q20_lag": ret21_q20_lag,
            "winner_event": winner_event.astype(bool),
            "loser_event": loser_event.astype(bool),
            "post_weekend": (df.index.dayofweek == 0),
            "abn_volume_z": lagged_zscore(log_volume),
            "range_vol_z": lagged_zscore(range_vol),
            "gap_abs_z": lagged_zscore(gap_abs),
            "rv_z": lagged_zscore(rv),
        },
        index=df.index,
    )
    out.index.name = "date"
    return out


def bootstrap_ci_mean(values: np.ndarray, rng: np.random.Generator) -> tuple[float | None, float | None]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return None, None
    boot = np.empty(BOOT_REPS)
    for i in range(BOOT_REPS):
        boot[i] = rng.choice(values, size=len(values), replace=True).mean()
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return float(lo), float(hi)


def ticker_level_diffs(
    panel: pd.DataFrame,
    group: str,
    window: WindowSpec,
    outcome: str,
) -> pd.DataFrame:
    group_panel = panel[panel["group"] == group].copy()
    win_mask = window.mask(group_panel)
    group_panel = group_panel[win_mask & np.isfinite(group_panel[outcome])]

    rows = []
    for ticker, sub in group_panel.groupby("ticker", sort=True):
        winners = sub.loc[sub["winner_event"], outcome].dropna()
        losers = sub.loc[sub["loser_event"], outcome].dropna()
        if len(winners) < window.min_events_per_side or len(losers) < window.min_events_per_side:
            continue
        rows.append(
            {
                "ticker": ticker,
                "winner_mean": float(winners.mean()),
                "loser_mean": float(losers.mean()),
                "winner_minus_loser": float(winners.mean() - losers.mean()),
                "n_winner": int(len(winners)),
                "n_loser": int(len(losers)),
            }
        )
    return pd.DataFrame(rows)


def within_group_test(
    panel: pd.DataFrame,
    group: str,
    window: WindowSpec,
    outcome: str,
    rng: np.random.Generator,
) -> dict:
    diffs = ticker_level_diffs(panel, group, window, outcome)
    diff_values = diffs["winner_minus_loser"].to_numpy(dtype=float) if len(diffs) else np.array([])
    n_tickers = int(len(diff_values))

    if n_tickers >= 3:
        t_stat, p_value = stats.ttest_1samp(diff_values, popmean=0.0)
    else:
        t_stat, p_value = np.nan, np.nan

    ci_lo, ci_hi = bootstrap_ci_mean(diff_values, rng)
    return {
        "test_type": "within_group_ticker_cluster_mean",
        "group": group,
        "window": window.name,
        "window_description": window.description,
        "outcome": outcome,
        "outcome_label": OUTCOMES[outcome],
        "n_tickers": n_tickers,
        "n_winner_events": int(diffs["n_winner"].sum()) if len(diffs) else 0,
        "n_loser_events": int(diffs["n_loser"].sum()) if len(diffs) else 0,
        "mean_winner": safe_float(diffs["winner_mean"].mean()) if len(diffs) else None,
        "mean_loser": safe_float(diffs["loser_mean"].mean()) if len(diffs) else None,
        "mean_winner_minus_loser": safe_float(diff_values.mean()) if n_tickers else None,
        "t_stat": safe_float(t_stat),
        "p_value_raw": safe_float(p_value),
        "bootstrap_ci_95": [ci_lo, ci_hi],
        "ticker_effects": diffs.to_dict(orient="records"),
    }


def did_test(
    panel: pd.DataFrame,
    window: WindowSpec,
    outcome: str,
    rng: np.random.Generator,
) -> dict:
    retail = ticker_level_diffs(panel, "retail_meme_risk", window, outcome)
    control = ticker_level_diffs(panel, "large_cap_control", window, outcome)
    retail_values = (
        retail["winner_minus_loser"].to_numpy(dtype=float) if len(retail) else np.array([])
    )
    control_values = (
        control["winner_minus_loser"].to_numpy(dtype=float) if len(control) else np.array([])
    )

    if len(retail_values) >= 3 and len(control_values) >= 3:
        t_stat, p_value = stats.ttest_ind(retail_values, control_values, equal_var=False)
        did = float(retail_values.mean() - control_values.mean())
        boot = np.empty(BOOT_REPS)
        for i in range(BOOT_REPS):
            r = rng.choice(retail_values, size=len(retail_values), replace=True).mean()
            c = rng.choice(control_values, size=len(control_values), replace=True).mean()
            boot[i] = r - c
        ci_lo, ci_hi = np.quantile(boot, [0.025, 0.975])
    else:
        t_stat, p_value, did, ci_lo, ci_hi = np.nan, np.nan, np.nan, np.nan, np.nan

    return {
        "test_type": "difference_in_differences_ticker_cluster_mean",
        "contrast": "retail_meme_risk_minus_large_cap_control",
        "window": window.name,
        "window_description": window.description,
        "outcome": outcome,
        "outcome_label": OUTCOMES[outcome],
        "n_retail_tickers": int(len(retail_values)),
        "n_control_tickers": int(len(control_values)),
        "retail_mean_winner_minus_loser": safe_float(retail_values.mean())
        if len(retail_values)
        else None,
        "control_mean_winner_minus_loser": safe_float(control_values.mean())
        if len(control_values)
        else None,
        "did_retail_minus_control": safe_float(did),
        "t_stat": safe_float(t_stat),
        "p_value_raw": safe_float(p_value),
        "bootstrap_ci_95": [safe_float(ci_lo), safe_float(ci_hi)],
        "retail_ticker_effects": retail.to_dict(orient="records"),
        "control_ticker_effects": control.to_dict(orient="records"),
    }


def holm_adjust(records: list[dict], p_key: str = "p_value_raw") -> None:
    valid = [
        (idx, rec[p_key])
        for idx, rec in enumerate(records)
        if rec.get(p_key) is not None and np.isfinite(rec[p_key])
    ]
    m = len(valid)
    if m == 0:
        for rec in records:
            rec["p_value_holm"] = None
            rec["holm_reject_5pct"] = False
        return

    valid_sorted = sorted(valid, key=lambda item: item[1])
    running_max = 0.0
    adjusted: dict[int, float] = {}
    for rank, (idx, p_value) in enumerate(valid_sorted, start=1):
        adj = min(1.0, (m - rank + 1) * float(p_value))
        running_max = max(running_max, adj)
        adjusted[idx] = running_max

    for idx, rec in enumerate(records):
        adj = adjusted.get(idx)
        rec["p_value_holm"] = safe_float(adj)
        rec["holm_reject_5pct"] = bool(adj is not None and adj <= 0.05)


def summarize_sample(panel: pd.DataFrame) -> dict:
    summary: dict[str, dict] = {}
    for group, sub_group in panel.groupby("group"):
        group_summary = {}
        for ticker, sub in sub_group.groupby("ticker"):
            group_summary[ticker] = {
                "start": str(sub.index.min().date()),
                "end": str(sub.index.max().date()),
                "observations": int(len(sub)),
                "winner_events": int(sub["winner_event"].sum()),
                "loser_events": int(sub["loser_event"].sum()),
                "post_weekend_observations": int(sub["post_weekend"].sum()),
            }
        summary[group] = group_summary
    return summary


def verdict_from_tests(within: list[dict], did: list[dict]) -> dict:
    retail_passes = [
        rec
        for rec in within
        if rec["group"] == "retail_meme_risk"
        and rec.get("holm_reject_5pct")
        and (rec.get("mean_winner_minus_loser") or 0.0) > 0
    ]
    control_passes = [
        rec
        for rec in within
        if rec["group"] == "large_cap_control"
        and rec.get("holm_reject_5pct")
        and (rec.get("mean_winner_minus_loser") or 0.0) > 0
    ]
    did_passes = [
        rec
        for rec in did
        if rec.get("holm_reject_5pct") and (rec.get("did_retail_minus_control") or 0.0) > 0
    ]
    retail_negative_passes = [
        rec
        for rec in within
        if rec["group"] == "retail_meme_risk"
        and rec.get("holm_reject_5pct")
        and (rec.get("mean_winner_minus_loser") or 0.0) < 0
    ]
    control_negative_passes = [
        rec
        for rec in within
        if rec["group"] == "large_cap_control"
        and rec.get("holm_reject_5pct")
        and (rec.get("mean_winner_minus_loser") or 0.0) < 0
    ]

    if retail_passes and did_passes:
        label = "POSITIVE_PROXY_RETAIL_WINNER_SIDE_ATTENTION"
        interpretation = (
            "Retail/meme-risk winner-minus-loser asymmetry survives Holm correction "
            "and is stronger than the large-cap control for at least one outcome/window."
        )
    elif did_passes:
        label = "RELATIVE_DID_ONLY_NO_ABSOLUTE_RETAIL_PASS"
        interpretation = (
            "Retail-minus-control asymmetry survives Holm correction, but the retail "
            "basket's own winner-minus-loser effects do not. This is compatible with "
            "retail winner-side attention, but the evidence is relative and exploratory, "
            "not an absolute positive winner-side pass."
        )
    elif retail_passes:
        label = "POSITIVE_WITHOUT_RETAIL_CONTROL_DOMINANCE"
        interpretation = (
            "Retail/meme-risk winners show Holm-significant asymmetry, but the "
            "retail-minus-control difference does not survive correction."
        )
    elif retail_negative_passes:
        label = "CONTRARY_OR_MIXED_PROXY"
        interpretation = (
            "At least one corrected retail test is significant in the opposite direction; "
            "the winner-side attention proxy is not supported as stated."
        )
    else:
        label = "NULL_AFTER_MULTIPLE_TESTING"
        interpretation = (
            "No positive winner-side attention test survives Holm correction. "
            "Raw p-values, if any, should be treated as exploratory only."
        )

    return {
        "verdict": label,
        "interpretation": interpretation,
        "retail_positive_holm_passes": len(retail_passes),
        "control_positive_holm_passes": len(control_passes),
        "did_positive_holm_passes": len(did_passes),
        "retail_negative_holm_passes": len(retail_negative_passes),
        "control_negative_holm_passes": len(control_negative_passes),
        "primary_pass_tests": [
            {
                "scope": rec.get("test_type"),
                "group_or_contrast": rec.get("group", rec.get("contrast")),
                "window": rec["window"],
                "outcome": rec["outcome"],
                "effect": rec.get("mean_winner_minus_loser", rec.get("did_retail_minus_control")),
                "p_value_holm": rec.get("p_value_holm"),
            }
            for rec in (retail_passes + did_passes)
        ],
    }


def make_figure(within: list[dict], did: list[dict]) -> None:
    all_day = [rec for rec in within if rec["window"] == "all_next_sessions"]
    outcomes = list(OUTCOMES.keys())
    x = np.arange(len(outcomes))
    width = 0.35

    retail_effects = []
    control_effects = []
    retail_stars = []
    control_stars = []
    did_effects = []
    did_stars = []

    for outcome in outcomes:
        retail = next(
            rec for rec in all_day if rec["group"] == "retail_meme_risk" and rec["outcome"] == outcome
        )
        control = next(
            rec for rec in all_day if rec["group"] == "large_cap_control" and rec["outcome"] == outcome
        )
        did_rec = next(
            rec
            for rec in did
            if rec["window"] == "all_next_sessions" and rec["outcome"] == outcome
        )
        retail_effects.append(retail["mean_winner_minus_loser"] or 0.0)
        control_effects.append(control["mean_winner_minus_loser"] or 0.0)
        did_effects.append(did_rec["did_retail_minus_control"] or 0.0)
        retail_stars.append("*" if retail.get("holm_reject_5pct") else "")
        control_stars.append("*" if control.get("holm_reject_5pct") else "")
        did_stars.append("*" if did_rec.get("holm_reject_5pct") else "")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=150)
    ax = axes[0]
    ax.axhline(0, color="#666666", linewidth=0.8)
    bars1 = ax.bar(x - width / 2, retail_effects, width, label="Retail/meme-risk", color="#2C7FB8")
    bars2 = ax.bar(x + width / 2, control_effects, width, label="Large-cap control", color="#F28E2B")
    ax.set_xticks(x)
    ax.set_xticklabels(["Volume", "Range", "Gap", "RV"], rotation=0)
    ax.set_ylabel("Winner minus loser, ticker-mean z-score")
    ax.set_title("All next sessions")
    ax.legend(frameon=False)
    for bars, stars in [(bars1, retail_stars), (bars2, control_stars)]:
        for bar, star in zip(bars, stars):
            if not star:
                continue
            y = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                y + 0.03 * np.sign(y if y else 1),
                star,
                ha="center",
                va="bottom" if y >= 0 else "top",
                fontsize=14,
            )

    ax = axes[1]
    ax.axhline(0, color="#666666", linewidth=0.8)
    bars = ax.bar(x, did_effects, 0.55, color="#59A14F")
    ax.set_xticks(x)
    ax.set_xticklabels(["Volume", "Range", "Gap", "RV"], rotation=0)
    ax.set_ylabel("Retail minus control asymmetry")
    ax.set_title("Difference in differences")
    for bar, star in zip(bars, did_stars):
        if not star:
            continue
        y = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            y + 0.03 * np.sign(y if y else 1),
            star,
            ha="center",
            va="bottom" if y >= 0 else "top",
            fontsize=14,
        )

    fig.suptitle("Attention-utility winner focus proxy diagnostic (Holm * at 5%)")
    fig.tight_layout()
    fig.savefig(FIG_PATH, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    rng = np.random.default_rng(SEED)
    tickers = [ticker for basket in BASKETS.values() for ticker in basket]
    data = download_panel(tickers)

    frames: list[pd.DataFrame] = []
    missing_by_group: dict[str, list[str]] = {}
    for group, group_tickers in BASKETS.items():
        missing_by_group[group] = []
        for ticker in group_tickers:
            if ticker not in data:
                missing_by_group[group].append(ticker)
                continue
            frames.append(build_features(ticker, group, data[ticker]))

    if not frames:
        raise RuntimeError("No usable ticker data returned from yfinance.")

    panel = pd.concat(frames, axis=0).sort_index()
    panel = panel.dropna(subset=list(OUTCOMES.keys()), how="all")

    within_records: list[dict] = []
    for window in WINDOWS:
        for group in BASKETS:
            for outcome in OUTCOMES:
                within_records.append(within_group_test(panel, group, window, outcome, rng))

    did_records: list[dict] = []
    for window in WINDOWS:
        for outcome in OUTCOMES:
            did_records.append(did_test(panel, window, outcome, rng))

    all_family = within_records + did_records
    holm_adjust(all_family)

    verdict = verdict_from_tests(within_records, did_records)
    make_figure(within_records, did_records)

    sample_summary = summarize_sample(panel)
    result = {
        "experiment_id": EXPERIMENT_ID,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "data": {
            "source": "yfinance daily OHLCV",
            "download_call": "yf.download(..., auto_adjust=True, actions=False)",
            "start": DATA_START,
            "end_exclusive": DATA_END,
            "baskets": BASKETS,
            "missing_tickers": missing_by_group,
            "effective_date_range": {
                "start": str(panel.index.min().date()),
                "end": str(panel.index.max().date()),
            },
            "n_panel_rows_after_feature_build": int(len(panel)),
        },
        "literature": [
            {
                "title": "Attention Utility: Evidence from Individual Investors",
                "venue": "Review of Economic Studies, 2026",
                "url": "https://academic.oup.com/restud/article/93/1/664/8149267",
                "use_in_design": "Winner-side selective attention motivation; not directly replicated.",
            },
            {
                "title": "All that Glitters: The Effect of Attention and News on the Buying Behavior of Individual and Institutional Investors",
                "venue": "Review of Financial Studies, 2008",
                "url": "https://academic.oup.com/rfs/article-abstract/21/2/785/1607197",
                "use_in_design": "Abnormal trading volume and extreme returns as attention-grabbing stock proxies.",
            },
            {
                "title": "In Search of Attention",
                "venue": "Journal of Finance, 2011",
                "url": "https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2011.01679.x",
                "use_in_design": "Google SVI motivation; unavailable here, so OHLCV proxy is labelled as indirect.",
            },
        ],
        "methodology": {
            "unit": "ticker-day panel",
            "event_label": {
                "winner": "ret21_lag >= rolling252 q80 OR prior close within 2% of prior 63d high",
                "loser": "ret21_lag <= rolling252 q20 OR prior close within 2% of prior 63d low",
                "conflicts": "dropped from both sides",
            },
            "outcomes": {
                "abn_volume_z": "log(volume)_t standardized by lagged 252d mean/std through t-1",
                "range_vol_z": "(log(high_t/low_t)*100)^2 standardized by lagged 252d mean/std through t-1",
                "gap_abs_z": "|log(open_t/close_{t-1})*100| standardized by lagged 252d mean/std through t-1",
                "rv_z": "(log(close_t/close_{t-1})*100)^2 standardized by lagged 252d mean/std through t-1",
            },
            "windows": {window.name: window.description for window in WINDOWS},
            "test": (
                "Ticker-level winner-minus-loser mean differences; one-sample t across "
                "tickers within each basket; Welch t for retail-minus-control DiD."
            ),
            "multiple_testing": (
                "Holm adjustment across all within-group and DiD tests "
                f"({len(all_family)} total tests)."
            ),
            "bootstrap": f"{BOOT_REPS} resamples across ticker-level effects, seed={SEED}.",
        },
        "lookahead_controls": {
            "winner_loser_labels": (
                "ret21_lag uses close.pct_change(21).shift(1); prior high/low uses "
                "close.shift(1).rolling(...). Event labels at date t never use close_t."
            ),
            "outcome_standardization": (
                "Every outcome z-score uses series.shift(1).rolling(...) for mean/std, "
                "so t's outcome is not included in its own benchmark."
            ),
            "no_training_split": (
                "This is an event-study diagnostic, not an OOS forecast. There is no "
                "model selection on the test window; all thresholds are fixed ex ante."
            ),
        },
        "sample_summary": sample_summary,
        "tests": {
            "within_group": within_records,
            "difference_in_differences": did_records,
        },
        "primary_summary": verdict,
        "limitations": [
            "No brokerage-login, Google Trends, Reddit, or Stocktwits attention data were used.",
            "Earnings-window attention is not tested; reliable point-in-time earnings dates were outside the free-data scope.",
            "Daily OHLCV cannot separate market-close attention from intraday order flow.",
            "Ticker-level t-tests reduce but do not eliminate common-date cross-sectional dependence.",
            "This is a proxy mechanism screen and should not be treated as causal identification.",
        ],
        "figure": str(FIG_PATH.name),
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=json_safe)

    print(json.dumps(verdict, indent=2, ensure_ascii=False, default=json_safe))
    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {FIG_PATH}")


if __name__ == "__main__":
    main()
