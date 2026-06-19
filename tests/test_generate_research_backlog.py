from __future__ import annotations

import importlib.util
import json
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
