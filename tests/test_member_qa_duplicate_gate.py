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


# --- gate 3: PUBLISH-TIME (the reader-visible artifact) ---------------------
# This is the gate the 2026-07-19 incident actually needed: both upstream gates
# guard an INTENT step and are bypassed by any caller that writes the article by
# hand and calls publish_milestone directly.

from volpred.ops import content  # noqa: E402


ART_15PCT = "mile_d84aa7d0"
ART_7PCT = "mile_0205a444"


def _published_answer(article_id: str, question_id: str, **over) -> dict:
    item = {
        "id": article_id,
        "title": "會員提問｜30 年每年成長",
        "status": "published",
        "audience": "member_qa",
        "category": "member_qa",
        "details": {"question_id": question_id},
    }
    item.update(over)
    return item


def _no_remote(monkeypatch):
    """Supabase returns nothing (healthy, empty) - local feed decides."""
    monkeypatch.setattr(content, "_select_rows", lambda table, select=None, **kw: [])


def test_publish_gate_blocks_second_answer_to_the_same_question(monkeypatch):
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT)]
    with pytest.raises(content.MemberQaDuplicatePublishError) as exc:
        content.assert_member_qa_publish_allowed(ID_15PCT, feed=feed)
    # The error must name the article that already exists.
    assert ART_15PCT in str(exc.value)


def test_publish_gate_allows_a_first_answer(monkeypatch):
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT)]
    result = content.assert_member_qa_publish_allowed(ID_7PCT, feed=feed)
    assert result["blocked"] is False
    assert result["verdict"] == "clear"


def test_publish_gate_counts_scheduled_answers_too(monkeypatch):
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT, status="scheduled")]
    with pytest.raises(content.MemberQaDuplicatePublishError):
        content.assert_member_qa_publish_allowed(ID_15PCT, feed=feed)


def test_publish_gate_ignores_unpublished_prior(monkeypatch):
    """A retracted/unpublished prior (e.g. mile_530a28bc) is not a live answer."""
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT, status="unpublished")]
    assert content.assert_member_qa_publish_allowed(ID_15PCT, feed=feed)["blocked"] is False


def test_supersedes_naming_the_prior_article_passes(monkeypatch):
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT)]
    result = content.assert_member_qa_publish_allowed(
        ID_15PCT, feed=feed, supersedes=ART_15PCT
    )
    assert result["verdict"] == "supersedes"
    assert result["blocked"] is False


def test_supersedes_must_name_every_prior_answer(monkeypatch):
    """Not an unconditional bypass: a truthy-but-wrong value must not clear."""
    _no_remote(monkeypatch)
    feed = [
        _published_answer(ART_15PCT, ID_15PCT),
        _published_answer("mile_other", ID_15PCT),
    ]
    with pytest.raises(content.MemberQaDuplicatePublishError):
        content.assert_member_qa_publish_allowed(
            ID_15PCT, feed=feed, supersedes=ART_15PCT
        )
    with pytest.raises(content.MemberQaDuplicatePublishError):
        content.assert_member_qa_publish_allowed(ID_15PCT, feed=feed, supersedes="yes")
    ok = content.assert_member_qa_publish_allowed(
        ID_15PCT, feed=feed, supersedes=f"{ART_15PCT},mile_other"
    )
    assert ok["verdict"] == "supersedes"


def test_publish_gate_sees_supabase_only_duplicates(monkeypatch):
    """Prior answer absent from this checkout's feed but present remotely."""

    def _rows(table, select=None, **kw):
        if table == "question_articles":
            return [{"question_id": ID_15PCT, "article_id": "uuid-1"}]
        if table == "articles":
            return [{"id": "uuid-1", "slug": ART_15PCT, "status": "published", "title": "x"}]
        return []

    monkeypatch.setattr(content, "_select_rows", _rows)
    with pytest.raises(content.MemberQaDuplicatePublishError) as exc:
        content.assert_member_qa_publish_allowed(ID_15PCT, feed=[])
    assert ART_15PCT in str(exc.value)


