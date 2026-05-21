"""K1373: 台股除權息日波動率事件研究.

Tests whether Taiwan stocks show systematic volatility changes around
dividend ex-dates. Motivated by research_program.md dividend research direction
and upcoming Taiwan dividend season (June 2026+).

Differentiation vs K498 (earnings volatility):
- K498 focuses on earnings announcements (quarterly)
- K1373 focuses on dividend ex-dates (annual, specific to Taiwan高股息文化)
- K1373 tests: does the market "build up" volatility before ex-date
  (uncertainty about fill-up), show elevated vol on ex-date, and revert post-ex-date?

Lookahead note:
  This is a descriptive event study using an EXTERNAL calendar (ex-dividend dates
  from yfinance .dividends). We measure contemporaneous |r| around known event dates.
  No forecasting model is built; no future data is used to classify past days.
  signal.shift(1) is NOT needed — we are studying the effect of a known calendar
  event on the same-day realized volatility measure.

Usage:
    uv run python experiments/k1373/k1373.py
"""

import json
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

np.random.seed(42)  # reproducibility (no bootstrap here, but standard practice)

ASSETS = ["0050.TW", "0056.TW", "2330.TW", "2317.TW", "2882.TW"]
START = "2015-01-01"
END = "2025-12-31"
EVENT_WINDOW = 10  # ±10 trading days around ex-date
OUTPUT_PATH = "experiments/k1373/k1373_results.json"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def download_prices(ticker: str, start: str, end: str) -> pd.Series:
    """Download adjusted close prices; return daily series."""
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No price data for {ticker}")
    close = hist["Close"].dropna()
    close.index = close.index.tz_localize(None).normalize()
    return close


def get_ex_dates(ticker: str, start: str, end: str) -> list[date]:
    """Return ex-dividend dates within [start, end] for ticker."""
    t = yf.Ticker(ticker)
    divs = t.dividends
    if divs.empty:
        return []
    # Normalize index timezone
    divs.index = divs.index.tz_localize(None).normalize() if divs.index.tzinfo else divs.index.normalize()
    mask = (divs.index >= pd.Timestamp(start)) & (divs.index <= pd.Timestamp(end))
    return [d.date() for d in divs.index[mask]]


def compute_absr(prices: pd.Series) -> pd.Series:
    """Absolute log returns: |log(P_t / P_{t-1})|."""
    log_ret = np.log(prices / prices.shift(1))
    return log_ret.abs().dropna()


# ---------------------------------------------------------------------------
# Event study logic
# ---------------------------------------------------------------------------

