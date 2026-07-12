from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "scan_trending_agy.py"
SPEC = importlib.util.spec_from_file_location("scan_trending_agy", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeProc:
    """Stand-in for the Popen handle scan_trending_agy drives."""

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.args = [MODULE.AGY]
        self.pid = -1
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout=None):  # noqa: ARG002 - mirrors Popen signature
        return self._stdout, self._stderr


@pytest.fixture(autouse=True)
def no_real_agy(monkeypatch):
    """A test that forgets to stub Popen must fail loudly, not shell out to the real agy."""

    def forbidden(*args, **kwargs):
        raise AssertionError("scan_trending_agy tests must not spawn the real agy CLI")

    monkeypatch.setattr(MODULE.subprocess, "Popen", forbidden)


def _stub_popen(monkeypatch, proc: FakeProc) -> None:
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *args, **kwargs: proc)


def test_main_warns_on_nonzero_agy_exit(monkeypatch, capsys):
    _stub_popen(monkeypatch, FakeProc(returncode=2, stdout="", stderr="auth failed"))

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["candidates"] == []
    assert payload["error"] == "agy_exit_nonzero"
    assert payload["returncode"] == 2
    assert payload["stderr_tail"] == "auth failed"
    assert "[scan_trending_agy] WARN agy command exited nonzero returncode=2" in captured.err


def test_main_warns_when_no_json_from_agy(monkeypatch, capsys):
    _stub_popen(monkeypatch, FakeProc(returncode=0, stdout="not json", stderr=""))

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["candidates"] == []
    assert payload["error"] == "no_json_from_agy"
    assert payload["raw_tail"] == "not json"
    assert "[scan_trending_agy] WARN agy output did not contain JSON candidates" in captured.err


def test_main_warns_when_agy_binary_missing(monkeypatch, capsys):
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", MODULE.AGY)

    monkeypatch.setattr(MODULE.subprocess, "Popen", raise_missing)

    assert MODULE.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["candidates"] == []
    assert payload["error"] == "FileNotFoundError"
    assert "[scan_trending_agy] WARN agy command failed before producing output" in captured.err


def test_main_returns_candidates_from_agy_json(monkeypatch, capsys):
    stdout = '```json\n[{"topic": "AI capex", "title": "t", "description": "d"}]\n```'
    _stub_popen(monkeypatch, FakeProc(returncode=0, stdout=stdout, stderr=""))

    assert MODULE.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == [{"topic": "AI capex", "title": "t", "description": "d"}]


def test_main_kills_process_group_on_timeout(monkeypatch, capsys):
    killed: list[int] = []

    class TimingOutProc(FakeProc):
        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)

        def wait(self):
            return -9

    _stub_popen(monkeypatch, TimingOutProc(returncode=-9, stdout="", stderr=""))
    monkeypatch.setattr(MODULE.os, "getpgid", lambda pid: 4242)
    monkeypatch.setattr(MODULE.procutil, "kill_pgid", lambda pgid: killed.append(pgid))

    assert MODULE.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == []
    assert payload["error"] == "TimeoutExpired"
    assert killed == [4242], "agy's process group must be killed, not just the pid we spawned"
