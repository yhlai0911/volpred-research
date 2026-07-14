"""Mechanical gate for the raw-MDD scale-artifact bug class (K1702 / K1265b, 2026-07-13).

THE BUG CLASS
-------------
Raw max drawdown is not comparable across two return series that run at different
exposure.  A vol-managed / de-levered / partially-in-cash strategy shows a shallower
drawdown for purely arithmetic reasons -- "took less risk", not "timed risk well".
Anyone can reproduce the entire "benefit" by scaling their position down.

  K1702 §5.4 : factor zoo -- raw MDD improved 5/6 factors; per unit of realized
               volatility, only 1/6.  R3's "MDD improvement is robust" was a scale artifact.
  K1265b     : SPY VIX-managed -- K1265's headline "50-62% MDD reduction" shrinks to a
               9.8-22.1pp gap against a benchmark carrying the SAME realized volatility,
               and no spec survives Holm correction against a circular-shift null.

WHAT IS ENFORCED
----------------
1. RUNTIME (the substantive rule): if two series' realized volatilities differ by more
   than 20%, a raw-MDD comparison is not reportable on its own.
   Owner: ``volpred.stats.drawdown.compare_max_drawdown`` /
   ``assert_drawdown_comparison_is_fair``.  Tested here directly, including the
   property that a PURE de-levering earns a ~zero exposure-matched gap -- which is the
   whole point: if the gate did not have that property it would not detect the artifact.

2. STATIC (the ratchet): no AST can evaluate "vols differ by 20%", so the statically
   checkable version is -- a site that compares drawdowns across series must ALSO compute
   a scale-invariant companion.  455 pre-existing sites are frozen into a baseline.  The
   class may not GROW: a newly written raw-MDD comparison fails CI, and a site retired
   from the baseline can never come back.

Per anti-stacking this is the SINGLE enforcement owner for this concern.  Do not add a
second watchdog -- extend this one.

Run:
    uv run --extra dev python -m pytest scripts/tests/test_mdd_scale_artifact_ratchet.py -v

To retire a site after fixing it:
    uv run python scripts/audit_mdd_scale_artifact.py --json /tmp/a.json
    # drop its "<file>::<scope>" key from storage/ops/mdd_scale_artifact_baseline.json
    # and append it to "retired"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from audit_mdd_scale_artifact import (  # noqa: E402
    RATCHET_VERDICTS,
    classify_scope,
    scan_file,
    scan_population,
)
from volpred.stats.drawdown import (  # noqa: E402
    VOL_MISMATCH_THRESHOLD,
    RawDrawdownComparisonError,
    assert_drawdown_comparison_is_fair,
    compare_max_drawdown,
    max_drawdown,
)

BASELINE_PATH = REPO_ROOT / "storage" / "ops" / "mdd_scale_artifact_baseline.json"

CANDIDATE_ROOT_RAW_FIXTURE = """
def compare(strategy_returns, buy_hold_returns):
    mdd = max_drawdown(strategy_returns)
    bh_mdd = max_drawdown(buy_hold_returns)
    return {"delta_mdd": mdd - bh_mdd}
