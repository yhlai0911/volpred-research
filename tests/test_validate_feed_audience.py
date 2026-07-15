from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_feed_audience.py"
    spec = importlib.util.spec_from_file_location("validate_feed_audience", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(**overrides):
    row = {
        "id": "mile_test",
        "title": "給一般讀者的市場風險說明",
        "content": "用白話說明市場風險。",
        "description": "",
        "audience": "general",
        "category": "general",
        "status": "published",
        "tags": ["一般讀者", "風險管理"],
        "details": {},
    }
    row.update(overrides)
    return row


def test_visible_academic_signals_match_publisher_research_inference() -> None:
    mod = _load_module()
    mismatch, labels = mod.check_entry(
        _entry(content="比較 QLIKE 後再用 GARCH 估計。")
    )
    assert mismatch is True
    assert labels == ["QLIKE", "GARCH"]


def test_title_k_id_rule_is_not_lost_when_it_is_the_only_signal() -> None:
    mod = _load_module()
    row = _entry(title="K184 的市場風險邊界")
    assert mod.infer_entry_audience(row) == "research"
    assert mod.check_entry(row) == (True, ["K-id"])


def test_tags_participate_in_the_same_inference_as_publisher() -> None:
    mod = _load_module()
    row = _entry(content="本文比較 QLIKE。", tags=["一般讀者", "VaR"])
    mismatch, labels = mod.check_entry(row)
    assert mismatch is True
    assert labels == ["QLIKE", "VaR"]


def test_daily_digest_type_lock_allows_academic_archive_references() -> None:
    mod = _load_module()
    row = _entry(
        content="串起 K123、QLIKE、GARCH、bootstrap 與 Sharpe 的舊文。",
        details={"content_type": "daily_digest"},
    )
    assert mod.infer_entry_audience(row) == "general"
    assert mod.check_entry(row) == (False, [])


def test_daily_update_metadata_is_reported_as_daily_not_research() -> None:
    mod = _load_module()
    row = _entry(
        content="每日模板包含 GARCH、VaR 與 Sharpe。",
        tags=["每日建議", "VIX"],
        details={"content_type": "daily_update"},
    )
    assert mod.infer_entry_audience(row) == "daily"
    mismatch, labels = mod.check_entry(row)
    assert mismatch is True
    assert {"GARCH", "VaR", "Sharpe"}.issubset(labels)


def test_member_qa_is_reported_as_type_metadata_drift_not_research() -> None:
    mod = _load_module()
    row = _entry(
        content="回答 K1466，並說明 bootstrap 與 GARCH。",
        details={"content_type": "member_qa"},
    )
    assert mod.infer_entry_audience(row) == "member_qa"
    mismatch, labels = mod.check_entry(row)
    assert mismatch is True
    assert "K-id" in labels


def test_event_article_is_reported_as_type_metadata_drift_not_research() -> None:
    mod = _load_module()
    row = _entry(
        content="K129 事件的 bootstrap 與 GARCH 追蹤。",
        details={"content_type": "event_article"},
    )
    assert mod.infer_entry_audience(row) == "event"
    mismatch, labels = mod.check_entry(row)
    assert mismatch is True
    assert "K-id" in labels


def test_markdown_image_url_does_not_create_a_second_academic_signal() -> None:
    mod = _load_module()
    row = _entry(
        content=(
            "正文只提一次 QLIKE。\n\n"
            "![比較圖](https://example.test/charts/k1685_qlike_oos.png)"
        )
    )
    assert mod.infer_entry_audience(row) == "general"
    assert mod.check_entry(row) == (False, [])


def test_non_visible_general_rows_are_outside_reader_facing_invariant() -> None:
    mod = _load_module()
    assert mod.check_entry(
        _entry(status="archived", content="K123 QLIKE GARCH")
    ) == (False, [])


def test_main_is_fail_closed_for_missing_malformed_and_wrong_shape(tmp_path: Path) -> None:
    mod = _load_module()
    missing = tmp_path / "missing.json"
    assert mod.main(str(missing)) == 1

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert mod.main(str(malformed)) == 1

    wrong_shape = tmp_path / "wrong-shape.json"
    wrong_shape.write_text("{}", encoding="utf-8")
    assert mod.main(str(wrong_shape)) == 1


def test_main_passes_clean_feed_and_fails_mismatch(tmp_path: Path) -> None:
    mod = _load_module()
    path = tmp_path / "feed.json"
    path.write_text(json.dumps([_entry()]), encoding="utf-8")
    assert mod.main(str(path)) == 0

    path.write_text(
        json.dumps([_entry(content="QLIKE 與 GARCH")]),
        encoding="utf-8",
    )
    assert mod.main(str(path)) == 1
