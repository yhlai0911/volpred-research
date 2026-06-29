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
