from __future__ import annotations

import importlib.util
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
