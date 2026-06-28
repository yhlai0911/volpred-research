from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_build_experiments_index():
    module_path = ROOT / "scripts" / "build_experiments_index.py"
    spec = importlib.util.spec_from_file_location("build_experiments_index", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_load_knowledge_k_map_warns_on_invalid_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_build_experiments_index()
    bad_knowledge = tmp_path / "knowledge.json"
    bad_knowledge.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(module, "KNOWLEDGE_PATH", bad_knowledge)

    assert module.load_knowledge_k_map() == {}
    captured = capsys.readouterr()

    assert "[experiments_index] WARN knowledge.json parse failed" in captured.err
    assert "JSONDecodeError" in captured.err
    assert str(bad_knowledge) in captured.err


def test_readme_extractors_warn_on_unreadable_path(tmp_path: Path, capsys) -> None:
    module = _load_build_experiments_index()
    readme_dir = tmp_path / "README.md"
    readme_dir.mkdir()

    assert module.first_heading(readme_dir) == ""
    assert module.readme_date(readme_dir) is None
    captured = capsys.readouterr()

    assert "README heading read failed" in captured.err
    assert "README date read failed" in captured.err
    assert "IsADirectoryError" in captured.err


def test_readme_heading_warns_when_missing(tmp_path: Path, capsys) -> None:
    module = _load_build_experiments_index()
    missing = tmp_path / "missing_README.md"

    assert module.first_heading(missing) == ""
    captured = capsys.readouterr()

    assert "README missing; using UNKNOWN title" in captured.err
    assert "FileNotFoundError" in captured.err
    assert str(missing) in captured.err


def test_readme_date_warns_on_invalid_date_field(tmp_path: Path, capsys) -> None:
    module = _load_build_experiments_index()
    readme = tmp_path / "README.md"
    readme.write_text("# K999\n\nDate: 2026-99-99\n", encoding="utf-8")

    assert module.readme_date(readme) is None
    captured = capsys.readouterr()

    assert "README date parse failed; using fallback date" in captured.err
    assert "ValueError" in captured.err
    assert str(readme) in captured.err


def test_load_paper_k_map_warns_when_markdown_read_fails(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_build_experiments_index()
    paper_dir = tmp_path / "paper"
    paper_sub = paper_dir / "sample-paper"
    paper_sub.mkdir(parents=True)
    readme = paper_sub / "README.md"
    readme.write_text("K123", encoding="utf-8")
    monkeypatch.setattr(module, "PAPER_DIR", paper_dir)

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):
        if self == readme:
            raise OSError("simulated read failure")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert module.load_paper_k_map() == {}
    captured = capsys.readouterr()

    assert "paper markdown read failed; skipping paper coverage source" in captured.err
    assert "OSError: simulated read failure" in captured.err
    assert str(readme) in captured.err


def test_git_first_commit_date_warns_on_probe_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_build_experiments_index()
    target = tmp_path / "k999"
    target.mkdir()

    def fail_check_output(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.subprocess, "check_output", fail_check_output)

    assert module.git_first_commit_date(target) is None
    captured = capsys.readouterr()

    assert "git first-commit date lookup failed; using fallback date" in captured.err
    assert "OSError: git unavailable" in captured.err


def test_git_first_commit_date_allows_untracked_paths_silently(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_build_experiments_index()
    target = tmp_path / "k999"
    target.mkdir()

    def missing_from_git(*_args, **_kwargs):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.subprocess, "check_output", missing_from_git)

    assert module.git_first_commit_date(target) is None
    assert capsys.readouterr().err == ""


def test_summarize_warns_on_invalid_explicit_date(capsys) -> None:
    module = _load_build_experiments_index()

    summary = module.summarize(
        [
            {
                "k_id": "k999",
                "verdict": "-",
                "feed": "-",
                "paper": "-",
                "date": "not-a-date",
                "date_explicit": True,
            }
        ]
    )
    captured = capsys.readouterr()

    assert summary["active_last_30d_readme_dated"] == 0
    assert summary["readme_has_explicit_date"] == 1
    assert "explicit README date parse failed in summary k_id=k999" in captured.err
