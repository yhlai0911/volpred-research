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

import contextlib
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

# A pair engineered to sit in the WARN band (0.35 <= s < 0.70): a real follow-up
# that overlaps an answered question but adds predictors it did not cover. The
# band membership is asserted in the test, not assumed here.
Q_GAP_BASE = "台指期夜盤的隔夜跳空能否用日內 realized vol 預測？"
Q_GAP_FOLLOWUP = (
    "台指期夜盤的隔夜跳空風險，能不能用日內波動率加上成交量與外資買賣超一起預測？"
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
    monkeypatch.setattr(questions, "_record_duplicate_override", lambda qid, r: True)
    # 2026-07-19 residual 3: the override now costs a written reason.
    result = questions.claim_question_for_research(
        ID_7PCT,
        allow_duplicate=True,
        new_angle="既有文章只回答 15% 目標，本題要的是 7% 下的提領率",
    )
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


def _summary(ranked, *, pending=None):
    """Ranking summary WITHOUT a history corpus.

    2026-07-19 residual 2: `ensure_member_qa_task` no longer reads history from
    the summary. History belongs to `member_qa_duplicate_verdict` alone, so
    these fixtures feed it via `_patch_history` instead — if a future change
    reintroduces a second corpus here, the tests below stop constraining it.
    """
    return {
        "health": {"researching": 0},
        "ranked_table": ranked,
        "pending_questions": pending or [],
    }


def _patch_history(monkeypatch, history):
    """Stub THE single history source (there is only one)."""
    monkeypatch.setattr(questions, "_fetch_question_history", lambda source: history)


def test_re_asked_question_becomes_duplicate_review_not_research(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(
        monkeypatch,
        [
            {
                "question_id": ID_15PCT,
                "question": Q_15PCT,
                "status": "answered",
                "linked_articles_count": 1,
            }
        ],
    )
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
            ]
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
    # The description must NOT read like a normal research commission.
    assert "預設不做新研究" in task["description"]
    # 2026-07-19 residual 3: the gate must not hand out its own bypass key.
    # A pasteable override command in the task description is a gate that
    # opens itself, so the description carries the *requirement*, not the
    # command. (`--help` is where the syntax lives.)
    assert "--allow-duplicate" not in task["description"]
    assert "question-claim --help" in task["description"]
    assert "exit 2" in task["description"]


def test_fresh_question_is_not_starved_behind_a_duplicate(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    fresh_id = "aaaaaaaa-0000-0000-0000-000000000000"
    _patch_history(
        monkeypatch,
        [{"question_id": ID_15PCT, "question": Q_15PCT, "status": "answered"}],
    )
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
            ]
        ),
    )

    result = questions.ensure_member_qa_task()
    assert result["created"] is True
    assert result["mode"] == "research"
    assert result["question_id"] == fresh_id


def test_unreachable_history_fails_closed(monkeypatch, tmp_path):
    """Fail-closed survives the move to a single owner.

    Previously this was pinned as "summary is missing 'answered_history'".
    History no longer arrives via the summary, so the same property is pinned
    where it now lives: if the one corpus cannot be loaded, no task is written.
    """
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: _summary(
            [
                {
                    "question_id": ID_7PCT,
                    "question": Q_7PCT,
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                }
            ]
        ),
    )

    def _boom(source):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(questions, "_fetch_question_history", _boom)
    with pytest.raises(RuntimeError):
        questions.ensure_member_qa_task()
    assert not (tmp_path / "storage" / "next_tasks.json").exists()


# --- residual 2: ONE adjudicator, ONE corpus -------------------------------


def test_neither_consumer_adjudicates_on_its_own():
    """Source-level pin: the consumers delegate, they do not re-implement.

    `find_duplicate_question` stays as the adjudicator's internal detail, so a
    runtime stub cannot tell "consumer called it" from "the owner called it".
    Reading the two consumer bodies can: neither may name the low-level matcher
    or a history fetch, and both must name the owner.
    """
    import inspect

    for fn in (questions.claim_question_for_research, questions.ensure_member_qa_task):
        body = inspect.getsource(fn)
        assert "member_qa_duplicate_verdict(" in body, fn.__name__
        assert "find_duplicate_question(" not in body, fn.__name__
        assert "_fetch_question_history(" not in body, fn.__name__
        assert "answered_history" not in body, fn.__name__


