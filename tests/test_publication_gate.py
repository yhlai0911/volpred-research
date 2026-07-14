"""Regression tests for the reviewer publication gate.

Incident (2026-07-14): K1684's Codex review cleared it as research
(CONDITIONAL_PASS) while explicitly withholding it from publication —
"use limited to null and methodology knowledge; E2 required before
publication/paper routing" — and its README says 「不得據此寫 feed」. Nothing read
that condition, so refill_task_pool auto-created `K1684_article_general` and it
sat in the pending pool waiting for a writer agent.

The gate must catch that, and must NOT catch the 110 other CONDITIONAL_PASS
entries whose conditions have nothing to do with publication (blocking those
would starve the article pool).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from volpred.publication_gate import is_publication_blocked, publication_block_reason


K1684_ENTRY = {
    "experiment_id": "K1684",
    "verdict": "CONDITIONAL_PASS",
    "title": "K1684 R3：共同目標下 forecast-tail divergence 的 leg 1 無法建立",
    "content": "K1684 R3 是 forecast-tail-divergence E1 的誠實 null。",
    "codex_review": (
        "CONDITIONAL_PASS: core timing/support/gate/result packet verified; "
        "use limited to null and methodology knowledge; E2 required before "
        "publication/paper routing."
    ),
}


def test_k1684_is_blocked():
    """The exact entry that leaked an article task must be blocked."""
    assert is_publication_blocked(K1684_ENTRY)
    reason = publication_block_reason(K1684_ENTRY)
    assert "codex_review" in reason
    assert "before publication" in reason.lower()


def test_conditional_pass_without_publication_condition_is_not_blocked():
    """A CONDITIONAL_PASS whose condition is unrelated to publication stays open.

    Blanket-blocking the verdict would remove 110 of 825 K's from the pool.
    """
    entry = {
        "experiment_id": "K9999",
        "verdict": "CONDITIONAL_PASS",
        "content": "DM t=4.2 passes Harvey. Robust across three markets.",
        "codex_review": "CONDITIONAL_PASS: fix the fig-2 caption and note the 2020 gap in limitations.",
    }
    assert not is_publication_blocked(entry)


def test_clean_pass_is_not_blocked():
    entry = {
        "experiment_id": "K9998",
        "verdict": "PASS",
        "content": "Published results replicate across SPY/QQQ/0050.",
        "codex_review": "PASS: no blockers.",
    }
    assert not is_publication_blocked(entry)


@pytest.mark.parametrize(
    "field,text",
    [
        ("codex_review", "E2 required before publication/paper routing."),
        ("content", "Do not publish a Friday/OPEX auction-crowding RV claim from this proxy."),
        ("content", "因 gate 為 null，不得據此寫 feed 或選論文路線。"),
        ("review_notes", "This result is not publishable until the sample is extended."),
        ("codex_review", "禁止發佈：樣本不足。"),
    ],
)
def test_reviewer_prohibitions_are_caught(field, text):
    assert is_publication_blocked({"experiment_id": "KX", field: text})


def test_mere_mention_of_publication_is_not_a_block():
    """Precision guard: a false positive silently deletes a publishable result."""
    entry = {
        "experiment_id": "K9997",
        "verdict": "PASS",
        "content": (
            "Consistent with the publication-bias literature; the effect was published "
            "in 2024 and survives our replication."
        ),
    }
    assert not is_publication_blocked(entry)


def test_live_knowledge_base_block_set_is_small():
    """Guard against a future phrase widening the gate into a content black hole.

    If this ever fails, the new phrase is over-matching — tighten it rather than
    raising the bound.
    """
    knowledge = json.loads((ROOT / "storage/memory/knowledge.json").read_text())
    entries = knowledge if isinstance(knowledge, list) else knowledge.get("entries", [])
    by_k = {e["experiment_id"]: e for e in entries if e.get("experiment_id")}
    blocked = [k for k, e in by_k.items() if is_publication_blocked(e)]
    assert "K1684" in blocked
    assert len(blocked) <= 10, f"gate over-matching ({len(blocked)} blocked): {blocked}"


def test_candidate_builder_excludes_blocked_k():
    """End-to-end: the built candidate file must not contain a blocked K."""
    candidates_path = ROOT / "storage/publication_candidates.json"
    if not candidates_path.exists():
        pytest.skip("publication_candidates.json not built")
    payload = json.loads(candidates_path.read_text())
    k_ids = {c.get("k_id") for c in payload.get("candidates", [])}
    assert "K1684" not in k_ids
