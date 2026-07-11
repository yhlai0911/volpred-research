from __future__ import annotations

import math
import stat
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts import collect_taifex_tick as collector
from scripts import collect_tw_data


TEN_COLUMNS = [
    "成交日期",
    "商品代號",
    "到期月份(週別)",
    "成交時間",
    "成交價格",
    "成交數量(B+S)",
    "近月價格",
    "遠月價格",
    "開盤集合競價",
    "時間戳記",
]


def _write_tx_file(path: Path, rows: list[list[object]], *, nine_columns: bool = False) -> None:
    columns = TEN_COLUMNS.copy()
    if nine_columns:
        columns.remove("開盤集合競價")
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding="big5")


def _ten_column_rows() -> list[list[object]]:
    rows: list[list[object]] = []
    # Low-volume contract must not leak into the active-contract bars.
    for time_value, price in [(84500, 900), (85000, 901), (85500, 902), (134500, 903)]:
        rows.append([20260105, "TX", 202601, time_value, price, 1, "-", "-", "", "x"])

    active_ticks = [
        (20260102, 150000, 98),
        (20260102, 150500, 99),
        (20260105, 0, 100),
        (20260105, 50000, 101),
        (20260105, 84500, 100),
        (20260105, 85000, 101),
        (20260105, 85500, 102),
        (20260105, 134500, 103),
    ]
    for trade_date, time_value, price in active_ticks:
        rows.append(
            [trade_date, "TX", 202602, time_value, price, 10, "-", "-", "", "x"]
        )
    # An auction outlier would dominate the first bar if the flag were ignored.
    rows.append([20260105, "TX", 202602, 84600, 9999, 10, "-", "-", "*", "x"])
    return rows


def test_process_tick_file_normalizes_schema_selects_volume_and_resets_sessions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Daily_2026_01_05TX.csv"
    _write_tx_file(source, _ten_column_rows())

    row = collector.process_tick_file(source)

    expected_day = float(np.square(np.diff(np.log([100.0, 101.0, 102.0, 103.0]))).sum())
    expected_night = float(np.square(np.diff(np.log([98.0, 99.0, 100.0, 101.0]))).sum())
    assert row["active_contract"] == 202602
    assert row["selection_rule"] == "same_day_max_total_volume_monthly_TX"
    assert row["day_n_bars"] == 4  # 13:45 is folded into the 13:40 final bar
    assert row["night_n_bars"] == 4  # 05:00 is folded into the 04:55 final bar
    assert math.isclose(row["rv_day"], expected_day, rel_tol=1e-12)
    assert math.isclose(row["rv_night"], expected_night, rel_tol=1e-12)
    assert math.isclose(row["rv_5min"], expected_day, rel_tol=1e-12)
    assert math.isclose(row["rv_total"], expected_day + expected_night, rel_tol=1e-12)
    assert row["day_close"] == 103.0  # auction price 9999 was excluded


def test_nine_column_legacy_file_is_supported(tmp_path: Path) -> None:
    rows = []
    times = [84500, 85000, 85500, 90000, 90500, 91000, 91500, 92000, 92500, 93000, 93500, 94000]
    for index, time_value in enumerate(times):
        rows.append([20120102, "TX", 201201, time_value, 7000 + index, 2, "-", "-", "x"])
    source = tmp_path / "Daily_2012_01_02TX.csv"
    _write_tx_file(source, rows, nine_columns=True)

    row = collector.process_tick_file(source)

    assert row["active_contract"] == 201201
    assert row["day_n_bars"] == 12
    assert row["night_n_bars"] == 0
    assert math.isnan(row["rv_night"])
    assert row["has_night"] is False


