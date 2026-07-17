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

2026-07-14 recurrence (one day later, same theme, same victims): the trending
task 「AI變現挑戰：從期權波動率解析科技巨頭的資本定價分歧」 scored
entities=[US_EQUITY] — non-empty, so the 2026-07-13 guard (`not entities and not
refs`) did not fire, and the CLI printed `clean` against those same articles.
US_EQUITY is a CORE entity, which `_is_significant_overlap` subtracts before
matching, so a core-only entity list is exactly as unanchorable as an empty one.

The guard now asks the matcher itself (`arc_dedup.is_arc_anchorless`) whether it
had an anchor, so the CLI can no longer hold a narrower opinion than the matcher
it is reporting on. These tests assert the PREDICATE, not just the hint list the
old tests exercised — that gap is why the same hole leaked twice.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import (  # noqa: E402
    arc_signature,
    find_arc_duplicates,
    is_arc_anchorless,
    is_arc_near_miss,
)

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


# --- the anchor predicate itself -------------------------------------------
# The 2026-07-13 tests above only exercised find_lexical_hints — the guard's
# *output*. Nothing asserted the guard actually FIRES on the incident topic, so
# when the definition of "thin" turned out to be too narrow, no test objected.
# These pin the predicate.

# 2026-07-14: the topic that came back and passed as `clean`.
CAPEX_TITLE = "AI變現挑戰：從期權波動率解析科技巨頭的資本定價分歧"
CAPEX_TEXT = (
    "隨著市場對 AI 變現速度的審視，高額資本支出面臨考驗。可量化角度：分析美股七巨頭的"
    "歷史 CapEx 宣告日前後，其隱含波動率（IV）與歷史波動率（HV）的溢價擴張程度。"
)


def _verdict(title, text, feed):
    """The CLI's verdict ladder, reproduced over an explicit feed.

    `check_arc_dedup.main` derives this from find_arc_duplicates + the anchor
    predicate; the tests below only care that the incident topics never reach
    `clean`.
    """
    matches = find_arc_duplicates(
        title, text, feed, days=3650, audience="general", include_fuzzy=True
    )
    dups = [m for m in matches if not is_arc_near_miss(m)]
    near = [m for m in matches if is_arc_near_miss(m)]
    if dups:
        return "block_arc_dup"
    if near:
        return "warn_arc_near_miss"
    if is_arc_anchorless(arc_signature(title, text), None):
        return "unjudged_thin_signature"
    return "clean"


# Both incident topics were waved through as `clean`. THAT is the invariant, and
# these assert it end-to-end rather than via a proxy. The two tests here used to
# pin the proxy instead — "entities are empty" / "entities are core-only" — which
# made them fixtures of the VOCABULARY HOLE rather than of the guarantee. When
# 2026-07-17 registered the mega-cap vocabulary (the fix for that very hole),
# both proxies went stale and the topics became anchorable; asserting the verdict
# keeps the guarantee pinned no matter what the entity table learns to see next.


def test_2026_07_13_incident_topic_is_never_clean():
    """It is a duplicate of the live twins; the gate must not say otherwise."""
    assert _verdict(TOPIC_TITLE, TOPIC_TEXT, FEED) != "clean"


def test_2026_07_13_incident_topic_now_names_its_twins():
    """The 2026-07-17 vocabulary upgrade: the gate stopped shrugging and looked.

    Pre-fix this topic scored entities=[] -> `unjudged_thin_signature`, an honest
    "I could not look" that still left the caller to find the twins by hand. With
    BIG_TECH/CAPEX_CYCLE registered it now names them.
    """
    sig = arc_signature(TOPIC_TITLE, TOPIC_TEXT)
    assert "BIG_TECH" in sig["entities"]
    assert is_arc_anchorless(sig, None) is False
    hit_ids = {
        m["id"]
        for m in find_arc_duplicates(
            TOPIC_TITLE, TOPIC_TEXT, FEED, days=3650,
            audience="general", include_fuzzy=True,
        )
    }
    assert "mile_f5f4cb43" in hit_ids
    # Retracted articles are not reader-visible, so they cannot constitute a dup.
    assert "mile_dead0001" not in hit_ids
    # ... and an unrelated copper piece must not be swept in by the new vocabulary.
    assert "mile_unrelated" not in hit_ids
    # NOT asserted: mile_622a2b73. These FEED rows carry a title and nothing else,
    # and its title alone yields no mechanism, which the descriptive branch needs.
    # Against the real feed (full body text) the topic does reach it. Pinning it
    # here would pin the fixture's thinness, not the gate.


