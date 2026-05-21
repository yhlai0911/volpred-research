"""Tests for citation-context exemption in publish_draft.py sanitizer (2026-05-08).

Background: the general-audience sanitizer in scripts/publish_draft.py
replaces banned author surnames ("Harvey" → "嚴格統計", "Diebold-Mariano" →
"兩模型比較顯著") to keep articles jargon-free for retail readers. Prior to
the citation-context exemption, this corrupted legitimate academic citations
inside the same article body:

  - mile_4c1045ea (K663): "Erb & Harvey (2013)" → "Erb & 嚴格統計 (2013)"
    (later manually rewritten to "Erb 與合著者" — wrong author swap, made it
    look like Erb is the citation author).
  - mile_0c1f9687 (K531): "Harvey, Liu and Zhu" → "嚴格統計, 嚴格統計, Liu
    and Zhu" (duplicated banned-token replacement broke the citation entirely).

Fix strategy (Option A): stash citation strings as opaque placeholders before
sanitization, restore after. Citations identified by year-paren or
year-comma patterns:

  - "Author1, Author2 and Author3 (YYYY)"     →  Harvey, Liu and Zhu (2016)
  - "Author1 et al. (YYYY)"                   →  Harvey et al. (2017)
  - "Author1 & Author2 (YYYY)"                →  Erb & Harvey (2013)
  - "Author1 and Author2 (YYYY)"              →  Diebold and Mariano (1995)
  - "Author (YYYY)"                           →  Patton (2011), Bollerslev (1986)
  - "Author, YYYY"                            →  Bouman & Jacobsen, 2002

Bare jargon ("Harvey threshold" / "DM test 顯示") still sanitizes — only
explicit citation-paren / citation-comma forms escape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import sanitize_general, _stash_citations, _restore_citations  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Citation preservation (GOOD cases — must survive sanitize unchanged)
# ──────────────────────────────────────────────────────────────────────────

def test_citation_three_authors_with_and_preserved():
    """Harvey, Liu and Zhu (2016) — 3-author 'and' form must survive."""
    text = "依 Harvey, Liu and Zhu (2016) 的門檻..."
    out, _ = sanitize_general(text)
    assert "Harvey, Liu and Zhu (2016)" in out


def test_citation_three_authors_with_oxford_comma_preserved():
    text = "Harvey, Liu, and Zhu (2016) 提出..."
    out, _ = sanitize_general(text)
    assert "Harvey, Liu, and Zhu (2016)" in out


def test_citation_three_authors_with_ampersand_preserved():
    """K928 footgun (mile_0e16d067 2026-05-08): & form must also survive."""
    text = "依 Harvey, Liu & Zhu (2016) 的門檻..."
    out, _ = sanitize_general(text)
    assert "Harvey, Liu & Zhu (2016)" in out


def test_citation_three_authors_with_html_ampersand_preserved():
    """HTML-escaped & in 3-author citation must also survive."""
    text = "依 Harvey, Liu &amp; Zhu (2016) 的門檻..."
    out, _ = sanitize_general(text)
    assert "Harvey, Liu &amp; Zhu (2016)" in out


def test_citation_et_al_preserved():
    """Harvey et al. (2017) — must not become '嚴格統計 et al.'"""
    text = "Harvey et al. (2017) shows that ..."
    out, _ = sanitize_general(text)
    assert "Harvey et al. (2017)" in out


def test_citation_ampersand_two_authors_preserved():
    """Erb & Harvey (2013) — the K663 reproduction case."""
    text = "Erb & Harvey (2013) 提出 The Golden Dilemma."
    out, _ = sanitize_general(text)
    assert "Erb & Harvey (2013)" in out
    assert "嚴格統計" not in out


def test_citation_and_two_authors_preserved():
    """Diebold and Mariano (1995) — explicit 'and' connector."""
    text = "Diebold and Mariano (1995) 提出 DM 檢定."
    out, _ = sanitize_general(text)
    assert "Diebold and Mariano (1995)" in out


def test_citation_single_author_preserved():
    """Patton (2011) — single author + paren year."""
    text = "Patton (2011) 提出 QLIKE 損失函數."
    out, _ = sanitize_general(text)
    assert "Patton (2011)" in out


def test_citation_bollerslev_preserved():
    """Bollerslev (1986) — single author classic."""
    text = "Bollerslev (1986) introduced GARCH."
    out, _ = sanitize_general(text)
    assert "Bollerslev (1986)" in out


def test_citation_fullwidth_paren_preserved():
    """Chinese fullwidth parens 「（」「）」 used in CJK article bodies."""
    text = "Lamoureux & Lastrapes（1990，發表於 Journal of Finance）的研究..."
    out, _ = sanitize_general(text)
    assert "Lamoureux & Lastrapes（1990" in out


def test_citation_comma_year_preserved():
    """Bouman & Jacobsen, 2002 — comma-year (no parens) form."""
    text = "依 Bouman & Jacobsen, 2002 的研究..."
    out, _ = sanitize_general(text)
    assert "Bouman & Jacobsen, 2002" in out


def test_citation_year_letter_suffix_preserved():
    """Author (2016a) / (2016b) — disambiguation suffix common in references."""
    text = "Patton (2011a) 與 Patton (2011b) 都提到..."
    out, _ = sanitize_general(text)
    assert "Patton (2011a)" in out
    assert "Patton (2011b)" in out


# ──────────────────────────────────────────────────────────────────────────
# Jargon sanitization (BAD cases — must still trigger replacement)
# ──────────────────────────────────────────────────────────────────────────

def test_harvey_threshold_jargon_still_sanitized():
    """'Harvey threshold' (no year, no paren) is jargon — still rewrite."""
    text = "通過 Harvey threshold 檢驗的策略..."
    out, _ = sanitize_general(text)
    assert "Harvey threshold" not in out
    assert "嚴格統計檢驗門檻" in out


def test_bare_harvey_jargon_still_sanitized():
    """Bare 'Harvey' without citation context — still jargon-replace."""
    text = "Harvey 的門檻是 t > 3.0."
    out, _ = sanitize_general(text)
    # Bare Harvey (no year, no paren, no comma-year) should sanitize
    assert "Harvey 的門檻" not in out


def test_dm_test_jargon_still_sanitized():
    """'DM test 顯示' is jargon — still rewrite."""
    text = "DM test 顯示兩模型差異顯著."
    out, _ = sanitize_general(text)
    assert "DM test" not in out
    assert "比較檢定" in out


def test_diebold_mariano_jargon_still_sanitized():
    """'Diebold-Mariano test' bare jargon — still rewrite."""
    text = "Diebold-Mariano test 的結果..."
    out, _ = sanitize_general(text)
    assert "Diebold-Mariano" not in out
    assert "兩模型比較顯著" in out


def test_t_stat_jargon_still_sanitized():
    """t=4.38 / |t|>3 / t-stat — still sanitize."""
    text = "結果顯示 t=4.38, |t|>3, t-stat 高."
    out, _ = sanitize_general(text)
    assert "t=4.38" not in out
    assert "|t|" not in out
    assert "t-stat" not in out


def test_p_value_jargon_still_sanitized():
    text = "結果 p=0.001, p<0.05 顯著."
    out, _ = sanitize_general(text)
    assert "p=0.001" not in out
    assert "p<0.05" not in out


# ──────────────────────────────────────────────────────────────────────────
# Mixed contexts — citations + jargon in same body
# ──────────────────────────────────────────────────────────────────────────

def test_mixed_citation_and_jargon():
    """Article with both legitimate citation AND bare jargon — handle both."""
    text = (
        "依 Harvey, Liu and Zhu (2016) 的 Harvey threshold 檢驗，"
        "DM test 結果 t=4.38, p<0.05 顯著."
    )
    out, _ = sanitize_general(text)
    # Citation preserved
    assert "Harvey, Liu and Zhu (2016)" in out
    # Jargon sanitized
    assert "Harvey threshold" not in out
    assert "DM test" not in out
    assert "t=4.38" not in out
    assert "p<0.05" not in out


def test_k531_repro_no_duplication():
    """K531 reproduction: 'Harvey, Liu and Zhu' must not become '嚴格統計, 嚴格統計, Liu and Zhu'."""
    text = "Harvey, Liu and Zhu (2016) 提出嚴格門檻."
    out, _ = sanitize_general(text)
    # Must not produce the duplicated-banned-token pattern
    assert "嚴格統計, 嚴格統計" not in out
    assert "Harvey, Liu and Zhu (2016)" in out


def test_k663_repro_erb_harvey_2013():
    """K663 reproduction: 'Erb & Harvey (2013)' must not become 'Erb & 嚴格統計 (2013)'."""
    text = "Erb & Harvey (2013). The Golden Dilemma."
    out, _ = sanitize_general(text)
    assert "Erb & Harvey (2013)" in out
    assert "Erb & 嚴格統計" not in out


def test_references_section_full_block():
    """Realistic references section with multiple citations interleaved."""
    text = (
        "## 參考文獻\n"
        "- Patton (2011). QLIKE loss. *J. Econometrics*.\n"
        "- Harvey, Liu and Zhu (2016). RFS.\n"
        "- Erb & Harvey (2013). The Golden Dilemma. *FAJ*.\n"
        "- Diebold and Mariano (1995). JBES.\n"
        "- Bollerslev (1986). JoE.\n"
    )
    out, _ = sanitize_general(text)
    for citation in [
        "Patton (2011)",
        "Harvey, Liu and Zhu (2016)",
        "Erb & Harvey (2013)",
        "Diebold and Mariano (1995)",
        "Bollerslev (1986)",
    ]:
        assert citation in out, f"missing citation: {citation}"


# ──────────────────────────────────────────────────────────────────────────
# Stash/restore round-trip
# ──────────────────────────────────────────────────────────────────────────

def test_stash_restore_round_trip():
    text = "Harvey, Liu and Zhu (2016) and Patton (2011) found ..."
    stashed, citations = _stash_citations(text)
    # Stashed text must contain none of the original citations
    for c in citations:
        assert c not in stashed
    # Restore must reproduce original
    restored = _restore_citations(stashed, citations)
    assert restored == text


def test_stash_skips_text_without_citations():
    """Plain prose with no citation pattern returns unchanged + empty list."""
    text = "這是一段純白話，沒有任何引文。"
    stashed, citations = _stash_citations(text)
    assert stashed == text
    assert citations == []


# ──────────────────────────────────────────────────────────────────────────
# Audit-side parity (publisher.py _audit_general_content must also exempt)
# ──────────────────────────────────────────────────────────────────────────

def test_audit_exempts_citation_with_harvey():
    """publisher.py audit must not flag 'Patton (2011)' / 'Erb & Harvey (2013)'."""
    from volpred.publisher.publisher import _audit_general_content

    content = (
        "依 Patton (2011) 與 Erb & Harvey (2013) 的研究，"
        "黃金避險效果隨利率環境而變."
    )
    # Audit should pass — only citations contain banned surnames
    issues = _audit_general_content("general", ["一般讀者", "黃金"], content)
    assert issues == [], f"unexpected audit issues: {issues}"


def test_audit_still_blocks_bare_jargon():
    """Bare 'Harvey threshold' / 't=4.38' must still raise audit issues."""
    from volpred.publisher.publisher import _audit_general_content

    content = "通過 Harvey threshold 檢驗，DM test 顯示 t=4.38, p<0.05."
    issues = _audit_general_content("general", ["一般讀者"], content)
    assert any("禁用統計術語" in i for i in issues)


def test_audit_mixed_citation_and_jargon():
    """Citation present should not mask separate bare jargon."""
    from volpred.publisher.publisher import _audit_general_content

    content = (
        "Harvey, Liu and Zhu (2016) 提出 Harvey threshold；"
        "本文 t=4.38, p<0.05."
    )
    issues = _audit_general_content("general", ["一般讀者"], content)
    # Bare jargon still flagged even though citation is present
    assert any("禁用統計術語" in i for i in issues)