def _history_rows():
    return [{"question_id": ID_15PCT, "question": Q_15PCT, "status": "answered"}]


def test_claim_delegates_to_the_single_adjudicator(monkeypatch):
    """`claim_question_for_research` must not compute its own verdict."""
    monkeypatch.setattr(
        questions,
        "_select_rows",
        lambda table, select=None, **kw: [
            {"id": ID_7PCT, "question": Q_7PCT, "status": "ranked", "source": "user"}
        ],
    )
    calls: list[tuple] = []
    real = questions.member_qa_duplicate_verdict

    def _spy(question_id, question_text, **kw):
        calls.append((question_id, question_text, kw.get("source")))
        return real(question_id, question_text, **kw)

    _patch_history(monkeypatch, _history_rows())
    monkeypatch.setattr(questions, "member_qa_duplicate_verdict", _spy)

    result = questions.claim_question_for_research(ID_7PCT)
    assert result["claimed"] is False
    assert len(calls) == 1
    assert calls[0][0] == ID_7PCT


def test_materializer_delegates_to_the_single_adjudicator(monkeypatch, tmp_path):
    """`ensure_member_qa_task` must use the same owner and the same corpus."""
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _history_rows())
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
                }
            ]
        ),
    )
    calls: list[str] = []
    real = questions.member_qa_duplicate_verdict

    def _spy(question_id, question_text, **kw):
        calls.append(question_id)
        return real(question_id, question_text, **kw)

    monkeypatch.setattr(questions, "member_qa_duplicate_verdict", _spy)

    result = questions.ensure_member_qa_task()
    assert result["mode"] == "duplicate_review"
    assert calls == [ID_7PCT]


def test_both_consumers_share_one_history_fetch_per_source(monkeypatch, tmp_path):
    """The corpus is fetched by the adjudicator, and cached within a pass."""
    fetches: list[str] = []

    def _fetch(source):
        fetches.append(source)
        return _history_rows()

    monkeypatch.setattr(questions, "_fetch_question_history", _fetch)
    _patch_project_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        questions,
        "get_member_question_ranking_summary",
        lambda source="user", limit=10: _summary(
            [
                {
                    "question_id": ID_7PCT,
                    "question": Q_7PCT,
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                },
                {
                    "question_id": "bbbbbbbb-0000-0000-0000-000000000000",
                    "question": Q_15PCT,
                    "status": "ranked",
                    "created_at": "2026-07-18T06:19:41+00:00",
                },
            ]
        ),
    )
    questions.ensure_member_qa_task()
    # Two candidates adjudicated, one corpus load — the cache is a cache, and
    # the corpus is not re-derived per candidate.
    assert fetches == ["user"]


# --- residual 2: verdict tri-state ----------------------------------------


def test_verdict_is_block_for_the_incident_pair(monkeypatch):
    _patch_history(monkeypatch, _history_rows())
    verdict = questions.member_qa_duplicate_verdict(ID_7PCT, Q_7PCT)
    assert verdict["verdict"] == "block"
    assert verdict["matched_question_id"] == ID_15PCT
    assert verdict["similarity"] >= questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    assert "block" in verdict["basis"]


