from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from volpred.ops import termination


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
    monkeypatch.setattr(
        MODULE,
        "authorize_provider_spawn",
        lambda **kwargs: SimpleNamespace(
            resolved_executable=kwargs["executable_path"],
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "agy-cli",
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        ),
    )
    monkeypatch.setattr(MODULE, "verify_spawn_receipt", lambda _receipt: None)


def _stub_popen(monkeypatch, proc: FakeProc) -> None:
    monkeypatch.setattr(MODULE.subprocess, "Popen", lambda *args, **kwargs: proc)


def test_provider_policy_denial_precedes_agy_popen(monkeypatch, capsys):
    monkeypatch.setattr(
        MODULE,
        "authorize_provider_spawn",
        lambda **_kwargs: (_ for _ in ()).throw(
            MODULE.ProviderRegistryError("API key path denied")
        ),
        raising=False,
    )

    assert MODULE.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == []
    assert payload["error"] == "provider_policy_denied"
    assert "API key path denied" in payload["detail"]


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
    killed: list[tuple[int, object | None]] = []
    armed_intent = object()

    class TimingOutProc(FakeProc):
        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)

        def wait(self):
            return -9

    _stub_popen(monkeypatch, TimingOutProc(returncode=-9, stdout="", stderr=""))
    monkeypatch.setattr(MODULE.os, "getpgid", lambda pid: 4242)
    monkeypatch.setattr(termination, "arm", lambda **kwargs: armed_intent)
    monkeypatch.setattr(
        MODULE.procutil,
        "kill_pgid",
        lambda pgid, *, intent=None: killed.append((pgid, intent)),
    )

    assert MODULE.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] == []
    assert payload["error"] == "TimeoutExpired"
    assert killed == [
        (4242, armed_intent)
    ], "agy's process group must be killed under its durable intent"
