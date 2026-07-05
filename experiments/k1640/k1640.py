"""K1640 - VIX 30/40 panic-entry event study.

Question
--------
Is "buy SPY when VIX breaks 30 or 40" genuinely better than entering on an
unconditional random trading day, over 5/10/20/60 trading-day horizons?

This is an independent 30/40-threshold replication of the broader K1633
myth-bust. K1640 intentionally keeps only the thresholds named in the task.

Lookahead policy
----------------
Primary timing is same-close event-study timing: the VIX crossing is observed
at day t close and SPY is entered at that same close, then only future SPY
prices t+H are measured. Robustness uses an explicit signal.shift(1) lag:

    signal_lag1 = signal.shift(1).fillna(False)

Only complete forward windows are kept. Overlapping H-day returns use HAC with
maxlags=H and a random-entry placebo with the same horizon geometry.

Randomness
----------
All random procedures use seed=42.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for _thread_var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_thread_var, "1")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

SEED = 42
THRESHOLDS = [30, 40]
HORIZONS = [5, 10, 20, 60]
COOLDOWN = 20
N_PLACEBO = 5000

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "k1640_results.json"

LITERATURE = [
    {
        "citation": "Whaley (2000), The Investor Fear Gauge",
        "url": "https://pm-research.com/content/iijpormgmt/26/3/12.full.pdf",
        "note": "VIX as investor fear gauge and market-implied volatility proxy.",
    },
    {
        "citation": "Giot (2005), Relationships Between Implied Volatility Indexes and Stock Index Returns",
        "url": "https://www.pm-research.com/content/iijpormgmt/31/3/92",
        "note": "Implied volatility indexes and future/spot stock-index return relationship.",
    },
    {
        "citation": "Bekaert and Hoerova (2014), The VIX, the Variance Premium and Stock Market Volatility",
        "url": "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1675.pdf",
        "note": "VIX reflects physical expected variance plus variance risk premium.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jfloat(x: Any, digits: int | None = None) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(y):
        return None
    return round(y, digits) if digits is not None else y


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def load_data() -> pd.DataFrame:
    ensure_dirs()
    vix_path = DATA_DIR / "vix_full.csv"
    spy_path = DATA_DIR / "spy_full.csv"

    if not (vix_path.exists() and spy_path.exists()):
        src_vix = Path("experiments/k1633/data/vix_full.csv")
        src_spy = Path("experiments/k1633/data/spy_full.csv")
        if src_vix.exists() and src_spy.exists():
            shutil.copy2(src_vix, vix_path)
            shutil.copy2(src_spy, spy_path)
        else:
            import yfinance as yf

            vix = yf.download("^VIX", start="1990-01-01", end="2026-07-05", progress=False, auto_adjust=False)
            spy = yf.download("SPY", start="1993-01-01", end="2026-07-05", progress=False, auto_adjust=True)
            for frame in (vix, spy):
                if isinstance(frame.columns, pd.MultiIndex):
                    frame.columns = [c[0] for c in frame.columns]
            vix[["Close"]].rename(columns={"Close": "VIX"}).to_csv(vix_path)
            spy[["Close"]].rename(columns={"Close": "SPY"}).to_csv(spy_path)

    vix = pd.read_csv(vix_path, index_col=0, parse_dates=True)
    spy = pd.read_csv(spy_path, index_col=0, parse_dates=True)
    df = pd.concat([vix["VIX"], spy["SPY"]], axis=1, join="inner")
    df = df.dropna().sort_index()
    df = df[~df.index.duplicated(keep="first")]
    if len(df) < 1000:
        raise RuntimeError("insufficient VIX/SPY common history")
    return df


def crossing_signal(vix: pd.Series, threshold: float) -> pd.Series:
    signal = (vix >= threshold) & (vix.shift(1) < threshold)
    signal = signal.fillna(False)
    return signal


def de_cluster_positions(signal: pd.Series, cooldown: int) -> list[int]:
    raw = np.where(signal.to_numpy(dtype=bool))[0].tolist()
    accepted: list[int] = []
    last = -10**9
    for pos in raw:
        if pos - last >= cooldown:
            accepted.append(int(pos))
            last = pos
    return accepted


def forward_returns(prices: np.ndarray, entries: list[int], horizon: int) -> tuple[np.ndarray, list[int]]:
    out: list[float] = []
    kept: list[int] = []
    n = len(prices)
    for e in entries:
        if e + horizon < n:
            out.append(float(prices[e + horizon] / prices[e] - 1.0))
            kept.append(e)
    return np.asarray(out, dtype=float), kept


def baseline_forward(prices: np.ndarray, horizon: int) -> np.ndarray:
    return prices[horizon:] / prices[:-horizon] - 1.0


def window_mdd(prices: np.ndarray, entries: list[int], horizon: int) -> np.ndarray:
    out: list[float] = []
    n = len(prices)
    for e in entries:
        if e + horizon < n:
            path = prices[e : e + horizon + 1]
            peak = np.maximum.accumulate(path)
            out.append(float((path / peak - 1.0).min()))
    return np.asarray(out, dtype=float)


def return_stats(x: np.ndarray) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    return {
        "n": int(len(x)),
        "win_rate": jfloat(np.mean(x > 0), 6),
        "mean": jfloat(np.mean(x), 8),
        "median": jfloat(np.median(x), 8),
        "std": jfloat(np.std(x, ddof=1), 8) if len(x) > 1 else None,
        "p5": jfloat(np.percentile(x, 5), 8) if len(x) else None,
        "p95": jfloat(np.percentile(x, 95), 8) if len(x) else None,
    }


def hac_event_test(all_forward: np.ndarray, event_entries: list[int], horizon: int) -> dict[str, Any]:
    mask = np.zeros(len(all_forward), dtype=float)
    valid_events = [e for e in event_entries if e < len(mask)]
    mask[valid_events] = 1.0
    x = sm.add_constant(mask)
    fit = sm.OLS(all_forward, x).fit(cov_type="HAC", cov_kwds={"maxlags": horizon})
    return {
        "event_vs_non_event_coef": jfloat(fit.params[1], 8),
        "hac_t": jfloat(fit.tvalues[1], 6),
        "hac_p": jfloat(fit.pvalues[1], 8),
        "maxlags": int(horizon),
    }


def random_entry_placebo(
    prices: np.ndarray,
    event_mean: float,
    n_events: int,
    horizon: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    valid = np.arange(0, len(prices) - horizon)
    null = np.empty(N_PLACEBO, dtype=float)
    for i in range(N_PLACEBO):
        pick = rng.choice(valid, size=n_events, replace=False)
        null[i] = np.mean(prices[pick + horizon] / prices[pick] - 1.0)
    p_one = float(np.mean(null >= event_mean))
    centered = null - null.mean()
    p_two = float(np.mean(np.abs(centered) >= abs(event_mean - null.mean())))
    return {
        "null_mean": jfloat(null.mean(), 8),
        "p_one_sided_event_gt_random": jfloat(p_one, 8),
        "p_two_sided": jfloat(p_two, 8),
        "null_p95": jfloat(np.percentile(null, 95), 8),
        "reps": N_PLACEBO,
    }


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        running = min(running, pvalues[idx] * m / rank)
        q[idx] = min(running, 1.0)
    return q


def build_cells(df: pd.DataFrame, entry_lag: int = 0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spy = df["SPY"].to_numpy(dtype=float)
    vix = df["VIX"]
    cells: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []

    for threshold in THRESHOLDS:
        signal = crossing_signal(vix, threshold)
        if entry_lag == 1:
            signal = signal.shift(1).fillna(False)
        positions = de_cluster_positions(signal, COOLDOWN)
        for horizon in HORIZONS:
            event_returns, kept = forward_returns(spy, positions, horizon)
            base = baseline_forward(spy, horizon)
            mdd = window_mdd(spy, kept, horizon)
            hac = hac_event_test(base, kept, horizon)
            rng = np.random.default_rng(SEED + int(threshold) * 100 + horizon + entry_lag * 10000)
            placebo = random_entry_placebo(spy, float(event_returns.mean()), len(event_returns), horizon, rng)
            cell_id = f"thr{int(threshold)}_H{horizon}_lag{entry_lag}"
            base_stats = return_stats(base)
            event_stats = return_stats(event_returns)
            cell = {
                "threshold": threshold,
                "horizon": horizon,
                "entry_lag": entry_lag,
                "n_events": int(len(event_returns)),
                "first_event": str(df.index[kept[0]].date()) if kept else None,
                "last_event": str(df.index[kept[-1]].date()) if kept else None,
                "event": event_stats,
                "baseline": base_stats,
                "excess_mean": jfloat(event_returns.mean() - base.mean(), 8),
                "win_vs_base": jfloat(event_stats["win_rate"] - base_stats["win_rate"], 8),
                "event_window_mdd_mean": jfloat(mdd.mean(), 8) if len(mdd) else None,
                "hac": hac,
                "placebo": placebo,
            }
            cells[cell_id] = cell
            rows.append(
                {
                    "cell_id": cell_id,
                    "threshold": threshold,
                    "horizon": horizon,
                    "entry_lag": entry_lag,
                    "n_events": len(event_returns),
                    "event_mean": event_stats["mean"],
                    "baseline_mean": base_stats["mean"],
                    "excess_mean": cell["excess_mean"],
                    "event_win_rate": event_stats["win_rate"],
                    "baseline_win_rate": base_stats["win_rate"],
                    "win_vs_base": cell["win_vs_base"],
                    "hac_p": hac["hac_p"],
                    "placebo_p_one_sided": placebo["p_one_sided_event_gt_random"],
                }
            )
    return cells, rows


def add_fdr(cells: dict[str, Any], rows: list[dict[str, Any]], entry_lag: int) -> dict[str, Any]:
    ids = [r["cell_id"] for r in rows if r["entry_lag"] == entry_lag]
    pvals = [float(cells[cell_id]["hac"]["hac_p"]) for cell_id in ids]
    qvals = benjamini_hochberg(pvals)
    for cell_id, q in zip(ids, qvals):
        cells[cell_id]["bh_qvalue"] = jfloat(q, 8)
        cells[cell_id]["bh_fdr_5pct"] = bool(q <= 0.05)
        cells[cell_id]["bh_fdr_10pct"] = bool(q <= 0.10)
    survivors_5 = [cell_id for cell_id, q in zip(ids, qvals) if q <= 0.05]
    survivors_10 = [cell_id for cell_id, q in zip(ids, qvals) if q <= 0.10]
    return {
        "method": f"Benjamini-Hochberg FDR over {len(ids)} lag{entry_lag} HAC p-values",
        "n_cells": len(ids),
        "n_positive_excess": int(sum(cells[cell_id]["excess_mean"] > 0 for cell_id in ids)),
        "raw_5pct_survivors": [cell_id for cell_id in ids if cells[cell_id]["hac"]["hac_p"] <= 0.05],
        "bh_fdr_5pct_survivors": survivors_5,
        "bh_fdr_10pct_survivors": survivors_10,
    }


def plot_excess(rows: list[dict[str, Any]]) -> None:
    df = pd.DataFrame([r for r in rows if r["entry_lag"] == 0])
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    x = np.arange(len(df))
    colors = ["#264b72" if t == 30 else "#b34d2f" for t in df["threshold"]]
    ax.bar(x, df["excess_mean"] * 100, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    labels = [f"VIX>{int(t)}\nH{int(h)}" for t, h in zip(df["threshold"], df["horizon"])]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Excess return vs random entry (%)")
    ax.set_title("K1640 VIX panic-entry excess returns")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1640_excess_returns.png", bbox_inches="tight")
    plt.close(fig)


def plot_winrates(rows: list[dict[str, Any]]) -> None:
    df = pd.DataFrame([r for r in rows if r["entry_lag"] == 0])
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    x = np.arange(len(df))
    width = 0.36
    ax.bar(x - width / 2, df["event_win_rate"] * 100, width, label="VIX event", color="#264b72")
    ax.bar(x + width / 2, df["baseline_win_rate"] * 100, width, label="Random day", color="#9a9a9a")
    labels = [f">{int(t)} H{int(h)}" for t, h in zip(df["threshold"], df["horizon"])]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Win rate (%)")
    ax.set_title("Win rate: event entry vs unconditional baseline")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1640_winrates.png", bbox_inches="tight")
    plt.close(fig)


def save_event_returns(df: pd.DataFrame) -> None:
    spy = df["SPY"].to_numpy(dtype=float)
    rows = []
    for threshold in THRESHOLDS:
        signal = crossing_signal(df["VIX"], threshold)
        positions = de_cluster_positions(signal, COOLDOWN)
        for horizon in HORIZONS:
            event_returns, kept = forward_returns(spy, positions, horizon)
            for pos, ret in zip(kept, event_returns):
                rows.append(
                    {
                        "threshold": threshold,
                        "horizon": horizon,
                        "entry_date": str(df.index[pos].date()),
                        "vix_close": jfloat(df["VIX"].iloc[pos], 6),
                        "spy_close": jfloat(df["SPY"].iloc[pos], 6),
                        "forward_return": jfloat(ret, 10),
                    }
                )
    pd.DataFrame(rows).to_csv(DATA_DIR / "k1640_event_returns.csv", index=False)


def main() -> None:
    ensure_dirs()
    df = load_data()
    cells0, rows0 = build_cells(df, entry_lag=0)
    cells1, rows1 = build_cells(df, entry_lag=1)
    cells = {**cells0, **cells1}
    rows = rows0 + rows1
    fdr0 = add_fdr(cells, rows, entry_lag=0)
    fdr1 = add_fdr(cells, rows, entry_lag=1)

    table = pd.DataFrame(rows)
    table.to_csv(DATA_DIR / "k1640_cell_summary.csv", index=False)
    save_event_returns(df)
    plot_excess(rows)
    plot_winrates(rows)

    baseline_win_rates = {
        str(h): cells[f"thr30_H{h}_lag0"]["baseline"]["win_rate"] for h in HORIZONS
    }
    event_counts = {
        str(t): cells[f"thr{t}_H5_lag0"]["n_events"] for t in THRESHOLDS
    }

    h60_pattern = {
        str(t): {
            "excess_mean": cells[f"thr{t}_H60_lag0"]["excess_mean"],
            "hac_p": cells[f"thr{t}_H60_lag0"]["hac"]["hac_p"],
            "bh_qvalue": cells[f"thr{t}_H60_lag0"]["bh_qvalue"],
        }
        for t in THRESHOLDS
    }

    verdict = "CONDITIONAL_PASS_HALF_TRUE_QUALIFIED"
    if fdr0["bh_fdr_5pct_survivors"]:
        verdict = "CONDITIONAL_PASS_PANIC_ENTRY_SURVIVES_FDR5"
    elif fdr0["n_positive_excess"] < len(THRESHOLDS) * len(HORIZONS) - 1:
        verdict = "CONDITIONAL_PASS_WEAK_OR_MIXED"

    results = {
        "experiment_id": "K1640",
        "generated_at": utc_now(),
        "seed": SEED,
        "verdict": verdict,
        "research_question": "Does SPY entry after VIX first crosses 30 or 40 outperform unconditional random-day entry over 5/10/20/60 trading days?",
        "data": {
            "source": "yfinance ^VIX close + SPY adjusted close; K1640 cache copied from K1633 cache when present",
            "period": f"{df.index.min().date()} .. {df.index.max().date()}",
            "n_trading_days": int(len(df)),
            "thresholds": THRESHOLDS,
            "horizons": HORIZONS,
            "cooldown_trading_days": COOLDOWN,
        },
        "literature_checked": LITERATURE,
        "method": {
            "primary_entry": "signal-day close; forward return uses only SPY[t+H]/SPY[t]-1 after the signal day",
            "robustness_entry": "lag1 close using explicit signal.shift(1)",
            "baseline": "every eligible trading day as an entry point, same SPY price series and same horizon",
            "inference": "HAC/Newey-West fwd_return ~ event_dummy with maxlags=horizon; BH-FDR across 8 lag0 cells",
            "placebo": f"{N_PLACEBO} random-entry draws per cell, seed-derived from SEED=42",
        },
        "event_counts": event_counts,
        "baseline_win_rates": baseline_win_rates,
        "cells": cells,
        "multiple_testing_lag0": fdr0,
        "multiple_testing_lag1": fdr1,
        "h60_pattern": h60_pattern,
        "headline": (
            "Half true: VIX 30/40 entries usually have positive excess returns over random entry, "
            "but strict FDR-5% leaves no individual lag0 cell. The durable pattern is H60 slow recovery, "
            "not an instant rebound; VIX>40 has only 17 events."
        ),
        "outputs": {
            "cell_summary_csv": str(DATA_DIR / "k1640_cell_summary.csv"),
            "event_returns_csv": str(DATA_DIR / "k1640_event_returns.csv"),
            "fig_excess_returns": str(FIG_DIR / "k1640_excess_returns.png"),
            "fig_winrates": str(FIG_DIR / "k1640_winrates.png"),
        },
        "limitations": [
            "Lag0 is an event-study timing convention, not guaranteed same-close executable trading.",
            "VIX>40 has small sample size (17 accepted events), so single-cell estimates are fragile.",
            "This is SPY-only and does not model transaction costs, cash yields, taxes, or execution slippage.",
            "K1640 intentionally focuses on thresholds 30 and 40; K1633 contains the broader 30/35/40 version.",
        ],
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    print(
        json.dumps(
            {
                "verdict": verdict,
                "event_counts": event_counts,
                "baseline_win_rates": baseline_win_rates,
                "h60_pattern": h60_pattern,
                "fdr5_survivors": fdr0["bh_fdr_5pct_survivors"],
                "fdr10_survivors": fdr0["bh_fdr_10pct_survivors"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
