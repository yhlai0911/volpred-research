from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "task_generator_v2.py"
SPEC = importlib.util.spec_from_file_location("task_generator_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_make_task_adds_default_dispatch_lanes() -> None:
    experiment = MODULE.make_task(
        task_id="gen_exp_vol",
        title="vol",
        description="experiment",
        task_type="experiment",
    )
    paper_body = MODULE.make_task(
        task_id="gen_paper_body",
        title="paper",
        description="paper edit",
        task_type="paper_body",
    )

    assert experiment["dispatch_lane"] == "agent"
    assert paper_body["dispatch_lane"] == "main_thread"


def test_load_next_tasks_warns_on_invalid_json(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)

    tasks = MODULE.load_next_tasks()

    assert tasks == []
    captured = capsys.readouterr()
    assert "[task_generator_v2] WARN next_tasks JSON read failed; treating as empty" in captured.err
    assert "next_tasks.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_iter_managed_event_dates_warns_on_invalid_runtime_schedules(
    tmp_path, monkeypatch, capsys
) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)

    managed = MODULE._iter_managed_event_dates([])

    assert managed == set()
    captured = capsys.readouterr()
    assert (
        "[task_generator_v2] WARN runtime_schedules JSON read failed; "
        "treating event schedules as empty"
    ) in captured.err
    assert "runtime_schedules.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_iter_managed_event_dates_warns_on_bad_runtime_event_date(
    tmp_path, monkeypatch, capsys
) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text(
        json.dumps(
            {
                "event_jobs": {
                    "items": [
                        {
                            "id": "bad-date",
                            "event_key": "FOMC_2026_bad",
                            "task_template": {
                                "payload_patch": {
                                    "event_type": "FOMC",
                                    "event_date": "not-a-date",
                                }
                            },
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)

    managed = MODULE._iter_managed_event_dates([])

    assert managed == set()
    captured = capsys.readouterr()
    assert "[task_generator_v2] WARN runtime event_date parse failed; skipping managed event" in captured.err
    assert "not-a-date" in captured.err
    assert "runtime_schedules.json" in captured.err


def test_iter_managed_event_dates_warns_on_bad_existing_task_event_date(
    tmp_path, monkeypatch, capsys
) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text(json.dumps({"event_jobs": {"items": []}}), encoding="utf-8")
    next_tasks = tmp_path / "next_tasks.json"
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)

    managed = MODULE._iter_managed_event_dates(
        [
            {
                "id": "event_bad_date",
                "task_type": "event_article",
                "event_type": "CPI",
                "event_date": "bad-date",
            }
        ]
    )

    assert managed == set()
    captured = capsys.readouterr()
    assert "[task_generator_v2] WARN existing event task date parse failed; skipping managed event" in captured.err
    assert "event_bad_date" in captured.err
    assert "bad-date" in captured.err


def test_k_ids_with_feed_articles_warns_on_grep_failure(tmp_path, monkeypatch, capsys) -> None:
    feed = tmp_path / "feed.json"
    feed.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(MODULE, "FEED_JSON", feed)

    def _raise(*args, **kwargs):
        raise RuntimeError("grep unavailable")

    monkeypatch.setattr(MODULE.subprocess, "run", _raise)

    k_ids = MODULE.k_ids_with_feed_articles()

    assert k_ids == set()
    captured = capsys.readouterr()
    assert "[task_generator_v2] WARN feed K-id grep failed; treating as no feed coverage" in captured.err
    assert "feed.json" in captured.err
    assert "RuntimeError: grep unavailable" in captured.err


def test_experiment_readme_corpus_warns_on_unreadable_readme(
    tmp_path, monkeypatch, capsys
) -> None:
    readme = tmp_path / "experiments" / "k9999" / "README.md"
    readme.mkdir(parents=True)
    monkeypatch.setattr(MODULE, "EXPERIMENTS_DIR", tmp_path / "experiments")

    corpus = MODULE.experiment_readme_corpus()

    assert corpus == ""
    captured = capsys.readouterr()
    assert (
        "[task_generator_v2] WARN experiment README read failed; "
        "excluding from stale-backlog corpus"
    ) in captured.err
    assert "README.md" in captured.err
    assert "IsADirectoryError" in captured.err


def test_generate_paper_body_tasks_warns_on_unreadable_tex(
    tmp_path, monkeypatch, capsys
) -> None:
    tex_path = tmp_path / "paper" / "paper_1" / "main.tex"
    tex_path.mkdir(parents=True)
    monkeypatch.setattr(MODULE, "PAPER_DIR", tmp_path / "paper")

    tasks = MODULE.generate_paper_body_tasks(existing=[])

    assert tasks == []
    captured = capsys.readouterr()
    assert (
        "[task_generator_v2] WARN paper tex read failed; "
        "excluding from paper_body TODO scan"
    ) in captured.err
    assert "main.tex" in captured.err
    assert "IsADirectoryError" in captured.err


def test_event_article_skips_runtime_managed_adjacent_fomc_date(tmp_path, monkeypatch) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text(
        json.dumps(
            {
                "event_jobs": {
                    "items": [
                        {
                            "id": "fomc-2026-06-17-t7",
                            "event_key": "FOMC_2026_06_17",
                            "task_template": {
                                "payload_patch": {
                                    "event_type": "FOMC",
                                    "event_date": "2026-06-17",
                                }
                            },
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(
        MODULE,
        "EVENT_CALENDAR",
        [("fomc", "2026-06-18", "FOMC meeting June 2026")],
    )

    tasks = MODULE.generate_event_article_tasks(existing=[], reference_date=date(2026, 6, 13))

    assert tasks == []


def test_event_article_warns_on_bad_calendar_event_date(
    tmp_path, monkeypatch, capsys
) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text(json.dumps({"event_jobs": {"items": []}}), encoding="utf-8")
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(
        MODULE,
        "EVENT_CALENDAR",
        [("cpi", "bad-date", "BLS CPI release with bad date")],
    )

    tasks = MODULE.generate_event_article_tasks(existing=[], reference_date=date(2026, 6, 13))

    assert tasks == []
    captured = capsys.readouterr()
    assert (
        "[task_generator_v2] WARN event calendar date parse failed; "
        "skipping event"
    ) in captured.err
    assert "bad-date" in captured.err
    assert "task_generator_v2.py" in captured.err


def test_event_article_skips_existing_adjacent_event_task(tmp_path, monkeypatch) -> None:
    runtime_schedules = tmp_path / "runtime_schedules.json"
    runtime_schedules.write_text(json.dumps({"event_jobs": {"items": []}}), encoding="utf-8")
    monkeypatch.setattr(MODULE, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(
        MODULE,
        "EVENT_CALENDAR",
        [("fomc", "2026-06-18", "FOMC meeting June 2026")],
    )
    existing = [
        {
            "id": "event_article_fomc_2026-06-17_tminus7",
            "task_type": "event_article",
            "event_type": "FOMC",
            "event_date": "2026-06-17",
        }
    ]

    tasks = MODULE.generate_event_article_tasks(existing=existing, reference_date=date(2026, 6, 13))

    assert tasks == []
