"""Event articles use exact stage identity, not fuzzy semantics, as the hard lock."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_arc_dedup as cli  # noqa: E402


def _write_feed(root: Path, rows: list[dict]) -> None:
    reports = root / "storage" / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text(
        json.dumps(rows, ensure_ascii=False),
        encoding="utf-8",
    )


def _event_article(slot: str) -> dict:
    return {
        "id": f"mile_fomc_{slot}",
        "title": "事件溫度計｜FOMC 利率決議",
        "content": "聯準會利率決議與市場反應。",
        "status": "published",
        "audience": "event",
        "published_at": "2026-07-29T02:01:00+00:00",
        "event_key": "FOMC_2026_07_29",
        "event_type": "FOMC",
        "event_date": "2026-07-29",
        "event_series_slot": slot,
        "details": {
            "event_key": "FOMC_2026_07_29",
            "event_type": "FOMC",
            "event_date": "2026-07-29",
            "event_series_slot": slot,
        },
    }


def test_cross_stage_arc_duplicate_is_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_feed(tmp_path, [_event_article("T-2")])
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "find_arc_duplicates",
        lambda *_a, **_k: [
            {
                "id": "mile_fomc_T-2",
                "title": "事件溫度計｜FOMC 利率決議",
                "match_reason": "descriptive_strict",
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "事件溫度計｜FOMC 利率決議",
            "--audience",
            "event",
            "--event-key",
            "FOMC_2026_07_29",
            "--event-series-slot",
            "T+0",
        ],
    )

    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "warn_event_arc_dup"
    assert report["event_stage_coverage"] == []


def test_same_event_stage_is_hard_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_feed(tmp_path, [_event_article("T+0")])
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "事件溫度計｜FOMC 利率決議後",
            "--audience",
            "event",
            "--event-key",
            "FOMC_2026_07_29",
            "--event-series-slot",
            "T+0",
        ],
    )

    assert cli.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "block_event_stage_coverage"
    assert [row["id"] for row in report["event_stage_coverage"]] == ["mile_fomc_T+0"]


def test_same_event_stage_fails_open_without_durable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_feed(tmp_path, [_event_article("T+0")])
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "事件溫度計｜FOMC 利率決議後",
            "--audience",
            "event",
            "--event-key",
            "FOMC_2026_07_29",
            "--event-series-slot",
            "T+0",
        ],
    )

    assert cli.main() == 0


def test_cross_stage_k_coverage_is_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_feed(tmp_path, [_event_article("T-2")])
    experiment = tmp_path / "experiments" / "k2000"
    experiment.mkdir(parents=True)
    (experiment / "README.md").write_text("FOMC evidence", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "find_k_coverage",
        lambda *_a, **_k: [
            {
                "id": "mile_fomc_T-2",
                "title": "事件溫度計｜FOMC 會前",
                "status": "published",
                "audience": "event",
                "published_at": "2026-07-29T02:01:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(cli, "find_arc_duplicates", lambda *_a, **_k: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "事件溫度計｜FOMC 決議後",
            "--k-id",
            "K2000",
            "--audience",
            "event",
            "--event-key",
            "FOMC_2026_07_29",
            "--event-series-slot",
            "T+0",
        ],
    )

    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "warn_event_k_coverage"


def test_event_identity_arguments_are_all_or_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_feed(tmp_path, [])
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "FOMC",
            "--event-key",
            "FOMC_2026_07_29",
        ],
    )

    assert cli.main() == 2


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [("T0", "T+0"), ("T-0", "T+0"), ("T+00", "T+0")],
)
def test_event_slot_spelling_cannot_bypass_exact_stage_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
    canonical: str,
) -> None:
    _write_feed(tmp_path, [_event_article(canonical)])
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--title",
            "FOMC reaction retry",
            "--event-key",
            "FOMC_2026_07_29",
            "--event-series-slot",
            raw,
        ],
    )

    assert cli.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["event_identity"]["event_series_slot"] == canonical


def test_generic_fuzzy_arc_is_warn_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_feed(tmp_path, [_event_article("T-2")])
    (tmp_path / "storage" / "next_tasks.json").write_text(
        json.dumps([{"id": "daily_article_same_fuzzy_story"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "_log_dedup_decision", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "find_arc_duplicates",
        lambda *_a, **_k: [
            {
                "id": "mile_prior",
                "title": "same fuzzy story",
                "match_reason": "descriptive_strict",
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--candidate-id",
            "daily_article_same_fuzzy_story",
            "--title",
            "same fuzzy story",
        ],
    )

    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "warn_arc_dup"