def test_incremental_noop_does_not_touch_canonical_mtime(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "Daily_2026_01_05TX.csv"
    _write_tx_file(source, _ten_column_rows())
    output = tmp_path / "taifex_5min_rv.csv"

    first = collector.update_canonical(source_dir, output, workers=1, min_days=1)
    first_mtime = output.stat().st_mtime_ns
    second = collector.update_canonical(source_dir, output, workers=1, min_days=1)

    assert first["wrote_output"] is True
    assert second["changed_files"] == 0
    assert second["wrote_output"] is False
    assert output.stat().st_mtime_ns == first_mtime
    assert stat.S_IMODE(output.stat().st_mode) == 0o644


def test_source_error_preserves_previous_canonical_atomically(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    valid = source_dir / "Daily_2026_01_05TX.csv"
    _write_tx_file(valid, _ten_column_rows())
    output = tmp_path / "taifex_5min_rv.csv"
    collector.update_canonical(source_dir, output, workers=1, min_days=1)
    before = output.read_bytes()

    corrupt = source_dir / "Daily_2026_01_06TX.csv"
    corrupt.write_text("not,a,taifex,file\n1,2,3,4\n")
    with pytest.raises(RuntimeError, match="canonical output was not changed"):
        collector.update_canonical(
            source_dir,
            output,
            full_rebuild=True,
            workers=1,
            min_days=1,
        )

    assert output.read_bytes() == before


@pytest.mark.parametrize("full_rebuild", [False, True])
def test_disappeared_source_is_not_silently_kept_as_fresh(
    tmp_path: Path, full_rebuild: bool
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "Daily_2026_01_05TX.csv"
    _write_tx_file(source, _ten_column_rows())
    output = tmp_path / "taifex_5min_rv.csv"
    collector.update_canonical(source_dir, output, workers=1, min_days=1)
    before = output.read_bytes()

    source.unlink()
    placeholder = source_dir / "Daily_2026_01_06TX.csv"
    _write_tx_file(placeholder, _ten_column_rows())
    with pytest.raises(RuntimeError, match=r"source file\(s\) disappeared"):
        collector.update_canonical(
            source_dir,
            output,
            full_rebuild=full_rebuild,
            workers=1,
            min_days=1,
        )

    assert output.read_bytes() == before


def test_validation_gate_rejects_candidate_without_replacing_canonical(
    monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "Daily_2026_01_05TX.csv"
    rows = _ten_column_rows()
    _write_tx_file(source, rows)
    output = tmp_path / "taifex_5min_rv.csv"
    collector.update_canonical(source_dir, output, workers=1, min_days=1)
    before = output.read_bytes()

    changed_rows = _ten_column_rows()
    changed_rows[-2][4] = 104  # active contract's 13:45 close
    _write_tx_file(source, changed_rows)
    args = SimpleNamespace(
        source_dir=source_dir,
        output=output,
        full_rebuild=False,
        workers=1,
        min_days=1,
        validate=True,
        validation_dir=tmp_path,
        min_overlap=20,
        require_correlation=0.9,
    )
    monkeypatch.setattr(collector, "_parse_args", lambda: args)
    monkeypatch.setattr(collector, "LOCK_PATH", tmp_path / "collector.lock")
    monkeypatch.setattr(
        collector,
        "validate_against_0050",
        lambda *_: {
            "overlap_days": 100,
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "pearson_r": 0.5,
        },
    )

    with pytest.raises(RuntimeError, match="validation correlation gate failed"):
        collector.main()

    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".*.candidate"))


def test_0050_rv_is_computed_within_each_saved_day(tmp_path: Path) -> None:
    # A huge prior-day close would contaminate day 2 under the old multi-day
    # pct_change-before-grouping implementation.  Per-file rebuilding excludes it.
    for date, close in {
        "2026-01-05": [100.0, 101.0, 102.0],
        "2026-01-06": [200.0, 202.0, 204.0],
    }.items():
        pd.DataFrame({"Close": close}).to_csv(tmp_path / f"0050_TW_5min_{date}.csv")

    result = collect_tw_data.rebuild_saved_daily_rv("0050.TW", tmp_path)

    expected = float(np.square(np.diff(np.log([200.0, 202.0, 204.0]))).sum())
    assert math.isclose(float(result.loc["2026-01-06", "rv_5min"]), expected, rel_tol=1e-12)
    persisted = pd.read_csv(tmp_path / "0050_TW_daily_rv.csv")
    assert len(persisted) == 2
    assert stat.S_IMODE((tmp_path / "0050_TW_daily_rv.csv").stat().st_mode) == 0o644


def test_0050_overlap_validation_names_and_computes_daily_rv(tmp_path: Path) -> None:
    reference_rows = []
    taifex_rows = []
    for index, date in enumerate(["2026-01-05", "2026-01-06", "2026-01-07"], start=1):
        close = np.array([100.0, 100.0 + index, 100.0 + 2 * index])
        pd.DataFrame({"Close": close}).to_csv(tmp_path / f"0050_TW_5min_{date}.csv")
        rv = float(np.square(np.diff(np.log(close))).sum())
        reference_rows.append(rv)
        taifex_rows.append({"date": date, "rv_day": rv * 2.0})
    output = tmp_path / "taifex.csv"
    pd.DataFrame(taifex_rows).to_csv(output, index=False)

    validation = collector.validate_against_0050(output, tmp_path)

    assert validation["overlap_days"] == 3
    assert math.isclose(validation["pearson_r"], 1.0, rel_tol=1e-12)


def test_collect_tw_treats_taifex_canonical_failure_as_critical() -> None:
    assert collect_tw_data._collection_exit_code({"tw50_daily": True, "taifex_5min_rv": False}) == 1
    assert collect_tw_data._collection_exit_code({"tw50_daily": False, "taifex_5min_rv": True}) == 0
    assert collect_tw_data._collection_exit_code({"tw50_daily": False, "taifex_5min_rv": False}) == 1
