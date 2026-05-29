"""Tests for `volpred.publisher.emdash_normalizer`.

Anti-AI-style landmine 9 (破折號上癮, 最隱性 AI tell): AI glues supplementary
clauses with `——`/`—` (「VIX 體制——美股恐慌指數——反映…」). The publish-time
normalizer applies the skill's endorsed fix (b)「改逗號併入主句」: replace a
CJK-flanked em-dash with a comma (semantically lossless in Chinese). These
tests pin down the conservative scope — only the appositive CJK case is
rewritten; ranges, Latin compounds, attribution, code, and tables are
preserved.
"""
from __future__ import annotations

import textwrap

from volpred.publisher.emdash_normalizer import normalize_emdash


def test_cjk_appositive_single_dash_to_comma():
    out, rep = normalize_emdash("波動率上升—市場開始恐慌。")
    assert out == "波動率上升，市場開始恐慌。"
    assert rep.changed and rep.replaced == 1
    assert rep.fixed_lines == [1]


def test_cjk_double_dash_to_single_comma():
    out, rep = normalize_emdash("VIX 體制——美股恐慌指數——反映情緒")
    assert out == "VIX 體制，美股恐慌指數，反映情緒"
    assert rep.replaced == 2


def test_numeric_range_preserved():
    """`2020—2024` is a year range, not an appositive — digit flank, skip."""
    src = "樣本期間 2020—2024 年，報酬率 3—5%。"
    out, rep = normalize_emdash(src)
    assert out == src
    assert not rep.changed


def test_latin_compound_preserved():
    """`risk—reward` has Latin flanks — skip."""
    src = "經典的 risk—reward tradeoff 不變。"
    out, rep = normalize_emdash(src)
    assert out == src
    assert not rep.changed


def test_attribution_line_preserved():
    """Leading em-dash = quote signature「——作者」, leave alone."""
    src = "——賴奕豪，2026"
    out, rep = normalize_emdash(src)
    assert out == src
    assert not rep.changed


def test_code_fence_preserved():
    src = textwrap.dedent(
        """
        正文一段—補充說明。
        ```python
        x = a—b  # 不可動 code
        ```
        正文二段—另一個補充。
        """
    ).strip()
    out, rep = normalize_emdash(src)
    assert "x = a—b" in out               # code untouched
    assert "正文一段，補充說明。" in out    # prose fixed
    assert "正文二段，另一個補充。" in out
    assert rep.replaced == 2


def test_table_row_preserved():
    src = textwrap.dedent(
        """
        | 指標 | 說明 |
        |---|---|
        | VIX | 恐慌—指數 |
        """
    ).strip()
    out, rep = normalize_emdash(src)
    assert out == src                      # dash inside a table cell untouched
    assert not rep.changed


def test_density_reporting():
    """density_before is the per-1000-char metric validate_anti_ai_style flags."""
    src = "甲—乙丙丁戊。"  # 1 emdash, len 7 → ~142.86/1k
    _, rep = normalize_emdash(src)
    assert rep.density_before > 1


def test_clean_prose_is_noop():
    src = "這是一段沒有破折號的正常中文。短句、句號、口語連接詞。"
    out, rep = normalize_emdash(src)
    assert out == src
    assert not rep.changed
    assert rep.density_before == 0


def test_dash_at_clause_boundary_with_punct():
    """CJK punctuation counts as CJK flank: 「…結束）—接著」still appositive."""
    out, rep = normalize_emdash("策略崩潰）—於是放棄。")
    assert out == "策略崩潰），於是放棄。"
    assert rep.replaced == 1