def test_supabase_outage_degrades_loudly_but_does_not_stall_the_line(monkeypatch, capsys):
    """'Cannot cross-check' must not silently become 'clear' - but a remote
    outage must not freeze member_qa publishing either."""

    def _boom(table, select=None, **kw):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(content, "_select_rows", _boom)
    result = content.assert_member_qa_publish_allowed(ID_7PCT, feed=[])
    assert result["blocked"] is False
    assert result["verdict"] == "clear_degraded"
    assert result["remote_ok"] is False
    assert "DEGRADED" in capsys.readouterr().out


def test_supabase_outage_still_blocks_a_locally_visible_duplicate(monkeypatch):
    def _boom(table, select=None, **kw):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(content, "_select_rows", _boom)
    with pytest.raises(content.MemberQaDuplicatePublishError):
        content.assert_member_qa_publish_allowed(
            ID_15PCT, feed=[_published_answer(ART_15PCT, ID_15PCT)]
        )


def test_unreadable_local_feed_is_indeterminate_not_clear(monkeypatch):
    _no_remote(monkeypatch)

    def _boom(storage_dir="storage"):
        raise OSError("feed.json unreadable")

    monkeypatch.setattr(content, "load_feed", _boom)
    with pytest.raises(content.MemberQaPublishGateIndeterminate):
        content.assert_member_qa_publish_allowed(ID_15PCT)


def test_publish_milestone_refuses_the_real_incident_pair(monkeypatch, tmp_path):
    """End-to-end through Publisher.publish_milestone: the exact STRIKE 2 shape."""
    from volpred.publisher.publisher import Publisher

    _no_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    monkeypatch.setattr(
        Publisher, "_load_feed", lambda self: [_published_answer(ART_15PCT, ID_15PCT)]
    )
    with pytest.raises(content.MemberQaDuplicatePublishError):
        pub.publish_milestone(
            title="會員提問｜想要30 年每年賺 7%",
            description="body",
            phase="member_qa",
            details={"question_id": ID_15PCT, "content_type": "member_qa"},
            audience="member_qa",
            category="member_qa",
        )


# --- G2: answer_internal_question idempotency ------------------------------


def test_answer_is_idempotent_when_a_published_answer_exists(monkeypatch):
    monkeypatch.setattr(
        questions,
        "_existing_published_answer_articles",
        lambda qid, exclude_article_id=None, storage_dir="storage": [ART_15PCT],
    )

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("must not re-bind / re-stamp an answered question")

    monkeypatch.setattr(questions, "_patch_where", _explode)
    monkeypatch.setattr(questions, "_link_question_article", _explode)

    result = questions.answer_internal_question(ID_15PCT, "answer", article_id=ART_7PCT)
    assert result["skipped"] is True
    assert result["reason"] == "already_answered"
    assert result["existing_articles"] == [ART_15PCT]
    assert result["linked_article"] is None


def test_answered_at_is_a_first_answer_stamp(monkeypatch, tmp_path):
    """Re-running the answer step for the SAME article must not move answered_at."""
    patches: list[dict] = []
    monkeypatch.setattr(
        questions,
        "_existing_published_answer_articles",
        lambda qid, exclude_article_id=None, storage_dir="storage": [],
    )
    monkeypatch.setattr(questions, "_get_article_status", lambda slug: "published")
    monkeypatch.setattr(
        questions, "_question_answered_at", lambda qid: "2026-07-12T00:00:00+00:00"
    )
    monkeypatch.setattr(questions, "_link_question_article", lambda q, a: True)
    monkeypatch.setattr(questions, "_ensure_article_question_metadata", lambda a, q: None)
    monkeypatch.setattr(
        questions, "_patch_where", lambda table, where, payload: patches.append(payload)
    )

    class _Mem:
        def __init__(self, storage_dir="storage"):
            pass

        def answer_question(self, qid, answer):
            return True

    monkeypatch.setattr(questions, "MemorySystem", _Mem)

    questions.answer_internal_question(
        ID_15PCT, "answer", storage_dir=str(tmp_path), article_id=ART_15PCT
    )
    assert patches and "answered_at" not in patches[0]
    assert patches[0]["status"] == "answered"
