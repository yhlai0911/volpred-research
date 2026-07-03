from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refill_reader_facing_pool.py"
SPEC = importlib.util.spec_from_file_location("reader_facing_refill", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


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


def test_refill_event_candidates_adds_only_in_horizon(tmp_path, monkeypatch):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "_now_utc", lambda: MODULE.datetime(2026, 5, 27, 0, 0, tzinfo=MODULE.timezone.utc))
    monkeypatch.setattr(
        MODULE,
        "_load_runtime_event_items",
        lambda: [
            {
                "id": "near",
                "event_key": "CPI_US_2026_06_01",
                "task_template": {
                    "title": "near title",
                    "description": "near desc",
                    "payload_patch": {
                        "event_type": "CPI_US",
                        "event_date": "2026-06-01",
                        "event_series_slot": "T-2",
                    },
                },
            },
            {
                "id": "far",
                "event_key": "CPI_US_2026_06_20",
                "task_template": {
                    "title": "far title",
                    "description": "far desc",
                    "payload_patch": {
                        "event_type": "CPI_US",
                        "event_date": "2026-06-20",
                        "event_series_slot": "T-2",
                    },
                },
            },
        ],
    )

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert result["added"] == ["event_article_cpi_us_2026-06-01_tminus2"]
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_refill_event_candidates_respects_not_before(tmp_path, monkeypatch):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        MODULE, "_now_utc", lambda: MODULE.datetime(2026, 5, 28, 0, 0, tzinfo=MODULE.timezone.utc)
    )
    monkeypatch.setattr(
        MODULE,
        "_load_runtime_event_items",
        lambda: [
            {
                "id": "future-window",
                "event_key": "CPI_US_2026_06_11",
                "not_before": "2026-06-09T08:00:00+08:00",
                "task_template": {
                    "title": "future window title",
                    "description": "desc",
                    "payload_patch": {
                        "event_type": "CPI_US",
                        "event_date": "2026-06-11",
                        "event_series_slot": "T-2",
                    },
                },
            },
            {
                "id": "open-window",
                "event_key": "NFP_2026_05_29",
                "not_before": "2026-05-27T08:00:00+08:00",
                "task_template": {
                    "title": "open window title",
                    "description": "desc",
                    "payload_patch": {
                        "event_type": "NFP",
                        "event_date": "2026-05-29",
                        "event_series_slot": "T-2",
                    },
                },
            },
        ],
    )

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert result["added"] == ["event_article_nfp_2026-05-29_tminus2"]
    not_yet = [s for s in result["skipped"] if s.get("reason") == "not_yet_in_window"]
    assert [s["id"] for s in not_yet] == ["future-window"]
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert [task["id"] for task in data] == ["event_article_nfp_2026-05-29_tminus2"]


def test_refill_event_candidates_warns_on_bad_event_date(tmp_path, monkeypatch, capsys):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    schedules = tmp_path / "runtime_schedules.json"
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", schedules)
    monkeypatch.setattr(
        MODULE, "_now_utc", lambda: MODULE.datetime(2026, 5, 28, 0, 0, tzinfo=MODULE.timezone.utc)
    )
    monkeypatch.setattr(
        MODULE,
        "_load_runtime_event_items",
        lambda: [
            {
                "id": "bad-date",
                "event_key": "CPI_US_BAD",
                "task_template": {
                    "title": "bad date title",
                    "description": "desc",
                    "payload_patch": {
                        "event_type": "CPI_US",
                        "event_date": "not-a-date",
                        "event_series_slot": "T-2",
                    },
                },
            }
        ],
    )

    result = MODULE.refill_event_candidates(horizon_days=14)

    captured = capsys.readouterr()
    assert result["added"] == []
    assert result["skipped"] == [{"id": "bad-date", "reason": "bad_event_date"}]
    assert "[reader_facing_refill] WARN event_date parse failed" in captured.err
    assert "field=event_date" in captured.err
    assert "raw=not-a-date" in captured.err
    assert "item_id=bad-date" in captured.err
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == []


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

    def _fake_is_dup(title, desc, feed):
        if "duplicate" in title:
            return {"id": "mile_existing"}
        return None

    monkeypatch.setattr(MODULE, "_is_arc_duplicate", _fake_is_dup)

    result = MODULE.refill_trending_candidates()

    assert result["ok"] is True
    assert result["added"] == ["dup_topic"] or result["added"] == ["fresh_topic"]
    # exactly one fresh task added, dup must appear in skipped with arc_duplicate reason
    skipped_dup = [s for s in result["skipped"] if s.get("reason") == "arc_duplicate"]
    assert any(s.get("dup_of") == "mile_existing" for s in skipped_dup)
    # the dup id must not appear in next_tasks.json
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    dup_ids = [t["id"] for t in data if "duplicate" in t.get("title", "")]
    assert dup_ids == []