def test_verdict_is_warn_between_the_thresholds(monkeypatch):
    """A follow-up that overlaps an answered question without repeating it.

    The pair is checked to actually sit in the warn band first: a threshold or
    tokenizer change that moves it out must fail as "the fixture no longer
    exercises warn", not silently stop testing the middle verdict.
    """
    assert (
        questions.MEMBER_QA_DUP_WARN_THRESHOLD
        <= questions.question_similarity(Q_GAP_BASE, Q_GAP_FOLLOWUP)
        < questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    )
    _patch_history(
        monkeypatch,
        [{"question_id": ID_15PCT, "question": Q_GAP_BASE, "status": "answered"}],
    )
    verdict = questions.member_qa_duplicate_verdict(ID_7PCT, Q_GAP_FOLLOWUP)
    assert verdict["verdict"] == "warn"
    assert (
        questions.MEMBER_QA_DUP_WARN_THRESHOLD
        <= verdict["similarity"]
        < questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    )
    assert verdict["matched_question_id"] == ID_15PCT


def test_verdict_is_clear_for_an_unrelated_question(monkeypatch):
    _patch_history(monkeypatch, _history_rows())
    verdict = questions.member_qa_duplicate_verdict(
        ID_7PCT, "BTC 的波動率預測能不能用傳統 GARCH？有什麼要注意的？"
    )
    assert verdict["verdict"] == "clear"
    assert verdict["matched_question_id"] is None
    assert verdict["matched"] is None


def test_warn_does_not_block_the_claim(monkeypatch):
    """warn is an annotation, not a refusal — it must reach the PATCH."""
    _patch_history(
        monkeypatch,
        [
            {
                "question_id": ID_15PCT,
                "question": Q_CONGRESS_FOLLOW,
                "status": "answered",
            }
        ],
    )
    monkeypatch.setattr(
        questions,
        "_select_rows",
        lambda table, select=None, **kw: [
            {
                "id": ID_7PCT,
                "question": Q_CONGRESS_FADE,
                "status": "ranked",
                "source": "user",
            }
        ],
    )
    monkeypatch.setattr(
        questions,
        "_patch_where_returning",
        lambda table, where, payload: [{"id": ID_7PCT, "status": "researching"}],
    )
    assert questions.claim_question_for_research(ID_7PCT)["claimed"] is True


# --- residual 3: the gate must not hand out its own bypass key -------------


def test_override_without_a_reason_is_refused(monkeypatch):
    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a reasonless override must not reach the PATCH")

    monkeypatch.setattr(questions, "_patch_where_returning", _explode)
    for reason in (None, "", "   "):
        with pytest.raises(questions.MemberQaOverrideReasonRequired):
            questions.claim_question_for_research(
                ID_7PCT, allow_duplicate=True, new_angle=reason
            )


def test_override_with_a_reason_is_written_to_the_work_log(monkeypatch):
    entries: list[dict] = []
    monkeypatch.setattr(
        questions,
        "_patch_where_returning",
        lambda table, where, payload: [{"id": ID_7PCT, "status": "researching"}],
    )
    monkeypatch.setattr(
        questions,
        "_record_duplicate_override",
        lambda qid, reason: entries.append({"qid": qid, "reason": reason}) or True,
    )
    result = questions.claim_question_for_research(
        ID_7PCT,
        allow_duplicate=True,
        new_angle="既有文章只談 15% 目標的資產配置，本題要的是 7% 下的提領率",
    )
    assert result["claimed"] is True
    assert result["duplicate_override_logged"] is True
    assert entries and entries[0]["qid"] == ID_7PCT
    assert "提領率" in entries[0]["reason"]


def test_override_reason_routes_through_the_locked_work_log_writer(monkeypatch):
    """Never a hand-rolled JSON append (scripts/tests/test_work_log_writer_gate)."""
    import scripts.append_work_log as awl

    seen: list[dict] = []
    monkeypatch.setattr(awl, "append_entry", lambda entry, **kw: seen.append(entry) or 1)
    assert questions._record_duplicate_override(ID_7PCT, "新角度：提領率") is True
    assert seen and seen[0]["task_type"] == "member_qa"
    assert "提領率" in seen[0]["summary"]
    assert ID_7PCT in seen[0]["summary"]


