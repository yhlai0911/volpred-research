#!/usr/bin/env python3
"""K1484: feasibility audit for Taiwan typhoon-holiday volatility study."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1484_results.json"

PRICE_0050 = ROOT / "storage" / "macro" / "yf_0050.TW.csv"
SEARCH_ROOTS = ["storage", "experiments", "data", "docs"]


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
    }


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
    tw50 = series_summary(PRICE_0050, "0050.TW")
    typhoon_related = find_related_files(["typhoon", "颱風", "weather", "cwb"])
    taiex_related = find_related_files(["taiex", "txf", "taifex", "twse", "holiday"])

    return {
        "experiment_id": "k1484",
        "title": "Feasibility audit for Taiwan typhoon-holiday volatility mechanism study",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "The repo has local 0050.TW price history, but it lacks a canonical typhoon-holiday event table "
                "and lacks local TAIEX / index-futures price series. That means the requested reopening-gap and "
                "holiday-mechanism study cannot yet be executed honestly."
            ),
        },
        "research_question": {
            "core": "Do typhoon landfalls and typhoon holidays create systematic reopening volatility in Taiwan markets?",
            "proposed_design": [
                "Typhoon landfall / warning / market-closure event table",
                "Reopen-day gap and realized-vol study on TAIEX / TXF / 0050.TW",
                "Compare against ordinary long-holiday reopenings",
            ],
        },
        "available_local_inputs": {
            "price_series": [tw50],
            "typhoon_or_cwb_files": typhoon_related,
            "taiex_txf_or_holiday_files": taiex_related,
            "has_0050_price_history": True,
            "has_taiex_or_txf_local_series": False,
            "has_canonical_typhoon_holiday_event_table": False,
        },
        "blocking_conditions": [
            {
                "type": "missing_event_table",
                "detail": (
                    "No canonical typhoon-holiday event table was found. The study needs exact dates for landfall, "
                    "warnings, closure decisions, and reopening days."
                ),
            },
            {
                "type": "missing_market_series",
                "detail": (
                    "Local 0050.TW exists, but the broader target design explicitly references TAIEX and TAIFEX. "
                    "Those local series were not found in reusable canonical form."
                ),
            },
            {
                "type": "control_group_not_defined",
                "detail": (
                    "The question requires comparison against ordinary long holidays, but there is no canonical "
                    "Taiwan market-holiday classification table in repo."
                ),
            },
        ],
        "required_canonical_inputs": {
            "typhoon_holiday_event_table": {
                "required_columns": [
                    "event_date",
                    "event_name",
                    "landfall_date",
                    "market_closed",
                    "reopen_date",
                    "source_url",
                ],
                "why_needed": "Needed to distinguish landfall risk from closure/reopening mechanism."
            },
            "market_price_cache": {
                "required_files": [
                    "storage/macro/yf_0050.TW.csv",
                    "storage/macro/yf_TAIEX.csv or equivalent",
                    "storage/macro/yf_TXF.csv or equivalent",
                ],
                "why_needed": "Needed to separate ETF, cash-index, and futures reopening responses."
            },
            "holiday_calendar_table": {
                "required_columns": [
                    "date",
                    "holiday_type",
                    "is_typhoon_related",
                ],
                "why_needed": "Needed for the non-typhoon long-holiday control group."
            },
        },
        "related_prior_findings": [
            {
                "reference": "K1481",
                "lesson": "Taiwan-specific event studies often fail on missing canonical event tables even when local price history exists.",
            },
            {
                "reference": "Taiwan local advantage backlog",
                "lesson": "The value of this idea comes from local institutional detail, so using hand-picked dates would defeat the point."
            },
        ],
        "recommended_next_step": {
            "phase_1": "Build a canonical typhoon-holiday event table from CWB / exchange closure notices.",
            "phase_2": "Pin local TAIEX / TXF price series alongside 0050.TW.",
            "phase_3": "Run reopening-gap and realized-vol comparisons vs ordinary long holidays.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
