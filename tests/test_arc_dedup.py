"""Tests for narrative-arc duplicate detection (2026-06-10 K1449/K1091 incident).

Regression contract: every case below reproduces a real shipped duplicate (or a
real non-duplicate that must NOT be blocked). If any of these fail, the arc gate
has regressed to the title-similarity blind spot.
"""

from datetime import datetime, timedelta, timezone

import pytest

from volpred.publisher.arc_dedup import (
    classify_conclusion,
    extract_entities,
    find_arc_duplicates,
)


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# --- The actual K1091 article (2026-05-16) that K1449 duplicated -------------
K1091_ARTICLE = {
    "id": "mile_232ce5d4",
    "title": "ç‚ºä»€éº¼åŒæ¨£æ˜¯ã€å•†å“ ETFã€ï¼ŒéŠ…éŠ€å°±æ˜¯åƒä¸åˆ° VIX ç´…åˆ©ï¼Ÿâ€”â€” çµ¦æ•£æˆ¶èˆ‡è³‡ç”¢é…ç½®è€…çš„ä¸€å¼µè³‡ç”¢ç›¸å®¹æ€§åœ°åœ–",
    "description": (
        "æ‹¿ VIXï¼ˆS&P 500 çš„ææ…ŒæŒ‡æ•¸ï¼‰å»æ¨å…¨çƒè‚¡ç¥¨ ETFï¼ˆVGK æ­è‚¡ã€EWJ æ—¥è‚¡ï¼‰çš„æ³¢å‹•ç‡æ˜¯æœ‰æ•ˆçš„ï¼›"
        "æ‹¿åŒä¸€å€‹ VIX å»æ¨æ²’æœ‰è‡ªå·± IV æŒ‡æ•¸çš„å•†å“ ETFï¼ˆCPER éŠ…ã€SLV éŠ€ï¼‰ï¼Œå¹¾ä¹æ²’ç”¨ï¼Œè·Ÿä¸€èˆ¬ GARCH æ¨¡å‹æ²’å·®åˆ¥ã€‚"
    ),
    "status": "published",
    "published_at": _ts(days_ago=25),
}

# --- The K1449 piece that slipped through every gate on 2026-06-10 -----------
K1449_TITLE = "éŠ…åšå£«çš„æ³¢å‹•ç‡ç‰ˆæœ¬ï¼š13 å¹´æ•¸æ“šèªªäº†ä»€éº¼"
K1449_CONTENT = (
    "éŠ…çš„æ³¢å‹•ç¨‹åº¦ï¼Œèƒ½ä¸èƒ½é æ¸¬è‚¡å¸‚æœªä¾†çš„æ³¢å‹•ç¨‹åº¦ï¼Ÿé€™å€‹åˆ†æè¿½è¹¤ CPER å’Œ SPY çš„ 21 æ—¥å¯¦ç¾æ³¢å‹•ç‡ã€‚"
    "ç›¸é—œä¿‚æ•¸ 0.057ï¼Œæ¥è¿‘æ–¼é›¶ã€‚åŠ å…¥ VIX å¾Œï¼ŒéŠ…æ³¢å‹•çš„å¢é‡è³‡è¨Šå¹¾ä¹æ­¸é›¶ã€‚"
)


class TestEntityExtraction:
    def test_copper_from_chinese_and_ticker(self):
        ents = extract_entities("éŠ…åšå£«çš„æ³¢å‹•ç‡ç‰ˆæœ¬ CPER vs SPY")
        assert "COPPER" in ents
        assert "US_EQUITY" in ents

    def test_ticker_word_boundary(self):
        # 'tip' must not match inside other words
        assert "TIPS" not in extract_entities("multiple tips for traders")
        assert "TIPS" in extract_entities("TIP æŠ—é€šè†¨å‚µ ETF")

    def test_no_entities_returns_empty(self):
        assert extract_entities("ä¸€ç¯‡é—œæ–¼æ–¹æ³•è«–çš„æ–‡ç« ") == set()

    def test_low_vol_factor_requires_factor_etf_context(self):
        # Generic market-regime wording should not collide with USMV/factor ETF
        # articles in arc dedup.
        assert "LOW_VOL_FACTOR" not in extract_entities("è¿‘æœŸä½æ³¢å‹•ç’°å¢ƒè®“ VIX é™åˆ° 14")
        assert "LOW_VOL_FACTOR" in extract_entities("USMV æ˜¯ä½æ³¢å‹• ETF")
        assert "LOW_VOL_FACTOR" in extract_entities("ä½æ³¢å‹•å› å­å’Œå“è³ªå› å­æ¯”è¼ƒ")