def test_cli_question_claim_exits_2_without_new_angle():
    """The bypass path is unusable without a written reason."""
    from click.testing import CliRunner

    from volpred.cli import cli

    result = CliRunner().invoke(
        cli, ["ops", "question-claim", ID_7PCT, "--allow-duplicate"]
    )
    assert result.exit_code == 2
    assert "--new-angle" in result.output


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


# --- G1b: missing question_id is FAIL-CLOSED (2026-07-22 residual 1) --------
# Until this change a member_qa publish with no details['question_id'] was let
# through with a warning ("unjudged"). That made the only reader-facing gate a
# no-op for anyone who simply omitted the key. Flipping it to fail-closed was
# gated on first backfilling the two historical unbound articles:
#   mile_530a28bc -> bound to df669347… (retracted 1st attempt; live answer is
#                    mile_42ee876c, so a re-publish now correctly needs supersedes)
#   mile_e4002f4f -> waived: commissioned as task K1466_article_general, byline
#                    "[提出：Claude，執行：Claude]", no matching row in `questions`

VALID_WAIVER = {
    "reason": (
        "Commissioned as task K1466_article_general (audience=general, auto-discovered "
        "uncovered K); byline names no member and a sweep of all 89 `questions` rows "
        "returns no match. Answers no member question, so nothing can be bound."
    ),
    "adjudicated_by": "dispatch:member_qa_dedup_owner_convergence_20260719",
    "adjudicated_at": "2026-07-22T04:00:00+00:00",
}


def test_missing_question_id_now_fails_closed(monkeypatch):
    """The cheapest bypass (just omit the key) must no longer clear the gate."""
    _no_remote(monkeypatch)
    with pytest.raises(content.MemberQaPublishGateIndeterminate) as exc:
        content.assert_member_qa_publish_allowed(None, feed=[], title="會員提問｜x")
    msg = str(exc.value)
    # The error must be ACTIONABLE: name the key, the CLI flag, and the waiver.
    assert "question_id" in msg
    assert "--question-id" in msg
    assert "question_id_waiver" in msg


def test_missing_question_id_is_indeterminate_not_a_duplicate(monkeypatch):
    """'Cannot judge' must not be reported as 'this is a duplicate'."""
    _no_remote(monkeypatch)
    with pytest.raises(content.MemberQaPublishGateIndeterminate):
        content.assert_member_qa_publish_allowed(None, feed=[])
    # MemberQaDuplicatePublishError and MemberQaPublishGateIndeterminate are
    # siblings, not parent/child: catching one must never catch the other.
    assert not issubclass(
        content.MemberQaPublishGateIndeterminate, content.MemberQaDuplicatePublishError
    )
    assert not issubclass(
        content.MemberQaDuplicatePublishError, content.MemberQaPublishGateIndeterminate
    )


def test_empty_string_question_id_also_fails_closed(monkeypatch):
    """Falsy-but-present must not sneak past as 'set'."""
    _no_remote(monkeypatch)
    for empty in ("", "   ", None):
        with pytest.raises(content.MemberQaPublishGateIndeterminate):
            content.assert_member_qa_publish_allowed(empty, feed=[])


def test_valid_waiver_clears_with_an_explicit_verdict(monkeypatch, capsys):
    _no_remote(monkeypatch)
    result = content.assert_member_qa_publish_allowed(
        None, feed=[], waiver=dict(VALID_WAIVER)
    )
    assert result["blocked"] is False
    assert result["verdict"] == "unbound_waived"
    assert result["waiver"]["adjudicated_by"] == VALID_WAIVER["adjudicated_by"]
    # A waiver being used is not a silent event.
    assert "waiver" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "bad, why",
    [
        ({k: v for k, v in VALID_WAIVER.items() if k != "reason"}, "no reason"),
        ({k: v for k, v in VALID_WAIVER.items() if k != "adjudicated_by"}, "unsigned"),
        ({k: v for k, v in VALID_WAIVER.items() if k != "adjudicated_at"}, "undated"),
        ({**VALID_WAIVER, "reason": "legacy"}, "placeholder reason"),
        ({**VALID_WAIVER, "reason": "   "}, "blank reason"),
        ({**VALID_WAIVER, "adjudicated_by": ""}, "blank signer"),
        ({**VALID_WAIVER, "adjudicated_at": "whenever"}, "non-ISO date"),
        ("waived", "bare string, not an object"),
        (True, "truthy scalar"),
        ({}, "empty object"),
    ],
)
def test_malformed_waiver_still_fails_closed(monkeypatch, bad, why):
    """The waiver must not degrade into a copy-pasteable bypass token."""
    _no_remote(monkeypatch)
    with pytest.raises(content.MemberQaPublishGateIndeterminate, match="waiver|question_id"):
        content.assert_member_qa_publish_allowed(None, feed=[], waiver=bad)


