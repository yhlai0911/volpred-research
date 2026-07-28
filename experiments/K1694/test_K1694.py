#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mechanical gates for the eight defects Codex round 1 blocked K1694 on.

Each test names the defect it guards. They read the committed artifacts and, where
a claim is about the estimator rather than the output, rebuild the panel from the
cached CSVs -- so a future edit that reintroduces a defect fails here rather than
in round 3 of a review.

Run: uv run --active python -m pytest experiments/K1694/test_K1694.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import K1694  # noqa: E402


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads((HERE / "K1694_results.json").read_text())


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads((HERE / "reproduce_spec.json").read_text())


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return K1694.build_panel(K1694.build_fcm(), K1694.build_dcot(), K1694.build_vol())


@pytest.fixture(scope="module")
def frame(panel: pd.DataFrame) -> pd.DataFrame:
    return K1694.build_spec_frame(panel)


# --- defect 1: bootstrap must estimate spec1, not a neighbouring specification ---

def test_bootstrap_shares_spec1_design_matrix(results: dict) -> None:
    s1 = results["panel_regressions"]["spec1_fcm_highvol"]
    for key in ("stationary_block_by_month", "month_cluster_iid"):
        boot = results["bootstrap_spec1"][key]
        assert boot["rhs"] == s1["rhs"], f"{key} RHS differs from spec1"
        assert "t" in boot["rhs"], f"{key} dropped the time trend spec1 includes"
        assert boot["n_rows"] == s1["n_obs"], f"{key} sample differs from spec1"
        assert boot["n_months"] == s1["n_months"]
    assert results["primary_interaction"]["bootstrap_matches_spec1_sample_and_rhs"]


def test_bootstrap_point_is_the_reported_spec1_coefficient(results: dict) -> None:
    s1c = results["panel_regressions"]["spec1_fcm_highvol"]["driscoll_kraay"]["coef"]
    for key in ("stationary_block_by_month", "month_cluster_iid"):
        boot = results["bootstrap_spec1"][key]
        assert boot["point"] == pytest.approx(s1c["fcm_x_highvol"], rel=1e-12)
        chk = boot["point_estimator_identity_check"]
        assert chk["max_abs_diff"] < 1e-12, "within-OLS drifted from PanelOLS"


def test_within_ols_equals_panel_ols(frame: pd.DataFrame) -> None:
    """The bootstrap's fast estimator is the same estimator, not an approximation."""
    from linearmodels.panel import PanelOLS
    df = frame.dropna(subset=["d_nonrep"] + K1694.SPEC1_RHS)
    ref = PanelOLS(df.set_index(["commodity", "month_ts"])["d_nonrep"],
                   df.set_index(["commodity", "month_ts"])[K1694.SPEC1_RHS].astype(float),
                   entity_effects=True).fit(cov_type="unadjusted")
    beta = K1694._within_ols(df["d_nonrep"].to_numpy(float),
                            df[K1694.SPEC1_RHS].to_numpy(float),
                            pd.factorize(df["commodity"])[0])
    for j, name in enumerate(K1694.SPEC1_RHS):
        assert beta[j] == pytest.approx(float(ref.params[name]), rel=1e-9, abs=1e-18)


def test_single_estimation_sample_owner(frame: pd.DataFrame, results: dict) -> None:
    """Every spec's sample is a subset of the one frame; spec1/2 are exactly it."""
    for label in ("spec1_fcm_highvol", "spec2_fcm_rvz_continuous"):
        assert results["panel_regressions"][label]["n_obs"] == len(frame)
    for label, block in results["panel_regressions"].items():
        if isinstance(block, dict) and "n_obs" in block:
            assert block["n_obs"] <= len(frame)


# --- defect 2: a missing RV must not be silently labelled low-volatility ---

def test_highvol_is_nan_when_rv_is_missing(panel: pd.DataFrame) -> None:
    assert int((panel["rv"].isna() & panel["highvol"].notna()).sum()) == 0
    assert int(panel["rv"].isna().sum()) == int(panel["highvol"].isna().sum())