class TestConclusionClassification:
    def test_null_class(self):
        assert classify_conclusion("å¢é‡è³‡è¨Šå¹¾ä¹æ­¸é›¶ï¼Œæ¥è¿‘æ–¼é›¶") == "null_no_info"
        assert classify_conclusion("åƒä¸åˆ° VIX ç´…åˆ©ï¼Œå¹¾ä¹æ²’ç”¨") == "null_no_info"

    def test_descriptive_fallback(self):
        assert classify_conclusion("æœ¬æ–‡ä»‹ç´¹ä¸‰ç¨®æ¨¡å‹çš„å»ºæ§‹æ–¹å¼") == "descriptive"


class TestArcDuplicates:
    def test_k1449_vs_k1091_regression(self):
        """The 2026-06-10 incident: ~0 title overlap, different K refs,
        same story (copper Ã— VIX/equity-vol â†’ no info). MUST be caught."""
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [K1091_ARTICLE])
        assert dups, "K1449 arc-duplicate of K1091 was not detected â€” incident regression"
        assert dups[0]["id"] == "mile_232ce5d4"
        assert "COPPER" in dups[0]["shared_entities"]

    def test_direction_agnostic(self):
        """Aâ†’B null vs Bâ†’A null is the same arc to the reader."""
        reversed_article = {
            "id": "mile_x",
            "title": "VIX æ¨ä¸å‹•éŠ…åƒ¹æ³¢å‹•",
            "description": "VIX å° CPER æ³¢å‹•ç‡å¹¾ä¹æ²’æœ‰é æ¸¬åŠ›ï¼Œç„¡å¢é‡è³‡è¨Šã€‚",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [reversed_article])
        assert dups and dups[0]["id"] == "mile_x"

    def test_core_only_overlap_not_blocked(self):
        """Two articles that only share SPY/VIX (ubiquitous) are NOT dups."""
        other = {
            "id": "mile_y",
            "title": "é»ƒé‡‘æ³¢å‹•ç‡åœ¨å‡æ¯å¾ªç’°çš„è¡¨ç¾",
            "description": "GLD èˆ‡ SPY çš„æ³¢å‹•ç‡æ¯”è¼ƒï¼Œé»ƒé‡‘é¿éšªæ•ˆæœä¸æˆç«‹ã€‚",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        new_title = "æ—¥åœ“é¿éšªå±¬æ€§æª¢é©—"
        new_content = "FXY èˆ‡ SPY æ³¢å‹•ç‡ï¼Œrisk-off æ™‚æ—¥åœ“é¿éšªä¸æˆç«‹ï¼Œç„¡å¢é‡è³‡è¨Šã€‚"
        dups = find_arc_duplicates(new_title, new_content, [other])
        assert dups == []  # share only US_EQUITY (core) â€” different assets

    def test_different_conclusion_class_not_blocked(self):
        """Same assets but opposite conclusion = genuinely new finding, allow."""
        positive_copper = {
            "id": "mile_z",
            "title": "éŠ…æ³¢å‹•çš„é ˜å…ˆè¨Šè™Ÿ",
            "description": "CPER æ³¢å‹•ç‡é¡¯è‘—é ˜å…ˆ SPYï¼Œé æ¸¬åŠ›é¡¯è‘—ï¼Œé€šéæª¢å®šã€‚",
            "status": "published",
            "published_at": _ts(days_ago=5),
        }
        dups = find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [positive_copper])
        assert dups == []

    def test_old_article_outside_window(self):
        old = dict(K1091_ARTICLE, published_at=_ts(days_ago=120))
        assert find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [old], days=90) == []

    def test_unpublished_ignored(self):
        unpub = dict(K1091_ARTICLE, status="unpublished")
        assert find_arc_duplicates(K1449_TITLE, K1449_CONTENT, [unpub]) == []