def test_rejected_waiver_says_what_was_wrong(monkeypatch):
    _no_remote(monkeypatch)
    with pytest.raises(content.MemberQaPublishGateIndeterminate) as exc:
        content.assert_member_qa_publish_allowed(
            None, feed=[], waiver={**VALID_WAIVER, "reason": "legacy"}
        )
    assert "reason" in str(exc.value)


def test_waiver_does_not_bypass_the_duplicate_check(monkeypatch):
    """A waiver excuses a MISSING binding; it must not excuse a real duplicate."""
    _no_remote(monkeypatch)
    feed = [_published_answer(ART_15PCT, ID_15PCT)]
    with pytest.raises(content.MemberQaDuplicatePublishError):
        content.assert_member_qa_publish_allowed(
            ID_15PCT, feed=feed, waiver=dict(VALID_WAIVER)
        )


def test_publish_milestone_fails_closed_without_a_question_id(monkeypatch, tmp_path):
    """End-to-end: the publisher call site must forward the waiver, and must
    refuse an unbound member_qa publish."""
    from volpred.publisher.publisher import Publisher

    _no_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    monkeypatch.setattr(Publisher, "_load_feed", lambda self: [])
    kwargs = dict(
        title="會員提問｜未綁定的提問",
        description="body",
        phase="member_qa",
        audience="member_qa",
        category="member_qa",
    )
    with pytest.raises(content.MemberQaPublishGateIndeterminate):
        pub.publish_milestone(details={"content_type": "member_qa"}, **kwargs)

    # …and details['question_id_waiver'] must actually REACH the gate. Pinned
    # with a spy rather than by asserting the publish succeeds, so the test does
    # not depend on the unrelated publishing steps that run after the gate.
    gate_saw: dict = {}
    real = content.assert_member_qa_publish_allowed

    def _spy(question_id, **kw):
        gate_saw.update(kw)
        return real(question_id, **kw)

    monkeypatch.setattr(content, "assert_member_qa_publish_allowed", _spy)
    with contextlib.suppress(Exception):
        pub.publish_milestone(
            details={"content_type": "member_qa", "question_id_waiver": dict(VALID_WAIVER)},
            **kwargs,
        )
    assert gate_saw.get("waiver") == VALID_WAIVER, "publisher did not forward the waiver"


def test_every_live_member_qa_article_still_passes_the_gate(monkeypatch):
    """Regression: the fail-closed flip must not strand any EXISTING article.

    Reads the canonical feed. Every member_qa article must now either carry a
    question_id or a valid waiver — this is the check that the A-before-B
    ordering (backfill first, tighten second) actually held.
    """
    _no_remote(monkeypatch)
    feed_path = Path(__file__).resolve().parents[1] / "storage" / "reports" / "feed.json"
    if not feed_path.exists():  # pragma: no cover - canonical feed absent in CI
        pytest.skip("canonical feed.json not available")
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    qa = [
        a
        for a in feed
        if isinstance(a, dict)
        and (a.get("audience") == "member_qa" or a.get("category") == "member_qa")
    ]
    assert len(qa) >= 15, f"expected the known member_qa corpus, got {len(qa)}"

    unbound = []
    for art in qa:
        details = art.get("details") or {}
        if details.get("question_id"):
            continue
        checked, err = content._validate_question_id_waiver(
            details.get("question_id_waiver")
        )
        if checked is None:
            unbound.append((art.get("id"), err))
    assert not unbound, f"member_qa articles that the tightened gate would strand: {unbound}"


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


