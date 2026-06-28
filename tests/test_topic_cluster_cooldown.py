from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from volpred.publisher.publisher import Publisher
from volpred import topic_clusters


def test_classify_topic_cluster_detects_vix_title():
    cluster = topic_clusters.classify_topic_cluster(
        "VIX 當日反應是抽籤，term structure 才是訊號",
        ["一般讀者", "macro"],
        "",
    )
    assert cluster == "vix"


def test_publish_milestone_blocks_over_cap_cluster(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    monkeypatch.setattr(
        "volpred.publisher.publisher.cluster_gate_status",
        lambda cluster: {
            "cluster": cluster,
            "count": 15,
            "cap": 15,
            "total": 40,
            "ratio": 0.375,
            "blocked": True,
            "dominant_ratio_breached": True,
        },
    )

    pub = Publisher(storage_dir=str(tmp_path))
    with pytest.raises(ValueError, match="topic_cluster_cooldown_blocked"):
        pub.publish_milestone(
            title="VIX 又來了：市場恐慌數字背後的交易心理",
            description="白話解釋 VIX 為什麼又變熱門。",
            phase="research",
            audience="general",
            tags=["一般讀者", "VIX"],
            status="draft",
        )


def test_cluster_cooldown_type_exempt_covers_trending_repost_content_type():
    """2026-06-28 regression: a trending_repost declared by content_type (not via a
    magic 'trending_repost' tag or 'trending_' phase) must be exempt. K1557
    (content_type=trending_repost, tags=台股/波動率, phase=research) was wrongly
    cluster-blocked before the fix, which only matched content_type=='daily_digest'."""
    from volpred.publisher.publisher import cluster_cooldown_type_exempt

    # K1557 case → exempt by content_type alone
    assert cluster_cooldown_type_exempt(
        "general", None, "trending_repost", ["台股", "波動率", "回測"], "research"
    ) is True
    # every timely content_type → exempt
    for ct in ("event_article", "member_qa", "daily_digest", "daily_update"):
        assert cluster_cooldown_type_exempt("general", None, ct, [], "research") is True
    # plain general / research (no timely type) → still cluster-gated
    assert cluster_cooldown_type_exempt(
        "general", None, None, ["台股", "VIX"], "research"
    ) is False
    assert cluster_cooldown_type_exempt("research", None, "", [], "research") is False
    # legacy tag / phase fallbacks still exempt older callers
    assert cluster_cooldown_type_exempt(
        "general", None, None, ["trending_repost"], "research"
    ) is True
    assert cluster_cooldown_type_exempt("general", None, None, [], "trending_2026") is True


def test_build_publication_candidates_applies_cluster_penalty(tmp_path: Path, monkeypatch):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_publication_candidates.py"
    spec = importlib.util.spec_from_file_location("build_publication_candidates", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    knowledge_path = tmp_path / "knowledge.json"
    feed_path = tmp_path / "feed.json"
    output_path = tmp_path / "publication_candidates.json"
    exp_dir = tmp_path / "experiments" / "k2000"
    exp_dir.mkdir(parents=True)
    (exp_dir / "k2000_results.json").write_text("{}", encoding="utf-8")

    knowledge_path.write_text(
        json.dumps(
            [
                {
                    "experiment_id": "K2000",
                    "title": "VIX cross-market lesson",
                    "content": "PASS robust VIX methodology warning",
                    "updated_at": "2026-05-27T00:00:00+00:00",
                    "tags": ["VIX"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    feed_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "KNOWLEDGE_PATH", knowledge_path)
    monkeypatch.setattr(mod, "FEED_PATH", feed_path)
    monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(
        mod,
        "cluster_gate_status",
        lambda cluster: {
            "cluster": cluster,
            "count": 20,
            "cap": 15,
            "total": 60,
            "ratio": 0.3333,
            "blocked": True,
            "dominant_ratio_breached": True,
        },
    )

    mod.main()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    candidate = payload["candidates"][0]
    assert candidate["topic_cluster"] == "vix"
    assert candidate["base_score"] > candidate["score"]
    assert any("cluster cooldown penalty" in reason for reason in candidate["reasons"])
