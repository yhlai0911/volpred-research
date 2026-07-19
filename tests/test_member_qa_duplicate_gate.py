"""Regression pins for the member_qa duplicate gate (2026-07-19 incident).

Incident: member yaoxk1431 asked the same question twice, one week apart, with
only the target return number changed. Both were researched and published as
near-identical member_qa articles:

  e79a7097 (2026-07-11) → mile_d84aa7d0  "…資金穩定每年成長 15%…"
  3e258ba2 (2026-07-18) → mile_0205a444  "…資金穩定每年成長 7%…"

The strings below are the real question texts from Supabase. They are pinned
verbatim so that any future change to the tokenizer / threshold that would let
this pair through fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops import questions

# --- real incident corpus (verbatim from Supabase `questions`) --------------
Q_15PCT = "如果我要接下來30年我的資金穩定每年成長15%, 我該問什麼問題, 我必須掌握投資的15個問題"
Q_7PCT = "如果我要接下來30年我的資金穩定每年成長7%, 我該問什麼問題, 我必須掌握投資的15個問題"
ID_15PCT = "e79a7097-0000-0000-0000-000000000000"
ID_7PCT = "3e258ba2-0000-0000-0000-000000000000"

# Highest-scoring *legitimate* pair in the same live corpus (0.386): congressional
# trades, follow vs fade. Two genuinely different studies — must NOT be blocked.
Q_CONGRESS_FOLLOW = (
    "如果看美國國會議員比較大的持股項目和變化 雖然公告時間落後 但是否還是具有一定的獲利性？ "
    "另外 不是看單一人 而是看整體"
)
Q_CONGRESS_FADE = (
    "如果把美國過會議員比較大的持股項目和變化 在公告後 逆向操作呢？ "
    "賣出買入最多（或增加買入最多）的 同時買入賣出最多（或增加賣出最多）的"
)


def _patch_project_path(monkeypatch, tmp_path: Path) -> None:
    def fake_project_path(*parts: str) -> Path:
        path = tmp_path
        for part in parts:
            path = path / part
        return path

    monkeypatch.setattr(questions, "project_path", fake_project_path)


# --- similarity core -------------------------------------------------------


def test_incident_pair_is_recognised_as_the_same_question():
    """15% vs 7% differ only by digits — the tokenizer strips them."""
    similarity = questions.question_similarity(Q_15PCT, Q_7PCT)
    assert similarity == pytest.approx(1.0)
    assert similarity >= questions.MEMBER_QA_DUP_BLOCK_THRESHOLD


def test_legitimate_related_pair_stays_below_the_block_threshold():
    similarity = questions.question_similarity(Q_CONGRESS_FOLLOW, Q_CONGRESS_FADE)
    assert similarity < questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    # Margin check: if a tokenizer change pushes this above ~0.5 the threshold
    # is no longer separating the incident from healthy follow-up questions.
    assert similarity < 0.5


def test_unrelated_questions_score_near_zero():
    assert questions.question_similarity(
        "請問 VIX 和台灣加權指數的相關性有多高？",
        "BTC 的波動率預測能不能用傳統 GARCH？有什麼要注意的？",
    ) < 0.35


def test_find_duplicate_ignores_questions_that_never_consumed_research():
    """A ranked-but-unanswered sibling is not a reason to refuse work."""
    history = [
        {"question_id": ID_15PCT, "question": Q_15PCT, "status": "ranked"},
    ]
    assert questions.find_duplicate_question(Q_7PCT, history) is None

    history[0]["status"] = "answered"
    hit = questions.find_duplicate_question(Q_7PCT, history)
    assert hit is not None
    assert hit["question_id"] == ID_15PCT


def test_find_duplicate_excludes_the_question_itself():
    history = [{"question_id": ID_7PCT, "question": Q_7PCT, "status": "answered"}]
    assert (
        questions.find_duplicate_question(
            Q_7PCT, history, exclude_question_id=ID_7PCT
        )
        is None
    )


# --- gate 1: atomic claim --------------------------------------------------


def test_claim_is_refused_for_a_re_asked_question(monkeypatch):
    """The mandatory choke point refuses without ever touching the PATCH."""
    monkeypatch.setattr(
        questions,
        "_select_rows",
        lambda table, select=None, **kw: [
            {"id": ID_7PCT, "question": Q_7PCT, "status": "ranked", "source": "user"}
        ],
    )
    monkeypatch.setattr(
        questions,
        "_fetch_question_history",
        lambda source: [
            {"question_id": ID_15PCT, "question": Q_15PCT, "status": "answered"}
        ],
    )

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("duplicate question must not reach the claim PATCH")

    monkeypatch.setattr(questions, "_patch_where_returning", _explode)

    result = questions.claim_question_for_research(ID_7PCT)
    assert result["claimed"] is False
    assert result["duplicate_of"]["question_id"] == ID_15PCT
    assert "duplicate_of=" in result["reason"]


def test_claim_override_reaches_the_patch(monkeypatch):
    calls: list[tuple] = []

    def _patch(table, where, payload):
        calls.append((table, where, payload))
        return [{"id": ID_7PCT, "status": "researching"}]

    monkeypatch.setattr(questions, "_patch_where_returning", _patch)
    result = questions.claim_question_for_research(ID_7PCT, allow_duplicate=True)
    assert result["claimed"] is True
    assert calls and calls[0][1]["status"] == "ranked"


def test_claim_gate_does_not_swallow_history_lookup_failures(monkeypatch):
    """A guard rail inside a fail-open try is not a guard rail (2026-07-14)."""
    monkeypatch.setattr(
        questions,
        "_select_rows",
        lambda table, select=None, **kw: [
            {"id": ID_7PCT, "question": Q_7PCT, "status": "ranked", "source": "user"}
        ],
    )

    def _boom(source):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(questions, "_fetch_question_history", _boom)
    with pytest.raises(RuntimeError):
        questions.claim_question_for_research(ID_7PCT)


# --- gate 2: task materialization -----------------------------------------


def _summary(ranked, *, history, pending=None):
    return {
        "health": {"researching": 0},
        "ranked_table": ranked,
        "pending_questions": pending or [],
        "answered_history": history,
    }


def test_re_asked_question_becomes_duplicate_review_not_research(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: _summary(
            [
                {
                    "question_id": ID_7PCT,
                    "question": Q_7PCT,
                    "proposer": "yaoxk1431",
                    "status": "ranked",
                    "score": 82,
                    "created_at": "2026-07-18T06:19:41+00:00",
                }
            ],
            history=[
                {
                    "question_id": ID_15PCT,
                    "question": Q_15PCT,
                    "status": "answered",
                    "linked_articles_count": 1,
                }
            ],
        ),
    )

    result = questions.ensure_member_qa_task()

    assert result["created"] is True
    assert result["mode"] == "duplicate_review"
    assert result["duplicate_of"]["question_id"] == ID_15PCT

    tasks = json.loads((tmp_path / "storage" / "next_tasks.json").read_text())
    task = tasks[0]
    assert task["task_mode"] == "duplicate_review"
    assert task["duplicate_of"]["question_id"] == ID_15PCT
    assert "--allow-duplicate" in task["description"]
    # The description must NOT read like a normal research commission.
    assert "預設不做新研究" in task["description"]


def test_fresh_question_is_not_starved_behind_a_duplicate(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    fresh_id = "aaaaaaaa-0000-0000-0000-000000000000"
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: _summary(
            [
                {
                    "question_id": ID_7PCT,
                    "question": Q_7PCT,
                    "proposer": "yaoxk1431",
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                },
                {
                    "question_id": fresh_id,
                    "question": "台指期夜盤的隔夜跳空能否用日內 realized vol 預測？",
                    "proposer": "yaoxk1431",
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                },
            ],
            history=[
                {"question_id": ID_15PCT, "question": Q_15PCT, "status": "answered"}
            ],
        ),
    )

    result = questions.ensure_member_qa_task()
    assert result["created"] is True
    assert result["mode"] == "research"
    assert result["question_id"] == fresh_id


def test_missing_history_key_fails_closed(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: {
            "health": {"researching": 0},
            "ranked_table": [
                {
                    "question_id": ID_7PCT,
                    "question": Q_7PCT,
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                }
            ],
            "pending_questions": [],
        },
    )
    with pytest.raises(ValueError, match="answered_history"):
        questions.ensure_member_qa_task()
    assert not (tmp_path / "storage" / "next_tasks.json").exists()
