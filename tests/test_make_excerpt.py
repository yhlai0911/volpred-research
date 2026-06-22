"""Tests for publisher._make_excerpt and the description-excerpt invariant.

2026-06-23: feed.json bloat fix. The publisher used to store the full article
body in BOTH ``description`` and ``content`` (every article persisted twice,
~5.8MB of a 23MB feed.json). description is now a short plain-text excerpt while
content keeps the canonical full body. These tests pin that behavior so the
duplication never regresses.
"""
from volpred.publisher.publisher import _make_excerpt, _EXCERPT_MAX_CHARS


def test_empty_input_returns_empty():
    assert _make_excerpt('') == ''
    assert _make_excerpt(None) == ''


def test_short_body_passes_through_plain():
    body = "# 標題\n\n這是一段短內容。"
    out = _make_excerpt(body)
    assert out == "標題 這是一段短內容。"
    assert '#' not in out
    assert '\n' not in out


def test_long_body_truncated_with_ellipsis():
    body = "正文" * 1000  # 2000 chars, no markdown
    out = _make_excerpt(body)
    assert len(out) <= _EXCERPT_MAX_CHARS + 1  # +1 for the ellipsis char
    assert out.endswith('…')


def test_strips_images_and_links():
    body = "![chart](https://x/y.png)\n\n見 [這篇文章](https://a/b) 的分析結論。"
    out = _make_excerpt(body)
    assert 'png' not in out
    assert 'http' not in out
    assert '這篇文章' in out  # link text kept
    assert '的分析結論' in out


def test_strips_markdown_marks():
    body = "## 重點\n\n- **粗體** 與 `code` 與 __底線__"
    out = _make_excerpt(body)
    assert '#' not in out
    assert '*' not in out
    assert '`' not in out
    assert '_' not in out
    assert '重點' in out
    assert '粗體' in out


def test_deterministic():
    body = "# A\n\n" + ("內容句子。" * 100)
    assert _make_excerpt(body) == _make_excerpt(body)


def test_excerpt_is_not_full_body_for_long_article():
    # The core invariant: a long body must NOT round-trip into description.
    body = "# 文章\n\n" + ("這是很長的正文段落，重複很多次以模擬真實文章。" * 50)
    out = _make_excerpt(body)
    assert len(out) < len(body)
    assert len(out) <= _EXCERPT_MAX_CHARS + 1
