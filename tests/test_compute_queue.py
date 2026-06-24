from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import audit_silent_fallbacks
import scripts.compute_queue as module


def _patch_queue_paths(tmp_path: Path, monkeypatch) -> Path:
    queue_dir = tmp_path / "compute_queue"
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(module, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(module, "LOG_DIR", log_dir)
    monkeypatch.setattr(module, "LOCK_FILE", queue_dir / ".worker.lock")
    return queue_dir


def test_list_jobs_warns_and_skips_bad_job_json(tmp_path: Path, monkeypatch, capsys):
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("{bad json", encoding="utf-8")
    (queue_dir / "good.json").write_text(
        json.dumps(
            {
                "id": "good",
                "status": "queued",
                "title": "valid compute job",
                "queued_at": "2026-06-23T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    rc = module.list_jobs(SimpleNamespace(status=None, completed_pending_followup=False, json=True))

    captured = capsys.readouterr()
    assert rc == 0
    assert "[compute_queue] WARN list job JSON read failed; skipping" in captured.err
    assert "bad.json" in captured.err
    payload = json.loads(captured.out)
    assert [item["id"] for item in payload] == ["good"]


def test_run_next_warns_and_skips_bad_job_json(tmp_path: Path, monkeypatch, capsys):
    queue_dir = _patch_queue_paths(tmp_path, monkeypatch)
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("{bad json", encoding="utf-8")

    rc = module.run_next(SimpleNamespace())

    captured = capsys.readouterr()
    assert rc == 0
    assert "[compute_queue] WARN run-next job JSON read failed; skipping" in captured.err
    assert "no queued jobs" in captured.out


def test_acquire_lock_warns_when_lock_cannot_be_written(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    lock_path = tmp_path / "missing-parent" / ".worker.lock"
    monkeypatch.setattr(module, "LOCK_FILE", lock_path)

    assert module._acquire_lock() is False

    captured = capsys.readouterr()
    assert "[compute_queue] WARN worker lock write failed; skipping run" in captured.err
    assert ".worker.lock" in captured.err
    assert "FileNotFoundError" in captured.err


def test_compute_queue_has_no_silent_fallback_audit_findings() -> None:
    findings = audit_silent_fallbacks.audit_file(Path(module.__file__))

    assert findings == []
