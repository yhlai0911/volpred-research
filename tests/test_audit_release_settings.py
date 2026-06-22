from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_release_settings.py"
SPEC = importlib.util.spec_from_file_location("audit_release_settings", MODULE_PATH)
audit_release_settings = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit_release_settings)


def test_invalid_local_release_settings_warns(tmp_path, monkeypatch, capsys) -> None:
    settings_path = tmp_path / "storage" / ".release_settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(audit_release_settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["audit_release_settings.py", "--json"])

    rc = audit_release_settings.main()

    assert rc == 0
    captured = capsys.readouterr()
    assert "[audit] WARN local release settings read failed" in captured.err
    assert str(settings_path) in captured.err
    payload = json.loads(captured.out)
    assert payload == {"status": "no_local_file", "ok": False}


def test_non_object_local_release_settings_warns(tmp_path, monkeypatch, capsys) -> None:
    settings_path = tmp_path / "storage" / ".release_settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(["bad-schema"]), encoding="utf-8")
    monkeypatch.setattr(audit_release_settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["audit_release_settings.py", "--json"])

    rc = audit_release_settings.main()

    assert rc == 0
    captured = capsys.readouterr()
    assert "[audit] WARN local release settings schema is not an object" in captured.err
    assert str(settings_path) in captured.err
    payload = json.loads(captured.out)
    assert payload == {"status": "no_local_file", "ok": False}
