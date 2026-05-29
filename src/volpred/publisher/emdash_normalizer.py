"""Em-dash (破折號) overuse normalizer — anti-AI-style publish-time defense.

Background (2026-05-29, boss asked「寫文都會經過 anti-ai-style?」): the
publishing rule (`.claude/rules/publishing.md` §7) mandates that every
reader-facing article co-run the `anti-ai-style` skill, but the publisher
had **no hard gate** — enforcement relied entirely on the writing agent's
self-discipline. `scripts/validate_anti_ai_style.py` added an *audit* layer
(non-blocking detection); this module adds the *defensive* layer that
auto-corrects the single most insidious AI tell at the canonical write site,
mirroring the proven `markdown_table_sanitizer` two-layer pattern.

Anti-AI-style landmine 9 (最隱性 AI tell, `.claude/skills/anti-ai-style/SKILL.md`):
  AI loves `——`/`—` to glue supplementary clauses
  (「VIX 體制——美股恐慌指數——反映…」). Natural Chinese writing almost never
  does this. Density >1/1000 chars = elevated, >3/1000 = severe AI 味.
  Endorsed fix (b)「改逗號併入主句」: replace the dash with a comma. A comma
  is a pause, exactly what the supplementary dash was doing — so this is
  **semantically lossless** in Chinese prose, and strictly safer than fix
  (a) period (which can leave a sentence fragment) or fix (c) deletion
  (which drops content).

Conservative scope — only the unambiguous CJK appositive case is rewritten:
  - Rewrite `X—Y` / `X——Y` → `X，Y` only when BOTH flanks are CJK.
  - SKIP numeric ranges (`2020—2024`, `3—5%`): a digit on either flank.
  - SKIP Latin contexts (`risk—reward`): an ASCII letter on either flank.
  - SKIP attribution / leader lines (line starts with `—`/`——`, e.g. a
    quote signature「——作者」).
  - SKIP code fences and markdown tables (handled like the table sanitizer:
    walk lines, never touch ``` blocks or `|`-delimited table rows).
  Anything outside this narrow appositive pattern is left untouched, so the
  normalizer cannot mangle ranges, English em-dashes, or signatures.

Two-layer defense (same as markdown_table_sanitizer):
  - PRIMARY: `publisher._append_to_feed` calls `normalize_emdash` before
    writing feed.json. Canonical local source stays clean.
  - (Secondary Supabase-side wiring can be added later if a bypass path is
    observed; today every reader-facing write goes through the publisher.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# CJK ranges: common ideographs + extension A + fullwidth punctuation that
# naturally flanks prose dashes. Used to decide "is this an appositive break
# between Chinese text" vs a numeric range / English compound.
_CJK = (
    r"㐀-䶿"   # CJK ext A
    r"一-鿿"   # CJK unified ideographs
    r"豈-﫿"   # CJK compat ideographs
    r"　-〿"   # CJK symbols & punctuation (、。「」etc.)
    r"＀-￯"   # fullwidth forms (，；：！？「」（）etc.)
)
_CJK_CLASS = f"[{_CJK}]"

# One or more em-dashes (U+2014). `——` (the canonical Chinese double dash)
# and a lone `—` are both captured by `—+`. Require a CJK char on BOTH sides
# so numeric ranges (digit flank) and Latin compounds (letter flank) never
# match — those flanks are simply not in _CJK_CLASS.
_CJK_EMDASH = re.compile(f"({_CJK_CLASS})—+({_CJK_CLASS})")

_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _is_attribution_line(line: str) -> bool:
    """A line whose first non-space char is an em-dash is a quote
    attribution / leader (「——作者」); leave it alone."""
    return line.lstrip().startswith("—")


def _normalize_line(line: str) -> tuple[str, int]:
    """Replace CJK-flanked em-dash run(s) with a single comma.

    `re.sub` with a callback so overlapping consecutive dashes
    (`A——B——C`) are all converted: each match consumes the right flank,
    but the regex engine re-scans from there so the next `B——C` still
    matches on a fresh pass. To guarantee full coverage we loop until the
    pattern no longer matches (bounded — each pass strictly removes a dash).
    """
    count = 0
    prev = None
    cur = line
    while prev != cur:
        prev = cur
        cur, n = _CJK_EMDASH.subn(r"\1，\2", cur)
        count += n
    return cur, count


@dataclass
class EmdashReport:
    """Outcome of `normalize_emdash`."""

    fixed_lines: list[int]
    replaced: int          # total em-dash runs converted to commas
    density_before: float  # em-dashes per 1000 prose chars (pre-fix)

    @property
    def changed(self) -> bool:
        return self.replaced > 0

    def summary(self) -> str:
        return (
            f"replaced={self.replaced} lines={self.fixed_lines} "
            f"density_before={self.density_before}/1k"
        )


def _count_emdash(text: str) -> int:
    return text.count("—")


def normalize_emdash(content: str) -> tuple[str, EmdashReport]:
    """Convert over-used CJK appositive em-dashes to commas (anti-AI-style
    landmine 9 fix (b)).

    Conservative: only `X—Y`/`X——Y` with CJK on both flanks is rewritten.
    Code fences, markdown table rows, numeric ranges, Latin compounds, and
    attribution lines are left untouched.

    Returns:
      (normalized_content, EmdashReport).
      - identical input is returned when nothing matched.
      - `EmdashReport.fixed_lines`: 1-indexed lines that were changed.
      - `EmdashReport.replaced`: total em-dash runs converted.
      - `EmdashReport.density_before`: pre-fix em-dash density per 1000
        chars (the metric `validate_anti_ai_style.py` flags; >1 elevated).
    """
    lines = content.split("\n")
    out: list[str] = []
    fixed: list[int] = []
    replaced = 0
    in_code = False
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        # Toggle fenced code block; never touch lines inside it.
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        # Skip markdown table rows / separators and attribution lines.
        if (
            stripped.startswith("|")
            or _TABLE_SEPARATOR.match(stripped)
            or _is_attribution_line(line)
        ):
            out.append(line)
            continue
        new_line, n = _normalize_line(line)
        if n:
            fixed.append(idx + 1)
            replaced += n
        out.append(new_line)

    n_chars = max(len(content), 1)
    density = round(_count_emdash(content) / n_chars * 1000, 2)
    return "\n".join(out), EmdashReport(
        fixed_lines=fixed,
        replaced=replaced,
        density_before=density,
    )
