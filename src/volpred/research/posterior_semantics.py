"""Machine-readable posterior support diagnostics for BMA experiments."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def summarize_posterior_support(
    *,
    model_names: Sequence[str],
    invalid_forecasts: np.ndarray,
    posterior_excluded: np.ndarray,
    final_weights: Sequence[float],
    revival_policy: str,
) -> dict[str, object]:
    """Summarize why each model is present or absent from the final posterior.

    ``invalid_forecasts`` and ``posterior_excluded`` must cover the same
    evaluation days.  A drop event is the first day of a consecutive invalid
    forecast spell; posterior-excluded days count the support actually used by
    the forecast, so an absorbing policy can remain excluded after forecasts
    become valid again.
    """

    names = tuple(model_names)
    invalid = np.asarray(invalid_forecasts, dtype=bool)
    excluded = np.asarray(posterior_excluded, dtype=bool)
    weights = np.asarray(final_weights, dtype=float)

    if invalid.ndim != 2 or invalid.shape[1] != len(names):
        raise ValueError(
            "invalid_forecasts must have shape (n_days, n_models)"
        )
    if excluded.shape != invalid.shape:
        raise ValueError(
            "posterior_excluded must match invalid_forecasts shape"
        )
    if weights.shape != (len(names),):
        raise ValueError("final_weights must have one value per model")
    if revival_policy not in {"absorbing", "floor_revival"}:
        raise ValueError(f"unknown revival_policy: {revival_policy}")

    if invalid.shape[0]:
        spell_starts = invalid.copy()
        spell_starts[1:] &= ~invalid[:-1]
    else:
        spell_starts = invalid.copy()

    diagnostics: dict[str, dict[str, int]] = {}
    ever_invalid: list[str] = []
    absorbing_dropped: list[str] = []
    final_status: dict[str, str] = {}

    for index, model in enumerate(names):
        invalid_days = int(invalid[:, index].sum())
        diagnostics[model] = {
            "invalid_forecast_days": invalid_days,
            "drop_events": int(spell_starts[:, index].sum()),
            "posterior_excluded_days": int(excluded[:, index].sum()),
        }
        if invalid_days:
            ever_invalid.append(model)
            if revival_policy == "absorbing":
                absorbing_dropped.append(model)

        weight = weights[index]
        if not np.isfinite(weight) or weight < 0:
            status = "invalid_final_weight"
        elif revival_policy == "absorbing" and invalid_days:
            status = "absorbing_dropped"
        elif revival_policy == "floor_revival" and invalid_days:
            status = (
                "revived_after_floor"
                if weight > 0
                else "excluded_at_final_forecast_revivable"
            )
        elif weight > 0:
            status = "active_positive"
        else:
            status = "numerically_zero_without_invalid_forecast"
        final_status[model] = status

    return {
        "support_diagnostics": diagnostics,
        "ever_invalid_models": ever_invalid,
        "absorbing_dropped_models": absorbing_dropped,
        "final_weight_status": final_status,
    }


__all__ = ["summarize_posterior_support"]
