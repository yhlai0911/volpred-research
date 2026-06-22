from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "drain_failed_supabase_syncs.py"
    spec = importlib.util.spec_from_file_location("drain_failed_supabase_syncs", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


drain = _load_script_module()


def test_load_list_warns_when_queue_json_is_invalid(tmp_path, capsys):
    queue_path = tmp_path / ".failed_supabase_syncs.json"
    queue_path.write_text("{bad json", encoding="utf-8")

    assert drain._load_list(queue_path) == []

    captured = capsys.readouterr()
    assert "[drain] WARN queue JSON read failed; treating as empty" in captured.out
    assert ".failed_supabase_syncs.json" in captured.out
    assert "JSONDecodeError" in captured.out


def test_load_list_warns_when_queue_json_is_not_a_list(tmp_path, capsys):
    queue_path = tmp_path / ".failed_supabase_syncs.json"
    queue_path.write_text('{"mile": "x"}', encoding="utf-8")

    assert drain._load_list(queue_path) == []

    captured = capsys.readouterr()
    assert "[drain] WARN queue JSON is not a list; treating as empty" in captured.out
    assert ".failed_supabase_syncs.json" in captured.out
