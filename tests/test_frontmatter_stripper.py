"""Tests for `volpred.publisher.frontmatter_stripper`.

Background (2026-06-24): a few published articles had a leaked YAML
frontmatter block glued to the start of their markdown body, so the frontend
rendered `audience: general` / `content_type: daily_digest` as literal text
and the leading `---` as a horizontal rule. The publish-time stripper removes
a genuine leading frontmatter block (and a stray leading `---`) while leaving
mid-article `---` section breaks and frontmatter-free prose untouched. These
tests pin down that conservative scope.
"""
from __future__ import annotations

import textwrap

from volpred.publisher.frontmatter_stripper import strip_frontmatter


# --- positive: leaked frontmatter is removed -------------------------------

def test_daily_digest_frontmatter_stripped():
    """Real daily_digest frontmatter (with a digest_articles list) → removed;
    body starts at the real prose."""
    src = textwrap.dedent(
        """\
        ---
        title: "每日精選導讀｜隔夜波動率：學術上很重要，實戰裡很尷尬"
        audience: general
        tags: ["精選導讀", "隔夜波動率"]
        status: published
        content_type: daily_digest
        digest_articles: ["mile_0a7041f4", "mile_f8d2ffb9"]
        ---

        今天早上十點，市場開盤前的隔夜變動已經寫好結局。
        這篇導讀串聯六個月的研究歷程。
        """
    )
    out, rep = strip_frontmatter(src)
    assert rep.stripped and rep.shape == "full_block"
    assert out.startswith("今天早上十點")
    assert "audience: general" not in out
    assert "content_type: daily_digest" not in out
    assert "digest_articles" not in out
    assert "title" in rep.keys and "digest_articles" in rep.keys


def test_minimal_frontmatter_stripped():
    src = "---\ntitle: 範例\naudience: research\n---\n\n正文第一段。"
    out, rep = strip_frontmatter(src)
    assert rep.stripped and rep.shape == "full_block"
    assert out == "正文第一段。"
    assert rep.keys == ["title", "audience"]


def test_dangling_leading_rule_stripped():
    """mile_0baeb00c shape: a lone leading `---` (frontmatter residue) followed
    directly by a heading, no closing fence → drop just that stray rule."""
    src = textwrap.dedent(
        """\
        ---

        ## 到底算錯了什麼？

        2026 年 3 月，我們在 K604 實驗中計算台股策略的交易成本時，犯了兩個錯誤。
        """
    )
    out, rep = strip_frontmatter(src)
    assert rep.stripped and rep.shape == "dangling_rule"
    assert rep.keys == []
    assert out.startswith("## 到底算錯了什麼？")
    # the two mid-body... there are none here, but the heading must survive
    assert "K604" in out


# --- negative: must NOT mangle these ---------------------------------------

def test_midbody_horizontal_rule_preserved():
    """A `---` section break in the middle of prose is not frontmatter."""
    src = textwrap.dedent(
        """\
        這是文章開頭第一段，沒有任何 frontmatter。

        接著講第二個重點。

        ---

        最後做個總結。
        """
    )
    out, rep = strip_frontmatter(src)
    assert out == src
    assert not rep.stripped
    assert rep.shape == ""


def test_plain_prose_start_noop():
    """Body that already begins with a normal heading/paragraph → unchanged."""
    src = "假設你手上有五個資產：美股 SPY、台股 0050、比特幣。\n\n但這個配置有一個問題。"
    out, rep = strip_frontmatter(src)
    assert out == src
    assert not rep.stripped


def test_leading_fence_with_prose_not_yaml_preserved():
    """Opening `---`, then prose (not YAML keys), then `---` — a deliberate
    prose-fenced block, not leaked frontmatter. Leave it alone."""
    src = textwrap.dedent(
        """\
        ---
        這是一段引言，不是 YAML。
        作者想用線框起來強調。
        ---

        正文從這裡開始。
        """
    )
    out, rep = strip_frontmatter(src)
    assert out == src
    assert not rep.stripped


def test_empty_fence_pair_preserved():
    """`---\\n\\n---` (no YAML keys between) is a divider pair, not frontmatter."""
    src = "---\n\n---\n\n正文。"
    out, rep = strip_frontmatter(src)
    assert out == src
    assert not rep.stripped


def test_empty_content_noop():
    out, rep = strip_frontmatter("")
    assert out == ""
    assert not rep.stripped


# --- integration: stripper composes with the other sanitizers --------------

def test_chain_with_table_and_emdash_sanitizers():
    """A body that leads with frontmatter AND contains a markdown table +
    appositive em-dash: strip_frontmatter removes the block first, then the
    table sanitizer and em-dash normalizer still work on the real prose."""
    from volpred.publisher.markdown_table_sanitizer import sanitize_markdown_tables
    from volpred.publisher.emdash_normalizer import normalize_emdash

    src = textwrap.dedent(
        """\
        ---
        title: "整合測試"
        audience: research
        ---

        波動率上升—市場開始恐慌。

        | 指標 | 條件 |
        |---|---|
        | t | |t|>3.0 |
        """
    )
    cleaned, fmrep = strip_frontmatter(src)
    assert fmrep.stripped
    assert "audience: research" not in cleaned
    assert cleaned.startswith("波動率上升")

    # em-dash normalizer still fixes the appositive dash
    em_out, emrep = normalize_emdash(cleaned)
    assert emrep.changed
    assert "波動率上升，市場開始恐慌。" in em_out

    # table sanitizer still escapes the |t| inside the table cell
    tbl_out, tblrep = sanitize_markdown_tables(em_out)
    assert tblrep.changed
    assert r"\|t\|>3.0" in tbl_out
