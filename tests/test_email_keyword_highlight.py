"""Unit tests for highlight_email_keywords() — boss email-12143 視覺化升級。

確保 keyword highlighter:
1. 染色 CRITICAL/WARN/INFO/PASS/FAIL/中文狀態詞/emoji
2. 不破壞 <code>/<pre>/<a> 內的關鍵詞（避免 code 區段被汙染）
3. 不破壞既有 HTML 結構（tag 屬性、巢狀標籤）
4. Idempotent — 再跑一次不會雙重包 span
5. Empty / None safe
"""
from __future__ import annotations

import pytest

from volpred.publisher.email_notifier import (
    highlight_email_keywords,
    _email_shell,
)


class TestKeywordHighlight:
    def test_critical_token_highlighted(self):
        out = highlight_email_keywords("<p>Status: CRITICAL — 立即處理</p>")
        assert 'class="kw-critical">CRITICAL</span>' in out

    def test_warn_token_highlighted(self):
        out = highlight_email_keywords("<p>level=WARN, breaches=2</p>")
        assert 'class="kw-warn">WARN</span>' in out

    def test_info_token_highlighted(self):
        out = highlight_email_keywords("<p>INFO message</p>")
        assert 'class="kw-info">INFO</span>' in out

    def test_pass_and_fail_separate_classes(self):
        out = highlight_email_keywords("<p>experiments: 5 PASS, 1 FAIL</p>")
        assert 'class="kw-ok">PASS</span>' in out
        assert 'class="kw-critical">FAIL</span>' in out

    def test_chinese_status_words(self):
        out = highlight_email_keywords("<p>結果：成功 23 件，失敗 2 件，警告 5 件</p>")
        assert 'class="kw-ok">成功</span>' in out
        assert 'class="kw-critical">失敗</span>' in out
        assert 'class="kw-warn">警告</span>' in out

    def test_emoji_status_indicators(self):
        out = highlight_email_keywords("<p>🟢 通過 ❌ 失敗 ⚠️ 警告</p>")
        # emoji + 中文都應被包
        assert 'class="kw-ok">🟢</span>' in out
        assert 'class="kw-critical">❌</span>' in out
        # warning emoji 是「⚠️」complex sequence (warn sign + VS16)
        assert "kw-warn" in out

    def test_code_block_not_highlighted(self):
        html = "<p>狀態 <code>WARN_THRESHOLD=80</code> CRITICAL</p>"
        out = highlight_email_keywords(html)
        # <code> 內的 WARN_THRESHOLD 不應被染色（WARN word-boundary 還會切到，但會被 stash 保護）
        assert "<code>WARN_THRESHOLD=80</code>" in out
        # <code> 外的 CRITICAL 仍然染色
        assert 'class="kw-critical">CRITICAL</span>' in out

    def test_pre_block_not_highlighted(self):
        html = "<pre><code>def fail():\n    return PASS</code></pre><p>結果 PASS</p>"
        out = highlight_email_keywords(html)
        # pre/code 內保留原樣
        assert "def fail():" in out
        assert "    return PASS" in out
        # 外面的 PASS 染色
        # 找最後一個 PASS 應該在 span 內
        assert out.count('class="kw-ok">PASS</span>') >= 1

    def test_link_text_not_highlighted(self):
        html = '<p>See <a href="/foo">CRITICAL incident</a> next.</p>'
        out = highlight_email_keywords(html)
        # <a> 內 CRITICAL 保留 plain（不染色）
        assert '<a href="/foo">CRITICAL incident</a>' in out

    def test_html_tag_attributes_preserved(self):
        html = '<table><tr><th>結果</th><td>成功</td></tr></table>'
        out = highlight_email_keywords(html)
        # table/tr/th/td 結構不變
        assert "<table>" in out
        assert "<tr>" in out
        assert "</table>" in out
        # cell 文字內染色
        assert 'class="kw-ok">成功</span>' in out

    def test_idempotent_double_pass(self):
        once = highlight_email_keywords("<p>CRITICAL alert</p>")
        twice = highlight_email_keywords(once)
        # 跑兩次 CRITICAL 不會在 span 內再包 span（因為 <span class="kw-critical"> 算 tag，
        # 內部 CRITICAL 文字 segment 會再次 match — 這是一個 edge case。
        # 解：第一次包後變成 <span ...>CRITICAL</span>，第二次跑時 segment splitter
        # 把 <span ...>...</span> 切成 [<span...>, CRITICAL, </span>]，CRITICAL 仍是
        # text segment，會再被包一次 → <span ...>＜span...＞CRITICAL</span></span>
        # 不希望這樣，所以 test 確認單次 match count 與雙次 match count 相同
        assert once.count('class="kw-critical">CRITICAL</span>') == 1
        # idempotency 需要：第二次跑後 critical span count 不應翻倍
        # （此 expectation 預期 highlighter 知道跳過 已包 span 的內容）
        # 若失敗，需要把 highlighter 改成 segment-aware：tag 已是 span.kw-* 就跳過內部 text
        assert twice.count('class="kw-critical">CRITICAL</span>') == 1, (
            f"highlighter not idempotent — twice produced doubled spans:\n{twice}"
        )

    def test_empty_input(self):
        assert highlight_email_keywords("") == ""

    def test_no_keywords_no_change(self):
        html = "<p>純散文沒有狀態詞</p>"
        assert highlight_email_keywords(html) == html

    def test_pass_does_not_match_passed_inside_word(self):
        out = highlight_email_keywords("<p>passing the test</p>")
        # PASSING uppercase 才染；小寫 passing 不染（word boundary + uppercase pattern）
        assert 'class="kw-ok"' not in out

    def test_chinese_status_inline_phrase(self):
        out = highlight_email_keywords("<p>K1234 通過 Codex review 並完成 publishing。</p>")
        assert 'class="kw-ok">通過</span>' in out
        assert 'class="kw-ok">完成</span>' in out


class TestEmailShellRendersHighlights:
    """確保 _email_shell 輸出包含 keyword CSS class 與 keyword span 兼容。"""

    def test_shell_includes_keyword_css(self):
        html = _email_shell("title", "subtitle", "<p>body</p>")
        # 4 種 keyword class 都要在 <style>
        assert ".kw-critical" in html
        assert ".kw-warn" in html
        assert ".kw-info" in html
        assert ".kw-ok" in html

    def test_shell_includes_table_zebra(self):
        html = _email_shell("title", None, "<p>body</p>")
        # 隔行底色 CSS
        assert "tr:nth-child(even)" in html

    def test_shell_includes_h2_accent_bar(self):
        html = _email_shell("title", None, "<p>body</p>")
        assert "border-left:4px solid #2563eb" in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
