"""Fail-closed helpers for bounded, multi-start numerical estimation.

Research estimators must not silently accept an optimizer's last iterate when the
optimizer failed, returned a non-finite objective, or escaped the declared parameter
domain.  This module centralizes that contract so experiments do not each reinvent a
slightly different (and often fail-open) result-selection loop.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import optimize

Bounds = Sequence[tuple[float | None, float | None]]


@dataclass(frozen=True)
class BoundedOptimizationFit:
    """The best optimizer result that passed every declared validity check."""

    params: np.ndarray
    objective: float
    optimizer_success: bool
    iterations: int
    message: str


def _clip_start(start: Sequence[float], bounds: Bounds) -> np.ndarray:
    values = np.asarray(start, dtype=float).copy()
    if values.shape != (len(bounds),):
        raise ValueError(
            f"start has shape {values.shape}; expected ({len(bounds)},)"
        )
    if not np.all(np.isfinite(values)):
        raise ValueError("optimization start contains a non-finite value")
    for index, (lower, upper) in enumerate(bounds):
        if lower is not None:
            values[index] = max(values[index], lower)
        if upper is not None:
            values[index] = min(values[index], upper)
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"invalid bound at index {index}: {lower} > {upper}")
    return values


def _inside_bounds(params: np.ndarray, bounds: Bounds, *, atol: float = 1e-10) -> bool:
    for value, (lower, upper) in zip(params, bounds, strict=True):
        if lower is not None and value < lower - atol:
            return False
        if upper is not None and value > upper + atol:
            return False
    return True


def bounded_multistart_minimize(
    objective: Callable[[np.ndarray], float],
    *,
    starts: Iterable[Sequence[float]],
    bounds: Bounds,
    method: str = "L-BFGS-B",
    options: dict[str, float | int] | None = None,
    invalid_objective: float = 1e9,
) -> BoundedOptimizationFit:
    """Return the best successful, finite, in-bounds optimization result.

    Failed starts are retained only as diagnostics in the eventual exception.  They
    can never become a fitted model merely because their objective happened to be
    numerically smaller than another failed run.
    """

    starts_list = list(starts)
    if not starts_list:
        raise ValueError("at least one optimization start is required")
    if not bounds:
        raise ValueError("bounded optimization requires explicit bounds")

    best: optimize.OptimizeResult | None = None
    failures: list[str] = []
    for start_number, start in enumerate(starts_list, start=1):
        x0 = _clip_start(start, bounds)
        try:
            result = optimize.minimize(
                objective,
                x0,
                method=method,
                bounds=bounds,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001  # silent-ok: each start failure is retained in the aggregated fail-closed RuntimeError
            failures.append(f"start {start_number}: {type(exc).__name__}: {exc}")
            continue

        params = np.asarray(result.x, dtype=float)
        objective_value = float(result.fun)
        valid = (
            bool(result.success)
            and params.shape == (len(bounds),)
            and np.all(np.isfinite(params))
            and np.isfinite(objective_value)
            and objective_value < invalid_objective
            and _inside_bounds(params, bounds)
        )
        if not valid:
            failures.append(
                f"start {start_number}: success={bool(result.success)} "
                f"objective={objective_value!r} message={str(result.message)!r}"
            )
            continue
        if best is None or objective_value < float(best.fun):
            best = result

    if best is None:
        detail = "; ".join(failures) or "no optimizer result returned"
        raise RuntimeError(f"all bounded optimization starts failed: {detail}")

    return BoundedOptimizationFit(
        params=np.asarray(best.x, dtype=float).copy(),
        objective=float(best.fun),
        optimizer_success=True,
        iterations=int(getattr(best, "nit", 0)),
        message=str(best.message),
    )


__all__ = ["BoundedOptimizationFit", "bounded_multistart_minimize"]
