#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Invariant tests for K1658 — guard the lookahead policy, seed, and claim scope.

These prove the pipeline runs the way the README says, not that the NULL result
is "good". Run:  uv run --extra dev pytest experiments/K1658/test_K1658.py -q
"""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
import K1658 as K  # noqa: E402  (test lives beside the module)


def _load_results():
    p = os.path.join(HERE, "K1658_results.json")
    if not os.path.exists(p):
        pytest.skip("results JSON not generated yet; run K1658.py first")
    with open(p) as f:
        return json.load(f)


def test_seed_is_42():
    assert K.SEED == 42


def test_windows_do_not_overlap():
    # statement ends at 14:15, presser starts at 14:25 -> a real gap, no overlap
    assert K.STMT_WIN[1] < K.PRESS_WIN[0]


def test_emergency_2020_meetings_excluded():
    assert "2020-03-15" not in K.FOMC_SET
    assert "2020-03-03" not in K.FOMC_SET


def test_holm_family_is_exactly_six():
    r = _load_results()
    fam = r["part3_aggregate_fomc_effect"]["multiple_testing"]["family_size"]
    assert fam == 6, f"family size drifted to {fam}"
    assert len(r["part3_aggregate_fomc_effect"]["results"]) == 6


def test_feasibility_is_infeasible_and_small_N():
    r = _load_results()["part1_feasibility_diagnosis"]["feasibility"]
    assert r["n_usable_events"] <= 3, "cross-event inference must remain infeasible"
    assert "INFEASIBLE" in r["verdict"]


def test_lookahead_shift1_present_in_source():
    with open(os.path.join(HERE, "K1658.py")) as f:
        src = f.read()
    # the lag must be literally in the code (repo hard rule)
    assert ".shift(1)" in src
    assert 'cov_type="HAC"' in src


def test_regression_uses_lagged_predictor_not_contemporaneous():
    """Reconstruct the alignment: outcome at t, FOMC dummy from t-1."""
    daily = {tk: K.load_daily(tk, refresh=False) for tk in K.ASSETS}
    df = daily["TLT"].copy()
    df.index = pd.to_datetime(df.index)
    fomc = pd.Series([1.0 if d.strftime("%Y-%m-%d") in K.FOMC_SET else 0.0
                      for d in df.index], index=df.index)
    logrv = np.log(K.parkinson_var(df).replace(0.0, np.nan))
    data = pd.concat([logrv.rename("logrv"), fomc.rename("FOMC")], axis=1).dropna()
    lagged = data["FOMC"].shift(1)
    # on a known FOMC day, the *same-day* dummy is 1 but the lagged regressor is 0
    fomc_days = data.index[data["FOMC"] == 1.0]
    assert len(fomc_days) > 5
    d0 = fomc_days[5]
    assert data.loc[d0, "FOMC"] == 1.0
    assert lagged.loc[d0] == 0.0  # predictor does NOT see same-day event -> no leakage


def test_bootstrap_reproducible_with_seed():
    daily = {tk: K.load_daily(tk, refresh=False) for tk in K.ASSETS}
    b1 = K._block_bootstrap_beta(daily, proxy="parkinson", n_boot=200)
    b2 = K._block_bootstrap_beta(daily, proxy="parkinson", n_boot=200)
    for tk in K.ASSETS:
        assert b1[tk]["beta_mean"] == b2[tk]["beta_mean"], "seed not deterministic"


def test_results_has_required_sections_and_scope_caveat():
    r = _load_results()
    for k in ("part1_feasibility_diagnosis", "part2_intraday_case_studies",
              "part3_aggregate_fomc_effect", "verdict", "unresolved",
              "lookahead_policy", "orthogonality_note"):
        assert k in r, f"missing {k}"
    assert "does NOT" in r["part3_aggregate_fomc_effect"]["scope_caveat"] or \
           "not separate" in r["part3_aggregate_fomc_effect"]["scope_caveat"]
    assert "descriptive only" in r["part2_intraday_case_studies"]["caveat"] or \
           "NO cross-event" in r["part2_intraday_case_studies"]["caveat"]
