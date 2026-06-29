"""Tests for the publish-time semantic near-dup WARN (boss email-12139).

WARN-ONLY + fail-open: it logs `warn_semantic_dup` to dedup_decisions.jsonl when a
publish is a semantic rehash the keyword gate missed, but NEVER blocks the publish.
"""

from __future__ import annotations

import json
from pathlib import Path

from volpred.publisher.publisher import _semantic_dup_warn


def _decisions(storage: Path) -> list[dict]:
    path = storage / "logs" / "dedup_decisions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_warns_on_semantic_rehash(tmp_path: Path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "logs").mkdir(parents=True)
    item = {"id": "new1", "status": "published", "title": "RECH-X 跨市場實測",
            "description": "深度學習波動率模型 RECH-X"}
    existing = {"id": "old1", "status": "published", "title": "AI 波動率模型 RECH-X 的答案很克制",
                "description": "RECH-X 結論", "published_at": "2026-06-28T00:00:00Z"}
    feed = [item, existing]

    # query (idx 0) ≈ existing (idx 1) → cosine ~1.0 → near-dup.
    monkeypatch.setattr(
        "volpred.ops.topic_similarity.embed_with_cache",
        lambda texts, **k: [[1.0, 0.0]] * len(texts),
    )
    _semantic_dup_warn(str(storage), item, feed)
    decisions = _decisions(storage)
    assert any(d["action"] == "warn_semantic_dup" and d["matched_id"] == "old1" for d in decisions)


def test_no_warn_when_distinct(tmp_path: Path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "logs").mkdir(parents=True)
    item = {"id": "new1", "status": "published", "title": "台股擇時"}
    existing = {"id": "old1", "status": "published", "title": "選擇權定價",
                "published_at": "2026-06-28T00:00:00Z"}
    # query distinct from existing → low cosine.
    monkeypatch.setattr(
        "volpred.ops.topic_similarity.embed_with_cache",
        lambda texts, **k: [[1.0, 0.0], [0.0, 1.0]],
    )
    _semantic_dup_warn(str(storage), item, [item, existing])
    assert _decisions(storage) == []


def test_fail_open_when_embeddings_unavailable(tmp_path: Path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "logs").mkdir(parents=True)
    item = {"id": "new1", "status": "published", "title": "RECH-X"}
    existing = {"id": "old1", "status": "published", "title": "RECH-X 改寫",
                "published_at": "2026-06-28T00:00:00Z"}
    # embeddings down → None → no log, no crash.
    monkeypatch.setattr("volpred.ops.topic_similarity.embed_with_cache", lambda texts, **k: None)
    _semantic_dup_warn(str(storage), item, [item, existing])  # must not raise
    assert _decisions(storage) == []


def test_skips_daily_templated(tmp_path: Path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "logs").mkdir(parents=True)
    item = {"id": "new1", "status": "published", "title": "每日策略建議：VIX 18"}
    called = {"n": 0}

    def spy(texts, **k):
        called["n"] += 1
        return [[1.0]] * len(texts)

    monkeypatch.setattr("volpred.ops.topic_similarity.embed_with_cache", spy)
    _semantic_dup_warn(str(storage), item, [item])
    assert called["n"] == 0  # daily-templated skipped before embedding
    assert _decisions(storage) == []
