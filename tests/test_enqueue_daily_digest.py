from __future__ import annotations

import sys
from pathlib import Path

import scripts.enqueue_daily_digest as module


def _patch_paths(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    feed = tmp_path / "feed.json"
    next_tasks = tmp_path / "next_tasks.json"
    monkeypatch.setattr(module, "FEED", feed)
    monkeypatch.setattr(module, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(module, "_today_str", lambda: "2026-06-23")
    return feed, next_tasks


def test_dry_run_would_enqueue_when_sources_are_valid(tmp_path: Path, monkeypatch, capsys):
    feed, next_tasks = _patch_paths(tmp_path, monkeypatch)
    feed.write_text("[]", encoding="utf-8")
    next_tasks.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["enqueue_daily_digest.py", "--dry-run"])

    assert module.main() == 0

    captured = capsys.readouterr()
    assert "DRY-RUN would add: daily_digest_20260623" in captured.out
    assert captured.err == ""
    assert next_tasks.read_text(encoding="utf-8") == "[]"


def test_corrupt_feed_aborts_to_avoid_duplicate_digest(tmp_path: Path, monkeypatch, capsys):
    feed, next_tasks = _patch_paths(tmp_path, monkeypatch)
    feed.write_text("{bad json", encoding="utf-8")
    next_tasks.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["enqueue_daily_digest.py", "--dry-run"])

    assert module.main() == 1

    captured = capsys.readouterr()
    assert "[digest-enqueue] WARN feed JSON read failed; aborting" in captured.err
    assert "abort to avoid duplicate digest" in captured.err


def test_corrupt_next_tasks_aborts_without_rewriting_pool(tmp_path: Path, monkeypatch, capsys):
    feed, next_tasks = _patch_paths(tmp_path, monkeypatch)
    feed.write_text("[]", encoding="utf-8")
    next_tasks.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["enqueue_daily_digest.py"])

    assert module.main() == 1

    captured = capsys.readouterr()
    assert "[digest-enqueue] WARN next_tasks JSON read failed; aborting" in captured.err
    assert "不亂建任務池" in captured.err
    assert next_tasks.read_text(encoding="utf-8") == "{bad json"