# --- residual 4: warn-band adjudication is persisted and computed ONCE ------


def _warn_history():
    return [{"question_id": ID_15PCT, "question": Q_GAP_BASE, "status": "answered"}]


def test_warn_band_triggers_one_semantic_adjudication(monkeypatch, tmp_path):
    """A warn-band pair is handed to the adjudicator; its answer moves the verdict."""
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    calls: list[tuple[str, str, float]] = []

    def _adjudicator(a: str, b: str, similarity: float):
        calls.append((a, b, similarity))
        return "duplicate", "同一份研究即可回答"

    verdict = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_adjudicator
    )
    assert len(calls) == 1
    assert (
        questions.MEMBER_QA_DUP_WARN_THRESHOLD
        <= calls[0][2]
        < questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    )
    # `duplicate` escalates the mechanical warn to a refusal.
    assert verdict["verdict"] == "block"
    assert verdict["adjudication"]["adjudication"] == "duplicate"
    assert verdict["adjudication"]["cached"] is False
    assert "adjudication=duplicate" in verdict["basis"]


def test_distinct_adjudication_downgrades_the_warn_to_clear(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    verdict = questions.member_qa_duplicate_verdict(
        ID_7PCT,
        Q_GAP_FOLLOWUP,
        adjudicator=lambda a, b, s: ("distinct", "需要新的預測變數"),
    )
    assert verdict["verdict"] == "clear"
    assert verdict["adjudication"]["adjudication"] == "distinct"


def test_adjudication_is_persisted_with_an_auditable_record(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=lambda a, b, s: ("distinct", "理由")
    )
    store = json.loads(
        (
            tmp_path / "storage" / "ops" / "member_qa_duplicate_adjudications.json"
        ).read_text(encoding="utf-8")
    )
    entry = store["pairs"][questions.member_qa_pair_key(ID_7PCT, ID_15PCT)]
    assert entry["adjudication"] == "distinct"
    assert entry["reason"] == "理由"
    assert entry["adjudicated_at"]
    assert (
        questions.MEMBER_QA_DUP_WARN_THRESHOLD
        <= entry["similarity"]
        < questions.MEMBER_QA_DUP_BLOCK_THRESHOLD
    )
    assert entry["pair"] == sorted([ID_7PCT, ID_15PCT])


def test_second_call_for_the_same_pair_reads_the_cache(monkeypatch, tmp_path):
    """The whole point of the store: adjudicate once, never re-litigate.

    The counter is the proof — a second verdict for the same pair must not
    reach the adjudicator at all, otherwise the same two questions could get
    two different answers on two different shifts.
    """
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    calls = {"n": 0}

    def _adjudicator(a, b, s):
        calls["n"] += 1
        return "duplicate", "同一份研究"

    first = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_adjudicator
    )
    second = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_adjudicator
    )
    assert calls["n"] == 1
    assert first["verdict"] == second["verdict"] == "block"
    assert first["adjudication"]["cached"] is False
    assert second["adjudication"]["cached"] is True


def test_pair_key_is_order_independent(monkeypatch, tmp_path):
    """(a,b) and (b,a) are ONE entry — two entries would allow two verdicts."""
    _patch_project_path(monkeypatch, tmp_path)
    assert questions.member_qa_pair_key(
        ID_7PCT, ID_15PCT
    ) == questions.member_qa_pair_key(ID_15PCT, ID_7PCT)
    calls = {"n": 0}

    def _adjudicator(a, b, s):
        calls["n"] += 1
        return "distinct", "r"

    # Adjudicate A→B, then ask B→A: the reversed pair must hit the same entry.
    _patch_history(monkeypatch, _warn_history())
    questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_adjudicator
    )
    _patch_history(
        monkeypatch,
        [{"question_id": ID_7PCT, "question": Q_GAP_FOLLOWUP, "status": "answered"}],
    )
    reversed_call = questions.member_qa_duplicate_verdict(
        ID_15PCT, Q_GAP_BASE, adjudicator=_adjudicator
    )
    assert calls["n"] == 1
    assert reversed_call["adjudication"]["cached"] is True


