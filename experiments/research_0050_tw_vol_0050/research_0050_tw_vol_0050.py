#!/usr/bin/env python3
"""
research_0050_tw_vol_0050: backlog resolver
===========================================

This task resolves the pending backlog item:
  "除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）"

Instead of rerunning the same question, this script audits whether existing
canonical experiments already answer it.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().with_name("research_0050_tw_vol_0050_results.json")

K512 = ROOT / "experiments" / "k512" / "k512_tw_exdividend_results.json"
K917 = ROOT / "experiments" / "k917" / "k917_taiwan_ex_dividend_vol_results.json"
TOPICS = ROOT / "docs" / "research_archive" / "detailed_research_topics.md"
PROGRAM = ROOT / "research_program.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    k512 = load_json(K512)
    k917 = load_json(K917)

    k512_0050 = k512["assets_results"]["0050.TW"]["event_study"]
    k917_core = k917["core_test_summer_vs_other"]

    results = {
        "experiment_id": "RESEARCH_0050_TW_VOL_0050",
        "title": "Backlog Resolver — 0050.TW Ex-Dividend Volatility Question",
        "status": "RESOLVED_ALREADY_COVERED",
        "question": "Do ex-dividend periods materially raise 0050.TW volatility?",
        "canonical_sources": {
            "k512": str(K512.relative_to(ROOT)),
            "k917": str(K917.relative_to(ROOT)),
            "topics_doc": str(TOPICS.relative_to(ROOT)),
            "research_program": str(PROGRAM.relative_to(ROOT)),
        },
        "existing_evidence": {
            "k512_event_window": {
                "n_events": k512_0050["n_events"],
                "post_near_vs_control_t": k512_0050["tests"]["post_near_vs_control"]["t"],
                "post_near_vs_control_p": k512_0050["tests"]["post_near_vs_control"]["p"],
                "pre_vs_post_t": k512_0050["tests"]["pre_vs_post"]["t"],
                "pre_vs_post_p": k512_0050["tests"]["pre_vs_post"]["p"],
                "interpretation": (
                    "Specific 0050.TW ex-dividend event windows show a modest near-post-event "
                    "volatility lift in K512."
                ),
            },
            "k917_seasonal_cluster_test": {
                "summer_mean_rv": k917_core["summer_mean"],
                "other_mean_rv": k917_core["other_mean"],
                "welch_t": k917_core["welch_t"],
                "welch_p": k917_core["welch_p"],
                "cohens_d": k917_core["cohens_d"],
                "interpretation": (
                    "When the question is broadened to ex-dividend season / concentrated dividend months, "
                    "there is no statistically significant 0050.TW volatility regime shift."
                ),
            },
        },
        "resolution": {
            "answer": (
                "The backlog question is already effectively answered by existing experiments: "
                "K512 finds a local ex-dividend event-window uplift, but K917 rejects a broader, "
                "systematic seasonal-volatility effect for 0050.TW."
            ),
            "operational_decision": (
                "Do not re-run as a fresh experiment unless the question is narrowed further "
                "(for example, constituent-level clustering, ETF-vs-stock decomposition, or "
                "post-2026 extension)."
            ),
        },
        "closeout_actions": [
            "Treat this pending backlog item as covered by K512 + K917 evidence.",
            "Keep K1374/K1375 as the broader Taiwan ex-dividend extension line in research_program.",
            "Recycle the slot instead of duplicating the same 0050.TW ex-div question.",
        ],
    }

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
