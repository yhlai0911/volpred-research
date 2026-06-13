"""Tests for task_generator_v2 stale backlog guards."""
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "task_generator_v2.py"
SPEC = importlib.util.spec_from_file_location("task_generator_v2_for_test", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
tg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tg)


def test_generate_experiment_tasks_skips_completed_k_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    research_program = tmp_path / "research_program.md"
    experiments = tmp_path / "experiments"
    completed = experiments / "k1061"
    completed.mkdir(parents=True)
    (completed / "README.md").write_text("# K1061 done\n", encoding="utf-8")
    research_program.write_text(
        "\n".join(
            [
                "- [ ] **K1061**: already completed experiment",
                "- [ ] **K9999**: genuinely new experiment",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(tg, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(tg, "EXPERIMENTS_DIR", experiments)

    tasks = tg.generate_experiment_tasks([])
    ids = {task["id"] for task in tasks}

    assert "gen_exp_1061" not in ids
    assert "gen_exp_9999" in ids


def test_generate_experiment_tasks_skips_readme_documented_no_k_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stale_item = "台灣 5-min 數據 HAR-RV（0050.TW 47 天，ETA 2026 Q2）"
    fresh_item = "全新無 K 編號探索題"
    research_program = tmp_path / "research_program.md"
    experiments = tmp_path / "experiments"
    completed = experiments / "k1325"
    completed.mkdir(parents=True)
    (completed / "README.md").write_text(
        f"# K1325\n\n原始待辦：\n\n> {stale_item}\n",
        encoding="utf-8",
    )
    research_program.write_text(
        "\n".join(
            [
                f"- [ ] {stale_item}",
                f"- [ ] {fresh_item}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(tg, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(tg, "EXPERIMENTS_DIR", experiments)

    tasks = tg.generate_experiment_tasks([])
    descriptions = [task["description"] for task in tasks]

    assert all(stale_item not in description for description in descriptions)
    assert any(fresh_item in description for description in descriptions)
