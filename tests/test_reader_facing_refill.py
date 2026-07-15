from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refill_reader_facing_pool.py"
SPEC = importlib.util.spec_from_file_location("reader_facing_refill", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


@pytest.fixture(autouse=True)
def _redirect_storage(tmp_path, monkeypatch):
    """Point every storage constant this module writes through at tmp_path.

    Redirecting NEXT_TASKS alone leaves DEDUP_LOG (the coverage gate's audit
    trail) and STORAGE (handed to build_pending_event_task, which logs through
    topic_dedup) aimed at the live checkout, so the tests appended real decisions
    to the shared audit trail. Autouse so a new test cannot forget one.
    """
    monkeypatch.setattr(MODULE, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(MODULE, "DEDUP_LOG", tmp_path / "storage" / "logs" / "dedup_decisions.jsonl")


def test_build_event_task_id_and_payload():
    item = {
        "id": "cpi-us-2026-06-11-t2",
        "event_key": "CPI_US_2026_06_11",
        "task_template": {
            "title": "Event article: CPI_US 2026-06-11 T-2",
            "description": "demo",
            "payload_patch": {
                "event_type": "CPI_US",
                "event_date": "2026-06-11",
                "event_series_slot": "T-2",
            },
        },
    }
    task = MODULE._build_event_task(item)
    assert task["id"] == "event_article_cpi_us_2026-06-11_tminus2"
    assert task["task_type"] == "event_article"
    assert task["ref_event_job_id"] == "cpi-us-2026-06-11-t2"


def test_run_refill_skips_if_state_already_today(tmp_path, monkeypatch):
    state_path = tmp_path / "storage" / "ops" / "daily_reader_facing_scan_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_payload = {
        "date": "2026-05-27",
        "scanned": True,
        "scanned_at": "2026-05-27T00:00:00+00:00",
    }
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(MODULE, "STATE_PATH", state_path)
    monkeypatch.setattr(MODULE, "_today_local", lambda: "2026-05-27")

    result = MODULE.run_refill(force=False)

    assert result["skip"] is True
    assert result["reason"] == "already_scanned_today"


def test_load_json_warns_on_invalid_existing_file(tmp_path, capsys):
    path = tmp_path / "state.json"
    path.write_text("{bad json", encoding="utf-8")

    assert MODULE._load_json(path, {"fallback": True}) == {"fallback": True}

    captured = capsys.readouterr()
    # diagnostics.warn emits structured warnings on stderr (no-silent-fallback rule)
    assert "[reader_facing_refill] WARN JSON read failed; using default" in captured.err
    assert "state.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_refill_event_candidates_delegates_to_single_event_owner(monkeypatch):
    calls = []

    def fake_expand(*, storage_dir, now):
        calls.append((storage_dir, now))
        return {
            "created": [
                {
                    "task": {"id": "event_article_cpi_us_2026-06-01_tminus2"},
                    "queue_created": True,
                }
            ],
            "skipped": [{"id": "future-window", "reason": "pending"}],
            "expired_tasks": {"next_tasks": [], "legacy_receipts": []},
        }

    monkeypatch.setattr(MODULE, "expand_due_event_jobs", fake_expand)

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert len(calls) == 1
    assert result["added"] == ["event_article_cpi_us_2026-06-01_tminus2"]
    assert result["skipped"] == [{"id": "future-window", "reason": "pending"}]


def test_refill_event_candidates_never_uses_legacy_append_writer(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "_append_task",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("legacy event writer called")),
    )
    monkeypatch.setattr(
        MODULE,
        "expand_due_event_jobs",
        lambda **_kwargs: {
            "created": [],
            "skipped": [],
            "expired_tasks": {"next_tasks": [], "legacy_receipts": []},
        },
    )

    assert MODULE.refill_event_candidates() == {
        "added": [],
        "skipped": [],
        "expired": {"next_tasks": [], "legacy_receipts": []},
    }


