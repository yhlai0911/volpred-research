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

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_dm_hac_lag import (  # noqa: E402
    CANONICAL_LIKE,
    DEGENERATE,
    NO_HAC,
    NOT_A_TEST,
    RATCHET_VERDICTS,
    scan_population,
)

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


def test_paper_side_experiments_are_in_population(findings) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    assert verdicts[
        "paper/taiwan-vt/experiments/k849_har_rv_taifex.py::dm_test"
    ] == CANONICAL_LIKE


def test_result_readers_do_not_masquerade_as_dm_tests(findings) -> None:
    verdicts = {_site_key(f): f.verdict for f in findings}
    assert verdicts["experiments/k1203/k1203.py::plot_dm_bar_eem"] == NOT_A_TEST


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
