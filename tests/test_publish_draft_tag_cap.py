"""Tests for tag count cap with priority eviction in publish_draft.py.

Background (2026-05-08, K726 mile_b4cd56fa agent feedback):
    Cross-K general articles routinely listed 6-8 user tags in frontmatter
    + experiment_refs=[K1, K2, K3]. Publisher prepends the audience badge
    tag (`一般讀者`) → final tag count overshoots publisher's
    `_GENERAL_MAX_TAG_COUNT = 8` audit cap and fails the publish. Agents
    had to manually shrink frontmatter tags to ≤6 as buffer space.

    Per CLAUDE.md "永遠修流程，不修資料" the cap is now applied in
    publish_draft.py before the publisher CLI is invoked, with priority
    eviction (user > audience > K-id).

Test surface:
    - _cap_tags_with_priority unit tests (eviction order, dedupe, edge cases)
    - Per spec: 3 scenario tests covering 6+1+3, 5+1+1, 8+1+2 inputs
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import (  # noqa: E402
    TAG_CAP,
    _cap_tags_with_priority,
)


# ---------------------------------------------------------------------------
# Spec scenarios from K726 agent feedback
# ---------------------------------------------------------------------------


def test_six_user_tags_plus_audience_plus_three_kids_caps_at_eight():
    """frontmatter 6 + audience=general + refs=[K1,K2,K3] → final ≤8 (K-id evicted)."""
    user = ["a", "b", "c", "d", "e", "f"]
    refs = ["K1", "K2", "K3"]
    final, audit = _cap_tags_with_priority(user, "general", refs)
    assert len(final) <= TAG_CAP
    assert len(final) == 8
    # User tags must all survive (highest priority)
    for t in user:
        assert t in final
    # Audience tag survives
    assert "一般讀者" in final
    # K-id eviction: 6 + 1 + 3 = 10 → evict 2 from end of K-id group.
    # Newest K-id (K3) evicted first, then K2; K1 survives.
    assert "K1" in final
    assert "K2" not in final
    assert "K3" not in final
    # Audit verifies eviction order: K3 first (newest), K2 second
    assert audit["evicted"] == ["K3", "K2"]


def test_five_user_tags_plus_audience_plus_one_kid_no_eviction():
    """frontmatter 5 + audience=general + refs=[K1] → final 7 (no eviction)."""
    user = ["a", "b", "c", "d", "e"]
    refs = ["K1"]
    final, audit = _cap_tags_with_priority(user, "general", refs)
    assert len(final) == 7
    assert audit["evicted"] == []
    assert final == ["a", "b", "c", "d", "e", "一般讀者", "K1"]


def test_eight_user_tags_plus_audience_plus_two_kids_evicts_all_kids_and_audience():
    """frontmatter 8 + audience=general + refs=[K1,K2] → final 8 user tags only.

    Total input = 8 user + 1 audience + 2 K-ids = 11 → evict 3 to fit cap=8.
    Eviction order: K2, K1 (kid group from end), then audience (lowest non-user).
    All 8 user tags survive (highest priority).
    """
    user = ["a", "b", "c", "d", "e", "f", "g", "h"]
    refs = ["K1", "K2"]
    final, audit = _cap_tags_with_priority(user, "general", refs)
    assert len(final) == 8
    # All user tags survive (top priority)
    for t in user:
        assert t in final
    # All K-ids evicted (lowest priority, evicted first)
    assert "K1" not in final
    assert "K2" not in final
    # Audience also evicted (1 more needed after K-ids exhausted)
    assert "一般讀者" not in final
    # Audit: K2 evicted first (newest), K1 next, audience last
    assert audit["evicted"] == ["K2", "K1", "一般讀者"]


# ---------------------------------------------------------------------------
# Eviction order edge cases
# ---------------------------------------------------------------------------


def test_dedupe_case_insensitive_first_occurrence_wins():
    """`Tag` and `tag` deduped; first-occurrence casing kept."""
    user = ["Alpha", "alpha", "Beta"]
    final, _ = _cap_tags_with_priority(user, "general", [])
    # 'Alpha' kept (first), 'alpha' deduped, 'Beta' kept; +'一般讀者'
    assert final == ["Alpha", "Beta", "一般讀者"]


def test_kid_dedupe_against_user_tag():
    """K-id tag also in user tags is deduped (kept under user priority)."""
    user = ["alpha", "K1"]  # K1 directly listed as user tag
    refs = ["K1", "K2"]
    final, audit = _cap_tags_with_priority(user, "general", refs)
    # K1 kept under user priority; ref K1 dropped via dedupe; K2 added as kid
    assert "K1" in final
    assert final.count("K1") == 1
    assert "K2" in final


def test_no_audience_tag_for_unknown_audience():
    """Unknown audience → no audience tag added; cap budget reflects this."""
    user = ["a", "b", "c", "d", "e", "f", "g", "h"]
    refs = ["K1"]
    final, audit = _cap_tags_with_priority(user, "unknown_audience", refs)
    # 8 user + 0 audience + 1 K-id = 9 → evict K1
    assert len(final) == 8
    assert audit["input_audience_tag"] == ""
    assert "K1" not in final


def test_research_audience_uses_yan_jiu_tag():
    """audience='research' inserts `研究` badge, not `一般讀者`."""
    user = ["a", "b"]
    final, audit = _cap_tags_with_priority(user, "research", [])
    assert audit["input_audience_tag"] == "研究"
    assert "研究" in final
    assert "一般讀者" not in final


def test_empty_inputs_returns_empty_list():
    """No user tags + unknown audience + no refs → empty list."""
    final, audit = _cap_tags_with_priority([], "", [])
    assert final == []
    assert audit["evicted"] == []


def test_non_kid_refs_filtered_from_tag_assembly():
    """Non-K provenance refs (e.g. 'paper-9') excluded from tag list."""
    user = ["a"]
    refs = ["paper-9", "K1", "fred-vix", "K2"]
    final, audit = _cap_tags_with_priority(user, "general", refs)
    # Only K1, K2 are kid_tags; paper-9, fred-vix not eligible as tags
    assert audit["input_kid_tags"] == ["K1", "K2"]
    assert "paper-9" not in final
    assert "fred-vix" not in final
    assert "K1" in final
    assert "K2" in final


def test_audience_evicted_only_after_all_kids_gone():
    """When user tags fill cap, audience evicted before any user tag."""
    # 9 user tags > cap 8 → no kid in input, audience must be evicted
    user = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]
    final, audit = _cap_tags_with_priority(user, "general", [])
    # 9 + 1 audience = 10; need to drop 2 → audience first, then last user 'i'
    assert len(final) == 8
    assert "一般讀者" not in final
    # Last user tag 'i' evicted (after audience)
    assert "i" not in final
    # Earlier user tags survive (a-h)
    for t in ["a", "b", "c", "d", "e", "f", "g", "h"]:
        assert t in final


def test_evicts_newest_kid_first_within_kid_group():
    """When eviction needed within K-id group, last (newest) K-id evicted first."""
    user = ["a", "b", "c", "d", "e", "f", "g"]  # 7 user
    refs = ["K100", "K200", "K300"]  # 3 K-ids
    final, audit = _cap_tags_with_priority(user, "general", refs)
    # 7 + 1 + 3 = 11 → evict 3 (all K-ids), audit shows newest-first order
    assert audit["evicted"] == ["K300", "K200", "K100"]
    assert "一般讀者" in final
    for t in user:
        assert t in final
