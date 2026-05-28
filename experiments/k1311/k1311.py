#!/usr/bin/env python3
"""
K1311 scaffold and readiness diagnostic for the 252-day VIXTWN/VIX ratio gate.

This script intentionally does not overwrite K1308's intermediate findings.
It only measures local coverage against the pre-registered 252-day threshold.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1311"
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_PATH = SCRIPT_DIR / "k1311_results.json"
VIXTWN_PATH = PROJECT_ROOT / "data" / "vixtwn" / "vixtwn_daily.csv"
TARGET_DAYS = 252


@dataclass(frozen=True)
class CoverageSummary:
    path: str
    total_rows: int
    non_null_rows: int
    first_date: str | None
    last_date: str | None


def load_vixtwn(path: Path = VIXTWN_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing VIXTWN file: {path}")
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "vixtwn_close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing VIXTWN columns: {sorted(missing)}")
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df


def summarize(df: pd.DataFrame) -> CoverageSummary:
    non_null = df.dropna(subset=["vixtwn_close"]).copy()
    return CoverageSummary(
        path=str(VIXTWN_PATH.relative_to(PROJECT_ROOT)),
        total_rows=int(len(df)),
        non_null_rows=int(len(non_null)),
        first_date=non_null["date"].iloc[0].strftime("%Y-%m-%d") if len(non_null) else None,
        last_date=non_null["date"].iloc[-1].strftime("%Y-%m-%d") if len(non_null) else None,
    )


def readiness(summary: CoverageSummary) -> dict:
    current_n = summary.non_null_rows
    remaining = max(TARGET_DAYS - current_n, 0)
    pct = round(100 * current_n / TARGET_DAYS, 1) if TARGET_DAYS else 0.0
    verdict = "READY_FOR_252D_VALIDATION" if current_n >= TARGET_DAYS else "NOT_READY_BELOW_252D_GATE"
    return {
        "verdict": verdict,
        "current_n": current_n,
        "target_n": TARGET_DAYS,
        "pct_complete": pct,
        "remaining_trading_days": remaining,
        "notes": [
            "K1181 provided the early ratio baseline; K1308 already documented intermediate instability at 119 days.",
            "K1311 is a readiness gate, not a replacement for K1308's substantive findings.",
            "Do not upgrade narrative claims until the sample reaches the 252-day threshold.",
        ],
    }


def build_results() -> dict:
    df = load_vixtwn()
    coverage = summarize(df)
    gate = readiness(coverage)
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": "scaffold_with_local_diagnostic",
        "executed_full_experiment": False,
        "seed": SEED,
        "related_experiments": ["K1181", "K1308"],
        "research_question": "Once VIXTWN reaches ~252 trading days, does the VIXTWN/VIX ratio stabilize or remain time-varying?",
        "data_sources": {
            "vixtwn": asdict(coverage),
        },
        "readiness_gate": gate,
        "future_full_validation_plan": [
            "Recompute ratio distribution on the full 252-day sample",
            "Compare against K1181 and K1308 baselines with explicit sample-end dates",
            "Re-run rolling stability, time-trend, and structural-change diagnostics",
            "State clearly whether Paper 2 can still use a fixed ratio constant",
        ],
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
