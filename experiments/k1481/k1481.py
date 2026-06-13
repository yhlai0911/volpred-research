#!/usr/bin/env python3
"""K1481: feasibility audit for Taiwan country-GPR volatility study."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1481_results.json"

PRICE_0050 = ROOT / "storage" / "macro" / "yf_0050.TW.csv"
PRICE_TWDX = ROOT / "storage" / "macro" / "yf_TWDX.csv"

EVENT_DATES = {
    "pelosi_taiwan_visit": "2022-08-02",
    "taiwan_presidential_election": "2024-01-13",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yf_cache(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=2)
    df.columns = ["date", "close", "high", "low", "open", "volume"]
    df["date"] = pd.to_datetime(df["date"], utc=False)
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    for col in ["close", "high", "low", "open", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def series_summary(path: Path, label: str) -> dict:
    df = load_yf_cache(path)
    return {
        "label": label,
        "path": str(path.relative_to(ROOT)),
        "rows": int(len(df)),
        "start": df["date"].min().date().isoformat(),
        "end": df["date"].max().date().isoformat(),
        "close_first": float(df["close"].iloc[0]),
        "close_last": float(df["close"].iloc[-1]),
    }


def event_window_coverage(path: Path, event_date: str, window: int = 20) -> dict:
    df = load_yf_cache(path)
    event_ts = pd.Timestamp(event_date)
    before = int((df["date"] < event_ts).sum())
    after = int((df["date"] > event_ts).sum())
    return {
        "event_date": event_date,
        "has_full_pre_window": before >= window,
        "has_full_post_window": after >= window,
        "available_pre_obs": before,
        "available_post_obs": after,
    }


def find_local_gpr_candidates() -> list[str]:
    matches: list[str] = []
    for rel in ("storage", "experiments", "data", "docs"):
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if any(token in name for token in ("gpr", "geopolit", "iacoviello", "caldara")):
                matches.append(str(path.relative_to(ROOT)))
    return sorted(matches)


def build_results() -> dict:
    local_gpr_files = find_local_gpr_candidates()
    tw50_summary = series_summary(PRICE_0050, "0050.TW")
    twdx_summary = series_summary(PRICE_TWDX, "USD/TWD")

    event_windows = {
        "0050.TW": {name: event_window_coverage(PRICE_0050, dt) for name, dt in EVENT_DATES.items()},
        "USD/TWD": {name: event_window_coverage(PRICE_TWDX, dt) for name, dt in EVENT_DATES.items()},
    }

    return {
        "experiment_id": "k1481",
        "title": "Feasibility audit for Taiwan country-GPR and Taiwan volatility study",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "Local Taiwan market price inputs exist, but the repo lacks a canonical Taiwan "
                "country-GPR time series and publication-lag metadata. Any predictive regression "
                "or event-window claim would currently rely on fabricated or timing-ambiguous inputs."
            ),
        },
        "research_question": {
            "core": "Can Taiwan-specific geopolitical risk pricing explain or predict Taiwan equity and FX volatility?",
            "proposed_design": [
                "Monthly Taiwan country-GPR vs 0050.TW realized volatility",
                "Monthly Taiwan country-GPR vs USD/TWD volatility",
                "Event windows around August 2022 and January 2024"
            ],
        },
        "available_local_inputs": {
            "price_series": [tw50_summary, twdx_summary],
            "event_window_coverage": event_windows,
            "local_gpr_related_files": local_gpr_files,
            "has_taiwan_country_gpr_raw_series": False,
        },
        "blocking_conditions": [
            {
                "type": "missing_core_series",
                "detail": (
                    "No local file contains a canonical Taiwan country-GPR monthly series. Existing "
                    "GPR artifacts are either prior experiment outputs or non-Taiwan proxy studies."
                ),
            },
            {
                "type": "release_timing_unknown",
                "detail": (
                    "Even if a monthly country-GPR level were obtained, the study needs release dates "
                    "or a conservative publication-lag rule. Using same-month GPR to explain same-month "
                    "volatility would violate the project's no-lookahead discipline."
                ),
            },
            {
                "type": "event_source_missing",
                "detail": (
                    "Taiwan-specific geopolitical event windows can be specified, but without the country-GPR "
                    "series the design collapses into pure narrative event study rather than the intended "
                    "country-risk measurement test."
                ),
            },
        ],
        "required_canonical_inputs": {
            "taiwan_country_gpr_monthly_csv": {
                "required_columns": [
                    "period",
                    "country",
                    "gpr_value",
                    "source_url",
                    "publication_date",
                ],
                "why_needed": (
                    "The publication date is required to enforce signal_t -> return_t+1 timing rather than "
                    "same-period leakage."
                ),
            },
            "optional_event_table": {
                "required_columns": [
                    "event_date",
                    "event_name",
                    "event_type",
                    "source_url",
                ],
                "why_needed": "Supports a reproducible event-window appendix once the core GPR series exists.",
            },
        },
        "related_prior_findings": [
            {
                "reference": "K100",
                "lesson": "Generic geopolitical proxies added little incremental volatility information beyond VIX.",
            },
            {
                "reference": "K446",
                "lesson": (
                    "Broad GPR daily index study found weak or reversed predictive content in general US-volatility "
                    "tests, so a Taiwan-specific extension needs genuinely distinct data rather than recycled proxies."
                ),
            },
        ],
        "recommended_next_step": {
            "phase_1": "Build and pin a canonical Taiwan country-GPR monthly file with publication dates.",
            "phase_2": "Run lag-respected monthly regressions on 0050.TW RV and USD/TWD volatility.",
            "phase_3": "Add August 2022 and January 2024 event windows as descriptive supplements only.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
