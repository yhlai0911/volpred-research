from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops.retraction import RETRACTION_FIELDS, RetractionError, retract_article


def _write_feed(storage: Path) -> Path:
    path = storage / "reports" / "feed.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            [
                {"id": "mile_old0001", "title": "old", "status": "published"},
                {"id": "mile_new0001", "title": "new", "status": "published"},
            ]
        ),
        encoding="utf-8",
    )
    return path


def _article(path: Path, article_id: str = "mile_old0001") -> dict:
    return next(row for row in json.loads(path.read_text()) if row["id"] == article_id)


def test_retract_with_successor_writes_complete_schema_and_readback(tmp_path: Path) -> None:
    feed_path = _write_feed(tmp_path)

    receipt = retract_article(
        "mile_old0001",
        reason="material factual error",
        superseded_by=["mile_new0001"],
        errata_ref="task:correction-1",
        storage_dir=tmp_path,
        actor="pytest",
    )

    article = _article(feed_path)
    assert receipt["changed"] is True
    assert article["status"] == "retracted"
    assert RETRACTION_FIELDS <= article.keys()
    assert article["retracted_reason"] == "material factual error"
    assert article["retracted_superseded_by"] == ["mile_new0001"]
    assert article["retracted_errata_ref"] == "task:correction-1"
    assert article["retracted_no_successor_reason"] is None
    assert article["retraction_schema_version"] == 1

    log = (tmp_path / "ops" / "writer_log.jsonl").read_text(encoding="utf-8")
    assert '"record_id": "mile_old0001"' in log


def test_retract_without_successor_requires_an_explicit_reason(tmp_path: Path) -> None:
    feed_path = _write_feed(tmp_path)

    with pytest.raises(RetractionError, match="choose exactly one"):
        retract_article("mile_old0001", reason="bad", storage_dir=tmp_path)

    retract_article(
        "mile_old0001",
        reason="bad",
        no_successor_reason="editorial successor has not been approved",
        storage_dir=tmp_path,
    )
    article = _article(feed_path)
    assert article["retracted_superseded_by"] == []
    assert article["retracted_no_successor_reason"] == (
        "editorial successor has not been approved"
    )


def test_unknown_successor_and_silent_metadata_rewrite_fail_closed(tmp_path: Path) -> None:
    _write_feed(tmp_path)
    with pytest.raises(RetractionError, match="do not exist"):
        retract_article(
            "mile_old0001",
            reason="bad",
            superseded_by=["mile_missing"],
            storage_dir=tmp_path,
        )

    retract_article(
        "mile_old0001",
        reason="bad",
        superseded_by=["mile_new0001"],
        storage_dir=tmp_path,
    )
    with pytest.raises(RetractionError, match="conflicts"):
        retract_article(
            "mile_old0001",
            reason="different reason",
            superseded_by=["mile_new0001"],
            storage_dir=tmp_path,
        )


def test_checked_in_schema_requires_every_writer_owned_field() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "article_retraction.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    required = set(schema["required"])
    assert {"id", "status", "retraction_schema_version"} | RETRACTION_FIELDS <= required
