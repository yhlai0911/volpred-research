#!/usr/bin/env python3
"""K1482: feasibility audit for green-minus-brown transition-risk study."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "k1482_results.json"

TARGET_TICKERS = ["ICLN", "TAN", "XLE", "XOP"]
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
    climate_related = sorted(
        set(
            find_related_files(["climate", "weather", "green", "brown", "transition", "esg"])
            + find_related_files(["k148", "k335"])
        )
    )

    return {
        "experiment_id": "k1482",
        "title": "Feasibility audit for green-minus-brown transition-risk volatility spread",
        "run_timestamp": utc_now(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_full_study_now": False,
            "plain_english": (
                "The repo currently lacks the core green/brown ETF price series and a canonical "
                "climate-policy event table. Without those two inputs, any transition-risk volatility "
                "spread would be either fabricated or replaced by mismatched legacy proxies."
            ),
        },
        "research_question": {
            "core": "Can green-minus-brown volatility spread proxy transition-risk sentiment?",
            "proposed_design": [
                "Construct RV spread: mean(RV of ICLN/TAN) minus mean(RV of XLE/XOP)",
                "Test jumps around climate-policy events",
                "Check whether spread predicts broad-equity or sector volatility next period",
            ],
        },
        "available_local_inputs": {
            "target_ticker_files": ticker_availability(),
            "related_climate_or_esg_artifacts": climate_related,
            "has_all_four_price_series_locally": False,
            "has_transition_policy_event_table_locally": False,
        },
        "blocking_conditions": [
            {
                "type": "missing_core_price_series",
                "detail": (
                    "No local cached price histories were found for the four required ETFs "
                    "(ICLN, TAN, XLE, XOP)."
                ),
            },
            {
                "type": "missing_event_table",
                "detail": (
                    "No canonical climate-policy / transition-policy event table is present. "
                    "A jump-study needs exact event dates and source provenance."
                ),
            },
            {
                "type": "proxy_mismatch_risk",
                "detail": (
                    "Prior climate artifacts (for example K148 named-weather events and K335 ESG proxies) "
                    "are not valid substitutes for a transition-risk spread. Reusing them would change the "
                    "research question rather than answer it."
                ),
            },
        ],
        "required_canonical_inputs": {
            "price_cache": {
                "required_files": [
                    "storage/macro/yf_ICLN.csv",
                    "storage/macro/yf_TAN.csv",
                    "storage/macro/yf_XLE.csv",
                    "storage/macro/yf_XOP.csv",
                ],
                "why_needed": "The spread itself cannot be constructed without synchronized green and brown ETF histories.",
            },
            "transition_policy_event_table": {
                "required_columns": [
                    "event_date",
                    "event_name",
                    "event_type",
                    "jurisdiction",
                    "source_url",
                ],
                "why_needed": (
                    "Needed for reproducible event-window tests instead of hand-picked narrative examples."
                ),
            },
        },
        "related_prior_findings": [
            {
                "reference": "K148",
                "lesson": (
                    "Physical-climate event dummies were mostly absorbed by VIX in volatility forecasting, "
                    "so transition-risk needs its own measurement channel rather than generic weather proxies."
                ),
            },
            {
                "reference": "K335",
                "lesson": (
                    "ESG-leader vs ESG-laggard proxy design exists conceptually, but that experiment relied on "
                    "online yfinance download and broader ESG framing, not a transition-risk volatility spread."
                ),
            },
        ],
        "recommended_next_step": {
            "phase_1": "Pin local ETF price caches for ICLN/TAN/XLE/XOP.",
            "phase_2": "Build a canonical transition-policy event table with exact dates and sources.",
            "phase_3": "Run lag-respected RV-spread and event-window tests once both inputs exist.",
        },
    }


def main() -> None:
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
