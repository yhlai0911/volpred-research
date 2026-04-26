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
    assert "禁用統計術語" in issues[0]


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


def test_publish_milestone_strict_blocks_general_with_research_jargon(
    tmp_path: Path, monkeypatch
):
    """Integration: publish_milestone with audit_strict=True (default) raises
    ValueError on a general-audience article containing forbidden terms."""
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    # Stub out supabase + email side effects
    import volpred.publisher.publisher as mod
    monkeypatch.setattr(mod, "__name__", mod.__name__)

    pub = Publisher(storage_dir=str(tmp_path))

    # Stub external calls that would fire on publish path
    def _no_op_sync(item, **kwargs):
        return True
    monkeypatch.setattr("scripts.supabase_sync.sync_article", _no_op_sync, raising=False)

    polluted_content = "FOMC 會議前 t=4.38, Harvey |t|>3, DM test p=0.04."

    with pytest.raises(ValueError, match="general"):
        pub.publish_milestone(
            title="一般讀者測試標題",
            description=polluted_content,
            phase="research",
            audience="general",
            tags=["一般讀者", "FOMC"],
            status="draft",
        )


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
        description="一個白話故事，沒有 jargon",
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
