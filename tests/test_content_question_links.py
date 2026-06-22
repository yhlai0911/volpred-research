from __future__ import annotations

from volpred.ops import content


def test_mark_questions_answered_on_publish_warns_when_lookup_fails(monkeypatch, capsys):
    monkeypatch.setattr(content, "_get_article_id", lambda article_slug: "article-uuid")

    def fail_select(*args, **kwargs):
        raise RuntimeError("question link lookup down")

    monkeypatch.setattr(content, "_select_rows", fail_select)

    assert content._mark_questions_answered_on_publish("mile_question_article") == 0

    captured = capsys.readouterr()
    assert "[content_question_links] WARN mark answered failed on publish" in captured.out
    assert "article_slug=mile_question_article" in captured.out
    assert "RuntimeError: question link lookup down" in captured.out


def test_cleanup_question_article_links_warns_when_delete_fails(monkeypatch, capsys):
    monkeypatch.setattr(content, "_get_article_id", lambda article_slug: "article-uuid")
    monkeypatch.setattr(
        content,
        "_select_rows",
        lambda *args, **kwargs: [{"question_id": "question-1", "article_id": "article-uuid"}],
    )

    def fail_delete(*args, **kwargs):
        raise RuntimeError("question link delete down")

    monkeypatch.setattr(content, "_delete_where", fail_delete)

    assert content._cleanup_question_article_links("mile_question_article") == 0

    captured = capsys.readouterr()
    assert "[content_question_links] WARN cleanup failed" in captured.out
    assert "article_slug=mile_question_article" in captured.out
    assert "RuntimeError: question link delete down" in captured.out
