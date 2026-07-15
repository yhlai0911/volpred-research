"""Hermetic tests for the pregate crosscheck attribution instrument.

Covers the 2026-07-14 topology-audit fix to
`scripts/crosscheck_pregate_outcomes.py`:

  * `_is_hourly_attributed` reads BOTH actor and owner (an entry stamped
    owner="hourly-11" with an empty actor is attributed), and the
    dispatch-worker VOLPRED_ACTOR prefix; concurrent codex / interactive work
    is NOT attributed.
  * `attribution_coverage` is window-scoped: only substantive work_log entries
    that fall inside an hourly fire's [fire_at, fire_at+duration_s] window count
    toward the denominator. Concurrent non-fire work outside every window is
    excluded (this is what let the true in-window stamping ~92% get buried under
    a 10% all-population number).
  * `attribution_coverage_all_population` still reports the polluted denominator
    as an informational lower bound.

Run::
    uv run --extra dev python -m pytest scripts/tests/test_crosscheck_attribution.py -q
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from scripts import crosscheck_pregate_outcomes as cc


def test_is_hourly_attributed_reads_both_fields() -> None:
    # actor convention
    assert cc._is_hourly_attributed("hourly-16", "") is True
    # owner-only convention (the bug: actor empty, owner carries the stamp)
    assert cc._is_hourly_attributed("", "hourly-11") is True
    # VOLPRED_ACTOR dispatch-worker prefix
    assert cc._is_hourly_attributed(
        "dispatch-worker:volpred-hourly-dispatch:1600:slot-1:abcd1234", ""
    ) is True
    # supervisor-issued unique claim tokens: primary Claude and Codex failover
    assert cc._is_hourly_attributed("", "hourly-slot-1-job-a") is True
    assert cc._is_hourly_attributed("codex-failover-slot-2-job-b", "") is True
    # concurrent codex / interactive work is NOT hourly
    assert cc._is_hourly_attributed("", "codex") is False
    assert cc._is_hourly_attributed("codex-vscode", "codex-vscode") is False
    assert cc._is_hourly_attributed("main-session", "") is False


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's canonical paths at hermetic fixtures.

    One fire window: 2026-07-10T16:00:00Z .. 16:10:00Z (600s). Work log:
      a  16:05Z experiment actor=hourly-00           -> in-window, hourly
      b  16:07Z experiment owner=codex               -> in-window, NOT hourly
      c  18:00Z experiment owner=codex               -> OUT-of-window (excluded)
      d  16:06Z platform_ops                         -> in-window, NOT substantive
      e  16:08Z experiment owner=hourly-00 (actor="")-> in-window, hourly via owner
    """
    work_log = [
        {"timestamp": "2026-07-11T00:05:00+08:00", "task_type": "experiment",
         "actor": "hourly-00", "task_id": "a"},
        {"timestamp": "2026-07-11T00:07:00+08:00", "task_type": "experiment",
         "owner": "codex", "task_id": "b"},
        {"timestamp": "2026-07-11T02:00:00+08:00", "task_type": "experiment",
         "owner": "codex", "task_id": "c"},
        {"timestamp": "2026-07-11T00:06:00+08:00", "task_type": "platform_ops",
         "actor": "hourly-00", "task_id": "d"},
        {"timestamp": "2026-07-11T00:08:00+08:00", "task_type": "experiment",
         "owner": "hourly-00", "task_id": "e"},
    ]
    dispatch_state = {
        "completions": [
            {"fire_at": "2026-07-10T16:00:00+00:00", "duration_s": 600.0,
             "outcome": "success"},
        ]
    }
    # A would-skip supervisor fire whose 55-min window (16:00..16:55Z) contains
    # the owner-stamped entry e -> strict mismatch must be caught via owner too.
    pregate_lines = [
        json.dumps({"ts": "2026-07-10T16:00:05+00:00", "invoker": "supervisor",
                    "mode": "shadow", "would_skip": True, "reasons": {}}),
    ]
    wl_path = tmp_path / "work_log.json"
    ds_path = tmp_path / "dispatch_state.json"
    pg_path = tmp_path / "hourly_pregate.jsonl"
    _write(wl_path, work_log)
    _write(ds_path, dispatch_state)
    pg_path.write_text("\n".join(pregate_lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(cc, "WORK_LOG", wl_path)
    monkeypatch.setattr(cc, "DISPATCH_STATE", ds_path)
    monkeypatch.setattr(cc, "PREGATE_LOG", pg_path)
    return tmp_path


def _run(argv: list[str]) -> dict:
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["crosscheck_pregate_outcomes.py", *argv]
    try:
        with redirect_stdout(buf):
            cc.main()
    finally:
        sys.argv = old
    return json.loads(buf.getvalue())


def test_window_scoped_coverage_excludes_out_of_window_codex(wired: Path) -> None:
    rep = _run(["--invoker", "supervisor", "--json"])
    # In-window substantive entries: a, b, e (c is out-of-window, d not substantive).
    assert rep["attribution_window_n"] == 3
    # Hourly-attributed in-window: a (actor) + e (owner) = 2 of 3.
    assert rep["attribution_coverage"] == pytest.approx(2 / 3)
    # All-population denominator still counts c -> 4 substantive, 2 hourly.
    assert rep["attribution_substantive_n"] == 4
    assert rep["attribution_coverage_all_population"] == pytest.approx(0.5)


def test_strict_mismatch_uses_owner_stamp(wired: Path) -> None:
    # The single would-skip fire's window catches entry e (owner=hourly-00),
    # so the owner-aware strict detector must flag it as a mismatch.
    rep = _run(["--invoker", "supervisor", "--json"])
    assert rep["would_skip"] == 1
    assert rep["strict_mismatch"] == 1
    assert rep["strict_mismatch_rate"] == pytest.approx(1.0)


def test_empty_windows_yield_none_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No completions -> no fire windows -> window-scoped coverage is None
    # (undefined), never a divide-by-zero.
    _write(tmp_path / "work_log.json", [
        {"timestamp": "2026-07-11T00:05:00+08:00", "task_type": "experiment",
         "actor": "hourly-00", "task_id": "a"},
    ])
    _write(tmp_path / "dispatch_state.json", {"completions": []})
    (tmp_path / "hourly_pregate.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(cc, "WORK_LOG", tmp_path / "work_log.json")
    monkeypatch.setattr(cc, "DISPATCH_STATE", tmp_path / "dispatch_state.json")
    monkeypatch.setattr(cc, "PREGATE_LOG", tmp_path / "hourly_pregate.jsonl")
    rep = _run(["--invoker", "supervisor", "--json"])
    assert rep["attribution_coverage"] is None
    assert rep["attribution_window_n"] == 0
