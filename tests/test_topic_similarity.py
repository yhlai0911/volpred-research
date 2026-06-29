"""Tests for `volpred.ops.topic_similarity` — semantic topic similarity.

All offline (fake embedder) so they're deterministic + cost-free. The real
embedding path is validated separately via the module against the boss's example.
"""

from __future__ import annotations

from pathlib import Path

from volpred.ops import topic_similarity as ts


def _fake_embedder(vectors_by_text):
    """Build an embedder that returns preset vectors per text."""
    def embed(texts):
        return [vectors_by_text[t] for t in texts]
    return embed


def test_cosine_basic():
    assert ts.cosine([1, 0], [1, 0]) == 1.0
    assert ts.cosine([1, 0], [0, 1]) == 0.0
    assert ts.cosine([1, 0], [0, 0]) == 0.0  # zero vector → 0, no crash
    assert abs(ts.cosine([1, 1], [1, 0]) - 0.7071) < 1e-3


def test_effective_near_dup_threshold_dynamic_ladder():
    """Boss email-12153 directive: threshold relaxes as drought deepens.

    Lower gap → stricter (lower) threshold; longer drought → more permissive
    (higher threshold). None / zero / negative → baseline (no known drought).
    """
    base = ts.DEFAULT_NEAR_DUP_THRESHOLD  # 0.74
    # No drought info → baseline
    assert ts.effective_near_dup_threshold(None) == base
    assert ts.effective_near_dup_threshold(0.0) == base
    assert ts.effective_near_dup_threshold(-1.0) == base
    # Sub-6h: still baseline
    assert ts.effective_near_dup_threshold(2.5) == base
    assert ts.effective_near_dup_threshold(5.9) == base
    # 6–12h: slight relax
    assert ts.effective_near_dup_threshold(6.0) == 0.78
    assert ts.effective_near_dup_threshold(11.9) == 0.78
    # 12–24h: drought territory
    assert ts.effective_near_dup_threshold(12.0) == 0.82
    assert ts.effective_near_dup_threshold(23.9) == 0.82
    # ≥24h: deep drought (caps at 0.86; only near-verbatim triggers)
    assert ts.effective_near_dup_threshold(24.0) == 0.86
    assert ts.effective_near_dup_threshold(72.0) == 0.86
    # Monotone: longer gap never returns a stricter threshold
    prev = base
    for gap in (0.5, 5.0, 6.0, 10.0, 12.0, 20.0, 24.0, 48.0, 100.0):
        thr = ts.effective_near_dup_threshold(gap)
        assert thr >= prev, f"non-monotone at gap={gap}: {thr} < {prev}"
        prev = thr


def test_concentration_detects_semantic_twin(tmp_path: Path):
    # A and A2 are the same topic (identical vectors → cosine 1.0); B is distinct.
    vecs = {
        "波動率對風險值的影響": [1.0, 0.0, 0.0],
        "波動率與 VaR 的關係（換句話說）": [1.0, 0.0, 0.0],  # rehash of A
        "波動率對選擇權定價的影響": [0.0, 1.0, 0.0],  # distinct subtopic
    }
    r = ts.topic_concentration(
        list(vecs.keys()),
        embedder=_fake_embedder(vecs),
        storage_dir=str(tmp_path / "storage"),
    )
    assert r["rehash_count"] == 2  # A and its twin both flagged
    assert any(p["similarity"] >= 0.99 for p in r["near_twin_pairs"])
    # The distinct option-pricing subtopic must NOT be a near-twin of the VaR ones.
    twins_text = " ".join(p["title"] + p["twin"] for p in r["near_twin_pairs"])
    assert "選擇權定價" not in twins_text


def test_concentration_ok_when_all_distinct(tmp_path: Path):
    vecs = {
        "波動率對風險值的影響": [1.0, 0.0, 0.0],
        "波動率對選擇權定價的影響": [0.0, 1.0, 0.0],
        "波動率擇時策略回測": [0.0, 0.0, 1.0],
    }
    r = ts.topic_concentration(
        list(vecs.keys()),
        embedder=_fake_embedder(vecs),
        storage_dir=str(tmp_path / "storage"),
    )
    assert r["status"] == "ok"
    assert r["rehash_count"] == 0


