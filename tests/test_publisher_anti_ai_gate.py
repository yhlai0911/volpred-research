from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import volpred.publisher.publisher as publisher_module
from volpred.ops.content import release_pool_articles
from volpred.publisher.publisher import Publisher


def _init_storage(storage: Path, feed: list[dict] | None = None) -> None:
    (storage / "reports").mkdir(parents=True, exist_ok=True)
    (storage / "logs").mkdir(parents=True, exist_ok=True)
    (storage / "reports" / "feed.json").write_text(
        json.dumps(feed or [], ensure_ascii=False),
        encoding="utf-8",
    )


def _feed(storage: Path) -> list[dict]:
    return json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))


def _decisions(storage: Path) -> list[dict]:
    path = storage / "logs" / "dedup_decisions.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _bad_item(pub_id: str = "mile_ai_bad") -> dict:
    return {
        "id": pub_id,
        "title": "AI 味測試文章",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "details": {"content_type": "research_article"},
        "tags": ["研究"],
        "content": "朋友問我，這個策略是不是一定能避開崩盤。\n\n答案要用回測檢查。",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def test_anti_ai_gate_warn_only_logs_but_allows_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "storage"
    _init_storage(storage)
    monkeypatch.setenv("VOLPRED_ANTI_AI_GATE_MODE", "warn")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    result = Publisher(storage_dir=str(storage))._append_to_feed(_bad_item())

    assert result == "mile_ai_bad"
    assert [item["id"] for item in _feed(storage)] == ["mile_ai_bad"]
    decision = next(d for d in _decisions(storage) if d.get("gate") == "anti_ai_style")
    assert decision["decision"] == "warn"
    assert "WARN-ONLY migration" in decision["reason"]
    assert decision["strict_after"] == "2026-07-13"


def test_anti_ai_gate_strict_blocks_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "storage"
    _init_storage(storage)
    monkeypatch.setenv("VOLPRED_ANTI_AI_GATE_MODE", "strict")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    with pytest.raises(ValueError, match="anti_ai_style publish gate failed"):
        Publisher(storage_dir=str(storage))._append_to_feed(_bad_item())

    assert _feed(storage) == []
    decision = next(d for d in _decisions(storage) if d.get("gate") == "anti_ai_style")
    assert decision["decision"] == "block"
    assert any("[MUST]" in failure for failure in decision["failures"])


def test_anti_ai_gate_fails_open_when_block_receipt_is_not_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "storage"
    _init_storage(storage)
    monkeypatch.setenv("VOLPRED_ANTI_AI_GATE_MODE", "strict")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)
    monkeypatch.setattr(
        publisher_module,
        "_log_anti_ai_gate_decision_impl",
        lambda *_args, **_kwargs: False,
    )

    result = Publisher(storage_dir=str(storage))._append_to_feed(_bad_item())

    assert result == "mile_ai_bad"
    assert [item["id"] for item in _feed(storage)] == ["mile_ai_bad"]


def test_anti_ai_gate_checker_exception_fail_open_with_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "storage"
    _init_storage(storage)
    monkeypatch.setenv("VOLPRED_ANTI_AI_GATE_MODE", "strict")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    def broken_check(text: str, *, fb_mode: bool) -> tuple[bool, list[str]]:
        raise RuntimeError("checker unavailable")

    alerts: list[dict] = []

    def fake_send_alert(**kwargs):
        alerts.append(kwargs)
        return {"sent": False}

    monkeypatch.setattr(publisher_module, "_run_anti_ai_checks", broken_check)
    monkeypatch.setattr("volpred.ops.alerts.send_alert", fake_send_alert)

    result = Publisher(storage_dir=str(storage))._append_to_feed(_bad_item())

    assert result == "mile_ai_bad"
    assert [item["id"] for item in _feed(storage)] == ["mile_ai_bad"]
    decision = next(d for d in _decisions(storage) if d.get("gate") == "anti_ai_style")
    assert decision["decision"] == "pass"
    assert "gate_error_fail_open" in decision["reason"]
    assert alerts and alerts[0]["level"] == "warn"


def test_release_pool_strict_uses_anti_ai_gate_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = tmp_path / "storage"
    draft = _bad_item("mile_release_ai_bad")
    draft["status"] = "draft"
    draft["created_at"] = "2026-07-01T00:00:00+00:00"
    draft["published_at"] = "2026-07-01T00:00:00+00:00"
    _init_storage(storage, [draft])
    monkeypatch.setenv("VOLPRED_ANTI_AI_GATE_MODE", "strict")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    result = release_pool_articles(
        pub_id="mile_release_ai_bad",
        include_drafts=True,
        due_only=False,
        storage_dir=str(storage),
    )

    assert result["released_count"] == 0
    assert result["audit_skipped"][0]["id"] == "mile_release_ai_bad"
    assert "anti_ai_style publish gate failed" in result["audit_skipped"][0]["issues"][0]
    assert _feed(storage)[0]["status"] == "draft"
    decision = next(d for d in _decisions(storage) if d.get("gate") == "anti_ai_style")
    assert decision["decision"] == "block"


def test_fb_mode_never_applies_to_feed_items():
    """2026-07-16 regression: FB caption layout checks (short paragraph /
    list structure) must not run on feed articles. A digest whose spec
    requires a curated link list was blocked at 3 cumulative WARNs once the
    gate turned strict; feed text always audits with fb_mode=False."""
    from volpred.publisher.publisher import _anti_ai_fb_mode

    for item in (
        {"audience": "general", "details": {"content_type": "daily_digest"}},
        {"audience": "event", "details": {"content_type": "event_article"}},
        {"audience": "general", "details": {"content_type": "trending_repost"}},
        {"audience": "research", "details": {}},
    ):
        assert _anti_ai_fb_mode(item) is False
