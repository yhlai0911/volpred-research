from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "detect_price_split_breaks.py"
SPEC = importlib.util.spec_from_file_location("detect_price_split_breaks", SCRIPT)
assert SPEC and SPEC.loader
detector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detector)


def _write_split_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "Date,Close\n"
        "2013-12-27,40\n"
        "2013-12-30,40\n"
        "2013-12-31,40\n"
        "2014-01-02,10\n"
        "2014-01-03,10\n"
        "2014-01-06,10\n",
        encoding="utf-8",
    )


def test_csv_scan_collects_and_detects_snapshots_at_any_depth(
    tmp_path: Path, capsys,
) -> None:
    expected = {
        tmp_path / "experiments" / "k1406" / "data" / "0050.TW.csv",
        tmp_path / "experiments" / "group" / "deep" / "k1411" / "data" / "T0050.csv",
        tmp_path / "paper" / "nested" / "study" / "data" / "prices.csv",
    }
    for path in expected:
        _write_split_fixture(path)

    assert set(detector.collect_snapshot_csvs(tmp_path)) == expected
    assert detector.run_csv_scan(tmp_path, as_json=True) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["scanned"] == 3
    assert {Path(item["path"]) for item in report["dirty"]} == expected
    for item in report["dirty"]:
        assert item["breaks"][0]["ratio"] == 0.25
        assert item["breaks"][0]["date"] == "2014-01-02"


def test_csv_scan_with_no_snapshots_is_configuration_error(
    tmp_path: Path, capsys,
) -> None:
    assert detector.run_csv_scan(tmp_path, as_json=True) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["scanned"] == 0
    assert "configuration error" in report["error"]
