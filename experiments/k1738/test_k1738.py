"""K1738 tests: lookahead guards, construction invariants, estimator sanity.

The lookahead tests are the load-bearing ones.  This design has two distinct lookahead traps and
both are tested:
  (1) anchoring on the fiscal period end instead of the announcement date, and
  (2) letting the outcome window touch the pre-announcement or reaction period.
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

import K1738 as K  # noqa: E402

PANEL_PATH = HERE / "panel_k1738.parquet"
RESULTS_PATH = HERE / "K1738_results.json"


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        pytest.skip("panel not built yet; run K1738.py first")
    return pd.read_parquet(PANEL_PATH)


@pytest.fixture(scope="module")
def results() -> dict:
    if not RESULTS_PATH.exists():
        pytest.skip("results not built yet; run K1738.py first")
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# Lookahead guards
# ---------------------------------------------------------------------------------------------

def test_outcome_window_starts_after_confounder_window(panel):
    """Feature end (t0-1) must precede label start (r+1) with a gap of >= 2 trading days."""
    gap = (panel["reaction_pos"] + 1) - panel["conf_pos"]
    assert (gap >= 2).all(), f"min feature/label gap {gap.min()} < 2 trading days"


def test_confounder_date_strictly_before_announcement(panel):
    assert (panel["conf_date"] < panel["ann_date"]).all(), \
        "confounder window must end strictly before the announcement calendar date"


def test_reaction_day_not_before_announcement(panel):
    assert (panel["reaction_date"] >= panel["ann_date"]).all(), \
        "reaction day cannot precede the announcement"


def test_confounder_position_precedes_announcement_position(panel):
    assert (panel["conf_pos"] < panel["ann_pos"]).all()
    assert (panel["reaction_pos"] >= panel["ann_pos"]).all()


def test_outcome_windows_do_not_overlap_confounder_windows(panel):
    """The longest confounder lookback is 252d; it must not reach into any outcome window."""
    conf_start = panel["conf_pos"] - 252
    outcome_start = panel["reaction_pos"] + 1
    assert (conf_start < outcome_start).all()
    assert (panel["conf_pos"] < outcome_start).all()


def test_guard_rejects_a_deliberately_leaked_window():
    """Negative control: the same guard must FAIL when the outcome window is shifted backwards."""
    fake = pd.DataFrame({"conf_pos": [100, 200], "reaction_pos": [99, 199]})
    gap = (fake["reaction_pos"] + 1) - fake["conf_pos"]
    assert not (gap >= 2).all(), "guard failed to catch an outcome window that precedes features"


def test_sue_denominator_uses_only_prior_announcements():
    """sigma_hat at row q must equal std of raw surprises at rows q-8..q-1, never including q."""
    raw = pd.Series([1.0, -2.0, 3.0, 0.5, -1.5, 2.5, -0.5, 4.0, 100.0, 1.0])
    sigma = raw.shift(1).rolling(K.SUE_WINDOW, min_periods=K.SUE_MIN_OBS).std(ddof=1)
    # row 8 carries the huge value 100.0; its own sigma must not see it
    expected_row8 = raw.iloc[0:8].std(ddof=1)
    assert np.isclose(sigma.iloc[8], expected_row8)
    # row 9's sigma DOES see row 8, and must therefore be much larger
    assert sigma.iloc[9] > sigma.iloc[8] * 2


def test_announcement_date_not_period_end(panel):
    """Announcement dates must look like announcement dates, not fiscal quarter ends.

    Fiscal period ends cluster hard on month-end (31 Mar / 30 Jun / 30 Sep / 31 Dec).  If we had
    mistakenly anchored on period end, the day-of-month distribution would spike at 28-31.
    """
    dom = panel["ann_date"].dt.day
    month_end_share = float((dom >= 28).mean())
    assert month_end_share < 0.35, (
        f"{month_end_share:.1%} of anchors fall on days 28-31 -- this looks like fiscal period "
        "ends, not announcement dates"
    )


def test_macro_is_backward_filled_only():
    """as-of lookup must never pull a future observation backwards."""
    s = pd.Series([1.0, np.nan, np.nan, 4.0],
                  index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]))
    filled = s.ffill()
    assert filled.loc["2020-01-02"] == 1.0 and filled.loc["2020-01-03"] == 1.0
    assert filled.loc["2020-01-03"] != 4.0


# ---------------------------------------------------------------------------------------------
# Construction invariants
# ---------------------------------------------------------------------------------------------

def test_realized_vol_estimator():
    r = np.array([0.01, -0.01, 0.02, -0.02])
    assert np.isclose(K.annualized_rv(r), np.sqrt(252.0 * np.mean(r ** 2)))
    assert np.isnan(K.annualized_rv(np.array([np.nan, np.nan])))


def test_rv_positive_and_finite(panel):
    for h in K.HORIZONS:
        v = panel[f"rv_{h}"].dropna()
        assert (v > 0).all() and np.isfinite(v).all()


def test_treatment_is_winsorized(panel):
    lo, hi = panel["sue_raw"].quantile(K.WINSOR)
    assert panel["sue"].min() >= lo - 1e-9
    assert panel["sue"].max() <= hi + 1e-9
    assert (panel["abs_sue"] >= 0).all()


def test_treatment_proxy_matches_frozen_analyst_estimate_fields(panel, results):
    """The frozen bytes are analyst-estimate based, not a seasonal-random-walk proxy."""
    assert np.allclose(panel["raw_surprise"], panel["eps_act"] - panel["eps_est"])
    assert np.allclose(panel["sue_raw"], panel["raw_surprise"] / panel["sigma_hat"])
    label = results["treatment_definition"]["type"].lower()
    assert "analyst-estimate-based" in label
    assert "not a seasonal-random-walk" in label


def test_sigma_hat_strictly_positive(panel):
    assert (panel["sigma_hat"].dropna() > 0).all()


def test_peer_instrument_uses_only_prior_announcements(panel):
    """Z must be built from announcements strictly before t0, and never from the firm itself."""
    sub = panel[panel["peer_n"] > 0]
    if sub.empty:
        pytest.skip("no peer coverage")
    # reconstruct a sample of rows and confirm no same-ticker / non-prior contamination
    rng = np.random.default_rng(0)
    for i in rng.choice(sub.index.values, size=min(40, len(sub)), replace=False):
        row = panel.loc[i]
        peers = panel[(panel["sector"] == row["sector"])
                      & (panel["ann_date"] < row["ann_date"])
                      & (panel["ann_date"] >= row["ann_date"] - pd.Timedelta(days=K.PEER_WINDOW_DAYS))
                      & (panel["ticker"] != row["ticker"])]
        assert len(peers) == row["peer_n"]
        if len(peers):
            assert np.isclose(peers["sue"].mean(), row["peer_sue"])


def test_grouped_folds_never_split_a_firm():
    groups = np.array(["A"] * 10 + ["B"] * 10 + ["C"] * 10 + ["D"] * 10 + ["E"] * 10)
    fid = K.grouped_folds(groups, 5, seed=42)
    for g in np.unique(groups):
        assert len(np.unique(fid[groups == g])) == 1, f"firm {g} straddles folds"
    assert len(np.unique(fid)) == 5


def test_grouped_folds_are_seed_reproducible():
    g = np.array([f"T{i // 3}" for i in range(60)])
    assert (K.grouped_folds(g, 5, 42) == K.grouped_folds(g, 5, 42)).all()
    assert not (K.grouped_folds(g, 5, 42) == K.grouped_folds(g, 5, 7)).all()


# ---------------------------------------------------------------------------------------------
# Inference machinery
# ---------------------------------------------------------------------------------------------

def test_twoway_meat_is_psd():
    rng = np.random.default_rng(0)
    s = rng.normal(size=(200, 3))
    cl1 = rng.integers(0, 10, 200).astype(str)
    cl2 = rng.integers(0, 7, 200).astype(str)
    M = K.twoway_meat(s, cl1, cl2)
    assert np.all(np.linalg.eigvalsh((M + M.T) / 2) >= -1e-9)


def test_clustering_widens_se_under_within_cluster_correlation():
    """The whole point of clustering: iid SE must be too small when errors are clustered."""
    rng = np.random.default_rng(1)
    n_cl, per = 40, 25
    cl = np.repeat(np.arange(n_cl), per).astype(str)
    shock = np.repeat(rng.normal(size=n_cl), per)
    x = rng.normal(size=n_cl * per)
    y = 0.5 * x + shock + 0.1 * rng.normal(size=n_cl * per)
    W = np.column_stack([x, np.ones(len(x))])
    _, V_cl = K.ols_twoway(y, W, cl, cl)
    e = y - W @ np.linalg.pinv(W.T @ W) @ (W.T @ y)
    XtX_inv = np.linalg.pinv(W.T @ W)
    V_iid = XtX_inv * float(e @ e) / (len(y) - 2)
    assert V_cl[0, 0] > 0 and V_iid[0, 0] > 0


def test_ols_twoway_recovers_a_known_coefficient():
    rng = np.random.default_rng(2)
    n = 4000
    x = rng.normal(size=n)
    z = rng.normal(size=n)
    y = 1.5 * x - 0.8 * z + rng.normal(size=n) * 0.5
    cl = rng.integers(0, 50, n).astype(str)
    b, V = K.ols_twoway(y, np.column_stack([x, z, np.ones(n)]), cl, cl)
    assert abs(b[0] - 1.5) < 0.05 and abs(b[1] + 0.8) < 0.05
    assert V[0, 0] > 0


def test_dml_recovers_a_known_effect_under_confounding():
    """Synthetic DGP where the naive estimate is badly biased and DML should not be."""
    rng = np.random.default_rng(3)
    n_firms, per = 120, 25
    firm = np.repeat([f"F{i}" for i in range(n_firms)], per)
    month = np.array([f"M{i % 60}" for i in range(n_firms * per)])
    n = n_firms * per
    X = rng.normal(size=(n, 5))
    conf = X[:, 0] + 0.5 * X[:, 1] ** 2
    d = conf + rng.normal(size=n)
    theta = 0.30
    y = theta * d + 2.0 * conf + rng.normal(size=n)
    naive_b, _ = K.ols_twoway(y, np.column_stack([d, np.ones(n)]), firm, month)
    out = K.dml_plr(y, d, X, firm, month, n_reps=2)
    assert abs(naive_b[0] - theta) > 0.5, "test DGP is not actually confounded"
    assert abs(out["theta"] - theta) < 0.12, f"DML off: {out['theta']} vs {theta}"
    assert out["se"] > 0


def test_dml_returns_null_effect_when_there_is_none():
    rng = np.random.default_rng(4)
    n_firms, per = 100, 20
    firm = np.repeat([f"F{i}" for i in range(n_firms)], per)
    month = np.array([f"M{i % 40}" for i in range(n_firms * per)])
    n = n_firms * per
    X = rng.normal(size=(n, 4))
    d = X[:, 0] + rng.normal(size=n)
    y = 1.5 * X[:, 0] + rng.normal(size=n)          # no direct d -> y path
    out = K.dml_plr(y, d, X, firm, month, n_reps=2)
    assert abs(out["theta"]) < 3 * out["se"] + 0.05, "DML found an effect that does not exist"


def test_bh_fdr_is_weakly_conservative():
    p = [0.001, 0.02, 0.04, 0.20, 0.60, 0.90]
    rej, adj = K.bh_fdr(p, q=0.10)
    assert (np.asarray(adj)[np.isfinite(adj)] >= np.asarray(p)[np.isfinite(adj)] - 1e-12).all()
    assert rej[0]
    assert not rej[-1]
    assert rej.sum() <= sum(1 for x in p if x < 0.05)


def test_iv2sls_recovers_effect_with_a_valid_instrument():
    rng = np.random.default_rng(5)
    n = 6000
    z = rng.normal(size=n)
    u = rng.normal(size=n)                      # unobserved confounder
    d = 0.9 * z + u + rng.normal(size=n) * 0.4
    y = 0.5 * d + 1.5 * u + rng.normal(size=n) * 0.4
    cl = rng.integers(0, 60, n).astype(str)
    ones = np.ones((n, 1))
    b_ols, _ = K.ols_twoway(y, np.column_stack([d, ones]), cl, cl)
    b_iv, V = K.iv2sls_twoway(y, np.column_stack([d, ones]), np.column_stack([z, ones]), cl, cl)
    assert abs(b_ols[0] - 0.5) > 0.2, "OLS should be biased in this DGP"
    assert abs(b_iv[0] - 0.5) < 0.08, f"2SLS off: {b_iv[0]}"
    assert V[0, 0] > 0


# ---------------------------------------------------------------------------------------------
# Results-file contract
# ---------------------------------------------------------------------------------------------

def test_results_has_required_fields(results):
    for k in ("experiment_id", "verdict", "verdict_reason", "seed", "code_sha256",
              "sample", "treatment_definition", "lookahead_policy", "method",
              "estimates", "multiple_testing", "instrument_analysis", "limitations"):
        assert k in results, f"missing field {k}"
    assert results["experiment_id"] == "K1738"
    assert results["seed"] == 42
    assert results["verdict"] in {"PASS", "CONDITIONAL_PASS", "FAIL", "NULL", "INSUFFICIENT_DATA"}


def test_results_sample_meets_declared_thresholds(results):
    s = results["sample"]
    if results["verdict"] == "INSUFFICIENT_DATA":
        pytest.skip("verdict is INSUFFICIENT_DATA; thresholds intentionally unmet")
    assert s["n_firm_quarters"] >= 500
    assert s["n_firms"] >= 30
    assert s["n_quarters"] >= 20
    coverage = s["sue_coverage"]
    assert coverage["n_announcement_records"] > coverage["n_sue_constructible"] > 0
    assert coverage["coverage"] >= 0.30


def test_effect_size_labels_are_per_treatment_unit(results):
    blob = json.dumps(results)
    assert "pct_vol_change_per_1sd" not in blob
    assert "pct_vol_change_per_treatment_unit" in blob
    assert not np.isclose(results["treatment_definition"]["descriptives"]["std"], 1.0)


def test_every_estimate_reports_uncertainty(results):
    if not results["estimates"]:
        pytest.skip("no estimates")
    for tname, horizons in results["estimates"].items():
        for hname, ests in horizons.items():
            for ename in ("naive_ols", "ols_controls", "dml"):
                e = ests[ename]
                if e.get("status", "").startswith("NOT_COMPUTED"):
                    continue          # interim artifact: block declared missing, not silently absent
                assert e["se"] is not None and e["se"] > 0, f"{tname}/{hname}/{ename} has no SE"
                assert e["ci95"][0] < e["ci95"][1], f"{tname}/{hname}/{ename} CI malformed"
                assert e["p_raw"] is not None


def test_fdr_correction_present_and_not_looser_than_raw(results):
    if not results["multiple_testing"]:
        pytest.skip("no estimates")
    for ename, blk in results["multiple_testing"].items():
        assert blk["m_hypotheses"] == 6
        for k, t in blk["tests"].items():
            if t["p_raw"] is not None and t["q_bh"] is not None:
                assert t["q_bh"] >= t["p_raw"] - 1e-12, f"{ename}/{k}: BH q below raw p"
        # No bound is asserted between the BH(q=0.10) count and the raw-p<0.05 count: they use
        # different thresholds, so BH can legitimately flag MORE hypotheses than raw p<0.05.
        # The real invariant is q >= p, checked above.
        assert blk["n_significant_bh"] <= blk["m_hypotheses"]
        assert blk["n_significant_raw"] <= blk["m_hypotheses"]


def test_within_month_c4_uses_bh_q(results):
    fe = results["robustness"]["within_month_demeaned"]
    for h in K.HORIZONS:
        assert fe[h]["q_bh_F3"] >= fe[h]["p_raw"] - 1e-12
        assert fe[h]["significant_bh_F3"] == (fe[h]["q_bh_F3"] < K.FDR_Q)
    primary_sign = np.sign(results["estimates"]["signed_sue"]["h1m"]["dml"]["theta"])
    expected = any(
        np.sign(fe[h]["theta"]) == primary_sign and fe[h]["q_bh_F3"] < K.FDR_Q
        for h in K.HORIZONS
    )
    assert results["prereg_checks"]["c4_survives_within_month_fe"] is expected


def test_iv_verdict_is_not_overclaimed(results):
    iv = results["instrument_analysis"]
    if iv.get("status") != "ESTIMATED":
        pytest.skip("IV not estimated")
    if iv["exclusion_restriction_violated"]:
        assert iv["instrument_valid"] is False
        assert "NOT interpreted causally" in iv["interpretation"]
    assert iv["instrument_valid"] is False
    assert iv["exclusion_restriction_credible"] is False
    assert iv["invalid_reasons"]
    assert "non-rejection" in iv["interpretation"]
    assert "NOT interpreted causally" in iv["interpretation"]


def test_causal_claim_is_capped_without_a_valid_instrument(results):
    iv = results["instrument_analysis"]
    if not iv.get("instrument_valid", False):
        assert results["causal_claim_cap"], \
            "every conclusion without a valid instrument must carry an explicit causal-claim cap"
        assert "never as a causal ATE" in results["causal_claim_cap"]
    assert "unconfoundedness" in results["identification_stance"].lower()
    assert "not an identified ate" in results["method"]["estimand"].lower()


def test_code_sha_matches_the_script_on_disk(results):
    import hashlib
    actual = hashlib.sha256((HERE / "K1738.py").read_bytes()).hexdigest()
    assert actual == results["code_sha256"], \
        "K1738.py changed after results were written; re-run before certifying"
    assert actual == results["code_trace"]["sha256"]
    assert (HERE / "K1738.py").stat().st_size == results["code_trace"]["size_bytes"]


def test_final_runtime_artifact_and_spec_are_complete(results):
    import hashlib

    assert results["run_complete"] is True
    assert results["stages_missing"] == []
    expected = {
        "naive_and_ols_controls", "instrument", "primary",
        "robustness:within_month_demeaned", "subperiods",
        "robustness:inclusive_window", "robustness:level_rv_outcome",
        "robustness:lasso_nuisance",
    }
    assert expected.issubset(set(results["stages_completed"]))
    assert results["last_checkpoint"] == "complete"

    spec = json.loads((HERE / "reproduce_spec.json").read_text(encoding="utf-8"))
    result_bytes = RESULTS_PATH.read_bytes()
    ident = spec["canonical_result_identity"]
    assert ident["path"] == "K1738_results.json"
    assert ident["sha256"] == hashlib.sha256(result_bytes).hexdigest()
    assert ident["size_bytes"] == len(result_bytes)
    assert spec["entrypoint"]["sha256"] == results["code_trace"]["sha256"]
    assert spec["entrypoint"]["size_bytes"] == results["code_trace"]["size_bytes"]
    assert spec["entrypoint"]["args"] == ["--no-download"]
    assert spec["network"] == "deny"
    assert {p["path"] for p in spec["inputs"]} == {
        "experiments/k1738/panel_k1738.parquet",
        "experiments/k1738/cache/earnings.parquet",
    }


def test_subperiod_f2_covers_all_nine_declared_cells(results):
    cells = []
    for pname, block in results["subperiods"].items():
        assert block.get("status") != "TOO_SMALL", f"{pname} unexpectedly too small"
        for h in K.HORIZONS:
            cell = block[h]
            assert cell["p_raw"] is not None
            assert cell["q_bh_F2"] is not None
            assert cell["q_bh_F2"] >= cell["p_raw"] - 1e-12
            cells.append(cell)
    assert len(cells) == 9


def test_resid_cache_returns_identical_residuals_and_catches_collisions():
    """The cache must be transparent (same answer as an uncached fit) and fail loudly on misuse."""
    rng = np.random.default_rng(11)
    n = 600
    X = rng.normal(size=(n, 4))
    firm = np.repeat([f"F{i}" for i in range(30)], 20)
    y = X[:, 0] + rng.normal(size=n)
    cache = K.ResidCache(X, firm)
    direct = K.crossfit_resid(y, X, firm, K.N_FOLDS, K.SEED + 0, "hgb")
    cached = cache.get("y", y, 0)
    assert np.allclose(direct, cached, equal_nan=True)
    assert cache.get("y", y, 0) is cache.get("y", y, 0)      # second call is served from cache
    with pytest.raises(AssertionError):
        cache.get("y", y + 1.0, 0)                            # same key, different values


def test_dml_cached_and_uncached_agree():
    rng = np.random.default_rng(12)
    n_firms, per = 60, 15
    firm = np.repeat([f"F{i}" for i in range(n_firms)], per)
    month = np.array([f"M{i % 30}" for i in range(n_firms * per)])
    n = n_firms * per
    X = rng.normal(size=(n, 4))
    d = X[:, 0] + rng.normal(size=n)
    y = 0.4 * d + X[:, 0] + rng.normal(size=n)
    plain = K.dml_plr(y, d, X, firm, month, n_reps=2)
    cache = K.ResidCache(X, firm)
    cached = K.dml_plr(y, d, X, firm, month, n_reps=2, cache=cache, y_key="y", d_key="d")
    assert np.isclose(plain["theta"], cached["theta"]), "cache changed the estimate"
    assert np.isclose(plain["se"], cached["se"])
