from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    module_path = ROOT / "scripts" / "audit_topic_clusters.py"
    spec = importlib.util.spec_from_file_location("audit_topic_clusters", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        dt = datetime(2026, 6, 23, tzinfo=timezone.utc)
        return dt if tz is None else dt.astimezone(tz)

    @staticmethod
    def fromisoformat(value: str):
        return datetime.fromisoformat(value)


def test_audit_topic_clusters_warns_on_bad_feed_timestamp(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "datetime", FixedDateTime)
    monkeypatch.setattr(
        module,
        "load_feed_items",
        lambda: [
            {
                "id": "bad_ts",
                "title": "VIX bad timestamp",
                "tags": ["VIX"],
                "status": "published",
                "published_at": "not-a-date",
            },
            {
                "id": "good_ts",
                "title": "SPY normal timestamp",
                "tags": ["SPY"],
                "status": "published",
                "published_at": "2026-06-11T00:00:00+00:00",
            },
        ],
    )

    result = module.main()

    assert result == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["total_articles"] == 1
    assert payload["clusters"][0]["cluster"] == "spy"
    assert payload["clusters"][0]["count_90d"] == 1
    assert (
        "[audit_topic_clusters] WARN feed timestamp parse failed; skipping item"
        in captured.err
    )
    assert "bad_ts" in captured.err
    assert "not-a-date" in captured.err
