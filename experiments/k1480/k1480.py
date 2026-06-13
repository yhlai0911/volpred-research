#!/usr/bin/env python3
"""K1480: feasibility audit for 0050 constituent-change fragility study."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1480_results.json"


def main() -> None:
    local_price_sources = [
        "storage/macro/yf_0050.TW.csv",
        "experiments/k1090b/data/0050.TW.csv",
        "experiments/k1406/data/0050.TW.csv",
        "experiments/k1411/data/T0050.csv",
    ]

    required_event_table_schema = [
        "announcement_date",
        "effective_date",
        "ticker",
        "event_type",
        "source_url",
        "source_title",
    ]

    results = {
        "experiment_id": "k1480",
        "title": "Feasibility audit for 0050 constituent-change fragility event study",
        "run_timestamp": __import__("pandas").Timestamp.now("UTC").isoformat(),
        "verdict": {
            "overall": "BLOCKED_ON_DATA",
            "can_honestly_run_event_study_now": False,
            "plain_english": (
                "The repo contains 0050 price history but not a canonical historical constituent-change "
                "event table. Without official add/delete events, any event study would be fabricated or "
                "hand-assembled from unstable secondary sources."
            ),
        },
        "available_local_inputs": {
            "price_series_examples": local_price_sources,
            "historical_constituent_change_event_table_found": False,
            "official_review_archive_found_locally": False,
        },
        "minimum_required_canonical_input": {
            "table_name": "0050_constituent_change_events.csv",
            "required_columns": required_event_table_schema,
            "why_needed": (
                "Event-study / DiD design requires exact announcement dates, effective dates, and add/delete "
                "membership events before any volatility inference can be trusted."
            ),
        },
        "recommended_next_step": {
            "phase_1": "Build canonical historical event table from official FTSE/TWSE/Yuanta sources",
            "phase_2": "Run add/delete event-study on abs_ret, park_var, and idiosyncratic volatility",
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")


if __name__ == "__main__":
    main()