class TestPublisherGateWiring:
    def test_publish_milestone_blocks_arc_dup(self, tmp_path, monkeypatch):
        """End-to-end: publish_milestone must refuse the K1449 article when the
        K1091 article is in the feed."""
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=K1449_TITLE,
            description=K1449_CONTENT,
            phase="Phase_X",
            status="draft",
            audit_strict=False,
        )
        # Blocked â†’ returns the existing dup id, and no new article in feed
        assert returned == "mile_232ce5d4"
        feed = _json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
        assert len(feed) == 1

    def test_dup_waiver_overrides(self, tmp_path):
        import json as _json

        storage = tmp_path / "storage"
        (storage / "reports").mkdir(parents=True)
        (storage / "reports" / "feed.json").write_text(
            _json.dumps([K1091_ARTICLE], ensure_ascii=False), encoding="utf-8"
        )
        from volpred.publisher.publisher import Publisher

        pub = Publisher(storage_dir=str(storage))
        returned = pub.publish_milestone(
            title=K1449_TITLE,
            description=K1449_CONTENT,
            phase="Phase_X",
            status="draft",
            details={"dup_waiver": "deliberate follow-up with new angle"},
            audit_strict=False,
        )
        assert returned != "mile_232ce5d4"


def test_vt_crowding_arc_caught():
    """2026-06-14 regression: ï¿½…ï¿½ï¿½‡ï¿½€VT crowding ï¿½†’ ï¿½‚å ´ï¿½›ï¿½ï¿½ï¿½‰ï¿½…ï¿½ï¿½€ï¿½Œ arc ï¿½ï¿½Œ K/audience
    ï¿½ˆmile_ec28b1cc K1047 ï¿½€ï¿½ˆï¿½ï¿½€ï¿½€… + mile_1a6d9369 K864 ï¿½”ç©¶ï¿½‰ï¿½Œï¿½—ï¿½ï¿½™ï¿½ï¿½ˆï¿½ï¿½ï¿½ï¿½ˆï¿½ï¿½€‚
    ä¿®ï¿½œï¿½Œ VOL_TARGETING å¯¦ï¿½” + systemic_crowding conclusion class ï¿½‡‰ï¿½Š“ï¿½ˆï¿½ï¿½€‚"""
    from volpred.publisher.arc_dedup import find_arc_duplicates, extract_entities, classify_conclusion
    existing = [{
        "id": "mile_1a6d9369", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "ï¿½ˆ†ï¿½•ï¿½ï¿½­–ï¿½•ï¿½ï¿½•‘ï¿½ï¿½†ï¿½‚å ´ï¿½šæ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ï¿½š„ï¿½›†ï¿½”ï¿½™ï¿½ï¿½˜ï¿½",
        "content": "æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ï¿½­–ï¿½•ï¿½ç¾¤ï¿½šä½¿ï¿½”ï¿½ï¿½Œ1000 agents ä»£ï¿½†äººæ¨¡ï¿½“ï¿½é¡¯ç¤ºï¿½›†ï¿½”ï¿½™ï¿½ï¿½˜ï¿½ï¿½€ç³»çµ±ï¿½€ï¿½é¢¨ï¿½šï¿½ï¿½€ï¿½–ƒå´©ï¿½”ï¿½å¤§æ³¢ï¿½‹•ï¿½€‚é¢¨ï¿½šï¿½å¹³ï¿½ƒï¿½ï¿½Œï¿½†ï¿½€‚",
    }]
    new_title = "ï¿½‚ï¿½œï¿½„ˆï¿½†ï¿½„ˆï¿½šäººï¿½ƒï¿½ï¿½”ï¿½ï¿½Œï¿½€ï¿½—ï¿½ï¿½ï¿½šï¿½ï¿½ï¿½‰‡ï¿½Œï¿½‚å ´ï¿½œƒï¿½›ï¿½ï¿½‰ï¿½…ï¿½ï¿½—ï¿½Ÿ"
    new_content = "ï¿½„ˆï¿½†ï¿½„ˆï¿½šäººï¿½…ï¿½ï¿½Œï¿½€ï¿½—æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ï¿½ï¿½‰‡ï¿½šï¿½Œï¿½‚å ´ï¿½›†ï¿½”ï¿½ï¿½ï¿½šï¿½ï¿½ï¿½€Œï¿½›ï¿½ï¿½ï¿½‰ï¿½…ï¿½ï¿½Œæ¨¡ï¿½“ï¿½ï¿½”ç©¶é¡¯ç¤ºç¾¤ï¿½šï¿½”ï¿½å¤§æ³¢ï¿½‹•ï¿½€‚"
    assert "VOL_TARGETING" in extract_entities(new_title + "\n" + new_content)
    assert classify_conclusion(new_title + "\n" + new_content) == "systemic_crowding"
    dups = find_arc_duplicates(new_title, new_content, existing, days=3650)
    assert any(d["id"] == "mile_1a6d9369" for d in dups), "VT-crowding arc ï¿½‡‰è¢«ï¿½Š“ï¿½ˆï¿½"


