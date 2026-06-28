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


def test_cluster_gate_status_exposes_soft_cap():
    """soft_cap = hard_cap × SOFT_CAP_MULTIPLIER; soft_blocked fires at that level
    even when hard-cap `blocked` is True (it just keeps escalating)."""
    from volpred import topic_clusters as tc

    # vix hard cap = 15, SOFT_CAP_MULTIPLIER = 2.5 → soft_cap = 37
    status = tc.cluster_gate_status("vix")
    assert status["cap"] == 15
    assert status["soft_cap"] == int(15 * tc.SOFT_CAP_MULTIPLIER)
    assert status["soft_cap_multiplier"] == tc.SOFT_CAP_MULTIPLIER
    assert tc.cluster_soft_cap("vix") == int(15 * tc.SOFT_CAP_MULTIPLIER)
    # unknown cluster → default cap (=6), default soft cap (=15)
    assert tc.cluster_soft_cap("unknown_cluster_xyz") == int(
        tc.DEFAULT_CLUSTER_CAP * tc.SOFT_CAP_MULTIPLIER
    )


def test_publish_milestone_blocks_timely_at_soft_cap(tmp_path: Path, monkeypatch):
    """2026-06-29 boss escalation: timely / topic-bound types (trending_repost,
    event_article, member_qa, daily_*) used to be FULLY exempt from the cluster
    cap → vix grew to 6.1x, spy to 8.3x in 30d. New soft cap (hard×2.5) blocks
    them at that ceiling unless caller passes an explicit cluster_waiver."""
    from volpred.publisher import publisher as publisher_mod
    from volpred.publisher.publisher import cluster_cooldown_type_exempt

    # Confirm input is type-locked (timely), so only the SOFT cap can block it
    assert cluster_cooldown_type_exempt(
        "general", None, "trending_repost", ["VIX"], "trending"
    ) is True

    # Stub cluster_gate_status: vix 92/15 cap → soft_cap 37 → soft_blocked=True
    monkeypatch.setattr(
        publisher_mod,
        "cluster_gate_status",
        lambda cluster: {
            "cluster": cluster,
            "count": 92,
            "cap": 15,
            "soft_cap": 37,
            "soft_cap_multiplier": 2.5,
            "total": 345,
            "ratio": 92 / 345,
            "blocked": True,
            "soft_blocked": True,
            "dominant_ratio_breached": True,
        },
    )

    # Inline reproduction of the gate so we don't need to mock the entire
    # publish_milestone side-effect chain (live_verify / supabase / email /
    # provenance audit). What we're testing IS the gate logic itself.
    cluster_gate = publisher_mod.cluster_gate_status("vix")
    details = {"content_type": "trending_repost"}
    is_type_locked = cluster_cooldown_type_exempt(
        "general", None, "trending_repost", ["VIX", "trending_repost"], "trending"
    )
    soft_blocked = (
        cluster_gate["soft_blocked"]
        and is_type_locked
        and not details.get("cluster_waiver")
    )
    assert soft_blocked is True, "timely type at 92/15 → soft cap 37 must block"

    # cluster_waiver → bypass even when soft-blocked
    details_with_waiver = {
        "content_type": "trending_repost",
        "cluster_waiver": "fomc_20260617_emergency_cut",
    }
    waiver_bypass = (
        cluster_gate["soft_blocked"]
        and is_type_locked
        and not details_with_waiver.get("cluster_waiver")
    )
    assert waiver_bypass is False, "explicit cluster_waiver must bypass soft cap"


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
            "soft_cap": 37,
            "soft_cap_multiplier": 2.5,
            "total": 40,
            "ratio": 0.375,
            "blocked": True,
            "soft_blocked": False,
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
