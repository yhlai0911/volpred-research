from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "session_replay_pending.py"
SPEC = importlib.util.spec_from_file_location("session_replay_pending", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_main_returns_1_on_invalid_pending_json(tmp_path, monkeypatch, capsys):
    pending = tmp_path / "pending_sessions.json"
    pending.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "PENDING_PATH", pending)
    monkeypatch.setattr(MODULE.sys, "argv", ["session_replay_pending.py", "--dry-run"])

    assert MODULE.main() == 1

    captured = capsys.readouterr()
    assert "[session-replay] ERROR pending_sessions read failed; cannot mark replayed" in captured.err
    assert "JSONDecodeError" in captured.err
    assert captured.out == ""


def test_main_skips_bad_job_entries_but_marks_valid_job(tmp_path, monkeypatch, capsys):
    pending = tmp_path / "pending_sessions.json"
    pending.write_text(
        json.dumps(
            {
                "jobs": {
                    "bad_schema": "not a job",
                    "bad_count": {"recorded_count": "nan"},
                    "ok_job": {
                        "recorded_count": 1,
                        "recorded_at": "2026-06-23T00:00:00+00:00",
                        "replayed_at": None,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "PENDING_PATH", pending)
    monkeypatch.setattr(MODULE.sys, "argv", ["session_replay_pending.py", "--dry-run"])

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    assert "pending_sessions job schema invalid; skipping job_id=bad_schema" in captured.err
    assert "pending_sessions recorded_count invalid; skipping job_id=bad_count" in captured.err
    assert "Marked replayed: 1" in captured.out
    assert "ok_job" in captured.out
    assert "Total recorded_count" in captured.out
