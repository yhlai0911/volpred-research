"""Summary stats reproducer for Paper 9 garch-x-vix Table 1.

Outputs Table 1 cells (Mean ann. VIX / Std ann. SPY / Skewness / Kurtosis /
Min / Max / N) for both Full Sample and OOS (2019-01-02 onward) splits.
Source: paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv (pinned
snapshot, auto_adjust=False per .claude/rules/paper-workflow.md).

Resolves the three "no-source" cells flagged in
storage/next_tasks.json::Data_summary_script_SPY_VIX:
- SPY ann.std (full sample)   = 0.188
- VIX ann.mean (OOS)          = 22.14
- VIX ann.mean (full sample)  = 18.97

Usage: uv run python paper/garch-x-vix/scripts/summary_stats.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

PAPER_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = PAPER_DIR / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv"
OUTPUT_PATH = PAPER_DIR / "results" / "summary_stats.json"

FULL_SAMPLE_START = "2005-01-01"
OOS_START = "2019-01-02"
TRADING_DAYS_PER_YEAR = 252


def _stats(returns_or_levels: pd.Series, *, is_returns: bool) -> dict:
    """Annualized mean/std for returns; raw moments + level mean for VIX."""
    s = returns_or_levels.dropna()
    if is_returns:
        mean_ann = float(s.mean() * TRADING_DAYS_PER_YEAR)
        std_ann = float(s.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        mean_ann = float(s.mean())
        std_ann = float(s.std(ddof=1))
    return {
        "mean": mean_ann,
        "std": std_ann,
        "skewness": float(s.skew()),
        "excess_kurtosis": float(s.kurt()),
        "min": float(s.min()),
        "max": float(s.max()),
        "n": int(s.shape[0]),
    }


def main() -> int:
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # SPY log returns from spy_adj_close (auto_adjust=False snapshot per
    # paper-workflow.md). Drop pre-2007 NaNs implicitly via dropna.
    df["spy_logret"] = np.log(df["spy_adj_close"]).diff()

    # VIX uses level (close), not returns. Source column: vix_adj_close.
    df["vix_level"] = df["vix_adj_close"]

    # Paper 9 §1: "Using S&P 500 daily returns from 2005 to 2026 with an
    # out-of-sample (OOS) period spanning 2019-2026 (1,825 observations)"
    full = df[df["date"] >= FULL_SAMPLE_START].copy()
    oos = df[df["date"] >= OOS_START].copy()

    spy_full = _stats(full["spy_logret"], is_returns=True)
    spy_oos = _stats(oos["spy_logret"], is_returns=True)
    vix_full = _stats(full["vix_level"], is_returns=False)
    vix_oos = _stats(oos["vix_level"], is_returns=False)

    payload = {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "data_provenance": "yfinance auto_adjust=False snapshot, pinned per .claude/rules/paper-workflow.md",
        "full_sample_start": FULL_SAMPLE_START,
        "oos_start": OOS_START,
        "trading_days_per_year": TRADING_DAYS_PER_YEAR,
        "full_sample": {
            "spy_logret": spy_full,
            "vix_level": vix_full,
            "date_range": [
                str(full["date"].min().date()),
                str(full["date"].max().date()),
            ],
        },
        "oos_sample": {
            "spy_logret": spy_oos,
            "vix_level": vix_oos,
            "date_range": [
                str(oos["date"].min().date()),
                str(oos["date"].max().date()),
            ],
        },
        "table1_cells": {
            "vix_mean_ann_full": round(vix_full["mean"], 2),
            "vix_mean_ann_oos": round(vix_oos["mean"], 2),
            "spy_std_ann_full": round(spy_full["std"], 3),
            "spy_std_ann_oos": round(spy_oos["std"], 3),
            "spy_skewness_full": round(spy_full["skewness"], 2),
            "spy_skewness_oos": round(spy_oos["skewness"], 2),
            "vix_skewness_full": round(vix_full["skewness"], 2),
            "vix_skewness_oos": round(vix_oos["skewness"], 2),
            "spy_kurtosis_full": round(spy_full["excess_kurtosis"], 2),
            "spy_kurtosis_oos": round(spy_oos["excess_kurtosis"], 2),
            "vix_kurtosis_full": round(vix_full["excess_kurtosis"], 2),
            "vix_kurtosis_oos": round(vix_oos["excess_kurtosis"], 2),
            "spy_min_full": round(spy_full["min"], 3),
            "spy_max_full": round(spy_full["max"], 3),
            "spy_min_oos": round(spy_oos["min"], 3),
            "spy_max_oos": round(spy_oos["max"], 3),
            "vix_min_full": round(vix_full["min"], 2),
            "vix_max_full": round(vix_full["max"], 2),
            "vix_min_oos": round(vix_oos["min"], 2),
            "vix_max_oos": round(vix_oos["max"], 2),
            "n_full": spy_full["n"],
            "n_oos": spy_oos["n"],
        },
    }

    # Compare against current Paper 9 main.tex Table 1 claims to surface
    # any numeric drift (the original task motivation: 3 cells had no source
    # script). Per paper-workflow.md "腳本 / 資料 / 論文三方一致", drift is
    # reported honestly — fix is errata or paper edit, never fudge here.
    paper_table1_claimed = {
        "vix_mean_ann_full": 18.97,
        "vix_mean_ann_oos": 22.14,
        "spy_std_ann_full": 0.188,
        "spy_std_ann_oos": 0.213,
        "n_full": 5347,
        "n_oos": 1825,
    }
    cells = payload["table1_cells"]
    discrepancies = []
    for key, claimed in paper_table1_claimed.items():
        computed = cells.get(key)
        if computed is None:
            continue
        if isinstance(claimed, int):
            if abs(computed - claimed) > 0:
                discrepancies.append({
                    "field": key,
                    "paper_claim": claimed,
                    "snapshot_computed": computed,
                    "delta": computed - claimed,
                })
        else:
            if abs(computed - claimed) > 0.005:
                discrepancies.append({
                    "field": key,
                    "paper_claim": claimed,
                    "snapshot_computed": computed,
                    "delta_abs": round(abs(computed - claimed), 4),
                })
    payload["paper_table1_claimed"] = paper_table1_claimed
    payload["discrepancies_vs_paper"] = discrepancies

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["table1_cells"], indent=2))
    if discrepancies:
        print("\n[summary_stats] PAPER vs SNAPSHOT discrepancies:")
        for entry in discrepancies:
            print(f"  - {entry}")
    else:
        print("\n[summary_stats] no discrepancies — paper Table 1 matches snapshot")
    print(f"\n[summary_stats] wrote {OUTPUT_PATH.relative_to(PAPER_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
