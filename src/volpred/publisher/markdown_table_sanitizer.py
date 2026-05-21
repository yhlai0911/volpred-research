"""Markdown table cell sanitizer.

Architectural fix (2026-04-29) for the recurring issue where article writers
embed unescaped pipe characters inside table cells (e.g. statistical notation
`|t|>3.0` for Harvey threshold). The pipe is interpreted as a cell delimiter
by GFM/CommonMark renderers, breaking the entire table layout.

Two-layer defense:
  - PRIMARY: `volpred.publisher.publisher._append_to_feed` calls
    `sanitize_markdown_tables` before writing feed.json. Canonical local
    source stays clean.
  - SECONDARY: `scripts.supabase_sync.sync_article` calls the same helper
    before Supabase write. Catches content that bypassed the publisher path
    (e.g. legacy entries, manual edits).

Common patterns auto-escaped: `|t|`, `|z|`, `|r|`, `|p|`, `|t-stat|`,
`|F|`, `|chi|` — short alphanumeric tokens between pipes that match
the conventional statistical notation idiom.

Reference incident: K549 article `mile_5c662be0` (2026-04-29) used
`Harvey (2016) |t|>3.0` and `Pass |t|>3?` inside table cells without escape;
frontend rendered the table as broken because pipe count != header count.
K1018 article `mile_b4cf48f9` written by another agent in parallel did
escape correctly with `\\|t\\|`. Behavioral inconsistency between agents
shows manual escape is unenforceable; this module makes it automatic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Match unescaped |TOKEN| where TOKEN is a short alphanumeric statistical
# notation. Negative lookbehind avoids re-escaping. Bounded length [1, 11]
# avoids matching long phrases that should not be escaped.
_PIPE_NOTATION = re.compile(r"(?<!\\)\|([A-Za-z][A-Za-z0-9_-]{0,10})\|")

# Detect a markdown table separator row, e.g. `|---|---|` or `|:---:|---:|`.
_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _is_table_separator(line: str) -> bool:
    s = line.strip()
    if not _TABLE_SEPARATOR.match(s):
        return False
    inner = s.strip("|").strip()
    return "-" in inner


def _count_unescaped_pipes(line: str) -> int:
    """Count `|` that are not preceded by `\\`."""
    return len(re.findall(r"(?<!\\)\|", line))


def _escape_pipe_notation(line: str) -> str:
    """Replace `|t|`/`|z|`/etc. with `\\|t\\|`/`\\|z\\|`/etc."""
    return _PIPE_NOTATION.sub(r"\\|\1\\|", line)


@dataclass
class SanitizeReport:
    """Outcome of `sanitize_markdown_tables`."""

    fixed_lines: list[int]
    unfixed_lines: list[int]
    table_count: int

    @property
    def changed(self) -> bool:
        return bool(self.fixed_lines)

    @property
    def has_unfixed(self) -> bool:
        return bool(self.unfixed_lines)

    def summary(self) -> str:
        parts = [f"tables={self.table_count}"]
        if self.fixed_lines:
            parts.append(f"auto_fixed_lines={self.fixed_lines}")
        if self.unfixed_lines:
            parts.append(f"unfixable_lines={self.unfixed_lines}")
        return " ".join(parts)


def sanitize_markdown_tables(content: str) -> tuple[str, SanitizeReport]:
    """Auto-escape unescaped statistical-notation pipes inside markdown
    table cells.

    Algorithm:
      1. Walk lines; detect table blocks via header + separator pattern.
      2. Use the separator row's pipe count as ground truth for cell count
         (separator pattern `|---|---|...|` is unambiguous).
      3. For each header / data row whose unescaped pipe count differs from
         the separator's, attempt `_escape_pipe_notation`. If the resulting
         pipe count matches, accept the fix; otherwise keep the original
         (caller can decide how to surface the warning).

    Args:
      content: full markdown article body.

    Returns:
      (sanitized_content, SanitizeReport).
      - `sanitized_content`: same as input if no fixes were applied.
      - `SanitizeReport.fixed_lines`: 1-indexed line numbers that were
        auto-fixed.
      - `SanitizeReport.unfixed_lines`: 1-indexed line numbers where pipe
        count mismatch could not be auto-resolved (callers should warn).
      - `SanitizeReport.table_count`: number of detected table blocks.
    """
    lines = content.split("\n")
    out: list[str] = []
    fixed: list[int] = []
    unfixed: list[int] = []
    table_count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect table block start: line starts with | AND next line is separator
        if (
            line.lstrip().startswith("|")
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            table_count += 1
            sep = lines[i + 1]
            expected = _count_unescaped_pipes(sep)

            # Process header row
            header = line
            if _count_unescaped_pipes(header) != expected:
                fixed_header = _escape_pipe_notation(header)
                if _count_unescaped_pipes(fixed_header) == expected:
                    out.append(fixed_header)
                    fixed.append(i + 1)
                else:
                    out.append(header)
                    unfixed.append(i + 1)
            else:
                out.append(header)

            out.append(sep)
            i += 2

            # Process data rows
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                row = lines[i]
                if _count_unescaped_pipes(row) != expected:
                    fixed_row = _escape_pipe_notation(row)
                    if _count_unescaped_pipes(fixed_row) == expected:
                        out.append(fixed_row)
                        fixed.append(i + 1)
                    else:
                        out.append(row)
                        unfixed.append(i + 1)
                else:
                    out.append(row)
                i += 1
        else:
            out.append(line)
            i += 1

    return "\n".join(out), SanitizeReport(
        fixed_lines=fixed,
        unfixed_lines=unfixed,
        table_count=table_count,
    )