"""


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


@pytest.fixture(scope="module")
def findings():
    return scan_population()


# ---------------------------------------------------------------------------
# 1. The runtime rule -- the part that actually implements ">20% vol gap"
# ---------------------------------------------------------------------------
def _spy_like(n: int = 3000, seed: int = 42) -> np.ndarray:
    """A return path with volatility clustering and a long, deep drawdown episode."""
    rng = np.random.default_rng(seed)
    vol = np.empty(n)
    vol[0] = 0.01
    for t in range(1, n):  # crude GARCH-ish persistence so drawdowns are contiguous
        vol[t] = np.sqrt(1e-6 + 0.90 * vol[t - 1] ** 2 + 0.08 * (vol[t - 1] * rng.normal()) ** 2)
    r = rng.normal(0.0003, 1.0, n) * vol
    r[1200:1450] -= 0.004  # a sustained bear episode
    return r


def test_pure_deleveraging_shows_a_raw_mdd_improvement_that_is_entirely_fake():
    """The defining property of the bug class, asserted as a fact.

    Halve your exposure every single day -- zero skill, zero timing -- and the raw max
    drawdown improves substantially.  The exposure-matched gap sees through it and
    returns 0.

    Honest note: for a CONSTANT rescaling the gap is zero by algebra, not by empirical
    luck (lambda resolves to exactly 0.5, so the matched benchmark IS the strategy).
    That makes this a regression guard on the implementation rather than a discriminating
    test -- and it is also precisely WHY exposure-matching is the right instrument.  The
    discriminating test is the next one.
    """
    bh = _spy_like()
    dumb = 0.5 * bh  # constant leverage: no information, no timing, just less risk

    cmp = compare_max_drawdown(dumb, bh)

    # the artifact: raw MDD looks much better
    assert cmp.raw_mdd_improvement > 0.05, "constant de-levering should shallow the raw MDD"
    assert cmp.exposure_mismatch, "a 2x exposure gap must be flagged"

    # the truth: against a same-risk benchmark there is nothing there
    assert abs(cmp.exposure_matched_gap) < 1e-9, (
        "a pure de-levering must earn a ZERO exposure-matched gap; "
        f"got {cmp.exposure_matched_gap}"
    )


def test_a_positive_exposure_matched_gap_is_not_by_itself_evidence_of_timing():
    """The counter-intuitive fact that this whole audit turns on -- pinned as a test.

    Matching REALIZED VOLATILITY is not enough.  A strategy whose weights are merely
    DISPERSED earns a positive exposure-matched gap even when its timing is exactly
    BACKWARDS, because dispersed weights concentrate risk into bursts, and a bursty path
    accumulates a shallower peak-to-trough drawdown than a constant-volatility path of the
    same unconditional volatility.  Drawdowns are built by sustained bleeding, not by
    isolated spikes.

    Consequence, and the reason this is a test and not a comment: `gap > 0` is NECESSARY
    but NOT SUFFICIENT for "the drawdown reduction is not just mechanical".  The only
    honest inference is gap-vs-its-own-shift-null (see experiments/k1265b).  An earlier
    draft of this very sweep wrote "3/3 gaps positive, therefore not purely mechanical" --
    this test exists so that nobody, including a future me, can make that leap again.
    """
    bh = _spy_like()
    turbulent = np.abs(bh) > np.quantile(np.abs(bh), 0.70)

    # exactly wrong timing: lever UP into turbulence, cut risk when calm. Same dosage.
    anti_timing = np.where(turbulent, 1.0, 0.4) * bh

    gap = compare_max_drawdown(anti_timing, bh).exposure_matched_gap
    assert gap > 0, (
        "the premise of this test has changed: an anti-timing dispersed-weight strategy is "
        f"expected to STILL earn a positive exposure-matched gap, got {gap:.4f}. If this now "
        "fails, re-derive the k1265b conclusions -- the instrument behaves differently."
    )


def test_equal_exposure_comparison_is_not_flagged():
    bh = _spy_like()
    other = _spy_like(seed=7) * 1.05  # 5% vol difference: within tolerance
    cmp = compare_max_drawdown(other, bh)
    assert not cmp.exposure_mismatch
    assert cmp.raw_mdd_improvement_is_reportable_alone
    assert_drawdown_comparison_is_fair(other, bh)  # must not raise


def test_assert_raises_on_a_material_exposure_gap():
    bh = _spy_like()
    with pytest.raises(RawDrawdownComparisonError, match="different exposure"):
        assert_drawdown_comparison_is_fair(0.5 * bh, bh)


def test_threshold_boundary():
    bh = _spy_like()
    inside = compare_max_drawdown((1.0 - VOL_MISMATCH_THRESHOLD + 0.01) * bh, bh)
    outside = compare_max_drawdown((1.0 - VOL_MISMATCH_THRESHOLD - 0.01) * bh, bh)
    assert not inside.exposure_mismatch
    assert outside.exposure_mismatch


def test_max_drawdown_counts_a_first_period_loss():
    """K1265 and K1702 both omit the initial wealth of 1.0, hiding a leading loss."""
    assert max_drawdown(np.array([-0.10, 0.0, 0.0])) == pytest.approx(-0.10)


def test_misaligned_series_are_refused():
    with pytest.raises(ValueError, match="aligned"):
        compare_max_drawdown(np.zeros(10), np.zeros(11))


# ---------------------------------------------------------------------------
# 2. The static classifier -- does it recognise the shapes?
# ---------------------------------------------------------------------------
def test_classifier_flags_a_naked_raw_mdd_comparison():
    src = """