def test_highvol_pit_is_nan_when_rv_is_missing(panel: pd.DataFrame) -> None:
    assert int((panel["rv"].isna() & panel["highvol_pit"].notna()).sum()) == 0


# --- defect 3: the bootstrap's name must match what it resamples ---

def test_bootstrap_names_are_honest(results: dict) -> None:
    boots = results["bootstrap_spec1"]
    assert boots["stationary_block_by_month"]["preserves_serial_correlation"] is True
    assert boots["stationary_block_by_month"]["mean_block_months"] >= 2
    iid = boots["month_cluster_iid"]
    assert iid["preserves_serial_correlation"] is False
    assert "NOT a block bootstrap" in iid["label"]
    assert boots["headline"] == "stationary_block_by_month"


def test_stationary_blocks_are_consecutive_months() -> None:
    rng = np.random.default_rng(0)
    idx = K1694._month_blocks_stationary(120, 6, rng)
    runs = int((np.diff(idx) == 1).sum())
    assert runs > 0.5 * (len(idx) - 1), "blocks are not consecutive in time"


# --- defect 4: partial months excluded by a reproducible rule, not a date ---

def test_partial_months_are_excluded_by_rule(results: dict, panel: pd.DataFrame) -> None:
    cov = results["sample"]["completeness"]
    assert cov["rule"]["date_hardcoded"] is False
    dropped = {m["month"] for m in cov["dropped_partial_dcot_months"]}
    assert "2026-07" in dropped, "the partial DCOT month is still in the panel"
    assert str(panel["month"].max()) not in dropped
    assert results["sample"]["panel_span"][1] == "2026-06"
    assert results["sample"]["panel_span_is_complete_months_only"] is True


def test_completeness_rule_holds_on_every_retained_row(panel: pd.DataFrame) -> None:
    assert (panel["nweeks"] >= K1694.MIN_DCOT_WEEKS).all()
    assert (panel["dcot_tail_gap_days"] <= K1694.MAX_DCOT_TAIL_GAP_DAYS).all()
    have_rv = panel["rv"].notna()
    assert (panel.loc[have_rv, "rv_ndays"] >= K1694.MIN_RV_DAYS).all()


def test_differences_never_span_a_dropped_month(panel: pd.DataFrame) -> None:
    """Excluding a month must not silently turn the next month into a 2-month diff."""
    non_adjacent = panel.loc[~panel["adjacent_prev_month"]]
    assert non_adjacent["d_nonrep"].notna().sum() == 0
    assert non_adjacent["nonrep_lag"].notna().sum() == 0
    assert non_adjacent["dlog_oi"].notna().sum() == 0


# --- defect 5: the methodology description must match the code ---

def test_bandwidth_rule_is_named_for_what_it_computes(results: dict) -> None:
    assert K1694._hac_bandwidth_rule(149) == 6
    assert not hasattr(K1694, "_acf_bandwidth"), "the misleading name is back"
    rule = results["panel_regressions"]["_hac_bandwidth_rule"]
    assert "not ACF-derived" in rule
    assert "acf" not in results["timeseries_regression"]["hac_lag_rule"].lower() or \
           "not ACF-derived" in results["timeseries_regression"]["hac_lag_rule"]


def test_bandwidth_choice_is_backed_by_a_sensitivity_grid(results: dict) -> None:
    sens = results["dk_bandwidth_sensitivity_spec1"]
    assert [r["bandwidth"] for r in sens["grid"]] == list(range(1, 25))
    assert sens["term"] == "fcm_x_highvol"


def test_promised_predictive_spec_exists(results: dict) -> None:
    spec4 = results["panel_regressions"]["spec4_predictive_fully_lagged"]
    assert "fcm_pre_x_highvol_lag" in spec4["rhs"]
    assert "dlog_oi_lag" in spec4["rhs"], "spec4 must not use a contemporaneous control"
    assert "highvol" not in spec4["rhs"], "spec4 must not use the full-sample regime label"
    assert spec4["n_obs"] > 0


