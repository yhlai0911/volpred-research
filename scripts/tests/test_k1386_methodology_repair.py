"""Regression coverage for the K1386 HAC, data, and timing repair."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from volpred.stats.model_evaluation import dm_test


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "experiments" / "k1386" / "k1386.py"
RESULTS_PATH = REPO_ROOT / "experiments" / "k1386" / "k1386_results.json"
README_PATH = REPO_ROOT / "experiments" / "k1386" / "README.md"


@pytest.fixture(scope="module")
def k1386():
    spec = importlib.util.spec_from_file_location("k1386_repair_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_qlike_dm_and_strict_alignment_are_pinned() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "qlike_pointwise(actual_rv, har_f)" in source
    assert "qlike_pointwise(actual_rv, uni_f)" in source
    assert "dm_test(loss_model, loss_har, h=h)" in source
    assert "def dm_test_harvey" not in source
    assert "strategy_dm_test" not in source
    assert ".reindex(eval_idx).ffill()" not in source
    assert "forecasts.index.equals(oos_idx)" in source


def test_frozen_input_is_unique_hash_pinned_and_one_to_one(k1386) -> None:
    frame, audit = k1386.load_data()
    columns = [
        "date",
        "spy_adj_close",
        "spy_high",
        "spy_low",
        "qqq_adj_close",
        "qqq_high",
        "qqq_low",
        "gld_adj_close",
        "gld_high",
        "gld_low",
    ]
    assert len(frame) == 4119
    assert frame["date"].is_monotonic_increasing
    assert not frame["date"].duplicated().any()
    assert k1386.dataframe_sha256(frame[columns]) == k1386.EXPECTED_ANALYSIS_SLICE_SHA256
    assert audit["merge_validation"] == "one_to_one"
    assert audit["analysis_window_merged_rows"] == 4119
    for source_audit in (audit["spy_qqq_source"], audit["gld_source"]):
        assert source_audit["raw_rows"] == 4129
        assert source_audit["unique_dates"] == 4119
        assert source_audit["duplicate_date_count"] == 10
        assert source_audit["duplicate_values_identical"] is True


def test_conflicting_duplicate_dates_fail_closed(k1386) -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
            "value": [1.0, 2.0],
        }
    )
    with pytest.raises(ValueError, match="conflicting rows"):
        k1386._deduplicate_identical_dates(frame, "synthetic.csv")


def test_first_oos_value_cannot_change_har_fit(k1386) -> None:
    values = pd.Series(np.linspace(0.0001, 0.003, 60) ** 2)
    train_mask = pd.Series([True] * 50 + [False] * 10)
    test_mask = ~train_mask

    _, beta, valid = k1386.har_rv_predict(values, train_mask, test_mask)
    changed = values.copy()
    changed.iloc[50] *= 1000.0
    _, changed_beta, changed_valid = k1386.har_rv_predict(
        changed, train_mask, test_mask
    )

    np.testing.assert_array_equal(valid, changed_valid)
    np.testing.assert_allclose(beta, changed_beta, rtol=0.0, atol=0.0)
    assert int(valid[-1]) == 48


def test_diagnostics_delegate_exactly_to_canonical_dm(k1386) -> None:
    rng = np.random.default_rng(1386)
    differential = np.zeros(500)
    innovations = rng.normal(size=500)
    for index in range(1, len(differential)):
        differential[index] = 0.55 * differential[index - 1] + innovations[index]
    differential += 0.2
    benchmark = np.zeros_like(differential)

    expected_t, expected_p = dm_test(differential, benchmark, h=1)
    result = k1386.forecast_dm_diagnostics(differential, benchmark, h=1)
    assert result["t_stat"] == pytest.approx(expected_t, abs=1e-15)
    assert result["p_value_two_sided"] == pytest.approx(expected_p, abs=1e-15)
    assert result["hac_lag"] == k1386.canonical_hac_lag(len(differential), h=1)
    assert set(result["loss_diff_acf"]) == {str(lag) for lag in range(1, 21)}


def test_saved_losses_reproduce_results_and_readme() -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    readme = README_PATH.read_text(encoding="utf-8")
    losses = {
        "HAR": np.load(RESULTS_PATH.with_name("k1386_loss_har.npy")),
        "fGN_univariate": np.load(
            RESULTS_PATH.with_name("k1386_loss_fgn_uni.npy")
        ),
        "fGN_multivariate": np.load(
            RESULTS_PATH.with_name("k1386_loss_fgn_multi.npy")
        ),
    }
    assert results["data"]["n_oos"] == 1098
    assert results["data"]["n_eval"] == 1097
    assert all(len(values) == 1097 for values in losses.values())
    for model, values in losses.items():
        assert values.mean() == pytest.approx(results["qlike_oos"][model], abs=5e-9)

    for key, model in (
        ("fGN_uni_vs_HAR", "fGN_univariate"),
        ("fGN_multi_vs_HAR", "fGN_multivariate"),
    ):
        expected_t, expected_p = dm_test(losses[model], losses["HAR"], h=1)
        saved = results["dm_test"][key]
        assert saved["t_stat"] == pytest.approx(expected_t, abs=1e-15)
        assert saved["p_value_two_sided"] == pytest.approx(expected_p, abs=1e-15)
        assert saved["hac_lag"] == 11

    for token in (
        "0.37534907",
        "0.47163477",
        "0.47314873",
        "+3.437383",
        "+3.452342",
        "`n=1,097`",
        "NULL_NO_FGN_IMPROVEMENT",
    ):
        assert token in readme


def test_atomic_json_failure_preserves_previous_final(k1386, monkeypatch, tmp_path) -> None:
    destination = tmp_path / "result.json"
    original = b'{"old": true}\n'
    destination.write_bytes(original)

    def fail_dump(*args, **kwargs):
        raise RuntimeError("injected dump failure")

    monkeypatch.setattr(k1386.json, "dump", fail_dump)
    with pytest.raises(RuntimeError, match="injected"):
        k1386.atomic_write_json(destination, {"new": True})
    assert destination.read_bytes() == original
    assert not destination.with_suffix(".json.tmp").exists()
