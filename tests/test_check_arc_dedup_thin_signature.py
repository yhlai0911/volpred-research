"""Regression tests for the pre-write dedup gate's thin-signature guard.

2026-07-13 incident: the trending task "AI營收不如預期？科技股選擇權偏斜率（Skew）洩天機"
passed `check_arc_dedup.py` with a green ✅ and exit 0 while four live articles
already told that story (`mile_f5f4cb43`, `mile_8a5e80b0`, `mile_49616ac2`,
`mile_622a2b73`).

Root cause: the topic carried no K-id and no ticker, so `extract_entities`
returned nothing, and `find_arc_duplicates` bails out with `[]` in exactly that
case (arc_dedup.py ~L856: "with no entities AND no refs there is nothing to
anchor a match on"). That `[]` means "I could not look", but the CLI rendered it
identically to "I looked and it is clean".

The fix cannot be a hard block: `.claude/rules/dedup-gate-audit.md` requires
fuzzy gates to fail OPEN (a fail-closed dedup gate caused the 2026-06-23 eight-day
content black hole). So the guard keeps exit 0 and instead refuses to claim the
piece is clean, surfacing lexical near-misses for the caller to judge.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_arc_dedup import _tokens, find_lexical_hints  # noqa: E402


def _item(mile_id, title, status="published", audience="general"):
    return {
        "id": mile_id,
        "title": title,
        "status": status,
        "audience": audience,
        "published_at": "2026-06-30T00:00:00+00:00",
    }


# The articles that were live on 2026-07-13 when the gate waved the topic through.
FEED = [
    _item("mile_f5f4cb43", "科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點"),
    _item("mile_622a2b73", "資本支出暴增八成，股票卻平靜如水：AI 巨頭的波動率定價迷局"),
    _item("mile_0941e2f0", "半導體修正進行中：選擇權偏斜告訴你市場還沒放心"),
    _item("mile_unrelated", "銅博士的波動率版本：金屬與股市的尾部連動"),
    _item("mile_dead0001", "AI 資本支出的裂縫：指數安靜，個股先吵起來", status="retracted"),
]

TOPIC_TITLE = "AI營收不如預期？科技股選擇權偏斜率（Skew）洩天機"
TOPIC_TEXT = (
    "聚焦科技巨頭資本支出轉化為實際營收的效率。量化方法：分析 Nasdaq 100 "
    "隱含波動率偏斜率（Skew Index）與科技股季報營收驚喜度之關聯性。"
)


def test_the_duplicate_that_slipped_through_is_now_surfaced():
    """The whole point: the AI-capex/skew twin must appear in the hints."""
    hits = find_lexical_hints(TOPIC_TITLE, TOPIC_TEXT, FEED)
    assert "mile_f5f4cb43" in {h["id"] for h in hits}


def test_closest_article_ranks_first():
    hits = find_lexical_hints(TOPIC_TITLE, TOPIC_TEXT, FEED)
    assert hits[0]["id"] == "mile_f5f4cb43"
    assert hits[0]["score"] > hits[-1]["score"]


def test_unrelated_article_is_not_a_hint():
    ids = {h["id"] for h in find_lexical_hints(TOPIC_TITLE, TOPIC_TEXT, FEED)}
    assert "mile_unrelated" not in ids


def test_retracted_article_is_not_a_hint():
    """A retracted piece is not reader-visible, so it is not evidence of coverage —
    otherwise a retraction would permanently discourage the corrected rewrite."""
    ids = {h["id"] for h in find_lexical_hints(TOPIC_TITLE, TOPIC_TEXT, FEED)}
    assert "mile_dead0001" not in ids


def test_empty_probe_yields_no_hints():
    assert find_lexical_hints("", "", FEED) == []


def test_hints_are_capped():
    feed = [_item(f"mile_{i}", TOPIC_TITLE) for i in range(20)]
    assert len(find_lexical_hints(TOPIC_TITLE, TOPIC_TEXT, feed)) <= 5


def test_tokens_handle_cjk_and_latin():
    toks = _tokens("科技股 Skew index")
    assert "科技" in toks  # CJK bigram
    assert "skew" in toks  # latin word, lowercased
    assert "科技股" not in toks  # trigrams are not emitted; bigrams only


def test_tokens_drop_short_latin_words():
    """Two-letter noise ('AI', 'of') would match almost anything."""
    assert _tokens("AI of the") == {"the"}