def test_predictive_spec_signal_precedes_the_outcome_window(panel: pd.DataFrame) -> None:
    have = panel.dropna(subset=["avail_date_pre"])
    assert int((have["avail_date_pre"] >= have["month_start"]).sum()) == 0


def test_primary_merge_is_backward_only(panel: pd.DataFrame) -> None:
    have = panel.dropna(subset=["avail_date"])
    assert int((have["avail_date"] > have["month_end"]).sum()) == 0


# --- defect 6 / 7: the JSON must not overstate, and NULL must be scoped ---

def test_results_do_not_claim_prediction_for_the_association_specs(results: dict) -> None:
    """The claim-bearing surface -- title, primary_interaction, spec1-3 notes -- must
    read as association. Prose that *denies* prediction (data_provenance,
    claim_language_rule, limitations) is the point, so it is not searched."""
    assert results["claim_type"] == "ex_post_association"
    assert results["primary_interaction"]["claim_type"] == "ex_post_association"
    banned = ("predictive", "causal", "known-before-outcome", "forecast")
    headline = json.dumps([results["title"], results["primary_interaction"]]).lower()
    for word in banned:
        assert word not in headline, f"headline surface claims '{word}'"
    specs = results["panel_regressions"]
    for label in ("spec1_fcm_highvol", "spec2_fcm_rvz_continuous",
                  "spec3_trader_conc4_highvol"):
        note = specs[label]["note"].lower()
        assert note.startswith("ex-post association"), label
        assert "predictive" not in note, label
    assert specs["spec4_predictive_fully_lagged"]["note"].startswith("predictive"), (
        "spec4 is the only spec allowed to be described as predictive")


def test_limitations_cover_every_disclosure_codex_named(results: dict) -> None:
    blob = " ".join(results["limitations"]).lower()
    for token in ("synthetic", "timing overlap", "full-sample", "serial correlation"):
        assert token in blob, f"limitations omit '{token}'"


def test_null_is_scoped_and_names_the_positive_continuous_result(results: dict) -> None:
    assert results["verdict"] == "NULL"
    scope = results["verdict_scope"]
    assert "NEGATIVE" in scope and "BINARY" in scope
    assert "no association" in scope.lower()
    sec = results["secondary_findings"][
        "spec2_continuous_interaction_is_positive_and_significant"]
    assert sec["coef"] > 0
    assert abs(sec["t_driscoll_kraay"]) >= 1.96


def test_no_stale_bootstrap_key_impersonating_a_spec1_ci(results: dict) -> None:
    assert "bootstrap_interaction_spec1" not in results
    assert "bootstrap_ci95" not in results["primary_interaction"]


# --- defect 8: reproduce_spec.json must be a side effect of the run ---

def test_reproduce_spec_pins_the_bytes_that_ran(results: dict, spec: dict) -> None:
    assert spec["schema_version"] == "volpred.reproduce_spec.v1"
    assert spec["entrypoint"]["sha256"] == results["code_trace"]["sha256"]
    assert spec["entrypoint"]["size_bytes"] == results["code_trace"]["size_bytes"]
    on_disk = (HERE / "K1694.py").read_bytes()
    import hashlib
    assert hashlib.sha256(on_disk).hexdigest() == spec["entrypoint"]["sha256"], (
        "K1694.py changed after the run that produced these results -- rerun, do not "
        "refresh the checksum")


def test_reproduce_spec_pins_the_result_bytes(spec: dict) -> None:
    import hashlib
    ident = spec["canonical_result_identity"]
    raw = (HERE / ident["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ident["sha256"]
    assert len(raw) == ident["size_bytes"]


def test_reproduce_spec_declares_seed_and_inputs(spec: dict) -> None:
    assert spec["randomness"]["status"] == "declared"
    assert {"library": "numpy", "value": K1694.SEED} in spec["randomness"]["seeds"]
    inputs = {Path(i["path"]).name for i in spec["inputs"]}
    assert {"fcm_monthly.csv", "dcot_weekly.csv", "rv_monthly.csv"} <= inputs
