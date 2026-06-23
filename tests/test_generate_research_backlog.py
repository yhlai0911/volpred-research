from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_research_backlog.py"
SPEC = importlib.util.spec_from_file_location("generate_research_backlog", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _setup_paths(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    research_program = tmp_path / "research_program.md"
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    experiments_dir = tmp_path / "experiments"
    next_tasks.parent.mkdir(parents=True, exist_ok=True)
    experiments_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(MODULE, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(MODULE, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(MODULE, "EXPERIMENTS_DIR", experiments_dir)
    return research_program, next_tasks, experiments_dir


def test_build_experiment_brief_marks_agent_dispatch_lane():
    brief = MODULE.build_experiment_brief(
        {"text": "GARCH model regime test for volatility forecasting", "source_line": 12},
        1500,
    )

    assert brief["task_type"] == "experiment"
    assert brief["dispatch_lane"] == "agent"


def test_generate_backlog_all_covered_materializes_journal_discovery(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text(
        "- [ ] GARCH model regime test for VIX volatility spillover and variance forecasting\n",
        encoding="utf-8",
    )
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K1302",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "source": "research_backlog_auto",
                    "source_line": 1,
                }
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = MODULE.generate(dry_run=False, max_new=5)

    assert result["added"] == 1
    assert result["fallback_reason"] == "journal_discovery_dispatch"
    assert result["reason"] == "all_already_covered_or_in_progress"
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert len(data) == 2
    journal = data[1]
    assert journal["id"].startswith("journal_discovery_")
    assert journal["task_type"] == "platform_ops"
    assert journal["dispatch_lane"] == "agent"
    assert journal["source"] == "auto_journal_discovery_fallback"


def test_generate_backlog_apply_uses_reserved_k_id(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text(
        "- [ ] GARCH model regime test for ETF volatility forecasting using panel regression\n",
        encoding="utf-8",
    )
    next_tasks.write_text("[]\n", encoding="utf-8")
    reserved_items: list[str] = []

    def fake_reserve(item: dict) -> int:
        reserved_items.append(item["text"])
        return 2400

    monkeypatch.setattr(MODULE, "_reserve_backlog_k_id", fake_reserve)

    result = MODULE.generate(dry_run=False, max_new=5)

    assert result == {"ok": True, "added": 1, "added_ids": ["K2400"]}
    assert reserved_items == [
        "GARCH model regime test for ETF volatility forecasting using panel regression"
    ]
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert data[0]["id"] == "K2400"
    assert "K2400.py" in data[0]["description"]
    assert "K2400_results.json" in data[0]["description"]


def test_generate_backlog_dry_run_does_not_reserve_k_id(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text(
        "- [ ] HAR model stress test for VIX volatility spillover using rolling regression\n",
        encoding="utf-8",
    )
    next_tasks.write_text("[]\n", encoding="utf-8")

    def fail_reserve(_item: dict) -> int:
        raise AssertionError("dry-run must not reserve K-id")

    monkeypatch.setattr(MODULE, "_reserve_backlog_k_id", fail_reserve)

    result = MODULE.generate(dry_run=True, max_new=5)

    assert result["dry_run"] is True
    assert result["would_add"] == 1
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == []


def test_reserve_backlog_k_id_uses_shared_registry_floor(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text("# test\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_reserve_k_id(**kwargs) -> dict:
        seen.update(kwargs)
        return {"number": 2401}

    monkeypatch.setattr(MODULE, "reserve_k_id", fake_reserve_k_id)

    k_id = MODULE._reserve_backlog_k_id({"text": "HAR model volatility test"})

    assert k_id == 2401
    assert seen["claimed_by"] == "research_backlog_auto"
    assert seen["topic"] == "HAR model volatility test"
    assert seen["root"] == tmp_path
    assert seen["registry_path"] == tmp_path / "storage" / "ops" / "k_id_registry.json"
    assert seen["next_tasks_path"] == next_tasks
    assert seen["minimum"] == 1302


def test_generate_backlog_all_covered_dry_run_does_not_write(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text(
        "- [ ] HAR model rolling panel test for realized variance forecasting and VIX regimes\n",
        encoding="utf-8",
    )
    initial_tasks = [
        {
            "id": "K1302",
            "task_type": "experiment",
            "status": "pending",
            "source": "research_backlog_auto",
            "source_line": 1,
        }
    ]
    next_tasks.write_text(json.dumps(initial_tasks, ensure_ascii=False) + "\n", encoding="utf-8")

    result = MODULE.generate(dry_run=True, max_new=5)

    assert result["dry_run"] is True
    assert result["would_add"] == 1
    assert result["fallback_reason"] == "journal_discovery_dispatch"
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == initial_tasks


def test_generate_backlog_all_covered_skips_when_journal_live(
    tmp_path: Path,
    monkeypatch,
):
    research_program, next_tasks, _ = _setup_paths(tmp_path, monkeypatch)
    research_program.write_text(
        "- [ ] BMA regression test for volatility factor spillover and regime forecasting\n",
        encoding="utf-8",
    )
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K1302",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "source": "research_backlog_auto",
                    "source_line": 1,
                },
                {
                    "id": "journal_discovery_20260619_3",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "source": "auto_journal_discovery_fallback",
                },
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = MODULE.generate(dry_run=False, max_new=5)

    assert result == {
        "ok": True,
        "added": 0,
        "reason": "all_already_covered_or_in_progress",
        "journal_discovery": "skipped_recent_or_live",
    }
    data = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert len(data) == 2


def test_journal_discovery_warns_on_bad_cooldown_timestamp(capsys):
    tasks = [
        {
            "id": "journal_discovery_20260622_0",
            "task_type": "platform_ops",
            "status": "succeeded",
            "source": "auto_journal_discovery_fallback",
            "completed_at": "not-a-date",
        }
    ]

    generated = MODULE._journal_discovery_dispatch_task(
        tasks,
        existing_ids=set(),
        now_utc=datetime(2026, 6, 23, 5, tzinfo=timezone.utc),
    )

    assert len(generated) == 1
    err = capsys.readouterr().err
    assert "[research_backlog] WARN journal discovery timestamp parse failed" in err
    assert "not-a-date" in err
