"""Tests for topic-cluster cooldown gate in publish_milestone.

Covers:
- type-locked exemption (daily / member_qa / event / trending_repost not blocked)
- title-only classification (boilerplate VIX/GARCH in description doesn't count)
- general/research over-cap → raise ValueError
- explicit cluster_waiver bypasses gate
"""
from __future__ import annotations
import json
import pytest
import sys
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.publisher.publisher import Publisher
from volpred.topic_clusters import classify_topic_cluster, cluster_gate_status


@pytest.fixture
def pub(tmp_path, monkeypatch):
    monkeypatch.setenv("VOLPRED_ACTOR", "claude")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda self, *a, **kw: None, raising=False)
    from volpred.publisher.email_notifier import EmailNotifier
    from volpred.publisher import live_verify

    monkeypatch.setattr(EmailNotifier, "notify_article_published", lambda *a, **kw: None)
    monkeypatch.setattr(live_verify, "verify_article_live", lambda *a, **kw: True)
    monkeypatch.setattr(live_verify, "stamp_verified", lambda *a, **kw: None)
    monkeypatch.setattr(live_verify, "emit_verify_alert", lambda *a, **kw: None)
    # 2026-07-04: stub the 2026-06-30 pre-publish burst throttle — this file's
    # tests publish several articles milliseconds apart, which the rhythm gate
    # reads as a <30min burst. Cluster gating is what's under test, not the
    # throttle (that has its own test file).
    import volpred.publisher.throttle as _throttle
    monkeypatch.setattr(_throttle, "check_publish_throttle", lambda *a, **kw: None, raising=False)
    for mod_name in ("supabase_sync", "scripts.supabase_sync"):
        try:
            mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
            if hasattr(mod, "sync_article"):
                monkeypatch.setattr(mod, "sync_article", lambda *a, **kw: True, raising=False)
            if hasattr(mod, "_post"):
                monkeypatch.setattr(mod, "_post", lambda *a, **kw: False, raising=False)
        except (ImportError, ModuleNotFoundError):
            pass
    # Redirect cluster gate to tmp feed. 2026-06-29: the FEED_PATH monkeypatch
    # alone was ineffective because cluster_gate_status / recent_cluster_counts
    # capture the original FEED_PATH as a default arg at import time. Tests
    # previously "passed" only because the type-locked bypass was unconditional
    # and the count value didn't matter. The new soft cap (hard×2.5) actually
    # reads counts, so we monkeypatch publisher.cluster_gate_status to read
    # from the temp feed explicitly.
    import volpred.topic_clusters as tc
    temp_feed = tmp_path / "reports" / "feed.json"
    monkeypatch.setattr(tc, "FEED_PATH", temp_feed, raising=False)

    def _temp_cluster_gate_status(cluster):
        counts, total = tc.recent_cluster_counts(days=30, feed_path=temp_feed)
        count = counts.get(cluster or "", 0) if cluster else 0
        cap = tc.cluster_cap(cluster)
        soft_cap = int(cap * tc.SOFT_CAP_MULTIPLIER)
        ratio = (count / total) if total else 0.0
        return {
            "cluster": cluster,
            "count": count,
            "cap": cap,
            "soft_cap": soft_cap,
            "soft_cap_multiplier": tc.SOFT_CAP_MULTIPLIER,
            "total": total,
            "ratio": ratio,
            "blocked": bool(cluster and count >= cap),
            "soft_blocked": bool(cluster and count >= soft_cap),
            "dominant_ratio_breached": bool(cluster and ratio > tc.DOMINANT_RATIO_LIMIT),
        }

    monkeypatch.setattr(
        "volpred.publisher.publisher.cluster_gate_status",
        _temp_cluster_gate_status,
    )
    return Publisher(storage_dir=str(tmp_path))


