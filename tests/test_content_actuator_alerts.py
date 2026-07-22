from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from volpred.ops import alerts


def _healthy_snapshot() -> dict:
    return {
        "daily_digest_uniqueness": {"status": "ok"},
        "publish_rhythm": {"status": "ok"},
        "title_format": {"findings": []},
        "arc_diversity": {"status": "ok"},
        "arc_dedup_overmatches": {"status": "ok", "count": 0, "candidates": []},
        "audience_classification": {
            "status": "ok",
            "summary": {"high_confidence": 0},
            "tiers": {"HIGH": [], "MEDIUM": [], "LOW": []},
        },
        "release_deadlock": {"status": "ok"},
        "frontend_render": {"status": "unknown"},
        "content_completeness": {
            "status": "ok",
            "lazypack": {"below_threshold": False},
        },
    }


def test_arc_overmatch_verdict_drives_hourly_alert_breach(monkeypatch) -> None:
    snapshot = _healthy_snapshot()
    snapshot["arc_dedup_overmatches"] = {
        "status": "overmatch",
        "count": 1,
        "candidates": [{"candidate_id": "mile_candidate"}],
    }
    monkeypatch.setattr(alerts, "content_quality_snapshot", lambda *args, **kwargs: deepcopy(snapshot))

    condition = alerts._parse_content_quality_state(
        "storage", datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    assert condition["breached"] is True
    assert "arc_dedup_overmatch" in condition["title"]
    assert "mile_candidate" in condition["body"]


def test_high_audience_candidate_drives_hourly_alert_breach(monkeypatch) -> None:
    snapshot = _healthy_snapshot()
    snapshot["audience_classification"] = {
        "status": "misclassified",
        "summary": {"high_confidence": 1},
        "tiers": {"HIGH": [{"id": "mile_research"}], "MEDIUM": [], "LOW": []},
    }
    monkeypatch.setattr(alerts, "content_quality_snapshot", lambda *args, **kwargs: deepcopy(snapshot))

    condition = alerts._parse_content_quality_state(
        "storage", datetime(2026, 7, 22, tzinfo=timezone.utc)
    )

    assert condition["breached"] is True
    assert "audience_classification" in condition["title"]
    assert "mile_research" in condition["body"]
