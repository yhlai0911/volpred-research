from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refill_task_pool.py"
SPEC = importlib.util.spec_from_file_location("refill_task_pool", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_refill_skips_blank_title_candidates(tmp_path, monkeypatch):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    candidates = tmp_path / "storage" / "publication_candidates.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    candidates.write_text(
        json.dumps(
            {
                "top_10_uncovered": [
                    {
                        "k_id": "K1378",
                        "title": "",
                        "score": 4,
                        "reasons": ["robust inference"],
                        "verdict_preview": "stale robustness fix",
                        "audiences_covered": [],
                        "covered_by": [],
                    }
                ],
                "missing_research_top5": [],
                "missing_general_top5": [],
                "candidates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())

    result = MODULE.refill(target=3, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["reason"] == "no_new_candidates_passing_filter"
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert data == []


def test_archived_articles_count_as_feed_coverage(tmp_path, monkeypatch):
    """Regression: 2026-05-31 K274/K288/K319 dup refill.

    `_any_feed_coverage_kids` and `_kids_with_general_article` originally
    treated only (draft, published, scheduled) as coverage. 122 archived feed
    articles with K refs were invisible → audit_pending_kids dedup failed
    → refill created K274_article_general_v2 / K288_v2 / K319_v2 even though
    each K had an archived feed article.
    """
    feed = tmp_path / "storage" / "reports" / "feed.json"
    feed.parent.mkdir(parents=True, exist_ok=True)
    feed.write_text(
        json.dumps(
            [
                {
                    "id": "mile_archived_general",
                    "title": "K319 reader article",
                    "status": "archived",
                    "audience": "general",
                    "details": {"experiment_refs": ["K319"]},
                },
                {
                    "id": "mile_archived_research",
                    "title": "K274 deep dive",
                    "status": "archived",
                    "audience": "research",
                    "details": {"experiment_refs": ["K274"]},
                },
                {
                    "id": "mile_retracted_skip",
                    "title": "K999 should be ignored",
                    "status": "retracted",
                    "audience": "general",
                    "details": {"experiment_refs": ["K999"]},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)

    any_feed = MODULE._any_feed_coverage_kids()
    general = MODULE._kids_with_general_article()

    # Archived under any audience counts as feed coverage (audit_pending guard).
    assert "K319" in any_feed
    assert "K274" in any_feed
    # General-audience archived counts as general coverage (direct dedup).
    assert "K319" in general
    # Research-audience archived does NOT count as general coverage; the
    # audit_pending intersection handles it instead.
    assert "K274" not in general
    # Retracted is explicit "not coverage".
    assert "K999" not in any_feed
    assert "K999" not in general


def test_research_reader_friendly_still_allows_general_companion(tmp_path, monkeypatch):
    """Regression: 2026-06-06 candidate-pool saturation audit.

    The 2026-06-03 "7th belt" skip was too aggressive: if a research article
    title already sounded reader-friendly, refill suppressed the general
    companion entirely. That dried up legitimate dual-audience candidates such
    as K593/K683/K1021 even though publish-time gates already protect against
    research-style drafts and true (K-id, audience) duplicates.

    Current rule: refill should still enqueue the general companion. The
    audience gate / duplicate gate remain the final enforcement layer.
    """
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    candidates = tmp_path / "storage" / "publication_candidates.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    candidates.write_text(
        json.dumps(
            {
                "top_10_uncovered": [],
                "missing_research_top5": [],
                "missing_general_top5": [
                    {
                        "k_id": "K1120",
                        "title": "TLT FinStress regime-dependent",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "post-2022 regime",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_b8a4dc23",
                                "title": "長期美國公債的風險模型在 2022 年壞掉了——你的債券 ETF 需要一套「升息專用」的風控",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                    },
                    {
                        "k_id": "K9999",
                        "title": "should still queue",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "ok",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_jargon_title",
                                "title": "K9999: GARCH-X bootstrap p-value t-stat audit",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                    },
                ],
                "candidates": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())
    monkeypatch.setattr(MODULE, "_any_feed_coverage_kids", lambda: set())

    result = MODULE.refill(target=5, dry_run=False)
    assert result["ok"] is True
    added_ids = json.loads(next_tasks.read_text(encoding="utf-8"))
    ids = [t["id"] for t in added_ids]
    # Reader-friendly research coverage no longer suppresses the general queue.
    assert "K1120_article_general" in ids, (
        f"K1120 should remain eligible for a general companion; got {ids}"
    )
    # K9999 has academic-jargon-laden title (K-id, GARCH, bootstrap, p-value, t-stat)
    # → still eligible for general companion
    assert "K9999_article_general" in ids, (
        f"K9999 with jargon title should still queue; got {ids}"
    )


def test_research_cover_helper_acceptance():
    """Unit test for _research_cover_is_reader_friendly helper."""
    # Reader-friendly research title → True
    assert MODULE._research_cover_is_reader_friendly({
        "audiences_covered": ["research"],
        "covered_by": [{
            "audience": "research",
            "title": "升息週期下的長債風控",
        }],
    }) is True

    # Title with K-id → False (still jargony)
    assert MODULE._research_cover_is_reader_friendly({
        "audiences_covered": ["research"],
        "covered_by": [{
            "audience": "research",
            "title": "K1120 TLT FinStress regime-dependent",
        }],
    }) is False

    # Title with academic acronym → False
    assert MODULE._research_cover_is_reader_friendly({
        "audiences_covered": ["research"],
        "covered_by": [{
            "audience": "research",
            "title": "GARCH vs HAR-RV bootstrap comparison",
        }],
    }) is False

    # No research audience cover → False
    assert MODULE._research_cover_is_reader_friendly({
        "audiences_covered": ["general"],
        "covered_by": [{
            "audience": "general",
            "title": "reader friendly",
        }],
    }) is False

    # Empty covered_by → False
    assert MODULE._research_cover_is_reader_friendly({
        "audiences_covered": ["research"],
        "covered_by": [],
    }) is False
