from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "scan_trending_agy.py"
SPEC = importlib.util.spec_from_file_location("scan_trending_agy", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_main_warns_on_nonzero_agy_exit(monkeypatch, capsys):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=2, stdout="", stderr="auth failed")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["candidates"] == []
    assert payload["error"] == "agy_exit_nonzero"
    assert payload["returncode"] == 2
    assert payload["stderr_tail"] == "auth failed"
    assert "[scan_trending_agy] WARN agy command exited nonzero returncode=2" in captured.err


def test_main_warns_when_no_json_from_agy(monkeypatch, capsys):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="not json", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["candidates"] == []
    assert payload["error"] == "no_json_from_agy"
    assert payload["raw_tail"] == "not json"
    assert "[scan_trending_agy] WARN agy output did not contain JSON candidates" in captured.err

