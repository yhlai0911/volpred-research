from __future__ import annotations

from pathlib import Path

from volpred.ops import papers


def test_sync_all_papers_warns_on_invalid_supabase_updated_at(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    paper_dir = tmp_path / "paper-a"
    paper_dir.mkdir()
    (paper_dir / "main.tex").write_text(r"\title{Paper A}", encoding="utf-8")

    monkeypatch.setattr(
        papers,
        "list_papers",
        lambda: [{"id": "paper-a", "updated_at": "not-a-date"}],
    )

    result = papers.sync_all_papers(dry_run=True, paper_root=tmp_path)

    assert result == [{"paper_id": "paper-a", "action": "would_update", "in_db": True}]
    err = capsys.readouterr().err
    assert "[papers] WARN Supabase updated_at parse failed; treating paper as stale" in err
    assert "paper_id=paper-a" in err
    assert "not-a-date" in err
    assert "ValueError" in err
