#!/usr/bin/env python3
"""K1483: feasibility audit for physical-climate ETF volatility event study."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1483_results.json"

TARGET_TICKERS = ["KIE", "KBWP", "XLU"]
SEARCH_ROOTS = ["storage", "experiments", "data", "docs"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_related_files(tokens: list[str]) -> list[str]:
    matches: list[str] = []
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
                matches.append(str(path.relative_to(ROOT)))
    return sorted(matches)


def find_ticker_files(ticker: str) -> list[str]:
    pat = re.compile(rf"(^|[^A-Za-z]){re.escape(ticker.lower())}([^A-Za-z]|$)")
    matches: list[str] = []
    for rel in SEARCH_ROOTS:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            stem = path.stem.lower()
            name = path.name.lower()
            haystacks = [stem, name.replace(".", "_"), name.replace("-", "_")]
            if any(pat.search(h) for h in haystacks):
                matches.append(str(path.relative_to(ROOT)))
    return sorted(matches)


def ticker_availability() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ticker in TARGET_TICKERS:
        files = find_ticker_files(ticker)
        out[ticker] = {
            "local_price_file_found": False,
            "matching_files": files,
        }
    return out


def build_results() -> dict:
    weather_related = sorted(
        set(
            find_related_files(["noaa", "hurricane", "storm", "heat", "weather", "wildfire", "flood"])
            + find_related_files(["k148", "climate_event"])
        )
    )

    return {
        "experiment_id": "k1483",
        "title": "Feasibility audit for extreme-weather ETF volatility event study",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "The repo currently lacks local KIE/KBWP/XLU price caches and lacks a canonical NOAA-style "
                "event table. K148 provides a hand-curated precedent, but not a reusable canonical input for "
                "the requested insurance/utilities ETF event study."
            ),
        },
        "research_question": {
            "core": "Do extreme heat and hurricane events raise insurance and utilities ETF volatility?",
            "proposed_design": [
                "NOAA event-date table with event severity metadata",
                "ETF realized-volatility event study for KIE, KBWP, and XLU",
                "Dose-response by damage/severity and sector sensitivity",
            ],
        },
        "available_local_inputs": {
            "target_ticker_files": ticker_availability(),
            "related_weather_or_climate_artifacts": weather_related,
            "has_all_three_price_series_locally": False,
            "has_canonical_noaa_event_table_locally": False,
            "has_prior_manual_event_list_example": True,
        },
        "blocking_conditions": [
            {
                "type": "missing_core_price_series",
                "detail": (
                    "No local cached price histories were found for KIE, KBWP, and XLU. Without synchronized "
                    "sector ETF histories the requested event study cannot be reproduced offline."
                ),
            },
            {
                "type": "missing_canonical_event_table",
                "detail": (
                    "K148 embeds a manual named-disaster list in code, but the repo does not contain a canonical "
                    "NOAA-style event table with exact dates, categories, and source provenance."
                ),
            },
            {
                "type": "methodology_drift_risk",
                "detail": (
                    "Reusing K148 directly would silently change the target universe (SPY/XLE/DBA/KIE/USO) and "
                    "reuse a hand-curated event list, which is not the same as the requested KIE/KBWP/XLU design."
                ),
            },
        ],
        "required_canonical_inputs": {
            "price_cache": {
                "required_files": [
                    "storage/macro/yf_KIE.csv",
                    "storage/macro/yf_KBWP.csv",
                    "storage/macro/yf_XLU.csv",
                ],
                "why_needed": "Required to compute the sector RV panels before any event-window inference.",
            },
            "noaa_event_table": {
                "required_columns": [
                    "event_date",
                    "event_name",
                    "event_category",
                    "damage_usd_billion",
                    "source_url",
                ],
                "why_needed": "Needed for a reproducible event window and dose-response design instead of manual date picking.",
            },
        },
        "related_prior_findings": [
            {
                "reference": "K148",
                "lesson": (
                    "Physical-climate events can correlate with contemporaneous volatility, but the old study was "
                    "mostly absorbed by VIX and relied on online downloads plus a hand-built event list."
                ),
            },
            {
                "reference": "K861",
                "lesson": (
                    "Climate/macro shock proxies can produce publishable asymmetries, but proxy-based results are "
                    "not interchangeable with a true ETF event-study design."
                ),
            },
        ],
        "recommended_next_step": {
            "phase_1": "Pin local ETF price caches for KIE, KBWP, and XLU.",
            "phase_2": "Build a canonical NOAA-derived event table with severity metadata.",
            "phase_3": "Run lag-respected event windows and damage-dose stratification once both inputs exist.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
