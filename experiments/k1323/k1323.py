#!/usr/bin/env python3
"""
K1323: VIXTWN 252-day gate update with VIX source freshness audit.

This is the honest successor to K1321:
  - the 252-day gate is still not reached
  - local VIX pairing data in paper/taiwan-vt is stale after 2026-05-19
  - a fresh experiment-scoped ^VIX snapshot confirms the instability direction
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "k1323"
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent.parent
DATA_DIR = ROOT / "data"
RESULTS_PATH = ROOT / "k1323_results.json"
README_PATH = ROOT / "README.md"

VIXTWN_PATH = PROJECT_ROOT / "data" / "vixtwn" / "vixtwn_daily.csv"
LOCAL_VIX_PATH = (
    PROJECT_ROOT
    / "paper"
    / "taiwan-vt"
    / "data"
    / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
)
TARGET_DAYS = 252
K1181_BASELINE_MEAN = 1.3906
K1181_BASELINE_CV = 0.098
K1321_RESULTS_PATH = PROJECT_ROOT / "experiments" / "k1321" / "k1321_results.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_vixtwn() -> tuple[pd.Series, dict]:
    df = pd.read_csv(VIXTWN_PATH, parse_dates=["date"])
    raw_rows = len(df)
    dup_rows = int(df["date"].duplicated().sum())
    df = df.sort_values("date").drop_duplicates("date", keep="first")
    series = df.set_index("date")["vixtwn_close"].astype(float).dropna().sort_index()
    meta = {
        "path": str(VIXTWN_PATH.relative_to(PROJECT_ROOT)),
        "raw_rows": raw_rows,
        "duplicate_dates_removed": dup_rows,
        "unique_rows": int(len(series)),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
    }
    return series, meta


def load_local_vix() -> tuple[pd.Series, dict]:
    df = pd.read_csv(LOCAL_VIX_PATH, parse_dates=["date"], usecols=["date", "vix_close"])
    raw_rows = len(df)
    dup_rows = int(df["date"].duplicated().sum())
    df = df.sort_values("date").drop_duplicates("date", keep="first")
    series = df.set_index("date")["vix_close"].astype(float).dropna().sort_index()
    meta = {
        "path": str(LOCAL_VIX_PATH.relative_to(PROJECT_ROOT)),
        "raw_rows": raw_rows,
        "duplicate_dates_removed": dup_rows,
        "non_null_rows": int(len(series)),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
    }
    return series, meta


def load_fresh_vix(start: str, end: str) -> tuple[pd.Series, dict]:
    raw = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("Fresh ^VIX download returned empty frame.")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Adj Close"]["^VIX"]
    else:
        close = raw["Adj Close"]
    close = close.dropna().astype(float)
    out_path = DATA_DIR / "vix_yfinance_snapshot.csv"
    raw.to_csv(out_path, index_label="Date")
    meta = {
        "path": str(out_path.relative_to(PROJECT_ROOT)),
        "non_null_rows": int(len(close)),
        "start": str(close.index.min().date()),
        "end": str(close.index.max().date()),
    }
    return close, meta


def summarize_ratio(ratio: pd.Series) -> dict:
    n = len(ratio)
    first_half = ratio.iloc[: n // 2]
    second_half = ratio.iloc[n // 2 :]
    x = np.arange(n)
    trend = stats.linregress(x, ratio.values)
    t_stat, p_value = stats.ttest_1samp(ratio.values, popmean=K1181_BASELINE_MEAN)
    rolling20 = ratio.rolling(20).mean().dropna()
    ci = stats.t.interval(
        0.95, df=n - 1, loc=ratio.mean(), scale=stats.sem(ratio)
    ) if n > 1 else (np.nan, np.nan)
    return {
        "n": int(n),
        "start": str(ratio.index.min().date()),
        "end": str(ratio.index.max().date()),
        "mean": float(ratio.mean()),
        "median": float(ratio.median()),
        "std": float(ratio.std(ddof=1)),
        "cv": float(ratio.std(ddof=1) / ratio.mean()),
        "min": float(ratio.min()),
        "max": float(ratio.max()),
        "ci_95_mean": [float(ci[0]), float(ci[1])],
        "first_half_mean": float(first_half.mean()),
        "second_half_mean": float(second_half.mean()),
        "trend_slope_per_day": float(trend.slope),
        "trend_rvalue": float(trend.rvalue),
        "trend_pvalue": float(trend.pvalue),
        "ttest_vs_k1181_mean": {
            "baseline_mean": K1181_BASELINE_MEAN,
            "t_stat": float(t_stat),
            "p_value": float(p_value),
        },
        "rolling20_mean_start": float(rolling20.iloc[0]),
        "rolling20_mean_end": float(rolling20.iloc[-1]),
        "tail_snapshot": {
            str(idx.date()): float(val) for idx, val in ratio.tail(5).items()
        },
    }


def build_ratio(vixtwn: pd.Series, vix: pd.Series) -> pd.Series:
    overlap = vixtwn.index.intersection(vix.index)
    return (vixtwn.loc[overlap] / vix.loc[overlap]).dropna().sort_index()


def plot_ratio(local_ratio: pd.Series, fresh_ratio: pd.Series) -> str:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    if not local_ratio.empty:
        ax.plot(local_ratio.index, local_ratio.values, label="Local VIX source", lw=2, color="#1f77b4")
    if not fresh_ratio.empty:
        ax.plot(fresh_ratio.index, fresh_ratio.values, label="Fresh yfinance ^VIX", lw=2, color="#d97706")
    ax.axhline(K1181_BASELINE_MEAN, color="#6b7280", ls="--", lw=1.5, label="K1181 mean 1.3906")
    ax.set_title("VIXTWN / VIX ratio: local gate vs fresh-source audit")
    ax.set_ylabel("Ratio")
    ax.legend()
    fig.tight_layout()
    out = ROOT / "k1323_ratio_paths.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out.name


def load_k1321_baseline() -> dict:
    return json.loads(K1321_RESULTS_PATH.read_text())


def rounded(obj):
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def main() -> None:
    ensure_dirs()

    vixtwn, vixtwn_meta = load_vixtwn()
    local_vix, local_vix_meta = load_local_vix()
    fresh_vix, fresh_vix_meta = load_fresh_vix(
        start=str(vixtwn.index.min().date()),
        end=str((vixtwn.index.max() + pd.Timedelta(days=1)).date()),
    )

    local_ratio = build_ratio(vixtwn, local_vix)
    fresh_ratio = build_ratio(vixtwn, fresh_vix)
    local_stats = summarize_ratio(local_ratio)
    fresh_stats = summarize_ratio(fresh_ratio)
    k1321 = load_k1321_baseline()

    unique_vixtwn_days = int(len(vixtwn))
    progress = {
        "target_days": TARGET_DAYS,
        "unique_vixtwn_days": unique_vixtwn_days,
        "completion_ratio": float(unique_vixtwn_days / TARGET_DAYS),
        "days_remaining": int(max(TARGET_DAYS - unique_vixtwn_days, 0)),
        "target_reached": bool(unique_vixtwn_days >= TARGET_DAYS),
    }

    freshness_gap = {
        "vixtwn_last_date": vixtwn_meta["end"],
        "local_vix_last_date": local_vix_meta["end"],
        "fresh_vix_last_date": fresh_vix_meta["end"],
        "local_pairing_overlap_days": int(len(local_ratio)),
        "fresh_pairing_overlap_days": int(len(fresh_ratio)),
        "overlap_gain_from_fresh_vix": int(len(fresh_ratio) - len(local_ratio)),
        "local_source_stale_vs_vixtwn_days": int(
            len(pd.bdate_range(pd.Timestamp(local_vix.index.max()) + pd.Timedelta(days=1), pd.Timestamp(vixtwn.index.max())))
        ),
    }

    k1321_ratio = k1321["ratio_stats"]
    comparison_to_k1321 = {
        "k1321_overlap_days": int(k1321_ratio["n"]),
        "current_local_overlap_days": int(local_stats["n"]),
        "current_fresh_overlap_days": int(fresh_stats["n"]),
        "delta_local_mean_vs_k1321": float(local_stats["mean"] - k1321_ratio["mean"]),
        "delta_fresh_mean_vs_k1321": float(fresh_stats["mean"] - k1321_ratio["mean"]),
        "delta_local_cv_vs_k1321": float(local_stats["cv"] - k1321_ratio["cv"]),
        "delta_fresh_cv_vs_k1321": float(fresh_stats["cv"] - k1321_ratio["cv"]),
    }

    figure_name = plot_ratio(local_ratio, fresh_ratio)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "VIXTWN 252-day gate update with VIX source freshness audit",
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "related_experiments": ["K1181", "K1308", "K1321"],
        "progress_to_252": progress,
        "data_sources": {
            "vixtwn": vixtwn_meta,
            "local_vix_primary": local_vix_meta,
            "fresh_vix_audit": fresh_vix_meta,
        },
        "cleaning": {
            "dedup_rule": 'sort by date, drop_duplicates(date, keep="first")',
            "alignment": "intersection on date labels only",
            "lookahead": "not applicable; descriptive stability audit only",
        },
        "primary_local_gate": {
            "purpose": "strictly comparable continuation of K1321 using the same local VIX source family",
            "ratio_stats": local_stats,
        },
        "fresh_vix_audit": {
            "purpose": "check whether the local gate is materially distorted by stale VIX pairing data",
            "ratio_stats": fresh_stats,
        },
        "source_freshness_gap": freshness_gap,
        "comparison_to_k1321": comparison_to_k1321,
        "baseline_comparison": {
            "k1181_mean": K1181_BASELINE_MEAN,
            "k1181_cv": K1181_BASELINE_CV,
        },
        "verdict": {
            "target_reached": progress["target_reached"],
            "stable_under_local_gate": False,
            "stable_under_fresh_audit": False,
            "summary": (
                "NOT_READY_AND_UNSTABLE: VIXTWN has only 116 unique days, far below the "
                "252-day gate. Under both the old local VIX pairing and a fresh experiment-"
                "scoped ^VIX snapshot, the ratio remains above K1181's 1.3906 baseline, "
                "dispersion is elevated, and the time trend is strongly positive."
            ),
        },
        "key_findings": [
            (
                f"252-day gate progress is {unique_vixtwn_days}/{TARGET_DAYS} "
                f"({progress['completion_ratio']:.1%}); the formal one-year validation is not ready."
            ),
            (
                f"Primary local pairing yields n={local_stats['n']} through {local_stats['end']}, "
                f"mean={local_stats['mean']:.4f}, CV={local_stats['cv']:.4f}."
            ),
            (
                f"Fresh ^VIX pairing extends overlap to n={fresh_stats['n']} through {fresh_stats['end']}, "
                f"mean={fresh_stats['mean']:.4f}, CV={fresh_stats['cv']:.4f}."
            ),
            (
                f"Local VIX source is stale at {local_vix_meta['end']} while VIXTWN already reaches "
                f"{vixtwn_meta['end']}; freshness audit adds {freshness_gap['overlap_gain_from_fresh_vix']} "
                f"paired days but does not restore stability."
            ),
        ],
        "artifacts": {
            "figure": figure_name,
            "fresh_vix_snapshot": fresh_vix_meta["path"],
        },
    }

    RESULTS_PATH.write_text(json.dumps(rounded(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(rounded(results), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
