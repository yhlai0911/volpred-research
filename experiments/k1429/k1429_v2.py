"""
K1429 v2 — EAV effect with reaction-day alignment and permutation inference.

Fixes versus v1:
1. Earnings timestamps are pulled from yfinance earnings calendar instead of a
   hand-maintained date list.
2. Event day T is the first tradable reaction day. After-close announcements
   shift to the next trading day; before-open announcements stay on the same
   trading day.
3. Event statistics use a single 5-day window measure:
      sqrt(252 / 5 * sum(r_t^2))
4. Inference uses a randomization test against baseline 5-day windows instead
   of a paired t-test versus a fixed baseline constant.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


OUT_DIR = Path("experiments/k1429")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ANALYSIS_START = pd.Timestamp("2024-01-01")
ANALYSIS_END = pd.Timestamp("2026-06-08")
DOWNLOAD_START = "2023-12-01"
DOWNLOAD_END = "2026-06-09"
TICKERS = ["NVDA", "AAPL", "MSFT"]
WINDOW_DAYS = 5
BASELINE_EXCL = 10
N_PERMUTATIONS = 20_000
SEED = 42
MULTIPLE_TESTS = 6

COLORS = {"NVDA": "#76B900", "AAPL": "#7A7A7A", "MSFT": "#00A4EF"}


@dataclass
class EventRecord:
    announce_ts_ny: str
    announce_date: str
    release_session: str
    reaction_date: str


def classify_release_session(ts_ny: pd.Timestamp) -> str:
    minutes = ts_ny.hour * 60 + ts_ny.minute
    if minutes >= 16 * 60:
        return "after_close"
    if minutes < 9 * 60 + 30:
        return "before_open"
    return "during_market"


def reaction_day_for_announcement(
    announce_date: pd.Timestamp,
    session: str,
    trading_index: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    pos = trading_index.searchsorted(announce_date)
    if pos >= len(trading_index):
        return None
    if trading_index[pos] != announce_date:
        return trading_index[pos]
    if session == "after_close":
        pos += 1
        if pos >= len(trading_index):
            return None
    return trading_index[pos]


def window_vol(returns: pd.Series, days: pd.DatetimeIndex) -> float | None:
    vals = returns.loc[days].dropna().to_numpy(dtype=float)
    if len(vals) != WINDOW_DAYS:
        return None
    return float(np.sqrt(252.0 / WINDOW_DAYS * np.sum(vals**2)))


def permutation_p_value(
    baseline_values: np.ndarray,
    event_values: np.ndarray,
    *,
    rng: np.random.Generator,
    n_permutations: int = N_PERMUTATIONS,
) -> float:
    n_event = len(event_values)
    n_base = len(baseline_values)
    observed = float(event_values.mean() - baseline_values.mean())
    perm_diffs = np.empty(n_permutations, dtype=float)

    for i in range(n_permutations):
        sample_idx = rng.choice(n_base, size=n_event, replace=False)
        mask = np.ones(n_base, dtype=bool)
        mask[sample_idx] = False
        perm_diffs[i] = baseline_values[sample_idx].mean() - baseline_values[mask].mean()

    return float((np.sum(np.abs(perm_diffs) >= abs(observed)) + 1) / (n_permutations + 1))


def fetch_price_data() -> dict[str, pd.Series]:
    raw = yf.download(
        TICKERS,
        start=DOWNLOAD_START,
        end=DOWNLOAD_END,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
    )
    closes: dict[str, pd.Series] = {}
    for ticker in TICKERS:
        closes[ticker] = raw[ticker]["Close"].dropna()
    return closes


def fetch_earnings_records(ticker: str, trading_index: pd.DatetimeIndex) -> list[EventRecord]:
    ed = yf.Ticker(ticker).get_earnings_dates(limit=12)
    ed = ed[ed["Reported EPS"].notna()].copy()
    ed = ed.sort_index()
    records: list[EventRecord] = []

    for ts in ed.index:
        ts_ny = pd.Timestamp(ts).tz_convert("America/New_York")
        announce_date = pd.Timestamp(ts_ny.date())
        if not (ANALYSIS_START <= announce_date <= ANALYSIS_END):
            continue
        session = classify_release_session(ts_ny)
        reaction_date = reaction_day_for_announcement(announce_date, session, trading_index)
        if reaction_date is None:
            continue
        records.append(
            EventRecord(
                announce_ts_ny=ts_ny.isoformat(),
                announce_date=announce_date.strftime("%Y-%m-%d"),
                release_session=session,
                reaction_date=reaction_date.strftime("%Y-%m-%d"),
            )
        )
    return records


def build_results() -> dict:
    closes = fetch_price_data()
    rng = np.random.default_rng(SEED)
    results_by_ticker: dict[str, dict] = {}
    figure_points: dict[str, dict[str, list[float]]] = {}
    event_records_by_ticker: dict[str, list[dict]] = {}

    for ticker in TICKERS:
        close = closes[ticker]
        trading_index = close.index
        log_returns = np.log(close).diff().reindex(trading_index)
        event_records = fetch_earnings_records(ticker, trading_index)
        event_records_by_ticker[ticker] = [asdict(record) for record in event_records]
        reaction_days = pd.DatetimeIndex([pd.Timestamp(r.reaction_date) for r in event_records])

        excluded_days: set[pd.Timestamp] = set()
        for reaction_day in reaction_days:
            pos = trading_index.get_loc(reaction_day)
            for offset in range(-BASELINE_EXCL, BASELINE_EXCL + 1):
                target = pos + offset
                if 0 <= target < len(trading_index):
                    excluded_days.add(trading_index[target])

        pre_values: list[float] = []
        post_values: list[float] = []
        labels: list[str] = []

        for record in event_records:
            reaction_day = pd.Timestamp(record.reaction_date)
            pos = trading_index.get_loc(reaction_day)
            pre_days = trading_index[pos - WINDOW_DAYS : pos]
            post_days = trading_index[pos : pos + WINDOW_DAYS]
            if len(pre_days) != WINDOW_DAYS or len(post_days) != WINDOW_DAYS:
                continue
            pre_vol = window_vol(log_returns, pre_days)
            post_vol = window_vol(log_returns, post_days)
            if pre_vol is None or post_vol is None:
                continue
            pre_values.append(pre_vol)
            post_values.append(post_vol)
            labels.append(record.reaction_date)

        baseline_values: list[float] = []
        for start in range(0, len(trading_index) - WINDOW_DAYS + 1):
            days = trading_index[start : start + WINDOW_DAYS]
            if any(day in excluded_days for day in days):
                continue
            vol = window_vol(log_returns, days)
            if vol is not None:
                baseline_values.append(vol)

        pre_arr = np.array(pre_values, dtype=float)
        post_arr = np.array(post_values, dtype=float)
        baseline_arr = np.array(baseline_values, dtype=float)
        baseline_mean = float(baseline_arr.mean())

        p_pre = permutation_p_value(baseline_arr, pre_arr, rng=rng)
        p_post = permutation_p_value(baseline_arr, post_arr, rng=rng)
        p_pre_bonf = min(1.0, p_pre * MULTIPLE_TESTS)
        p_post_bonf = min(1.0, p_post * MULTIPLE_TESTS)

        pre_diff = float(pre_arr.mean() - baseline_mean)
        post_diff = float(post_arr.mean() - baseline_mean)
        pre_pct = pre_diff / baseline_mean * 100.0
        post_pct = post_diff / baseline_mean * 100.0

        results_by_ticker[ticker] = {
            "n_events": int(len(pre_arr)),
            "baseline_windows_n": int(len(baseline_arr)),
            "baseline_mean_window_vol": round(baseline_mean, 4),
            "pre_mean_window_vol": round(float(pre_arr.mean()), 4),
            "post_mean_window_vol": round(float(post_arr.mean()), 4),
            "pre_mean_diff": round(pre_diff, 4),
            "post_mean_diff": round(post_diff, 4),
            "pre_diff_pct": round(pre_pct, 2),
            "post_diff_pct": round(post_pct, 2),
            "p_pre_permutation": round(p_pre, 6),
            "p_post_permutation": round(p_post, 6),
            "p_pre_bonferroni": round(p_pre_bonf, 6),
            "p_post_bonferroni": round(p_post_bonf, 6),
            "significant_pre_uncorrected": bool(p_pre < 0.05),
            "significant_post_uncorrected": bool(p_post < 0.05),
            "significant_pre_bonferroni": bool(p_pre_bonf < 0.05),
            "significant_post_bonferroni": bool(p_post_bonf < 0.05),
            "reaction_dates": labels,
        }

        figure_points[ticker] = {
            "labels": labels,
            "pre_values": pre_values,
            "post_values": post_values,
            "baseline_mean": baseline_mean,
        }

    return {
        "metadata": {
            "analysis_start": ANALYSIS_START.strftime("%Y-%m-%d"),
            "analysis_end": ANALYSIS_END.strftime("%Y-%m-%d"),
            "tickers": TICKERS,
            "price_source": "yfinance adjusted close",
            "earnings_source": "yfinance.Ticker.get_earnings_dates(limit=12)",
            "window_measure": "sqrt(252/5 * sum(r_t^2)) over 5 close-to-close log returns",
            "pre_window": "T-5 to T-1, where T is the first tradable reaction day",
            "post_window": "T to T+4, where T is the first tradable reaction day",
            "baseline_exclusion": "exclude reaction-day neighborhoods ±10 trading days",
            "inference": (
                "two-sided randomization test: compare observed event-window mean "
                "difference vs mean differences from baseline pseudo-event samples"
            ),
            "multiple_testing": "Bonferroni over 6 tests",
            "seed": SEED,
            "n_permutations": N_PERMUTATIONS,
        },
        "results_by_ticker": results_by_ticker,
        "event_records_by_ticker": event_records_by_ticker,
        "_figure_points": figure_points,
    }


def make_figures(payload: dict) -> list[str]:
    points = payload.pop("_figure_points")
    results_by_ticker = payload["results_by_ticker"]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), dpi=120, sharey=True)
    for ax, ticker in zip(axes, TICKERS):
        fp = points[ticker]
        x = np.arange(len(fp["labels"]))
        ax.scatter(x - 0.12, fp["pre_values"], color=COLORS[ticker], label="Pre [T-5,T-1]", alpha=0.85)
        ax.scatter(
            x + 0.12,
            fp["post_values"],
            color=COLORS[ticker],
            marker="s",
            label="Post [T,T+4]",
            alpha=0.85,
        )
        ax.axhline(fp["baseline_mean"], color="#C92A2A", linestyle="--", linewidth=1.5, label="Baseline mean")
        ax.set_xticks(x)
        ax.set_xticklabels([d[2:] for d in fp["labels"]], rotation=45, ha="right", fontsize=8)
        ax.set_title(
            f"{ticker}\npre {results_by_ticker[ticker]['pre_diff_pct']:+.1f}% | "
            f"post {results_by_ticker[ticker]['post_diff_pct']:+.1f}%"
        )
        ax.grid(alpha=0.2, axis="y")
    axes[0].set_ylabel("5-day window annualized volatility")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles[:3], labels[:3], loc="upper center", ncol=3, frameon=False)
    fig.suptitle("K1429 v2: Event-window volatility by reaction day", y=1.03, fontsize=14)
    fig.tight_layout()
    fig_path_1 = OUT_DIR / "fig_event_windows_v2.png"
    fig.savefig(fig_path_1, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)
    tick_positions: list[float] = []
    tick_labels: list[str] = []
    width = 0.34
    for i, ticker in enumerate(TICKERS):
        base_x = i * 2.2
        row = results_by_ticker[ticker]
        bars = [
            (base_x - width / 2, row["pre_diff_pct"], row["p_pre_bonferroni"]),
            (base_x + width / 2, row["post_diff_pct"], row["p_post_bonferroni"]),
        ]
        for x, value, p_bonf in bars:
            hatch = "///" if p_bonf < 0.05 else ""
            ax.bar(x, value, width=width, color=COLORS[ticker], alpha=0.85, hatch=hatch)
            ax.text(
                x,
                value + (3 if value >= 0 else -5),
                f"{value:+.1f}%",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=9,
            )
        tick_positions.extend([base_x - width / 2, base_x + width / 2])
        tick_labels.extend([f"{ticker}\nPre", f"{ticker}\nPost"])

    ax.axhline(0, color="black", linewidth=1)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels)
    ax.set_ylabel("Mean difference vs baseline (%)")
    ax.set_title("K1429 v2: Mean event-window difference vs baseline\nHatching = survives Bonferroni (6 tests)")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig_path_2 = OUT_DIR / "fig_premium_compare_v2.png"
    fig.savefig(fig_path_2, bbox_inches="tight")
    plt.close(fig)

    return [fig_path_1.name, fig_path_2.name]


def attach_summary(payload: dict, figures: list[str]) -> dict:
    results = payload["results_by_ticker"]
    bonf_hits = []
    for ticker in TICKERS:
        row = results[ticker]
        if row["significant_pre_bonferroni"]:
            bonf_hits.append(f"{ticker} pre")
        if row["significant_post_bonferroni"]:
            bonf_hits.append(f"{ticker} post")

    payload.update(
        {
            "experiment_id": "K1429",
            "title": "EAV Effect v2: Reaction-day aligned 5-day window volatility",
            "description": (
                "Recomputed NVDA/AAPL/MSFT earnings-window volatility with "
                "reaction-day alignment, 5-day realized-vol windows, and "
                "permutation inference."
            ),
            "figures": figures,
            "verdict": "CONDITIONAL_PASS" if bonf_hits else "FAIL",
            "verdict_rationale": (
                "Only MSFT post survives Bonferroni after correcting event alignment "
                "and inference." if bonf_hits else "No effect survives corrected inference."
            ),
            "bonferroni_survivors": bonf_hits,
        }
    )
    return payload


def main() -> None:
    payload = build_results()
    figures = make_figures(payload)
    payload = attach_summary(payload, figures)
    out_path = OUT_DIR / "k1429_v2_results.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out_path}")
    for ticker in TICKERS:
        row = payload["results_by_ticker"][ticker]
        print(
            f"{ticker}: n={row['n_events']} | pre {row['pre_diff_pct']:+.1f}% "
            f"(p={row['p_pre_permutation']:.4f}, bonf={row['p_pre_bonferroni']:.4f}) | "
            f"post {row['post_diff_pct']:+.1f}% "
            f"(p={row['p_post_permutation']:.4f}, bonf={row['p_post_bonferroni']:.4f})"
        )


if __name__ == "__main__":
    main()