def _saturate_cluster(pub, cluster_keyword: str, n: int):
    """Publish n articles with cluster_keyword in title (general audience) to saturate cluster."""
    for i in range(n):
        pub.publish_milestone(
            title=f"{cluster_keyword} 散戶導讀 {i}",
            description=f"純散戶解說 {i}。",
            phase="general",
            audience="general",
            tags=[cluster_keyword, "一般讀者"],
            status="published",
            details={"cluster_waiver": "test_saturation"},
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )


class TestClusterClassification:
    def test_title_only_classification_no_content_scan(self):
        """boilerplate mention in content/description must NOT count."""
        cluster = classify_topic_cluster(
            "定期定額的秘密",  # title — no cluster keyword
            ["一般讀者", "定期定額"],
            "市場快照: VIX 17.01, GARCH 11.3%, SPY $750",  # boilerplate VIX/GARCH/SPY in body
        )
        assert cluster is None, f"content scan leaked — got {cluster}"

    def test_title_with_vix_classified(self):
        assert classify_topic_cluster("VIX 期限結構分析", [], "") == "vix"

    def test_tag_with_garch_classified(self):
        assert classify_topic_cluster("某文章", ["GARCH", "VolatilityModel"], "") == "garch"

    def test_factor_etf_classified_before_spy_cluster(self):
        cluster = classify_topic_cluster(
            "美股 ETF 低波動配置還有用嗎",
            ["USMV", "一般讀者"],
            "",
        )
        assert cluster == "factor_etf"

    def test_short_ascii_keyword_no_substring_false_match(self):
        """2026-07-04 regression: short ASCII keywords must match as whole
        tokens, not substrings — "es" (Expected Shortfall) inside "timestamp"
        and "var" (VaR) inside "variance" silently mis-routed articles to
        risk_mgmt, corrupting cluster counts / caps / dedup."""
        # "variance" is a volatility term — must NOT hit VaR→risk_mgmt.
        assert classify_topic_cluster("SPY variance forecast", [], "") == "spy"
        # "timestamp"/"series" must not hit ES→risk_mgmt.
        assert classify_topic_cluster("SPY normal timestamp", [], "") == "spy"
        assert classify_topic_cluster("美股 series 回顧", [], "") is None
        # But the real keywords still classify, and CJK-adjacent still matches.
        assert classify_topic_cluster("VaR 回測", [], "") == "risk_mgmt"
        assert classify_topic_cluster("VIX期限結構", [], "") == "vix"


