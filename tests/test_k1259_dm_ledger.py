"""Regression tests for the K1259 DM-ledger ingestion boundary."""

from __future__ import annotations

from experiments.k1259 import build_dm_ledger as ledger


def test_get_numeric_warns_then_tries_next_alias(capsys) -> None:
    payload = {"dm_stat": "not-a-number", "stat": "1.25"}

    assert ledger.get_numeric(payload, "dm_stat", "stat") == 1.25

    stderr = capsys.readouterr().err
    assert "[k1259_dm_ledger] WARN numeric field is not parseable" in stderr
    assert "field=dm_stat" in stderr


def test_extract_rows_warns_before_skipping_bad_json(tmp_path, capsys) -> None:
    result_file = tmp_path / "broken_results.json"
    result_file.write_text("{not-json", encoding="utf-8")

    assert ledger.extract_rows_from_file(result_file) == []

    stderr = capsys.readouterr().err
    assert "[k1259_dm_ledger] WARN result JSON is unreadable" in stderr
    assert f"path={result_file}" in stderr


def test_iter_pair_entries_honors_ledger_exclude() -> None:
    payload = {
        "keep_vs_baseline": {"dm_stat": 1.5, "p_value": 0.1},
        "legacy_vs_baseline": {
            "dm_stat": 9.9,
            "p_value": 0.0,
            "ledger_exclude": True,
        },
    }

    entries = list(ledger.iter_pair_entries(payload, []))

    assert [label for _row, label, _path in entries] == ["keep_vs_baseline"]
