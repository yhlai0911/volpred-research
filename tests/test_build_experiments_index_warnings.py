from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime, timezone
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


def test_scan_k_dirs_uses_one_bulk_git_date_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_build_experiments_index()
    experiments_dir = tmp_path / "experiments"
    for name in ("k1", "k2"):
        directory = experiments_dir / name
        directory.mkdir(parents=True)
        (directory / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    calls = 0

    def bulk_dates() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"k1": "2026-01-01", "k2": "2026-01-02"}

    monkeypatch.setattr(module, "EXPERIMENTS_DIR", experiments_dir)
    monkeypatch.setattr(module, "git_first_commit_date_map", bulk_dates)
    monkeypatch.setattr(
        module,
        "git_first_commit_date",
        lambda _path: (_ for _ in ()).throw(AssertionError("per-directory git probe")),
    )

    rows = module.scan_k_dirs()

    assert calls == 1
    assert {row["k_id"]: row["date"] for row in rows} == {
        "k1": "2026-01-01",
        "k2": "2026-01-02",
    }


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


def test_research_metrics_projection_distinguishes_indexed_experiments_from_artifacts(
    tmp_path: Path,
) -> None:
    module = _load_build_experiments_index()
    experiments_dir = tmp_path / "experiments"
    (experiments_dir / "k1").mkdir(parents=True)
    (experiments_dir / "k2").mkdir()
    (experiments_dir / "k1" / "K1_results.json").write_text("{}", encoding="utf-8")
    (experiments_dir / "k1" / "K1_robustness_results.json").write_text(
        "{}", encoding="utf-8"
    )
    (experiments_dir / "k2" / "K2_result.json").write_text("{}", encoding="utf-8")
    generated_at = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)

    payload = module.build_research_metrics_payload(
        {"total": 2},
        generated_at=generated_at,
        experiments_dir=experiments_dir,
    )

    assert payload == {
        "schema_version": 1,
        "generated_at": "2026-07-30T10:00:00+00:00",
        "source_index": "experiments/index.json",
        "indexed_experiments": 2,
        "result_artifacts": 3,
    }


def test_research_metrics_projection_writes_declared_frontend_target(
    tmp_path: Path,
) -> None:
    module = _load_build_experiments_index()
    target = tmp_path / "frontend" / "data" / "research_metrics.json"
    payload = {
        "schema_version": 1,
        "generated_at": "2026-07-30T10:00:00+00:00",
        "source_index": "experiments/index.json",
        "indexed_experiments": 2,
        "result_artifacts": 3,
    }

    written = module.write_research_metrics_projection(payload, [target])

    assert written == [target]
    assert json.loads(target.read_text(encoding="utf-8")) == payload
