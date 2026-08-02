"""Contract tests for canonical multiple-testing and permutation inference."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from volpred.stats.inference import (
    bootstrap_long_run_scale,
    exact_label_permutation,
    holm_step_down,
    monte_carlo_p_value,
)

ROOT = Path(__file__).resolve().parents[1]


def test_monte_carlo_p_value_uses_plus_one_correction() -> None:
    assert monte_carlo_p_value(0, 499) == pytest.approx(1.0 / 500.0)
    assert monte_carlo_p_value(499, 499) == 1.0


@pytest.mark.parametrize(("exceedances", "draws"), [(-1, 499), (500, 499), (0, 0)])
def test_monte_carlo_p_value_rejects_invalid_counts(
    exceedances: int, draws: int
) -> None:
    with pytest.raises(ValueError):
        monte_carlo_p_value(exceedances, draws)


def test_bootstrap_long_run_scale_uses_sampling_distribution_of_mean() -> None:
    bootstrap_means = np.array(
        [
            [1.0, 2.0],
            [1.2, 1.8],
            [0.8, 2.2],
        ]
    )
    observed_means = np.array([1.0, 2.0])

    scale = bootstrap_long_run_scale(
        bootstrap_means,
        observed_means,
        sample_size=25,
    )

    np.testing.assert_allclose(
        scale,
        np.std(5.0 * (bootstrap_means - observed_means), axis=0, ddof=1),
    )


def test_holm_step_down_matches_branch_self_check() -> None:
    result = holm_step_down([0.01, 0.04, 0.03], alpha=0.05)

    assert result.adjusted_p_values == (0.03, 0.06, 0.06)
    assert result.rejected == (True, False, False)
    assert holm_step_down([0.01, 0.04]).adjusted_p_values == (0.02, 0.04)


def test_holm_step_down_reproduces_k1380_committed_numbers() -> None:
    payload = json.loads(
        (
            ROOT
            / "experiments/K1380_v4/k1380_v4_rc_correction_results.json"
        ).read_text(encoding="utf-8")
    )
    expected = payload["holm_step_down"]["per_spec"]
    labels = list(expected)
    raw_p_values = [expected[label]["raw_p"] for label in labels]

    result = holm_step_down(raw_p_values, alpha=payload["holm_step_down"]["alpha"])

    np.testing.assert_allclose(
        result.adjusted_p_values,
        [expected[label]["holm_adj_p"] for label in labels],
        rtol=0.0,
        atol=1e-15,
    )
    assert result.rejected == tuple(
        expected[label]["reject_at_0.10"] for label in labels
    )


@pytest.mark.parametrize(
    "p_values",
    [[], [-0.01], [1.01], [float("nan")], [[0.1, 0.2]]],
)
def test_holm_step_down_rejects_invalid_families(p_values: object) -> None:
    with pytest.raises(ValueError):
        holm_step_down(p_values)  # type: ignore[arg-type]


@pytest.mark.parametrize("alpha", [0.0, 1.01, float("nan")])
def test_holm_step_down_rejects_invalid_alpha_value(alpha: object) -> None:
    with pytest.raises(ValueError):
        holm_step_down([0.05], alpha=alpha)  # type: ignore[arg-type]


@pytest.mark.parametrize("alpha", [True, "0.05"])
def test_holm_step_down_rejects_invalid_alpha_type(alpha: object) -> None:
    with pytest.raises(TypeError):
        holm_step_down([0.05], alpha=alpha)  # type: ignore[arg-type]


def test_exact_label_permutation_matches_branch_self_check() -> None:
    result = exact_label_permutation(
        [1.0, 2.0, 3.0, 4.0],
        [False, False, True, True],
        alternative="greater",
    )

    assert result.difference_high_minus_low == 2.0
    assert result.permutations == 6
    assert result.p_one_sided_exact == pytest.approx(1.0 / 6.0)
    assert result.p_two_sided_exact == pytest.approx(2.0 / 6.0)
    assert result.high_mean == 3.5
    assert result.low_mean == 1.5


def test_exact_label_permutation_supports_less_alternative() -> None:
    result = exact_label_permutation(
        [3.0, 4.0, 1.0, 2.0],
        [False, False, True, True],
        alternative="less",
    )

    assert result.difference_high_minus_low == -2.0
    assert result.p_one_sided_exact == pytest.approx(1.0 / 6.0)
    assert result.p_two_sided_exact == pytest.approx(2.0 / 6.0)


def test_exact_label_permutation_does_not_swallow_tiny_effects_as_ties() -> None:
    base = exact_label_permutation(
        [0.0, 1.0, 2.0, 3.0],
        [False, False, True, True],
        alternative="greater",
    )
    tiny = exact_label_permutation(
        [0.0, 1e-13, 2e-13, 3e-13],
        [False, False, True, True],
        alternative="greater",
    )

    assert tiny.p_one_sided_exact == base.p_one_sided_exact == pytest.approx(1 / 6)
    assert tiny.p_two_sided_exact == base.p_two_sided_exact == pytest.approx(2 / 6)


def test_exact_label_permutation_is_translation_invariant() -> None:
    base = exact_label_permutation(
        [0.0, 2.0, 4.0, 6.0],
        [False, False, True, True],
        alternative="greater",
    )
    shifted = exact_label_permutation(
        [1e16, 1e16 + 2.0, 1e16 + 4.0, 1e16 + 6.0],
        [False, False, True, True],
        alternative="greater",
    )

    assert shifted.difference_high_minus_low == base.difference_high_minus_low
    assert shifted.p_one_sided_exact == base.p_one_sided_exact
    assert shifted.p_two_sided_exact == base.p_two_sided_exact


@pytest.mark.parametrize(
    ("values", "labels", "alternative"),
    [
        ([1.0], [True], "greater"),
        ([1.0, 2.0], [True], "greater"),
        ([1.0, float("nan")], [True, False], "greater"),
        ([1.0, 2.0], [True, True], "greater"),
        ([1.0, 2.0], [0, 1], "greater"),
        ([1.0, 2.0], [True, False], "two-sided"),
    ],
)
def test_exact_label_permutation_rejects_invalid_inputs(
    values: object,
    labels: object,
    alternative: str,
) -> None:
    with pytest.raises(ValueError):
        exact_label_permutation(
            values,  # type: ignore[arg-type]
            labels,  # type: ignore[arg-type]
            alternative=alternative,  # type: ignore[arg-type]
        )


def test_exact_label_permutation_rejects_non_iterable_labels() -> None:
    with pytest.raises(TypeError):
        exact_label_permutation(
            [1.0, 2.0],
            None,  # type: ignore[arg-type]
            alternative="greater",
        )


def test_exact_label_permutation_refuses_unbounded_enumeration() -> None:
    with pytest.raises(ValueError, match="exceed max_permutations"):
        exact_label_permutation(
            range(10),
            [True] * 5 + [False] * 5,
            alternative="greater",
            max_permutations=100,
        )
