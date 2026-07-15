"""Mechanical gate for the DM HAC bandwidth bug class (K1655, 2026-07-11).

A local Diebold-Mariano helper that computes its Newey-West correction with
``for k in range(1, h)`` applies *no* correction at h == 1, because the loop is
empty. That is the textbook one-step DM, and it is only wrong when the loss
differential is genuinely autocorrelated -- but when it is (K1655: acf(1) = 0.68
from a persistent predictor), it inflates |t| and manufactures significance. The
canonical helper, ``volpred.stats.model_evaluation.dm_test``, floors its
bandwidth at 1 and scales it with the sample, so it never degenerates.

This is a RATCHET, not a clean-tree assertion. Pre-existing sites are frozen into
a baseline; re-running and correcting them is tracked separately. What the gate
enforces is that the class cannot GROW: a newly written local DM with either an
h=1-degenerate bandwidth or no HAC at all fails CI, and every site removed from
the baseline can never come back.

Per anti-stacking, this is the single enforcement owner for this concern. Do not
add a second watchdog -- extend this one.

Run:
    uv run --extra dev python -m pytest scripts/tests/test_dm_hac_lag_ratchet.py -v

To retire a site after fixing and re-running it:
    uv run python scripts/audit_dm_hac_lag.py --json /tmp/a.json
    # then drop its "<file>::<function>" key from the baseline below
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_dm_hac_lag import (  # noqa: E402
    CANONICAL_LIKE,
    DEGENERATE,
    DELEGATES,
    DEPENDENCE_ROBUST,
    NO_HAC,
    NOT_A_TEST,
    RATCHET_VERDICTS,
    UNKNOWN,
    _classify_lag_expr,
    _scan_function,
    scan_population,
)
from audit_dm_hac_lag import REPO_ROOT as AUDIT_REPO_ROOT  # noqa: E402


def _verdict_of_source(src: str, fn_name: str) -> str:
    """Classify a single synthetic DM helper the way scan_file would."""
    tree = ast.parse(src)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == fn_name
    )
    finding = _scan_function(
        fn, AUDIT_REPO_ROOT / "experiments" / "synthetic.py", False, set()
    )
    assert finding is not None
    return finding.verdict

BASELINE_PATH = REPO_ROOT / "storage" / "ops" / "dm_hac_lag_baseline.json"


def _site_key(finding) -> str:
    return f"{finding.file}::{finding.function}"


@pytest.fixture(scope="module")
def findings():
    return scan_population()


@pytest.fixture(scope="module")
def affected_sites(findings) -> set[str]:
    return {_site_key(f) for f in findings if f.verdict in RATCHET_VERDICTS}


@pytest.fixture(scope="module")
def baseline_payload() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline(baseline_payload: dict) -> set[str]:
    return set(baseline_payload["degenerate_sites"]) | set(
        baseline_payload.get("blindspot_sites", [])
    )


@pytest.fixture(scope="module")
def retired(baseline_payload: dict) -> set[str]:
    return {entry["site"] for entry in baseline_payload.get("retired", [])}


def test_no_new_degenerate_dm(affected_sites: set[str], baseline: set[str]) -> None:
    """A newly written local DM must not omit HAC correction."""
    new_sites = affected_sites - baseline
    assert not new_sites, (
        "New local DM implementation(s) omit HAC or use an h=1-degenerate "
        "bandwidth:\n\n"
        + "\n".join(f"  - {s}" for s in sorted(new_sites))
        + "\n\nUse volpred.stats.model_evaluation.dm_test, whose bandwidth is "
        "max(1, min(ceil(h**(1/3) * n**(1/3)), n // 4)). If you must write a local "
        "helper, floor the bandwidth at the canonical value -- never at h - 1. "
        "See .claude/rules/experiments.md, 'DM 的 HAC 落後期不可只用 h-1'."
    )


def test_baseline_only_contains_active_sites(
    affected_sites: set[str], baseline: set[str]
) -> None:
    """A repaired site must be pruned rather than left as stale baseline debt."""
    stale = baseline - affected_sites
    assert not stale, (
        f"{len(stale)} baseline entries are already clean; prune them from "
        f"{BASELINE_PATH.name}: {sorted(stale)[:5]}"
    )


def test_retired_sites_cannot_resurrect(
    affected_sites: set[str], baseline: set[str], retired: set[str]
) -> None:
    """The old test used an always-empty set expression; retired is the memory."""
    assert baseline.isdisjoint(retired), "Active baseline and retired ledger overlap"
    resurrected = affected_sites & retired
    assert not resurrected, f"Fixed sites regressed: {sorted(resurrected)}"


def test_baseline_metadata_matches_frozen_cohorts(baseline_payload: dict) -> None:
    """The one-time blind-spot expansion stays explicit and auditable."""
    original = baseline_payload["degenerate_sites"]
    blindspots = baseline_payload["blindspot_sites"]

    assert original == sorted(set(original))
    assert blindspots == sorted(set(blindspots))
    assert set(original).isdisjoint(blindspots)
    assert baseline_payload["original_cohort_count"] == len(original)
    assert baseline_payload["blindspot_cohort_count"] == len(blindspots)
    assert baseline_payload["count"] == len(original) + len(blindspots)


def test_known_blind_spots_are_now_classified(findings) -> None:
    """Regression coverage for the six variants found by the paper deep review."""
    verdicts = {_site_key(f): f.verdict for f in findings}

    assert verdicts[
        "experiments/k730/k730_cross_asset_vol_momentum.py::dm_test_func"
    ] == DEGENERATE
    assert verdicts["experiments/k731/k731_vix_term_structure.py::dm_test"] == NO_HAC
    assert verdicts["experiments/k1116b/k1116b.py::dm_hln"] == NO_HAC
    assert verdicts["experiments/k1203/k1203.py::dm_hln"] == NO_HAC
    assert verdicts[
        "experiments/k1116c/k1116c_clark_west.py::one_sample_t"
    ] == NO_HAC
    assert verdicts[
        "experiments/k751/k751_overnight_vix_news.py::<module>:ttest_1samp@416"
    ] == NO_HAC


def test_paper_review_named_hac_debt_is_frozen(findings, baseline) -> None:
    """VIX-sufficiency and EAV sites named by the deep review stay visible."""
    verdicts = {_site_key(f): f.verdict for f in findings}
    expected = {
        "experiments/k1148_d2/k1148_d2.py::dm_hln_stat": NO_HAC,
        "experiments/k1149/k1149.py::dm_hln": NO_HAC,
        "paper/vix-sufficiency/experiments/k730_cross_asset_vol_momentum.py::dm_test_func": DEGENERATE,
        "paper/vix-sufficiency/experiments/k731_vix_term_structure.py::dm_test": NO_HAC,
        "paper/vix-sufficiency/experiments/k828_vix_only_insurance.py::manual_dm_test": NO_HAC,
    }

    for site, verdict in expected.items():
        assert verdicts[site] == verdict
        assert site in baseline


def test_paper_side_experiments_are_in_population(findings) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    assert verdicts[
        "paper/taiwan-vt/experiments/k849_har_rv_taifex.py::dm_test"
    ] == CANONICAL_LIKE

    assert verdicts[
        "paper/taiwan-vt/experiments/k844_futures_vs_stock_vt.py::<module>:ttest_1samp@570"
    ] == NO_HAC


def test_zero_floor_is_not_mistaken_for_positive_floor() -> None:
    assert _classify_lag_expr("max(0, h - 1)")[0] == DEGENERATE
    assert _classify_lag_expr("max(horizon - 1, 0)")[0] == DEGENERATE
    assert _classify_lag_expr("max(1, h - 1)")[0] == CANONICAL_LIKE
    assert _classify_lag_expr("max(h - 1, 1)")[0] == CANONICAL_LIKE


def test_zero_floor_and_h1_branch_variants_are_frozen(findings, baseline) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    sites = {
        "experiments/K1618/K1618.py::dm_hln",
        "experiments/k1301/k1301_har_rs.py::dm_hln",
        "experiments/k1309/k1309.py::dm_hln",
        "experiments/k1316/k1316.py::dm_hln",
        "experiments/k1432/k1432_tw_financial_stress.py::dm_test",
        "experiments/k1600/k1600.py::dm_hln",
        "experiments/k1605/k1605_formal.py::dm_test",
        "experiments/k1682/k1682.py::hln_dm",
        "experiments/k1683/k1683.py::hln_dm",
        "experiments/k782/k782_har_5d_rv.py::dm_test",
        "experiments/k782v2/k782v2_har_5d_rv.py::dm_test",
        "experiments/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har/research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har.py::dm_hln",
    }
    for site in sites:
        assert verdicts[site] == DEGENERATE
        assert site in baseline


def test_manual_hac_and_canonical_wrappers_are_not_false_positives(findings) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    assert verdicts[
        "experiments/K1424_hurst_garch_covariate/K1424_hurst_garch_covariate.py::dm_test"
    ] == CANONICAL_LIKE
    assert verdicts["experiments/k797/k797_kan_garch.py::dm_test"] == CANONICAL_LIKE
    assert verdicts[
        "experiments/k797v2/k797v2_kan_garch.py::dm_test"
    ] == CANONICAL_LIKE
    assert verdicts["experiments/k1337/K1337.py::dm_test_hac"] == UNKNOWN
    assert verdicts["experiments/K1611/K1611.py::dm_hln"] == CANONICAL_LIKE
    assert verdicts[
        "experiments/k507/k507_dynamic_allocation.py::diebold_mariano_test"
    ] == DELEGATES
    assert verdicts[
        "experiments/k436/k436_vrp_robustness.py::block_bootstrap_dm"
    ] == DEPENDENCE_ROBUST


def test_result_readers_do_not_masquerade_as_dm_tests(findings) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    assert verdicts["experiments/k1203/k1203.py::plot_dm_bar_eem"] == NOT_A_TEST
    assert verdicts["experiments/K1404/K1404.py::classify_dm_status"] == NOT_A_TEST


def test_canonical_dm_does_not_degenerate_at_h1() -> None:
    """The canonical helper keeps a real HAC correction at h == 1."""
    import numpy as np

    from volpred.stats.model_evaluation import dm_test

    rng = np.random.default_rng(1655)
    n = 500
    # A strongly autocorrelated loss differential -- exactly the case where the
    # h-1 rule silently drops the correction and inflates |t|.
    noise = rng.standard_normal(n)
    d = np.zeros(n)
    for i in range(1, n):
        d[i] = 0.7 * d[i - 1] + noise[i]
    d += 0.15

    t_hac, _ = dm_test(d, np.zeros(n), h=1)

    # The naive h=1 statistic with no HAC term, for comparison.
    t_naive = d.mean() / np.sqrt(d.var(ddof=1) / n)

    assert abs(t_hac) < abs(t_naive), (
        "Canonical dm_test at h=1 should widen the standard error on an "
        f"autocorrelated differential (|t_hac|={abs(t_hac):.2f} should be below "
        f"the no-HAC |t|={abs(t_naive):.2f}); if it does not, the canonical "
        "bandwidth floor has regressed."
    )


def test_manual_variance_idiom_is_no_hac(findings, baseline) -> None:
    """k1379 hand-computes gamma0 = np.mean(d**2) - d_bar**2 with no HAC loop.

    PLAIN_VARIANCE_RE only saw np.var / np.std, so this idiom -- treating the
    plain sample variance as the DM long-run variance (zero HAC correction) --
    fell through to ``unknown``. Freeze the classification so the extended
    detection cannot silently regress back into the blind spot.
    """
    verdicts = {_site_key(f): f.verdict for f in findings}
    site = "experiments/k1379/k1379.py::dm_test"
    assert verdicts[site] == NO_HAC
    assert site in baseline


def test_manual_variance_regex_regression() -> None:
    """The E[X^2]-E[X]^2 idiom is no_hac; the deviation form + HAC loop is not."""
    # Every equivalent way to write the squared mean must classify as no_hac.
    for squared_mean in ("d_bar**2", "np.mean(d)**2", "d.mean()**2", "d_bar ** 2"):
        src = (
            "import numpy as np\n"
            "from scipy import stats\n"
            "def dm_test(d):\n"
            "    T = len(d)\n"
            "    d_bar = np.mean(d)\n"
            f"    gamma0 = np.mean(d**2) - {squared_mean}\n"
            "    dm_stat = d_bar / np.sqrt(gamma0 / T)\n"
            "    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))\n"
            "    return float(dm_stat), float(p_val)\n"
        )
        assert _verdict_of_source(src, "dm_test") == NO_HAC, squared_mean

    # A genuine gamma0 + Bartlett autocovariance loop must NOT be mistaken for
    # no_hac just because gamma0 is written out longhand: the deviation form has
    # inner parens after mean( and the serial-lag loop is the backstop guard.
    hac_src = (
        "import numpy as np\n"
        "def dm_test(d, h):\n"
        "    d_bar = np.mean(d)\n"
        "    gamma0 = np.mean((d - d_bar)**2)\n"
        "    for k in range(1, h + 1):\n"
        "        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))\n"
        "        gamma0 += 2 * (1 - k / (h + 1)) * gamma_k\n"
        "    dm_stat = d_bar / np.sqrt(gamma0 / len(d))\n"
        "    return float(dm_stat)\n"
    )
    assert _verdict_of_source(hac_src, "dm_test") != NO_HAC
