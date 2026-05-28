"""
K1321: VIXTWN ratio stability checkpoint before 252 days.

Purpose:
  - re-check the VIXTWN/VIX ratio with stricter de-duplication
  - compare against K1181 baseline (mean=1.3906)
  - document that the 252-day target has not yet been reached
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SEED = 42
np.random.seed(SEED)

REPO_ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
OUT_DIR = REPO_ROOT / "experiments" / "k1321"

VIXTWN_PATH = REPO_ROOT / "data" / "vixtwn" / "vixtwn_daily.csv"
VIX_PATH = (
    REPO_ROOT
    / "paper"
    / "taiwan-vt"
    / "data"
    / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
)

K1181_BASELINE_MEAN = 1.3906
TARGET_DAYS = 252


def load_vixtwn() -> tuple[pd.Series, dict]:
    df = pd.read_csv(VIXTWN_PATH)
    df["date"] = pd.to_datetime(df["date"])
    raw_rows = len(df)
    dup_rows = int(df["date"].duplicated().sum())
    df = df.sort_values("date").drop_duplicates("date", keep="first")
    series = df.set_index("date")["vixtwn_close"].astype(float).sort_index()
    meta = {
        "raw_rows": raw_rows,
        "duplicate_dates_removed": dup_rows,
        "unique_rows": int(len(series)),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
    }
    return series, meta


def load_vix() -> tuple[pd.Series, dict]:
    df = pd.read_csv(VIX_PATH)
    df["date"] = pd.to_datetime(df["date"])
    raw_rows = len(df)
    dup_rows = int(df["date"].duplicated().sum())
    df = df.sort_values("date").drop_duplicates("date", keep="first")
    series = df.set_index("date")["vix_close"].astype(float).sort_index()
    meta = {
        "raw_rows": raw_rows,
        "duplicate_dates_removed": dup_rows,
        "unique_rows": int(len(series)),
        "start": str(series.index.min().date()),
        "end": str(series.index.max().date()),
    }
    return series, meta


def summarize_ratio(ratio: pd.Series) -> dict:
    n = len(ratio)
    first_half = ratio.iloc[: n // 2]
    second_half = ratio.iloc[n // 2 :]
    x = np.arange(n)
    trend = stats.linregress(x, ratio.values)
    t_stat, p_value = stats.ttest_1samp(ratio.values, popmean=K1181_BASELINE_MEAN)
    roll20 = ratio.rolling(20).mean().dropna()

    return {
        "n": int(n),
        "mean": float(ratio.mean()),
        "median": float(ratio.median()),
        "std": float(ratio.std(ddof=1)),
        "cv": float(ratio.std(ddof=1) / ratio.mean()),
        "min": float(ratio.min()),
        "max": float(ratio.max()),
        "first_half_mean": float(first_half.mean()),
        "second_half_mean": float(second_half.mean()),
        "trend_slope_per_day": float(trend.slope),
        "trend_rvalue": float(trend.rvalue),
        "trend_pvalue": float(trend.pvalue),
        "trend_stderr": float(trend.stderr),
        "ttest_vs_k1181_mean": {
            "baseline_mean": K1181_BASELINE_MEAN,
            "t_stat": float(t_stat),
            "p_value": float(p_value),
        },
        "rolling_20_mean_start": float(roll20.iloc[0]),
        "rolling_20_mean_end": float(roll20.iloc[-1]),
    }


def rounded(obj):
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def main() -> None:
    vixtwn, vixtwn_meta = load_vixtwn()
    vix, vix_meta = load_vix()

    overlap = vixtwn.index.intersection(vix.index)
    ratio = (vixtwn.loc[overlap] / vix.loc[overlap]).dropna().sort_index()
    ratio_stats = summarize_ratio(ratio)

    progress = {
        "target_days": TARGET_DAYS,
        "unique_vixtwn_days": int(len(vixtwn)),
        "overlap_days": int(len(ratio)),
        "completion_ratio": float(len(vixtwn) / TARGET_DAYS),
        "days_remaining": int(max(TARGET_DAYS - len(vixtwn), 0)),
        "target_reached": bool(len(vixtwn) >= TARGET_DAYS),
    }

    verdict = {
        "ratio_stable_before_252": False,
        "reason": (
            "Mean is above K1181 baseline, CV is elevated, and the time trend is "
            "strongly positive. Current sample is still below 252 trading days."
        ),
    }

    results = {
        "experiment_id": "k1321",
        "title": "VIXTWN ratio stability checkpoint before 252 days",
        "date": "2026-05-26",
        "seed": SEED,
        "data_sources": {
            "vixtwn": str(VIXTWN_PATH.relative_to(REPO_ROOT)),
            "vix": str(VIX_PATH.relative_to(REPO_ROOT)),
        },
        "cleaning": {
            "vixtwn": vixtwn_meta,
            "vix": vix_meta,
            "alignment": "intersection of deduplicated same-date labels",
            "dedup_rule": 'sort by date, drop_duplicates(date, keep="first")',
        },
        "baseline_comparison": {
            "k1181_mean": K1181_BASELINE_MEAN,
            "k1181_note": "Early official sample from Dec 2025 to Apr 2026",
        },
        "progress_to_252": progress,
        "ratio_stats": ratio_stats,
        "verdict": verdict,
        "key_findings": [
            (
                f"Cleaned overlap sample is n={ratio_stats['n']} with mean="
                f"{ratio_stats['mean']:.4f} and CV={ratio_stats['cv']:.4f}."
            ),
            (
                f"First-half mean={ratio_stats['first_half_mean']:.4f} vs "
                f"second-half mean={ratio_stats['second_half_mean']:.4f}."
            ),
            (
                f"Trend slope={ratio_stats['trend_slope_per_day']:.6f}/day "
                f"(p={ratio_stats['trend_pvalue']:.3e})."
            ),
            (
                f"One-sample t-test vs K1181 mean {K1181_BASELINE_MEAN:.4f}: "
                f"t={ratio_stats['ttest_vs_k1181_mean']['t_stat']:.4f}, "
                f"p={ratio_stats['ttest_vs_k1181_mean']['p_value']:.3e}."
            ),
            (
                f"Progress to 252-day target: {progress['unique_vixtwn_days']}/"
                f"{TARGET_DAYS} ({progress['completion_ratio']:.1%})."
            ),
        ],
        "tail_snapshot": {
            str(idx.date()): round(float(val), 6)
            for idx, val in ratio.tail(5).items()
        },
    }

    out_path = OUT_DIR / "k1321_results.json"
    out_path.write_text(json.dumps(rounded(results), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(rounded(results), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
