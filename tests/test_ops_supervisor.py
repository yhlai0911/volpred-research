from __future__ import annotations

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