def classify_days(absr: pd.Series, ex_dates: list[date], window: int):
    """
    For each trading day, classify as:
      - 'ex'     : t=0 (ex-date itself, if trading day)
      - 'pre'    : within [-window, -1] of an ex-date
      - 'post'   : within [+1, +window] of an ex-date
      - 'control': ≥ window+1 days away from ANY ex-date

    Returns a dict with:
      pre_vals, ex_vals, post_vals, control_vals  — lists of |r| values
      pre_dates, ex_dates_found, post_dates, control_dates — corresponding dates
    """
    trading_days = list(absr.index.date)
    td_set = set(trading_days)
    td_idx = {d: i for i, d in enumerate(trading_days)}

    # For each ex-date, find nearest trading day (could be weekend → next day)
    ex_trading = []
    for ex in ex_dates:
        ex_ts = pd.Timestamp(ex)
        # Find first trading day on or after the ex-date
        candidates = [d for d in trading_days if d >= ex]
        if candidates:
            ex_trading.append(candidates[0])

    # Mark event zones: for each trading day, what is its minimum distance to any ex-trading day
    n = len(trading_days)
    min_dist = {d: float("inf") for d in trading_days}
    event_day_map = {d: None for d in trading_days}  # nearest ex-date

    # Count how many ex-dates each day falls within window of (for overlap detection)
    in_window_count = {d: 0 for d in trading_days}

    for ex_td in ex_trading:
        if ex_td not in td_idx:
            continue
        i_ex = td_idx[ex_td]
        for offset in range(-window, window + 1):
            j = i_ex + offset
            if 0 <= j < n:
                d = trading_days[j]
                in_window_count[d] += 1
                if abs(offset) < abs(min_dist.get(d, float("inf"))):
                    min_dist[d] = offset
                    event_day_map[d] = ex_td
                # Tied-distance: day is equidistant from two ex-dates.
                # Leave min_dist[d] as-is (first-processed wins); overlap_days
                # below will exclude it from all groups.

    # Days within the event window of MORE than one ex-date are ambiguous:
    # exclude them from all groups to avoid classification errors.
    overlap_days = {d for d, c in in_window_count.items() if c > 1}

    pre_vals, ex_vals, post_vals, control_vals = [], [], [], []
    pre_dates, ex_dates_found, post_dates, control_dates = [], [], [], []

    for d in trading_days:
        if d not in absr.index.date:
            continue
        if d in overlap_days:
            continue  # ambiguous — within window of multiple ex-dates
        val = absr.loc[pd.Timestamp(d)]
        dist = min_dist[d]
        if dist == 0:
            ex_vals.append(val)
            ex_dates_found.append(d)
        elif -window <= dist < 0:
            pre_vals.append(val)
            pre_dates.append(d)
        elif 0 < dist <= window:
            post_vals.append(val)
            post_dates.append(d)
        else:
            control_vals.append(val)
            control_dates.append(d)

    return {
        "pre": np.array(pre_vals),
        "ex": np.array(ex_vals),
        "post": np.array(post_vals),
        "control": np.array(control_vals),
        "n_ex_dates": len(ex_trading),
        "ex_dates_found": len(ex_vals),
    }


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d: (mean_a - mean_b) / pooled_std."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return float("nan")
    pooled_var = ((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2)
    if pooled_var == 0:
        return float("nan")
    return float((np.mean(a) - np.mean(b)) / np.sqrt(pooled_var))


def run_tests(group_a: np.ndarray, group_b: np.ndarray, label_a="A", label_b="B") -> dict:
    """Run t-test and Mann-Whitney U between two groups."""
    if len(group_a) < 2 or len(group_b) < 2:
        return {
            "t_stat": None, "p_value": None,
            "mw_statistic": None, "mw_p_value": None,
            "n_a": len(group_a), "n_b": len(group_b),
            "note": "insufficient data"
        }
    t_stat, p_val = stats.ttest_ind(group_a, group_b, equal_var=False)
    mw_stat, mw_p = stats.mannwhitneyu(group_a, group_b, alternative="two-sided")
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "mw_statistic": float(mw_stat),
        "mw_p_value": float(mw_p),
        "n_a": int(len(group_a)),
        "n_b": int(len(group_b)),
    }


# ---------------------------------------------------------------------------
# Per-asset analysis
# ---------------------------------------------------------------------------

def analyze_asset(ticker: str) -> dict:
    print(f"\n  [{ticker}] Downloading prices...", flush=True)
    prices = download_prices(ticker, START, END)
    absr = compute_absr(prices)

    print(f"  [{ticker}] Getting ex-dates...", flush=True)
    ex_dates = get_ex_dates(ticker, START, END)
    print(f"  [{ticker}] Found {len(ex_dates)} ex-dates in period.", flush=True)

    classified = classify_days(absr, ex_dates, EVENT_WINDOW)
    pre = classified["pre"]
    ex = classified["ex"]
    post = classified["post"]
    ctrl = classified["control"]

    print(f"  [{ticker}] Ex obs={len(ex)}, Pre obs={len(pre)}, Post obs={len(post)}, Control obs={len(ctrl)}", flush=True)

    # t-tests and Mann-Whitney
    ex_vs_ctrl = run_tests(ex, ctrl)
    pre_vs_ctrl = run_tests(pre, ctrl)
    post_vs_ctrl = run_tests(post, ctrl)
    cd = cohens_d(ex, ctrl)

    stats = {
        "ticker": ticker,
        "n_ex_dates": classified["n_ex_dates"],
        "n_ex_obs": int(len(ex)),
        "n_pre_obs": int(len(pre)),
        "n_post_obs": int(len(post)),
        "n_control_obs": int(len(ctrl)),
        "mean_absr_pre": float(np.mean(pre)) if len(pre) > 0 else None,
        "mean_absr_exdate": float(np.mean(ex)) if len(ex) > 0 else None,
        "mean_absr_post": float(np.mean(post)) if len(post) > 0 else None,
        "mean_absr_control": float(np.mean(ctrl)) if len(ctrl) > 0 else None,
        "ttest_exdate_vs_control": {
            "t_stat": ex_vs_ctrl["t_stat"],
            "p_value": ex_vs_ctrl["p_value"],
            "n_ex": ex_vs_ctrl["n_a"],
            "n_control": ex_vs_ctrl["n_b"],
        },
        "mannwhitney_exdate_vs_control": {
            "statistic": ex_vs_ctrl["mw_statistic"],
            "p_value": ex_vs_ctrl["mw_p_value"],
        },
        "cohens_d": cd,
        "ttest_pre_vs_control": {
            "t_stat": pre_vs_ctrl["t_stat"],
            "p_value": pre_vs_ctrl["p_value"],
        },
        "ttest_post_vs_control": {
            "t_stat": post_vs_ctrl["t_stat"],
            "p_value": post_vs_ctrl["p_value"],
        },
    }
    return stats, classified


