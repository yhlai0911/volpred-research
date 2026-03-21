"""Base class for custom MLE volatility models.

Subclasses only need to implement four methods:

* ``_initial_params()``  -- starting point for the optimiser
* ``_bounds()``          -- box constraints
* ``_conditional_variance(params, returns)`` -- the sigma2_t recursion
* ``_param_names()``     -- human-readable names for each parameter
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

from volpred.core.interfaces import BaseVolatilityModel
from volpred.core.types import (
    DataRequirement,
    ForecastResult,
    ModelState,
)


class CustomVolModel(BaseVolatilityModel):
    """Base for custom log-likelihood + scipy MLE models.

    Subclasses implement:
        - ``_initial_params() -> np.ndarray``
        - ``_bounds() -> list[tuple[float, float]]``
        - ``_conditional_variance(params, returns) -> np.ndarray`` of sigma2_t
        - ``_param_names() -> list[str]``
    """

    def __init__(self, dist: str = "normal", **kwargs):
        self._dist = dist
        self._params: np.ndarray | None = None
        self._returns: np.ndarray | None = None
        self._fit_result = None
        self._config: dict = kwargs

    # ------------------------------------------------------------------
    # BaseVolatilityModel interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return self.__class__.__name__

    def get_data_requirement(self) -> DataRequirement:
        return DataRequirement(fields=["returns"])

    def fit(self, data) -> dict:
        """Fit model via MLE using ``scipy.optimize.minimize``."""
        if isinstance(data, np.ndarray):
            returns = data
        elif "returns" in data.columns:
            returns = data["returns"].values
        else:
            returns = data.iloc[:, 0].values

        self._returns = returns

        # Multi-start optimization: try initial params + perturbed versions
        init = self._initial_params()
        bounds = self._bounds()
        neg_ll = lambda p: -self._log_likelihood(p, returns)

        best_result = None
        starts = [init]
        # Add perturbed starting points
        rng = np.random.RandomState(42)
        for _ in range(3):
            perturbed = init * (1 + 0.3 * rng.randn(len(init)))
            # Clip to bounds
            for j, (lo, hi) in enumerate(bounds):
                perturbed[j] = np.clip(perturbed[j], lo * 1.01, hi * 0.99)
            starts.append(perturbed)

        for x0 in starts:
            try:
                result = minimize(
                    fun=neg_ll, x0=x0, method="L-BFGS-B",
                    bounds=bounds,
                    options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
                )
                if best_result is None or result.fun < best_result.fun:
                    best_result = result
            except Exception:
                continue

        if best_result is None:
            # All starts failed; fallback to simple minimize
            best_result = minimize(
                fun=neg_ll, x0=init, method="L-BFGS-B",
                bounds=bounds, options={"maxiter": 1000},
            )

        self._params = best_result.x
        self._fit_result = best_result

        return {
            "converged": bool(best_result.success),
            "loglik": -best_result.fun,
            "params": dict(zip(self._param_names(), best_result.x)),
            "n_iter": int(best_result.nit),
        }

    def forecast(self, steps: int = 1) -> ForecastResult:
        """One-step-ahead forecast from the last fitted conditional variance."""
        if self._params is None or self._returns is None:
            raise RuntimeError("Model has not been fitted yet.")

        sigma2 = self._conditional_variance(self._params, self._returns)
        last_sigma2 = float(sigma2[-1])

        return ForecastResult(
            date=datetime.now(),
            point_forecast=last_sigma2 ** 0.5,
            variance_forecast=last_sigma2,
            distribution_params={"dist": self._dist},
            model_name=self.get_name(),
            fit_info={"converged": self._fit_result.success}
            if self._fit_result
            else {},
        )

    def get_state(self) -> ModelState:
        return ModelState(
            model_name=self.get_name(),
            params={
                "fitted": dict(zip(self._param_names(), self._params.tolist()))
                if self._params is not None
                else {}
            },
            config={"dist": self._dist, **self._config},
            timestamp=datetime.now(),
        )

    def load_state(self, state: ModelState) -> None:
        if state.params.get("fitted"):
            self._params = np.array(
                [state.params["fitted"][n] for n in self._param_names()]
            )
        self._dist = state.config.get("dist", self._dist)

    # ------------------------------------------------------------------
    # Default log-likelihood
    # ------------------------------------------------------------------

    def _log_likelihood(self, params: np.ndarray, returns: np.ndarray) -> float:
        """Gaussian or Student-t log-likelihood using conditional variance."""
        sigma2 = self._conditional_variance(params, returns)
        sigma2 = np.maximum(sigma2, 1e-12)  # numerical safety

        if self._dist == "normal":
            ll = -0.5 * (
                np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2
            )

        elif self._dist == "studentt":
            nu = params[-1]  # last parameter is degrees of freedom
            ll = (
                gammaln((nu + 1) / 2)
                - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2))
                - 0.5 * np.log(sigma2)
                - (nu + 1) / 2 * np.log(1 + returns**2 / (sigma2 * (nu - 2)))
            )

        else:
            raise ValueError(f"Unknown distribution: {self._dist}")

        return float(np.sum(ll))

    # ------------------------------------------------------------------
    # Abstract methods for subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def _initial_params(self) -> np.ndarray:
        """Return a 1-D array of starting parameter values."""
        ...

    @abstractmethod
    def _bounds(self) -> list[tuple[float, float]]:
        """Return per-parameter (lower, upper) bounds for the optimiser."""
        ...

    @abstractmethod
    def _conditional_variance(
        self, params: np.ndarray, returns: np.ndarray
    ) -> np.ndarray:
        """Compute the conditional variance series sigma2_t."""
        ...

    @abstractmethod
    def _param_names(self) -> list[str]:
        """Return human-readable names matching the parameter vector."""
        ...
