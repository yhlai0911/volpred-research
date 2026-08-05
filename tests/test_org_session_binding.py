"""A role's token spend should be measured, not inferred.

Token telemetry lives in `~/.claude/projects/**/*.jsonl` and carries no role
field: a department's identity arrives through `--append-system-prompt`, which
Claude Code does not write into the transcript. So "which department spent this"
has been answered heuristically — 95 sessions measured on 2026-08-05 came out
exact 22 / strong 15 / weak 44 / unknown 14, leaving 29.9% of the spend
unattributable. The session id is already in the environment and already names
the transcript file; writing it down once turns the whole question into a join.

The binding is recorded as a side effect of sending, because a step every role
already performs beats a step every role has to remember. That places one
requirement on it above all others: **it must never be able to fail a send.**
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ORG_DIR = Path(__file__).resolve().parents[1] / "scripts" / "org"


@pytest.fixture(scope="module")
def core():
    sys.path.insert(0, str(ORG_DIR))
    spec = importlib.util.spec_from_file_location(
        "org_core_session_test", ORG_DIR / "_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_binding_names_the_session_the_role_and_the_time(tmp_path, core, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-aaa")

    path = core.record_session(tmp_path / "org", "widgets")

    assert path is not None
    row = _lines(path)[0]
    assert row["session_id"] == "sess-aaa"
    assert row["dept"] == "widgets"
    assert row["started_at"], "a binding with no time cannot be joined to a spend window"


def test_recording_the_same_session_twice_adds_nothing(tmp_path, core, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-bbb")
    root = tmp_path / "org"

    core.record_session(root, "widgets")
    path = core.record_session(root, "widgets")

    assert len(_lines(path)) == 1, (
        "every send would otherwise append another identical row, and the file "
        "would grow with the shift instead of with the sessions"
    )


def test_a_pane_that_runs_several_sessions_keeps_all_of_them(tmp_path, core, monkeypatch):
    """This is why it is a log and not a field on the lease."""
    root = tmp_path / "org"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-morning")
    core.record_session(root, "widgets")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-evening")
    path = core.record_session(root, "widgets")

    assert [r["session_id"] for r in _lines(path)] == ["sess-morning", "sess-evening"], (
        "a single field would overwrite the earlier session — usually the one you "
        "went looking for"
    )


def test_no_session_id_in_the_environment_is_not_an_error(tmp_path, core, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    assert core.record_session(tmp_path / "org", "widgets") is None


def test_an_unwritable_runtime_dir_never_breaks_the_caller(tmp_path, core, monkeypatch):
    """The send is the work; this is bookkeeping riding along with it."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-ccc")
    blocked = tmp_path / "org"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("not a directory", encoding="utf-8")

    assert core.record_session(blocked, "widgets") is None
