from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_next_tasks_status.py"
SPEC = importlib.util.spec_from_file_location("sync_next_tasks_status", MODULE_PATH)
sync_next_tasks_status = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sync_next_tasks_status)


def test_apply_blocks_codex_desktop_experiment_without_codex_review(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    experiments = tmp_path / "experiments"
    exp_dir = experiments / "k7777"
    next_tasks.parent.mkdir(parents=True)
    exp_dir.mkdir(parents=True)
    (exp_dir / "README.md").write_text("# K7777\n\nStatus: PASS\n", encoding="utf-8")
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K7777",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "priority": "P3",
                    "claimed_by": "codex-desktop",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sync_next_tasks_status, "ROOT", tmp_path)
    monkeypatch.setattr(sync_next_tasks_status, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(sync_next_tasks_status, "EXPERIMENTS", experiments)
    monkeypatch.setattr(sys, "argv", ["sync_next_tasks_status.py", "--apply"])

    rc = sync_next_tasks_status.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    source = next(t for t in saved if t["id"] == "K7777")
    followup = next(t for t in saved if t["id"] == "K7777_codex_review_followup")
    assert source["status"] == "blocked"
    assert source["blocked_reason"] == "awaiting_codex_review"
    assert source["review_gate_previous_status"] == "succeeded"
    assert source["review_gate_followup_task_id"] == "K7777_codex_review_followup"
    assert followup["status"] == "pending"
    assert followup["task_type"] == "experiment"
    assert followup["related_k_id"] == "K7777"
    assert followup["dispatch_lane"] == "agent"


def test_existing_codex_review_artifact_prevents_review_gate_gap(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    experiments = tmp_path / "experiments"
    exp_dir = experiments / "k8888"
    next_tasks.parent.mkdir(parents=True)
    exp_dir.mkdir(parents=True)
    (exp_dir / "README.md").write_text("# K8888\n\nStatus: PASS\n", encoding="utf-8")
    (exp_dir / "codex_review.md").write_text("VERDICT=PASS\n", encoding="utf-8")
    original = [
        {
            "id": "K8888",
            "task_type": "experiment",
            "status": "succeeded",
            "priority": "P3",
            "claimed_by": "codex-desktop",
        }
    ]
    next_tasks.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(sync_next_tasks_status, "ROOT", tmp_path)
    monkeypatch.setattr(sync_next_tasks_status, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(sync_next_tasks_status, "EXPERIMENTS", experiments)
    monkeypatch.setattr(sys, "argv", ["sync_next_tasks_status.py", "--apply"])

    rc = sync_next_tasks_status.main()

    assert rc == 0
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original


def test_codex_review_artifact_under_reviews_dir_prevents_gap(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    experiments = tmp_path / "experiments"
    exp_dir = experiments / "k8889"
    reviews = exp_dir / "reviews"
    next_tasks.parent.mkdir(parents=True)
    reviews.mkdir(parents=True)
    (exp_dir / "README.md").write_text("# K8889\n\nStatus: PASS\n", encoding="utf-8")
    (reviews / "codex_review_20260620.md").write_text("VERDICT=PASS\n", encoding="utf-8")
    original = [
        {
            "id": "K8889",
            "task_type": "experiment",
            "status": "succeeded",
            "priority": "P3",
            "claimed_by": "codex-desktop",
        }
    ]
    next_tasks.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(sync_next_tasks_status, "ROOT", tmp_path)
    monkeypatch.setattr(sync_next_tasks_status, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(sync_next_tasks_status, "EXPERIMENTS", experiments)
    monkeypatch.setattr(sys, "argv", ["sync_next_tasks_status.py", "--apply"])

    rc = sync_next_tasks_status.main()

    assert rc == 0
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original