class TestTypeLockedExemption:
    """daily / member_qa / event / trending_repost must bypass cluster cap
    — they are topic-bound by definition; cap would break their core function."""

    def test_daily_strategy_with_vix_in_title_not_blocked(self, pub):
        # Saturate VIX cluster first
        _saturate_cluster(pub, "VIX", 16)  # over cap=15
        # Now publish daily strategy with VIX in title — must NOT raise
        pub_id = pub.publish_milestone(
            title="每日策略建議：VIX 17.01（正常）— 2026-05-27",
            description="boilerplate VIX/GARCH/SPY",
            phase="daily_recommendation",
            audience="daily",
            category="general",
            tags=["每日建議", "VIX", "策略配置"],
            status="published",
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")

    def test_member_qa_not_blocked_by_cluster(self, pub):
        _saturate_cluster(pub, "SPY", 12)
        pub_id = pub.publish_milestone(
            title="會員提問：SPY 走勢預測",
            description="回應會員 SPY 問題",
            phase="member_qa_response",
            audience="member_qa",
            tags=["會員提問", "SPY"],
            status="published",
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")

    def test_event_article_not_blocked(self, pub):
        _saturate_cluster(pub, "VIX", 16)
        pub_id = pub.publish_milestone(
            title="FOMC 前 VIX 走勢預覽",
            description="event-driven analysis",
            phase="event_article_preview",
            audience="event",
            category="event_article",
            tags=["event_article", "VIX", "FOMC"],
            status="published",
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")

    def test_trending_repost_not_blocked(self, pub):
        _saturate_cluster(pub, "VIX", 16)
        pub_id = pub.publish_milestone(
            title="VIX spike 評論 — havingchien 風格改寫",
            description="trending commentary",
            phase="trending_repost_2026_05_27",
            audience="general",
            tags=["trending_repost", "VIX"],
            status="published",
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")


class TestClusterCapEnforcement:
    """general/research must be blocked when over cap."""

    def test_general_article_blocked_when_vix_cluster_saturated(self, pub, monkeypatch):
        # 2026-07-04: vix's production hard cap was raised 15→80 ("vol is core
        # for a vol platform", topic_clusters.py). Saturating to 81 would be
        # slow and brittle; the gate SEMANTICS (general blocked at count>=cap)
        # are what this test asserts, so pin a small deterministic cap and
        # saturate just past it. _temp_cluster_gate_status reads tc.cluster_cap.
        import volpred.topic_clusters as tc
        monkeypatch.setattr(tc, "cluster_cap", lambda c: 3)
        _saturate_cluster(pub, "VIX", 4)  # over pinned cap=3
        with pytest.raises(ValueError, match="topic_cluster_cooldown_blocked"):
            pub.publish_milestone(
                title="VIX 散戶新解",
                description="散戶散戶散戶",
                phase="general",
                audience="general",
                tags=["VIX", "一般讀者"],
                status="published",
                audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
            )

    def test_explicit_cluster_waiver_allows_publish(self, pub):
        _saturate_cluster(pub, "VIX", 16)
        pub_id = pub.publish_milestone(
            title="VIX 罕見破紀錄行情",
            description="散戶散戶",
            phase="general",
            audience="general",
            tags=["VIX", "一般讀者"],
            status="published",
            details={"cluster_waiver": "rare market event — manual override"},
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")

    def test_uncluster_topic_unaffected(self, pub):
        _saturate_cluster(pub, "VIX", 16)
        # 'bond' is not in any cluster — should publish freely
        pub_id = pub.publish_milestone(
            title="美債收益率深度分析",
            description="bond bond bond",
            phase="general",
            audience="general",
            tags=["債券", "一般讀者"],
            status="published",
            audit_strict=False,  # depth gate covered by test_content_depth_gate.py; this file tests cluster gating
        )
        assert pub_id.startswith("mile_")


def _days_ago_iso(days: int) -> str:
    """recent_cluster_counts() cuts off at now - `days`, so fixtures must be
    relative. Hard-coded dates silently age out of the window and turn a real
    assertion into a time bomb (2026-07-10: this file's 06-10 fixture did)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_recent_cluster_counts_split_factor_etf_from_spy(tmp_path):
    feed_path = tmp_path / "feed.json"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "title": "SPY 估值觀察",
                    "tags": ["SPY"],
                    "status": "published",
                    "published_at": _days_ago_iso(2),
                },
                {
                    "title": "USMV 的低波動配置",
                    "tags": ["USMV", "美股 ETF"],
                    "status": "published",
                    "published_at": _days_ago_iso(1),
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import volpred.topic_clusters as tc

    counts, total = tc.recent_cluster_counts(days=30, feed_path=feed_path)
    assert total == 2
    assert counts["spy"] == 1
    assert counts["factor_etf"] == 1


def test_recent_cluster_counts_warns_on_bad_timestamp(tmp_path, capsys):
    feed_path = tmp_path / "feed.json"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "bad_ts",
                    "title": "VIX 壞時間戳",
                    "tags": ["VIX"],
                    "status": "published",
                    "published_at": "not-a-date",
                },
                {
                    "id": "good_ts",
                    "title": "SPY 正常時間戳",
                    "tags": ["SPY"],
                    "status": "published",
                    "published_at": _days_ago_iso(1),
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import volpred.topic_clusters as tc

    counts, total = tc.recent_cluster_counts(days=30, feed_path=feed_path)

    assert total == 1
    assert counts["vix"] == 0
    assert counts["spy"] == 1
    captured = capsys.readouterr()
    assert "[topic_clusters] WARN feed timestamp parse failed; skipping item" in captured.err
    assert "bad_ts" in captured.err
    assert "not-a-date" in captured.err
