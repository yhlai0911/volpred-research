"""Tests for in-place published-article corrections.

The property under test is fail-loud: a correction that does not apply must
raise rather than quietly stamping an errata over an unchanged article.
"""

from __future__ import annotations

import json

import pytest

from volpred.publisher.article_correction import (
    CorrectionNotApplied,
    apply_article_correction,
)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    feed = [
        {
            "id": "mile_test",
            "status": "published",
            "published_at": "2026-07-01T17:24:08+00:00",
            "content": "近 20 日波動 18.1%，近 5 日 14.0%。事件在 7/2。",
            "details": {"event": "NFP_US_2026_07_03", "as_of": "2026-07-01 close"},
        },
        {"id": "mile_other", "status": "published", "content": "unrelated"},
    ]
    (reports / "feed.json").write_text(
        json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(
        "volpred.canonical_write.guard_canonical_write", lambda *_a, **_kw: None
    )
    return tmp_path


def _feed(storage):
    return json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))


def _article(storage, aid="mile_test"):
    return next(a for a in _feed(storage) if a["id"] == aid)


def test_corrects_body_and_details_and_stamps_errata(storage):
    report = apply_article_correction(
        "mile_test",
        content_replacements=[("18.1%", "18.28%"), ("14.0%", "14.41%")],
        details_patch={"event": "NFP_US_2026_07_02", "as_of": "2026-07-02 close"},
        summary="official calendar correction",
        storage_dir=storage,
        sync=False,
    )

    art = _article(storage)
    assert "18.28%" in art["content"] and "14.41%" in art["content"]
    assert "18.1%" not in art["content"]
    assert art["details"]["event"] == "NFP_US_2026_07_02"
    assert art["errata"]["update_summary"] == "official calendar correction"
    assert len(art["errata"]["update_history"]) == 1
    assert report["details_changes"]["event"]["from"] == "NFP_US_2026_07_03"


def test_published_at_is_not_touched(storage):
    """A correction must not reorder the feed."""
    before = _article(storage)["published_at"]
    apply_article_correction(
        "mile_test",
        content_replacements=[("18.1%", "18.28%")],
        summary="s",
        storage_dir=storage,
        sync=False,
    )
    art = _article(storage)
    assert art["published_at"] == before
    assert art["last_updated_at"] != before


def test_missing_substring_raises_and_writes_nothing(storage):
    original = _feed(storage)
    with pytest.raises(CorrectionNotApplied, match="matched 0 times"):
        apply_article_correction(
            "mile_test",
            content_replacements=[("nonexistent number", "x")],
            summary="s",
            storage_dir=storage,
            sync=False,
        )
    assert _feed(storage) == original


def test_ambiguous_substring_raises_and_writes_nothing(storage):
    original = _feed(storage)
    with pytest.raises(CorrectionNotApplied, match="matched 2 times"):
        apply_article_correction(
            "mile_test",
            content_replacements=[("日", "x")],  # occurs twice
            summary="s",
            storage_dir=storage,
            sync=False,
        )
    assert _feed(storage) == original


def test_partially_valid_batch_is_all_or_nothing(storage):
    """The good replacement must not land when a later one is unmatched."""
    with pytest.raises(CorrectionNotApplied):
        apply_article_correction(
            "mile_test",
            content_replacements=[("18.1%", "18.28%"), ("missing", "x")],
            summary="s",
            storage_dir=storage,
            sync=False,
        )
    assert "18.1%" in _article(storage)["content"]
    assert "errata" not in _article(storage)


def test_noop_correction_refuses_to_stamp_errata(storage):
    with pytest.raises(CorrectionNotApplied, match="no-op"):
        apply_article_correction(
            "mile_test",
            details_patch={"event": "NFP_US_2026_07_03"},  # already this value
            summary="s",
            storage_dir=storage,
            sync=False,
        )
    assert "errata" not in _article(storage)


def test_unknown_article_raises(storage):
    with pytest.raises(KeyError, match="mile_ghost"):
        apply_article_correction(
            "mile_ghost", details_patch={"a": 1}, summary="s",
            storage_dir=storage, sync=False,
        )


def test_other_articles_are_untouched(storage):
    apply_article_correction(
        "mile_test", details_patch={"event": "X"}, summary="s",
        storage_dir=storage, sync=False,
    )
    assert _article(storage, "mile_other") == {
        "id": "mile_other", "status": "published", "content": "unrelated"
    }


def test_repeated_corrections_append_to_history(storage):
    for val in ("A", "B"):
        apply_article_correction(
            "mile_test", details_patch={"event": val}, summary=f"fix {val}",
            storage_dir=storage, sync=False,
        )
    hist = _article(storage)["errata"]["update_history"]
    assert [h["summary"] for h in hist] == ["fix A", "fix B"]


def test_sync_failure_propagates(storage, monkeypatch):
    """An unsynced correction leaves the live page wrong; it must not be silent."""
    import sys
    import types

    fake = types.ModuleType("scripts.supabase_sync")

    def boom(*_a, **_kw):
        raise RuntimeError("supabase unreachable")

    fake.sync_article = boom
    monkeypatch.setitem(sys.modules, "scripts.supabase_sync", fake)

    with pytest.raises(RuntimeError, match="supabase unreachable"):
        apply_article_correction(
            "mile_test",
            details_patch={"event": "NFP_US_2026_07_02"},
            summary="s",
            storage_dir=storage,
            sync=True,
        )

    # The feed edit itself is already committed; only the projection failed.
    # Surfacing that is the point -- the caller must retry the sync.
    assert _article(storage)["details"]["event"] == "NFP_US_2026_07_02"
