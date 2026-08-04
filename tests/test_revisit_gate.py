"""Tests for the power-based revisit gate (src/volpred/research/revisit_gate.py).

The bug being locked out: a checkpoint pipeline shipping a revisit condition
that cannot separate the hypotheses it is gating. K1325 observed DM-HLN
t = 0.883 at n_test = 18 and the old gate promised to re-run at n_test = 50 --
a point where the extrapolated |t| is ~1.47, against a |t| > 3 bar.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.research.revisit_gate import (  # noqa: E402
    GatePolicy,
    GateVerdict,
    PipelineSplit,
    evaluate_gate,
    evaluate_registered_pipeline,
    implied_total_days,
    load_registry,
    required_test_days,
)

TW50 = "tw50_5min_har_rv"
# K1325's measured checkpoint, the case that motivated this module.
K1325_T = 0.882689
K1325_N_TEST = 18


def test_required_test_days_matches_published_extrapolation():
    """208 test days is the number the public article committed to."""
    assert required_test_days(K1325_T, K1325_N_TEST, 3.0) == 208


def test_required_days_scale_as_inverse_square_of_t():
    """Halving the observed effect quadruples the sample needed."""
    strong = required_test_days(2.0, 100, 3.0)
    weak = required_test_days(1.0, 100, 3.0)
    assert weak == 4 * strong


def test_zero_effect_is_unreachable_not_a_huge_number():
    assert required_test_days(0.0, 50, 3.0) is None


def test_required_test_days_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        required_test_days(1.0, 0, 3.0)
    with pytest.raises(ValueError):
        required_test_days(1.0, 50, 0.0)


def test_implied_total_days_adds_warmup_after_scaling_by_split():
    split = PipelineSplit(test_fraction=0.3, warmup_days=22)
    # 208 / 0.3 = 693.34 -> 694 usable rows, plus the 22-day HAR warm-up.
    assert implied_total_days(208, split) == 716


def test_old_50_day_trigger_could_not_have_reached_the_bar():
    """The regression this module exists to prevent.

    At the old trigger point the extrapolated |t| is ~1.47 -- so firing the
    gate at n_test = 50 buys a re-run that reproduces the same verdict.
    """
    implied_t = K1325_T * math.sqrt(50 / K1325_N_TEST)
    assert 1.4 < implied_t < 1.55
    assert implied_t < 3.0


def _k1325_gate(**overrides):
    kwargs = dict(
        pipeline=TW50,
        observed_abs_t=K1325_T,
        observed_test_days=K1325_N_TEST,
        split=PipelineSplit(test_fraction=0.3, warmup_days=22),
        policy=GatePolicy(),
        current_total_days=82,
    )
    kwargs.update(overrides)
    return evaluate_gate(**kwargs)


def test_k1325_case_demands_a_design_change_not_a_wait():
    gate = _k1325_gate()
    assert gate.verdict == GateVerdict.DESIGN_CHANGE_REQUIRED
    assert gate.gate_passed is False
    assert gate.required_test_days == 208
    assert gate.required_total_days == 716
    assert gate.additional_trading_days_needed == 634


def test_reachable_shortfall_is_a_wait_not_a_design_change():
    gate = _k1325_gate(observed_abs_t=2.0, observed_test_days=90, current_total_days=320)
    assert gate.verdict == GateVerdict.WAIT_FOR_DATA
    assert gate.required_test_days == 203
    assert 0 < gate.additional_trading_days_needed <= gate.policy["max_wait_trading_days"]


def test_floor_blocks_a_large_t_on_a_tiny_window():
    """A big |t| on 12 test days must not open the gate."""
    gate = _k1325_gate(observed_abs_t=6.0, observed_test_days=12, current_total_days=60)
    assert gate.required_test_days == GatePolicy().min_test_days_floor
    assert gate.gate_passed is False


def test_gate_met_only_once_the_window_is_long_enough():
    gate = _k1325_gate(observed_abs_t=4.0, observed_test_days=120, current_total_days=420)
    assert gate.verdict == GateVerdict.GATE_MET
    assert gate.gate_passed is True


def test_wrong_signed_effect_is_never_a_wait():
    gate = _k1325_gate(effect_favours_challenger=False)
    assert gate.verdict == GateVerdict.NEGATIVE_EFFECT
    assert gate.required_test_days is None


def test_requirement_ci_reports_unbounded_when_the_band_crosses_zero():
    """Honesty check: at |t| = 0.88 the requirement itself is not pinned down."""
    ci = _k1325_gate().required_test_days_ci
    assert ci["optimistic_test_days"] == 21
    assert ci["pessimistic_test_days"] is None


def test_registry_carries_no_hardcoded_day_thresholds():
    """Policy must be derivable, not a re-hidden 200/50."""
    registry = load_registry()
    entry = registry["pipelines"][TW50]
    assert registry["policy"]["target_abs_t"] == 3.0
    assert set(entry["split"]) >= {"test_fraction", "warmup_days"}
    assert "n_test_days_required" not in json.dumps(entry)


def test_registered_pipeline_reads_the_checkpoint_artifact():
    """End-to-end: config + archived results -> the same 208/716 decision."""
    gate = evaluate_registered_pipeline(TW50)
    assert gate.observed_test_days == K1325_N_TEST
    assert gate.required_test_days == 208
    assert gate.verdict == GateVerdict.DESIGN_CHANGE_REQUIRED


def test_generated_artifact_matches_a_fresh_evaluation():
    """experiments/k1325/revisit_gate.json is generated, so it must not drift."""
    path = PROJECT_ROOT / "experiments" / "k1325" / "revisit_gate.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    fresh = evaluate_registered_pipeline(TW50).to_dict()
    for field in ("verdict", "required_test_days", "required_total_days", "policy"):
        assert stored[field] == fresh[field], f"{field} drifted from the generator"


def test_pipeline_scripts_no_longer_hardcode_the_old_thresholds():
    """The whole chain must source the gate, not carry private copies."""
    offenders = []
    for rel in (
        "experiments/k1307/k1307.py",
        "experiments/K1322/K1322.py",
        "experiments/k1324/k1324.py",
        "experiments/k1325/k1325.py",
    ):
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        # Strip the module docstring, which documents what was removed.
        code = code.split('"""', 2)[-1]
        for banned in (
            "REVISIT_GATE_TOTAL_DAYS =",
            "REVISIT_GATE_TEST_DAYS =",
            "REVISIT_GATE_DAYS =",
            "POWERED_OOS_TARGET =",
        ):
            if banned in code:
                offenders.append(f"{rel}: {banned}")
    assert not offenders, f"hardcoded revisit thresholds are back: {offenders}"
