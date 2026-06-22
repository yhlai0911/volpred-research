from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_session_health.py"
if str(MODULE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("check_session_health", MODULE_PATH)
check_session_health = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(check_session_health)


def test_invalid_token_policy_warns_and_uses_default(tmp_path, monkeypatch, capsys) -> None:
    policy_path = tmp_path / "token_policy.json"
    policy_path.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(check_session_health, "POLICY_PATH", policy_path)

    policy = check_session_health.load_session_health_policy()

    captured = capsys.readouterr()
    assert policy == check_session_health.DEFAULT_POLICY
    assert "[session_health] WARN token policy read failed" in captured.err
    assert str(policy_path) in captured.err


def test_invalid_session_health_section_warns_and_uses_default(tmp_path, monkeypatch, capsys) -> None:
    policy_path = tmp_path / "token_policy.json"
    policy_path.write_text(json.dumps({"session_health": ["bad-schema"]}), encoding="utf-8")
    monkeypatch.setattr(check_session_health, "POLICY_PATH", policy_path)

    policy = check_session_health.load_session_health_policy()

    captured = capsys.readouterr()
    assert policy == check_session_health.DEFAULT_POLICY
    assert "[session_health] WARN token policy session_health section is missing or invalid" in captured.err
    assert str(policy_path) in captured.err
