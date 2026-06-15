"""K1341: Index Reconstitution Day Volatility Event Study.

Tests whether Russell (annual June) and S&P 500 (quarterly) index
reconstitution days exhibit intraday-range volatility dislocation that
mean-reverts on day t+1.

Lookahead policy
----------------
- Event dates are publicly known calendar events (no signal-shift needed).
- Baseline = same-calendar-month mean EXCLUDING the [t_e-5, t_e+5] event
  window for that event — ensures the baseline does not absorb the event.
- All vol measures use only same-day OHLC (no forward-looking smoothing).
- Bootstrap uses np.random.default_rng(seed=42).

Author: VolPred Research Platform
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
EVENT_HALF_WINDOW = 5  # +-5 trading days around event
BOOTSTRAP_B = 1000
BOOTSTRAP_BLOCK = 5
TICKERS = ["IWM", "IWB", "SPY", "QQQ"]
START = "2014-01-01"
END = "2026-06-14"

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ----------------------------------------------------------------------
# Event date calendars
# ----------------------------------------------------------------------
def last_friday_of_june(year: int) -> date:
    """Russell reconstitution: last Friday of June."""
    d = date(year, 6, 30)
    while d.weekday() != 4:  # 4 = Friday
        d -= timedelta(days=1)
    return d


def third_friday(year: int, month: int) -> date:
    """S&P quarterly rebalance: third Friday of Mar/Jun/Sep/Dec."""
    d = date(year, month, 1)
    fridays = 0
    while True:
        if d.weekday() == 4:
            fridays += 1
            if fridays == 3:
                return d
        d += timedelta(days=1)


def russell_recon_dates(start_year: int = 2014, end_year: int = 2025) -> list[pd.Timestamp]:
    return [pd.Timestamp(last_friday_of_june(y)) for y in range(start_year, end_year + 1)]


def sp_quarterly_dates(
    start_year: int = 2014, end_year: int = 2026
) -> list[pd.Timestamp]:
    out = []
    for y in range(start_year, end_year + 1):
        for m in (3, 6, 9, 12):
            d = third_friday(y, m)
            if d <= date(2026, 6, 14):
                out.append(pd.Timestamp(d))
    return out


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
def fetch_ohlc(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=START,
        end=END,
        progress=False,
        auto_adjust=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


# ----------------------------------------------------------------------
# Vol measures (all same-day, no lookahead)
# ----------------------------------------------------------------------
def add_vol_measures(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # Same-day log return (uses today's close and yesterday's close).
    out["r_cc"] = np.log(out["Close"] / out["Close"].shift(1))
    out["r2_cc"] = out["r_cc"] ** 2
    # Parkinson intraday range estimator from same-day H and L.
    # 0.361 = 1 / (4 * ln 2). Use ln(H/L)^2.
    out["parkinson"] = 0.361 * (np.log(out["High"] / out["Low"]) ** 2)
    # Close-to-open squared (overnight gap, secondary).
    out["r_co"] = np.log(out["Close"] / out["Open"])
    out["r2_co"] = out["r_co"] ** 2
    return out


# ----------------------------------------------------------------------
# Event window extraction
# ----------------------------------------------------------------------
def align_event_to_index(
    event_date: pd.Timestamp, idx: pd.DatetimeIndex, max_gap_days: int = 3
) -> int | None:
    """Return integer position of event_date in idx.

    If event_date is a trading day, return its exact position.
    If event_date is a holiday, snap FORWARD to the next trading day ONLY IF
    that next trading day is within `max_gap_days` calendar days; otherwise
    return None (no safe alignment). Holiday Fridays should map to Monday
    (3 cal days) so default 3 is correct; longer gaps signal a data problem.
    """
    pos = idx.searchsorted(event_date)
    if pos >= len(idx):
        return None
    actual = idx[pos]
    gap_days = (actual - event_date).days
    if gap_days > max_gap_days:
        return None
    return int(pos)


def extract_event_windows(
    df: pd.DataFrame, event_dates: list[pd.Timestamp], measure: str
) -> tuple[np.ndarray, list[pd.Timestamp], list[int]]:
    """Return (n_events x window_len) array, matched event timestamps, and
    the integer positions of each matched event in df.index."""
    series = df[measure]
    idx = df.index
    rows = []
    matched_dates = []
    matched_positions: list[int] = []
    window_len = 2 * EVENT_HALF_WINDOW + 1
    for ed in event_dates:
        pos = align_event_to_index(ed, idx)
        if pos is None:
            continue
        lo = pos - EVENT_HALF_WINDOW
        hi = pos + EVENT_HALF_WINDOW + 1
        if lo < 0 or hi > len(idx):
            continue
        window = series.iloc[lo:hi].values
        if np.any(np.isnan(window)):
            continue
        rows.append(window)
        matched_dates.append(idx[pos])
        matched_positions.append(pos)
    if not rows:
        return np.empty((0, window_len)), [], []
    return np.vstack(rows), matched_dates, matched_positions


def same_month_baseline_values(
    df: pd.DataFrame, event_pos: int, measure: str
) -> pd.Series:
    """Return the per-day baseline series for the same calendar month as the
    event-positioned row, EXCLUDING the exact trading-day window
    [event_pos - EVENT_HALF_WINDOW, event_pos + EVENT_HALF_WINDOW]
    (uses trading-day positional indexing — not calendar-day buffer — so
    holiday weeks are handled correctly).

    If the same-month sample after exclusion is empty, fall back to a
    +/-30 trading-day neighbourhood (still positionally excluded).
    """
    series = df[measure].dropna()
    event_ts = df.index[event_pos]
    same_month = series[
        (series.index.year == event_ts.year)
        & (series.index.month == event_ts.month)
    ]
    # Build the set of excluded timestamps from the trading-day window.
    excl_lo = max(0, event_pos - EVENT_HALF_WINDOW)
    excl_hi = min(len(df.index), event_pos + EVENT_HALF_WINDOW + 1)
    excluded = set(df.index[excl_lo:excl_hi])
    base = same_month[~same_month.index.isin(excluded)]
    if len(base) == 0:
        lo_pos = max(0, event_pos - 30)
        hi_pos = min(len(series), event_pos + 30)
        nearby = series.iloc[lo_pos:hi_pos]
        base = nearby[~nearby.index.isin(excluded)]
    return base


def same_month_baseline_mean(
    df: pd.DataFrame, event_pos: int, measure: str
) -> float:
    base = same_month_baseline_values(df, event_pos, measure)
    return float(base.mean()) if len(base) else float("nan")


def same_month_baseline_std(
    df: pd.DataFrame, event_pos: int, measure: str
) -> float:
    base = same_month_baseline_values(df, event_pos, measure)
    return float(base.std(ddof=1)) if len(base) > 1 else float("nan")


# ----------------------------------------------------------------------
# Statistical tests
# ----------------------------------------------------------------------
def wilcoxon_paired(diffs: np.ndarray) -> tuple[float, float]:
    diffs = diffs[~np.isnan(diffs)]
    if len(diffs) < 3:
        return float("nan"), float("nan")
    nonzero = diffs[diffs != 0]
    if len(nonzero) < 3:
        return float("nan"), float("nan")
    try:
        stat, p = stats.wilcoxon(nonzero, alternative="greater")
        return float(stat), float(p)
    except Exception:
        return float("nan"), float("nan")


def block_bootstrap_pvalue(
    diffs: np.ndarray,
    block: int = BOOTSTRAP_BLOCK,
    B: int = BOOTSTRAP_B,
    seed: int = SEED,
) -> float:
    """Block bootstrap one-sided p-value: H0 mean(diff) <= 0 vs H1 > 0."""
    diffs = diffs[~np.isnan(diffs)]
    n = len(diffs)
    if n < block * 2:
        return float("nan")
    rng = np.random.default_rng(seed)
    observed = float(np.mean(diffs))
    # Centre under H0 (subtract mean -> null distribution).
    centred = diffs - observed
    n_blocks = math.ceil(n / block)
    boot_means = np.empty(B)
    for b in range(B):
        # Sample n_blocks starting positions with replacement.
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([centred[s : s + block] for s in starts])[:n]
        boot_means[b] = sample.mean()
    # Use (count + 1) / (B + 1) to avoid zero p-values (Davison & Hinkley).
    p = float((np.sum(boot_means >= observed) + 1) / (B + 1))
    return p


# ----------------------------------------------------------------------
# Main per-ticker-per-event-set analysis
# ----------------------------------------------------------------------
MEASURES = ["r2_cc", "parkinson", "r2_co"]


def analyse(
    ticker: str,
    df: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    event_label: str,
) -> dict:
    out = {"ticker": ticker, "event_set": event_label, "measures": {}}
    rows_by_measure: dict[str, np.ndarray] = {}
    for measure in MEASURES:
        windows, matched_dates, matched_positions = extract_event_windows(
            df, event_dates, measure
        )
        if len(windows) == 0:
            out["measures"][measure] = {"n_events": 0}
            continue
        rows_by_measure[measure] = windows
        # Event-day value (centre column) for each event.
        centre_col = EVENT_HALF_WINDOW
        event_vals = windows[:, centre_col]
        t_plus_1 = windows[:, centre_col + 1]
        # Per-event baselines: mean and within-month std EXCLUDING the
        # exact trading-day event window (positional, holiday-safe).
        baselines = np.array(
            [same_month_baseline_mean(df, pos, measure) for pos in matched_positions]
        )
        baseline_stds = np.array(
            [same_month_baseline_std(df, pos, measure) for pos in matched_positions]
        )
        diffs = event_vals - baselines
        # Mean-reversion t+1 z-score: per-event (t+1 minus per-event
        # baseline mean) divided by per-event baseline std, then averaged.
        with np.errstate(divide="ignore", invalid="ignore"):
            per_event_z = (t_plus_1 - baselines) / baseline_stds
        t_plus_1_z = float(np.nanmean(per_event_z))
        # Stats.
        stat_w, p_w = wilcoxon_paired(diffs)
        p_boot = block_bootstrap_pvalue(diffs)
        out["measures"][measure] = {
            "n_events": int(len(event_vals)),
            "event_mean": float(np.nanmean(event_vals)),
            "baseline_mean": float(np.nanmean(baselines)),
            "diff_mean": float(np.nanmean(diffs)),
            "wilcoxon_stat": stat_w,
            "wilcoxon_p_one_sided_greater": p_w,
            "block_bootstrap_p_one_sided_greater": p_boot,
            "t_plus_1_z_score": t_plus_1_z,
        }
    return out, rows_by_measure


# ----------------------------------------------------------------------
# Plots
# ----------------------------------------------------------------------
def plot_event_window(
    results_by_ticker: dict[str, dict[str, np.ndarray]],
    measure: str,
    title: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = np.arange(-EVENT_HALF_WINDOW, EVENT_HALF_WINDOW + 1)
    for ticker, by_measure in results_by_ticker.items():
        windows = by_measure.get(measure)
        if windows is None or len(windows) == 0:
            continue
        mean_profile = np.nanmean(windows, axis=0)
        ax.plot(xs, mean_profile, marker="o", label=f"{ticker} (n={len(windows)})")
    ax.axvline(0, color="k", linestyle=":", linewidth=0.8)
    ax.set_xlabel("Trading days from event (t=0 is reconstitution day)")
    ax.set_ylabel(measure)
    ax.set_title(title)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main() -> None:
    np.random.seed(SEED)
    russell_dates = russell_recon_dates(2014, 2025)
    sp_dates = sp_quarterly_dates(2014, 2026)

    print(f"Russell reconstitution dates: {len(russell_dates)}")
    print(f"S&P quarterly rebalance dates: {len(sp_dates)}")

    data: dict[str, pd.DataFrame] = {}
    for t in TICKERS:
        print(f"Downloading {t}...")
        df = fetch_ohlc(t)
        df = add_vol_measures(df)
        data[t] = df
        print(f"  {t}: {len(df)} rows {df.index.min().date()} -> {df.index.max().date()}")

    results: list[dict] = []
    plot_rows_russell: dict[str, dict[str, np.ndarray]] = {}
    plot_rows_sp: dict[str, dict[str, np.ndarray]] = {}

    # Russell event set: applied to IWM, IWB (primary) + QQQ (control).
    for ticker in ["IWM", "IWB", "QQQ"]:
        res, rows = analyse(ticker, data[ticker], russell_dates, "russell_recon_jun_last_fri")
        results.append(res)
        plot_rows_russell[ticker] = rows

    # S&P quarterly event set: applied to SPY (primary) + QQQ (control).
    for ticker in ["SPY", "QQQ"]:
        res, rows = analyse(ticker, data[ticker], sp_dates, "sp500_quarterly_third_fri")
        results.append(res)
        plot_rows_sp[ticker] = rows

    # Figures.
    plot_event_window(
        plot_rows_russell,
        "parkinson",
        "Parkinson intraday-range vol around Russell reconstitution day (last Fri of June)",
        FIG_DIR / "event_window_parkinson_russell.png",
    )
    plot_event_window(
        plot_rows_russell,
        "r2_cc",
        "Close-to-close r^2 around Russell reconstitution day",
        FIG_DIR / "event_window_r2cc_russell.png",
    )
    plot_event_window(
        plot_rows_sp,
        "parkinson",
        "Parkinson intraday-range vol around S&P 500 quarterly rebalance",
        FIG_DIR / "event_window_parkinson_sp.png",
    )

    summary = {
        "k_id": "K1341",
        "run_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "seed": SEED,
        "window_half_width": EVENT_HALF_WINDOW,
        "bootstrap_B": BOOTSTRAP_B,
        "bootstrap_block": BOOTSTRAP_BLOCK,
        "tickers": TICKERS,
        "period": {"start": START, "end": END},
        "event_sets": {
            "russell_recon_jun_last_fri": [d.strftime("%Y-%m-%d") for d in russell_dates],
            "sp500_quarterly_third_fri": [d.strftime("%Y-%m-%d") for d in sp_dates],
        },
        "lookahead_policy": (
            "Event dates are publicly known. Baselines exclude [t_e-5, t_e+5] "
            "to prevent event leakage. All vol measures use only same-day OHLC."
        ),
        "results": results,
    }
    out_path = OUT_DIR / "K1341_results.json"
    with out_path.open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Wrote {out_path}")

    # Brief verdict print.
    print("\n=== SUMMARY ===")
    for r in results:
        ticker = r["ticker"]
        evset = r["event_set"]
        for measure, m in r["measures"].items():
            if "n_events" not in m or m.get("n_events", 0) == 0:
                continue
            print(
                f"{ticker:>4} {evset[:20]:>20} {measure:>10} "
                f"n={m['n_events']:>2} "
                f"event={m['event_mean']:.6e} base={m['baseline_mean']:.6e} "
                f"p_wilcox={m['wilcoxon_p_one_sided_greater']:.4f} "
                f"p_boot={m['block_bootstrap_p_one_sided_greater']:.4f} "
                f"z(t+1)={m['t_plus_1_z_score']:.3f}"
            )


if __name__ == "__main__":
    main()