def test_2026_07_14_mechanism_silent_topic_still_names_its_twin():
    """THE REGRESSION, in its 2026-07-17 form — and where the fix belongs.

    This topic is `descriptive` and writes 「期權」/「隱含波動率」, neither of which
    is a mechanism keyword, so mechanisms is [unspecified]. The descriptive branch
    used to demand a shared SPECIFIC mechanism, which read "no mechanism could be
    extracted" as "a different mechanism" — so the 2026-07-13 twins, every one of
    them descriptive AND mechanism-silent, were unmatchable BY CONSTRUCTION. The
    vocabulary fix alone could not reach this: it gives the topic more entities,
    and the branch was not looking at entities.

    Making `is_arc_anchorless` mirror that behaviour (descriptive + no mechanism
    -> "unanchorable") would have pinned the bug as a rule. The matcher now falls
    back to the entity overlap when either side is mechanism-silent, so the topic
    is judged on its merits and NAMES the twin instead of shrugging at it.
    """
    sig = arc_signature(CAPEX_TITLE, CAPEX_TEXT)
    assert sig["conclusion_class"] == "descriptive"
    assert sig["mechanisms"] == ["unspecified"]
    assert set(sig["entities"]) - {"US_EQUITY", "VIX", "TW_EQUITY"}, (
        "fixture premise: this topic DOES now carry distinctive entities"
    )
    # It has something to compare on, so the gate must not excuse itself.
    assert is_arc_anchorless(sig, None) is False
    hit_ids = {
        m["id"]
        for m in find_arc_duplicates(
            CAPEX_TITLE, CAPEX_TEXT, FEED, days=3650,
            audience="general", include_fuzzy=True,
        )
    }
    assert "mile_f5f4cb43" in hit_ids
    assert "mile_unrelated" not in hit_ids


def test_2026_07_14_incident_topic_is_never_clean():
    assert _verdict(CAPEX_TITLE, CAPEX_TEXT, FEED) != "clean"


def test_descriptive_with_specific_mechanism_is_anchorable():
    """The tightening must not swallow the anchored case it is carved out of."""
    sig = {
        "entities": ["COPPER", "VIX"],
        "conclusion_class": "descriptive",
        "mechanisms": ["carry_regime"],
    }
    assert is_arc_anchorless(sig, None) is False


def test_mechanism_silence_is_not_evidence_of_a_different_arc():
    """Two descriptive pieces on the same entity match even with no mechanism.

    The inverse — both sides naming a specific and DISJOINT mechanism — is real
    evidence of different arcs and still separates them; that is the SpaceX
    false-positive guard, pinned in `test_disjoint_specific_mechanisms_separate`.
    """
    feed = [
        {
            "id": "mile_copper",
            "audience": "general",
            "status": "published",
            "published_at": "2026-06-30T00:00:00+00:00",
            "title": "銅的波動率結構",
            "summary": "分析 HG=F 銅期貨的波動率結構。",
        }
    ]
    hits = find_arc_duplicates(
        "銅期貨的波動特徵", "檢視 HG=F 銅期貨的波動率行為。",
        feed, days=3650, audience="general", include_fuzzy=True,
    )
    assert {m["id"] for m in hits} == {"mile_copper"}
    # Advisory only: mechanism-silent evidence must never become a hard block.
    assert all(is_arc_near_miss(m) for m in hits)


def test_disjoint_specific_mechanisms_separate():
    """Both sides named a mechanism and they disagree -> genuinely different arcs."""
    feed = [
        {
            "id": "mile_copper_carry",
            "audience": "general",
            "status": "published",
            "published_at": "2026-06-30T00:00:00+00:00",
            "title": "銅礦股的散戶參與度",
            "summary": "分析 HG=F 銅期貨的散戶參與與融資餘額變化。",
        }
    ]
    hits = find_arc_duplicates(
        "銅的選擇權偏斜", "檢視 HG=F 銅期貨選擇權偏斜（skew）與 vix9d 的期限結構。",
        feed, days=3650, audience="general", include_fuzzy=True,
    )
    assert hits == []


def test_non_descriptive_piece_anchors_on_entities_alone():
    """Outside the descriptive branch, `unspecified` mechanisms stay compatible."""
    sig = {
        "entities": ["COPPER"],
        "conclusion_class": "null_no_info",
        "mechanisms": ["unspecified"],
    }
    assert is_arc_anchorless(sig, None) is False


def test_distinctive_entity_is_anchorable():
    """A non-core entity gives the matcher something to compare on -> not thin.

    2026-07-17: this fixture used to carry no mechanism keyword and still expected
    `False`, which the matcher never actually honoured on the descriptive path —
    it needs a specific shared mechanism there. The fixture now says 「選擇權
    偏斜」 so the piece is anchorable for the reason the test claims. The
    no-mechanism case it used to assert by accident is pinned explicitly in
    `test_generic_mechanism_does_not_anchor_a_descriptive_piece`.
    """
    sig = arc_signature(
        "銅博士的波動率版本：金屬與股市的尾部連動",
        "分析 HG=F 銅期貨與 SPY 的尾部相關性，以及選擇權偏斜（skew）的波動率外溢。",
    )
    assert set(sig["entities"]) - {"US_EQUITY", "VIX", "TW_EQUITY"}
    assert is_arc_anchorless(sig, None) is False


def test_experiment_ref_alone_is_an_anchor():
    """No entities at all, but a K-id -> the same-K short-circuit can still fire."""
    sig = arc_signature("一個沒有標的的題目", "純方法論討論，不提任何資產。")
    assert is_arc_anchorless(sig, {"K1054"}) is False


def test_core_entities_are_never_anchors():
    """Pin the core set the predicate mirrors, so a matcher change breaks a test."""
    sig = {"entities": ["US_EQUITY", "VIX", "TW_EQUITY"], "conclusion_class": "descriptive"}
    assert is_arc_anchorless(sig, None) is True
