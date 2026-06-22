from __future__ import annotations

from datetime import datetime, timezone

from volpred.ops import supervisor


def test_load_supervisor_rules_warns_on_invalid_json(tmp_path, capsys) -> None:
    rules_path = tmp_path / "supervisor_rules.json"
    rules_path.write_text("{bad-json", encoding="utf-8")

    rules = supervisor.load_supervisor_rules(str(rules_path))

    assert rules == {}
    captured = capsys.readouterr()
    assert "[ops_supervisor] WARN supervisor rules read failed; using defaults" in captured.err
    assert "supervisor_rules.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_feed_rhythm_warns_on_unreadable_feed_json(tmp_path, capsys) -> None:
    feed_path = tmp_path / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True)
    feed_path.write_text("{bad-json", encoding="utf-8")

    result = supervisor._feed_rhythm(
        str(tmp_path),
        cutoff=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result == {"available": False, "error": "feed.json unreadable"}
    captured = capsys.readouterr()
    assert "[ops_supervisor] WARN feed rhythm read failed; marking unavailable" in captured.err
    assert "feed.json" in captured.err
    assert "JSONDecodeError" in captured.err