def test_vt_different_conclusion_not_blocked():
    """ï¿½èª¤ï¿½“‹ï¿½šï¿½Œæ¨£ VT å¯¦ï¿½”ï¿½†ï¿½ï¿½Œï¿½ï¿½–ï¿½ˆcrowding vs ï¿½­ï¿½ï¿½‘ï¿½‰ï¿½ï¿½‡‰ dedupï¿½€‚"""
    from volpred.publisher.arc_dedup import find_arc_duplicates
    existing = [{
        "id": "mile_vtpos", "status": "published",
        "published_at": "2026-06-14T04:00:00+00:00",
        "title": "æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™é¡¯ï¿½‘—ï¿½™ï¿½ï¿½›ï¿½’ï¿½ï¿½šè·¨ï¿½‡ï¿½”ï¿½å¯¦ï¿½­‰",
        "content": "æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ï¿½­–ï¿½•ï¿½ï¿½œ‰ï¿½•ˆï¿½™ï¿½ MDDï¿½Œï¿½€šï¿½ DM æª¢ï¿½šé¡¯ï¿½‘—ï¿½”ï¿½ï¿½–„ï¿½Œç©©ï¿½ï¿½ï¿½ˆï¿½‹ï¿½€‚",
    }]
    dups = find_arc_duplicates(
        "æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ï¿½š„ï¿½›†ï¿½”ï¿½™ï¿½ï¿½˜ï¿½ï¿½šç¾¤ï¿½šï¿½”ï¿½å¤§ç³»çµ±ï¿½€ï¿½é¢¨ï¿½šï¿½",
        "æ³¢ï¿½‹•ï¿½‡ï¿½›ï¿½ï¿½™ç¾¤ï¿½šä½¿ï¿½”ï¿½ï¿½ï¿½‡ï¿½ï¿½›†ï¿½”ï¿½™ï¿½ï¿½˜ï¿½ï¿½€ç³»çµ±ï¿½€ï¿½é¢¨ï¿½šï¿½ï¿½€ï¿½–ƒå´©ï¿½€‚",
        existing, days=3650,
    )
    assert not dups, "ï¿½ï¿½Œï¿½ï¿½–ï¿½š„ VT ï¿½–‡ç« ï¿½ï¿½‡‰è¢«èª¤ï¿½“‹"
