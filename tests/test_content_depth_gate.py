"""Tests for the minimum-depth publish floor (_audit_content_depth).

2026-07-02 boss escalation regression gate: general median length collapsed
4459→2293 chars (-49%) May→June because the publishing.md L98 floors had zero
code enforcement while every code gate pushed in the compress direction. Any
future change that silently drops the floor should fail here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from volpred.publisher.publisher import (  # noqa: E402
    _audit_content_depth,
    _count_md_tables,
)

TABLE = "| a | b |\n|---|---|\n| 1 | 2 |\n"
LONG_1600 = "深" * 1600
LONG_2100 = "深" * 2100


def test_general_below_floor_blocks():
    issues, _ = _audit_content_depth("general", "太短" * 100)  # 200 chars
    assert len(issues) == 1 and "below floor" in issues[0]


def test_general_at_floor_passes_with_table_warning_only():
    issues, warnings = _audit_content_depth("general", LONG_1600)
    assert issues == []
    assert len(warnings) == 1 and "0 markdown tables" in warnings[0]


def test_general_with_table_clean():
    issues, warnings = _audit_content_depth("general", LONG_1600 + "\n" + TABLE)
    assert issues == [] and warnings == []


def test_research_needs_2000_and_table():
    issues, _ = _audit_content_depth("research", LONG_1600 + "\n" + TABLE)
    assert any("below floor" in i for i in issues)  # 1600 < 2000
    issues2, _ = _audit_content_depth("research", LONG_2100)
    assert any("0 markdown result tables" in i for i in issues2)
    issues3, warnings3 = _audit_content_depth("research", LONG_2100 + "\n" + TABLE)
    assert issues3 == [] and warnings3 == []


def test_exempt_content_types_and_audiences():
    for ct in ("daily_digest", "event_article", "member_qa"):
        assert _audit_content_depth("general", "短", content_type=ct) == ([], [])
    # non-general/research audiences are out of scope
    for aud in ("daily", "member_qa", "event", ""):
        assert _audit_content_depth(aud, "短") == ([], [])


def test_fail_open_on_bad_input():
    issues, warnings = _audit_content_depth("general", None)  # type: ignore[arg-type]
    # None content → treated as empty → blocks (deterministic), must not raise
    assert isinstance(issues, list) and isinstance(warnings, list)


def test_count_md_tables():
    assert _count_md_tables(TABLE) == 1
    assert _count_md_tables(TABLE + "\n文字\n" + TABLE) == 2
    assert _count_md_tables("| 單行不是表 |") == 0
    assert _count_md_tables("") == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
