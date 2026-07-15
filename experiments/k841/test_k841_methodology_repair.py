"""Regression tests for K841's timing, cost, and strategy-risk DM repair."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "k841_futures_realtime_vt",
    HERE / "k841_futures_realtime_vt.py",
)
K841 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(K841)


def _tiny_inputs():
    dates = pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-08"])
    tx = pd.DataFrame(
        {
            "date": dates,
            "night_open": [100.0, 100.0, 100.0],
            "night_close": [101.0, 101.0, 101.0],
            "night_high": [101.0, 101.0, 101.0],
            "night_low": [99.0, 99.0, 99.0],
            "night_volume": [1000.0, 1000.0, 1000.0],
            "night_session_status": ["available", "available", "available"],
            "night_start_date": [20200103, 20200106, 20200107],
            "night_continuation_date": [20200104, 20200107, 20200108],
            "day_open": [100.0, 100.0, 100.0],
            "day_close": [100.0, 100.0, 100.0],
            "day_volume": [1000.0, 1000.0, 1000.0],
            "night_ticks": [100, 100, 100],
        }
    )
    vix = pd.Series(
        20.0,
        index=pd.to_datetime(
            ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
        ),
        name="vix",
    )
    index = dates
    close = pd.Series([110.0, 110.0, 110.0], index=index, name="tw50_close")
    gap = pd.Series([0.10, 0.0, 0.0], index=index, name="tw50_gap_ret")
    intraday = pd.Series(0.0, index=index, name="tw50_intraday_ret")
    returns = ((1.0 + gap) * (1.0 + intraday) - 1.0).rename("tw50_ret")
    return tx, vix, close, returns, gap, intraday


def test_open_known_weight_is_not_back_applied_to_overnight_gap():
    merged = K841.compute_strategies(*_tiny_inputs())
    target = K841.VIX_ANCHOR / 20.0

    assert merged.iloc[0]["s1_overnight_weight"] == 1.0
    assert merged.iloc[0]["s1_weight_adj"] == target
    expected_cost = abs(1.0 - target) * 0.003
    assert np.isclose(merged.iloc[0]["s1_ret"], 0.10 - expected_cost)
    assert not np.isclose(merged.iloc[0]["s1_ret"], target * 0.10 - expected_cost)


def test_active_night_hedge_pays_round_trip_cost_every_night():
    merged = K841.compute_strategies(*_tiny_inputs())
    expected_cost = merged["hedge_ratio_adj"] * K841.FUTURES_TX_COST_PCT
    observed_cost = merged["tw50_ret"] + merged["s2_hedge_ret"] - merged["s2_ret"]

    assert (expected_cost > 0).all()
    assert np.allclose(observed_cost, expected_cost)
    assert np.allclose(
        merged["s5_ret"],
        merged["s1_ret"] + merged["s2_hedge_ret"] - expected_cost,
    )


def test_positive_serial_dependence_changes_iid_t_diagnostic():
    rng = np.random.default_rng(42)
    innovations = rng.normal(scale=0.0005, size=800)
    differential = np.empty_like(innovations)
    differential[0] = 0.0002 + innovations[0]
    for i in range(1, len(differential)):
        differential[i] = 0.0002 + 0.8 * differential[i - 1] + innovations[i]
    common_level = 0.01
    returns1 = np.sqrt(common_level + differential - differential.min())
    returns2 = np.sqrt(np.full(len(differential), common_level - differential.min()))

    diagnostic, _, _ = K841.risk_loss_dm_diagnostics(returns1, returns2)
    iid_t = diagnostic["lag_sensitivity_t"]["0"]

    assert diagnostic["hac_lag"] >= 1
    assert diagnostic["loss_differential_acf"]["1"] > 0.5
    assert abs(diagnostic["t_stat"]) < abs(iid_t)


def test_variance_risk_strategy_dm_matches_positive_squared_loss_dm():
    returns1 = np.array([0.02, -0.01, 0.03, -0.04] * 30, dtype=float)
    returns2 = np.array([0.01, -0.02, 0.01, -0.02] * 30, dtype=float)

    strategy_t, strategy_p = K841.strategy_dm_test(
        returns1, returns2, h=1, loss_fn="variance_risk"
    )
    loss_t, loss_p = K841.canonical_dm_test(returns1**2, returns2**2, h=1)

    assert np.isclose(strategy_t, loss_t, atol=1e-15)
    assert np.isclose(strategy_p, loss_p, atol=1e-15)


def test_saved_evidence_recomputes_every_reported_dm_cell():
    results_path = HERE / "k841_futures_realtime_vt_results.json"
    artifact_path = HERE / "k841_strategy_returns.npz"
    assert artifact_path.exists(), "final pointwise evidence must be committed"

    results = json.loads(results_path.read_text(encoding="utf-8"))
    expected_hash = results["data_source_details"]["strategy_return_artifact_sha256"]
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == expected_hash

    with np.load(artifact_path, allow_pickle=False) as evidence:
        for key, reported in results["dm_tests"].items():
            loss1 = evidence[f"{key}_loss1"]
            loss2 = evidence[f"{key}_loss2"]
            t_stat, p_value = K841.canonical_dm_test(loss1, loss2, h=1)
            assert np.isclose(t_stat, reported["t_stat"], atol=1e-12)
            assert np.isclose(p_value, reported["p_value"], atol=1e-15)
            assert reported["hac_lag"] == K841.canonical_hac_lag(len(loss1), h=1)


def test_legacy_evidence_recomputes_every_hac_only_cell():
    results = json.loads(
        (HERE / "k841_futures_realtime_vt_results.json").read_text(encoding="utf-8")
    )
    artifact_path = HERE / "k841_legacy_dm_losses.npz"
    assert artifact_path.exists(), "legacy pointwise losses must be committed"
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == (
        results["data_source_details"]["legacy_dm_evidence_sha256"]
    )

    reported_cells = results["methodology_repair"][
        "hac_only_repair_on_legacy_return_streams"
    ]
    with np.load(artifact_path, allow_pickle=False) as evidence:
        assert len(evidence["date_ordinal"]) == 2157
        for key, reported in reported_cells.items():
            loss1 = evidence[f"{key}_loss1"]
            loss2 = evidence[f"{key}_loss2"]
            recomputed = K841.loss_dm_diagnostics(loss1, loss2, h=1)
            assert np.isclose(recomputed["t_stat"], reported["t_stat"], atol=1e-12)
            assert np.isclose(recomputed["p_value"], reported["p_value"], atol=1e-15)
            assert recomputed["hac_lag"] == reported["hac_lag"] == 13
            assert recomputed["harvey_significant"] is reported["harvey_significant"]


def test_primary_source_and_results_are_hash_pinned_fail_closed():
    source = (HERE / "k841_futures_realtime_vt.py").read_text(encoding="utf-8")
    results = json.loads(
        (HERE / "k841_futures_realtime_vt_results.json").read_text(encoding="utf-8")
    )

    assert "__FILL" not in source
    assert "startswith('__FILL')" not in source
    assert "def dm_test(" not in source
    assert results["data_source_details"]["expected_yfinance_snapshot_sha256"] == (
        K841.EXPECTED_YFINANCE_SNAPSHOT_SHA256
    )
    assert results["data_source_details"]["expected_analysis_slice_sha256"] == (
        K841.EXPECTED_ANALYSIS_SLICE_SHA256
    )
    assert results["data_source_details"]["expected_legacy_dm_evidence_sha256"] == (
        K841.EXPECTED_LEGACY_DM_EVIDENCE_SHA256
    )
    for reported in results["dm_tests"].values():
        assert type(reported["significant_at_5pct"]) is bool
        assert type(reported["harvey_significant"]) is bool


def test_night_session_diagnostic_keeps_legitimate_zero_returns():
    results = json.loads(
        (HERE / "k841_futures_realtime_vt_results.json").read_text(encoding="utf-8")
    )
    diagnostic = results["night_session_diagnostics"]

    assert "basis_analysis" not in results
    assert diagnostic["sample_days"] == 2157
    assert diagnostic["available_night_sessions"] == 2152
    assert diagnostic["availability_pct"] == 99.8
    assert diagnostic["legitimate_zero_return_sessions"] == 10
    assert results["strategies"]["S2"].startswith("Buy & Hold 0050.TW")


def test_monday_file_uses_saturday_am_night_continuation(tmp_path):
    source = pd.DataFrame(
        {
            "商品代號": ["TX"] * 6,
            "到期月份(週別)": [202603] * 6,
            "成交數量(B+S)": [1] * 6,
            "成交日期": [20260313, 20260313, 20260314, 20260314, 20260316, 20260316],
            "成交時間": [150000, 235900, 100, 45900, 84500, 134500],
            "成交價格": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            "時間戳記": [
                "2026-03-13 15:00:00",
                "2026-03-13 23:59:00",
                "2026-03-14 00:01:00",
                "2026-03-14 04:59:00",
                "2026-03-16 08:45:00",
                "2026-03-16 13:45:00",
            ],
        }
    )
    path = tmp_path / "Daily_2026_03_16TX.csv"
    source.to_csv(path, index=False, encoding="big5")

    parsed = K841.parse_single_tx_file(path)

    assert parsed["night_start_date"] == 20260313
    assert parsed["night_continuation_date"] == 20260314
    assert parsed["night_open"] == 100.0
    assert parsed["night_close"] == 103.0
    assert parsed["night_ticks"] == 4