def evaluate(strategy_returns, buy_hold_returns):
    wealth = (1 + strategy_returns).cumprod()
    mdd = (wealth / wealth.cummax() - 1).min()
    bh_wealth = (1 + buy_hold_returns).cumprod()
    bh_mdd = (bh_wealth / bh_wealth.cummax() - 1).min()
    return {"mdd": mdd, "mdd_bh": bh_mdd, "improvement": mdd - bh_mdd}
"""
    verdict, _ = classify_scope(src, module_delegates=False)
    assert verdict in RATCHET_VERDICTS


def test_classifier_accepts_a_scale_invariant_comparison():
    src = """
def evaluate(strategy_returns, buy_hold_returns, vol_s, vol_b):
    wealth = (1 + strategy_returns).cumprod()
    mdd = (wealth / wealth.cummax() - 1).min()
    mdd_per_annual_vol = mdd / vol_s
    return {"mdd": mdd, "mdd_per_annual_vol": mdd_per_annual_vol}
"""
    verdict, _ = classify_scope(src, module_delegates=False)
    assert verdict not in RATCHET_VERDICTS


def test_classifier_ignores_prose_that_merely_says_drawdown():
    src = '''
def tag_article(article):
    """Tag the article; topics include drawdown, mdd and buy_hold."""
    # drawdown vs buy_hold is a common topic
    return ["drawdown", "mdd", "buy_hold"]
'''
    verdict, _ = classify_scope(src, module_delegates=False)
    assert verdict == "", "a tag list is not a drawdown computation"


def test_scan_file_keys_sites_to_the_candidate_root(tmp_path: Path) -> None:
    path = tmp_path / "experiments" / "k9995" / "k9995.py"
    path.parent.mkdir(parents=True)
    path.write_text(CANDIDATE_ROOT_RAW_FIXTURE, encoding="utf-8")

    findings = scan_file(path, tmp_path)

    assert [finding.key() for finding in findings] == [
        "experiments/k9995/k9995.py::compare"
    ]
    assert findings[0].verdict in RATCHET_VERDICTS


# ---------------------------------------------------------------------------
# 3. The ratchet -- the class may not grow
# ---------------------------------------------------------------------------
def test_baseline_is_intact(baseline):
    assert baseline["count"] == len(baseline["sites"])
    assert len(set(baseline["sites"])) == len(baseline["sites"]), "duplicate keys in baseline"


def test_no_new_raw_mdd_comparison_sites(findings, baseline):
    frozen = set(baseline["sites"])
    current = {f.key() for f in findings if f.verdict in RATCHET_VERDICTS}
    new = sorted(current - frozen)
    assert not new, (
        f"{len(new)} NEW raw-MDD-comparison site(s) introduced.\n\n"
        + "\n".join(f"  - {k}" for k in new[:20])
        + "\n\nRaw max drawdown is not comparable across series at different exposure "
        "(K1702 §5.4, K1265b). Either compare at matched exposure, or report the "
        "scale-invariant companion.\n"
        "Canonical helper: volpred.stats.drawdown.compare_max_drawdown()\n"
        "Audit: uv run python scripts/audit_mdd_scale_artifact.py --violations-only"
    )


def test_retired_sites_never_come_back(findings, baseline):
    retired = set(baseline.get("retired", []))
    if not retired:
        pytest.skip("nothing retired yet")
    current = {f.key() for f in findings if f.verdict in RATCHET_VERDICTS}
    regressed = sorted(retired & current)
    assert not regressed, f"previously-fixed sites regressed: {regressed}"


def test_ratchet_only_shrinks(findings, baseline):
    current = {f.key() for f in findings if f.verdict in RATCHET_VERDICTS}
    assert len(current) <= baseline["count"], (
        f"class grew from {baseline['count']} to {len(current)} sites"
    )
