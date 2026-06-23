"""Tests for volpred.ops.diagnostics."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from volpred.ops import diagnostics
from volpred.ops.diagnostics import warn


@pytest.fixture(autouse=True)
def _redirect_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path / "diag_logs")
    yield


def test_warn_writes_tag_prefix_and_msg(capsys):
    warn("dispatch", "claim failed")
    captured = capsys.readouterr()
    assert "[dispatch] WARN claim failed" in captured.err
    assert captured.out == ""


def test_warn_appends_ctx_kv_pairs(capsys):
    warn("refill", "skipped", task_id="t1", count=3)
    err = capsys.readouterr().err
    assert "[refill] WARN skipped" in err
    assert "task_id=t1" in err
    assert "count=3" in err


def test_warn_truncates_long_ctx_values(capsys):
    huge = "x" * 500
    warn("cron", "blob", payload=huge)
    err = capsys.readouterr().err
    assert "...<truncated>" in err
    assert len(err) < 500


def test_warn_stream_override():
    buf = io.StringIO()
    warn("tag", "hi", stream=buf)
    assert buf.getvalue().startswith("[tag] WARN hi")


def test_warn_no_persist_by_default(capsys, monkeypatch):
    monkeypatch.delenv("VOLPRED_DIAGNOSTICS_PERSIST", raising=False)
    warn("foo", "no persist")
    capsys.readouterr()
    assert not diagnostics.LOG_DIR.exists()


def test_warn_persist_when_env_set(capsys, monkeypatch):
    monkeypatch.setenv("VOLPRED_DIAGNOSTICS_PERSIST", "1")
    warn("foo", "yes persist", k=1)
    capsys.readouterr()
    log = diagnostics.LOG_DIR / "foo.jsonl"
    assert log.exists()
    line = log.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["tag"] == "foo"
    assert rec["msg"] == "yes persist"
    assert rec["ctx"] == {"k": 1}
    assert "ts" in rec


def test_warn_persist_safe_for_non_json_ctx(capsys, monkeypatch):
    monkeypatch.setenv("VOLPRED_DIAGNOSTICS_PERSIST", "1")
    warn("foo", "obj", path=Path("/tmp/x"), err=ValueError("bad"))
    capsys.readouterr()
    log = diagnostics.LOG_DIR / "foo.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").strip())
    assert isinstance(rec["ctx"]["path"], str)
    assert "bad" in rec["ctx"]["err"]


def test_warn_persist_failure_does_not_raise(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VOLPRED_DIAGNOSTICS_PERSIST", "1")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    monkeypatch.setattr(diagnostics, "LOG_DIR", blocker / "diag")
    warn("foo", "should not raise")
    err = capsys.readouterr().err
    assert "[foo] WARN should not raise" in err
    assert "[diagnostics] WARN persist failed" in err


def test_persist_env_truthy_variants(capsys, monkeypatch):
    for val in ["1", "true", "YES", "On"]:
        monkeypatch.setenv("VOLPRED_DIAGNOSTICS_PERSIST", val)
        assert diagnostics._persist_enabled(), val
    monkeypatch.setenv("VOLPRED_DIAGNOSTICS_PERSIST", "0")
    assert not diagnostics._persist_enabled()


def test_warn_bytes_ctx(capsys):
    warn("foo", "bytes", payload=b"hello")
    err = capsys.readouterr().err
    assert "payload=hello" in err
