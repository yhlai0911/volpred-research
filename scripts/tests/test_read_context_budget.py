"""Regression tests for the PreToolUse(Read) context budget hook.

The hook's whole value proposition is "bound the default, never break the
caller". These tests pin both halves: it must bite on unbounded reads of long
files, and it must be invisible everywhere else -- including on inputs designed
to make it throw.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "read_context_budget.py"
TRIGGER_LINES = 250
DEFAULT_LIMIT = 200


def run_hook(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook must never fail: {proc.stderr}"
    return json.loads(proc.stdout or "{}")


def read_payload(path, **tool_input) -> dict:
    return {"tool_name": "Read", "tool_input": {"file_path": str(path), **tool_input}}


def write_lines(tmp_path: Path, name: str, n: int) -> Path:
    p = tmp_path / name
    p.write_text("".join(f"line {i}\n" for i in range(n)))
    return p


def limit_of(out: dict):
    return out.get("hookSpecificOutput", {}).get("updatedInput", {}).get("limit")


def test_long_file_without_limit_gets_default_budget(tmp_path):
    big = write_lines(tmp_path, "big.py", 1000)
    out = run_hook(read_payload(big))
    assert limit_of(out) == DEFAULT_LIMIT
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    # the caller must be told the real size and how to page, or the budget is a trap
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "1001 lines" in ctx or "1000 lines" in ctx
    assert "offset" in ctx


def test_explicit_limit_is_never_overridden(tmp_path):
    big = write_lines(tmp_path, "big.py", 1000)
    assert run_hook(read_payload(big, limit=900)) == {}


def test_explicit_offset_is_never_overridden(tmp_path):
    """Paging through a file is exactly the behaviour we asked for; don't fight it."""
    big = write_lines(tmp_path, "big.py", 1000)
    assert run_hook(read_payload(big, offset=500)) == {}


def test_short_file_is_untouched(tmp_path):
    small = write_lines(tmp_path, "small.py", TRIGGER_LINES - 50)
    assert run_hook(read_payload(small)) == {}


def test_file_exactly_at_trigger_is_untouched(tmp_path):
    """Boundary: the policy is > TRIGGER_LINES, not >=."""
    exact = tmp_path / "exact.py"
    exact.write_text("".join(f"line {i}\n" for i in range(TRIGGER_LINES - 1)))
    assert run_hook(read_payload(exact)) == {}  # 249 newlines + fragment = 250 lines


@pytest.mark.parametrize("name", ["doc.pdf", "nb.ipynb", "chart.png", "logo.svg"])
def test_non_line_oriented_formats_are_skipped(tmp_path, name):
    """Read renders these specially (pages/cells/visually); a line limit would
    change behaviour rather than bound it."""
    f = tmp_path / name
    f.write_text("".join(f"line {i}\n" for i in range(1000)))
    assert run_hook(read_payload(f)) == {}


def test_binary_file_is_skipped(tmp_path):
    blob = tmp_path / "data.bin"
    blob.write_bytes(b"\x00\x01\x02" * 5000 + b"\n" * 500)
    assert run_hook(read_payload(blob)) == {}


def test_other_tools_are_ignored(tmp_path):
    big = write_lines(tmp_path, "big.py", 1000)
    payload = {"tool_name": "Bash", "tool_input": {"command": f"cat {big}"}}
    assert run_hook(payload) == {}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_name": "Read"},
        {"tool_name": "Read", "tool_input": {}},
        {"tool_name": "Read", "tool_input": {"file_path": "/nonexistent/nope.py"}},
        {"tool_name": "Read", "tool_input": {"file_path": "/etc"}},  # directory
        {"tool_name": "Read", "tool_input": "not-a-dict"},
        {"tool_name": "Read", "tool_input": {"file_path": 12345}},
    ],
)
def test_malformed_input_fails_open(payload):
    """A hook that breaks Read costs far more than one that misses a saving."""
    assert run_hook(payload) == {}


def test_garbage_stdin_fails_open():
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{not json at all",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout or "{}") == {}
