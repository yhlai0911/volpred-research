"""Contract tests for the boss-facing per-procedure progress report.

2026-07-15 boss directive (Telegram msg 796/808/810): the ops manager kept
reporting "發現問題 → 設計任務 → 下輪解決" in a shape where the boss could not tell
whether anything was actually finished, or merely queued. The fix is not a prose
reminder in the SOP — prose is exactly what failed. It is a checker that refuses
to emit a "done" report without a real measurement behind it.

These tests pin the refusals. If a future edit relaxes one, the report can once
again claim done with nothing behind it, and the pain point is back.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "progress_report", PROJECT_ROOT / "scripts" / "progress_report.py"
)
progress_report = importlib.util.module_from_spec(_spec)
sys.modules["progress_report"] = progress_report
_spec.loader.exec_module(progress_report)


def _args(**overrides):
    """A valid `done` report; override single fields to build each violation."""
    base = dict(
        procedure="PHASE B",
        status="done",
        conclusion="回報格式已上線",
        verified="測試全過，沒實測就寫不出「做完」",
        verified_cmd="pytest tests/test_progress_report.py → passed",
        unverified=None,
        artifacts="scripts/progress_report.py",
        blockers=None,
        next="PHASE Z @19:35",
        actor="test",
    )
    base.update(overrides)
    return pytest.importorskip("argparse").Namespace(**base)


def test_valid_done_report_renders_every_field():
    block, record = progress_report.build(_args())
    assert record["status"] == "done"
    for field in ("結論", "驗證", "產物", "阻塞", "下一步"):
        assert field in block
    assert "白話：" in block and "實測：" in block
    assert "🕘" in block  # msg 808: emoji-headed visual hierarchy


def test_done_without_verification_is_refused():
    # The msg 796 pain point itself: claiming done with nothing measured.
    with pytest.raises(ValueError, match="verified"):
        progress_report.build(_args(verified=None, unverified="懶得測"))


def test_done_without_command_evidence_is_refused():
    # A plain-language claim with no command behind it is still just a claim.
    with pytest.raises(ValueError, match="verified-cmd"):
        progress_report.build(_args(verified_cmd=None))


def test_done_without_artifacts_is_refused():
    with pytest.raises(ValueError, match="artifacts"):
        progress_report.build(_args(artifacts=None))


def test_plain_language_field_rejects_a_pasted_command():
    # msg 810「要說明清楚」— a bare command tells a non-engineer nothing.
    with pytest.raises(ValueError, match="白話"):
        progress_report.build(_args(verified="uv run python x.py → exit 0"))


def test_conclusion_must_stay_one_short_line():
    with pytest.raises(ValueError, match="結論"):
        progress_report.build(_args(conclusion="長" * (progress_report.CONCLUSION_MAX + 1)))


def test_blocked_requires_a_named_blocker():
    with pytest.raises(ValueError, match="blockers"):
        progress_report.build(
            _args(status="blocked", verified=None, verified_cmd=None, unverified="尚未執行")
        )


def test_queued_is_a_distinct_status_not_a_softer_done():
    # 「已建任務待下輪」must not be reportable as done — that erasure is the bug.
    block, record = progress_report.build(
        _args(
            status="queued",
            verified=None,
            verified_cmd=None,
            unverified="agent 由 */15 worker 非同步執行，本班無結果可測",
            artifacts="job agent-k1678-closeout",
        )
    )
    assert record["status"] == "queued"
    assert "未完成" in block
    assert "未驗證：" in block
