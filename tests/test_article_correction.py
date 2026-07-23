"""Tests for in-place published-article corrections.

The property under test is fail-loud: a correction that does not apply must
raise rather than quietly stamping an errata over an unchanged article.
"""

from __future__ import annotations

import json

import pytest

from volpred.publisher.article_correction import (
    CorrectionNotApplied,
    CorrectionNotSynced,
    apply_article_correction,
)


@pytest.fixture
def storage(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    feed = [
        {
            "id": "mile_test",
            "title": "old title",
            "description": "old description",
            "audience": "general",
            "tags": ["一般讀者"],
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
    )

    art = _article(storage)
    assert "18.28%" in art["content"] and "14.41%" in art["content"]
    assert "18.1%" not in art["content"]
    assert art["details"]["event"] == "NFP_US_2026_07_02"
    assert art["errata"]["update_summary"] == "official calendar correction"
    assert len(art["errata"]["update_history"]) == 1
    assert report["details_changes"]["event"]["from"] == "NFP_US_2026_07_03"


def test_corrects_exact_title_and_records_change(storage):
    report = apply_article_correction(
        "mile_test",
        title_replacement=("old title", "new title"),
        summary="headline number correction",
        storage_dir=storage,
    )

    art = _article(storage)
    assert art["title"] == "new title"
    expected = {"from": "old title", "to": "new title"}
    assert art["errata"]["update_history"][-1]["title_change"] == expected
    assert report["title_change"] == expected


def test_title_mismatch_fails_before_writing(storage):
    original = _feed(storage)
    with pytest.raises(CorrectionNotApplied, match="title did not exactly match"):
        apply_article_correction(
            "mile_test",
            title_replacement=("stale title", "new title"),
            summary="headline number correction",
            storage_dir=storage,
        )
    assert _feed(storage) == original


def test_corrects_exact_description_and_records_change(storage):
    report = apply_article_correction(
        "mile_test",
        description_replacement=("old description", "new description"),
        summary="card excerpt correction",
        storage_dir=storage,
    )

    art = _article(storage)
    assert art["description"] == "new description"
    expected = {"from": "old description", "to": "new description"}
    assert art["errata"]["update_history"][-1]["description_change"] == expected
    assert report["description_change"] == expected


def test_description_mismatch_fails_before_writing(storage):
    original = _feed(storage)
    with pytest.raises(CorrectionNotApplied, match="description did not exactly match"):
        apply_article_correction(
            "mile_test",
            description_replacement=("stale description", "new description"),
            summary="card excerpt correction",
            storage_dir=storage,
        )
    assert _feed(storage) == original


def test_research_upcast_fails_before_writing(storage):
    original = _feed(storage)
    with pytest.raises(
        CorrectionNotApplied,
        match="violates the declared general-audience contract",
    ):
        apply_article_correction(
            "mile_test",
            content_replacements=[
                ("18.1%", "K741"),
                ("14.0%", "bootstrap"),
            ],
            summary="must remain reader-facing",
            storage_dir=storage,
        )
    assert _feed(storage) == original


def test_bare_statistical_notation_fails_before_writing(storage):
    original = _feed(storage)
    with pytest.raises(
        CorrectionNotApplied,
        match="violates the declared general-audience contract",
    ):
        apply_article_correction(
            "mile_test",
            content_replacements=[("18.1%", "p=0.03")],
            summary="must remain plain language",
            storage_dir=storage,
        )
    assert _feed(storage) == original


def test_published_at_is_not_touched(storage):
    """A correction must not reorder the feed."""
    before = _article(storage)["published_at"]
    apply_article_correction(
        "mile_test",
        content_replacements=[("18.1%", "18.28%")],
        summary="s",
        storage_dir=storage,
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
        )
    assert "errata" not in _article(storage)


def test_unknown_article_raises(storage):
    with pytest.raises(KeyError, match="mile_ghost"):
        apply_article_correction(
            "mile_ghost", details_patch={"a": 1}, summary="s",
            storage_dir=storage,
        )


def test_other_articles_are_untouched(storage):
    apply_article_correction(
        "mile_test", details_patch={"event": "X"}, summary="s",
        storage_dir=storage,
    )
    assert _article(storage, "mile_other") == {
        "id": "mile_other", "status": "published", "content": "unrelated"
    }


def test_repeated_corrections_append_to_history(storage):
    for val in ("A", "B"):
        apply_article_correction(
            "mile_test", details_patch={"event": val}, summary=f"fix {val}",
            storage_dir=storage,
        )
    hist = _article(storage)["errata"]["update_history"]
    assert [h["summary"] for h in hist] == ["fix A", "fix B"]


def _fake_sync(monkeypatch, impl):
    import supabase_sync

    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr("volpred.publisher.publisher.Publisher.REMOTE_URL", "")
    monkeypatch.setattr(supabase_sync, "sync_article", impl)


def test_sync_exception_propagates(storage, monkeypatch):
    """An unsynced correction leaves the live page wrong; it must not be silent."""

    def boom(*_a, **_kw):
        raise RuntimeError("supabase unreachable")

    _fake_sync(monkeypatch, boom)

    with pytest.raises(CorrectionNotSynced, match="projection sync failed"):
        apply_article_correction(
            "mile_test",
            details_patch={"event": "NFP_US_2026_07_02"},
            summary="s",
            storage_dir=storage,
        )

    # The feed edit itself is already committed; only the projection failed.
    # Surfacing that is the point -- the caller must retry the sync.
    assert _article(storage)["details"]["event"] == "NFP_US_2026_07_02"


def test_sync_returning_false_is_an_error_not_a_quiet_flag(storage, monkeypatch):
    """sync_article signals failure by RETURNING FALSE, not by raising.

    Reporting that as {"synced": False} and returning normally would leave
    feed.json corrected while the live page still served the old number --
    the exact silent-failure class this module exists to end.
    """
    _fake_sync(monkeypatch, lambda *_a, **_kw: False)

    with pytest.raises(CorrectionNotSynced, match="queued a retry"):
        apply_article_correction(
            "mile_test",
            details_patch={"event": "NFP_US_2026_07_02"},
            summary="s",
            storage_dir=storage,
        )
    dead_letters = json.loads(
        (storage / ".failed_supabase_syncs.json").read_text(encoding="utf-8")
    )
    assert dead_letters == ["mile_test"]


def test_sync_success_is_reported(storage, monkeypatch):
    _fake_sync(monkeypatch, lambda *_a, **_kw: True)
    report = apply_article_correction(
        "mile_test", details_patch={"event": "X"}, summary="s",
        storage_dir=storage,
    )
    assert report["synced"] is True
    assert report["gateway"]["feed_written"] is True


def test_gateway_pushes_mirror_and_supabase(storage, monkeypatch):
    calls = {"mirror": [], "supabase": []}

    def fake_mirror(_self, pub_id, item):
        calls["mirror"].append((pub_id, item["details"]["event"]))
        return True

    def fake_supabase(item, **_kwargs):
        calls["supabase"].append((item["id"], item["details"]["event"]))
        return True

    _fake_sync(monkeypatch, fake_supabase)
    monkeypatch.setattr(
        "volpred.publisher.publisher.Publisher.REMOTE_URL",
        "https://mirror.example",
    )
    monkeypatch.setattr(
        "volpred.publisher.publisher.Publisher._sync_report_to_remote",
        fake_mirror,
    )

    report = apply_article_correction(
        "mile_test",
        details_patch={"event": "corrected"},
        summary="s",
        storage_dir=storage,
    )

    assert report["gateway"]["mirror"] == "ok"
    assert calls == {
        "mirror": [("mile_test", "corrected")],
        "supabase": [("mile_test", "corrected")],
    }


def test_concurrent_edit_is_not_overwritten(storage, monkeypatch):
    from volpred.publisher.publisher import Publisher

    real_gateway = Publisher.rewrite_and_sync_article

    def inject_concurrent_edit(self, pub_id, updated_item, *, expected_item=None):
        feed = _feed(storage)
        feed[0]["content"] = "newer concurrent content"
        (storage / "reports" / "feed.json").write_text(
            json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return real_gateway(
            self,
            pub_id,
            updated_item,
            expected_item=expected_item,
        )

    monkeypatch.setattr(Publisher, "rewrite_and_sync_article", inject_concurrent_edit)

    with pytest.raises(CorrectionNotApplied, match="changed concurrently"):
        apply_article_correction(
            "mile_test",
            details_patch={"event": "corrected"},
            summary="s",
            storage_dir=storage,
        )
    assert _article(storage)["content"] == "newer concurrent content"
    assert _article(storage)["details"]["event"] == "NFP_US_2026_07_03"


def test_replacements_cannot_chain_into_each_other(storage):
    """[(A->B), (B->C)] on "A B" must give "B C", never "C B".

    Sequential str.replace would let the second pattern eat the first
    pattern's output. Spans are resolved against the original text.
    """
    art = _article(storage)
    art["content"] = "A B"
    feed = _feed(storage)
    feed[0] = art
    (storage / "reports" / "feed.json").write_text(
        json.dumps(feed, ensure_ascii=False), encoding="utf-8"
    )

    apply_article_correction(
        "mile_test",
        content_replacements=[("A", "B"), ("B", "C")],
        summary="s",
        storage_dir=storage,
    )
    assert _article(storage)["content"] == "B C"


def test_overlapping_replacements_are_rejected(storage):
    with pytest.raises(CorrectionNotApplied, match="overlap"):
        apply_article_correction(
            "mile_test",
            content_replacements=[("18.1%", "x"), ("18.1", "y")],
            summary="s",
            storage_dir=storage,
        )
    assert "18.1%" in _article(storage)["content"]


def test_write_is_atomic_and_leaves_no_temp_files(storage):
    apply_article_correction(
        "mile_test", details_patch={"event": "X"}, summary="s",
        storage_dir=storage,
    )
    leftovers = list((storage / "reports").glob(".feed.json.tmp"))
    assert leftovers == []
    # File is complete and parseable, not truncated.
    assert len(_feed(storage)) == 2


def test_failed_write_does_not_leave_a_partial_feed(storage, monkeypatch):
    """If the atomic write blows up, the original feed must survive intact."""
    original = _feed(storage)

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError, match="disk full"):
        apply_article_correction(
            "mile_test", details_patch={"event": "X"}, summary="s",
            storage_dir=storage,
        )

    assert _feed(storage) == original
    assert list((storage / "reports").glob(".feed.json.tmp")) == []
