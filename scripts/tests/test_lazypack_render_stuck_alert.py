"""The `lazypack_render_stuck` alert must fire on the 2026-07-11 incident state.

A general-reader draft cannot be released without its `## 懶人包圖組` section, and
that section is appended by the async render job. When the render failed for
mile_531e4c87 (K1683), the article became quietly un-releasable and NOTHING said
so — it surfaced three shifts later, sideways, as a PHASE-Z orphan-file alert.

An alert that cannot be shown to fire on the state it was built for is decoration.
These tests reconstruct that state and assert it breaches, and — just as important
— that the rescue paths clear it, so the alert cannot nag about work already done.

Run: uv run --extra dev python -m pytest scripts/tests/test_lazypack_render_stuck_alert.py -v
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops.alerts import (
    LAZYPACK_STUCK_CRITICAL_HOURS,
    _parse_lazypack_render_state,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
ARTICLE = "mile_531e4c87"
SECTION = "## 懶人包圖組\n\n![panel](https://example/1.png)\n"


def _storage(tmp_path: Path, *, jobs: list[dict], article_content: str) -> str:
    queue = tmp_path / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    for job in jobs:
        (queue / f"{job['id']}.json").write_text(json.dumps(job), encoding="utf-8")

    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text(json.dumps([
        {"id": ARTICLE, "status": "draft", "content": f"# 內文\n{article_content}"},
    ]), encoding="utf-8")
    return str(tmp_path)


def _job(job_id: str, status: str, *, hours_ago: float = 2.0,
         article: str = ARTICLE) -> dict:
    return {
        "id": job_id,
        "status": status,
        "exit_code": 2 if status == "failed" else 0,
        "completed_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "args": ["run", "--article-id", article, "--experiment", "k1683"],
    }


def test_fires_on_the_incident_state(tmp_path):
    """Render failed, article has no section → stranded, and we say so."""
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed")],
        article_content="",  # the section never landed — this is the incident
    )

    result = _parse_lazypack_render_state(storage, NOW)

    assert result["breached"] is True, (
        "the render failed and the article has no 懶人包圖組 section — it cannot be "
        "released, and this is exactly the state that went unsignalled for 3 shifts"
    )
    assert result["level"] == "warn"
    stranded = result["details"]["stranded"]
    assert [s["article_id"] for s in stranded] == [ARTICLE]


def test_escalates_to_critical_after_a_day(tmp_path):
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed",
                   hours_ago=LAZYPACK_STUCK_CRITICAL_HOURS + 1)],
        article_content="",
    )

    assert _parse_lazypack_render_state(storage, NOW)["level"] == "critical"


def test_a_completed_retry_clears_it(tmp_path):
    """The `-r2` rescue is what a human did by hand, twice. Honour it."""
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed"),
              _job(f"lazypack-{ARTICLE}-r2", "completed", hours_ago=1.0)],
        article_content="",
    )

    assert _parse_lazypack_render_state(storage, NOW)["breached"] is False


def test_a_queued_retry_suppresses_the_nag(tmp_path):
    """A retry already waiting on the worker is not a thing to alert about."""
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed"),
              _job(f"lazypack-{ARTICLE}-r2", "queued", hours_ago=0.1)],
        article_content="",
    )

    assert _parse_lazypack_render_state(storage, NOW)["breached"] is False


def test_section_present_means_nothing_is_stranded(tmp_path):
    """The job record says failed, but the panels are on the article. Not stuck."""
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed")],
        article_content=SECTION,
    )

    assert _parse_lazypack_render_state(storage, NOW)["breached"] is False


def test_clean_queue_does_not_breach(tmp_path):
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "completed")],
        article_content=SECTION,
    )

    result = _parse_lazypack_render_state(storage, NOW)
    assert result["breached"] is False
    assert result["level"] == "info"


def test_unreadable_job_file_does_not_crash_the_hourly_check(tmp_path):
    """A corrupt queue record must not take the whole alert path down with it."""
    storage = _storage(
        tmp_path,
        jobs=[_job(f"lazypack-{ARTICLE}", "failed")],
        article_content="",
    )
    (Path(storage) / "ops" / "compute_queue" / "lazypack-broken.json").write_text(
        "{not json", encoding="utf-8")

    result = _parse_lazypack_render_state(storage, NOW)

    assert result["breached"] is True  # the real one still surfaces
