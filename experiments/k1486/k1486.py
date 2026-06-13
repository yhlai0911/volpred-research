#!/usr/bin/env python3
"""K1486: feasibility audit for BTC ETF intraday-vol-structure study."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1486_results.json"
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
    btc_daily = sorted(
        {
            *find_related_files(["btc_usd.csv"]),
            *find_related_files(["btc-usd.csv"]),
        }
    )
    btc_hourly = sorted(
        {
            p
            for p in (
                find_related_files(["btc_1h"])
                + find_related_files(["btc-1h"])
                + find_related_files(["btc_hourly"])
                + find_related_files(["btc_60m"])
                + find_related_files(["btc_h1"])
            )
            if "btc" in p.lower()
        }
    )
    spot_etfs = sorted(
        {
            *find_related_files(["ibit"]),
            *find_related_files(["fbtc"]),
            *find_related_files(["arkb"]),
            *find_related_files(["bitb"]),
        }
    )
    k916_files = find_related_files(["k916_mfgjr_bitcoin"])

    return {
        "experiment_id": "k1486",
        "title": "Feasibility audit for BTC ETF intraday volatility-structure study",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "The repo has BTC daily history but no reusable 24/7 hourly BTC panel and no local spot-BTC-ETF "
                "dataset. Without intraday timestamps, the requested US-session versus non-US-session versus weekend "
                "volatility-structure study cannot be executed honestly."
            ),
        },
        "research_question": {
            "core": "Did the 2024 spot-BTC-ETF launch change when Bitcoin volatility occurs across the trading day and weekend?",
            "proposed_design": [
                "Use 24/7 BTC hourly data to split US cash-session / non-cash-session / weekend realized volatility",
                "Run a 2024-01 structural-break test around spot-BTC-ETF launch",
                "Assess whether volatility share shifted toward the traditional US market clock",
            ],
        },
        "available_local_inputs": {
            "btc_daily_files": btc_daily,
            "btc_intraday_hourly_files": btc_hourly,
            "spot_btc_etf_files": spot_etfs,
            "related_prior_experiment_files": k916_files,
            "has_btc_daily_data": len(btc_daily) > 0,
            "has_btc_hourly_panel": False,
            "has_local_spot_btc_etf_panel": False,
        },
        "blocking_conditions": [
            {
                "type": "missing_intraday_btc_panel",
                "detail": (
                    "BTC daily files exist, but no canonical 24/7 hourly BTC panel was found, so the session-share "
                    "decomposition cannot be constructed."
                ),
            },
            {
                "type": "missing_session_classification_layer",
                "detail": (
                    "There is no reusable local panel or rule layer that labels US cash-session, non-cash-session, "
                    "and weekend intervals with fixed timezone handling."
                ),
            },
            {
                "type": "missing_spot_etf_local_context",
                "detail": (
                    "No local IBIT/FBTC/ARKB/BITB dataset or canonical ETF event metadata was found. Existing daily "
                    "BTC studies cannot substitute for the event-context layer required by this question."
                ),
            },
        ],
        "related_prior_findings": [
            {
                "reference": "K916",
                "lesson": (
                    "The repo already studied daily BTC structural behavior and ETF-era subsamples, but K916 used "
                    "business-day daily data and cannot identify intraday or weekend volatility-share shifts."
                ),
            },
            {
                "reference": "BTC daily compendium in repo",
                "lesson": (
                    "There is enough daily BTC history for daily-vol questions, but this topic is specifically about "
                    "time-of-day structure, so daily files are insufficient."
                ),
            },
        ],
        "required_canonical_inputs": {
            "btc_hourly_price_panel": {
                "required_columns": [
                    "timestamp_utc",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
                "why_needed": "Needed to construct realized volatility by trading-time segment."
            },
            "session_classification_layer": {
                "required_columns": [
                    "timestamp_utc",
                    "is_us_cash_session",
                    "is_us_non_cash_session",
                    "is_weekend",
                ],
                "why_needed": "Needed to split BTC volatility into market-clock regimes with stable timezone rules."
            },
            "spot_btc_etf_event_context": {
                "required_columns": [
                    "event_date",
                    "event_name",
                    "event_type",
                    "source_url",
                ],
                "optional_extensions": [
                    "IBIT local price history",
                    "FBTC local price history",
                    "ARKB local price history",
                    "BITB local price history",
                ],
                "why_needed": "Needed to define the institutionalization breakpoint instead of using a vague date split."
            },
        },
        "recommended_next_step": {
            "phase_1": "Pin a canonical 24/7 BTC hourly panel into local storage.",
            "phase_2": "Build a timezone-stable session-classification layer for US cash / non-cash / weekend.",
            "phase_3": "Add spot-BTC-ETF event metadata and run structural-break tests on volatility shares.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
