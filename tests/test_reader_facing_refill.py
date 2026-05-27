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
