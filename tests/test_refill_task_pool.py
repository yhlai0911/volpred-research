from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refill_task_pool.py"
SPEC = importlib.util.spec_from_file_location("refill_task_pool", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_ensure_candidates_fresh_times_out_builder(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    builder = scripts_dir / "build_publication_candidates.py"
    builder.write_text("print('slow')\n", encoding="utf-8")
    candidates = tmp_path / "storage" / "publication_candidates.json"

    calls: list[dict] = []

    def fake_run(cmd, *, capture_output, timeout, check):
        calls.append(
            {
                "cmd": cmd,
                "capture_output": capture_output,
                "timeout": timeout,
                "check": check,
            }
        )
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setenv("REFILL_CANDIDATES_TIMEOUT_SECONDS", "7")

    result = MODULE._ensure_candidates_fresh()

    assert result == {
        "rebuilt": False,
        "reason": "rebuild_timeout",
        "timeout_seconds": 7,
    }
    assert calls and calls[0]["timeout"] == 7
    assert calls[0]["cmd"] == ["uv", "run", "python", str(builder)]


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
    monkeypatch.setattr(MODULE, "_ensure_candidates_fresh", lambda: {"rebuilt": False, "reason": "test"})
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())
    monkeypatch.setattr(MODULE, "_kids_with_audience_article", lambda audience: set())
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

    result = MODULE.refill(target=3, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["reason"] == "no_new_candidates_passing_filter"
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert data == []


def test_refill_skips_failed_source_experiment_k(tmp_path, monkeypatch, capsys):
    """Regression: K1327 failed experiment must not become an article task.

    publication_candidates can retain a stale verdict signal after a Codex
    review or follow-up marks the source K experiment failed. Refill must trust
    the task receipt and skip the K before creating `<K>_article_<audience>`.
    """
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    candidates = tmp_path / "storage" / "publication_candidates.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K1327",
                    "task_type": "experiment",
                    "status": "failed",
                    "title": "K1327 source experiment failed",
                },
                {
                    "id": "K1327_v2_fix_methodology",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "title": "K1327-v2 follow-up should not revive K1327",
                },
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    candidates.write_text(
        json.dumps(
            {
                "top_10_uncovered": [
                    {
                        "k_id": "K1327",
                        "title": "Adaptive Multi-Factor HAR",
                        "score": 4,
                        "reasons": ["stale PASS"],
                        "verdict_preview": "stale candidate after failed source",
                        "audiences_covered": [],
                        "covered_by": [],
                    },
                    {
                        "k_id": "K1056",
                        "title": "legitimate publishable K",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "ok",
                        "audiences_covered": [],
                        "covered_by": [],
                    },
                ],
                "missing_research_top5": [],
                "missing_general_top5": [],
                "candidates": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_ensure_candidates_fresh", lambda: {"rebuilt": False, "reason": "test"})
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())
    monkeypatch.setattr(MODULE, "_kids_with_audience_article", lambda audience: set())
    monkeypatch.setattr(MODULE, "_any_feed_coverage_kids", lambda: set())
    monkeypatch.setattr(MODULE, "_breached_clusters", lambda: set())
    monkeypatch.setattr(MODULE, "_is_arc_duplicate_candidate", lambda cand: False)
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

    result = MODULE.refill(target=3, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 1
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    ids = [t["id"] for t in data]
    assert "K1327_article_general" not in ids
    assert "K1056_article_general" in ids
    assert "skip K1327: source experiment task status=failed" in capsys.readouterr().out


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
    monkeypatch.setattr(MODULE, "_kids_with_audience_article", lambda audience: set())
    monkeypatch.setattr(MODULE, "_any_feed_coverage_kids", lambda: set())
    monkeypatch.setattr(MODULE, "_is_arc_duplicate_candidate", lambda cand: False)
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

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


def test_terminal_article_attempts_release_pre_gate_kids():
    """2026-06-07 K672/K957/K593/K1021/K1151 unblock fix.

    Pre-gate (before 2026-05-28T20:29:54+00:00) all terminal article tasks
    are caught by publish-time audience gate now → safe to re-enter refill pool.
    Only K-ids with a post-gate terminal article task stay audit_pending.
    """
    tasks = [
        # K672: only pre-gate terminal failures → should be released
        {"id": "K672_article_general", "status": "failed",
         "task_type": "daily_article", "k_id": "K672",
         "completed_at": "2026-05-28T06:31:18+00:00"},
        {"id": "K672_article_general_v2", "status": "failed",
         "task_type": "daily_article", "k_id": "K672",
         "completed_at": "2026-05-28T20:10:42+00:00"},
        # K1021/K593: date-only completed_at (pre-2026-05-28) → released
        {"id": "K1021_article_general", "status": "succeeded",
         "task_type": "daily_article", "k_id": "K1021",
         "completed_at": "2026-05-05"},
        {"id": "K593_article_general", "status": "succeeded",
         "task_type": "daily_article", "k_id": "K593",
         "completed_at": "2026-05-05"},
        # K9999: ONE terminal task post-gate → stays blocked
        {"id": "K9999_article_general_v3", "status": "failed",
         "task_type": "daily_article", "k_id": "K9999",
         "completed_at": "2026-05-29T10:00:00+00:00"},
        # K9999: also has a pre-gate task — presence of any post-gate failure dominates
        {"id": "K9999_article_general", "status": "succeeded",
         "task_type": "daily_article", "k_id": "K9999",
         "completed_at": "2026-05-04"},
        # Non-article task → ignored
        {"id": "platform_ops_some_audit", "status": "succeeded",
         "task_type": "platform_ops", "k_id": "K1234"},
        # Pending task → ignored (not terminal)
        {"id": "K5555_article_general", "status": "pending",
         "task_type": "daily_article", "k_id": "K5555"},
    ]
    blocked = MODULE._kids_with_terminal_article_attempts(tasks)
    assert "K672" not in blocked, "pre-gate terminal-only K should be released"
    assert "K1021" not in blocked, "date-only completed_at treated as pre-gate"
    assert "K593" not in blocked, "date-only completed_at treated as pre-gate"
    assert "K9999" in blocked, "any post-gate terminal task → stays blocked"
    assert "K1234" not in blocked, "non-article task should not block K"
    assert "K5555" not in blocked, "pending tasks are not terminal"


def test_terminal_article_attempts_null_completed_at_treated_as_pregate():
    """If completed_at is null/missing, allow retry (pre-gate by default)."""
    tasks = [
        {"id": "K7777_article_general", "status": "failed",
         "task_type": "daily_article", "k_id": "K7777",
         "completed_at": None},
        {"id": "K7777_article_general_v2", "status": "succeeded",
         "task_type": "daily_article", "k_id": "K7777"},
    ]
    blocked = MODULE._kids_with_terminal_article_attempts(tasks)
    assert "K7777" not in blocked


def test_refill_skips_general_retry_v2_when_feed_already_has_k_coverage(tmp_path, monkeypatch):
    """Regression: 2026-06-08 stale retry-v2 pollution.

    If a K already has:
    1. a succeeded `*_article_general` task, and
    2. any feed article referencing that K,
    refill must not auto-create `*_article_general_v2` even when
    publication_candidates still reports `audiences_covered=["research"]`.
    """
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    candidates = tmp_path / "storage" / "publication_candidates.json"
    feed = tmp_path / "storage" / "reports" / "feed.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    feed.parent.mkdir(parents=True, exist_ok=True)

    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K676_article_general",
                    "status": "succeeded",
                    "task_type": "daily_article",
                    "k_id": "K676",
                    "completed_at": "2026-05-08T07:13:00+00:00",
                }
            ],
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    feed.write_text(
        json.dumps(
            [
                {
                    "id": "mile_d9d88717",
                    "title": "VT 策略的稅務黑盒",
                    "status": "published",
                    "audience": "research",
                    "details": {"experiment_refs": ["K676"]},
                }
            ],
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    candidates.write_text(
        json.dumps(
            {
                "top_10_uncovered": [],
                "missing_research_top5": [],
                "missing_general_top5": [
                    {
                        "k_id": "K676",
                        "title": "K676 tax optimization",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "already covered in feed",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_d9d88717",
                                "title": "VT 策略的稅務黑盒",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                    }
                ],
                "candidates": [
                    {
                        "k_id": "K676",
                        "title": "K676 tax optimization",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "already covered in feed",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_d9d88717",
                                "title": "VT 策略的稅務黑盒",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_breached_clusters", lambda: set())
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

    result = MODULE.refill(target=3, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["reason"] == "no_new_candidates_passing_filter"
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert [t["id"] for t in data] == ["K676_article_general"]


def test_refill_fallback_audience_gap_requires_score_threshold(tmp_path, monkeypatch):
    """Regression: 2026-06-08 low-signal audience-gap leakage.

    Fallback audience-gap scanning should not enqueue low-score K's that only
    have research coverage. Otherwise paper appendix / guide / score-0 null
    studies flood the general article queue.
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
                "missing_general_top5": [],
                "candidates": [
                    {
                        "k_id": "K1202",
                        "title": "paper appendix verification",
                        "score": 0,
                        "reasons": [],
                        "verdict_preview": "",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_cbb93ff8",
                                "title": "K1202 research article",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                        "topic_family_collisions": {"general": [], "research": []},
                    },
                    {
                        "k_id": "K1056",
                        "title": "legit missing general",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "ok",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {
                                "id": "mile_some_research",
                                "title": "K1056 research article",
                                "status": "published",
                                "audience": "research",
                            }
                        ],
                        "topic_family_collisions": {"general": [], "research": []},
                    },
                ],
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_ensure_candidates_fresh", lambda: {"rebuilt": False, "reason": "test"})
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())
    monkeypatch.setattr(MODULE, "_kids_with_audience_article", lambda audience: set())
    monkeypatch.setattr(MODULE, "_any_feed_coverage_kids", lambda: set())
    monkeypatch.setattr(MODULE, "_breached_clusters", lambda: set())
    monkeypatch.setattr(MODULE, "_is_arc_duplicate_candidate", lambda cand: False)
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

    result = MODULE.refill(target=5, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 1
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert [t["id"] for t in data] == ["K1056_article_general"]


def test_refill_skips_research_saturated_k(tmp_path, monkeypatch):
    """Regression: 2026-06-08 K159/K495/K510/K737 incident.

    hourly-00 codex-cli refill enqueued 5 K-article-general tasks where each K
    already had ≥2 research-audience feed articles (published+archived). All 5
    became narrative-arc duplicates — the K's story had been told under
    research audience and pulling/reframing it had already happened.

    8th belt (_is_research_saturated): K with ≥2 research articles in
    feed (published / archived / draft / scheduled) is research-saturated.
    Refill should skip a general companion for these K's; the audience gate
    and duplicate gate were not the right enforcement layer because the agent
    had already spent tokens producing the draft.
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
                "missing_general_top5": [],
                "candidates": [
                    {
                        "k_id": "K159",
                        "title": "EVT-GPD VaR comparison",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "Mixed",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {"id": "a", "title": "x", "status": "published", "audience": "research"},
                            {"id": "b", "title": "y", "status": "archived", "audience": "research"},
                            {"id": "c", "title": "z", "status": "archived", "audience": "research"},
                        ],
                        "topic_family_collisions": {"general": [], "research": []},
                    },
                    {
                        "k_id": "K1056",
                        "title": "legit single research coverage",
                        "score": 4,
                        "reasons": ["PASS"],
                        "verdict_preview": "ok",
                        "audiences_covered": ["research"],
                        "covered_by": [
                            {"id": "d", "title": "w", "status": "published", "audience": "research"},
                        ],
                        "topic_family_collisions": {"general": [], "research": []},
                    },
                ],
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "CANDIDATES", candidates)
    monkeypatch.setattr(MODULE, "_ensure_candidates_fresh", lambda: {"rebuilt": False, "reason": "test"})
    monkeypatch.setattr(MODULE, "_kids_with_general_article", lambda: set())
    monkeypatch.setattr(MODULE, "_kids_with_audience_article", lambda audience: set())
    monkeypatch.setattr(MODULE, "_any_feed_coverage_kids", lambda: set())
    monkeypatch.setattr(MODULE, "_breached_clusters", lambda: set())
    monkeypatch.setattr(MODULE, "_is_arc_duplicate_candidate", lambda cand: False)
    monkeypatch.setattr(MODULE, "_research_backlog_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(MODULE, "_journal_discovery_dispatch_task", lambda *args, **kwargs: [])

    result = MODULE.refill(target=5, dry_run=False)

    assert result["ok"] is True
    assert result["added"] == 1
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    ids = [t["id"] for t in data]
    assert "K1056_article_general" in ids
    assert "K159_article_general" not in ids, (
        f"K159 with 3 research articles should be skipped as saturated; got {ids}"
    )


def test_research_backlog_arc_dedup_ignores_explanatory_tail(tmp_path, monkeypatch):
    """Regression: 2026-06-13 pool=0 due to backlog tail entity false positives.

    research_program fallback stores open directions as:
      `<short title> — <motivation/assets/citation tail>`
    The short title may contain no asset entities, while the explanatory tail
    mentions tickers only as examples. Arc dedup must not treat that tail as
    the canonical direction text, or unrelated recent articles can block every
    fallback candidate and drain the task pool.
    """
    rp = tmp_path / "research_program.md"
    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    rp.write_text(
        "\n".join(
            [
                "## 面向 A",
                "### 開放方向",
                "- [ ] 加密「vol-of-vol」與跨市場尾部外溢的免期權版 — yfinance BTC/ETH 算 RV 與 vol-of-vol，檢定對股/金/油尾部外溢",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (reports / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_existing",
                    "title": "比特幣與以太幣的波動率結構變了嗎？",
                    "description": "舊文只談 BTC/ETH 自身波動結構。",
                    "status": "published",
                    "published_at": "2099-01-01T00:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "RESEARCH_PROGRAM", rp)
    monkeypatch.setattr(MODULE, "_ARC_FEED_CACHE", None)

    tasks = MODULE._research_backlog_candidates(tasks=[], existing_ids=set(), limit=2)

    assert len(tasks) == 1
    assert tasks[0]["id"].startswith("research_")


def test_research_backlog_arc_dedup_warns_on_invalid_feed_timestamp(
    tmp_path, monkeypatch, capsys
):
    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_bad_ts",
                    "title": "BTC ETH volatility spillover",
                    "description": "BITCOIN and ETHEREUM vol-of-vol spillover",
                    "status": "published",
                    "published_at": "not-a-date",
                }
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "_ARC_FEED_CACHE", None)

    hits = MODULE._arc_covered_by_recent_article("BTC ETH vol-of-vol", days=90)
    output = capsys.readouterr().out

    assert hits == [
        {
            "id": "mile_bad_ts",
            "title": "BTC ETH volatility spillover",
            "shared_entities": ["BITCOIN", "ETHEREUM"],
        }
    ]
    assert "recent arc feed timestamp invalid" in output
    assert "mile_bad_ts" in output
    assert "not-a-date" in output


def test_journal_discovery_tier3_dispatched_on_empty_pool():
    """Tier-3 fallback fires when no live or recent journal_discovery_* exists."""
    out = MODULE._journal_discovery_dispatch_task(tasks=[], existing_ids=set())
    assert len(out) == 1
    t = out[0]
    assert t["id"].startswith("journal_discovery_")
    assert t["task_type"] == "platform_ops"
    assert t["dispatch_lane"] == "agent"
    assert t["status"] == "pending"
    assert t["source"] == "auto_journal_discovery_fallback"
    assert t["priority"] == 2


def test_journal_discovery_tier3_idempotent_when_live_task_exists():
    """Don't double-queue when an existing journal_discovery_* is still live."""
    existing_live = [
        {
            "id": "journal_discovery_20260101",
            "status": "pending",
            "task_type": "platform_ops",
        }
    ]
    out = MODULE._journal_discovery_dispatch_task(tasks=existing_live, existing_ids={"journal_discovery_20260101"})
    assert out == []


def test_journal_discovery_tier3_skips_when_recent_completed_within_24h():
    """24h cap: a journal_discovery_* completed within the last 24h blocks new dispatch."""
    from datetime import datetime, timedelta, timezone

    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    existing_recent = [
        {
            "id": "journal_discovery_20260101",
            "status": "succeeded",
            "task_type": "platform_ops",
            "completed_at": recent_ts,
        }
    ]
    out = MODULE._journal_discovery_dispatch_task(tasks=existing_recent, existing_ids=set())
    assert out == []


def test_journal_discovery_tier3_allows_after_24h():
    """A journal_discovery_* completed >24h ago doesn't block a new dispatch."""
    from datetime import datetime, timedelta, timezone

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    existing_stale = [
        {
            "id": "journal_discovery_20260101",
            "status": "succeeded",
            "task_type": "platform_ops",
            "completed_at": stale_ts,
        }
    ]
    out = MODULE._journal_discovery_dispatch_task(tasks=existing_stale, existing_ids=set())
    assert len(out) == 1
    assert out[0]["id"].startswith("journal_discovery_")