def test_unavailable_adjudicator_falls_back_to_warn_and_is_not_cached(
    monkeypatch, tmp_path
):
    """Fallback = the identity operation, and it must leave no fossil.

    Caching "the LLM was down" would freeze one outage into a permanent verdict
    for this pair, because the store is read first and unconditionally.
    """
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())

    def _unavailable(a, b, s):
        raise questions.WarnBandAdjudicatorUnavailable("agy not on PATH")

    verdict = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_unavailable
    )
    assert verdict["verdict"] == "warn"  # neither cleared nor blocked
    assert verdict["adjudication"]["adjudication"] == "unavailable"
    assert verdict["adjudication"]["persisted"] is False
    assert not (
        tmp_path / "storage" / "ops" / "member_qa_duplicate_adjudications.json"
    ).exists()

    # ...and the next shift re-asks rather than reading a fossilised verdict.
    calls = {"n": 0}

    def _adjudicator(a, b, s):
        calls["n"] += 1
        return "distinct", "r"

    again = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=_adjudicator
    )
    assert calls["n"] == 1
    assert again["verdict"] == "clear"


def test_no_adjudicator_at_all_is_the_same_conservative_fallback(monkeypatch, tmp_path):
    """No LLM resolvable in this process (the default under pytest)."""
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    monkeypatch.setattr(questions, "_default_warn_band_adjudicator", lambda: None)
    verdict = questions.member_qa_duplicate_verdict(ID_7PCT, Q_GAP_FOLLOWUP)
    assert verdict["verdict"] == "warn"
    assert verdict["adjudication"]["adjudication"] == "unavailable"
    assert verdict["adjudication"]["persisted"] is False


def test_malformed_adjudicator_answer_is_treated_as_unavailable(monkeypatch, tmp_path):
    _patch_project_path(monkeypatch, tmp_path)
    _patch_history(monkeypatch, _warn_history())
    verdict = questions.member_qa_duplicate_verdict(
        ID_7PCT, Q_GAP_FOLLOWUP, adjudicator=lambda a, b, s: ("maybe", "shrug")
    )
    assert verdict["verdict"] == "warn"
    assert verdict["adjudication"]["adjudication"] == "unavailable"
    assert verdict["adjudication"]["persisted"] is False


def test_block_and_clear_bands_never_consult_the_adjudicator(monkeypatch, tmp_path):
    """Adjudication is a warn-band tool only — the mechanical bands are decided."""
    _patch_project_path(monkeypatch, tmp_path)

    def _explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("outside the warn band nothing may be adjudicated")

    _patch_history(monkeypatch, _history_rows())
    assert (
        questions.member_qa_duplicate_verdict(ID_7PCT, Q_7PCT, adjudicator=_explode)[
            "verdict"
        ]
        == "block"
    )
    assert (
        questions.member_qa_duplicate_verdict(
            ID_7PCT, "BTC 波動率能不能用 GARCH 預測？", adjudicator=_explode
        )["verdict"]
        == "clear"
    )


def test_the_test_suite_never_reaches_a_live_model():
    """PYTEST_CURRENT_TEST is set → the default adjudicator refuses to shell out."""
    assert questions._default_warn_band_adjudicator() is None


# --- residual 5: the release path runs the SAME G1 gate --------------------


def _member_qa_feed(tmp_path: Path, items: list[dict]) -> Path:
    feed_path = tmp_path / "storage" / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return feed_path


