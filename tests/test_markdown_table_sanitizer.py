"""Regression tests for `volpred.publisher.markdown_table_sanitizer`.

K549 mile_5c662be0 (2026-04-29) regression: agent wrote `Harvey (2016) |t|>3.0`
inside a 2-cell table row. Frontend GFM/CommonMark renderer split the row
into 4 cells (5 unescaped pipes) → broken table layout. K1018 same-day
parallel agent escaped some rows but missed line 28 — proves manual escape
is unenforceable. This module is the architectural fix; these tests guard
against regression.
"""
from __future__ import annotations

import textwrap

from volpred.publisher.markdown_table_sanitizer import (
    sanitize_markdown_tables,
)


def test_no_op_on_clean_table():
    """Already-correct content must pass through unchanged."""
    md = textwrap.dedent(
        """
        | A | B |
        |---|---|
        | x | y |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert out == md
    assert not report.changed
    assert report.table_count == 1


def test_k549_harvey_t_inside_2cell_row():
    """K549 line-32 regression: `|t|>3.0` inside 2-cell row."""
    md = textwrap.dedent(
        """
        | 項目 | 設定 |
        |------|------|
        | 統計門檻 | Harvey (2016) |t|>3.0 |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert report.changed
    assert 3 in report.fixed_lines  # 1-indexed; data row is line 3
    # Original row had 5 pipes (broken); after fix should have 3 pipes.
    fixed_row = out.split("\n")[2]
    assert fixed_row.count("|") - fixed_row.count(r"\|") == 3
    assert r"\|t\|" in fixed_row


def test_k549_pass_t3_inside_header():
    """K549 line-70 regression: `|t|>3?` inside HEADER row."""
    md = textwrap.dedent(
        """
        | Config | Harvey t | p | Pass |t|>3? |
        |--------|----------|---|----------------|
        | A | -1.5 | 0.2 | NO |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert report.changed
    assert 1 in report.fixed_lines  # header is 1-indexed line 1
    fixed_header = out.split("\n")[0]
    assert r"\|t\|" in fixed_header


def test_already_escaped_no_change():
    """K1018 mostly-correct rows: cells already containing `\\|t\\|` must be
    left alone (no double-escape)."""
    md = textwrap.dedent(
        r"""
        | 項目 | 數值 |
        |------|------|
        | t-stat | \|t\| ≥ 3.0 |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert not report.changed
    assert out == md


def test_multiple_tables_only_broken_ones_fixed():
    """Mixed: clean table + broken table; only broken one fixed."""
    md = textwrap.dedent(
        """
        | A | B |
        |---|---|
        | x | y |

        Some prose here.

        | M | N |
        |---|---|
        | foo | Harvey |t|>3 stuff |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert report.changed
    assert report.table_count == 2
    # Line numbering: line 1 first header, line 5 prose, lines 7-9 second table
    # Data row of second table is line 9 (1-indexed)
    assert 9 in report.fixed_lines
    # First table unchanged
    assert "| x | y |" in out


def test_unfixable_row_preserved_with_warning():
    """If pipe-count mismatch can't be auto-resolved (e.g. cell contains a
    long phrase with bare pipe that doesn't match short-token pattern),
    keep the row but flag it."""
    md = textwrap.dedent(
        """
        | A | B |
        |---|---|
        | x | this has a very long | embedded pipe segment of words |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    # 5 pipes in data row vs 3 expected; long phrase between pipes is NOT
    # matched by `_PIPE_NOTATION` (only matches short alphanum tokens).
    assert 3 in report.unfixed_lines
    # Row preserved as-is
    assert "this has a very long | embedded pipe segment" in out


def test_separator_with_alignment_colons():
    """Separator rows can have alignment colons like `|:---:|---:|`."""
    md = textwrap.dedent(
        """
        | A | B |
        |:--:|---:|
        | x | y |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert report.table_count == 1
    assert not report.changed


def test_non_table_pipes_untouched():
    """Inline pipes outside tables must not be escaped."""
    md = "Some prose with |t|>3 statistical notation, no table around it."
    out, report = sanitize_markdown_tables(md)
    assert out == md
    assert report.table_count == 0
    assert not report.changed


def test_real_k549_problematic_rows():
    """Verbatim K549 mile_5c662be0 problem rows."""
    md = textwrap.dedent(
        """
        | 項目 | 設定 |
        |------|------|
        | 統計門檻 | DM (Diebold-Mariano) p<0.05；**Harvey (2016) |t|>3.0** 為主要 robust 門檻 |

        Some text.

        | Config | mean Sharpe diff（vs A） | SE | **Harvey t** | p | **Pass |t|>3?** |
        |--------|------------------------:|----:|------------:|---:|:--------------:|
        | B_TLT | -0.214 | 0.138 | -1.554 | 0.195 | NO |
        """
    ).strip()
    out, report = sanitize_markdown_tables(md)
    assert report.changed
    assert report.table_count == 2
    # Both broken rows fixed
    assert len(report.fixed_lines) == 2
    assert not report.unfixed_lines
    # Verify renderer-equivalent: pipe counts now match
    lines = out.split("\n")
    # Line 3 (statistical 門檻 row) should have 3 unescaped pipes (2 cells)
    import re
    def unescaped_pipes(line):
        return len(re.findall(r"(?<!\\)\|", line))
    sep1_pipes = unescaped_pipes(lines[1])  # |------|------|
    row3_pipes = unescaped_pipes(lines[2])
    assert row3_pipes == sep1_pipes
