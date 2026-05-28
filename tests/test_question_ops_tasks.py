from __future__ import annotations

import json
from pathlib import Path

from volpred.ops import questions


def _patch_project_path(monkeypatch, tmp_path: Path) -> None:
    def fake_project_path(*parts: str) -> Path:
        path = tmp_path
        for part in parts:
            path = path / part
        return path

    monkeypatch.setattr(questions, "project_path", fake_project_path)


def test_ensure_member_qa_task_creates_ranked_research_task(monkeypatch, tmp_path: Path):
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [
                {
                    "question_id": "abc12345-0000-0000-0000-000000000000",
                    "question": "台灣進口車比例為何提高？",
                    "proposer": "yaoxk1431",
                    "status": "ranked",
                    "score": 6.0,
                    "created_at": "2026-05-25T07:53:08+00:00",
                }
            ],
            "pending_questions": [],
        },
    )

    result = questions.ensure_member_qa_task()

    assert result["created"] is True
    assert result["mode"] == "research"
    next_tasks = json.loads((tmp_path / "storage" / "next_tasks.json").read_text())
    assert next_tasks[0]["task_type"] == "member_qa"
    assert next_tasks[0]["question_id"] == "abc12345-0000-0000-0000-000000000000"
    assert next_tasks[0]["task_mode"] == "research"


def test_ensure_member_qa_task_creates_evaluate_task_when_only_pending(monkeypatch, tmp_path: Path):
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [],
            "pending_questions": [
                {
                    "question_id": "def67890-0000-0000-0000-000000000000",
                    "question": "進口車帶動哪些台股受惠？",
                    "proposer": "reader",
                    "status": "evaluating",
                    "created_at": "2026-05-26T01:00:00+00:00",
                }
            ],
        },
    )

    result = questions.ensure_member_qa_task()

    assert result["created"] is True
    assert result["mode"] == "evaluate"
    next_tasks = json.loads((tmp_path / "storage" / "next_tasks.json").read_text())
    assert next_tasks[0]["task_mode"] == "evaluate"
    assert "question-ranking-workflow" in next_tasks[0]["description"]


def test_ensure_member_qa_task_dedupes_existing_active_task(monkeypatch, tmp_path: Path):
    _patch_project_path(monkeypatch, tmp_path)
    next_tasks_path = tmp_path / "storage" / "next_tasks.json"
    next_tasks_path.parent.mkdir(parents=True, exist_ok=True)
    next_tasks_path.write_text(
        json.dumps(
            [
                {
                    "id": "member_qa_existing",
                    "task_type": "member_qa",
                    "status": "pending",
                    "question_id": "dup00000-0000-0000-0000-000000000000",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [
                {
                    "question_id": "dup00000-0000-0000-0000-000000000000",
                    "question": "same question",
                    "proposer": "reader",
                    "status": "ranked",
                    "score": 5.0,
                    "created_at": "2026-05-26T01:00:00+00:00",
                }
            ],
            "pending_questions": [],
        },
    )

    result = questions.ensure_member_qa_task()

    assert result["created"] is False
    assert result["reason"] == "task_already_exists"