def test_near_duplicates_finds_semantic_match(tmp_path: Path):
    vecs = {
        "VIX 期限結構能不能預測回檔": [1.0, 0.0],
        "用 VIX term structure 預測股市修正": [0.98, 0.199],  # paraphrase
        "台股波動率擇時": [0.0, 1.0],  # unrelated
    }
    r = ts.near_duplicates(
        "VIX 期限結構能不能預測回檔",
        ["用 VIX term structure 預測股市修正", "台股波動率擇時"],
        embedder=_fake_embedder(vecs),
        storage_dir=str(tmp_path / "storage"),
    )
    assert r["status"] == "duplicate"
    assert r["matches"][0]["candidate"] == "用 VIX term structure 預測股市修正"


def test_fail_open_when_embedder_raises(tmp_path: Path):
    def boom(texts):
        raise RuntimeError("no API key")

    r = ts.topic_concentration(
        ["a topic", "another topic"],
        embedder=boom,
        storage_dir=str(tmp_path / "storage"),
    )
    assert r["status"] == "semantic_unavailable"  # never raises


def test_article_topic_text_combines_whole_topic():
    item = {
        "title": "VIX 自己的波動率能不能預測 VIX",
        "description": "用自製 vol-of-vol 訊號預測明天 VIX",
        "details": {"conclusion": "贏 AR(1) 但過不了多重檢定", "other": "ignored"},
    }
    text = ts.article_topic_text(item)
    assert "VIX 自己的波動率" in text
    assert "vol-of-vol" in text
    assert "多重檢定" in text  # conclusion folded in (whole topic, not just title)
    # missing fields don't crash:
    assert ts.article_topic_text({"title": "只有標題"}) == "只有標題"
    assert ts.article_topic_text({}) == ""


def test_semantic_concentration_report_reads_feed(tmp_path: Path):
    import json as _json

    storage = tmp_path / "storage"
    (storage / "reports").mkdir(parents=True)
    feed = [
        {"id": "a", "status": "published", "title": "VIX 期限結構預測回檔",
         "description": "用 term structure 訊號", "published_at": "2026-06-29T03:00:00Z"},
        {"id": "b", "status": "published", "title": "VIX term structure 預測股市修正",
         "description": "同一套訊號改寫", "published_at": "2026-06-29T02:00:00Z"},
        {"id": "c", "status": "published", "title": "台股波動率擇時回測",
         "description": "完全不同", "published_at": "2026-06-29T01:00:00Z"},
        {"id": "d", "status": "draft", "title": "草稿不算", "published_at": "2026-06-29T00:00:00Z"},
    ]
    (storage / "reports" / "feed.json").write_text(_json.dumps(feed, ensure_ascii=False), encoding="utf-8")

    # Fake embedder: a≈b (rehash), c distinct. Keyed by whole-topic text.
    def embed(texts):
        out = []
        for t in texts:
            if "term structure" in t or "期限結構" in t:
                out.append([1.0, 0.0, 0.0])
            else:
                out.append([0.0, 1.0, 0.0])
        return out

    r = ts.semantic_concentration_report(str(storage), embedder=embed, use_cache=False)
    assert r["sample"] == 3  # draft excluded
    assert r["basis"] == "whole_topic_semantic"
    assert r["rehash_count"] == 2  # a and b are semantic twins


def test_cache_avoids_reembedding(tmp_path: Path):
    calls = {"n": 0}

    def counting_embed(texts):
        calls["n"] += len(texts)
        return [[1.0, 0.0] for _ in texts]

    storage = str(tmp_path / "storage")
    ts.embed_with_cache(["x", "y"], embedder=counting_embed, storage_dir=storage)
    assert calls["n"] == 2
    # second call: same texts → served from disk cache, no new embeds
    ts.embed_with_cache(["x", "y"], embedder=counting_embed, storage_dir=storage)
    assert calls["n"] == 2
