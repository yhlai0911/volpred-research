"""Tests for the translation-oriented general sanitizer (2026-07-02).

Background (docs/error_log.md 2026-07-02 15:15 root cause #1): the general
no-jargon gate was "deletion-oriented" — agents dropped whole statistics
paragraphs to pass the audit, halving general-article median depth (-49%).
Fix: sanitize_general translates statistical expressions into graded plain
language WITH the numeric value preserved, so agents keep the evidence chain.

Key invariants guarded here:
  1. Grading never overstates evidence (p=0.30 must NOT read 「達顯著水準」).
  2. Round-trip: sanitize_general output contains ZERO hits of the publisher's
     _GENERAL_FORBIDDEN_PATTERNS (translation actually clears the gate).
  3. Idempotency: sanitizing twice equals sanitizing once.
  4. Citation exemption (2026-05-08) still holds.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "scripts"), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from publish_draft import (  # noqa: E402
    sanitize_general,
    _translate_p_upper_bound,
    _translate_t_value,
)
from volpred.publisher.publisher import _GENERAL_FORBIDDEN_PATTERNS  # noqa: E402


def _forbidden_hits(text: str) -> list[str]:
    return [hint for pat, hint in _GENERAL_FORBIDDEN_PATTERNS if pat.search(text)]


# ──────────────────────────────────────────────────────────────────────────
# t-value grading (thresholds: 1.645 / 1.96 / 3.0)
# ──────────────────────────────────────────────────────────────────────────

def test_t_value_strong():
    out, _ = sanitize_general("動能因子 t = 3.5，效果穩定。")
    assert "統計檢定高度顯著（強度很強，統計值 3.5）" in out


def test_t_value_moderate():
    out, _ = sanitize_general("結果 t=2.24 支持假說。")
    assert "統計檢定顯著（強度中上，統計值 2.24）" in out


def test_t_value_marginal():
    out, _ = sanitize_general("次樣本 t = 1.7 稍弱。")
    assert "統計檢定接近顯著（強度偏弱，統計值 1.7）" in out


def test_t_value_insignificant():
    out, _ = sanitize_general("控制後 t = 0.8。")
    assert "未達統計顯著（統計值 0.8）" in out


def test_t_value_negative_uses_absolute_strength():
    out, _ = sanitize_general("方向相反：t = -2.5。")
    assert "統計檢定顯著（強度中上，統計值 -2.5）" in out


def test_t_value_trailing_sentence_dot_not_swallowed():
    # regex must capture 2.24 and leave the sentence period alone
    out, _ = sanitize_general("t=2.24.")
    assert "統計值 2.24）" in out and out.endswith(".")


# ──────────────────────────────────────────────────────────────────────────
# p-value grading (point value & bounds) — never overstate evidence
# ──────────────────────────────────────────────────────────────────────────

def test_p_point_highly_significant():
    out, _ = sanitize_general("p = 0.003 的結果。")
    assert "高度顯著（顯著性 0.003）" in out


def test_p_point_significant():
    out, _ = sanitize_general("差異 p=0.03。")
    assert "達顯著水準（顯著性 0.03）" in out


def test_p_point_marginal():
    out, _ = sanitize_general("p = 0.08 邊際。")
    assert "接近顯著水準（顯著性 0.08）" in out


def test_p_point_insignificant_must_not_claim_significance():
    # THE research-honesty case: old table rendered p=0.30 as 「達顯著水準」
    out, _ = sanitize_general("但 p = 0.30，無法拒絕虛無假設。")
    assert "未達顯著水準（顯著性 0.30）" in out
    # a positive claim would be 達顯著水準 NOT preceded by 未
    assert not re.search(r"(?<!未)達顯著水準", out)


def test_p_upper_bound_significant():
    out, _ = sanitize_general("結果 p < 0.05。")
    assert "達顯著水準（顯著性低於 0.05）" in out


def test_p_upper_bound_highly_significant():
    out, _ = sanitize_general("p<0.01 的證據。")
    assert "高度顯著（顯著性低於 0.01）" in out


def test_p_lower_bound_insignificant():
    # p>N was banned by the publisher but had NO translation before 2026-07-02
    out, _ = sanitize_general("穩健性檢查 p > 0.10。")
    assert "未達顯著水準（顯著性高於 0.10）" in out


# ──────────────────────────────────────────────────────────────────────────
# Confidence intervals
# ──────────────────────────────────────────────────────────────────────────

def test_ci_bracket_ascii():
    out, _ = sanitize_general("估計效果 95% CI [1.2, 3.4]。")
    assert "合理範圍約 1.2 到 3.4（95% 信心水準）" in out


def test_ci_bracket_negative_and_parens():
    out, _ = sanitize_general("90% CI (-0.5, 0.7) 橫跨零。")
    assert "合理範圍約 -0.5 到 0.7（90% 信心水準）" in out


def test_ci_chinese_keyword_fullwidth_comma():
    out, _ = sanitize_general("95% 信賴區間 [2.1，4.4] 內。")
    assert "合理範圍約 2.1 到 4.4（95% 信心水準）" in out


def test_ci_bare_keyword_without_interval():
    out, _ = sanitize_general("我們用 95% confidence interval 評估。")
    assert "95% 信心水準的合理範圍" in out


def test_ci_keyword_does_not_eat_citation_placeholder():
    # CITE0000 placeholders from _stash_citations must never match the CI rule
    out, _ = sanitize_general("Patton (2011) 提出 95% CI [0.1, 0.2]。")
    assert "Patton (2011)" in out
    assert "合理範圍約 0.1 到 0.2（95% 信心水準）" in out


# ──────────────────────────────────────────────────────────────────────────
# Cross-module invariants
# ──────────────────────────────────────────────────────────────────────────

STAT_HEAVY_CORPUS = """
本策略 alpha 的 t = 2.24，p = 0.03；bootstrap p_ 值一致。
對照組 t = -3.6（p < 0.01），效果 95% CI [0.8, 2.9]。
夜盤子樣本 p > 0.10，t-stat 偏弱，|t| 未過 Harvey threshold。
DM test 與 Diebold-Mariano test 均顯示模型差異，p=0.30 的配對除外。
"""


def test_round_trip_sanitized_output_clears_publisher_gate():
    """Translation must actually clear the audit — else agents delete again."""
    out, applied = sanitize_general(STAT_HEAVY_CORPUS)
    assert applied, "sanitizer should have rewritten the corpus"
    assert _forbidden_hits(out) == [], f"residual banned jargon in: {out!r}"


def test_sanitize_is_idempotent():
    once, _ = sanitize_general(STAT_HEAVY_CORPUS)
    twice, _ = sanitize_general(once)
    assert once == twice


def test_replacements_preserve_numeric_values():
    """Translation-oriented = the reader can still verify the numbers."""
    out, _ = sanitize_general(STAT_HEAVY_CORPUS)
    for num in ("2.24", "0.03", "-3.6", "0.01", "0.8", "2.9", "0.10", "0.30"):
        assert num in out, f"numeric value {num} lost in translation"


def test_citation_exemption_still_holds():
    out, _ = sanitize_general("依 Harvey, Liu and Zhu (2016)，t = 3.2 才算數。")
    assert "Harvey, Liu and Zhu (2016)" in out
    assert "統計檢定高度顯著（強度很強，統計值 3.2）" in out


# ──────────────────────────────────────────────────────────────────────────
# Defensive fallback (no-silent-fallback: must log, not swallow)
# ──────────────────────────────────────────────────────────────────────────

def test_unparseable_t_value_falls_back_with_warning(caplog):
    m = re.match(r"(.+)", "2.2.4")  # simulate a capture float() rejects
    with caplog.at_level("WARNING"):
        assert _translate_t_value(m) == "統計檢定值 2.2.4"
    assert any("unparseable t value" in r.message for r in caplog.records)


def test_unparseable_p_bound_falls_back_with_warning(caplog):
    m = re.match(r"(.+)", "0..5")
    with caplog.at_level("WARNING"):
        assert _translate_p_upper_bound(m) == "顯著性低於 0..5"
    assert any("unparseable p bound" in r.message for r in caplog.records)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
