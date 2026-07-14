from __future__ import annotations

from contextlib import contextmanager
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backfill_arc_dedup_metadata as backfill  # noqa: E402


def test_backfill_plan_uses_same_title_content_tags_surface_as_runtime():
    item = {
        "id": "mile_tags",
        "title": "流動性觀察",
        "content": "市場結構追蹤。",
        "tags": ["USDC", "DeFi"],
        "details": {
            "arc_signature": {
                "schema_version": "arc_dedup_v3",
                "entities": [],
            }
        },
    }

    plan = backfill.build_backfill_plan([item])

    assert plan["count"] == 1
    desired = plan["entries"][0]["arc_signature"]
    assert desired == backfill.arc_signature_from_feed_item(item)
    assert {"STABLECOIN", "DEFI"} <= set(desired["entities"])


def test_write_existing_single_files_syncs_patched_feed(tmp_path, monkeypatch):
    reports_dir = tmp_path / "storage" / "reports"
    reports_dir.mkdir(parents=True)
    single_path = reports_dir / "mile_test.json"
    single_path.write_text(
        json.dumps({"id": "mile_test", "details": {"old": True}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(backfill, "REPORTS_DIR", reports_dir)

    feed = [
        {
            "id": "mile_test",
            "title": "Updated",
            "details": {
                "arc_signature": {
                    "schema_version": "arc_dedup_v2",
                    "mechanisms": ["cross_asset_spillover"],
                }
            },
        },
        {"id": "mile_missing_single", "details": {"arc_signature": {}}},
    ]

    written = backfill._write_existing_single_files(
        feed,
        {"mile_test", "mile_missing_single"},
    )

    assert written == 1
    saved = json.loads(single_path.read_text(encoding="utf-8"))
    assert saved == feed[0]


def test_atomic_writers_call_canonical_guard_for_feed_and_single(tmp_path, monkeypatch):
    reports_dir = tmp_path / "storage" / "reports"
    reports_dir.mkdir(parents=True)
    feed_path = reports_dir / "feed.json"
    single_path = reports_dir / "mile_test.json"
    single_path.write_text("{}", encoding="utf-8")
    guarded: list[Path] = []
    monkeypatch.setattr(backfill, "FEED_PATH", feed_path)
    monkeypatch.setattr(backfill, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(backfill, "guard_canonical_write", lambda path: guarded.append(Path(path)))

    feed = [{"id": "mile_test", "title": "kept"}]
    backfill._write_feed_atomic(feed)
    assert backfill._write_existing_single_files(feed, {"mile_test"}) == 1

    assert guarded == [feed_path, single_path]
    assert json.loads(feed_path.read_text(encoding="utf-8")) == feed
    assert json.loads(single_path.read_text(encoding="utf-8")) == feed[0]


def test_apply_reloads_inside_publisher_lock_and_preserves_concurrent_article(
    tmp_path, monkeypatch
):
    reports_dir = tmp_path / "storage" / "reports"
    reports_dir.mkdir(parents=True)
    feed_path = reports_dir / "feed.json"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_target",
                    "title": "USDC 流動性",
                    "content": "DeFi stablecoin pool。",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(backfill, "FEED_PATH", feed_path)
    monkeypatch.setattr(backfill, "REPORTS_DIR", reports_dir)
    lock_calls: list[tuple[str, str]] = []

    @contextmanager
    def fake_lock(name, storage_dir, **kwargs):
        lock_calls.append((name, storage_dir))
        latest = json.loads(feed_path.read_text(encoding="utf-8"))
        latest.append(
            {
                "id": "mile_concurrent",
                "title": "concurrent publish",
                "content": "must survive",
                "details": {"keep": True},
            }
        )
        feed_path.write_text(json.dumps(latest), encoding="utf-8")
        yield True

    monkeypatch.setattr(backfill, "shared_state_lock", fake_lock)
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_arc_dedup_metadata.py", "--apply", "--id", "mile_target"],
    )

    assert backfill.main() == 0

    saved = json.loads(feed_path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in saved}
    assert set(by_id) == {"mile_target", "mile_concurrent"}
    assert by_id["mile_concurrent"]["details"] == {"keep": True}
    assert by_id["mile_target"]["details"]["arc_signature"]["schema_version"] == "arc_dedup_v4"
    assert lock_calls == [("publisher_feed", str(tmp_path / "storage"))]