# ---------------------------------------------------------------------------
# Pooled analysis
# ---------------------------------------------------------------------------

def analyze_pooled(per_asset_classified: list[dict]) -> dict:
    """Pool all events across all assets."""
    all_ex = np.concatenate([d["ex"] for d in per_asset_classified])
    all_pre = np.concatenate([d["pre"] for d in per_asset_classified])
    all_post = np.concatenate([d["post"] for d in per_asset_classified])
    all_ctrl = np.concatenate([d["control"] for d in per_asset_classified])
    n_events_total = sum(d["n_ex_dates"] for d in per_asset_classified)

    print(f"\n  [POOLED] n_events={n_events_total}, ex={len(all_ex)}, pre={len(all_pre)}, post={len(all_post)}, ctrl={len(all_ctrl)}", flush=True)

    ex_vs_ctrl = run_tests(all_ex, all_ctrl)
    pre_vs_ctrl = run_tests(all_pre, all_ctrl)
    post_vs_ctrl = run_tests(all_post, all_ctrl)
    cd = cohens_d(all_ex, all_ctrl)

    return {
        "n_events_total": int(n_events_total),
        "n_ex_obs": int(len(all_ex)),
        "mean_absr_pre": float(np.mean(all_pre)) if len(all_pre) > 0 else None,
        "mean_absr_exdate": float(np.mean(all_ex)) if len(all_ex) > 0 else None,
        "mean_absr_post": float(np.mean(all_post)) if len(all_post) > 0 else None,
        "mean_absr_control": float(np.mean(all_ctrl)) if len(all_ctrl) > 0 else None,
        "ttest_exdate_vs_control": {
            "t_stat": ex_vs_ctrl["t_stat"],
            "p_value": ex_vs_ctrl["p_value"],
            "n_ex": ex_vs_ctrl["n_a"],
            "n_control": ex_vs_ctrl["n_b"],
        },
        "mannwhitney_exdate_vs_control": {
            "statistic": ex_vs_ctrl["mw_statistic"],
            "p_value": ex_vs_ctrl["mw_p_value"],
        },
        "cohens_d": cd,
        "ttest_pre_vs_control": {
            "t_stat": pre_vs_ctrl["t_stat"],
            "p_value": pre_vs_ctrl["p_value"],
        },
        "ttest_post_vs_control": {
            "t_stat": post_vs_ctrl["t_stat"],
            "p_value": post_vs_ctrl["p_value"],
        },
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def determine_verdict(pooled: dict) -> tuple[str, str]:
    """Determine PASS/CONDITIONAL_PASS/NULL based on pooled t-test."""
    p = pooled["ttest_exdate_vs_control"]["p_value"]
    t = pooled["ttest_exdate_vs_control"]["t_stat"]
    mw_p = pooled["mannwhitney_exdate_vs_control"]["p_value"]
    cd = pooled["cohens_d"]

    mean_ex = pooled["mean_absr_exdate"]
    mean_ctrl = pooled["mean_absr_control"]
    direction = "elevated" if mean_ex > mean_ctrl else "suppressed"

    if p is None:
        return "NULL", "Insufficient data to run pooled test."

    if p < 0.05:
        verdict = "PASS"
        interp = (
            f"Ex-date |r| is significantly {direction} vs control days "
            f"(pooled t-stat={t:.3f}, p={p:.4f}, Cohen's d={cd:.3f}). "
            f"Mann-Whitney also {'significant' if mw_p < 0.05 else 'not significant'} "
            f"(p={mw_p:.4f})."
        )
    elif p < 0.10:
        verdict = "CONDITIONAL_PASS"
        interp = (
            f"Ex-date |r| is marginally {direction} vs control days "
            f"(pooled t-stat={t:.3f}, p={p:.4f}, Cohen's d={cd:.3f}). "
            f"Result is marginal (0.05 ≤ p < 0.10); treat with caution."
        )
    else:
        verdict = "NULL"
        interp = (
            f"No significant difference in |r| between ex-dates and control days "
            f"(pooled t-stat={t:.3f}, p={p:.4f}, Cohen's d={cd:.3f}). "
            f"Mean ex-date |r|={mean_ex:.5f} vs control={mean_ctrl:.5f}. "
            f"Taiwan dividend ex-dates do not show systematic volatility elevation in this sample."
        )

    return verdict, interp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("K1373: 台股除權息日波動率事件研究")
    print("=" * 60)
    print(f"Assets : {ASSETS}")
    print(f"Period : {START} to {END}")
    print(f"Window : ±{EVENT_WINDOW} trading days")

    per_asset_results = {}
    per_asset_classified = []

    for ticker in ASSETS:
        try:
            result, classified = analyze_asset(ticker)
            per_asset_results[ticker] = result
            per_asset_classified.append(classified)

        except Exception as e:
            print(f"  ERROR for {ticker}: {e}", flush=True)
            per_asset_results[ticker] = {"error": str(e)}

    # Pooled
    print("\nRunning pooled analysis...", flush=True)
    valid_classified = [d for d in per_asset_classified if len(d.get("ex", [])) > 0]
    pooled = analyze_pooled(valid_classified)

    # Verdict
    verdict, summary = determine_verdict(pooled)
    print(f"\nVerdict: {verdict}")
    print(f"Summary: {summary}")

    # Validate minimum events
    n_total = pooled["n_events_total"]
    if n_total < 30:
        print(f"WARNING: Only {n_total} total ex-date events found. Expected ≥30.", flush=True)

    # Build results JSON
    # Re-structure per_asset to match required schema
    per_asset_output = {}
    for ticker, r in per_asset_results.items():
        if "error" in r:
            per_asset_output[ticker] = r
            continue
        per_asset_output[ticker] = {
            "n_ex_dates": r["n_ex_dates"],
            "mean_absr_pre": r["mean_absr_pre"],
            "mean_absr_exdate": r["mean_absr_exdate"],
            "mean_absr_post": r["mean_absr_post"],
            "mean_absr_control": r["mean_absr_control"],
            "ttest_exdate_vs_control": r["ttest_exdate_vs_control"],
            "mannwhitney_exdate_vs_control": r["mannwhitney_exdate_vs_control"],
            "cohens_d": r["cohens_d"],
            "ttest_pre_vs_control": r["ttest_pre_vs_control"],
            "ttest_post_vs_control": r["ttest_post_vs_control"],
        }

    results = {
        "experiment_id": "K1373",
        "title": "台股除權息日波動率事件研究",
        "description": (
            "Event study of absolute log returns around Taiwan stock/ETF dividend ex-dates. "
            "Tests whether ex-date volatility is systematically elevated vs non-event control days, "
            "and whether pre-window (buildup) and post-window (reversion) patterns exist."
        ),
        "date": "2026-05-18",
        "assets": ASSETS,
        "period": {"start": START, "end": END},
        "event_window": EVENT_WINDOW,
        "measure": "absolute log return |log(P_t / P_{t-1})|",
        "per_asset": per_asset_output,
        "pooled": pooled,
        "verdict": verdict,
        "summary": summary,
        "methodology_notes": {
            "lookahead": "CLEAN — ex-dates from external dividend calendar (yfinance .dividends index); no future return data used to classify days",
            "seed": "np.random.seed(42)",
            "control_definition": "all trading days with min distance > EVENT_WINDOW from any ex-date for the same asset",
            "ex_date_alignment": "if ex-date falls on non-trading day, use next available trading day",
        },
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to {OUTPUT_PATH}")
    return results


if __name__ == "__main__":
    main()
