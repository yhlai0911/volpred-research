"""Tests for K1733.

These do three jobs, in decreasing order of usefulness:

1. **Exercise the dormant H4 path.** H4's pre-specified precondition (H2 or H3
   ACCEPT/PARTIAL) was not met, so ``run_h4`` never executed in the production
   run. Untested dormant code should not be described as working, so it is run
   here against the real cached panel and its outputs are checked for internal
   coherence. Nothing this test computes enters any claim.
2. **Re-derive each verdict from the stored statistics.** A verdict string is a
   claim about numbers that sit beside it; if the two can drift, the artifact is
   only as good as the author's attention.
3. **Assert the invariants the estimators must satisfy** — GFEVD row sums, NET
   summing to zero, order-invariance, the lookahead probe's zero deviations, and
   the label-embargo arithmetic in ``expanding_oos``.

Run: ``uv run --extra dev python -m pytest experiments/k1733/test_k1733.py -q``
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("k1733_mod", HERE / "K1733.py")
K = importlib.util.module_from_spec(_spec)
sys.modules["k1733_mod"] = K
_spec.loader.exec_module(K)

RESULTS = HERE / "K1733_results.json"


@pytest.fixture(scope="module")
def res() -> dict:
    if not RESULTS.exists():
        pytest.skip("K1733_results.json not present — run the experiment first")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def panel() -> dict:
    if not (HERE / "data" / "prices_raw.csv").exists():
        pytest.skip("price snapshot not present")
    return K.download_panel(refresh=False)


# ── 1. the dormant H4 path actually runs ──────────────────────────────────────

def test_h4_path_executes_and_is_coherent(panel):
    """run_h4 is dead code in the production run; prove it is not broken code."""
    log_vol, _ = K.build_log_vol(panel, "parkinson")
    returns = K.close_returns(panel)
    out = K.run_h4(log_vol, returns, "long7", K.FORECAST_SPECS["long7"], "QQQ")

    assert out["n_days"] > 1000
    assert set(out["cost_grid"]) == {"0bps", "1bps", "5bps"}
    for arm in ("own_vol_gate", "market_vol_gate", "cross_basket_gate"):
        assert 0.0 <= out["avg_exposure"][arm] <= 1.0
        assert out["annual_turnover"][arm] >= 0.0

    # A gate can only ever reduce exposure relative to buy-and-hold.
    zero = out["cost_grid"]["0bps"]
    assert zero["cross_basket_gate"]["ann_vol"] <= zero["buy_and_hold"]["ann_vol"] + 1e-12

    # Costs are monotone: more cost per side can never raise the net return.
    for arm in ("own_vol_gate", "market_vol_gate", "cross_basket_gate"):
        r0 = out["cost_grid"]["0bps"][arm]["ann_return"]
        r1 = out["cost_grid"]["1bps"][arm]["ann_return"]
        r5 = out["cost_grid"]["5bps"][arm]["ann_return"]
        assert r0 >= r1 - 1e-12 >= r5 - 1e-9, arm

    # The drawdown audit must carry the exposure-matched companion and its null.
    dd = out["drawdown"]
    for key in ("exposure_matched_gap", "matched_benchmark_mdd", "matched_lambda",
                "vol_ratio", "exposure_mismatch", "p_value_vs_phase_null"):
        assert key in dd, key
    assert 0.0 < dd["p_value_vs_phase_null"] <= 1.0
    assert dd["n_phase_reps"] == K.N_PHASE_NULL

    # And the turnover-artifact rule must be a real function of the grid, not a
    # constant: high-cost-only wins are the pattern it exists to catch.
    assert out["turnover_artifact"] == bool(
        out["wins_both_baselines_by_cost"]["5bps"]
        and not out["wins_both_baselines_by_cost"]["0bps"]
    )


def test_h4_verdict_helper_covers_both_branches():
    assert K.verdict_h4(None, False)["verdict"] == "NOT_RUN_PRECONDITION_NOT_MET"
    fake = {
        "wins_both_baselines_by_cost": {"0bps": False, "1bps": False, "5bps": True},
        "turnover_artifact": True,
        "drawdown": {"exposure_matched_gap": 0.05, "p_value_vs_phase_null": 0.4},
    }
    assert K.verdict_h4(fake, True)["verdict"] == "REJECT_TURNOVER_ARTIFACT"
    fake2 = dict(fake, turnover_artifact=False,
                 wins_both_baselines_by_cost={"0bps": True, "1bps": True, "5bps": True})
    assert K.verdict_h4(fake2, True)["verdict"] == "ACCEPT"


# ── 2. verdicts must follow from the stored statistics ────────────────────────

def test_h1_verdict_follows_from_stored_p_values(res):
    v = res["verdicts"]["H1"]
    ps = [n["h1_total_spillover"]["p_value_vs_independent_ar_null"]
          for n in res["networks"].values()]
    assert v["verdict"] == ("ACCEPT" if all(p < 0.05 for p in ps) else "PARTIAL")
    for n in res["networks"].values():
        h1 = n["h1_total_spillover"]
        assert h1["tci_pp"] > h1["null_floor_q95"], "TCI must clear its own null floor"


def test_h2_reject_because_no_pair_is_positive_and_significant(res):
    rows = res["networks"]["full8"]["h2_pairwise"]
    assert res["verdicts"]["H2"]["verdict"] == "REJECT"
    assert not [r for r in rows if r["fdr_significant"] and r["npdc_pp"] > 0]
    # The REJECT is a sign failure, not a power failure: every estimate is
    # negative with a bootstrap interval strictly below zero.
    for r in rows:
        assert r["npdc_pp"] < 0, r["pair"]
        assert r["ci_high_90"] < 0, r["pair"]
        assert r["boot_sign_stability"] >= 0.90, r["pair"]


def test_h3_reject_and_the_ladder_is_what_reverses_the_reading(res):
    h3 = res["h3_forecast"]
    assert res["verdicts"]["H3"]["verdict"] == "REJECT"
    assert h3["fdr_by_rung"]["M3_vs_M2"]["n_fdr_significant"] == 0
    # The loose literal reading would have "passed" — that is the whole point of
    # the ladder, and if this ever stops being true the README's headline is stale.
    assert h3["fdr_by_rung"]["M0plusExog_vs_M0"]["n_fdr_significant"] > 0
    assert h3["fdr_by_rung"]["M1_vs_M0"]["n_fdr_significant"] > 0
    loose_max = max(c["ladder"]["M0plusExog_vs_M0"]["clark_west"]["t_stat"]
                    for c in h3["cells"])
    prim_max = max(c["ladder"]["M3_vs_M2"]["clark_west"]["t_stat"] for c in h3["cells"])
    assert loose_max > 3.0 > prim_max


def test_every_primary_nested_comparison_uses_clark_west(res):
    for c in res["h3_forecast"]["cells"]:
        for key, rung in c["ladder"].items():
            assert rung["clark_west"]["test"].startswith("Clark-West"), key
            assert rung["clark_west"]["status"] == "ok", key
            # A degenerate HAC bandwidth is the K1655 failure mode.
            assert rung["clark_west"]["hac_lag"] >= 1, key
            assert rung["qlike_role"] == "descriptive_only_no_nested_test"


def test_h4_not_run_matches_the_precondition(res):
    v = res["verdicts"]
    precondition = (v["H2"]["verdict"] in ("ACCEPT", "PARTIAL")
                    or v["H3"]["verdict"] in ("ACCEPT", "PARTIAL"))
    assert precondition is False
    assert v["H4"]["verdict"] == "NOT_RUN_PRECONDITION_NOT_MET"
    assert res["h4_strategy"] is None


# ── 3. estimator and pipeline invariants ─────────────────────────────────────

def test_gfevd_matrix_invariants(res):
    for name, net in res["networks"].items():
        m = np.asarray(net["observed"]["matrix"])
        assert np.allclose(m.sum(axis=1), 100.0, atol=1e-6), name
        net_vals = np.asarray(list(net["observed"]["net"].values()))
        assert abs(net_vals.sum()) < 1e-6, name
        to_ = net["observed"]["to_others"]
        from_ = net["observed"]["from_others"]
        for a in net["assets"]:
            assert net["observed"]["net"][a] == pytest.approx(to_[a] - from_[a], abs=1e-9)


def test_pairwise_net_matches_the_matrix(res):
    for name, net in res["networks"].items():
        assets = net["assets"]
        m = np.asarray(net["observed"]["matrix"])
        for key, val in net["observed"]["pairwise_net"].items():
            s, t = key.split("->")
            i, j = assets.index(s), assets.index(t)
            assert val == pytest.approx(m[j, i] - m[i, j], abs=1e-9), key


def test_kpps_is_order_invariant_and_cholesky_is_not(res):
    for name, o in res["ordering_robustness"].items():
        assert o["n_orderings"] >= 100, name
        assert o["kpps_order_invariance_verified"] is True, name
        assert o["kpps_max_abs_dev_all"] < 1e-6, name
        # The artifact yardstick must actually show an artifact, otherwise the
        # audit is not measuring anything.
        assert o["cholesky_worst_pair_sign_stability"] < 0.90, name


def test_subperiod_signs_are_stable(res):
    for name, net in res["networks"].items():
        s = net["subperiod_summary"]
        assert s["n_subperiods_run"] == 3, name
        assert s["sign_agreement_with_full_sample"] == 1.0, name


def test_granger_hac_bandwidth_is_not_degenerate(res):
    for name, g in res["granger_lead_lag"].items():
        assert g["hac_lag"] >= int(np.ceil(g["n_obs"] ** (1 / 3))) - 1, name
        assert g["hac_lag"] > 1, name
        for t in g["tests"]:
            assert 0.0 <= t["p_value"] <= 1.0
            assert len(t["lag_coefficients"]) == t["lag"]
            assert len(t["lag_coefficient_hac_se"]) == t["lag"]
            lo, hi = t["coef_sum_boot_ci_90"]
            assert lo <= hi


def test_lookahead_probe_is_clean(res):
    p = res["lookahead_diagnostics"]
    assert p["verdict"] == "CLEAN"
    assert p["n_violations"] == 0 and p["violations"] == []
    assert p["log_vol_max_abs_deviation_pre_cut"] == 0.0
    assert p["strategy_weight_max_abs_deviation_pre_cut"] == 0.0
    assert p["forecast_checks"], "the probe must actually have compared some origins"
    for c in p["forecast_checks"]:
        assert c["n_pre_cut_origins"] > 100
        for col, dev in c["max_abs_deviation"].items():
            assert dev == 0.0, f"{c['target']}/h{c['horizon']}/{col}"


def test_label_embargo_arithmetic():
    """Row j may train for origin i only if its label window closed: j + h - 1 < i."""
    n = 60
    idx = pd.RangeIndex(n)
    X = pd.DataFrame({"x": np.arange(n, dtype=float)}, index=idx)
    y = pd.Series(np.linspace(1.0, 2.0, n), index=idx)
    for h in (1, 5, 22):
        mask = np.zeros(n, dtype=bool)
        mask[-1] = True
        pred, sig2, ok = K.expanding_oos(X, y, mask, h, min_train=n - h)
        # min_train is set to exactly the admissible count, so the last origin is
        # forecast iff `last_train + 1 == i - h + 1 >= min_train`.
        assert ok[-1] == ((n - 1) - h + 1 >= n - h)
        if ok[-1]:
            assert np.isfinite(sig2[-1]) and sig2[-1] >= 0.0
        # One fewer admissible row than min_train must refuse to forecast.
        _, _, ok2 = K.expanding_oos(X, y, mask, h, min_train=n - h + 1)
        assert not ok2[-1]


def test_feature_rows_are_lagged_by_one_day(panel):
    """The shift(1) contract, checked on the real panel rather than asserted."""
    log_vol, _ = K.build_log_vol(panel, "parkinson")
    returns = K.close_returns(panel)
    rv = returns ** 2
    designs, y, idx = K.ladder_designs("QQQ", 5, rv, log_vol, returns, ["XLU", "HYG", "LQD"])
    # M1's own_pk_d column at date t must equal the target's log vol at t-1.
    pos = idx.get_loc(idx[500])
    t, prev = idx[pos], idx[pos - 1]
    assert designs["M1"].loc[t, "own_pk_d"] == pytest.approx(log_vol.loc[prev, "QQQ"])
    # And the target at t is the forward 5-day mean squared return starting AT t.
    fwd = float((returns["QQQ"].loc[t:].iloc[:5] ** 2).mean())
    assert y.loc[t] == pytest.approx(fwd)


def test_every_model_shares_one_index_and_nests(panel):
    log_vol, _ = K.build_log_vol(panel, "parkinson")
    returns = K.close_returns(panel)
    designs, y, idx = K.ladder_designs("SMH", 1, returns ** 2, log_vol, returns,
                                       ["XLU", "HYG", "LQD"])
    for d in designs.values():
        assert d.index.equals(idx)
        assert d.notna().all().all()
    for small, large in (("M0", "M1"), ("M1", "M2"), ("M2", "M3"), ("M0", "M0plusExog")):
        assert set(designs[small].columns) < set(designs[large].columns), (small, large)


def test_reported_coverage_matches_the_snapshot(res, panel):
    for tk, cov in res["ticker_coverage"].items():
        df = panel[tk]
        assert cov["n_obs"] == len(df), tk
        assert cov["first_date"] == str(df.index[0].date()), tk


def test_results_are_the_output_of_the_pinned_code(res):
    """The stored code_trace must describe the K1733.py sitting next to it."""
    import hashlib

    data = (HERE / "K1733.py").read_bytes()
    assert res["code_trace"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert res["code_trace"]["size_bytes"] == len(data)
    assert res["config"]["quick_mode"] is False, "a quick run must never be the artifact"
    assert res["config"]["seed"] == 42
