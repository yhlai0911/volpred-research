"""Public-contract regression tests for the adopted NFP T-7 evidence package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "nfp_20260807_t7"
LEGACY_SHA256 = {
    "nfp_t7_results.json": "7658a1610c200840f76699e62e1d38d574930f3956710647e1398b2e1991a315",
    "nfp_t7_events.csv": "be020d5230a61c6b9b56b5bd817a1cca0d2f8fb07b0560a6554ea18f716a70d3",
    "nfp_t7_regime.png": "266ca0f29518c43d3fd6bc0ef041e7c6572eb64b2e30533d0adb53c5ed54a728",
}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_nfp_t7_package_passes_the_canonical_artifact_gate() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_experiment_artifacts.py"),
            "check",
            "--path",
            str(EXPERIMENT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_every_control_window_is_return_interval_disjoint_from_every_event() -> None:
    closes = pd.read_csv(
        EXPERIMENT / "data" / "vix_close_2010-01-01_2026-07-30.csv"
    )
    controls = pd.read_csv(EXPERIMENT / "nfp_20260807_t7_controls.csv")
    events = pd.read_csv(EXPERIMENT / "nfp_20260807_t7_events.csv")

    positions = {
        value: index for index, value in enumerate(closes["date"].astype(str))
    }
    event_intervals = []
    for row in events.itertuples(index=False):
        release_index = positions[row.release]
        start_index = positions[row.start_date]
        assert release_index - start_index == 7
        event_intervals.append(set(range(start_index + 1, release_index)))

    for start_date in controls["start_date"].astype(str):
        start_index = positions[start_date]
        control_intervals = set(range(start_index + 1, start_index + 7))
        assert all(control_intervals.isdisjoint(event) for event in event_intervals)


def test_runtime_spec_binds_the_code_result_and_pinned_inputs() -> None:
    results = json.loads(
        (EXPERIMENT / "nfp_20260807_t7_results.json").read_text(encoding="utf-8")
    )
    spec = json.loads(
        (EXPERIMENT / "reproduce_spec.json").read_text(encoding="utf-8")
    )

    assert spec["network"] == "deny"
    assert spec["canonical_result"] == "nfp_20260807_t7_results.json"
    assert results["code_trace"]["sha256"] == spec["entrypoint"]["sha256"]
    assert results["code_trace"]["size_bytes"] == spec["entrypoint"]["size_bytes"]
    assert {row["path"] for row in spec["inputs"]} == {
        "experiments/nfp_20260807_t7/data/vix_close_2010-01-01_2026-07-30.csv",
        "experiments/nfp_20260807_t7/data/nfp_release_dates_2010-01-01_2026-07-31.json",
        "experiments/nfp_20260807_t7/nfp_t7_results.json",
    }


def test_canonical_result_records_the_published_correction_obligation() -> None:
    results = json.loads(
        (EXPERIMENT / "nfp_20260807_t7_results.json").read_text(encoding="utf-8")
    )

    correction = results["published_article_correction"]
    assert correction["required"] is True
    assert correction["article_id"] == "mile_84e3be0a"
    assert correction["archived_claims"] == {
        "control_n": 1485,
        "control_mean_pct": 0.35935433947436984,
        "iid_welch_p": 0.34229977127113453,
    }
    assert correction["canonical_claims"] == {
        "control_n": 2062,
        "control_mean_pct": 0.8004987972103451,
        "hac22_p": 0.5833876088096346,
    }


def test_target_current_state_uses_the_exact_trading_day_t7_information_set() -> None:
    results = json.loads(
        (EXPERIMENT / "nfp_20260807_t7_results.json").read_text(encoding="utf-8")
    )

    assert results["data"]["vix_snapshot_through"] == "2026-07-30"
    assert results["current_state"]["as_of"] == "2026-07-29"
    assert results["current_state"]["information_set_role"] == "trading_day_T-7"
    assert results["current_state"]["vix_close"] == pytest.approx(20.65999984741211)
    assert results["current_state"]["regime"] == "20-25"
    assert results["current_state"]["latest_snapshot_date"] == "2026-07-30"
    assert results["current_state"]["latest_snapshot_role"] == "trading_day_T-6"


def test_bootstrap_refuses_to_overwrite_pinned_snapshots(monkeypatch) -> None:
    module = _load_module(
        EXPERIMENT / "nfp_20260807_t7.py", "nfp_t7_bootstrap_contract"
    )

    class NetworkMustNotRun:
        def __init__(self) -> None:
            raise AssertionError("network acquisition ran before immutable-input guard")

    monkeypatch.setattr("volpred.data.manager.DataManager", NetworkMustNotRun)

    with pytest.raises(FileExistsError, match="already exist"):
        module.bootstrap_snapshots()


def test_retired_producer_main_only_delegates_and_preserves_legacy_bytes(
    monkeypatch,
) -> None:
    legacy_paths = [
        EXPERIMENT / "nfp_t7_results.json",
        EXPERIMENT / "nfp_t7_events.csv",
        EXPERIMENT / "nfp_t7_regime.png",
    ]
    before = {path.name: _sha256(path) for path in legacy_paths}
    assert before == LEGACY_SHA256
    module = _load_module(
        ROOT / "scripts" / "gen_nfp_20260807_t7_analysis.py",
        "retired_nfp_t7_producer",
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        module.runpy,
        "run_path",
        lambda path, *, run_name: calls.append((path, run_name)),
    )
    module.main()

    assert calls == [
        (str(EXPERIMENT / "nfp_20260807_t7.py"), "__main__")
    ]
    assert {path.name: _sha256(path) for path in legacy_paths} == before


def test_published_article_carries_the_canonical_correction() -> None:
    article_id = "mile_84e3be0a"
    feed = json.loads((ROOT / "storage" / "reports" / "feed.json").read_text())
    article = next(row for row in feed if row.get("id") == article_id)
    assert article["status"] == "published"
    assert article["title"].startswith("🌡️ 事件溫度計｜")
    assert article["details"]["experiment_refs"] == ["nfp_20260807_t7"]
    assert any(
        row.get("action") == "nfp_t7_hac_provenance_correction"
        for row in article["errata"]["update_history"]
    )
    series = json.loads((ROOT / "config" / "article_series.json").read_text())
    assert article_id in series["series"]["event_thermometer"]["members"]
    assert "2,062" in article["content"]
    assert "p=0.583" in article["content"]
    assert "一般週（n=1,485）" not in article["content"]
    assert "Welch t 檢定：" not in article["content"]
    assert "nfp_20260807_t7_regime.png" in article["content"]
    assert "從 7 月 30 日收盤算起，還有七個交易日" not in article["content"]
    assert "7 月 29 日 VIX 收在 **20.66**" in article["content"]
    assert "不確定性解除之後波動率下滑，這部分倒是穩定的" not in article["content"]
    assert "沒有事件日對照組" in article["content"]
    assert article["details"]["arc_signature"]["time_horizon"] == "weekly"
    note = series["series"]["event_thermometer"]["note"]
    assert "皆 published" not in note
    assert "成員數與狀態不在 note 複製" in note