def test_refill_event_candidates_warns_and_skips_on_bad_not_before(tmp_path, monkeypatch, capsys):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    schedules = tmp_path / "runtime_schedules.json"
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", schedules)
    monkeypatch.setattr(
        MODULE, "_now_utc", lambda: MODULE.datetime(2026, 5, 28, 0, 0, tzinfo=MODULE.timezone.utc)
    )
    monkeypatch.setattr(
        MODULE,
        "_load_runtime_event_items",
        lambda: [
            {
                "id": "bad-window",
                "event_key": "CPI_US_2026_06_11",
                "not_before": "not-a-timestamp",
                "task_template": {
                    "title": "bad window title",
                    "description": "desc",
                    "payload_patch": {
                        "event_type": "CPI_US",
                        "event_date": "2026-06-11",
                        "event_series_slot": "T-2",
                    },
                },
            }
        ],
    )

    result = MODULE.refill_event_candidates(horizon_days=14)

    captured = capsys.readouterr()
    assert result["added"] == []
    assert result["skipped"] == [{"id": "bad-window", "reason": "bad_not_before"}]
    assert "[reader_facing_refill] WARN not_before parse failed" in captured.err
    assert "field=not_before" in captured.err
    assert "raw=not-a-timestamp" in captured.err
    assert "item_id=bad-window" in captured.err
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == []


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
    assert hit["match"] == "fuzzy"


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


def _monkeypatch_event_env(tmp_path, monkeypatch, feed):
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    next_tasks.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "DEDUP_LOG", tmp_path / "dedup_decisions.jsonl")
    monkeypatch.setattr(
        MODULE, "_now_utc", lambda: MODULE.datetime(2026, 7, 3, 0, 0, tzinfo=MODULE.timezone.utc)
    )
    monkeypatch.setattr(MODULE, "_load_feed_for_dedup", lambda: feed)
    monkeypatch.setattr(
        MODULE,
        "_load_runtime_event_items",
        lambda: [{
            "id": "nfp-2026-07-03-t0",
            "event_key": "NFP_2026_07_03",
            "task_template": {
                "title": "Event article: NFP_US 2026-07-03 T+0",
                "description": "reaction",
                "payload_patch": {
                    "event_type": "NFP_US",
                    "event_date": "2026-07-03",
                    "event_series_slot": "T+0",
                },
            },
        }],
    )
    return next_tasks


def test_refill_skips_reaction_when_already_covered(tmp_path, monkeypatch):
    """T+0 發過則 skip T+0."""
    feed = [{
        "id": "mile_35eef830",
        "status": "published",
        "title": "6 月非農爆冷 5.7 萬，SPY 卻只動 0.13%",
        "tags": ["NFP", "非農就業"],
        "published_at": "2026-07-01T17:24:08+00:00",
    }]
    next_tasks = _monkeypatch_event_env(tmp_path, monkeypatch, feed)

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert result["added"] == []
    skipped = [s for s in result["skipped"] if s.get("reason") == "reaction_already_covered"]
    assert skipped and skipped[0]["dup_of"] == "mile_35eef830"
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == []
    # audit trail written
    log = (tmp_path / "dedup_decisions.jsonl").read_text(encoding="utf-8")
    assert "reaction_already_covered" in log and "event_reaction_coverage" in log


def test_refill_generates_reaction_when_only_forward_covered(tmp_path, monkeypatch):
    """T-7 發過但 T+0 仍生成（forward article 不覆蓋 reaction slot）."""
    feed = [{
        "id": "mile_forward",
        "status": "published",
        "title": "非農就業報告前7天：勞動市場到底在哪個位置？",
        "tags": ["NFP", "非農就業"],
        "published_at": "2026-07-01T09:00:00+00:00",
    }]
    next_tasks = _monkeypatch_event_env(tmp_path, monkeypatch, feed)

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert result["added"] == ["event_article_nfp_us_2026-07-03_tplus0"]
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert [t["id"] for t in data] == ["event_article_nfp_us_2026-07-03_tplus0"]


def test_refill_generates_reaction_for_brand_new_event(tmp_path, monkeypatch):
    """全新 event 正常生成（feed 無覆蓋）."""
    feed = [{
        "id": "mile_unrelated",
        "status": "published",
        "title": "台積電六月營收再創高，記憶體需求回溫",
        "tags": ["台積電", "半導體"],
        "published_at": "2026-07-02T09:00:00+00:00",
    }]
    next_tasks = _monkeypatch_event_env(tmp_path, monkeypatch, feed)

    result = MODULE.refill_event_candidates(horizon_days=14)

    assert result["added"] == ["event_article_nfp_us_2026-07-03_tplus0"]


def test_reaction_coverage_fails_open_on_bad_feed(monkeypatch):
    """Any error in the coverage check returns None (never blocks a real task)."""
    # non-dict feed entries are skipped; a malformed published_at just skips that row
    feed = ["not-a-dict", {"id": "x", "status": "published", "title": "非農",
                           "published_at": "garbage"}]
    hit = MODULE._reaction_already_covered("nfp_us", MODULE.date(2026, 7, 3), feed)
    assert hit is None
