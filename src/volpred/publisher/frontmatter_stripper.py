"""YAML-frontmatter leakage stripper — publish-time rendering defense.

Background (2026-06-24, boss saw published 文章「排版亂了」): a handful of
articles had a block of **YAML frontmatter** glued to the very start of their
markdown `content` body, e.g.

    ---
    title: "每日精選導讀｜..."
    audience: general
    tags: [...]
    status: published
    content_type: daily_digest
    digest_articles: ["mile_xxx", ...]
    ---

    今天早上十點...（真正內文從這裡開始）

The frontend renders `content` as markdown, so the leading `---` became a
horizontal rule and every `audience: general` / `content_type: daily_digest`
line showed up as literal grey text — readers saw a wall of garbage before the
article even started. The article's real metadata already lives in the feed
entry's top-level fields, so this leading block is pure leakage and is safe to
drop.

The publisher had **no gate** for this — enforcement relied on whichever
writing agent assembled the item not pasting its own frontmatter into the
body. This module adds the defensive layer at the canonical write site,
mirroring the proven `markdown_table_sanitizer` / `emdash_normalizer`
two-layer pattern.

Two shapes are recognized, both **strictly conservative**:

  1. FULL frontmatter block — the body's first non-blank line is `---`, a
     closing `---` follows within ~40 lines, and **every** line in between is
     either blank or a YAML mapping (`key:` form, allowing wrapped list
     values). The whole block (both fences included) is removed.

  2. DANGLING leading rule — the first non-blank line is `---` and the next
     non-blank line is a markdown ATX heading (`#`/`##`/...). A lone `---`
     directly above a section heading is the residue of half-stripped
     frontmatter (as in mile_0baeb00c, whose body opened `---` then
     `## 到底算錯了什麼？`); a real article never opens with a horizontal rule
     stacked on a heading. Only that single `---` (plus surrounding blanks) is
     removed, leaving the heading and body untouched.

Everything outside these two narrow shapes is left alone, so the stripper can
never mangle a mid-article `---` section break, a body that already starts
with prose, or an opening `---` that fences free-form prose rather than YAML
(e.g. `---\n引言散文\n---` stays as-is — the next line is prose, not a heading,
and not a YAML key).

Fail-open (per .claude/rules/no-silent-fallback.md): any unexpected error is
logged via `volpred.ops.diagnostics.warn` and the original content is returned
unchanged. We would rather leave a frontmatter line than drop real prose.

Two-layer defense (same as markdown_table_sanitizer / emdash_normalizer):
  - PRIMARY: `publisher._append_to_feed` calls `strip_frontmatter` before any
    other sanitizer, so feed.json never stores a leading YAML block.
  - (Secondary Supabase-side wiring can be added later if a bypass path is
    observed; today every reader-facing write goes through the publisher.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A line that opens or closes a YAML frontmatter fence: a line whose only
# non-space content is three-or-more dashes (`---`, `----`, ...).
_FENCE = re.compile(r"^\s*-{3,}\s*$")

# A markdown ATX heading (`# `, `## `, ...). Used only by the dangling-rule
# branch: a lone leading `---` stacked directly on a heading is frontmatter
# residue, never deliberate prose.
_ATX_HEADING = re.compile(r"^\s*#{1,6}\s+\S")

# A YAML mapping line: an unquoted scalar key followed by a colon, e.g.
# `title:`, `digest_articles:`, `content_type: daily_digest`. Conservative on
# purpose — only lines of this shape (or blank, or a wrapped list/scalar value)
# are accepted between the fences.
_YAML_KEY = re.compile(r"^\s*[A-Za-z_][\w-]*\s*:(\s|$)")

# A wrapped value line inside a YAML block (a list item or quoted/bracketed
# continuation that does not itself start a new key), e.g. a `digest_articles`
# list that the writer broke across lines:
#   digest_articles:
#     - "mile_xxx"
#     - "mile_yyy"
# or a value continuation. Kept narrow: list dash, or a line that is purely a
# bracketed/quoted token. This only matters when a YAML value spans lines.
_YAML_VALUE_CONT = re.compile(r"^\s*(-\s+\S|[\[\]{}\"'].*)$")

# Cap how far we will look for the closing fence. A real frontmatter block is
# small; scanning the whole article for a stray `---` section break would risk
# swallowing prose.
_MAX_FRONTMATTER_LINES = 40


@dataclass
class FrontmatterReport:
    """Outcome of `strip_frontmatter`."""

    stripped: bool = False
    removed_lines: int = 0
    keys: list[str] = field(default_factory=list)
    # "full_block" | "dangling_rule" | "" (nothing stripped)
    shape: str = ""

    @property
    def changed(self) -> bool:
        return self.stripped

    def summary(self) -> str:
        return (
            f"stripped={self.stripped} shape={self.shape or '-'} "
            f"removed_lines={self.removed_lines} keys={self.keys}"
        )


def _first_content_index(lines: list[str]) -> int:
    """Index of the first non-blank line, or len(lines) if all blank."""
    for i, line in enumerate(lines):
        if line.strip():
            return i
    return len(lines)


def _scan_full_block(lines: list[str], start: int) -> tuple[int, list[str]] | None:
    """If `lines[start]` opens a valid YAML frontmatter block, return
    `(closing_fence_index, keys)`. Otherwise return None.

    `start` must point at the opening fence. We require a closing fence within
    `_MAX_FRONTMATTER_LINES`, with every intervening line either blank, a YAML
    key line, or a wrapped value continuation.
    """
    keys: list[str] = []
    limit = min(len(lines), start + 1 + _MAX_FRONTMATTER_LINES)
    for j in range(start + 1, limit):
        line = lines[j]
        if _FENCE.match(line):
            # Closing fence found — block is valid only if it held at least
            # one YAML key (an empty `---\n---` pair is not frontmatter).
            if keys:
                return j, keys
            return None
        if not line.strip():
            continue
        m = _YAML_KEY.match(line)
        if m:
            keys.append(line.split(":", 1)[0].strip())
            continue
        if _YAML_VALUE_CONT.match(line):
            # Wrapped value for the key we just saw; allowed only if we are
            # already inside a key (otherwise it is loose prose).
            if keys:
                continue
            return None
        # Any other content (prose, etc.) → not a frontmatter block.
        return None
    # No closing fence within the cap → not a frontmatter block.
    return None


def strip_frontmatter(content: str) -> tuple[str, FrontmatterReport]:
    """Remove a leaked YAML frontmatter block (or stray leading `---`) from the
    start of an article body.

    Conservative: only a genuine leading YAML frontmatter block, or a lone
    leading `---` horizontal rule, is removed. A mid-article `---` section
    break, prose that already starts the body, and an opening `---` that fences
    free-form prose are all left untouched.

    Returns:
      (cleaned_content, FrontmatterReport).
      - identical input is returned when nothing matched (`stripped=False`).
      - `FrontmatterReport.shape`: "full_block" | "dangling_rule" | "".
      - `FrontmatterReport.removed_lines`: number of source lines dropped
        (fences + YAML + surrounding blanks).
      - `FrontmatterReport.keys`: YAML keys removed (empty for a dangling rule).
    """
    if not content:
        return content, FrontmatterReport()

    try:
        lines = content.split("\n")
        start = _first_content_index(lines)
        if start >= len(lines):
            return content, FrontmatterReport()

        # The body must open with a fence to be in scope at all.
        if not _FENCE.match(lines[start]):
            return content, FrontmatterReport()

        block = _scan_full_block(lines, start)
        if block is not None:
            close_idx, keys = block
            # Drop everything up to and including the closing fence, then any
            # blank lines immediately after it (the spacer before real prose).
            cut = close_idx + 1
            while cut < len(lines) and not lines[cut].strip():
                cut += 1
            removed = cut  # lines[0:cut] are gone (leading blanks + block)
            cleaned = "\n".join(lines[cut:])
            return cleaned, FrontmatterReport(
                stripped=True,
                removed_lines=removed,
                keys=keys,
                shape="full_block",
            )

        # Not a valid frontmatter block. The only other in-scope shape is a
        # lone leading `---` stacked directly on a markdown heading — the
        # residue of half-stripped frontmatter (mile_0baeb00c). Require the
        # next non-blank line to be an ATX heading; anything else (prose, a
        # second fence, a list) is left untouched so deliberate prose-fenced
        # blocks and section dividers are never mangled.
        nxt = start + 1
        while nxt < len(lines) and not lines[nxt].strip():
            nxt += 1
        if nxt >= len(lines) or not _ATX_HEADING.match(lines[nxt]):
            return content, FrontmatterReport()

        # Remove the lone leading fence plus the blank lines that follow it,
        # and any leading blanks before it.
        removed = nxt  # lines[0:nxt] (leading blanks + the lone `---`)
        cleaned = "\n".join(lines[nxt:])
        return cleaned, FrontmatterReport(
            stripped=True,
            removed_lines=removed,
            keys=[],
            shape="dangling_rule",
        )
    except Exception as e:  # pragma: no cover - defensive, fail-open
        from volpred.ops.diagnostics import warn

        warn(
            "frontmatter_stripper",
            "strip failed, returning content unchanged",
            err=str(e),
            head=content[:80],
        )
        return content, FrontmatterReport()
