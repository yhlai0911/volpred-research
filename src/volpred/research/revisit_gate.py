"""Power-based revisit gates for checkpoint experiments.

WHY THIS MODULE EXISTS
----------------------
K1325 (0050.TW 5-min HAR-RV checkpoint) shipped a public article,
``mile_3445217e``, that admitted the project's own revisit condition was set
too loose and promised readers it would be fixed. The old condition was two
hardcoded integers, duplicated by copy-paste across four experiment scripts::

    REVISIT_GATE_TOTAL_DAYS = 200
    REVISIT_GATE_TEST_DAYS  = 50

Nobody derived those numbers from anything. K1325 observed DM-HLN
``t = 0.883`` at ``n_test = 18``. A DM t-statistic grows roughly like
``sqrt(n_test)`` when the per-observation loss differential is stable, so the
gate's own trigger point of ``n_test = 50`` implies ``t ≈ 1.47`` -- still far
below the project's Harvey ``|t| > 3`` bar. Firing that gate would have bought
one more run and one more identical "not enough data to conclude" verdict.

A gate whose trigger point cannot separate the hypotheses is not a gate. It is
a scheduled way to spend a slot.

WHAT REPLACES IT
----------------
The required test window is *derived* from the effect size actually observed,
against the significance bar the project actually enforces::

    n_required = n_observed * (t_target / |t_observed|) ** 2

and then screened against a wait horizon. Waiting is only a legitimate answer
when the data can plausibly arrive; past that, the honest verdict is that the
comparison is not resolvable by waiting and the *design* has to change (pool
across assets, buy deeper history, move to a frequency where the effect is
bigger). See ``GateVerdict``.

ASSUMPTIONS, STATED BECAUSE THEY ARE LOAD-BEARING
-------------------------------------------------
1. ``t ∝ sqrt(n)``: the mean loss differential and its long-run variance stay
   at their currently observed values as the sample grows. This is an
   extrapolation, not a formal power calculation, and it is only as good as
   the current estimate of the effect.
2. That current estimate is itself noisy. A t-statistic has a standard error of
   roughly 1, so at ``t = 0.883`` the requirement is uncertain by an order of
   magnitude -- ``required_test_days_ci`` reports that band explicitly rather
   than hiding it behind the point estimate. The gate *decision* uses the point
   estimate; the band is what stops anyone reading the number as a promise.
3. The observed effect keeps its sign. A challenger that is currently *worse*
   than the baseline does not become better by collecting more days, so a
   wrong-signed effect returns ``NEGATIVE_EFFECT`` instead of a wait.

Policy inputs (target t, floor, horizon, per-pipeline split convention) live in
``config/revisit_gates.json``. This module owns the arithmetic; the config owns
the numbers; experiment scripts own neither.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "GateVerdict",
    "GatePolicy",
    "PipelineSplit",
    "required_test_days",
    "implied_total_days",
    "evaluate_gate",
    "load_registry",
    "gate_for_pipeline",
    "evaluate_registered_pipeline",
]

CONFIG_RELPATH = "config/revisit_gates.json"

#: Standard error of a t-statistic, used only for ``required_test_days_ci``.
#: A studentised statistic has se ≈ 1 in large samples; at n_test = 18 this is
#: itself approximate, which is the point being communicated.
T_STAT_SE = 1.0

_CI_Z = 1.96


class GateVerdict:
    """Verdicts a revisit gate can return. Strings, so they survive JSON."""

    #: Enough test days are already in hand -- run the comparison for real.
    GATE_MET = "GATE_MET"
    #: Not there yet, but the shortfall is reachable inside the wait horizon.
    WAIT_FOR_DATA = "WAIT_FOR_DATA"
    #: Reachable only past the wait horizon. Waiting is no longer a plan.
    DESIGN_CHANGE_REQUIRED = "DESIGN_CHANGE_REQUIRED"
    #: The challenger is currently losing. More of the same data will not fix it.
    NEGATIVE_EFFECT = "NEGATIVE_EFFECT"


@dataclass(frozen=True)
class GatePolicy:
    """Thresholds shared by every pipeline. Loaded from the registry config."""

    #: The |t| the project requires before a verdict is publishable (Harvey bar).
    target_abs_t: float = 3.0
    #: Never declare a gate met below this many test days, whatever the
    #: extrapolation says: below ~60 the HAC/Harvey small-sample corrections in
    #: ``dm_hln`` are themselves unreliable, so a large |t| there is not
    #: trustworthy evidence -- it is a reason to distrust the statistic.
    min_test_days_floor: int = 60
    #: Past this many additional trading days, a "revisit later" plan is not
    #: credible: ~2 years of 0050.TW / market microstructure drift breaks the
    #: stationary-effect assumption the extrapolation rests on.
    max_wait_trading_days: int = 504
    #: Trading days per calendar year, for the ETA readout only.
    trading_days_per_year: int = 252

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "GatePolicy":
        raw = raw or {}
        defaults = cls()
        return cls(
            target_abs_t=float(raw.get("target_abs_t", defaults.target_abs_t)),
            min_test_days_floor=int(
                raw.get("min_test_days_floor", defaults.min_test_days_floor)
            ),
            max_wait_trading_days=int(
                raw.get("max_wait_trading_days", defaults.max_wait_trading_days)
            ),
            trading_days_per_year=int(
                raw.get("trading_days_per_year", defaults.trading_days_per_year)
            ),
        )


@dataclass(frozen=True)
class PipelineSplit:
    """How a pipeline turns raw days into test days.

    ``test_fraction`` is the share of post-warm-up rows held out, and
    ``warmup_days`` is what the feature construction eats before the first
    usable row (22 for HAR's monthly lag).
    """

    test_fraction: float
    warmup_days: int

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "PipelineSplit":
        return cls(
            test_fraction=float(raw["test_fraction"]),
            warmup_days=int(raw["warmup_days"]),
        )


def required_test_days(
    observed_abs_t: float,
    observed_test_days: int,
    target_abs_t: float,
) -> Optional[int]:
    """Test days needed for ``|t|`` to reach ``target_abs_t``.

    Returns ``None`` when the observed statistic is zero (or effectively so),
    i.e. when no finite amount of the same data would get there.
    """
    if observed_test_days <= 0:
        raise ValueError("observed_test_days must be positive")
    if target_abs_t <= 0:
        raise ValueError("target_abs_t must be positive")
    observed_abs_t = abs(float(observed_abs_t))
    if observed_abs_t <= 1e-9:
        return None
    return int(math.ceil(observed_test_days * (target_abs_t / observed_abs_t) ** 2))


def implied_total_days(test_days: int, split: PipelineSplit) -> int:
    """Raw days a pipeline must collect to yield ``test_days`` held-out days."""
    if not 0.0 < split.test_fraction <= 1.0:
        raise ValueError("test_fraction must be in (0, 1]")
    return int(math.ceil(test_days / split.test_fraction)) + split.warmup_days


def _ci_bounds(
    observed_abs_t: float,
    observed_test_days: int,
    target_abs_t: float,
) -> Dict[str, Optional[int]]:
    """Requirement implied by the ±1.96 se band around the observed t.

    The optimistic end is a real number; the pessimistic end is ``None``
    whenever the band crosses zero, which is the honest way to say "this
    sample cannot bound how long the wait would be".
    """
    hi_t = abs(observed_abs_t) + _CI_Z * T_STAT_SE  # optimistic: fewer days needed
    lo_t = abs(observed_abs_t) - _CI_Z * T_STAT_SE  # pessimistic: more days needed
    return {
        "optimistic_test_days": required_test_days(hi_t, observed_test_days, target_abs_t),
        "pessimistic_test_days": (
            required_test_days(lo_t, observed_test_days, target_abs_t)
            if lo_t > 1e-9
            else None
        ),
    }


@dataclass
class GateEvaluation:
    """Result of one gate evaluation. ``to_dict`` is what goes into artifacts."""

    pipeline: str
    verdict: str
    gate_passed: bool
    observed_abs_t: float
    observed_test_days: int
    current_total_days: Optional[int]
    target_abs_t: float
    required_test_days: Optional[int]
    required_total_days: Optional[int]
    required_test_days_ci: Dict[str, Optional[int]]
    additional_trading_days_needed: Optional[int]
    eta_years: Optional[float]
    policy: Dict[str, Any]
    split: Dict[str, Any]
    rationale: str
    assumptions: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_gate(
    *,
    pipeline: str,
    observed_abs_t: float,
    observed_test_days: int,
    split: PipelineSplit,
    policy: Optional[GatePolicy] = None,
    current_total_days: Optional[int] = None,
    effect_favours_challenger: bool = True,
) -> GateEvaluation:
    """Decide whether a checkpoint pipeline should be re-run, and when.

    ``observed_abs_t`` / ``observed_test_days`` come from the most recent
    checkpoint's own results file -- never from a hand-written note.
    ``effect_favours_challenger`` is False when the model under test is the one
    losing, in which case waiting is not a plan.
    """
    policy = policy or GatePolicy()
    assumptions = [
        "t grows as sqrt(n_test): mean loss differential and its long-run "
        "variance are assumed to stay at their currently observed values.",
        "This is an extrapolation from a small sample, not a formal power "
        "calculation; required_test_days_ci shows how wide the band is.",
        f"Target bar is the project's Harvey |t| > {policy.target_abs_t:g}.",
        f"Floor of {policy.min_test_days_floor} test days applies regardless of "
        "the extrapolation, because DM-HLN small-sample corrections are not "
        "trustworthy below it.",
    ]

    if not effect_favours_challenger:
        return GateEvaluation(
            pipeline=pipeline,
            verdict=GateVerdict.NEGATIVE_EFFECT,
            gate_passed=False,
            observed_abs_t=abs(float(observed_abs_t)),
            observed_test_days=int(observed_test_days),
            current_total_days=current_total_days,
            target_abs_t=policy.target_abs_t,
            required_test_days=None,
            required_total_days=None,
            required_test_days_ci={
                "optimistic_test_days": None,
                "pessimistic_test_days": None,
            },
            additional_trading_days_needed=None,
            eta_years=None,
            policy=asdict(policy),
            split=asdict(split),
            rationale=(
                "The observed loss differential favours the baseline, not the "
                "challenger. Collecting more of the same data cannot reverse "
                "the sign; revisit only after a design change."
            ),
            assumptions=assumptions,
        )

    raw_required = required_test_days(
        observed_abs_t, observed_test_days, policy.target_abs_t
    )
    required = (
        max(raw_required, policy.min_test_days_floor)
        if raw_required is not None
        else None
    )
    required_total = implied_total_days(required, split) if required is not None else None
    ci = _ci_bounds(observed_abs_t, observed_test_days, policy.target_abs_t)

    additional = None
    eta_years = None
    if required_total is not None and current_total_days is not None:
        additional = max(required_total - int(current_total_days), 0)
        eta_years = round(additional / policy.trading_days_per_year, 2)

    if required is not None and observed_test_days >= required:
        verdict = GateVerdict.GATE_MET
        rationale = (
            f"{observed_test_days} test days already meet the {required}-day "
            f"requirement implied by |t|={abs(observed_abs_t):.3f}; run the "
            "comparison for real rather than as a checkpoint."
        )
    elif required is None:
        verdict = GateVerdict.DESIGN_CHANGE_REQUIRED
        rationale = (
            "The observed loss differential is indistinguishable from zero, so "
            "no finite test window reaches the target. Change the design."
        )
    elif additional is not None and additional > policy.max_wait_trading_days:
        verdict = GateVerdict.DESIGN_CHANGE_REQUIRED
        rationale = (
            f"Reaching |t|={policy.target_abs_t:g} needs {required} test days "
            f"(~{required_total} raw trading days). That is {additional} more "
            f"trading days ≈ {eta_years} years beyond the current "
            f"{current_total_days}, past the {policy.max_wait_trading_days}-day "
            "wait horizon. Do not schedule a re-run; change the design "
            "(pool across assets, deeper history, or a frequency where the "
            "effect is larger)."
        )
    else:
        verdict = GateVerdict.WAIT_FOR_DATA
        rationale = (
            f"Re-run at {required} test days (~{required_total} raw trading "
            f"days), not before. Earlier triggers cannot separate the "
            "hypotheses and only reproduce the same inconclusive verdict."
        )

    return GateEvaluation(
        pipeline=pipeline,
        verdict=verdict,
        gate_passed=verdict == GateVerdict.GATE_MET,
        observed_abs_t=abs(float(observed_abs_t)),
        observed_test_days=int(observed_test_days),
        current_total_days=current_total_days,
        target_abs_t=policy.target_abs_t,
        required_test_days=required,
        required_total_days=required_total,
        required_test_days_ci=ci,
        additional_trading_days_needed=additional,
        eta_years=eta_years,
        policy=asdict(policy),
        split=asdict(split),
        rationale=rationale,
        assumptions=assumptions,
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_registry(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load ``config/revisit_gates.json`` -- the policy source of truth."""
    path = Path(config_path) if config_path else _project_root() / CONFIG_RELPATH
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def gate_for_pipeline(
    pipeline: str,
    *,
    observed_abs_t: float,
    observed_test_days: int,
    current_total_days: Optional[int] = None,
    effect_favours_challenger: bool = True,
    config_path: Optional[Path] = None,
) -> GateEvaluation:
    """Evaluate the gate for a registered pipeline.

    This is the entry point experiment scripts call, so a script never carries
    its own copy of the thresholds.
    """
    registry = load_registry(config_path)
    pipelines = registry.get("pipelines", {})
    if pipeline not in pipelines:
        raise KeyError(
            f"pipeline {pipeline!r} is not registered in {CONFIG_RELPATH}; "
            f"known: {sorted(pipelines)}"
        )
    entry = pipelines[pipeline]
    policy = GatePolicy.from_dict(
        {**registry.get("policy", {}), **entry.get("policy_overrides", {})}
    )
    split = PipelineSplit.from_dict(entry["split"])
    return evaluate_gate(
        pipeline=pipeline,
        observed_abs_t=observed_abs_t,
        observed_test_days=observed_test_days,
        split=split,
        policy=policy,
        current_total_days=current_total_days,
        effect_favours_challenger=effect_favours_challenger,
    )


def _dig(payload: Dict[str, Any], dotted: str) -> Any:
    node: Any = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"field {dotted!r} not found in results file")
        node = node[part]
    return node


