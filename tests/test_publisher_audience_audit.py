"""Tests for 2026-04-26 audience-content consistency gate.

Root cause covered: prior bug let agents publish audience='general' articles
containing K-id tags + research jargon (Harvey, DM test, t-stats) because
publisher only checked the audience field, not whether content matched.
mile_4fa40750 (FOMC T-2) was the trigger incident — 14 tags including 4
K-ids, 1788 CJK with research-style scenario grids labelled 'general'.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from volpred.publisher.publisher import (
    Publisher,
    _audit_general_content,
    _extract_experiment_refs,
)

# A valid general-audience article must carry a 懶人包圖組 (publishing.md §4,
# enforced by publish_milestone). These audit tests are about the audience-content
# consistency gate, not lazypack coverage, so they append a minimal lazypack to the
# general-audience descriptions to clear that orthogonal gate.
_LZ_BASE = "https://supabase.test/storage/v1/object/public/article-images"
_LZ = (
    "\n\n## 懶人包圖組\n\n"
    f"![概念]({_LZ_BASE}/lz1.png)\n\n"
    f"![結果]({_LZ_BASE}/lz2.png)\n"
)

# 2026-07-02 minimum-depth floor (general ≥1500 / research ≥2000 + 表格)：
# these tests target the audience/lazypack gates, so pad fixtures past the
# orthogonal depth gate with clean、無統計術語的白話填充。
_PAD_GENERAL = (
    "市場觀察筆記：投資人今天關心的是資金流向與情緒變化，"
    "我們用白話整理重點，幫你快速掌握全貌。"
) * 40
_TABLE = "\n\n| 項目 | 內容 |\n|---|---|\n| 重點 | 白話整理 |\n"
_PAD_RESEARCH = (
    "本研究完整交代資料來源、樣本期間、方法設計與穩健性檢查，"
    "並將結果整理成表格供讀者驗證，附錄提供重現步驟。"
) * 50 + _TABLE


def test_extract_experiment_refs_separates_k_ids():
    tags = ["一般讀者", "FOMC", "T-2", "K513", "K820", "K1100g", "macro"]
    cleaned, refs = _extract_experiment_refs(tags)
    assert cleaned == ["一般讀者", "FOMC", "T-2", "macro"]
    assert refs == ["K513", "K820", "K1100G"]


def test_extract_experiment_refs_handles_pure_user_tags():
    tags = ["一般讀者", "FOMC", "T-2", "macro-event"]
    cleaned, refs = _extract_experiment_refs(tags)
    assert cleaned == tags
    assert refs == []


def test_audit_general_content_clean_passes():
    content = (
        "想像你今天有 100 萬要投資。FOMC 會議要開了，你該怎麼辦？"
        "我們的研究發現：散戶通常會做錯三件事..."
    )
    tags = ["一般讀者", "FOMC", "macro", "教學"]
    assert _audit_general_content("general", tags, content) == []


def test_audit_general_content_blocks_t_stat_and_p_value():
    content = "本文研究結果 t=4.38, p=0.001, p<0.05 顯著."
    tags = ["一般讀者"]
    issues = _audit_general_content("general", tags, content)
    assert len(issues) == 1
    # 19daf2115 起 general-gate 訊息改「翻譯向」（裸統計術語→白話包裝指引），非舊「禁用統計術語」刪除向
    assert "裸統計術語" in issues[0]


def test_audit_general_content_blocks_harvey_dm_bootstrap():
    content = "通過 Harvey threshold 檢驗，DM test 結果顯著，bootstrap p_value=0.03."
    tags = ["一般讀者"]
    issues = _audit_general_content("general", tags, content)
    assert len(issues) == 1
    assert "Harvey" in issues[0] or "DM" in issues[0]


def test_audit_general_content_blocks_excessive_tags():
    tags = ["一般讀者", "a", "b", "c", "d", "e", "f", "g", "h"]  # 9 tags
    issues = _audit_general_content("general", tags, "簡單白話的文章")
    assert any("tag count" in i for i in issues)


def test_audit_general_content_research_audience_exempt():
    """Research audience can use t-stat / Harvey / unlimited K-id refs."""
    content = "Harvey |t|>3, DM test p=0.04, bootstrap p<0.05."
    tags = ["研究", "K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10"]
    assert _audit_general_content("research", tags, content) == []


def test_publish_milestone_research_jargon_overrides_general_audience(
    tmp_path: Path, monkeypatch, capsys
):
    """Integration: publish_milestone with audience='general' but research-grade
    content (Harvey, DM test, t-value) → _infer_audience overrides to 'research'
    instead of raising ValueError. (2026-05-26 behavior change: _infer_audience
    enforce gate takes priority over _audit_general_content; mile_d0d66405 fix.)

    Prior behavior (pre-2026-05-26): raised ValueError with match='general'.
    New behavior: audience silently corrected to 'research' + WARN log printed.
    """
    import json

    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))

    polluted_content = ("FOMC 會議前 t=4.38, Harvey |t|>3, DM test p=0.04。"
                        + _PAD_RESEARCH)

    # Should NOT raise ValueError — _infer_audience upgrades to 'research'
    pub_id = pub.publish_milestone(
        title="一般讀者測試標題",
        description=polluted_content,
        phase="research",
        audience="general",
        tags=["一般讀者", "FOMC"],
        status="draft",
    )

    assert pub_id.startswith("mile_")
    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(i for i in feed if i["id"] == pub_id)
    # _infer_audience must have overridden 'general' to 'research'
    assert item["audience"] == "research", f"expected 'research', got '{item['audience']}'"
    # WARN must be printed to stdout
    captured = capsys.readouterr()
    assert "_infer_audience" in captured.out and "WARN" in captured.out


def test_publish_milestone_strict_passes_clean_general(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))

    clean_content = (
        "想像你今天要參加一個重要會議。Fed 也是。94.8% 的人猜對結果，"
        "但市場為什麼還在緊張？因為剩下的 5% 機率太刺激了。"
        + _PAD_GENERAL + _LZ
    )

    pub_id = pub.publish_milestone(
        title="散戶的 FOMC 心理戰",
        description=clean_content,
        phase="research",
        audience="general",
        tags=["一般讀者", "FOMC", "心理", "教學"],
        status="draft",
    )
    assert pub_id.startswith("mile_")


def test_publish_milestone_strips_redundant_audience_aliases(
    tmp_path: Path, monkeypatch
):
    """Tag list must end with exactly one canonical Chinese audience badge.
    Historical bug: brief had ["一般讀者", "general"] or ["研究",
    "一般讀者", "general"]; old strip logic only knew Chinese values, so
    English 'general' / 'research' / 'daily-update' leaked through.
    """
    import json
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))

    pub_id = pub.publish_milestone(
        title="散戶可讀的方法論文章",
        description="一個白話故事，不含 jargon。" + _PAD_GENERAL + _LZ,
        phase="research",
        audience="general",
        # Polluted brief: Chinese + English audience tags + wrong-audience tag
        tags=["一般讀者", "general", "研究", "Research", "FOMC", "macro"],
        status="draft",
    )
    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(i for i in feed if i["id"] == pub_id)

    audience_aliases = {"一般讀者", "general", "研究", "research", "Research",
                        "General", "每日建議", "daily", "daily-update", "Daily",
                        "會員提問", "member_qa", "member-qa"}
    found_audience = [t for t in item["tags"] if t in audience_aliases]
    # Exactly one canonical Chinese audience tag
    assert found_audience == ["一般讀者"], f"got {found_audience}"
    # User-facing topic tags preserved
    assert "FOMC" in item["tags"]
    assert "macro" in item["tags"]


def test_publish_milestone_research_canonical_strips_general_alias(
    tmp_path: Path, monkeypatch
):
    """audience='research' brief with stray 'general' tag must yield only '研究'."""
    import json
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))

    pub_id = pub.publish_milestone(
        title="完整研究報告",
        description="包含完整方法論、表格與限制。" * 50,  # long enough
        phase="research",
        audience="research",
        tags=["研究", "general", "BMA", "波動率"],
        status="draft",
        audit_strict=False,  # research bypass not required, just here for clarity
    )
    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(i for i in feed if i["id"] == pub_id)

    audience_aliases = {"一般讀者", "general", "研究", "research"}
    found_audience = [t for t in item["tags"] if t in audience_aliases]
    assert found_audience == ["研究"]


def test_publish_milestone_extracts_k_ids_to_metadata(
    tmp_path: Path, monkeypatch
):
    """Brief sends K-ids in tags; publisher must move them to
    details.experiment_refs to keep user-facing tags clean."""
    import json
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)

    pub = Publisher(storage_dir=str(tmp_path))

    pub_id = pub.publish_milestone(
        title="散戶可讀的方法論文章",
        description="一個白話故事，沒有 jargon" + _PAD_GENERAL + _LZ,
        phase="research",
        audience="general",
        tags=["一般讀者", "K513", "FOMC", "K820", "macro"],
        status="draft",
    )

    feed = json.loads((tmp_path / "reports" / "feed.json").read_text())
    item = next(i for i in feed if i["id"] == pub_id)
    assert "K513" not in item["tags"]
    assert "K820" not in item["tags"]
    assert "FOMC" in item["tags"]
    assert sorted(item["details"]["experiment_refs"]) == ["K513", "K820"]


# ---------------------------------------------------------------------------
# 2026-06-30 (boss): lazypack gate at the Publisher chokepoint
# ---------------------------------------------------------------------------


def _patch_remote(monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)


def test_publish_milestone_blocks_immediate_publish_general_without_lazypack(
    tmp_path: Path, monkeypatch
):
    """2026-07-02 boundary semantics: audience='general' + audit_strict + no
    懶人包圖組 blocks ONLY at the reader-visible boundary (status='published',
    i.e. immediate-publish event/trending paths)."""
    _patch_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    with pytest.raises(ValueError, match="懶人包"):
        pub.publish_milestone(
            title="散戶白話文無懶人包",
            description="一個白話故事，沒有 jargon，但忘了附懶人包圖。" + _PAD_GENERAL,
            phase="research",
            audience="general",
            tags=["一般讀者", "教學"],
            status="published",
        )


def test_publish_milestone_draft_without_lazypack_defers_to_async(
    tmp_path: Path, monkeypatch, capsys
):
    """2026-07-02 async pipeline (error_log 15:15 #4): a general DRAFT may be
    created without the 懶人包圖組 section — the codex render runs on the
    compute_queue lane and the release_pool gate holds the flip to published.
    publish_milestone must pass AND print the enqueue reminder."""
    _patch_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="散戶白話文草稿走 async 懶人包",
        description="一個白話故事，沒有 jargon，懶人包晚點由 compute worker 補。" + _PAD_GENERAL,
        phase="research",
        audience="general",
        tags=["一般讀者", "教學"],
        status="draft",
    )
    assert pub_id.startswith("mile_")
    out = capsys.readouterr().out
    assert "lazypack_async_render.py enqueue" in out


def test_publish_milestone_general_with_lazypack_passes(tmp_path: Path, monkeypatch):
    """audience='general' WITH a 懶人包圖組 → publishes."""
    _patch_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="散戶白話文有懶人包",
        description="一個白話故事，沒有 jargon。" + _PAD_GENERAL + _LZ,
        phase="research",
        audience="general",
        tags=["一般讀者", "教學"],
        status="draft",
    )
    assert pub_id.startswith("mile_")


def test_publish_milestone_audit_strict_false_bypasses_lazypack(tmp_path: Path, monkeypatch):
    """audit_strict=False is the documented escape hatch (batch / non-reader)."""
    _patch_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="批次遷移無懶人包",
        description="一個白話故事，沒有 jargon，批次遷移略過 gate。",
        phase="research",
        audience="general",
        tags=["一般讀者"],
        status="draft",
        audit_strict=False,
    )
    assert pub_id.startswith("mile_")


def test_publish_milestone_daily_audience_exempt_from_lazypack(tmp_path: Path, monkeypatch):
    """Non-general reader audiences (daily) are exempt from the lazypack gate."""
    _patch_remote(monkeypatch)
    pub = Publisher(storage_dir=str(tmp_path))
    pub_id = pub.publish_milestone(
        title="每日建議無懶人包",
        description="今日市場：VIX 16，維持中性配置。",
        phase="research",
        audience="daily",
        tags=["每日建議"],
        status="draft",
    )
    assert pub_id.startswith("mile_")
