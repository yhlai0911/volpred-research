from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from scripts import collect_ndc_bci


def _snapshot() -> dict:
    payload = {
        "schema_version": 1,
        "source": "National Development Council Business Indicators DataBase",
        "source_origin": collect_ndc_bci.NDC_ORIGIN,
        "captured_at": "2026-07-26T11:00:00+00:00",
        "collector": "scripts/collect_ndc_bci.py",
        "transport": "playwright_chrome_official_json_response",
        "source_endpoint": collect_ndc_bci.NDC_DATA_ENDPOINT,
        "source_latest_date": "2026-05-01",
        "source_revision_notice": [
            "每月發布景氣指標時均回朔修正歷史資料。"
        ],
        "tables": [
            {
                "key": "leading_indicator",
                "item": "景氣領先指標不含趨勢指數(點)",
                "unit": "",
                "freq": "M",
                "source_url": (
                    "https://index.ndc.gov.tw/n/zh_tw/data/eco/indicators_table2"
                ),
                "source_endpoint": collect_ndc_bci.NDC_DATA_ENDPOINT,
                "source_code": "SR0051",
                "source_name": "領先指標不含趨勢指數",
                "source_unit": "(點)",
                "caption": "領先指標",
                "headers": ["年月", "領先指標不含趨勢指數(點)"],
                "rows": [
                    ["2026-01", "101.93"],
                    ["2026-02", "102.25"],
                    ["2026-05", "103.81"],
                ],
            },
            {
                "key": "signal_score",
                "item": "景氣對策信號(分)",
                "unit": "",
                "freq": "M",
                "source_url": (
                    "https://index.ndc.gov.tw/n/zh_tw/data/eco/indicators_table1"
                ),
                "source_endpoint": collect_ndc_bci.NDC_DATA_ENDPOINT,
                "source_code": "SR0005",
                "source_name": "景氣對策信號",
                "source_unit": "(分)",
                "caption": "景氣對策信號",
                "headers": ["年月", "景氣對策信號(燈號)", "景氣對策信號(分)"],
                "rows": [
                    ["2026-04", "", "40"],
                    ["2026-05", "", "39"],
                ],
            },
        ],
    }
    payload["content_sha256"] = collect_ndc_bci._snapshot_content_sha256(payload)
    return payload


def _write_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "item,unit,freq,period,value",
                "其他指標,,M,2026M01,7",
                "景氣對策信號(分),,M,2026M04,39.0",
                "景氣領先指標不含趨勢指數(點),點,M,2026M01,103.63",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_apply_snapshot_revises_appends_and_reads_back(tmp_path: Path) -> None:
    csv_path = tmp_path / "bci.csv"
    snapshot_path = tmp_path / "snapshot.json"
    _write_csv(csv_path)

    result = collect_ndc_bci.apply_snapshot(
        csv_path,
        _snapshot(),
        snapshot_path=snapshot_path,
    )

    assert result == {
        "inserted": 3,
        "revised": 2,
        "unchanged": 0,
        "row_count": 6,
        "readback_verified": True,
        "latest_periods": {
            "leading_indicator": "2026M05",
            "signal_score": "2026M05",
        },
    }
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keyed = {(row["item"], row["period"]): row for row in rows}
    assert keyed[("其他指標", "2026M01")]["value"] == "7"
    assert (
        keyed[("景氣領先指標不含趨勢指數(點)", "2026M01")]["value"]
        == "101.93"
    )
    assert keyed[("景氣領先指標不含趨勢指數(點)", "2026M05")]["value"] == "103.81"
    assert keyed[("景氣對策信號(分)", "2026M04")]["value"] == "40.0"
    assert keyed[("景氣對策信號(分)", "2026M05")]["value"] == "39.0"
    assert snapshot_path.exists()


def test_validate_snapshot_rejects_schema_drift() -> None:
    snapshot = _snapshot()
    snapshot.pop("content_sha256")
    snapshot["tables"][0]["headers"] = ["年月", "網站已改欄位"]

    with pytest.raises(collect_ndc_bci.NdcCollectionError, match="headers mismatch"):
        collect_ndc_bci.validate_snapshot(snapshot)


def test_validate_snapshot_rejects_tampered_hashed_payload() -> None:
    snapshot = _snapshot()
    snapshot["tables"][1]["rows"][-1][-1] = "99"

    with pytest.raises(
        collect_ndc_bci.NdcCollectionError, match="content hash mismatch"
    ):
        collect_ndc_bci.validate_snapshot(snapshot)


def test_freshness_requires_both_series(tmp_path: Path) -> None:
    csv_path = tmp_path / "bci.csv"
    _write_csv(csv_path)

    report = collect_ndc_bci.freshness_report(
        csv_path,
        target_date=date(2026, 7, 26),
    )

    assert report["expected_period"] == "2026M05"
    assert report["fresh"] is False
    assert report["series"]["leading_indicator"]["latest_period"] == "2026M01"
    assert report["series"]["signal_score"]["latest_period"] == "2026M04"
