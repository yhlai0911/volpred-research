"""Regression invariants for the 2026-07-12 paper/K-id governance cleanup."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_k189_article_reviews_are_not_a_paper() -> None:
    tracker = json.loads((ROOT / "storage/paper_pipeline_status.json").read_text())
    paper_ids = [entry["paper"] for entry in tracker["papers"]]

    assert "k189_audit" not in paper_ids
    assert len(paper_ids) == len(set(paper_ids))
    assert not (ROOT / "paper/k189_audit").exists()
    assert (ROOT / "experiments/k189/reviews/codex_review_2026_06_11.md").is_file()
    assert (
        ROOT
        / "experiments/k189/reviews/codex_review_mile_48c8328b_2026_06_15.md"
    ).is_file()


def test_term_spread_uses_k1696_and_prg_keeps_k1544() -> None:
    assert not (ROOT / "experiments/K1544").exists()

    term = json.loads((ROOT / "experiments/K1696/K1696_results.json").read_text())
    prg = json.loads(
        (ROOT / "experiments/k1544_prg_fair_info_gjr/results.json").read_text()
    )

    assert term["experiment_id"] == "K1696"
    assert term["id_migration"] == {
        "renumbered_from": "K1544",
        "renumbered_at": "2026-07-12",
        "reason": "K-id collision with unrelated PRG fair-information experiment",
        "original_result_commit": "4ba6d9503",
        "research_outputs_changed": False,
    }
    assert prg["experiment_id"] == "k1544_prg_fair_info_gjr"
