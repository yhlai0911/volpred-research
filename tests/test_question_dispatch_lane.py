from __future__ import annotations

import json
from pathlib import Path

from volpred.ops import questions


def test_member_qa_materializer_marks_agent_dispatch_lane(monkeypatch, tmp_path: Path) -> None:
    def fake_project_path(*parts: str) -> Path:
        path = tmp_path
        for part in parts:
            path = path / part
        return path

    monkeypatch.setattr(questions, "project_path", fake_project_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [
                {
                    "question_id": "abc12345-0000-0000-0000-000000000000",
                    "question": "台股波動率是否出現 regime change?",
                    "proposer": "reader",
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
    tasks = json.loads((tmp_path / "storage" / "next_tasks.json").read_text(encoding="utf-8"))
    assert tasks[0]["task_type"] == "member_qa"
    assert tasks[0]["dispatch_lane"] == "agent"
