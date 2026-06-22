from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_session_drill_down_module():
    root = Path(__file__).resolve().parents[1]
    script_path = root / "scripts" / "session_drill_down.py"
    spec = importlib.util.spec_from_file_location("session_drill_down_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scan_jsonl_warns_on_bad_lines_without_blocking(tmp_path: Path, capsys) -> None:
    mod = _load_session_drill_down_module()
    jsonl = tmp_path / "session.jsonl"
    valid = {
        "type": "assistant",
        "timestamp": "2026-06-22T01:02:03Z",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1},
            "content": [{"type": "text", "text": "ok"}],
        },
    }
    bad_ts = {
        "type": "assistant",
        "timestamp": "not-a-timestamp",
        "message": {"model": "claude-opus-4-7", "content": []},
    }
    missing_ts = {
        "type": "assistant",
        "message": {"model": "claude-opus-4-7", "content": []},
    }
    jsonl.write_text(
        "\n".join([
            json.dumps(valid),
            "{bad-json",
            json.dumps(bad_ts),
            json.dumps(missing_ts),
        ]),
        encoding="utf-8",
    )

    rows = mod.scan_jsonl(jsonl)

    assert len(rows) == 1
    assert rows[0][2] == {"input_tokens": 1}
    err = capsys.readouterr().err
    assert "[session_drill_down] WARN JSONL line parse failed; skipping" in err
    assert "[session_drill_down] WARN assistant timestamp parse failed; skipping" in err
    assert "[session_drill_down] WARN assistant message missing timestamp; skipping" in err
    assert "session.jsonl:2" in err
    assert "JSONDecodeError" in err


def test_scan_jsonl_warns_on_unreadable_path(tmp_path: Path, capsys) -> None:
    mod = _load_session_drill_down_module()
    missing = tmp_path / "missing.jsonl"

    rows = mod.scan_jsonl(missing)

    assert rows == []
    err = capsys.readouterr().err
    assert "[session_drill_down] WARN JSONL file read failed; returning empty session" in err
    assert "missing.jsonl" in err
    assert "FileNotFoundError" in err
