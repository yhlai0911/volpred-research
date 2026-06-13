#!/usr/bin/env python3
"""K1485: feasibility audit for FINRA off-exchange short-volume study."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1485_results.json"
SEARCH_ROOTS = ["storage", "experiments", "data", "docs"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_related_files(tokens: list[str]) -> list[str]:
    out: list[str] = []
    lowered = [t.lower() for t in tokens]
    for rel in SEARCH_ROOTS:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if any(token in name for token in lowered):
                out.append(str(path.relative_to(ROOT)))
    return sorted(out)


def build_results() -> dict:
    finra_related = find_related_files(
        ["finra", "trf", "short_volume", "off_exchange", "dark_pool", "short_interest"]
    )
    k186_files = find_related_files(["k186_volume_displacement"])
    k367_files = find_related_files(["k367_short_interest"])

    return {
        "experiment_id": "k1485",
        "title": "Feasibility audit for FINRA off-exchange short-volume ratio study",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "The repo does not contain canonical FINRA/TRF off-exchange short-volume daily files. "
                "Without true short-volume inputs, this task cannot be honestly completed as specified."
            ),
        },
        "research_question": {
            "core": "Does FINRA off-exchange short-volume ratio predict next-day realized volatility or extreme returns?",
            "proposed_design": [
                "Construct daily off-exchange short ratio from FINRA raw files",
                "Lag the ratio explicitly at t and predict t+1 realized-vol / tail outcomes",
                "Compare against simpler volume and fear proxies",
            ],
        },
        "available_local_inputs": {
            "finra_or_off_exchange_related_files": finra_related,
            "k186_proxy_files": k186_files,
            "k367_proxy_files": k367_files,
            "has_canonical_finra_short_volume_table": False,
            "has_true_off_exchange_short_ratio_panel": False,
        },
        "blocking_conditions": [
            {
                "type": "missing_finra_raw_data",
                "detail": (
                    "No canonical FINRA/TRF off-exchange short-volume raw files were found in local storage."
                ),
            },
            {
                "type": "proxy_not_equivalent",
                "detail": (
                    "K186 and K367 are proxy studies based on OHLCV, inverse ETF activity, and VIX composites. "
                    "They do not answer the exact FINRA off-exchange short-ratio question."
                ),
            },
            {
                "type": "missing_target_panel",
                "detail": (
                    "There is no canonical merged panel aligning lagged short-volume ratio with next-day realized-vol "
                    "and extreme-return targets."
                ),
            },
        ],
        "related_prior_findings": [
            {
                "reference": "K186",
                "lesson": (
                    "The repo has prior interest in dark-pool / institutional-flow themes, but K186 explicitly used "
                    "volume proxies because actual FINRA/TRF data were unavailable."
                ),
            },
            {
                "reference": "K367",
                "lesson": (
                    "Short-interest-style signals can be approximated with inverse ETF volume, but proxy evidence "
                    "cannot be relabeled as true FINRA off-exchange short-volume evidence."
                ),
            },
        ],
        "required_canonical_inputs": {
            "finra_daily_short_volume_table": {
                "required_columns": [
                    "date",
                    "ticker",
                    "short_volume",
                    "short_exempt_volume",
                    "total_volume",
                    "source_url",
                ],
                "why_needed": "Needed to construct the actual off-exchange short-volume ratio from primary data.",
            },
            "ratio_construction_layer": {
                "required_columns": [
                    "off_exchange_short_ratio",
                    "lagged_ratio",
                ],
                "why_needed": "Needed to enforce a causal t to t+1 design with explicit lagging.",
            },
            "price_and_target_panel": {
                "required_columns": [
                    "date",
                    "ticker",
                    "close",
                    "log_return",
                    "next_day_realized_vol_proxy",
                    "next_day_extreme_return_proxy",
                ],
                "why_needed": "Needed for the next-day volatility and tail-risk prediction targets.",
            },
        },
        "recommended_next_step": {
            "phase_1": "Pin canonical FINRA/TRF daily off-exchange short-volume files into local storage.",
            "phase_2": "Build a clean ratio-construction layer with explicit lagging.",
            "phase_3": "Merge with local price targets and run honest next-day prediction tests.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
