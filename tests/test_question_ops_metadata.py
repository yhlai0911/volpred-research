from __future__ import annotations

from pathlib import Path

from volpred.ops import questions


def test_article_status_lookup_failure_warns(monkeypatch, capsys):
    def fail_select(*args, **kwargs):
        raise RuntimeError("supabase unavailable")

    monkeypatch.setattr(questions, "_select_rows", fail_select)

    assert questions._get_article_status("mile_test") is None

    captured = capsys.readouterr()
    assert "[question_ops] WARN article status lookup failed" in captured.out
    assert "slug=mile_test" in captured.out
    assert "supabase unavailable" in captured.out


def test_question_article_link_failure_warns(monkeypatch, capsys):
    import scripts.supabase_sync as supabase_sync

    monkeypatch.setattr(supabase_sync, "_get_article_id", lambda article_slug: "article-uuid")

    def fail_post(*args, **kwargs):
        raise RuntimeError("link insert failed")

    monkeypatch.setattr(questions, "_post", fail_post)

    assert questions._link_question_article("question-1", "mile_test") is False

    captured = capsys.readouterr()
    assert "[question_ops] WARN question_articles link failed" in captured.out
    assert "question_id=question-1" in captured.out
    assert "article_slug=mile_test" in captured.out
    assert "link insert failed" in captured.out


def test_article_question_metadata_failure_warns(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.chdir(tmp_path)
    reports_dir = tmp_path / "storage" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text("{bad json", encoding="utf-8")

    questions._ensure_article_question_metadata("mile_test", "question-1")

    captured = capsys.readouterr()
    assert "[question_ops] WARN article question metadata update failed" in captured.out
    assert "article_slug=mile_test" in captured.out
    assert "question_id=question-1" in captured.out
    assert "Expecting property name" in captured.out
