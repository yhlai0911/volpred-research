"""Regression gate for the 2026-07-13 release-pool starvation (boss msg 660).

The incident: the draft pool held 7 articles and released NOTHING for 6.5h. Every
draft sat in one narrative cluster, the release gate blocks a cluster once 2 of the
last 3 published share it, so `eligible` was 0 while `draft` read 7 — a pool that
looks stocked and is entirely unreleasable. Refill kept topping it up by COUNT,
blind to the gate, so it manufactured more dead stock every tick.

These tests pin the layer-2 invariant: refill plans against the SAME gate release
enforces, and a cluster may not occupy more than its quota of the pipeline.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from volpred.ops.content import (  # noqa: E402
    make_narrative_cluster_classifier,
    release_cluster_planner_state,
)


def _storage(tmp_path: Path, feed: list[dict]) -> str:
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "feed.json").write_text(
        json.dumps(feed, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "memory" / "knowledge.json").write_text("[]", encoding="utf-8")
    return str(tmp_path)


def _published(idx: int, title: str) -> dict:
    return {
        "id": f"pub_{idx}",
        "title": title,
        "status": "published",
        "audience": "general",
        "published_at": f"2026-07-1{idx}T00:00:00+00:00",
        "tags": [],
    }


def _draft(idx: int, title: str) -> dict:
    return {
        "id": f"draft_{idx}",
        "title": title,
        "status": "draft",
        "audience": "general",
        "tags": [],
    }


VIX_TITLES = [
    "VIX 期限結構倒掛後的 30 天",
    "VIX 為什麼在崩盤前不動",
    "VIX 與實現波動的價差怎麼收斂",
    "VIX 曲線的隱含成本",
]


def test_planner_reports_the_gate_that_starved_the_pool(tmp_path):
    """The deadlock state must be legible to refill: cluster blocked + pool saturated."""
    feed = [_published(1, VIX_TITLES[0]), _published(2, VIX_TITLES[1]), _published(3, "HAR-RV 的落後期怎麼選")]
    feed += [_draft(i, t) for i, t in enumerate(VIX_TITLES)]
    state = release_cluster_planner_state(storage_dir=_storage(tmp_path, feed))

    assert "vix" in state["blocked_clusters"], "2-of-last-3 published are VIX → gate blocks it"
    assert state["pipeline_counts"]["vix"] >= state["threshold"], "pool is already VIX-saturated"


def test_refill_will_not_stock_a_cluster_the_gate_cannot_drain(tmp_path, monkeypatch):
    """The actual regression: candidates all in a saturated cluster → add NOTHING.

    Pre-fix this queued more VIX article tasks, which became more unreleasable VIX
    drafts. Adding zero here is the honest outcome — the shortfall is a content-supply
    gap, and it must be reported as one rather than padded with drafts that can't ship.
    """
    import refill_task_pool as rtp

    feed = [_published(1, VIX_TITLES[0]), _published(2, VIX_TITLES[1]), _published(3, "HAR-RV 的落後期怎麼選")]
    feed += [_draft(i, t) for i, t in enumerate(VIX_TITLES)]
    storage = _storage(tmp_path, feed)

    monkeypatch.setattr(
        rtp, "release_cluster_planner_state", None, raising=False
    )  # ensure we exercise the real import path below
    import volpred.ops.content as content

    monkeypatch.setattr(
        content,
        "release_cluster_planner_state",
        lambda **_: release_cluster_planner_state(storage_dir=storage),
    )
    monkeypatch.setattr(
        content,
        "make_narrative_cluster_classifier",
        lambda **_: make_narrative_cluster_classifier(storage_dir=storage),
    )

    budget = rtp._ClusterBudget([])
    assert budget.enabled

    vix_candidates = [
        {"k_id": "K9001", "title": "VIX 的隱含波動溢酬還剩多少", "score": 4},
        {"k_id": "K9002", "title": "VIX 反向 ETF 的滑價", "score": 4},
    ]
    for cand in vix_candidates:
        cluster = budget.cluster_of(cand)
        assert cluster == "vix"
        assert not budget.allows(cluster), "VIX pipeline quota is already full"

    fresh = {"k_id": "K9003", "title": "GJR-GARCH 的槓桿項在台股有多大", "score": 4}
    fresh_cluster = budget.cluster_of(fresh)
    assert fresh_cluster != "vix"
    assert budget.allows(fresh_cluster), "a different cluster must still be refillable"


def test_in_flight_article_tasks_count_against_the_quota(tmp_path, monkeypatch):
    """Queued-but-unwritten article tasks are pipeline stock too.

    Without charging them, a slow writer queue lets refill re-stack the same cluster
    tick after tick — the pool looks empty of drafts while N same-cluster tasks are
    already in flight to fill it.
    """
    import refill_task_pool as rtp
    import volpred.ops.content as content

    storage = _storage(tmp_path, [])  # empty feed: nothing blocked, nothing in pool
    monkeypatch.setattr(
        content,
        "release_cluster_planner_state",
        lambda **_: release_cluster_planner_state(storage_dir=storage),
    )
    monkeypatch.setattr(
        content,
        "make_narrative_cluster_classifier",
        lambda **_: make_narrative_cluster_classifier(storage_dir=storage),
    )

    in_flight = [
        {"task_type": "daily_article", "status": "pending", "title": VIX_TITLES[0]},
        {"task_type": "daily_article", "status": "in_progress", "title": VIX_TITLES[1]},
        {"task_type": "daily_article", "status": "succeeded", "title": VIX_TITLES[2]},
    ]
    budget = rtp._ClusterBudget(in_flight)

    assert budget.counts.get("vix") == 2, "only ACTIVE tasks are stock; succeeded is not"
    assert not budget.allows("vix"), "2 in-flight VIX articles already fill the quota"


def test_budget_fails_open_when_the_planner_is_unavailable(monkeypatch):
    """A planner fault must not dry the pool — fail open, but audibly (no silent skip)."""
    import refill_task_pool as rtp
    import volpred.ops.content as content

    def _boom(**_):
        raise RuntimeError("feed unreadable")

    monkeypatch.setattr(content, "release_cluster_planner_state", _boom)

    budget = rtp._ClusterBudget([])
    assert not budget.enabled
    assert budget.allows("vix"), "fail-open: refill keeps working without cluster planning"
    assert budget.cluster_of({"k_id": "K1", "title": VIX_TITLES[0]}) is None


def test_unclassifiable_candidates_are_never_budgeted(tmp_path, monkeypatch):
    """We can't cap a cluster we can't name; refusing on a guess would dry the pool."""
    import refill_task_pool as rtp
    import volpred.ops.content as content

    storage = _storage(tmp_path, [])
    monkeypatch.setattr(
        content,
        "release_cluster_planner_state",
        lambda **_: release_cluster_planner_state(storage_dir=storage),
    )
    monkeypatch.setattr(
        content,
        "make_narrative_cluster_classifier",
        lambda **_: make_narrative_cluster_classifier(storage_dir=storage),
    )

    budget = rtp._ClusterBudget([])
    assert budget.allows(None)
    for _ in range(10):
        budget.charge(None)
    assert budget.allows(None), "None is not a cluster and must never saturate"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