def read_latest_checkpoint(
    pipeline: str, *, config_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Pull the observed statistic straight out of the latest checkpoint's file.

    Reading it programmatically is the point: a gate must never be argued from
    a number somebody retyped into a docstring.
    """
    registry = load_registry(config_path)
    entry = registry["pipelines"][pipeline]
    spec = entry["latest_checkpoint"]
    results_path = _project_root() / spec["results_path"]
    with open(results_path, "r", encoding="utf-8") as fh:
        results = json.load(fh)
    return {
        "experiment_id": spec["experiment_id"],
        "results_path": spec["results_path"],
        "observed_t": float(_dig(results, spec["observed_abs_t_field"])),
        "observed_test_days": int(_dig(results, spec["observed_test_days_field"])),
        "current_total_days": int(_dig(results, spec["current_total_days_field"])),
    }


def evaluate_registered_pipeline(
    pipeline: str,
    *,
    current_total_days: Optional[int] = None,
    config_path: Optional[Path] = None,
) -> GateEvaluation:
    """Gate decision for a pipeline, sourced entirely from config + artifacts.

    Upstream checkpoints in a chain (which have no DM statistic of their own,
    e.g. a readiness diagnostic) call this to learn the pipeline-level data
    requirement instead of carrying a second, inconsistent hardcoded number.
    """
    checkpoint = read_latest_checkpoint(pipeline, config_path=config_path)
    return gate_for_pipeline(
        pipeline,
        observed_abs_t=checkpoint["observed_t"],
        observed_test_days=checkpoint["observed_test_days"],
        current_total_days=(
            current_total_days
            if current_total_days is not None
            else checkpoint["current_total_days"]
        ),
        # A positive DM-HLN t in this chain means the challenger has the lower
        # loss, i.e. the effect points the way the hypothesis is stated.
        effect_favours_challenger=checkpoint["observed_t"] > 0,
        config_path=config_path,
    )