def test_refill_trending_skips_arc_duplicate(tmp_path, monkeypatch):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setenv("VOLPRED_TRENDING_SCAN_CMD", "echo dummy")

    candidates = [
        {"id": "dup_topic", "title": "duplicate fed-pivot story", "description": "..."},
        {"id": "fresh_topic", "title": "novel arc on green hydrogen vol", "description": "..."},
    ]

    class _FakeProc:
        returncode = 0
        stdout = json.dumps(candidates)
        stderr = ""

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **kw: _FakeProc())
    monkeypatch.setattr(MODULE, "_load_feed_for_dedup", lambda: [{"id": "mile_existing"}])

    # 2026-07-14: `_is_arc_duplicate` was replaced by `_screen_trending_topic`,
    # which returns a TopicScreen (arc dup + K coverage + theme saturation) instead
    # of a bare match dict, and blocks with an explicit verdict + reason.
    from volpred.ops.topic_dedup import BLOCK_ARC_DUP, CLEAN, TopicScreen

    def _fake_screen(title, desc, feed):
        if "duplicate" in title:
            return TopicScreen(
                verdict=BLOCK_ARC_DUP,
                blocked=True,
                reason="narrative-arc duplicate of mile_existing",
                matches=[{"id": "mile_existing"}],
            )
        return TopicScreen(verdict=CLEAN, blocked=False, reason="clean")

    monkeypatch.setattr(MODULE, "_screen_trending_topic", _fake_screen)

    result = MODULE.refill_trending_candidates()

    assert result["ok"] is True
    assert result["added"] == ["dup_topic"] or result["added"] == ["fresh_topic"]
    # dup must appear in skipped with the arc-dup verdict AND a human-readable reason
    skipped_dup = [s for s in result["skipped"] if s.get("reason") == BLOCK_ARC_DUP]
    assert any(s.get("dup_of") == "mile_existing" for s in skipped_dup)
    assert all(s.get("detail") for s in skipped_dup), "a skip with no detail is a silent skip"
    # the dup id must not appear in next_tasks.json
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    dup_ids = [t["id"] for t in data if "duplicate" in t.get("title", "")]
    assert dup_ids == []


# --- Slot-aware event coverage (2026-07-03 NFP T+0 stale-duplicate fix) --------

def test_slot_is_reaction_classification():
    # Reaction (result-known) slots
    assert MODULE._slot_is_reaction("T+0") is True
    assert MODULE._slot_is_reaction("T-0") is True
    assert MODULE._slot_is_reaction("T+1") is True
    # Forward (pre-event) slots
    assert MODULE._slot_is_reaction("T-7") is False
    assert MODULE._slot_is_reaction("T-2") is False
    # Unknown / empty -> treated as forward (never gate on surprise labels)
    assert MODULE._slot_is_reaction("") is False
    assert MODULE._slot_is_reaction("weird") is False


def test_reaction_already_covered_fuzzy_early_release():
    """The NFP incident: reaction article published early (no event metadata)."""
    feed = [{
        "id": "mile_35eef830",
        "status": "published",
        "title": "6 月非農爆冷 5.7 萬，SPY 卻只動 0.13%",
        "tags": ["NFP", "非農就業", "VIX"],
        "published_at": "2026-07-01T17:24:08+00:00",
    }]
    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)
    assert hit is not None
    assert hit["id"] == "mile_35eef830"
    assert hit["match"] == "title_keyword"


def test_reaction_coverage_does_not_use_generic_tags_as_event_identity():
    feed = [{
        "id": "mile_5dd7c135",
        "status": "published",
        "title": "油價跳漲，金價卻連摔兩天：避風港有沒有上班",
        "tags": ["黃金", "避險", "通膨"],
        "published_at": "2026-07-14T03:24:06+00:00",
    }]

    hit = MODULE._reaction_already_covered("CPI_US", MODULE.date(2026, 7, 14), feed)

    assert hit is None


def test_reaction_already_covered_exact_event_metadata():
    """New publisher writes top-level event metadata, so coverage can be exact."""
    feed = [{
        "id": "mile_exact",
        "status": "published",
        "title": "Unrelated title that should not matter",
        "tags": [],
        "event_key": "NFP_US_2026_07_03",
        "event_type": "NFP_US",
        "event_date": "2026-07-03",
        "event_series_slot": "T+0",
        "published_at": "2026-06-01T00:00:00+00:00",
    }]

    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)

    assert hit is not None
    assert hit["id"] == "mile_exact"
    assert hit["match"] == "metadata"


def test_reaction_metadata_forward_slot_does_not_cover_reaction():
    feed = [{
        "id": "mile_forward_metadata",
        "status": "published",
        "title": "NFP T-2 preview",
        "tags": ["NFP"],
        "event_type": "NFP_US",
        "event_date": "2026-07-03",
        "event_series_slot": "T-2",
        "published_at": "2026-07-01T00:00:00+00:00",
    }]

    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)

    assert hit is None


def test_reaction_coverage_excludes_forward_preview():
    """A forward preview (前7天) must NOT count as reaction coverage."""
    feed = [{
        "id": "mile_forward",
        "status": "published",
        "title": "非農就業報告前7天：勞動市場到底在哪個位置？",
        "tags": ["NFP", "非農就業"],
        "published_at": "2026-07-01T09:00:00+00:00",  # inside the reaction window
    }]
    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)
    assert hit is None  # forward title excluded even though it's in the date window


def test_reaction_coverage_fails_open_on_bad_feed(monkeypatch):
    """Any error in the coverage check returns None (never blocks a real task)."""
    # non-dict feed entries are skipped; a malformed published_at just skips that row
    feed = ["not-a-dict", {"id": "x", "status": "published", "title": "非農",
                           "published_at": "garbage"}]
    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)
    assert hit is None
