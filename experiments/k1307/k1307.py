#!/usr/bin/env python3
"""
K1307 scaffold and readiness diagnostic for Taiwan 5-minute HAR-RV on 0050.TW.

This script does not claim a new forecasting result. It audits local sample
coverage and verifies whether the current 0050.TW 5-minute RV history is long
enough for a powered HAR-RV experiment.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1307"
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_PATH = SCRIPT_DIR / "k1307_results.json"
TW_RV_PATH = PROJECT_ROOT / "data" / "intraday" / "0050_TW_daily_rv.csv"
SPY_RV_PATH = PROJECT_ROOT / "data" / "intraday" / "SPY_daily_rv.csv"
MIN_HAR_LAG_DAYS = 22
MIN_TRAIN_DAYS = 30
POWERED_OOS_TARGET = 252


@dataclass(frozen=True)
class CoverageSummary:
    path: str
    total_rows: int
    non_null_rows: int
    first_non_null: str | None
    last_non_null: str | None


def load_rv_series(path: Path) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(f"Missing RV file: {path}")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if "rv_5min" not in df.columns:
        raise ValueError(f"Expected 'rv_5min' column in {path}")
    rv = df["rv_5min"].copy()
    rv.index = pd.to_datetime(rv.index).normalize()
    return rv.sort_index()


def summarize_series(path: Path, series: pd.Series) -> CoverageSummary:
    non_null = series.dropna()
    return CoverageSummary(
        path=str(path.relative_to(PROJECT_ROOT)),
        total_rows=int(len(series)),
        non_null_rows=int(len(non_null)),
        first_non_null=non_null.index[0].strftime("%Y-%m-%d") if len(non_null) else None,
        last_non_null=non_null.index[-1].strftime("%Y-%m-%d") if len(non_null) else None,
    )


def build_har_feature_frame(rv: pd.Series) -> pd.DataFrame:
    rv = rv.dropna().sort_index()
    frame = pd.DataFrame(index=rv.index)
    frame["target_rv_t"] = rv
    frame["rv_1d"] = rv.shift(1)  # signal.shift(1): no same-day leakage
    frame["rv_5d"] = rv.shift(1).rolling(5).mean()
    frame["rv_22d"] = rv.shift(1).rolling(22).mean()
    return frame.dropna()


def readiness_diagnostic(rv: pd.Series) -> dict:
    feature_frame = build_har_feature_frame(rv)
    usable_obs = int(len(feature_frame))
    max_oos_after_min_train = max(usable_obs - MIN_TRAIN_DAYS, 0)
    non_null_obs = int(rv.dropna().shape[0])

    if non_null_obs >= POWERED_OOS_TARGET:
        verdict = "READY_FOR_FULL_OOS"
    elif usable_obs >= MIN_TRAIN_DAYS and max_oos_after_min_train > 0:
        verdict = "NOT_READY_SAMPLE_TOO_SHORT"
    else:
        verdict = "NOT_READY_INSUFFICIENT_TRAINING_WINDOW"

    return {
        "verdict": verdict,
        "non_null_rv_days": non_null_obs,
        "har_feature_rows_after_lags": usable_obs,
        "min_har_lag_days": MIN_HAR_LAG_DAYS,
        "min_train_days": MIN_TRAIN_DAYS,
        "max_oos_obs_after_min_train": max_oos_after_min_train,
        "powered_oos_target_days": POWERED_OOS_TARGET,
        "meets_powered_threshold": non_null_obs >= POWERED_OOS_TARGET,
        "notes": [
            "This file is a sample-readiness diagnostic, not a full forecasting run.",
            "K1318 already showed methodology is viable but 0050.TW OOS power is too low in short samples.",
            "Use signal from t-1 to predict RV at t; explicit rv.shift(1) enforced in feature construction.",
        ],
    }


def build_results() -> dict:
    tw_rv = load_rv_series(TW_RV_PATH)
    spy_rv = load_rv_series(SPY_RV_PATH)
    tw_summary = summarize_series(TW_RV_PATH, tw_rv)
    spy_summary = summarize_series(SPY_RV_PATH, spy_rv)
    diagnostic = readiness_diagnostic(tw_rv)

    return {
        "experiment_id": EXPERIMENT_ID,
        "status": "scaffold_with_local_diagnostic",
        "executed_full_experiment": False,
        "seed": SEED,
        "related_experiments": ["K848", "K850", "K852", "K1318"],
        "research_question": "When 0050.TW 5-minute RV sample is long enough, can HAR-RV beat daily-proxy baselines on Taiwan volatility forecasting?",
        "data_sources": {
            "tw_rv": asdict(tw_summary),
            "spy_rv_reference": asdict(spy_summary),
        },
        "lookahead_certification": {
            "rule": "signal from t-1, target at t",
            "enforcement": [
                "rv_1d = rv.shift(1)",
                "rv_5d = rv.shift(1).rolling(5).mean()",
                "rv_22d = rv.shift(1).rolling(22).mean()",
            ],
        },
        "diagnostic": diagnostic,
        "success_criteria": {
            "current_turn": "Create traceable research package and local readiness gate.",
            "future_full_run": [
                "At least ~252 non-null 0050.TW RV days for a powered OOS comparison",
                "QLIKE-based forecast comparison against HAR-ABS / HAR-SQ / EWMA",
                "DM-HLN / Harvey threshold with honest null reporting if not significant",
            ],
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
