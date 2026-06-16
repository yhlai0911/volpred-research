"""K1514 — Liberation Day 2025 cross-asset correlation event study.

Event timing:
- The reciprocal tariff announcement was on 2025-04-02.
- We use close-to-close returns, so the post-event sample starts on the first
  trading day after 2025-04-02.

This is an ex-post event study, not a trading signal. No same-day signal is
multiplied by same-day returns.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

for _thread_var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_thread_var] = "1"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm, t as student_t


SEED = 42
START = "2019-01-01"
END = "2025-08-31"
EVENT_DATE = "2025-04-02"
CONTROL_YEARS = [2021, 2022, 2023, 2024]
WINDOWS = [30, 60, 90]
BOOT_REPS = 1000
BOOT_BLOCK = 5

TICKERS = {
    "SPY": "SPY",
    "TLT": "TLT",
    "GLD": "GLD",
    "PDBC": "PDBC",
    "BTC": "BTC-USD",
    "VIX": "^VIX",
}

PAIRS = [
    ("SPY", "TLT", "stock_bond"),
    ("SPY", "GLD", "stock_gold"),
    ("SPY", "PDBC", "stock_commodity"),
    ("SPY", "BTC", "stock_btc"),
    ("SPY", "VIX", "stock_vol"),
    ("TLT", "GLD", "bond_gold"),
]

OUT_DIR = Path(__file__).parent
DATA_PATH = OUT_DIR / "prices.csv"
RESULTS_PATH = OUT_DIR / "k1514_results.json"
FIG_PATH = OUT_DIR / "k1514_fig.png"


def fetch_prices() -> pd.DataFrame:
    if DATA_PATH.exists():
        cached = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)
        min_required_end = pd.Timestamp(END) - pd.Timedelta(days=7)
        if set(TICKERS).issubset(cached.columns) and cached.index.max() >= min_required_end:
            return cached[list(TICKERS)].dropna()

    raw = yf.download(
        list(TICKERS.values()),
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    rename = {v: k for k, v in TICKERS.items()}
    close = close.rename(columns=rename)[list(TICKERS)].dropna()
    close.to_csv(DATA_PATH)
    return close


def first_index_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp:
    later = index[index > date]
    if later.empty:
        raise ValueError(f"No trading day after {date.date()}")
    return later[0]


def last_index_on_or_before(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp:
    earlier = index[index <= date]
    if earlier.empty:
        raise ValueError(f"No trading day on or before {date.date()}")
    return earlier[-1]


def event_windows(
    returns: pd.DataFrame,
    event_date: pd.Timestamp,
    window: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    pre_end = last_index_on_or_before(returns.index, event_date)
    post_start = first_index_after(returns.index, event_date)
    pre = returns.loc[:pre_end].tail(window)
    post = returns.loc[post_start:].head(window)
    meta = {
        "event_date": str(event_date.date()),
        "pre_start": str(pre.index.min().date()),
        "pre_end": str(pre.index.max().date()),
        "post_start": str(post.index.min().date()),
        "post_end": str(post.index.max().date()),
        "n_pre": int(len(pre)),
        "n_post": int(len(post)),
    }
    return pre, post, meta


def fisher_corr_test(pre: pd.DataFrame, post: pd.DataFrame, x: str, y: str) -> dict:
    pre_xy = pre[[x, y]].dropna()
    post_xy = post[[x, y]].dropna()
    n_pre, n_post = len(pre_xy), len(post_xy)
    if n_pre < 10 or n_post < 10:
        return {
            "corr_pre": None,
            "corr_post": None,
            "delta_corr": None,
            "z_stat": None,
            "p_value": None,
            "n_pre": int(n_pre),
            "n_post": int(n_post),
            "note": "insufficient data",
        }
    r_pre = float(pre_xy[x].corr(pre_xy[y]))
    r_post = float(post_xy[x].corr(post_xy[y]))
    z_pre = np.arctanh(np.clip(r_pre, -0.999999, 0.999999))
    z_post = np.arctanh(np.clip(r_post, -0.999999, 0.999999))
    se = np.sqrt(1.0 / (n_pre - 3) + 1.0 / (n_post - 3))
    z_stat = float((z_post - z_pre) / se)
    p_value = float(2.0 * (1.0 - norm.cdf(abs(z_stat))))
    return {
        "corr_pre": r_pre,
        "corr_post": r_post,
        "delta_corr": float(r_post - r_pre),
        "z_stat": z_stat,
        "p_value": p_value,
        "n_pre": int(n_pre),
        "n_post": int(n_post),
    }


def block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        length = int(min(rng.geometric(1.0 / block), n - i))
        for k in range(length):
            idx[i + k] = (start + k) % n
        i += length
    return idx


def bootstrap_delta_corr(
    pre: pd.DataFrame,
    post: pd.DataFrame,
    x: str,
    y: str,
    *,
    reps: int,
    block: int,
    seed: int,
) -> dict:
    pre_xy = pre[[x, y]].dropna().values
    post_xy = post[[x, y]].dropna().values
    n_pre, n_post = len(pre_xy), len(post_xy)
    if n_pre < 10 or n_post < 10:
        return {"reps": reps, "block": block, "seed": seed, "ci95": None, "note": "insufficient data"}
    rng = np.random.default_rng(seed)
    deltas = np.empty(reps)
    for i in range(reps):
        pre_b = pre_xy[block_bootstrap_indices(n_pre, block, rng)]
        post_b = post_xy[block_bootstrap_indices(n_post, block, rng)]
        r_pre = np.corrcoef(pre_b[:, 0], pre_b[:, 1])[0, 1]
        r_post = np.corrcoef(post_b[:, 0], post_b[:, 1])[0, 1]
        deltas[i] = r_post - r_pre
    return {
        "reps": int(reps),
        "block": int(block),
        "seed": int(seed),
        "mean": float(np.nanmean(deltas)),
        "ci95": [
            float(np.nanquantile(deltas, 0.025)),
            float(np.nanquantile(deltas, 0.975)),
        ],
    }


def placebo_deltas(
    returns: pd.DataFrame,
    pair: tuple[str, str],
    window: int,
) -> dict:
    x, y = pair
    rows = []
    for year in CONTROL_YEARS:
        event_date = pd.Timestamp(f"{year}-04-02")
        try:
            pre, post, meta = event_windows(returns, event_date, window)
        except ValueError:
            continue
        stats = fisher_corr_test(pre, post, x, y)
        if stats["delta_corr"] is not None:
            rows.append({"year": year, "delta_corr": stats["delta_corr"], **meta})
    vals = np.array([r["delta_corr"] for r in rows], dtype=float)
    if len(vals) == 0:
        return {"control_years": CONTROL_YEARS, "deltas": rows, "mean_delta": None, "std_delta": None}
    return {
        "control_years": CONTROL_YEARS,
        "deltas": rows,
        "mean_delta": float(vals.mean()),
        "std_delta": float(vals.std(ddof=1)) if len(vals) > 1 else None,
        "n_controls": int(len(vals)),
    }


def did_against_placebo(delta_event: float | None, placebo: dict) -> dict:
    if delta_event is None or placebo.get("mean_delta") is None:
        return {"did_delta": None, "note": "insufficient data"}
    did = float(delta_event - placebo["mean_delta"])
    n_controls = placebo.get("n_controls", 0)
    std = placebo.get("std_delta")
    if n_controls >= 2 and std and std > 0:
        t_stat = did / (std / np.sqrt(n_controls))
        p_value = float(2.0 * (1.0 - student_t.cdf(abs(t_stat), df=n_controls - 1)))
    else:
        t_stat = None
        p_value = None
    return {
        "did_delta": did,
        "placebo_mean_delta": placebo["mean_delta"],
        "placebo_std_delta": std,
        "n_controls": int(n_controls),
        "t_vs_placebo_mean": float(t_stat) if t_stat is not None else None,
        "p_vs_placebo_mean": p_value,
    }


def summarize(results_by_window: dict) -> dict:
    primary_pairs = {"stock_bond", "stock_gold", "stock_btc", "stock_vol"}
    pair_hits: dict[str, int] = {name: 0 for _, _, name in PAIRS}
    pair_deltas: dict[str, list[float]] = {name: [] for _, _, name in PAIRS}

    for window_result in results_by_window.values():
        for pair_name, stats in window_result["pairs"].items():
            delta = stats["event"].get("delta_corr")
            p_value = stats["event"].get("p_value")
            ci = stats["bootstrap_delta_corr"].get("ci95")
            if delta is not None:
                pair_deltas[pair_name].append(delta)
            if (
                pair_name in primary_pairs
                and delta is not None
                and p_value is not None
                and p_value < 0.05
                and ci is not None
                and not (ci[0] <= 0 <= ci[1])
            ):
                pair_hits[pair_name] += 1

    robust_pairs = {
        pair: hits
        for pair, hits in pair_hits.items()
        if pair in primary_pairs and hits >= 2
    }
    avg_deltas = {
        pair: float(np.mean(vals)) if vals else None
        for pair, vals in pair_deltas.items()
    }
    if len(robust_pairs) >= 3:
        verdict = "PASS"
        verdict_reason = f"{len(robust_pairs)} primary pair shifts are significant in >=2 windows."
    elif len(robust_pairs) >= 1:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = f"{len(robust_pairs)} primary pair shift(s) are significant in >=2 windows."
    else:
        verdict = "NULL"
        verdict_reason = "No primary cross-asset correlation shift is significant in >=2 windows."
    return {
        "pair_hits": pair_hits,
        "robust_primary_pairs": robust_pairs,
        "average_delta_corr_by_pair": avg_deltas,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


def make_figure(results_by_window: dict, rolling_corr: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 9))

    heat = pd.DataFrame(
        {
            window: {
                pair: stats["event"]["delta_corr"]
                for pair, stats in result["pairs"].items()
            }
            for window, result in results_by_window.items()
        }
    ).loc[[name for _, _, name in PAIRS]]
    im = axes[0].imshow(heat.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    axes[0].set_title("K1514 Liberation Day correlation shift: post minus pre")
    axes[0].set_xticks(range(len(heat.columns)), labels=[f"{w}d" for w in heat.columns])
    axes[0].set_yticks(range(len(heat.index)), labels=heat.index)
    for i in range(heat.shape[0]):
        for j in range(heat.shape[1]):
            val = heat.iloc[i, j]
            axes[0].text(j, i, f"{val:+.2f}", ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=axes[0], label="delta correlation")

    for col in rolling_corr.columns:
        axes[1].plot(rolling_corr.index, rolling_corr[col], label=col, lw=1.2)
    axes[1].axvline(pd.Timestamp(EVENT_DATE), color="black", lw=1.0, ls="--", label="2025-04-02")
    axes[1].set_title("Rolling 30d correlations around event")
    axes[1].set_ylabel("correlation")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best", ncol=2, fontsize=9)
    plt.tight_layout()
    plt.savefig(FIG_PATH, dpi=120)


def main() -> None:
    t0 = time.time()
    prices = fetch_prices()
    returns = prices.pct_change().dropna()
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

    results_by_window: dict[str, dict] = {}
    for window in WINDOWS:
        pre, post, meta = event_windows(returns, pd.Timestamp(EVENT_DATE), window)
        window_key = str(window)
        results_by_window[window_key] = {"event_window": meta, "pairs": {}}
        for x, y, pair_name in PAIRS:
            event_stats = fisher_corr_test(pre, post, x, y)
            boot = bootstrap_delta_corr(
                pre,
                post,
                x,
                y,
                reps=BOOT_REPS,
                block=BOOT_BLOCK,
                seed=SEED + window + len(pair_name),
            )
            placebo = placebo_deltas(returns, (x, y), window)
            did = did_against_placebo(event_stats.get("delta_corr"), placebo)
            results_by_window[window_key]["pairs"][pair_name] = {
                "assets": [x, y],
                "event": event_stats,
                "bootstrap_delta_corr": boot,
                "calendar_placebo": placebo,
                "did_vs_calendar_placebo": did,
            }

    rolling = pd.DataFrame(index=returns.index)
    for x, y, pair_name in PAIRS:
        rolling[pair_name] = returns[x].rolling(30).corr(returns[y])
    rolling_plot = rolling.loc["2024-10-01":"2025-07-31"]
    make_figure(results_by_window, rolling_plot)

    summary = summarize(results_by_window)
    out = {
        "experiment_id": "K1514",
        "title": "Liberation Day 2025 cross-asset correlation event study",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "tickers": TICKERS,
            "period": [START, END],
            "event_date": EVENT_DATE,
            "event_timing": "post window starts on first trading day after event date",
            "windows_trading_days": WINDOWS,
            "control_years": CONTROL_YEARS,
            "bootstrap_reps": BOOT_REPS,
            "bootstrap_block": BOOT_BLOCK,
            "lookahead_policy": "ex-post event study; pre windows end on/before event date, post windows start strictly after event date",
        },
        "sample": {
            "first_return_day": str(returns.index.min().date()),
            "last_return_day": str(returns.index.max().date()),
            "n_obs": int(len(returns)),
        },
        "results_by_window": results_by_window,
        "summary": summary,
        "verdict": summary["verdict"],
        "verdict_reason": summary["verdict_reason"],
        "runtime_seconds": round(time.time() - t0, 2),
        "codex_review": None,
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[K1514] Results written to {RESULTS_PATH}")
    print(f"[K1514] Figure written to {FIG_PATH}")
    print(f"[K1514] VERDICT: {out['verdict']}")
    print(f"[K1514] {out['verdict_reason']}")
    for pair_name, delta in summary["average_delta_corr_by_pair"].items():
        print(f"[K1514] avg delta {pair_name}: {delta:+.3f}")


if __name__ == "__main__":
    main()
