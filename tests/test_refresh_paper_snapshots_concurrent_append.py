"""Regression: concurrent refresh must not double-append the same dates.

K1685 found paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv carrying
byte-identical duplicate rows for 2026-05-04..05-15. Root cause: the append
path read `old_last`, spent minutes in yfinance, then appended — with no lock
and no re-read, two overlapping refreshes both saw the same stale boundary and
both wrote the same block.

These tests drive the post-download half of the path directly (the download
itself is what makes the race window wide, not what makes it a race).
"""
from __future__ import annotations

import importlib.util
import multiprocessing as mp
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "refresh_paper_snapshots", ROOT / "scripts" / "refresh_paper_snapshots.py"
)
refresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh)

COLS = ["date", "spy_close", "vix_close"]


def _write_csv(path: Path, dates: list[str]) -> None:
    lines = [",".join(COLS)]
    lines += [f"{d},100.5,20.25" for d in dates]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fetched_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "spy_close": [101.5] * len(dates),
        "vix_close": [21.25] * len(dates),
    })


def _append(csv_path: Path, new_dates: list[str]) -> dict:
    with refresh.shared_state_lock(refresh._snapshot_lock_name(csv_path)):
        return refresh._append_new_rows_locked(
            csv_path, _fetched_frame(new_dates), COLS, {}
        )


def _worker(csv_path: str, new_dates: list[str], barrier=None) -> None:
    """Reproduce the real sequence: read boundary → slow download → append.

    The pre-download read is the stale value that caused K1685, so the worker
    takes it *before* waiting on the barrier and never passes it downstream —
    the append path must re-derive the boundary under its own lock. Without
    that re-read (or without the lock), both workers append the same block.
    """
    path = Path(csv_path)
    _ = refresh._read_dates(path)  # stale boundary, as the real script reads it
    if barrier is not None:
        barrier.wait(timeout=30)  # both processes now hold the same stale view
    _append(path, new_dates)


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "spy_vix_2000-2026.csv"
    _write_csv(path, ["2026-05-01", "2026-05-02"])
    return path


def test_two_processes_appending_same_batch_produce_no_duplicates(snapshot: Path):
    """The K1685 scenario: both processes fetched the same new dates."""
    new_dates = ["2026-05-04", "2026-05-05", "2026-05-06"]
    ctx = mp.get_context("fork")
    barrier = ctx.Barrier(2)
    procs = [
        ctx.Process(target=_worker, args=(str(snapshot), new_dates, barrier))
        for _ in range(2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    dates = refresh._read_dates(snapshot)
    assert refresh._duplicate_dates(dates) == []
    assert dates == ["2026-05-01", "2026-05-02", *new_dates]


def test_second_append_of_same_batch_is_a_noop(snapshot: Path):
    """Serialized equivalent — the loser of the race must write nothing."""
    new_dates = ["2026-05-04", "2026-05-05"]
    first = _append(snapshot, new_dates)
    second = _append(snapshot, new_dates)

    assert first["written"] is True
    assert first["append_only_appended"] == 2
    assert second["written"] is False
    assert second["append_only_note"] == "no_strictly_new_dates"
    assert refresh._duplicate_dates(refresh._read_dates(snapshot)) == []


def test_partial_overlap_appends_only_the_novel_dates(snapshot: Path):
    _append(snapshot, ["2026-05-04", "2026-05-05"])
    result = _append(snapshot, ["2026-05-05", "2026-05-06", "2026-05-07"])

    assert result["append_only_appended"] == 2
    assert refresh._read_dates(snapshot) == [
        "2026-05-01", "2026-05-02", "2026-05-04", "2026-05-05",
        "2026-05-06", "2026-05-07",
    ]


def test_append_fails_closed_on_a_contaminated_file(snapshot: Path):
    _write_csv(snapshot, ["2026-05-01", "2026-05-02", "2026-05-02"])
    result = _append(snapshot, ["2026-05-04"])

    assert result["written"] is False
    assert "preexisting_duplicate_dates" in result["error"]
    # Nothing appended on top of the damage.
    assert refresh._read_dates(snapshot) == ["2026-05-01", "2026-05-02", "2026-05-02"]


def test_dupes_within_one_fetched_frame_are_collapsed(snapshot: Path):
    result = _append(snapshot, ["2026-05-04", "2026-05-04", "2026-05-05"])

    assert result["append_only_appended"] == 2
    assert refresh._duplicate_dates(refresh._read_dates(snapshot)) == []


def test_repair_drops_byte_identical_duplicates_and_preserves_survivors(snapshot: Path):
    body = ["2026-05-01,100.5,20.25", "2026-05-04,111.0,22.0", "2026-05-04,111.0,22.0"]
    snapshot.write_text(",".join(COLS) + "\n" + "\n".join(body) + "\n", encoding="utf-8")

    report = refresh._repair_duplicate_dates(snapshot, dry_run=False)

    assert report["repaired"] is True
    assert report["rows_dropped"] == 1
    assert report["duplicate_dates"] == ["2026-05-04"]
    # Surviving rows are byte-for-byte the originals — append-only intact.
    assert snapshot.read_text(encoding="utf-8").splitlines()[1:] == body[:2]


def test_repair_refuses_non_identical_duplicates(snapshot: Path):
    body = ["2026-05-04,111.0,22.0", "2026-05-04,999.0,33.0"]
    snapshot.write_text(",".join(COLS) + "\n" + "\n".join(body) + "\n", encoding="utf-8")

    report = refresh._repair_duplicate_dates(snapshot, dry_run=False)

    assert report["repaired"] is False
    assert "non_identical_duplicate_dates" in report["error"]
    assert snapshot.read_text(encoding="utf-8").splitlines()[1:] == body


def test_repair_dry_run_reports_without_writing(snapshot: Path):
    _write_csv(snapshot, ["2026-05-01", "2026-05-04", "2026-05-04"])
    before = snapshot.read_text(encoding="utf-8")

    report = refresh._repair_duplicate_dates(snapshot, dry_run=True)

    assert report["repaired"] is False
    assert report["rows_dropped"] == 1
    assert snapshot.read_text(encoding="utf-8") == before