def _promote(item: dict, storage_dir: Path) -> dict:
    from datetime import datetime, timezone

    return content._atomic_promote_release_item(
        dict(item),
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
        released_at="2026-07-19T00:00:00+00:00",
        storage_dir=str(storage_dir),
        route="release_pool",
        expected_item=item,
    )


def test_release_promotion_blocks_a_duplicate_member_qa_answer(tmp_path, monkeypatch):
    """release_pool's status rewrite must hit G1, not bypass it."""
    prior = {
        "id": ART_15PCT,
        "title": "會員提問｜已回答",
        "status": "published",
        "audience": "member_qa",
        "published_at": "2026-07-12T00:00:00+00:00",
        "details": {"question_id": ID_15PCT},
    }
    draft = {
        "id": ART_7PCT,
        "title": "會員提問｜再問一次",
        "status": "scheduled",
        "audience": "member_qa",
        "created_at": "2026-07-19T00:00:00+00:00",
        "details": {"question_id": ID_15PCT},
    }
    feed_path = _member_qa_feed(tmp_path, [prior, draft])
    monkeypatch.setattr(
        content, "_member_qa_remote_prior_answers", lambda qid: ([], None)
    )

    outcome = _promote(draft, tmp_path / "storage")
    assert outcome["outcome"] == "member_qa_publish_blocked"
    assert "member_qa_duplicate_publish_blocked" in outcome["reason"]
    # Fail-closed means the draft stays a draft, not that the whole run dies.
    assert json.loads(feed_path.read_text(encoding="utf-8"))[1]["status"] == "scheduled"


def test_release_promotion_blocks_member_qa_without_a_question_id(tmp_path):
    """The fail-closed unbound branch reaches the release path too."""
    draft = {
        "id": ART_7PCT,
        "title": "會員提問｜沒綁 question_id",
        "status": "scheduled",
        "audience": "member_qa",
        "created_at": "2026-07-19T00:00:00+00:00",
        "details": {},
    }
    _member_qa_feed(tmp_path, [draft])
    outcome = _promote(draft, tmp_path / "storage")
    assert outcome["outcome"] == "member_qa_publish_blocked"
    assert "member_qa_publish_gate_indeterminate" in outcome["reason"]


def test_release_promotion_allows_a_first_member_qa_answer(tmp_path, monkeypatch):
    """The gate must not deadlock the lane: a `scheduled` article is not its own
    duplicate (exclude_article_id), so a first answer still releases."""
    draft = {
        "id": ART_7PCT,
        "title": "會員提問｜第一次回答",
        "status": "scheduled",
        "audience": "member_qa",
        "created_at": "2026-07-19T00:00:00+00:00",
        "details": {"question_id": ID_7PCT},
    }
    _member_qa_feed(tmp_path, [draft])
    monkeypatch.setattr(
        content, "_member_qa_remote_prior_answers", lambda qid: ([], None)
    )
    assert _promote(draft, tmp_path / "storage")["outcome"] == "promoted"


def test_gate_applicability_predicate_covers_every_member_qa_marker():
    assert content.member_qa_publish_gate_applies({"audience": "general"}) is False
    assert (
        content.member_qa_publish_gate_applies(
            {"audience": "member_qa", "status": "retracted"}
        )
        is False
    )
    assert content.member_qa_publish_gate_applies({"audience": "member_qa"}) is True
    assert content.member_qa_publish_gate_applies({"category": "member_qa"}) is True
    assert (
        content.member_qa_publish_gate_applies(
            {"details": {"content_type": "member_qa"}}
        )
        is True
    )
    assert content.member_qa_publish_gate_applies({"phase": "member_qa_answer"}) is True


def test_both_publish_paths_share_one_applicability_predicate():
    """Anti-stacking pin: publish_milestone must not re-implement the test."""
    import inspect

    from volpred.publisher import publisher as publisher_mod

    src = inspect.getsource(publisher_mod.Publisher.publish_milestone)
    assert "member_qa_publish_gate_applies" in src
    # The inline copy of the predicate must be gone.
    assert "str(audience or '').strip() == 'member_qa'" not in src
