"""Canonical finite-family and exact randomization inference.

The public interface deliberately returns immutable, input-order results.  A
caller may attach domain labels when rendering its own artifact, while the
statistical correction remains centralized and independent of experiment
schemas.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from math import comb
from numbers import Integral, Real
from typing import Literal

import numpy as np

Alternative = Literal["less", "greater"]


@dataclass(frozen=True)
class HolmStepDownResult:
    """Holm-adjusted p-values and decisions in the caller's input order."""

    raw_p_values: tuple[float, ...]
    adjusted_p_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    alpha: float


@dataclass(frozen=True)
class ExactLabelPermutationResult:
    """Exact fixed-count label-permutation result for a difference in means."""

    difference_high_minus_low: float
    high_mean: float
    low_mean: float
    alternative: Alternative
    p_one_sided_exact: float
    p_two_sided_exact: float
    permutations: int
    n_high: int
    n_low: int


def _finite_vector(values: Iterable[float], *, name: str) -> np.ndarray:
    try:
        array = np.asarray(list(values), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric iterable") from exc
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional iterable")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def monte_carlo_p_value(exceedances: int, draws: int) -> float:
    """Return the finite-simulation p-value ``(r + 1) / (B + 1)``.

    The observed statistic is treated as the additional draw.  This prevents a
    finite Monte Carlo experiment from reporting an impossible exact zero.
    """

    if (
        isinstance(exceedances, bool)
        or not isinstance(exceedances, Integral)
        or isinstance(draws, bool)
        or not isinstance(draws, Integral)
    ):
        raise TypeError("exceedances and draws must be integers")
    exceedance_count = int(exceedances)
    draw_count = int(draws)
    if draw_count < 1 or exceedance_count < 0 or exceedance_count > draw_count:
        raise ValueError("require draws >= 1 and 0 <= exceedances <= draws")
    return (exceedance_count + 1.0) / (draw_count + 1.0)


def bootstrap_long_run_scale(
    bootstrap_means: np.ndarray,
    observed_means: np.ndarray,
    *,
    sample_size: int,
) -> np.ndarray:
    """Estimate the long-run scale of ``sqrt(T) * mean(d_t)``.

    ``bootstrap_means`` must contain one stationary-bootstrap mean per draw and
    model.  The returned denominator is the across-draw standard deviation of
    ``sqrt(T) * (mean_b - mean_observed)`` for each model, rather than the raw
    observation-level standard deviation that is invalid under serial dependence.
    """

    bootstrap_array = np.asarray(bootstrap_means, dtype=np.float64)
    observed_array = np.asarray(observed_means, dtype=np.float64)
    if bootstrap_array.ndim != 2 or bootstrap_array.shape[0] < 2:
        raise ValueError("bootstrap_means must be a B-by-model matrix with B >= 2")
    if observed_array.ndim != 1 or observed_array.shape[0] != bootstrap_array.shape[1]:
        raise ValueError("observed_means must match the model dimension")
    if not np.isfinite(bootstrap_array).all() or not np.isfinite(observed_array).all():
        raise ValueError("bootstrap and observed means must be finite")
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, Integral)
        or sample_size < 2
    ):
        raise ValueError("sample_size must be an integer >= 2")

    centered = np.sqrt(float(sample_size)) * (
        bootstrap_array - observed_array[None, :]
    )
    scale = np.std(centered, axis=0, ddof=1)
    if not np.isfinite(scale).all() or np.any(scale <= np.finfo(np.float64).eps):
        raise ValueError("bootstrap long-run scale must be finite and positive")
    return scale


def holm_step_down(
    p_values: Iterable[float],
    *,
    alpha: float = 0.05,
) -> HolmStepDownResult:
    """Apply the Holm (1979) step-down family-wise error correction.

    Adjusted p-values and rejection decisions retain the original input order.
    Ties are deterministic because the stable sort preserves caller order.
    """

    p_array = _finite_vector(p_values, name="p_values")
    if np.any((p_array < 0.0) | (p_array > 1.0)):
        raise ValueError("p_values must lie in the closed interval [0, 1]")
    if isinstance(alpha, bool) or not isinstance(alpha, Real):
        raise TypeError("alpha must be a real number")
    alpha_value = float(alpha)
    if not np.isfinite(alpha_value) or not 0.0 < alpha_value <= 1.0:
        raise ValueError("alpha must lie in the interval (0, 1]")

    order = np.argsort(p_array, kind="stable")
    adjusted = np.empty(p_array.size, dtype=np.float64)
    running_max = 0.0
    family_size = int(p_array.size)
    for rank, original_index in enumerate(order):
        candidate = min(1.0, (family_size - rank) * float(p_array[original_index]))
        running_max = max(running_max, candidate)
        adjusted[original_index] = running_max

    return HolmStepDownResult(
        raw_p_values=tuple(float(value) for value in p_array),
        adjusted_p_values=tuple(float(value) for value in adjusted),
        rejected=tuple(bool(value <= alpha_value) for value in adjusted),
        alpha=alpha_value,
    )


def exact_label_permutation(
    values: Iterable[float],
    high: Iterable[bool],
    *,
    alternative: Alternative,
    max_permutations: int = 1_000_000,
) -> ExactLabelPermutationResult:
    """Exhaustively permute a fixed number of boolean group labels.

    The statistic is ``mean(high) - mean(low)``.  The observed allocation is
    part of the exhaustive reference distribution, so no Monte Carlo ``+1``
    correction is applied.  Enumeration fails closed above ``max_permutations``
    rather than silently turning an exact test into an unbounded computation.
    """

    value_array = _finite_vector(values, name="values")
    try:
        raw_labels = list(high)
    except TypeError as exc:
        raise TypeError("high must be a one-dimensional boolean iterable") from exc
    if len(raw_labels) != value_array.size:
        raise ValueError("values and high must have identical lengths")
    if not raw_labels or any(
        not isinstance(label, (bool, np.bool_)) for label in raw_labels
    ):
        raise ValueError("high must contain boolean labels only")
    if alternative not in {"less", "greater"}:
        raise ValueError("alternative must be 'less' or 'greater'")
    if (
        isinstance(max_permutations, bool)
        or not isinstance(max_permutations, Integral)
        or max_permutations < 1
    ):
        raise ValueError("max_permutations must be a positive integer")

    high_array = np.asarray(raw_labels, dtype=bool)
    n_total = int(value_array.size)
    n_high = int(high_array.sum())
    n_low = n_total - n_high
    if n_high == 0 or n_low == 0:
        raise ValueError("both label groups are required")

    max_permutations_value = int(max_permutations)
    permutation_count = comb(n_total, n_high)
    if permutation_count > max_permutations_value:
        raise ValueError(
            f"exact permutations {permutation_count} exceed max_permutations "
            f"{max_permutations_value}"
        )

    # Center before summation.  The test statistic is translation invariant,
    # but summing a large common level and subtracting it back is not: e.g.
    # values around 1e16 can otherwise change tail membership by cancellation.
    centered = value_array - value_array[0]
    centered_total = float(centered.sum())
    observed_high_sum = float(centered[high_array].sum())
    observed = (
        observed_high_sum / n_high
        - (centered_total - observed_high_sum) / n_low
    )
    high_mean = float(value_array[high_array].mean())
    low_mean = float(value_array[~high_array].mean())

    one_sided_extreme = 0
    two_sided_extreme = 0
    for high_indices in combinations(range(n_total), n_high):
        high_sum = float(centered[list(high_indices)].sum())
        statistic = (
            high_sum / n_high - (centered_total - high_sum) / n_low
        )
        if alternative == "less":
            one_sided_extreme += statistic <= observed
        else:
            one_sided_extreme += statistic >= observed
        two_sided_extreme += abs(statistic) >= abs(observed)

    return ExactLabelPermutationResult(
        difference_high_minus_low=float(observed),
        high_mean=float(high_mean),
        low_mean=float(low_mean),
        alternative=alternative,
        p_one_sided_exact=one_sided_extreme / permutation_count,
        p_two_sided_exact=two_sided_extreme / permutation_count,
        permutations=permutation_count,
        n_high=n_high,
        n_low=n_low,
    )
